#!/usr/bin/env python3
"""find-skills helper: scan local skills, search remote ones, vet them, install them.

Standard library only. Network access goes to three hosts:
  skills.sh (search API), api.github.com (repo metadata, trees), raw.githubusercontent.com (files).

A GitHub token is optional. It comes from GITHUB_TOKEN / GH_TOKEN or `gh auth token`,
is sent only to api.github.com, and is never printed.

Subcommands:
  local     [QUERY]                     list or match installed skills
  baseline  [--kinds ui,code,writing]   check that the anti-slop baseline is installed
  catalog   [DOMAIN|QUERY]              show curated, pre-checked sources
  search    QUERY                       search skills.sh (+ GitHub) and rank by quality
  list      OWNER/REPO                  list every skill inside a repository
  vet       OWNER/REPO SKILL            download to staging, run the static scan, score it
  install   OWNER/REPO SKILL            vet again at a pinned commit, copy into a skills dir, mark active
  use       NAME...                     mark already-installed skills as active for this project
  unuse     NAME...                     drop skills from the active list (they stay installed)
  active                                show the active skills the agent must apply

Active skills are written to .kiro/steering/find-skills-active.md (inclusion: always), so every
later session is told to read and apply them.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG_DIR = HERE.parent / "references" / "catalog"
STAGING_ROOT = Path(tempfile.gettempdir()) / "find-skills-staging"
LOCK_NAME = ".find-skills-lock.json"
UA = "find-skills/1.0 (+agent skill finder)"

MAX_FILES = 3000
MAX_FILE_BYTES = 5_000_000
MAX_TOTAL_BYTES = 60_000_000
MAX_TARBALL_BYTES = 400_000_000
RAW_FETCH_LIMIT = 40  # above this many files, download one tarball instead of N raw files
FINDINGS_PRINT_LIMIT = 40
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# --------------------------------------------------------------------------- utils

def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


_CATALOG: dict | None = None


def load_catalog() -> dict:
    """Merge references/catalog/*.json. core.json holds shared data; every other file is a profile.

    Only the profiles chosen at install time are present on disk. Draft profiles load only
    when FIND_SKILLS_DRAFTS=1.
    """
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    cat = {"trusted_owners": [], "clone_watch": {}, "anti_slop_baseline": {}, "domains": {},
           "profiles": {}, "baseline_kinds": []}
    drafts_ok = os.environ.get("FIND_SKILLS_DRAFTS") == "1"
    files = sorted(CATALOG_DIR.glob("*.json"), key=lambda p: (p.stem != "core", p.stem))
    if not files:
        print(f"warning: no catalog files in {CATALOG_DIR}", file=sys.stderr)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: skipping {path.name} ({exc})", file=sys.stderr)
            continue
        name = data.get("profile", path.stem)
        if data.get("status") == "draft" and not drafts_ok:
            continue
        cat["trusted_owners"] += data.get("trusted_owners", [])
        cat["clone_watch"].update(data.get("clone_watch", {}))
        cat["anti_slop_baseline"].update(data.get("anti_slop_baseline", {}))
        for key, dom in data.get("domains", {}).items():
            cat["domains"][key] = {**dom, "profile": name}
        if name != "core":
            cat["profiles"][name] = {"title": data.get("title", name), "status": data.get("status", "stable"),
                                     "domains": list(data.get("domains", {})),
                                     "baseline_kinds": data.get("baseline_kinds", [])}
            for k in data.get("baseline_kinds", []):
                if k not in cat["baseline_kinds"]:
                    cat["baseline_kinds"].append(k)
    CLONE_WATCH.update({k.lower(): v for k, v in cat["clone_watch"].items()})
    _CATALOG = cat
    return cat


CLONE_WATCH: dict[str, str] = {}


def days_since(iso: str) -> int:
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - then).days


STOPWORDS = {
    "a", "an", "and", "the", "for", "to", "of", "in", "on", "with", "use", "when", "or",
    "is", "are", "be", "this", "that", "it", "as", "by", "at", "from", "your", "you",
    "skill", "skills", "agent", "agents", "untuk", "dan", "yang", "di", "ke", "buat", "bikin",
}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in STOPWORDS]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Small YAML-frontmatter reader: top-level scalars, quoted values, | and > blocks."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    block, fm, j = lines[1:end], {}, 0
    while j < len(block):
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", block[j])
        if not m:
            j += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        j += 1
        if val in ("|", ">", "|-", ">-", "|+", ">+"):
            buf = []
            while j < len(block) and (block[j][:1] in (" ", "\t") or not block[j].strip()):
                buf.append(block[j].strip())
                j += 1
            fm[key] = ("\n" if val.startswith("|") else " ").join(buf).strip()
            continue
        if val:
            # plain scalar continued on indented lines
            while j < len(block) and block[j][:1] in (" ", "\t") and block[j].strip() \
                    and not re.match(r"^\s+[A-Za-z0-9_-]+:\s", block[j]):
                val += " " + block[j].strip()
                j += 1
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
        fm[key] = val
    return fm, "\n".join(lines[end + 1:])


# --------------------------------------------------------------------------- http

_TOKEN: str | None = None


def github_token() -> str | None:
    global _TOKEN
    if _TOKEN is None:
        tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if not tok and shutil.which("gh"):
            try:
                tok = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                     text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                tok = ""
        _TOKEN = tok
    return _TOKEN or None


def http_get(url: str, headers: dict | None = None, timeout: int = 25, raw: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data if raw else json.loads(data)


def gh_api(path: str):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        return http_get("https://api.github.com" + path, headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and not tok:
            raise RuntimeError("GitHub rate limit hit. Set GITHUB_TOKEN or run `gh auth login`.") from exc
        raise


def raw_file(full: str, sha: str, path: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{full}/{sha}/{urllib.parse.quote(path)}"
    return http_get(url, raw=True)


class _CappedReader:
    """File wrapper that aborts once more than `cap` bytes have been read."""

    def __init__(self, fh, cap: int):
        self.fh, self.cap, self.n = fh, cap, 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.fh.read(size)
        self.n += len(chunk)
        if self.n > self.cap:
            raise RuntimeError(f"repository tarball exceeds {self.cap // 1_000_000} MB; vet aborted")
        return chunk


def tarball_members(full: str, sha: str, paths: set[str]):
    """Stream the repo tarball at `sha` and yield (repo_path, bytes) for regular files in `paths`.

    Symlinks, devices and anything outside `paths` are never written anywhere.
    """
    req = urllib.request.Request(f"https://codeload.github.com/{full}/tar.gz/{sha}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with tarfile.open(fileobj=_CappedReader(resp, MAX_TARBALL_BYTES), mode="r|gz") as tar:
            for m in tar:
                if not m.isfile():
                    continue
                parts = m.name.split("/", 1)
                if len(parts) != 2 or parts[1] not in paths:
                    continue
                fh = tar.extractfile(m)
                if fh is not None:
                    yield parts[1], fh.read()


_META: dict[str, dict] = {}


def repo_meta(full: str) -> dict:
    key = full.lower()
    if key not in _META:
        d = gh_api(f"/repos/{full}")
        lic = (d.get("license") or {}).get("spdx_id")
        _META[key] = {
            "full_name": d["full_name"],
            "stars": d["stargazers_count"],
            "fork": d["fork"],
            "archived": d["archived"],
            "owner_type": d["owner"]["type"],
            "license": None if lic in (None, "") else ("custom" if lic == "NOASSERTION" else lic),
            "pushed_at": d["pushed_at"],
            "created_at": d["created_at"],
            "default_branch": d["default_branch"],
            "description": d.get("description") or "",
        }
    return _META[key]


# --------------------------------------------------------------------------- scoring

def quality(meta: dict, installs: int | None, trusted: set[str]) -> tuple[int, list[str]]:
    """0-100 popularity/maintenance score plus warning flags. Not a safety verdict."""
    flags: list[str] = []
    stars = meta["stars"]
    owner = meta["full_name"].split("/")[0].lower()
    is_trusted = owner in trusted

    score = min(40.0, 40 * math.log10(stars + 1) / math.log10(100_000))
    if installs:
        score += min(20.0, 20 * math.log10(installs + 1) / math.log10(500_000))
    pushed = days_since(meta["pushed_at"])
    score += 10 if pushed <= 90 else 5 if pushed <= 365 else 0
    if pushed > 365:
        flags.append(f"stale: last push {pushed} days ago")
    if is_trusted:
        score += 15
    if meta["license"]:
        score += 5
    else:
        flags.append("no license")
    if meta["fork"]:
        score -= 15
        flags.append("fork")
    if meta["archived"]:
        score -= 30
        flags.append("archived")
    if installs and installs >= 5000 and installs > 200 * max(stars, 1):
        if is_trusted:
            flags.append(f"installs ({installs}) far above stars ({stars}); official vendor, likely tooling-driven")
        else:
            score -= 40
            flags.append(f"INSTALL-INFLATION: {installs} installs vs {stars} stars (clone farm pattern)")
    age = days_since(meta["created_at"])
    if age < 30:
        flags.append(f"new repo ({age} days old)")
    repo_name = meta["full_name"].split("/")[1].lower()
    original = CLONE_WATCH.get(repo_name)
    if original and original.lower() != meta["full_name"].lower():
        score -= 25
        flags.append(f"NAME-COPY: same repo name as {original}; probably a clone or fork-by-copy")
    if is_trusted:
        flags.insert(0, "trusted owner")
    return round(max(0.0, min(100.0, score))), flags


# --------------------------------------------------------------------------- local

def local_skill_dirs(cwd: Path) -> list[tuple[str, Path]]:
    home = Path.home()
    return [
        ("workspace/kiro", cwd / ".kiro" / "skills"),
        ("global/kiro", home / ".kiro" / "skills"),
        ("workspace/claude", cwd / ".claude" / "skills"),
        ("global/claude", home / ".claude" / "skills"),
        ("workspace/agents", cwd / ".agents" / "skills"),
        ("global/agents", home / ".agents" / "skills"),
        ("global/codex", home / ".codex" / "skills"),
    ]


def scan_local(cwd: Path) -> list[dict]:
    seen, out = set(), []
    for scope, base in local_skill_dirs(cwd):
        if not base.is_dir():
            continue
        for md in sorted(base.glob("*/SKILL.md")):
            real = md.resolve()
            if real in seen:
                continue
            seen.add(real)
            try:
                fm, _ = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            out.append({
                "name": fm.get("name") or md.parent.name,
                "description": fm.get("description", ""),
                "scope": scope,
                "path": str(md.parent),
            })
    return out


def match_local(skills: list[dict], query: str) -> list[dict]:
    q = tokens(query)
    if not q:
        return skills
    ranked = []
    for s in skills:
        name_t, desc_t = set(tokens(s["name"])), set(tokens(s["description"]))
        score = sum(3 * (t in name_t) + (t in desc_t) + (t in s["name"].lower()) for t in q)
        if score:
            ranked.append({**s, "match": score})
    return sorted(ranked, key=lambda s: -s["match"])


def cmd_local(args) -> None:
    skills = match_local(scan_local(Path.cwd()), " ".join(args.query))
    if args.json:
        print(json.dumps(skills, indent=2, ensure_ascii=False))
        return
    if not skills:
        print("No matching local skills." if args.query else "No local skills installed.")
        return
    for s in skills:
        extra = f"  match={s['match']}" if "match" in s else ""
        print(f"- {s['name']}  [{s['scope']}]{extra}\n    {s['description'][:220]}\n    {s['path']}")


def cmd_baseline(args) -> None:
    cat = load_catalog()
    base = cat.get("anti_slop_baseline", {})
    installed = {s["name"] for s in scan_local(Path.cwd())}
    kinds_arg = args.kinds or ",".join(cat["baseline_kinds"] or base)
    kinds = [k.strip() for k in kinds_arg.split(",") if k.strip()]
    report = []
    for kind in kinds:
        spec = base.get(kind)
        if not spec:
            report.append({"kind": kind, "status": "unknown-kind"})
            continue
        sets = spec["satisfied_by"]
        hit = next((s for s in sets if all(n in installed for n in s)), None)
        report.append({
            "kind": kind,
            "status": "ok" if hit else "MISSING",
            "satisfied_by": hit,
            "purpose": spec.get("purpose", ""),
            "recommend": None if hit else spec["recommend"],
        })
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    for r in report:
        if r["status"] == "ok":
            print(f"[ok]      {r['kind']}: covered by {', '.join(r['satisfied_by'])}")
        elif r["status"] == "MISSING":
            print(f"[MISSING] {r['kind']}: {r['purpose']}")
            for rec in r["recommend"]:
                print(f"            -> {rec['source']}: {', '.join(rec['skills'])}  ({rec['why']})")
        else:
            print(f"[?]       {r['kind']}: not a baseline kind (use: {', '.join(base)})")


# --------------------------------------------------------------------------- catalog

def cmd_catalog(args) -> None:
    cat = load_catalog()
    domains = cat.get("domains", {})
    query = " ".join(args.query).strip().lower()
    if not query:
        profiles = cat.get("profiles", {})
        print("installed profiles: " + (", ".join(f"{p} ({v['status']})" for p, v in profiles.items())
                                         or "none (core only)"))
        for key, d in domains.items():
            print(f"  {key:20s} [{d['profile']}] {d['title']}")
        print("\nUse: catalog <domain>   or   catalog <keywords>. Other topics: use `search`.")
        return
    if query in domains:
        picked = {query: domains[query]}
    else:
        q = set(tokens(query))
        picked = {k: d for k, d in domains.items()
                  if q & set(tokens(" ".join(d.get("keywords", [])) + " " + k + " " + d["title"]))}
    if not picked:
        print("No curated domain matches. Run `search` instead.")
        return
    if args.json:
        print(json.dumps(picked, indent=2, ensure_ascii=False))
        return
    for key, d in picked.items():
        print(f"## {key} [{d['profile']}]: {d['title']}")
        if d.get("note"):
            print(f"   note: {d['note']}")
        for e in d["entries"]:
            print(f"   - {e['source']}: {', '.join(e['skills'])}\n       {e['why']}")
        print()


# --------------------------------------------------------------------------- search

def skills_sh_search(query: str, limit: int) -> list[dict]:
    url = "https://skills.sh/api/search?" + urllib.parse.urlencode({"q": query, "limit": limit})
    try:
        return http_get(url).get("skills", [])
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"warning: skills.sh search failed ({exc})", file=sys.stderr)
        return []


def github_repo_search(query: str, limit: int) -> list[dict]:
    q = f"{query} skills in:name,description,topics fork:false archived:false"
    try:
        d = gh_api("/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "order": "desc", "per_page": limit}))
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"warning: GitHub search failed ({exc})", file=sys.stderr)
        return []
    return [{"source": r["full_name"], "skillId": None, "installs": None} for r in d.get("items", [])]


def cmd_search(args) -> None:
    cat = load_catalog()
    trusted = {o.lower() for o in cat.get("trusted_owners", [])}
    query = " ".join(args.query)
    hits = skills_sh_search(query, args.limit * 2)
    if args.github or len(hits) < 3:
        hits += github_repo_search(query, max(5, args.limit // 2))

    sources = sorted({h["source"] for h in hits if REPO_RE.match(h["source"] or "")})
    metas: dict[str, dict | str] = {}

    def fetch(src: str):
        try:
            return src, repo_meta(src)
        except Exception as exc:  # noqa: BLE001 - reported per row
            return src, f"metadata error: {exc}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        for src, meta in pool.map(fetch, sources):
            metas[src] = meta

    rows, seen = [], set()
    for h in hits:
        key = (h["source"].lower(), (h.get("skillId") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        meta = metas.get(h["source"])
        row = {"source": h["source"], "skill": h.get("skillId"), "installs": h.get("installs")}
        if isinstance(meta, dict):
            score, flags = quality(meta, h.get("installs"), trusted)
            row.update(stars=meta["stars"], license=meta["license"], pushed=meta["pushed_at"][:10],
                       score=score, flags=flags)
        else:
            row.update(stars=None, score=0, flags=[meta or "not a GitHub owner/repo source; cannot vet"])
        rows.append(row)
    rows.sort(key=lambda r: -r["score"])
    rows = rows[: args.limit]

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if not rows:
        print("No results. Try broader or different keywords.")
        return
    for r in rows:
        skill = r["skill"] or "(repo; run `list` to see its skills)"
        inst = f"{r['installs']:,}" if r["installs"] else "-"
        stars = f"{r['stars']:,}" if r["stars"] is not None else "-"
        print(f"[{r['score']:3d}] {r['source']} :: {skill}\n      stars={stars} installs={inst} "
              f"license={r.get('license') or '-'} pushed={r.get('pushed', '-')}")
        if r["flags"]:
            print(f"      flags: {'; '.join(r['flags'])}")


# --------------------------------------------------------------------------- repo tree

def repo_tree(full: str, ref: str | None) -> tuple[dict, str, list[dict]]:
    meta = repo_meta(full)
    ref = ref or meta["default_branch"]
    sha = gh_api(f"/repos/{full}/commits/{urllib.parse.quote(ref, safe='')}")["sha"]
    tree = gh_api(f"/repos/{full}/git/trees/{sha}?recursive=1")
    # mode 120000 = symlink; skip so mirrored folders (.codex/skills/...) do not duplicate
    blobs = [t for t in tree.get("tree", []) if t["type"] == "blob" and t.get("mode") != "120000"]
    if tree.get("truncated"):
        print("warning: repository tree truncated by GitHub; some skills may be missing", file=sys.stderr)
    return meta, sha, blobs


def skill_md_paths(blobs: list[dict]) -> list[str]:
    return sorted(b["path"] for b in blobs if b["path"] == "SKILL.md" or b["path"].endswith("/SKILL.md"))


def cmd_list(args) -> None:
    _, sha, blobs = repo_tree(args.source, args.ref)
    paths = skill_md_paths(blobs)
    print(f"{args.source} @ {sha[:12]}: {len(paths)} skill(s)")
    for p in paths:
        folder = p.rsplit("/", 2)[-2] if "/" in p else "(repo root)"
        print(f"  {folder:40s} {p}")


def resolve_skill(full: str, skill: str, sha: str, blobs: list[dict]) -> str:
    """Return the path of the SKILL.md for `skill` (folder name, frontmatter name, or path)."""
    paths = skill_md_paths(blobs)
    if not paths:
        raise RuntimeError(f"{full} contains no SKILL.md")
    s = skill.strip().strip("/")
    for p in paths:  # explicit path
        if p == s or p == f"{s}/SKILL.md":
            return p
    by_folder = [p for p in paths if "/" in p and p.rsplit("/", 2)[-2].lower() == s.lower()]
    if by_folder:
        return min(by_folder, key=lambda p: (p.startswith("."), p.count("/"), len(p)))
    if "SKILL.md" in paths and full.split("/")[1].lower() == s.lower():
        return "SKILL.md"
    # fall back to frontmatter names, checking likely candidates first
    toks = [t for t in re.split(r"[-_]", s.lower()) if t]
    cands = sorted(paths, key=lambda p: -sum(t in p.lower() for t in toks))[:40]
    for p in cands:
        try:
            fm, _ = parse_frontmatter(raw_file(full, sha, p).decode("utf-8", "replace"))
        except urllib.error.URLError:
            continue
        if fm.get("name", "").lower() == s.lower():
            return p
    raise RuntimeError(f"skill '{skill}' not found in {full}. Run: list {full}")


# --------------------------------------------------------------------------- static scan

SCRIPT_EXT = {".sh", ".bash", ".zsh", ".fish", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx",
              ".ps1", ".psm1", ".rb", ".pl", ".php", ".go", ".lua", ".bat", ".cmd", ".rs"}
BINARY_EXT = {".exe", ".dll", ".so", ".dylib", ".bin", ".jar", ".class", ".pyc", ".wasm",
              ".msi", ".deb", ".rpm", ".app", ".scr", ".com", ".elf"}
TEXT_HINT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ".csv",
                 ".xml", ".svg", ".ini", ".cfg"} | SCRIPT_EXT

# (severity, id, scope, regex) ; scope: all | script | doc
RULES = [
    ("HIGH", "pipe-to-shell", "all",
     r"(curl|wget|iwr|invoke-webrequest)\b[^\n|]{0,300}\|\s*(sudo\s+)?(ba|z|da|k)?sh\b|\|\s*iex\b|invoke-expression"),
    ("HIGH", "secret-paths", "all",
     r"\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.netrc\b|\.pypirc|\.docker/config\.json"
     r"|\.config/gh/hosts|login data|keychain-db|wallet\.dat|\.gnupg"),
    ("HIGH", "prompt-injection", "all",
     r"ignore (all |any )?(of )?(the )?(previous|prior|above|earlier) (instructions|rules|messages)"
     r"|disregard (the |all |any )?(system|previous|prior)|do not (tell|inform|mention (this )?to) the user"
     r"|without (asking|telling|informing|notifying) the user|hide (this|it|these) from the user"
     r"|you are now (in )?(developer|dan|jailbreak|unrestricted)|override (the )?system prompt"),
    ("HIGH", "destructive", "all",
     r"rm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$home|\*)(\s|$)|\bmkfs\b|\bdd\s+if=[^\n]*of=/dev/|:\(\)\s*\{\s*:\|:&\s*\};:"),
    ("HIGH", "obfuscated-exec", "all",
     r"(base64\s+(-d|--decode)|b64decode|atob\(|frombase64string)[^\n]{0,200}(\|\s*(ba)?sh|exec|eval|invoke)"
     r"|(eval|exec)\s*\(\s*(base64|atob|bytes\.fromhex|codecs\.decode|zlib\.decompress)"),
    ("HIGH", "secret-exfil", "all",
     r"(curl|wget|fetch\(|requests\.(post|put)|axios\.(post|put)|http\.request)[^\n]{0,250}"
     r"(\$\(?(env|printenv)|process\.env|os\.environ|github_token|aws_secret|api_key|\.env\b)"),
    ("MEDIUM", "sudo", "all", r"\bsudo\s+\S"),
    ("MEDIUM", "network-in-script", "script",
     r"urllib\.request|\brequests\.(get|post|put|delete|request)|http\.client|\bsocket\.socket|\baxios\b"
     r"|xmlhttprequest|net\.connect|\bfetch\(\s*[`'\"]https?://(?!127\.0\.0\.1|localhost)"
     r"|\b(curl|wget)\s+(-[a-z]+\s+)*['\"]?https?://"),
    ("MEDIUM", "dynamic-exec", "script",
     r"(?<![.\w])(eval|exec)\s*\(|new Function\(|subprocess\.|os\.system|os\.popen|child_process"
     r"|exec(file)?sync|spawnsync|shell\s*=\s*true"),
    ("MEDIUM", "remote-instructions", "doc",
     r"raw\.githubusercontent\.com|(curl|wget)\s+(-[a-z]+\s+)*https?://|fetch (the )?(latest )?instructions from"),
    ("LOW", "package-install", "all",
     r"\b(npx|bunx|uvx|pipx)\s+[a-z@]|\bnpm\s+(i|install)\s+-g|\bpip3?\s+install\b|\bbrew\s+install\b|\bcargo\s+install\b"),
    ("LOW", "env-access", "script", r"os\.environ|process\.env|\bgetenv\("),
    ("LOW", "account-required", "doc",
     r"\b(api[ _-]?key|access[ _-]token|sign up (for|at)|create an account|requires? (an? )?(paid )?account"
     r"|paid plan|credits)\b|^\s*[a-z0-9-]+ (auth )?login\s*$"),
]
COMPILED = [(sev, rid, scope, re.compile(rx, re.IGNORECASE)) for sev, rid, scope, rx in RULES]
HIDDEN_HIGH = re.compile("[\u202a-\u202e\u2066-\u2069\U000E0000-\U000E007F]")  # bidi + tag chars
HIDDEN_MED = re.compile("[\u200b-\u200f\u2060\ufeff]")  # zero-width
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def scan_files(root: Path, files: list[str]) -> list[dict]:
    findings: list[dict] = []
    per_rule: dict[tuple[str, str], int] = {}

    def add(sev, rid, rel, line_no, line):
        k = (rid, rel)
        per_rule[k] = per_rule.get(k, 0) + 1
        if per_rule[k] <= 3:
            findings.append({"severity": sev, "rule": rid, "file": rel, "line": line_no,
                             "text": line.strip()[:180]})

    for rel in files:
        path = root / rel
        ext = path.suffix.lower()
        if ext in BINARY_EXT:
            add("HIGH", "binary-executable", rel, 0, "compiled/binary executable bundled in skill")
            continue
        data = path.read_bytes()
        if b"\x00" in data[:8192] and ext not in TEXT_HINT_EXT:
            add("LOW", "binary-file", rel, 0, "non-text file (image/font/archive?), not scanned")
            continue
        text = data.decode("utf-8", "replace")
        is_script = ext in SCRIPT_EXT or text.startswith("#!")
        scope = "script" if is_script else "doc"
        for i, line in enumerate(text.splitlines(), 1):
            if HIDDEN_HIGH.search(line):
                add("HIGH", "hidden-unicode", rel, i, repr(line)[:180])
            elif HIDDEN_MED.search(line):
                add("MEDIUM", "zero-width-chars", rel, i, repr(line)[:180])
            for sev, rid, rscope, rx in COMPILED:
                if rscope in ("all", scope) and rx.search(line):
                    add(sev, rid, rel, i, line)
    for (rid, rel), n in per_rule.items():
        if n > 3:
            findings.append({"severity": "LOW", "rule": rid, "file": rel, "line": 0,
                             "text": f"... {n - 3} more '{rid}' hits in this file"})
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["file"], f["line"]))


def check_frontmatter(fm: dict, md_text: str, folder: str) -> list[dict]:
    out = []

    def add(sev, msg):
        out.append({"severity": sev, "rule": "frontmatter", "file": "SKILL.md", "line": 0, "text": msg})

    name, desc = fm.get("name", ""), fm.get("description", "")
    if not name or not desc:
        add("MEDIUM", "missing name or description; not a valid Agent Skill")
    if name and (not SKILL_NAME_RE.match(name) or len(name) > 64):
        add("LOW", f"name '{name}' breaks the spec (lowercase, digits, hyphens, max 64)")
    if name and folder and name != folder:
        add("LOW", f"name '{name}' differs from folder '{folder}'; install uses the name")
    if len(desc) > 1024:
        add("LOW", f"description is {len(desc)} chars (spec max 1024)")
    if len(md_text) > 30_000:
        add("LOW", f"SKILL.md is {len(md_text):,} chars; costs a lot of context when it loads")
    tools = fm.get("allowed-tools", "")
    if re.search(r"\bBash\b(?!\()|Bash\(\*\)", tools):
        add("LOW", f"allowed-tools grants unrestricted shell: {tools}")
    return out


# --------------------------------------------------------------------------- vet / install

def stage_skill(full: str, skill: str, ref: str | None) -> dict:
    if not REPO_RE.match(full):
        raise RuntimeError(f"'{full}' is not an OWNER/REPO GitHub source")
    meta, sha, blobs = repo_tree(full, ref)
    md_path = resolve_skill(full, skill, sha, blobs)
    folder = md_path.rsplit("/", 1)[0] if "/" in md_path else ""
    prefix = f"{folder}/" if folder else ""

    other_skill_dirs = [p.rsplit("/", 1)[0] + "/" for p in skill_md_paths(blobs) if p != md_path and "/" in p]
    files = []
    for b in blobs:
        p = b["path"]
        if not p.startswith(prefix):
            continue
        if any(p.startswith(d) for d in other_skill_dirs if d.startswith(prefix)):
            continue  # nested skill, not part of this one
        if not folder and (p.startswith((".github/", ".git")) or p.startswith(".")):
            continue
        files.append(b)

    md_raw = raw_file(full, sha, md_path).decode("utf-8", "replace")
    fm, _ = parse_frontmatter(md_raw)
    name = fm.get("name") if SKILL_NAME_RE.match(fm.get("name", "")) else None
    name = name or (folder.rsplit("/", 1)[-1] if folder else full.split("/")[1]).lower()

    owner, repo = full.split("/")
    stage = STAGING_ROOT / f"{owner}__{repo}__{name}__{sha[:12]}"
    if stage.exists():
        shutil.rmtree(stage)
    skill_root = stage / "skill"
    skill_root.mkdir(parents=True)

    wanted, skipped = {}, []
    total_planned = 0
    for b in sorted(files, key=lambda b: b["path"]):
        rel = b["path"][len(prefix):]
        size = b.get("size", 0)
        if ".." in Path(rel).parts or rel.startswith("/") or size > MAX_FILE_BYTES \
                or len(wanted) >= MAX_FILES or total_planned + size > MAX_TOTAL_BYTES:
            skipped.append(rel)
            continue
        wanted[b["path"]] = rel
        total_planned += size

    kept, total = [], 0

    def write(rel: str, data: bytes) -> None:
        nonlocal total
        dest = skill_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        kept.append(rel)
        total += len(data)

    if len(wanted) <= RAW_FETCH_LIMIT:
        for path, rel in wanted.items():
            write(rel, md_raw.encode() if path == md_path else raw_file(full, sha, path))
    else:
        for path, data in tarball_members(full, sha, set(wanted)):
            write(wanted[path], data)
        missing = set(wanted.values()) - set(kept)
        skipped.extend(sorted(missing))
    kept.sort()

    return {"meta": meta, "sha": sha, "md_path": md_path, "folder": folder, "name": name,
            "frontmatter": fm, "md_text": md_raw, "stage": stage, "skill_root": skill_root,
            "files": kept, "skipped": skipped, "bytes": total}


def vet(full: str, skill: str, ref: str | None, installs: int | None = None) -> dict:
    cat = load_catalog()
    trusted = {o.lower() for o in cat.get("trusted_owners", [])}
    st = stage_skill(full, skill, ref)
    folder_name = st["folder"].rsplit("/", 1)[-1] if st["folder"] else ""
    findings = check_frontmatter(st["frontmatter"], st["md_text"], folder_name)
    findings += scan_files(st["skill_root"], st["files"])
    if st["skipped"]:
        findings.append({"severity": "MEDIUM", "rule": "not-downloaded", "file": "-", "line": 0,
                         "text": f"{len(st['skipped'])} file(s) over size/count limits were not staged or scanned"})
    findings.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    if installs is None:
        installs = lookup_installs(full, st["name"])
    score, flags = quality(st["meta"], installs, trusted)
    sevs = {f["severity"] for f in findings}
    verdict = "REJECT" if "HIGH" in sevs else "REVIEW" if "MEDIUM" in sevs else "PASS"
    clone_signal = any(f.startswith(("INSTALL-INFLATION", "NAME-COPY")) for f in flags)
    if clone_signal and score < 20:
        verdict = "REJECT"
        findings.insert(0, {"severity": "HIGH", "rule": "clone-repo", "file": "-", "line": 0,
                            "text": "clone/impersonation signals with quality < 20; use the original repo instead"})
    elif clone_signal and verdict == "PASS":
        verdict = "REVIEW"
    report = {
        "source": full, "skill": st["name"], "sha": st["sha"], "skill_path": st["md_path"],
        "url": f"https://github.com/{full}/tree/{st['sha']}/{st['folder']}",
        "description": st["frontmatter"].get("description", ""),
        "stars": st["meta"]["stars"], "installs": installs, "license": st["meta"]["license"],
        "pushed": st["meta"]["pushed_at"][:10], "quality": score, "quality_flags": flags,
        "verdict": verdict, "findings": findings,
        "files": st["files"], "bytes": st["bytes"],
        "staged_dir": str(st["skill_root"]),
    }
    (st["stage"] / "vet-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def lookup_installs(full: str, name: str) -> int | None:
    for s in skills_sh_search(name, 20):
        if s.get("source", "").lower() == full.lower() and s.get("skillId", "").lower() == name.lower():
            return s.get("installs")
    return None


def print_report(r: dict) -> None:
    print(f"VERDICT: {r['verdict']}   quality={r['quality']}/100")
    print(f"skill:   {r['skill']}  from {r['source']} @ {r['sha'][:12]}")
    print(f"url:     {r['url']}")
    print(f"stats:   stars={r['stars']:,} installs={r['installs'] or '-'} license={r['license'] or '-'} "
          f"pushed={r['pushed']}")
    if r["quality_flags"]:
        print(f"flags:   {'; '.join(r['quality_flags'])}")
    print(f"desc:    {r['description'][:300]}")
    print(f"files:   {len(r['files'])} ({r['bytes']:,} bytes): {', '.join(r['files'][:12])}"
          + (" ..." if len(r["files"]) > 12 else ""))
    if r["findings"]:
        counts = {s: sum(f["severity"] == s for f in r["findings"]) for s in SEVERITY_ORDER}
        print("findings: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n))
        for f in r["findings"][:FINDINGS_PRINT_LIMIT]:
            loc = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            print(f"  [{f['severity']:6s}] {f['rule']:20s} {loc}  {f['text']}")
        if len(r["findings"]) > FINDINGS_PRINT_LIMIT:
            print(f"  ... {len(r['findings']) - FINDINGS_PRINT_LIMIT} more in "
                  f"{Path(r['staged_dir']).parent / 'vet-report.json'}")
    else:
        print("findings: none")
    print(f"staged:  {r['staged_dir']}")
    print("next:    read staged SKILL.md and every script before recommending; pass --sha "
          f"{r['sha']} to install")


def cmd_vet(args) -> None:
    r = vet(args.source, args.skill, args.sha or args.ref, args.installs)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print_report(r)


def target_dir(args) -> Path:
    if args.dir:
        return Path(args.dir).expanduser().resolve()
    agent_dir = {"kiro": ".kiro", "claude": ".claude", "agents": ".agents"}[args.agent]
    base = Path.home() if args.scope == "global" else Path.cwd()
    return base / agent_dir / "skills"


def cmd_install(args) -> None:
    r = vet(args.source, args.skill, args.sha)
    print_report(r)
    print()
    if r["verdict"] == "REJECT" and not args.force:
        die("verdict REJECT: not installing. (--force exists only for a user who read the findings "
            "and explicitly insists.)", 2)
    if r["verdict"] == "REVIEW" and not (args.allow_review or args.force):
        die("verdict REVIEW: read the flagged lines, get the user's OK, then rerun with --allow-review.", 2)

    dest_root = target_dir(args)
    dest = dest_root / r["skill"]
    dest_root.mkdir(parents=True, exist_ok=True)
    lock_path = dest_root / LOCK_NAME
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}

    if dest.exists():
        if not args.overwrite:
            die(f"{dest} already exists. Rerun with --overwrite to replace it (a backup is kept).", 3)
        backup_root = dest_root.parent / "skills-backup"  # outside skills/ so it never loads twice
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = backup_root / f"{r['skill']}-{stamp}"
        n = 2
        while backup.exists():
            backup = backup_root / f"{r['skill']}-{stamp}-{n}"
            n += 1
        shutil.move(str(dest), str(backup))
        print(f"backed up existing skill to {backup}")

    shutil.copytree(r["staged_dir"], dest)
    lock[r["skill"]] = {
        "source": r["source"], "path": r["skill_path"], "sha": r["sha"], "url": r["url"],
        "verdict": r["verdict"], "quality": r["quality"],
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    print(f"installed {r['skill']} -> {dest}")
    print(f"pinned at {r['sha']} (recorded in {lock_path})")

    if args.dir or args.agent != "kiro":
        print("note: not added to the Kiro active-skills steering (custom --dir or non-Kiro agent). "
              "Read the SKILL.md now and apply it.")
    else:
        steering = register_active(args.scope, [{
            "name": r["skill"], "description": r["description"], "path": str(dest / "SKILL.md"),
            "source": r["source"],
        }])
        print(f"active: {r['skill']} added to {steering}")
    print(f"NEXT: read {dest / 'SKILL.md'} in full now and apply it to the current task.")


# --------------------------------------------------------------------------- active skills
#
# Every skill the user approved (installed here, or already local and chosen for the project)
# is listed in a Kiro steering file with `inclusion: always`. That file is loaded in every
# session, so the agent keeps using the skills instead of installing them and forgetting them.

ACTIVE_JSON = "find-skills-active.json"
ACTIVE_STEERING = "find-skills-active.md"
ACTIVE_DESC_CHARS = 220


def active_base(scope: str) -> Path:
    return (Path.home() if scope == "global" else Path.cwd()) / ".kiro"


def display_path(p: str) -> str:
    path = Path(p)
    for root, prefix in ((Path.cwd(), ""), (Path.home(), "~/")):
        try:
            return prefix + str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def load_active(scope: str) -> dict:
    f = active_base(scope) / ACTIVE_JSON
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        die(f"{f} is not valid JSON; fix or delete it, then rerun")
    return {}


def render_steering(scope: str, active: dict) -> str:
    where = "every project" if scope == "global" else "this project"
    lines = [
        "---", "inclusion: always", "---", "",
        "# Active skills (managed by find-skills)", "",
        f"The user approved these skills for {where}. They are already installed. Use them; "
        "do not ask again whether to install or use them.", "",
        "1. Before working in an area a skill covers, read its SKILL.md in full (path below) unless it is "
        "already loaded in this session, then follow it, including its own setup questions and checklists.",
        "2. Apply every skill whose \"Use when\" matches the work, not only the first match.",
        "3. Before reporting work as done, go through this list. For each skill, either name what you did "
        "with it (rule applied, audit run, gate passed) or say in a few words why it did not apply. "
        "Never skip one silently.", "",
        "| Skill | Use when | SKILL.md |", "|---|---|---|",
    ]
    for name in sorted(active):
        a = active[name]
        desc = " ".join(a.get("description", "").split())
        if len(desc) > ACTIVE_DESC_CHARS:
            desc = desc[:ACTIVE_DESC_CHARS].rsplit(" ", 1)[0] + "…"
        desc = desc.replace("|", "\\|")
        lines.append(f"| `{name}` | {desc} | `{a['display_path']}` |")
    lines.append("")
    lines.append("Manage this list with `find-skills` (`use`, `unuse`, `active`); manual edits are overwritten.")
    return "\n".join(lines) + "\n"


def write_active(scope: str, active: dict) -> Path:
    base = active_base(scope)
    steering = base / "steering" / ACTIVE_STEERING
    (base / "steering").mkdir(parents=True, exist_ok=True)
    (base / ACTIVE_JSON).write_text(json.dumps(active, indent=2, ensure_ascii=False) + "\n")
    if active:
        steering.write_text(render_steering(scope, active), encoding="utf-8")
    elif steering.exists():
        steering.unlink()
    return steering


def register_active(scope: str, skills: list[dict]) -> Path:
    active = load_active(scope)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for s in skills:
        active[s["name"]] = {
            "description": s.get("description", ""),
            "path": s["path"],
            "display_path": display_path(s["path"]),
            "source": s.get("source", "local"),
            "added_at": now,
        }
    return write_active(scope, active)


def cmd_use(args) -> None:
    local = {}
    for s in scan_local(Path.cwd()):  # first hit wins: workspace before global
        local.setdefault(s["name"], s)
    missing = [n for n in args.names if n not in local]
    if missing:
        die(f"not installed locally: {', '.join(missing)}. Run `local` to see installed skills.")
    picked = [{"name": n, "description": local[n]["description"],
               "path": str(Path(local[n]["path"]) / "SKILL.md")} for n in args.names]
    steering = register_active(args.scope, picked)
    for p in picked:
        print(f"active: {p['name']}  ({display_path(p['path'])})")
    print(f"written: {steering}")
    print("NEXT: read each SKILL.md above in full now and apply it to the current task.")


def cmd_unuse(args) -> None:
    active = load_active(args.scope)
    for n in args.names:
        if active.pop(n, None) is None:
            print(f"not active: {n}")
        else:
            print(f"removed from active list: {n} (the skill stays installed)")
    print(f"written: {write_active(args.scope, active)}")


def cmd_active(args) -> None:
    shown = False
    for scope in ("workspace", "global"):
        active = load_active(scope)
        if not active:
            continue
        shown = True
        print(f"[{scope}] {active_base(scope) / 'steering' / ACTIVE_STEERING}")
        for name in sorted(active):
            a = active[name]
            ok = "" if Path(a["path"]).exists() else "   (MISSING on disk)"
            print(f"  - {name:28s} {a['display_path']}{ok}")
    if not shown:
        print("No active skills registered.")


# --------------------------------------------------------------------------- cli

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("local", help="list or match installed skills")
    s.add_argument("query", nargs="*")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_local)

    s = sub.add_parser("baseline", help="check the mandatory anti-slop baseline")
    s.add_argument("--kinds", help="comma list of ui, code, writing (default: what the installed profiles need)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_baseline)

    s = sub.add_parser("catalog", help="curated sources by domain")
    s.add_argument("query", nargs="*")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_catalog)

    s = sub.add_parser("search", help="search skills.sh and GitHub, ranked by quality")
    s.add_argument("query", nargs="+")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--github", action="store_true", help="always include GitHub repo search")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("list", help="list skills inside a repo")
    s.add_argument("source")
    s.add_argument("--ref")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("vet", help="stage + scan + score one skill")
    s.add_argument("source")
    s.add_argument("skill")
    s.add_argument("--ref", help="branch or tag (default: repo default branch)")
    s.add_argument("--sha", help="exact commit")
    s.add_argument("--installs", type=int, help="install count from `search`, if known")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_vet)

    s = sub.add_parser("install", help="vet at a pinned commit and install (only after user consent)")
    s.add_argument("source")
    s.add_argument("skill")
    s.add_argument("--sha", help="commit from the vet step; pins exactly what the user approved")
    s.add_argument("--scope", choices=["workspace", "global"], default="workspace")
    s.add_argument("--agent", choices=["kiro", "claude", "agents"], default="kiro")
    s.add_argument("--dir", help="explicit skills directory (overrides --scope/--agent)")
    s.add_argument("--overwrite", action="store_true")
    s.add_argument("--allow-review", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("use", help="mark already-installed skills as active for this project")
    s.add_argument("names", nargs="+")
    s.add_argument("--scope", choices=["workspace", "global"], default="workspace")
    s.set_defaults(fn=cmd_use)

    s = sub.add_parser("unuse", help="remove skills from the active list (keeps them installed)")
    s.add_argument("names", nargs="+")
    s.add_argument("--scope", choices=["workspace", "global"], default="workspace")
    s.set_defaults(fn=cmd_unuse)

    s = sub.add_parser("active", help="show the active skills the agent must apply")
    s.set_defaults(fn=cmd_active)

    args = p.parse_args()
    try:
        args.fn(args)
    except (RuntimeError, urllib.error.URLError) as exc:
        die(str(exc))
    except KeyboardInterrupt:
        die("interrupted", 130)


if __name__ == "__main__":
    main()

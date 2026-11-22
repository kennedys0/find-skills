#!/usr/bin/env python3
"""Re-vet every curated catalog entry and report regressions.

Runs `skillfinder.py vet --json` for each (source, skill) in every stable profile,
against each repo's current default branch, so drift is noticed: a repo that got
archived, cloned, or flagged since it was added shows up here.

REJECT or a vet that fails to run is a failure (exit 1). REVIEW is reported as a
warning only: the contribution rules allow REVIEW entries when the flags are explained.

Writes revet-report.md (and prints the same markdown) for the CI issue.
Standard library only.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "skills" / "find-skills" / "references" / "catalog"
SF = ROOT / "skills" / "find-skills" / "scripts" / "skillfinder.py"
REPORT = Path("revet-report.md")


def vet_one(source: str, skill: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SF), "vet", source, skill, "--json"],
        capture_output=True, text=True, timeout=300)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"verdict": "ERROR", "quality": None,
                "detail": (proc.stderr or proc.stdout or "no output").strip()[:300]}
    detail = "; ".join(f["text"] for f in report.get("findings", [])[:3])
    if report.get("quality_flags"):
        detail = (detail + "; " if detail else "") + "; ".join(report["quality_flags"][:3])
    return {"verdict": report.get("verdict", "?"), "quality": report.get("quality"), "detail": detail}


def main() -> int:
    lines = ["# Catalog re-vet report", ""]
    rejects, warns, total = [], [], 0
    for path in sorted(CATALOG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") == "draft":
            continue
        profile = data.get("profile", path.stem)
        for key, dom in sorted(data.get("domains", {}).items()):
            for entry in dom.get("entries", []):
                source = entry.get("source", "")
                for skill in entry.get("skills", []):
                    total += 1
                    r = vet_one(source, skill)
                    row = f"- `{source}` :: `{skill}` [{profile}/{key}] — **{r['verdict']}**"
                    if r["quality"] is not None:
                        row += f" (quality {r['quality']})"
                    if r["detail"]:
                        row += f" — {r['detail']}"
                    lines.append(row)
                    if r["verdict"] == "REJECT":
                        rejects.append(row)
                    elif r["verdict"] in ("REVIEW", "ERROR"):
                        warns.append(row)
    lines.insert(2, f"Checked {total} skill(s): {len(rejects)} reject(s), {len(warns)} warning(s).")
    lines.insert(3, "")
    report = "\n".join(lines) + "\n"
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    if rejects:
        print(f"::error::{len(rejects)} catalog entry/entries now vet as REJECT; "
              "replace or remove them.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

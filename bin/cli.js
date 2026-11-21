#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PKG_ROOT = path.resolve(__dirname, "..");
const PKG = require(path.join(PKG_ROOT, "package.json"));
const SKILL_SRC = path.join(PKG_ROOT, "skills", "find-skills");
const CATALOG_SRC = path.join(SKILL_SRC, "references", "catalog");
const AGENTS_FILE = path.join(SKILL_SRC, "references", "agents.json");
const STEERING_SRC = path.join(PKG_ROOT, "steering", "find-skills-auto.md");
const SKILL_NAME = "find-skills";
const VERSION = PKG.version;
const REPO = (/github\.com[/:]([^/]+\/[^/.]+)/.exec((PKG.repository || {}).url || "") || [])[1]
  || "kennedys0/find-skills";
const HOME = os.homedir();
const CONFIG_HOME = process.env.XDG_CONFIG_HOME || path.join(HOME, ".config");
const IS_WIN = process.platform === "win32";

// ------------------------------------------------------------------ data

function readProfiles() {
  const out = {};
  for (const file of fs.readdirSync(CATALOG_SRC).filter((f) => f.endsWith(".json")).sort()) {
    const data = JSON.parse(fs.readFileSync(path.join(CATALOG_SRC, file), "utf8"));
    const name = data.profile || path.basename(file, ".json");
    if (name === "core") continue;
    out[name] = { file, title: data.title || name, status: data.status || "stable",
                  domains: Object.keys(data.domains || {}) };
  }
  return out;
}

function expandHome(p) {
  return p.replace(/^\{config\}/, CONFIG_HOME).replace(/^~(?=$|[\\/])/, HOME);
}

function readAgents() {
  const raw = JSON.parse(fs.readFileSync(AGENTS_FILE, "utf8")).agents;
  const agents = {};
  const alias = {};
  for (const [id, a] of Object.entries(raw)) {
    agents[id] = { id, ...a, globalDir: expandHome(a.global), detectPaths: (a.detect || []).map(expandHome) };
    alias[id] = id;
    for (const al of a.aliases || []) alias[al] = id;
  }
  return { agents, alias };
}

const PROFILES = readProfiles();
const { agents: AGENTS, alias: AGENT_ALIAS } = readAgents();
const stable = () => Object.keys(PROFILES).filter((p) => PROFILES[p].status !== "draft");
const detected = () => Object.values(AGENTS).filter((a) => a.detectPaths.some((p) => fs.existsSync(p))).map((a) => a.id);
function tilde(p) {
  const cwd = process.cwd();
  if (cwd !== HOME && p.startsWith(cwd + path.sep)) return "." + p.slice(cwd.length);
  return p.startsWith(HOME) ? "~" + p.slice(HOME.length) : p;
}

// ------------------------------------------------------------------ versions

function parseVersion(v) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)(-.+)?$/.exec(String(v || "").trim());
  return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] ? 0 : 1] : null;
}

/** >0 when a is newer than b. A pre-release sorts before its release. Unknown sorts first. */
function compareVersions(a, b) {
  const x = parseVersion(a);
  const y = parseVersion(b);
  if (!x || !y) return x ? 1 : y ? -1 : 0;
  for (let i = 0; i < 4; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}

/** Latest stable release tag, or null when offline. Uses the web redirect, which has no API rate limit. */
async function latestVersion() {
  const timeout = () => AbortSignal.timeout(6000);
  try {
    const r = await fetch(`https://github.com/${REPO}/releases/latest`, { redirect: "manual", signal: timeout() });
    const m = /\/releases\/tag\/v?([^/?#]+)/.exec(r.headers.get("location") || "");
    if (m) return decodeURIComponent(m[1]);
  } catch { /* fall through */ }
  try {
    const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
    const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      signal: timeout(),
    });
    if (r.ok) return String((await r.json()).tag_name || "").replace(/^v/, "") || null;
  } catch { /* offline */ }
  return null;
}

function skillVersion(dir) {
  try {
    const m = /^\s+version:\s*["']?([^"'\s]+)["']?\s*$/m.exec(fs.readFileSync(path.join(dir, "SKILL.md"), "utf8"));
    return m ? m[1] : "unknown";
  } catch {
    return "unknown";
  }
}

function npmCmd(args, extra = {}) {
  return spawnSync(IS_WIN ? "npm.cmd" : "npm", args, { encoding: "utf8", shell: IS_WIN, ...extra });
}

/** True when this file runs from `npm install -g`, not from npx or a git clone. */
function isGlobalInstall() {
  const r = npmCmd(["root", "-g"]);
  if (r.status !== 0) return false;
  const root = path.resolve(r.stdout.trim());
  const here = fs.realpathSync(PKG_ROOT);
  return here.startsWith(root + path.sep) && !here.includes(`${path.sep}_npx${path.sep}`);
}

// ------------------------------------------------------------------ cli

function help() {
  const rows = Object.entries(PROFILES)
    .map(([n, p]) => `  --${n.padEnd(12)} ${p.title}${p.status === "draft" ? "  (coming soon)" : ""}`)
    .join("\n");
  console.log(`find-skills ${VERSION}: skill finder for Kiro and other Agent Skills tools

Usage:
  find-skills [profiles] [options]   install or update the skill
  find-skills update                 update this command and every installed copy of the skill
  find-skills version                version of the command, the latest release, and installed copies
  find-skills status                 same as version
  find-skills list                   profiles
  find-skills agents                 supported agents and where skills go
  find-skills uninstall [options]    remove the skill (the command stays; npm uninstall -g find-skills)

Without a global install, prefix commands with: npx github:${REPO}

Profiles:
${rows}
  --all          every stable profile
  (no profile)   keeps the profiles of an existing install, or installs all stable ones

Options:
  --agent <id>        target agent (default: kiro). Repeat or comma-separate: --agent codex,pi
                      ids: ${Object.keys(AGENTS).join(", ")}
  --detect            also install for every agent found on this machine
  --workspace [dir]   install into the project at <dir> (default: current folder)
                      without it, installs globally into each agent's home folder
  --only              replace the installed profiles instead of adding to them
  --auto              add an always-on Kiro steering file so it triggers on new projects
  --force             update: reinstall copies even when they are already current
  --dry-run           print what would happen, change nothing
  -h, --help          this help
  -v, --version       same as \`find-skills version\`

Examples:
  find-skills --website --auto
  find-skills --website --agent codex --agent opencode
  find-skills --website --detect
  find-skills update`);
}

function fail(msg) {
  console.error(`find-skills: ${msg}`);
  process.exit(1);
}

function parseArgs(argv) {
  const opts = { cmd: "install", profiles: [], agents: [], detect: false, workspace: null,
                 only: false, auto: false, dryRun: false, all: false, force: false };
  const commands = { install: "install", add: "install", uninstall: "uninstall", remove: "uninstall",
                     list: "list", agents: "agents", update: "update", upgrade: "update",
                     version: "version", status: "version", help: "help" };
  // Accept single-dash long options too: -detect, -website, -agent=codex mean --detect, --website, --agent=codex.
  argv = argv.map((a) => (/^-[a-z][a-z0-9-]+(=.*)?$/i.test(a) ? "-" + a : a));
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => (argv[i + 1] && !argv[i + 1].startsWith("-") ? argv[++i] : null);
    if (a === "-h" || a === "--help") opts.cmd = "help";
    else if (a === "-v" || a === "--version") opts.cmd = "version";
    else if (a === "--update") opts.cmd = "update";
    else if (a === "--list") opts.cmd = "list";
    else if (commands[a]) opts.cmd = commands[a];
    else if (a === "--all") opts.all = true;
    else if (a === "--only") opts.only = true;
    else if (a === "--auto") opts.auto = true;
    else if (a === "--detect") opts.detect = true;
    else if (a === "--force") opts.force = true;
    else if (a === "--dry-run") opts.dryRun = true;
    else if (a === "--global") opts.workspace = null;
    else if (a === "--workspace") opts.workspace = path.resolve(next() || ".");
    else if (a === "--agent" || a.startsWith("--agent=")) {
      const v = a.includes("=") ? a.split("=")[1] : next();
      if (!v) fail("--agent needs a value. Run `find-skills agents` for the list.");
      for (const name of v.split(",").map((s) => s.trim()).filter(Boolean)) {
        const id = AGENT_ALIAS[name.toLowerCase()];
        if (!id) fail(`unknown agent '${name}'. Run \`find-skills agents\` for the list.`);
        opts.agents.push(id);
      }
    } else if (a.startsWith("--") || PROFILES[a]) {
      const name = a.replace(/^--/, "");
      if (!PROFILES[name]) fail(`unknown option or profile '${a}'. Run with --help.`);
      opts.profiles.push(name);
    } else fail(`unexpected argument '${a}'. Run with --help.`);
  }
  return opts;
}

// ------------------------------------------------------------------ targets

/** Resolve agents to unique skill folders; agents sharing a folder get one install. */
function targets(opts) {
  let ids = [...opts.agents];
  if (opts.detect) ids.push(...detected());
  if (!ids.length) ids = ["kiro"];
  const byDir = new Map();
  for (const id of [...new Set(ids)]) {
    const a = AGENTS[id];
    const root = path.resolve(opts.workspace ? path.join(opts.workspace, a.project) : a.globalDir);
    if (!byDir.has(root)) byDir.set(root, { root, ids: [] });
    byDir.get(root).ids.push(id);
  }
  return [...byDir.values()];
}

/** Every existing copy of find-skills: each agent's global folder, plus project folders under `cwd`. */
function installedCopies(cwd) {
  const byDir = new Map();
  for (const a of Object.values(AGENTS)) {
    for (const root of [a.globalDir, path.join(cwd, a.project)].map((p) => path.resolve(p))) {
      const dest = path.join(root, SKILL_NAME);
      if (!isOurSkill(dest)) continue;
      if (!byDir.has(root)) {
        byDir.set(root, { root, ids: [], version: skillVersion(dest), profiles: installedProfiles(dest) });
      }
      if (!byDir.get(root).ids.includes(a.id)) byDir.get(root).ids.push(a.id);
    }
  }
  return [...byDir.values()];
}

function isOurSkill(dir) {
  try {
    return /^name:\s*find-skills\s*$/m.test(fs.readFileSync(path.join(dir, "SKILL.md"), "utf8"));
  } catch {
    return false;
  }
}

function installedProfiles(dir) {
  const cat = path.join(dir, "references", "catalog");
  if (!fs.existsSync(cat)) return [];
  return fs.readdirSync(cat).filter((f) => f.endsWith(".json") && f !== "core.json")
    .map((f) => path.basename(f, ".json"));
}

function backupPath(root) {
  // A sibling of the skills folder, so the backup is never loaded as a second skill.
  const dir = path.join(path.dirname(root), "skills-backup");
  const base = `${SKILL_NAME}-${new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15)}`;
  let candidate = path.join(dir, base);
  for (let n = 2; fs.existsSync(candidate); n++) candidate = path.join(dir, `${base}-${n}`);
  return candidate;
}

function findPython() {
  for (const cmd of ["python3", "python", "py"]) {
    const r = spawnSync(cmd, ["-c", "import sys; print(sys.version_info >= (3, 9))"], { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim() === "True") return cmd;
  }
  return null;
}

function resolveProfiles(opts, existing) {
  for (const p of opts.profiles) {
    if (PROFILES[p].status === "draft") fail(`profile '${p}' is coming soon and cannot be installed yet.`);
  }
  const known = existing.filter((p) => PROFILES[p] && PROFILES[p].status !== "draft");
  let chosen;
  if (opts.all) chosen = stable();
  else if (opts.profiles.length) chosen = opts.only ? opts.profiles : [...new Set([...known, ...opts.profiles])];
  else chosen = known.length ? known : stable();
  return [...new Set(chosen)].sort();
}

const label = (t) => t.ids.map((id) => AGENTS[id].name).join(", ");

/** Label for a found copy: only agents installed on this machine, since many agents share a folder. */
function copyLabel(c) {
  const found = new Set(detected());
  const ids = c.ids.filter((id) => found.has(id));
  if (ids.length) return ids.map((id) => AGENTS[id].name).join(", ");
  const named = c.ids.filter((id) => id !== "agents");
  return named.length === 1 ? AGENTS[named[0]].name : `shared folder (${c.ids.length} agents)`;
}
const pre = (opts) => (opts.dryRun ? "[dry-run] " : "");

/** Copy the bundled skill into <root>/find-skills with the given profiles, backing up any old copy. */
function copySkill(root, profiles) {
  const dest = path.join(root, SKILL_NAME);
  if (fs.existsSync(dest)) {
    const backup = backupPath(root);
    fs.mkdirSync(path.dirname(backup), { recursive: true });
    fs.renameSync(dest, backup);
    console.log(`  previous copy moved to ${tilde(backup)}`);
  }
  fs.mkdirSync(root, { recursive: true });
  const keep = new Set(["core.json", ...profiles.map((p) => PROFILES[p].file)]);
  fs.cpSync(SKILL_SRC, dest, {
    recursive: true,
    filter: (src) => {
      const base = path.basename(src);
      if (base === "__pycache__" || base.endsWith(".pyc")) return false;
      if (path.dirname(src) === CATALOG_SRC && base.endsWith(".json")) return keep.has(base);
      return true;
    },
  });
  try { fs.chmodSync(path.join(dest, "scripts", "skillfinder.py"), 0o755); } catch { /* windows */ }
}

function hints(opts, chosenIds) {
  const others = detected().filter((id) => !chosenIds.has(id));
  if (others.length && !opts.detect) {
    console.log(`\nalso found on this machine: ${others.map((id) => AGENTS[id].name).join(", ")}. ` +
                "Add --detect to install for them too.");
  }
  const python = findPython();
  if (!python) {
    console.log("\nwarning: Python 3.9+ not found. The skill's helper script needs it; install Python first.");
  } else if (python !== "python3") {
    console.log(`\nnote: Python is available as '${python}', not 'python3'. Tell the agent to use '${python}'.`);
  }
  const gh = spawnSync("gh", ["auth", "status"], { encoding: "utf8" });
  if (gh.status !== 0 && !process.env.GITHUB_TOKEN && !process.env.GH_TOKEN) {
    console.log("tip: run 'gh auth login' or set GITHUB_TOKEN to avoid GitHub's 60 requests/hour limit.");
  }
}

// ------------------------------------------------------------------ commands

function install(opts) {
  const list = targets(opts);
  // Refuse before touching anything if any target holds someone else's folder.
  for (const t of list) {
    const dest = path.join(t.root, SKILL_NAME);
    if (fs.existsSync(dest) && !isOurSkill(dest)) {
      fail(`${dest} exists but is not find-skills. Move it away first; nothing was changed.`);
    }
  }
  for (const t of list) {
    const dest = path.join(t.root, SKILL_NAME);
    const profiles = resolveProfiles(opts, fs.existsSync(dest) ? installedProfiles(dest) : []);
    console.log(`${pre(opts)}${label(t)}: ${tilde(dest)}`);
    console.log(`  profiles: ${profiles.join(", ")}`);
    if (opts.dryRun) continue;
    copySkill(t.root, profiles);
    console.log(`  installed ${VERSION}`);
  }

  if (opts.auto) {
    if (!list.some((t) => t.ids.includes("kiro"))) console.log("note: --auto only applies to Kiro; skipped.");
    else {
      const target = path.join(opts.workspace || HOME, ".kiro", "steering", "find-skills-auto.md");
      console.log(`${pre(opts)}steering: ${tilde(target)}`);
      if (!opts.dryRun) {
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.copyFileSync(STEERING_SRC, target);
      }
    }
  }

  hints(opts, new Set(list.flatMap((t) => t.ids)));
  if (!isGlobalInstall()) {
    console.log(`tip: run 'npm install -g github:${REPO}' to get the 'find-skills' command (version, update, ...).`);
  }
  if (!opts.dryRun) console.log("\nDone. Start a new agent session (or reload the IDE) so the skill is discovered.");
}

async function version() {
  const global = isGlobalInstall();
  console.log(`find-skills ${VERSION}${global ? "" : "  (running via npx or a clone, not installed as a command)"}`);
  const latest = await latestVersion();
  if (!latest) console.log("latest:  unknown (offline?)");
  else if (compareVersions(latest, VERSION) > 0) console.log(`latest:  ${latest} available. Run: find-skills update`);
  else if (compareVersions(latest, VERSION) < 0) console.log(`latest:  ${latest} (this copy is newer than the latest release)`);
  else console.log(`latest:  ${latest} (up to date)`);

  const copies = installedCopies(process.cwd());
  if (!copies.length) {
    console.log("skill:   not installed for any agent. Run: find-skills --website");
    return;
  }
  console.log("skill:");
  const width = Math.min(40, Math.max(...copies.map((c) => copyLabel(c).length)));
  for (const c of copies) {
    const newest = latest && compareVersions(latest, VERSION) > 0 ? latest : VERSION;
    const flag = compareVersions(newest, c.version) > 0 ? "  (outdated)" : "";
    console.log(`  ${copyLabel(c).slice(0, width).padEnd(width)}  ${c.version.padEnd(8)} ${(c.profiles.join(",") || "-").padEnd(10)} ${tilde(path.join(c.root, SKILL_NAME))}${flag}`);
  }
}

async function update(opts) {
  // 1. Get the newest release first, then let that version update the installed copies.
  if (!process.env.FIND_SKILLS_UPDATED) {
    const latest = await latestVersion();
    if (!latest) console.log("Could not reach GitHub to check for a newer release; updating copies from this version.");
    else if (compareVersions(latest, VERSION) > 0) {
      const passthrough = [opts.force && "--force", opts.dryRun && "--dry-run"].filter(Boolean);
      const env = { ...process.env, FIND_SKILLS_UPDATED: "1" };
      const spec = `github:${REPO}#v${latest}`;
      console.log(`find-skills ${VERSION} -> ${latest}`);
      if (opts.dryRun) {
        console.log(`[dry-run] would ${isGlobalInstall() ? `run: npm install -g ${spec}` : `run: npx ${spec} update`}`);
        return;
      }
      let r;
      if (isGlobalInstall()) {
        r = npmCmd(["install", "-g", spec], { stdio: "inherit", encoding: undefined });
        if (r.status !== 0) fail(`could not update the command. Run it yourself: npm install -g ${spec}`);
        r = spawnSync(process.execPath, [path.join(PKG_ROOT, "bin", "cli.js"), "update", ...passthrough],
                      { stdio: "inherit", env });
      } else {
        r = spawnSync(IS_WIN ? "npx.cmd" : "npx", ["--yes", spec, "update", ...passthrough],
                      { stdio: "inherit", env, shell: IS_WIN });
      }
      process.exit(r.status === null ? 1 : r.status);
    } else if (compareVersions(latest, VERSION) < 0) {
      console.log(`find-skills ${VERSION} is newer than the latest release (${latest}).`);
    } else {
      console.log(`find-skills ${VERSION} is the latest release.`);
    }
  }

  // 2. This process is the newest version: refresh every installed copy that is older.
  const copies = installedCopies(process.cwd());
  if (!copies.length) {
    console.log("The skill is not installed for any agent yet. Run: find-skills --website");
    return;
  }
  let changed = 0;
  for (const c of copies) {
    const dest = path.join(c.root, SKILL_NAME);
    if (!opts.force && compareVersions(c.version, VERSION) >= 0) {
      console.log(`${copyLabel(c)}: ${c.version} up to date (${tilde(dest)})`);
      continue;
    }
    const profiles = resolveProfiles({ ...opts, profiles: [], all: false }, c.profiles);
    console.log(`${pre(opts)}${copyLabel(c)}: ${c.version} -> ${VERSION} (${tilde(dest)}), profiles: ${profiles.join(", ")}`);
    if (opts.dryRun) continue;
    copySkill(c.root, profiles);
    changed++;
  }
  for (const base of new Set([HOME, process.cwd()])) {
    const steering = path.join(base, ".kiro", "steering", "find-skills-auto.md");
    if (fs.existsSync(steering) && !opts.dryRun) fs.copyFileSync(STEERING_SRC, steering);
  }
  if (changed) console.log("\nDone. Start a new agent session (or reload the IDE) to load the new version.");
}

function uninstall(opts) {
  const list = targets(opts);
  for (const t of list) {
    const dest = path.join(t.root, SKILL_NAME);
    if (!fs.existsSync(dest)) { console.log(`${label(t)}: not installed (${tilde(dest)})`); continue; }
    if (!isOurSkill(dest)) { console.log(`${label(t)}: ${dest} is not find-skills; left alone`); continue; }
    console.log(`${pre(opts)}${label(t)}: removing ${tilde(dest)}`);
    if (!opts.dryRun) fs.rmSync(dest, { recursive: true, force: true });
  }
  const steering = path.join(opts.workspace || HOME, ".kiro", "steering", "find-skills-auto.md");
  if (list.some((t) => t.ids.includes("kiro")) && fs.existsSync(steering)) {
    console.log(`${pre(opts)}removing ${tilde(steering)}`);
    if (!opts.dryRun) fs.rmSync(steering);
  }
  if (isGlobalInstall()) console.log("The 'find-skills' command is still installed. Remove it with: npm uninstall -g find-skills");
}

function listProfiles() {
  for (const [name, p] of Object.entries(PROFILES)) {
    const tag = p.status === "draft" ? "coming soon" : "available";
    console.log(`${name.padEnd(10)} ${tag.padEnd(12)} ${p.title}`);
    console.log(`${"".padEnd(23)}${p.domains.join(", ")}`);
  }
}

function listAgents() {
  const found = new Set(detected());
  console.log(`${"id".padEnd(13)} ${"agent".padEnd(26)} ${"project folder".padEnd(18)} global folder`);
  for (const a of Object.values(AGENTS)) {
    const mark = found.has(a.id) ? " *" : "";
    console.log(`${a.id.padEnd(13)} ${a.name.slice(0, 26).padEnd(26)} ${a.project.padEnd(18)} ${tilde(a.globalDir)}${mark}`);
  }
  console.log("\n* found on this machine");
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  switch (opts.cmd) {
    case "help": return help();
    case "version": return version();
    case "update": return update(opts);
    case "list": return listProfiles();
    case "agents": return listAgents();
    case "uninstall": return uninstall(opts);
    default: return install(opts);
  }
}

main().catch((err) => fail(err && err.message ? err.message : String(err)));

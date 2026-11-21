#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PKG_ROOT = path.resolve(__dirname, "..");
const SKILL_SRC = path.join(PKG_ROOT, "skills", "find-skills");
const CATALOG_SRC = path.join(SKILL_SRC, "references", "catalog");
const AGENTS_FILE = path.join(SKILL_SRC, "references", "agents.json");
const STEERING_SRC = path.join(PKG_ROOT, "steering", "find-skills-auto.md");
const SKILL_NAME = "find-skills";
const VERSION = require(path.join(PKG_ROOT, "package.json")).version;
const HOME = os.homedir();
const CONFIG_HOME = process.env.XDG_CONFIG_HOME || path.join(HOME, ".config");

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

// ------------------------------------------------------------------ cli

function help() {
  const rows = Object.entries(PROFILES)
    .map(([n, p]) => `  --${n.padEnd(12)} ${p.title}${p.status === "draft" ? "  (coming soon)" : ""}`)
    .join("\n");
  console.log(`find-skills ${VERSION}: skill finder for Kiro and other Agent Skills tools

Usage:
  npx find-skills [profiles] [options]
  npx find-skills uninstall [options]
  npx find-skills list          profiles
  npx find-skills agents        supported agents and where skills go

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
  --dry-run           print what would happen, change nothing
  -h, --help          this help
  -v, --version       print version

Examples:
  npx find-skills --website --auto
  npx find-skills --website --agent codex --agent opencode
  npx find-skills --website --detect
  npx find-skills --website --workspace --agent claude`);
}

function fail(msg) {
  console.error(`find-skills: ${msg}`);
  process.exit(1);
}

function parseArgs(argv) {
  const opts = { cmd: "install", profiles: [], agents: [], detect: false, workspace: null,
                 only: false, auto: false, dryRun: false, all: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => (argv[i + 1] && !argv[i + 1].startsWith("-") ? argv[++i] : null);
    if (a === "-h" || a === "--help") { help(); process.exit(0); }
    else if (a === "-v" || a === "--version") { console.log(VERSION); process.exit(0); }
    else if (a === "install" || a === "add") opts.cmd = "install";
    else if (a === "uninstall" || a === "remove") opts.cmd = "uninstall";
    else if (a === "list" || a === "--list") opts.cmd = "list";
    else if (a === "agents") opts.cmd = "agents";
    else if (a === "--all") opts.all = true;
    else if (a === "--only") opts.only = true;
    else if (a === "--auto") opts.auto = true;
    else if (a === "--detect") opts.detect = true;
    else if (a === "--dry-run") opts.dryRun = true;
    else if (a === "--global") opts.workspace = null;
    else if (a === "--workspace") opts.workspace = path.resolve(next() || ".");
    else if (a === "--agent" || a.startsWith("--agent=")) {
      const v = a.includes("=") ? a.split("=")[1] : next();
      if (!v) fail("--agent needs a value. Run `npx find-skills agents` for the list.");
      for (const name of v.split(",").map((s) => s.trim()).filter(Boolean)) {
        const id = AGENT_ALIAS[name.toLowerCase()];
        if (!id) fail(`unknown agent '${name}'. Run \`npx find-skills agents\` for the list.`);
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
    const root = opts.workspace ? path.join(opts.workspace, a.project) : a.globalDir;
    const key = path.resolve(root);
    if (!byDir.has(key)) byDir.set(key, { root: key, ids: [] });
    byDir.get(key).ids.push(id);
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
    .map((f) => path.basename(f, ".json")).filter((p) => PROFILES[p]);
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
  let chosen;
  if (opts.all) chosen = stable();
  else if (opts.profiles.length) chosen = opts.only ? opts.profiles : [...new Set([...existing, ...opts.profiles])];
  else chosen = existing.length ? existing : stable();
  return [...new Set(chosen)].sort();
}

const label = (t) => t.ids.map((id) => AGENTS[id].name).join(", ");
const pre = (opts) => (opts.dryRun ? "[dry-run] " : "");

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
    const exists = fs.existsSync(dest);
    const profiles = resolveProfiles(opts, exists ? installedProfiles(dest) : []);
    console.log(`${pre(opts)}${label(t)}: ${dest}`);
    console.log(`  profiles: ${profiles.join(", ")}`);
    if (opts.dryRun) continue;

    if (exists) {
      const backup = backupPath(t.root);
      fs.mkdirSync(path.dirname(backup), { recursive: true });
      fs.renameSync(dest, backup);
      console.log(`  previous copy moved to ${backup}`);
    }
    fs.mkdirSync(t.root, { recursive: true });
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
    console.log("  installed");
  }

  if (opts.auto) {
    if (!list.some((t) => t.ids.includes("kiro"))) console.log("note: --auto only applies to Kiro; skipped.");
    else {
      const target = path.join(opts.workspace || HOME, ".kiro", "steering", "find-skills-auto.md");
      console.log(`${pre(opts)}steering: ${target}`);
      if (!opts.dryRun) {
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.copyFileSync(STEERING_SRC, target);
      }
    }
  }

  const chosen = new Set(list.flatMap((t) => t.ids));
  const others = detected().filter((id) => !chosen.has(id));
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
  if (!opts.dryRun) console.log("\nDone. Start a new agent session (or reload the IDE) so the skill is discovered.");
}

function uninstall(opts) {
  const list = targets(opts);
  for (const t of list) {
    const dest = path.join(t.root, SKILL_NAME);
    if (!fs.existsSync(dest)) { console.log(`${label(t)}: not installed (${dest})`); continue; }
    if (!isOurSkill(dest)) { console.log(`${label(t)}: ${dest} is not find-skills; left alone`); continue; }
    console.log(`${pre(opts)}${label(t)}: removing ${dest}`);
    if (!opts.dryRun) fs.rmSync(dest, { recursive: true, force: true });
  }
  const steering = path.join(opts.workspace || HOME, ".kiro", "steering", "find-skills-auto.md");
  if (list.some((t) => t.ids.includes("kiro")) && fs.existsSync(steering)) {
    console.log(`${pre(opts)}removing ${steering}`);
    if (!opts.dryRun) fs.rmSync(steering);
  }
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
  const tilde = (p) => (p.startsWith(HOME) ? "~" + p.slice(HOME.length) : p);
  console.log(`${"id".padEnd(13)} ${"agent".padEnd(26)} ${"project folder".padEnd(18)} global folder`);
  for (const a of Object.values(AGENTS)) {
    const mark = found.has(a.id) ? " *" : "";
    console.log(`${a.id.padEnd(13)} ${a.name.slice(0, 26).padEnd(26)} ${a.project.padEnd(18)} ${tilde(a.globalDir)}${mark}`);
  }
  console.log("\n* found on this machine");
}

const opts = parseArgs(process.argv.slice(2));
if (opts.cmd === "list") listProfiles();
else if (opts.cmd === "agents") listAgents();
else if (opts.cmd === "uninstall") uninstall(opts);
else install(opts);

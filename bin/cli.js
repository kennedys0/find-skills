#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PKG_ROOT = path.resolve(__dirname, "..");
const SKILL_SRC = path.join(PKG_ROOT, "skills", "find-skills");
const CATALOG_SRC = path.join(SKILL_SRC, "references", "catalog");
const STEERING_SRC = path.join(PKG_ROOT, "steering", "find-skills-auto.md");
const SKILL_NAME = "find-skills";
const AGENT_DIRS = { kiro: ".kiro", claude: ".claude", agents: ".agents" };
const VERSION = require(path.join(PKG_ROOT, "package.json")).version;

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

const PROFILES = readProfiles();
const stable = () => Object.keys(PROFILES).filter((p) => PROFILES[p].status !== "draft");

function help() {
  const rows = Object.entries(PROFILES)
    .map(([n, p]) => `  --${n.padEnd(12)} ${p.title}${p.status === "draft" ? "  (coming soon)" : ""}`)
    .join("\n");
  console.log(`find-skills ${VERSION}: skill finder for Kiro and other Agent Skills tools

Usage:
  npx find-skills [profiles] [options]
  npx find-skills uninstall [options]
  npx find-skills list

Profiles:
${rows}
  --all          every stable profile
  (no profile)   keeps the profiles of an existing install, or installs all stable ones

Options:
  --workspace [dir]   install into <dir>/.kiro/skills (default dir: current folder)
                      without it, installs globally into ~/.kiro/skills
  --agent <name>      kiro (default), claude or agents; repeat for several
  --only              replace the installed profiles instead of adding to them
  --auto              add an always-on Kiro steering file so it triggers on new projects
  --dry-run           print what would happen, change nothing
  -h, --help          this help
  -v, --version       print version

Examples:
  npx find-skills --website --auto
  npx find-skills --website --workspace
  npx find-skills --website --agent kiro --agent claude`);
}

function fail(msg) {
  console.error(`find-skills: ${msg}`);
  process.exit(1);
}

function parseArgs(argv) {
  const opts = { cmd: "install", profiles: [], agents: [], workspace: null, only: false,
                 auto: false, dryRun: false, all: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => (argv[i + 1] && !argv[i + 1].startsWith("-") ? argv[++i] : null);
    if (a === "-h" || a === "--help") { help(); process.exit(0); }
    else if (a === "-v" || a === "--version") { console.log(VERSION); process.exit(0); }
    else if (a === "install" || a === "add") opts.cmd = "install";
    else if (a === "uninstall" || a === "remove") opts.cmd = "uninstall";
    else if (a === "list" || a === "--list") opts.cmd = "list";
    else if (a === "--all") opts.all = true;
    else if (a === "--only") opts.only = true;
    else if (a === "--auto") opts.auto = true;
    else if (a === "--dry-run") opts.dryRun = true;
    else if (a === "--global") opts.workspace = null;
    else if (a === "--workspace") opts.workspace = path.resolve(next() || ".");
    else if (a === "--agent") {
      const v = next();
      if (!v || !AGENT_DIRS[v]) fail(`--agent needs one of: ${Object.keys(AGENT_DIRS).join(", ")}`);
      opts.agents.push(v);
    } else if (a.startsWith("--") || PROFILES[a]) {
      const name = a.replace(/^--/, "");
      if (!PROFILES[name]) fail(`unknown option or profile '${a}'. Run with --help.`);
      opts.profiles.push(name);
    } else fail(`unexpected argument '${a}'. Run with --help.`);
  }
  if (!opts.agents.length) opts.agents = ["kiro"];
  return opts;
}

function skillsRoot(agent, workspace) {
  return path.join(workspace || os.homedir(), AGENT_DIRS[agent], "skills");
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
  const dir = path.join(root, "..", "skills-backup");
  const base = `${SKILL_NAME}-${new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15)}`;
  let candidate = path.join(dir, base);
  for (let n = 2; fs.existsSync(candidate); n++) candidate = path.join(dir, `${base}-${n}`);
  return path.normalize(candidate);
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

function install(opts) {
  const python = findPython();
  for (const agent of opts.agents) {
    const root = skillsRoot(agent, opts.workspace);
    const dest = path.join(root, SKILL_NAME);
    const exists = fs.existsSync(dest);
    if (exists && !isOurSkill(dest)) {
      fail(`${dest} exists but is not find-skills. Move it away first; nothing was changed.`);
    }
    const profiles = resolveProfiles(opts, exists ? installedProfiles(dest) : []);
    console.log(`${opts.dryRun ? "[dry-run] " : ""}${agent}: ${dest}`);
    console.log(`  profiles: ${profiles.join(", ")}`);
    if (opts.dryRun) continue;

    if (exists) {
      const backup = backupPath(root);
      fs.mkdirSync(path.dirname(backup), { recursive: true });
      fs.renameSync(dest, backup);
      console.log(`  previous copy moved to ${backup}`);
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
    console.log("  installed");
  }

  if (opts.auto) {
    if (!opts.agents.includes("kiro")) console.log("note: --auto only applies to Kiro; skipped.");
    else {
      const target = path.join(opts.workspace || os.homedir(), ".kiro", "steering", "find-skills-auto.md");
      console.log(`${opts.dryRun ? "[dry-run] " : ""}steering: ${target}`);
      if (!opts.dryRun) {
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.copyFileSync(STEERING_SRC, target);
      }
    }
  }

  if (!python) {
    console.log("\nwarning: Python 3.9+ not found. The skill's helper script needs it; install Python first.");
  } else if (python !== "python3") {
    console.log(`\nnote: Python is available as '${python}', not 'python3'. Tell the agent to use '${python}'.`);
  }
  const gh = spawnSync("gh", ["auth", "status"], { encoding: "utf8" });
  if (gh.status !== 0 && !process.env.GITHUB_TOKEN && !process.env.GH_TOKEN) {
    console.log("tip: run 'gh auth login' or set GITHUB_TOKEN to avoid GitHub's 60 requests/hour limit.");
  }
  if (!opts.dryRun) console.log("\nDone. Start a new session (or reload the IDE) so the skill is discovered.");
}

function uninstall(opts) {
  for (const agent of opts.agents) {
    const dest = path.join(skillsRoot(agent, opts.workspace), SKILL_NAME);
    if (!fs.existsSync(dest)) { console.log(`${agent}: not installed (${dest})`); continue; }
    if (!isOurSkill(dest)) { console.log(`${agent}: ${dest} is not find-skills; left alone`); continue; }
    console.log(`${opts.dryRun ? "[dry-run] " : ""}${agent}: removing ${dest}`);
    if (!opts.dryRun) fs.rmSync(dest, { recursive: true, force: true });
  }
  const steering = path.join(opts.workspace || os.homedir(), ".kiro", "steering", "find-skills-auto.md");
  if (opts.agents.includes("kiro") && fs.existsSync(steering)) {
    console.log(`${opts.dryRun ? "[dry-run] " : ""}removing ${steering}`);
    if (!opts.dryRun) fs.rmSync(steering);
  }
}

function list() {
  for (const [name, p] of Object.entries(PROFILES)) {
    const tag = p.status === "draft" ? "coming soon" : "available";
    console.log(`${name.padEnd(10)} ${tag.padEnd(12)} ${p.title}`);
    console.log(`${"".padEnd(23)}${p.domains.join(", ")}`);
  }
}

const opts = parseArgs(process.argv.slice(2));
if (opts.cmd === "list") list();
else if (opts.cmd === "uninstall") uninstall(opts);
else install(opts);

// Tests for bin/cli.js argument parsing and version comparison (node:test, no dependencies).
const test = require("node:test");
const assert = require("node:assert");
const cli = require("../bin/cli.js");

test("parseArgs: profile and comma-separated agents", () => {
  const o = cli.parseArgs(["--website", "--agent", "codex,pi"]);
  assert.deepEqual(o.profiles, ["website"]);
  assert.deepEqual(o.agents, ["codex", "pi"]);
  assert.equal(o.cmd, "install");
});

test("parseArgs: repeated --agent flags accumulate", () => {
  const o = cli.parseArgs(["--agent", "codex", "--agent", "pi"]);
  assert.deepEqual(o.agents, ["codex", "pi"]);
});

test("parseArgs: --agent=value form", () => {
  const o = cli.parseArgs(["--agent=codex"]);
  assert.deepEqual(o.agents, ["codex"]);
});

test("parseArgs: agent aliases resolve to ids", () => {
  const o = cli.parseArgs(["--agent", "claude-code"]);
  assert.equal(o.agents[0], "claude");
});

test("parseArgs: single-dash long options are accepted", () => {
  const o = cli.parseArgs(["-website", "-dry-run"]);
  assert.deepEqual(o.profiles, ["website"]);
  assert.equal(o.dryRun, true);
});

test("parseArgs: subcommands", () => {
  assert.equal(cli.parseArgs(["update"]).cmd, "update");
  assert.equal(cli.parseArgs(["upgrade"]).cmd, "update");
  assert.equal(cli.parseArgs(["list"]).cmd, "list");
  assert.equal(cli.parseArgs(["agents"]).cmd, "agents");
  assert.equal(cli.parseArgs(["uninstall"]).cmd, "uninstall");
  assert.equal(cli.parseArgs(["--help"]).cmd, "help");
  assert.equal(cli.parseArgs(["-v"]).cmd, "version");
});

test("parseArgs: --workspace with a value", () => {
  const o = cli.parseArgs(["--workspace", "/tmp/try"]);
  assert.equal(o.workspace, "/tmp/try");
});

test("parseArgs: --workspace defaults to the current folder", () => {
  const o = cli.parseArgs(["--workspace"]);
  assert.equal(o.workspace, process.cwd());
});

// fail() in cli.js prints the reason to stderr, then calls process.exit. Capture both.
function expectFail(fn, pattern) {
  const origExit = process.exit;
  const origErr = console.error;
  let printed = "";
  console.error = (msg) => { printed += `${msg}\n`; };
  process.exit = (code) => { throw new Error(printed.trim() || `exit ${code}`); };
  try {
    assert.throws(fn, pattern);
  } finally {
    process.exit = origExit;
    console.error = origErr;
  }
}

test("parseArgs: unknown agent fails", () => {
  expectFail(() => cli.parseArgs(["--agent", "nope"]), /unknown agent/);
});

test("parseArgs: unknown option fails", () => {
  expectFail(() => cli.parseArgs(["--nope"]), /unknown option or profile/);
});

test("compareVersions: semantic ordering", () => {
  assert.ok(cli.compareVersions("1.4.1", "1.4.0") > 0);
  assert.ok(cli.compareVersions("1.4.0", "1.4.1") < 0);
  assert.equal(cli.compareVersions("1.4.1", "1.4.1"), 0);
  assert.ok(cli.compareVersions("2.0.0", "1.9.9") > 0);
});

test("compareVersions: pre-release sorts before its release", () => {
  assert.ok(cli.compareVersions("1.3.0-beta.1", "1.3.0") < 0);
  assert.ok(cli.compareVersions("1.3.0", "1.3.0-beta.1") > 0);
});

test("compareVersions: unknown version sorts first", () => {
  assert.ok(cli.compareVersions("garbage", "1.0.0") < 0);
  assert.ok(cli.compareVersions("1.0.0", "garbage") > 0);
  assert.equal(cli.compareVersions("garbage", "also-garbage"), 0);
});

test("resolveProfiles: adds to existing profiles by default", () => {
  const chosen = cli.resolveProfiles({ profiles: ["website"], all: false, only: false }, ["website"]);
  assert.deepEqual(chosen, ["website"]);
});

test("resolveProfiles: --only replaces profiles", () => {
  const chosen = cli.resolveProfiles({ profiles: ["website"], all: false, only: true }, ["other-stable"]);
  assert.deepEqual(chosen, ["website"]);
});

test("resolveProfiles: no flags keeps existing profiles", () => {
  const chosen = cli.resolveProfiles({ profiles: [], all: false, only: false }, ["website"]);
  assert.deepEqual(chosen, ["website"]);
});

test("resolveProfiles: no flags and no existing installs all stable profiles", () => {
  const chosen = cli.resolveProfiles({ profiles: [], all: false, only: false }, []);
  assert.ok(chosen.includes("website"));
  assert.ok(!chosen.includes("game")); // draft
});

test("resolveProfiles: draft profile fails", () => {
  expectFail(() => cli.resolveProfiles({ profiles: ["game"], all: false, only: false }, []), /coming soon/);
});

test("targets: agents sharing a folder get one install", () => {
  const list = cli.targets({ agents: ["codex", "pi"], detect: false, workspace: null });
  assert.equal(list.length, 1);
  assert.deepEqual(list[0].ids.sort(), ["codex", "pi"]);
});

test("targets: distinct folders per agent", () => {
  const list = cli.targets({ agents: ["kiro", "claude"], detect: false, workspace: null });
  assert.equal(list.length, 2);
});

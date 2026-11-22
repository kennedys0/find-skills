# find-skills

A skill finder for Kiro and other agents that use the Agent Skills format (`SKILL.md`). When you start a project, it finds the best skills for it, checks that they are good and safe, asks before installing, and makes sure the agent actually uses them.

It currently focuses on **websites and web apps**. More profiles, such as games, are planned.

## What it does

When you start a project, or the work moves into a new area, the agent:

1. **Checks the anti-slop baseline.** Skills that stop generic AI-looking UI, code and writing are always proposed first if they are missing.
2. **Looks at local skills first.** It searches `.kiro/skills`, `~/.kiro/skills`, `.claude/skills`, `~/.agents/skills` and others before going online.
3. **Searches for the gaps.** It uses a curated catalog, then skills.sh and GitHub, ranked by stars, installs, license and recent activity.
4. **Vets every candidate.** It downloads the skill to a staging folder at one commit, scans every file, and reads the skill itself before recommending it.
5. **Asks you.** For example: *"May I install these skills for anti-slop?"* It replies in your language and installs nothing without a clear yes.
6. **Installs what you approve,** pinned to the exact commit it reviewed.
7. **Uses every approved skill.** It reads them right away, maps each one to part of the task, applies them while working, and before delivery reports per skill what it did or why the skill did not apply.

### Anti-slop baseline

| Kind | Primary | Alternatives |
|---|---|---|
| UI | `miqdadbadjuber/anti-slop` → `antislop`, `antislop-ui`, `antislop-layoutmobile` | `leonxlnx/taste-skill` → `design-taste-frontend` |
| Code | `cursor/plugins` → `deslop` | `antislop-code` |
| Writing | `blader/humanizer` → `humanizer` | `hardikpandya/stop-slop`, `antislop-copywriting` |

### Profiles

| Profile | Status | Domains |
|---|---|---|
| `website` | available | ui-ux, frontend, performance-a11y, backend, security, testing, seo-marketing, deploy, workflow |
| `game` | coming soon | game-godot, game-unity, game-design, art-3d-character |

Topics outside the installed profiles are still searched on skills.sh and GitHub, without a curated list behind them.

### Safety checks

- **Quality score (0–100):** stars, installs, last push, license, and trusted owners such as official vendors. Forks, archived repos and clone patterns lose points.
- **Clone detection:** many clone repos have a few dozen stars but tens of thousands of reported installs (for example `101-skills/superpowers`: 31 stars, 67k installs). These are rejected automatically.
- **Static scan:** `curl | sh`, PowerShell download cradles, reads of `~/.ssh`, `.npmrc` and other credentials, tokens sent over the network, prompt injection (English and Indonesian), hidden Unicode, multi-line command splitting, bundled binaries, `rm -rf /`, dynamic exec, and network calls in scripts.
- **Verdicts:** `PASS`; `REVIEW` (the agent explains the flags and you decide); `REJECT` (never installed unless you insist).

The scan matches patterns, so the agent must still read the SKILL.md and every script itself.

### Approved skills stay in use

Every approved skill is listed in `.kiro/steering/find-skills-active.md` (or `~/.kiro/steering/` for global installs). That steering file uses `inclusion: always`, so every later session is told to read and apply the listed skills without asking again.

## Install

Requirements: Node 18+ for the installer, Python 3.9+ for the helper the agent runs, and network access. Run `gh auth login` or set `GITHUB_TOKEN` to avoid GitHub's limit of 60 requests per hour.

```bash
npx github:kennedys0/find-skills --website --auto
```

This installs the skill globally for Kiro into `~/.kiro/skills/find-skills` and adds an always-on steering file, so it triggers on every new project. For other agents, add `--agent` (see [Supported agents](#supported-agents)). Start a new session or reload the IDE afterwards.

More examples:

```bash
npx github:kennedys0/find-skills#v1.3.0 --website                    # pin a version
npx github:kennedys0/find-skills --website --agent codex             # Codex CLI
npx github:kennedys0/find-skills --website --agent antigravity,opencode,pi
npx github:kennedys0/find-skills --website --detect                  # every agent found on this machine
npx github:kennedys0/find-skills --website --workspace               # this project only
npx github:kennedys0/find-skills agents                              # supported agents and folders
npx github:kennedys0/find-skills list                                # available profiles
npx github:kennedys0/find-skills uninstall --agent codex
```

| Option | Meaning |
|---|---|
| `--website` | install the website profile |
| `--all` | every available profile |
| `--agent <id>` | target agent (default `kiro`); repeat or comma-separate |
| `--detect` | also install for every agent found on this machine |
| `--workspace [dir]` | install into the project at `<dir>` only; without it, installs globally |
| `--only` | replace the installed profiles; by default new profiles are added |
| `--auto` | add the always-on Kiro steering file so the skill triggers on new projects |
| `--dry-run` | print the plan without changing anything |

### Supported agents

| `--agent` | Agent | Global folder |
|---|---|---|
| `kiro` | Kiro IDE and CLI | `~/.kiro/skills` |
| `claude` | Claude Code | `~/.claude/skills` |
| `codex` | Codex CLI | `~/.agents/skills` |
| `antigravity` | Antigravity IDE and CLI (`agy`) | `~/.gemini/config/skills` |
| `gemini` | Gemini CLI | `~/.gemini/skills` |
| `opencode` | OpenCode | `~/.config/opencode/skills` |
| `pi` | Pi | `~/.agents/skills` |
| `cursor` | Cursor | `~/.cursor/skills` |
| `copilot` | GitHub Copilot | `~/.copilot/skills` |
| `windsurf` | Windsurf | `~/.codeium/windsurf/skills` |

Also supported: `cline`, `kimi`, `amp`, `droid`, `goose`, `qwen`, `qoder`, `trae`, `roo`, `kilo`, `junie`, `augment`, `continue`, `crush`, `openhands`, `warp`, `zed`, `hermes`, `vibe`, `devin`, `grok`, and `agents` (the shared `.agents/skills` folder). Run `npx github:kennedys0/find-skills agents` for every folder.

- Agents that share a folder get one copy. Codex, Pi, Cline, Kimi, Warp and Zed all read `~/.agents/skills`.
- In a project (`--workspace`), most agents read `.agents/skills`. Kiro, Claude Code, Windsurf and a few others use their own folder.
- The installer never uses `--detect` on its own. It prints which other agents it found so you can add them.
- `--auto` and the active-skills steering are Kiro features. Other agents find the skill through its description, or when you invoke it by name.

### The `find-skills` command

Install the command once to manage the skill from any terminal:

```bash
npm install -g github:kennedys0/find-skills
```

| Command | What it does |
|---|---|
| `find-skills --website --auto` | install the skill (same options as above) |
| `find-skills --version` | version of the command, the latest release, and every installed copy per agent |
| `find-skills update` | update the command to the latest release, then every installed copy, keeping their profiles |
| `find-skills update --force` | reinstall every copy even when it is already current |
| `find-skills agents` | supported agents and their folders (`*` = found on this machine) |
| `find-skills list` | profiles |
| `find-skills uninstall --agent codex` | remove the skill for an agent |
| `npm uninstall -g find-skills` | remove the command |

The command is `find-skills` with a hyphen. Typed as `find skills`, the terminal runs the system `find` tool. Every command also works without a global install: `npx github:kennedys0/find-skills update`.

- `update` checks for new copies in every agent's global folder and in the current project. Old copies are moved to `skills-backup/`.
- Use `npx`, not `npm install <pkg> --website`. `npm install` does not pass flags like `--website` to the package.
- Without `--auto`, the skill still activates when a request matches its description ("build a website", "find a skill for auth"), or when you type `/find-skills`.
- Without npm: in Kiro IDE open **Agent Steering & Skills → + → Import skill from a repository URL** and paste `https://github.com/kennedys0/find-skills/tree/main/skills/find-skills`. This copies every profile and skips the `--auto` steering file.

## Contributing

Contributions are welcome. The most useful ones are:
- **Better catalog entries:** a skill that beats one already listed, or a wrong or outdated entry.
- **New profiles:** for example finishing `game`, or adding `mobile`.
- **Better safety rules:** a scan rule that misses something, or one that raises false alarms.
- **Bug reports.**

For a quick suggestion, [open an issue](https://github.com/kennedys0/find-skills/issues) with the repo link and why it is better.

### Setup

```bash
git clone https://github.com/kennedys0/find-skills.git
cd find-skills
SF="python3 skills/find-skills/scripts/skillfinder.py"

$SF catalog                              # domains in the profiles
FIND_SKILLS_DRAFTS=1 $SF catalog         # include draft profiles
$SF search "astro"                       # ranked search
$SF list owner/repo                      # skills inside a repo
$SF vet owner/repo skill-name            # scan and score one skill
node bin/cli.js --website --workspace /tmp/try --dry-run   # try the installer
```

The helper uses only the Python standard library and the installer has no npm dependencies. Please keep it that way.

### Project layout

```
bin/cli.js                         npx installer
skills/find-skills/
├── SKILL.md                       workflow the agent follows
├── scripts/skillfinder.py         helper: local, baseline, catalog, search, list, vet, install, verify, use, unuse, active
└── references/
    ├── catalog/core.json          anti-slop baseline, trusted owners, clone detection
    ├── catalog/website.json       website profile
    ├── catalog/game.json          game profile (draft)
    ├── agents.json                supported agents and their skills folders
    └── vetting.md                 manual review checklist
steering/find-skills-auto.md       optional always-on trigger
.github/workflows/release.yml      automatic releases
.github/workflows/ci.yml           checks and tests on every pull request
.github/workflows/catalog-revet.yml weekly re-vet of every catalog entry; opens an issue on regressions
.github/scripts/revet_catalog.py   the re-vet script the workflow runs
tests/                              unit tests (Python unittest + node:test), run by CI on every pull request
```

### Adding a catalog entry

Each entry in a profile's `domains` looks like this:

```json
{"source": "owner/repo", "skills": ["skill-name"], "why": "One sentence with facts: owner, stars, license, what it covers."}
```

An entry is accepted when:
1. `$SF list owner/repo` shows every skill name you listed.
2. `$SF vet owner/repo skill-name` gives `PASS`, or gives `REVIEW` and your PR explains every flag.
3. You have read the SKILL.md and its scripts, and the instructions are current for the stack.
4. It is the original repo, not a copy or clone. Prefer the official vendor of the tool when one exists.
5. The `why` field states facts, not praise.

### Adding a profile

1. Create `skills/find-skills/references/catalog/<name>.json` in the same shape as `website.json`: `profile`, `title`, `status`, `baseline_kinds`, `detect`, `domains`.
2. Keep `"status": "draft"` while you work. The installer refuses draft profiles and the helper ignores them unless `FIND_SKILLS_DRAFTS=1`.
3. Once every entry meets the rules above, set `"status": "stable"`.

The installer creates the `--<name>` flag from the file name, so `bin/cli.js` needs no change.

### Adding an agent

Add an entry to `skills/find-skills/references/agents.json`:

```json
"myagent": {"name": "My Agent", "project": ".myagent/skills", "global": "~/.myagent/skills", "detect": ["~/.myagent"], "aliases": ["my-agent"]}
```

`~` is the home folder and `{config}` is `$XDG_CONFIG_HOME` (default `~/.config`). `detect` lists folders that exist only when the agent is installed. Link the agent's documentation for its skills folder in the pull request. The installer and the helper both read this file, so no code change is needed.

### Before opening a pull request

Run the same checks as the release workflow:

```bash
python3 -m py_compile skills/find-skills/scripts/skillfinder.py
python3 -m unittest discover -s tests
node --check bin/cli.js
node --test
for f in skills/find-skills/references/*.json skills/find-skills/references/catalog/*.json; do python3 -m json.tool "$f" >/dev/null || echo "bad: $f"; done
node bin/cli.js list
```

- Keep each pull request to one topic.
- Do not bump the version; the maintainer does that when releasing.
- Contributions are released under the project's MIT license.

### Releasing (maintainers)

Bump `version` in `package.json` and `metadata.version` in `skills/find-skills/SKILL.md` to the same value, then push to `main`. The release workflow checks the versions and the package, then creates the `vX.Y.Z` tag and a GitHub release with notes generated from the commits. A version such as `1.3.0-beta.1` becomes a pre-release.

# find-skills

A skill finder for Kiro and other agents that use the Agent Skills format (`SKILL.md`). It currently focuses on **websites and web apps**. More profiles, such as games, are planned.

When you start a project, the agent:

1. Checks whether **anti-slop** skills for UI, code and writing are installed. Any that are missing go to the top of its proposal.
2. Looks for matching skills that are already installed (`.kiro/skills`, `~/.kiro/skills`, `.claude/skills`, `~/.agents/skills` and others).
3. Fills the gaps from a curated catalog, then from skills.sh and GitHub, ranked by stars, installs, license and recent activity.
4. Downloads each candidate to a staging folder, scans every file, and reads the skill itself.
5. Asks you first, for example: *"May I install these skills for anti-slop?"* It replies in your language.
6. Installs only what you approve, pinned to the commit it reviewed.
7. Uses every approved skill. It reads them right away, maps each one to part of the task, applies them while working, and reports per skill before delivery what it did or why the skill did not apply.

## Approved skills stay in use

Approved skills, whether newly installed or already local, are listed in `.kiro/steering/find-skills-active.md`, or `~/.kiro/steering/` for global installs. That steering file uses `inclusion: always`, so every later session is told to read and apply them without asking again.

```bash
SF="python3 ~/.kiro/skills/find-skills/scripts/skillfinder.py"
$SF active                      # show the list
$SF use antislop antislop-ui    # add skills that were already installed
$SF unuse stop-slop             # stop applying a skill (it stays installed)
```

## Install

From GitHub:

```bash
npx github:kennedys0/find-skills --website --auto          # global + auto-trigger on new projects (recommended)
npx github:kennedys0/find-skills#v1.2.0 --website          # pin a specific version
npm install -g github:kennedys0/find-skills && find-skills --website
```

Once the package is published to npm, the shorter form works too:

```bash
npx find-skills --website --auto
npx find-skills --website --workspace                      # this project only
npx find-skills --website --agent kiro --agent claude      # Kiro + Claude Code
npx find-skills list                                       # show available profiles
npx find-skills uninstall
```

Use `npx` rather than `npm install <pkg> --website`: `npm install` does not pass flags like `--website` to the package.

Without npm: in Kiro IDE open **Agent Steering & Skills → + → Import skill from a repository URL** and paste `https://github.com/kennedys0/find-skills/tree/main/skills/find-skills`. This copies every profile and does not install the `--auto` steering file.

| Option | Meaning |
|---|---|
| `--website` | website profile: ui-ux, frontend, performance-a11y, backend, security, testing, seo-marketing, deploy, workflow |
| `--game` | *coming soon*, cannot be installed yet |
| `--all` | every stable profile |
| `--workspace [dir]` | install into `<dir>/.kiro/skills` only; without it, installs globally into `~/.kiro/skills` |
| `--agent kiro\|claude\|agents` | target agent; repeat for several (default `kiro`) |
| `--only` | replace the installed profiles; by default new profiles are **added** to existing ones |
| `--auto` | add the `find-skills-auto.md` steering file (`always` mode) so it triggers on every new project |
| `--dry-run` | print the plan without changing anything |

Running the installer again without a profile updates the skill and keeps the same profiles. The previous copy is moved to `skills-backup/`.

Without `--auto`, the skill still activates when your request matches its description ("build a website", "landing page", "find a skill for auth"), and you can call it directly with `/find-skills`.

**Requirements:** Node 18+ for the installer, Python 3.9+ for the helper script the agent runs, and network access. Run `gh auth login` or set `GITHUB_TOKEN` to avoid GitHub's 60 requests/hour anonymous limit.

## Anti-slop (always proposed)

| Kind | Primary | Alternatives |
|---|---|---|
| UI | `miqdadbadjuber/anti-slop` → `antislop`, `antislop-ui`, `antislop-layoutmobile` | `leonxlnx/taste-skill` → `design-taste-frontend` |
| Code | `cursor/plugins` → `deslop` | `antislop-code` |
| Writing | `blader/humanizer` → `humanizer` | `hardikpandya/stop-slop`, `antislop-copywriting` |

All of these passed `vet` on 2026-11-21. `taste-skill` gets REVIEW because it is large (about 37 MB) and runs headless Chrome locally.

## Using the helper directly

```bash
SF="python3 ~/.kiro/skills/find-skills/scripts/skillfinder.py"
$SF baseline
$SF local nextjs
$SF catalog security
$SF search "supabase auth"
$SF vet vercel-labs/agent-skills vercel-react-best-practices
$SF install vercel-labs/agent-skills vercel-react-best-practices --sha <sha from vet>
```

## How quality and safety are judged

- **Quality score (0–100):** stars, installs, last push, license and trusted owners (official vendors). Forks, archived repos and clone patterns lose points.
- **Clone detection:** many clone repos have a few dozen stars but tens of thousands of reported installs (for example `101-skills/superpowers`: 31 stars, 67k installs). These are rejected automatically.
- **Static scan:** `curl | sh`, access to `~/.ssh` and other credentials, tokens sent over the network, prompt injection, hidden Unicode, bundled binaries, `rm -rf /`, dynamic exec, and network calls in scripts.
- **Verdicts:** `PASS`; `REVIEW` (must be read and approved); `REJECT` (never installed unless you insist with `--force`).
- The scan matches patterns, so the agent must still read the SKILL.md and every script before recommending a skill.

## Adding a profile

1. Create `skills/find-skills/references/catalog/<name>.json` in the same shape as `website.json`: `profile`, `title`, `status`, `baseline_kinds`, `detect`, `domains`.
2. While it is unfinished, set `"status": "draft"`. The installer refuses it ("coming soon") and the helper ignores it unless `FIND_SKILLS_DRAFTS=1`.
3. Confirm every skill in the catalog exists in its repo and passes `vet`, then set `"status": "stable"` and bump the version in `package.json`.

The `--<name>` flag comes from the file name, so `bin/cli.js` needs no changes. `game.json` is already there as a draft.

## Layout

```
bin/cli.js                    npx installer (no dependencies)
skills/find-skills/
├── SKILL.md                  workflow the agent follows
├── scripts/skillfinder.py    helper (standard library only)
└── references/
    ├── catalog/
    │   ├── core.json         anti-slop baseline, trusted owners, clone detection
    │   ├── website.json      website profile (stable)
    │   └── game.json         game profile (draft)
    └── vetting.md            manual review checklist
steering/find-skills-auto.md  optional auto-trigger
```

## Publishing to npm

```bash
npm login
npm publish --dry-run   # check the package contents first
npm publish
```

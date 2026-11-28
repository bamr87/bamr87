<!-- kit: governance v0.1.0 -->
# NEW — Every fleet repo ships VS Code tooling and aligned Claude Code slash commands that cross-reference

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-11-27
- **Proposed by:** Grok Bot, at Amr's request on 2026-11-27: add to the constitution that every repo should have vscode tools, such as the run/debug settings, but also align/add/update the slash commands for claude code that cross reference
- **Ratified by:** (leave blank until merged)
- **Affects:** constitution § 20 items 5, 7 and 8 (extends amendment [0018](../0018-editor-front-door.md)); AGENTS.md convention; feature `HUB-NEW:vscode-and-claude-commands`; requirement `FR-NEW:vscode-and-claude-commands`; UPS-REPO-40 (promoted from SHOULD to MUST in a follow-up spec edit); a new UPS-REPO row for slash commands and cross-references (follow-up)
- **Supersedes:** none (extends § 20; does not replace items 1–4 or 6)
- **Related:** [`.vscode/README.md`](../../.vscode/README.md), [`.claude/README.md`](../../.claude/README.md), [specs/REPOSITORY.md](../../specs/REPOSITORY.md) UPS-REPO-30 / UPS-REPO-40, [specs/STACKS.md](../../specs/STACKS.md), 0016's warn-then-fail rollout pattern, the `templates/vscode/` seed-kit gap recorded in amendment 0018

## Context

Amendment [0018](../0018-editor-front-door.md) already made the editor a front door on the hub and said a fleet repo with a run, test or debug command should carry `.vscode/launch.json` and `tasks.json`. That fleet rule has stayed warn-only: the `templates/vscode/` seed kit it named was never landed, so adoption is uneven and there is no required baseline for `extensions.json` or `settings.json`.

A 2026-11-27 read-only survey of the hub and the 41 submodules in `.gitmodules` (42 repos) found:

- 19 repos have `.vscode/launch.json`; 18 have `tasks.json`; 15 have `extensions.json`; 14 have `settings.json`; 12 have all four (the hub, `gitorio`, `it-journey`, `law-ai`, `lifehacker.dev`, `godotgo`, `zer0-CMS`, `zer0-mistakes`, `SCHEMA`, `bash-365.com`, `ai-world-view.github.io`, `year-of-ai.github.io`).
- 7 more are partial (`bashcrawl`, `bashos`, `djangoerp`, `ocrmd`, `rewind-arcade`, `vs-sonic-pi`, `zpl-viewer`).
- 23 have no run/debug `.vscode` toolkit, including newer infra and app repos (`kvlite`, `fleet-infra`, `fleet-observe`, `ragio-ai`, `cv-pro`, `fredgar-ai`, `githubai`, and others) and the upstream `microsoft/skills` submodule (which has only `.vscode/mcp.json`).
- Only 6 repos have `.claude/commands/` at all: the hub (harness, loops, console, weekly and a few setup commands), `bash-365.com`, `bashos`, `githubai`, `gitorio` and `law-ai`. The names barely overlap — `implement` appears in two repos, and `law-ai` uses `implement-feature` for the same job. None of the command files systematically point at the repo's VS Code tasks or launch configurations, and `AGENTS.md` files do not list both surfaces together.

On 2026-11-27 Amr asked to add to the constitution that every repo should have VS Code tools, such as the run and debug settings, and also to align, add and update the Claude Code slash commands so they cross-reference. This amendment writes that rule in the hub. The seed kit, the conformance check and the per-repo fan-out are follow-up work, executed by Claude Code after ratification (constitution § 26).

## Amendment

Replace constitution § 20 item 5, keep item 6, and add items 7 and 8:

> 5. **Fleet VS Code tooling** — every non-exempt fleet repo ships VS Code workspace tooling for its stack: `.vscode/launch.json` with run and debug configurations that call the repo's own one-command entry points (the same commands its README Quick start names), `.vscode/tasks.json` for the tasks those configurations and the Quick start use, `.vscode/extensions.json` recommending the fleet set the hub's `.devcontainer/` and `.vscode/extensions.json` pin (UPS-REPO-30), and `.vscode/settings.json` where the stack needs workspace settings. A repo with a run, test or debug command includes launch and task entries for them; a debugger-capable surface gets a real debugger entry (item 4), not a terminal launcher. The hub's `.vscode/` is the reference.
> 6. **Exemptions** — content repos, forks and archived or retired repos are exempt; any other exemption is recorded as a standard deviation (UPS README "Deviating").
> 7. **Aligned slash commands** — every non-exempt fleet repo carries Claude Code slash commands under `.claude/commands/`. A shared core set uses the same names fleet-wide (`/dev`, `/test`, `/lint`, `/debug`, `/review`, `/implement`); a repo adds or updates repo-specific commands for its stack and domain, and does not invent a second name for a job the core already covers. The shared core and per-stack skeletons live in the hub's `templates/` once the seed kit lands; until then the names in this section are the contract.
> 8. **Cross-reference** — VS Code tasks and launch configurations, Claude Code slash commands and `AGENTS.md` point at each other both ways: a command that runs, tests, lints or debugs the repo names the matching `tasks.json` label and `launch.json` configuration; a task or launch entry that an agent should use names the matching slash command; each command points at the related commands and at `AGENTS.md`; `AGENTS.md` lists both the editor entries and the slash commands.

Items 1–4 of § 20 are unchanged and still bind the hub's own editor entries.

### Shared core

| Command | Job | Typical VS Code counterpart |
| --- | --- | --- |
| `/dev` | Start or attach to the local stack | default run configuration; `dev` / `up` / `serve` task |
| `/test` | Run the repo's test suite | `test` task |
| `/lint` | Run lint, typecheck and the repo's local gates | `lint` / `check` task |
| `/debug` | Debug a failing run through the repo's debugger entry | debugger launch configuration (item 4) |
| `/review` | Review the current branch or a named pull request | (no required launch entry) |
| `/implement` | Implement a named issue or task, then run `/test` and `/lint` before a PR is offered | (uses the test and lint tasks) |

A repo that already has a close name (`implement-feature`, a namespaced `/spec-driven:implement`, or `bashos`'s `/debug`) keeps the specialized command and, at fan-out, adds the core name or a one-line wrapper so the fleet name resolves. Hub-only commands (`/harness`, `/loops`, `/console`, `/weekly`) stay repo-specific.

### Minimum baseline per stack

Profiles are those in [specs/STACKS.md](../../specs/STACKS.md). Exemptions in item 6 still apply.

| Stack | VS Code minimum | Commands minimum |
| --- | --- | --- |
| app, api, site | `launch.json` (run, plus a debugger where the surface can be debugged), `tasks.json` (`dev`, `test`, `lint`), `extensions.json`, `settings.json` as needed | the shared core, plus repo-specific commands that match extra stack tasks (for example a migrate or compose task) |
| ext | `launch.json` (Extension Host), `tasks.json` (`build`, `test`, `lint`), `extensions.json` | the shared core |
| cli, lib | launch and task entries for the CLI or test entry, `extensions.json` | the shared core |
| infra | `tasks.json` for validate or plan where those commands exist, `extensions.json`, and `launch.json` when there is something to run or debug | `/lint` and `/review`, plus a repo-specific plan or apply command; the rest of the core when it applies |
| content | exempt from the launch and debug MUST (item 6); SHOULD ship `extensions.json` and a `/lint` command when a lint path exists | `/lint` when a lint path exists |

## Consequences

- **Hub, this PR.** Constitution § 20 items 5, 7 and 8, this record, a feature fragment (`HUB-NEW:vscode-and-claude-commands` / `FR-NEW:vscode-and-claude-commands`), a changelog fragment, and the matching AGENTS.md convention line. The hub already has a complete `.vscode/` set and many repo-specific slash commands; adding the shared core names and the bidirectional cross-references is follow-up, so this pull request stays a constitution change.
- **Seed kit, follow-up (Claude Code, after ratification).** `templates/vscode/` (the gap amendment 0018 already named) and `templates/claude-commands/` with the shared core and per-stack skeletons, each with a `SCHEMA.md`. This pull request does not add those directories.
- **Standards, follow-up.** UPS-REPO-40 is promoted from SHOULD to MUST for the same applicability (app, api, site, ext, cli, lib, and any other non-exempt repo with a run, test or debug command). A new UPS-REPO row covers `.claude/commands/`, the shared core names and the cross-reference rule. `_data/standards.yml` gains or updates the `vscode` and `claude-commands` artifacts. Those numbers are not claimed here.
- **Verification, follow-up.** `tools/conformance.py` and `dash audit` check that the required files exist, that launch and task JSONC is parseable, that every `preLaunchTask` resolves, that the six core command files exist (or documented wrappers), and that the cross-references are present. The fleet-pulse doctor can run the same check across the fleet. The check is warn-only per repo until that repo's fan-out PR lands, then a hard failure for that repo (amendment 0016's rollout pattern). A Fleet issue to add the doctor check is proposed as follow-up and is not filed by this pull request.
- **Rollout, after ratification, executed by Claude Code (§ 26), PR-only, never merged by an agent.** (1) Seed kit and the conformance / doctor check in a hub PR. (2) Hub follow-up: shared core command names and cross-references in the hub's own `.claude/commands/`, `.vscode/` and `AGENTS.md`. (3) Fan-out to each non-exempt fleet repo, one PR per repo, adding or updating `.vscode/`, aligning slash commands to the core names, adding repo-specific commands, and writing the cross-references. A repo opts out only by a recorded deviation (item 6).

## Fan-out plan

After ratification, in this order. Each step is a pull request, dry-run first where a kit applies, never merged by the agent.

| # | Scope | What goes out | Why this order |
| --- | --- | --- | --- |
| 1 | **The hub** | Seed kit, conformance / doctor check, UPS-REPO and `standards.yml` updates, the hub's own core command names and cross-references | The hub is the reference and proves the kit on itself |
| 2 | **Repos that already have both surfaces** (`gitorio`, `law-ai`, `bash-365.com`, `bashos`, `githubai`) | Align names, fill missing `.vscode/` files, write cross-references | Smallest diff, and they set the pattern for specialized commands |
| 3 | **Repos that already have a complete or partial `.vscode/`** | Add the shared core commands and cross-references; fill missing `extensions.json` or `settings.json` | Most of the editor work is already done |
| 4 | **The rest of the non-exempt registry** | The full baseline from the seed kit | Routine once 1–3 are green |

Content repos, forks and archived or retired repos stay exempt (item 6), including the upstream `microsoft/skills` submodule.

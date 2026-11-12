<!-- kit: sdlc v0.1.0 · AGENTS.md is the CANONICAL agent instructions file (decision D4, UPS-AGENT-07/08). -->

# bamr87

> The fleet's control plane: about forty projects mounted as Git submodules and managed, monitored and standardized from one hub, which is also the GitHub profile and the public Harness Console site.

## What this repo is

A monorepo of Git submodules under `projects/` that doubles as a self-managing **dash** and a GitHub profile README. Each submodule is a separate repository with its own stack, branch and release cycle; there is no shared build. The root (`tools/`, `.github/`, `_data/`, `specs/`, `templates/`, `docs/`, `pages/`) is the machinery that manages, monitors, documents and standardizes them, and the published site at bamr87.github.io/bamr87 is the Harness Console built static.

A change is done when `tools/check-drift.sh` is green, the focused tests for what you touched pass (table below), the nearest `README.md` and `SCHEMA.md` say what changed, and any generated projection you affected has been regenerated.

## Stack & commands

Python 3.12 (stdlib + PyYAML, PyGithub), Bash, a FastAPI + React console, GitHub Actions. Toolchain versions live in `_data/fleet.yml` `toolchain:`. Prefer the `devenv` container (`/workspace`); copy `.env.example` to `.env` before the first start.

```bash
tools/dash up                                                  # shared core: devenv, console, one Postgres, one Redis
docker compose exec devenv bash                                # a shell in the workspace
python3 -m pip install -r .github/scripts/dash-gen/requirements.txt
tools/check-drift.sh                                           # the hub gate (registry parity, generated files, schema, policy)
tools/run-all-tests.sh                                         # root checks + dash-gen + console + checked-out submodule suites
python3 tools/schema_lint.py check .                           # SCHEMA pyramid (warnings fail the gate too)
python3 tools/unwrap-prose.py --check <changed .md files>      # one paragraph per line
python3 tools/docs_index.py --check                            # docs/README.md index is fresh
```

| Scope | Command |
| --- | --- |
| One generator test file | `python3 .github/scripts/dash-gen/test_machine_api.py` (offline fixtures; any `test_*.py` there runs the same way) |
| One unittest case | `python3 .github/scripts/dash-gen/test_machine_api.py MachineApiTests.test_degraded_without_inputs` |
| CV projection | `python3 -m pytest .github/scripts/dash-gen/test_cv_fragment.py -q` (pytest only; no standalone runner) |
| Hub tools | `python3 tools/test_<name>.py` (conformance, docs index, docker, fleet config, …) |
| Public site | `python3 tools/console/test_pages.py`, then `tools/console/build-pages.sh` |
| Shell / workflows | `shellcheck tools/*.sh tools/observability/*.sh` · `actionlint .github/workflows/*.yml` · `tools/dash workflows lint` |
| Specs / catalog | `python3 tools/gen-specs-data.py --check` · `python3 tools/gen-catalog.py --check` (main only — a PR never commits `CATALOG.md`: `python3 -m tools.jev generated guard --base origin/main`) |

`tools/dash` is the command router for everything else; its full reference is generated in [docs/DASH.md](docs/DASH.md#the-dash-cli). `tools/dash-gen` and `tools/check-drift.sh` honour `PYTHON=/path/to/python`. `run-all-tests.sh` skips projects whose dependencies are not installed, so green means only that what ran passed.

## Layout

See [`SCHEMA.md`](SCHEMA.md) and the chain of `SCHEMA.md` files down to where you work, and [`CATALOG.md`](CATALOG.md) for everything the hub provides. In brief:

| Path | What lives there |
| --- | --- |
| `projects/` | The submodules — separate pyramids, terminal to the hub's schema. The list is the registry, not this file. |
| `_data/` | `projects.yml` (the registry), `fleet.yml` (the control plane's settings), `standards.yml`, `specs.yml`, and the committed fleet snapshots the site renders |
| `tools/` | `dash` (CLI), the gates (`check-drift.sh`, `conformance.py`, `schema_lint.py`), generators, `fanout.sh`, the console (`console/`), the TUI (`tui/`) and their shared core (`fleetcore/`) |
| `.github/` | Workflows (the loops), composite actions, the `dash-gen` generator (`scripts/dash-gen/`); `agents|instructions|prompts/` are Copilot-format reference templates read in place by hub skills |
| `specs/` | The Universal Project Standard every fleet repo is built to (machine twin `_data/specs.yml`) |
| `templates/` | Kits fanned out into the fleet (CI, agent context, sdlc, schema, feedback, verify, …) |
| `infra/` | Infrastructure as code: OpenTofu root modules for each fleet node's network and data volumes (`tools/dash infra`); Ansible and Salt arrive with their phases ([ADR 0003](docs/adr/0003-fleet-platform-nodes-iac-and-scale-out.md), [docs/PLATFORM.md](docs/PLATFORM.md)) |
| `docs/` | Operator documentation, indexed in [`docs/README.md`](docs/README.md) |
| `pages/`, `compose/`, `diagrams/` | Site Markdown, compose overrides, harness diagrams |
| `features/`, `verify/`, `test/` | The hub's own feature index, user scenarios and evidence ([docs/VERIFICATION.md](docs/VERIFICATION.md)) |
| `.claude/`, `.mcp.json` | The AI layer: skills, commands, agents, hooks, the `fleet` MCP server ([`.claude/README.md`](.claude/README.md)) |

## Conventions

- **Backlog of record:** GitHub Issues with the fleet labels; cross-repo initiatives in `_data/roadmap.yml`. **Definition of Done:** `.github/pull_request_template.md`. **Decisions:** `docs/adr/`.
- **Commits:** Conventional Commits (`feat fix docs style refactor test chore perf ci`). **Branches:** `feature/`, `fix/`, `docs/`, `refactor/`, `test/`.
- **README-First, README-Last:** read the nearest `README.md` before changing a directory and update it after.
- **SCHEMA protocol:** place files per the nearest `SCHEMA.md` `## Placement`; a new directory is created with its `SCHEMA.md` (from `templates/schema/SCHEMA.template.md`) and a row in its parent; any add, remove or rename updates the local `SCHEMA.md` in the same commit. `python3 tools/schema_lint.py check . --fix` fixes mechanical drift. The kit is vendored from bamr87/SCHEMA: improvements go upstream first, then re-vendor ([docs/SCHEMA-FRAMEWORK.md](docs/SCHEMA-FRAMEWORK.md)).
- **Dependencies are always latest:** no exact pins, no ceilings, no committed lockfiles. Actions ride major tags; pre-commit `rev:` pins and `toolchain:` versions are the exceptions ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).
- **Numbers are assigned at merge ([amendment 0002](docs/amendments/0002-conflict-free-numbering.md)):** a new feature is `features/features.d/<slug>.yml` with `id: HUB-NEW`, a changelog entry is `changelog.d/<slug>.md`, an amendment is `docs/amendments/proposed/<slug>.md` with `**Number:** NEW`, a roadmap entry is `_data/roadmap.d/<slug>.yml` with `id: FF-NEW` (cite it as `FF-NEW:<slug>`); new requirements go in the feature fragment's `prd_new:` and are referenced by slug. `tools/jev/number.py` assigns the id on `main` and compiles the fragments — a PR never picks the next number, and a generated file is regenerated rather than hand-merged ([docs/JEV.md](docs/JEV.md)).
- **Generated, never hand-edited:** the README `AUTO:projects` span (`tools/dash-gen readme`), `projects/SCHEMA.md` (`tools/gen-projects-schema.py`), `_data/specs.yml` (`tools/gen-specs-data.py`), `CATALOG.md` (`tools/gen-catalog.py`), `_data/cv_portfolio.json` (`tools/dash-gen cv`), the dash CLI reference in `docs/DASH.md` (`tools/gen-dash-cli-doc.py`) and the `docs/README.md` index (`tools/docs_index.py`). `CATALOG.md` and `docs/README.md` are **main-only**: a pull request never edits them (CI fails it); `jev-number.yml` regenerates them, and the generated spans, after every push to `main` (docs/JEV.md). The committed fleet snapshots (`_data/fleet_triage.yml`, `_data/actions_usage.yml`, …) belong to their workflows; read the generator's README before refreshing one. `_data/project_health*.yml`, `_data/ai_activity.yml`, `_site/` and `.fleet/compose/` are ephemeral.
- **Central configuration is `_data/fleet.yml`** — toolchains, schedules, caps, budgets, the token contract and the canonical repo variables; read it with `tools/dash config show [key]`. `bamr87` is a personal account with no org-level secrets or variables, so the contract is declared here and projected onto the fleet (`dash config sync`, `dash secrets sync`). Reusable CI resolves a toolchain version as caller input → the repo's `vars.*` → the built-in default, so a bump here reaches every repo.
- **Secrets:** `_data/` is public site data. Secret values live only in GitHub secrets or `.env`; `fleet.yml` names them, never holds them.
- **Markdown** is one paragraph per line; respect `.prettierignore` (Prettier can desynchronize generated Markdown). Hooks compete through `core.hooksPath` — `bash tools/audit-git-hooks.sh` diagnoses.
- **The editor is a front door (constitution § 20):** every dash subcommand, loop, gate, scenario, site and submodule has its F5 entry in `.vscode/launch.json`; entries call `tools/dash`, a tool's own entry point or `docker compose`, never a second implementation; pickers and ports follow the registries (`python3 tools/test_vscode_launch.py` holds them). A new surface adds its entry and the `.vscode/README.md` line in the same PR.
- **Verify like a user:** a change to what someone sees or does follows [docs/VERIFICATION.md](docs/VERIFICATION.md) — feature index, scenario, evidence bundle under `test/evidence/<slug>/`; a non-visual change gets `skip-evidence` with a reason.
- **Never:** push to `main`, merge a PR that is not mergeable or is held by the review gate (constitution § 12), commit lockfiles or secrets, suppress type errors, leave empty exception handlers, or edit generated files by hand.

## Submodules

Commit inside the submodule's own repository first (submodules land in detached HEAD — check out the branch `.gitmodules` declares), push there, then record the new pointer in the hub. One submodule per PR; never bundle. The registry (`_data/projects.yml`) and `.gitmodules` must agree on paths, URLs and branches — read them, never assume `main`. The full workflow is [docs/SUBMODULES.md](docs/SUBMODULES.md).

The MkDocs site belongs to `projects/README/`; paths such as `projects/README/docs/scripts/` are aggregated copies of other submodules, so edit the original sources, never those copies.

## Standing rules for workflows and agents

Each of these came from an incident; the linked doc tells it.

- **Never end a workflow in a bare `git push` to a protected branch** — publish through `.github/actions/utilities/publish-data`, which falls back to a PR ([docs/DAILY-ANALYSIS.md](docs/DAILY-ANALYSIS.md)).
- **Prefer `needs:` over `workflow_run`** — a skipped upstream silently skips the follower.
- **A PR or push check never reads the whole fleet** — every run in a repo shares one `GITHUB_TOKEN` quota, so a fleet-wide scan on each PR spent it and failed unrelated workflows; fleet reads run on a schedule ([docs/WORKFLOW-OPTIMIZATION.md](docs/WORKFLOW-OPTIMIZATION.md#2026-11-05--a-status-you-can-trust)).
- **Every CI failure is explained on its PR** — `pr-review.yml` keeps one sticky comment per PR saying why each check failed and whether the PR caused it, and deletes it when nothing is failing (constitution § 19, [templates/pr-review/](templates/pr-review/README.md)).
- **A PR that must run CI is opened with `FLEET_TOKEN`, never `GITHUB_TOKEN`** (GitHub fires no workflow events for refs it pushes), and the token is probed with `gh api user`, not presence-checked ([docs/ISSUE-PIPELINE.md](docs/ISSUE-PIPELINE.md)).
- **A fleet-wide secret is written hub-first**, and the fan-out aborts if the hub refuses. Every fleet-scoped secret is named in `token-rotation.yml`'s `env:` (a workflow cannot enumerate `secrets.*`; drift check (l) gates the list) ([docs/TOKEN-ROTATION.md](docs/TOKEN-ROTATION.md)).
- **No hub cron fires on the hour** (`:07` housekeeping, `:37` the daily agent chain, fleet AI crons at 11:00 UTC or later); every hub `schedule:` is declared in `_data/fleet.yml` `schedule:` (`test_schedule.py`).
- **AI runs in a local session when one can do the job** — an interactive Claude Code session, or `claude -p` through `tools/dash loop` and `tools/dash conflicts`, with JEV's tiers, caps and ledger; a CI agent step is the fallback for work that must react inside GitHub or when no local host is up, and new AI work ships with a local entry point first (constitution § 10.9).
- **Every agent is registered and measured** — a new AI workflow, JEV loop step, conflict tier or LaunchAgent lands with its `_data/agents.yml` entry (`tools/dash agents`; drift check (p) fails the PR otherwise), and its KPIs, sources and exemptions live in `_data/fleet.yml` `harness.efficacy` / `sources` / `agents`, never in the agent's own prompt. The 2026-11-07 review found agents failing silently on numbers nobody checked, with inputs nobody refreshed (constitution § 29, [AGENT-EFFICACY.md](docs/AGENT-EFFICACY.md)).
- **A harness is built to the standard, and a kit copy stays the kit's** — every workflow that reaches a model, by any route, is graded against `_data/fleet.yml` `harnesses.standard` (`tools/dash harnesses`, `/harnesses`), and a new one lands on a fleet route (`ai-lane.yml`, `claude-run`, the kit's `claude.yml`) with an exact model, its caps and its switch. Change a kit-seeded workflow in the kit, never in the copy: an edited copy is skipped by every later upgrade. On 2026-11-11 the inventory knew one route and had missed 56 of 117 AI workflows, and the hub's own `claude.yml` had been hand-edited away from the kit whose stamp it carried ([HARNESS-OPS.md](docs/HARNESS-OPS.md#the-harness-standard)).
- **Merge conflicts resolve themselves** — JEV resolves them by script, then with a capped model in a local session; CI runs only the script tier, and a model's resolution carries `needs-amr` (constitution § 12.7, [docs/JEV.md](docs/JEV.md)).
- **Every scheduled agent loop has a `vars.<NAME>_ENABLED` kill switch** that a manual dispatch bypasses; one added to a running loop defaults on (`!= 'false'`).
- **Actions cost is read from GitHub's billing meter**, never from run wall-clock; external mirrors never enter fleet totals ([docs/WORKFLOW-OPTIMIZATION.md](docs/WORKFLOW-OPTIMIZATION.md)).
- **A spent Claude usage window is capacity, not a defect**: every scheduled agent step is `continue-on-error` and its `claude-cost` step runs with `usage-limit: skip`, so a 429 is a warning while every other failure still fails the job (`test_ai_budget.py` pairs them) ([AI-INTEGRATION.md](docs/AI-INTEGRATION.md#spend-guardrails)).
- **Claude auth follows each repo's `CLAUDE_AUTH_ORDER`** (default `oauth,api_key`, set in `_data/fleet.yml` `ai_auth:`), and every headless call is capped by `--max-budget-usd` from `fleet.yml` `budget:` (`test_ai_budget.py`); a budget hit fails the cost step ([docs/AI-INTEGRATION.md](docs/AI-INTEGRATION.md)).
- **No expression in a composite action's `description:`** — the manifest is a template and the action fails before any step runs (drift check (l)).
- **Work by the DevOps methodology (constitution § 10)**: every task is an issue/PR on the [Fleet project #14](https://github.com/users/bamr87/projects/14) with Status and Priority set; multi-phase work is an `epic` (`#6E40C9`) with ordered sub-issues carrying scope, acceptance criteria and guardrails; nothing on Amr's Mac changes before an explicitly approved deploy step; new tools are read-only with allowlists, caps, time limits and redaction; AI cost is labelled "API-equivalent (estimate)". Without the `project` scope (`gh auth refresh -s project`), say so — never change auth yourself.
- **GitHub write-back only through § 11** (amendment 0006 `projects-write-back`): change projects, items, issues or PRs from the harness only via `tools/console/gh_projects_write.py` — plan first, show the diff, apply only after the user confirms (`confirm=true`, same `plan_id`, `HARNESS_PROJECTS_WRITES=1`); never merge, delete or change settings; never print `PROJECTS_TOKEN`.
- **Fan-outs are dry-run by default, PR-only and additive** (`tools/fanout.sh`); agents open PRs and never merge.

## The loops and surfaces

| Loop / surface | What it does | Doc |
| --- | --- | --- |
| `fleet-pulse.yml` | Daily: gather every fleet signal in one commit, rank failing + expensive workflows, the Opus `doctor` opens fix PRs | [DAILY-ANALYSIS.md](docs/DAILY-ANALYSIS.md) |
| `issue-pipeline.yml` | Label-driven three-tier loop: intake with an evidence bundle → implement → complete; never merges; `agent:hold` / `human-review` brake it | [ISSUE-PIPELINE.md](docs/ISSUE-PIPELINE.md) |
| `token-rotation.yml`, `api-keys.yml` | Weekly credential propagate / audit / re-mint; Anthropic Console key expiry | [TOKEN-ROTATION.md](docs/TOKEN-ROTATION.md) |
| `repo-evolution.yml` | Weekly draft improvement PRs in each `auto_evolve` submodule's own repo | [EVOLUTION.md](docs/EVOLUTION.md) |
| `repo-scout.yml` | Daily: a rotating sample of owned repos, a Sonnet agent with no GitHub credential proposes, the `file` job opens labelled issues for the issue pipeline; new loop, so off unless `vars.REPO_SCOUT_ENABLED` is `true` | [SCOUT.md](docs/SCOUT.md) |
| `fleet-pm.yml`, `tools/dash pm` | Daily, read-only: every open issue and PR, their PR state, comments and releases, and the Fleet project, checked against the project, the roadmap and each release train; plans Fleet project ops for `dash projects apply` (§ 11) and roadmap status edits for the working tree; never applies; off unless `vars.FLEET_PM_ENABLED` is `true` | [PM.md](docs/PM.md) |
| `drift-check.yml`, `reconcile-registry.yml`, `update-submodules.yml` | The hard drift gate; registry ↔ GitHub reconciliation (regenerates the README span in its own PR); daily pointer bumps | [DASH.md](docs/DASH.md) |
| `fanout.yml` (`kit` = standardize, harness, schema, verify, feedback, deps-latest, docker), `backlog-fanout.yml` | Kits and backlog items pushed down into the fleet as PRs; one dispatch surface, dry-run default | [STANDARDS.md](docs/STANDARDS.md), [HARNESS-OPS.md](docs/HARNESS-OPS.md), [DOCKER.md](docs/DOCKER.md), [VERIFICATION.md](docs/VERIFICATION.md), [BACKLOG-FANOUT.md](docs/BACKLOG-FANOUT.md) |
| `build-dash.yml` | Builds the console page static with its API snapshot and deploys Pages | [CONSOLE-PAGES.md](docs/CONSOLE-PAGES.md) |
| `jev-number.yml`, `jev-conflicts.yml` | JEV: ids assigned at merge from fragments (serialized on `main`), then the `ratify` job records the ratification / acceptance / completion the maintainer's merges decided in a status-only PR it merges after every check (amendment 0015 `ratification-records`); and tiered PR-conflict triage every 6h — tier 0 free in CI, then Haiku and Sonnet in a local session (`tools/dash conflicts sweep`), then a human; never merges | [JEV.md](docs/JEV.md) |
| `tools/dash console` / `tui` | The write-capable local console (127.0.0.1:4001) and the terminal dash; never commits or merges | [HARNESS-OPS.md](docs/HARNESS-OPS.md) |
| `tools/dash lake` / `observe` / `content` | The local data lake, the log/metrics/trace planes, the content atlas | [HARNESS-OPS.md](docs/HARNESS-OPS.md), [OBSERVABILITY.md](docs/OBSERVABILITY.md), [CONTENT-ATLAS.md](docs/CONTENT-ATLAS.md) |
| `tools/dash workflows` | The workflow atlas: the hub's workflows and actions as one model, linted against the standards, failures classified from the lake, new workflows scaffolded inside the rules (console `/workflows`, MCP `fleet_workflows`) | [WORKFLOW-ATLAS.md](docs/WORKFLOW-ATLAS.md) |
| `tools/dash agents` | The agent inventory under the efficacy contract (§ 29): every CI agent step, JEV loop step, conflict tier and LaunchAgent, with its owner, trigger, switch, cap, model, KPIs, the sources it reads and their writers, and its contract gaps, in `_data/agents.yml`; `--check` is drift check (p), refreshed daily by `fleet-pulse.yml`; gaps warn until a gated PR enables enforcement after the shadow period | [AGENT-EFFICACY.md](docs/AGENT-EFFICACY.md), [ADR 0009](docs/adr/0009-agentic-efficacy-model.md) |
| `tools/dash graph` / `learn` | The fleet graph: registries, atlas, switches, agents, features, decisions and the four operator surfaces as one model (`impact`, `lineage`, `path`, `check` with the surface-parity notes). Outcome learning, shadow only: what happened to each loop's output, a landing estimate per loop and repo, a Thompson plan, a replay test; it steers nothing (API `/api/graph`, `/api/learn`; MCP `fleet_graph`, `fleet_learning`) | [FLEET-GRAPH.md](docs/FLEET-GRAPH.md), [LEARNING.md](docs/LEARNING.md), [ADR 0010](docs/adr/0010-fleet-graph-and-outcome-learning.md) |
| `tools/dash decisions` | The decision index: what waits on Amr across the fleet in ONE call (`needs-amr`, awaiting ratification, failing or major Dependabot, ready to merge) from a local index with a TTL and a hard time budget; read-only; use it instead of sweeping repos (API `/api/decisions`; MCP `decision_queue`) | [DECISION-INDEX.md](docs/DECISION-INDEX.md) |
| `tools/dash up` / `dev` / `docker` | The container plane, per-project dev stacks, the image standard | [CONTAINERS.md](docs/CONTAINERS.md), [FLEET-COMPOSE.md](docs/FLEET-COMPOSE.md), [DOCKER.md](docs/DOCKER.md) |
| `tools/dash refine` | Recursive harness refinement (Harness²): the harness surface validated as a sensor (`surface check`), one Propose–Probe–Compose step planned and evidenced from real local attempts at $0 (`plan`, `evidence`), and the human-gated experience library the context pack reads (`library`), fed by the incident reflector (`reflect`: one capped session over the week's agent incidents, weekly from `tools/install-harness-review.sh`; it previews, a person files); a refinement edits only a loop's tunable half, never a step spec; in the console: Harnesses → Refine (the review queue approves a loop-run preview's filing behind the confirm) and Operate → Assist (a read-only assistant over the fleet MCP server); the Propose–Probe–Compose sessions are ADR 0004 P1's next part | [HARNESS-REFINEMENT.md](docs/HARNESS-REFINEMENT.md), [ADR 0004](docs/adr/0004-recursive-harness-refinement.md) |
| `tools/dash node` / `infra` | Where hub workloads run — the Mac edge and the forge workload node, from `_data/fleet.yml` `nodes:`: status, plan, generated overlays and Ansible inventory, the forwarding-only link key; OpenTofu for a node's network and volumes (apply needs `--yes` and a current plan) | [PLATFORM.md](docs/PLATFORM.md), [ADR 0003](docs/adr/0003-fleet-platform-nodes-iac-and-scale-out.md) |

## Gotchas

- **The site:** `tools/dash serve` builds it at `/` on :4000; Pages serves it under `/bamr87/`, so every in-app link goes through React Router's `basename` and every file URL through `asset()` (`web/src/api/backend.ts`) — never a bare `/path`. A new route needs a row in `snapshot.STATIC_ROUTES` (`test_pages.py` holds them equal). Production builds `tools/console/build-pages.sh` into `_site`, then `tools/dash-gen machine-api --out _site` ([docs/MACHINE-API.md](docs/MACHINE-API.md)).
- **The fleet is many compose projects, not one:** `include:` would silently keep one of five services called `jekyll`. Each repo is its own project on the shared `fleet` network, with one Postgres and Redis and one port map (`dev_port` in the registry; overrides from `tools/dash gen compose` into `.fleet/compose/`, never into a submodule). The project name is pinned to `fleet` so worktrees share volumes ([docs/CONTAINERS.md](docs/CONTAINERS.md)).
- **Images:** versions come from `_data/fleet.yml` `images:` (Ruby is 3.4, not 4.0: `github-pages` caps it). A Postgres major bump orphans local volumes; migrate with `tools/dash dev db-upgrade <project> --yes` — for the hub core's `db`, `tools/pg-major-upgrade.sh --service db --yes -- --project-directory .`, which `dash up` names when it refuses ([docs/DOCKER.md](docs/DOCKER.md)).
- **Shared surface code lives in `tools/fleetcore/`:** a view, key binding, colour or job-API call the console and the TUI both use goes there, never into one of them. The `fleet` MCP server (`.mcp.json`) is built on the same core.
- **Consumed interfaces:** `_data/harness_registry.yml` (`schema: harness-registry/v1`) is read by GitFactory's Fleet Studio — additive changes are free, renames bump the marker ([docs/HARNESS-OPS.md](docs/HARNESS-OPS.md)).
- **Local sessions run zsh on macOS:** the Bash tool's shell is zsh with BSD tools and no `timeout`, and its traps were over a quarter of the failed tool calls in the week to 2026-11-07. An unquoted `echo ====` separator is a `=command` lookup that aborts everything after it (`(eval):1: ==== not found`): write `echo '== x =='`. An unmatched glob fails in the shell before the command runs, so `2>/dev/null` cannot hide it (`no matches found`): quote a glob the program expands itself (`--include='*.py'`, `find -name '*.yml'`). `set -- $var` does not split. A multi-line script runs as `bash <<'EOF' … EOF`, which is bash 5. `python3 -I` also drops the `PYTHONPATH` that `tools/devtools-env.sh` puts PyYAML on: keep `-I` for scripts that read untrusted downloads and run hub tools as plain `python3`.
- **Edit trusts only its own Read:** Claude Code's Edit refuses a file the Read tool has not read since its last change (two in three failed Edits): a `cat` or `sed -n` view does not count, and a rewrite from Bash (`python`, `sed -i`, `git checkout`) voids the earlier Read, so Read the slice (`offset`/`limit`) just before editing. To wait, use `run_in_background` and its notification, or Monitor; `sleep N; <check>` is refused.

## Fleet context

This is the hub. It owns the fleet's standards (`specs/`, including the documentation framework [specs/DOCS.md](specs/DOCS.md)), the kits that seed them, and the vendored payloads it holds byte-identical across the fleet (`tools/unwrap-prose.py`, `tools/schema_lint.py`, `tools/docs_index.py`, the feedback widget; drift check (i)). The fleet's documentation is reviewed in one place by the README submodule's survey ([`context/reports/docs_review.md`](https://github.com/bamr87/README/blob/main/context/reports/docs_review.md)).

## Standard deviations

Declared in `.github/sdlc.yml` `deviations:` (the hub's SDLC profile, UPS-WORK-01):

- UPS-REPO-21 waived until 2027-04-01: the hub's public interface (reusable workflows + checker) versions by hand-cut major tags (`v1`, `v2`) per `docs/WORKFLOW-VERSIONING.md`, and `CHANGELOG.md` is maintained with those cuts rather than by release-please.

## Agent roles (constitution § 26)

Amr's split (amendment 0032 `claude-code-executes`):

| Actor | Does | Does not |
| --- | --- | --- |
| **Claude Code** (local CLI or console-/workflow-dispatched) | Execute software changes and Harness Console–bound apply/jobs; open implementation PRs | Merge gated PRs; change settings; print secrets |
| **Grok bots** (Grok Bot primary, Platform Architect, Fleet Ops, Tools, Sites, Content & Comms, Researcher, Bashcrawl & Games, Law AI Lead, and their subagents) | Propose **direction-setting** amendment PRs (constitution + `docs/amendments/proposed/` + `changelog.d/`); file/comment issues; hand off execution | Open software/console implementation PRs; apply console execution write-back; merge |

**Handoff:** a Grok bot that needs software or console work files a Fleet issue (and/or console job) with goal, acceptance criteria and constraints for Claude Code to execute.

**Fallback:** if Claude Code is unavailable or out of budget, stop and wait for Amr's explicit OK — do not silently implement as a Grok bot.

Details: [`docs/constitution.md`](docs/constitution.md) § 26; [`docs/amendments/0032-claude-code-executes.md`](docs/amendments/0032-claude-code-executes.md).

## Grok ↔ Claude Code governance (constitution § 28, amendment 0031)

- **Grok bots (direction):** constitution, amendments, PRD, features, roadmap, research, assessments. They hand off software/console work by opening a Fleet issue or console job stating the requirement, acceptance criteria and a link to the **ratified** governing amendment or FR.
- **Claude Code (execution):** every software change and console job, against that spec; the PR body carries `Governed by:` (amendment and/or `FRn`/`NFRn`/`FR-NEW:<key>`). Check with `python3 tools/governance_trace_lint.py check --body-file BODY.md` (warn-only).
- **Before merge:** a Grok bot reviews the result for alignment with direction, not the code.
- **Escalation:** if Claude Code is unavailable or out of budget, work stops until Amr approves an alternative path.
- No orphan changes. Only Amr ratifies, by merging.

## Governance

Read [`docs/constitution.md`](docs/constitution.md) before changing anything: it is the highest-precedence rule set here and wins over this file when they disagree. It changes only through a numbered record in [`docs/amendments/`](docs/amendments/), ratified by the maintainer merging the PR; agents propose, never merge. Every user-facing feature has a stable id in [`features/features.yml`](features/features.yml) with `status`, location and the PRD requirement ids it serves; the PRD's "Feature catalog" block is generated from it (`python3 <bamr87/bamr87>/tools/governance_lint.py prd-sync . --write`; check with `… check .`). Never hand-edit that block or `CHANGELOG.md`.

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
| Shell / workflows | `shellcheck tools/*.sh tools/observability/*.sh` · `actionlint .github/workflows/*.yml` |
| Specs / catalog | `python3 tools/gen-specs-data.py --check` · `python3 tools/gen-catalog.py --check` |

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
- **Generated, never hand-edited:** the README `AUTO:projects` span (`tools/dash-gen readme`), `projects/SCHEMA.md` (`tools/gen-projects-schema.py`), `_data/specs.yml` (`tools/gen-specs-data.py`), `CATALOG.md` (`tools/gen-catalog.py`), `_data/cv_portfolio.json` (`tools/dash-gen cv`), the dash CLI reference in `docs/DASH.md` (`tools/gen-dash-cli-doc.py`) and the `docs/README.md` index (`tools/docs_index.py`). The committed fleet snapshots (`_data/fleet_triage.yml`, `_data/actions_usage.yml`, …) belong to their workflows; read the generator's README before refreshing one. `_data/project_health*.yml`, `_data/ai_activity.yml`, `_site/` and `.fleet/compose/` are ephemeral.
- **Central configuration is `_data/fleet.yml`** — toolchains, schedules, caps, budgets, the token contract and the canonical repo variables; read it with `tools/dash config show [key]`. `bamr87` is a personal account with no org-level secrets or variables, so the contract is declared here and projected onto the fleet (`dash config sync`, `dash secrets sync`). Reusable CI resolves a toolchain version as caller input → the repo's `vars.*` → the built-in default, so a bump here reaches every repo.
- **Secrets:** `_data/` is public site data. Secret values live only in GitHub secrets or `.env`; `fleet.yml` names them, never holds them.
- **Markdown** is one paragraph per line; respect `.prettierignore` (Prettier can desynchronize generated Markdown). Hooks compete through `core.hooksPath` — `bash tools/audit-git-hooks.sh` diagnoses.
- **Verify like a user:** a change to what someone sees or does follows [docs/VERIFICATION.md](docs/VERIFICATION.md) — feature index, scenario, evidence bundle under `test/evidence/<slug>/`; a non-visual change gets `skip-evidence` with a reason.
- **Never:** push to `main`, merge your own PR, commit lockfiles or secrets, suppress type errors, leave empty exception handlers, or edit generated files by hand.

## Submodules

Commit inside the submodule's own repository first (submodules land in detached HEAD — check out the branch `.gitmodules` declares), push there, then record the new pointer in the hub. One submodule per PR; never bundle. The registry (`_data/projects.yml`) and `.gitmodules` must agree on paths, URLs and branches — read them, never assume `main`. The full workflow is [docs/SUBMODULES.md](docs/SUBMODULES.md).

The MkDocs site belongs to `projects/README/`; paths such as `projects/README/docs/scripts/` are aggregated copies of other submodules, so edit the original sources, never those copies.

## Standing rules for workflows and agents

Each of these came from an incident; the linked doc tells it.

- **Never end a workflow in a bare `git push` to a protected branch** — publish through `.github/actions/utilities/publish-data`, which falls back to a PR ([docs/DAILY-ANALYSIS.md](docs/DAILY-ANALYSIS.md)).
- **Prefer `needs:` over `workflow_run`** — a skipped upstream silently skips the follower.
- **A PR that must run CI is opened with `FLEET_TOKEN`, never `GITHUB_TOKEN`** (GitHub fires no workflow events for refs it pushes), and the token is probed with `gh api user`, not presence-checked ([docs/ISSUE-PIPELINE.md](docs/ISSUE-PIPELINE.md)).
- **A fleet-wide secret is written hub-first**, and the fan-out aborts if the hub refuses. Every fleet-scoped secret is named in `token-rotation.yml`'s `env:` (a workflow cannot enumerate `secrets.*`; drift check (l) gates the list) ([docs/TOKEN-ROTATION.md](docs/TOKEN-ROTATION.md)).
- **No hub cron fires on the hour** (`:07` housekeeping, `:37` the daily agent chain, fleet AI crons at 11:00 UTC or later); every hub `schedule:` is declared in `_data/fleet.yml` `schedule:` (`test_schedule.py`).
- **Every scheduled agent loop has a `vars.<NAME>_ENABLED` kill switch** that a manual dispatch bypasses; one added to a running loop defaults on (`!= 'false'`).
- **Actions cost is read from GitHub's billing meter**, never from run wall-clock; external mirrors never enter fleet totals ([docs/WORKFLOW-OPTIMIZATION.md](docs/WORKFLOW-OPTIMIZATION.md)).
- **Claude auth follows each repo's `CLAUDE_AUTH_ORDER`** (default `oauth,api_key`, set in `_data/fleet.yml` `ai_auth:`), and every headless call is capped by `--max-budget-usd` from `fleet.yml` `budget:` (`test_ai_budget.py`); a budget hit fails the cost step ([docs/AI-INTEGRATION.md](docs/AI-INTEGRATION.md)).
- **No expression in a composite action's `description:`** — the manifest is a template and the action fails before any step runs (drift check (l)).
- **Fan-outs are dry-run by default, PR-only and additive** (`tools/fanout.sh`); agents open PRs and never merge.

## The loops and surfaces

| Loop / surface | What it does | Doc |
| --- | --- | --- |
| `fleet-pulse.yml` | Daily: gather every fleet signal in one commit, rank failing + expensive workflows, the Opus `doctor` opens fix PRs | [DAILY-ANALYSIS.md](docs/DAILY-ANALYSIS.md) |
| `issue-pipeline.yml` | Label-driven three-tier loop: intake with an evidence bundle → implement → complete; never merges; `agent:hold` / `human-review` brake it | [ISSUE-PIPELINE.md](docs/ISSUE-PIPELINE.md) |
| `token-rotation.yml`, `api-keys.yml` | Weekly credential propagate / audit / re-mint; Anthropic Console key expiry | [TOKEN-ROTATION.md](docs/TOKEN-ROTATION.md) |
| `repo-evolution.yml` | Weekly draft improvement PRs in each `auto_evolve` submodule's own repo | [EVOLUTION.md](docs/EVOLUTION.md) |
| `drift-check.yml`, `refresh-dash.yml`, `reconcile-registry.yml`, `update-submodules.yml` | The hard drift gate; nightly README/registry refresh; registry ↔ GitHub reconciliation; daily pointer bumps | [DASH.md](docs/DASH.md) |
| `standardize-`, `schema-`, `feedback-`, `harness-`, `deps-`, `docker-`, `verify-fanout.yml` | Kits pushed down into the fleet as PRs | [STANDARDS.md](docs/STANDARDS.md), [HARNESS-OPS.md](docs/HARNESS-OPS.md), [DOCKER.md](docs/DOCKER.md), [VERIFICATION.md](docs/VERIFICATION.md) |
| `build-dash.yml` | Builds the console page static with its API snapshot and deploys Pages | [CONSOLE-PAGES.md](docs/CONSOLE-PAGES.md) |
| `tools/dash console` / `tui` | The write-capable local console (127.0.0.1:4001) and the terminal dash; never commits or merges | [HARNESS-OPS.md](docs/HARNESS-OPS.md) |
| `tools/dash lake` / `observe` / `content` | The local data lake, the log/metrics/trace planes, the content atlas | [HARNESS-OPS.md](docs/HARNESS-OPS.md), [OBSERVABILITY.md](docs/OBSERVABILITY.md), [CONTENT-ATLAS.md](docs/CONTENT-ATLAS.md) |
| `tools/dash up` / `dev` / `docker` | The container plane, per-project dev stacks, the image standard | [CONTAINERS.md](docs/CONTAINERS.md), [FLEET-COMPOSE.md](docs/FLEET-COMPOSE.md), [DOCKER.md](docs/DOCKER.md) |

## Gotchas

- **The site:** `tools/dash serve` builds it at `/` on :4000; Pages serves it under `/bamr87/`, so every in-app link goes through React Router's `basename` and every file URL through `asset()` (`web/src/api/backend.ts`) — never a bare `/path`. A new route needs a row in `snapshot.STATIC_ROUTES` (`test_pages.py` holds them equal). Production builds `tools/console/build-pages.sh` into `_site`, then `tools/dash-gen machine-api --out _site` ([docs/MACHINE-API.md](docs/MACHINE-API.md)).
- **The fleet is many compose projects, not one:** `include:` would silently keep one of five services called `jekyll`. Each repo is its own project on the shared `fleet` network, with one Postgres and Redis and one port map (`dev_port` in the registry; overrides from `tools/dash gen compose` into `.fleet/compose/`, never into a submodule). The project name is pinned to `fleet` so worktrees share volumes ([docs/CONTAINERS.md](docs/CONTAINERS.md)).
- **Images:** versions come from `_data/fleet.yml` `images:` (Ruby is 3.4, not 4.0: `github-pages` caps it). A Postgres major bump orphans local volumes; migrate with `tools/dash dev db-upgrade <project> --yes` ([docs/DOCKER.md](docs/DOCKER.md)).
- **Shared surface code lives in `tools/fleetcore/`:** a view, key binding, colour or job-API call the console and the TUI both use goes there, never into one of them. The `fleet` MCP server (`.mcp.json`) is built on the same core.
- **Consumed interfaces:** `_data/harness_registry.yml` (`schema: harness-registry/v1`) is read by GitFactory's Fleet Studio — additive changes are free, renames bump the marker ([docs/HARNESS-OPS.md](docs/HARNESS-OPS.md)).

## Fleet context

This is the hub. It owns the fleet's standards (`specs/`, including the documentation framework [specs/DOCS.md](specs/DOCS.md)), the kits that seed them, and the vendored payloads it holds byte-identical across the fleet (`tools/unwrap-prose.py`, `tools/schema_lint.py`, `tools/docs_index.py`, the feedback widget; drift check (i)). The fleet's documentation is reviewed in one place by the README submodule's survey ([`context/reports/docs_review.md`](https://github.com/bamr87/README/blob/main/context/reports/docs_review.md)).

## Standard deviations

Declared in `.github/sdlc.yml` `deviations:` (the hub's SDLC profile, UPS-WORK-01):

- UPS-REPO-21 waived until 2027-04-01: the hub's public interface (reusable workflows + checker) versions by hand-cut major tags (`v1`, `v2`) per `docs/WORKFLOW-VERSIONING.md`, and `CHANGELOG.md` is maintained with those cuts rather than by release-please.

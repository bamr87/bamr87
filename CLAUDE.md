# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **monorepo of ~40 Git submodules** that doubles as a self-managing **dash** (control plane) and a GitHub profile README. Every directory under `projects/` is a _separate Git repository_ with its own stack, branch, and release cycle — there is no shared build system tying them together. The root repo (`tools/`, `docs/`, `.github/`, `_data/`, `pages/`, and the Jekyll site) is the machinery that manages, monitors, documents, and **standardizes** them.

**The authoritative project list is [`_data/projects.yml`](_data/projects.yml)** (the registry), cross-checked against `.gitmodules` by the drift gate — _not_ this file. Don't maintain a submodule list here; read the registry. Representative/foundational submodules:

| Path | Upstream | Branch | Stack |
| --- | --- | --- | --- |
| `projects/cv-builder-pro/` | `bamr87/cv-builder-pro` | `main` | React, TypeScript, Vite, Tailwind, Firebase |
| `projects/README/` | `bamr87/README` | `main` | Python, MkDocs, Wiki.js |
| `projects/scripts/` | `bamr87/scripts` | `main` | Bash, Python |
| `projects/zer0-mistakes/` | `bamr87/zer0-mistakes` | `main` | Jekyll theme (powers this dash) |
| `projects/it-journey/` | `bamr87/it-journey` | `main` | Jekyll, Ruby |
| `projects/skills/` | `microsoft/skills` (external) | `main`, `update = merge` | Markdown skills, MCP |

**Branch exceptions** (all submodules track `main` except one): `sonic-pi` tracks **`dev`** (fork of `sonic-pi-net/sonic-pi`, whose upstream has no `main`); `skills` is an external `microsoft/skills` mirror on `main` (`update = merge`). Always read the branch from `.gitmodules` / the registry — never assume.

`tools/`, `docs/`, `.github/`, `_data/`, and `pages/` are part of the **root** repo (not submodules).

## Submodule workflow (critical, non-obvious)

Submodules are full clones of other repos. A change inside `projects/cv-builder-pro/`, `projects/README/`, `projects/scripts/`, or `projects/skills/` is **not** committed by the root repo — you commit it _in the submodule's own repo first_, then update the pointer in root:

```bash
cd projects/cv-builder-pro
git checkout main                      # submodules often land in detached HEAD; check out the branch first
# ...edit, then:
git add . && git commit -m "feat: ..."
git push origin main                   # pushes to bamr87/cv-builder-pro, NOT this repo
cd ../..
git add projects/cv-builder-pro && git commit -m "chore: update cv submodule"   # root only records the new commit SHA
```

Consequences:

- Branches: all track `main` except `sonic-pi` (`dev`, upstream fork). Read the branch from `.gitmodules`; don't assume.
- `projects/skills/` belongs to `microsoft/skills`; you generally consume it, not modify it.
- Don't bundle changes across multiple submodules into one PR.
- After pulling, run `git submodule update --init --recursive` if a submodule looks empty or stale.

Clone fresh with `git clone --recurse-submodules ...`; bootstrap everything with `./tools/setup-dev.sh`.

## Common commands

Run project commands **inside the relevant submodule** — each has its own dependencies.

**CV Builder (`projects/cv-builder-pro/`)** — Vite dev server (serves on port 5000 per the compose/`kill` config; docs sometimes cite Vite's default 5173):

```bash
cd projects/cv-builder-pro
npm install
npm run dev
npm run build        # tsc -b --noCheck && vite build
npm run lint         # eslint .
npm run kill         # frees port 5000
```

Note: there is **no `npm test` script** in `projects/cv-builder-pro/`. Tests are Cypress e2e specs under `projects/cv-builder-pro/cypress/e2e/` (`npx cypress run` against a running dev server).

**Documentation (`projects/README/`)** — Python + pytest:

```bash
cd projects/README
pip install -r requirements.txt
pytest tests/                  # or a single test: pytest tests/test_x.py::test_name -v
```

**MkDocs site (root)** — builds from `projects/README/docs` (see `docs_dir` in `mkdocs.yml`):

```bash
pip install -r requirements-docs.txt
mkdocs serve                   # http://localhost:8000
mkdocs build --strict          # CI-style strict build
```

**Aggregate verification** — delegates to each project's own checks; skips any whose tooling/deps are absent:

```bash
./tools/run-all-tests.sh       # fans out over EVERY checked-out submodule, running each project's own suite when its deps are installed and skipping (with a reason) otherwise; plus mkdocs build + shellcheck of tools/ & projects/scripts/. cv-builder-pro is a skip, not a failure (no npm test script).
```

**Shell scripts** — `shellcheck tools/*.sh projects/scripts/*.sh` (CI uses `--severity=warning`).

## Container-first development

`docker-compose.yml` defines the full environment. `devenv` is the primary workspace container (the repo is mounted at `/workspace`); other services are optional.

```bash
docker compose up -d                  # start all default services
docker compose up -d devenv           # just the dev workspace
docker compose exec devenv bash       # shell into it
docker compose --profile admin up -d  # add pgAdmin
docker compose down -v                # stop and wipe volumes
```

Services: `devenv` (ports 5000 CV / 5173 HMR / 8000 MkDocs / 4000 Jekyll), `mkdocs`, `wiki` (Wiki.js, needs `db`), `db` (Postgres 15), `redis` (`full` profile), `pgadmin` (`admin` profile). Copy `.env.example` → `.env` before first run.

## Docs aggregation gotcha

The published MkDocs site (`docs_dir: projects/README/docs`) pulls from the **README submodule**. Paths like `projects/README/docs/scripts/` and `projects/README/docs/skills/` are _aggregated documentation copies_ for the site — they are **not** the same working trees as the root `projects/scripts/` and `projects/skills/` submodules. Edit source in the submodules; the copies under `projects/README/docs` are generated/mirrored content.

## Quality gates

- **pre-commit** (`.pre-commit-config.yaml`): trailing-whitespace, end-of-file, check-yaml/json, markdownlint (`--fix`, MD013/MD033/MD041 disabled), shellcheck, prettier. `black` + `flake8` (max-line 120) are **scoped to `projects/README/**/*.py` only**. Install with `pip install pre-commit && pre-commit install`; CI skips shellcheck + markdownlint.
- **Husky** (`.husky/pre-commit`) runs `pnpm lint-staged`.
- **CI**: the live control-plane workflows are `build-dash.yml` (builds the Jekyll dash and deploys to Pages — the sole Pages surface), `drift-check.yml` (hard drift gate), `refresh-dash.yml` (nightly README/registry refresh PR), `reconcile-registry.yml` (nightly registry↔GitHub reconciliation: auto-fix PR for renames/URL mismatches, tracking _issue_ for 404s and branch drift — deletions are never auto-applied, since a repo-scoped token 404s on a private repo identically), `update-submodules.yml` (daily PR bumping submodule pointers _up_), `standardize-fanout.yml` (opens standardization PRs _down_ into submodules — the reusable `standard-ci.yml` caller, `.editorconfig`, and on request the **agent-context kit**: artifacts `agent-context,claude` seed a `CLAUDE.md` scaffold + the `@claude` mention workflow from `templates/agent-context/`), `schema-fanout.yml` (opens Pyramid Schema adoption PRs _down_ into submodules; optional `agent_fill` Claude Code pass fills scaffold TODOs), and **`fleet-pulse.yml`** — THE daily loop (see [`docs/DAILY-ANALYSIS.md`](docs/DAILY-ANALYSIS.md)). One workflow, two jobs: `pulse` gathers every fleet signal (Actions analytics, Claude usage + engagement actuals, prior-day digest, open-state triage snapshot) off ONE checkout, publishes them in ONE commit via `.github/actions/utilities/publish-data`, and merges the **failing** + **expensive** signals into one ranked, deduped, capped fix queue (`dash-gen remediate`); `doctor` (`needs: pulse`) runs an **Opus Claude Code agent** that reads each candidate's logs and opens a draft _PR with the fix_ — in the hub, or **in the submodule that owns the workflow** — falling back to a hub _issue_ when it can't. It replaces `actions-usage.yml`, `ai-usage.yml`, `actions-review.yml`, and `daily-repo-analysis.yml`, which were four workflows doing one job and which had been **silently dead for three weeks**: a ruleset requiring PRs on `main` made their closing `git push` fail every day, and `actions-review`'s `workflow_run` trigger meant it was skipped as collateral. Hence two standing rules — **never end a workflow in a bare `git push` to a protected branch** (use `publish-data`, which falls back to a PR), and **prefer `needs:` over `workflow_run`**. Both fan-outs ride `tools/fanout.sh` (dry-run default, PRs only, additive-only). **Claude auth convention**: every `anthropics/claude-code-action` call site (`claude.yml` @claude handler, `fleet-pulse.yml` `doctor`, `unified-evolution.yml`, `schema-fanout.yml` `agent_fill`) is OAuth-first — `CLAUDE_CODE_OAUTH_TOKEN` preferred, `ANTHROPIC_API_KEY` fallback; see [`docs/AI-INTEGRATION.md`](docs/AI-INTEGRATION.md). `unified-evolution.yml` is the last of the generic `unified-*.yml` suite and is legacy/dispatch-only; the rest (`unified-cicd`, `unified-release`, `unified-maintenance`, `workflow-dispatcher`) were removed as obsolete. Reusable composite actions live in `.github/actions/{ci,deployment,setup,utilities}`.

## The Dash (central command surface)

The repo is a self-managing **dash**. See [`docs/DASH.md`](docs/DASH.md). Key facts:

- **Single source of truth**: [`_data/projects.yml`](_data/projects.yml) — the project registry. To add/change a project, edit ONLY this file; every surface (portfolio, dashboard, monitor, the profile `README.md` `<!-- AUTO:projects -->` span, the drift gate) follows.
- **Central configuration**: [`_data/fleet.yml`](_data/fleet.yml) — the control plane's own settings, the counterpart to the project registry: toolchain versions, schedule cadences, remediation caps + severity ranking, the **token contract** (which secret does what and where it must exist), and the canonical repo **variables**. Read it with `dash config show [dotted.key]`; audit the fleet against it with `dash secrets`; project the variables outward with `dash config sync --apply`. `bamr87` is a personal account, not an org, so GitHub's org-level secrets/variables don't exist — declaring the contract in version control and projecting/auditing it with tooling is the substitute. Reusable CI resolves toolchain versions as caller input → the repo's `vars.*` → built-in default, so bumping a version here reaches all ~40 repos. **Secret _values_ never live in this file** (or any other — `_data/` is public site data).
- **Dash site**: the **root** Jekyll site (`remote_theme: bamr87/zer0-mistakes`) renders the dash from the `pages/_dash/` collection (Portfolio/Dashboard/Monitor/Toolbox/Resume/Docs), published at `bamr87.github.io/bamr87/`. Local: `tools/dash serve` (docker, :4000).
- **CLI**: `tools/dash {status|audit|monitor|actions|actions-review|daily|triage|remediate|secrets|config|reconcile|estimate|ledger|serve|sync|foreach|run|new|adopt-release|protect|evolve|ai|gen|test|doctor}` (alias `bamr87-dash`) — reuses `setup.sh`/`run-all-tests.sh`/`update-submodules.sh`/`audit-standards.sh`/`projects/scripts/`. `dash audit` prints the per-repo standardization conformance matrix; `dash foreach <cmd>` runs a command in every submodule; `dash actions` prints GitHub Actions usage/effectiveness analytics; `dash daily` builds the prior-day fleet activity digest + failure work order; `dash triage` snapshots the fleet's open issues/PRs/CI state into `_data/fleet_triage.yml` (the `/triage/` portal); `dash reconcile` compares the registry + `.gitmodules` against GitHub reality and (with `--apply`) writes only the unambiguous fixes; `dash remediate` merges the failing + expensive workflow signals into the one ranked fix queue that drives `fleet-pulse.yml`'s `doctor` job; `dash secrets` prints the per-repo matrix of declared secrets/variables vs what GitHub actually has (`dash secrets sync --apply` provisions the token contract fleet-wide, reading values only from env); `dash config [show|sync]` reads [`_data/fleet.yml`](_data/fleet.yml) and (with `sync --apply`) projects the canonical repo **variables** onto every fleet repo.
- **Generator**: `.github/scripts/dash-gen` (`tools/dash-gen`) — `health` gathers live GitHub signals → ephemeral `_data/project_health.yml` (gitignored, never commit); `readme` regenerates the README AUTO span (deterministic, committable); `ai` shadow-prices local Claude Code usage per repo (`ai_activity.py`: scans `~/.claude/projects/` JSONL, persists `~/.claude/ai-activity-ledger.json`, writes gitignored `_data/ai_activity.yml` for the `/ai-activity/` page — local-only, never part of `all`/CI); `actions` analyzes GitHub Actions consumption via **PyGithub** (`actions_analytics.py`: per-workflow cost/effectiveness/waste + type grouping → **committed** `_data/actions_usage.yml` for the `/actions/` page, refreshed daily by `fleet-pulse.yml`'s `pulse` job); `actions-review` (`actions_review.py`) is the legacy triage layer — it selects the worst workflows from that data, dedupes them against open `actions-review` issues, and emits a work order (its dedicated workflow was retired; those signals now flow through `remediate` into `fleet-pulse.yml`'s `doctor` job); `daily` (`daily_report.py`) scans the fleet's prior-day activity via **PyGithub** → writes the **committed** digest `_reports/daily/<date>.md` and a **deduped** failure work order, refreshed daily by the same `pulse` job (see [`docs/DAILY-ANALYSIS.md`](docs/DAILY-ANALYSIS.md)); `triage` (`fleet_triage.py`) inventories the fleet's **open state** — every open issue, open PR (with CI check status), and failing workflow — into **committed** `_data/fleet_triage.yml` with per-repo attention scores and a prioritized cross-fleet inbox, rendered at `/triage/` (refreshed by the same daily run); `remediate` (`remediation.py`) merges the two ACTIONABLE signals — standing failures from `fleet_triage.yml` and cost/slowness flags from `actions_usage.yml` — into ONE queue keyed on `owner/repo:workflow-path`, so a workflow that is both red and expensive is one candidate with both signals rather than two competing tickets; it classifies each as hub-fixable or cross-repo, ranks by severity then wasted minutes, dedupes against open issues **and** open PRs in both the hub and the target repo (honouring the retired loops' markers so pre-migration tickets aren't re-filed), and caps per `_data/fleet.yml`; `reconcile` (`reconcile.py`) compares three sources — the registry's `repo_url`, the `.gitmodules` url, and GitHub itself — and routes findings by signal quality: **authoritative** drift (renames, registry↔`.gitmodules` url mismatches) is written by `--apply` via surgical edits that preserve YAML comments, while **advisory** drift (404s, branch drift) is only reported, because a repo-scoped token 404s on a private repo exactly as on a deleted one and this fleet deliberately tracks non-default branches; driven nightly by `reconcile-registry.yml`; `estimate` + `ledger` (`engagements.py`) treat every registry project as a **client**: deterministic engagement estimates from open issues (estimator-v1 + the `_data/engagement_rates.yml` rate card — AI implementation + human-broker + platform cost decomposition, pre-AI `traditional` comparison → leverage) into **committed** `_data/engagements.yml`, then actuals accrued from `ai_usage.yml` evidence (URL-deduped) with variance + per-client rollups, rendered at `/engagements/` (accrual runs daily in `fleet-pulse.yml`'s `pulse` job; estimates are proposals — status transitions are human-owned; see [`docs/ESTIMATION.md`](docs/ESTIMATION.md)).
- **Drift**: `tools/check-drift.sh` — a fast, offline+API gate (no Ruby/Jekyll build in CI). Hard-fails on registry/.gitmodules parity — paths, branches, **and urls** (an offline check, so registry↔`.gitmodules` url divergence gates every PR) — stray/unregistered project dirs, stale README, missing top-level READMEs, and SCHEMA.md pyramid errors or a stale generated `projects/SCHEMA.md` (check (h)); advises (non-gating) on GitHub-reality drift — renames/deletions/branch (`--remote`/`--ci`) — and standardization. The advisory half is acted on nightly by `reconcile-registry.yml` (see `dash reconcile`). The submodule checked-out-branch check is local-only (skipped when submodules aren't checked out); the internal-link check is `--links` only (needs a local `_site`).
- **AI layer**: [`.claude/README.md`](.claude/README.md) indexes it. `.mcp.json` (MCP servers) + `.claude/skills/` (drift-report, evolve-project, new-project, refresh-portfolio, run-dash, sync-project-docs, triage-attention, update-registry, **standardize-audit**, **standardize-project**, **onboard-dir**, **actions-triage**, **estimate-issue**) + `.claude/commands/` (`/dash-status`, `/evolve`, `/register-project`, `/adopt-release`, `/adopt-schema`, `/future-features`) + `.claude/agents/feature-scout.md` + `.claude/hooks/` (Future-Features session hooks). The **`run-dash` skill's `driver.py` is the orchestration entrypoint** (per-submodule work orders). `unified-evolution.yml` runs Claude Code (`anthropics/claude-code-action`; auth per [`docs/AI-INTEGRATION.md`](docs/AI-INTEGRATION.md)). Note: `.github/agents|instructions|prompts/` are **Copilot-format reference templates consumed in place by hub skills** (e.g. `evolve-project` reads the agent personas) — nothing seeds them into submodules, and they are not dash-operational Claude subagents (only `.claude/agents/` are Task-launchable).

## SCHEMA.md protocol (Pyramid Schema)

The hub is structured by `SCHEMA.md` files — one per directory, a lintable contract of what lives where and what goes there next (framework doc: [`docs/SCHEMA-FRAMEWORK.md`](docs/SCHEMA-FRAMEWORK.md)). Orient by reading `./SCHEMA.md` and the chain down to where you're working, instead of `ls -R`.

- **Follow**: place new files per `## Placement` in the nearest `SCHEMA.md`; if nothing routes it, add the table row first, then create the file. Respect `## Forbidden`; never hand-edit `generated` entries; never descend into `terminal` ones.
- **Propagate**: creating a directory is atomic — the dir + its `SCHEMA.md` (from `templates/schema/SCHEMA.template.md`) + a row in the parent's Structure table.
- **Maintain**: any add/remove/rename updates the local `SCHEMA.md` in the same commit. `projects/SCHEMA.md` is **generated** — after registry/`.gitmodules` changes, run `tools/gen-projects-schema.py`.
- **Fleet**: `projects/*` are separate pyramids (`terminal` here). Seed one locally with `tools/seed-schema.sh <name> --apply` (then commit inside the submodule per the workflow above), or dispatch **`schema-fanout.yml`** (dry-run default; `agent_fill` runs a Claude Code OAuth pass that fills scaffold TODOs on the adoption PR branch).
- **Verify**: `python3 tools/schema_lint.py check .` — wired into the drift gate as check (h), where errors **and warnings** fail CI (the hub practices what it seeds). `check . --fix` remediates mechanical drift — registers strays with TODO purposes, prunes stale rows — then you fill in the TODOs. Gitignored ephemera belong in the tables as `generated` (absence tolerated).

## Conventions

- **Commits**: Conventional Commits — `type(scope): description` (`feat`/`fix`/`docs`/`style`/`refactor`/`test`/`chore`/`perf`/`ci`). Use `gh` CLI for GitHub operations.
- **Branches**: `feature/`, `fix/`, `docs/`, `refactor/`, `test/`.
- **README-First, README-Last**: a heavily-emphasized house rule (`AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/`). Read the nearest `README.md` for context before changing a directory, and update it after. Several directories keep their own `README.md` current as part of the change.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers.

## Where the detailed guidance lives

- `AGENTS.md` — agent working principles (simplicity-first, surgical changes, TDD), submodule/port reference tables.
- `.github/instructions/*.instructions.md` — scoped guidance (`core`, `development`, `bash`, `documentation`, `tools`, `version-control`) with `applyTo` globs.
- `docs/DASH.md` — the dash architecture (registry, surfaces, monitoring, drift gates, AI self-evolution loop).
- `docs/AI-INTEGRATION.md` — the AI layer: surfaces, Claude auth/secrets matrix, loops, fleet propagation.
- `docs/MONOREPO.md`, `docs/DEVELOPMENT.md`, `docs/ARCHITECTURE.md`, `SUBMODULES.md` — architecture and setup deep-dives.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **monorepo of ~40 Git submodules** that doubles as a self-managing **dash** (control plane) and a GitHub profile README. Every directory under `projects/` is a *separate Git repository* with its own stack, branch, and release cycle — there is no shared build system tying them together. The root repo (`tools/`, `docs/`, `.github/`, `_data/`, `pages/`, and the Jekyll site) is the machinery that manages, monitors, documents, and **standardizes** them.

**The authoritative project list is [`_data/projects.yml`](_data/projects.yml)** (the registry), cross-checked against `.gitmodules` by the drift gate — *not* this file. Don't maintain a submodule list here; read the registry. Representative/foundational submodules:

| Path | Upstream | Branch | Stack |
|------|----------|--------|-------|
| `projects/cv-builder-pro/` | `bamr87/cv-builder-pro` | `main` | React, TypeScript, Vite, Tailwind, Firebase |
| `projects/README/` | `bamr87/README` | `main` | Python, MkDocs, Wiki.js |
| `projects/scripts/` | `bamr87/scripts` | **`master`** | Bash, Python |
| `projects/zer0-mistakes/` | `bamr87/zer0-mistakes` | `main` | Jekyll theme (powers this dash) |
| `projects/it-journey/` | `bamr87/it-journey` | `main` | Jekyll, Ruby |
| `projects/skills/` | `microsoft/skills` (external) | `main`, `update = merge` | Markdown skills, MCP |

**Branch exceptions** (most submodules track `main`): `scripts` and `jekyll` track **`master`**; `sonic-pi` tracks **`dev`**; `skills` is an external `microsoft/skills` mirror (`update = merge`). Always read the branch from `.gitmodules` / the registry — never assume `main`.

`tools/`, `docs/`, `.github/`, `_data/`, and `pages/` are part of the **root** repo (not submodules).

## Submodule workflow (critical, non-obvious)

Submodules are full clones of other repos. A change inside `projects/cv-builder-pro/`, `projects/README/`, `projects/scripts/`, or `projects/skills/` is **not** committed by the root repo — you commit it *in the submodule's own repo first*, then update the pointer in root:

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
- Branches vary: `scripts`/`jekyll` track `master`, `sonic-pi` tracks `dev`, the rest track `main`. Read the branch from `.gitmodules`; don't assume `main`.
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
./tools/run-all-tests.sh       # cv test+lint+build, README pytest, mkdocs build, shellcheck of tools/ & projects/scripts/
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

The published MkDocs site (`docs_dir: projects/README/docs`) pulls from the **README submodule**. Paths like `projects/README/docs/scripts/` and `projects/README/docs/skills/` are *aggregated documentation copies* for the site — they are **not** the same working trees as the root `projects/scripts/` and `projects/skills/` submodules. Edit source in the submodules; the copies under `projects/README/docs` are generated/mirrored content.

## Quality gates

- **pre-commit** (`.pre-commit-config.yaml`): trailing-whitespace, end-of-file, check-yaml/json, markdownlint (`--fix`, MD013/MD033/MD041 disabled), shellcheck, prettier. `black` + `flake8` (max-line 120) are **scoped to `projects/README/**/*.py` only**. Install with `pip install pre-commit && pre-commit install`; CI skips shellcheck + markdownlint.
- **Husky** (`.husky/pre-commit`) runs `pnpm lint-staged`.
- **CI**: the live control-plane workflows are `build-dash.yml` (builds the Jekyll dash and deploys to Pages — the sole Pages surface), `drift-check.yml` (hard drift gate), `refresh-dash.yml` (nightly README/registry refresh PR), `update-submodules.yml` (weekly PR bumping submodule pointers *up*), `standardize-fanout.yml` (opens standardization PRs *down* into submodules from the reusable `standard-ci.yml` `workflow_call` template), `schema-fanout.yml` (opens Pyramid Schema adoption PRs *down* into submodules; optional `agent_fill` Claude Code OAuth pass fills scaffold TODOs), `actions-usage.yml` (daily commit of the Actions cost/effectiveness analytics), and `actions-review.yml` (an **Opus Claude Code reviewer** that deep-dives the worst workflows from that analytics and files optimization *issues*). The generic `unified-*.yml` suite is legacy/dispatch-only. Reusable composite actions live in `.github/actions/{ci,deployment,setup,utilities}`.

## The Dash (central command surface)

The repo is a self-managing **dash**. See [`docs/DASH.md`](docs/DASH.md). Key facts:

- **Single source of truth**: [`_data/projects.yml`](_data/projects.yml) — the project registry. To add/change a project, edit ONLY this file; every surface (portfolio, dashboard, monitor, the profile `README.md` `<!-- AUTO:projects -->` span, the drift gate) follows.
- **Dash site**: the **root** Jekyll site (`remote_theme: bamr87/zer0-mistakes`) renders the dash from the `pages/_dash/` collection (Portfolio/Dashboard/Monitor/Toolbox/Resume/Docs), published at `bamr87.github.io/bamr87/`. Local: `tools/dash serve` (docker, :4000).
- **CLI**: `tools/dash {status|audit|monitor|actions|serve|sync|foreach|run|new|adopt-release|protect|evolve|ai|gen|test|doctor}` (alias `bamr87-dash`) — reuses `setup.sh`/`run-all-tests.sh`/`update-submodules.sh`/`audit-standards.sh`/`projects/scripts/`. `dash audit` prints the per-repo standardization conformance matrix; `dash foreach <cmd>` runs a command in every submodule; `dash actions` prints GitHub Actions usage/effectiveness analytics.
- **Generator**: `.github/scripts/dash-gen` (`tools/dash-gen`) — `health` gathers live GitHub signals → ephemeral `_data/project_health.yml` (gitignored, never commit); `readme` regenerates the README AUTO span (deterministic, committable); `ai` shadow-prices local Claude Code usage per repo (`ai_activity.py`: scans `~/.claude/projects/` JSONL, persists `~/.claude/ai-activity-ledger.json`, writes gitignored `_data/ai_activity.yml` for the `/ai-activity/` page — local-only, never part of `all`/CI); `actions` analyzes GitHub Actions consumption via **PyGithub** (`actions_analytics.py`: per-workflow cost/effectiveness/waste + type grouping → **committed** `_data/actions_usage.yml` for the `/actions/` page, refreshed daily by `actions-usage.yml`); `actions-review` (`actions_review.py`) is the triage layer that closes the loop — it selects the worst workflows from that data, dedupes them against open `actions-review` issues, and emits a work order that `actions-review.yml` hands to an Opus Claude Code reviewer to file one optimization issue per candidate.
- **Drift**: `tools/check-drift.sh` — a fast, offline+API gate (no Ruby/Jekyll build in CI). Hard-fails on registry/.gitmodules parity, stray/unregistered project dirs, stale README, missing top-level READMEs, and SCHEMA.md pyramid errors or a stale generated `projects/SCHEMA.md` (check (h)); advises (non-gating) on GitHub-reality drift — renames/deletions/branch (`--remote`/`--ci`) — and standardization. The submodule checked-out-branch check is local-only (skipped when submodules aren't checked out); the internal-link check is `--links` only (needs a local `_site`).
- **AI layer**: [`.claude/README.md`](.claude/README.md) indexes it. `.mcp.json` (MCP servers) + `.claude/skills/` (drift-report, evolve-project, new-project, refresh-portfolio, run-dash, sync-project-docs, triage-attention, update-registry, **standardize-audit**, **standardize-project**, **onboard-dir**) + `.claude/commands/` (`/dash-status`, `/evolve`, `/register-project`, `/adopt-release`, `/future-features`) + `.claude/agents/feature-scout.md` + `.claude/hooks/` (Future-Features session hooks). The **`run-dash` skill's `driver.py` is the orchestration entrypoint** (per-submodule work orders). `unified-evolution.yml` runs Claude Code (`anthropics/claude-code-action`, needs `ANTHROPIC_API_KEY`). Note: `.github/agents|instructions|prompts/` are **portable Copilot templates** meant to be seeded into submodules — not dash-operational Claude subagents (only `.claude/agents/` are Task-launchable).

## SCHEMA.md protocol (Pyramid Schema)

The hub is structured by `SCHEMA.md` files — one per directory, a lintable contract of what lives where and what goes there next (framework doc: [`docs/SCHEMA-FRAMEWORK.md`](docs/SCHEMA-FRAMEWORK.md)). Orient by reading `./SCHEMA.md` and the chain down to where you're working, instead of `ls -R`.

- **Follow**: place new files per `## Placement` in the nearest `SCHEMA.md`; if nothing routes it, add the table row first, then create the file. Respect `## Forbidden`; never hand-edit `generated` entries; never descend into `terminal` ones.
- **Propagate**: creating a directory is atomic — the dir + its `SCHEMA.md` (from `templates/schema/SCHEMA.template.md`) + a row in the parent's Structure table.
- **Maintain**: any add/remove/rename updates the local `SCHEMA.md` in the same commit. `projects/SCHEMA.md` is **generated** — after registry/`.gitmodules` changes, run `tools/gen-projects-schema.py`.
- **Fleet**: `projects/*` are separate pyramids (`terminal` here). Seed one locally with `tools/seed-schema.sh <name> --apply` (then commit inside the submodule per the workflow above), or dispatch **`schema-fanout.yml`** (dry-run default; `agent_fill` runs a Claude Code OAuth pass that fills scaffold TODOs on the adoption PR branch).
- **Verify**: `python3 tools/schema_lint.py check .` — wired into the drift gate as check (h), so schema drift fails CI.

## Conventions

- **Commits**: Conventional Commits — `type(scope): description` (`feat`/`fix`/`docs`/`style`/`refactor`/`test`/`chore`/`perf`/`ci`). Use `gh` CLI for GitHub operations.
- **Branches**: `feature/`, `fix/`, `docs/`, `refactor/`, `test/`.
- **README-First, README-Last**: a heavily-emphasized house rule (`AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/`). Read the nearest `README.md` for context before changing a directory, and update it after. Several directories keep their own `README.md` current as part of the change.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers.

## Where the detailed guidance lives

- `AGENTS.md` — agent working principles (simplicity-first, surgical changes, TDD), submodule/port reference tables.
- `.github/instructions/*.instructions.md` — scoped guidance (`core`, `development`, `bash`, `documentation`, `tools`, `version-control`) with `applyTo` globs.
- `docs/DASH.md` — the dash architecture (registry, surfaces, monitoring, drift gates, AI self-evolution loop).
- `docs/MONOREPO.md`, `docs/DEVELOPMENT.md`, `docs/ARCHITECTURE.md`, `SUBMODULES.md` — architecture and setup deep-dives.

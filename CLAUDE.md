# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **monorepo composed of Git submodules**. The root is simultaneously a GitHub profile README, a documentation hub, and the container for several independent projects. Each top-level project directory is a *separate Git repository* with its own stack, branch, and release cycle — there is no shared build system tying them together.

| Path | Upstream repo | Branch | Stack |
|------|---------------|--------|-------|
| `projects/cv/` | `bamr87/cv-builder-pro` | `main` | React, TypeScript, Vite (GitHub Spark template), Tailwind |
| `projects/README/` | `bamr87/README` | `main` | Python, MkDocs, Wiki.js |
| `projects/scripts/` | `bamr87/scripts` | **`master`** | Bash, Python |
| `projects/skills/` | `microsoft/skills` (external) | `main`, `update = merge` | Markdown skills, prompts, MCP configs |

`tools/`, `docs/`, and `.github/` are part of the **root** repo (not submodules).

## Submodule workflow (critical, non-obvious)

Submodules are full clones of other repos. A change inside `projects/cv/`, `projects/README/`, `projects/scripts/`, or `projects/skills/` is **not** committed by the root repo — you commit it *in the submodule's own repo first*, then update the pointer in root:

```bash
cd projects/cv
git checkout main                      # submodules often land in detached HEAD; check out the branch first
# ...edit, then:
git add . && git commit -m "feat: ..."
git push origin main                   # pushes to bamr87/cv-builder-pro, NOT this repo
cd ../..
git add projects/cv && git commit -m "chore: update cv submodule"   # root only records the new commit SHA
```

Consequences:
- `projects/scripts/` tracks `master`, the rest track `main` — don't assume `main` everywhere.
- `projects/skills/` belongs to `microsoft/skills`; you generally consume it, not modify it.
- Don't bundle changes across multiple submodules into one PR.
- After pulling, run `git submodule update --init --recursive` if a submodule looks empty or stale.

Clone fresh with `git clone --recurse-submodules ...`; bootstrap everything with `./tools/setup-dev.sh`.

## Common commands

Run project commands **inside the relevant submodule** — each has its own dependencies.

**CV Builder (`projects/cv/`)** — Vite dev server (serves on port 5000 per the compose/`kill` config; docs sometimes cite Vite's default 5173):
```bash
cd projects/cv
npm install
npm run dev
npm run build        # tsc -b --noCheck && vite build
npm run lint         # eslint .
npm run kill         # frees port 5000
```
Note: there is **no `npm test` script** in `projects/cv/`. Tests are Cypress e2e specs under `projects/cv/cypress/e2e/` (`npx cypress run` against a running dev server).

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
- **CI**: `.github/workflows/unified-*.yml` (CI/CD, release, maintenance, evolution) plus `build-dash.yml` (builds the Jekyll dash and deploys to Pages), `drift-check.yml` (hard drift gate), `refresh-dash.yml` (nightly projects/README/registry refresh PR), and `update-submodules.yml` (weekly PR bumping submodule pointers). `build-docs.yml` (MkDocs) is **deprecated/manual-only**, superseded by `build-dash.yml`. Reusable composite actions live in `.github/actions/{ci,deployment,setup,utilities}`.

## The Dash (central command surface)

The repo is a self-managing **dash**. See [`docs/DASH.md`](docs/DASH.md). Key facts:

- **Single source of truth**: [`dash/_data/projects.yml`](dash/_data/projects.yml) — the project registry. To add/change a project, edit ONLY this file; every surface (portfolio, dashboard, monitor, the profile `README.md` `<!-- AUTO:projects -->` span, the drift gate) follows.
- **Dash site**: `dash/` is a Jekyll site using `remote_theme: bamr87/zer0-mistakes`, published at `bamr87.github.io/bamr87/`. Local: `tools/dash serve` (docker, :4000).
- **CLI**: `tools/dash {status|monitor|serve|sync|run|new|evolve|gen|test}` (alias `bamr87-dash`) — reuses `setup.sh`/`run-all-tests.sh`/`update-submodules.sh`/`projects/scripts/`.
- **Generator**: `.github/scripts/dash-gen` (`tools/dash-gen`) — `health` gathers live GitHub signals → ephemeral `dash/_data/project_health.yml` (gitignored, never commit); `readme` regenerates the README AUTO span (deterministic, committable).
- **Drift**: `tools/check-drift.sh` gates on registry/.gitmodules parity, stale README, missing READMEs, submodule branch drift, broken dash links.
- **AI layer**: `.mcp.json` (MCP servers) + `.claude/skills/` + `.claude/commands/` (`/dash-status`, `/evolve`, `/register-project`). `unified-evolution.yml` runs Claude Code (`anthropics/claude-code-action`, needs `ANTHROPIC_API_KEY`).

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

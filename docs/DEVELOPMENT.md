# Development Guide

> Prerequisites, getting the source, running the console and the site, containers, and which check to run for what you changed.

How to get the hub running on your machine, change it, and check it before a pull request. The root [`README.md`](../README.md) is a GitHub profile; this is the contributor's entry point. Contribution process: [`CONTRIBUTING.md`](../CONTRIBUTING.md). Where everything lives: [`SCHEMA.md`](../SCHEMA.md), the authoritative map, and [`CATALOG.md`](../CATALOG.md), the index of what the hub provides.

## What this repository is

The root is the **control plane** for ~45 projects, each a Git submodule under `projects/` with its own stack, branch and release cycle ([`SUBMODULES.md`](SUBMODULES.md)). The root itself is the machinery that manages them:

| Part | Where |
| --- | --- |
| The project registry and every other registry | `_data/` — `projects.yml` is the single source of truth |
| The dash CLI, gates and generators | `tools/` (`tools/dash`), `.github/scripts/dash-gen/` |
| The Harness Console — the local control plane **and**, built static, the public site | `tools/console/` ([CONSOLE-PAGES.md](CONSOLE-PAGES.md)) |
| The loops, gates and reusable workflows | `.github/workflows/` |
| What every fleet repo is built to, and the kits that seed it | `specs/`, `templates/` |
| The site's content | `_data/profile.yml`, `pages/profile/`, `pages/posts/` |
| The fleet dev stack | `docker-compose.yml`, `compose/` ([CONTAINERS.md](CONTAINERS.md)) |
| The AI layer | `.claude/` (skills, commands, agents, hooks), `.agents/` (the same skills for other agents), `.mcp.json`, `fleet.manifest.yml` (this repo's AI lanes in the shared `fleet/v1` vocabulary), [`AGENTS.md`](../AGENTS.md), [`CLAUDE.md`](../CLAUDE.md) |

## Prerequisites

| Tool | Why |
| --- | --- |
| Git | Everything; submodules need a recent 2.x |
| Python 3.12+ with PyYAML | The dash CLI, generators, gates and the console (which bootstraps its own venv) |
| Node, current LTS (≥ 22) | The console's page and the public site build (React Router 8 needs ≥ 22; the fleet's `NODE_VERSION` of 20 is too old for it) |
| `gh`, signed in | Anything that reads or writes GitHub (`gh auth login`) |
| Docker with Compose | Optional: the containerized workspace, the fleet dev stack, the observability planes |
| bash ≥ 4 | `tools/check-drift.sh` (macOS ships 3.2; `brew install bash`) |
| `pre-commit`, `shellcheck` | The hooks and the shell gate |

`tools/setup.sh` installs and wires most of this (`--help` for its options; `--skip-terminal` skips the macOS terminal step, which delegates to [bashOS `chui/`](https://github.com/bamr87/bashos/tree/main/chui), formerly bamr87/chui).

## Get the source

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
cp .env.example .env          # ports and optional credentials; .env is never committed
pip install pre-commit && pre-commit install
```

Already cloned without submodules? `git submodule update --init --recursive`. Submodules land in detached HEAD — check out the branch `.gitmodules` declares before working in one, and commit there first ([`SUBMODULES.md`](SUBMODULES.md)).

`.env` needs no edits for a first run: every port has a default. Credentials (`GH_TOKEN` / `FLEET_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`) only matter for operations that call GitHub or Claude, and the console can be handed them on its Credentials page instead. The token contract is in [`_data/fleet.yml`](../_data/fleet.yml) and [AI-INTEGRATION.md](AI-INTEGRATION.md).

## Run it

```bash
tools/dash                    # every command, one line each
tools/dash status             # submodules, registry, drift at a glance
tools/dash console            # the Harness Console, live — http://127.0.0.1:4001
tools/dash serve              # the public site, built static exactly as Pages publishes it — http://127.0.0.1:4000
tools/dash tui                # the terminal dash
```

The console and the public site are one React app (`tools/console/web/`); `cd tools/console/web && npm run dev` serves it with hot reload against a running console. See [CONSOLE-PAGES.md](CONSOLE-PAGES.md) for the three ways the page runs and what the static build never publishes.

### In containers

```bash
tools/dash up                 # the shared core: devenv, console, one Postgres, one Redis
tools/dash up it-journey      # …plus a submodule, as its own compose project
tools/dash ps                 # what is running fleet-wide
docker compose exec devenv bash
docker compose up -d phoenix  # traces — http://127.0.0.1:6006
tools/dash observe up         # logs + metrics — Kibana :5601, Grafana :3001
```

The workspace image (`.devcontainer/`) is also a VS Code Dev Container; its post-create step runs `tools/setup.sh --skip-deps --local`. Ports come from one registry, [`_data/ports.yml`](../_data/ports.yml); [CONTAINERS.md](CONTAINERS.md) and [FLEET-COMPOSE.md](FLEET-COMPOSE.md) explain the fleet stack.

## Check it

| What changed | Run |
| --- | --- |
| Anything | `tools/run-all-tests.sh` — the hub's checks plus every checked-out submodule's own suite (skips what lacks deps, and says why) |
| Registry, `.gitmodules`, a `SCHEMA.md`, README, workflows | `tools/check-drift.sh` — the gate CI runs (bash ≥ 4) |
| A directory's contents | `python3 tools/schema_lint.py check .` (`--fix` registers strays) |
| `tools/console/` | `python3 tools/console/test_console.py && python3 tools/console/test_pages.py`; `cd tools/console/web && npm run build` |
| The site or a dash page | `CONSOLE_BASE=/ OUT=_site tools/console/build-pages.sh`, serve `_site`, then `node verify/runner.mjs` ([VERIFICATION.md](VERIFICATION.md)) |
| dash-gen | `python3 .github/scripts/dash-gen/test_<module>.py` |
| Shell | `shellcheck --severity=warning tools/*.sh` |
| Markdown | one paragraph per line: `python3 tools/unwrap-prose.py --check <files>` (`--write` fixes; `tools/install-prose-hook.sh` runs it on every commit, in every repo) |

Before a pull request: the checks for what you changed pass, generated files are regenerated rather than hand-edited (`projects/SCHEMA.md`, `CATALOG.md`, `_data/specs.yml`, `compose/overrides/`), the nearest `README.md` and `SCHEMA.md` reflect the change, and the commit message is a Conventional Commit. Dependencies are always-latest: no exact pins and no committed lockfiles ([DEPENDENCIES.md](DEPENDENCIES.md)).

## Editors

`.vscode/` carries the shared settings, tasks and launch configurations — notably the raised `git.detectSubmodulesLimit` the submodules need. `home.code-workspace` opens the hub together with related clones as one multi-root workspace.

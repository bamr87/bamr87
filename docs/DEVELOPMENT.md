# Development Setup

Local setup for the hub. The projects under `projects/` are separate repositories with their own toolchains — run their commands **inside the submodule**, and read a submodule's branch from `.gitmodules` rather than assuming `main`.

Submodule mechanics (commit in the submodule, then bump the pointer) live in one place: [`../SUBMODULES.md`](../SUBMODULES.md). The architecture lives in [DASH.md](DASH.md).

## Prerequisites

| Tool | Why | Notes |
| --- | --- | --- |
| git 2.13+ | submodules | `git clone --recurse-submodules` |
| Docker + Compose | the container-first path | `devenv` is the workspace container |
| Ruby 3.3 | the Jekyll dash site | only for local `dash serve` outside Docker |
| Python 3.12 | `dash-gen`, the drift gate, schema lint | |
| Node 20 | the JS/TS projects | |
| `gh` CLI | every GitHub operation, incl. fan-outs | must be authenticated |

Versions come from [`_data/fleet.yml`](../_data/fleet.yml) (`toolchain:`), which is also what reusable CI resolves against — so bumping one there reaches the whole fleet. Read them with `tools/dash config show toolchain`.

## Bootstrap

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
./tools/setup.sh              # cross-platform: packages, submodules, venvs, script CLIs
./tools/setup.sh --dry-run    # preview first (same as `tools/dash doctor`)
```

If a submodule directory looks empty or stale after a pull:

```bash
git submodule update --init --recursive
```

## Containers

`docker-compose.yml` defines the full environment; `devenv` is the primary workspace (repo mounted at `/workspace`).

```bash
docker compose up -d devenv
docker compose exec devenv bash
docker compose up -d console           # the Harness Console — http://127.0.0.1:4001 (or: tools/dash console)
docker compose up -d phoenix           # Phoenix traces — http://127.0.0.1:6006 (tools/dash lake export ships traces to it)
docker compose --profile admin up -d   # adds pgAdmin
docker compose down -v                 # stop and wipe volumes
```

The `console` service is the local control plane's **front end**: it renders every committed fleet signal, runs the allowlisted `tools/dash` operations as jobs with live logs, dispatches the control-plane workflows, and edits the `harnesses:` contract — dry-run by default, confirm-gated for anything that writes to GitHub, never a commit. Its credentials come from `.env` (`FLEET_TOKEN` / `GH_TOKEN` / the Claude tokens, by name). See [HARNESS-OPS.md](HARNESS-OPS.md) and [`tools/console/README.md`](../tools/console/README.md).

The `phoenix` service is the local stack's trace store ([Arize Phoenix](https://github.com/Arize-ai/phoenix)): `tools/dash lake sync` extracts the fleet's GitHub records (runs, jobs, steps, run logs, issues, workflow files, `.factory/` blueprints) into the gitignored `.dash-lake/fleet.sqlite`, and `tools/dash lake export [--local]` turns the agent runs — and, optionally, this machine's Claude Code sessions — into OpenInference traces you browse at :6006. The console's **Traces** tab drives both.

Copy `.env.example` → `.env` before the first run. Ports and services are tabulated in [DASH.md](DASH.md) — that table is maintained in exactly one place.

## The everyday loop

```bash
tools/dash status              # submodules + registry + drift, at a glance
tools/dash serve               # the Jekyll dash on :4000 (docker)
tools/dash audit               # per-repo standardization conformance
tools/dash foreach <cmd>       # run a command in every submodule
tools/check-drift.sh --report  # explain every drift finding
./tools/run-all-tests.sh       # each project's own suite, skipping what isn't installed
```

`tools/dash` is the entry point for everything else (`triage`, `remediate`, `reconcile`, `secrets`, `config`, `estimate`); run it with no arguments for the full list.

## Before you open a PR

- `tools/check-drift.sh` must be green — it gates every PR. `/drift-report` explains failures in plain language.
- Shell changes: `shellcheck --severity=warning`.
- Workflow changes: `actionlint` (the drift gate runs it over every workflow, with no exemptions).
- Markdown: one paragraph per line. You should never have to think about this: CI self-heals it on a pull request (the `markdown-oneline` gate unwraps the prose and pushes the fix to your branch), and running `tools/install-prose-hook.sh` once installs a global `pre-commit` hook that fixes it in every repo before the commit exists — so the gate stays green without a build. To fix by hand: `python3 tools/unwrap-prose.py --write`.
- Structure changes: update the directory's `SCHEMA.md` in the same commit, then `python3 tools/schema_lint.py check .`.

## Docs sites

The hub publishes the **Jekyll dash** (`build-dash.yml` → GitHub Pages) — that is the only Pages surface the hub owns. The MkDocs documentation site belongs to the README submodule and builds from its own config:

```bash
cd projects/README && mkdocs serve      # or: docker compose up -d mkdocs
```

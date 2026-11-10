# VS Code: the harness from F5

> Every surface of the control plane — the container plane, the Harness Console, the public site, the lake and log planes, the generators, the local loop runner, the gates, and every submodule — as launch configurations and tasks, each one calling the same `tools/dash` entry point the CLI, the console's job API and CI run.

[`launch.json`](launch.json) is the run/debug menu, [`tasks.json`](tasks.json) holds the silent helpers it leans on plus the hub gate, [`settings.json`](settings.json) carries what the repo needs from the editor, and [`extensions.json`](extensions.json) is one list the host and the dev container agree on.

## One front door, two planes

Every entry goes through [`tools/dash`](../tools/dash) (the command router, [docs/DASH.md](../docs/DASH.md)) or a tool's own entry point, never a second implementation. Two things decide where a process runs:

| Plane | Entry | What it is |
| --- | --- | --- |
| **The shared core** | `tools/dash up` | compose project `fleet` from [`docker-compose.yml`](../docker-compose.yml): `devenv` (the workspace), `console` (:4001), `db`, `redis`; Phoenix, MkDocs, pgAdmin, MCP and the log planes behind profiles ([docs/CONTAINERS.md](../docs/CONTAINERS.md)) |
| **Per-project stacks** | `tools/dash dev up <project> [--debug]` | the submodule's own `docker-compose.yml` as its own compose project on `fleet-net`, ports from [`_data/ports.yml`](../_data/ports.yml) through the committed [`compose/overrides/`](../compose/overrides/) ([docs/FLEET-COMPOSE.md](../docs/FLEET-COMPOSE.md); drift check (m) gates the map) |

The hub's own tools run **natively** where that is what they are built for: the console (`tools/dash console`, its own `.venv-console`), the TUI (`.venv-tui`), the MCP server (`.venv-mcp`), the generators and the gates (`python3` with PyYAML). Submodules with no compose file of their own run **inside `devenv`** by `docker compose exec`, on the workspace port block. Nothing installs on the host beyond those venvs, Node for the console's page, and Playwright for `verify`.

The debug entries are real debuggers, not terminal runs: the console's FastAPI under `debugpy` on **:4004** (so it never fights the compose console on :4001), the page under Vite on **:5173** with source maps in Edge, a generator or hub test file under `debugpy`, and `debugpy` **attach** into the Django and FastAPI containers that ship a debug layer.

## Groups

The groups follow the console's own sections, in its order.

| Group | What it covers |
| --- | --- |
| **0-fleet** | `tools/dash up` (core, or core + a profile), `tools/dash dev up` one, several, or `--debug`; `ps` fleet-wide and per project; `ports`; `apps` (every frontend with its live and local address) `apps check` (does each answer, can the shell frame it) and `apps plan` (every repo's frontend component and what it is owed); `logs`; `smoke check/record`; `docker view --write`; `doctor`; `down` |
| **1-console** | the Harness Console three ways (native `debugpy` on :4004 with the page's dev server proxied to it, the compose service on :4001, native with `CONSOLE_RELOAD=1`), the page in Edge against either, attach to Edge, the TUI native or in Docker, the MCP layer (list tools, HTTP on :4002, compose + tunnel URL, live smoke test); the compound **Console: full stack** starts API + page + browser together |
| **2-site** | `tools/dash serve` (the console built static on :4000), Edge against it, the CI-exact build into `_site`, `tools/dash verify` (all scenarios, one headed, or the list) |
| **3-observe** | the lake (`sync`, `sessions`, `review`, `status`, `export` dry run or ship to Phoenix :6006), the log plane (`observe status/up/ship/down`, the Claude Code OTel status), the code index (`index status/coverage/search`), the content atlas (`report`, `sync`, `brief`) |
| **4-generate** | `tools/dash gen <subcommand>` from a picker, any `tools/dash` subcommand typed, and the registry generators the console's Operations page lists: status, monitor, harnesses (live, offline, gaps), harness, the agent inventory (`tools/dash agents`, and `--check`, drift check (p); [docs/AGENT-EFFICACY.md](../docs/AGENT-EFFICACY.md)), workflows list/health, features fleet, issues, triage, actions, AI usage, remediate, reconcile, spec fleet, config show, secrets plan + keys status, the projects triage + Fleet board backfill plan (dry run), and the PM review (`tools/dash pm`: the read-only review, its Fleet project plan and the release train) |
| **5-loops** | the local loop runner (`loop list/doctor/plan/run --rehearse/run/budget`, [docs/JEV.md](../docs/JEV.md)), the conflict sweep (`conflicts sweep`, with and without `--dry-run`), `scout plan`, `evolve`, scaffolding a workflow inside the standards (dry run), an issue's evidence bundle, harness refinement (`refine surface check`, `refine plan`, and the incident reflector `refine reflect --rehearse` ($0) and `refine reflect` (one capped session that previews and never files), [docs/HARNESS-REFINEMENT.md](../docs/HARNESS-REFINEMENT.md)) |
| **6-verify** | the hub gate: `check-drift.sh --report`, a picker over every individual check, `tools/dash test`; native `debugpy` on the current test file, one unittest case, pytest on the current file, any Python file; the console's test files; the current test file inside devenv |
| **7-projects** | compose-hosted submodules through `tools/dash dev`: it-journey (:4010), gitorio dev/preview (:5113/:5114), law-ai backend/frontend (:8110/:5110), djangoerp web (:8111), fredgar-ai web/frontend/frontend-prod (:8112/:5111/:5115), bashos (:8116), zer0-cms (:8117/:8118); `debugpy` **attach** for law-ai backend/worker (:5713/:5714), djangoerp web/worker (:5710/:5711), fredgar-ai web (:5712) |
| **8-workspace** | devenv-hosted submodules on the workspace block: Jekyll for bamr87.github.io, lifehacker.dev, zer0-mistakes, year-of-ai.github.io, ai-world-view.github.io, bash-365.com (:4040–:4045, livereload 35760–35765); Vite for cv-pro/app (:5000), rewind-arcade/arcade (:5001), gitorio/packages/gitnexus (:8080); MkDocs for projects/README in devenv (:8000) or the compose service (:8001) and `build --strict`; a devenv shell; any command in any submodule |
| **9-ext** | VS Code extensions (vs-sonic-pi, zpl-viewer, zer0-cms): compile inside devenv, Extension Host on the host |
| **10-cli** | CLIs and suites in devenv: bashos, ocrmd, wtd and gwtp (both under gitorio/packages), bashcrawl `npm test`, githubai pytest, pytest or an npm script in any submodule, a scripts/ file, skills' Agents.md |

Each devenv entry installs what it needs on first use (`bundle install`, `npm install`) inside the container, so a fresh clone works without a manual step; the install lands in the container's volumes, never on the host.

## Ports

Ports are never invented here. The `/docker/` page (`tools/dash docker view`) joins this file to the port registry by the `:NNNN` in each entry's name, so the port stays in the name.

| Source | Ports |
| --- | --- |
| `docker-compose.yml` (the hub) | **4000** site · **4001** console · **4002** MCP · **4003** tunnel metrics · **6006**/4317 Phoenix · **8001** MkDocs · 3000 Wiki.js · 5050 pgAdmin · 5432 Postgres · 6379 Redis · 9200 Elasticsearch · 5601 Kibana · 3001 Grafana · 9090 Prometheus · 4318 OTel · 6333 Qdrant |
| this file (native debug) | **4004** the console under `debugpy` · **5173** the page's Vite dev server · 9222 Edge remote debugging |
| `_data/fleet.yml` `containers.ports.workspace*` (what devenv publishes) | **4040–4049** Jekyll · **35760–35769** livereload · **5000–5001** Vite · 8000 MkDocs · 8080 gitnexus |
| `_data/ports.yml` (compose-hosted projects) | 4010–4039 Jekyll · 5000–5199 frontends · 8100–8149 APIs · 5700–5749 debugpy · 5430–5469 / 6380–6399 per-project stores |

A seam to know about: `_data/ports.yml` also lists the devenv-hosted sites on 4012/4013/5175, which is the map `tools/dash dev up hub` (compose project `fleet-hub`) would publish. The entries here use `tools/dash up` instead — the `fleet` project that is actually running — whose devenv publishes the workspace block above, so those sites are on 4040+ here. Two hub projects cannot run at once (both publish 4000/4001), so this file never starts `fleet-hub`, and `--all` is avoided for the same reason.

If `devenv` was started before a port mapping existed, recreate it with the task **Docker: recreate devenv**.

## Tasks

| Kind | Tasks |
| --- | --- |
| ensure / bootstrap (silent preLaunch) | `Fleet: up core`, `Fleet: up core + traces`, `Fleet: up core + docs`, `Fleet: dev up law-ai / fredgar-ai / djangoerp (debug)`, `Console: ensure compose service`, `Console: bootstrap venv` (creates `.venv-console` and installs `tools/console/requirements.txt` + pytest only when something is missing; `Console: upgrade venv` re-resolves to latest), `Console: web install`, `Console: web dev server (→ :4001 / → :4004)` (background, waits for Vite's `Local:`), `Verify: install Playwright`, `devenv: compile vs-sonic-pi / zpl-viewer / zer0-cms` |
| the gate (`test` group) | `Gate: drift (report)` / `(full)`, `Test: run all` (the default test task), `Gate: schema lint`, `docs index`, `prose (current file)`, `specs data`, `catalog (main only)`, `generated guard (JEV)`, `workflows lint`, `governance lint`, `shellcheck` (into the Problems panel), `actionlint`, and `Gate: all offline checks` running them in sequence; `Test: console`, `Test: dash-gen (all fixture tests)`, `Test: current file (native)`, `Test: CV projection (pytest)`, `Lint: Markdown Files` |
| fleet / docker chores | `Fleet: down core`, `Fleet: ps`, `Fleet: sync port allocation`, `Console: web build / typecheck`, `Observe: up`, `devenv: bundle install / npm install (pick a submodule)`, `Django: migrate / createsuperuser`, `Docker: core logs / rebuild core images / recreate devenv / prune` |

## Inputs

Pickers are generated from the registries by hand and must follow them: `fleetProject` and `fleetProjects` from `_data/ports.yml` (`tools/dash dev list`), `submodule` from `.gitmodules`, `hubProfile` from `docker-compose.yml`'s profiles, `dashGenCommand` from `tools/dash-gen --help`, `contentSite` from `_data/fleet.yml` `content.sites`, `verifyScenario` from `verify/scenarios/`, `loopId` from `tools/dash loop list`, `refineLoop` from the `tools/jev/steps/` directories, `gateCommand` from AGENTS.md "Stack & commands". When a submodule, site, scenario or loop is added, add it to the matching picker in the same change.

## Settings and extensions

`settings.json` is machine-neutral: the raised `git.detectSubmodulesLimit` the ~40 submodules need, the interpreter the debug entries use (`.venv-console`), Docker Compose v2, file associations for the fleet's stacks, soft wrap for the one-paragraph-per-line Markdown, and the ignores that keep watching and search off the venvs, the lake, the compose overrides, the built site and page, and the evidence bundles. Personal preferences (font, line height, minimap, auto-save) belong in [`home.code-workspace`](../home.code-workspace) or user settings. `extensions.json` is the union of what the dev container installs and what the launch and task entries rely on, so the host and the container agree.

## Governance

Constitution § 20 (proposed amendment `editor-front-door`) makes this directory a front door: entries call `tools/dash` or a tool's own entry point, pickers and ports follow the registries, and a new surface adds its entry in the same PR. [`tools/test_vscode_launch.py`](../tools/test_vscode_launch.py) is the gate (run by `tools/run-all-tests.sh`): the four files parse, every task and input resolves, each picker equals its registry, every named port is one its plane publishes, and nothing calls `fleet-dev.sh` directly or starts `fleet-hub`. Fleet repos are held to the same idea by UPS-REPO-40 ([specs/REPOSITORY.md](../specs/REPOSITORY.md), audited by `tools/conformance.py`) and surfaced by `dash audit` as the `vscode` artifact; this directory is the reference until a `templates/vscode/` kit exists. [`SCHEMA.md`](SCHEMA.md) lists the files and the placement rules.

## Notes

- The console's compose service and the native debug session coexist (:4001 and :4004). `Console: native with auto-reload` and `MCP: streamable HTTP server` take :4001 and :4002 and so expect the compose `console` / `mcp` services stopped first.
- `tools/dash dev up` projects join `fleet-net`; the shared core is on `fleet`. A project whose compose points at the hub's Phoenix by alias (law-ai, bashos) reaches it only through the `fleet-hub` layer, which these entries do not start; the project still runs, without traces.
- The pre-2026 configurations that targeted repositories this one no longer contains (barodybroject, PostHog, lawmode, books, gitnexus as a top-level submodule) are gone; recover them from git history if ever wanted.

Last modified: 2026-11-02

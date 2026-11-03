---
schema: '0.1'
coverage: listed
---

# SCHEMA — .vscode

> The editor as a front door to the harness (constitution § 20): launch configurations and tasks that call `tools/dash`, a tool's own entry point, or `docker compose` against the hub's services — never a second implementation — plus the machine-neutral settings and the extension list the dev container shares.

## Conventions

- Every entry calls `tools/dash <cmd>`, a tool's own entry point (`tools/console/run.sh`, `tools/check-drift.sh`, `verify/runner.mjs`, `.venv-console/bin/python`), or `docker compose` against `docker-compose.yml`; `tools/fleet-dev.sh` is reached only through `tools/dash dev`, and no entry starts the `fleet-hub` pseudo-project or `dash dev up --all` beside the running `fleet` core.
- Ports and names are never invented here: compose-hosted ports from `_data/ports.yml`, workspace ports from `_data/fleet.yml` `containers.ports.workspace*`, hub ports from `docker-compose.yml`, projects from `.gitmodules`, scenarios from `verify/scenarios/`, sites from `fleet.yml` `content.sites`. A picker is held equal to its registry by `tools/test_vscode_launch.py`.
- An entry's name carries its port as `(:NNNN` so `tools/docker_view.py` can join it to the port registry for the `/docker/` page; a debugger attach carries the port structurally in `connect.port`.
- Groups are `<n>-<name>` in the console's section order; a new surface adds its entry and a line in `README.md` in the same change (README-Last).
- JSONC: line comments only, so the hub's own parsers (`docker_view.py`, `conformance.py`, the parity test) can strip them.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What each group covers, the two planes, the port sources, the tasks and inputs, the known seam | required |
| `launch.json` | file | The run/debug menu: every harness surface as a configuration, grouped in the console's order; `inputs` are the pickers; `compounds` start a stack | required |
| `tasks.json` | file | The silent pre-launch helpers (ensure core, bootstrap venvs, dev servers, compiles), the hub gate one task each, fleet and docker chores | required |
| `settings.json` | file | Machine-neutral workspace settings: the submodule cap, the debug interpreter (`.venv-console`), Compose v2, associations, excludes; personal preferences live in `home.code-workspace` | required |
| `extensions.json` | file | The recommended extension set — the union of `.devcontainer/devcontainer.json` and what the entries rely on | required |

## Placement

- New dash subcommand, loop, gate, scenario, site or submodule → its configuration in `launch.json` (right group, port in the name), any helper in `tasks.json`, the picker option, and the `README.md` line.
- A new picker → `inputs` in `launch.json` (or `tasks.json` when only a task uses it) and its registry named in `README.md` "Inputs"; add the equality check to `tools/test_vscode_launch.py`.
- Anything else VS Code wants in this directory is machine-local and gitignored (`.gitignore` tracks exactly these five files).

## Forbidden

- No direct `tools/fleet-dev.sh`, no `dash dev up hub`, no `dash dev up --all`, no hand-picked port.
- No personal editor preferences (font, line height, auto-save) — they belong in `home.code-workspace` or user settings.
- No credential, token or `.env` value, and no path outside this checkout.

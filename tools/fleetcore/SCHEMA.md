---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/fleetcore

> The core the Harness Console (browser), the terminal dash (TUI) and AI agents (MCP) share: the fleet views, keys v1, the bashOS palette, the console job-API client and the `fleet` MCP server, so every surface renders one model and runs one runtime (docs/TERMINAL-FRAMEWORK.md §10).

## Conventions

- Pure Python on the standard library + PyYAML. No web framework, no Textual import at module level (`theme.textual_themes()` imports it lazily), so either surface and the tests can load any module.
- A surface consumes this package; it does not copy from it. A view, key or colour both surfaces show is defined here once.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What the core is, which surface reads what, and how the TUI joins the console runtime | required |
| `__init__.py` | file | Package marker (`from fleetcore import …` with `tools/` on the path) | required |
| `fleet.py` | file | The data layer: registry ⨝ `project_health.yml` ⨝ `fleet_triage.yml` ⨝ `harness_health.yml`, the inbox and per-repo drill-down, source freshness, filters and sorts — degrading cleanly when any signal is absent | required |
| `host.py` | file | Docker inventory over every `DASH_DOCKER_HOST` endpoint, attributed to registry rows by the UPS-OPS-17 label, then by name | required |
| `nodes.py` | file | Where each hub workload runs: `_data/fleet.yml` `nodes:` resolved against `docker-compose.yml` (edge-bound, dependency-direction, durable-data and link-port rules), the plan against running containers, the per-node compose overlays and OpenTofu inputs (`dash node`, `dash infra`; ADR 0003) | required |
| `views.py` | file | `dash_view()` / `docker_view()` — the views as plain data, filtered and sorted by `fleet.py`'s own functions; the console serves them at `/api/fleet` | required |
| `apps.py` | file | The app portal's launcher (`fleet-launcher/v1`, ADR 0005): every registry `frontend:` block joined to its live address and its compose-hosted dev stack's ports in `_data/ports.yml`, the verify kit's device matrix, and the origins the console's Content-Security-Policy admits; `python3 -m fleetcore.apps` is `tools/dash apps` | required |
| `loopjob.py` | file | The `loop-run` job (the JEV loop runner started from the console) read once: its `--json` run record or, before one exists, its status lines → the fields the page and the TUI render (`parse_log`, `summary_lines`) | required |
| `keys.py` | file | keys v1 as data — the TUI builds its Bindings from it and the console serves it at `/api/keys` | required |
| `theme.py` | file | The bashOS palette as tokens → console CSS (`/theme.css`) and Textual themes (`bashos-dark` / `bashos-light`) | required |
| `client.py` | file | Stdlib client for the console's job API over http:// or unix:// (`DASH_CONSOLE_URL`) — how the TUI and the MCP server submit jobs to the same runtime the browser uses | required |
| `mcp_server.py` | file | MERGED into `tools/console/mcp_layer/`: its tool functions are reused there; running it delegates to the layer (`FLEET_MCP_STDLIB=1` keeps the old stdlib loop) | required |

## Placement

- A new derived view or KPI → a pure function in `fleet.py` (case in `tools/test_tui_fleet.py`), exposed through `views.py`; then each surface renders it.
- A new fact about where a frontend runs (a target kind, a launcher field) → `apps.py` (case in `tools/test_fleetcore_apps.py`); the Apps page, `tools/dash apps` and `tools/frontend_registry.py launcher` all read that one projection.
- A new key → `keys.py` (case in `tools/test_fleetcore.py`); map its action in `tools/tui/app.py` `KEY_ACTIONS` and the page's `KEY_DO`.
- A new colour role → `theme.py` `TOKENS` + `CSS_ROLES`.
- A new agent capability → a tool in `tools/console/mcp_layer/server.py` over an existing view or console route (case in `tools/test_fleetcore.py`); never a path that skips the console's allowlist.

## Forbidden

- No writes and no subprocesses other than `docker ps`. Running anything belongs to the console's allowlist (`tools/console/core.py` `OPS`), reached through `client.py`.
- No credentials stored here; `client.py` reads `DASH_CONSOLE_TOKEN` from the environment and sends it only to the console.

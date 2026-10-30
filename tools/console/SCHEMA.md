---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console

> The Harness Console — and, built static, the public site at bamr87.github.io/bamr87 (docs/CONSOLE-PAGES.md): the local control plane's credentialed, write-capable front end (FastAPI + a React/Mantine page, with the terminal dash embedded) wrapping the allowlisted `tools/dash` operations — docs/HARNESS-OPS.md.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How to run the console (native venv or compose), what it can and cannot do | required |
| `core.py` | file | Pure logic: committed-state loader, the operation ALLOWLIST, the job manager, the comment-preserving fleet.yml config editor (`CONFIG_SECTIONS`), and the credential layer (`CREDENTIALS`, process env, `.env`, `gh auth login`), the content-atlas + editorial-plan adapters over dash-gen's `content_atlas.py`, and the Work board adapters over dash-gen's `work_board.py` (board, preview, apply: label moves through a writer the route supplies, `work_queue.yml` and `roadmap.yml` in the working tree) — no web framework, testable on PyYAML alone | required |
| `app.py` | file | FastAPI routes over core.py, the CSP, and the page fallback (every non-API path serves `web/dist`) (`/api/project/{name}`, `/api/tui` + `/api/tui/status`, `/api/theme`, `/api/state`, `/api/ops`, `/api/jobs`, `/api/contract`, `/api/config`, `/api/auth` + `/api/auth/credential` + `/api/auth/github`, `/api/capabilities`, `/api/lake` + `/api/lake/runs` + `/api/lake/lines`, `/api/content` + `/api/content/{site}/docs` + `/api/content/{site}/brief`, `/api/editorial/decision` + `/api/editorial/{site}`, `/api/work` + `/api/work/preview` + `/api/work/apply` + `/api/work/item`, `/api/github/repos/{owner}/{repo}/pulls/{number}/specs`); `/api/fleet`, `/api/fleet/docker`, `/api/keys`, `/theme.css` serve the core shared with the TUI (`tools/fleetcore`); Host allowlist + optional bearer-token guard | required |
| `run.sh` | file | Bootstraps `.venv-console` at latest and execs uvicorn (`tools/dash console`, the compose `console` service) | required |
| `github_link.py` | file | GitHub through the console's OAuth App: the device and browser (state + PKCE) flows, delivering the token to the session / gh / `.env`, and fleet repo management — reads anywhere (including `pull_specs`: the spec packages a PR changes, read at its head), confirm-gated writes (issues, runs, workflows) only to repos the hub owns, an action log; never a merge, delete or push. Stdlib HTTP, so tests swap `_http` | required |
| `tui_bridge.py` | file | The Terminal page's bridge: runs the terminal dash (`tools/tui/app.py`) on a pty and relays it over the `/api/tui` WebSocket — Host + Origin checks, the hello-frame token, the session cap, process-group hang-up | required |
| `serve.py` | file | One uvicorn server on the TCP port AND `CONSOLE_UDS` — the Unix socket the `tui` service reaches the same runtime through | required |
| `requirements.txt` | file | Always-latest deps: dash-gen's requirements + fastapi, uvicorn, ruamel.yaml, websockets (`/api/tui`), the TUI's requirements (Textual, for the Terminal page), the OpenTelemetry SDK + OTLP/HTTP exporter (lake export) | required |
| `site_docs.py` | file | The site's own documents — `_data/profile.yml`, `pages/profile/*.md`, `pages/posts/*.md` and the public registries (`PUBLIC_DATA`) — served live at `/api/site*` + `/api/data/{name}` and written by `snapshot.py`, so both faces read one source | required |
| `snapshot.py` | file | Builds the PUBLIC site's data: every GET document the page reads, rendered by the console's own functions, written as static JSON under `snapshot/` — never the lake, a credential, a local probe, a local path or a draft — plus a page per route, `404.html`, sitemap, feed and theme (docs/CONSOLE-PAGES.md) | required |
| `build-pages.sh` | file | Builds the public site: the page with the Pages base path and `VITE_STATIC=1`, the diagrams, then `snapshot.py` (`build-dash.yml`, `tools/dash serve`, `verify/verify.yml`) | required |
| `test_pages.py` | file | The public site's guarantees — nothing local/secret/draft in the snapshot, a page per app route, the retired URLs kept, the diagram sandbox, and the remote-page door (CORS only while a token is required) | required |
| `test_console.py` | file | Fixture tests — allowlist refusals, argv shapes, confirm gate, job manager, state degradation, multi-section config round-trip, credential handling (values never returned, `.env` only on confirm, the kill switch), the page's CSP and fallback, the Terminal socket's Host/Origin/token refusals, the project drill-down | required |
| `test_tui_bridge.py` | file | The Terminal WebSocket — Origin/Host/token checks and every refusal code (4403/4400/4401/4501/4429) before a process exists, the Pages origin only with a token, and an admitted session relaying both ways on a real pty, clamped resizes, the exit code, and a whole-process-group hang-up | required |
| `test_health_autostart.py` | file | Startup health refresh — the `health` job starts when `_data/project_health.yml` is missing, undated or stale and not when fresh, the timeout cancels it, failures never block startup, `CONSOLE_AUTO_HEALTH=0`, and the FastAPI lifespan wiring | required |
| `mcp_layer/` | dir | The console's HTTP API as an MCP server (official `mcp` SDK): `server.py` (read tools, resources, guarded write tools behind `HARNESS_MCP_ALLOW_WRITES`, stdio and bearer-authenticated streamable HTTP on loopback) and `client.py` (stdlib HTTP client; token from env or `.env`, never printed) — docs/mcp-layer.md | required |
| `live.py` | file | Builds the `/api/live` snapshot for the `/live` page (sessions, Claude live usage, jobs, spend, health, deep dive) | required |
| `subscription.py` | file | The Claude subscription as a discounted rate off API list prices: API-equivalent estimate vs the prorated flat fee per window (effective discount, rate multiplier, value multiple), usage-pace headroom, metered API spend kept separate — never summed | required |
| `live_collector.py` | file | Host-side collector writing `.dash-live/sessions.json` (the container cannot see host Claude processes) | required |
| `mcp.sh` | file | Bootstraps `.venv-mcp` from `requirements-mcp.txt` and execs the MCP server (`tools/dash mcp`, `.mcp.json` `fleet`; `--http`, `--tunnel`, `--fleet-compat`) | required |
| `requirements-mcp.txt` | file | The MCP layer's dependencies (`mcp`, `uvicorn`), always-latest | required |
| `test_subscription.py` | file | Subscription-discount model tests: the 24 h worked example, degraded inputs, honest headroom without plan-limit data, metered N/A, the `/api/state` and `/api/live` blocks | required |
| `test_mcp_layer.py` | file | MCP layer unit tests — mocked HTTP through the real protocol: writes hidden by default, destructive annotations and the confirm refusal, result trimming, tool errors without the token, HTTP bearer + Host checks | required |
| `smoke_mcp_layer.py` | file | Live smoke test — the MCP server over stdio against the running console: list tools and resources, call read tools | required |
| `docs/` | dir | Console design notes: `mcp-layer.md` (the MCP layer: setup, transports, tool catalog) | terminal |
| `design-system/` | dir | `@bamr87/harness-console-ui` — the console's EARLIER hand-written look as a small React package, kept as the Claude Design sync source (the live page is `web/`) (source in `src/`, built to `dist/`), and the `.design-sync/` config that publishes it to Claude Design | terminal |
| `web/` | dir | The page — React + TypeScript on Mantine, TanStack Query, React Router and xterm.js, built by Vite into `web/dist/` (gitignored) that `app.py` serves; `run.sh` rebuilds it when its sources change | terminal |
| `claude_telemetry.py` | file | `/api/claude-telemetry`: Claude Code native OTel, read-only — `claude_code_*` metrics from Prometheus and `api_request`/`tool_result` events from Elasticsearch; cost labelled API-equivalent (estimate) | terminal |
| `test_claude_telemetry.py` | file | Tests for `claude_telemetry.py`: totals, window/session validation, no identity fields, degradation | terminal |

## Placement

- A new operation → an `OPS` entry in `core.py` (argv builder + validation) and, if it takes a new kind of parameter, a field in `web/src/jobs/OpForm.tsx`; every operation is already reachable from the Operations page and the palette. Never a free-form command path.
- A new editable contract knob → a field in the matching `CONFIG_SECTIONS` entry of `core.py` (declared in `_data/fleet.yml` first); the form and the API follow from it.
- A new credential the console may hold → a `CREDENTIALS` entry in `core.py`; nothing else changes.
- A new GitHub write → an `ACTIONS` entry and a branch in `github_link.act` (validated params, fleet-scoped, confirm-gated, logged), a button through `web/src/github/useGhAction.tsx`, and a test in `test_console.py`. Never a merge, delete, push or settings change.
- A new API route → `app.py`, calling into `core.py`; its query hook → `web/src/api/hooks.ts`.
- A new page → `web/src/pages/`, a route in `web/src/main.tsx`, an entry in `web/src/nav.ts`, and its link builder in `web/src/lib/links.ts` (see web/SCHEMA.md).
- A view, key or colour the terminal dash shows too → `tools/fleetcore/`, served from `app.py`; never a second copy in `web/`.

## Forbidden

- No shell strings built from request data; no credential values in responses or logs (a wrapped tool's own output is scrubbed before it is returned) and none on a command line — `gh` is fed over stdin; no commits or pushes from the console.

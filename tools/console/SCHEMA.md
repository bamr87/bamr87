---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console

> The Harness Console: the local control plane's credentialed, write-capable front end (FastAPI + a React/Mantine page, with the terminal dash embedded) wrapping the allowlisted `tools/dash` operations — docs/HARNESS-OPS.md.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How to run the console (native venv or compose), what it can and cannot do | required |
| `core.py` | file | Pure logic: committed-state loader, the operation ALLOWLIST, the job manager, the comment-preserving fleet.yml config editor (`CONFIG_SECTIONS`), and the credential layer (`CREDENTIALS`, process env, `.env`, `gh auth login`), and the content-atlas + editorial-plan adapters over dash-gen's `content_atlas.py` — no web framework, testable on PyYAML alone | required |
| `app.py` | file | FastAPI routes over core.py, the CSP, and the page fallback (every non-API path serves `web/dist`) (`/api/project/{name}`, `/api/tui` + `/api/tui/status`, `/api/theme`, `/api/state`, `/api/ops`, `/api/jobs`, `/api/contract`, `/api/config`, `/api/auth` + `/api/auth/credential` + `/api/auth/github`, `/api/capabilities`, `/api/lake` + `/api/lake/runs` + `/api/lake/lines`, `/api/content` + `/api/content/{site}/docs` + `/api/content/{site}/brief`, `/api/editorial/decision` + `/api/editorial/{site}`); `/api/fleet`, `/api/fleet/docker`, `/api/keys`, `/theme.css` serve the core shared with the TUI (`tools/fleetcore`); Host allowlist + optional bearer-token guard | required |
| `run.sh` | file | Bootstraps `.venv-console` at latest and execs uvicorn (`tools/dash console`, the compose `console` service) | required |
| `github_link.py` | file | GitHub through the console's OAuth App: the device and browser (state + PKCE) flows, delivering the token to the session / gh / `.env`, and fleet repo management — reads anywhere, confirm-gated writes (issues, runs, workflows) only to repos the hub owns, an action log; never a merge, delete or push. Stdlib HTTP, so tests swap `_http` | required |
| `tui_bridge.py` | file | The Terminal page's bridge: runs the terminal dash (`tools/tui/app.py`) on a pty and relays it over the `/api/tui` WebSocket — Host + Origin checks, the hello-frame token, the session cap, process-group hang-up | required |
| `serve.py` | file | One uvicorn server on the TCP port AND `CONSOLE_UDS` — the Unix socket the `tui` service reaches the same runtime through | required |
| `requirements.txt` | file | Always-latest deps: dash-gen's requirements + fastapi, uvicorn, ruamel.yaml, websockets (`/api/tui`), the TUI's requirements (Textual, for the Terminal page), the OpenTelemetry SDK + OTLP/HTTP exporter (lake export) | required |
| `test_console.py` | file | Fixture tests — allowlist refusals, argv shapes, confirm gate, job manager, state degradation, multi-section config round-trip, credential handling (values never returned, `.env` only on confirm, the kill switch), the page's CSP and fallback, the Terminal socket's Host/Origin/token refusals, the project drill-down | required |
| `design-system/` | dir | `@bamr87/harness-console-ui` — the console's EARLIER hand-written look as a small React package, kept as the Claude Design sync source (the live page is `web/`) (source in `src/`, built to `dist/`), and the `.design-sync/` config that publishes it to Claude Design | terminal |
| `web/` | dir | The page — React + TypeScript on Mantine, TanStack Query, React Router and xterm.js, built by Vite into `web/dist/` (gitignored) that `app.py` serves; `run.sh` rebuilds it when its sources change | terminal |

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

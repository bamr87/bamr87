---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console

> The Harness Console: the local control plane's credentialed, write-capable front end (FastAPI + one static page) wrapping the allowlisted `tools/dash` operations — docs/HARNESS-OPS.md.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How to run the console (native venv or compose), what it can and cannot do | required |
| `core.py` | file | Pure logic: committed-state loader, the operation ALLOWLIST, the job manager, the comment-preserving fleet.yml config editor (`CONFIG_SECTIONS`), and the credential layer (`CREDENTIALS`, process env, `.env`, `gh auth login`) — no web framework, testable on PyYAML alone | required |
| `app.py` | file | FastAPI routes over core.py (`/api/state`, `/api/ops`, `/api/jobs`, `/api/contract`, `/api/config`, `/api/auth` + `/api/auth/credential` + `/api/auth/github`, `/api/capabilities`, `/api/lake` + `/api/lake/runs` + `/api/lake/lines`) + the static page; Host allowlist + optional bearer-token guard | required |
| `run.sh` | file | Bootstraps `.venv-console` at latest and execs uvicorn (`tools/dash console`, the compose `console` service) | required |
| `requirements.txt` | file | Always-latest deps: dash-gen's requirements + fastapi, uvicorn, ruamel.yaml, the OpenTelemetry SDK + OTLP/HTTP exporter (lake export) | required |
| `test_console.py` | file | Fixture tests — allowlist refusals, argv shapes, confirm gate, job manager, state degradation, multi-section config round-trip, credential handling (values never returned, `.env` only on confirm, the kill switch) | required |
| `static/` | dir | The single-page front end (`index.html`: overview, harnesses, schedules, loops, costs, traces — the lake + Phoenix — fleet, config, auth, jobs) | terminal |

## Placement

- A new operation → an `OPS` entry in `core.py` (argv builder + validation) and a button/param in `static/index.html`; never a free-form command path.
- A new editable contract knob → a field in the matching `CONFIG_SECTIONS` entry of `core.py` (declared in `_data/fleet.yml` first); the form and the API follow from it.
- A new credential the console may hold → a `CREDENTIALS` entry in `core.py`; nothing else changes.
- A new API route → `app.py`, calling into `core.py`.

## Forbidden

- No shell strings built from request data; no credential values in responses or logs (a wrapped tool's own output is scrubbed before it is returned) and none on a command line — `gh` is fed over stdin; no commits or pushes from the console.

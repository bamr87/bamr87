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
| `core.py` | file | Pure logic: committed-state loader, the operation ALLOWLIST, the job manager, the comment-preserving contract editor (no web framework — testable on PyYAML alone) | required |
| `app.py` | file | FastAPI routes over core.py (`/api/state`, `/api/ops`, `/api/jobs`, `/api/contract`, `/api/capabilities`, `/api/lake` + `/api/lake/runs` + `/api/lake/lines` for the data lake) + the static page; optional bearer-token guard | required |
| `run.sh` | file | Bootstraps `.venv-console` at latest and execs uvicorn (`tools/dash console`, the compose `console` service) | required |
| `requirements.txt` | file | Always-latest deps: dash-gen's requirements + fastapi, uvicorn, ruamel.yaml, the OpenTelemetry SDK + OTLP/HTTP exporter (lake export) | required |
| `test_console.py` | file | Fixture tests — allowlist refusals, argv shapes, confirm gate, job manager, state degradation, contract round-trip | required |
| `static/` | dir | The single-page front end (`index.html`: overview, harnesses, schedules, loops, costs, traces — the lake + Phoenix — fleet, contract, jobs) | terminal |

## Placement

- A new operation → an `OPS` entry in `core.py` (argv builder + validation) and a button/param in `static/index.html`; never a free-form command path.
- A new API route → `app.py`, calling into `core.py`.

## Forbidden

- No shell strings built from request data; no credential values in responses or logs beyond what the wrapped tool itself prints; no commits or pushes from the console.

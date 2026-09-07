---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/tui

> The terminal command center: the Jekyll dash's read-only twin in a TUI — the same registry and committed health signals, plus live container state from the `forge` Docker host (`tools/dash tui`; docs/FORGE-HOST.md).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How to run the terminal dash, and what it reads | required |
| `fleet.py` | file | Pure logic: join/filter/sort over `_data/projects.yml` + `_data/project_health.yml`, degrading cleanly when health is absent — no Textual import, testable on PyYAML alone | required |
| `host.py` | file | Docker inventory over `DASH_DOCKER_HOST` (default `ssh://forge`), matched onto registry rows | required |
| `app.py` | file | The Textual UI over `fleet.py` + `host.py` | required |
| `run.sh` | file | Bootstraps `.venv-tui` at latest and execs `app.py` (`tools/dash tui`) | required |
| `requirements.txt` | file | Always-latest deps: `PyYAML` + `textual`, unpinned | required |
| `__init__.py` | file | Package marker so `fleet.py` is importable by `tools/test_tui_fleet.py` | required |

## Placement

- New derived view (a filter, a sort, a KPI) → a pure function in `fleet.py` with a case in `tools/test_tui_fleet.py`; the widget in `app.py` follows from it.
- New remote-host query → `host.py`; it must degrade to an empty inventory when the host is unreachable.

## Forbidden

- No writes: the TUI is read-only over committed signals and `docker ps`. Anything that mutates GitHub or the fleet belongs in `tools/dash` (and, gated, the Harness Console).
- No credentials in this tree; the Docker endpoint comes from `DASH_DOCKER_HOST`.

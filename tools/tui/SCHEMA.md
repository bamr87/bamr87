---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/tui

> The terminal command center: the Jekyll dash's read-only twin in a TUI — the registry plus the dash's committed signals (health, triage inbox, harness wires) and live containers from `DASH_DOCKER_HOST` (local + the `forge` host; `tools/dash tui`; docs/FORGE-HOST.md).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How to run the terminal dash, its tabs and keys, and what it reads | required |
| `fleet.py` | file | Pure logic: join/filter/sort over `_data/projects.yml` + `project_health.yml` + `fleet_triage.yml` + `harness_health.yml`, inbox + per-repo drill-down, source freshness — degrading cleanly when any signal is absent; no Textual import, testable on PyYAML alone | required |
| `host.py` | file | Docker inventory over every `DASH_DOCKER_HOST` endpoint (`local`, `ssh://forge`, …), attributed to registry rows by the UPS-OPS-17 label, then by name | required |
| `app.py` | file | The Textual UI over `fleet.py` + `host.py` | required |
| `test_app.py` | file | Headless Textual-Pilot tests of `app.py` (layout, cursor, drill-down, markup safety, refresh); self-skips without Textual | required |
| `run.sh` | file | Bootstraps `.venv-tui` at latest and execs `app.py` (`tools/dash tui`) | required |
| `requirements.txt` | file | Always-latest deps: `PyYAML` + `textual`, unpinned | required |
| `__init__.py` | file | Package marker so `fleet.py` is importable by `tools/test_tui_fleet.py` | required |

## Placement

- New derived view (a filter, a sort, a KPI, a new committed signal) → a pure function in `fleet.py` with a case in `tools/test_tui_fleet.py`; the widget in `app.py` follows from it, with a Pilot case in `test_app.py` when it adds a key or a tab.
- New remote-host query → `host.py`; it must degrade to an empty inventory plus a per-host error when the host is unreachable.

## Forbidden

- No writes: the TUI is read-only over committed signals and `docker ps`. Anything that mutates GitHub or the fleet belongs in `tools/dash` (and, gated, the Harness Console).
- No credentials in this tree; Docker endpoints come from `DASH_DOCKER_HOST`.
- No `str` cells built from GitHub text: DataTable parses strings as Rich markup, so issue titles and reasons go through `Text` (`_plain` / `_clip` in `app.py`).

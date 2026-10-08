---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/tui

> The terminal command center: the Jekyll dash's twin in a TUI — the registry plus the dash's committed signals (health, triage inbox, harness wires), live containers from `DASH_DOCKER_HOST` (local + the `forge` host; docs/FORGE-HOST.md), and a Jobs tab on the Harness Console's runtime. Its data, keys and palette come from `tools/fleetcore/` — the same core the browser console renders (`tools/dash tui [--docker]`).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How to run the terminal dash, its tabs and keys, and what it reads | required |
| `app.py` | file | The Textual UI over `tools/fleetcore` (views, keys v1, the bashOS theme) + the Jobs tab and `:` palette, which submit to the console via `fleetcore.client` | required |
| `test_app.py` | file | Headless Textual-Pilot tests of `app.py` (layout, cursor, drill-down, markup safety, refresh, keys v1, the Jobs tab against a fake console and its confirm gate); self-skips without Textual | required |
| `run.sh` | file | Bootstraps `.venv-tui` at latest and execs `app.py` (`tools/dash tui`) | required |
| `requirements.txt` | file | Always-latest deps: `PyYAML` + `textual`, unpinned | required |
| `__init__.py` | file | Package marker | required |

## Placement

- New derived view, key or colour → `tools/fleetcore/` (its SCHEMA routes it), so the browser console gets it too; the widget in `app.py` follows, with a Pilot case in `test_app.py` when it adds a key or a tab.
- New action that changes anything → an `OPS` entry in the console (`tools/console/core.py`); it then appears in the `:` palette here without code in this tree.

## Forbidden

- No writes of its own: the TUI reads committed signals and `docker ps`, and runs `dash-gen health` on `R`. Anything that mutates GitHub or the fleet is a job SUBMITTED to the Harness Console's API (`fleetcore.client`), where the allowlist and the confirm-before-write gate run — never a subprocess here.
- No credentials in this tree; Docker endpoints come from `DASH_DOCKER_HOST`.
- No `str` cells built from GitHub text: DataTable parses strings as Rich markup, so issue titles and reasons go through `Text` (`_plain` / `_clip` in `app.py`).

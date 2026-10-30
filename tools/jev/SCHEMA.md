---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev

> JEV, the harness-level agent logic engine: the assign-at-merge numbering compiler (`number.py`) and the tiered pull-request conflict triage and resolution engine (`conflicts.py`, `classify.py`, `ledger.py`). Entry point `python3 -m tools.jev`; doc `docs/JEV.md`.

## Conventions

- Python 3.12, stdlib + PyYAML. Every GitHub call goes through `common.gh`, which refuses `--admin` and refuses `pr merge`; every subprocess returns a `Run` rather than raising, because a failing trial merge is data.
- A module is importable with no side effects: configuration is read when a function asks for it, never at import.
- Tests live beside the other hub gates as `tools/test_jev_*.py` (collected by `run-all-tests.sh` and `python-tests.yml`), not in this directory.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | How to run JEV, set up the merge driver, and read the tier ladder | required |
| `__init__.py` | file | Package marker and version | required |
| `__main__.py` | file | The CLI entry point — the `number` and `conflicts` command groups | required |
| `common.py` | file | Hub paths, `_data/fleet.yml` `jev:` / `budget.jev` reader, the `gh` and `git` wrappers, the no-admin/no-merge guard | required |
| `classify.py` | file | The deterministic classifier: conflicted file → kind, and (files, hunks, lines, history) → one tier | required |
| `number.py` | file | The assign-at-merge compiler: fragments → `features/features.yml`, `PRD.md`, `CHANGELOG.md`, `docs/amendments/NNNN-*.md`; plus the hand-picked-number lint | required |
| `conflicts.py` | file | Detect, trial-merge, triage, resolve by tier, validate, push a merge commit, escalate | required |
| `ledger.py` | file | `_data/jev_resolutions.yml` — append-only cost records and the monthly cap arithmetic | required |
| `merge-regen.sh` | file | The `jev-regen` git merge driver: keep ours, record the path for regeneration | required |

## Placement

- New JEV capability → a module here plus a `tools/test_jev_<name>.py`, a row in this table, and a section in `docs/JEV.md`.

## Forbidden

- No `gh pr merge`, no `--admin`, no repository-settings call, no force-push — asserted in `common.assert_no_admin` and covered by `tools/test_jev_conflicts.py`.
- No secret, token or model credential in this directory; the `claude` CLI reads its own environment.

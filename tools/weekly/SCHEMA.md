---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/weekly

> The weekly routine (`tools/dash weekly`, docs/WEEKLY.md): Friday closes the week, Saturday prepares the next, Sunday plans it, and one confirm is their only external write. It lists what is ready to merge and what is stale; it never merges or closes.

## Conventions

- One module per stage; `core.py` holds the plumbing they share (git helpers, the lock, the run record, the ranking, confirm). A stage imports `core`, never another stage's internals.
- A stage reads and reports. Every write outside the run folder and the local archive belongs to `core.cmd_confirm`, behind `--apply`.
- Config is `_data/fleet.yml` `weekly:`; each module's `DEFAULTS` is what a missing key means, never a second source of truth.
- Tests are `tools/test_weekly*.py`, offline: git on throwaway repositories, `gh`, `docker`, `launchctl` and the model call as functions the test supplies.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What each module does and how the stages hand off | required |
| `__init__.py` | file | Package marker | required |
| `__main__.py` | file | `python3 -m tools.weekly` | required |
| `cli.py` | file | The command line: `close`, `prepare`, `plan`, `auto` (the LaunchAgent's catch-up dispatcher), `confirm`, `status`, `inventory`, `brief` | required |
| `core.py` | file | Friday's core (inventory, merge proof, save, refresh and tidy, ranking, chronicles and retro) and `confirm` | required |
| `closeout.py` | file | Friday: one disposition for every open pull request and issue, and the live review-gate scan; read-only | required |
| `prepare.py` | file | Saturday: next week's scheduled activities, when each fires and whether it can run (switches, last results, credentials, budgets, source freshness, this Mac) | required |
| `agenda.py` | file | Sunday: the handoff boost, the week day by day and the Monday brief | required |
| `harness.py` | file | The two halves: the close-out agent's one capped session (Claude Code), the Grok briefs and the direction issue (Grok bots) | required |
| `briefs/` | dir | The standing briefs: the close-out agent's prompt and one Grok brief a stage | required |

## Placement

- New stage → a module here, its subcommand in `cli.py`, its slot in `_data/fleet.yml` `weekly.schedule`, a Grok brief in `briefs/`, a section in `docs/WEEKLY.md`.
- New external write → `core.cmd_confirm` only, dry run first, under the lock, with a test that the dry run writes nothing. A write that cannot be undone (a merge, a close, a comment under the owner's name) is its own reviewed change, never an addition here.
- New model call → `harness.py`, through `tools/jev/reflect.run_session` (budget.loops, the AI ledger); never a `claude -p` of its own.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No GitHub write from a scheduled stage, and none anywhere outside `core.cmd_confirm`.
- No merge, no close, no comment and no label, anywhere in this package: `tools/test_weekly_dispositions.py` and `tools/test_weekly_stages.py` hold the source to it.
- No secret value read, printed or written; the credential checks read names, ages and expiry dates.

# Daily repo deep dive

> One bamr87 repo a day, every repo once per 42-day cycle: the ledger (`_data/deep-dive.yml`), its tool (`tools/deep_dive.py`), the daily refresh (`deep-dive.yml`) and the `/deep-dive` dashboard (HUB-029, PRD FR24–FR25).

## What it is

A daily routine (06:00 America/Denver) deep-dives the repo scheduled for the day: review, analysis, documentation, issues, feature requests and UI/UX improvements. Everything it files carries the `deep-dive` label, and each run records its progress with a PR to this hub that runs `tools/deep_dive.py record`. The routine only ever opens issues and PRs; it never merges, force-pushes or changes settings or secrets.

The rotation is every non-archived repo owned by `bamr87` (forks included), oldest first, starting 2026-10-30. A cycle is `cycle_days` long (42); the rotation fills the first days and the remaining days are catch-up slots, in which `today` returns the earliest repo whose day passed without a `done` run.

## Commands

```bash
python3 tools/deep_dive.py today [--date 2026-10-30] [--json]     # the repo for a date
python3 tools/deep_dive.py record REPO --status done \
  --issue URL --pr URL --findings "…" --score 78 --next-focus "…"  # record a run
python3 tools/deep_dive.py refresh [--dry-run]                     # open deep-dive issues/PRs per repo (GH_TOKEN)
python3 tools/deep_dive.py json [--write | --check]                # the frontend projection
python3 tools/deep_dive.py rollover [--force]                      # start the next cycle
python3 tools/deep_dive.py init --from-github --force              # rebuild the rotation from GitHub
```

Every write rewrites both `_data/deep-dive.yml` and `_data/deep_dive.json`. Tests: `python3 tools/test_deep_dive.py`.

## Schema (`deep-dive/v1`)

Top level: `schema`, `owner`, `label` (the GitHub label every deep-dive item carries), `cycle` (1-based), `cycle_start` (ISO date of day 1), `cycle_days` (≥ the rotation length), `refreshed_at` (UTC timestamp of the last GitHub refresh) and `repos`.

Each `repos[]` entry:

| Field | Type | Meaning |
|---|---|---|
| `day` | int | 1-based day index in the cycle; equal to the entry's position |
| `repo` | string | repo name under `owner` |
| `scheduled` | date | `cycle_start + day − 1` |
| `status` | enum | `pending`, `in_progress`, `done` or `skipped` |
| `last_processed` | date \| null | the date of the last `done` / `in_progress` run (kept across cycles) |
| `cycle` | int | the cycle the status belongs to |
| `issues`, `prs` | list of URLs | issues and PRs the deep dives opened (deduplicated; refresh adds open labelled ones) |
| `open_issues`, `open_prs` | int | open `deep-dive` issues / PRs right now (refresh) |
| `findings` | string | summary of the last run's findings |
| `score` | number \| null | 0–100 health / UPS conformance score from the last run |
| `next_focus` | string | what the next pass on this repo should look at |

`_data/deep_dive.json` is the same document plus a precomputed `summary` (progress x/N, counts per status, today / next / last repo, average score, open totals), pinned to `refreshed_at` so `--check` is deterministic; the page recomputes today from the viewer's clock.

## Refresh workflow

`.github/workflows/deep-dive.yml` runs daily at 12:17 UTC (06:17 MDT; `_data/fleet.yml` `schedule.deep_dive`). It runs `refresh` with the workflow token (two search API calls), uploads both files as an artifact, and on the schedule publishes them through `publish-data` with auto-merge off, so the update arrives as the stable `chore/deep-dive-refresh` PR a human merges. A manual run defaults to `dry_run: true` (artifact only).

## Dashboard

`/deep-dive` in the Harness Console (Harnesses section) shows cycle progress, today / last / next repo, a calendar of every cycle day, and a per-repo table with status, score, open issue/PR links, findings and next focus. It reads `/api/data/deep_dive` (`site_docs.PUBLIC_DATA`), so the published snapshot renders it too. The workflow also appears in the harness pipeline map automatically, as every workflow does (FR21).

# Daily Repo Analysis

The dash's **continuous analysis → implementation cycle**: once a day it reviews
the whole fleet's prior-day activity, saves a durable summary in the monorepo, and
dispatches a Claude Code agent to turn the day's CI failures into fixes.

It complements the other daily jobs — `refresh-dash` (README/registry),
`actions-usage` + `actions-review` (Actions cost), `ai-usage` (Claude spend) — by
answering a different question: **what happened across the fleet yesterday, and
what broke that we should fix today?**

## The loop

```text
                 ┌──────────────────────── daily 06:00 UTC ────────────────────────┐
                 │                                                                  │
   registry ──▶  1. GATHER            2. RECORD                3. IMPLEMENT         │
 _data/         dash-gen daily  ──▶  commit digest to    ──▶  Opus Claude Code      │
 projects.yml   (PyGithub scan)      _reports/daily/          agent reviews each    │
                 │                    <date>.md                CI failure and opens  │
                 │                                             a draft PR (hub) or   │
                 ▼                                             files an issue (sub). │
        daily-analysis-workorder.md ─────────────────────────────▲                 │
        (ephemeral, deduped failures) ─────────────────────────── ┘                 │
                                                                                    │
   next day the agent's PRs/issues show up in the digest ◀───────────────────────── ┘
```

1. **Gather** — `.github/scripts/dash-gen/daily_report.py` (`tools/dash-gen daily`,
   `tools/dash daily`) queries the GitHub API via PyGithub for every repo in
   `_data/projects.yml`, over the window `[now − days, now]` (default 1 day):
   commits on the default branch, PRs opened/merged/closed, issues opened/closed,
   releases, and **completed workflow runs that failed / timed out** (the
   actionable signal). External mirrors (e.g. `microsoft/skills`) appear in the
   digest but are never turned into failure work — their failures aren't ours.

2. **Record** — a Markdown digest is written to `_reports/daily/<date>.md` and
   committed to `main` (a durable summary saved in the monorepo). The index span
   in [`_reports/README.md`](../_reports/README.md) is regenerated in place.
   `_reports/` is `generated` in the SCHEMA pyramid — never hand-edited.

3. **Implement** — the gather step also emits an ephemeral
   `daily-analysis-workorder.md`: one candidate per failing workflow, **deduped**
   against open `daily-analysis` issues so a persistently-failing workflow gets one
   thread, not one per day. When there are fresh failures and Claude auth is
   present, the [`daily-repo-analysis.yml`](../.github/workflows/daily-repo-analysis.yml)
   workflow runs an **Opus Claude Code agent** that, per candidate:
   - **hub-fixable** (`bamr87/bamr87`): opens ONE **draft PR** with the surgical fix;
   - **submodule / cross-repo**: files ONE **issue** in `bamr87/bamr87`.

   The draft PRs then flow through the normal review + CI gate before anyone
   merges — the agent proposes, humans dispose.

## Guardrails

- **Code decides what's actionable, not the AI.** Candidate selection + dedupe run
  in `daily_report.py`; the AI only investigates + authors fixes for a pre-vetted,
  capped list. It cannot spam.
- **Per-run cap** (`--limit`, default 6; `max_failures` dispatch input).
- **Draft PRs only** — never merges, never pushes to `main`, never force-pushes,
  and never modifies submodule working trees. It edits only this repo's tree and
  never the generated surfaces (`_site/`, `_reports/`, README AUTO span,
  `projects/SCHEMA.md`).
- **Self-skips** without Claude auth (`CLAUDE_CODE_OAUTH_TOKEN` preferred,
  `ANTHROPIC_API_KEY` fallback — see [AI-INTEGRATION.md](AI-INTEGRATION.md)) and on
  a `dry_run` dispatch. The digest is still gathered + committed in both cases.

## Running it

```bash
# Locally — build today's digest + work order (needs gh auth or GH_TOKEN):
tools/dash daily                     # last 1 day
tools/dash daily --days 3            # wider window
tools/dash daily --no-dedupe        # skip the open-issue dedupe (offline/testing)

# In CI — scheduled daily 06:00 UTC, or on demand:
#   Actions ▸ 🗓️ Daily Repo Analysis ▸ Run workflow
#   inputs: days, max_failures, dry_run
```

## Tokens & secrets

| Secret | Needed for | Fallback |
| --- | --- | --- |
| `GITHUB_TOKEN` | read public activity, commit the digest, open PRs/issues | — (built-in) |
| `DAILY_ANALYSIS_TOKEN` | read **private** submodules' run logs (fine-grained PAT, `actions:read`) | `GITHUB_TOKEN` |
| `CLAUDE_CODE_OAUTH_TOKEN` | the AI implement step | `ANTHROPIC_API_KEY` |

Without a Claude token the workflow degrades to gather + record only — the digest
still lands every day.

## Files

| Path | Role |
| --- | --- |
| `.github/workflows/daily-repo-analysis.yml` | the daily cron workflow (gather → record → implement) |
| `.github/scripts/dash-gen/daily_report.py` | the PyGithub gather + digest + work-order generator |
| `_reports/daily/<date>.md` | committed daily digests |
| `_reports/README.md` | reports index (AUTO span regenerated each run) |
| `daily-analysis-workorder.md` | ephemeral agent brief (gitignored) |

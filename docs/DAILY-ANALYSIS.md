# The Daily Fleet Loop

The dash's **continuous analysis → remediation cycle**. Once a day it measures
the whole fleet, records what it found as durable data in the monorepo, and
dispatches a Claude Code agent to **fix** the workflows that are broken or
burning time — opening the fix as a draft PR in whichever repo owns it.

One workflow does all of it: [`fleet-pulse.yml`](../.github/workflows/fleet-pulse.yml).

## The loop

```text
              ┌───────────────────── daily 06:00 UTC · fleet-pulse.yml ─────────────────────┐
              │                                                                              │
              │   job: pulse                                    job: doctor  (needs: pulse)  │
              │  ┌────────────────────────────────┐            ┌────────────────────────┐   │
 registry ──▶ │  │ 1. GATHER                      │            │ 3. FIX                 │   │
 _data/       │  │   dash-gen actions   (cost)    │            │  Opus Claude Code      │   │
 projects.yml │  │   dash-gen ai-usage  (spend)   │            │  · reads each run's    │   │
              │  │   dash-gen ledger    (actuals) │            │    failing log         │   │
              │  │   dash-gen daily     (digest)  │            │  · finds root cause    │   │
              │  │   dash-gen triage    (open)    │            │  · opens a DRAFT PR    │   │
              │  └───────────────┬────────────────┘            │    with the fix — in   │   │
              │                  ▼                             │    the hub OR in the   │   │
              │  ┌────────────────────────────────┐            │    submodule that      │   │
              │  │ 2. PUBLISH + TRIAGE            │            │    owns the workflow   │   │
              │  │   publish-data → one commit    │            │  · falls back to a hub │   │
              │  │     (direct push, else a PR)   │            │    issue when it can't │   │
              │  │   dash-gen remediate → queue   │──────────▶ │                        │   │
              │  └────────────────────────────────┘            └───────────┬────────────┘   │
              │                                                            │                │
              └────────────────────────────────────────────────────────────┼────────────────┘
                                                                           ▼
                       tomorrow's run sees the open PR/issue and does NOT re-file it
```

### 1. Gather

Five generators run off one checkout and one Python setup. Each is independently
fault-tolerant (`continue-on-error`) and its outcome is reported in the run
summary — one degraded API call costs that signal, not the whole day's data.

| Generator | Writes | Signal |
| --- | --- | --- |
| `dash-gen actions` | `_data/actions_usage.yml` | per-workflow cost / effectiveness / waste, with `slow`/`flaky`/`high-cost-low-value` flags |
| `dash-gen ai-usage` | `_data/ai_usage.yml` | fleet Claude Code touchpoints (runs, commits, PRs) |
| `dash-gen ledger --no-local` | `_data/engagements.yml` | engagement actuals accrued from that evidence |
| `dash-gen daily` | `_reports/daily/<date>.md` | prior-day commits / PRs / issues / releases / CI failures |
| `dash-gen triage` | `_data/fleet_triage.yml` | **open state**: every open issue, open PR (with CI status), and each workflow's latest conclusion, plus per-repo attention scores — the `/triage/` portal |

External mirrors (e.g. `microsoft/skills`) appear in the digests but are excluded
from totals, scores, and anything actionable — their failures are not ours.

### 2. Publish + triage

All five outputs land in **one commit** through
[`utilities/publish-data`](../.github/actions/utilities/publish-data/action.yml),
which pushes straight to `main` when branch protection allows it and otherwise
opens a stable-branch pull request (`chore/fleet-pulse`, updated in place,
auto-merge requested). See [Why publishing is indirect](#why-publishing-is-indirect).

Then `dash-gen remediate`
([`remediation.py`](../.github/scripts/dash-gen/remediation.py)) merges the two
*actionable* signals into **one ranked queue**:

- **failing** — from `fleet_triage.yml`: every workflow whose latest completed run
  is red. This is *standing* state, so a workflow broken for three weeks stays on
  the queue until it's fixed — the class of failure a prior-day-only scan misses.
- **expensive** — from `actions_usage.yml`: slow, flaky, cancel-heavy,
  cron-heavy, or high-cost-low-value.

Candidates are keyed on `owner/repo:workflow-path`, so a workflow that is *both*
red and slow is **one** entry with both signals — not two tickets, which is how
the previous split loops turned a queue into noise. Each is then classified `hub`
(fixable in this checkout) or `submodule` (needs a cross-repo PR), ranked by
severity then wasted minutes, de-duplicated against open issues **and** open PRs
in both the hub and the target repo, and capped.

### 3. Fix

`doctor` is a `needs: pulse` job — not a separate `workflow_run` workflow — so it
runs off the same checkout and cannot be skipped by an upstream publish problem.

For each candidate the Opus agent reads the failing run's log and the workflow
definition, forms a specific root cause, and then:

- **hub** (`bamr87/bamr87`) → branches in the checkout, makes the minimal fix,
  opens a **draft PR** here;
- **submodule** → clones that repo to a scratch dir (never into `projects/`),
  fixes it there, opens a **draft PR in that repo**. Requires `FLEET_TOKEN`;
- **can't fix safely** → files ONE tracking issue in the hub.

The agent proposes; humans dispose. Draft PRs flow through the normal review + CI
gate.

## Guardrails

- **Code decides what's actionable, not the AI.** Selection, merging, dedupe,
  ranking, and caps all run in `remediation.py`. The AI only investigates and
  authors on a pre-vetted, capped list — it cannot spam the fleet.
- **Caps** come from `_data/fleet.yml` → `remediation.max_candidates` (default 4)
  and `max_cross_repo` (default 3). The cross-repo sub-cap stops a burst of
  submodule failures from starving hub fixes that could land the same day.
- **The cap is paid for out of a turn budget.** `doctor` runs the agent with
  `--max-turns 160`, and one candidate costs ~40 turns: 2 reads to diagnose it
  (run log + workflow definition) and 7 to author the fix (clone, branch, read,
  edit, commit, push, `gh pr create`), plus margin for a wrong first guess. The
  cap and the budget are therefore one number, stated in two files — the
  workflow's `--limit` fallback shadows the registry value, so both move
  together or neither does. `.github/scripts/dash-gen/test_fleet_pulse_doctor.py`
  fails if they drift, or if the budget stops covering the cap. Set at 6 with a
  120-turn budget, the agent exhausted its turns mid-queue and the run produced
  **nothing** — an unfinishable queue delivers fewer fixes than a shorter one.
- **The agent's allowlist has to cover its own prompt.** The prompt tells it to
  read `gh run view --log-failed`; a pipeline is permission-matched per segment,
  so `Bash(gh:*)` does not cover the filter on the right of the `|`. The
  log-triage filters (`grep`, `head`, `tail`, `wc`, `jq`, …) are in
  `--allowedTools` for that reason, and the same test asserts it — a prompt that
  instructs a command nobody granted turns the budget into denials, silently.
- **Dedupe is marker-based.** Every PR/issue body starts with
  `<!-- fleet-doctor key="owner/repo:path" -->`. Markers from the two retired
  loops (`actions-review`, `daily-analysis`) are honoured too, so open tickets
  from before the migration are not re-filed.
- **Draft PRs only** — never merges, never pushes to a default branch, never
  force-pushes, never touches submodule working trees under `projects/`, and
  never edits generated surfaces (`_site/`, `_reports/`, `_data/*_usage.yml`,
  `_data/fleet_triage.yml`, the README AUTO span, `projects/SCHEMA.md`).
- **Retired workflows are dropped.** GitHub keeps a deleted workflow's run
  history forever, so one deleted while red stays "currently failing" in the
  triage data permanently. Each candidate's file is verified to still exist on
  its default branch before it is queued — checked at selection time, so the API
  cost is bounded by the cap. Ambiguity resolves toward *keeping* the candidate:
  an unreachable private repo 404s exactly like a deleted file, and dropping real
  work silently is worse than carrying one stale entry.
- **Token validity is probed, not assumed.** A secret can be set and still be
  expired. `pulse` probes the write token against the API and reports the
  degraded capability, rather than inferring health from the secret's presence.
- **No green-washing.** The agent is explicitly forbidden from adding
  `continue-on-error` or blanket retries to make a red workflow look healthy.
- **Degrades, never blocks.** Without Claude auth the fixer is skipped and the
  data still lands. Without `FLEET_TOKEN` cross-repo fixes downgrade to hub
  issues. Both are reported in the run summary.

## Why publishing is indirect

The three data-refresh workflows this loop replaces each ended in a bare
`git push` to `main`. A ruleset was then added to `bamr87/bamr87` — *"Changes must
be made through a pull request"* and *"Commits must have verified signatures"* —
and every one of them began failing on that final step, every day. Because
`actions-review.yml` triggered on `actions-usage.yml` **succeeding**, it stopped
running as collateral.

Every generator still worked perfectly. The data simply stopped being saved, and
nothing said so; `_data/actions_usage.yml` sat three weeks stale while the daily
runs went red in a tab nobody was watching.

Two structural lessons are baked into the replacement:

1. **The publish route is a property of the repository, not the workflow**, and it
   can change without warning. So it is resolved at runtime by `publish-data`,
   which falls back to a PR rather than failing.
2. **`workflow_run` chaining is fragile** — it couples workflows by display-name
   string and silently skips the downstream when the upstream fails for *any*
   reason. `needs:` within one workflow does not have that failure mode.

## Running it

```bash
# Locally — any single signal (needs gh auth or GH_TOKEN):
tools/dash actions                  # cost/effectiveness analytics
tools/dash daily                    # prior-day digest + failure work order
tools/dash triage                   # open-state snapshot → _data/fleet_triage.yml

# The merged remediation queue:
tools/dash remediate                        # respects _data/fleet.yml caps
tools/dash remediate --limit 3              # override the cap
tools/dash remediate --no-dedupe            # skip the open-issue/PR check (offline)

# In CI — scheduled daily 06:00 UTC, or on demand:
#   Actions ▸ 🩺 Fleet Pulse ▸ Run workflow
#   inputs: days, max_candidates, dry_run (data only, no fixer), skip_publish
```

## Tokens & secrets

Declared centrally in [`_data/fleet.yml`](../_data/fleet.yml); audit what is
actually set with `tools/dash secrets`.

| Secret | Needed for | Fallback |
| --- | --- | --- |
| `GITHUB_TOKEN` | read public activity, publish data, open hub PRs/issues | — (built-in) |
| `FLEET_TOKEN` | read **private** repos' runs/issues, and **push fix branches + open PRs in submodules** | `ACTIONS_ANALYTICS_TOKEN` → `DAILY_ANALYSIS_TOKEN` → `FANOUT_TOKEN` → `GITHUB_TOKEN` |
| `CLAUDE_CODE_OAUTH_TOKEN` | the fixer job | `ANTHROPIC_API_KEY` |

`FLEET_TOKEN` supersedes the three legacy PATs; they stay wired as fallbacks so
the migration is non-breaking. `dash secrets` flags them once `FLEET_TOKEN` is in
place.

Without a Claude token the loop degrades to gather + publish — the data still
lands every day.

## Files

| Path | Role |
| --- | --- |
| `.github/workflows/fleet-pulse.yml` | the daily loop (gather → publish → triage → fix) |
| `.github/actions/utilities/publish-data/action.yml` | protection-proof publish (direct push, else stable-branch PR) |
| `.github/scripts/dash-gen/remediation.py` | merges failing + expensive signals into the ranked fix queue |
| `.github/scripts/dash-gen/daily_report.py` | prior-day gather + digest generator |
| `.github/scripts/dash-gen/fleet_triage.py` | open-state (issues/PRs/CI) snapshot generator |
| `.github/scripts/dash-gen/actions_analytics.py` | Actions cost / effectiveness / waste analytics |
| `_data/fleet.yml` | central config: caps, cadences, toolchain, token contract |
| `_reports/daily/<date>.md` | committed daily digests |
| `_data/fleet_triage.yml` | committed open-state snapshot rendered at `/triage/` |
| `pages/_dash/triage.md` | the Fleet Triage portal page |
| `remediation-workorder.md` | ephemeral agent brief (gitignored; also a run artifact) |

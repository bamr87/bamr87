---
name: actions-triage
description: Read the committed Actions analytics (_data/actions_usage.yml), explain the worst workflows (cost, effectiveness, waste), and drive the next action — dispatch the actions-review issue-filer or fix a workflow directly. Use when asked "where are Actions minutes going" or after the daily actions-usage refresh.
---

# actions-triage

The analytics loop: `tools/dash-gen actions` (`actions_analytics.py`, PyGithub) writes the **committed** `_data/actions_usage.yml`, refreshed daily by `actions-usage.yml`; `actions-review.yml` is the downstream AI issue-filer. This skill is the local triage between the two.

## Steps

1. Read `_data/actions_usage.yml`. Check `generated_at` / `window_days`; if stale or missing, regenerate with `tools/dash-gen actions` (needs a GitHub token — `GH_TOKEN`/`GITHUB_TOKEN` or `gh auth login` — plus PyGithub).
2. Summarize the worst offenders. The `workflows` list is pre-sorted by `priority` (waste minutes + total minutes discounted by effectiveness). Per entry: `repo`, `workflow`, `type`, `runs`, `total_min`, `avg_min`, `p95_min`, `waste_min`, `effectiveness_pct` (share of minutes ending in success), `success_rate_pct`, `sched_pct`, `events`, and `flags` (`high-cost-low-value`, `failing`, `flaky`, `slow`, `cancel-heavy`, `cron-heavy`). Rollups live in `totals`, `by_type`, `by_repo`, `by_day`; `inactive` lists workflows that never ran in the window (prune candidates).
3. Cross-check open `actions-review`-labeled issues to avoid duplicates: `gh issue list -R bamr87/bamr87 --label actions-review --state open`.
4. Propose ONE concrete fix per flagged workflow: dependency/build caching, a `concurrency` group with `cancel-in-progress` (cancel-heavy), `timeout-minutes` (slow), `paths`/`paths-ignore` filters, a looser cron cadence (cron-heavy), or disabling/pruning an `inactive` workflow.
5. Drive the action, with approval:
   - **Deep AI pass** → `gh workflow run actions-review.yml` (deterministic candidate selection + dedupe, then an Opus reviewer files one optimization issue per candidate; `dry_run` / `max_issues` inputs).
   - **Direct fix** → edit the workflow in the owning submodule and commit in THAT repo (branch + PR per the submodule workflow) — never in the hub.

## Guardrail

`_data/actions_usage.yml` is GENERATED (its header says so) — never hand-edit it; fix the generator or the workflows it measures.

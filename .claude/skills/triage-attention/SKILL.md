---
name: triage-attention
description: Read the Monitor board health data, explain why each repo needs attention, and propose the next concrete action per repo. Use to turn monitoring signals into action, or as the input step of the self-evolution loop.
---

# triage-attention

## Steps

1. Ensure fresh data. Two complementary sources:
   - `_data/fleet_triage.yml` — the committed daily open-state snapshot (every open issue, PR with CI status, failing workflow, per-repo attention score, prioritized `inbox`). Refreshed daily by `daily-repo-analysis.yml`; regenerate on demand with `tools/dash triage`. Prefer this for issue/PR/CI triage — it has the actual items.
   - `tools/dash-gen health` (writes ephemeral `_data/project_health.yml`) — adds signals triage doesn't carry: stars, commit activity, security alerts, releases.
2. Read them and rank repos: fleet_triage's `by_repo` is pre-sorted by attention score (or use health's `attention_rank`, 🔴 first, then 🟠). Start from fleet_triage's `inbox` — it is already the prioritized queue.
3. For each flagged repo, diagnose from `attention.reasons` and propose ONE next action:
   - **CI failing** → open the failing run, summarize the error, propose a fix PR.
   - **stale (no commits)** → confirm intent; if abandoned, set `status: archived`.
   - **security alerts** → review Dependabot alerts; propose the bump.
   - **open bugs / stale issues** → triage, label, or close with reasoning.
4. Output a prioritized action list. With approval, execute the safe items and open PRs/issues (use the github MCP + the `github-issue-creator` skill at `projects/skills/.github/skills/github-issue-creator/`).

## Pairs with

`sync-project-docs` and `refresh-portfolio` in the self-evolution loop (`unified-evolution.yml` — dispatch-only, no schedule; trigger via `tools/dash evolve` or `gh workflow run unified-evolution.yml`).

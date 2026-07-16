---
name: triage-attention
description: Read the Monitor board health data, explain why each repo needs attention, and propose the next concrete action per repo. Use to turn monitoring signals into action, or as the input step of the self-evolution loop.
---

# triage-attention

## Steps
1. Ensure fresh data: `tools/dash-gen health` (writes `_data/project_health.yml`).
2. Read it and rank repos by `attention_rank` (🔴 first, then 🟠).
3. For each flagged repo, diagnose from `attention.reasons` and propose ONE next
   action:
   - **CI failing** → open the failing run, summarize the error, propose a fix PR.
   - **stale (no commits)** → confirm intent; if abandoned, set `status: archived`.
   - **security alerts** → review Dependabot alerts; propose the bump.
   - **open bugs / stale issues** → triage, label, or close with reasoning.
4. Output a prioritized action list. With approval, execute the safe items and
   open PRs/issues (use the github MCP + the `github-issue-creator` skill at
   `projects/skills/.github/skills/github-issue-creator/`).

## Pairs with
`sync-project-docs` and `refresh-portfolio` in the self-evolution loop
(`unified-evolution.yml` — dispatch-only, no schedule; trigger via
`tools/dash evolve` or `gh workflow run unified-evolution.yml`).

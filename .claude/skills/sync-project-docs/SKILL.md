---
name: sync-project-docs
description: Pull each project's current README summary and status from GitHub into the registry descriptions. Use periodically (or in the evolution loop) to keep the dash's descriptions accurate as projects progress.
---

# sync-project-docs

## Steps
1. For each project in `_data/projects.yml`, use the github MCP to read the
   repo's description, topics, latest release, and README headline.
2. Update the registry `description`, `stack`, and `status` when they have
   drifted from reality (e.g. an experiment that became active, or archived).
3. Keep descriptions to one concise line; do not overwrite hand-curated nuance
   without reason.
4. Run `tools/dash-gen readme` and propose the change as a PR (base `main`).

## Inputs
Reads recent activity via the github MCP and `git log`. Pairs with the
`triage-attention` skill in the self-evolution loop.

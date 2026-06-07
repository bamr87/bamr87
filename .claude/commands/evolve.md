---
description: Run the attention-driven self-evolution loop (or trigger the CI workflow)
---

Run the dash self-evolution loop for: $ARGUMENTS (default: all flagged repos).

1. Use the `triage-attention` skill to read `dash/_data/project_health.yml`
   (run `tools/dash-gen health` first if missing) and prioritize 🔴/🟠 repos.
2. Use `sync-project-docs` to update registry descriptions/status from reality.
3. Use `evolve-project` for the top-priority repo's improvement pass.
4. Run `tools/dash-gen readme` + `tools/check-drift.sh`, then open a PR to `main`.

To run unattended in CI instead, trigger the workflow:
`gh workflow run unified-evolution.yml`.

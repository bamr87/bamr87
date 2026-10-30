---
description: Run the attention-driven self-evolution loop (or trigger the CI workflow)
allowed-tools: Skill, Bash(tools/dash-gen:*), Bash(tools/check-drift.sh:*), Bash(gh:*), Bash(git:*)
argument-hint: '[repo name — default: all flagged repos]'
---

Run the dash self-evolution loop for: $ARGUMENTS (default: all flagged repos).

This command chains the loop's skills (`triage-attention` → `sync-project-docs` → `evolve-project` → `refresh-portfolio`); the `evolve-project` skill on its own is just the per-repo improvement step.

1. Use the `triage-attention` skill to read `_data/project_health.yml` (run `tools/dash-gen health` first if missing) and prioritize 🔴/🟠 repos.
2. Use `sync-project-docs` to update registry descriptions/status from reality.
3. Use `evolve-project` for the top-priority repo's improvement pass.
4. Run `tools/dash-gen readme` + `tools/check-drift.sh`, then open a PR to `main`.

There is no CI twin for the hub (`unified-evolution.yml` was retired on 2026-10-27): file a hub issue and the issue pipeline implements it, or run the per-submodule CI pass with `tools/dash evolve --repo <name>` / `--all` (`repo-evolution.yml`).

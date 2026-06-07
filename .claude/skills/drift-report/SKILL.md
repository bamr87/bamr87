---
name: drift-report
description: Run the dash drift gate and explain every failure in plain language with the exact fix. Use when CI drift-check fails or before opening a PR.
---

# drift-report

## Steps
1. Run `tools/check-drift.sh --report` (never fails) to list all drift.
2. For each issue, explain the cause and the fix:
   - **(a) registry/.gitmodules parity** → fix `dash/_data/projects.yml` or
     `.gitmodules`; run the `update-registry` skill.
   - **(b) stale README AUTO span** → run `tools/dash-gen readme`.
   - **(d) missing README** → create the missing `README.md`.
   - **(e) submodule branch drift** → `git -C <sub> checkout <declared-branch>`
     (verify no in-progress work first; some submodules sit on feature branches
     intentionally).
3. Offer to apply the safe, non-destructive fixes.

## Guardrail
Do not force-checkout a submodule that has uncommitted or unpushed work — surface
it and ask first.

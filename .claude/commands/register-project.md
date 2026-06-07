---
description: Add or reconcile a project in the dash registry
---

Register/reconcile project: $ARGUMENTS

Use the `update-registry` skill: ensure `dash/_data/projects.yml` has an accurate
entry (all required fields), keep it in sync with `.gitmodules`, then run
`tools/dash-gen readme` and `tools/check-drift.sh --report`. If a new submodule is
involved, walk through `git submodule add`.

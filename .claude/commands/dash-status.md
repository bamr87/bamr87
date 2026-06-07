---
description: Show submodule, registry, drift, and attention status for the dash
allowed-tools: Bash(tools/dash:*), Bash(tools/check-drift.sh:*), Bash(git submodule status)
---

Run `tools/dash status` and summarize the result: submodule branches, registry
counts, and any drift. If there is drift, briefly explain each item and the fix
(invoke the `drift-report` skill for detail). Do not make changes — this is a
read-only status command.

---
name: "source-command-dash-status"
description: "Show submodule, registry, drift, and attention status for the dash"
---

# source-command-dash-status

Use this skill when the user asks to run the migrated source command `dash-status`.

## Command Template

Run `tools/dash status` and summarize the result: submodule branches, registry counts, and any drift. If there is drift, briefly explain each item and the fix (invoke the `drift-report` skill for detail). Do not make changes — this is a read-only status command.

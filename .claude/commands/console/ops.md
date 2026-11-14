---
description: The Harness Console's operation allowlist — every operation by group with its parameters and gates, one operation in full, or the loops table ($0)
argument-hint: '[group | op | loops]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops list *), Bash(tools/dash ops show *), Bash(tools/dash ops loops *)
metadata:
  ops: []
---

# /console:ops — what the console can run

Argument: $ARGUMENTS

- Blank: `tools/dash ops list`, every operation by group (observe, plan, verify, lake, content, deploy, refine) with its gates: `confirm:write`, `confirm:spend`, `token` (needs GitHub auth), `lock:<key>` (runs alone), `unavailable`.
- A group: `tools/dash ops list --group <group>`.
- An operation: `tools/dash ops show <op>`, what it runs, its parameters and why it may be unavailable here.
- `loops`: `tools/dash ops loops`, the console's loops table with the slash command that drives each.

This is the same list the console's Operations page, the terminal dash and the `fleet` MCP server read (`tools/console/core.py` `OPS`). To run one: `/console:run <op> key=value …`, or the `/harness:` or `/loops:` command that owns it.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

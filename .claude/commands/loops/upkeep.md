---
description: The hub's upkeep loops — reconcile the registry with GitHub, regenerate the README project list, and dispatch the submodule bump, the site build or the backlog fan-out
argument-hint: '[reconcile | readme | submodules [name] | site | backlog]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run reconcile *), Bash(tools/dash ops run readme *), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [reconcile_registry, update_submodules, build_dash, backlog_fanout]
  ops: [reconcile, readme, dispatch]
---

# /loops:upkeep — the hub keeping itself current

Stage: $ARGUMENTS (no stage means `reconcile`)

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| `reconcile` | `tools/dash ops run reconcile`: renames, url mismatches, deletions and branch drift between the registry, `.gitmodules` and GitHub, reported, never applied | $0; reads GitHub |
| `readme` | `tools/dash ops run readme`: regenerate the README's project list span | $0; edits `README.md` in the working tree |
| `submodules [name]` | `tools/dash ops run dispatch workflow=update-submodules fields.submodule=<name>` | runs in Actions and opens a pointer-bump pull request: ask, then `--confirm` |
| `site` | `tools/dash ops run dispatch workflow=build-dash` | rebuilds and deploys the public site: ask, then `--confirm` |
| `backlog` | `tools/dash ops run dispatch workflow=backlog-fanout fields.dry_run=true` | runs in Actions: ask, then `--confirm` |

Applying a reconcile finding is the `update-registry` skill's job, in a pull request. Before a dispatch, run it with `--explain` and show that output.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

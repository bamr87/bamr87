---
description: The weekly cadence — Friday close-out, Saturday gather and Sunday finalize; read the triage snapshot and the decision queue locally, or dispatch one of the three in CI
argument-hint: '[triage | decisions | refresh | closeout | gather | finalize]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run triage *), Bash(tools/dash ops run decisions *), Bash(tools/dash ops run decisions-refresh *), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [weekly_closeout, weekly_gather, weekly_finalize]
  ops: [triage, decisions, decisions-refresh, dispatch]
---

# /loops:weekly — close the week, plan the next

Stage: $ARGUMENTS (blank means `decisions`)

| Stage | Runs | Cost |
| --- | --- | --- |
| `triage` | `tools/dash ops run triage`: open issues, pull requests and failing workflows across the fleet into `_data/fleet_triage.yml` | $0; reads GitHub |
| `decisions` | `tools/dash ops run decisions`: what waits on Amr, from the local index | $0 |
| `refresh` | `tools/dash ops run decisions-refresh`: read GitHub now and rewrite the index | $0; reads GitHub |
| `closeout` | `tools/dash ops run dispatch workflow=weekly-closeout` | runs in Actions: ask, then `--confirm` |
| `gather` | `tools/dash ops run dispatch workflow=weekly-gather` | runs in Actions: ask, then `--confirm` |
| `finalize` | `tools/dash ops run dispatch workflow=weekly-finalize` | runs in Actions: ask, then `--confirm` |

The CI runs never merge; what they propose waits on Amr (docs/WEEKLY-CLOSEOUT.md).

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

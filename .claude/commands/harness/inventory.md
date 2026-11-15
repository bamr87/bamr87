---
description: The AI-harness inventory against the harness standard — every AI workflow's route, caps, verdict and rebuild lever; regrade offline, rescan live, or list the fan-out gaps
argument-hint: '[offline | live [days] | gaps | lever <lever> | repo <name>]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run harnesses-offline *), Bash(tools/dash ops run harnesses *), Bash(tools/dash ops run gaps *), Read, Grep
metadata:
  ops: [harnesses-offline, harnesses, gaps]
---

# /harness:inventory — every AI workflow, graded

Stage: $ARGUMENTS (blank means `offline`)

| Stage | Runs | Cost |
| --- | --- | --- |
| `offline` | `tools/dash ops run harnesses-offline`: regrade the last scan against `_data/fleet.yml` `harnesses.standard` | $0, no GitHub |
| `live [days]` | `tools/dash ops run harnesses days=<days>`: rescan every registry repo and the hub | $0, about 550 GitHub API calls on the operator's token; say so before starting |
| `gaps` | `tools/dash ops run gaps`: the repos the kit fan-out can help (deploying them is `/loops:fanout`) | $0 |
| `lever <lever>` / `repo <name>` | no refresh: read `_data/harness_registry.yml` (`catalog`, then the matching `repos[].harnesses[]` rows) | $0 |

Both refreshes rewrite the committed `_data/harness_registry.yml` in the working tree. That file belongs to the daily `fleet-pulse` run: report what it says, and tell the person not to commit it on a feature branch.

Report: how many harnesses are on the standard out of how many, the count per lever with what each lever takes, and the controls missed most. For `lever` or `repo`, list the rows with their route and missing controls. The routes, controls and levers are explained in docs/HARNESS-OPS.md, "The harness standard".

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

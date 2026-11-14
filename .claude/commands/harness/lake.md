---
description: The local data lake the harness reads — its status, extract GitHub runs and logs, extract this machine's Claude Code sessions, review both planes ($0, writes only .dash-lake/)
argument-hint: '[status | sync [days] [repo] | sessions [days] | review [days] [repo]]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run lake-status *), Bash(tools/dash ops run lake-sync *), Bash(tools/dash ops run lake-sessions *), Bash(tools/dash ops run lake-review *)
metadata:
  ops: [lake-status, lake-sync, lake-sessions, lake-review]
---

# /harness:lake — the data the harness reads

Stage: $ARGUMENTS (blank means `status`)

| Stage | Runs |
| --- | --- |
| `status` | `tools/dash ops run lake-status`: what the lake holds, how fresh, and whether Phoenix answers |
| `sync [days] [repo]` | `tools/dash ops run lake-sync days=<days> target=<repo>`: GitHub runs, jobs, steps, logs, issues and workflow files into `.dash-lake/fleet.sqlite` (reads GitHub on the operator's token) |
| `sessions [days]` | `tools/dash ops run lake-sessions days=<days>`: this machine's Claude Code transcripts into the lake |
| `review [days] [repo]` | `tools/dash ops run lake-review days=<days> target=<repo>`: cost, turns, tools, failures and findings across both planes |

The lake is gitignored and only one writer may hold it: when the console runs a lake job, a second waits or is refused, and the message says which job holds it. `/harness:learn`, `/harness:health failures` and the loop doctors read what this writes (docs/HARNESS-OPS.md).

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

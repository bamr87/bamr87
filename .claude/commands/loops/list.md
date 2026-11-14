---
description: Every loop the harness runs — schedule, local operations, agent steps, CI dispatch, this month's loop spend, and the /loops command that drives each stage ($0)
argument-hint: '[loop]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash loop list *), Bash(tools/dash loop budget *), Bash(tools/dash ops run learn-status *)
metadata:
  ops: [learn-status]
---

# /loops:list — the loops and how to drive them

Loop: $ARGUMENTS (blank means all of them)

1. `tools/dash ops loops`: the console's loops table (the same one its Loops page draws), each loop with its schedule, local operations, local agent steps, CI dispatch and slash command.
2. `tools/dash loop list`: each local agent step's model, turn cap, dollar cap and switch.
3. `tools/dash loop budget`: this month's loop spend against `budget.loops` (API-equivalent, an estimate).
4. With a loop named, or when it helps: `tools/dash ops run learn-status` for whether its output is landing.

Present one row per loop: what it does, when it runs, its switch, its command. Then the stage ladder every `/loops:` command shares:

| Stage | What it does | Cost and gate |
| --- | --- | --- |
| (none) | where the loop stands | $0 |
| `plan` | what the next run would do: the sample, the briefs, the queue | $0 |
| `rehearse` | everything up to the model call | $0 |
| `run` | the agent step here, one capped attempt per item, a reviewable preview under `.fleet/runs/` | Claude spend: asks first |
| `show` / `publish <run_id>` | read a run's preview; `publish` checks it, then with `apply` files it | filing writes to GitHub: asks first |
| `ci` | the loop's workflow in GitHub Actions, dry run unless told otherwise | runs in CI: asks first |

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

---
description: Run any operation from the Harness Console's allowlist with the console's own validation and confirm gate — explains first, asks before a GitHub write or Claude spend
argument-hint: '<op> [key=value ...]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops show *), Bash(tools/dash ops run * --explain), AskUserQuestion
metadata:
  ops: []
---

# /console:run — one operation, through the console's front door

Operation and parameters: $ARGUMENTS

1. `tools/dash ops show <op>`: what it runs, its parameters and gates. An unknown operation or parameter is refused; say which, and list the right ones (`/console:ops`).
2. `tools/dash ops run <op> key=value … --explain`: the exact argv, the gate and whether it can run here. Runs nothing.
3. No gate: run it, `tools/dash ops run <op> key=value …`. A gate (`confirm (write)` or `confirm (spend)`): show the person the explain output, ask with AskUserQuestion, and only after a yes run it with `--confirm` added.

Parameters are `key=value`; the dispatch operation's workflow inputs are `fields.<input>=<value>`. When the console is running for this checkout the job runs there (it shows on the Jobs page, and the console's locks apply); otherwise it runs here with the same argv. Exit codes: 2 a bad parameter, 3 the gate wants `--confirm`, 4 it cannot run here (the message says why: no docker, no `claude`, switched off), 5 no console answered `--console`, 6 the console holds the lock this operation needs. Report the exit and what the output showed.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

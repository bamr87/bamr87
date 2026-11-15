---
description: The running Harness Console's jobs — the recent ones from the page, the terminal dash, MCP and slash commands, or follow one to its end ($0, read-only)
argument-hint: '[job-id]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops jobs *)
metadata:
  ops: []
---

# /console:jobs — what the console has run

Job: $ARGUMENTS

- Blank: `tools/dash ops jobs`, the console's recent jobs with status, operation and start time.
- A job id: `tools/dash ops jobs <job-id>`, its log streamed until it finishes; its exit is the job's outcome.

It needs a running console (`tools/dash console`, or the compose service) at `DASH_CONSOLE_URL` (default `http://127.0.0.1:4001`), with `DASH_CONSOLE_TOKEN` set when the console requires one. When none answers, say so: jobs run by `tools/dash ops run` without a console ran in the terminal and are not listed anywhere. Report failures with the line of the log that says why.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

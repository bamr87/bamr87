---
description: The harness at a glance — drift, the six-layer scorecard, what waits on Amr, and whether each loop's output is landing ($0, read-only)
argument-hint: '[focus: a repo, loop or layer to look at first]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run status *), Bash(tools/dash ops run harness *), Bash(tools/dash ops run decisions *), Bash(tools/dash ops run learn-status *), Bash(tools/dash ops loops *), Read
metadata:
  ops: [status, harness, decisions, learn-status]
---

# /harness:status — the harness at a glance

Focus: $ARGUMENTS (blank means the whole hub)

Run these four in order. Each is read-only and $0; `decisions` reads GitHub only when its local index is past its TTL.

1. `tools/dash ops run status`: submodules, registry and drift.
2. `tools/dash ops run harness`: the six-layer scorecard and its trip wires (`_data/harness_health.yml`, docs/HARNESS.md).
3. `tools/dash ops run decisions`: what waits on Amr (`needs-amr`, ratifications, Dependabot, ready to merge). If it fails for want of a GitHub token, say so and carry on.
4. `tools/dash ops run learn-status`: per loop, how much output landed, was rejected, went stale or is still open (shadow; it needs the local lake, so say so when the lake is empty).

Answer in this order: a one-line verdict; drift, each item with its fix, or "none"; the red and amber layers and every tripped wire; the decision queue as counts by kind with the oldest item; the loops whose output is not landing. Apply the focus when one was given. End with the one or two commands to run next (`/harness:inventory`, `/harness:health`, `/harness:gates`, `/loops:list`, `/loops:<loop> <stage>`). Change nothing.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

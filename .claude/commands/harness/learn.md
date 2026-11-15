---
description: Outcome learning, shadow only — what happened to each loop's output, where its next slots would pay, and the replay test ($0, read-only)
argument-hint: '[status | plan | replay] [loop]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run learn-status *), Bash(tools/dash ops run learn-plan *), Bash(tools/dash learn *)
metadata:
  ops: [learn-status, learn-plan]
---

# /harness:learn — did the loops' output land?

View and loop: $ARGUMENTS (blank means `status` for every loop)

- `status`: `tools/dash ops run learn-status`. Per loop: landed, rejected, stale, working and young, the landing estimate and the backlog advice.
- `plan`: `tools/dash ops run learn-plan`. The share of the next slots each repo would get, beside what the loop filed lately.
- `replay`, or any view for one loop: `tools/dash learn <view> --loop <loop>` (a loop of `learning.loops` in `_data/fleet.yml`).

It reads the local lake and steers nothing (docs/LEARNING.md). When the lake is empty or stale, say so and name `/harness:lake sync`. Report the loops whose output is not landing first, with the reason the outcomes show.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

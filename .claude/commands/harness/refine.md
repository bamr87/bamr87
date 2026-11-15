---
description: Harness² refinement — check a harness surface, plan one Propose–Probe–Compose step, build a loop's evidence tree, check the experience library; reflect on the week's incidents (asks first)
argument-hint: '[surface [target|fleet] | plan <loop> [step] | evidence <loop> <item> | library | reflect]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run refine-surface *), Bash(tools/dash ops run refine-plan *), Bash(tools/dash ops run refine-evidence *), Bash(tools/dash ops run refine-library-check *), Bash(tools/dash refine reflect --rehearse *), AskUserQuestion
metadata:
  ops: [refine-surface, refine-plan, refine-evidence, refine-library-check]
---

# /harness:refine — refine the harness from its own runs

Stage: $ARGUMENTS (blank means `surface`)

| Stage | Runs | Cost |
| --- | --- | --- |
| `surface [target]` | `tools/dash ops run refine-surface target=<name or fleet>`: the hub's surface, one submodule's, or every checked-out one | $0 |
| `plan <loop> [step]` | `tools/dash ops run refine-plan loop=<loop> step=<step>`: the schedule, the ceiling against `budget.loops`, the tunable files and the read-only hard rules | $0 |
| `evidence <loop> <item>` | `tools/dash ops run refine-evidence loop=<loop> item=<owner/repo>`: the redacted evidence tree from that loop's real local attempts, under `.fleet/refine/` | $0 |
| `library` | `tools/dash ops run refine-library-check`: every entry under `_data/harness_library` is well-formed and carries nothing private | $0 |
| `reflect` | `tools/dash refine reflect --rehearse` first ($0); a real reflection is ONE capped Claude session that previews lessons | spend: ask, then `tools/dash refine reflect` |

A loop here is a `tools/jev/steps/` directory (`repo-scout`, `repo-evolution`, `fleet-pulse`, `fanout`). A refinement edits only a loop's tunable half, never a step spec (docs/HARNESS-REFINEMENT.md). Filing the reflector's lessons is `tools/dash refine reflect publish <stamp> --apply`, a draft pull request: a separate GitHub write that needs its own yes.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

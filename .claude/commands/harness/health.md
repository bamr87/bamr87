---
description: The hub's harness health — the six-layer scorecard and trip wires, the agent inventory's contract gaps, and why recent workflow runs failed ($0, read-only)
argument-hint: '[layers | agents | failures [days]]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run harness *), Bash(tools/dash ops run agents *), Bash(tools/dash workflows health *), Read
metadata:
  ops: [harness, agents]
---

# /harness:health — is the harness itself healthy?

Part: $ARGUMENTS (blank means `layers` then `agents`)

| Part | Runs | Reads |
| --- | --- | --- |
| `layers` | `tools/dash ops run harness` | the six layers and their trip wires from the committed signals (docs/HARNESS.md) |
| `agents` | `tools/dash ops run agents` | every agent against the efficacy contract (constitution § 29, docs/AGENT-EFFICACY.md): owner, trigger, switch, cap, model, KPIs, and the sources it reads that nothing writes |
| `failures [days]` | `tools/dash workflows health --days <days>` | why the hub's workflow runs failed, classified from the local lake (docs/WORKFLOW-ATLAS.md); say so when the lake is empty |

All three are read-only and $0. `agents` checks the committed `_data/agents.yml` and rewrites nothing; when it reports the file stale, say that `tools/dash agents` regenerates it, and do not run that here.

Report each red or amber layer and tripped wire with its cause, each agent contract gap grouped by rule, and the failure classes with the workflows they hit. Name the command that would fix or rebuild each one (`/harness:inventory`, `/loops:<loop>`, `/harness:gates`).

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

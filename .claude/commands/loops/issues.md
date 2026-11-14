---
description: The issue pipeline, one stage at a time — rebuild the three tiers' queues, build one issue's evidence bundle, or dispatch intake, implement or complete in CI
argument-hint: '[queues | evidence <owner/repo> <number> | ci [tiers] [repos]]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run issues *), Bash(tools/dash ops run evidence *), Bash(tools/dash ops run dispatch * --explain), Read, Skill, AskUserQuestion
metadata:
  loops: [issue_pipeline]
  ops: [issues, evidence, dispatch]
---

# /loops:issues — intake → implement → complete

Stage: $ARGUMENTS (no stage means: read where the queues stand in `_data/issue_pipeline.yml`)

The pipeline is label-driven: intake builds an evidence bundle, implement opens a pull request, complete takes it through CI; it never merges, and `agent:hold` or `human-review` stop it (docs/ISSUE-PIPELINE.md). Its tiers run in CI only; locally you plan and gather evidence.

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| (none) | read `_data/issue_pipeline.yml`: the count per tier and the oldest item in each | $0 |
| `queues` | `tools/dash ops run issues`: classify the fleet's open issues into the three tiers, with work orders | $0; reads GitHub |
| `evidence <owner/repo> <number>` | `tools/dash ops run evidence repo=<owner/repo> number=<n>`: one issue's evidence, built in an isolated virtual environment | $0; local files only |
| `ci [tiers] [repos]` | `tools/dash ops run dispatch workflow=issue-pipeline fields.tiers=<all, 1, 2, 3, 1-2 or 2-3> fields.repos=<names> fields.dry_run=true` | runs in Actions, and tiers 2–3 spend Claude budget there: ask, then `--confirm` |

`queues` rewrites the committed `_data/issue_pipeline.yml` in the working tree; it belongs to the scheduled run, so do not commit it on a feature branch. For walking one issue through the tiers and explaining why an issue sits where it does, use the `issue-pipeline` skill. Before `ci`, run it with `--explain` and show that output.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

---
description: Stargazer, the open-source radar — read GitHub's stars and trending now, run the AI review pass, push the radar to Grafana, or dispatch the loop in CI
argument-hint: '[refresh | review [limit] | metrics | ci]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run stars-refresh *), Bash(tools/dash ops run stars-review * --explain), Bash(tools/dash ops run stars-metrics *), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [stargazer]
  ops: [stars-refresh, stars-review, stars-metrics, dispatch]
---

# /loops:stargazer — the open-source radar

Stage: $ARGUMENTS (no stage means: where the loop stands, from `tools/dash ops loops`)

Stargazer reads the account's stars, the repos rising in the fleet's topics and the repos most like each fleet project into `_data/stars.json`, and an optional AI pass lays verdicts over them (docs/STARGAZER.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| (none) | `tools/dash ops loops` | $0 |
| `refresh` | `tools/dash ops run stars-refresh`: stars, trending and like-the-fleet → `_data/stars.json` + `_data/stars_history.json`; read-only on GitHub | $0 |
| `review [limit]` | `tools/dash ops run stars-review limit=<n>`: tool-less, capped Claude sessions → `_data/stars_ai.json` | Claude spend: ask, then `--confirm` |
| `metrics` | `tools/dash ops run stars-metrics`: the radar as gauges to the local OTel collector (needs `tools/dash observe up`) | $0 |
| `ci` | `tools/dash ops run dispatch workflow=stargazer` | runs in Actions: ask, then `--confirm` |

Before a gated call, run it with `--explain` and show that output.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

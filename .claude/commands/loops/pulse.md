---
description: Fleet pulse, one stage at a time — gather the fleet's signals, build the doctor's fix queue, rehearse or run the doctor locally, show or publish a run, or dispatch the daily loop in CI
argument-hint: '[gather [triage|actions|ai-usage|harnesses|harness] | queue | plan | rehearse | run | show [run_id] | publish <run_id> [item] | doctor | ci] [repo]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run triage *), Bash(tools/dash ops run actions *), Bash(tools/dash ops run ai-usage *), Bash(tools/dash ops run harnesses *), Bash(tools/dash ops run harness *), Bash(tools/dash ops run remediate *), Bash(tools/dash ops run refine-plan *), Bash(tools/dash loop plan fleet-pulse *), Bash(tools/dash loop show *), Bash(tools/dash loop doctor fleet-pulse), Bash(tools/dash loop budget *), Bash(tools/dash ops run loop-run * --explain), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [fleet_pulse]
  ops: [triage, actions, ai-usage, harnesses, harness, remediate, refine-plan, loop-run, dispatch]
---

# /loops:pulse — the daily fleet loop

Stage and repo: $ARGUMENTS (no stage means: where the loop stands)

Fleet pulse gathers every fleet signal in one commit, ranks the failing and expensive workflows, and its `doctor` step opens fix pull requests. Schedule, switch (`FLEET_PULSE_ENABLED`), model and caps: `tools/dash ops loops` and `tools/dash loop list` (docs/DAILY-ANALYSIS.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| (none) | `tools/dash ops loops`, then `tools/dash loop show --latest` | $0 |
| `gather [signal…]` | one `tools/dash ops run <signal>` each, default `triage actions harness`: `triage`, `actions days=14`, `ai-usage days=14`, `harnesses days=14` (about 550 API calls), `harness` | $0; reads GitHub |
| `queue` | `tools/dash ops run remediate`: the doctor's ranked fix queue | $0; reads GitHub |
| `plan [repo]` | `tools/dash loop plan fleet-pulse --target <repo>` | $0 |
| `rehearse [repo]` | `tools/dash ops run loop-run loop=fleet-pulse target=<repo> rehearse=true` | $0 |
| `run [repo]` | `tools/dash ops run loop-run loop=fleet-pulse target=<repo>` | Claude spend: ask, then `--confirm` |
| `show [run_id]` | `tools/dash loop show <run_id>` (or `--latest`) | $0 |
| `publish <run_id> [item]` | `tools/dash ops run loop-run loop=fleet-pulse run_id=<id> item=<owner/repo:path>` (read-only check); filing is the same with `apply=true` | filing opens a fix pull request: ask, then `--confirm` |
| `doctor` | `tools/dash loop doctor fleet-pulse` (never `--live` from here) | $0 |
| `ci` | `tools/dash ops run dispatch workflow=fleet-pulse fields.dry_run=true` | runs in Actions: ask, then `--confirm` |

`gather` and `queue` rewrite committed snapshots under `_data/` in the working tree. Those files belong to the daily run: report what they show, and tell the person not to commit them on a feature branch. Before a gated call, run it with `--explain` and show that output.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

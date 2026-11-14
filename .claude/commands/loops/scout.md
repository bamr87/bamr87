---
description: Repo scout, one stage at a time — plan today's sample, rehearse, run the scout agent locally, show or publish a run, or dispatch the loop in CI
argument-hint: '[plan | rehearse | run | show [run_id] | publish <run_id> [item] | doctor | ci] [repo]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run scout *), Bash(tools/dash ops run refine-plan *), Bash(tools/dash loop plan repo-scout *), Bash(tools/dash loop show *), Bash(tools/dash loop doctor repo-scout), Bash(tools/dash loop budget *), Bash(tools/dash ops run loop-run * --explain), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [repo_scout]
  ops: [scout, refine-plan, loop-run, dispatch]
---

# /loops:scout — the daily issue-proposal loop

Stage and repo: $ARGUMENTS (no stage means: where the loop stands)

The scout reads a rotating sample of owned repositories and proposes issues; the workflow's `file` job opens them for the issue pipeline. The agent holds no GitHub credential. Schedule, switch (`REPO_SCOUT_ENABLED`), model and caps: `tools/dash ops loops` and `tools/dash loop list` (docs/SCOUT.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| (none) | `tools/dash ops loops`, then `tools/dash loop show --latest` | $0 |
| `plan [repo]` | `tools/dash ops run scout` (today's sample and briefs, offline); for one repo `tools/dash loop plan repo-scout --target <repo>` | $0 |
| `rehearse [repo]` | `tools/dash ops run loop-run loop=repo-scout target=<repo> rehearse=true` | $0 |
| `run [repo]` | `tools/dash ops run loop-run loop=repo-scout target=<repo>` (blank repo: today's sample, one attempt each) | Claude spend: ask, then `--confirm` |
| `show [run_id]` | `tools/dash loop show <run_id>` (or `--latest`) | $0 |
| `publish <run_id> [item]` | `tools/dash ops run loop-run loop=repo-scout run_id=<id> item=<owner/repo>` (matches or differs, read-only); filing is the same with `apply=true` | filing opens issues: ask, then `--confirm` |
| `doctor` | `tools/dash loop doctor repo-scout` (never `--live` from here) | $0 |
| `ci [repo]` | `tools/dash ops run dispatch workflow=repo-scout fields.target=<repo> fields.dry_run=true`: the scout runs in Actions and, with `dry_run=true`, its `file` job opens no issue (the local `publish` stage is unrelated) | runs in Actions: ask, then `--confirm`; `dry_run=false` only when asked |

Before a gated call, run it with `--explain` and show that output. After `run`, show the preview's proposals and the run id, and offer `publish`. To tune the loop rather than run it: `/harness:refine plan repo-scout`.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

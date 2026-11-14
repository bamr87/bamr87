---
description: Repo evolution, one stage at a time — plan the opted-in repos' briefs, rehearse, run the builder locally, show or publish a run, dispatch it in CI, or evolve the hub itself
argument-hint: '[plan | rehearse | run | show [run_id] | publish <run_id> [item] | doctor | ci | hub] [repo]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run targets *), Bash(tools/dash ops run refine-plan *), Bash(tools/dash loop plan repo-evolution *), Bash(tools/dash loop show *), Bash(tools/dash loop doctor repo-evolution), Bash(tools/dash loop budget *), Bash(tools/dash ops run loop-run * --explain), Bash(tools/dash ops run dispatch * --explain), Skill, AskUserQuestion
metadata:
  loops: [repo_evolution]
  ops: [targets, refine-plan, loop-run, dispatch]
---

# /loops:evolution — the improvement loop

Stage and repo: $ARGUMENTS (no stage means: where the loop stands)

Repo evolution takes one unit of work in each `auto_evolve` submodule and opens one draft pull request in that repository; it never merges. Schedule, switch (`REPO_EVOLUTION_ENABLED`), model and caps: `tools/dash ops loops` and `tools/dash loop list` (docs/EVOLUTION.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| (none) | `tools/dash ops loops`, then `tools/dash loop show --latest` | $0 |
| `plan [repo]` | `tools/dash ops run targets` (the opt-ins and their briefs, offline); for one repo `tools/dash loop plan repo-evolution --target <repo>` | $0 |
| `rehearse [repo]` | `tools/dash ops run loop-run loop=repo-evolution target=<repo> rehearse=true` | $0 |
| `run [repo]` | `tools/dash ops run loop-run loop=repo-evolution target=<repo>` | Claude spend: ask, then `--confirm` |
| `show [run_id]` | `tools/dash loop show <run_id>` (or `--latest`) | $0 |
| `publish <run_id> [item]` | `tools/dash ops run loop-run loop=repo-evolution run_id=<id> item=<owner/repo>` (read-only check); filing is the same with `apply=true` | filing opens a draft pull request: ask, then `--confirm` |
| `doctor` | `tools/dash loop doctor repo-evolution` (never `--live` from here) | $0 |
| `ci [repo]` | `tools/dash ops run dispatch workflow=repo-evolution fields.target=<repo> fields.dry_run=true` | runs in Actions: ask, then `--confirm` |
| `hub` | the hub's own evolution, which has no CI pass: the `triage-attention` skill on `_data/project_health.yml`, `sync-project-docs`, `evolve-project` for the top item, `refresh-portfolio`, then `/harness:gates` and a pull request to `main` that waits for Amr | spend of this session; never pushes to `main` |

Before a gated call, run it with `--explain` and show that output. To tune the loop rather than run it: `/harness:refine plan repo-evolution`.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

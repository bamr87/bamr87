---
description: The PM review, one view at a time — every open issue and pull request against the Fleet project, the roadmap and the release trains; read-only, or dispatch it in CI
argument-hint: '[review | plan | roadmap | releases | status | ci]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run pm *), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [fleet_pm]
  ops: [pm, dispatch]
---

# /loops:pm — is the open work where the plan says?

View: $ARGUMENTS (blank means `status`, then `review` when the person asks for a fresh read)

| View | Runs | Cost |
| --- | --- | --- |
| `review` | `tools/dash ops run pm view=review`: reads every open issue and pull request of the registry repos, their comments, the releases and the Fleet project, and writes only local files | $0; reads GitHub |
| `plan` | `tools/dash ops run pm view=plan`: the Fleet project ops the last review proposes, before and after | $0 |
| `roadmap` | `tools/dash ops run pm view=roadmap`: the roadmap status edits it proposes | $0 |
| `releases` | `tools/dash ops run pm view=releases`: each release train | $0 |
| `status` | `tools/dash ops run pm view=status`: the committed snapshot's headline | $0 |
| `ci` | `tools/dash ops run dispatch workflow=fleet-pm fields.dry_run=true` | runs in Actions: ask, then `--confirm` |

This command never applies anything. Applying the Fleet project plan is a constitution § 11 write (`tools/console/gh_projects_write.py`: plan, show the diff, apply only after Amr confirms); say what it would change and leave it to him (docs/PM.md).

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

---
description: Kit fan-outs, one stage at a time — list the gap repos, deploy the agent-context kit to one repo or every gap (dry run first, then asks), fill a kit's scaffold with the agent, or dispatch fanout.yml
argument-hint: '[gaps | deploy <repo|gaps> [artifacts] [upgrade] | fill <schema|standardize> <repo> | ci <kit> [target]]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run gaps *), Bash(tools/dash ops run deploy-target * --explain), Bash(tools/dash ops run deploy-gaps * --explain), Bash(tools/dash loop plan fanout *), Bash(tools/dash loop show *), Bash(tools/dash ops run loop-run * --explain), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [harness_fanout]
  ops: [gaps, deploy-target, deploy-gaps, loop-run, dispatch]
---

# /loops:fanout — kits pushed down into the fleet

Stage: $ARGUMENTS (no stage means `gaps`)

Fan-outs are dry runs by default, open pull requests only, and add without overwriting: a hand-edited file is never touched, and `upgrade` replaces only a byte-identical machine seed (docs/HARNESS-OPS.md, docs/STANDARDS.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| `gaps` | `tools/dash ops run gaps`: the repos the kit can help, from `_data/harness_registry.yml` with `harnesses.exempt` read live | $0 |
| `deploy <repo>` | `tools/dash ops run deploy-target target=<repo> artifacts=claude upgrade=true` (dry run: the diff each repo would get), then with `apply=true` | opens a pull request in that repo: ask, then `--confirm` |
| `deploy gaps` | `tools/dash ops run deploy-gaps artifacts=claude upgrade=true` (dry run), then with `apply=true` | one pull request per gap repo: ask, then `--confirm` |
| `fill <kit> <repo>` | `tools/dash ops run loop-run loop=fanout step=agent-fill-<kit> target=<repo> rehearse=true`, then without `rehearse` | Claude spend fills the scaffold's TODOs: ask, then `--confirm` |
| `ci <kit> [target]` | `tools/dash ops run dispatch workflow=fanout fields.kit=<kit> fields.target=<target> fields.dry_run=true` | runs in Actions: ask, then `--confirm` |

Show the dry run's target list and per-repo diffstat before asking. After an apply, list each pull request it opened; they wait for review in their own repositories.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

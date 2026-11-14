---
description: Merge conflicts through JEV's tiers — scan the fleet, triage one pull request, resolve one or sweep them all (dry run first, then asks), the month's budget, or dispatch the CI scan
argument-hint: '[scan [owner/repo] | triage <owner/repo#n> | resolve <owner/repo#n> | sweep | budget | ci]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run conflicts *), Bash(tools/dash ops run conflicts-resolve dry_run=true), Bash(tools/dash ops run conflicts-resolve * dry_run=true), Bash(tools/dash ops run conflicts-resolve * --explain), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [jev_conflicts]
  ops: [conflicts, conflicts-resolve, dispatch]
---

# /loops:conflicts — conflicts resolve themselves, cheapest tier first

Stage: $ARGUMENTS (no stage means `scan`)

JEV reproduces each conflict in a throwaway clone, classifies it, and spends the cheapest thing that settles it: nothing for generated, fragment and union files, a cheap model for small conflicts, a strong one for large, a person for the rest. Each tier resolves with a merge commit pushed to the pull request's branch after the repo's own checks pass; never a rebase, a force-push or a merge, and a model's resolution carries `needs-amr` (constitution § 12.7, docs/JEV.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| `scan [owner/repo]` | `tools/dash ops run conflicts action=scan repo=<owner/repo>` | $0; reads GitHub |
| `triage <owner/repo#n>` | `tools/dash ops run conflicts action=triage pr=<owner/repo#n>`: the trial merge and the tier that would settle it | $0 |
| `resolve <owner/repo#n>` | `tools/dash ops run conflicts-resolve pr=<owner/repo#n> dry_run=true` first; then, after a yes, the same without `dry_run` and with `--confirm` | pushes a merge commit, and tiers 1–2 spend Claude budget |
| `sweep` | `tools/dash ops run conflicts-resolve dry_run=true` first; then, after a yes, `tools/dash ops run conflicts-resolve --confirm` | every conflicting pull request up the tiers |
| `budget` | `tools/dash ops run conflicts action=budget`: the engine's month against its cap | $0 |
| `ci` | `tools/dash ops run dispatch workflow=jev-conflicts fields.dry-run=true`: the free tier in Actions | runs in Actions: ask, then `--confirm` |

Show the dry run's decision for each pull request (its tier, and what it would push) before asking. Report each result with its link; a pull request that needs a person stays with Amr.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

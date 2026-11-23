---
description: Fleet uplift — what one repo improved that the others still lack, which rollouts have not landed, and the work order for judging the candidates ($0, reads local git only)
argument-hint: '[scan | show <key> | brief [key …] | verify | status] [--days N] [--repo name]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run uplift *), Bash(tools/dash uplift scan *), Bash(tools/dash uplift show *), Bash(tools/dash uplift brief *), Bash(tools/dash uplift verify *), Bash(tools/dash uplift status *)
metadata:
  ops: [uplift]
---

# /harness:uplift — what should spread from one repo to the rest?

View: $ARGUMENTS (blank means `scan`)

- `scan`: `tools/dash ops run uplift`. Candidates (one repo changed a file other repos still hold in an earlier version, with the kit or patch route), rollouts in flight (a kit or hub change that has not reached everyone), forked seeds and the features each repo declared or shipped. For another window or one repo's changes: `tools/dash uplift scan --days N --repo <name>`.
- `show <key>`: `tools/dash uplift show <key>`. One candidate or rollout in full, with its diff.
- `brief`: `tools/dash uplift brief --top 5`, or `tools/dash uplift brief <key> …`. The work order: judge each candidate as the `uplift` skill sets out (is it general, where does it belong, who gets it, what proves it landed).
- `verify`: `tools/dash uplift verify`. Re-derives who is behind a second way and fails when the scan disagrees; run it when a count looks wrong, and report a failure as a defect in the scan, not as a finding about the fleet.
- `status`: `tools/dash uplift status`. The last scan's headline.

It reads the local submodule checkouts, never GitHub, and calls no model (docs/UPLIFT.md). Report the candidates you judge general first, each with its key, the repos behind and its route; then the rollouts still in flight; then anything listed as NOT READ or STALE, which is unknown, not quiet.

Capturing a candidate is not pre-approved here. `tools/dash uplift file <key>` writes a preview and files nothing; `tools/dash uplift file <key> --apply` files the previewed bytes as a hub issue, and is run only when the person asks for it, for the keys they name.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

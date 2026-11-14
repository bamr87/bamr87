---
description: The decision queue — what waits on Amr across the fleet in one call (needs-amr, ratifications, Dependabot, ready to merge); read-only
argument-hint: '[refresh] [kind] [owner/repo]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run decisions *), Bash(tools/dash ops run decisions-refresh *), Bash(tools/dash decisions queue *)
metadata:
  ops: [decisions, decisions-refresh]
---

# /harness:decisions — what waits on Amr

Arguments: $ARGUMENTS

- No arguments: `tools/dash ops run decisions`, the queue from the local index (it reads GitHub only when the index is past its TTL).
- `refresh`: `tools/dash ops run decisions-refresh` first (reads every open pull request and gate-labelled issue again; it fails unless the read finished clean), then the queue.
- A kind or a repository: `tools/dash decisions queue --kind <kind> --repo <owner/repo>`.

Use this, never a sweep of each repository (docs/DECISION-INDEX.md). Report the items grouped by kind, oldest first, each with its link and what it waits for. "Ready to merge" is mechanical: a gated pull request still needs Amr, and merging is never done from here (constitution § 12).

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

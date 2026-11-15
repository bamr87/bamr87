---
description: Credential rotation, one stage at a time — audit secrets and API keys by name, plan a rotation, verify keys, then push, rotate or project the auth order (dry run first, then asks)
argument-hint: '[status | plan | verify | watch | push [secret] | rotate | keys-rotate | auth-sync [repo] | ci]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops loops *), Bash(tools/dash ops run secrets-audit *), Bash(tools/dash ops run secrets-plan *), Bash(tools/dash ops run keys-status *), Bash(tools/dash ops run keys-watch *), Bash(tools/dash ops run ai-auth *), Bash(tools/dash ops run secrets-push * --explain), Bash(tools/dash ops run secrets-rotate * --explain), Bash(tools/dash ops run keys-rotate * --explain), Bash(tools/dash ops run ai-auth-sync * --explain), Bash(tools/dash ops run dispatch * --explain), AskUserQuestion
metadata:
  loops: [token_rotation]
  ops: [secrets-audit, secrets-plan, keys-status, keys-verify, keys-watch, ai-auth, secrets-push, ai-auth-sync, keys-rotate, secrets-rotate, dispatch]
---

# /loops:credentials — the fleet's credentials

Stage: $ARGUMENTS (no stage means `status`)

Every operation here handles credential NAMES, never values: never print, echo, read or paste a secret or a key, never open `.env`, and never put a value in an argument (docs/TOKEN-ROTATION.md).

| Stage | Runs | Cost and gate |
| --- | --- | --- |
| `status` | `tools/dash ops run secrets-audit`, `tools/dash ops run keys-status`, `tools/dash ops run ai-auth` | $0; reads GitHub |
| `plan` | `tools/dash ops run secrets-plan`: each repo's credential age and what a rotation would rewrite | $0 |
| `verify` | `tools/dash ops run keys-verify`: one cheap API call per Anthropic key | cents of API spend: say so first |
| `watch` | `tools/dash ops run keys-watch`: the deployed keys against the lifetime policy | $0 |
| `push [secret]` | `tools/dash ops run secrets-push secret=<NAME>` (dry run), then with `apply=true` | writes repo secrets hub-first: ask, then `--confirm` |
| `rotate` | `tools/dash ops run secrets-rotate` (dry run), then with `apply=true` | the weekly loop now: ask, then `--confirm` |
| `keys-rotate` | `tools/dash ops run keys-rotate` (dry run), then with `apply=true` | new keys to their repos, old keys disabled: ask, then `--confirm` |
| `auth-sync [repo]` | `tools/dash ops run ai-auth-sync target=<repo>` (dry run), then with `apply=true` | writes `CLAUDE_AUTH_ORDER` variables: ask, then `--confirm` |
| `ci` | `tools/dash ops run dispatch workflow=token-rotation fields.apply=false` | runs in Actions: ask, then `--confirm` |

A fleet-wide secret is written hub-first, and the fan-out stops if the hub refuses (AGENTS.md). Report names, ages and repositories only.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.

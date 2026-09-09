# `ai-runner` — the fleet's AI step and lane, versioned once

Every AI lane in the fleet is the same job: gate on a repo variable, check a credential exists, run one Claude Code agent against the repo, have it open ONE pull request a human merges. The 2026-09-06 review of the content/AI workspace found that shape hand-rolled in ~60 workflows across 11 repos, with three divergent copies of one `claude-run` action (three hashes, one name) and two of them exiting 0 on a dead credential. This kit is that job, written once, **consumed by reference** — a consumer follows the hub at `@main` and receives every fix on its next run, with nothing to copy forward and nothing to drift.

## The two things a repo can reference

| Reference | Use it when | What it gives you |
| --- | --- | --- |
| `uses: bamr87/bamr87/.github/actions/claude-run@main` | You keep your own workflow shape (a planning job feeding a matrix, a multi-job pipeline, a `workflow_run` trigger) and only want the model step | Claude Code first, OAuth-first, model from the consumer's `_data/ai.yml`, optional API fallback and metering, exit 1 on attempted-and-failed. Inputs: `prompt`, `agent`, `tools`, `mcp`, `system`, `out`, `model`, `max-turns` |
| `uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main` | The lane IS the standard shape | Everything above plus the kill switch (`switch:` names the `*_ENABLED` variable; `workflow_dispatch` bypasses it), the bot guard, named concurrency (writers never cancelled), a probed `GH_PAT` exported as `GH_TOKEN`, Ruby/Node/Python setup, `pre-run`/`post-run` hooks for the repo's own harness, the `result-file` assertion ("the agent produced nothing" is RED), and an artifact |

[`ai-lane.template.yml`](ai-lane.template.yml) is a complete caller: copy it once per lane and fill `__LANE__`, `__SWITCH__`, `__AGENT__`, `__PROJECT_NAME__`. Least privilege is declared **there** — a called workflow inherits the caller job's `permissions` and can only narrow them.

## What stays in the consumer repo, by design

| Consumer file | Role | Required |
| --- | --- | --- |
| `_data/ai.yml` | `model:` (and `fallback_model`, `max_tokens` for the API fallback) | recommended; the runner falls back to the fleet default |
| `.claude/agents/<name>.md` | The role the lane runs as (`agent:`) | per lane |
| `scripts/ai/usage.rb`, `usage_report.rb` | Metering: one JSONL record per call, step summary, `ai-usage-*` artifact, sticky PR cost comment | optional |
| `scripts/ai/api_call.rb` or `.py` | The single-shot Claude API fallback | optional |
| `tools/unwrap-prose.py`, `.prose-excludes` | Post-run one-paragraph-per-line normalizer (the `prose` kit's gate) and its extra excludes, one extended regex per line | optional |
| `<LANE>_ENABLED` repo **variable** | The kill switch. Default OFF: a lane idles until it is `true` | per scheduled lane |
| The verification harness | Whatever proves the agent's work (`scripts/ci/run-all.sh`, `make cms-all`, …) — passed as `pre-run`/`post-run`, or run by the agent | per repo |

Canonical environment (no repo prefix, so nothing is repo-specific): `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `AI_MODEL`, `AI_FORCE_API`, `AI_MAX_TURNS`, `AI_USAGE_DIR`, `AI_ROLE`, `AI_REPO_ROOT`.

## Exit contract

| Exit | Meaning |
| --- | --- |
| `0` | The call ran, **or** nothing was attempted (no `claude` on PATH and no API key — the documented no-op, so a human running a skill locally without credentials degrades gracefully) |
| `1` | The call was attempted and failed with no usable fallback. The reason (auth rejected, quota exhausted, model unavailable) is printed and raised as a `::error::` annotation. Before the kit, this case exited 0 and the lane learned of it a step later as a generic "no PR was opened" |

## Not expressible as the reusable lane

Keep your own workflow and reference only the action for: matrices computed by a planning job (call the lane once per item from the caller, as it-journey's `quest-fix-loop.yml` already does), multi-job pipelines with artifact hand-offs, lanes that check out ANOTHER repository, and several model passes in one job.

## Tests

`tests/contract.sh` pins the runner's contract with a stubbed `claude` — success, rejected call, silent CLI, no-op, `is_error` with exit 0, kit-only mode without metering, flag passthrough — no network, no credential. CI runs it on every change to the runner, the lane, or this kit (`ai-runner-contract.yml`). A consumer that still vendors the runner proves parity with:

```bash
AI_RUNNER_SUT=scripts/ai/run.sh bash <hub>/templates/ai-runner/tests/contract.sh
```

## Migrating a vendored copy

1. Replace `uses: ./.github/actions/claude-run` with `uses: bamr87/bamr87/.github/actions/claude-run@main` in every workflow (the inputs are identical).
2. Delete `.github/actions/claude-run/` and `scripts/ai/run.sh`; keep the companions in the table above.
3. Delete the vendored copy of the contract test; it lives here now.
4. Where a lane is the standard shape, collapse it to the caller template and delete the hand-rolled gate/concurrency/setup steps.

Versioning: `VERSION` here is the kit's version (`# kit: ai-runner vX.Y.Z` stamps the caller template, which IS a file a repo holds and so is archived for `--upgrade`); the runtime is consumed at `@main`. Tagged refs are a deliberate second step once the fleet wants a rollback lever it has never needed.

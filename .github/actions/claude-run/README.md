# claude-run

The fleet's universal AI step — kit `ai-runner`, **source of truth for every AI lane in the fleet**. Consume it by reference:

```yaml
- uses: bamr87/bamr87/.github/actions/claude-run@v2
  with:
    agent: grow                       # .claude/agents/grow.md in the CONSUMER repo
    prompt: "Produce ONE piece from the backlog, verify it, open ONE PR, write its URL to pr-result.txt."
    tools: "Bash,Read,Write,Edit,Grep,Glob"
```

with `CLAUDE_CODE_OAUTH_TOKEN` in the job `env` (OAuth only for now, 2026-11-15: `ANTHROPIC_API_KEY` is unset by the step and `api_key` is dropped from the order, so there is no key-billed run and no Claude API fallback). Or take the whole lane — kill switch, concurrency, checkout, runtimes, this step, the result assertion — from the reusable [`ai-lane.yml`](../../workflows/ai-lane.yml).

| File | Purpose |
| --- | --- |
| `action.yml` | The composite manifest: inputs `prompt`, `agent`, `tools`, `mcp`, `system`, `out`, `model`, `max-turns`; installs Claude Code `@latest` (best-effort, log kept; explicit tag because a bare name resolves to an old release on Node < 22), then always prints the version line `claude-run: Claude Code <version> on Node <version>` and, when an install that exited 0 left no `claude` on PATH, a `::warning::` naming `$RUNNER_TEMP/npm-install.log` (bamr87#499; `tools/test_claude_run.py`), calls `run.sh`, then publishes the consumer's metering when it has any |
| `run.sh` | The runner. Model: `--model` > `AI_MODEL` > the consumer's `_data/ai.yml` > the fleet default. Auth in the order `AI_AUTH_ORDER` names (the repo's `CLAUDE_AUTH_ORDER` via `ai-lane.yml`; default `oauth,api_key`). The CLI sees only the credential being tried, and a refused credential moves on to the next one. A transient failure that billed nothing is re-run on the same credential (below). Claude Code primary; Claude API fallback when the consumer ships `scripts/ai/api_call.rb\|py`. Post-run one-paragraph-per-line normalizer honouring the consumer's `.prose-excludes`. Exit `0` = ran, or nothing was attempted (no CLI, no key: the documented no-op); exit `1` = attempted and FAILED, reason printed and raised as `::error::` |

The runner acts on the **consumer** tree (`$GITHUB_WORKSPACE`; `AI_REPO_ROOT` overrides for local runs), never on this action's own checkout. What it looks for there, all optional: `_data/ai.yml`, `scripts/ai/usage.rb` + `usage_report.rb` (metering), `scripts/ai/api_call.rb|py` (fallback), `tools/unwrap-prose.py` + `.prose-excludes` (normalizer).

## Transient retry

A call that fails with a transient API error (529, 503, 502, `overloaded`) is run again on the same credential, but only when its result payload shows that nothing was billed: zero cost, zero tokens of every kind, and no more than one turn. A call that billed anything, or whose payload cannot show that it billed nothing, is never re-run, because the model may already have done work. A transient failure never moves on to the next credential in `AI_AUTH_ORDER`; only a refused credential does. The Claude Code CLI already retries a 529 inside one call and stops after three in a row (`Repeated 529 Overloaded errors`), so this retry covers an overload that lasts minutes. Two environment variables, set on the step or the job, tune it:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AI_TRANSIENT_RETRIES` | `2` | How many times the same call is re-run; at most `5`, and `0` turns the retry off |
| `AI_TRANSIENT_BACKOFF` | `30 90` | The seconds to wait before each retry, space-separated; the last wait repeats, and none is longer than `300` |

Each retry prints its attempt number and wait (`attempt 2/3 of the same call in 30s`), raises a `::warning::` under Actions, and adds a line to the step summary with the retry count and the step's exit code. Where the consumer tree carries `tools/fleet_activity.py` (the hub does), each retry is also spooled as a fleet activity `retry` event; that is best-effort and never fails the step.

Contract tests: [`templates/ai-runner/tests/contract.sh`](../../../templates/ai-runner/tests/contract.sh), run by `ai-runner-contract.yml` on every change here. Kit docs and the caller template: [`templates/ai-runner/`](../../../templates/ai-runner/). Reference consumer: [bamr87/lifehacker.dev](https://github.com/bamr87/lifehacker.dev).

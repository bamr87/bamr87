# claude-run

The fleet's universal AI step — kit `ai-runner`, **source of truth for every AI lane in the fleet**. Consume it by reference:

```yaml
- uses: bamr87/bamr87/.github/actions/claude-run@main
  with:
    agent: grow                       # .claude/agents/grow.md in the CONSUMER repo
    prompt: "Produce ONE piece from the backlog, verify it, open ONE PR, write its URL to pr-result.txt."
    tools: "Bash,Read,Write,Edit,Grep,Glob"
```

with `CLAUDE_CODE_OAUTH_TOKEN` and/or `ANTHROPIC_API_KEY` in the job `env`. Or take the whole lane — kill switch, concurrency, checkout, runtimes, this step, the result assertion — from the reusable [`ai-lane.yml`](../../workflows/ai-lane.yml).

| File | Purpose |
| --- | --- |
| `action.yml` | The composite manifest: inputs `prompt`, `agent`, `tools`, `mcp`, `system`, `out`, `model`, `max-turns`; installs Claude Code (best-effort, log kept), calls `run.sh`, then publishes the consumer's metering when it has any |
| `run.sh` | The runner. Model: `--model` > `AI_MODEL` > the consumer's `_data/ai.yml` > the fleet default. Auth OAuth-first (`env -u ANTHROPIC_API_KEY`). Claude Code primary; Claude API fallback when the consumer ships `scripts/ai/api_call.rb\|py`. Post-run one-paragraph-per-line normalizer honouring the consumer's `.prose-excludes`. Exit `0` = ran, or nothing was attempted (no CLI, no key: the documented no-op); exit `1` = attempted and FAILED, reason printed and raised as `::error::` |

The runner acts on the **consumer** tree (`$GITHUB_WORKSPACE`; `AI_REPO_ROOT` overrides for local runs), never on this action's own checkout. What it looks for there, all optional: `_data/ai.yml`, `scripts/ai/usage.rb` + `usage_report.rb` (metering), `scripts/ai/api_call.rb|py` (fallback), `tools/unwrap-prose.py` + `.prose-excludes` (normalizer).

Contract tests: [`templates/ai-runner/tests/contract.sh`](../../../templates/ai-runner/tests/contract.sh), run by `ai-runner-contract.yml` on every change here. Kit docs and the caller template: [`templates/ai-runner/`](../../../templates/ai-runner/). Reference consumer: [bamr87/lifehacker.dev](https://github.com/bamr87/lifehacker.dev).

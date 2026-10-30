# `claude-cost`

The per-run spend readout for a `claude-code-action` step, and the two classifications that make a red agent step actionable.

## Why

Every scheduled loop carried the same ~85-line `Report Claude run cost` step, copied six times. The copies drifted: `fleet-pulse.yml` reported against a `$25` cap while its `claude_args` said `$40`, so its budget-hit detection was measuring the wrong number. The script now lives once, here, and `.github/scripts/dash-gen/test_ai_budget.py` asserts it (and every call site's `budget-usd`) once.

## Contract

- Runs on **every** outcome (`if: !cancelled()`), because a green run is the one whose spend accumulates unnoticed.
- Echoes the result record into the run log as `claude-run-result …` so `ai_usage_collector.py` sees the run even on the abort path.
- **Budget abort fails the step** (`exit 1`) and publishes `budget_hit=true`, so a step that publishes the agent's tree can mark the pull request as a mid-task fragment rather than a finished pass.
- **Rejected credential** (`total_cost_usd == 0` and empty `modelUsage` on a failed step) is called out as "rotate `CLAUDE_CODE_OAUTH_TOKEN`"; a **429 usage limit** is called out as "do NOT rotate" and publishes `usage_limit=true`.
- **`usage-limit: skip`** (scheduled loops): the caller marks its agent step `continue-on-error: true` and this step owns the job's verdict. A usage limit is a warning and exits 0; a budget hit, a refused credential, an agent failure or a missing result record exit 1. Without the flag (`fail`, the default) the agent step's own failure decides, as before. `test_ai_budget.py` holds the pair together and requires it on every scheduled call site.

## Usage

```yaml
- name: Report Claude run cost
  id: cost
  if: ${{ !cancelled() && env.HAS_CLAUDE_AUTH == 'true' }}
  uses: ./.github/actions/claude-cost
  with:
    tier: Fleet doctor
    icon: 🩺
    budget-usd: "40"        # the same number as the step's --max-budget-usd
    outcome: ${{ steps.fix.outcome }}
    usage-limit: skip       # scheduled loop: the agent step above is continue-on-error
```

In a job whose workspace is **another repository** (repo-evolution, the fan-out's agent-fill, fleet-verify), reference it from the hub's sparse checkout instead: `uses: ./.fleet-hub/.github/actions/claude-cost`.

| Input | Default | Description |
| --- | --- | --- |
| `tier` | — | Label for the summary and annotations |
| `icon` | 🤖 | Emoji for the summary heading |
| `budget-usd` | — | The step's dollar cap (`budget.call_sites` in `_data/fleet.yml`) |
| `outcome` | — | The agent step's `outcome` |
| `log` | `$RUNNER_TEMP/claude-execution-output.json` | The execution log to read |
| `usage-limit` | `fail` | `skip` = this step decides the verdict; a usage limit is a warning (pair with `continue-on-error: true` on the agent step) |

| Output | Description |
| --- | --- |
| `budget_hit` | `true` when the cap stopped the run |
| `usage_limit` | `true` when the subscription's usage window was spent (HTTP 429) |
| `cost_usd` | `total_cost_usd` from the result record |
| `turns` | `num_turns` from the result record |

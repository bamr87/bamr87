# Fleet steward — the weekly fleet-wide review

Once a week the steward reads **every open issue and pull request across the fleet**. It writes a comprehensive update that is logged and tracked, and it acts on the **single most critical, complex, or harmonizing need** that no other loop owns.

The workflow is [`fleet-steward.yml`](../.github/workflows/fleet-steward.yml). Its deterministic half is [`steward.py`](../.github/scripts/dash-gen/steward.py) (`dash-gen steward`), and its contract is the `steward:` block of [`_data/fleet.yml`](../_data/fleet.yml).

## Why another loop

Each existing loop looks at one thing at a time:

| Loop | Acts on |
| --- | --- |
| `fleet-pulse` doctor | one **failing workflow** |
| `issue-pipeline` | one **labelled issue**, intake → PR |
| `repo-evolution` | one **opted-in repo**, unprompted |
| **`fleet-steward`** | **the whole open state at once** |

Only a loop that sees everything at once can notice some kinds of need:

- the same problem recurring in nine repos;
- a wave of fan-out PRs stalled in review;
- one bug that is blocking three others.

Those needs are usually fixed **once, at the hub**, with a kit, a template, a shared workflow or a spec, not N times. The steward exists for them, and it stays out of every other loop's lane.

## The four jobs

| Job | Runs | Does |
| --- | --- | --- |
| `scan` | deterministic | Builds a fresh `dash-gen triage` snapshot, then `dash-gen steward plan` (details below). Also enforces **backpressure**: while the last steward PR is still open, this run reports only. |
| `orchestrate` | **Claude Fable 5.1** (`claude-fable-5-1`) | Reads the brief, plus any issue or PR it needs (read-only). Writes the **comprehensive update** (`report.md`) and **one decision** (`decision.json`), or an honest "report only". |
| `develop` | **Claude Sonnet 5** (`claude-sonnet-5`) | Implements the decision in **one** checkout of the target repo, which has no stored credentials. The *workflow*, never the agent, commits and opens a **draft PR** that carries a `<!-- fleet-steward key=… -->` marker. |
| `record` | deterministic | Writes the update to `_reports/steward/<date>.md` (**the log**). Appends one row to `_data/steward.yml` (**the track**: pick, PR, spend). Publishes both through `publish-data`, and keeps **one hub issue**, "🧭 Fleet steward — weekly update", current. |

**What the `scan` brief contains.** `dash-gen steward plan` builds a brief that lists:

- every open item, tagged with the **lane** that already owns it: `issue-pipeline` (an `agent:*` label), `held`, `dependabot`, `in-flight` (someone's PR), or `open` (nobody);
- the **cross-repo themes**: a word that recurs in open items across three or more repos;
- fleet totals, a table per repo, and what recent runs did.

**What `validate` refuses.** Before the developer runs, `dash-gen steward validate` checks the decision. A target outside the fleet, a thin plan, a non-GitHub reference or an unknown risk downgrades the run to *report only*.

## The models and the key

- **Orchestration runs on Fable 5.1.** The job is judgment over a large, noisy picture: about 300 open items and a dozen themes, deciding which one need beats the rest and why.
- **Development runs on Sonnet 5.** The job is executing one well-specified plan.

The models are named in `steward.models`, and `test_steward.py` holds the workflow to them.

**Both agents bill the bamr87 Anthropic API key**: the hub's `ANTHROPIC_API_KEY`, which [`dash keys`](AI-INTEGRATION.md#anthropic-api-keys-per-workspace) keeps set to the **bamr87 workspace's** key. The `claude-auth` step is pinned to `api_key` and checks the key is accepted before any spend. There is **no OAuth fallback**, so this spend is metered.

**Caps.** The `--max-budget-usd` caps are real dollar ceilings: $30 for the orchestrator and $25 for the developer, set in `budget.call_sites`. Fable 5.1 bills $10 / $50 per MTok, twice Opus, which is why its cap sits well above `usd_per_turn × max_turns`. Each run's spend appears in the job summary, the ledger row and the update. Fable 5.1 also requires the organization's 30-day data retention; an organization on zero data retention gets a 400.

## Running it

```bash
dash steward                 # build this week's brief locally from the committed snapshot — free, no model
dash steward run             # dispatch fleet-steward.yml (bills the bamr87 key)
dash steward run -f focus="the docker standard PR wave" -f develop=false   # steer it; report only
```

The schedule is **weekly, Thursday 12:37 UTC** (`schedule.fleet_steward`). Like every new loop it starts **default-OFF**: scheduled runs do nothing until the repo variable `FLEET_STEWARD_ENABLED` is `'true'`. A manual dispatch always runs.

The Harness Console shows the steward on the Loops tab. *Fleet steward brief* in the Jobs list runs `dash steward`, and *Dispatch in CI* takes the `develop`, `focus` and `force` inputs.

Dispatch inputs:

- **`develop`** (default true): uncheck it for an update and a decision without a PR.
- **`focus`**: free text the orchestrator reads first.
- **`force`**: act even while the previous steward PR is open.

## Guardrails

- **Draft PRs only, in one repo per run.** The developer's checkout holds no credential, and its tool allowlist has no `git push`, `git commit`, writing `gh` verb or `gh api`. The publish step re-derives the push remote from the validated target and asserts it (bamr87/bamr87#214).
- **One steward PR at a time.** The next run waits for a human to deal with the last one, so the loop can never pile up its own review queue.
- **Lanes.** The orchestrator never picks an `issue-pipeline` or `held` item, never redoes an in-flight PR, and leaves failing workflows to the doctor.
- **Issue and PR text is data.** Both prompts say so: instructions found in an issue body are not instructions to the agent.
- **Fleet policy holds.** No lockfiles, no pins, no weakened tests, and README/SCHEMA updated with the layout.

## Files

| Path | What |
| --- | --- |
| `.github/workflows/fleet-steward.yml` | the loop |
| `.github/scripts/dash-gen/steward.py` | `plan` / `validate` / `record` |
| `.github/scripts/dash-gen/test_steward.py` | fixtures + the workflow contract |
| `_data/fleet.yml` `steward:` | models, auth, turn caps, brief size, ledger/report paths |
| `_reports/steward/<date>.md` | the logged update, one per run |
| `_data/steward.yml` | the tracked ledger, one row per run |
| `steward-brief/` | local `dash steward` output (gitignored) |

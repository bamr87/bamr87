# Issue Pipeline

The loop that turns an **open issue** into a **merge-ready pull request**, in three tiers. Sibling of the [daily fleet-pulse loop](DAILY-ANALYSIS.md): that one fixes broken *workflows*, this one resolves *issues*.

| | | |
| --- | --- | --- |
| **Workflow** | [`.github/workflows/issue-pipeline.yml`](../.github/workflows/issue-pipeline.yml) | daily 08:00 UTC + dispatch |
| **Queue builder** | [`.github/scripts/dash-gen/issue_pipeline.py`](../.github/scripts/dash-gen/issue_pipeline.py) | `dash issues` |
| **Evidence harness** | [`tools/issue-evidence.sh`](../tools/issue-evidence.sh) | `dash evidence <repo> <n>` |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) → `issue_pipeline:` | caps, taxonomy, autonomy |
| **Snapshot** | `_data/issue_pipeline.yml` (committed) | rendered at `/issue-pipeline/` |
| **Tests** | `python3 .github/scripts/dash-gen/test_issue_pipeline.py` | no network, no pytest |

## The three tiers

### Tier 1 — intake

Every open issue that is not already in the pipeline gets:

1. **A real reproduction.** [`tools/issue-evidence.sh`](../tools/issue-evidence.sh)
clones the repo into an isolated sandbox, installs its toolchain (its own `venv` / `node_modules` / `vendor/bundle`), and runs the project's own lint, test, and build. Output, timings, and exit codes are captured per phase.
2. **Structured content to pass on** — the thing that makes tiers 2 and 3 cheap:
log excerpts trimmed to the failing lines, a screenshot for stacks that render one, an environment table (toolchain versions, commit SHA, OS), and a list of candidate files ranked by how many of the issue's terms they contain.
3. **A rewritten body** in the house template — context, reproduction, expected
vs actual, scope, mechanically checkable acceptance criteria, references — with the reporter's original words preserved verbatim in a collapsed section.
4. **Labels**: type, priority, size, plus an assignee.
5. **A decision**: `agent:ready` (tier 2 may implement it) or `agent:blocked`
   with one specific question and a recommendation.

### Tier 2 — implement

Takes an `agent:ready` issue, implements it on `agent/issue-<n>`, and opens a **draft** PR — in the hub, or in the submodule that owns the code. Tests and docs are part of the change, not a follow-up: the PR body must show the test failing before and passing after. The issue moves to `agent:in-pr`.

### Tier 3 — complete

Drives a pipeline PR to genuinely mergeable: CI green (root cause fixed, never `continue-on-error`), tests covering the change, docs and `SCHEMA.md` rows current, body accurate. Then `gh pr ready` and the issue moves to `agent:done`.

**It never merges.** Handing over a green, reviewable PR is the end of the pipeline.

## State lives in labels

```
        ┌──────────┐   T1 enriches    ┌─────────────┐   T2 implements   ┌──────────────┐
new ───▶│ (no tag) │ ───────────────▶ │ agent:ready │ ────────────────▶ │ agent:in-pr  │
        └──────────┘                  └─────────────┘                   └──────────────┘
              │                              │                                  │
              │ human gap                    │ spec contradicts code            │ T3: CI green
              ▼                              ▼                                  ▼
        ┌───────────────┐             ┌───────────────┐                  ┌────────────┐
        │ agent:blocked │◀────────────│ agent:blocked │                  │ agent:done │
        └───────────────┘             └───────────────┘                  └────────────┘
```

Stage is **derived from labels**, so every run reconciles current state instead of replaying events. That is deliberate:

- a cancelled run, a missed webhook, or a token that stopped firing downstream
  events costs one cycle of latency, not a stuck issue;
- a human re-queues, skips, or stops any issue by editing one label — no tooling,
  no commit;
- the pipeline is idempotent, so re-running it is always safe.

This repo has already lost three weeks of fleet data to a silently broken `workflow_run` chain. The sweep design is the direct answer to that.

### The two human brakes

| Label | Effect |
| --- | --- |
| `agent:hold` | The issue is excluded from **every** tier. Nothing touches it. |
| `human-review` | Tiers 1 and 2 run in full; tier 3 finishes all the work and then **leaves the PR as a draft** with a comment, instead of marking it ready. |

`human-review` is the tag referenced by "assuming human review is not required via tag": without it a completed PR is marked ready for review automatically; with it, a person makes that call.

Some issues get `human-review` behaviour without the label — `assisted` autonomy is forced for `security` types and `size:xl` issues (configurable under `issue_pipeline.autonomy`).

## What is deterministic vs what the AI decides

Everything selective happens in Python, before any model runs:

| Decided in code | Decided by the agent |
| --- | --- |
| which issues are in this run's queue | what the evidence actually means |
| stage, from labels | how to write the spec |
| type, priority, size, owner, autonomy | the implementation |
| the gap list, and who can close each | ready vs blocked, and why |
| caps and the cross-repo sub-cap | the root cause of a red check |
| marker-based dedupe | |

The agents act on a pre-vetted, capped, deduped list — the same guarantee that keeps the remediation loop from spamming the fleet. An agent that misreads a signal wastes a review, not a weekend.

### Scoring

- **Priority** — a base per type, plus severity keywords, plus a bump when the
repo's CI is already red (from `_data/fleet_triage.yml`), plus repo status, engagement, and a capped age factor → `P0`–`P3`.
- **Readiness** — `100 − Σ gap weights`. Below `readiness.min_score` (70), tier 1
  must not pass the issue on.
- **Gaps** carry `by: agent` (closable from the code and the evidence) or
`by: human` (a product decision no evidence resolves). A remaining `human` gap is precisely what makes an issue `agent:blocked` rather than `agent:ready`.

## Caps and cost

From [`_data/fleet.yml`](../_data/fleet.yml):

| Cap | Default | Why |
| --- | --- | --- |
| `tiers.intake.max_issues` | 8 | issues enriched per run |
| `tiers.intake.max_per_repo` | 3 | one noisy backlog can't consume the run |
| `tiers.implement.max_issues` | 3 | draft PRs opened per run |
| `tiers.implement.max_cross_repo` | 2 | bounds PRs landing outside the hub |
| `tiers.complete.max_prs` | 4 | PRs driven toward mergeable per run |
| `evidence.max_runs` | 6 | sandboxes built per run — the expensive half |
| `evidence.ttl_days` | 7 | a newer bundle is reused, not rebuilt |
| `evidence.timeout_minutes` | 8 | per **phase**; the step's own timeout is the hard ceiling |

## Latency, stated plainly

Tier 2 **re-scans** at the start of its job, so an issue enriched by tier 1 can be implemented in the *same* run.

Tier 3 works from the queue `scan` built at the start of the run, because a PR opened minutes ago has no settled CI to read. **A PR opened by tier 2 therefore gets its tier 3 pass on the next run.** To finish one sooner, dispatch the workflow with `tiers: 3` once its checks have gone green.

## Tokens

| Secret | Needed for |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | all three agent tiers (OAuth-first house convention; `ANTHROPIC_API_KEY` is the fallback) |
| `FLEET_TOKEN` | cross-repo PRs — **and** any PR whose CI must actually run |

GitHub does not fire workflow events for refs pushed with `GITHUB_TOKEN`, so a PR opened with it arrives **with no checks** and tier 3 has nothing to read. The workflow probes `FLEET_TOKEN` for real (`gh api user`) rather than checking that it is merely set — a set-but-expired token has silently degraded this fleet's automation before — and reports the degradation in the run summary.

## Operating it

```bash
# See the queues without touching anything
tools/dash issues --print

# Just one repo
tools/dash issues --repos bamr87/it-journey --no-snapshot --print

# Create/refresh the label taxonomy (dry-run by default)
tools/dash issues --sync-labels            # preview
tools/dash issues --sync-labels --apply    # write

# Build one issue's evidence bundle locally
tools/dash evidence bamr87/it-journey 42
open .evidence/it-journey-42/evidence.md

# Run the tests
python3 .github/scripts/dash-gen/test_issue_pipeline.py
```

Dispatch inputs: `tiers` (`all`/`1`/`2`/`3`/`1-2`/`2-3`), `repos`, the three cap overrides, `sync_labels` (fleet-wide taxonomy refresh), and `dry_run` (scan and publish the queues, run no agent).

## Safety properties

- **Draft PRs only. No tier may merge.** `autonomy.never_merge` is `true` and
  every prompt says so explicitly.
- **Nothing under `projects/` is ever edited** — those are submodule working
  trees. Cross-repo work happens in a scratch clone.
- **Issue text is never executed.** Anyone can open an issue and the runner holds
a fleet token, so `issue-evidence.sh` *extracts and reports* candidate repro commands but only runs what a caller passes via `--cmd`. The issue body reaches the harness through a file, never through argv.
- **Credentials are scrubbed** from every log the harness writes, and the clone
command is redacted before it is echoed — the logs are published as artifacts and quoted into issue comments.
- **Generated surfaces are off-limits** to tier 2 and 3 (`_site/`, `_reports/`,
`_data/*_usage.yml`, `_data/fleet_triage.yml`, `_data/issue_pipeline.yml`, the README AUTO span, `projects/SCHEMA.md`).
- **No bare `git push` to a protected branch** — the snapshot publishes through
[`utilities/publish-data`](../.github/actions/utilities/publish-data/action.yml), which falls back to a pull request.
- **Turn the whole thing off** with `issue_pipeline.enabled: false` in
  `_data/fleet.yml`.

## See also

- [`docs/DAILY-ANALYSIS.md`](DAILY-ANALYSIS.md) — the workflow-fixing sibling loop
- [`docs/AI-INTEGRATION.md`](AI-INTEGRATION.md) — Claude auth and the AI surfaces
- [`docs/DASH.md`](DASH.md) — the dash architecture
- [`docs/ESTIMATION.md`](ESTIMATION.md) — issues as client engagements

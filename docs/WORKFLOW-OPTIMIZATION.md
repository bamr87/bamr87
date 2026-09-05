# Workflow Optimization

A fleet-wide audit of every GitHub Actions workflow in the hub and its submodules, and the record of what was changed.

Baseline: `_data/actions_usage.yml` (14-day window ending 2026-07-13) plus a static read of all workflow files in the checked-out submodules.

> **Read the snapshot date before acting on a row.** The analytics refresh is daily, but a finding drawn from it can be stale by the time it is read — `it-journey` had already consolidated three auto-merge workflows into one after the snapshot above was taken. Always confirm a workflow still exists, and still looks the way the data implies, before opening work against it.

## Scope of the audit

| | Count |
| --- | --- |
| Workflow files read | 130 (18 hub + 112 submodule) |
| Total workflow YAML | ~18,400 lines |
| Repos with checked-out workflows | 9 submodules + hub |
| Cron-triggered workflows | 47 |
| Workflows with no `concurrency` group | 24 |
| `push`/`pull_request` workflows with no path filter | 16 |
| Workflows with **zero runs** in the window | 49 |

Measured consumption in the window: **3,290 minutes** across 1,594 runs, of which **1,271 minutes (39%) were waste** (runs that failed, were cancelled, or produced no change). Two repos account for 78% of all minutes: `it-journey` (1,461) and `zer0-mistakes` (1,104).

## The two kinds of waste

The distinction drives every recommendation below, because the fixes are completely different:

- **Structural waste** — the workflow is configured to do more work than it needs to: no dependency cache, a cron that fires more often than its inputs change, a missing concurrency guard, a job that exists only to spin a runner. Fixable by editing YAML. This is what was implemented.
- **Failure waste** — the workflow is correctly configured but its runs fail. `zer0-mistakes/ci.yml` (528 lines, change-detection, matrix with `fail-fast: false`, npm caching, per-job timeouts) is *well* engineered; its 134 wasted minutes come from failing runs, not from its config. Re-shaping it would not recover a minute. This class already has an owner — the `fleet-pulse.yml` `doctor` job opens a PR or files an issue per failing workflow — and is deliberately **not** addressed here.
- **Cancellation waste** — a third class, identified after the first pass and described under [Measurement](#measurement-the-success-rate-was-wrong) below. The minutes are real, but nothing is broken and there is nothing to fix in the workflow.

Distinguishing them matters: 984 of the 1,271 wasted minutes are in the `ai` workflow type, whose runs are expensive by design. An AI loop that fails half its runs is a correctness problem, not a configuration problem.

## Changes implemented (hub)

### Fleet-wide, effective immediately

`standard-ci.yml` is the reusable gate that member repos call at `@main`, so a change here reaches every adopting repo on its next run with no fan-out.

| Change | Why |
| --- | --- |
| Added `cache: npm` to `setup-node` (guarded on a lockfile existing) | Every run re-downloaded the full npm tree. |
| Added `cache: pip` + `cache-dependency-path` to `setup-python` (guarded on a cacheable file existing) | Same, for pip. |
| Fixed the pytest exit-code handling | **Correctness bug.** `run:` executes under `bash -eo pipefail`, so `pytest -q; rc=$?` aborted the step the moment pytest returned non-zero — the `rc -eq 5` ("no tests collected") branch below it was unreachable. Every adopting repo without tests was failing its own CI gate. Now captured under `set +e`. |

Both cache guards are conditional because `setup-node`/`setup-python` hard-fail when `cache` is set and no dependency file matches — an unconditional `cache:` would have broken repos that have a `package.json` but no lockfile.

### Removed as obsolete

`unified-cicd.yml`, `unified-release.yml`, `unified-maintenance.yml`, `workflow-dispatcher.yml` — **1,754 lines deleted**. A generic single-app CI/CD template that only ever ran against the root tree, which has no app code (the projects are submodules). Nothing in `tools/`, `.claude/`, or the docs invoked them; `workflow-dispatcher.yml` existed solely to dispatch the other three. They were already `workflow_dispatch`-only, so this reclaims no minutes directly — it removes a maintenance surface, the ~240 pre-existing `actionlint` findings they carried, and the risk of someone dispatching a 16-job pipeline against an empty tree.

`unified-evolution.yml` was **kept**: it is documented and live, and `tools/dash evolve` invokes it.

### Reduced run frequency and churn

| Workflow | Before | After | Effect |
| --- | --- | --- | --- |
| `build-dash.yml` | `0 */6 * * *` | `0 7 * * *` | The site's inputs are committed by the data jobs between 04:00 and 06:00 UTC. Three of the four daily builds fired before any new data existed and republished an unchanged site. The 07:00 slot now sits after all four. Removes ~1,095 full Ruby+Jekyll build+deploy runs per year. |
| `refresh-dash.yml` | `branch: chore/refresh-dash-${{ github.run_id }}` | `branch: chore/refresh-dash` | The per-run branch name meant `create-pull-request` opened a **new PR every day** instead of updating one, each dragging its own `drift-check` runs behind it and leaving a stale branch. Now one rolling PR. |
| `drift-check.yml` | separate `actionlint` job | `actionlint` step inside the `drift` job | The second job was a whole extra runner (and billed minute) on every push and PR, just to `curl` a binary and lint. It now reuses the checkout the gate already did. |
| `claude.yml` (+ the `templates/agent-context/` copy it seeds) | no `concurrency` | per-thread group, `cancel-in-progress: false` | Several `@claude` mentions in quick succession each spun up their own 30-minute agent against the same thread, racing on the same branch. Now serialized. Deliberately *not* cancelling: each mention is a distinct request and the agent pushes commits, so a superseded run should queue, not die mid-push. |

`drift-check.yml` also now discovers workflows by glob instead of a hand-maintained include list. The old list silently skipped any newly added workflow — a gate that quietly stops covering new files. `unified-evolution.yml` is the single documented exemption, as the last of the legacy suite.

## Outstanding — submodule-owned

The hub has **read-only** access to submodule repos (`git push` returns 403), and the standardization kits are additive-only by design, so the following cannot be implemented from here. They are ordered by measured cost.

### 1. `skills` — 350 minutes on an external mirror (highest value, lowest risk)

`projects/skills/` is a mirror of `microsoft/skills` (`update = merge`), consumed, not developed. It burned **350 minutes across 131 runs** — 10% of all fleet minutes — on someone else's evaluation harness:

- `run-vally-evaluations.yml` — 220 min, 6 runs, **0% success**
- `vally-evaluation.yml` — 31 min, 27 runs, 5.9% success
- `vally-evaluation.lock.yml` — 16 min, 10 runs, 0% success

None of it produces value for this fleet. **Disable Actions on the mirror** (Settings → Actions → Disable). This is the single largest recoverable block of minutes in the audit and carries no engineering risk.

### 2. `templates/agent-context/claude.yml` back-fill

The concurrency fix landed in the template, but the kit never overwrites an existing file, so the ~9 repos already carrying a seeded `claude.yml` (`README`, `bamr87.github.io`, `bashconsultants`, `githubai`, `it-journey`, `lifehacker.dev`, `vscode-front-matter`, `wargames`, `zer0-mistakes`) will not pick it up via fan-out. The three-line `concurrency:` block needs applying directly in each. Kit bumped to `0.2.0` to mark the divergence.

### 3. Dead workflows — 49 with zero runs

Not all are wrong (a `release.yml` that fires on tags legitimately idles), but several clusters are plainly finished:

- `skills-github-pages` — six numbered tutorial workflows (`0-welcome` … `5-merge-your-pull-request`) from a completed GitHub Skills course.
- `ai-seed` — five scheduled evolution workflows (`daily-evolution`, `weekly-health-check`, `monthly-evolution-report`, `quarterly-major-evolution`, `ci-cd`) that never fired in the window.
- `it-journey` — `quest-fix.yml` (535 lines) and `quest-walkthrough.yml` (309) are `workflow_call`/dispatch-only targets of the quest loop, so idle is expected; `new-feature-request.yml`, `validate-solutions.yml`, `quest-report-auto-merge.yml` are candidates for review.

Auditing these is cheap and each removal is one fewer thing to keep green.

### 4. `it-journey/quest-perfection.yml` — 728 wasted minutes

The largest single line item in the fleet: 1,153 minutes over 15 runs (77 min average), **53% success**, flagged `high-cost-low-value`, `flaky`, `slow`. This is a deliberate, multi-layer-gated AI curriculum loop that is off by default — its cost is intentional, so this is explicitly *not* a recommendation to remove it. But a 47% failure rate on a 77-minute run means roughly half its minutes produce nothing. It needs a **reliability** fix, not a config fix, and it should be the first candidate the `actions-review` loop deep-dives.

### 5. Structural gaps worth a fan-out

- `it-journey/dependabot-auto-merge.yml` — 30 wasted minutes over 35 runs, `high-cost-low-value`. An auto-merge helper should cost seconds.
- Missing `concurrency` on 24 workflows, and no path filters on 16 `push`/`pull_request` workflows — both are exactly what the `standardize-fanout.yml` channel exists to propagate.

> `it-journey/content-auto-merge.yml` was listed here in the first pass as "114 runs at 8% success". That was the measurement bug below, not the workflow: it has **1 real failure**. It also already absorbed the separate `issue-pr-auto-merge.yml` and `quest-report-auto-merge.yml`, so the three-workflows-per-PR-event problem the analytics snapshot captured is already fixed upstream.

## Measurement: the success rate was wrong

The single most consequential finding, and the reason several entries above needed correcting.

`success_rate_pct` was computed as `success / (success + failure + cancelled)`. Cancelled runs have no verdict — they were superseded by a newer commit, which is exactly what a `concurrency: cancel-in-progress: true` guard is *supposed* to do, and which the hub's own workflow standards mandate. Counting them as non-successes made the metric measure churn instead of correctness, and anything under 50% then tripped the **`failing`** flag.

`failing` is in `SERIOUS_FLAGS`, so those workflows were nominated for the `actions-review` loop, where an **Opus** agent was dispatched to read `--log-failed` evidence for runs that had never failed. Replaying the corrected logic over the same data, six workflows change classification — and **four of them had zero actual failures**:

| Workflow | ok / fail / cancelled | Old | New |
| --- | --- | --- | --- |
| `it-journey/agentic-quest-review.yml` | 3 / **0** / 8 | 27.3%, `failing` | **100%**, clean |
| `zer0-mistakes/issue-autopilot.yml` | 8 / **0** / 11 | 42.1%, `failing` | **100%**, clean |
| `it-journey/issue-pr-auto-merge.yml` | 0 / **0** / 27 | 0%, `failing` | no verdicts, clean |
| `it-journey/content-auto-merge.yml` | 4 / 1 / 45 | 8.0%, `failing` | 80%, `flaky` |
| `zer0-mistakes/ci.yml` | 40 / 7 / 14 | 65.6%, `flaky` | **85.1%**, clean |
| `skills/vally-evaluation.lock.yml` | 0 / **0** / 6 | `failing` | no verdicts |

Fixed in `.github/scripts/dash-gen/`:

- `success_rate_pct` now counts only runs that reached a verdict (`success + failure`). Cancelled **minutes** still count in `waste_min` — they were really burned — and the churn stays visible as the new `cancel_pct` field and the existing `cancel-heavy` flag.
- The `failing`/`flaky` flags gate on decided runs, not completed ones. Without this the fix is incomplete: `pct(0, 0)` returns `0.0`, so a workflow with only cancellations would still have read as "0% success" and stayed flagged.
- `cancel-heavy` no longer pulls failing-run evidence in `actions_review.py` — cancelled runs produce no failure logs.
- The reviewer's suggested angle for `cancel-heavy` no longer says "add `concurrency: cancel-in-progress: true`". That was self-contradictory: a high cancel share usually means the guard is already there and working. The advice is now to start fewer runs, not to cancel more.

## Verification

`tools/check-drift.sh` passes. The three `SCHEMA.md` warnings it reports (`_data`, `templates`) pre-date these changes and are unrelated to workflows. All edited YAML parses.

`actionlint` could not be run locally in the authoring environment (the download is network-restricted); it runs in CI via `drift-check.yml`. That is why the legacy `unified-evolution.yml` exemption was kept rather than removed on the assumption it now passes.

## 2026-09-05 audit — the sensor was the problem

A second fleet-wide pass, this time with the local data lake, Phoenix traces, GitHub's billing meter and a live scan of every repo behind it (`tools/dash lake sync`, `dash harnesses`, `dash actions`, `/users/bamr87/settings/billing/usage`). Snapshot: 39 registry repos (27 public, 12 private), 267 workflows, 724 runs in the 7-day window, 16 scheduled AI crons, 219 open PRs.

### What the numbers actually said

| Signal as published | What was true | Why |
| --- | --- | --- |
| `budget-breach` sev 90: **287k–384k** Actions min/month vs a 120k ceiling | GitHub billed **21.9k** in August, **26.6k** in July, **6.2k** for 1–5 Sep — every month at **$0 net** | `actions_analytics` priced `run_started_at → updated_at`. Two `bashconsultants` runs parked in `action_required` reported 6,413 min each (107 h — past GitHub's own 72 h limit); every `it-journey` workflow carried one ~4,080-min outlier; and `tt-a1i/archify`, an **external** upstream, contributed 21,807 min (25% of the "fleet") that is not this account's spend |
| `waste-ceiling` tripped: waste 158% of total | waste cannot exceed consumption | same proxy, summed over a different population than its denominator |
| `cost-spike` tripped | downstream of the same number | — |
| 4 "failing" scheduled agents (`bashconsultants` ×3, `gitorio` factory-1) | the agents **finished**: `Claude reported a successful result after 43 turns, exceeding the configured maximum of 40` / `after 9 turns … maximum of 8` | turn caps with zero margin; the hub already solved this for repo-evolution with a salvage step (#217) |
| 4 AI crons collide at 06:00 UTC | real: fleet-pulse (daily), lifehacker Issue Factory 1 (Mon–Fri), gitorio Factory 3 (Mon), githubai Maintenance (Mon 06:17) — one OAuth rate limit | every hub cron sat on `:00`, the minute GitHub delays most; the fleet's own repos already use `:17/:23/:37/:47` |
| 9 scheduled agents with no kill switch | 3 of them are the hub's own loops | the convention existed in `wtd`, `ai-seed`, `lifehacker.dev`, `it-journey` — the hub did not practise it |
| 3 coverage gaps | `.github` is the org-defaults + `workflow-templates` repo, not a project | it belongs in `harnesses.exempt`; `git-with-the-program` and `irony-works` are real gaps |
| 10 near-duplicate `docs:` drafts open on the hub | all on `wtd/*` branches | `wtd` — registry status *archived* — runs a 4-hourly agent loop (42 runs/week, `WTD_FLEET_ENABLED=true`) that keeps re-drafting orientation docs nobody merges |
| 157 skipped `Claude` runs in 7 days | mention handlers firing on bot comments and skipping at the `if:` | ~0 minutes; noise in every run count, which the proxy fix now treats as non-verdict |

The compounding fact: the fleet's own doctor had **already diagnosed the metric** and opened #206 (30 Aug) and #231 (3 Sep) — two overlapping fixes for one defect from two issues the pipeline did not recognise as the same — plus #209 and #217 for the turn caps. All four sat unreviewed. The loops generate fixes faster than one human merges them, so the highest-value change was not another fix but making the queue *believable*: a sensor that lies at the top of the attention list costs every finding below it.

### Changed in the hub (this pass)

- **Cost is read from the meter.** `dash-gen actions` fetches GitHub's billing usage (one request), publishes it as `actions_usage.yml` `billing:` (per month, per repo, gross/net), and the harness budget wire prices **that** — run-rate once a week of the month exists, else last full month, growth month-over-month. The wall-clock proxy stays for ranking, now bounded as #231 proposed (merged into this branch: `MAX_RUN_MIN`, zero-job runs cost 0, fleet totals over owned workflows only). Ceiling re-based from 120,000 to **40,000 billed minutes** — Jun–Aug ran 21–27k.
- **Every hub cron moved off the hour and into one declared map** (`fleet.yml` `schedule:`): housekeeping at `:07` (rotation 02, submodules 03, README 04, reconcile 05), the daily agent chain at `:37` (pulse 05, build 06, issue-pipeline 07), weeklies at `:07`/`:37` (schema-vendor Mon 08, evolution Mon 10). Fleet-pulse leaving 06:00 clears the collision without touching any fleet repo. `update_submodules` said weekly in the contract and ran daily — the contract now matches the workflow, and `schema_vendor` is declared at all.
- **Kill switches on the three scheduled agent loops** — `FLEET_PULSE_ENABLED`, `ISSUE_PIPELINE_ENABLED`, `REPO_EVOLUTION_ENABLED` — default-ON (`!= 'false'`) because they were added to loops already in service, bypassed by `workflow_dispatch` so a switched-off loop stays testable.
- **The hub's `claude.yml` is stamped** `kit: agent-context v0.4.0`; it was byte-identical to the kit apart from that line, so it is now a recognisable machine seed like the 30 fleet copies.
- **`.github` exempted** from the harness baseline.
- **Three new sensors** so none of this regresses silently: `test_schedule.py` (cron ↔ contract parity both ways, never on the hour, switch present and dispatch-bypassing) and `test_actions_billing.py` plus a budget-wire test in `test_harness_registry.py` (the meter prices, the proxy ranks, an errored meter falls back and says so).

### Fleet changes (opened as PRs)

- `bashconsultants` — content-review / content-gardener / preacher: `--max-turns 40 → 80` (observed 43) and a `CONTENT_AGENTS_ENABLED` switch on the existing gate step.
- `githubai` — `claude-maintenance`: `CLAUDE_MAINTENANCE_ENABLED` switch beside its config-file toggle.
- `gitorio` — `.factory/blueprint.json` `maxTurns` 8 → 24, 12 → 30, 25 → 50, with the generated `factory--*.yml` lines updated in lockstep (the factory re-renders the hash on its next pass; lifehacker's factory lines already carry a `gate` job, so a re-render with the current GitFactory gains the switch too).
- `git-with-the-program`, `irony-works` — the agent-context kit (`claude.yml` + `CLAUDE.md`).

### Recommended, deliberately not mass-edited

These are repo-owned pipelines with their own gates; the evidence is here, the decision stays with the repo.

- **`wtd`**: set `WTD_FLEET_ENABLED=false` and close the ten `wtd/*` drafts, or un-archive it in the registry — an archived project should not run the fleet's noisiest agent loop. `fleet-pulse` reads real logs; `wtd` files tickets from metadata.
- **`lifehacker.dev`** (21,323 of August's 21,891 billed minutes): `auto-update` and `auto-merge` fire on `workflow_run` *and* a 4-hourly cron (132 runs/week each); the cron half is redundant with the event half. 26 workflows, 15 of them cron-driven.
- **`it-journey`** (33 workflows, 11 on every PR, five of them agentic with 39–56% success): consolidate the PR-time checks behind one workflow with `paths:` filters; the AI reviews belong on `workflow_dispatch` or a label, not every PR.
- **`zer0-mistakes`** (28 workflows; seven fire on every push *and* PR, 18–26% cancelled): the same `paths:` and `cancel-in-progress` treatment, plus a second run of the July audit above.
- **Merge throughput**: 219 open PRs, 100 dependabot, 94 stale, 74 drafts. Merge #231's successor (this PR), close #206 as superseded, and let the issue-pipeline's dedupe key on root cause, not issue number.

### Verification

`python3 .github/scripts/dash-gen/test_schedule.py`, `test_actions_billing.py`, `test_harness_registry.py`, `test_actions_analytics.py` (26 checks from #231) all pass, and every patched workflow parses. A live `dash-gen actions --days 7` on the branch, then `dash harnesses --offline` + `dash harness`, before → after:

| | before | after |
| --- | --- | --- |
| proxy totals (7d) | 3,336 runs · 84,864 min · waste 134,402 · effectiveness **−58.4%** | 2,986 runs · 3,881 min · waste 692 · effectiveness **82.2%** |
| Actions budget | proxy 287,369 min/mo vs 120,000 → **breach** | billed 21,891 (Aug) vs 40,000 → **ok**; Sep run-rate 38,160 after 5 days, not yet trusted |
| attention items | 15, led by `budget-breach` sev 90 | 12 — `budget-breach` and both `.github` coverage gaps gone |
| trip wires | waste-ceiling, cost-spike, credential-overdue | cost-spike, credential-overdue |

What remains is either **scan-derived** — `schedule-collision` and the hub's `switch-missing` read the workflows as GitHub has them, so they clear on the first live inventory after this merges — or **fleet-owned**: the four `harness-failing` rows and the two real coverage gaps are the fleet PRs above. `credential-overdue` is `ANTHROPIC_API_KEY` at 78 days against a 45-day policy + 15 grace: a human re-mint (`docs/TOKEN-ROTATION.md`). `cost-spike` compares against a fleet median of ~1 minute, so any genuine build trips it; its thresholds want re-basing once a month of billed data exists.

# Workflow Optimization

> The fleet-wide GitHub Actions audit of 2026-09 and the record of what changed because of it.

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

## 2026-10-19 pass — the loops had copied themselves until they drifted

Written on 2026-10-19 and landed on 2026-10-27 together with the pass below, ported over the week's changes in between (the `@v2` self-references, the kind-aware fan-outs of #394, `backlog-fanout.yml`, the work board). A read of all 36 hub workflows (7,581 lines) against the 14-day run history, `_data/fleet.yml` and the tests that pin workflow shapes. Nothing here changes what any loop *does*; it changes how many places say it.

| Finding | Change |
| --- | --- |
| `Report Claude run cost` was one ~85-line step pasted into six jobs, and the copies had drifted: `fleet-pulse` reported against a `$25` cap while its `claude_args` said `$40`, so its budget-hit detection measured the wrong number | One composite action, [`claude-cost`](../.github/actions/claude-cost/README.md), called from every `claude-code-action` site bar the `@claude` handler (now also the fan-out's agent-fill and `fleet-verify`). `test_ai_budget.py` asserts the script once and every call site's `budget-usd` against its own `--max-budget-usd`. |
| Five inline "probe the PAT with `gh api user`" loops (fleet-pulse ×2, reconcile-registry, issue-pipeline, repo-evolution) plus six presence chains (`FLEET_TOKEN \|\| DAILY_ANALYSIS_TOKEN \|\| GITHUB_TOKEN`) — against a house rule that says probe, never presence-check — falling back to two legacy PATs that no longer exist on the hub | One action, [`resolve-fleet-token`](../.github/actions/resolve-fleet-token/README.md) (rewritten: `GET /user`, exports `GH_TOKEN`), at every token step. The legacy fallbacks and their contract entries are gone. Loops that cannot deliver without the PAT (repo-evolution, the fan-out, git-digs) pass no default and fail before any Claude spend. |
| Four hand-rolled "find the open issue by title, edit or create, create labels first" blocks (api-keys, token-rotation, reconcile-registry, schema-vendor), each with its own duplicate-issue history | One action, [`upsert-issue`](../.github/actions/utilities/upsert-issue/README.md), with `state: close` for the clean night. |
| Seven dispatch-only fan-out workflows — `standardize`, `schema`, `deps`, `docker`, `feedback`, `verify`, `harness` — that were the same three steps around `tools/fanout.sh`, twice carrying their own copy of the agent-fill job | One `fanout.yml` with a `kit` input: a `plan` job (kit defaults, pre-flight tests, `gaps` from the committed inventory via `dash harnesses gaps` / the new `dash verify gaps`, which now honours the `verify.fanout.max_targets_per_run` knob nothing used to read), one `fanout` job, one `agent-fill` job. The console dispatches `fanout` with `kit=…`. |
| `refresh-dash.yml` ran every day and never once produced a change (`git log --grep="refresh README"` is empty): the README span depends only on the registry, and the drift gate already fails any PR that edits the registry without regenerating it. Its dispatch-only `escalate-attention` job duplicated the fleet doctor | Deleted. `reconcile-registry.yml` — the one automated registry edit — regenerates the span in its own PR, and opens that PR with the probed PAT so it actually gets CI (it used `GITHUB_TOKEN`, against standing rule 3). Same fix for `schema-vendor`'s re-vendor PR. |
| Every morning's generated-data push (fleet-pulse, issue-pipeline, token-rotation) woke `drift-check`, `python-tests`, `conformance`, `markdown-oneline` AND `build-dash`; `build-dash` then ran again on its 06:37 cron, which also missed the 07:37 issue-pipeline snapshot by an hour — three site builds a day, two of them of an unchanged or stale tree | Data commits carry `[skip ci]` (as `update-submodules` already did); `build-dash`'s cron moved to 08:37, after the last push. One build a day. The nightly `python-tests` run is what still verifies `main` after data lands. |
| `conformance.yml` (the hub's advisory self-call) ran on every PR and push — ~50 runs a fortnight nobody read; `site-quality-selftest` ran three Lighthouse scans for any edit to `.gitignore`, `check-drift.sh` or `conformance.py` | Both path-filtered to what they actually exercise. The kit test and the quality-contract test those paths were there for run in `python-tests.yml` on every PR instead. |
| `templates/{sdlc,community,spec-driven,site-quality}/test_*.py` ran in no workflow at all (`test_sdlc_kit` had been red since the kit moved to `@v2`); dash-gen tests ran inside the drift gate | `python-tests.yml` runs every Python suite in the repo, one glob list, with the `__main__`-runner check; `drift-check.yml` is the gate plus `actionlint`, nothing else. |
| Three jobs running in another repo's checkout referenced the hub's actions at a floating `@v1` tag (and a new action would not exist at that tag until a release) | They take the hub's actions from a sparse `.fleet-hub` checkout of the workflow's own commit, hidden from git. |
| Two PR gates with no `concurrency`; comments naming retired workflows; `fleet.manifest.yml` crons that predated the `:07/:37` rule | Fixed in passing. |

Net: 36 → 29 workflows, 7,581 → 6,467 lines, with three new actions (~400 lines) holding what was previously repeated. Not changed, and worth a decision of its own: the fleet's canonical `toolchain.node` is still `20` (end of life) while three hub workflows override to `lts/*` because the console's React Router 8 needs ≥ 22.

## 2026-10-27 pass — red runs that were not defects

Three weeks of run history (1,000 runs, 2026-10-07 → 10-27), the failed-step logs of every red run on `main`, and the open fleet-doctor issues. Nearly every red run on a schedule turned out to be something other than a broken workflow.

| Finding | Change |
| --- | --- |
| `fleet-pulse` (6 of 21) and `issue-pipeline` (7 of 21) were the most-failed hub workflows. Every one died in its Claude step after one turn, $0 and ~500 ms: `Claude usage limit hit (HTTP 429): You've hit your weekly limit` (10-23..25) or the five-hour session limit (10-07, 10-08, 10-12, 10-18). The credential was valid, the window shared by every hub loop was spent, and the doctor filed issues about its own red runs (#335, #348) | `claude-cost` gains `usage-limit: skip`. The scheduled agent steps (doctor, the three tiers, repo-evolution) are `continue-on-error` and the cost step owns the verdict: a usage limit is a warning and `usage_limit=true`; a budget hit, a refused credential, an agent failure or a missing result still fail the job. Tiers 2 and 3 skip once an earlier tier was refused. `test_ai_budget.py` requires the pair on every scheduled site. The doctor skips fleet candidates whose only failure is a usage limit. |
| One `issue-pipeline` run (10-22) failed because the Claude Code installer got HTTP 429 three times | Left alone: transient, and the action already retries. |
| `Dependabot Updates` failed 26 of 31 runs. Early runs died cloning a nested submodule of the deleted `bamr87/books.git`; since 10-14 every security update for `.github/site-quality` failed because the patched `tmp`, `zod` and `basic-ftp` sit outside the ranges `@lhci/cli` 0.15.1 (the latest) pins, so the resolver tried to downgrade lhci and the PR was refused | Scoped `overrides` in the runtime's `package.json` lift them (the runner's 39 tests pass; the self-test runs the real scanners). `extract-zip` has no patched release and stays open. The github-actions entry also scans `.github/actions/**`, whose composite actions Dependabot never saw. |
| `git-digs.yml`: 17 runs in its life, every one skipped; schedule commented out on 10-14, kill switch never set | Retired. |
| `unified-evolution.yml`: unrun since 2026-07-08 (failed), and its 08-09 rewrite never ran | Retired; `dash evolve` points at `/evolve`, the issue pipeline and `--repo` / `--all`. |
| A `.github/workflows/cicd.yml` is still registered on the repo with no file behind it: five failed runs from March on the closed PR #6 keep it alive | Nothing to commit; deleting those five runs removes it from the Actions list. |
| One-off reds on `main` — Verify on 10-08 (`@v1` did not exist yet; cut that day), build-dash on 10-07 (Pages API rate limit), publish-kits on 10-18 (an npm `edgesOut` crash), repo-evolution on 10-21 (`FLEET_TOKEN` rejected, rotated since) | Each verified as already resolved or transient. |
| A line-by-line read of the gates and data loops found seven defects that had not yet produced a red run: `schema-vendor`'s re-vendor PR could never open on the cron (`inputs.apply != false` is false when `inputs.apply` is null) and its issue never closed; `api-keys` closed its alarm with an all-clear when the watch crashed before judging; PR builds shared build-dash's production `pages` group; a dry-run or one-repo `token-rotation` dispatch overwrote the fleet's public ledger; `tools/tui/test_app.py` ran in no workflow; the `harness` and `standardize` kits push one branch from different concurrency groups; every label re-ran (and cancelled) the verify pass | Each fixed at the line: the schedule-safe `apply` gate plus a close-when-clean step (not on an unreachable upstream); the watch fails, leaving the issue alone, unless it wrote a verdict; PR builds get their own cancelling group; the ledger publishes only from a full apply run; the TUI suite joins `python-tests`; one concurrency group per engine; only a `verify` label runs the pass. |
| Waste in the same read: `verify` and `conformance` re-ran on push with `gate: false`, so they could not fail; `console-web` built the public site a second time (build-dash's PR paths already cover it); `reconcile-registry` swept the fleet twice to print what it had just fetched; build-dash swept project health on PR builds that are never deployed; `publish-kits` woke on `VERSION` edits it never publishes; the self-test's `expect` job ran on cancelled runs; `backlog-fanout`'s daily dry run picked an expired PAT by presence | Push triggers dropped, the duplicate build removed (its CSP and snapshot assertions moved into build-dash), findings rendered from the JSON, health gated to deploying builds, the `VERSION` path dropped, `!cancelled()`, `resolve-fleet-token`. Smaller: markdown-oneline and verify watch the files they exercise, build-dash watches `diagrams/`, and `agent_fill` on kit `standardize` refuses to run without the `agent-context` artifact it fills. |
| `claude.yml` ran 559 times and executed once; every bot-filed issue and comment wakes it to skip | Kept: it is the hub's own UPS baseline (`claude_workflow`), and a skipped job costs nothing. Its trusted-author guard is ahead of the kit's copy — see below. |

Net with the 10-19 pass: 38 → 29 workflows, 7,900 → 6,508 lines, 6 → 8 shared actions.

Not changed, and each worth a decision of its own:

- **API-key fallback on a spent window.** `CLAUDE_AUTH_ORDER` is `oauth,api_key` and the hub holds a valid key, but nothing falls back on a 429; the `claude-run` step already does. Turning it on moves the doctor and the three tiers (caps $40 + $40 + $60 + $60 a day) onto metered billing whenever the subscription runs out (#348).
- **The agent-context kit's `claude.yml` has no trusted-author guard.** The hub's copy only runs for an OWNER, MEMBER or COLLABORATOR; the template seeded into the fleet runs for anyone who writes `@claude` on a public repo. It needs a kit release and an `--upgrade` fan-out.
- **`toolchain.node` is still `20`** (end of life), as the 10-19 pass noted.

## 2026-10-28 — the pass as a tool

The 2026-10-27 pass was done by hand: reading 29 files, cross-checking five hand-kept copies of their facts, and grepping run logs for why each red run failed. The [workflow atlas](WORKFLOW-ATLAS.md) does that reading every time. Its 17 rules are the standards above (run against `main` before #422, they report the `null-input`, `usage-limit`, `pr-token` and README findings this pass found by hand); its classifier sorts each failed run into capacity, config, transient, dependency or defect; its Retire tab lists ghosts and dead schedules; and its scaffold writes a new workflow inside the rules. Two of the hand-kept copies are gone: the console's dispatch inputs (it refused every input of four workflows) and `test_schedule.py`'s key table, which are now read from the files and from a naming convention.

## 2026-11-05 — a status you can trust

A review of all 412 workflows in 42 repos, and their 9,989 runs from Oct 23 to Nov 5, using custom scripts over the atlas's parser, rules and failure classifier. It ranked by trust, time to a result and API quota, because Actions cost nothing net: October used 44,563 minutes, $292.21 gross, $0.00 net on the billing meter.

Most workflows work. The problem was that their status could not be trusted:

| Finding | Evidence | What changed |
| --- | --- | --- |
| `verify` passed with nothing run | 22 of 25 repos run no scenarios: the kit's empty `app:` block meant a 180-second wait, skipped scenarios and a green job | `fleet-verify.yml` reports **Not verified** in seconds, and a failed build or start fails the job |
| One check spent the hub's API quota | `drift` check (k) made at least 475 calls a run on the shared `GITHUB_TOKEN`. Quota ran out after 4 to 9 full scans in an hour, failing 41 `build-dash` and `verify` runs at `setup-node` and leaving 29 drift runs green with nothing read | The fleet-wide checks run daily; `node-version` is a number, held by the atlas rule `node-alias`; check (k) reports skipped when it read nothing |
| 21-minute `python-tests` on every PR | 98% was one serial step, and install took 12 seconds, so caching could not help | Four parallel shards, and PRs touching only `docs/`, `changelog.d/` or feature fragments skip them |
| `verify` ran for fragments it cannot read | `features/**` matched `features/features.d/` | The trigger is `features/features.yml` |

**Reading run data.** 541 runs never started. 514 were PRs from `github-actions[bot]`, held for approval [since June 2026](https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/); 272 of the 541 show as failures with zero jobs. Their `updated_at` moves days after the event, so a total from run timestamps reads 4,392 hours where the executed runs took 315. Exclude them before computing any rate or duration. Of 595 failed runs, 323 ran a job, and 143 of those were code or test defects.

Not changed here, and each a decision of its own:

- **22 repos still need an `app:` block**, or the verify kit removed. Each is its own PR in its own repo.
- **A new `v2` minor.** The tag from 2026-10-14 lacks `spec-gate.yml`, so `law-ai`'s CI is rejected with zero jobs, and the `release-please.yml` change that turns a denied PR into a warning.
- **`RELEASE_PLEASE_TOKEN` in four repos:** `ai-world-view.github.io`, `bash-365-apex`, `bash-365.com` and `year-of-ai.github.io`. Bots on `it-journey`, `zer0-mistakes` and the hub's `amend/` branches still open PRs that wait for approval.
- **118 references call the hub at `@main`**, and 191 jobs across the fleet have no timeout. The atlas reads only the hub, so neither shows up there.


## 2026-11-07 — measured against the meter

E1 of epic #773 (#775): before acting on any more numbers, make the numbers true. CI deep dives that day set the Actions analytics and the Claude ledger against GitHub's billing meter and against the runs' own logs, and found four ways the analytics under-counted and one way the ledger over-counted:

| Defect | Evidence | Change (schema `actions-usage/v2`) |
| --- | --- | --- |
| The hub was never scanned | `build_report` iterated `_data/projects.yml`; the hub used about 7,900 of about 12,050 billed minutes on Nov 1–7 | `with_hub()` (`fleet.yml` `hub.repo`), shared with the AI collector |
| A silent 600-run cap | fleet-pulse passed `--max-runs 600`; zer0-CMS had 767 runs in the window, zer0-mistakes 1,208, lifehacker.dev 1,959 (its `verify.yml` alone 275 against 73 reported) | every run created in the window is listed by date range, split below GitHub's 1,000-result cap; what still falls short is `truncated: true` + `runs_missed` |
| Cost was run wall clock | GitHub bills each job, rounded up to a minute; on the same runs job-minutes were 1.33x the wall clock overall and up to 2.5x for one workflow, and the deep dive's v1 comparisons (cap and clock together) were 2–4x | `total_min` and its kin are job-minutes; the bounded wall clock stays as `wall_*` and decides `slow` |
| The meter read as per-repo shares | it files the account's whole total under one name: lifehacker.dev 43,924 of 44,563 in October, bamr87 11,920 of 11,925 in November | `account_total_filed_under_*`, `scope: account`; `parity.actions_minutes` compares totals instead |
| Every hub Claude call charged twice | claude-code-action's pretty result block was read line by line into a second record beside claude-cost's echo | the block is decoded whole and folded by #771's same-call rules; `parity.ai_ci_cost` holds the ledger to the echo lines |

**Measured on the branch** (a local `dash-gen actions --days 7` over the hub, zer0-mistakes and zer0-CMS, every run measured, none sampled; window 2026-11-01 01:13 → 11-08 01:13 UTC):

| Repo | Runs | v1 would publish | Job-minutes | Wall clock |
| --- | --- | --- | --- | --- |
| hub | 2,005 | not scanned | 8,567 | 6,887 |
| zer0-mistakes | 584 | 942 | 1,663 | 942 |
| zer0-CMS | 223 | 405 | 716 | 405 |
| **total** | **2,812** | **1,347** | **10,946** | **8,233** |

Per workflow: the hub's `python-tests.yml` is 5,065 job-minutes over 327 runs, 46% of the three repos; zer0-mistakes `ci.yml` 814 against 491 wall (46 runs); zer0-CMS `content.yml` 302 against 130 (14 runs); the hub's `jev-conflicts.yml` 152 against 61. **Parity:** the cache's job-minutes for runs created between Nov 1 and the meter reading in the committed snapshot (Nov 7 05:40 UTC) are 10,109 for these three repos (the hub 7,894), against 11,925 on the meter for the whole account: −15.2% before the other ~40 repos are counted. The first fleet-wide sweep publishes the real gap. The local run could not read the meter itself (the `gh` token lacks the `user` scope), so its own `parity` block says so.

**The ledger, same day:** `dash-gen ai-usage --days 7` on the hub listed 2,003 runs (the old 300-run budget reached about a day of them; the committed ledger held 5 hub runs for 14 days), found 207 Claude runs, 180 of them no-spend, and priced 26 with result lines at $124.14 — equal to the lines, gap 0.0%. The 23 of those 26 still in the ledger's 200 rows priced at **$221.96 with the old parser and $110.98 with the new**: exactly 2.0x, run 42352285943's $25.64 against $12.82 among them.

**The API budget.** Job-minutes cost one jobs request per run. The jobs endpoint, not `/timing`: on a public repo `/timing` reports `total_ms: 0` for every job, and it is the legacy usage endpoint GitHub is closing down. So:

- a completed run's job-minutes are cached per (repo, run id, attempt) in `.dash-lake/actions_jobs_cache.json`, which fleet-pulse restores and saves with `actions/cache`; only runs new since the last sweep are fetched;
- `skipped`, `startup_failure` and `action_required` runs need no request (22% of the 2,812 above);
- the fetch stops at `--max-job-calls` (1,500), at the quota left after `--api-reserve` (1,000) and after `--max-job-seconds` (600), wall-clock suspects first and then round-robin across workflows; anything left is estimated from its workflow's measured job/wall ratio and every row holding an estimate says `sampled: true`.

The measured run above made 2,229 requests (2,193 jobs, 33 listings, 3 workflow lists) in 27 minutes over a home connection. Estimated steady state for the whole fleet: about 600 job requests a day for the runs new since yesterday, plus about 150 listing pages, 45 workflow lists and one meter read — roughly 800 a day, against 5,000 an hour. The first sweeps start cold: they spend the ceiling, publish `sampled: true`, and converge within about a week as the window slides.

Left in E1: the conformance / features-index writer (#775), and a first fleet-wide sweep in fleet-pulse to replace the three-repo parity above with the real one.

## 2026-11-07 — a red PR is not a flaky workflow

The `zer0-mistakes` Evidence gate was flagged `flaky` at 70.3% success, and the fleet-doctor advised de-flaking it. The gate is deterministic: every failure was the gate rejecting a PR that lacked its regression spec or before/after evidence. Five came from one open PR, and one from a PR that passed once its evidence was committed. The `flaky` rule only had counts, so it could not tell "the PR decided the verdict" from "the verdict is random" (#614).

The analytics now record `head_branch` and `head_sha` for each run, plus the repo's default branch (one `/repos/{nwo}` request per repo; the run's embedded `repository` does not carry it), and use the definition of flakiness: **the same commit produced different verdicts**. A workflow that would read `flaky` or `failing` gets **`pr-red`** instead when every failure is on a non-default-branch head and no commit both passed and failed. `pr-red` is not a correctness signal, and `remediate` does not queue a workflow that carries only `pr-red`. A re-run that flips the verdict on one commit is still `flaky`. A failure on the default branch still counts. A run with no head fields falls back to the old rule. The flag catches any check whose verdict depends on the PR's contents, not only the gates someone remembered to list.

## 2026-11-07 — the hub's own minutes

The billing meter put 11,920 of November's first 11,925 minutes on `bamr87`, the hub, and the analytics showed no hub rows at all, because `actions_analytics.py` read only the submodule registry (#782, above, has since added the hub). So the hub's minutes were measured directly: all 1,955 hub runs from Nov 1 to Nov 7, jobs fetched for a stratified sample of 709, and per-job minutes rounded up the way billing rounds them.

| Workflow | Event | Runs | Job-minutes | Billed (rounded per job) |
| --- | --- | --- | --- | --- |
| `python-tests` | pull_request | 213 | 3,533 | 3,731 |
| `python-tests` | push | 102 | 756 | 855 |
| `drift-check` | pull_request + push | 315 | 579 | 741 |
| `verify` | pull_request | 149 | 441 | 503 |
| `build-dash` | all | 193 | 444 | 581 |
| `jev-number` | push + issues | 114 | 308 | 410 |
| `issue-pipeline` | schedule + dispatch | 11 | 386 | 402 |
| `markdown-oneline` | pull_request + push | 277 | 44 | 274 |
| everything else | | 581 | 445 | 697 |
| **Hub total** | | **1,955** | **6,936** | **8,194** |

**The meter's per-repo split is not a per-repo split.** Up to the meter's fetch (Nov 7 05:40 UTC) the hub measured about 7,900 billed minutes; a sampled measurement of the other 38 active repos (1,785 runs) came to about 4,130; together about 12,050, against the meter's 11,925 account total. The meter puts that whole total under one repository name: all of October went to `lifehacker.dev` while the hub, with 2,090 runs that month, never appeared, and November's only other row, `zer0-mistakes`' 5 minutes, matches the 5 macOS minutes that repo ran. The hub is about two thirds of the fleet's November minutes, not 99%.

**Where the hub's minutes go.** `python-tests` is 58% of them. The Nov 6 shard split cut wall-clock but raised a full run from about 18.7 to 27.1 billed minutes: four setups, a `changes` job and the final `python-tests` job, each rounded up to a whole minute. The larger cost was inside the tests: every file runs under `coverage run`, and coverage's default tracer more than doubled the console, pages and spec files. The test shards now run with `COVERAGE_CORE=sysmon` (Python 3.12's `sys.monitoring`). On `python:3.12` with coverage 7.17, the same files took 930 seconds under the old tracer and 570 under `sysmon` (`test_console` 116 → 50, `test_jev_spec` 62 → 28, `test_jev_loop` 310 → 249, the `rest` shard 214 → 149), and the coverage table was identical (5,758 statements, the same misses). That is about 7 billed minutes off each full run, roughly 2,300 to 2,800 minutes per 14 days at November's volume (estimated). No test, file or gate changed.

Next, by minutes per 14 days, each a change of its own:

- **About 1,300 (new load, not a saving):** `pr-review.yml` started on Nov 7 and runs one ~10-second job, billed as a minute, for each PR workflow that finishes. It already merges pending runs per head SHA; anything more would cost the § 19 contract.
- **About 900:** cancelled `python-tests` push runs. Merges in quick succession cancel the run before them after all four shards have started.
- **About 900, once `sysmon` has landed:** two shards instead of four. The serial suite was split because it took 21 minutes, and most of that was the tracer.
- **About 265:** `jev-conflicts.yml` starts a runner on every push and every six hours only to read `vars.JEV_CONFLICTS_ENABLED`. As a job-level `if:` on `triage`, the check costs nothing, which is the form the atlas rule recommends.
- **About 230:** the `changes` job also runs on push and on the schedule, where its answer is always "run".

Not costs: the 191 skipped `claude.yml` runs and the 93 skipped `pr-review.yml` runs started no job and billed nothing. Bot data commits carry `[skip ci]` or are pushed with `GITHUB_TOKEN`, so only 6 of the 32 `jev-number` commits started a push suite.

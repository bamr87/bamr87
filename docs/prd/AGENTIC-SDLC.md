# Plan — GitHub Actions as the agentic SDLC platform: typed decisions, telemetry and the trim/verify loops

> **Status: Draft / proposed.** Plan only; nothing here is implemented. Accepted when the maintainer merges this PR; each phase lands in its own PR.
> Decision record: [ADR 0008](../adr/0008-typed-decisions-as-pipeline-gates.md) (proposed in the same PR). Feature: `HUB-NEW` (slug `agentic-sdlc-platform`, fragment [`features/features.d/agentic-sdlc-platform.yml`](../../features/features.d/agentic-sdlc-platform.yml)). Roadmap: `FF-NEW:agentic-sdlc-platform` ([`_data/roadmap.d/agentic-sdlc-platform.yml`](../../_data/roadmap.d/agentic-sdlc-platform.yml)).
> Requirements: new `FR-NEW:typed-decision-gate`, `FR-NEW:decision-trace-replay`, `FR-NEW:trim-verify-loops`, `NFR-NEW:fail-closed-decisions` (declared in the fragment's `prd_new:`, numbered at merge); existing FR7, FR10, FR15, FR26, FR60, NFR4, NFR9.
> Source: the maintainer's design note *GitHub Actions as an Agentic SDLC Platform — Design with Jev* (2026-11-06), restated here in the hub's terms. Where the note and the hub disagree, § 2 says which won and why.
> Builds on: [WORKFLOW-ATLAS.md](../WORKFLOW-ATLAS.md) (the rules), [WORKFLOW-OPTIMIZATION.md](../WORKFLOW-OPTIMIZATION.md) (the cost audit), [DAILY-ANALYSIS.md](../DAILY-ANALYSIS.md) (the doctor), [JEV.md](../JEV.md) (the engine), [OBSERVABILITY.md](../OBSERVABILITY.md) (the lake and OTel planes), ADR 0002 (local runner), ADR 0007 (the Studio, whose S1 sync and S2 views this plan reads and extends).
> Governing rules: [`docs/constitution.md`](../constitution.md) § 10 (methodology, prior art first), § 11 (write-back), § 12 (merge authority), § 13 (eval baseline and risk tiers), § 17 (loop switches).

## 1. Outcome

A pull request in any fleet repository runs only the checks its diff can affect, and a typed, thresholded, replayable decision is what said so. A failed run is classified before any agent spends a turn on it. A nightly full run is the backstop, and every failure it catches that a trimmed run missed becomes a regression case that tightens the next decision. Minute spend, flake rate and the missed-failure count are one fitness function, read from the billing meter and the lake, and an optimization survives only if minutes drop while missed failures stay at zero.

## 2. The note, mapped onto the hub

The note describes an organization with three repositories and a vendor ecosystem. The hub is one personal account with one hub repository, its own agent engine and its own rules. Each row says what the note asks for, what the hub does today, and what this plan does about the gap.

| Note | Hub today | This plan |
| --- | --- | --- |
| `org/.github` holds every reusable workflow, versioned by tag, consumers pin | `.github/workflows/` holds seven `workflow_call` workflows, versioned by hand-cut major tags (`v1`, `v2`, [WORKFLOW-VERSIONING.md](../WORKFLOW-VERSIONING.md)); callers ride `@main` or `@vN` | No change to the home; the decision node lands inside these workflows (A2) |
| Pinned action SHAs | Actions ride major tags by standing rule ([DEPENDENCIES.md](../DEPENDENCIES.md)); drift check (j) holds it | Not adopted; the `sha-pin` rule stays as it is. Re-pinning the decision model release is quarterly (A6) |
| Concurrency cancellation, path filters, caching, job consolidation, macOS isolation | `concurrency` is a rule; `standard-ci.yml` has a docs-paths decision and guarded caches; the 2026-09 audit fixed the worst cases by hand | Each lever becomes an atlas rule with a named incident, fleet-wide through the Studio's model (A1) |
| Jev decision node via `jev-action`, thresholds in a lockfile, conservative branch below the bar | Nothing | `typed-decision` composite action, `_data/decisions.yml`, fail-closed (A2) |
| Nightly Actions API query into a metrics branch | `fleet-pulse.yml` writes `_data/actions_usage.yml` from the billing meter daily; the lake keeps run history; the Studio sync (ADR 0007 S1) reads every repo's files | Add cache hit rate, queue time, flake rate, time-to-green and decision traces to the same stores; panels on the Studio (A3) |
| Agent triggered on failure, Jev pre-classifies, heavy agent proposes, never merges, `jev-review-action` screens its PR | The doctor (Opus, PR-only), the issue pipeline, scout and evolution; § 11, § 12, § 13; no typed pre-classification; no patch screen | Typed pre-classification in front of the doctor and tier 2; a patch screen on agent and human PRs at the 0.70 floor; trace routing (A4) |
| GitHub App installation tokens | `FLEET_TOKEN` probed with `gh api user` | Unchanged; a GitHub App is a maintainer decision, recorded if taken (A4 names it, does not assume it) |
| Leanest asks Jev which tests to skip; matrix pruned | Nothing; the hub's suites are Python `unittest` and pytest, the console's are Vitest, fleet repos vary (Jest, RSpec, pytest) | A test selector in shadow mode first, per repository, per suite runner (A5) |
| Nightly full suite, `trace-to-case`, `fuzz`, thresholds rise on instability, fitness function | Nothing | The verify loop as a scheduled hub workflow with a kill switch, and the fitness gate on every A5 promotion (A6) |
| Dashboard panels, alerts, weekly replay review, quarterly re-pin | The Studio (ADR 0007 S2) and the fleet-pulse digest | Panels and alerts in A3; the review cadence in A6 |
| `org/ci-metrics`, `org/ci-agent` | `_data/` plus the lake; `tools/jev/` | No new repository (ADR 0008 decision 8) |
| (not in the note; added by the maintainer 2026-11-06) the flow of work in process is governed and visible | Circuit breakers only: per-call caps, `max_open_per_repo`, `harnesses.throughput`; the Work board's human order; the PM review's daily read; the expedite class (§ 27) | One flow policy in `fleet.yml`, one module every loop reads, continuous flow and progress measurement on the console (A7) |

**The name.** Everywhere in the hub, **JEV** is the hub's engine and **TypeSafe Jev** (or **the decision model**) is the external model. A workflow, doc or issue that says "Jev" without the qualifier means the hub's engine.

## 3. Needs assessment, prior art and the build-versus-adopt call (§ 10.8)

These are recorded in [ADR 0008](../adr/0008-typed-decisions-as-pipeline-gates.md) and not repeated here. The short form: the decision model is adopted behind one thin action after an offline evaluation on the fleet's own history; the cost levers are adopted as atlas rules; test selection starts in shadow mode with an existing selector; the lockfile, flight recorder, replay and fuzzer are built in `tools/jev/` only if no maintained tool provides them when their phase starts. A0 is the phase that can still say no.

## 4. Architecture

```text
 pull request / push / schedule                              nightly (A6)
        │                                                        │
        ▼                                                        ▼
 reusable workflow (standard-ci, ai-lane, …)            verify loop: full suites unpruned
   ├─ typed-decision  ──► TypeSafe Jev (or claude -p fallback)   ├─ missed failure? → trace-to-case → eval set
   │     question + options + threshold from _data/decisions.yml │
   │     answer + confidence + cleared? ──► trace (JSON)         ├─ fuzz lockfile → unstable decision → threshold up
   ├─ cleared → trimmed selection / pruned matrix                 └─ fitness: minutes ↓ and missed = 0 → promote; else demote
   └─ not cleared or unreachable → run everything                            ▲
                                                                              │
 traces + run cost + cache/queue/flake/time-to-green ──► lake ──► Studio panels, fleet-pulse alerts
                                                                              │
 failure ──► typed pre-classification (category, severity, safe-to-fix) ──► doctor / tier 2 (PR only) ──► patch screen ≥ 0.70 ──► § 12 gate
```

### 4.1 The decision lockfile

`_data/decisions.yml`, `schema: decisions/v1`. One entry per decision: `id`, `kind` (`choice`, `score`, `yesno`), `question`, `options` or `rubric`, `threshold`, `conservative` (the branch taken below the bar), `consumers` (workflow and job), `risk` (§ 13.6 tag), and `fingerprint` (a hash of the fields above, written by `python3 -m tools.jev decisions lock`). A workflow reads a decision by `id`; a changed fingerprint is a changed policy, and replay refuses to compare traces across fingerprints unless asked. Thresholds change only through a PR that cites the missed-failure data, and that PR is gated (§ 12.3, "budgets or billing" and "security-sensitive config").

The first decisions:

| id | kind | threshold | conservative branch | consumer |
| --- | --- | --- | --- | --- |
| `change-class` | choice: docs, config, code, mixed | 0.85 | `mixed` (run everything) | `standard-ci.yml` (replaces the shell docs-paths test once it matches it on the eval set) |
| `sensitive-path` | yesno | 0.95 | yes (gate up) | `standard-ci.yml`, `ai-lane.yml` |
| `affected-suites` | choice, multi | 0.85 | all suites | `standard-ci.yml` → A5 |
| `platform-relevant` | yesno per OS leg | 0.85 | run the leg | matrix callers → A5 |
| `failure-class` | choice: flaky, real, infra, quota, cancelled | 0.95 | real (escalate to a person) | `fleet-pulse.yml` doctor, `issue-pipeline.yml` tier 2 → A4 |
| `safe-to-auto-fix` | yesno | 0.95 | no (open an issue) | the doctor → A4 |

### 4.2 The composite action

`.github/actions/typed-decision/`: inputs `decision` (the id), `context` (a file or a string), `model` (`typesafe` or `claude`, default from `_data/fleet.yml` `decisions.executor`), `max-budget-usd` from `budget.call_sites` like every other call site. Outputs `answer`, `confidence`, `cleared` (`true`/`false`) and `trace` (a path). It runs `python3 -m tools.jev decisions ask`, so a local run (`tools/dash loop run`, ADR 0002) and CI produce the same trace from the same code. It never has a GitHub token. A model error, timeout or 429 is `cleared=false` with `answer=<conservative>`, never a failed step, and the `claude-cost` pairing stays `usage-limit: skip` on a schedule (standing rule).

### 4.3 Traces, replay and fuzz

One JSON record per decision under the run's artifact (CI) or `.fleet/runs/<run_id>/decisions/` (local), shipped to the lake by the existing `dash lake sync` with a `decisions` table: run, repo, workflow, decision id, fingerprint, model version, inputs digest, usage, answer, confidence, cleared, outcome (filled in by A6 when the backstop knows whether the decision was right). `python3 -m tools.jev decisions replay --since 7d` re-asks each trace's question against the current lockfile and diffs the answers; `… fuzz <id>` mutates inputs (irrelevant context added, paths reordered, whitespace) and reports stability; an unstable decision has its threshold raised by the PR the weekly review opens, never silently.

### 4.4 Telemetry

Added to the stores that exist, never to a new one: per-job queue time and cache hit rate from the run API into the lake; flake rate and time-to-green derived in `actions_analytics` and written to `_data/actions_usage.yml` as new keys (additive; the file's consumers ignore unknown keys); the decision confidence distribution, the missed-failure count and the agent PR acceptance rate as Studio panels fed from the lake. Minutes keep coming from the billing meter and nothing else (standing rule). Alerts are rows in the fleet-pulse digest: spend above `harnesses.budget`, confidence distribution drifting down week over week, any missed failure, any agent PR whose `sensitive-path` answer was yes.

### 4.5 The trim and verify loops

Trim runs per PR inside the reusable workflows. For a repository in **shadow**, the decision is asked and recorded and the full suite still runs; for one **promoted**, the reduced selection runs and the full suite is the nightly backstop. Promotion is a per-repository flag in `_data/fleet.yml` `decisions.promoted:` changed by a gated PR that cites the window: at least 14 nightly backstop runs with zero missed failures and a replay diff with no flipped answers. Any missed failure demotes the repository in the same PR the verify loop opens, and raises that decision's threshold by 0.02. macOS and Windows legs follow the same flag through `platform-relevant`.

Verify is `.github/workflows/decision-verify.yml`, scheduled (declared in `fleet.yml` `schedule:`, not on the hour), `vars.DECISION_VERIFY_ENABLED` kill switch, `concurrency` group, `permissions: contents: read` plus `pull-requests: write` for the demotion PR through `publish-data`. It runs every promoted repository's full suites through the existing reusable workflows with trimming off, joins the results to the day's traces, writes `trace-to-case` regression cases into the decision's eval set (§ 13.1), runs `fuzz` on every lockfile entry, and opens one PR with the threshold and promotion changes the data justifies. It never merges.

### 4.6 The fitness function

A proposed optimization (a trim promotion, a cache key, a job consolidation, a matrix prune) carries three numbers from the lake over its window: minutes before and after by OS, flake rate, missed failures. It survives only if minutes dropped and missed failures are zero; the Studio shows the three numbers on the PR's row, and the verify loop writes them into the PR body.

### 4.7 Flow control: how much is in process, and who takes the next slot

The loops are many producers against one reviewer. Each has a circuit breaker, but nothing governs the whole: on a busy day the doctor, the issue pipeline, the scout and evolution can each open their cap of pull requests, and the review lane fills while the roadmap's own phases wait. Flow control is the configuration and the tool that shape what is in process at any moment, balance the loops against each other, and show progress continuously.

**The policy** is `_data/fleet.yml` `flow:` (`schema: flow/v1`), validated by `tools/test_flow.py`:

| Key | Meaning | First value |
| --- | --- | --- |
| `wip.fleet` | open items per lane across the fleet: `ready`, `in_flight`, `review` | taken from the observed counts on the day A7 lands, then tightened |
| `wip.loops.<loop>` | the same per loop (doctor, issue pipeline, scout, evolution, topic loop, fan-outs) | the loop's current cap (`max_open_per_repo`, remediation caps) expressed as WIP |
| `wip.repos.default`, `wip.repos.<repo>` | in-flight items per repository | 1 for `in_flight` (today's "one open PR per repo" backpressure), 3 for `review` |
| `shares` | each loop's share of the day's agent runs under `harnesses.throughput`, as a weight | equal weights; the Work board can skew them by PR |
| `classes` | `expedite` (WIP 1, preempts, § 27), `standard`, `maintenance` | as § 27 |
| `age.lift_after_days` | an item older than this in Ready moves to the front of its lane once | 14 (`pm.thresholds.stale_in_progress_days`) |
| `starve.alert_after_days` | a loop that took no slot for this long is an attention item | 7 |

**The tool** is `tools/fleetcore/flow.py` and `tools/dash flow [status | plan | check]`, one read model shared by the console, the TUI, the MCP (`fleet_flow`) and every loop. `status` reads the Fleet project, the issue labels, the open PRs and the roadmap and reports WIP per lane against its limit, per loop and per repository. `plan` says, for the next run of each loop, how many slots it has and which items (by the Work board's order) it would take; a loop whose lane is full gets zero and the reason. `check` is the gate `test_flow.py` and the drift check run: the policy parses, every loop in `switches.loops` has a share, and no repository limit exceeds the fleet limit. Each loop's queue builder (`issue_pipeline.py`, `remediation.py`, the scout's `file` job, evolution's targets) calls `flow.slots(loop, repo)` before it takes anything and writes the answer to its run summary, so a skipped item is explained, never silent. A human exception is a `work_queue.yml` override (the existing mechanism), which the board shows as an override against the policy.

**The measurement** is continuous and $0: `fleet-pm.yml`'s daily snapshot (`_data/pm_review.yml`) gains a `flow:` block with WIP per lane against limit, throughput (items that left In flight and Review per day, 7-day and 28-day), lead time (Ready to Done, P50 and P85), blocked age, loop starvation, and progress per epic (sub-issues closed over total, from GitHub's sub-issue summary) and per roadmap entry (status, phases, the sub-issue summary of its `issue_url`). The lake keeps the daily rows so the console draws trends.

**The console.** The Work board (`/work`) draws a meter on each lane (count against limit, red over it), a slot column per loop for its next run, and the override marks. The Roadmap page (`/roadmap`) draws progress per entry and per epic (phases done, the next phase, days since the last change) and a burn-up of entries shipped against proposed. The Home page carries a flow panel (WIP, throughput, lead time, starved loops) with its read time. All three read the snapshot and the lake and nothing reads GitHub on a PR; the public site shows the committed snapshot read-only.

**Alerts** are fleet-pulse digest rows: a lane over its limit, a starved loop, an in-flight item past `age.lift_after_days`, and an epic with no closed sub-issue in 28 days.

## 5. Guardrails (every phase)

- **Fail closed.** No decision below threshold, and no decision the model could not answer, ever skips work or lowers a gate.
- **Shadow first.** No repository is promoted without the window in § 4.5; the first promotion is the hub itself.
- **PR-only.** Every loop and agent opens PRs and never merges (§ 12); `FLEET_TOKEN` for PRs that must run CI, probed, never presence-checked.
- **Caps and the ledger.** Every decision call site is in `budget.call_sites` with `--max-budget-usd`; local runs count under `budget.loops`; every figure is API-equivalent (estimate).
- **Kill switches and crons.** `vars.DECISION_VERIFY_ENABLED` (on by default once the loop is live, `!= 'false'`); no cron on the hour; declared in `fleet.yml`.
- **Secrets.** The decision model's key is named in `fleet.yml` `tokens:` and `token-rotation.yml` `env:`, written hub-first, never held in `_data/`.
- **Gated changes.** Thresholds, promotions, the lockfile schema, the ADR and anything touching the token contract are § 12.3 gated PRs with `needs-amr`.
- **Hands off the Mac.** Nothing here changes the maintainer's machine; local runs use ADR 0002's isolated workspace.
- **Tests and evidence.** Each phase lists its tests and links the green run; a user-facing surface (Studio panels) follows [VERIFICATION.md](../VERIFICATION.md); everything else is `skip-evidence` with a reason.
- **Prior art.** A phase that adopts or builds one of the ecosystem pieces records which, with one line of fit, in its PR body (§ 10.8).
- **Flow.** From A7 on, no loop takes a slot its lane does not have; a limit changes only by a PR to `fleet.yml`, an exception only by the human's `work_queue.yml` override.

## 6. Roadmap and phases

Phases are the epic's sub-issues, done in order. A0 can end the plan. A1 and A7 need no model and can run beside A0; A7 depends on nothing in A2 to A6 and is worth doing even if A0 says no. A5 and A6 are one loop in two halves and ship in that order. Dates are targets, not promises; the fleet's loops are scheduled around a person, not the other way round.

| Phase | Delivers | Acceptance | Target |
| --- | --- | --- | --- |
| **A0** Evaluation spike and the decision record | ADR 0008 accepted; an eval set of about 20 real past PRs and 20 past failures (§ 13.1) under `tools/jev/evals/decisions/`; the model and the `claude -p` fallback both scored offline on `change-class`, `sensitive-path` and `failure-class`; a one-page result with accuracy, latency and cost per decision; the answer to "where does the model run" | The maintainer accepts or rejects the ADR with the numbers in front of them; every later phase cites the eval set | 2026-11 |
| **A1** Cost levers as standards | Atlas rules `cancel-in-progress`, `path-filter`, `macos-isolated`, `cache-measured`, `job-consolidation` at `warn`, each with its incident; `actions_usage.yml` gains minutes by OS and cache hit rate; `tools/dash workflows cost` lists the top ten levers fleet-wide through the Studio model; the hub's own workflows at zero warnings | The rules run over the fleet model with no false positive on the hub's 36 files; the fleet-pulse digest shows the top levers | 2026-11 |
| **A2** The typed-decision node | `_data/decisions.yml` (`decisions/v1`) with the six first decisions; `tools/jev/decisions.py` (`ask`, `lock`, `lint`); `.github/actions/typed-decision/`; `change-class` and `sensitive-path` wired into `standard-ci.yml` in shadow (answer recorded, nothing skipped); the trace format; `test_decisions.py`; the atlas rule `decision-threshold` (every consumer names a lockfile id, every id has a threshold and a conservative branch) | On the hub, 14 days of traces with `change-class` agreeing with the shell docs-paths test on every PR; no failed step from a model error | 2026-12 |
| **A3** Telemetry and the panels | Lake tables `decisions` and per-job `queue_ms`, `cache_hit`; flake rate and time-to-green in `actions_usage.yml`; replay (`decisions replay`); Studio panels (minutes by repo and OS, cache hit rate, P50/P95 job duration, flake rate, confidence distribution, missed-failure count, agent PR acceptance rate); the four alerts in the fleet-pulse digest | Every panel reads the lake, none reads GitHub on a PR; replay of a week's traces returns the same answers under the same fingerprint | 2026-12 |
| **A4** Harness pre-classification and the patch screen | `failure-class` and `safe-to-auto-fix` in front of the doctor and the issue pipeline's tier 2 (below the bar: an issue, no agent turn); a patch screen (adopted if one exists, else `decisions screen` over `claude -p` with a schema) at the 0.70 floor as a check on agent PRs and on human PRs, annotations and a JSON report, never prose; trace routing (auto-close, human review, bug, escalate) recorded on the run; the GitHub App question put to the maintainer as a decision, not assumed | A month of doctor runs where every agent turn was preceded by a cleared classification; the screen's findings on the eval set match the recorded outcomes | 2027-01 |
| **A5** The trim loop in shadow | `affected-suites` and `platform-relevant` wired into `standard-ci.yml` and the matrix callers; a selector per suite runner (pytest and `unittest` first, then Vitest and Jest) in shadow; `decisions.promoted:` in `fleet.yml`, empty; the trimmed selection recorded on every run beside what actually ran | On the hub, 14 nightly windows of shadow data; a report of what would have been skipped and whether any of it failed | 2027-01 |
| **A6** The verify loop and the first promotion | `decision-verify.yml` with its switch, cron and `publish-data`; `trace-to-case`; `fuzz`; the fitness numbers on every optimization PR; the weekly replay review as a digest row; the quarterly re-pin as a `token-rotation.yml` sibling task; the thin caller kit fanned out to fleet repositories by `fanout.yml` (dry run, PR-only); the hub promoted first, by a gated PR citing its window | The hub runs trimmed on PRs with the nightly backstop green for 14 days and zero missed failures; one fleet repository promoted the same way; minutes by OS down against the A1 baseline | 2027-02 |
| **A7** Flow control | `fleet.yml` `flow:` (`flow/v1`) with its first limits taken from observed counts; `tools/fleetcore/flow.py` and `tools/dash flow status|plan|check`; every loop's queue builder calls `flow.slots()` and writes the answer to its summary; `test_flow.py` in the drift gate; `pm_review.yml` `flow:` block with WIP, throughput, lead time, blocked age, starvation, epic and roadmap progress; Work board meters and slot column, Roadmap progress and burn-up, Home flow panel; MCP `fleet_flow`; four digest alerts | On a day when every loop fires, no lane ends over its limit and each loop's summary names the slots it had; the Roadmap page shows this epic's phases done over total from the sub-issue summary; the public site shows the same numbers read-only; `fleet-pm.yml` stays $0 | 2026-12 |

## 7. The epic

Filed 2026-11-06 on the Fleet project with Status and Priority set (§ 10): epic [#737](https://github.com/bamr87/bamr87/issues/737); sub-issues, in order, [#738](https://github.com/bamr87/bamr87/issues/738) (A0), [#739](https://github.com/bamr87/bamr87/issues/739) (A1), [#740](https://github.com/bamr87/bamr87/issues/740) (A2), [#741](https://github.com/bamr87/bamr87/issues/741) (A3), [#742](https://github.com/bamr87/bamr87/issues/742) (A4), [#743](https://github.com/bamr87/bamr87/issues/743) (A5), [#744](https://github.com/bamr87/bamr87/issues/744) (A6), [#748](https://github.com/bamr87/bamr87/issues/748) (A7, flow control, runs beside A1). Every one carries `agent:hold`; the phases whose PRs are gated (A0, A2, A4, A6) carry `needs-amr`. The issue bodies are the scope, acceptance and guardrails of § 6, restated per phase; the issues are the record from here, and a change to a phase's scope is made there and mirrored into § 6.

## 8. Open questions (from the note, with the hub's starting answers)

- **Where does the decision model run?** A0 answers it with latency and cost. The starting answer is the hosted API from a hosted runner, with `claude -p` as the fallback executor; a self-hosted runner on a public repository is already ruled out (#484).
- **What confidence floors?** 0.85 for skipping, 0.95 for gating, as the note proposes; A6 moves them from missed-failure data only.
- **How much of the harness should be typed questions rather than free-form reasoning?** The classification in front of the agent and the screen behind it are typed from A4; the proposal in between stays free-form under its allowlist and cap. Whether the proposal itself can be decomposed into typed steps is ADR 0004 P1's question and is not answered here.
- **Which WIP limits?** The observed in-flight counts on the day A7 lands, then tightened from the lead-time and throughput numbers; the Work board shows the effect of a proposed limit before the PR that sets it.
- **Jest.** The note assumes one Jest suite. The hub's suites are Python; A5 starts there and reaches Jest through the fleet kit.

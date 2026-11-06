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

## 6. Roadmap and phases

Phases are the epic's sub-issues, done in order. A0 can end the plan. A1 needs no model and can run beside A0. A5 and A6 are one loop in two halves and ship in that order. Dates are targets, not promises; the fleet's loops are scheduled around a person, not the other way round.

| Phase | Delivers | Acceptance | Target |
| --- | --- | --- | --- |
| **A0** Evaluation spike and the decision record | ADR 0008 accepted; an eval set of about 20 real past PRs and 20 past failures (§ 13.1) under `tools/jev/evals/decisions/`; the model and the `claude -p` fallback both scored offline on `change-class`, `sensitive-path` and `failure-class`; a one-page result with accuracy, latency and cost per decision; the answer to "where does the model run" | The maintainer accepts or rejects the ADR with the numbers in front of them; every later phase cites the eval set | 2026-11 |
| **A1** Cost levers as standards | Atlas rules `cancel-in-progress`, `path-filter`, `macos-isolated`, `cache-measured`, `job-consolidation` at `warn`, each with its incident; `actions_usage.yml` gains minutes by OS and cache hit rate; `tools/dash workflows cost` lists the top ten levers fleet-wide through the Studio model; the hub's own workflows at zero warnings | The rules run over the fleet model with no false positive on the hub's 36 files; the fleet-pulse digest shows the top levers | 2026-11 |
| **A2** The typed-decision node | `_data/decisions.yml` (`decisions/v1`) with the six first decisions; `tools/jev/decisions.py` (`ask`, `lock`, `lint`); `.github/actions/typed-decision/`; `change-class` and `sensitive-path` wired into `standard-ci.yml` in shadow (answer recorded, nothing skipped); the trace format; `test_decisions.py`; the atlas rule `decision-threshold` (every consumer names a lockfile id, every id has a threshold and a conservative branch) | On the hub, 14 days of traces with `change-class` agreeing with the shell docs-paths test on every PR; no failed step from a model error | 2026-12 |
| **A3** Telemetry and the panels | Lake tables `decisions` and per-job `queue_ms`, `cache_hit`; flake rate and time-to-green in `actions_usage.yml`; replay (`decisions replay`); Studio panels (minutes by repo and OS, cache hit rate, P50/P95 job duration, flake rate, confidence distribution, missed-failure count, agent PR acceptance rate); the four alerts in the fleet-pulse digest | Every panel reads the lake, none reads GitHub on a PR; replay of a week's traces returns the same answers under the same fingerprint | 2026-12 |
| **A4** Harness pre-classification and the patch screen | `failure-class` and `safe-to-auto-fix` in front of the doctor and the issue pipeline's tier 2 (below the bar: an issue, no agent turn); a patch screen (adopted if one exists, else `decisions screen` over `claude -p` with a schema) at the 0.70 floor as a check on agent PRs and on human PRs, annotations and a JSON report, never prose; trace routing (auto-close, human review, bug, escalate) recorded on the run; the GitHub App question put to the maintainer as a decision, not assumed | A month of doctor runs where every agent turn was preceded by a cleared classification; the screen's findings on the eval set match the recorded outcomes | 2027-01 |
| **A5** The trim loop in shadow | `affected-suites` and `platform-relevant` wired into `standard-ci.yml` and the matrix callers; a selector per suite runner (pytest and `unittest` first, then Vitest and Jest) in shadow; `decisions.promoted:` in `fleet.yml`, empty; the trimmed selection recorded on every run beside what actually ran | On the hub, 14 nightly windows of shadow data; a report of what would have been skipped and whether any of it failed | 2027-01 |
| **A6** The verify loop and the first promotion | `decision-verify.yml` with its switch, cron and `publish-data`; `trace-to-case`; `fuzz`; the fitness numbers on every optimization PR; the weekly replay review as a digest row; the quarterly re-pin as a `token-rotation.yml` sibling task; the thin caller kit fanned out to fleet repositories by `fanout.yml` (dry run, PR-only); the hub promoted first, by a gated PR citing its window | The hub runs trimmed on PRs with the nightly backstop green for 14 days and zero missed failures; one fleet repository promoted the same way; minutes by OS down against the A1 baseline | 2027-02 |

## 7. The epic

The epic and its sub-issues follow § 10.2: one `epic` issue, one sub-issue per phase in order, each with scope, acceptance criteria and guardrails, on the Fleet project with Status and Priority set, `agent:hold` on every one so the issue pipeline neither rewrites nor implements them out of order. The text below is what gets filed; after filing, this section is replaced by the issue numbers (the way [FLEET-ACTIVITY-REPLAY-PLAN.md](FLEET-ACTIVITY-REPLAY-PLAN.md) records #624).

### Epic — the agentic SDLC platform: typed decisions gate risk, telemetry scores efficiency, tests gate correctness (ADR 0008)

Labels: `epic`, `ci`, `P1`, `size:xl`, `agent:hold`, `governance`.

> GitHub Actions is the fleet's execution substrate, not a CI tool. This epic makes every skip, retry and auto-fix in the pipeline a typed, thresholded, replayable decision that fails closed; puts the cost and quality numbers beside those decisions in the lake; and adds the two loops that recover minutes safely, a per-PR trim and a nightly verify that converts every missed failure into a regression case.
>
> **Asked by the maintainer (2026-11-06):** build a plan, roadmap and epic for the design note *GitHub Actions as an Agentic SDLC Platform — Design with Jev*.
>
> **Where the hub is:** layers 1 to 3 of the note exist in some form (reusable workflows by major tag, the billing-meter snapshot and the lake, the doctor and the issue pipeline under § 11 to § 13). No typed decision node, no decision traces, no test selection, no backstop loop. Actions cost is $0 net on the meter today; the case is control, not money.
>
> **Naming:** JEV is the hub's engine; TypeSafe Jev is the external decision model. Nothing here replaces JEV.
>
> - **Decision record:** ADR 0008, proposed. Plan: `docs/prd/AGENTIC-SDLC.md`. Roadmap: `FF-NEW:agentic-sdlc-platform`. Feature: `HUB-NEW:agentic-sdlc-platform`.
> - **Related:** #719 (the Studio: A1 and A3 read its model and add to its views), #484 (local runner: the action runs the same code locally), #632 (harness protocol), #687 (expedite sprints), ADR 0002, ADR 0004, ADR 0007.
> - **Guardrails for every phase:** fail closed; shadow first; PR-only, never merges; every call site capped in `budget.call_sites`; kill switch and declared cron; thresholds and promotions are gated PRs; hands off the Mac; prior art recorded per phase (§ 10.8).
>
> **Phases (sub-issues, in order)**
>
> - [ ] A0 — Evaluation spike and the decision record
> - [ ] A1 — Cost levers as atlas standards, fleet-wide
> - [ ] A2 — The typed-decision node: lockfile, composite action, first decisions in shadow
> - [ ] A3 — Telemetry: decision traces and CI quality signals in the lake, Studio panels, alerts
> - [ ] A4 — Harness pre-classification and the patch screen
> - [ ] A5 — The trim loop in shadow: test selection and matrix pruning
> - [ ] A6 — The verify loop, the fitness gate and the first promotion

### A0 — Evaluation spike and the decision record

Labels: `ci`, `governance`, `P1`, `size:m`, `agent:hold`, `needs-amr`.

> **Scope.** Accept or reject ADR 0008 with numbers. Build the eval set under `tools/jev/evals/decisions/`: about 20 real past hub PRs labelled by change class and sensitive-path by hand, and about 20 past failed runs labelled flaky, real, infra, quota or cancelled from the lake. Score TypeSafe Jev through its SDK and `claude -p` with a JSON schema on the same set, offline, from the maintainer's machine or the devenv, at $0 on the Actions meter. Answer where the model runs (hosted API versus any local counterpart) and what that does to latency and cost per decision. Record the needs assessment, the prior-art lines and the build-versus-adopt call in the ADR if the spike changes them.
> **Acceptance.** A one-page result in the PR (accuracy per decision, P50 latency, cost per decision for both executors); the eval set committed with its labels; the ADR's status decided by the maintainer's merge; a go or no-go for A2 written into this issue. The decision model's key, if adopted, named in `fleet.yml` `tokens:` and `token-rotation.yml` `env:` in the A2 PR, never here.
> **Guardrails.** No workflow changes. No key in `_data/`. API-equivalent (estimate) on every cost figure. § 12.3 gated: this PR adds an ADR.

### A1 — Cost levers as atlas standards, fleet-wide

Labels: `ci`, `optimization`, `P1`, `size:m`, `agent:hold`.

> **Scope.** Five new atlas rules at `warn`, each naming its incident from the 2026-09 audit or the 2026-11-05 review: `cancel-in-progress` (a PR or push workflow with a concurrency group that does not cancel superseded runs), `path-filter` (a push or PR workflow with no `paths:` and no in-job change detection), `macos-isolated` (a macOS leg not behind a path filter or a `platform-relevant` decision), `cache-measured` (a `setup-*` or `actions/cache` step whose hit rate the lake cannot see), `job-consolidation` (three or more sequential jobs under two minutes each with no fan-out). `actions_analytics` adds minutes by OS and cache hit rate to `_data/actions_usage.yml`, additive keys. `tools/dash workflows cost` lists the top ten levers fleet-wide over the Studio's `fleet-workflows/v1` model (`hub_rules=False` where a rule is hub-only). The hub's 36 workflows at zero warnings from these rules.
> **Acceptance.** `test_workflow_atlas.py` holds the hub at zero errors and the new rules at zero false positives on its files; the fleet-pulse digest carries the top levers; `docs/WORKFLOW-ATLAS.md` rule table updated; one `fanout.yml` dry run shows what the rules would change in three fleet repositories, no PR opened.
> **Guardrails.** No model, no new call site. Minutes from the billing meter only. No PR-side read of the fleet. Rules land at `warn`; promotion to `error` is a later, cited change.

### A2 — The typed-decision node: lockfile, composite action, first decisions in shadow

Labels: `ci`, `feature`, `P1`, `size:l`, `agent:hold`, `needs-amr`.

> **Scope.** `_data/decisions.yml` (`schema: decisions/v1`) with `change-class`, `sensitive-path`, `affected-suites`, `platform-relevant`, `failure-class`, `safe-to-auto-fix`, their thresholds (0.85 skip-class, 0.95 gate-class) and conservative branches. `tools/jev/decisions.py`: `ask` (both executors, trace written, ledger row), `lock` (fingerprints), `lint` (every consumer names an id, every id has a threshold and a conservative branch). `.github/actions/typed-decision/` over `decisions ask`, no GitHub token, outputs `answer`, `confidence`, `cleared`, `trace`; a model error or 429 is `cleared=false` on the conservative branch, never a failed step. `change-class` and `sensitive-path` in `standard-ci.yml` in shadow: recorded, nothing skipped, the shell docs-paths test still decides. The call sites in `budget.call_sites`; the key in `fleet.yml` `tokens:` and `token-rotation.yml` `env:`, hub-first. Atlas rule `decision-threshold`. `fleet.yml` `decisions.executor` and `decisions.promoted: []`. `test_decisions.py`, `test_ai_budget.py` extended, the action's README and `docs/JEV.md` section.
> **Acceptance.** 14 days of hub traces where `change-class` agrees with the docs-paths test on every PR; zero failed steps attributable to the model; `tools/dash loop run` produces a byte-identical trace format locally (ADR 0002); drift check green including check (l) on the new action.
> **Guardrails.** Shadow only: no decision changes what runs in this phase. Threshold edits are gated. § 12.3 gated: the token contract changes.

### A3 — Telemetry: decision traces and CI quality signals in the lake, Studio panels, alerts

Labels: `ci`, `feature`, `data`, `P1`, `size:l`, `agent:hold`.

> **Scope.** Lake tables `decisions` (one row per trace, `outcome` nullable until A6) and per-job `queue_ms`, `cache_hit`, shipped by `dash lake sync`. `actions_analytics` adds flake rate and time-to-green per workflow, additive keys. `python3 -m tools.jev decisions replay --since 7d` with the fingerprint refusal and `--compare`. Studio panels (ADR 0007 S2 views, `tools/fleetcore/`): minutes by repo and OS, cache hit rate, P50/P95 job duration, flake rate, decision confidence distribution, missed-failure count, agent PR acceptance rate. The four alerts as fleet-pulse digest rows: spend above budget, confidence distribution drifting down week over week, any missed failure, any agent PR with `sensitive-path` yes. MCP read tool `fleet_decisions`.
> **Acceptance.** Every panel reads the lake and nothing reads GitHub on a PR; a week's replay returns identical answers under an unchanged fingerprint and a diff under a changed one; `test_pages.py` and `test_fleetcore_mcp.py` extended; evidence bundle for the panels under `test/evidence/decision-panels/`.
> **Guardrails.** Read-only surfaces. Fleet reads on a schedule only. Lake sync stays manual until its own decision.

### A4 — Harness pre-classification and the patch screen

Labels: `ci`, `feature`, `fleet-doctor`, `P1`, `size:l`, `agent:hold`, `needs-amr`.

> **Scope.** `failure-class` and `safe-to-auto-fix` asked in `fleet-pulse.yml` before the doctor job and in `issue-pipeline.yml` before tier 2; below the bar the loop files an issue through `upsert-issue` and spends no agent turn; above it the agent runs with its existing allowlist and cap. A patch screen at the 0.70 confidence floor over correctness, security, reliability, compatibility and test gaps: adopt a maintained screening action if one exists at phase start, else `decisions screen` over `claude -p` with a schema; emits annotations and a JSON report, never prose; runs as a check on agent PRs and on human PRs alike. Trace routing on every agent run (auto-close, human review, bug, escalate) recorded on the run and in the lake. The GitHub App installation-token question put to the maintainer as a yes/no in this issue; `FLEET_TOKEN` stays until answered.
> **Acceptance.** A month of doctor runs where every agent turn followed a cleared classification; the screen's findings on A0's failure set match the recorded outcomes at or above 0.70; `test_fleet_pulse_doctor.py` and `test_ai_budget.py` extended; `docs/DAILY-ANALYSIS.md` and `docs/ISSUE-PIPELINE.md` say what changed.
> **Guardrails.** Agents keep `contents: write` to a bot branch and `pull-requests: write`, nothing else. Never merges. The screen is advisory on human PRs until the maintainer makes it required. § 12.3 gated: loop and budget changes.

### A5 — The trim loop in shadow: test selection and matrix pruning

Labels: `ci`, `optimization`, `P2`, `size:l`, `agent:hold`.

> **Scope.** `affected-suites` and `platform-relevant` wired into `standard-ci.yml` and the matrix callers. A selector per suite runner: pytest and `unittest` first (the hub's own suites, through `tools/run-all-tests.sh`), then Vitest (the console) and Jest (fleet repos); PruneTest or a deterministic selector adopted where it fits, with one line of fit in the PR. Shadow mode everywhere: the trimmed selection and the pruned matrix are recorded on every run beside what actually ran, and the full suite still runs. `decisions.promoted:` stays empty.
> **Acceptance.** 14 nightly windows of hub shadow data in the lake; a report (`tools/dash workflows trim-report`) of what would have been skipped, what minutes it would have saved by OS, and whether anything skipped failed; zero missed failures on the hub in the window or the report says why.
> **Guardrails.** Nothing skipped in this phase. Any selector runs fail-open into "run everything". The hub first; no fleet repository until A6.

### A6 — The verify loop, the fitness gate and the first promotion

Labels: `ci`, `feature`, `P2`, `size:xl`, `agent:hold`, `needs-amr`.

> **Scope.** `.github/workflows/decision-verify.yml`: scheduled (declared in `fleet.yml`, not on the hour), `vars.DECISION_VERIFY_ENABLED`, concurrency group, least privilege, `publish-data` for its one PR; runs every promoted repository's full suites unpruned through the existing reusable workflows, joins results to the day's traces, fills `outcome` on each trace, converts each missed failure with `trace-to-case` into the decision's eval set, runs `fuzz` on every lockfile entry, and opens one PR with the threshold raises (+0.02 per miss or unstable decision) and demotions the data justifies. The fitness numbers (minutes by OS before and after, flake rate, missed failures) on every optimization PR body and Studio row. The weekly replay review as a digest row; the quarterly re-pin of the model release as a `token-rotation.yml` sibling task. The thin caller kit (`decisions` inputs on the reusable workflows) fanned out by `fanout.yml`, dry run then PR-only. The hub promoted first by a gated PR citing its 14-day window; one fleet repository after it.
> **Acceptance.** The hub runs trimmed on PRs with the nightly backstop green for 14 days and zero missed failures; one fleet repository promoted the same way; minutes by OS down against the A1 baseline on the billing meter; `test_schedule.py`, `test_ai_budget.py`, `test_workflow_atlas.py` green; `docs/AGENTIC-SDLC.md` written as the operator doc and this plan marked shipped.
> **Guardrails.** The loop never merges and never touches settings. Promotion and demotion are gated PRs. A missed failure demotes before anything else happens. Kill switch defaults on (`!= 'false'`).

## 8. Open questions (from the note, with the hub's starting answers)

- **Where does the decision model run?** A0 answers it with latency and cost. The starting answer is the hosted API from a hosted runner, with `claude -p` as the fallback executor; a self-hosted runner on a public repository is already ruled out (#484).
- **What confidence floors?** 0.85 for skipping, 0.95 for gating, as the note proposes; A6 moves them from missed-failure data only.
- **How much of the harness should be typed questions rather than free-form reasoning?** The classification in front of the agent and the screen behind it are typed from A4; the proposal in between stays free-form under its allowlist and cap. Whether the proposal itself can be decomposed into typed steps is ADR 0004 P1's question and is not answered here.
- **Jest.** The note assumes one Jest suite. The hub's suites are Python; A5 starts there and reaches Jest through the fleet kit.

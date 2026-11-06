# ADR 0008 — GitHub Actions as the agentic SDLC substrate: typed decisions gate risk, telemetry scores efficiency, tests gate correctness

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/745 (merged 2026-11-06 by @bamr87)
- **Date**: 2026-11-06
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-06: "build a plan, roadmap, and epic to implement this", with the design note *GitHub Actions as an Agentic SDLC Platform — Design with Jev*); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: constitution § 10.8 (prior art first), § 11 (write-back), § 12 (merge authority), § 13 (eval baseline and risk tiers), § 17 (loop switches), [ADR 0002](0002-agent-step-specs-and-local-runner.md), [ADR 0004](0004-recursive-harness-refinement.md), [ADR 0007](0007-workflow-studio.md), [docs/prd/AGENTIC-SDLC.md](../prd/AGENTIC-SDLC.md), [docs/WORKFLOW-ATLAS.md](../WORKFLOW-ATLAS.md), [docs/WORKFLOW-OPTIMIZATION.md](../WORKFLOW-OPTIMIZATION.md), [docs/JEV.md](../JEV.md)
- **Tracking**: #737

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### The design note

The maintainer's design note treats GitHub Actions as the execution substrate of the whole software development life cycle, not a CI tool, and proposes four layers: a substrate of reusable workflows with strict contracts, a telemetry layer that is the ground truth for cost and quality, a constrained agent harness that proposes and never merges, and an optimization layer where a decision model trims work per pull request while a nightly backstop and a fuzzer check that the trimming is safe. Its principle is the one this ADR adopts: **tests gate correctness, telemetry scores efficiency, typed decisions gate risk, and agents only move in the direction all three allow.**

The decision model it names is TypeSafe AI's **Jev**, a decision-only model released on 2026-09-15 that answers typed questions (Choice, Score, and a yes/no called Noul) with a calibrated probability rather than prose. That shape is what makes it usable as a gate: every answer is machine-checkable against a threshold, and a workflow can fail closed when the answer is not confident enough.

### Two things the hub must settle before building

**The name.** The hub already has `tools/jev/`, its own agent logic engine (numbering at merge, conflict triage, loop step specs, harness refinement; [docs/JEV.md](../JEV.md)). It is unrelated to TypeSafe's model. This ADR and everything that follows it call the external model **TypeSafe Jev** or simply **the decision model**, and the hub's engine **JEV** as before. A typed-decision node is a capability JEV gains, not a replacement for it.

**The ecosystem.** The note names four pieces around the model: a GitHub Action that sends a typed request and exposes the JSON answer, a workflow CLI with decision lockfiles, a flight recorder, replay and fuzzing, a patch-screening review action with a 0.70 confidence floor, and a test selector called Leanest. Only the model and its Python SDK were verifiable on 2026-11-06; the four pieces were not found. The plan treats each as a *capability to obtain*, by adopting a tool if one exists when the phase starts or by writing the thin piece in `tools/jev/` if it does not, and a phase records which it did.

### What the hub already has, layer by layer

| Layer in the note | Already in the hub | Missing |
| --- | --- | --- |
| 1 Substrate | Seven reusable workflows (`standard-ci`, `ai-lane`, `fleet-verify`, `fleet-conformance`, `spec-gate`, `site-quality`, `release-please`) versioned by major tag, six composite actions, least-privilege `permissions:`, kill switches (§ 17), `_data/fleet.yml` as the contract, the atlas's 17 lint rules | A decision node with a confidence threshold, a decision lockfile, and the cost-lever rules (cancel-in-progress, path filters, isolated macOS legs, measured cache hit rate) as standards |
| 2 Telemetry | `_data/actions_usage.yml` from the billing meter daily, the lake's run history, the OTel plane (Phoenix, Prometheus, Grafana), the Studio's sync (ADR 0007 S1) | Cache hit rate, queue time, flake rate, time-to-green, decision traces beside cost, replay |
| 3 Harness | The doctor, the issue pipeline, the scout and evolution loops, all PR-only and never merging; ADR 0002's local runner; § 11 write-back; § 13 risk tiers; the review gate (§ 12) | A typed pre-classification before the heavy agent runs (flaky or real, safe to auto-fix), a confidence-thresholded patch screen applied to agent and human PRs alike, trace routing |
| 4 Optimization | Nothing | Test selection, matrix pruning, the nightly backstop that converts a missed failure into a regression case, the fuzzer, and the fitness function |

### Prior art survey (§ 10.8)

- **TypeSafe Jev.** Fit: the only model found that answers typed questions with a calibrated probability in one call, which is the primitive a gate needs. Limits: hosted API only as far as was verified, a new vendor and a new credential, and no proof yet on this fleet's diffs.
- **A Claude call constrained to JSON through `claude -p` and a schema.** Fit: already wired (`dash ai run`, § 13 caps, the ledger). Limits: a sampled answer is not a calibrated probability, so a threshold on it is a convention, not a measurement; cost per decision is one to two orders higher.
- **PruneTest (GitHub Action).** Fit: semantic test selection with a shadow mode, fail-open layers and a composite action. Limits: embeddings and GBDT need a training window per repository; untested against Python suites run from `unittest`.
- **FineRTS, Ekstazi, STARTS and pytest-testmon.** Fit: regression test selection by static or coverage analysis, deterministic and free. Limits: language-bound, and testmon needs a committed coverage database per repository.
- **actionlint, zizmor, the atlas.** Fit: the cost levers (concurrency, path filters, caching, timeouts) are static rules, and the atlas already runs this kind of rule with a named incident behind each. Limits: none for layer 1; this is the right home.
- **GitHub's `concurrency.cancel-in-progress`, `paths:` filters and `actions/cache`.** Fit: the first three cost levers are platform primitives. Limits: `paths-ignore` cannot be used on a required check, which `standard-ci.yml` already works around with a docs-paths decision.
- **Datadog CI Visibility, Honeycomb build events, Blacksmith.** Declined in ADR 0007 for the same reasons: run status is the smallest part of the need, and the hub has its own OTel plane.

**Build versus adopt.** Adopt TypeSafe Jev as the decision model behind one thin composite action, after an offline evaluation on this fleet's own history proves its accuracy and latency; keep `claude -p` as the fallback executor so the gate works with the model switched off. Adopt the platform primitives and the atlas for every cost lever. Run a test selector in shadow mode first, PruneTest or a deterministic selector, and promote nothing until the nightly backstop reports zero missed failures. Build the decision lockfile, the flight recorder, replay and fuzzing in `tools/jev/` only if no maintained tool provides them when their phase starts.

## Decision

1. **Typed decisions are a JEV capability.** A decision has a question type, a declared option set or rubric, a confidence threshold and a conservative branch, and lives in a lockfile `_data/decisions.yml` (`schema: decisions/v1`). A workflow consumes a decision only through the `typed-decision` composite action, which returns the answer, its confidence and whether it cleared the threshold, and takes the conservative branch itself when it did not or when the model could not be reached. The action never acts; the workflow decides.

2. **Below the bar, the pipeline runs everything.** Every decision fails closed. The starting thresholds are 0.85 for anything that skips work (test selection, matrix pruning) and 0.95 for anything that raises or lowers a gate (sensitive paths, safe-to-auto-fix), as the note proposes; they move only from missed-failure data, never by hand in a workflow.

3. **Every decision leaves a trace.** One JSON record per decision, holding the policy fingerprint, model version, inputs, usage and the full typed answer, shipped to the lake beside run cost, with the ledger counting its spend as API-equivalent (estimate). A trace can be replayed against the current lockfile; replay refuses a different workflow fingerprint unless told to compare.

4. **The cost levers are standards, held by the atlas.** New rules, each landing at `warn` and each naming its incident: `cancel-in-progress`, `path-filter`, `macos-isolated`, `cache-measured`, `job-consolidation`. The billing meter stays the only source of minutes (standing rule).

5. **The harness pre-classifies before it spends.** The doctor and the issue pipeline ask typed questions first (failure category, severity, safe to auto-fix) and run the heavy agent only when the answers clear their thresholds; otherwise they open an issue for a person. Agent PRs are screened by the same patch screen, at the same 0.70 floor, as human PRs. Branch protection, required checks and the § 12 gate stay the guardrails; nothing in a prompt is one.

6. **Trimming is earned, never assumed.** Test selection and matrix pruning start in shadow mode, where the decision is recorded and the full suite still runs. A trim is promoted per repository only after the nightly backstop has reported zero missed failures across a window the plan fixes, and a proposed optimization survives only if minutes drop and the missed-failure count stays at zero. Any missed failure demotes the repository to shadow and raises the threshold.

7. **Agents keep the permissions they have.** `contents: write` to a bot branch, `pull-requests: write`, nothing else, through the existing token contract (`FLEET_TOKEN`, probed with `gh api user`); a GitHub App with installation tokens is a maintainer decision recorded in its own phase, not assumed here.

8. **No new repository.** The note's `org/.github`, `org/ci-metrics` and `org/ci-agent` are the hub's `.github/`, `_data/` plus the lake, and `tools/jev/` respectively; `bamr87` is a personal account with no organization, and the fleet's standing rule is one hub.

## Delivery

The phases are the epic's sub-issues, in [docs/prd/AGENTIC-SDLC.md § 6](../prd/AGENTIC-SDLC.md#6-roadmap-and-phases). A0 is the evaluation spike that can still reject the model; A1 needs no model at all.

## Consequences

**Positive**

- Every skip, retry and auto-fix in the pipeline is a recorded, thresholded answer that can be replayed, so an incident has a trace instead of a guess.
- Minutes are recovered where they are spent (per-PR test and matrix legs) without giving up the nightly full suite as the backstop.
- The fleet gains one more primitive that the console, the CLI and the MCP server share, in the place (`tools/jev/`) the fleet already looks for agent logic.

**Negative**

- A new vendor and credential in the token contract, with per-decision cost that the ledger must count.
- Shadow mode means the first weeks save nothing; the saving only comes once trims are promoted.
- Two things called Jev in the same documentation until every reader knows the convention.

**Risks**

- The ecosystem pieces may not exist; each phase records what it adopted or built, and A0 can end the plan at the ADR.
- A calibrated probability on one distribution is not calibrated on another; the eval set (§ 13.1) is this fleet's own history, and thresholds move only from its misses.
- A trim that silently drops a test is the worst outcome; decision 6 is why promotion is per repository and reversible.

## Alternatives considered

- **Keep deterministic filters only (paths, concurrency, cache).** Free and already standard, and A1 ships them regardless; but they cannot answer "which tests can this diff affect", which is where the minutes are.
- **Use Claude for every gate decision.** Already wired, but a sampled answer carries no calibrated confidence and costs far more per decision; it stays the fallback executor.
- **Adopt a CI observability vendor for layer 2.** Declined in ADR 0007; the hub's lake and OTel plane already hold the data, and decision traces must sit beside it.
- **Do nothing.** Actions cost is $0 net on the billing meter today, so the money case is weak; the case is the one the note makes, that gating by typed, replayable decisions is what lets agents move at all without a person reading every run.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none

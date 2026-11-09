# ADR 0009 — The agentic efficacy model: one agent inventory, five KPIs per kind of agent, and checks that run in shadow before they gate

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/781 (merged 2026-11-09 by @bamr87)
- **Date**: 2026-11-07
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-07, epic #773, phase E0 #774 approved the same day); the maintainer accepts or rejects it by merging the PR that adds it, which also ratifies amendment `agentic-efficacy-contract`
- **Related**: constitution § 29 (the contract this ADR's model serves), § 10.7 (honest cost), § 10.8 (prior art first), § 10.9 (local first), § 12.3 (gated changes), § 13 (eval baseline and risk tiers), § 17 (loop switches); [ADR 0002](0002-agent-step-specs-and-local-runner.md) (step specs and the local runner), [ADR 0004](0004-recursive-harness-refinement.md) (Harness² and the reflector), [ADR 0008](0008-typed-decisions-as-pipeline-gates.md) (telemetry scores efficiency); [docs/AGENT-EFFICACY.md](../AGENT-EFFICACY.md), [docs/HARNESS.md](../HARNESS.md), [docs/HARNESS-OPS.md](../HARNESS-OPS.md), [docs/JEV.md](../JEV.md)
- **Tracking**: #773

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

The maintainer asked on 2026-11-07 for agent efficacy to become part of the health checks, with "major governance and upgraded functionality". The review that day (epic #773) found three needs:

1. **Know every agent.** Agents are defined in five places: the workflows, the JEV step specs, `_data/fleet.yml` `jev:`, the `tools/install-*.sh` installers and, soon, the reflector's schedule. Only the first was inventoried (`_data/harness_registry.yml`), and only for `claude-code-action` call sites, so the hub's own `ai-lane.yml` (a `claude-run` call site) was invisible.
2. **Measure what an agent achieved, not only what it spent.** The hub counts runs, minutes and dollars, and judges the fleet's CI as a whole (`harness_health`'s completion and effectiveness). It never asks whether an agent's output was accepted. A conflict tier that resolved 0 of 5 conflicts for $2.27, and 13 false attention items out of 20, were found by a person reading logs.
3. **Trust the inputs.** The numbers the checks read were wrong in ways no check noticed: the hub missing from the Actions analytics, $0 and 0 turns for the hub's own loops in the lake, a 17-day-old `_data/conformance.yml` with no writer. A single global staleness threshold (`stale_data_days`) cannot say which input an agent depends on, or who should have refreshed it.

### Prior art survey (§ 10.8)

- **Barbaste et al., "Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents — A Source-Code Study of Eleven Systems"** (arXiv:2609.00006). It analyzes eleven production coding harnesses, including Claude Code, Codex CLI and OpenHands, and finds that they have grown from tools into platforms with recurring subsystems. ADR 0004 already adopted its surface rules. Fit: it says where a run record can be taken from (the runtime's events and hooks) and that policy belongs in data, not prose, which is what `harness.efficacy` is. Limits: it is a study of how harnesses are built, not of how well they do their work, so it gives no efficacy metric.
- **Xu et al., "Harness²: Recursive Agent Harnessing for an Open World"** (arXiv:2610.14224, google-research/harness2, Apache-2.0). The hub adopted the method in ADR 0004, and its reflector (PR #772) is this contract's rule 5. Fit: selection is blind and made over deliverables, and the reflector records per-edit verdicts, so outcomes are judged rather than process; the same stance gives "accepted outcomes" here. Limits: its tasks have a benchmark grader. The fleet's grader is a person merging, closing or reverting, which is slower and has to be read back from GitHub.
- **Kapoor, Stroebl, Siegel, Nadgir and Narayanan, "AI Agents That Matter"** (arXiv:2407.01502). Agent evaluations should treat cost as a metric beside accuracy and optimize for both. Fit: accepted outcomes per dollar and per Actions minute are that joint metric. Limits: written for benchmark comparisons; here the denominator is the fleet's own spend, labelled API-equivalent (estimate) (§ 10.7).
- **Yao, Shinn, Razavi and Narasimhan, "τ-bench"** (arXiv:2406.12045). Its pass^k metric measures how reliably an agent succeeds across repeated trials. Fit: a scheduled agent repeats similar work every day, so its false-signal and silent-failure rates are the production view of that reliability. pass^k itself belongs to the § 13.1 eval sets, where a task can be rerun. Limits: production never reruns the same task, so the KPIs here use rates, not pass^k.
- **Anthropic, "Demystifying evals for AI agents"** (Anthropic engineering, 2026-01-09). Grade what the agent produced, not the path it took; keep capability and regression evals apart; read the transcripts; production monitoring catches what synthetic evals miss, but it lacks ground truth and should sit beside evals, not replace them. Fit: these KPIs are production monitoring, and the maintainer's accept or reject is its ground truth. § 13.1's eval sets stay the regression suite, and the transcripts reach the reflector (rule 5). Limits: written for teams that build evals; it does not set thresholds.
- **Google, *The Site Reliability Workbook*, chapter 13, "Data Processing Pipelines"** (sre.google/workbook/data-processing). It defines data freshness as an SLO for a pipeline. Fit: rule 4's per-source writer and freshness SLO, in place of one global stale-data threshold. Limits: none for this use.
- **The DORA delivery metrics** that § 27.7 already reports. Fit: time to outcome is lead time for an agent's change, and the false-signal rate is the change failure rate of its output. Limits: built for teams, not single agents, and § 27 uses them as a guide, never a target; the same caution applies here.
- **What the hub already has.** `harness_health` (six layers, six trip wires), `harness_registry` (the fleet's AI workflows), `ai_usage.yml` and the lake (CI agent runs), the AI ledger's run records (local runs, the run-record schema in `.github/scripts/dash-gen/README.md`), `_data/jev_resolutions.yml`, the § 13.1 eval sets, Phoenix traces. Fit: these are the inputs, and the inventory reads them rather than replacing any. Limits: three run-record stores with three shapes, none of which has the contract's full schema (see decision 4).
- **Hosted agent-observability and eval platforms.** Fit: per-run traces, evaluators and dashboards. Limits: ADR 0007 already declined a CI observability vendor, and the hub runs Phoenix locally. What is missing here is not a dashboard. It is the join from a run to what a person later did with its output, which sits in GitHub and the hub's own ledgers.

**Build versus adopt.** Adopt the metric definitions (cost beside accuracy, outcomes over paths, freshness SLOs, rates as the production view of reliability). Build the inventory, the contract's data and the check in the hub's generator layer: they must read the hub's own files offline on every pull request, and they are small. Keep Phoenix and the lake as they are. The model-backed reflector stays ADR 0004's.

## Decision

1. **One inventory, a file of its own.** `_data/agents.yml` (`schema: agents/v1`) holds every agent. It is generated offline by `tools/dash agents` (`.github/scripts/dash-gen/agent_inventory.py`) from the hub's workflows, the JEV step specs (through `tools/jev/spec.py`), `_data/fleet.yml` `jev:`, the `tools/install-*.sh` installers that install a LaunchAgent, and, for the fleet, the committed `_data/harness_registry.yml`. It is not a block in `harness_registry.yml`, for four reasons. That file is a consumed interface for GitFactory's Fleet Studio, and the inventory should not put that contract at risk. It is written by a live GitHub scan, while the inventory must be rebuilt offline on every pull request (no PR check reads the fleet). Most agents (step specs, tiers, installers) are hub facts the scan never sees. And one file with two writers is the drift class this ADR exists to remove. The inventory reads the harness registry; it does not duplicate it.

2. **Efficacy has five KPIs, defined per kind.** The kinds are `ci-scheduled`, `ci-event` and `ci-mention` (CI agent steps), `loop-step`, `jev-tier` and `local-job`.

   | KPI | Definition | Better |
   | --- | --- | --- |
   | `accepted_per_usd` | accepted outcomes per USD, API-equivalent (estimate) | higher |
   | `accepted_per_actions_min` | accepted outcomes per billed Actions minute (the billing meter, never wall clock) | higher |
   | `time_to_outcome_h` | median hours from the trigger to the accepted outcome | lower |
   | `false_signal_pct` | share of outputs a person rejected as wrong: closed as not planned, reverted, or marked false | lower |
   | `silent_failure_pct` | share of runs that ended as success but left no outcome, no run record, or a cost read as $0 | lower |

   An **accepted outcome** is what a person kept: a merged pull request (the doctor, the pipeline, evolution, a fan-out fill), an issue left open or fixed rather than closed as not planned (scout), a conflict resolution whose pull request merged without the resolution being reverted (a JEV tier), a reply or pull request the asker accepted (a mention handler), or a lesson filed into the library (the reflector). A KPI over a zero denominator is not applicable. A $0 tier has no per-dollar figure, and a local run has no Actions minutes. A threshold of `null` means measured, not judged.

3. **Thresholds are provisional and gated.** `_data/fleet.yml` `harness.efficacy.kinds` sets starting values from the 2026-11-07 review and the caps already in `budget:` (for example, one accepted outcome per $20 for a scheduled CI agent, and at most 5% silent failures for every kind). E3 (#777) measures them in shadow, and a gated pull request retunes them from that data, never from one bad week.

4. **One run-record schema.** The fields are `cost_usd`, `cost_source`, `turns`, `model`, `outcome`, `permission_denials` and `tool_errors`. Three stores hold run records today, and `harness.efficacy.run_record.stores` declares what each one lacks: the lake's `agent_runs` (CI) lacks `cost_source` and `tool_errors`, the AI ledger's `runs` (local) lacks `permission_denials` and `tool_errors`, and the JEV ledger lacks `turns`, `permission_denials` and `tool_errors`. E1 (#775) converges them. The inventory reports each agent's gap until then.

5. **Every source has a writer and an SLO.** `harness.sources` declares each source an agent reads, with its writer and either `slo_days` or `slo: on-change` (configuration a reviewed PR changes) or `slo: live` (read at run time). A loop step's sources include its context pack's providers, read from its spec. `conformance` is declared with `writer: null`, the defect the review found, and the lake's writer is the harness-review job from PR #772, flagged pending until it is installed.

6. **The check gates registration and warns on the rest, until enforcement.** Drift check (p) runs `tools/dash agents --check` on every pull request. It fails on an agent the hub's files define but the committed inventory lacks, on a removed or changed hub agent, and on a contract section not regenerated. Drift in the fleet half warns, because no hub PR causes it; the daily `--ci` run fails on it (`--strict-fleet`), and `fleet-pulse.yml` rewrites both files in one commit. Contract gaps warn while `harness.efficacy.enforce` is false. A gated PR sets it true no earlier than `shadow_until` (2026-11-21), and the check refuses it before then. Agents first seen before that date keep a grace period until `grace_until` (2027-02-01).

7. **What this does not do.** It makes no model call and changes nothing on the Mac. It neither pauses nor tunes an agent (that is E5, #779, through § 11). It computes no KPI value yet (E3), and it adds no `harness_health` layer or trip wire (E2, #776).

## Consequences

**Positive**

- One place answers "which agents run, who owns them, what may they spend, what are they for, and what do they read": 71 agents on 2026-11-07, every one with its KPIs named.
- An agent added in a pull request is caught by the drift gate, with its exact fix (`tools/dash agents`).
- The gaps are a measured work list (R1–R6 counts in `totals.gaps_by_rule`) for E1–E5, so each phase can show what it closed.
- A source with no writer is now a named defect in the gate's output, not a stale file found by chance.

**Negative**

- A second generated inventory beside `harness_registry.yml`, and one more file a pull request regenerates when it adds an agent.
- Thresholds set before any measurement can be wrong in both directions. The shadow period and the gated retune are the mitigation.
- Some facts (an installer's model, a job's sources) are declared by hand in `harness.agents`, and a declaration can be wrong. The generator cross-checks what it can: references resolve from `_data/fleet.yml`, sources must exist, and a declared agent whose installer lands is reported.

**Risks**

- An "accepted outcome" read from GitHub can be gamed by an agent that only opens what is sure to be merged. The false-signal rate and a person's review (§ 12) keep that visible, and an agent never changes its own thresholds (§ 13.9).
- If `fleet-pulse.yml`'s inventory step fails, the fleet half lags the harness registry until the next run. The gate warns on each PR and fails the daily scheduled check, so the lag is loud, not silent.

## Alternatives considered

- **An additive `agents:` block in `_data/harness_registry.yml`.** Smallest diff, but it would put a PR-time offline writer and a daily live writer on one consumed interface, and the scan cannot see step specs, tiers or installers (decision 1).
- **Declare every agent by hand in `_data/fleet.yml`.** Simple, and it rots: nothing would notice a new workflow or installer. Generation from the defining files is what lets the gate fail a PR that adds an unregistered agent.
- **Score agents with an LLM judge.** Rejected, as docs/HARNESS.md already does for gates: the maintainer's merge, close or revert is the ground truth, and it costs nothing to read.
- **Enforce from day one.** It would turn 64 agents' known gaps into 64 failures on every pull request, none of them caused by that PR. Shadow, then grace, is the epic's guardrail and the pattern of `jev.numbering.enforce`.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none

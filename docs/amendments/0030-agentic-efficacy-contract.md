# 0030 — Every AI agent is registered, measured and held to declared efficacy

- **Status:** ratified
- **Number:** 0030
- **Date:** 2026-11-07
- **Proposed by:** agent, at the maintainer's request (2026-11-07: "This all needs to be part of the health checks. add roadmap and backlog item for AI agentic harness and workflow efficacy and management. need major governance and upgraded functionality."; E0 of epic bamr87/bamr87#773 approved the same day)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/781 (merged 2026-11-09 by @bamr87)
- **Affects:** constitution § 29 (new; follows § 28 `grok-claude-governance` in PR #695 and §§ 25–26 in PRs #685 and #686, all open — renumber to the next free section if any of them does not merge first); § 10.7, § 10.9, § 13 and § 17 by reference; `_data/fleet.yml` `harness.efficacy`, `harness.sources`, `harness.agents`; `_data/agents.yml` (new, `schema: agents/v1`); drift check (p); AGENTS.md standing rules; feature `HUB-092`; requirements `FR92`, `NFR19`
- **Supersedes:** none
- **Related:** ADR 0009 `docs/adr/0009-agentic-efficacy-model.md` (the efficacy model), ADR 0004 (Harness², the reflector), ADR 0008, amendment `local-first-ai` (§ 10.9), epic bamr87/bamr87#773 and its phase bamr87/bamr87#774, the roadmap entry `agentic-harness-efficacy` (PR #780, numbered when it merges), `docs/AGENT-EFFICACY.md` (paths, not links: this record moves to `docs/amendments/` when it is numbered)

## Context

The fleet runs about seventy agents: 60 AI workflows across 36 repos, 5 local loop steps, 3 conflict tiers and 3 scheduled jobs on the Mac. No rule said what an agent must report, what it must achieve, or who keeps its inputs fresh, and the console review and the five CI deep dives of 2026-11-07 (epic #773) found what that costs:

- **Wrong numbers, unnoticed.** The Actions analytics left out the hub (about two thirds of November's minutes) and came out 2–4× low for every repo measured; the hub's own CI loops read $0 and 0 turns in the lake (#771); the AI usage collector seems to double-count hub loop runs; `_data/conformance.yml` has no writer and was 17 days old.
- **Silent failures.** The JEV local conflict tier could never edit a file and resolved 0 of 5 conflicts for $2.27 (#764); 13 of 20 harness attention items were false (#765); 46% of Verify runs were redundant (#767).
- **Blind spots.** Local sessions are about 99% of AI spend ($2,731 API-equivalent in 7 days, against about $40 for CI agents), and the health checks see none of it; the session import into the lake had no schedule and was 6 days old.
- **No learning.** The experience library was empty until #769, and no reflector existed until PR #772.

`harness_health` has six layers and six trip wires; none of them covers agent efficacy, measurement coverage, per-source freshness or the learning loop. § 13 holds an agent's correctness before a change (its eval set). Nothing holds its efficacy after.

## Amendment

Add to the constitution:

> ## 29. The agentic efficacy contract
>
> "Agent" in this section means a CI agent step, a local loop step, a scheduled local job, or a JEV tier. Every agent:
>
> 1. **Is registered** in one inventory, `_data/agents.yml`, with its owner, trigger, kill switch, budget cap and model. The inventory is generated from the files that define agents (the workflows, the JEV step specs, `_data/fleet.yml` `jev:`, the `tools/install-*.sh` installers), plus `_data/fleet.yml` `harness.agents` for what the code cannot show; drift check (p) fails a pull request that adds an agent without registering it.
> 2. **Writes one run record per model call**, in one schema: its cost and the cost's source, turns, model, outcome, permission denials and tool errors. A run that leaves no record, or reads $0 when its cost is unknown, is a silent failure.
> 3. **Declares its efficacy**: KPIs and their thresholds, per kind of agent, in `_data/fleet.yml` `harness.efficacy` (ADR 0009: accepted outcomes per dollar and per Actions minute, time to outcome, false-signal rate, silent-failure rate). Every dollar figure is API-equivalent (estimate) (§ 10.7).
> 4. **Names the data it reads**: each source declared in `_data/fleet.yml` `harness.sources` with its writer and a freshness SLO. A source with no writer is a defect, and so is a source older than its SLO.
> 5. **Feeds the reflector**: its run records land where the incident reflector (`tools/dash refine reflect`) reads them, so its failures can become lessons in the experience library.
> 6. **Has a local entry point** (§ 10.9), unless it must react inside GitHub (an @claude mention handler); the inventory records the exemption and its reason.
> 7. **Shadow, then grace.** The checks are read-only. For at least 14 days after this section is ratified, and until `harness.efficacy.shadow_until`, a contract gap is a warning. Enforcement starts only when a gated pull request sets `harness.efficacy.enforce: true`. From then on, an agent first registered after the shadow period complies on arrival, and one registered before it keeps its gaps as warnings until `harness.efficacy.grace_until`. Registration itself (item 1) gates from the start.
> 8. **Gated.** The contract's KPIs, thresholds, sources and exemptions change only by a gated change (§ 12.3). An agent never changes its own KPIs, thresholds or exemptions (§ 13.9).

## Consequences

- `_data/agents.yml` (`schema: agents/v1`) is the inventory: generated by `tools/dash agents` (`.github/scripts/dash-gen/agent_inventory.py`), refreshed daily by `fleet-pulse.yml` in the same commit as `_data/harness_registry.yml`, and held current by drift check (p). On 2026-11-07 it holds 71 agents: 60 CI agent steps (10 scheduled, 15 event, 35 mention handlers; the 59 the harness registry finds plus the hub's `ai-lane.yml`, a claude-run call site it does not detect), 5 loop steps, 3 JEV tiers and 3 local jobs (`conflict-sweep`, `workspace-sync`, and `harness-review`, declared ahead of PR #772).
- On the first build, 64 of 71 agents have at least one gap. Every agent has its KPIs (R3: 0). The largest gap is the run record (R2: no store yet carries tool errors). After that come missing caps or models (R1: 53, mostly fleet mention handlers that pass no `--max-budget-usd`), missing local entry points (R6: 17), sources without a writer or whose writer is not installed (R4: 5, `conformance` and the lake), and the harness-review job's own records, which the reflector does not read (R5: 1). These gaps are the work list for E1–E5 (#775–#779), not violations, until enforcement is switched on.
- The shadow period runs to 2026-11-21 (`harness.efficacy.shadow_until`), or 14 days after ratification if that is later; the grace period for the agents registered now runs to 2027-02-01 (`grace_until`). Both are settings in `_data/fleet.yml`, changed by a gated PR.
- The thresholds in `harness.efficacy.kinds` are provisional starting values; E3 (#777) measures them in shadow and a gated PR retunes them.
- AGENTS.md gains the standing rule that points here. The PRD gains `FR92` and `NFR19` through the feature fragment `agent-inventory`.
- Merging the pull request that carries this record ratifies it, and accepts ADR 0009. An agent never merges it.

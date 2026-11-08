# 0026 — Expedite sprints run by agentic loops

- **Status:** ratified (ratification pending — Amr ratifies by merging this PR)
- **Number:** 0026
- **Date:** 2026-11-05
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:** https://github.com/bamr87/bamr87/pull/694 (merged 2026-11-06 by @bamr87)
- **Affects:** constitution § 27 (new; follows § 25 `mcp-lifecycle` #685 and § 26 `claude-code-executes` #686, both open — renumber to the next free section if either does not merge first); § 9, § 10, § 12, § 13, § 17 by reference; feature `HUB-087`; requirement `FR85`; roadmap FF-0042
- **Supersedes:** none
- **Related:** epic #687; backlog #688 (this amendment), #689 (sprint budget + circuit breaker), #690 (DORA metrics), #691 (live sprint record), #692 (bash-365.com pilot); research write-up https://cursor.com/canvas/store-ecae274f-8a58-44f1-9d6f-1810735ef947/c859cd74-6625-43b3-a8fe-c4588a912dcd; Design for Failure (DFF, `CONTRIBUTING.md`)

## Context

Amr's direction: run accelerated, top-priority sprints or pilots (tiger teams, swarming, hackathon-style spikes, a Kanban expedite lane, war rooms, time-boxed pilots) end to end with the fleet's agentic loops facilitating every phase — intake, scoping, build, test, deploy, monitor, retro — in a monitored way.

Today the fleet has P0–P3 labels, `_data/work_queue.yml` order overrides (empty), per-tier caps in the issue pipeline, JEV conflict tiers, per-call and per-engine budgets, kill switches and the review gate, but no expedite class of service, no sprint-level budget or circuit breaker, no delivery (DORA) metrics and no live sprint record.

## Prior art

Per 0008 (needs assessment, survey, build-vs-adopt):

- **Kanban expedite class of service** (D. Anderson): WIP limit 1, may exceed column limits, preempts other work, off-cycle release. Fit: the lane rule (§ 27.1). https://www.solutioneers.co.uk/kanban-classes-of-service/ · https://kanbanzone.com/resources/kanban/classes-of-service/
- **SRE incident management**: named roles, one command post, a live state document, only ops modify the system. Fit: the live record and one writer per repo. https://sre.google/sre-book/managing-incidents/
- **SRE error budget policy**: changes halt when the budget is spent. Fit: the circuit breaker. https://sre.google/workbook/error-budget-policy/
- **Shape Up appetite**: fixed time, variable scope; circuit breaker cancels rather than extends. Fit: § 27.3. https://basecamp.com/shapeup/1.2-chapter-03
- **DORA five metrics**: throughput and instability per app; not a goal. Fit: § 27.7. https://dora.dev/guides/dora-metrics-four-keys/
- **Agentic workflows**: gates between steps, stopping conditions, human checkpoints. Fit: the hub's existing loop shape. https://www.anthropic.com/engineering/building-effective-agents
- **Build-vs-adopt:** adopt issue pipeline T1–T3, JEV tiers, `budget.*`, § 17 switches, § 12 gate, trip wires and the ratchet; build only the lane rule, sprint ceiling, record and DORA projection.

## Amendment

New constitution section:

> ## 27. Expedite sprints run by agentic loops
>
> _(amendment `expedite-sprints`, numbered at merge — see the [amendment log](amendments/README.md); follows § 25 `mcp-lifecycle` (PR #685) and § 26 `claude-code-executes` (PR #686), both open; renumber to the next free section if either does not merge first; extends § 9, § 10, § 12, § 13 and § 17)_
>
> 1. **Expedite class of service** — an *expedite sprint* is an accelerated, top-priority, time-boxed pilot on one item. At most **one** expedite sprint is active fleet-wide (WIP 1); it may preempt other lanes' implement slots, and every lane it preempts is recorded.
> 2. **Three gates, all Amr's** — (a) **declaration**: Amr commits the item to `_data/work_queue.yml` `order:` with its appetite (hours plus an API-equivalent USD estimate); (b) **spec approval**: scope, user stories, Design-for-Failure table and acceptance criteria are approved before build; (c) **merge**: through the § 12 review gate (`needs-amr`). An agent never declares, approves or merges its own sprint.
> 3. **Fixed time, variable scope** — the appetite is a ceiling, not an estimate. At the cap or the end of the time box the sprint stops (circuit breaker): it files what it has as a draft and records the stop; it is never extended automatically.
> 4. **Budgets** — a sprint ceiling sits inside the existing caps (`budget.call_sites`, `budget.loops`, `budget.jev`, the fleet monthly ceiling) and never raises them; JEV starts at tier 0; every figure is labelled API-equivalent (estimate) (§ 10.7).
> 5. **Same gates, no shortcuts** — an expedite sprint skips no required check, eval, review gate, risk tier or kill switch; speed comes from priority and swarming, not from relaxed quality.
> 6. **Kill switch** — every loop a sprint drives honours its switch (§ 17); one sprint-scope switch stops all of them.
> 7. **Live record and metrics** — each sprint keeps a live state record (gates, phase, items, spend vs cap, trip wires) and reports DORA's delivery metrics for the target repo as a guide, never as a target.
> 8. **Retro** — every sprint ends with a retro that routes each failure to the strongest ratchet rung (`docs/HARNESS.md`) and files remaining quality debt as issues before it closes.
> 9. **Scope** — the standard is [`docs/EXPEDITE-SPRINTS.md`](EXPEDITE-SPRINTS.md); the budget, record and metrics tooling are follow-ups (epic #687).

## Design for Failure

| Failure | Behaviour |
| --- | --- |
| Sprint hits its cap mid-attempt | The attempt is discarded (`on_budget_hit: discard`); the sprint stops and files what it has as a draft |
| Gate never answered | The sprint waits; nothing times out to approve |
| Second expedite requested | Refused while one is active; Amr ends or demotes the first |
| Deploy breaks the site | Revert PR (or previous known-good digest, § 21); site-health and trip wires raise attention items |
| Kill switch flipped | Every sprint loop stops at its next check; state stays in labels and the record |
| Cost data unreadable | Charged at the cap (estimated), as JEV does |
| Quality debt from speed | Filed as issues at retro; required gates never relaxed |

## Open questions

- Sprint ceiling default and where it lives (`budget.sprints` in `_data/fleet.yml` proposed, #689).
- Whether to cap expedite sprints per quarter.
- Section number: § 27 assumes #685 and #686 merge first.

## Consequences

- Standard `docs/EXPEDITE-SPRINTS.md`; sub-PRD `docs/prd/EXPEDITE-SPRINTS.md` (US1–US6).
- Feature fragment `features/features.d/expedite-sprints.yml` (`HUB-NEW`, `FR85`); roadmap FF-0042.
- Follow-ups: #689, #690, #691, then the pilot #692 (needs a privacy review; prerequisites bash-365/bash-365.com#26 and the bash-365.com AGENTS.md PR-only fix).
- Predicted ids at merge (as of 2026-11-05): if #685 and #686 merge first — amendment **0026**, feature **HUB-086**, requirement **FR86**, § 27; if this merges first on today's main — **0024**, **HUB-084**, **FR84** (renumber the section to § 25).
- Ratification: Amr ratifies this amendment by merging the PR; agents propose, never merge (§ 8).

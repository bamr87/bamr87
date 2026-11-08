# PRD — Expedite sprints run by agentic loops

> Status: Draft / proposed. Requirement id assigned at merge as `FR-NEW:expedite-sprints` → predicted **FR86** (FR84 if this merges before #685 and #686).
> Feature: `HUB-NEW:expedite-sprints`. Epic [#687](https://github.com/bamr87/bamr87/issues/687). Backlog [#688](https://github.com/bamr87/bamr87/issues/688)–[#692](https://github.com/bamr87/bamr87/issues/692).
> Standard: [`docs/EXPEDITE-SPRINTS.md`](../EXPEDITE-SPRINTS.md). Amendment: `expedite-sprints` (§ 27).

## Problem

Urgent, high-value work waits in the same lanes and caps as everything else, and there is no fleet rule for running one accelerated, monitored build end to end: no expedite lane, no sprint budget or circuit breaker, no delivery metrics, no live record.

## Goals

1. One expedite lane (WIP 1) with three gates only Amr passes.
2. A sprint ceiling and circuit breaker inside the existing budgets.
3. A live sprint record and DORA delivery metrics per target repo.
4. No relaxed quality gates, kill switches or review rules.
5. A first pilot on bash-365.com.

## Non-goals (this slice)

- Raising any existing budget or cap.
- Unattended merges or deploys.
- Building the pilot feature in the ratification PR.

## User stories

| ID | As a… | I want… | So that… |
| --- | --- | --- | --- |
| US1 | owner (Amr) | to declare one item an expedite sprint with an appetite | the fleet's loops swarm it ahead of other work |
| US2 | owner | to approve the spec before any build spend | scope and privacy are settled first |
| US3 | owner | a sprint that stops itself at its cap | a runaway sprint never spends past its appetite |
| US4 | owner | one live record of gates, phase, spend and trip wires | I can see the sprint's state in one place |
| US5 | maintainer | DORA metrics for the target repo before and after | I can tell whether speed cost stability |
| US6 | owner | one switch that stops every sprint loop | I can halt the sprint instantly |

## Requirements (draft FR text)

`FR-NEW:expedite-sprints`: The hub must support one expedite sprint at a time — declared by Amr in `_data/work_queue.yml`, spec-approved and merged through the review gate — run by the existing loops under a sprint ceiling with a circuit breaker, a sprint kill switch, a live record and DORA delivery metrics, without relaxing any quality gate.

## Acceptance

- Amendment + § 27 merged (Amr).
- #689, #691, #690 land with fixture tests.
- Pilot #692 completes with a retro recorded.

## Design for Failure

Mirror the amendment table.

# PRD — Grok ↔ Claude Code governance

> **Status: Draft / proposed.** Governance first; trace lint warn-only on the hub.
> Feature: `HUB-NEW` (slug `grok-claude-governance`) in [`features/features.d/grok-claude-governance.yml`](../../features/features.d/grok-claude-governance.yml). Number assigned at merge.
> Requirements: `FR-NEW:grok-claude-handoff`, `FR-NEW:change-traceability`.
> Roadmap: `FF-NEW:grok-claude-governance` in [`_data/roadmap.d/grok-claude-governance.yml`](../../_data/roadmap.d/grok-claude-governance.yml).
> Amendment: `docs/amendments/0031-grok-claude-governance.md` (§ 28). Depends on [#686](https://github.com/bamr87/bamr87/pull/686) (§ 26 `claude-code-executes`).

## 1. Overview / problem

§ 26 says who acts (Grok directs, Claude Code executes) but not how work flows, how changes are proven to come from ratified direction, or what happens when the executor is down.

## 2. Goals and non-goals

**Goals:** a handoff contract; a direction (not code) review before merge; an audit trail with no orphan changes; a clear stop-and-escalate rule.

**Non-goals:** changing § 12 code review; fleet fan-out (follow-up); hard-failing the lint in this slice.

## 3. Requirements

- **FR-NEW:grok-claude-handoff** — Grok bots hand off software and console work through a Fleet issue or console job stating the requirement, acceptance criteria and the ratified governing link; Claude Code executes; a Grok bot reviews for alignment with direction before merge; if Claude Code cannot run, work stops until Amr approves an alternative.
- **FR-NEW:change-traceability** — every software PR carries a `Governed by:` line linking a ratified amendment or PRD requirement, checked by `tools/governance_trace_lint.py` (warn → fail).

## 4. User stories

- **US1:** As Amr, I can follow any merged change back to the amendment or requirement I ratified.
- **US2:** As a Grok bot, I file a handoff issue with a requirement, acceptance criteria and governing link, so Claude Code never has to guess scope.
- **US3:** As Claude Code, I start only from a complete handoff spec and ask on the issue when it is ambiguous.
- **US4:** As a Grok bot reviewer, I judge whether the PR meets the stated direction without reviewing code style.
- **US5:** As Amr, when Claude Code is out of budget I get one clear ask and nothing proceeds without my OK.
- **US6:** As a contributor, the PR template and lint tell me when my PR lacks a `Governed by:` link.

## 5. Phases

| Phase | Acceptance |
| --- | --- |
| P0 Governance + lint | § 28 merged; warn-only trace lint; PR template field; AGENTS.md roles |
| P1 Handoff template | Fleet issue template for Grok → Claude Code handoffs (Claude Code executes) |
| P2 CI wiring | Workflow runs the lint on PR bodies from the event payload (no API call) |
| P3 Hard fail + fan-out | Amr sets the date; spokes conform or amend |

## 6. Design for Failure

See the amendment's Design for Failure table: orphan changes, incomplete handoffs, unratified governing amendments, review drift, Claude Code unavailable, lint false positives, CI rate limits.

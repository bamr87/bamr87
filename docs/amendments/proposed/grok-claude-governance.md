# NEW — Grok ↔ Claude Code holistic governance (handoff, audit trail, roles, escalation)

- **Status:** proposed (ratification pending — Amr ratifies by merging this PR)
- **Number:** NEW
- **Date:** 2026-11-05
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:**
- **Affects:** constitution § 28 (new; follows proposed § 25 `mcp-lifecycle` #685, § 26 `claude-code-executes` #686, § 27 `expedite-sprints` #693 — **may be renumbered depending on merge order**); § 4 and § 26 by reference; feature `HUB-NEW:grok-claude-governance`; requirements `FR-NEW:grok-claude-handoff`, `FR-NEW:change-traceability`; roadmap FF-NEW:grok-claude-governance; `AGENTS.md` agent roles; `.github/pull_request_template.md`
- **Supersedes:** none (builds on `claude-code-executes`)
- **Depends on:** open PR [#686](https://github.com/bamr87/bamr87/pull/686) `claude-code-executes` (§ 26) — **not merged as of 2026-11-05**. This amendment assumes § 26's actor split; if #686 is changed or rejected, this text must be revised before ratification.
- **Related:** #685, #693 (pending sections); § 8 (agents propose, Amr ratifies); § 10 (Fleet project tracking); § 11 (plan → confirm → apply)

## Context

§ 26 (proposed in #686) splits *who* acts: Grok bots set direction, Claude Code executes. It does not yet say *how* work flows between them, how a change is proven to come from ratified direction, or what happens when the executor cannot run. Without that, the split leaks: Claude Code may build against an unstated or unratified idea, Grok may drift into reviewing code instead of direction, and changes appear that no amendment or requirement asked for.

## Prior art

- **§ 26 (proposed, #686):** actor split, handoff via Fleet issue / console job, Amr OK fallback. Fit: this section is the operating model on top of it.
- **features.d + `prd_new` + `jev/number.py`:** every feature already carries PRD ids. Fit: reuse as the trace target.
- **PR template / governance_lint / guides_visual_lint:** warn-then-fail lints. Fit: same pattern for a PR-body trace lint.
- **Build-vs-adopt:** adopt issues, console jobs and the PR template; the only new code is a small warn-only lint.

## Amendment

> ## 28. Grok ↔ Claude Code governance
>
> _(amendment `grok-claude-governance`, numbered at merge — see the [amendment log](amendments/README.md); follows proposed § 25–§ 27 (#685, #686, #693) and may be renumbered by merge order; depends on § 26 `claude-code-executes`)_
>
> 1. **Handoff contract** — a Grok bot starts software or console work only by opening a Fleet issue or a Harness Console job that states (a) the requirement (`FRn`/`NFRn`, or `FR-NEW:<key>` in a pending amendment), (b) acceptance criteria and constraints, and (c) a link to the **ratified** amendment or PRD requirement that governs it. Work whose governing amendment is still unratified stays queued.
> 2. **Execution** — Claude Code executes against that spec, opens the implementation PR, and links the handoff issue/job and the governing amendment or requirement in the PR body. Ambiguity goes back to the issue as a question, not into invented scope (unknown = **TBD**).
> 3. **Direction review** — before merge, a Grok bot reviews the result for **alignment with direction** (does it meet the stated requirement and stay inside the amendment's scope?) and records the verdict on the PR. It does not review or rewrite the code itself; code quality stays with § 12 / § 15 review and CI.
> 4. **Audit trail, no orphan changes** — every software change traces to a ratified amendment or PRD requirement. Each PR body carries a `Governed by:` line naming an amendment (`docs/amendments/NNNN-*.md`, `AMEND-NNNN`, or a pending amendment PR) and/or a requirement (`FRn`, `NFRn`, `FR-NEW:<key>`). `tools/governance_trace_lint.py` checks this; warn-only until adoption, then a hard failure. Trivial maintenance (dependency bumps, typo fixes, generated-file refreshes) cites the standing requirement that covers it or is labelled `trace-exempt` by Amr.
> 5. **Role boundaries** — Grok bots own direction: constitution, amendments, PRD, features, roadmap, research and assessments. Claude Code owns every software change and console job (§ 26). Neither crosses the boundary without Amr's explicit OK.
> 6. **Escalation** — if Claude Code is unavailable or out of budget, the work **stops**. The Grok bot records the blocker on the handoff issue and asks Amr; nothing proceeds until Amr approves an alternative path (wait, a one-shot exception, or Amr executes).
> 7. **Ratification** — this section and every amendment under it are ratified only when Amr merges the PR (§ 8).

## Design for Failure

| Failure mode | Detection | Containment | Recovery |
| --- | --- | --- | --- |
| Orphan change (PR with no amendment/FR) | `governance_trace_lint.py` on the PR body; PR template field | Warn now, fail after adoption; direction review blocks | Author adds `Governed by:`, or Grok files the missing amendment/FR first |
| Handoff spec missing governing link or acceptance criteria | Claude Code checks the issue before starting; lint on the resulting PR | Claude Code asks on the issue instead of guessing | Grok updates the issue; work resumes |
| Governing amendment not yet ratified | `Governed by:` points at an open PR | Work stays queued; implementation PR held | Proceeds after Amr merges the amendment |
| Grok review drifts into code review / rewrite | Review comments touching code style or pushing commits | § 26 lint flags Grok-authored software commits | Reviewer restates scope; code review stays with § 12/§ 15 |
| Claude Code unavailable / out of budget | Job failure, budget ledger, timeout | Work stops; no silent Grok implementation | Amr approves an alternative path |
| Lint false positive (e.g. trivial bumps) | Contributor report | Warn-only phase | `trace-exempt` label by Amr; lint patterns refined |
| GitHub API rate limit in CI | 403/429 in job logs | Lint reads body from file/event payload, not the API, where possible | Re-run; not a governance failure |

## Open questions (for Amr)

1. **#686 dependency** — #686 is not merged. Ratify this only after #686, or merge together?
2. **Section number** — § 28 assumes #685, #686, #693 merge first; renumber otherwise.
3. **Who records the direction review** — one designated Grok bot (e.g. Platform Architect) or whichever bot filed the handoff?
4. **Trace exemptions** — is the `trace-exempt` label (Amr-only) right for dependency bumps / generated refreshes, or should they cite a standing FR?
5. **When to hard-fail** the trace lint — after N clean weeks on the hub, or at a date Amr sets?
6. **Pending-amendment references** — may an implementation PR cite an *open* amendment PR (held until it merges), or only ratified numbers?
7. **This PR's own lint/template change** — under § 26 a Grok bot should not ship code; this PR includes a small lint and a PR-template field as direction-supporting fragments. Keep them here, or hand them to Claude Code as the first handoff under § 28?

## Consequences

- Handoffs carry a requirement, acceptance criteria and a ratified governing link.
- PRs carry a `Governed by:` line; a warn-only lint checks it.
- `AGENTS.md` agent roles gain the handoff/review/escalation flow.
- Predicted ids at merge (main tip 2026-11-05, assuming #685/#686/#693 merge first): amendment **0027**, HUB-**087**, FR**87**/FR**88**, § **28**, roadmap `FF-NEW:grok-claude-governance` (FF-NEW:grok-claude-governance went to another entry on main; the fragment is numbered at merge).
- Ratification: Amr ratifies by merging this PR; agents propose, never merge (§ 8).

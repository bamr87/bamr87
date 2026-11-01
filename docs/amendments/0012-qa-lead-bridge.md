<!-- kit: governance v0.1.0 -->
# 0012 — QA Lead first: a short warn-only bridge for the § 15 completeness review, and § 15 numbering made final

- **Status:** ratified
- **Number:** 0012
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/496 (merged 2026-10-31 by @bamr87)
- **Affects:** constitution § 15 (header note and item 5 "Interim"); features: none (HUB-046 and HUB-047 already say "interim fallback" generically; the compiled features.yml is not hand-edited)
- **Supersedes:** none (amends the interim clause of 0010 `major-change-evidence`; 0010 itself is not edited, per § 8)
- **Related:** #491 (merged as 0010), #492 (Build QA Lead), 0011 `eval-baseline-risk-tiers` (#482, merged), 0009 `agent-merge-review-gate`

## Context

Amr answered the open items on #491, and the answers were committed to its branch (7184e3f) minutes after #491 was merged, so they never reached `main`. Records are append-only (§ 8; `docs/amendments/SCHEMA.md`: never edit a ratified record), so 0010 is not edited. This amendment carries the two answers instead:

1. **Interim reviewer:** building QA Lead is the priority. Until QA Lead runs, the completeness review is warn-only with Amr as the fallback, explicitly a short bridge. QA Lead takes over as soon as it exists, and JEV joins later. This replaces 0010's interim clause ("until JEV exists, QA Lead reviews alone; until QA Lead exists, Amr reviews (proposed fallback, Amr to confirm)").
2. **Numbering:** § 15 stays. 0010 made the number contingent on #482; #482 has since merged as 0011 (§ 13), so the contingency is resolved and its text is removed.

## Prior art

No new tooling (0008). The bridge reuses the § 15.7 warn-then-fail rollout and the QA Lead role already in docs/PROJECTS-FRAMEWORK.md; the QA Lead build is tracked in #492.

## Amendment

In constitution § 15:

- Header note: replace "§ 13 is reserved for `eval-baseline-risk-tiers` (#482), so this number is contingent on #482 and is renumbered if #482 does not land;" with "§ 13 is `eval-baseline-risk-tiers` (0011), so the number § 15 is final; interim reviewer amended by `qa-lead-bridge`;".
- Item 5: replace the "**Interim:**" sentence with:

> **Interim (a short bridge):** building QA Lead is the priority (#492). Until QA Lead runs, the completeness review is warn-only, with Amr as the fallback reviewer. QA Lead takes over as soon as it exists, and JEV joins later.

## Consequences

- Until QA Lead runs, the § 15 completeness check never fails a build; it warns and asks for Amr's review. The § 15.7 warn-then-fail rollout applies once QA Lead exists.
- 0010's record keeps its original interim text as history; this record is the current rule.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

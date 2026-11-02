<!-- kit: governance v0.1.0 -->
# 0017 — Fleet PR review runs through one reusable workflow with one sticky summary

- **Status:** ratified
- **Number:** 0017
- **Date:** 2026-11-01
- **Proposed by:** agent (Grok Bot, as Platform Architect, on a branch opened for bamr87)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/563 (merged 2026-11-02 by @bamr87)
- **Affects:** constitution § 2 (new invariant), new § 19 (follows § 18 `fleet-design-consistency`, PR bamr87/bamr87#554; becomes § 18 if this merges first, numbered at merge); feature `fleet-pr-review` (HUB-NEW); requirement `FR61`; roadmap FF-0034
- **Supersedes:** none (extends § 11, § 12, § 13, § 15 and § 17)
- **Related:** 0009 `agent-merge-review-gate`, 0010 `major-change-evidence`, 0011 `eval-baseline-risk-tiers`, 0013 `ai-ready-foundation` (warn-then-fail rollout), `central-loop-switches` (§ 17), UPS-WORK-07 (reusable gate consumed by reference), `standard-ci.yml`

## Context

An audit of every PR comment, review and inline comment across the fleet (269 PRs, comments dated 2026-10-18 to 2026-11-01 plus 3 older comments on PRs still open in that window; dataset `pr-comment-audit/comments.csv`) found 173 comments on 103 PRs. Only 10 (5.8%) were actionable; 112 were informational, 37 noise, 10 invalid and 4 duplicate or duplicate-risk. 77 (44.5%) were posted under Amr's account `bamr87` by automation, against 78 by `github-actions[bot]`. 31 comments landed on Dependabot PRs.

The worst offenders:

- **Docs Warden** (`docs-warden.yml`, year-of-ai 13, ai-world-view 3): 16 comments, 9 of them invalid demands for a `CLAUDE.md` update on routine workflow and dependency edits, 6 of the 16 on Dependabot PRs.
- **Fleet merge agent (as bamr87):** 14 rubber-stamp "LGTM … approving" reviews by the same account as the author, all noise, 9 on Dependabot PRs.
- **Dependabot label warnings:** 8 noise comments about configured labels missing in the repo (6 in year-of-ai).
- **README docs-quality check:** one comment dumping raw JSON with 40,038 repo-wide lint issues, not scoped to the diff.
- **it-journey `content-quality.yml`:** `gh pr comment` with no upsert, so a new comment on every push (2 flagged).
- **Pass-only posts:** 7 all-pass deterministic stickies, 2 all-clear stickies, 1 empty "no issues" review, 4 "nothing to edit" scout reviews.
- **Cost tables:** 29 AI-usage meter comments (lifehacker.dev `usage_report.rb`, 25 as bamr87) that belong in the job summary.

## Prior art

- **0009 / § 12 merge authority and review gate:** a review only counts when it is a real review; a self-authored LGTM by the author's own account adds nothing to § 12.1.2 and hides who acted. This amendment stops automation reviewing as Amr.
- **§ 13 AI tiers and evals:** AI review is a medium-tier action with an audit record; it must pass its eval set before its findings can fail a build. The cost of running it on every push is the reason for the trigger rule.
- **§ 15 evidence:** completeness review and test evidence go in the PR body and linked runs; this amendment puts cost and test tables in job summaries for the same reason.
- **§ 17 loop switches:** the review workflow's AI steps are an AI-calling loop and must check the central switch.
- **§ 11 write-back:** GitHub writes go through sanctioned paths; identity is part of that.
- **UPS standards:** UPS-WORK-07 already consumes a hub reusable gate (`spec-gate.yml`) by reference with `rollout: warn`; `standard-ci.yml` is the hub's reusable merge gate called by 19 repos (docs/RELEASES.md). Reusable fleet workflows live in this hub, so the new one does too.
- **External:** sticky-comment actions (`marocchino/sticky-pull-request-comment`), reviewdog severity filters and `$GITHUB_STEP_SUMMARY` are the adopted patterns; nothing new is built that these cover.

## Amendment

Add to constitution § 2 (Invariants):

> - Fleet PR automation comments through the hub's reusable `pr-review.yml`: one sticky summary per PR, silent when clean, never under Amr's account. _(amendment `fleet-pr-review`, numbered at merge)_

Add constitution § 19 "Fleet PR review and comments" with the text in `docs/constitution.md`.

## Consequences

- Follow-up: implement `.github/workflows/pr-review.yml` and the per-repo stub (hub issue, `agent:queued`).
- Follow-up: identity and token changes (fleet app, removing Amr's PAT from bots) are a separate `needs-amr` issue.
- Fan-out: one PR per spoke repo replaces its own comment-posting steps with the stub; warn-only until that PR lands, then fail. Repos with no PRs in the audit window are N/A until they get one.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

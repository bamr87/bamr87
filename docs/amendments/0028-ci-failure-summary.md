# 0028 — Every CI failure is summarized on its pull request

- **Status:** ratified
- **Number:** 0028
- **Date:** 2026-11-06
- **Proposed by:** agent, at the maintainer's request (2026-11-06: "there needs to be a global rule that any CI failure needs to be summarized and commented on the PR ... i need to know why the workflows failed.")
- **Ratified by:** https://github.com/bamr87/bamr87/pull/750 (merged 2026-11-07 by @bamr87)
- **Affects:** constitution § 19 (new item 10); `specs/WORK.md` UPS-WORK-17; feature HUB-065; requirement FR61
- **Supersedes:** none (extends § 19)
- **Related:** 0017 `fleet-pr-review`, bamr87/bamr87#564, bamr87/bamr87#565

## Context

Nothing told anyone why a check failed. PR #747 showed a red check with no explanation. The cause was a duplicate key in `_data/fleet.yml` that two other PRs had merged, unrelated to #747, and `main` had been red for about 18 hours with nobody told.

§ 19 already says the fleet comments on a PR through one reusable workflow and one sticky summary, but `pr-review.yml` was never built, and § 19 does not say a CI failure must be explained.

## Amendment

Add to constitution § 19:

> 10. **CI failures** — every failed CI run on a pull request is summarized in the sticky comment, so nobody has to open a log to learn why it failed: the job and step, the reason taken from its log, whether the PR probably caused it, and what to do next. This covers a run that never started. When a step printed no clear error, the comment says so and does not guess. A failed push to the default branch is reported on the PR that merged it.

## Consequences

- `.github/workflows/pr-review.yml` and `.github/scripts/dash-gen/pr_review.py` land with this record, as the first check of #564. Inline findings, AI review and moving the existing comment-posting bots onto it stay on #564.
- UPS-WORK-17 holds the fleet to it, warn-only until each repo's fan-out PR lands (§ 19.9).
- The fleet stub calls the hub at `@v2`, so a repo adopts it after the tag that carries `pr-review.yml`.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

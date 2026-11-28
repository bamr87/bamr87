### Added

- `pr-review.yml` posts QA Lead's review (constitution § 15.5): when a repo's `qa-lead.yml` run finishes, `pr_review.py` recomputes the completeness review from live GitHub and posts one review per head commit and result, `REQUEST_CHANGES` on a gap and `COMMENT` otherwise, never `APPROVE`. A repo without `qa-lead.yml` sees no change.

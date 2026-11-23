### Added

- `pr-review.yml`: posts the AI review. When the workflow that finished is `pr-ai-review.yml`, the `ci-failure` pass reads its `fleet-review` artifact and posts one comment-only review per head commit: a summary, the findings that are not on an added line, and the next actions by who moves them (constitution § 19.7; ADR 0012 stage B). It believes only a `pull_request_target` run of that workflow and validates the artifact in memory. The workflow file gains no step and no input: a caller with no `pr-ai-review.yml` sees no change.

### Fixed

- `pr-review.yml` with `PR_READINESS_ENABLED` set to `true`: a check's `fleet-findings` are posted inline again. `pr_readiness.py` replaced `pr_review.py` as the entry point and did not read the findings channel, so turning readiness on turned inline findings off.

### Added

- Reusable `.github/workflows/pr-review.yml`: an `ai-analysis` job writes an AI analysis of every failed CI run into the PR's one sticky comment (root cause, whether the PR caused it, the fix), once per failed run attempt, from one capped, tool-less, one-turn Claude call; it takes an optional `CLAUDE_CODE_OAUTH_TOKEN` secret, and `vars.PR_AI_ANALYSIS_ENABLED=false` turns it off (constitution § 19.11). Kit `pr-review` 0.3.0 passes that secret; seed it after the `v2` tag carries the job.

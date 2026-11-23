### Added

- `pr-ai-review.yml` is reusable (`workflow_call`: inputs `hub-ref` and `pr`, secret `CLAUDE_CODE_OAUTH_TOKEN`), so a fleet repo can run the comment-only AI review of a pull request that is marked ready from its own caller (the pr-review kit's stub, 0.5.0, after this release). The hub's own run is unchanged: its tooling checkouts now name `bamr87/bamr87` at `hub-ref`, falling back to the event's ref.
- The pr-review kit's `pr-review.yml` stub (0.4.0) carries the `pull_request_target` trigger, so merge readiness (`PR_READINESS_ENABLED`) stays current in a fleet repo when a pull request is only marked ready, labelled or edited.

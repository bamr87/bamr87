### Added

- Constitution § 23 (amendment `writing-chronicle`): the writing section (`pages/posts/`) keeps a daily, summarized chronicle of all fleet operations, AI prompting and agent work — working on, pushing, committing and deploying — across all repos, with secrets always redacted; entries are drafts by default and publish only after review by a human and/or an agent.
- Shared voice model `voices/v1`: `_data/voices/voices.yml` (canonical; lifehacker.dev's SDLC persona cast) and `voices.schema.json`, validated by `tools/voices.py check` (with `--against` drift check and `assign`). § 23 also brings lifehacker.dev in as the hub-originated news agency.

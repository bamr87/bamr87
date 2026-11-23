### Added

- `.github/actions/codex-run`: the fleet's OpenAI step on the ChatGPT OAuth login (never a metered API key). Modes `review` (read-only, schema-bound, redacted), `image` (Codex's built-in `$imagegen`, a PNG plus its `.prompt.json` provenance), `setup` (exports `FLEET_IMAGEGEN` for the job) and `check`. Takes `CODEX_AUTH_JSON` from the job env and refuses a bundle older than 7.5 days instead of letting Codex refresh it. See docs/OPENAI-AUTH.md.
- `.github/workflows/independent-review.yml`: a reusable, advisory OpenAI review of non-technical changes (content and no code), on `opened`, `ready_for_review` and the `ai-review` label. Findings leave as the `fleet-findings` artifact for `pr-review.yml`; the verdict goes to the job summary. Inputs `hub-ref`, `scope`, `label`, `content-paths`, `technical-paths`, `model`, `base`, `head`, `timeout-minutes`; secret `CODEX_AUTH_JSON`; outputs `reviewed`, `verdict`.
- `.github/workflows/ai-lane.yml`: optional inputs `images` and `hub-ref`, and the optional secret `CODEX_AUTH_JSON`. With `images: true` the lane restores the OpenAI ChatGPT login and the agent paints with `$FLEET_IMAGEGEN`.

### Changed

- `.github/workflows/ai-lane.yml`: the agent no longer receives `OPENAI_API_KEY`; images run on the ChatGPT OAuth login. The secret input stays declared, so callers that pass it keep working.

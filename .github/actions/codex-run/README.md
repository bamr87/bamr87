# codex-run

The fleet's OpenAI step: one call through the Codex CLI on the ChatGPT subscription's OAuth login, never a metered API key. Contract: [`_data/fleet.yml`](../../../_data/fleet.yml) `openai_auth:`. Operator doc: [docs/OPENAI-AUTH.md](../../../docs/OPENAI-AUTH.md).

```yaml
- uses: bamr87/bamr87/.github/actions/codex-run@v2
  env:
    CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
  with:
    mode: image
    prompt: "an oil-painted server room at dawn"
    out: assets/images/posts/my-post/hero.png
```

A workflow whose workspace is another repo takes it from a sparse checkout of the hub at its own `hub-ref` (`uses: ./.fleet-hub/.github/actions/codex-run`), as `independent-review.yml` and `ai-lane.yml` do. A caller pins `@v2` only once a release carries this action ([WORKFLOW-VERSIONING.md](../../../docs/WORKFLOW-VERSIONING.md)).

## Modes

| Mode | What it does |
| --- | --- |
| `review` | Read-only sandbox. Codex reads the workspace and answers; the last message (JSON when `output-schema` is set) lands in `out`, redacted. |
| `exec` | The same, with the sandbox the caller names (`read-only` default). |
| `image` | Codex's built-in `$imagegen` (`gpt-image-2`) paints one image in a private work dir; the PNG goes to `out` with `<out>.prompt.json` (prompt, model, sha256, date). No image is RED. |
| `setup` | Restores the login for the rest of the job (`CODEX_HOME` via `$GITHUB_ENV`) and exports `FLEET_IMAGEGEN`, the image helper ([`imagegen.sh`](imagegen.sh)). |
| `check` | Restores and proves the login and the model with one tiny call. |

## Outputs

`ready` (a usable credential was restored), `outcome` (`success`, `skipped`, `limited`, `failure`), `reason`, `refreshed` (Codex rotated the bundle mid-call: the fleet's copies need a re-seed), `image`.

## The credential rules

- `CODEX_AUTH_JSON` comes from the job env. Absent, not a ChatGPT login, older than `max-seed-age-days` (7.5) or with an access token lapsing within `min-ttl-minutes` (30): a clean no-op with the reason. The hub's weekly rotation is the bundle's one refresher; a consumer that let Codex refresh it would rotate the fleet's one refresh token.
- The bundle goes into a fresh 0700 `CODEX_HOME` with `forced_login_method = "chatgpt"`; `OPENAI_API_KEY` is unset for the call; the home is deleted afterwards (not in `setup` mode). Nothing is persisted back.
- Every token is masked when read; everything the model writes is redacted before it reaches a file.
- The CLI is `@openai/codex` at latest, installed each job ([DEPENDENCIES.md](../../../docs/DEPENDENCIES.md)).
- A spent ChatGPT usage window is capacity, not a defect: with `usage-limit: skip` (default) it is outcome `limited` and a warning.

## Files

| File | Purpose |
| --- | --- |
| `action.yml` | The manifest; every input reaches `run.sh` through `env:`. |
| `run.sh` | The engine, shared with `tools/openai-auth.sh` (local runs use your own login: `CODEX_LOCAL=1`). |
| `imagegen.sh` | `$FLEET_IMAGEGEN`: `run.sh image` on the home a `setup` step restored. |
| `codex_auth.py` | Stdlib helpers: inspect a bundle without printing it, fingerprint the refresh token, redact, find the image, write the provenance sidecar. |

Tests: `python3 tools/test_codex_run.py` (a fake `codex` on `PATH`; no network, no account).

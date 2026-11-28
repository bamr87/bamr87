# OpenAI auth — images and the independent review on the ChatGPT OAuth login

> How the fleet uses OpenAI: every AI-painted image and every independent review of a non-technical change runs through the Codex CLI on a ChatGPT subscription's OAuth login, never on a metered API key. One credential (`CODEX_AUTH_JSON`), one refresher (the weekly token rotation), many read-only consumers.

The fleet's agents are Claude (constitution § 26). Two jobs go to OpenAI instead. **Images**, because Codex's built-in `$imagegen` paints with `gpt-image-2` on the ChatGPT plan. **An independent review of non-technical changes**, because a second opinion is worth more from a different model family than the Claude agents that write most fleet content. Both used to need `OPENAI_API_KEY`, a metered key billed per image; both now run on the subscription's OAuth tokens.

| | |
| --- | --- |
| Contract | [`_data/fleet.yml`](../_data/fleet.yml) `openai_auth:`, the `CODEX_AUTH_JSON` entry in `tokens:`, `ai_models.allowed.openai` |
| The step | [`.github/actions/codex-run`](../.github/actions/codex-run/README.md) (`review`, `image`, `setup`, `exec`, `check`) |
| The review | [`independent-review.yml`](../.github/workflows/independent-review.yml) (reusable), called by each repo's `openai-review.yml`; engine [`independent_review.py`](../.github/scripts/dash-gen/independent_review.py) |
| Images in a lane | [`ai-lane.yml`](../.github/workflows/ai-lane.yml) `images: true` → `$FLEET_IMAGEGEN` |
| The refresher | [`token-rotation.yml`](../.github/workflows/token-rotation.yml) through `tools/dash secrets rotate` ([TOKEN-ROTATION.md](TOKEN-ROTATION.md)) |
| Local front door | [`tools/openai-auth.sh`](../tools/openai-auth.sh) `seed` · `check` · `image` · `review` |
| Tests | `python3 tools/test_codex_run.py` · `python3 .github/scripts/dash-gen/test_independent_review.py` · `python3 tools/test_fleet_config.py` · `python3 .github/scripts/dash-gen/test_harness_registry.py` |

## TL;DR

```bash
tools/openai-auth.sh seed            # dry run: a dedicated ChatGPT login, checked, not written
```

```bash
tools/openai-auth.sh seed --apply    # write CODEX_AUTH_JSON to the hub
```

```bash
gh workflow run token-rotation.yml -R bamr87/bamr87 -f apply=true -f only=CODEX_AUTH_JSON -f source=env -f force=true
```

```bash
tools/openai-auth.sh check                                        # your login and the pinned model answer
tools/openai-auth.sh image --prompt "a lighthouse at dawn" --out /tmp/hero.png
tools/openai-auth.sh review --base origin/main                    # the independent review of your branch
```

## The credential

`CODEX_AUTH_JSON` is the `auth.json` that `codex login` writes for a ChatGPT account: an OAuth access token, an id token, a refresh token and a `last_refresh` stamp. It is never an API key; a bundle that carries `OPENAI_API_KEY` or has no refresh token is refused everywhere, by the rotation's shape check and by every consumer.

OpenAI documents running Codex in CI this way: restore `auth.json` into `CODEX_HOME`, run, and keep the refreshed file ([learn.chatgpt.com/docs/auth/ci-cd-auth](https://learn.chatgpt.com/docs/auth/ci-cd-auth)). It also warns against sharing one file across concurrent jobs or machines, because a refresh rotates the refresh token: once one copy refreshes, every other copy holds a dead one. Forty repos running reviews in parallel are exactly that. So the fleet splits the roles:

- **One writer.** The hub's weekly `token-rotation.yml` (Monday 02:07 UTC) is the only place the bundle is refreshed. An applying run exchanges the bundle's refresh token for a new set (the grant the Codex CLI itself uses, at `auth.openai.com`; unofficial like the Claude grant, so a failure there is a `needs-reseed` issue, never a broken value fanned out), stamps `last_refresh`, and writes the new bundle hub-first to every repo. A dry run never refreshes: the grant consumes the token it is given.
- **Many readers.** Every consumer restores the bundle into a fresh 0700 `CODEX_HOME`, forces the ChatGPT login (`forced_login_method = "chatgpt"`), unsets `OPENAI_API_KEY`, runs one call, and deletes the home. It never writes anything back.
- **Readers refuse before Codex would refresh.** Codex refreshes a bundle on its own once `last_refresh` is about 8 days old. A consumer refuses one older than `openai_auth.max_seed_age_days` (7.5), or whose access token lapses within `min_access_ttl_minutes` (30), and idles with a notice that names the fix. If Codex rotates the bundle anyway, the step says so in a warning (`refreshed: true`), because the fleet's copies are then dead until a re-seed.

### Seeding it

Seed from a **dedicated** login, never the one your own Codex sessions use: after the first refresh, the fleet's bundle and your laptop's would share a token family and log each other out. `tools/openai-auth.sh seed` logs in inside a throwaway `CODEX_HOME` (`--device-auth` for a headless machine; device-code login must be enabled in ChatGPT's security settings), checks the bundle is a ChatGPT login with a refresh token, and with `--apply` writes it to the hub with `gh secret set`. The local copy is deleted; from then on the weekly rotation is that login's only refresher. Propagate at once with the `token-rotation.yml` dispatch above, or wait for Monday.

Re-seed the same way when the rotation files `needs-reseed` or `refresh-store-failed`, or when a step warns that Codex refreshed the bundle mid-run.

## What runs on it

### Images

Codex's built-in `$imagegen` skill paints with `gpt-image-2` and counts against the ChatGPT plan's usage, not API credits ([learn.chatgpt.com/codex/image-generation](https://learn.chatgpt.com/codex/image-generation)). `codex-run` in `image` mode asks the driver model (`openai_auth.models.image_driver`) to call it once in a private work dir, takes the PNG it left there (or the newest under `$CODEX_HOME/generated_images`, by its magic bytes), copies it to `out`, and writes `<out>.prompt.json`: the prompt, the model, the sha256, the date and the note that the page embedding it must caption it as AI-generated. No image is a red step; it never falls back to anything.

In a workflow, call the action directly, or set `images: true` on an `ai-lane.yml` caller and pass `CODEX_AUTH_JSON`: the lane restores the login once and exports `FLEET_IMAGEGEN`, so the agent runs `"$FLEET_IMAGEGEN" --prompt "…" --out assets/images/…/hero.png`. `ai-lane.yml` no longer hands the agent `OPENAI_API_KEY`; the input stays declared so old callers do not break.

### The independent review

`independent-review.yml` classifies a change's files ([`independent_review.py`](../.github/scripts/dash-gen/independent_review.py)):

| Class | What | Examples |
| --- | --- | --- |
| content | prose and media a person reads or sees | `*.md`, `*.rst`, `*.txt`, images, PDFs |
| data | configuration and records riding with content | `_data/*.yml`, `_config.yml`, `*.json`, `*.csv` |
| code | anything that runs, builds or instructs an agent; anything unknown | source, templates (`_layouts/`, `*.html`), CI, `scripts/`, `AGENTS.md`, `CLAUDE.md`, lockfiles |

With `scope: non-technical` (the default, `openai_auth.review.scope`), a change with content and **no code** is reviewed; a change with code belongs to Claude Code and CI (§ 26) and is skipped. `scope: content-files` reviews the content files of any change and never shows the reviewer its code. A repo moves files between classes with the caller's `content-paths` and `technical-paths` globs.

The reviewer (`openai_auth.models.review`) reads the change read-only and answers in a strict JSON schema: a verdict (`clean`, `suggestions`, `concerns`), a summary, and findings on accuracy, sensitive data, attribution (including AI images without a caption or sidecar), accessibility, clarity, tone, grammar and links. Everything from the repository and the pull request is quoted to it as data; what it writes is redacted (bundle tokens, JWTs, API keys) and validated against the findings contract before it leaves the job.

It speaks through the fleet's one comment channel (constitution § 19): findings on lines the change adds become the `fleet-findings` artifact that `pr-review.yml` posts inline, signed, as `github-actions[bot]`, never approving (§ 19.3–19.5); the verdict and every finding go to the job summary (§ 19.8). It runs on `opened`, `ready_for_review` and the `ai-review` label, never on every push (§ 19.7). A commit pushed straight to a branch is reviewed on demand by dispatching the caller with `base` and `head`. It is advisory: a finding never fails the check, and only an attempt that could not finish is red. Before its findings may fail a build it needs a § 13.1 eval set.

Off switch: the repo variable `OPENAI_REVIEW_ENABLED` set to `false` (§ 17; a dispatch still runs). Without `CODEX_AUTH_JSON` (a fork's pull request, a repo not seeded yet) it idles with the reason in the job summary.

## Models

`openai_auth.models` names exact ids from `ai_models.allowed.openai` (§ 13.3): the reviewer, the image driver, and `gpt-image-2`, which is recorded in each image's provenance. A ChatGPT-account model can be retired out from under a pin (`gpt-5.5` was, for ChatGPT sign-ins, on 2026-10-14); the step names that failure and points here. Prove a replacement with `tools/openai-auth.sh check --model <id>`, then change `openai_auth.models` and `ai_models.allowed.openai` in one gated PR (§ 12.3); `tools/test_codex_run.py` holds the runner's defaults equal to them.

## Cost and capacity

Both jobs draw on the ChatGPT plan's usage window, not metered spend, so there is no per-call dollar figure and no `--max-budget-usd` to pass; the harness standard grades the `codex-run` route on its switch, pinned model, timeout and least privilege instead ([HARNESS-OPS.md](HARNESS-OPS.md#the-harness-standard)). That is not free: a spent window is the cost, and like a spent Claude window it is capacity, not a defect (`usage-limit: skip`: outcome `limited`, a warning, the next run tries again). The agent inventory records both workflows with `per_run_usd: 0.0` metered and says why ([AGENT-EFFICACY.md](AGENT-EFFICACY.md)).

## Rollout

| Step | What | Who |
| --- | --- | --- |
| 1 | This change: the contract, `codex-run`, the rotation's refresher, `independent-review.yml`, the hub's own `openai-review.yml`, `ai-lane.yml` images | merged by Amr (gated: `ai_models.allowed`, `harnesses.standard`) |
| 2 | Seed `CODEX_AUTH_JSON` and propagate it (TL;DR) | Amr, on a machine with a browser |
| 3 | Cut the next `v2.x.0` and move `v2` ([WORKFLOW-VERSIONING.md](WORKFLOW-VERSIONING.md)): a kit may pin `independent-review.yml@v2` and `codex-run@v2` only once the tag carries them (drift check (q)) | release |
| 4 | The `openai-review` kit (`templates/openai-review/`, the stub pinned `@v2`) and its `fanout.yml` wiring, then a dry-run fan-out to every repo, then `--apply` | follow-up PR, then a dispatch |
| 5 | The image generators that still call the Images API with `OPENAI_API_KEY` move to `codex-run` / `tools/openai-auth.sh image`, one PR in each repo: zer0-CMS `packages/zer0-image-generator` and `sites/drsai/tools/generate_illustrations.py`, zer0-mistakes `scripts/lib/preview_generator.py`. lifehacker.dev's `openai_image.mjs` is left: its automation was retired on 2026-11-05 | one PR per repo |

## Security notes

- `pull_request` only, never `pull_request_target`: a fork's run gets no secret and idles.
- The model call has no GitHub token in its environment and a read-only sandbox (review); image mode writes only to a private temp dir.
- An agent in an `images: true` lane can read the restored `auth.json` (it has a shell); that is the same trust the lane gave `OPENAI_API_KEY` before, with a token that lives a week instead of a key that lives until revoked.
- Nothing prints a token: every token is registered with the log scrubber the moment it is read, and the step's output is redacted.

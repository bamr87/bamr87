# Release & Versioning Methodology

> Release and versioning methodology across the fleet.

How versioning, changelogs, releases, and the merge-to-main quality gate work across every repo in this monorepo. The shared implementation lives in **[bamr87/.github](https://github.com/bamr87/.github)**; this doc is the operator's guide.

## TL;DR

- Write **[Conventional Commits](https://www.conventionalcommits.org/)**. That's the only manual step.
- **[release-please](https://github.com/googleapis/release-please)** turns commits into a version bump + `CHANGELOG.md` via a **release PR**.
- Merge the release PR → it tags `vX.Y.Z`, creates the GitHub Release, and publishes the package.
- Merges to `main` are gated by the repo's CI. The shared gate is this hub's reusable **[`standard-ci.yml`](../.github/workflows/standard-ci.yml)** (stack-detected lint, test and build), called by 19 member repos (2026-10-03); other repos run their own CI or none. `bamr87/.github`'s reusable `ci.yml` has no callers.

## The pipeline

```
feature branch ──PR──► CI gate ──► merge to main
                                           │
                                  release-please (on push)
                                           │
                               ┌───────────┴───────────┐
                               │   opens / updates a    │
                               │      release PR        │   ← review the version + changelog here
                               └───────────┬───────────┘
                                  merge the release PR
                                           │
                          tag vX.Y.Z + GitHub Release
                                           │
                                       publish.yml
                            (RubyGems / npm / PyPI / GHCR)
```

The merge gate lives in this hub: [`.github/workflows/standard-ci.yml`](../.github/workflows/standard-ci.yml). The release building blocks live in `bamr87/.github`:

| File | Role |
| --- | --- |
| `.github/workflows/release-please.yml` | version bump + CHANGELOG + GitHub Release |
| `.github/workflows/publish.yml` | publish to the detected registry + attach assets |
| `.github/actions/detect-stack` | emits `node`/`ruby`/`gem`/`python`/`jekyll`/`docker` + `registry` |

## Conventional Commits → semver

| Commit | Bump |
| --- | --- |
| `fix: …` | patch (x.y.**z**) |
| `feat: …` | minor (x.**y**.0) |
| `feat!: …` or a `BREAKING CHANGE:` footer | major (**x**.0.0) |
| `docs:` `chore:` `refactor:` `test:` `ci:` `perf:` `style:` `build:` | no release on their own |

The **squash-merge subject** (= PR title) is what counts. `standard-ci.yml` does not lint it, so review the PR title before merging.

## Adopt the pipeline in a repo

```bash
tools/adopt-release.sh <repo>                      # detect ecosystem, scaffold, open a PR
tools/adopt-release.sh <repo> --dry-run            # build the branch locally, show the diff
tools/adopt-release.sh <repo> --upgrade --dry-run  # an adopted repo: is its release.yml an untouched seed?
```

It detects the ecosystem and stamps in the per-repo glue (the shared logic stays in `bamr87/.github`):

```
.github/workflows/ci.yml        # → bamr87/bamr87 standard-ci.yml@v1   (skipped if the repo already has CI)
.github/workflows/release.yml   # → release-please.yml@v1 → publish.yml@v1   (bamr87/.github)
release-please-config.json      # release-type: ruby | node | python | simple
.release-please-manifest.json   # {".": "<current version>"}
CHANGELOG.md                    # seeded if missing
RELEASING.md                    # per-repo cheat-sheet
```

The templates are the release-pipeline kit, [`templates/release-pipeline/`](../templates/release-pipeline/), versioned in its `VERSION` file. Both callers pin a floating major tag, never a branch (UPS-WORK-10, UPS-QA-40); kit 0.1.0 called `bamr87/.github` at `@main`, which is how bamr87/bashos#97 failed its pin check. `--upgrade` rewrites only `release.yml`, and only when it is byte-identical to the current template or to a shape in the kit's `archive/`; a hand-edited copy is reported and left alone. `bamr87/.github`'s `release-please.yml` is the legacy caller under decision D3 (UPS-REPO-21, warn-only during its rollout); the sdlc kit seeds the hub's own `release-please.yml@v2` instead.

`release-type` is chosen automatically: `ruby` (gemspec), `node` (publishable `package.json`), `python` (pyproject/setup with packaging metadata), else **`simple`** (version + changelog + GitHub Release, no package) — which covers docs, Jekyll, bash, and script repos.

## Per-registry setup

Publishing only runs when the ecosystem is detected **and** its credential exists; otherwise the version bump, changelog, and GitHub Release still succeed. Add credentials as **repo secrets**:

| Registry | Credential | How |
| --- | --- | --- |
| RubyGems | `RUBYGEMS_API_KEY` | `gh secret set RUBYGEMS_API_KEY -R bamr87/<repo>` |
| npm | `NPM_TOKEN` | `gh secret set NPM_TOKEN -R bamr87/<repo>` (published with provenance) |
| PyPI | none | configure **trusted publishing** (OIDC) for the repo on pypi.org |
| GHCR | none | uses the built-in `GITHUB_TOKEN` |
| Opening the release PR | the release app: `RELEASE_APP_CLIENT_ID` + `RELEASE_APP_PRIVATE_KEY` | fanned out from the hub, never set by hand per repo: [The release app](#the-release-app). The release PR runs the CI gate and the tag fires the workflows that listen for it |

## The release app

release-please works through a GitHub App, the **release app**, not a personal access token. The app holds two repository permissions, Contents and Pull requests (read and write), and is installed on every owner in `_data/fleet.yml` `hub.owners`. Each release job mints an installation token for its own repo from two secrets, `RELEASE_APP_CLIENT_ID` and `RELEASE_APP_PRIVATE_KEY`; the token lasts an hour and is revoked when the job ends.

Why an app and not the job's own `GITHUB_TOKEN`, or a PAT:

| Credential | Opens the release PR | The PR runs CI, the tag fires workflows | Expires | Owners it covers |
| --- | --- | --- | --- | --- |
| `GITHUB_TOKEN` | only where the repo setting "Allow GitHub Actions to create and approve pull requests" is on (off in 33 of 40 fleet repos, 2026-11-19) | no: the PR's runs wait for a person to approve them, and its tag fires nothing | with the job | the one repo |
| `RELEASE_PLEASE_TOKEN`, a fine-grained PAT (legacy) | yes | yes | yes, and a person re-mints it | one |
| The release app | yes | yes | no | every owner it is installed on |

`release-please.yml` takes the first of these that is present: the app, then the legacy PAT, then `GITHUB_TOKEN`. The log line `Release credential: …` in the "Find the release credential" step says which one a run used.

### Set it up (once)

Only the maintainer can do the first three steps: they create an app and hand it access to repos.

1. **Register the app.** Open [this pre-filled form](https://github.com/settings/apps/new?name=bamr87-release&description=Opens%20release%20PRs%20and%20tags%20releases%20for%20the%20bamr87%20fleet%20%28release-please%29.&url=https%3A%2F%2Fgithub.com%2Fbamr87%2Fbamr87&public=true&webhook_active=false&contents=write&pull_requests=write). Check before creating: Webhook is not active, Repository permissions show Contents and Pull requests as "Read and write" and nothing else beyond Metadata, and "Any account" is selected (the three organisations cannot install an app that is private to `bamr87`). App names are global, so change the name if it is taken. The app has no server and no callback: installing it on an account gives the holder of its key access to that account's repos, never the reverse.
2. **Generate a private key.** On the app's page, "Generate a private key" downloads a `.pem`. Move it out of any repo, for example to `~/.config/bamr87/release-app.pem`, and `chmod 600` it. Copy the **Client ID** shown at the top of the same page.
3. **Install the app** (Install App, in the app's sidebar) on `bamr87`, `bash-365`, `year-of-ai` and `ai-world-view`, for all repositories or at least every repo that releases.
4. **Point the hub's `.env` at both** (the file is gitignored; the key stays in its own file because a dotenv line cannot hold thirty):

   ```bash
   RELEASE_APP_CLIENT_ID=Iv23…
   RELEASE_APP_PRIVATE_KEY_FILE=~/.config/bamr87/release-app.pem
   ```

5. **Fan them out.** The hub is written first, then every `bamr87/*` repo, the client ID before the key: the key is what arms the app, so no repo is ever left holding a key it cannot use. A value that is not a client ID, or not a whole key, stops the push before anything is written.

   ```bash
   tools/dash secrets push --only RELEASE_APP_CLIENT_ID --only RELEASE_APP_PRIVATE_KEY          # dry run
   tools/dash secrets push --only RELEASE_APP_CLIENT_ID --only RELEASE_APP_PRIVATE_KEY --apply
   ```

6. **The three organisations**, which the fan-out does not reach, take one pair of organisation secrets each (their fleet repos are public, so a Free plan serves them):

   ```bash
   for org in bash-365 year-of-ai ai-world-view; do
     gh secret set RELEASE_APP_CLIENT_ID   --org "$org" --visibility all --body 'Iv23…'    # first: inert alone
     gh secret set RELEASE_APP_PRIVATE_KEY --org "$org" --visibility all < ~/.config/bamr87/release-app.pem
   done
   ```

7. **Check one repo.** Push to its default branch, or run its Release workflow by hand, and read the "Find the release credential" step: it should say `the release app`. The release PR it opens is authored by the app and runs CI without anyone approving it.

Both secrets ride the weekly rotation after that (`token-rotation.yml`), which is what pulls a newly registered repo into line and puts back a copy someone deleted. Neither expires, so the loop never asks for a re-mint.

### A caller under another owner passes the secrets by name

GitHub hands `secrets: inherit` only to a reusable workflow of the caller's own owner. A `bamr87/*` repo inherits and needs no change. A repo under `bash-365`, `year-of-ai` or `ai-world-view` that calls this hub's `release-please.yml` with `secrets: inherit` arrives with nothing, whatever its organisation holds, so its caller names them:

```yaml
jobs:
  release:
    uses: bamr87/bamr87/.github/workflows/release-please.yml@v2
    permissions: { contents: write, pull-requests: write }
    secrets:
      RELEASE_APP_CLIENT_ID: ${{ secrets.RELEASE_APP_CLIENT_ID }}
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

A caller may name a secret only once the tag it pins declares it: against an older `v2`, GitHub rejects the whole workflow before any job starts. So the four callers under the organisations, and the sdlc kit that seeds them, change after the `v2` tag carries this workflow, not with it.

### Rotate the key, retire the PAT

- **Rotate the key:** generate a second key on the app, replace the `.pem`, run the push in step 5 and the loop in step 6, then delete the old key on the app. Both keys are valid in between, so no release run fails.
- **Retire `RELEASE_PLEASE_TOKEN`:** once every repo's release runs say `the release app`, delete the secret (`gh secret delete RELEASE_PLEASE_TOKEN -R <repo>`), then remove its entry from `_data/fleet.yml` `tokens:` and its line from `token-rotation.yml`. Eleven callers still carry a hand-added `preflight` job that tests for the PAT and skips the release without it (README, cv-pro, djangoerp, githubai, gitorio, godotgo, lifehacker.dev, outbox, rewind-arcade, scripts, zpl-viewer); the job's own comment says to drop it once `v2` guards the denial itself, which it does. Remove it from each before deleting the PAT there.

## When the release PR cannot be opened

Opening the release PR is the one step a caller cannot fix from a PR. It needs a credential allowed to create a pull request: the release app, the legacy `RELEASE_PLEASE_TOKEN`, or the repo setting **Settings > Actions > General > Workflow permissions > "Allow GitHub Actions to create and approve pull requests"** so that `GITHUB_TOKEN` may. With none, GitHub answers `POST /pulls` with `GitHub Actions is not permitted to create or approve pull requests` and release-please exits 1 — on every push, indefinitely, while nothing else about the run is wrong.

`release-please.yml` therefore makes two passes over the same config:

| Pass | Inputs | Needs | On failure |
| --- | --- | --- | --- |
| Tag and publish any merged release PR | `skip-github-pull-request: true` | `contents: write`, which every credential has | fails the run — a failure here is a real defect |
| Open or update the release PR | `skip-github-release: true` | permission to create a PR | `continue-on-error`, then the guard below |

The guard re-raises the failure when the app or the PAT **is** provisioned (the denial cannot be the known one, so it is a defect; an expired PAT fails exactly here), or when the caller passes `strict-pr-creation: true`. Otherwise it emits a warning annotation and writes both remedies into the run summary, and the run ends green. Versioning is paused, not broken: release-please keeps its release branch up to date, so the first push after a credential lands opens the PR with everything accumulated since.

Two failures are never downgraded, because each means a setup that someone started and did not finish:

| Run says | Cause | Fix |
| --- | --- | --- |
| `The release app has a key and no client ID` | the key is set and the client ID is not (the reverse is only a warning: the client ID alone is inert) | set the client ID, or pass both by name from a caller under another owner |
| `The release app could not mint a token` | the app is not installed on the repo, the key is not one of the app's, or the app lacks a permission | the run summary lists all three |

Pass `strict-pr-creation: true` from a caller whose credential is provisioned and whose releases must therefore never stop quietly:

```yaml
jobs:
  release:
    uses: bamr87/bamr87/.github/workflows/release-please.yml@v2
    with:
      strict-pr-creation: true
    permissions: { contents: write, pull-requests: write }
    secrets: inherit
```

The app's two secrets and the legacy PAT are declared fleet-scoped in [`_data/fleet.yml`](../_data/fleet.yml) `tokens:` and named in `token-rotation.yml`, so the weekly rotation carries the hub's copies to every `bamr87/*` repo. The history of the denial is [bamr87/bamr87#406](https://github.com/bamr87/bamr87/issues/406).

## Branch protection

Require the CI gate before merge (needs admin):

```bash
tools/protect-branch.sh <repo>           # require CI checks + PR review on the default branch
```

## Reference & status

- **Reference migration:** [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) (`ruby`) — replaced ~1000 lines of bespoke release bash.
- **Pilots:** [zpl-viewer](https://github.com/bamr87/zpl-viewer) (`node`/npm), [fredgar-ai](https://github.com/bamr87/fredgar-ai) (`simple`).
- Adoption + current version per repo is tracked in [`_data/projects.yml`](../_data/projects.yml) (`release:` block) and surfaced on the [dash](https://bamr87.github.io/bamr87/). Run `python3 .claude/skills/run-dash/driver.py releases` for a fleet view.

## FAQ

- **Why a release PR instead of auto-publishing?** Every release is reviewable, and it avoids the `[skip ci]` push-loop the old per-repo scripts needed.
- **No release happened after merge.** Your commits were all `chore:`/`docs:`/etc. — nothing to release. Land a `fix:`/`feat:` or merge the pending release PR.
- **Wrong version computed.** Check the commit types since the last tag and the seed in `.release-please-manifest.json`.

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
tools/adopt-release.sh <repo>            # detect ecosystem, scaffold, open a PR
tools/adopt-release.sh <repo> --dry-run  # build the branch locally, show the diff
```

It detects the ecosystem and stamps in the per-repo glue (the shared logic stays in `bamr87/.github`):

```
.github/workflows/ci.yml        # → ci.yml@main         (skipped if the repo already has CI)
.github/workflows/release.yml   # → release-please.yml@main → publish.yml@main
release-please-config.json      # release-type: ruby | node | python | simple
.release-please-manifest.json   # {".": "<current version>"}
CHANGELOG.md                    # seeded if missing
RELEASING.md                    # per-repo cheat-sheet
```

The scaffolded `ci.yml` still calls `bamr87/.github`'s unused `ci.yml` gate (`templates/release-pipeline/ci.yml`). None of the five current adopters (fredgar-ai, zer0-CMS, zer0-image-generator, zer0-mistakes, zpl-viewer) calls it today; pointing the kit at `standard-ci.yml` is a separate change.

`release-type` is chosen automatically: `ruby` (gemspec), `node` (publishable `package.json`), `python` (pyproject/setup with packaging metadata), else **`simple`** (version + changelog + GitHub Release, no package) — which covers docs, Jekyll, bash, and script repos.

## Per-registry setup

Publishing only runs when the ecosystem is detected **and** its credential exists; otherwise the version bump, changelog, and GitHub Release still succeed. Add credentials as **repo secrets**:

| Registry | Credential | How |
| --- | --- | --- |
| RubyGems | `RUBYGEMS_API_KEY` | `gh secret set RUBYGEMS_API_KEY -R bamr87/<repo>` |
| npm | `NPM_TOKEN` | `gh secret set NPM_TOKEN -R bamr87/<repo>` (published with provenance) |
| PyPI | none | configure **trusted publishing** (OIDC) for the repo on pypi.org |
| GHCR | none | uses the built-in `GITHUB_TOKEN` |
| Release-PR triggers CI | `RELEASE_PLEASE_TOKEN` (PAT) | so the release PR runs the CI gate. **Mandatory** on any repo whose Actions setting `can_approve_pull_request_reviews` is off — there `GITHUB_TOKEN` cannot open the release PR at all (`GitHub Actions is not permitted to create or approve pull requests`), so without it no release is ever cut (fredgar-ai, bamr87/bamr87#97) |

## When the release PR cannot be opened

Opening the release PR is the one step a caller cannot fix from a PR. It needs a credential allowed to create a pull request — either a `RELEASE_PLEASE_TOKEN` secret, or the repo setting **Settings > Actions > General > Workflow permissions > "Allow GitHub Actions to create and approve pull requests"** so that `GITHUB_TOKEN` may. With neither, GitHub answers `POST /pulls` with `GitHub Actions is not permitted to create or approve pull requests` and release-please exits 1 — on every push, indefinitely, while nothing else about the run is wrong.

`release-please.yml` therefore makes two passes over the same config:

| Pass | Inputs | Needs | On failure |
| --- | --- | --- | --- |
| Tag and publish any merged release PR | `skip-github-pull-request: true` | `contents: write`, which `GITHUB_TOKEN` always has | fails the run — a failure here is a real defect |
| Open or update the release PR | `skip-github-release: true` | permission to create a PR | `continue-on-error`, then the guard below |

The guard re-raises the failure when `RELEASE_PLEASE_TOKEN` **is** set (the denial cannot be the known one, so it is a defect), or when the caller passes `strict-pr-creation: true`. Otherwise it emits a warning annotation and writes both remedies into the run summary, and the run ends green. Versioning is paused, not broken: release-please keeps its release branch up to date, so the first push after a credential lands opens the PR with everything accumulated since.

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

`RELEASE_PLEASE_TOKEN` is declared fleet-scoped in [`_data/fleet.yml`](../_data/fleet.yml) `tokens:` and named in `token-rotation.yml`, so once the hub holds a copy the weekly rotation carries it to every repo that releases. Until then the loop reports it and writes nothing. The fleet decision is [bamr87/bamr87#406](https://github.com/bamr87/bamr87/issues/406).

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

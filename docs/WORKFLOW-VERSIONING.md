# Versioning the hub's reusable workflows

Member repos call workflows in this repo by reference (`uses: bamr87/bamr87/.github/workflows/<file>@<ref>`). A reference to `@main` means every merge here changes every caller's CI at once, with no review on the caller's side and no way to roll back one repo. This page defines the tags that make those workflows pinnable, what each kind of version bump promises, and how a release is cut.

The plan this implements is the SDLC harmonization plan, Wave 1 ("tag the reusable workflows"); the rule callers will be measured against is the proposed UPS-WORK-10 (reusable workflows referenced by tag or SHA, never `@main`).

## What is versioned

The tag covers the whole repository, but the compatibility promise below covers only the **public interface**: the files callers reference and the inputs, outputs and behaviour they depend on.

| File | Interface | Callers |
| --- | --- | --- |
| [`.github/workflows/standard-ci.yml`](../.github/workflows/standard-ci.yml) | inputs `node-version`, `python-version`, `ruby-version`; the single `ci` job; `vars.*` toolchain resolution | the `standard-ci` kit (`templates/standard-ci/ci.yml`) |
| [`.github/workflows/fleet-conformance.yml`](../.github/workflows/fleet-conformance.yml) | inputs `kinds`, `tier`, `gate`, `hub-ref`, `python-version`; the `ups-conformance` artifact | the `conformance` kit (`templates/conformance/conformance.yml`) |
| [`tools/conformance.py`](../tools/conformance.py) + [`_data/specs.yml`](../_data/specs.yml) | the checker and the rows it enforces, checked out by `fleet-conformance.yml` at `hub-ref` | through `fleet-conformance.yml` |
| [`.github/workflows/site-quality.yml`](../.github/workflows/site-quality.yml) + [`.github/site-quality/`](../.github/site-quality/) + [`templates/site-quality/site-quality.schema.json`](../templates/site-quality/site-quality.schema.json) | inputs `mode`, `config`, `base-url`, `source`, `build-command`, `build-command-token`, `theme-cache`, `expired-allowlist-level`, `gate`, `artifact-name`, `retention-days`, `hub-ref`, `node-version`, `ruby-version`; outputs `status`, `errors`, `warnings`, `theme-repo`, `theme-sha`, `report-artifact`; the report artifact and `report.json` (`site-quality-report/v1`); the config schema (`schema: site-quality/v1`) and its report-only defaults (the axe-core minor/major bumps that can add rules are released by hand: Dependabot ignores them); the pinned runtime (a runtime bump that can fail a gated caller, such as new axe rules, is major) | the `site-quality` kit (`templates/site-quality/site-quality.yml`); the org hubs' weekly url-mode scans |

Other hub files consumed by reference (`fleet-verify.yml`, `ai-lane.yml`, `.github/actions/claude-run`, `.github/actions/claude-auth`) ride along on the same tags but are not yet covered by the promise; they are added to the table, and to `CHANGELOG.md`, when their owners adopt it.

## Tag scheme

| Tag | Kind | Moves? | Use it when |
| --- | --- | --- | --- |
| `vX.Y.Z` (e.g. `v1.0.0`) | immutable release | never | you want an exact, reproducible gate (Dependabot can bump it for you) |
| `vX` (e.g. `v1`) | floating major | moved to each new `vX.Y.Z` | you want compatible fixes automatically, and never a breaking change |
| `main` | branch | every merge | pre-release testing only; the hub calls its own workflows by local path (`./.github/workflows/…`), not by ref |

Fleet callers pin the floating major:

```yaml
jobs:
  ci:
    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@v1
    secrets: inherit
```

```yaml
jobs:
  conformance:
    uses: bamr87/bamr87/.github/workflows/fleet-conformance.yml@v1
    with:
      hub-ref: v1   # keep the checker on the same version as the workflow
```

`fleet-conformance.yml` checks out the spec and checker separately, at `hub-ref` (default `main`). A caller that pins the workflow but not `hub-ref` still gets the checker from `main`, so pass the same ref to both.

Migrating the existing `@main` callers to `@v1` is a separate, later change (one fan-out through `templates/standard-ci/` and `templates/conformance/`); this page only makes the tags available.

## What each bump promises

Versions follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html), applied to the interface above.

| Bump | Allowed changes |
| --- | --- |
| **Major** (`v2.0.0`; the floating `v1` stays where it is) | Removing or renaming an input, output or artifact; changing an input's default; requiring a new secret, variable or permission; any change that can turn a caller red without the caller changing anything, such as a stricter gate or a new failure condition. |
| **Minor** (`v1.1.0`; `v1` moves) | New optional inputs or outputs; new steps that can only fail when the caller opts in; new advisory (non-gating) checks or report fields. |
| **Patch** (`v1.0.1`; `v1` moves) | Bug fixes that cannot turn a green caller red; documentation and comment changes; dependency bumps of actions used inside the workflow at the same major. |

When in doubt, treat the change as major: a new major costs callers one Dependabot PR, while a breaking change under `v1` breaks every caller on the same day.

## Moving callers to a new major

A new major never moves existing callers. The previous floating major is frozen at its last release, so a caller on `@v1` keeps exactly the behaviour it had.

When a major ships, each caller is tried on it, one PR per repo through the caller templates. A caller that stays green moves to `@vN`. A caller that turns red pins the previous major (`@v1`) until its own failures are fixed, and then moves.

The first planned major is `v2.0.0`, for #310: `standard-ci` stops ignoring failed dependency installs (`|| true`), which can turn a green caller red. `v1` keeps the lenient installs.

## Cutting a release

Releases are cut by hand from `main` until a release automation is adopted for the hub. Tags are created only after the change is merged, never from a PR branch.

1. Move the `## [Unreleased]` entries in [`CHANGELOG.md`](../CHANGELOG.md) under a new `## [X.Y.Z] - YYYY-MM-DD` heading (in a PR, like any other change).
2. After it merges, tag the merge commit and push the immutable tag:

   ```bash
   git fetch origin && git checkout <merge-sha>
   git tag -a vX.Y.Z -m "vX.Y.Z — reusable workflow interface"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --verify-tag --title "vX.Y.Z" --notes "See CHANGELOG.md"
   ```

3. For a minor or patch release, move the floating major to the same commit:

   ```bash
   git tag -fa vX -m "vX → vX.Y.Z" vX.Y.Z^{}
   git push --force origin refs/tags/vX
   ```

   For a major release, create the new `vX` instead and leave the previous major where it is.

**Rollback.** If a minor or patch release breaks callers, point `vX` back at the previous `vX.Y.Z` (step 3 with the older version) and fix forward in a new patch. Never delete or move an immutable `vX.Y.Z` tag.

## See also

- [`CHANGELOG.md`](../CHANGELOG.md): what changed in each version of the interface.
- [`RELEASES.md`](RELEASES.md): the release-please pipeline that member repos use for their own versions.
- [`specs/QUALITY.md`](../specs/QUALITY.md): UPS-QA-20, the thin-caller rule these workflows serve.

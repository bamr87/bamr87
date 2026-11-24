# Versioning the hub's reusable workflows

> How the reusable workflows are tagged (`vX.Y.Z` plus a floating `vX`), what each bump promises, and how a release is cut and rolled back.

Member repos call workflows in this repo by reference (`uses: bamr87/bamr87/.github/workflows/<file>@<ref>`). A reference to `@main` means every merge here changes every caller's CI at once, with no review on the caller's side and no way to roll back one repo. This page defines the tags that make those workflows pinnable, what each kind of version bump promises, and how a release is cut.

The plan this implements is the SDLC harmonization plan, Wave 1 ("tag the reusable workflows"); the rule callers will be measured against is the proposed UPS-WORK-10 (reusable workflows referenced by tag or SHA, never `@main`).

## What is versioned

The tag covers the whole repository, but the compatibility promise below covers only the **public interface**: the files callers reference and the inputs, outputs and behaviour they depend on.

| File | Interface | Callers |
| --- | --- | --- |
| [`.github/workflows/standard-ci.yml`](../.github/workflows/standard-ci.yml) | inputs `node-version`, `python-version`, `ruby-version`, `skip-docs-only`, `docs-paths`, `timeout-minutes`; the `changes` and `ci` jobs; `vars.*` toolchain resolution | the `standard-ci` kit (`templates/standard-ci/ci.yml`) |
| [`.github/workflows/fleet-conformance.yml`](../.github/workflows/fleet-conformance.yml) | inputs `kinds`, `tier`, `gate`, `hub-ref`, `python-version`; the `ups-conformance` artifact | the `conformance` kit (`templates/conformance/conformance.yml`) |
| [`tools/conformance.py`](../tools/conformance.py) + [`_data/specs.yml`](../_data/specs.yml) | the checker and the rows it enforces, checked out by `fleet-conformance.yml` at `hub-ref` | through `fleet-conformance.yml` |
| [`.github/workflows/site-quality.yml`](../.github/workflows/site-quality.yml) + [`.github/site-quality/`](../.github/site-quality/) + [`templates/site-quality/site-quality.schema.json`](../templates/site-quality/site-quality.schema.json) | inputs `mode`, `config`, `base-url`, `source`, `build-command`, `build-command-token`, `theme-cache`, `expired-allowlist-level`, `gate`, `artifact-name`, `retention-days`, `hub-ref`, `node-version`, `ruby-version`; outputs `status`, `errors`, `warnings`, `theme-repo`, `theme-sha`, `report-artifact`; the report artifact and `report.json` (`site-quality-report/v1`); the config schema (`schema: site-quality/v1`) and its report-only defaults (the axe-core and @lhci/cli minor/major bumps that can add rules or move Lighthouse are released by hand: Dependabot ignores them); the pinned runtime (a runtime bump that can fail a gated caller, such as new axe rules, is major) | the `site-quality` kit (`templates/site-quality/site-quality.yml`); the org hubs' weekly url-mode scans |
| [`.github/workflows/spec-gate.yml`](../.github/workflows/spec-gate.yml) + [`templates/spec-driven/tools/`](../templates/spec-driven/) | inputs `strict`, `backlog-lint-base`, `stale-report`, `stale-days`, `file-issue`, `issue-label`, `issue-title`, `hub-ref`, `python-version`; output `stale`; the job summary; the kit tools checked out at `hub-ref` | the `spec-driven` kit (`templates/spec-driven/workflows/spec-gate.yml`), law-ai's `ci.yml` |

Other hub files consumed by reference (`fleet-verify.yml`, `ai-lane.yml`, `pr-review.yml`, `pr-ai-review.yml`, `.github/actions/claude-run`, `.github/actions/claude-auth`) ride along on the same tags but are not yet covered by the promise; they are added to the table, and to `CHANGELOG.md`, when their owners adopt it.

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

The kits seed callers at the floating major: `templates/standard-ci/` and `templates/sdlc/` (`release-please.yml`) since `v2.0.0`, and `templates/conformance/` (0.2.0) and `templates/verify/` (0.3.0) since `v2.1.0`, each passing `hub-ref: v2` so the tooling it checks out is the same version. A repo still on an `@main` caller moves with `tools/fanout.sh --kit standardize --artifacts conformance --upgrade` (or `--kit verify --upgrade`), which repins only an untouched machine seed.

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

## Pins resolve before they ship

A caller that pins a ref without the file it names fails at startup: the run has no jobs, and nothing in the caller's repository says why. law-ai's CI on `main` failed that way from 2026-10-30, because its `ci.yml` called `spec-gate.yml@v2` while `v2` still pointed at 2.0.0, which predates the file; the `spec-driven` kit's caller template carried the same pin until v2.1.0 was cut (#610). Two rules follow, and [`hub_refs.py`](../.github/scripts/dash-gen/hub_refs.py) checks both.

- **A kit template pins only a ref that contains its target.** A new reusable workflow or action ships in a release, and `vX` moves to it, before any template under `templates/` pins it at `@vX`. Drift check (q) resolves every hub pin in `templates/` against the hub's tags on every pull request, offline, and warns on one that does not resolve. `tools/fanout.sh` resolves the kit's caller templates before it clones a target: its dry run names an unresolved pin, and `--apply` refuses to run until the pin resolves.
- **Before you tag, list what the release must carry.** Run `python3 .github/scripts/dash-gen/hub_refs.py check templates` for the kit templates and `python3 .github/scripts/dash-gen/hub_refs.py fleet` for the fleet's callers, as the daily harness scan recorded them (`_data/harness_registry.yml` `hub_refs`). Each broken pin names its fix. When the file is on `main` under `[Unreleased]`, the fix is this release: cut `vX.Y.0` and move `vX` (steps 2 and 3 below), then run the check again with fresh tags (`git fetch --no-tags --depth=1 origin '+refs/tags/v*:refs/tags/v*'`). Every pin should read `ok`.

A pin reads `ok`, `ref-missing` (the hub has no such ref), `file-missing-at-ref` (the ref exists but lacks the file) or `unverified`. `unverified` covers a tag missing from the local clone and any GitHub answer other than a 404, and it is never counted as broken or as clean. Repinning a caller to a SHA or to `@main` is only a stopgap: a SHA pin breaks drift check (k), and an `@main` pin breaks UPS-WORK-10. For a caller on a floating major, the fix is the hub release.

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

4. Check the pins: `python3 tools/test_template_pins.py` resolves every `bamr87/bamr87` and `bamr87/.github` pin in `templates/` and in the hub's own workflows and actions against the tags GitHub now serves, and fails on any pin whose ref lacks the file it names.

**Rollback.** If a minor or patch release breaks callers, point `vX` back at the previous `vX.Y.Z` (step 3 with the older version) and fix forward in a new patch. Never delete or move an immutable `vX.Y.Z` tag.

**Pins follow the tag.** A caller pins a tag only once that tag carries the file: a new workflow or action ships in a release (and `vX` moves) before a template, or a hub reusable workflow, pins it at `@vX`. `tools/test_template_pins.py` runs in `python-tests.yml`, so a pull request that pins ahead of the tag fails, and so does the next run after a rollback that takes a pinned file away. From 2026-10-26 until v2.1.0 the `spec-driven` kit pinned `spec-gate.yml@v2` while `v2` predated the file, and law-ai's CI, pinned the same way, failed at startup ([#457](https://github.com/bamr87/bamr87/issues/457)).

## See also

- [`CHANGELOG.md`](../CHANGELOG.md): what changed in each version of the interface.
- [`RELEASES.md`](RELEASES.md): the release-please pipeline that member repos use for their own versions.
- [`specs/QUALITY.md`](../specs/QUALITY.md): UPS-QA-20, the thin-caller rule these workflows serve.

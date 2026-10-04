# UPS-QA — Quality gates

> One lint/format/test/CI/release story per stack, so a green check means the same thing in every repo.

Evidence base: 20 repos are byte-identical callers of the reusable `standard-ci.yml`; 14 carry bespoke `ci.yml`. Ruff is the linter in 8 of 9 Python repos; pytest config lives in three different places; React apps span Vite 6/7/8 and vitest 3/4 plus one Cypress; VS Code extensions use four different bundler/test combinations; Prettier config exists in 3 repos. `standard-ci` treats "no tests collected" as a pass. Release-please is adopted in 5 repos; `templates/release-pipeline/` has no `VERSION`.

## Formatting and linting

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-01 | MUST | all | `.editorconfig` is the hub copy (REPO-17). Formatting is enforced by a formatter, not by review: **Prettier** for JS/TS/JSON/YAML/MD (hub `.prettierrc`: single quotes, semi, es5 commas, width 100, `proseWrap: never`), **ruff format** for Python, **shfmt** optional for Bash, **rubocop** for Ruby gems. | config file present; `format:check` script or pre-commit hook | `templates/lint/` (gap) |
| UPS-QA-02 | MUST | all with Python | **ruff** is the only Python linter (`[tool.ruff]` in `pyproject.toml`, line length 120, `select = ["E","F","I","B","UP"]`); black/flake8/isort are retired except where the hub scopes them to `projects/README`. | pyproject section | — |
| UPS-QA-03 | MUST | all with JS/TS | ESLint **flat config** (`eslint.config.js`) with `typescript-eslint` recommended and `eslint-config-prettier` last; no `.eslintrc*`. | file present | — |
| UPS-QA-04 | MUST | all with Bash | `shellcheck --severity=warning` clean; every script `set -euo pipefail`, quotes expansions, and carries the house header. | CI step | `standard-ci` (Bash detection — gap) |
| UPS-QA-05 | MUST | all | Markdown is one paragraph per line (`markdown-oneline.yml` self-healing gate, vendored `unwrap-prose.py`); markdownlint with the hub's disabled-rule set (MD013/MD033/MD041 off). | gate present | `tools/fanout.sh --kit prose` |
| UPS-QA-06 | SHOULD | all | `.pre-commit-config.yaml` runs the same checks locally (trailing whitespace, EOF, yaml/json, large files, private keys, markdownlint, shellcheck, the formatter). `rev:` pins are the sanctioned exception to always-latest. | file present | hub `.pre-commit-config.yaml` as reference |
| UPS-QA-07 | MUST | all with TS | `strict: true`; no `as any`, `@ts-ignore`, `@ts-expect-error` without a linked issue; no `# type: ignore` in Python without a reason. | grep-able | — |

## Tests

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-10 | MUST | app, api, lib, cli, ext | A unit-test runner is configured and **collects at least one test**; the CI gate fails on zero tests for these kinds (today's exit-code-5 pass is retained only for `site`/`content`). | runner config + ≥1 test | `standard-ci` change (gap) |
| UPS-QA-11 | MUST | all with Python | `pytest`, configured in `[tool.pytest.ini_options]` of `pyproject.toml` (not `pytest.ini`/`setup.cfg`), tests in `tests/`, AAA pattern, `pytest-cov` reporting. | pyproject section | — |
| UPS-QA-12 | MUST | all with JS/TS (non-ext) | **vitest** + Testing Library for units; **Playwright** for e2e and visual. Cypress is retired (migrate `cv-builder-pro`). Tests colocated as `*.test.ts(x)` or under `tests/`. | `vitest.config.ts`, `playwright.config.ts` | — |
| UPS-QA-13 | MUST | ext | VS Code extensions: **esbuild** bundler, **vitest** for unit tests, `@vscode/test-electron` for integration; one shared `extension.config` shape (lift from `vs-sonic-pi`). | files present | `templates/vscode-extension/` (gap) |
| UPS-QA-14 | SHOULD | app, api, lib | Coverage floor **70 %** lines on changed files, reported in CI; not a hard gate until the fleet audit sets per-repo baselines. | coverage report artifact | — |
| UPS-QA-15 | MUST | site | Jekyll sites run `jekyll build --strict_front_matter` plus `htmlproofer` (internal links, images) in CI; theme repos additionally run the Playwright visual suite. | CI step | `standard-ci` (Ruby branch) |
| UPS-QA-16 | SHOULD | app, site | The UX audit gate (FE-60) runs in CI for every UI surface. | CI step | `templates/ux-audit/` (gap) |
| UPS-QA-17 | MUST | api | Contract tests: the OpenAPI document is generated in CI and diffed against the committed one; a breaking diff fails without a version bump (BE-30). | CI step | — |

## Verification

Tests prove the code; verification proves the product — by using it the way a person does. Evidence base: zer0-mistakes holds a feature registry (`features/features.yml`, 84 entries with tests/provenance) plus an evidence standard (`test/visual/evidence-kit.mjs`, `.github/skills/visual-evidence`: regression test + before/after screenshots per UI change); it-journey and barodybroject carry the same registry shape with 2–3 entries; cv-builder-pro documents features in prose only; every other repo has no index at all, so an agent entering it has no map of what it does or what proves it. The hub's `tools/issue-evidence.sh` already screenshots issue reproductions in a sandbox. The rows below make that one contract: an index every agent reads, scenarios both a runner and an agent execute, evidence linked back, graded fleet-wide at `/features/`.

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-50 | MUST | site, app, api, cli, ext | A **feature index** `features/features.yml` (`schema: features/v1`; the legacy zer0/it-journey shape is accepted as-is) lists every user-facing capability with `surface`, `link`, `docs`, and the `tests` / `scenarios` / `evidence` that prove it; `{na: reason}` waives coverage explicitly. `tools/features_index.py check` validates it — bad or duplicate ids fail, dangling paths warn. | file present + valid | `templates/verify/` (`tools/fanout.sh --kit verify`) |
| UPS-QA-51 | MUST | site, app | The **verify kit** is present: `verify/verify.yml` (how to run the app like a user), ≥1 `verify/scenarios/*.yml` user scenario (`scenario/v1`), `verify/runner.mjs`, and `.github/workflows/verify.yml` calling the reusable `fleet-verify.yml` (advisory until `gate: true`). zer0-mistakes' `test/visual/evidence-kit.mjs` + `visual-evidence` skill satisfy this as the precedent. | files present | `templates/verify/` |
| UPS-QA-52 | SHOULD | site, app | Every PR that changes a user-visible surface ships **evidence**: a scenario that replays the user path plus `test/evidence/<slug>/` (screenshots at ≥2 viewports, `report.json`, a README saying what each image proves) linked from the feature entry — or the `skip-evidence` label with a reason. The `verify` label requests the Claude Code pass that drives the live app through the Playwright MCP; the workflow, never the agent, posts its report. | PR contents | `fleet-verify.yml` + the `verify-feature` skill |
| UPS-QA-53 | SHOULD | site, app | Every implemented `surface: ui` feature is **covered** (≥1 test or scenario that exists on disk) and carries a `verified:` stamp (`date`, `by: agent\|human\|ci`, `run`); the fleet index (`_data/features_index.yml`, rendered at `/features/`) grades coverage from files, not claims, and lists the gaps as attention items. | `dash features coverage` | `verify/runner.mjs --stamp`, the agent pass |

## Site quality

> **Draft, `rollout: warn`** (Platform Architect review). Until the marker is removed from [`QUALITY.contract.yml`](QUALITY.contract.yml), a failing row is reported as a warning and never gates.

Measured quality for Jekyll sites, run the same way everywhere: Lighthouse CI, axe-core at 390 px and 1366 px, and pa11y contrast (WCAG 1.4.3) through the reusable `bamr87/bamr87/.github/workflows/site-quality.yml`, graded by each repo's own `.github/site-quality.yml`. Evidence base: lifehacker.dev#683 and it-journey#790 each built the same scan independently and both went green. Before them the fleet survey (2026-10-03) found no repo running Lighthouse or performance budgets and only two running axe (zer0-mistakes, law-ai); every other Jekyll site's CI is `jekyll build`. lifehacker.dev's required `verify` check stayed green on a stale cached theme while its nightly failed at "Build (fresh theme)" for 15 nights straight, which is why the reusable workflow builds against a theme resolved to a commit SHA. These rows make the scan the measurable half of UPS-FE-50 (WCAG AA) and UPS-FE-53 (Lighthouse budgets). The workflow's runtime (`.github/site-quality/` in the hub) pins exactly with a committed `package-lock.json`, moved by a Dependabot `npm` entry, so every caller scans with the same tools: the hub-only exception that UPS-QA-40 and UPS-QA-41 now state, with the paths declared in `QUALITY.contract.yml` (`sanctioned_lockfiles`, `sanctioned_dependabot`). The rows bind a Jekyll site, meaning a repo with a root `_config.yml`; any other repo passes them unbound.

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-60 | SHOULD | site (Jekyll: root `_config.yml`) | The site carries a workflow calling `bamr87/bamr87/.github/workflows/site-quality.yml` with a ref that satisfies the UPS-WORK-10 rule (`@vN`, `@vX.Y.Z` or a full SHA; the kit pins `@v1`; never a branch or a custom tag such as `site-quality-v1`), in `mode: build`, so the site is scanned as built against a fresh theme resolved to a commit SHA. | caller present + pinned | `templates/site-quality/` (`tools/fanout.sh --kit site-quality`) |
| UPS-QA-61 | SHOULD | site (Jekyll: root `_config.yml`) | Its config (`.github/site-quality.yml`, or the caller's `config:` input) validates against `templates/site-quality/site-quality.schema.json`: `schema: site-quality/v1` (a required const, like `schema: sdlc/v1`), dates quoted, and every allowlist entry carries `rule`, `selector` and/or `page`, `reason`, `issue` (a link) and `until: "YYYY-MM-DD"`; a `page` of `*` or a prefix ending in `*` also needs a `selector` (a CSS selector, matched in the browser). Every threshold lives in this file; the workflow's defaults only report. | schema-valid config | `site-quality.template.yml` |
| UPS-QA-62 | SHOULD | site (Jekyll: root `_config.yml`) | No allowlist entry is past its `until` date. During rollout the workflow reports an expired entry as a warning (`allowlist.on_expired: warn`); the level moves to `error` through the config or the `expired-allowlist-level` input, not through this row. | no expired entries | renew the entry with a reason, or fix the linked issue and delete it |
| UPS-QA-63 | SHOULD | site (Jekyll: root `_config.yml`) | Every run uploads its reports as an artifact (`report.json` in `site-quality-report/v1`, Lighthouse HTML/JSON, raw axe and pa11y results) and writes the job summary, including the resolved theme ref. Nothing disables the upload. | the reusable workflow's upload step | `site-quality.yml` (reusable) |

## CI

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-20 | MUST | all except fork | `ci.yml` is a thin caller of the fleet's one shared gate, the hub's reusable `bamr87/bamr87/.github/workflows/standard-ci.yml`, at a pinned ref (UPS-WORK-10). Extra gates (CodeQL, e2e, …) live in their own workflows beside it. `bamr87/.github`'s `ci.yml` is retired (decision D3); a caller of it fails. Bespoke `ci.yml` is a deviation with a reason. | caller of `standard-ci.yml` | `tools/fanout.sh --artifacts ci` (`templates/standard-ci/ci.yml`), `tools/adopt-release.sh` |
| UPS-QA-21 | MUST | all | Toolchain versions resolve caller input → repo `vars.*` → fleet default (`_data/fleet.yml` `toolchain:`). No per-repo version pins in workflows. | grep | `dash config sync` |
| UPS-QA-22 | MUST | all | Actions ride major tags (`@vN`); `permissions:` is declared and minimal; `timeout-minutes` set; `concurrency` cancels superseded runs on PRs; no workflow ends in a bare `git push` to a protected branch; `needs:` over `workflow_run`; `actionlint` clean. | hub workflow standards | hub `.github/workflows/README.md` |
| UPS-QA-23 | MUST | all with `action.yml` | Composite action manifests contain no `${{ }}` in `description:` prose (drift check (l)). | check | — |
| UPS-QA-24 | SHOULD | all | Branch protection on the default branch requires the CI gate. | `tools/protect-branch.sh` | hub tool |

## Commits, branches, releases

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-30 | MUST | all | Conventional Commits `type(scope): description`; types `feat fix docs style refactor test chore perf ci build`. Bot commits use the fleet bot identity and the noreply email. | commit history | — |
| UPS-QA-31 | MUST | all | Default branch is `main`; work branches `feature/ fix/ docs/ refactor/ test/ chore/`; automation branches use their declared prefixes (`agent/issue-*`, `ai-evolution/*`, `chore/standardize-baseline`). | branch names | — |
| UPS-QA-32 | MUST | app, api, lib, cli, ext | **release-please** manages versions and `CHANGELOG.md` (`release-type` per ecosystem, `simple` for the rest); `release.yml` calls the shared publish workflow; registry `release:` block filled. Kit gains `VERSION` + `archive/` like every other kit. | files present | `tools/adopt-release.sh`, `templates/sdlc/release/` |
| UPS-QA-33 | MUST | site, content | Sites and content repos tag releases via release-please `simple` so the CHANGELOG exists (UPS-REPO-21, decision D5); publishing is Pages, not a registry. | config present | `templates/sdlc/release/release-please-config.simple.json` |
| UPS-QA-34 | MUST | all | Submodule rule: commit and push in the project repo first; the hub bumps the pointer. Never bundle several submodules in one PR. | `SUBMODULES.md` | — |

## Dependencies

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-40 | MUST | all | Always-latest: no exact pins, no ceilings, no committed lockfiles; floors (`>=`) are fine. Exceptions: GitHub Actions and reusable workflows referenced at `@vMAJOR`, `@vMAJOR.MINOR.PATCH` or a full 40-character SHA (optionally with a `# vX.Y.Z` comment), never a branch such as `@main`, with local `./` paths exempt (the same ref rule as UPS-WORK-10); pre-commit `rev:`; fleet toolchain versions; and, in the hub only, the runtime of a hub reusable workflow kept under `.github/` (today `.github/site-quality/`, the runtime of `site-quality.yml`), which pins exactly in its `package.json` and commits its lockfile so every caller runs the same tools. Those paths are declared once in `QUALITY.contract.yml` `sanctioned_lockfiles`; a path under `templates/` never qualifies, fan-out never copies one into a member repo, and no member repo can claim the exception. | drift checks (j)/(k) | `tools/unpin-deps.sh`, `deps-fanout.yml` |
| UPS-QA-41 | MUST | all | Dependabot for `github-actions` weekly, grouped, `ci` prefix; no package-ecosystem entries (always-latest makes them redundant), except, in the hub only, the entry that moves each sanctioned runtime's exact pins (`QUALITY.contract.yml` `sanctioned_dependabot`). | `.github/dependabot.yml` | `templates/community/.github/dependabot.yml` |
| UPS-QA-42 | SHOULD | app, api | A `supply-chain` CI step runs the ecosystem audit (`npm audit --audit-level=high`, `pip-audit`, `bundle audit`) as advisory; findings flow to the fleet-pulse doctor. | CI step | `standard-ci` change (gap) |

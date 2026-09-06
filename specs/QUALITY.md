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

## CI

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-20 | MUST | all except fork | `ci.yml` is a thin caller of a reusable workflow: `standard-ci.yml@main` (experiment/content tiers) or `bamr87/.github` `ci.yml@main` (active tier, six jobs incl. CodeQL). Bespoke `ci.yml` is a deviation with a reason. | byte-identical to kit, or stamped | `tools/fanout.sh --artifacts ci` |
| UPS-QA-21 | MUST | all | Toolchain versions resolve caller input → repo `vars.*` → fleet default (`_data/fleet.yml` `toolchain:`). No per-repo version pins in workflows. | grep | `dash config sync` |
| UPS-QA-22 | MUST | all | Actions ride major tags (`@vN`); `permissions:` is declared and minimal; `timeout-minutes` set; `concurrency` cancels superseded runs on PRs; no workflow ends in a bare `git push` to a protected branch; `needs:` over `workflow_run`; `actionlint` clean. | hub workflow standards | hub `.github/workflows/README.md` |
| UPS-QA-23 | MUST | all with `action.yml` | Composite action manifests contain no `${{ }}` in `description:` prose (drift check (l)). | check | — |
| UPS-QA-24 | SHOULD | all | Branch protection on the default branch requires the CI gate. | `tools/protect-branch.sh` | hub tool |

## Commits, branches, releases

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-30 | MUST | all | Conventional Commits `type(scope): description`; types `feat fix docs style refactor test chore perf ci build`. Bot commits use the fleet bot identity and the noreply email. | commit history | — |
| UPS-QA-31 | MUST | all | Default branch is `main`; work branches `feature/ fix/ docs/ refactor/ test/ chore/`; automation branches use their declared prefixes (`agent/issue-*`, `ai-evolution/*`, `chore/standardize-baseline`). | branch names | — |
| UPS-QA-32 | MUST | app, api, lib, cli, ext | **release-please** manages versions and `CHANGELOG.md` (`release-type` per ecosystem, `simple` for the rest); `release.yml` calls the shared publish workflow; registry `release:` block filled. Kit gains `VERSION` + `archive/` like every other kit. | files present | `tools/adopt-release.sh` |
| UPS-QA-33 | MUST | site, content | Sites and content repos still tag releases via release-please `simple` so the CHANGELOG exists; publishing is Pages, not a registry. | config present | `tools/adopt-release.sh` |
| UPS-QA-34 | MUST | all | Submodule rule: commit and push in the project repo first; the hub bumps the pointer. Never bundle several submodules in one PR. | `SUBMODULES.md` | — |

## Dependencies

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-QA-40 | MUST | all | Always-latest: no exact pins, no ceilings, no committed lockfiles; floors (`>=`) are fine. Exceptions: Actions `@vN`, pre-commit `rev:`, fleet toolchain versions. | drift checks (j)/(k) | `tools/unpin-deps.sh`, `deps-fanout.yml` |
| UPS-QA-41 | MUST | all | Dependabot for `github-actions` weekly, grouped, `ci` prefix; no package-ecosystem entries (always-latest makes them redundant). | `.github/dependabot.yml` | `templates/community/` (gap) |
| UPS-QA-42 | SHOULD | app, api | A `supply-chain` CI step runs the ecosystem audit (`npm audit --audit-level=high`, `pip-audit`, `bundle audit`) as advisory; findings flow to the fleet-pulse doctor. | CI step | `standard-ci` change (gap) |

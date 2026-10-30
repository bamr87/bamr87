# Workflows

The hub's 31 GitHub Actions workflows, in four groups: the **daily loops** that keep the fleet running, the **gates** that check the hub's own changes, the **fan-outs** that push kits down into fleet repos, and the **reusable workflows** member repos call by reference. Every loop is assembled from the shared composite actions in [`../actions/`](../actions/): `resolve-fleet-token` (probe the PAT, export `GH_TOKEN`), `utilities/publish-data` (never a bare push), `utilities/upsert-issue` (one tracking issue per concern), and `claude-auth` + `claude-cost` (the credential order and the spend readout around every `claude-code-action` step).

All times are UTC, all crons are declared in [`_data/fleet.yml`](../../_data/fleet.yml) `schedule:` (`test_schedule.py` holds them equal), and none fires on the hour.

## Daily and weekly loops

| Workflow | When | What it does |
| --- | --- | --- |
| `token-rotation.yml` | Mon 02:07, dispatch | **The credential loop.** Probes `secrets:write`, surveys every fleet repo's secret age from GitHub's `updated_at`, re-mints `CLAUDE_CODE_OAUTH_TOKEN` when the refresh grant is provisioned, and propagates the hub's value **hub-first** to every copy that is missing or past `max_age_days`. `report` keeps one tracking issue when a human has to run `claude setup-token`. Ledger: `_data/token_rotation.yml` (names and ages, never values). [TOKEN-ROTATION.md](../../docs/TOKEN-ROTATION.md) |
| `update-submodules.yml` | daily 03:07, dispatch | Bumps submodule pointers up into the hub and publishes them straight to `main` through `publish-data` (falls back to the stable branch `chore/update-submodules` if a ruleset refuses). `[skip ci]`. |
| `repo-scout.yml` | daily 04:37, dispatch | **The proactive issue loop**, repo-evolution's sibling: that one writes code, this one writes tickets for `issue-pipeline.yml` to intake the same day. `plan` (`dash-gen scout`) rotates over the owned, non-archived registry repos (opt-out `scout: false`) and writes each a brief; `scout` runs one Sonnet agent per repo on a checkout with no persisted credentials and no GitHub token, writing only `.scout/proposals.json`; `file` (`dash-gen scout-file`, the only writer) validates, dedupes, caps and files labelled issues. New loop, so the cron runs only while `vars.REPO_SCOUT_ENABLED` is `true`. [SCOUT.md](../../docs/SCOUT.md) |
| `reconcile-registry.yml` | daily 05:07, dispatch | Reconciles `_data/projects.yml` with GitHub (renames, deletions, branches). Authoritative fixes and the regenerated README `AUTO:projects` span go into one PR opened with the probed PAT (so it gets CI); advisory drift becomes one tracking issue. |
| `fleet-pulse.yml` | daily 05:37, dispatch | **The daily loop.** `pulse` gathers every fleet signal (Actions analytics, Claude usage, engagements, the prior-day digest, triage, the harness inventory, features index, scorecard), publishes them in one `[skip ci]` commit, and ranks one remediation queue. `doctor` (Opus) reads each queued workflow's logs and opens a draft fix PR in the hub or the owning repo, or one hub issue when a fix is not safe. [DAILY-ANALYSIS.md](../../docs/DAILY-ANALYSIS.md) |
| `api-keys.yml` | daily 06:47, dispatch | **The Anthropic API key watch.** Judges every deployed `ANTHROPIC_API_KEY` (ledger `_data/api_keys.yml`) against the 7-day policy with `CLAUDE_CONSOLE_TOKEN`, proves the hub's own key with one cheap call, and keeps one issue open (filed with `github.token`) while a key needs a human. Never rotates; rotation is `dash keys rotate --apply`. |
| `issue-pipeline.yml` | daily 07:37, dispatch | **The issue loop.** `scan` derives each open fleet issue's stage from its labels and writes one work order per tier. `tier1` builds an evidence bundle in an isolated environment ([`tools/issue-evidence.sh`](../../tools/issue-evidence.sh)) and rewrites the issue into a spec; `tier2` implements a ready issue as a draft PR; `tier3` drives that PR to mergeable. State is labels, so a missed run costs latency, not a stuck issue. Never merges. [ISSUE-PIPELINE.md](../../docs/ISSUE-PIPELINE.md) |
| `schema-vendor.yml` | Mon 08:07, dispatch | The upward half of the schema loop: grades the hub's vendored SCHEMA files against [bamr87/SCHEMA](https://github.com/bamr87/SCHEMA)'s `DISTRIBUTION.yml`. Strict-parity drift is re-vendored in a PR; reflowed-file drift becomes an issue, never an overwrite. |
| `backlog-fanout.yml` | daily 08:27, dispatch | **Backlog fan-out** (HUB-027): pending hub issues, unserved PRD requirements and unshipped catalog features become one idempotent `backlog/<item>` PR in each repo they apply to (`tools/fanout.sh --kit backlog`). Scheduled runs stay dry-run until `_data/backlog_fanout.yml` says `apply: true`. [BACKLOG-FANOUT.md](../../docs/BACKLOG-FANOUT.md) |
| `build-dash.yml` | daily 08:37, push `main` (site paths), PR (build only), dispatch | Builds the public site, the Harness Console's page built static with its API snapshot and the machine API, and deploys it to Pages, the hub's only Pages surface. The cron runs after the morning's last data push, because those carry `[skip ci]`. [CONSOLE-PAGES.md](../../docs/CONSOLE-PAGES.md) |
| `repo-evolution.yml` | Mon 10:37, dispatch | **The proactive loop.** `plan` picks each opted-in (`auto_evolve: true`), owned, unarchived submodule with no evolution PR still open and writes it a brief; `evolve` runs one Opus agent per target with a read-only allowlist, then the workflow, not the agent, pushes `ai-evolution/<date>-<run>` and opens a draft PR in the target's own repo. [EVOLUTION.md](../../docs/EVOLUTION.md) |
| `deep-dive.yml` | daily 12:17, dispatch (`dry_run`, default true) | **The deep-dive tracker** (HUB-029): refreshes the open `deep-dive` issue and PR counts per repo into `_data/deep-dive.yml` and regenerates the `_data/deep_dive.json` projection `/deep-dive` renders. Deterministic, read-only on every other repo; a dispatch only uploads the artifact, the scheduled run publishes a stable-branch PR through `publish-data` with auto-merge off. [DEEP-DIVE.md](../../docs/DEEP-DIVE.md) |

Every scheduled agent loop (`fleet-pulse`, `issue-pipeline`, `repo-evolution`, `repo-scout`, `api-keys`) has a `vars.<NAME>_ENABLED` kill switch that a manual dispatch bypasses; `backlog-fanout` is held by its own `apply:` flag.

## Gates on the hub's own changes

| Workflow | Runs on | Checks |
| --- | --- | --- |
| `drift-check.yml` | PR, push `main`, dispatch | **The hard gate** (`tools/check-drift.sh`): registry ↔ `.gitmodules` parity, stray project dirs, generated-file freshness, the SCHEMA pyramid, composite-action manifests, the always-latest policy, vendored-payload parity, ports and the Docker standard, plus `actionlint` over every workflow with no exemptions. Advisory GitHub-reality and standardization checks. |
| `python-tests.yml` | PR, push `main`, nightly 09:17, dispatch | Every Python fixture suite the hub carries (`.github/scripts/dash-gen/`, `tools/`, `tools/console/`, `tools/tui/`, `templates/*/`), each a standalone script; a file without a `__main__` runner fails. Nightly because the console's dependencies float. Records resolved versions and an advisory coverage table. |
| `markdown-oneline.yml` | PR, push `main` (Markdown) | One paragraph per line (`tools/unwrap-prose.py`): on a same-repo PR it pushes the unwrap to the branch itself; on a fork PR or `main` it fails with the command to run. |
| `conformance.yml` | PR (spec / checker / templates / reusable paths) | The hub's own caller of `fleet-conformance.yml` at the PR head, so a change to the spec or checker is exercised before it reaches the fleet. Advisory. |
| `verify.yml` | PR (console, features, verify, pages paths; a `verify` label adds the Claude pass), dispatch | The hub's own caller of `fleet-verify.yml` at the same checkout: Playwright scenarios against the running console, evidence bundle. [VERIFICATION.md](../../docs/VERIFICATION.md) |
| `console-web.yml` | PR (console web paths), dispatch | Type-checks and builds the console page at latest dependencies, and fails if the built page carries inline script the console's CSP would block. |
| `site-quality-selftest.yml` | PR, push `main` (site-quality runtime, workflows, fixtures, schema), dispatch | Runs the reusable `site-quality.yml` on a passing fixture, a failing fixture (asserted finding by finding, gate must reject) and a url-mode run. |
| `ai-runner-contract.yml` | PR, push `main` (runner, lane, kit paths) | The `claude-run` runner's contract tests (stubbed `claude`, no credential). |
| `fleet-engines-contract.yml` | PR, push `main` (`templates/fleet-engines/**`) | Typecheck, vitest, build, pack and VERSION ↔ `package.json` parity for `@bamr87/fleet-engines`. |
| `publish-kits.yml` | push `main` (kit `package.json` / `VERSION`), dispatch | Packs and verifies every `templates/*/package.json`; publishes new versions to npm `@bamr87/*` with `NPM_TOKEN`, skipping versions already on the registry. |
| `claude.yml` | `@claude` mention by an owner, member or collaborator | The agent-context kit's mention handler, kept so the hub meets its own UPS baseline (`claude_workflow`). Every other issue or comment event skips the job at no cost. |

## Fan-outs

| Workflow | Runs on | What it does |
| --- | --- | --- |
| `fanout.yml` | dispatch (`kit`, `target` = repo / `all` / `gaps`) | **One dispatch surface for every kit** the hub pushes down, through `tools/fanout.sh`: dry-run by default, PRs only, external upstreams skipped, additive. Kits: `standardize`, `harness`, `schema`, `verify`, `feedback`, `deps-latest`, `docker`. `plan` resolves the kit's defaults and pre-flight tests and, for `harness` / `verify`, `target: gaps` from the committed inventory; `fanout` opens one PR per target; `agent-fill` (standardize / schema, one target) fills scaffold TODOs on the PR branch. [STANDARDS.md](../../docs/STANDARDS.md), [HARNESS-OPS.md](../../docs/HARNESS-OPS.md) |

`backlog-fanout.yml` (above) is the one scheduled fan-out.

## Reusable workflows (`workflow_call`)

Member repos call these by reference at a major tag (`@v1`, `@v2`; scheme in [WORKFLOW-VERSIONING.md](../../docs/WORKFLOW-VERSIONING.md)). They are a public interface: a new required input, permission or failure condition is a major.

| Workflow | Runs on | Purpose |
| --- | --- | --- |
| `standard-ci.yml` | `workflow_call` | Lightweight one-job CI: detect the stack, lint, test, build. Toolchains resolve caller input → the repo's `vars.*` → a built-in default. |
| `fleet-conformance.yml` | `workflow_call` | The Universal Project Standard gate (`tools/conformance.py`, offline); advisory until the caller sets `gate: true`. [CONFORMANCE.md](../../specs/CONFORMANCE.md) |
| `release-please.yml` | `workflow_call` | The fleet's one release workflow: release PR, `vX.Y.Z` tag, GitHub Release, lockfile re-lock. Shipped by the SDLC kit. |
| `site-quality.yml` | `workflow_call` | Lighthouse CI, axe-core at two widths and pa11y contrast, on a built Jekyll site or live URLs. Runtime in `.github/site-quality/` (exact pins, the hub's one sanctioned lockfile). |
| `spec-gate.yml` | `workflow_call` | Validates a caller's `specs/` and `BACKLOG.md` with the spec-driven kit; optional stale-backlog issue. [SPEC-DRIVEN.md](../../docs/SPEC-DRIVEN.md) |
| `fleet-verify.yml` | `workflow_call` | Agent verification: feature index, Playwright scenarios, optional Claude pass through the Playwright MCP. Hub actions come from the `.fleet-hub` checkout at `hub-ref`. |
| `ai-lane.yml` | `workflow_call` | The fleet's AI lane (kit `ai-runner`): kill switch, bot guard, credential check, concurrency, the `claude-run` step, result assertion. Inherits the caller's permissions. |

## Standards

Each standard below is also a rule in the [workflow atlas](../../docs/WORKFLOW-ATLAS.md): `tools/dash workflows lint` checks them all, the console's **Workflows** page shows each finding with its fix, and `test_workflow_atlas.py` fails CI on an error. A new workflow starts from `tools/dash workflows new --kind <loop|agent-loop|gate|reusable|dispatch> --id <id>`, which passes every rule and prints the `fleet.yml` and README edits that go with it.

- **One workflow per durable responsibility.** Shared CI is a reusable workflow; shared steps are a composite action. Do not copy a step into a second workflow: the six inline copies of the cost readout had drifted, one to the wrong cap.
- **Least privilege.** Top-level `permissions: contents: read`, elevated per job. Every job sets `timeout-minutes`; every schedulable workflow that writes has a `concurrency:` group.
- **Actions ride major tags** (`actions/checkout@v7`), never SHAs; Dependabot moves the majors, for workflows and composite actions alike ([DEPENDENCIES.md](../../docs/DEPENDENCIES.md)).
- **Never end in a bare `git push` to a protected branch.** Publish generated data with `utilities/publish-data`, which pushes when allowed and opens a stable-branch PR when it isn't. A settings change once froze the fleet's data for three weeks this way.
- **Generated-data commits carry `[skip ci]`.** A data push needs none of the PR gates; `build-dash.yml`'s cron republishes after the last one and the nightly `python-tests.yml` run still verifies `main`.
- **Prefer `needs:` over `workflow_run`.** A `workflow_run` trigger couples workflows by display name and silently skips the follower whenever the upstream fails.
- **A multi-stage loop reconciles state, it does not replay events.** Stages live in labels, so a cancelled run costs one cycle of latency and a human can re-queue anything by editing a label.
- **A PR that must run CI is opened with `FLEET_TOKEN`, never `GITHUB_TOKEN`**, and the token is probed (`resolve-fleet-token`, `GET /user`), never presence-checked. A loop that cannot deliver without the PAT passes no `default-token` and fails before spending anything.
- **One tracking issue per concern**, updated in place and closed when clean, through `utilities/upsert-issue`. Alarms are filed with `github.token`: an alarm must not depend on the credential most likely to be dead.
- **Claude call sites.** Each `claude-code-action` step is preceded by `claude-auth` (the repo's `CLAUDE_AUTH_ORDER`) and passes `--max-budget-usd` equal to its `budget.call_sites` entry in `_data/fleet.yml`. It is followed by a `Report Claude run cost` step: `id: cost`, `if: !cancelled()`, `uses: ./.github/actions/claude-cost`. That step fails on a budget hit, names a refused credential, and echoes the result record for the cost collector. `test_ai_budget.py` asserts all of it. [AI-INTEGRATION.md](../../docs/AI-INTEGRATION.md#spend-guardrails)
- **A spent Claude usage window is capacity, not a defect.** Every scheduled agent step is `continue-on-error: true` and its cost step passes `usage-limit: skip`. A 429 then becomes a warning, `usage_limit=true` (later issue-pipeline tiers skip on it), and a green run; every other failure still fails the job. The two halves only work together, so `test_ai_budget.py` requires them as a pair on every scheduled site.
- **A job whose workspace is another repository** (repo-evolution `evolve`, fanout `agent-fill`, `fleet-verify.yml`) takes the hub's composite actions from a sparse `.fleet-hub` checkout, never from a floating tag.
- **Toolchain versions come from `vars.*`**, resolved caller input → repo variable → default, so `dash config sync` can move the fleet from `_data/fleet.yml`.
- **Fan-outs go through `tools/fanout.sh`** (dry-run default, PRs only, external-upstream guard). Do not inline a new clone → seed → PR loop.
- **Bot identity:** `bamr87-bot <10567847+bamr87@users.noreply.github.com>`; the noreply form is required by email-privacy push protection.
- Update this README, `AGENTS.md`'s loop table and `_data/fleet.yml` `schedule:` when adding, removing or renaming a workflow.

## Retired

| Date | Removed | Why |
| --- | --- | --- |
| 2026-10-27 | `git-digs.yml` | 17 runs in its life, all skipped: its kill switch was never set and its schedule had been commented out since 10-14. It only ever wrote to it-journey, which is where it belongs if it comes back. |
| 2026-10-27 | `unified-evolution.yml` | Dispatch-only Claude pass on the hub tree; unrun since 2026-07-08 (failed), and its 08-09 rewrite never ran. The hub evolves through the local `/evolve` loop, the issue pipeline and the doctor; `dash evolve` now says so. |
| 2026-10-19 | `standardize-`, `schema-`, `deps-`, `docker-`, `feedback-`, `verify-`, `harness-fanout.yml` | Seven copies of the same three steps around `tools/fanout.sh`; now `fanout.yml` with a `kit` input. |
| 2026-10-19 | `refresh-dash.yml` | Ran daily for months and never produced a change: the README span depends only on the registry, which the drift gate already guards. `reconcile-registry.yml` regenerates it in its own PR. |
| 2026-08 | `actions-usage`, `ai-usage`, `daily-repo-analysis`, `actions-review.yml` | Four workflows chained by `workflow_run` on a display name; the chain broke silently when a ruleset refused their pushes. Folded into `fleet-pulse.yml`. |
| 2026-08 | `unified-cicd`, `unified-release`, `unified-maintenance`, `workflow-dispatcher.yml` | A generic single-app suite for a tree with no app code; nothing invoked it. |

Recover any of them from git history if a reference implementation is ever wanted.

## Validation

`actionlint` runs in `drift-check.yml` and locally from the repo root. `python3 .github/scripts/dash-gen/test_ai_budget.py` and `test_schedule.py` hold the Claude call sites and the crons to `_data/fleet.yml`; `test_workflow_atlas.py` holds every workflow and action to the standards above (`tools/dash workflows lint` prints the same findings).

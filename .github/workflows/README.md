# Workflows

GitHub Actions for the bamr87 dash. Two groups: the **control-plane** workflows that keep the dash and its ~40 submodules aligned, and a **legacy** generic suite kept dispatch-only.

## Control plane (live)

| Workflow | Triggers | Purpose |
| --- | --- | --- |
| `build-dash.yml` | push `main` (dash paths), daily 07:00, dispatch | Builds the Jekyll dash + ephemeral health data; deploys to GitHub Pages. **The sole Pages surface.** The cron runs *after* the data-refresh jobs (04:00–06:00) commit, since their `GITHUB_TOKEN` commits can't trigger this workflow themselves. |
| `fleet-config` (tooling, not a workflow) | — | `_data/fleet.yml` is the fleet's central config — toolchain versions, cadences, remediation caps, the token contract, canonical repo variables. Audit it against reality with `dash secrets`; project the variables onto every repo with `dash config sync --apply`. |
| `drift-check.yml` | push `main`, PR, dispatch | Fast offline+API gate: registry↔`.gitmodules` parity, **stray/unregistered project dirs**, README AUTO freshness, missing top-level READMEs, **SCHEMA.md pyramid (h)**; advisory **GitHub-reality** (renames/deletions/branch) + **standardization**. Also runs `actionlint` — as a step in the same job, over every workflow found by glob (`unified-evolution.yml` exempt; no list to maintain). No Ruby/Jekyll build; the internal-link check is local-only (`--links`). |
| `refresh-dash.yml` | daily 04:00, dispatch | Regenerates the committable README `AUTO:projects` span + registry data; opens a PR on the **stable** `chore/refresh-dash` branch, so a daily no-op updates one rolling PR instead of opening a new one. |
| `update-submodules.yml` | weekly Sun 03:00, dispatch | Bumps submodule pointers **up** into root (pointer-only staging); opens a PR. |
| `standardize-fanout.yml` | dispatch (per-repo or all) | Opens standardization PRs **down** into submodules via `tools/fanout.sh`, seeding `.editorconfig`, the reusable `standard-ci.yml` caller, and on request the **agent-context kit** (`CLAUDE.md` scaffold + `@claude` workflow). Dry-run default. |
| `schema-fanout.yml` | dispatch (per-repo or all) | Opens **Pyramid Schema** adoption PRs down into submodules via `tools/fanout.sh` (SCHEMA.md contracts + vendored linter + CI gate). Optional `agent_fill` runs a Claude Code pass that fills scaffold TODOs on the PR branch (single target only). Dry-run default. |
| `standard-ci.yml` | `workflow_call` | Reusable **lightweight** CI (detect stack → lint + test + build) in ONE job, adopted by a short caller. The fleet's other gate, `bamr87/.github`'s `ci.yml`, runs six jobs including a CodeQL matrix — deliberately kept separate, since making every repo pay for the fuller gate would multiply per-push runners ~6× across the fleet. Pick by tier (`_data/standards.yml`): `experiment`/`content` take this one, `active` takes the full one. Toolchain versions resolve caller input → the repo's `vars.*` → built-in default. |
| `claude.yml` | `@claude` mention (issues/PRs) | Claude Code responds to `@claude` mentions in this repo. Same file the agent-context kit seeds into submodules. |
| `fleet-pulse.yml` | daily 06:00, dispatch | **THE daily loop.** Job `pulse` gathers every fleet signal (Actions analytics, Claude usage + engagement actuals, prior-day digest, open-state triage snapshot), publishes them in ONE commit via `utilities/publish-data`, and triages them into one ranked remediation queue (`dash-gen remediate`). Job `doctor` (`needs: pulse`) runs an **Opus Claude Code agent** that reads each failing / long-running workflow's logs and opens a draft **PR with the fix** — in this repo, or in the submodule that owns it — falling back to a hub **issue** when it can't. Deduped by hidden marker, capped by `_data/fleet.yml`. |

### Retired (folded into `fleet-pulse.yml`)

`actions-usage.yml`, `ai-usage.yml`, `daily-repo-analysis.yml`, and `actions-review.yml` were four workflows doing one job. Each paid for its own checkout and Python setup on its own cron, and they were chained by a `workflow_run` trigger matching a **display name** that had to be kept in sync by hand.

That chain broke silently. A ruleset was added to `main` ("Changes must be made through a pull request" + "Commits must have verified signatures"), the three data jobs' closing `git push` started being rejected, and because `actions-review.yml` triggered on `actions-usage.yml` *succeeding*, it stopped running too. Every generator still worked; the fleet's data froze for three weeks and nothing reported it.

Both structural causes are fixed in the replacement: publishing goes through [`utilities/publish-data`](../actions/utilities/publish-data/action.yml), which falls back to a pull request when a direct push is refused, and `doctor` is a `needs:` job rather than a separate `workflow_run` workflow, so it can't be skipped by an upstream publish failure. The generators themselves are unchanged and still available as `dash actions`, `dash ai-usage`, `dash daily`, `dash triage`, `dash actions-review`.

## Legacy / dispatch-only

`unified-evolution.yml` is the last of a generic single-app suite that only ever ran against the **root** tree (which has no app code — the projects are submodules). It is **`workflow_dispatch`-only** and still powers the manual AI evolution pass (trigger via `tools/dash evolve`).

The other four — `unified-cicd.yml`, `unified-release.yml`, `unified-maintenance.yml`, and `workflow-dispatcher.yml` (1,754 lines) — were **removed**: nothing in `tools/`, `.claude/`, or the docs invoked them, `workflow-dispatcher.yml` existed only to dispatch the other three, and every responsibility they nominally covered is served by a control-plane workflow above. Recover from git history if a reference implementation is ever wanted.

## Standards

- One workflow per durable responsibility; propagate shared CI via the `workflow_call` template, not by copying near-duplicate workflows.
- Top-level `permissions: contents: read`; elevate per-job only where needed.
- Every job sets `timeout-minutes`; every write-capable schedulable workflow has a `concurrency:` group.
- **Claude auth (house convention):** every `anthropics/claude-code-action@v1` call site is OAuth-first — `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}` with `anthropic_api_key: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN == '' && secrets.ANTHROPIC_API_KEY || '' }}` as the fallback. Provisioning: [`docs/AI-INTEGRATION.md`](../../docs/AI-INTEGRATION.md).
- **Bot identity:** automated commits use `bamr87-bot <10567847+bamr87@users.noreply.github.com>` (the noreply form is required by email-privacy push protection).
- **Never end a workflow in a bare `git push` to a protected branch.** Publish generated data through [`utilities/publish-data`](../actions/utilities/publish-data/action.yml), which pushes directly when allowed and opens a stable-branch PR when it isn't. The publish route is a property of the *repository* and can change without warning; resolving it at runtime is what stops a settings change from decapitating the automation. This is not hypothetical — it already happened once and cost three weeks of fleet data.
- **Prefer `needs:` over `workflow_run`.** A `workflow_run` trigger couples workflows by display-name string and silently skips the downstream when the upstream fails for *any* reason — including a reason unrelated to the data it produces.
- **Toolchain versions come from `vars.*`, not literals.** Reusable workflows resolve caller input → the calling repo's `vars.NODE_VERSION`/`PYTHON_VERSION`/`RUBY_VERSION` → a built-in default, so `dash config sync` can bump the fleet from `_data/fleet.yml`.
- **Token contract:** declared in [`_data/fleet.yml`](../../_data/fleet.yml). `FLEET_TOKEN` is the single fine-grained PAT the control plane uses fleet-wide; the legacy `ACTIONS_ANALYTICS_TOKEN` / `DAILY_ANALYSIS_TOKEN` / `FANOUT_TOKEN` remain as fallbacks during migration. Audit with `dash secrets`.
- Fan-outs go through `tools/fanout.sh` (dry-run default, PRs only, external-upstream guard) — don't inline new clone→seed→PR loops.
- Avoid scheduled write-capable workflows unless the owner confirmed perms/secrets.
- Update this README when adding, removing, or renaming workflows.

## Validation

`actionlint` runs in CI (drift-check.yml) and locally: `actionlint` from the repo root. Also check that referenced local actions/scripts exist.

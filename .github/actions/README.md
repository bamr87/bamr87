# Actions

Composite actions used by this hub's own workflows. Every action here is called by at least one workflow in `.github/workflows/` — that is the entry bar, not a nicety. One of them, `claude-run`, is also the fleet's shared runtime and is referenced remotely by member repos; it is the exception to "local glue only" below, made deliberately so the fleet receives the AI step by dependency rather than by copy (see `templates/ai-runner/`).

## Layout

| Path | Purpose | Called by |
| --- | --- | --- |
| `setup/dash-gen` | Install Python + the dash-gen generator's dependencies (pip-cached). | `fleet-pulse`, `build-dash`, `reconcile-registry`, `issue-pipeline`, `token-rotation`, `api-keys`, `schema-vendor`, `repo-evolution`, `drift-check`, `fanout` |
| `setup/configure-git` | Configure Git identity and an `insteadOf` token rewrite so `git submodule update --remote` can fetch private submodules. | `update-submodules` |
| `utilities/publish-data` | Commit generated `_data/` files and land them on the default branch by whatever route the ruleset allows: direct push, else a stable-branch PR updated in place. Never a bare `git push`. | `fleet-pulse`, `issue-pipeline`, `token-rotation`, `update-submodules` |
| `utilities/upsert-issue` | **One tracking issue per concern**: open or update it by exact title (labels created on demand), or `state: close` it when the concern is gone. Four loops hand-rolled this and each grew its own duplicate-issue bug. | `api-keys`, `token-rotation` (report), `reconcile-registry` (file + close), `schema-vendor` |
| `resolve-fleet-token` | **Probe, never presence-check.** Try `FLEET_TOKEN` (and an optional fallback PAT) against `GET /user`, export the winner as `GH_TOKEN`, and take `github.token` as the unprobed last resort only where the caller passes `default-token` — a loop that cannot deliver without the PAT passes none and fails before spending anything. Outputs `token`, `source`, `valid`, `pat`. | every loop's token step: `fleet-pulse` (pulse + doctor), `issue-pipeline` (all four jobs), `reconcile-registry`, `schema-vendor`, `token-rotation`, `repo-evolution`, `unified-evolution`, `git-digs`, `fanout` |
| `claude-auth` | Choose the Claude credential a `claude-code-action` step uses, from the repo's `CLAUDE_AUTH_ORDER` (`ai_auth:` in `_data/fleet.yml`). Outputs a method *name*, never a secret. A refused API key falls through to the next method. | every hub `claude-code-action` call site (`claude`, `fleet-pulse`, `issue-pipeline`, `repo-evolution`, `fanout` agent-fill, `fleet-verify`, `unified-evolution`) and the agent-context kit's `claude.yml` (which references it remotely) |
| `claude-cost` | **The spend readout after every `claude-code-action` step**: writes spend / cap / turns to the job summary on every run, echoes the result record into the run log for the cost collector, FAILS the step on a `--max-budget-usd` abort (publishing `budget_hit` for the step that would publish the agent's tree), and classifies a refused credential apart from a 429. Six inline copies of this step had drifted — one to the wrong cap. `test_ai_budget.py` asserts the script once and every call site's `budget-usd`. | `fleet-pulse` doctor, the three `issue-pipeline` tiers, `repo-evolution`, `unified-evolution`, `fanout` agent-fill, `fleet-verify` |
| `claude-run` | **The fleet's universal AI step** (kit `ai-runner`): install Claude Code, resolve the model from the CONSUMER repo, run `claude -p` in the repo's credential order with an optional API fallback and optional metering; attempted-and-failed is RED. The one action here meant to be referenced REMOTELY (`uses: bamr87/bamr87/.github/actions/claude-run@v1`). | `ai-lane.yml` (the reusable lane), `git-digs`, every fleet repo that adopts the kit; contract-tested by `ai-runner-contract` |

## Rules

- Keep each action focused on one responsibility.
- Pass project-specific values as inputs or environment variables.
- Do not hardcode registry hosts, organization names, local paths, or product-specific services.
- Include an `action.yml` and a README for every action directory.
- **Never write a workflow expression inside an `action.yml` description.** A
manifest is itself a template: GitHub evaluates `${{ … }}` wherever it appears, descriptions included. A context named there purely as prose documentation is parsed as a *real* expression against a context that does not exist at manifest-load time, and the action then fails to load at all — before a single step runs, taking every caller with it. `resolve-fleet-token` documented its default as "normally `${{ github.token }}`" and killed the first scheduled `token-rotation` run in 34 seconds with `Unrecognized named-value: 'github'`. Name contexts in plain backticks. Gated by **check (l)** of `tools/check-drift.sh`, because `actionlint` does not validate action manifests and nothing else would have caught it.
- **Resolve runner-provided values inside the step, not in a manifest default.**
`$GITHUB_REPOSITORY` and `$GITHUB_API_URL` are exported into every job; taking them from the environment keeps the manifest free of expressions entirely, so what a manifest may or may not evaluate stops being load-bearing.
- **A job whose workspace is another repository takes these actions from a sparse checkout of the hub at the same commit** (`actions/checkout` of `bamr87/bamr87` at `github.sha` — or `hub-ref` in a reusable workflow — into `.fleet-hub`, hidden from git in `.git/info/exclude`), then `uses: ./.fleet-hub/.github/actions/<name>`. That is what `repo-evolution`, the fan-out's `agent-fill` and `fleet-verify` do; it pins the action to the workflow's own version instead of a floating tag. `claude-run` and `claude-auth` are the two the fleet references remotely by design.
- **An action with no caller is deleted, not kept "for later."** Seven actions were removed on 2026-08-09 (`ci/run-checks`, `ci/run-tests`, `deployment/build-push-image`, `deployment/build-n-cache-image`, `setup/setup-ruby`, `utilities/get-pr-labels`, `run-backend-tests`) — 3,500 lines that every reader of this directory had to evaluate and no workflow ever ran. Two were actively misleading: `setup/setup-ruby` existed while every workflow called `ruby/setup-ruby@v1` directly. The fleet's shared CI lives in reusable *workflows* (`.github/workflows/standard-ci.yml` and `bamr87/.github`), which is where generic build/test logic belongs; local composite actions are for glue this hub alone needs.

## Usage

Reference local actions from workflows with:

```yaml
- uses: ./.github/actions/setup/dash-gen
```

A calling workflow must `actions/checkout` the repo first — a local `uses:` path resolves against the checked-out tree.

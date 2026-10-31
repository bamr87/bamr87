# AI Integration — surfaces, auth, and the loops

> The AI layer — every surface where Claude runs, the Claude auth order and secrets matrix, the loops, and how all of it propagates to the fleet.

One page for the whole AI layer: what runs where, how it authenticates, and the feedback loops it powers. If you're setting up Claude for this repo (or a fleet repo), start at [Auth & secrets](#auth--secrets).

## The four AI surfaces

1. **Local `.claude/` layer** — skills, commands, agents, and hooks that make the dash self-managing from a local Claude Code session. The full inventory lives in [`.claude/README.md`](../.claude/README.md); highlights: the `run-dash` skill (orchestration hub, `driver.py`), `drift-report` (explains drift-gate checks (a)–(l)), `standardize-audit`/`standardize-project`, `actions-triage`, `triage-attention`/`evolve-project`/`refresh-portfolio`, the `/adopt-schema` and `/adopt-release` commands, the `feature-scout` subagent, and the Future-Features session hooks.
2. **CI workflows** — every `anthropics/claude-code-action@v1` call site in the hub: [`claude.yml`](../.github/workflows/claude.yml) (@claude mention handler), [`fleet-pulse.yml`](../.github/workflows/fleet-pulse.yml) (the daily loop's `doctor` job — the Opus fixer; self-skips without Claude auth), the three agent tiers of [`issue-pipeline.yml`](../.github/workflows/issue-pipeline.yml) (intake / implement / complete; each self-skips without Claude auth, and tier 1 still builds and uploads its evidence bundles), the `agent-fill` job of [`fanout.yml`](../.github/workflows/fanout.yml) (kits `standardize` and `schema`), the verifier pass of [`fleet-verify.yml`](../.github/workflows/fleet-verify.yml), and the matrix `evolve` job of [`repo-evolution.yml`](../.github/workflows/repo-evolution.yml) (the weekly per-repo improvement pass — one Opus agent per opted-in submodule, draft PR in its upstream; the plan job fails loudly without auth, before any spend).
3. **MCP servers** — [`.mcp.json`](../.mcp.json): `github` (needs a `GITHUB_TOKEN` env var), `memory`, `sequentialthinking`, `context7`.
4. **Copilot-format reference templates** — `.github/agents/`, `.github/instructions/`, `.github/prompts/` are consumed _in place_ by hub skills (e.g. `evolve-project` reads the agent personas); nothing seeds them into submodules, and they are not Task-launchable Claude subagents (only `.claude/agents/` are).

## Auth & secrets

Every Claude call site tries its credentials **in the order its repo's `CLAUDE_AUTH_ORDER` variable names**. The order is configured per repo and per group in [`_data/fleet.yml`](../_data/fleet.yml) `ai_auth:`. The fleet default is `oauth,api_key`, the house convention since 2026-07: `CLAUDE_CODE_OAUTH_TOKEN` first, `ANTHROPIC_API_KEY` as the fallback. See [Auth order per repo](#auth-order-per-repo).

| Secret | Used by | Required? |
| --- | --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude.yml`, `fleet-pulse.yml`, `issue-pipeline.yml`, `repo-evolution.yml`, `fanout.yml` (kit `schema`) `agent_fill`, seeded fleet `claude.yml` workflows | Preferred Claude auth. From `claude setup-token` (a **one-year** credential), seeded onto the hub — [`token-rotation.yml`](../.github/workflows/token-rotation.yml) carries it to the rest of the fleet weekly. |
| `CLAUDE_CODE_OAUTH_REFRESH_TOKEN` | `token-rotation.yml` | **Optional**, hub only. Lets the weekly rotation re-mint the OAuth token without a browser. Unset → the loop still propagates and audits, it just asks a human when the credential nears its expiry. See [TOKEN-ROTATION.md](TOKEN-ROTATION.md). |
| `ANTHROPIC_API_KEY` | same call sites | The metered method. It comes second in the default order, or first in a repo whose `ai_auth` order puts `api_key` first. |
| `FLEET_TOKEN` | `fleet-pulse.yml`, `issue-pipeline.yml`, `repo-evolution.yml`, `fanout.yml`, `token-rotation.yml`, `reconcile-registry.yml`, `schema-vendor.yml` | **The one control-plane PAT.** Fine-grained, covering the fleet: `actions:read` + `contents:read` + `issues:read/write` + `pull_requests:read/write`, plus `contents:write` + **`workflows:write`** on repos the fan-outs and the fixer may open PRs against (GitHub refuses a push touching `.github/workflows/*` without the Workflows permission), plus **`secrets:write`** for the weekly rotation (writing an Actions secret is an admin-level call — `token-rotation.yml` is the only workflow that needs it). Probed everywhere by the shared `resolve-fleet-token` action (`GET /user`), never presence-checked; `GITHUB_TOKEN` is the unprobed last resort. The legacy per-loop PATs (`FANOUT_TOKEN`, `ACTIONS_ANALYTICS_TOKEN`, `DAILY_ANALYSIS_TOKEN`) are gone from the hub and from every workflow. |

### One-time setup

```bash
claude setup-token                                        # mint an OAuth token
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bamr87/bamr87    # provision the hub
dash secrets rotate --apply                               # carry it to the rest of the fleet
```

The third line is what the weekly [`token-rotation.yml`](../.github/workflows/token-rotation.yml) run does on its own every Monday, so seeding the **hub** is now the whole manual step — per-repo `gh secret set` is no longer needed, and a newly-registered repo is enrolled by the next run without anyone remembering to. Optionally provision `CLAUDE_CODE_OAUTH_REFRESH_TOKEN` on the hub to let the loop re-mint the credential too. Full doc: [TOKEN-ROTATION.md](TOKEN-ROTATION.md).

> **Status:** `CLAUDE_CODE_OAUTH_TOKEN` is provisioned in `bamr87/bamr87` (since 2026-07-16) and `FLEET_TOKEN` is the one live control-plane PAT — the hub's AI steps run. The legacy per-loop PATs were retired 2026-08-05 (`PAT_TOKEN`'s last call site was removed in PR #61); the legacy names above survive only as fallback expressions in the workflows. `ANTHROPIC_API_KEY` remains unset (it's only the fallback). Fleet repos still need their own `CLAUDE_CODE_OAUTH_TOKEN` for seeded `claude.yml` workflows — as of 2026-08-23 the weekly `token-rotation.yml` loop provisions and refreshes those from the hub's copy, so they are no longer placed by hand. `FLEET_TOKEN` needs `secrets:write` added for that loop to write anything; until it is, the loop audits and reports rather than failing.

### Canonical call site

Copy this shape verbatim into any new workflow (it is what `claude.yml` uses):

```yaml
- id: claude-auth
  uses: bamr87/bamr87/.github/actions/claude-auth@main
  with:
    order: ${{ vars.CLAUDE_AUTH_ORDER }}
    has-oauth: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN != '' }}
    api-key: ${{ secrets.ANTHROPIC_API_KEY }}
- uses: anthropics/claude-code-action@v1
  with:
    claude_code_oauth_token: ${{ steps.claude-auth.outputs.method == 'oauth' && secrets.CLAUDE_CODE_OAUTH_TOKEN || '' }}
    anthropic_api_key: ${{ steps.claude-auth.outputs.method == 'api_key' && secrets.ANTHROPIC_API_KEY || '' }}
    claude_args: "--max-budget-usd 10"     # see "Spend guardrails" below — required
```

### Auth order per repo

`ai_auth:` in [`_data/fleet.yml`](../_data/fleet.yml) decides which credential each repo tries first:

```yaml
ai_auth:
  variable: CLAUDE_AUTH_ORDER
  methods: { oauth: CLAUDE_CODE_OAUTH_TOKEN, api_key: ANTHROPIC_API_KEY }
  default: oauth,api_key               # everything not matched below
  groups:
    metered-lanes:                     # API key first, OAuth as the fallback
      order: api_key,oauth
      repos: [lifehacker.dev, it-journey]
      categories: []                   # …or every registry repo in a category
  repos:
    zer0-mistakes: api_key             # the key only, never OAuth
```

- **Precedence.** `repos:` beats `groups:`, which beats `default:`. A repo matched by two groups with *different* orders is an error. So is an unknown method or a key that names no fleet repo. Every writer refuses to act until the errors are fixed.
- **What it drives at runtime.** The order is projected onto each repo as the `CLAUDE_AUTH_ORDER` repository variable. Every `claude-code-action` step reads it through [`claude-auth`](../.github/actions/claude-auth/). Every `ai-lane` reads it through `claude-run`, where it becomes `AI_AUTH_ORDER`.
  - **`claude-auth`** outputs a method name, never the secret. An API key that the models endpoint refuses (`401`/`403`) falls through to the next method.
  - **`claude-run`** gives the CLI only the credential being tried. If that credential is **refused** (rejected, or its quota exhausted), it moves on to the next one. It never re-runs a task after any other kind of failure. An order without `api_key` never spends the key, not even on the single-shot API fallback.
- **What it drives in the secret store.** `dash secrets push`, `dash secrets sync`, `dash secrets rotate` and the weekly rotation send a repo only the credentials its order uses. The hub keeps every fleet secret whatever its own order, because it is the copy the fleet is written from.
- **An unset variable means the default**, so a repo behaves exactly as before until it is given an order.

```bash
dash config auth                        # each repo's order, where it came from, what it holds, its variable
dash config auth --offline              # the resolution alone (no GitHub calls)
dash config auth sync                   # dry run: which CLAUDE_AUTH_ORDER variables would change
dash config auth sync --apply           # set them (the weekly token-rotation variable pass does the same)
```

### Anthropic API keys (per workspace)

The `api_key` credential is not one fleet-wide value. Each repo holds the key of the **Console workspace that pays for it**, as declared in `_data/fleet.yml` `api_keys:`:

- A workspace claims repos by registry name, by `owner/repo` (which can be outside the registry, like a content site in another GitHub org), or by GitHub owner.
- Every repo that no workspace claims gets the key from the **Default Workspace**.
- A repo whose `ai_auth` order leaves `api_key` out is never sent a key.

**What the Admin API can and cannot do.** It can list keys (with `expires_at`) and disable them. It **cannot create a key**: keys, and their expiry, are minted in the Claude Console. That makes rotation *assisted*:

1. **Create the keys.** In the Console (Settings → API keys → **Create key**), create each workspace's key scoped to that workspace, with an expiry of `lifetime_days` (7).
2. **Paste them into `.env`.** Use any name starting with `ANTHROPIC_API_KEY`. The tool matches each value to its Console record by the key's partial hint and reads the workspace from the key's scope, so names don't matter. Admin keys and OAuth tokens are never taken, whatever they're called.
3. **Run `dash keys rotate --apply`**, or use the Auth tab's *Anthropic API keys* panel. For each workspace it:
   - takes the newest active key;
   - refuses any key that outlives the policy (`--allow-long-lived` overrides);
   - proves the key with **one cheap Messages call**, made exactly as CI makes it (no workspace header, so a key that would need one fails here rather than in CI);
   - writes the key hub-first to every repo the workspace serves;
   - records the ledger `_data/api_keys.yml` (ids, names, dates, repos; never a value);
   - and only then disables the key it replaced. That's only when every repo took the new one, and only a key this tool deployed itself, never one in use by hand.
4. **Let the daily check watch it.** [`api-keys.yml`](../.github/workflows/api-keys.yml) runs `dash keys watch`. It judges the *deployed* keys, proves the hub's own key live, and keeps one issue open from `renew_before_days` (2) before expiry until the replacement lands.

```bash
dash keys                          # each workspace's key in .env, its expiry vs policy, the repos it serves
dash keys verify                   # + one cheap call per key (a fraction of a cent each)
dash keys rotate                   # dry run: what would be written where
dash keys rotate --apply           # write, hub first, then disable the replaced keys
dash keys watch                    # the daily check: the DEPLOYED keys, from the ledger
```

`CLAUDE_CONSOLE_TOKEN` is the Admin API credential. It must be a service-account key **not** scoped to a workspace (a workspace-scoped key is refused by the Admin API), or an `sk-ant-admin` key. It is hub-only and never a fleet secret. Because `dash keys` owns `ANTHROPIC_API_KEY` (`managed_by: keys` in the token contract), the weekly rotation and `dash secrets push|sync` leave that secret alone. Otherwise they would overwrite every workspace's key with the hub's single copy.

### Keyless: stage 2 (Workload Identity Federation)

A 7-day key still has to be created by a person once a week. The documented way to have **no key at all** is Workload Identity Federation. A GitHub Actions job presents its OIDC token and exchanges it at `POST /v1/oauth/token` for a Claude access token that lives for minutes. There's nothing to mint, paste, expire or rotate. The plan is to prototype it on one repo before any fan-out:

1. **One-time setup (a human, in the Console or with an `org:admin` OAuth token):**
   - a service account per workspace with `organization_role: developer`;
   - a GitHub issuer (`issuer_url: https://token.actions.githubusercontent.com`, `jwks: {type: discovery}`);
   - and one rule per workspace (`oauth_scope: workspace:inference`), matched to an exact `repo:<owner>/<repo>:ref:refs/heads/main` subject. Never a trailing `*`, which would also admit pull requests from forks.
2. **In the job:** grant `id-token: write`, request the OIDC token, and exchange it. The SDKs do the exchange themselves when `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID` and `ANTHROPIC_IDENTITY_TOKEN` are set.
3. **Open questions the prototype has to answer before this replaces keys:**
   - Can `claude-code-action` and the `claude` CLI take the federated token? Probably via `ANTHROPIC_AUTH_TOKEN`, but that isn't confirmed.
   - Is `token_lifetime_seconds` long enough for a 30-minute agent run? Otherwise the run needs a refresh path.
   - GitHub's OIDC tokens are single-use (`jti`), so a job that calls the CLI more than once needs one exchange, not several.

The Harness Console has the same controls. The Auth tab has an *AI auth order* panel (resolve, sync dry run, confirm-gated sync), and the fleet-wide default is a choice on the Config tab.

## Spend guardrails

**`--max-turns` bounds iterations, not spend.** One turn against a large context can outspend thirty small ones, which is why a turn cap is not a budget: six scheduled loops ran for months turn-capped and dollar-uncapped (bamr87#128).

Every `anthropics/claude-code-action` call site therefore also passes `--max-budget-usd`. The ceiling is declared once in [`_data/fleet.yml`](../_data/fleet.yml) `budget:` — `usd_per_turn` (the derivation rule), `default_usd`, `local_usd` (for `dash ai run`), and `call_sites`, keyed `<workflow file>:<job id>`. A `claude_args` string cannot read YAML, so the number is necessarily written twice; `.github/scripts/dash-gen/test_ai_budget.py` asserts that the two copies agree, that no call site is missing a cap, and that each cap clears `usd_per_turn × --max-turns`. **Adding a new Claude call site without a cap fails that test.**

A cap is a **circuit breaker, not a target**. A budget abort stops the agent *mid-task* — worse than a turn overshoot, which at least stops at a boundary — so caps are set at roughly 1.5× a full run's observed spend, and hitting one is never a silent truncation. Read the current table with `dash config show budget`.

**What a cap does when it binds** is a three-part contract, asserted by `test_ai_budget.py` because every part of it is invisible until the day a ceiling is actually reached:

1. **The step fails.** `::error::` writes an annotation; it does not fail anything. A cost step that only annotated left the job green, and every `success()`-gated step after it ran on truncated work — including the ones that open pull requests. The step now exits non-zero, matching `dash ai run`, which already did: one event, one verdict.
2. **The verdict is readable.** The cost step is `id: cost` and publishes `budget_hit` as a step output. Whether `claude-code-action` itself exits non-zero on an abort is not a documented contract, so the workflow that publishes a PR *from the agent's working tree* (`repo-evolution.yml`) gates on that output rather than on the action's exit code — and when it is set they still publish, as a **draft whose body says the diff is partial and unverified**. Discarding a run that has already been paid for is the worse failure; shipping one that reads like a completed pass is the dangerous one. At the other call sites the agent opens its own PR, so a red job is the whole signal.
3. **The spend is still recorded.** `ai_usage_collector.py` regex-scrapes `total_cost_usd` out of the **run log**, so a run it cannot see is a run charged to nobody — and an abort is not the normal termination path. Each cost step therefore echoes the result record into the log itself. The collector takes the last occurrence and this is the same record, so the value is unchanged; it simply can no longer go missing on exactly the runs where the spend was highest.

**A spent usage window is capacity, not a defect.** Every hub loop shares one Claude subscription, so when its weekly or five-hour window runs out, every loop that starts afterwards is refused at its first call (`api_error_status: 429`, $0, empty `modelUsage`) until the reset. Reported as a red run, that kept fleet-pulse and issue-pipeline red for three mornings in a row (2026-10-23..25) and fed the doctor its own failures (#335, #348). So every **scheduled** call site marks its agent step `continue-on-error: true` and passes `usage-limit: skip` to `claude-cost`, which then owns the job's verdict: a usage limit is a warning, a job summary line and `usage_limit=true` (the issue pipeline's later tiers skip on it instead of paying their setup to be refused too); a budget hit, a refused credential, an agent failure or a missing result record still exit 1. The two halves are useless apart, so `test_ai_budget.py` asserts they come as a pair and that every scheduled loop uses them. Whether a refused subscription should fall back to the metered `ANTHROPIC_API_KEY` (the `api_key` half of `CLAUDE_AUTH_ORDER`, which the `claude-run` step already honours on a 429) is a billing decision #348 holds open; nothing falls back today.

**Under subscription auth a cap is a throughput ceiling, not a spend ceiling.** Every call site is OAuth-first, so in the normal case `total_cost_usd` is a *priced estimate* of what the work would have cost on the API, not an amount anyone is billed — it is a true dollar ceiling only where `ANTHROPIC_API_KEY` is in use. Both are worth having, and nothing downstream presents these numbers as an invoice: the job summary and the abort annotation both say which they are.

Cost is reported on **every** run, not only failures. Each call site's `Report Claude run cost` step is the shared [`claude-cost`](../.github/actions/claude-cost/README.md) action — one script, not six copies (which had drifted: fleet-pulse reported against $25 while its cap was $40) — which reads `${RUNNER_TEMP}/claude-execution-output.json` and writes spend / cap / turns to the job summary; it used to sit behind `if: failure()`, so a green run — the common case, and the one whose spend accumulates unnoticed — printed nothing. The durable record still belongs to `ai_usage_collector.py` and `fleet_lake.py`; the step is a readout, not a third parser.

Locally, `tools/dash ai run -- <args>` is the same guardrail: it wraps `claude -p --output-format json` at `budget.local_usd` and records the run's cost into the ledger's `runs` section ([schema](../.github/scripts/dash-gen/README.md#run-record-schema)).

### Local headless runs (the JEV loop runner's executor)

`tools/dash ai run` is also the one executor JEV's local loop runner uses ([ADR 0002](adr/0002-agent-step-specs-and-local-runner.md), P1; flags in the [dash-gen README](../.github/scripts/dash-gen/README.md#ai-run-flags)). The guardrails it adds for a local agent:

- **The CI cap, not a local one.** `--call-site <workflow>:<job>` caps the run at that step's `budget.call_sites` entry, so a local scout attempt is capped at the $8 CI uses; `--max-budget-usd` can only lower it.
- **One credential, chosen once.** With `--isolate` or `--auth-order`, the order is `--auth-order`, else `CLAUDE_AUTH_ORDER`, else `ai_auth:`, and the first credential that is **present** wins: for `oauth` the `CLAUDE_CODE_OAUTH_TOKEN` variable, then the keychain login (`claude auth status`), then the hub `.env` value; for `api_key` the variable, then `.env`. The `.env` is parsed for those two names only, never sourced. The other credential is unset — under `-p` an exported `ANTHROPIC_API_KEY` would otherwise win over OAuth — as are the CLI's other auth inputs (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDE_CONFIG_DIR`, the provider switches), and nothing falls back to it in the run, which keeps #348's status quo.
- **A 429 is capacity, not a defect**, locally too: `--usage-limit skip` turns a spent window into exit 0 with a warning ("the credential is VALID — do NOT rotate it"), the same verdict claude-cost's `usage-limit: skip` gives a scheduled loop.
- **No unmeasured run is free.** A run that leaves no result record is ledgered at its cap with `cost_source: estimated` whenever the session may have started (json output cannot show whether it did) or a wall clock or signal stopped it, and `no-spend` only when the CLI refused its argv before any request. `dash ai` reports billed and estimated dollars apart. Every figure is **API-equivalent (estimate)** under subscription auth — a throughput ceiling, not an invoice.
- **The agent's environment is built, not inherited.** `--isolate` gives claude PATH, HOME, the locale and a fixed set of offline git/npm/pip settings, plus at most one Claude credential: no GitHub token, no SSH agent, no `ANTHROPIC_BASE_URL`, no PYTHONPATH or OTEL settings. The session flags and the sandbox that go with it are recorded in ADR 0002's P1 section.
- **A monthly ceiling for the loops.** The loop runner (`tools/dash loop run`) also holds every local loop attempt to `_data/fleet.yml` `budget.loops` ($25 a UTC month, a `--scheduled` run stopping at 80%), summed over the ledger rows ai-run writes with `origin: local` and a `loop` field; an attempt runs only when the month can absorb its full call-site cap, and a plain `dash ai run` (no loop) never counts against it. `budget.loops` + `budget.jev` stay inside `harnesses.budget.monthly_ai_usd` (`test_ai_budget.py`); `tools/dash loop budget` prints the month ([docs/JEV.md](JEV.md#the-loop-runner-p1)).

## The loops

- **Self-evolution** — `triage-attention` (read Monitor signals) → `evolve-project` (fix the top item) → `refresh-portfolio` (regen) → PR → gates verify → human merges. No CI twin for the hub (`unified-evolution.yml` was retired 2026-10-27); the per-submodule CI pass is `repo-evolution.yml`. Details: [DASH.md](DASH.md#self-evolution-loop).
- **Actions optimization** — folded into the daily loop below: `fleet-pulse.yml` commits `_data/actions_usage.yml` and feeds its slow / flaky / high-cost flags into the same ranked queue as the failures, so an expensive workflow gets a *fix PR*, not just an issue. Locally, the `actions-triage` skill reads the same data. Details: [DASH.md](DASH.md#actions-optimization-loop-analytics--ai-review--issues).
- **The daily fleet loop** — `fleet-pulse.yml` (daily 06:00) gathers every signal in one job (Actions cost, Claude spend, engagement actuals, the prior-day digest `_reports/daily/<date>.md`, and the open-state snapshot `_data/fleet_triage.yml` → the [`/triage/`](https://bamr87.github.io/bamr87/triage/) portal), publishes them in ONE commit, merges the **failing** and **expensive** signals into a single ranked queue (`dash-gen remediate`), and hands it to an Opus agent that opens a draft PR **with the fix** — in the hub, or in the submodule that owns the workflow — falling back to a hub issue when it can't. Deduped by hidden marker, capped by `_data/fleet.yml`. Locally, the `triage-attention` skill reads the same snapshot. Details: [DAILY-ANALYSIS.md](DAILY-ANALYSIS.md).
- **The issue pipeline** — `issue-pipeline.yml` (daily 08:00) is the issue-side counterpart: a deterministic `scan` job derives every open issue's stage from its LABELS, scores its gaps / priority / size / autonomy, dedupes, caps per `_data/fleet.yml`, and publishes `_data/issue_pipeline.yml` → the [`/issue-pipeline/`](https://bamr87.github.io/bamr87/issue-pipeline/) portal. Then three Opus tiers: **intake** reproduces each issue in an isolated virtual environment (`tools/issue-evidence.sh`) and turns it into a specification with attached evidence; **implement** opens a draft PR; **complete** drives that PR to mergeable and marks it ready for review unless `human-review` says a person does. No tier ever merges. Because a PR opened with `GITHUB_TOKEN` never triggers its own CI, tier 2 needs `FLEET_TOKEN` for the checks tier 3 reads — the workflow probes it rather than presence-checking it. Locally, the `issue-pipeline` skill drives the same data. Details: [ISSUE-PIPELINE.md](ISSUE-PIPELINE.md).
- **Repo evolution** — `repo-evolution.yml` (weekly, Monday 09:00) is the fourth loop and the only *proactive* one: the three above react to a signal (a red workflow, a filed issue, an ageing credential); this one improves what nobody filed — documentation accuracy, onboarding, clarity, small correctness gaps — in each opted-in submodule's **own upstream repo**. A deterministic `plan` job (`dash-gen targets`) selects registry opt-ins that are owned, non-archived submodules, skips any whose previous pass is still open (one draft per repo is the backpressure), caps per `_data/fleet.yml`, and writes each a brief from the registry and the triage snapshot; a matrix `evolve` job runs one Opus agent per repo on a credential-less checkout and the *workflow* opens the draft PR, marker first. The brief tells the agent about the repo's failing workflows and open issues so it stays out of the doctor's and the pipeline's lanes. Locally, `tools/dash evolve --repo <name>` / `--all`. Details: [EVOLUTION.md](EVOLUTION.md).
- **Future-Features** — `SessionStart`/`Stop` hooks keep the pipeline active in every session; the `feature-scout` subagent proposes roadmap-ready specs; a human approves before anything lands in `_data/roadmap.yml` (rendered at the dash Roadmap surface).
- **Credential rotation** — `token-rotation.yml` (weekly, Monday 02:00) is the third reconciliation loop: `fleet-pulse` fixes broken *workflows*, `issue-pipeline` resolves *issues*, this one keeps *credentials* current. The hub is the master copy: it audits every fleet repo's secret age from GitHub's own `updated_at`, propagates the hub's stored `CLAUDE_CODE_OAUTH_TOKEN` (and `ANTHROPIC_API_KEY`, when one is set there) to any copy that is missing or stale, brings each repo's canonical repository **variables** into line with the hub's live values in the same pass, re-mints via the optional OAuth refresh grant when one is provisioned, and files one tracking issue when a human has to run `claude setup-token`. Ledger: `_data/token_rotation.yml` (names, ages, outcomes — never a value). Locally, `dash secrets plan` / `dash secrets rotate`. Details: [TOKEN-ROTATION.md](TOKEN-ROTATION.md).
- **Drift** — `drift-check.yml` runs `tools/check-drift.sh` in CI; the `/drift-report` skill explains any failure (checks (a)–(l)) with the exact fix.

## Usage dashboard (transparency + audit)

Two layers, one page family:

- **Fleet ledger — [`/ai-usage/`](https://bamr87.github.io/bamr87/ai-usage/)** (committed): `.github/workflows/fleet-pulse.yml` runs `tools/dash-gen ai-usage` daily, harvesting every Claude touchpoint the fleet leaves in public infrastructure — **CI runs** of any workflow that calls Claude by any of the fleet's three routes (`anthropics/claude-code-action`, the `claude-run` composite, a vendored `scripts/ai/run.sh`) in any registry repo **and in the hub itself**, **commits** with a `Co-Authored-By: Claude` trailer, and **PRs** carrying the Claude Code marker — into `_data/ai_usage.yml`, categorized by repo / workflow / registry category / day, with per-run audit links.
- **How a CI run is priced** (`cost_source` on every ledger row, `pricing:` for the window): `reported` is the run's own `total_cost_usd`, summed across the run's Claude sessions and de-duplicated per `session_id` (the figure is cumulative within a session, and GitHub's log zip carries each job's text twice); `tokens` prices a payload that carries a model and a token breakdown but no cost, at the same API list prices `dash ai` uses, cache writes at 1.25x/2x input and cache reads at 0.1x; `no-spend` is a run that cannot have spent anything (`skipped`, or a log with no Claude step in it — the loops open with an "is the loop on?" gate job); `estimated` is a run that ran Claude and left no usage behind, carrying an explicit `est_cost_usd` from the workflow's own priced median, else its turns at `budget.usd_per_turn`, else the fleet median. Totals report `ci_cost_usd` (measured), `ci_estimated_usd` and `ci_accounted_usd`; **the budget check reads the accounted figure** — a ceiling judged on the measured half alone read a fleet whose runs were 87% unpriced as $1.03 against $75/month (2026-10-29).
- **Local sessions — [`/ai-activity/`](https://bamr87.github.io/bamr87/ai-activity/)** (gitignored): `tools/dash ai` shadow-prices this machine's `~/.claude/projects/` transcripts with full token detail. The same page carries a separate **headless runs** table fed by `tools/dash ai run`: it reports `billed_cost_usd` (the `total_cost_usd` the CLI reported for itself, not a list-price shadow price) apart from `estimated_cost_usd` (a run that left no result, charged at its cap), under subscription auth both are API-equivalent (estimate), and the table is never summed with the scan (a headless run leaves a transcript the scan also reads, so each row is flagged `also_in_scan`). Publishing local spend is an explicit opt-in: running `tools/dash-gen ai-usage` **locally** folds the machine ledger's windowed aggregate into the committed file's `local` section; the daily CI refresh preserves (never adds, never erases) that section.

## Fleet propagation

Both fan-outs ride [`tools/fanout.sh`](../tools/fanout.sh) — dry-run by default, PRs only, additive-only, external-upstream guard, bot identity `bamr87-bot <10567847+bamr87@users.noreply.github.com>`:

- **`fanout.yml` (kit `standardize`)** with artifacts `agent-context,claude` seeds the agent-context kit ([`templates/agent-context/`](../templates/agent-context/)): a `CLAUDE.md` scaffold (only when the repo has no agent-context file) and the `@claude` mention workflow — the same `claude.yml` the hub runs. Defaults stay `editorconfig,ci`.
- **`fanout.yml` (kit `schema`)** seeds the Pyramid Schema kit; the optional `agent_fill` input runs a Claude Code pass that fills scaffold TODOs on the adoption PR branch (single target only). See [SCHEMA-FRAMEWORK.md](SCHEMA-FRAMEWORK.md).
- **`fanout.yml` (kit `harness`)** is the inventory-driven third fan-out: its `plan` job resolves `target: gaps` from the committed `_data/harness_registry.yml` (built daily by `dash-gen harnesses`, graded against `_data/fleet.yml` `harnesses:`), so agent-context kit PRs go **only to the repos the data says are missing or behind** — and `upgrade: true` refreshes machine-seeded harnesses stuck on an old kit (byte-identical check; hand-modified copies untouched). The read-only board is [`/harnesses/`](https://bamr87.github.io/bamr87/harnesses/); the runbook is [HARNESS-OPS.md](HARNESS-OPS.md).

Each fleet repo that adopts `claude.yml` needs its own `CLAUDE_CODE_OAUTH_TOKEN` secret — provisioned and kept current by the weekly rotation loop rather than by hand (see [One-time setup](#one-time-setup) and [TOKEN-ROTATION.md](TOKEN-ROTATION.md)).

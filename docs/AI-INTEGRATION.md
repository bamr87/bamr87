# AI Integration — surfaces, auth, and the loops

One page for the whole AI layer: what runs where, how it authenticates, and the feedback loops it powers. If you're setting up Claude for this repo (or a fleet repo), start at [Auth & secrets](#auth--secrets).

## The four AI surfaces

1. **Local `.claude/` layer** — skills, commands, agents, and hooks that make the dash self-managing from a local Claude Code session. The full inventory lives in [`.claude/README.md`](../.claude/README.md); highlights: the `run-dash` skill (orchestration hub, `driver.py`), `drift-report` (explains drift-gate checks (a)–(l)), `standardize-audit`/`standardize-project`, `actions-triage`, `triage-attention`/`evolve-project`/`refresh-portfolio`, the `/adopt-schema` and `/adopt-release` commands, the `feature-scout` subagent, and the Future-Features session hooks.
2. **CI workflows** — every `anthropics/claude-code-action@v1` call site in the hub: [`claude.yml`](../.github/workflows/claude.yml) (@claude mention handler), [`fleet-pulse.yml`](../.github/workflows/fleet-pulse.yml) (the daily loop's `doctor` job — the Opus fixer; self-skips without Claude auth), [`unified-evolution.yml`](../.github/workflows/unified-evolution.yml) (dispatch-only evolution pass; fails loudly without auth), the three agent tiers of [`issue-pipeline.yml`](../.github/workflows/issue-pipeline.yml) (intake / implement / complete; each self-skips without Claude auth, and tier 1 still builds and uploads its evidence bundles), the `agent_fill` job of [`schema-fanout.yml`](../.github/workflows/schema-fanout.yml), and the matrix `evolve` job of [`repo-evolution.yml`](../.github/workflows/repo-evolution.yml) (the weekly per-repo improvement pass — one Opus agent per opted-in submodule, draft PR in its upstream; the plan job fails loudly without auth, before any spend).
3. **MCP servers** — [`.mcp.json`](../.mcp.json): `github` (needs a `GITHUB_TOKEN` env var), `memory`, `sequentialthinking`, `context7`.
4. **Copilot-format reference templates** — `.github/agents/`, `.github/instructions/`, `.github/prompts/` are consumed _in place_ by hub skills (e.g. `evolve-project` reads the agent personas); nothing seeds them into submodules, and they are not Task-launchable Claude subagents (only `.claude/agents/` are).

## Auth & secrets

House convention: **OAuth-first**. Every Claude call site prefers `CLAUDE_CODE_OAUTH_TOKEN` and falls back to `ANTHROPIC_API_KEY` only when the OAuth token is absent.

| Secret | Used by | Required? |
| --- | --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude.yml`, `fleet-pulse.yml`, `issue-pipeline.yml`, `repo-evolution.yml`, `unified-evolution.yml`, `schema-fanout.yml` `agent_fill`, seeded fleet `claude.yml` workflows | Preferred Claude auth. From `claude setup-token` (a **one-year** credential), seeded onto the hub — [`token-rotation.yml`](../.github/workflows/token-rotation.yml) carries it to the rest of the fleet weekly. |
| `CLAUDE_CODE_OAUTH_REFRESH_TOKEN` | `token-rotation.yml` | **Optional**, hub only. Lets the weekly rotation re-mint the OAuth token without a browser. Unset → the loop still propagates and audits, it just asks a human when the credential nears its expiry. See [TOKEN-ROTATION.md](TOKEN-ROTATION.md). |
| `ANTHROPIC_API_KEY` | same call sites | Fallback only (used when the OAuth token is unset) |
| `FLEET_TOKEN` | `fleet-pulse.yml`, `issue-pipeline.yml`, `repo-evolution.yml`, `standardize-fanout.yml`, `schema-fanout.yml`, `token-rotation.yml` | **The one control-plane PAT.** Fine-grained, covering the fleet: `actions:read` + `contents:read` + `issues:read/write` + `pull_requests:read/write`, plus `contents:write` + **`workflows:write`** on repos the fan-outs and the fixer may open PRs against (GitHub refuses a push touching `.github/workflows/*` without the Workflows permission), plus **`secrets:write`** for the weekly rotation (writing an Actions secret is an admin-level call — `token-rotation.yml` is the only workflow that needs it). Supersedes the three legacy PATs below, which remain wired as fallbacks. |
| `FANOUT_TOKEN` | `standardize-fanout.yml`, `schema-fanout.yml` | **Legacy** — folded into `FLEET_TOKEN`. Still honoured as a fallback. |
| `ACTIONS_ANALYTICS_TOKEN` | `fleet-pulse.yml` | **Legacy** — folded into `FLEET_TOKEN`. Optional fallback (higher rate limits / private repos). |
| `DAILY_ANALYSIS_TOKEN` | `fleet-pulse.yml` | **Legacy** — folded into `FLEET_TOKEN`. Optional fallback so the digest + `/triage/` snapshot cover private submodules; without any PAT it falls back to `GITHUB_TOKEN` (public repos only). |

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
- uses: anthropics/claude-code-action@v1
  with:
    claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    anthropic_api_key: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN == '' && secrets.ANTHROPIC_API_KEY || '' }}
```

## The loops

- **Self-evolution** — `triage-attention` (read Monitor signals) → `evolve-project` (fix the top item) → `refresh-portfolio` (regen) → PR → gates verify → human merges. CI counterpart: `unified-evolution.yml` (**dispatch-only** — trigger via `tools/dash evolve`). Details: [DASH.md](DASH.md#self-evolution-loop).
- **Actions optimization** — folded into the daily loop below: `fleet-pulse.yml` commits `_data/actions_usage.yml` and feeds its slow / flaky / high-cost flags into the same ranked queue as the failures, so an expensive workflow gets a *fix PR*, not just an issue. Locally, the `actions-triage` skill reads the same data. Details: [DASH.md](DASH.md#actions-optimization-loop-analytics--ai-review--issues).
- **The daily fleet loop** — `fleet-pulse.yml` (daily 06:00) gathers every signal in one job (Actions cost, Claude spend, engagement actuals, the prior-day digest `_reports/daily/<date>.md`, and the open-state snapshot `_data/fleet_triage.yml` → the [`/triage/`](https://bamr87.github.io/bamr87/triage/) portal), publishes them in ONE commit, merges the **failing** and **expensive** signals into a single ranked queue (`dash-gen remediate`), and hands it to an Opus agent that opens a draft PR **with the fix** — in the hub, or in the submodule that owns the workflow — falling back to a hub issue when it can't. Deduped by hidden marker, capped by `_data/fleet.yml`. Locally, the `triage-attention` skill reads the same snapshot. Details: [DAILY-ANALYSIS.md](DAILY-ANALYSIS.md).
- **The issue pipeline** — `issue-pipeline.yml` (daily 08:00) is the issue-side counterpart: a deterministic `scan` job derives every open issue's stage from its LABELS, scores its gaps / priority / size / autonomy, dedupes, caps per `_data/fleet.yml`, and publishes `_data/issue_pipeline.yml` → the [`/issue-pipeline/`](https://bamr87.github.io/bamr87/issue-pipeline/) portal. Then three Opus tiers: **intake** reproduces each issue in an isolated virtual environment (`tools/issue-evidence.sh`) and turns it into a specification with attached evidence; **implement** opens a draft PR; **complete** drives that PR to mergeable and marks it ready for review unless `human-review` says a person does. No tier ever merges. Because a PR opened with `GITHUB_TOKEN` never triggers its own CI, tier 2 needs `FLEET_TOKEN` for the checks tier 3 reads — the workflow probes it rather than presence-checking it. Locally, the `issue-pipeline` skill drives the same data. Details: [ISSUE-PIPELINE.md](ISSUE-PIPELINE.md).
- **Repo evolution** — `repo-evolution.yml` (weekly, Monday 09:00) is the fourth loop and the only *proactive* one: the three above react to a signal (a red workflow, a filed issue, an ageing credential); this one improves what nobody filed — documentation accuracy, onboarding, clarity, small correctness gaps — in each opted-in submodule's **own upstream repo**. A deterministic `plan` job (`dash-gen targets`) selects registry opt-ins that are owned, non-archived submodules, skips any whose previous pass is still open (one draft per repo is the backpressure), caps per `_data/fleet.yml`, and writes each a brief from the registry and the triage snapshot; a matrix `evolve` job runs one Opus agent per repo on a credential-less checkout and the *workflow* opens the draft PR, marker first. The brief tells the agent about the repo's failing workflows and open issues so it stays out of the doctor's and the pipeline's lanes. Locally, `tools/dash evolve --repo <name>` / `--all`. Details: [EVOLUTION.md](EVOLUTION.md).
- **Future-Features** — `SessionStart`/`Stop` hooks keep the pipeline active in every session; the `feature-scout` subagent proposes roadmap-ready specs; a human approves before anything lands in `_data/roadmap.yml` (rendered at the dash Roadmap surface).
- **Credential rotation** — `token-rotation.yml` (weekly, Monday 02:00) is the third reconciliation loop: `fleet-pulse` fixes broken *workflows*, `issue-pipeline` resolves *issues*, this one keeps *credentials* current. The hub is the master copy: it audits every fleet repo's secret age from GitHub's own `updated_at`, propagates the hub's stored `CLAUDE_CODE_OAUTH_TOKEN` (and `ANTHROPIC_API_KEY`, when one is set there) to any copy that is missing or stale, brings each repo's canonical repository **variables** into line with the hub's live values in the same pass, re-mints via the optional OAuth refresh grant when one is provisioned, and files one tracking issue when a human has to run `claude setup-token`. Ledger: `_data/token_rotation.yml` (names, ages, outcomes — never a value). Locally, `dash secrets plan` / `dash secrets rotate`. Details: [TOKEN-ROTATION.md](TOKEN-ROTATION.md).
- **Drift** — `drift-check.yml` runs `tools/check-drift.sh` in CI; the `/drift-report` skill explains any failure (checks (a)–(l)) with the exact fix.

## Usage dashboard (transparency + audit)

Two layers, one page family:

- **Fleet ledger — [`/ai-usage/`](https://bamr87.github.io/bamr87/ai-usage/)** (committed): `.github/workflows/fleet-pulse.yml` runs `tools/dash-gen ai-usage` daily, harvesting every Claude touchpoint the fleet leaves in public infrastructure — **CI runs** of `anthropics/claude-code-action` in any registry repo (auto-detected from workflow content; cost + turn counts scraped from run logs), **commits** with a `Co-Authored-By: Claude` trailer, and **PRs** carrying the Claude Code marker — into `_data/ai_usage.yml`, categorized by repo / workflow / registry category / day, with per-run audit links. CI logs expose cost and turns but no token breakdown.
- **Local sessions — [`/ai-activity/`](https://bamr87.github.io/bamr87/ai-activity/)** (gitignored): `tools/dash ai` shadow-prices this machine's `~/.claude/projects/` transcripts with full token detail. Publishing local spend is an explicit opt-in: running `tools/dash-gen ai-usage` **locally** folds the machine ledger's windowed aggregate into the committed file's `local` section; the daily CI refresh preserves (never adds, never erases) that section.

## Fleet propagation

Both fan-outs ride [`tools/fanout.sh`](../tools/fanout.sh) — dry-run by default, PRs only, additive-only, external-upstream guard, bot identity `bamr87-bot <10567847+bamr87@users.noreply.github.com>`:

- **`standardize-fanout.yml`** with artifacts `agent-context,claude` seeds the agent-context kit ([`templates/agent-context/`](../templates/agent-context/)): a `CLAUDE.md` scaffold (only when the repo has no agent-context file) and the `@claude` mention workflow — the same `claude.yml` the hub runs. Defaults stay `editorconfig,ci`.
- **`schema-fanout.yml`** seeds the Pyramid Schema kit; the optional `agent_fill` input runs a Claude Code pass that fills scaffold TODOs on the adoption PR branch (single target only). See [SCHEMA-FRAMEWORK.md](SCHEMA-FRAMEWORK.md).
- **`harness-fanout.yml`** is the inventory-driven third fan-out: its `plan` job resolves `target: gaps` from the committed `_data/harness_registry.yml` (built daily by `dash-gen harnesses`, graded against `_data/fleet.yml` `harnesses:`), so agent-context kit PRs go **only to the repos the data says are missing or behind** — and `upgrade: true` refreshes machine-seeded harnesses stuck on an old kit (byte-identical check; hand-modified copies untouched). The read-only board is [`/harnesses/`](https://bamr87.github.io/bamr87/harnesses/); the runbook is [HARNESS-OPS.md](HARNESS-OPS.md).

Each fleet repo that adopts `claude.yml` needs its own `CLAUDE_CODE_OAUTH_TOKEN` secret — provisioned and kept current by the weekly rotation loop rather than by hand (see [One-time setup](#one-time-setup) and [TOKEN-ROTATION.md](TOKEN-ROTATION.md)).

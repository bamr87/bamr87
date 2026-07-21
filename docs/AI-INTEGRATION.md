# AI Integration — surfaces, auth, and the loops

One page for the whole AI layer: what runs where, how it authenticates, and the feedback loops it powers. If you're setting up Claude for this repo (or a fleet repo), start at [Auth & secrets](#auth--secrets).

## The four AI surfaces

1. **Local `.claude/` layer** — skills, commands, agents, and hooks that make the dash self-managing from a local Claude Code session. The full inventory lives in [`.claude/README.md`](../.claude/README.md); highlights: the `run-dash` skill (orchestration hub, `driver.py`), `drift-report` (explains drift-gate checks (a)–(h)), `standardize-audit`/`standardize-project`, `actions-triage`, `triage-attention`/`evolve-project`/`refresh-portfolio`, the `/adopt-schema` and `/adopt-release` commands, the `feature-scout` subagent, and the Future-Features session hooks.
2. **CI workflows** — every `anthropics/claude-code-action@v1` call site in the hub: [`claude.yml`](../.github/workflows/claude.yml) (@claude mention handler), [`actions-review.yml`](../.github/workflows/actions-review.yml) (Opus reviewer; self-skips without Claude auth), [`unified-evolution.yml`](../.github/workflows/unified-evolution.yml) (dispatch-only evolution pass; fails loudly without auth), and the `agent_fill` job of [`schema-fanout.yml`](../.github/workflows/schema-fanout.yml).
3. **MCP servers** — [`.mcp.json`](../.mcp.json): `github` (needs a `GITHUB_TOKEN` env var), `memory`, `sequentialthinking`, `context7`.
4. **Portable Copilot templates** — `.github/agents/`, `.github/instructions/`, `.github/prompts/` are templates meant to be _seeded into submodules_; they are not Task-launchable Claude subagents (only `.claude/agents/` are).

## Auth & secrets

House convention: **OAuth-first**. Every Claude call site prefers `CLAUDE_CODE_OAUTH_TOKEN` and falls back to `ANTHROPIC_API_KEY` only when the OAuth token is absent.

| Secret | Used by | Required? |
| --- | --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude.yml`, `actions-review.yml`, `daily-repo-analysis.yml`, `unified-evolution.yml`, `schema-fanout.yml` `agent_fill`, seeded fleet `claude.yml` workflows | Preferred Claude auth. From `claude setup-token`, then `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bamr87/<repo>` |
| `ANTHROPIC_API_KEY` | same call sites | Fallback only (used when the OAuth token is unset) |
| `FANOUT_TOKEN` | `standardize-fanout.yml`, `schema-fanout.yml` | Required for fan-outs — fine-grained PAT with contents + PR + **workflows** write on the targets (the kits push `.github/workflows/*` files, which GitHub refuses without the Workflows permission). **Already provisioned — verify it has the Workflows scope before the first non-dry run.** |
| `ACTIONS_ANALYTICS_TOKEN` | `actions-usage.yml`, `actions-review.yml` | Optional (higher rate limits / private repos) |
| `DAILY_ANALYSIS_TOKEN` | `daily-repo-analysis.yml` | Optional — fine-grained PAT (`actions:read`, `issues:read`, `pull_requests:read` on the fleet) so the daily digest + `/triage/` snapshot cover private submodules; falls back to `GITHUB_TOKEN` (public repos only) |
| `PAT_TOKEN` | `unified-evolution.yml` checkouts | Optional fallback to `GITHUB_TOKEN` |

### One-time setup

```bash
claude setup-token                                        # mint an OAuth token
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bamr87/bamr87    # provision the hub
# and for each fleet repo that adopts the seeded claude.yml workflow:
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bamr87/<repo>
```

> **Status:** `CLAUDE_CODE_OAUTH_TOKEN` is provisioned in `bamr87/bamr87` (since 2026-07-16), alongside `FANOUT_TOKEN` — the hub's AI steps run. `ANTHROPIC_API_KEY` remains unset (it's only the fallback). Fleet repos still need their own `CLAUDE_CODE_OAUTH_TOKEN` for seeded `claude.yml` workflows.

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
- **Actions optimization** — `actions-usage.yml` (daily) commits `_data/actions_usage.yml` → `actions-review.yml` runs the Opus reviewer that files one optimization issue per worst-offender workflow → locally, the `actions-triage` skill reads the same data and drives a direct fix or a dispatch. Details: [DASH.md](DASH.md#actions-optimization-loop-analytics--ai-review--issues).
- **Daily analysis + fleet triage** — `daily-repo-analysis.yml` (daily 06:00) commits the prior-day digest (`_reports/daily/<date>.md`) and the open-state snapshot (`_data/fleet_triage.yml` → the [`/triage/`](https://bamr87.github.io/bamr87/triage/) portal: every open issue, PR with CI status, failing workflow, prioritized inbox), then an Opus agent opens one draft PR (hub) or files one `daily-analysis` issue (submodule) per fresh CI failure — deduped by hidden marker, capped per run. Locally, the `triage-attention` skill reads the same snapshot. Details: [DAILY-ANALYSIS.md](DAILY-ANALYSIS.md).
- **Future-Features** — `SessionStart`/`Stop` hooks keep the pipeline active in every session; the `feature-scout` subagent proposes roadmap-ready specs; a human approves before anything lands in `_data/roadmap.yml` (rendered at the dash Roadmap surface).
- **Drift** — `drift-check.yml` runs `tools/check-drift.sh` in CI; the `/drift-report` skill explains any failure (checks (a)–(h)) with the exact fix.

## Usage dashboard (transparency + audit)

Two layers, one page family:

- **Fleet ledger — [`/ai-usage/`](https://bamr87.github.io/bamr87/ai-usage/)** (committed): `.github/workflows/ai-usage.yml` runs `tools/dash-gen ai-usage` daily, harvesting every Claude touchpoint the fleet leaves in public infrastructure — **CI runs** of `anthropics/claude-code-action` in any registry repo (auto-detected from workflow content; cost + turn counts scraped from run logs), **commits** with a `Co-Authored-By: Claude` trailer, and **PRs** carrying the Claude Code marker — into `_data/ai_usage.yml`, categorized by repo / workflow / registry category / day, with per-run audit links. CI logs expose cost and turns but no token breakdown.
- **Local sessions — [`/ai-activity/`](https://bamr87.github.io/bamr87/ai-activity/)** (gitignored): `tools/dash ai` shadow-prices this machine's `~/.claude/projects/` transcripts with full token detail. Publishing local spend is an explicit opt-in: running `tools/dash-gen ai-usage` **locally** folds the machine ledger's windowed aggregate into the committed file's `local` section; the daily CI refresh preserves (never adds, never erases) that section.

## Fleet propagation

Both fan-outs ride [`tools/fanout.sh`](../tools/fanout.sh) — dry-run by default, PRs only, additive-only, external-upstream guard, bot identity `bamr87-bot <10567847+bamr87@users.noreply.github.com>`:

- **`standardize-fanout.yml`** with artifacts `agent-context,claude` seeds the agent-context kit ([`templates/agent-context/`](../templates/agent-context/)): a `CLAUDE.md` scaffold (only when the repo has no agent-context file) and the `@claude` mention workflow — the same `claude.yml` the hub runs. Defaults stay `editorconfig,ci`.
- **`schema-fanout.yml`** seeds the Pyramid Schema kit; the optional `agent_fill` input runs a Claude Code pass that fills scaffold TODOs on the adoption PR branch (single target only). See [SCHEMA-FRAMEWORK.md](SCHEMA-FRAMEWORK.md).

Each fleet repo that adopts `claude.yml` needs its own `CLAUDE_CODE_OAUTH_TOKEN` secret (see [One-time setup](#one-time-setup)).

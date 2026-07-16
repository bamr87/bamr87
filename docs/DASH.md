# The Dash Architecture

This repo is a central **dash** that manages, showcases, monitors, and evolves a
portfolio of projects. Everything radiates from one machine-readable registry.

## The registry is the single source of truth

[`_data/projects.yml`](../_data/projects.yml) declares every project once.
Every surface reads from it:

```
                       _data/projects.yml   ← single source of truth (committed)
                                 │
   ┌──────────────┬─────────────┼──────────────┬──────────────┬──────────────────┐
   ▼              ▼             ▼              ▼              ▼                  ▼
Portfolio     Dashboard     Monitor        Toolbox       README.md          tools/check-drift.sh
(/portfolio)  (/dashboard)  (/monitor)     (/toolbox)    AUTO:projects      (registry ↔ .gitmodules)
                                 ▲
                  _data/project_health.yml  ← gh API: stars · CI · issues · PRs ·
                                 │                activity · security → attention (red/amber/green)
                  generated EPHEMERALLY at deploy by .github/scripts/dash-gen
```

To add or change a project, edit **only** `_data/projects.yml`. The portfolio,
dashboard, monitor, the profile `README.md` project list, and the drift gate all
follow.

## Components

| Layer | What | Where |
|---|---|---|
| Registry | Single source of truth | `_data/projects.yml` |
| Submodules | All projects, flat under one container | `projects/<name>/` (see [`projects/README.md`](../projects/README.md)) |
| Dash site | Root Jekyll site (`bamr87/zer0-mistakes` theme); dash pages are the `dash` collection (portfolio, dashboard, monitor, toolbox, actions, ai-activity, roadmap, resume, docs) | `pages/_dash/` → `bamr87.github.io/bamr87/` |
| Monitoring | Live GitHub signals + attention scoring | `.github/scripts/dash-gen` → `_data/project_health.yml` |
| AI activity | Shadow-priced Claude Code usage per repo (local-only) | `.github/scripts/dash-gen/ai_activity.py` → `_data/ai_activity.yml` + `~/.claude/ai-activity-ledger.json` |
| Actions usage | GitHub Actions cost/effectiveness analytics (via PyGithub, daily-committed) | `.github/scripts/dash-gen/actions_analytics.py` → `_data/actions_usage.yml` → `/actions/`; refreshed by `actions-usage.yml` |
| Actions review | Opus Claude Code deep-dive on failing/slow workflows → optimization **issues** (deduped) | `actions_review.py` (triage + dedupe) → `actions-review.yml` (Claude reviewer files one issue per candidate) |
| Generator | Health gathering + README AUTO regen + AI usage | `.github/scripts/dash-gen/dash_gen.py` (`tools/dash-gen`) |
| CLI | One entrypoint for dash ops | `tools/dash` (`bamr87-dash`) |
| Drift gates | Hard CI checks | `tools/check-drift.sh` + `.github/workflows/drift-check.yml` |
| Standards | Per-tier baseline + conformance audit | `_data/standards.yml`, `tools/audit-standards.sh` (`dash audit`), [`docs/STANDARDS.md`](STANDARDS.md) |
| Schema | Per-directory `SCHEMA.md` structural contracts + linter | `tools/schema_lint.py`, `tools/gen-projects-schema.py`, [`docs/SCHEMA-FRAMEWORK.md`](SCHEMA-FRAMEWORK.md) |
| Propagation | Standardization + schema PRs *into* submodules | `tools/fanout.sh` via `.github/workflows/standardize-fanout.yml` + `schema-fanout.yml`; `standard-ci.yml` (`workflow_call`) |
| Auto-fix bots | Scheduled PRs | `update-submodules.yml`, `refresh-dash.yml`, `dependabot.yml` |
| AI layer | Skills, commands, MCP | `.claude/`, `.mcp.json` |
| Future-Features | Capture feature ideas → roadmap | `_data/roadmap.yml`, `/future-features`, `feature-scout` agent + session hooks (`.claude/`) |
| Self-evolution | Dispatch-only AI pass (`tools/dash evolve`) | `.github/workflows/unified-evolution.yml` (Claude Code) |

## The dash CLI

```bash
tools/dash status         # submodules + registry + drift
tools/dash audit [name]   # standardization conformance matrix (--gate to fail on gaps)
tools/dash monitor        # refresh health, print repos needing attention
tools/dash actions        # GitHub Actions usage analytics (cost/effectiveness by workflow)
tools/dash actions-review # triage worst workflows → reviewer work order
tools/dash serve          # serve the Jekyll dash locally (docker, :4000)
tools/dash sync           # update submodules + regenerate dash data
tools/dash foreach <cmd>  # run a shell command in every checked-out submodule
tools/dash run <tool>     # run a projects/scripts/ submodule tool (forkme, stashme, ...)
tools/dash new <name>     # scaffold + register a new project
tools/dash adopt-release <repo>  # scaffold the release-please pipeline (--all)
tools/dash protect <repo> # require the CI gate on a repo's default branch (--all)
tools/dash evolve         # trigger the AI evolution workflow
tools/dash ai             # shadow-priced Claude Code usage per repo (local-only)
tools/dash doctor         # environment checks (setup.sh --dry-run)
tools/dash test           # run the aggregate test suite
tools/dash gen all        # run the generator (health + README)
```

## Monitoring & "needs attention"

`dash-gen health` aggregates, per repo: stars, CI build stats (pass-rate, last
conclusion, failing workflows), open issues (bugs / good-first-issue / stale),
open PRs, commit activity (7/30d, last-commit age), latest release age, and
security alerts. It computes an **attention level**:

- 🔴 **red** — CI failing, or an `active` repo with no commits past the stale
  threshold, or open security alerts.
- 🟠 **amber** — too many open bugs, stale issues, flaky CI, or security alerts.
- 🟢 **green** — healthy.

Thresholds live in [`_data/health_thresholds.yml`](../_data/health_thresholds.yml).
The board surfaces on the `/monitor/` page (and a "Needs Attention" strip on Home),
in `tools/dash monitor`, and as the input signal for the self-evolution loop.

## AI activity (shadow-priced usage)

`tools/dash ai` tracks Claude Code activity across **every repo touched from this
machine** — including repos outside the monorepo. Claude Code writes a JSONL
transcript per session to `~/.claude/projects/` with the model and full token
breakdown for every assistant turn; on a subscription plan there's no invoice, so
the generator answers *"what would this cost at API list prices?"*:

- **Scan** all session files, dedupe streamed records, attribute each turn to a
  repo via its `cwd` (worktrees and submodule gitdirs fold back to their repo).
- **Persist** daily `(machine, day, repo, model)` aggregates in
  `~/.claude/ai-activity-ledger.json` (max-merge), so history outlives Claude
  Code's ~30-day transcript cleanup.
- **Report** to the gitignored `_data/ai_activity.yml`, rendered at `/ai-activity/`
  (repo/model/day tables, cache-read ratio — the highest-leverage cost signal).

Costs are **estimates** (tokens × list prices; unknown models are flagged, not
guessed). Local-only by design: it never runs in CI, and the published dash shows
a "run `tools/dash ai` locally" notice instead of your spend.

## Actions optimization loop (analytics → AI review → issues)

The Actions layer doesn't just *report* waste — it closes the loop:

1. **Measure** — `actions-usage.yml` (daily) runs `actions_analytics.py` across the
   fleet and commits `_data/actions_usage.yml`, flagging each workflow as
   `failing` / `flaky` / `slow` / `high-cost-low-value` / `cancel-heavy` and
   ranking by a `priority` score (wasted minutes + ineffective minutes). Rendered
   at `/actions/`.
2. **Triage** — `actions-review.yml` (right after the refresh) runs
   `dash-gen actions-review`: it selects the top offenders, **dedupes** them
   against open `actions-review` issues (a hidden `<!-- actions-review key=… -->`
   marker), enriches each with links to the specific failing/slowest runs, and
   writes a capped Markdown *work order*. Selection + dedupe are deterministic code
   so the AI step can't spam.
3. **Review & file** — an **Opus Claude Code reviewer** reads the work order, does a
   deeper root-cause dive (`gh run view --log-failed`, reads the workflow file),
   and opens ONE GitHub issue per candidate in `bamr87/bamr87` — each naming the
   submodule + its workflow/responsibility with a concrete proposed fix (caching,
   `concurrency`, `timeout-minutes`, trigger gating, cron cadence, a failing-step
   fix…). Gated on Claude auth (`CLAUDE_CODE_OAUTH_TOKEN` preferred,
   `ANTHROPIC_API_KEY` fallback — see [AI-INTEGRATION.md](AI-INTEGRATION.md));
   self-skips when absent.

Run the triage locally with `tools/dash actions-review` (add `--no-enrich` to skip
the run-link lookups); the analytics itself is `tools/dash actions`.

## Anti-drift: gates + auto-fix PRs

**Hard gates** ([`tools/check-drift.sh`](../tools/check-drift.sh), run by
`drift-check.yml` — a fast offline+API check, no site build) fail CI on: registry
↔ `.gitmodules` mismatch, stray/unregistered project dirs, a stale README AUTO
span, missing top-level READMEs, and SCHEMA.md pyramid errors or a stale
generated `projects/SCHEMA.md` (check (h), `tools/schema_lint.py`). Advisory
(non-gating): GitHub-reality drift (renames/deletions/branch) and
standardization. The internal-link check is local-only
(`tools/check-drift.sh --links`, needs a built `_site`).

**Pyramid Schema**: every directory carries a lintable `SCHEMA.md` contract of
what lives where ([SCHEMA-FRAMEWORK.md](SCHEMA-FRAMEWORK.md)). `projects/SCHEMA.md`
is generated by `tools/gen-projects-schema.py`; submodules adopt their own
pyramids via the seed kit (`tools/seed-schema.sh`) or `schema-fanout.yml`.

**Auto-fix bots** open PRs (never direct pushes to `master`): submodule pointer
bumps (`update-submodules.yml`), projects/README/registry refresh (`refresh-dash.yml`),
and dependency updates (`dependabot.yml`).

Live monitoring data (`project_health.yml`) is network-derived, **ephemeral**, and
gitignored — generated on each deploy so it never flaps the gate.

## Self-evolution loop

`triage-attention` reads the Monitor signals → `sync-project-docs` updates the
registry → `evolve-project` makes a focused improvement → `refresh-portfolio`
regenerates → PR to `main` → gates verify → human merges → dash republishes. The CI
counterpart is `unified-evolution.yml` (**dispatch-only** — trigger via
`tools/dash evolve`; via `anthropics/claude-code-action`; auth:
`CLAUDE_CODE_OAUTH_TOKEN` preferred, `ANTHROPIC_API_KEY` fallback — see
[AI-INTEGRATION.md](AI-INTEGRATION.md)). So "which repos need attention" both shows
on the frontend and steers what the AI works on next.

## One-time setup

1. Repo **Settings → Pages → Source = "GitHub Actions"** (the dash deploys via
   `build-dash.yml`, the sole Pages surface; the old MkDocs `build-docs.yml` has
   been removed).
2. Provision Claude auth for the AI workflows (`claude.yml`, `actions-review.yml`,
   `unified-evolution.yml`, `schema-fanout.yml` `agent_fill`): `claude setup-token`
   → `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bamr87/bamr87` (preferred;
   `ANTHROPIC_API_KEY` is the fallback). Full secrets matrix:
   [AI-INTEGRATION.md](AI-INTEGRATION.md).
3. `pip install -r .github/scripts/dash-gen/requirements.txt` and `gh auth login`
   for local `tools/dash-gen health`.

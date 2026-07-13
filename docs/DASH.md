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
| Dash site | Root Jekyll site (`bamr87/zer0-mistakes` theme); dash pages are the `dash` collection | `pages/_dash/` → `bamr87.github.io/bamr87/` |
| Monitoring | Live GitHub signals + attention scoring | `.github/scripts/dash-gen` → `_data/project_health.yml` |
| AI activity | Shadow-priced Claude Code usage per repo (local-only) | `.github/scripts/dash-gen/ai_activity.py` → `_data/ai_activity.yml` + `~/.claude/ai-activity-ledger.json` |
| Actions usage | GitHub Actions cost/effectiveness analytics (via PyGithub, daily-committed) | `.github/scripts/dash-gen/actions_analytics.py` → `_data/actions_usage.yml` → `/actions/`; refreshed by `actions-usage.yml` |
| Generator | Health gathering + README AUTO regen + AI usage | `.github/scripts/dash-gen/dash_gen.py` (`tools/dash-gen`) |
| CLI | One entrypoint for dash ops | `tools/dash` (`bamr87-dash`) |
| Drift gates | Hard CI checks | `tools/check-drift.sh` + `.github/workflows/drift-check.yml` |
| Standards | Per-tier baseline + conformance audit | `_data/standards.yml`, `tools/audit-standards.sh` (`dash audit`), [`docs/STANDARDS.md`](STANDARDS.md) |
| Propagation | Standardization PRs *into* submodules | `.github/workflows/standardize-fanout.yml` + `standard-ci.yml` (`workflow_call`) |
| Auto-fix bots | Scheduled PRs | `update-submodules.yml`, `refresh-dash.yml`, `dependabot.yml` |
| AI layer | Skills, commands, MCP | `.claude/`, `.mcp.json` |
| Future-Features | Capture feature ideas → roadmap | `_data/roadmap.yml`, `/future-features`, `feature-scout` agent + session hooks (`.claude/`) |
| Self-evolution | Weekly AI pass | `.github/workflows/unified-evolution.yml` (Claude Code) |

## The dash CLI

```bash
tools/dash status     # submodules + registry + drift
tools/dash monitor    # refresh health, print repos needing attention
tools/dash serve      # serve the Jekyll dash locally (docker, :4000)
tools/dash sync       # update submodules + regenerate dash data
tools/dash run <tool> # run a projects/scripts/ submodule tool (forkme, stashme, ...)
tools/dash new <name> # scaffold + register a new project
tools/dash evolve     # trigger the AI evolution workflow
tools/dash ai         # shadow-priced Claude Code usage per repo (local-only)
tools/dash gen all    # run the generator (health + README)
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

## Anti-drift: gates + auto-fix PRs

**Hard gates** ([`tools/check-drift.sh`](../tools/check-drift.sh), run by
`drift-check.yml` — a fast offline+API check, no site build) fail CI on: registry
↔ `.gitmodules` mismatch, stray/unregistered project dirs, a stale README AUTO
span, and missing top-level READMEs. Advisory (non-gating): GitHub-reality drift
(renames/deletions/branch) and standardization. The internal-link check is
local-only (`tools/check-drift.sh --links`, needs a built `_site`).

**Auto-fix bots** open PRs (never direct pushes to `master`): submodule pointer
bumps (`update-submodules.yml`), projects/README/registry refresh (`refresh-dash.yml`),
and dependency updates (`dependabot.yml`).

Live monitoring data (`project_health.yml`) is network-derived, **ephemeral**, and
gitignored — generated on each deploy so it never flaps the gate.

## Self-evolution loop

`triage-attention` reads the Monitor signals → `sync-project-docs` updates the
registry → `evolve-project` makes a focused improvement → `refresh-portfolio`
regenerates → PR to `main` → gates verify → human merges → dash republishes. The CI
counterpart is `unified-evolution.yml` (weekly, via `anthropics/claude-code-action`,
needs the `ANTHROPIC_API_KEY` secret). So "which repos need attention" both shows
on the frontend and steers what the AI works on next.

## One-time setup

1. Repo **Settings → Pages → Source = "GitHub Actions"** (the dash deploys via
   `build-dash.yml`, the sole Pages surface; the old MkDocs `build-docs.yml` has
   been removed).
2. Add the `ANTHROPIC_API_KEY` repo secret to enable `unified-evolution.yml`.
3. `pip install -r .github/scripts/dash-gen/requirements.txt` and `gh auth login`
   for local `tools/dash-gen health`.

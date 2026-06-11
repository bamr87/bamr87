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
| Generator | Health gathering + README AUTO regen | `.github/scripts/dash-gen/dash_gen.py` (`tools/dash-gen`) |
| CLI | One entrypoint for dash ops | `tools/dash` (`bamr87-dash`) |
| Drift gates | Hard CI checks | `tools/check-drift.sh` + `.github/workflows/drift-check.yml` |
| Auto-fix bots | Scheduled PRs | `update-submodules.yml`, `refresh-dash.yml`, `dependabot.yml` |
| AI layer | Skills, commands, MCP | `.claude/`, `.mcp.json` |
| Self-evolution | Weekly AI pass on the monorepo | `.github/workflows/unified-evolution.yml` (Claude Code) |
| Per-repo evolution | Weekly AI pass on each upstream submodule (draft PRs) | `evolution-scheduler.yml` → `repo-evolution.yml` ([`docs/EVOLUTION.md`](EVOLUTION.md)) |

## The dash CLI

```bash
tools/dash status     # submodules + registry + drift
tools/dash monitor    # refresh health, print repos needing attention
tools/dash serve      # serve the Jekyll dash locally (docker, :4000)
tools/dash sync       # update submodules + regenerate dash data
tools/dash run <tool> # run a projects/scripts/ submodule tool (forkme, stashme, ...)
tools/dash new <name> # scaffold + register a new project
tools/dash evolve     # evolve the monorepo itself (unified-evolution.yml)
tools/dash evolve --repo <name>  # evolve one upstream submodule (draft PR upstream)
tools/dash evolve --all          # weekly fan-out across all auto_evolve submodules
tools/dash gen all    # run the generator (health + README)
tools/dash gen targets # print the per-repo evolution matrix (auto_evolve submodules)
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

## Anti-drift: gates + auto-fix PRs

**Hard gates** ([`tools/check-drift.sh`](../tools/check-drift.sh), run by
`drift-check.yml`) fail CI on: registry ↔ `.gitmodules` mismatch, stale README
AUTO span, missing READMEs, submodule branch drift, and broken internal dash links.

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

Beyond the monorepo, the **per-repo evolution framework** carries the same idea to the
individual upstream repos: `evolution-scheduler.yml` builds a matrix from every submodule
with `auto_evolve: true` (via `dash-gen targets`) and fans out to `repo-evolution.yml`,
which runs Claude Code against each repo and opens a **draft PR upstream**. The shared
prompts live in `.github/evolution/`. Full details in [`docs/EVOLUTION.md`](EVOLUTION.md).

## One-time setup

1. Repo **Settings → Pages → Source = "GitHub Actions"** (the dash deploys via
   `build-dash.yml`; the old MkDocs `build-docs.yml` is now manual-only).
2. Add the `ANTHROPIC_API_KEY` repo secret to enable `unified-evolution.yml`. For the
   per-repo framework also add `PAT_TOKEN` (PAT with `repo` + PR scope on the target repos).
3. `pip install -r .github/scripts/dash-gen/requirements.txt` and `gh auth login`
   for local `tools/dash-gen health`.

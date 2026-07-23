# dash-gen

Registry-driven generator for the development dash. Reads the single source of truth — [`_data/projects.yml`](../../../_data/projects.yml) — and:

- **`health`** → gathers live GitHub signals (stars, CI build stats, issues, PRs, commit activity, security alerts, latest release) per project, computes an **attention level** (red/amber/green + reasons) from [`_data/health_thresholds.yml`](../../../_data/health_thresholds.yml), and writes `_data/project_health.yml`. This file is **ephemeral** — generated at deploy time, gitignored, never committed.
- **`readme`** → rewrites only the `<!-- AUTO:projects -->` span of the profile [`README.md`](../../../README.md) from the registry's static facts. Deterministic and safe to commit. `--check` fails (non-zero) if the span is stale instead of writing — used by the drift gate.
- **`ai`** → shadow-prices local Claude Code usage per repo ([`ai_activity.py`](ai_activity.py)). Scans the per-session JSONL ledgers under `~/.claude/projects/`, dedupes streamed records, attributes each turn to a repo via its `cwd` (worktrees/submodules normalized), max-merges daily aggregates into a **persistent ledger** (`~/.claude/ai-activity-ledger.json`, so history survives Claude Code's ~30-day transcript cleanup), and writes `_data/ai_activity.yml` — **ephemeral**, gitignored, rendered by the `/ai-activity/` dash page. Costs are estimates at Anthropic API list prices (subscription usage bills nothing per token). **Local-only**: not part of `all`, never runs in CI, and spend data is never committed or published.
- **`actions`** → GitHub Actions usage analytics ([`actions_analytics.py`](actions_analytics.py)). Queries the Actions API for every registry repo via the **PyGithub** integration library, aggregates per-workflow consumption (wall-clock minutes, success/failure, **effectiveness** = share of minutes ending in success, **waste** = minutes on non-success runs), groups by workflow **type**, flags "high-running, low-effective" workflows, and writes `_data/actions_usage.yml` — rendered by the `/actions/` dash page. Unlike `health`/`ai`, this file is **committed** and refreshed **daily** by [`actions-usage.yml`](../../workflows/actions-usage.yml) so the page shows a stable once-a-day snapshot. Auth via `GH_TOKEN`/`GITHUB_TOKEN` or `gh auth token`.
- **`ai-usage`** → the COMMITTED fleet Claude Code ledger ([`ai_usage_collector.py`](ai_usage_collector.py)). Harvests every Claude touchpoint in public infrastructure: workflow runs of `anthropics/claude-code-action` in any registry repo (auto-detected from workflow content; **cost + turn counts scraped from run logs** — CI logs carry no token breakdown), commits with a `Co-Authored-By: Claude` trailer, and PRs carrying the Claude Code marker. Writes `_data/ai_usage.yml` (committed, refreshed daily by [`ai-usage.yml`](../../workflows/ai-usage.yml)), rendered by `/ai-usage/`. Run it **locally** to also fold the machine ledger's aggregate into the `local` section (an explicit publish); the CI refresh preserves that section without adding to it.
- **`daily`** → prior-day fleet activity digest + failure work order ([`daily_report.py`](daily_report.py)). Scans every registry repo (PyGithub) for the window's commits, PRs, issues, releases, and CI failures; writes the **committed** digest `_reports/daily/<date>.md` (+ regenerates the `_reports/README.md` index span) and an ephemeral, **deduped** failure work order for the [`daily-repo-analysis.yml`](../../workflows/daily-repo-analysis.yml) agent.
- **`triage`** → fleet-wide OPEN-state snapshot ([`fleet_triage.py`](fleet_triage.py)). Inventories every registry repo's open issues (items + labels/age), open PRs (draft/dependabot/CI status), and each workflow's latest completed conclusion; computes a deterministic per-repo attention score and a prioritized cross-fleet **inbox**; writes `_data/fleet_triage.yml` — **committed**, refreshed daily by the same `daily-repo-analysis.yml` run, rendered by the `/triage/` portal page. External mirrors are excluded from totals/scores/inbox.
- **`estimate`** → client-engagement estimates ([`engagements.py`](engagements.py)). Treats every registry project as a client: sweeps open issues from the committed triage snapshot (offline; `--repo`/`--issue` narrow it, single issues fall back to `gh api`), classifies each deterministically (**estimator-v1**: labels/title → type → tier, per-repo calibration from `ai_usage.yml`), prices it from the rate card `_data/engagement_rates.yml` (AI tokens at API list prices + human **broker** hours + CI minutes + confidence contingency, with a pre-AI `traditional` comparison → **leverage**), and appends draft engagements (status: `estimated` — proposals a human approves) to `_data/engagements.yml` — **committed**, rendered at `/engagements/`. Idempotent: same snapshot in, byte-identical file out. See [`docs/ESTIMATION.md`](../../../docs/ESTIMATION.md).
- **`ledger`** → engagement actuals + variance ([`engagements.py`](engagements.py)). Accrues auditable evidence — `ai_usage.yml` CI runs (real cost), Claude commits/PRs, plus this machine's ai-activity ledger unless `--no-local` — into each approved/in-progress/delivered engagement (URL-deduped, oldest-open-first attribution), recomputes actual cost (AI + broker hours + platform), variance bands, and the per-client + fleet rollups. Also the status console: `--set-status ENG-NNNN=<status>` (validated lifecycle) and `--broker ENG-NNNN=<hours>`. Runs daily in CI via `ai-usage.yml` right after the evidence harvest.
- **`all`** → `health` then `readme`.

## Usage

```bash
pip install -r .github/scripts/dash-gen/requirements.txt
gh auth login                       # health needs GitHub API access (or GH_TOKEN in CI)

python .github/scripts/dash-gen/dash_gen.py health
python .github/scripts/dash-gen/dash_gen.py readme [--check]
python .github/scripts/dash-gen/dash_gen.py ai [--window 30] [--ledger PATH] [--claude-dir PATH]

# or via the wrapper:
tools/dash-gen health
tools/dash-gen readme
tools/dash-gen ai        # also: tools/dash ai
tools/dash-gen ai-usage --days 14  # committed fleet Claude ledger (/ai-usage/)
tools/dash-gen actions --days 14   # also: tools/dash actions
tools/dash-gen daily --days 1      # also: tools/dash daily (digest + work order)
tools/dash-gen triage              # also: tools/dash triage (open-state snapshot, /triage/)
tools/dash-gen estimate --limit 10 # also: tools/dash estimate (draft engagement estimates)
tools/dash-gen ledger              # also: tools/dash ledger (accrue actuals + variance)
```

GitHub access uses the `gh` CLI, so failures degrade gracefully (a project that can't be reached yields nulls, not a crash).

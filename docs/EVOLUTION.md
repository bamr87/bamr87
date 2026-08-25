# Per-Repo Evolution Framework

A scheduled, registry-driven framework that automatically **reviews, analyzes, and
contributes** improvements back to the individual upstream repositories behind this
monorepo's submodules. Each run opens a **draft pull request** in the target repo focused
on improving its **documentation, functionality, and clarity**.

> **Two evolution layers — don't confuse them**
>
> | Layer | Workflow | Target | PR opened against |
> |-------|----------|--------|-------------------|
> | Monorepo self-evolution | `unified-evolution.yml` | this repo (`bamr87/bamr87`) | root `main` |
> | **Per-repo evolution (this doc)** | `evolution-scheduler.yml` → `repo-evolution.yml` | each upstream submodule repo | that repo's branch |

## How it works

```
_data/projects.yml                 # registry — auto_evolve: true opts a repo in
        │
        ▼
dash-gen targets                   # emits the JSON matrix of eligible submodules
        │
        ▼
evolution-scheduler.yml (weekly)   # fans out a parallel matrix, one job per repo
        │  uses: ./.github/workflows/repo-evolution.yml
        ▼
repo-evolution.yml (per repo)
   1. assemble prompt  ← .github/evolution/evolve-prompt.md + categories/<category>.md
   2. checkout target repo (FLEET_TOKEN)
   3. run anthropics/claude-code-action
   4. commit changes → branch ai-evolution/<date>-<run_id>
   5. gh pr create --draft   (in the TARGET repo)
```

- **Selection:** full weekly matrix over every submodule with `auto_evolve: true`. Schedule
  is `cron: '0 7 * * 1'` (Mon 07:00 UTC), offset after the 06:00 root run.
- **Scope today:** the three authored submodules — `cv-builder-pro` (main), `README` (main),
  `scripts` (main). `microsoft/skills` is excluded (not owned).
- **Delivery:** draft PRs only — a human reviews and merges. Nothing is auto-merged.

## Adding or removing a repo

Edit **only** the registry — `_data/projects.yml`:

```yaml
- name: scripts
  submodule_path: projects/scripts
  ...
  auto_evolve: true        # ← opt in / out here
```

Only repos that are **submodules you own and can open PRs against** should be enabled.
Verify the resulting matrix locally:

```bash
python3 .github/scripts/dash-gen/dash_gen.py targets   # or: tools/dash gen targets
```

## Required secrets

Both are part of the hub's token contract (`_data/fleet.yml`) and already live on `bamr87/bamr87` — audit with `tools/dash secrets`:

| Secret | Purpose |
|--------|---------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code (`anthropics/claude-code-action`) — preferred; `ANTHROPIC_API_KEY` is the fallback, OAuth-first at every call site (see [AI-INTEGRATION.md](AI-INTEGRATION.md)) |
| `FLEET_TOKEN` | The control-plane PAT with `repo` scope on **each target repo** — `GITHUB_TOKEN` cannot push or open PRs in other repositories, and fires no workflow events for refs it pushes |

## Running it manually

```bash
tools/dash evolve --all                       # trigger the full weekly fan-out now
tools/dash evolve --repo scripts              # evolve one repo
tools/dash evolve --repo scripts -f dry_run=true   # run Claude but open no PR
tools/dash evolve                             # (unchanged) evolve the monorepo itself
```

Or from the Actions tab: run **Evolution Scheduler (per-repo)** or **Per-Repo AI
Evolution** via `workflow_dispatch`.

## Tuning what the AI does

The prompt is version-controlled in [`.github/evolution/`](../.github/evolution/):

- `evolve-prompt.md` — base goals + hard guardrails (surgical, README-First/Last,
  Conventional Commits, no suppressions, draft-only, verify before finishing).
- `categories/{docs,full-stack-ai,dev-tools}.md` — per-category emphasis.

The manual `/evolve-project` skill reuses the same files, so automated and manual passes
stay consistent.

## Safety model

- **Draft PRs only** — every change is human-reviewed before merge.
- **Surgical scope** — the prompt forbids broad refactors and unrelated reformatting.
- **No secret/release tampering** — the prompt explicitly bars credential, license, and
  version changes.
- **Graceful no-op** — if a repo needs nothing, the run makes no changes and opens no PR.
- **Isolated blast radius** — `fail-fast: false`; one repo failing doesn't block the others.

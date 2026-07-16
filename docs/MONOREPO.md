# Monorepo Organization

> **This repo is a dash (control plane).** For the architecture — registry,
> surfaces, monitoring, drift gates, standardization, and the AI loop — read
> **[DASH.md](DASH.md)** first. This file covers the submodule mechanics.

The bamr87 repository is a monorepo of **~40 Git submodules** under `projects/`,
each a separate repository with its own stack, branch, and release cycle. The
root repo is the machinery that manages, monitors, documents, and standardizes
them; it is also the GitHub profile README and the published Jekyll dash site.

## The registry is the source of truth

The authoritative project list is **[`_data/projects.yml`](../_data/projects.yml)**,
cross-checked against `.gitmodules` by `tools/check-drift.sh`. This document does
not enumerate the submodules — read the registry, or:

```bash
tools/dash status         # registry + drift summary
git submodule status      # checked-out SHAs + branches
```

## Repository structure

```
bamr87/
├── _data/projects.yml    # THE REGISTRY — single source of truth
├── _data/standards.yml   # per-tier standardization requirements
├── pages/_dash/          # the Jekyll dash collection (Portfolio/Dashboard/Monitor/…)
├── projects/<name>/      # ~40 submodules, flat (category lives in the registry, not the fs)
├── tools/                # dash CLI + submodule/standardization scripts
│   ├── dash              #   unified CLI (status/audit/monitor/serve/sync/foreach/…)
│   ├── check-drift.sh    #   hard drift + standardization gate
│   ├── audit-standards.sh#   per-repo conformance matrix
│   └── update-submodules.sh
├── .github/
│   ├── workflows/        # build-dash, drift-check, refresh-dash, update-submodules, the fan-outs, …
│   ├── actions/          # reusable composite actions
│   └── agents|instructions|prompts/  # PORTABLE templates seeded into submodules
├── .claude/              # skills, commands, agents, hooks (dash-operational AI layer)
├── docs/                 # this documentation set (DASH.md is canonical)
├── .gitmodules           # submodule definitions (parity-checked vs the registry)
└── README.md             # GitHub profile README (AUTO:projects span is generated)
```

Logical grouping (docs / full-stack-ai / dev-tools / dash) lives in the
registry's `category` field, **not** the filesystem — so a project is
re-categorized by editing one line, without moving files.

## Why submodules

We use Git submodules rather than a monorepo build tool because each project must
keep **independent development, versioning, and release cycles**, and be
clonable/deployable on its own. The dash adds the coordination layer on top:
one registry, one CLI, one drift gate, one standardization pipeline.

## Working with submodules

### Setup

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
# already cloned:
git submodule update --init --recursive
```

At scale you rarely need all 40 checked out — `tools/dash sync` supports a
per-project/category subset.

### Making changes inside a submodule

A change inside a submodule is committed **in its own repo first**, then the
pointer is recorded in root. Use the submodule's own name, not `cv`:

```bash
cd projects/<name>
git checkout <branch>                    # read the branch from .gitmodules
git checkout -b feature/thing
# ...edit...
git add . && git commit -m "feat: ..."
git push origin feature/thing            # PR + merge in bamr87/<name>
cd ../..
git add projects/<name>
git commit -m "chore: bump <name> submodule"
```

Never bundle changes across multiple submodules into one PR.

### Updating pointers

```bash
./tools/update-submodules.sh             # refresh all onto declared branch (safe by default)
./tools/update-submodules.sh <name>      # one
```

The `update-submodules.yml` workflow does the same on a weekly schedule and opens
a reviewable PR — pointer bumps only, never content changes.

## Automated workflows

| Workflow | Direction | What |
|---|---|---|
| `build-dash.yml` | root | Builds the Jekyll dash and deploys to GitHub Pages (the sole Pages surface). |
| `drift-check.yml` | root | Hard gate: registry↔.gitmodules parity, stray projects, README freshness, missing top-level READMEs, SCHEMA.md pyramid (check h). Advisory: GitHub-reality drift + standardization. Also runs `actionlint`. |
| `refresh-dash.yml` | root | Nightly PR refreshing the README AUTO span + registry data. |
| `update-submodules.yml` | up | Weekly PR bumping submodule pointers into root. |
| `standardize-fanout.yml` | down | Opens standardization PRs into submodules via `tools/fanout.sh` (.editorconfig, the reusable `standard-ci.yml` caller, and on request the agent-context kit). |
| `schema-fanout.yml` | down | Opens Pyramid Schema adoption PRs into submodules via `tools/fanout.sh` (dry-run default; optional `agent_fill` Claude pass). |
| `claude.yml` | root | `@claude` mention handler (Claude Code) — same file the agent-context kit seeds into submodules. |
| `actions-usage.yml` | root | Daily commit of the Actions cost/effectiveness analytics (`_data/actions_usage.yml`). |
| `actions-review.yml` | root | Opus Claude Code reviewer files one optimization issue per worst-offender workflow. |

The generic `unified-*.yml` suite is legacy/dispatch-only (see
[DASH.md](DASH.md) and the workflow README).

## Troubleshooting

```bash
git submodule update --init --recursive   # not initialized
cd projects/<name> && git checkout <branch>; cd -   # detached HEAD
git submodule update --init --force        # reset to parent's recorded SHA
```

## Resources

- [DASH.md](DASH.md) — the dash architecture (start here)
- [STANDARDS.md](STANDARDS.md) — the per-tier standardization baseline
- [SUBMODULES.md](../SUBMODULES.md) — submodule quick reference
- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup
- [Git Submodules Documentation](https://git-scm.com/book/en/v2/Git-Tools-Submodules)

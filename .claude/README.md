# .claude/ — AI orchestration layer

Claude Code configuration that makes the dash self-managing.

## Contents

| Path | Purpose |
| --- | --- |
| `skills/update-registry/` | Reconcile `_data/projects.yml` with `.gitmodules` + repo metadata |
| `skills/refresh-portfolio/` | Regenerate monitoring data + README project list |
| `skills/sync-project-docs/` | Pull each project's current summary/status into the registry |
| `skills/sync-cv/` | Sync bamr87/cv's data/cv.json with the fleet via the `dash-gen cv` projection (`_data/cv_portfolio.json`) — curated merge PR, never a mechanical overwrite |
| `skills/drift-report/` | Explain drift-gate failures and the exact fix |
| `skills/standardize-audit/` | Audit the fleet against the tiered baseline (`dash audit`); explain each gap |
| `skills/standardize-project/` | Bring one submodule up to its tier baseline and open a PR |
| `skills/onboard-dir/` | Adopt or remove a stray/unregistered `projects/*/` dir the drift gate flagged |
| `skills/new-project/` | Scaffold + register a new project |
| `skills/triage-attention/` | Turn Monitor-board signals into prioritized actions |
| `skills/actions-triage/` | Explain the worst Actions workflows from `_data/actions_usage.yml`; drive a direct fix or dispatch `fleet-pulse.yml` (its `doctor` job is the AI fix pass) |
| `skills/issue-pipeline/` | Read the three-tier issue queues from `_data/issue_pipeline.yml`, build an issue's evidence bundle in an isolated virtual environment, and dispatch the intake/implement/complete tiers of `issue-pipeline.yml` |
| `skills/estimate-issue/` | Deep-analyze a GitHub issue into a client-engagement estimate in `_data/engagements.yml` (refines the `dash estimate` draft; approval stays human) |
| `skills/evolve-project/` | Focused per-project improvement pass (reads `.github/agents` personas as guidance; shares its goals file `.github/evolution/evolve-prompt.md` with the weekly `repo-evolution.yml` loop) |
| `skills/archify/` | Vendored [tt-a1i/archify](https://github.com/tt-a1i/archify) (MIT) — typed-JSON → validated HTML diagrams; the hub's harness/loop illustrations in `diagrams/` are authored with it and rendered by `tools/render-diagrams.sh` |
| `skills/run-dash/` | Orchestration hub: whole-repo project map + per-project "work order" (branch, stack, run cmd, context) for dispatching into a submodule; serve/screenshot the Jekyll dash. Driven by `driver.py` |
| `commands/dash-status.md` | `/dash-status` — read-only status |
| `commands/evolve.md` | `/evolve` — run the self-evolution loop |
| `commands/register-project.md` | `/register-project` — add/reconcile a project |
| `commands/adopt-release.md` | `/adopt-release <repo>` — adopt the standardized release-please pipeline (scaffold + PR) |
| `commands/adopt-schema.md` | `/adopt-schema <submodule>` — seed the Pyramid Schema kit into one submodule (preview → apply → PR) |
| `commands/future-features.md` | `/future-features <idea>` — draft a full feature spec + place it on the right repo's roadmap |
| `agents/feature-scout.md` | sub-agent that scans the session thread for latent feature ideas and proposes roadmap-ready specs (review/approval before backlog) |
| `hooks/` | `SessionStart` + `Stop` hooks that make the Future-Features pipeline active in **every** session (see `hooks/README.md`) |
| `settings.json` | registers the hooks above |

MCP servers (github, memory, sequentialthinking, context7) are configured in the repo-root [`.mcp.json`](../.mcp.json). The `github` server needs a `GITHUB_TOKEN` env var (referenced as `${GITHUB_TOKEN}` in `.mcp.json`).

> **Templates vs. subagents:** `.github/agents/`, `.github/instructions/`, and `.github/prompts/` are **Copilot-format reference templates** (per `.github/docs/toolkit-retention-map.md`) consumed in place by hub skills (e.g. `evolve-project` reads the agent personas) — nothing seeds them into submodules, and Claude Code cannot Task-launch them. Only `.claude/agents/` (feature-scout) are real subagents. For a working-diff review use the native `/code-review` skill.

## Standardization

`standardize-audit` (see what's off-standard, via `tools/dash audit` + [`_data/standards.yml`](../_data/standards.yml)) → `standardize-project` (fix one repo, PR into its own repo) → the `standardize-fanout.yml` workflow (fleet-wide `.editorconfig` + reusable `standard-ci.yml` adoption, plus the `agent-context,claude` artifacts: `CLAUDE.md` scaffold, `@claude` mention workflow, and the minimal `.claude/settings.json` baseline from [`templates/agent-context/`](../templates/agent-context/)). The full standard lives in [`docs/STANDARDS.md`](../docs/STANDARDS.md).

## The Future-Features pipeline

Captures feature ideas before they're lost and routes them to the right repo's roadmap. The backlog is [`_data/roadmap.yml`](../_data/roadmap.yml) (source of truth; rendered at the dash **Roadmap** surface), targets come from [`_data/projects.yml`](../_data/projects.yml) (or `bamr87` for the monorepo).

- **Manual:** `/future-features <idea>` → drafts a full spec → review/approval → appends to `_data/roadmap.yml` (optionally opens a GitHub issue).
- **Automatic:** a `SessionStart` hook keeps the workflow active; a throttled `Stop` hook nudges the `feature-scout` sub-agent (once per session) when feature-signal language appears. The scout **proposes**; a human approves; nothing is backlogged without approval. Opt out with `FUTURE_FEATURES_AUTOSCOUT=0`.

## The self-evolution loop

`triage-attention` (read Monitor signals) → `sync-project-docs` (update registry) → `evolve-project` (fix the top item) → `refresh-portfolio` (regen) → PR to `main` → drift + dash-build gates verify → human merges. The CI counterpart is `.github/workflows/unified-evolution.yml` (dispatch-only — trigger via `tools/dash evolve`; via `anthropics/claude-code-action`; auth: `CLAUDE_CODE_OAUTH_TOKEN` preferred, `ANTHROPIC_API_KEY` fallback — see [`docs/AI-INTEGRATION.md`](../docs/AI-INTEGRATION.md)).

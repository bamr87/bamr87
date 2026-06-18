# .claude/ — AI orchestration layer

Claude Code configuration that makes the dash self-managing.

## Contents

| Path | Purpose |
|---|---|
| `skills/update-registry/` | Reconcile `_data/projects.yml` with `.gitmodules` + repo metadata |
| `skills/refresh-portfolio/` | Regenerate monitoring data + README project list |
| `skills/sync-project-docs/` | Pull each project's current summary/status into the registry |
| `skills/drift-report/` | Explain drift-gate failures and the exact fix |
| `skills/new-project/` | Scaffold + register a new project |
| `skills/triage-attention/` | Turn Monitor-board signals into prioritized actions |
| `skills/evolve-project/` | Focused per-project improvement pass (maps to `.github/agents` personas) |
| `skills/run-dash/` | `/run-dash` — orchestration hub: whole-repo project map + per-project "work order" (branch, stack, run cmd, context) for dispatching into a submodule; serve/screenshot the Jekyll dash. Driven by `driver.py` |
| `commands/dash-status.md` | `/dash-status` — read-only status |
| `commands/evolve.md` | `/evolve` — run the self-evolution loop |
| `commands/register-project.md` | `/register-project` — add/reconcile a project |

MCP servers (github, memory, sequentialthinking, context7) are configured in the
repo-root [`.mcp.json`](../.mcp.json).

## The self-evolution loop

`triage-attention` (read Monitor signals) → `sync-project-docs` (update registry)
→ `evolve-project` (fix the top item) → `refresh-portfolio` (regen) → PR to `main`
→ drift + dash-build gates verify → human merges. The CI counterpart is
`.github/workflows/unified-evolution.yml` (weekly, via `anthropics/claude-code-action`).

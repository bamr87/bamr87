---
name: update-registry
description: Reconcile _data/projects.yml (the project registry) with .gitmodules and GitHub repo metadata. Use when a submodule or repo was added/removed/renamed, or the registry looks out of date.
---

# update-registry

The registry `_data/projects.yml` is the single source of truth for the dash.
Keep it in sync with reality.

## Steps

1. Read `.gitmodules` and `_data/projects.yml`.
2. For every submodule in `.gitmodules`, ensure a registry entry exists with a
   matching `submodule_path` and `branch`. Add missing ones; fix branch
   mismatches (remember `scripts` tracks `master`, `skills` tracks `main`).
3. For each entry, confirm `repo_url`, `description`, `stack`, `category`,
   `status`, and `featured` are accurate (use the github MCP to read the repo's
   description/topics/default branch when unsure).
4. Run `tools/check-drift.sh --report` and resolve any `(a)` parity issues.
5. Run `tools/dash-gen readme` so the profile README reflects the registry.

## Guardrails
- Never invent project facts — only the registry declares them.
- Keep one entry per project; do not duplicate.
- Preserve YAML comments and section ordering.

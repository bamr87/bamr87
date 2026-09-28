---
name: update-registry
description: Reconcile _data/projects.yml (the project registry) with .gitmodules and GitHub repo metadata. Use when a submodule or repo was added/removed/renamed, or the registry looks out of date.
---

# update-registry

The registry `_data/projects.yml` is the single source of truth for the dash. Keep it in sync with reality.

## Steps

1. Run `tools/dash reconcile` first — it compares the registry, `.gitmodules`, and GitHub reality; `--apply` writes only the unambiguous fixes (renames, url mismatches) with comment-preserving surgical edits. Manual editing below is for what it deliberately won't auto-apply (404s, branch questions — advisory drift).
2. Read `.gitmodules` and `_data/projects.yml`.
3. For every submodule in `.gitmodules`, ensure a registry entry exists with a matching `submodule_path` and `branch`. Add missing ones; fix branch mismatches — always read the branch from `.gitmodules`, never assume `main` (current exception for reference: `sonic-pi` tracks `dev`, an upstream-fork constraint).
4. For each entry, confirm `repo_url`, `description`, `stack`, `category`, `status`, and `featured` are accurate (use the github MCP to read the repo's description/topics/default branch when unsure).
5. Run `tools/check-drift.sh --report` and resolve any `(a)` parity issues.
6. Run `tools/dash-gen readme` so the profile README reflects the registry.

## Guardrails

- Never invent project facts — only the registry declares them.
- Keep one entry per project; do not duplicate.
- Preserve YAML comments and section ordering.

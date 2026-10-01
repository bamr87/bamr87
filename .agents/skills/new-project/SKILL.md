---
name: new-project
description: Scaffold a new project and register it in the dash. Use when starting a new repo/app that should appear in the portfolio.
---

# new-project

## Steps

1. Clarify: project name, stack, category (docs | full-stack-ai | dev-tools), and whether it will be a submodule or an external repo.
2. Scaffold via the scripts/ submodule: `tools/dash new <name>` (wraps `scripts/project-init.sh` + `scripts/git_init.sh`).
3. Add an entry to `_data/projects.yml` with all required fields (name, repo_url, description, stack, category, status, featured, maintained).
4. If it's a submodule, add it to `.gitmodules` and run `git submodule add <url> <path>`.
5. Run `tools/dash-gen readme` and `tools/check-drift.sh` to confirm it's wired in.

## Reuse

Prefer `scripts/project-init.sh` stacks over hand-rolling scaffolding; surface its available templates to the user.

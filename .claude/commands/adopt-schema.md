---
description: Adopt the Pyramid Schema in one submodule (seed kit + PR)
allowed-tools: Bash(tools/seed-schema.sh:*), Bash(python3 tools/gen-projects-schema.py:*), Bash(gh:*), Bash(git:*), Edit
argument-hint: "<submodule name (projects/ dir)>"
---

Adopt the Pyramid Schema for: $ARGUMENTS

1. Run `tools/seed-schema.sh $ARGUMENTS` (no `--apply`) — there is no separate
   dry-run flag; running without `--apply` IS the preview. Show the plan: the
   vendored `tools/schema_lint.py`, `.github/workflows/schema-check.yml` (gating
   branch read from `.gitmodules`), the protocol snippet appended to
   `CLAUDE.md`/`AGENTS.md`, and `SCHEMA.md` scaffolds for every directory. It
   refuses non-`bamr87` upstreams (e.g. the microsoft/skills mirror) unless
   `--force-external`.
2. If it looks right, run `tools/seed-schema.sh $ARGUMENTS --apply` (additive-only;
   never overwrites an existing file, and verifies the pyramid lints green).
3. Commit **inside the submodule** on a `chore/schema-adoption` branch and open a
   PR in the submodule's own repo — never push to its default branch:
   ```bash
   cd projects/$ARGUMENTS
   git checkout -b chore/schema-adoption
   git add -A && git commit -m "docs(schema): adopt Pyramid Schema kit"
   git push -u origin chore/schema-adoption
   gh pr create --fill
   ```
   Set the registry entry's `schema:` to `status: pending` + the PR URL.
4. After the PR merges, set the entry's `schema: status: adopted` in
   `_data/projects.yml` and run `python3 tools/gen-projects-schema.py` to
   regenerate `projects/SCHEMA.md` (it is generated — never hand-edit).

Alternative: dispatch `.github/workflows/schema-fanout.yml` (dry-run default;
`agent_fill` runs a Claude Code OAuth pass that fills scaffold TODOs on the
adoption PR branch — single target only). Framework doc: `docs/SCHEMA-FRAMEWORK.md`.

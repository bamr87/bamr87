---
name: evolve-project
description: Run a focused improvement pass on a single project (code quality, docs, tests, error handling) using the matching .github/agents persona. Use when a repo needs maintenance attention or as the action step of the evolution loop.
---

# evolve-project

This is the **manual** counterpart to the automated per-repo evolution framework
(`.github/workflows/evolution-scheduler.yml` → `repo-evolution.yml`). For consistency,
reuse the same shared prompt material in `.github/evolution/` — `evolve-prompt.md` (goals:
documentation, functionality, clarity + guardrails) plus the matching
`.github/evolution/categories/<category>.md`. The persona mapping below adds focus on top.

## Steps
1. Pick the project and the evolution type. Map type → persona in
   `.github/agents/`:
   - code quality → `code-reviewer.md`
   - documentation → `prompt-engineer.md` (+ `.github/instructions/documentation.instructions.md`, README-First rule)
   - testing → `test-writer.md`
   - CI/workflow → `workflow-reviewer.md`
   - debugging → `systematic-debugger.md`
2. Make surgical, well-scoped changes following the repo conventions
   (Conventional Commits, README-First/README-Last).
3. Run the relevant checks (`tools/run-all-tests.sh`, project lint/build).
4. Open a PR to `main` (never push to `master`). Keep diffs reviewable.

## Guardrails
Honor `AGENTS.md`: simplicity first, surgical changes, no `as any`/`@ts-ignore`/
`# type: ignore`, no empty exception handlers. Update the nearest README.

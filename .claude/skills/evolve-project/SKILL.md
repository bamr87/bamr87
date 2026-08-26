---
name: evolve-project
description: Run a focused improvement pass on a single project (code quality, docs, tests, error handling) using the matching .github/agents persona. Use when a repo needs maintenance attention or as the action step of the evolution loop.
---

# evolve-project

This is the per-repo action step of the self-evolution loop; `/evolve` is the loop's entry point (it chains triage-attention → sync-project-docs → this skill → refresh-portfolio).

It is also the **manual** counterpart to the weekly repo-evolution loop (`.github/workflows/repo-evolution.yml`, [`docs/EVOLUTION.md`](../../../docs/EVOLUTION.md)). For consistency, aim at the same goals: read `.github/evolution/evolve-prompt.md` (documentation → clarity → functionality, and the method) plus the matching `.github/evolution/categories/<category>.md`, and preview the brief the loop would hand its agent with `tools/dash gen targets --target <name> --no-dedupe` (it quotes the repo's current triage signals). The persona mapping below adds focus on top. Stay in the same lanes the loop does: a failing workflow is the fleet doctor's, an open issue is the issue pipeline's.

## Steps

1. Pick the project and the evolution type. The `.github/agents/*.md` files are **portable Copilot persona templates** (per `.github/docs/toolkit-retention-map.md`), not Claude subagents — **read** the matching one as guidance, don't try to Task-launch it. Map type → guidance / native tool:
   - code quality → run the native `/code-review` skill (read `code-reviewer.md` for framing)
   - documentation → `prompt-engineer.md` + `.github/instructions/documentation.instructions.md` (README-First rule)
   - testing → `test-writer.md`
   - CI/workflow → `workflow-reviewer.md`
   - debugging → `systematic-debugger.md`
2. Make surgical, well-scoped changes following the repo conventions (Conventional Commits, README-First/README-Last).
3. Run the relevant checks (`tools/run-all-tests.sh`, project lint/build).
4. Open a PR to `main` (never push to `master`). Keep diffs reviewable.

## Guardrails

Honor `AGENTS.md`: simplicity first, surgical changes, no `as any`/`@ts-ignore`/ `# type: ignore`, no empty exception handlers. Update the nearest README.

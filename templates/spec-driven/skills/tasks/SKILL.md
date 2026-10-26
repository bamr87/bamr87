---
name: tasks
description: "Spec-driven /tasks — break plan.md into an ordered, verifiable tasks.md whose tasks cover every FR/NFR/AC. Use after /spec-driven:plan."
argument-hint: "<spec slug>"
---

You are the **Task Decomposer**. You turn a plan into `tasks.md`.

## Preconditions

- `specs/NNN-*/spec.md` and `plan.md` are filled in and consistent.

## Procedure

1. Fill `specs/NNN-*/tasks.md` with `T-001`, `T-002`, … in the repo's `specs/_template/tasks.md` layout. Each task:
   - names the exact files to create or modify;
   - references at least one `FR-*` / `NFR-*` / `AC-*` id;
   - carries a deterministic `Verify:` block (commands or test names) that runs the way `AGENTS.md` says commands run here (for a Docker-first repo, through `make`).
2. Order tasks so each can be picked up independently after its predecessors; mark parallelizable tasks `(parallel)`.
3. Make sure **every** `FR-*`, `NFR-*`, and `AC-*` from `spec.md` is referenced by at least one task. The spec validator fails the gate otherwise.
4. Keep tasks small enough that `/spec-driven:implement` finishes each in a single PR.
5. End the file with a `## Follow-ups Discovered` section (the template has it). It stays a placeholder until `/spec-driven:implement` fills it.
6. Run the spec gate (`make lint-specs`, or the kit tools with `--root .`).

## Output

```
✅ Tasks drafted: specs/NNN-<slug>/tasks.md
Tasks: <count>  Parallel: <count>
Coverage check: all FR/NFR/AC referenced
Next: run /spec-driven:implement T-001
```

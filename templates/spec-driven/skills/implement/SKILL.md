---
name: implement
description: "Spec-driven /implement — implement exactly one task from a spec's tasks.md, run the repo's gates, record follow-ups in tasks.md and BACKLOG.md, and open the PR. Use to execute a task id such as T-003."
argument-hint: "<task id, e.g. T-003, inside specs/NNN-*/tasks.md>"
---

You are the **Implementation Agent** for a single task. One task, one PR; stop after it.

## Inputs

- `$ARGUMENTS`: a task id (`T-NNN`) and, when ambiguous, the spec slug it belongs to.

## Required reading

1. The task block in `tasks.md`.
2. The `FR-*` / `NFR-*` / `AC-*` lines it references in `spec.md`.
3. The matching section of `plan.md`.
4. `AGENTS.md` and `docs/constitution.md` when it exists (always).
5. The current contents of every file the task lists.

## Procedure

1. Mark the task `[~]` (in progress) in `tasks.md`.
2. Make the smallest change that satisfies the task and its acceptance criteria. Do not refactor unrelated code.
3. Add or update tests to the standard `AGENTS.md` sets.
4. Run the task's `Verify:` block and the repo's gates exactly as `AGENTS.md` names them (lint, typecheck, test). Never bypass a Docker-first rule by running a tool on the host.
5. Mark the task `[x]` only when verification passes.
6. **Record follow-ups (mandatory).** Before opening the PR:
   - Add at least one bullet under `## Follow-ups Discovered` in `tasks.md` for any refactor, missing test, doc gap, or stretch idea you noticed and did not implement. If there are truly none, replace the placeholder with `_none — justified: <reason>_`.
   - Mirror each new bullet into `BACKLOG.md` under `## Open` as `- **BL-YYYYMMDD-NN** — *kind, severity* — text`. Mint the id with `python3 "${CLAUDE_PLUGIN_ROOT}/tools/next_backlog_id.py" --root .`
   - Run the spec gate: `make lint-specs` when the Makefile defines it, otherwise `python3 "${CLAUDE_PLUGIN_ROOT}/tools/spec_validator.py" --root . --strict` and `python3 "${CLAUDE_PLUGIN_ROOT}/tools/backlog_lint.py" --root .`. Both must exit 0.
7. Open a PR whose description references `specs/NNN-<slug>/` and the task id, and includes the gates you ran with their results, and the new BACKLOG bullets verbatim (so a reviewer sees what the next cycle inherits).

## Output

```
✅ Implemented T-XXX (specs/NNN-<slug>)
Files changed: <list>
Tests: <pass count> / <total>  Coverage delta: <±X% or n/a>
Follow-ups added: <BL-...>, <BL-...>
PR: <url>
```

Stop after one task. Do not start the next task without a fresh `/spec-driven:implement` invocation.

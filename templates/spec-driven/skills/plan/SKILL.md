---
name: plan
description: "Spec-driven /plan — produce plan.md (architecture, components, provenance and approval gates, risks) from a clarified spec. Use after /spec-driven:clarify."
argument-hint: "<spec slug>"
---

You are the **System Architect**. You turn a clarified spec into `plan.md`.

## Preconditions

- `specs/NNN-*/spec.md` exists with **zero** unresolved `OQ-N` blocks. If any remain, stop and run `/spec-driven:clarify` first.

## Required reading

1. The spec.
2. `AGENTS.md`, `docs/constitution.md` when it exists, and the architecture docs `AGENTS.md` names.
3. Every module the spec touches: read the actual files, do not assume.

## Procedure

1. Fill in `specs/NNN-*/plan.md` end to end, section by section as the repo's `specs/_template/plan.md` lays it out.
2. For every `FR-*` and `NFR-*` in the spec, name the concrete module(s) that will satisfy it.
3. If the plan must deviate from the repo's locked tech stack, draft an ADR stub in the repo's ADR directory (`docs/adr/NNNN-<slug>.md` unless `AGENTS.md` says otherwise) and reference it from the plan.
4. Include a diagram only when it adds clarity; no boilerplate diagrams.
5. Where the template has provenance, audit, security, or human-approval sections, fill them; never leave them empty.
6. Set the spec's `Status` to `planned` and run the spec gate (`make lint-specs`, or the kit tools with `--root .`).

## Output

```
✅ Plan drafted: specs/NNN-<slug>/plan.md
Components touched: <count>
ADRs created: <list or none>
Next: run /spec-driven:tasks NNN-<slug>
```

Do not write code. Do not edit `spec.md`.

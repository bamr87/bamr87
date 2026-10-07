# Tasks: {Feature Name}

> Each task must reference one or more `FR-*` / `NFR-*` / `AC-*` IDs from `spec.md`. CI's `spec_validator.py` enforces that every requirement in `spec.md` is referenced by at least one task.

## Conventions

- Status: `[ ]` todo / `[~]` in-progress / `[x]` done.
- Owner: GitHub handle or `@agent:<role>`.
- Each task lists exact files to touch and how to verify.

---

## T-001 — {Short imperative title}

- **Refs**: FR-1, AC-1
- **Owner**: @github-handle
- **Status**: `[ ]`
- **Files**:
  - `src/…` (new)
  - `tests/…` (extend)
- **Steps**:
  1. …
  2. …
- **Verify**:
  - the repo's test command for the touched area passes.
  - the repo's lint and type checks are clean.

## T-002 — …

- **Refs**: FR-2, NFR-SEC-1
- **Owner**: …
- **Status**: `[ ]`
- **Files**: …
- **Steps**: …
- **Verify**: …

---

## Done-When (Definition of Done)

- All tasks `[x]`.
- All `AC-*` from `spec.md` covered by passing tests.
- The repo's full test and build commands are green, and the PR template's Definition of Done is ticked.
- **`## Follow-ups Discovered` section below populated** — at minimum, every implementer records one of: a new BACKLOG entry, a refactor candidate, a missing test, or `_none_` (justified in the PR).

---

## Follow-ups Discovered

> Append-only. Mirror each item into [BACKLOG.md](../../BACKLOG.md) with a `BL-YYYYMMDD-NN` id (`python3 tools/next_backlog_id.py`). CI checks this section exists (`spec_validator.py`) and the BACKLOG mirror (`backlog_lint.py`).

- _none_  <!-- replace with bullets like: "BL-YYYYMMDD-NN — feature, med — short description." -->

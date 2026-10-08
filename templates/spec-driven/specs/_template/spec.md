# Spec: {Feature Name}

- **ID**: NNN-feature-slug
- **Status**: draft | clarified | planned | in-progress | shipped | superseded
- **Owner**: @github-handle
- **Created**: YYYY-MM-DD
- **Roadmap link**: the issue this advances, or the hub `_data/roadmap.yml` initiative (`FF-NNNN`)
- **Constitution compliance**: confirmed against [docs/constitution.md](../../docs/constitution.md)

## 1. Problem & Motivation

What user problem does this solve? Quote concrete pain: an issue, an ADR, telemetry, or a live incident.

## 2. Origin & Background

- Backlog items claimed: **BL-YYYYMMDD-NN** (move each matching bullet from `## Open` to `## Claimed` in [BACKLOG.md](../../BACKLOG.md), annotated `claimed-by:specs/NNN-<slug>`), or "none — direct request".
- Prior art: the specs and ADRs this builds on or supersedes, and what changed since.
- Review questions: answer every question `specs/_review_questions.json` declares that applies to this feature, or say in one line why none applies.

## 3. Goals

- G1: …
- G2: …

## 4. Non-Goals

- NG1: …

## 5. User Stories

- As a {role}, I want {capability}, so that {outcome}.

## 6. Functional Requirements

Use stable IDs — `tasks.md` and tests reference these.

- **FR-1**: …
- **FR-2**: …

## 7. Non-Functional Requirements

- **NFR-SEC-1**: e.g. every external call has a timeout and a retry budget.
- **NFR-PERF-1**: e.g. p95 latency under a stated bound for the new path.

## 8. Data, Interface & Schema Impact

Data model or migration changes, public API or CLI changes, config keys, schema files. State "none" only with a reason.

## 9. Security Impact

Untrusted input paths, secret handling, permission changes. State "none" only with a reason.

## 10. Acceptance Criteria

Each criterion must be objectively testable. Maps 1:N to tasks.

- **AC-1**: Given …, when …, then ….
- **AC-2**: …

## 11. Risks & Open Questions

- **R-1**: …
- **OQ-1**: … (resolve via `/clarify` before moving to plan)

## 12. Out of Scope / Follow-ups

- …

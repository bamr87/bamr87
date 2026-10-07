# Plan: {Feature Name}

> Companion to `spec.md`. Describes **how** we will satisfy the requirements.

## 1. Architecture Overview

Short prose, plus a Mermaid diagram only if it adds clarity. Reference the relevant sections of the repo's architecture doc.

## 2. Component Changes

| Layer | File / Module | Change |
|-------|---------------|--------|
| … | … | … |

## 3. Data & Schema Changes

Migrations (idempotent, forward-only), schema files, compatibility with existing data.

## 4. Tech Choices & Alternatives

| Decision | Chosen | Alternatives Considered | Why |
|----------|--------|-------------------------|-----|
| … | … | … | … |

If a choice is hard to reverse or deviates from [docs/constitution.md](../../docs/constitution.md), add an ADR in `docs/adr/NNNN-slug.md` and reference it here.

## 5. Least Privilege & Untrusted Input

Mandatory — do not leave empty. New permissions or tool grants, each as narrow as possible, and which attacker-controlled inputs reach the change and how they are contained.

## 6. Test Strategy

- Unit and integration tests to add, and the invariants they assert.
- Fixtures needed.
- Manual or browser checks, if any.

## 7. Rollout

Feature flag or kill switch, migration order, docs to update.

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| … | low/med/high | low/med/high | … |

## 9. Estimated Effort

Sessions or tasks; flag any task that needs a human.

# __PROJECT_NAME__ — Backlog

> **Append-only** register of follow-ups discovered during implementation (AO-SDLC, from bamr87/law-ai and bamr87/gitorio). Every implementation cycle appends the work it discovers. Items graduate into `specs/NNN-*/` via `/specify`. Enforced by `tools/backlog_lint.py` (format, unique ids, no deletions against the PR base) in the CI spec-gate job. This file is the repo's backlog of record, declared in `.github/sdlc.yml` as `backlog: { mode: file, file: BACKLOG.md }`.

## Conventions

| Field | Values |
|---|---|
| id | `BL-YYYYMMDD-NN`: the discovery date plus an ordinal (01–99); mint it with `python3 tools/next_backlog_id.py` |
| kind | `feature` · `refactor` · `tech-debt` · `test-gap` · `doc-gap` · `infra` |
| severity | `low` · `med` · `high` (fleet priority when mirrored to Issues: P3 · P2 · P1) |
| surfaced in | the spec, PR or audit that found it |

Bullet format, one per item: `- **BL-YYYYMMDD-NN** — *kind, severity* — text. _Surfaced in:_ where.`

## Triage rules

1. New items go to **Open**. When a spec claims an item it moves to **Claimed**, annotated `claimed-by:specs/NNN-slug`. Resolved items move to **Done**. Never delete an item.
2. Open items older than 60 days are reviewed at the next `/specify` cycle and either closed `wontfix: <reason>` or escalated (`python3 tools/backlog_lint.py --stale-report`).
3. If two branches mint the same id, the branch that merges second renumbers forward. Never drop an id.
4. With `mirror_to_issues: true` in `.github/sdlc.yml`, a sync job opens one issue per Open item, labelled `backlog` plus the mapped type and priority, with the BL id in its body. The file stays the source of truth.

---

## Open

## Claimed

## Done

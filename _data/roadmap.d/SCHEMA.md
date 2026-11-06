---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data/roadmap.d

> Pending roadmap entries: one unnumbered entry per file, in the `../roadmap.yml` schema, compiled into `../roadmap.yml` on `main` by `tools/jev/number.py` (amendment 0002, extended by amendment `roadmap-numbering-at-merge`). A pull request writes here so that two parallel pull requests can never claim the same `FF-NNNN`.

## Conventions

- One entry per file, as a top-level mapping — not a list, and never two entries in one file.
- `id:` is always `FF-NEW`. A number here is a bug the numbering compiler refuses.
- Anything else that cites a pending entry writes `FF-NEW:<slug>`; the compiler rewrites it to the assigned id in the same run.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The fragment format and the compiler commands | required |
| `*.yml` | pattern | One pending roadmap entry, named `<kebab-slug>.yml`; consumed (deleted) when compiled | |

## Placement

- New roadmap entry → `<kebab-slug>.yml` here, never a new `- id: FF-NNNN` row in `../roadmap.yml`.

## Forbidden

- No hand-assigned `FF-NNNN` — the compiler owns the series, and gaps (FF-0022, FF-0023, FF-0027, FF-0028) are never back-filled.
- No fragment for an entry that already has a number; edit its row in `../roadmap.yml` (status, priority, issue_url).

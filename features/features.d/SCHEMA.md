---
schema: "0.1"
coverage: listed
---

# SCHEMA — features/features.d

> Pending feature entries: one unnumbered `features/v1` entry per file, compiled into `../features.yml` on `main` by `tools/jev/number.py` (amendment 0002). A pull request writes here so that two parallel pull requests can never claim the same `HUB-NNN`.

## Conventions

- One entry per file, as a top-level mapping — not a list, and never two features in one file.
- `id:` is always `HUB-NEW`. A number here is a bug the numbering lint reports.
- A reference to something else that is also new is written by slug: `HUB-NEW:<slug>`, `FR-NEW:<key>`, `NFR-NEW:<key>`, `AMEND-NEW:<slug>`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The fragment format and the compiler commands | required |
| `*.yml` | pattern | One pending feature, named `<kebab-slug>.yml`; consumed (deleted) when compiled | |

## Placement

- New feature → `<kebab-slug>.yml` here, never a new row in `../features.yml`.

## Forbidden

- No hand-assigned `HUB-NNN`, `FRn` or `NFRn` — the compiler owns every sequential id.
- No fragment for a feature that already has a number; edit its entry in `../features.yml`.

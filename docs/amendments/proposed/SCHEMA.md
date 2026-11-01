---
schema: '0.1'
coverage: listed
---

# SCHEMA — docs/amendments/proposed

> Unnumbered amendment records awaiting a number: a proposal is written as `<kebab-slug>.md` with `**Number:** NEW`, and `tools/jev/number.py` numbers it, moves it into `../` and indexes it when the pull request lands on `main` (amendment 0002).

## Conventions

- Same body as a numbered record (constitution § 8, `../0000-template.md`); only the H1 and `**Number:**` carry `NEW`.
- A reference to a feature or requirement that is also new is written by slug: `HUB-NEW:<slug>`, `FR-NEW:<key>`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | How a proposal is written and what the compiler does with it | required |
| `*.md` | pattern | One proposed amendment, named `<kebab-slug>.md`; consumed (moved to `../NNNN-<slug>.md`) when compiled | |

## Placement

- New amendment → `<kebab-slug>.md` here, never a hand-numbered `../NNNN-*.md`.

## Forbidden

- No numbered file names here — the number is assigned at merge and never reused.
- No edit to a record that has already been numbered; it is append-only history (constitution § 8). The one exception is its Status, Ratified by and index status cell, which the post-merge ratify job records (§ 8.3).

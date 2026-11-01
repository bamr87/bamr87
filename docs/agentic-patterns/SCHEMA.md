---
schema: '0.1'
coverage: listed
---

# SCHEMA — docs/agentic-patterns

> The fleet's map of Gulli's *Agentic Design Patterns*: one evidence-rated page per chapter, plus a JSON index that mirrors the pages' front matter.

## Conventions

- One chapter per page, named `patterns/NN-slug.md` (two-digit chapter number, `00` for the introduction).
- Front matter on every page: `id` (`ADP-NN`), `chapter`, `title`, `book_pages`, `status` (`proven` | `partial` | `gap`), `evidence_repos`, `last_verified`, `owner_bot`.
- Evidence links are permalinks pinned to a commit SHA. Evidence that exists only on an unmerged PR rates `partial` at most.
- Every gap links an issue.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | Index: status scale, tally and one row per page | required |
| `patterns/` | dir | One `NN-slug.md` page per chapter | required |
| `patterns.json` | file | Machine index; one entry per page, mirroring its front matter | required |
| `patterns.schema.json` | file | JSON Schema for `patterns.json` | required |

## Placement

- A new chapter or appendix page → `patterns/NN-slug.md`, plus its entry in `patterns.json` and a row in `README.md`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- Long verbatim quotes from the book; paraphrase instead.
- Evidence links to a branch name (`blob/main/...`) instead of a pinned SHA.

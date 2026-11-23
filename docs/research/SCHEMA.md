---
schema: "0.1"
coverage: listed
---

# SCHEMA — docs/research

> Dated research reports filed by Researcher: reviews, source packs, briefs and deep dives. Findings stay as filed.

## Conventions

- One report per file, named `YYYY-MM-DD-kebab-slug.md`. The date is the date written on the report. Names are lowercase.
- Every report has one H1 and a `>` summary directly under it.
- Prose is one paragraph per line.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | Index of the reports | required |
| `[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md` | pattern | One dated research report | |

## Placement

- New report from Researcher → `YYYY-MM-DD-slug.md` here, plus a row in `README.md`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- Rewriting a filed report's findings. The summary line and one-paragraph-per-line formatting are the only edits after filing.
- Secrets, tokens, or private data.

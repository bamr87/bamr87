---
schema: "0.1"
coverage: listed
---

# SCHEMA — docs

> Operator documentation for the dash machinery — how the hub, gates, and fleet workflows are meant to be run.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `*.md` | pattern | One UPPERCASE-TOPIC.md per concern; README.md is the index | required |
| `adr/` | dir | Architecture Decision Records — `NNNN-slug.md` + a README index (UPS-WORK-04, decision D2); the hub's `.github/sdlc.yml` names it as `adr_path` | required |
| `amendments/` | dir | Constitution amendment log — append-only `NNNN-slug.md` records (Status, Date, Ratified by, Affects) + README index; `constitution.md` changes only through it (UPS-WORK-16, templates/governance/) | required |

## Placement

- New machinery doc → `UPPERCASE-TOPIC.md` here; project-specific docs live in the project's own repo.

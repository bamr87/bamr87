---
schema: "0.1"
coverage: strict
---

# SCHEMA — templates/schema

> The Pyramid Schema seed kit — vendored from the upstream pyramid-schema package; re-vendor rather than edit in place.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What the kit contains and how seeding maps files into submodules | required |
| `SCHEMA.template.md` | file | Template for a new directory's SCHEMA.md | required |
| `CLAUDE.snippet.md` | file | Agent protocol block appended to a submodule's CLAUDE.md | required |
| `schema-check.yml` | file | CI workflow seeded as .github/workflows/schema-check.yml (`__DEFAULT_BRANCH__` substituted) | required |
| `VERSION` | file | Provenance: upstream package, commit, spec version, vendoring date | required |

## Forbidden

- No local edits without bumping VERSION — fleet learnings flow upstream first, then re-vendor.

# templates/schema — the Pyramid Schema seed kit

The fleet-facing distribution of the [Pyramid Schema](../../docs/SCHEMA-FRAMEWORK.md) paradigm: everything a submodule needs to adopt `SCHEMA.md` structural contracts, seeded by `tools/seed-schema.sh` locally or the `schema-fanout` workflow in CI.

| file | lands in the submodule as | purpose |
| --- | --- | --- |
| `../../tools/schema_lint.py` | `tools/schema_lint.py` | vendored stdlib linter: `check` + `init` |
| `SCHEMA.template.md` | _(used at authoring time)_ | template for each new directory's SCHEMA.md |
| `CLAUDE.snippet.md` | appended to `CLAUDE.md` | the agent protocol: orient, follow, propagate, maintain, verify |
| `schema-check.yml` | `.github/workflows/schema-check.yml` | CI gate (`__DEFAULT_BRANCH__` substituted at seed time) |
| `VERSION` | _(stays here)_ | provenance: upstream package + commit this kit was vendored from |

Seeding is idempotent and additive: existing files are never overwritten, `init` never touches an existing `SCHEMA.md`, and the snippet is appended only if the file lacks a `## SCHEMA.md protocol` heading.

Re-vendor from the upstream package (see `VERSION`) rather than editing the kit in place — fleet learnings flow upstream first, then back down.

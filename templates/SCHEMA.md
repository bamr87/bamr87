---
schema: "0.1"
coverage: listed
---

# SCHEMA — templates

> Seedable artifact kits: files the hub fans out into submodule repos via dispatch workflows and seed scripts.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | Index of kits and how fan-out works | required |
| `agent-context/` | dir | Agent-context kit: CLAUDE.md scaffold + @claude OAuth workflow, seeded by standardize-fanout | terminal |
| `standard-ci/` | dir | Reusable CI gate caller seeded by standardize-fanout | terminal |
| `release-pipeline/` | dir | release-please pipeline kit seeded by adopt-release | terminal |
| `year-repo/` | dir | Year-in-review knowledge-base repo kit (1987, 2005, …) — planned, currently empty | terminal |
| `schema/` | dir | Pyramid Schema seed kit: template, protocol snippet, CI check, provenance | required |

## Placement

- New kit → `templates/<kit-name>/` with its own SCHEMA.md if the hub must verify its contents.

## Forbidden

- Kits are copied verbatim into other repos — nothing repo-specific beyond documented `__PLACEHOLDER__` tokens.

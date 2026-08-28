---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools

> The dash's executable machinery: CLI, gates, generators, and fleet scripts.

## Conventions

- Shell for orchestration (`*.sh`, kebab-case); Python (stdlib + PyYAML) for gates and generators.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | Tools index | required |
| `dash` | file | Dash CLI entrypoint (status, audit, work orders) | required |
| `dash-gen` | file | Regenerates README AUTO spans and portfolio data from the registry | required |
| `fleet-config.py` | file | Reads `_data/fleet.yml`; audits fleet secrets/variables against GitHub and projects the canonical variables onto every repo (`dash secrets`, `dash config`) | required |
| `Brewfile` | file | macOS dev dependencies | |
| `devtools.conf` | file | Shared config for the devtools scripts | |
| `fanout.sh` | file | Shared fan-out engine — clone→branch→seed→commit→PR loop with dry-run and external-upstream guard (called by standardize-fanout.yml, schema-fanout.yml, and deps-fanout.yml) | |
| `unpin-deps.sh` | file | Converts one repo to the always-latest dependency policy — strips pins, removes + gitignores lockfiles, adapts CI installs (used by the deps-latest fan-out kit; docs/DEPENDENCIES.md) | |
| `issue-evidence.sh` | file | Builds one issue's evidence bundle in an isolated virtual environment — clone, toolchain install, lint/test/build, screenshots, candidate files (tier 1 of docs/ISSUE-PIPELINE.md) | |
| `render-diagrams.sh` | file | Validates + delivers every `diagrams/*.json` archify spec to its self-contained HTML via the vendored `.claude/skills/archify` renderer (`--check` validates only; docs/HARNESS.md) | |
| `*.sh` | pattern | One fleet/ops script per concern, kebab-case (gates, setup, fan-out seeds) | required |
| `*.py` | pattern | Python gate/generator tooling — includes the vendored schema_lint.py (see templates/schema/VERSION) | required |

## Placement

- New gate or generator → `*.py` here; new orchestration → `*.sh` here; document in README.md.

## Forbidden

- No secrets in scripts; tokens come from the environment or GitHub secrets.

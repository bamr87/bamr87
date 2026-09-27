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
| `audit-git-hooks.sh` | file | Read-only diagnostic answering the Husky-vs-pre-commit question — reports which hook manager is actually live via `core.hooksPath` (always exits 0) | |
| `macos-register-nerd-fonts.swift` | file | One-shot CoreText helper for `setup-terminal.sh` — registers the MesloLGS Nerd Font `.ttf`s so Terminal.app can see them (`swift` has no `*.swift` pattern row here; this is the fleet's only one) | |
| `console/` | dir | The Harness Console — local control plane UI + API (FastAPI) wrapping the allowlisted `dash` operations as jobs, rendering every committed fleet signal, editing the fleet.yml harness contract, and (Traces tab) reading the local data lake + linking Phoenix, (Content tab) the content atlas + editorial approvals; `tools/dash console`, compose service `console` (docs/HARNESS-OPS.md) | |
| `fleet/` | dir | Generated bootstrap for the shared container plane — the Postgres init that gives each project declaring `database: true` a database and role on the hub's one instance, replacing the eight separate Postgres containers the fleet used to run (docs/CONTAINERS.md) | generated |
| `observability/` | dir | The local LOG plane's configuration — Logstash pipelines (one shared redaction path), the label-gated Filebeat shipper, and the Elasticsearch/Kibana/Grafana objects rendered from `_data/fleet.yml` `observability:`; `tools/dash observe`, compose profile `elk` (docs/OBSERVABILITY.md) | |
| `*.sh` | pattern | One fleet/ops script per concern, kebab-case (gates, setup, fan-out seeds) | required |
| `*.py` | pattern | Python gate/generator tooling — includes the vendored schema_lint.py (see templates/schema/VERSION) | required |

## Placement

- New gate or generator → `*.py` here; new orchestration → `*.sh` here; document in README.md.

## Forbidden

- No secrets in scripts; tokens come from the environment or GitHub secrets.

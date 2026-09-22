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
| `fleet-dev.sh` | file | Fleet dev-stack entry point (`dash dev`) — runs any submodule as its own compose project on the shared `fleet-net`, with the hub's generated port override layered on (docs/FLEET-COMPOSE.md) | required |
| `fleet-compose.py` | file | Projects `_data/ports.yml` onto that stack (`.env.fleet`, `compose/overrides/*`, `compose.fleet.yml`) and gates the allocation as drift check (m) | required |
| `fleet_smoke.py` | file | Connects to and exercises every fleet container (HTTP, TCP, psql, redis-cli, exec), records the observation into `_data/smoke.yml`, and re-runs it as the monorepo smoke test (`dash dev smoke`) | required |
| `docker_harmonize.py` | file | The fleet Docker standard's transformer (`dash docker`, `fanout.sh --kit docker`): image versions from `_data/fleet.yml` `images:`, loopback env-overridable ports, no container_name, 127.0.0.1 healthchecks, Postgres 18 mount — line edits that preserve comments; idempotent (docs/DOCKER.md) | required |
| `docker_view.py` | file | Builds the consolidated `/docker/` dashboard: joins `_data/ports.yml`, `_data/fleet.yml` `images:`, `_data/smoke.yml`, `.vscode/launch.json` and the read-only harmonizer audit into `_data/docker.yml` (`dash docker view --write`) | required |
| `test_docker_harmonize.py` | file | Fixture tests for the transformer — every rule, pin logic, never-downgrade, idempotency | required |
| `test_docker_view.py` | file | Tests for the consolidated Docker view — contract-precision version comparison, the image census, pin/ceiling/floating classification, and that a missing checkout is never reported as conformance (run by drift check (n)) | required |
| `pg-major-upgrade.sh` | file | Postgres MAJOR upgrade for a compose service without data loss: raw-volume backup + `pg_dumpall` + restore; `--check` powers the `dash dev up` preflight (`dash dev db-upgrade`) | required |
| `Brewfile` | file | macOS dev dependencies | |
| `setup-terminal.sh` | file | macOS CHUI bootstrap (`bamr87/chui` + Meslo CoreText registration) | |
| `devtools.conf` | file | Shared config for the devtools scripts | |
| `fanout.sh` | file | Shared fan-out engine — clone→branch→seed→commit→PR loop with dry-run and external-upstream guard (called by standardize-fanout.yml, schema-fanout.yml, and deps-fanout.yml) | |
| `unpin-deps.sh` | file | Converts one repo to the always-latest dependency policy — strips pins, removes + gitignores lockfiles, adapts CI installs (used by the deps-latest fan-out kit; docs/DEPENDENCIES.md) | |
| `issue-evidence.sh` | file | Builds one issue's evidence bundle in an isolated virtual environment — clone, toolchain install, lint/test/build, screenshots, candidate files (tier 1 of docs/ISSUE-PIPELINE.md) | |
| `render-diagrams.sh` | file | Validates + delivers every `diagrams/*.json` archify spec to its self-contained HTML via the vendored `.claude/skills/archify` renderer (`--check` validates only; docs/HARNESS.md) | |
| `audit-git-hooks.sh` | file | Read-only diagnostic answering the Husky-vs-pre-commit question — reports which hook manager is actually live via `core.hooksPath` (always exits 0) | |
| `console/` | dir | The Harness Console — local control plane UI + API (FastAPI) wrapping the allowlisted `dash` operations as jobs, rendering every committed fleet signal, editing the fleet.yml harness contract, and (Traces tab) reading the local data lake + linking Phoenix; `tools/dash console`, compose service `console` (docs/HARNESS-OPS.md) | |
| `*.sh` | pattern | One fleet/ops script per concern, kebab-case (gates, setup, fan-out seeds) | required |
| `*.py` | pattern | Python gate/generator tooling — includes the vendored schema_lint.py (see templates/schema/VERSION) | required |

## Placement

- New gate or generator → `*.py` here; new orchestration → `*.sh` here; document in README.md.

## Forbidden

- No secrets in scripts; tokens come from the environment or GitHub secrets.

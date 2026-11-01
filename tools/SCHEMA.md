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
| `tui/` | dir | Terminal command center — the TTY twin of the dash (`dash tui`); see its README | |
| `fleetcore/` | dir | The core the console and the TUI share — fleet views, keys v1, the bashOS palette, the console job-API client (one model, one runtime, two surfaces); see its README | |
| `jev/` | dir | JEV — the harness-level agent logic engine: the assign-at-merge numbering compiler, the tiered PR conflict triage/resolution engine, the loop step specs every agent step's prompt, allowlist and caps are rendered from, and the local loop runner (`python3 -m tools.jev`; docs/JEV.md); see its README | |
| `fleet-config.py` | file | Reads `_data/fleet.yml`; audits fleet secrets/variables against GitHub and projects the canonical variables onto every repo (`dash secrets`, `dash config`) | required |
| `fleet-dev.sh` | file | Fleet dev-stack entry point (`dash dev`) — runs any submodule as its own compose project on the shared `fleet-net`, with the hub's generated port override layered on (docs/FLEET-COMPOSE.md) | required |
| `fleet-compose.py` | file | Projects `_data/ports.yml` onto that stack (`compose/fleet.env`, `compose/overrides/*`, `compose/fleet.yml`) and gates the allocation as drift check (m) | required |
| `fleet_smoke.py` | file | Connects to and exercises every fleet container (HTTP, TCP, psql, redis-cli, exec), records the observation into `_data/smoke.yml`, and re-runs it as the monorepo smoke test (`dash dev smoke`) | required |
| `docker_harmonize.py` | file | The fleet Docker standard's transformer (`dash docker`, `fanout.sh --kit docker`): image versions from `_data/fleet.yml` `images:`, loopback env-overridable ports, no container_name, 127.0.0.1 healthchecks, Postgres 18 mount — line edits that preserve comments; idempotent (docs/DOCKER.md) | required |
| `docker_view.py` | file | Builds the consolidated `/docker/` dashboard: joins `_data/ports.yml`, `_data/fleet.yml` `images:`, `_data/smoke.yml`, `.vscode/launch.json` and the read-only harmonizer audit into `_data/docker.yml` (`dash docker view --write`) | required |
| `test_docker_harmonize.py` | file | Fixture tests for the transformer — every rule, pin logic, never-downgrade, idempotency | required |
| `pipeline_map.py` | file | Builds the harness pipeline map view model (HUB-025, HUB-026): pipeline definition + activity-log events + job and workflow run status → node statuses and drill-downs; read-only (docs/prd/HARNESS-PIPELINE-MAP.md) | |
| `test_pipeline_map.py` | file | Offline tests for the pipeline map: definition integrity, status rules over the example fixture, unavailable log, workflow triggers/schedule/last run | |
| `test_docker_view.py` | file | Tests for the consolidated Docker view — contract-precision version comparison, the image census, pin/ceiling/floating classification, and that a missing checkout is never reported as conformance (run by drift check (n)) | required |
| `pg-major-upgrade.sh` | file | Postgres MAJOR upgrade for a compose service without data loss: raw-volume backup + `pg_dumpall` + restore; `--check` powers the `dash dev up` preflight (`dash dev db-upgrade`) | required |
| `Brewfile` | file | macOS dev dependencies | |
| `setup-terminal.sh` | file | macOS CHUI bootstrap (bashOS `chui/` + Meslo CoreText registration) | |
| `devtools.conf` | file | Shared config for the devtools scripts | |
| `fanout.sh` | file | Shared fan-out engine — clone→branch→seed→commit→PR loop with dry-run and external-upstream guard (called by .github/workflows/fanout.yml for every kit, and by dash harnesses/verify deploy) | |
| `backlog_fanout.py` | file | The backlog fan-out routine (HUB-027, FR22) — pending hub issues / unserved PRD requirements / unshipped features → idempotent `backlog/<item>` PRs in the repos they apply to via `fanout.sh --kit backlog`; dry-run default, never merges (backlog-fanout.yml; docs/BACKLOG-FANOUT.md) | |
| `frontend_registry.py` | file | The § 18 frontend registry: lints every `_data/projects.yml` `frontend:` block (drift check (o)) and generates the shell launcher manifest and the registry table (docs/FRONTEND-PLATFORM.md) | |
| `test_frontend_registry.py` | file | Tests for the frontend registry lint and launcher | |
| `test_conformance_frontend.py` | file | Fixture tests for UPS-FE-70..73 (tiers, N/A, warn-then-fail, forks) | |
| `fleet_activity.py` | file | Fire-and-forget fleet activity log client (FR23) — event schema from the activity-log PRD (#409), bounded redacted JSONL spool, best-effort flush; never raises | |
| `test_backlog_fanout.py` | file | Fixture tests for backlog_fanout.py + fleet_activity.py — mapping, idempotent update, cadence, cap, retries, graceful degradation of the activity log (run by python-tests.yml) | |
| `deep_dive.py` | file | The daily repo deep-dive tracker (HUB-029, FR24–FR25) — today's repo, record a run, refresh open `deep-dive` issue/PR counts from GitHub, rollover, and the `_data/deep_dive.json` projection (docs/DEEP-DIVE.md) | |
| `test_deep_dive.py` | file | Fixture tests for deep_dive.py — day math, catch-up, record, offline refresh, rollover, committed tracker freshness | |
| `test_jev_*.py` | pattern | Fixture tests for one `jev/` module each — the numbering compiler, the classifier, the conflict engine's safety rules, the ledger and the monthly cap, the loop step specs, the headless executor layer, the loop runner, its workspaces and each loop adapter (`test_jev_adapter_<name>.py`) (run by run-all-tests.sh and python-tests.yml) | |
| `unpin-deps.sh` | file | Converts one repo to the always-latest dependency policy — strips pins, removes + gitignores lockfiles, adapts CI installs (used by the deps-latest fan-out kit; docs/DEPENDENCIES.md) | |
| `issue-evidence.sh` | file | Builds one issue's evidence bundle in an isolated virtual environment — clone, toolchain install, lint/test/build, screenshots, candidate files (tier 1 of docs/ISSUE-PIPELINE.md) | |
| `features_index.py` | file | The fleet features index — validates a repo's `features/features.yml`, grades verification coverage from files on disk, aggregates every submodule → `_data/features_index.yml` (`dash features`; docs/VERIFICATION.md) | |
| `test_fleet_config.py` | file | Fixture tests for fleet-config.py's per-repo AI auth order — precedence, category groups, conflict/unknown errors, order-aware secret targets, the projected variable (run by run-all-tests.sh) | |
| `test_features_index.py` | file | Fixture tests for features_index.py (run by run-all-tests.sh) | |
| `governance_lint.py` | file | The fleet governance check — constitution + amendment log + PRD ↔ feature catalog links (UPS-WORK-15/16); `prd-ids` / `prd-sync` generate the PRD requirement ids and Feature catalog block; `fleet` checks every submodule | |
| `test_governance_lint.py` | file | Fixture tests for governance_lint.py | |
| `test_fleetcore_mcp.py` | file | Fixture tests for `fleetcore/mcp_server.py` — console tools pass exactly their arguments (confirm defaults false), refusals and bad arguments are tool errors, log truncation, the `.env` token parsed never sourced, the stdio loop (run by run-all-tests.sh) | |
| `test_fleetcore_host.py` | file | Fixture tests for `fleetcore/host.py` — DASH_DOCKER_HOST parsing, `docker ps` against a fake binary (errors and timeouts per host, never raised), label-authoritative and longest-key container attribution, `attach()` (run by run-all-tests.sh) | |
| `render-diagrams.sh` | file | Validates + delivers every `diagrams/*.json` archify spec to its self-contained HTML via the vendored `.claude/skills/archify` renderer (`--check` validates only; docs/HARNESS.md) | |
| `audit-git-hooks.sh` | file | Read-only diagnostic answering the Husky-vs-pre-commit question — reports which hook manager is actually live via `core.hooksPath` (always exits 0) | |
| `macos-register-nerd-fonts.swift` | file | One-shot CoreText helper for `setup-terminal.sh` — registers the MesloLGS Nerd Font `.ttf`s so Terminal.app can see them (`swift` has no `*.swift` pattern row here; this is the fleet's only one) | |
| `console/` | dir | The Harness Console — local control plane API (FastAPI) + page (React/Mantine, `console/web/`) wrapping the allowlisted `dash` operations as jobs, rendering every committed fleet signal with a drill-down per project, editing the fleet.yml contract, reading the local data lake + linking Phoenix, the content atlas + editorial approvals, and running the terminal dash in the page (Terminal); `tools/dash console`, compose service `console` (docs/HARNESS-OPS.md) | |
| `fleet/` | dir | Generated bootstrap for the shared container plane — the Postgres init that gives each project declaring `database: true` a database and role on the hub's one instance, replacing the eight separate Postgres containers the fleet used to run (docs/CONTAINERS.md) | generated |
| `observability/` | dir | The local LOG plane's configuration — Logstash pipelines (one shared redaction path), the label-gated Filebeat shipper, and the Elasticsearch/Kibana/Grafana objects rendered from `_data/fleet.yml` `observability:`; `tools/dash observe`, compose profile `elk` (docs/OBSERVABILITY.md) | |
| `*.sh` | pattern | One fleet/ops script per concern, kebab-case (gates, setup, fan-out seeds) | required |
| `*.py` | pattern | Python gate/generator tooling — includes the vendored schema_lint.py (see templates/schema/VERSION) | required |

## Placement

- New gate or generator → `*.py` here; new orchestration → `*.sh` here; document in README.md.

## Forbidden

- No secrets in scripts; tokens come from the environment or GitHub secrets.

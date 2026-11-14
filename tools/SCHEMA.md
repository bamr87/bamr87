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
| `jev/` | dir | JEV — the harness-level agent logic engine: the assign-at-merge numbering compiler, the tiered PR conflict triage/resolution engine, the loop step specs every agent step's prompt, allowlist and caps are rendered from, the local loop runner, and recursive harness refinement — the surface check, the Propose–Probe–Compose plan and evidence tree, the experience library (`python3 -m tools.jev`; docs/JEV.md, docs/HARNESS-REFINEMENT.md); see its README | |
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
| `test_vscode_launch.py` | file | The editor-is-a-front-door gate (constitution § 20): `.vscode/` parses as JSONC, every pre-launch task and input resolves, each picker equals its registry (`_data/ports.yml`, `.gitmodules`, `fleet.yml` content sites, `verify/scenarios/`, compose profiles), every port an entry names is published by the plane it talks to, no `fleet-dev.sh` / `fleet-hub` / `--all`; plus fixture tests for conformance.py's UPS-REPO-40 (run by run-all-tests.sh) | required |
| `pg-major-upgrade.sh` | file | Postgres MAJOR upgrade for a compose service without data loss: raw-volume backup + `pg_dumpall` + restore; `--check` powers the `dash dev up` preflight (`dash dev db-upgrade`) | required |
| `Brewfile` | file | macOS dev dependencies | |
| `setup-terminal.sh` | file | macOS CHUI bootstrap (bashOS `chui/` + Meslo CoreText registration) | |
| `devtools.conf` | file | Shared config for the devtools scripts | |
| `fanout.sh` | file | Shared fan-out engine — clone→branch→seed→commit→PR loop with dry-run and external-upstream guard (called by .github/workflows/fanout.yml for every kit, and by dash harnesses/verify deploy) | |
| `backlog_fanout.py` | file | The backlog fan-out routine (HUB-027, FR22) — pending hub issues / unserved PRD requirements / unshipped features → idempotent `backlog/<item>` PRs in the repos they apply to via `fanout.sh --kit backlog`; dry-run default, never merges (backlog-fanout.yml; docs/BACKLOG-FANOUT.md) | |
| `frontend_registry.py` | file | The § 18 frontend registry: lints every `_data/projects.yml` `frontend:` block (drift check (o)), prints the shell launcher manifest (`fleetcore/apps.py`) and the registry table, and `probe` asks each registry address whether it answers and whether the shell can frame it (docs/FRONTEND-PLATFORM.md) | |
| `test_frontend_registry.py` | file | Tests for the frontend registry lint, the launcher, the frame-policy reading and the probe (against a loopback server) | |
| `test_fleetcore_apps.py` | file | Tests for `fleetcore/apps.py` — live and local targets, the case-blind ports join, compose-hosted only, embed rules, address resolution, the hub launcher's coherence, the `dash apps` CLI | |
| `test_fleetcore_yamlio.py` | file | Tests for `fleetcore/yamlio.py` — the same objects `yaml.safe_load` builds, one parse per version of a file, a private copy per caller, a file that just changed never kept, a replaced file re-read, the bounded table, `cached()`, and the hub's own signals read both ways | |
| `test_fleetcore_graph.py` | file | Tests for `fleetcore/graph.py` — the closed vocabulary, impact and lineage directions, paths, every check rule, the layer's tools-to-routes parser, the builders over a fixture checkout, and the hub's own graph (every input read, no dangling edge, every exemption real) | |
| `test_fleetcore_learn.py` | file | Tests for `fleetcore/learn.py` — the config (shadow is the only mode), each outcome, the Beta functions against closed forms, decay and the prior, the seeded Thompson plan, the replay skill test, the read-only lake reader and a lake that predates the outcome columns, the `dash learn` CLI | |
| `test_conformance_frontend.py` | file | Fixture tests for UPS-FE-70..73 (tiers, N/A, warn-then-fail, forks) | |
| `scorecard_snapshot.py` | file | The security-posture snapshot: OpenSSF Scorecard JSON (scorecard-sweep.yml) → raw cache `_data/scorecard.yml` → the `security:` block of `_data/conformance.yml`; `targets`, `ingest`, `--write`, `--check` (drift check (f)) (docs/SECURITY-POSTURE.md) | |
| `test_scorecard_snapshot.py` | file | Offline fixture tests for scorecard_snapshot.py — normalization, `--check` after a hand edit, `conformance.py fleet --write` keeping the block byte-identical, the sweep workflow's read-only shape | |
| `fleet_activity.py` | file | Fire-and-forget fleet activity log client (FR23) — event schema from the activity-log PRD (#409), bounded redacted JSONL spool, best-effort flush; never raises | |
| `test_backlog_fanout.py` | file | Fixture tests for backlog_fanout.py + fleet_activity.py — mapping, idempotent update, cadence, cap, retries, graceful degradation of the activity log (run by python-tests.yml) | |
| `projects_backfill.py` | file | The issue-triage + Fleet-board backfill pass (constitution § 10 / § 11; amendment 0003 phase 1; #453, #473): compiles `_data/projects_backfill.yml` into the § 11 service's ops, previews before → after with plan ids, applies only with the flag + `--confirm` through `tools/console/gh_projects_write.py` (`dash projects`; docs/PROJECTS-FRAMEWORK.md § 3b) | |
| `test_projects_backfill.py` | file | Offline tests for projects_backfill.py — validation, compilation, batching, REST shapes, refusals, board planning, field precedence, the applied ledger (run by run-all-tests.sh and python-tests.yml) | |
| `pm_review.py` | file | The routine PM review (`dash pm`; docs/PM.md; #588): reads the fleet's open issues, pull requests, comments, releases and the Fleet project with GETs and GraphQL queries only, aligns them with the project, `_data/roadmap.yml` and each release train, and plans Fleet project ops as a preview `dash projects apply` takes plus roadmap status edits for the working tree; writes `_data/pm_review.yml` | |
| `test_pm_review.py` | file | Offline tests for pm_review.py: scope, the read-only gather against a recording fake `gh`, every lane's rules, the § 11 preview, the roadmap edits, snapshot privacy, the CLI and the workflow's never-apply guard (run by run-all-tests.sh and python-tests.yml) | |
| `deep_dive.py` | file | The daily repo deep-dive tracker (HUB-029, FR24–FR25) — today's repo, record a run and its Quest Log showcase, refresh open `deep-dive` issue/PR counts from GitHub, rollover, and the `_data/deep_dive.json` projection (docs/DEEP-DIVE.md, docs/SHOWCASE.md) | |
| `test_deep_dive.py` | file | Fixture tests for deep_dive.py — day math, catch-up, record, showcase record and count, offline refresh, rollover, committed tracker freshness | |
| `test_jev_*.py` | pattern | Fixture tests for one `jev/` module each — the numbering compiler, the ratification recorder, the classifier, the conflict engine's safety rules, the ledger and the monthly cap, the loop step specs, the headless executor layer, the loop runner, its workspaces, its context pack, each loop adapter (`test_jev_adapter_<name>.py`), harness refinement and its incident reflector (`test_jev_reflect.py`, which also runs `install-harness-review.sh`'s job) (run by run-all-tests.sh and python-tests.yml) | |
| `unpin-deps.sh` | file | Converts one repo to the always-latest dependency policy — strips pins, removes + gitignores lockfiles, adapts CI installs (used by the deps-latest fan-out kit; docs/DEPENDENCIES.md) | |
| `issue-evidence.sh` | file | Builds one issue's evidence bundle in an isolated virtual environment — clone, toolchain install, lint/test/build, screenshots, candidate files (tier 1 of docs/ISSUE-PIPELINE.md) | |
| `claude_code_executes_lint.py` | file | Constitution section 26 lint: validates agent_roles.yml and classifies paths/PRs as direction-setting vs software; warn-only by default, --gate hard-fails | |
| `test_claude_code_executes_lint.py` | file | Fixture tests for claude_code_executes_lint.py | |
| `governance_trace_lint.py` | file | Constitution section 28 lint: a PR body must carry a Governed by: line linking an amendment or FR/NFR; warn-only by default, --gate hard-fails | |
| `test_governance_trace_lint.py` | file | Fixture tests for governance_trace_lint.py | |
| `mcp_servers_lint.py` | file | MCP servers lifecycle lint (constitution section 25): validates .mcp.json / verify mcp configs and _data/mcp_servers.yml for shape and inline secrets; warn-only by default, --gate hard-fails (docs/MCP-SERVERS.md) | |
| `test_mcp_servers_lint.py` | file | Fixture tests for mcp_servers_lint.py (inline token detection, schema shape, registry) | |
| `guides_visual_lint.py` | file | Guides visual-evidence lint (constitution section 24): flags guide-like Markdown on the curated backlog lacking an image, evidence ref or skip-visuals reason; warn-only by default, --gate hard-fails (docs/VISUAL-EVIDENCE.md) | |
| `test_guides_visual_lint.py` | file | Fixture tests for guides_visual_lint.py (image/skip detection, backlog gaps, broken links) | |
| `voices.py` | file | The fleet voice model check — validates `_data/voices/voices.yml` against `voices.schema.json`, `--against` flags drift in a consumer copy, `assign` names the persona for an activity (constitution § 23 rule 7) | |
| `features_index.py` | file | The fleet features index — validates a repo's `features/features.yml`, grades verification coverage from files on disk, aggregates every submodule → `_data/features_index.yml` (`dash features`; docs/VERIFICATION.md) | |
| `test_fleet_config.py` | file | Fixture tests for fleet-config.py's per-repo AI auth order — precedence, category groups, conflict/unknown errors, order-aware secret targets, the projected variable (run by run-all-tests.sh) | |
| `test_loop_switches.py` | file | Offline checks for `_data/fleet.yml` `switches:` (constitution § 17) — entry shape, and every scheduled or `vars.*_ENABLED`-switched hub workflow has an entry whose variable it reads | |
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

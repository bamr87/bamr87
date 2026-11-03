# PRD — Fleet activity replay (live and historical animated view)

> **Status: Draft / proposed.** Design only; nothing is implemented by this PR.
> Feature: `HUB-NEW` (slug `fleet-activity-replay`, fragment [`features/features.d/fleet-activity-replay.yml`](../../features/features.d/fleet-activity-replay.yml)); the number is assigned at merge ([amendment 0002](../amendments/0002-conflict-free-numbering.md)).
> Requirements served: FR5, FR7, FR10, FR15, FR16–FR20, FR26, FR60, NFR4–NFR7, NFR9 in the root [`PRD.md`](../../PRD.md); new: `FR-NEW:activity-capture`, `FR-NEW:activity-stream-replay`, `FR-NEW:activity-replay-view`, `NFR-NEW:activity-replay-bounded` (declared in the fragment's `prd_new:`, numbered at merge).
> Builds on: [FLEET-ACTIVITY-LOG.md](FLEET-ACTIVITY-LOG.md) (`HUB-024`), [HARNESS-PIPELINE-MAP.md](HARNESS-PIPELINE-MAP.md) (`HUB-025`, `HUB-026`), `/live` (`HUB-030`), the MCP layer (`HUB-031`), Claude telemetry (`HUB-039`), job status (`HUB-064`), [OBSERVABILITY.md](../OBSERVABILITY.md), [CONTAINERS.md](../CONTAINERS.md) and the FF-0032 fleet shell plugin model (draft, `HUB-NEW` `fleet-shell`, issues #583, #586, #605).
> Related, not duplicated: [#479](https://github.com/bamr87/bamr87/issues/479) (`/map`, a live interactive map of loops and harnesses). #479 owns the structure layer (lanes, stages, nodes); this feature owns the captured runtime and history that #479's runtime layer and this feature's own timeline both read.
> Governing rules: [`docs/constitution.md`](../constitution.md) § 10 (methodology, prior art first), § 11, § 13 (risk tiers), § 18 (design consistency), § 20 (editor front door).

## 1. Problem

The fleet already produces a great deal of activity data, but it is scattered and mostly ephemeral. `/live` shows a 5-second snapshot of sessions, jobs and spend and then forgets it. Container logs go to Elasticsearch and metrics to Prometheus/Grafana, traces to Phoenix, jobs live in the console's in-process `JobManager`, and the activity log (`fleet_event`) is still a design. Nothing records *what every agent, harness and container was doing, in order, together*, so the operator cannot watch the fleet work in one picture or rewind to see what happened during a failed night run.

Amr's ask: "real-time or historical analysis or visualization of the agents and harnesses as they are processing information, built into the storage of the fleet. There should be a visual representation and animation of all of the activities and data that is captured in the Docker containers."

## 2. Goals and non-goals

**Goals**

- One append-only **activity store in the fleet's own storage** (the shared `db` Postgres; Redis for the hot tail) holding container, agent, job and fleet-event activity with one envelope.
- One **read-only API** that streams live and replays history with the same cursor, so live mode is just replay at the head.
- One **animated view** (timeline + node graph) as a console plugin, live or replay, with drill-down into the planes that already exist.
- Works on the static Pages site in snapshot mode with a committed, redacted sample window.

**Non-goals**

- A second log, metrics or trace plane: raw log text stays in Elasticsearch, metrics in Prometheus, spans in Phoenix; the store keeps **events and pointers** (trace id, log query, run id), not copies.
- Any write, exec or control action on containers or agents from this view (it is read-only; control stays with existing ops under § 11 / § 13).
- Replacing `/live`, the pipeline map or #479; this feature feeds them.
- Running in CI or publishing raw data to Pages (local-only by construction, like the lake and the observability stack).

## 3. User stories

| Id | As a… | I want… | So that… |
| --- | --- | --- | --- |
| US1 | operator (Amr) | to open `/replay` and watch agents, loops and containers light up and pass work along edges as it happens | I can see at a glance what the fleet is doing right now |
| US2 | operator | to pick last night's window and replay it at 10×–100× with play, pause and scrub | I can see the order of events behind a failed run without reading five tools |
| US3 | operator | to click any node or event and jump to its Kibana log query, Grafana panel, Phoenix trace, GitHub run or console job | analysis starts from the picture and ends in the plane with the detail |
| US4 | operator | to filter by project, container, agent, loop or run, and to see a heat strip of activity density and errors | I can find the busy, slow or failing part quickly |
| US5 | AI agent (via MCP) | `activity_stream` / `activity_replay` / `activity_summary` read tools | an agent can reason over what the fleet did without scraping the UI |
| US6 | visitor to the public site | a recorded, redacted sample window animating in snapshot mode | the Pages console shows how the harness works without exposing live data |
| US7 | maintainer | capture that never slows or breaks a container, drops events visibly and keeps no secret | turning the feature on is safe on the 7.7 GiB Docker VM |

## 4. What exists today (grounding)

| Piece | Today | Used how |
| --- | --- | --- |
| `docker-compose.yml` (project `fleet`) | `devenv`, `console`, `mcp`, `db` (Postgres), `redis`, `grafana`, `phoenix`, `prometheus`, `otel-collector`, ELK (`elasticsearch`, `logstash`, `kibana`, `filebeat`), `qdrant`, … with `com.bamr87.fleet.*` labels | label-gated discovery; `db` hosts the store; `redis` the hot tail |
| `filebeat` docker autodiscover, read-only `docker.sock` | ships container logs to Logstash → redact → Elasticsearch | the same label gate and redaction pipeline; the collector reuses the read-only socket pattern |
| `tools/console/live.py`, `live_collector.py`, `GET /api/live/stream` (SSE, token auth) | 5 s snapshots of sessions, jobs, spend | the SSE pattern and auth are reused; snapshots become events |
| `fleet_event` design (FR7–FR15) | append-only bot decision events with fire-and-forget spool | becomes one **source** of the store; its spool (NFR4/NFR5) is the model for every writer |
| `tools/pipeline_map.py`, `diagrams/pipeline-map/pipeline.json` | nodes and edges of every loop | the graph layout's node set; events map onto nodes |
| `tools/console/mcp_layer/` | read tools over the console API | three new read tools |
| `tools/console/web` (React + Mantine + Vite; console, snapshot and remote modes; `/live`, `/traces`, `/containers`, `/jobs`) | | the view is a new route, shipped as a fleet-shell plugin when FF-0032 lands |
| FF-0032 fleet shell (draft) | `fleet-mfe.json` manifests, regions (main, inspector, status bar, palette) | `/replay` is declared as a plugin: nav under *Observe*, graph in `main`, event detail in `inspector`, stream health in the status bar |

## 5. Design

### 5.1 Capture — `FR-NEW:activity-capture`

A new `activity` collector (one small service, compose profile `activity`, off by default) and thin source adapters write one envelope:

| Field | Notes |
| --- | --- |
| `seq` | bigserial; the global order and the replay cursor |
| `event_id` | UUID; idempotency key (at-least-once flush, NFR5) |
| `ts` | when it happened at the source (UTC) |
| `source` | `docker`, `docker_stats`, `agent_session`, `job`, `fleet_event`, `github_run`, `otel` |
| `kind` | e.g. `container.start/stop/die/oom/health`, `cpu_mem_sample`, `session.start/turn/idle/end`, `job.queued/running/stalled/done/failed`, `fleet_event.*` |
| `project`, `repo`, `container`, `service` | from `com.bamr87.fleet.*` labels / registry |
| `actor` | agent, loop or bot id (`bot_id` for fleet events) |
| `run_id`, `trace_id` | correlation; `trace_id` is the same sha256 used in Elasticsearch and Phoenix |
| `pipeline_node` | node id from `pipeline.json` when known (FR17/FR18) |
| `payload` | small redacted JSON (≤ 4 KB); never raw log text |

Sources: Docker Engine events API and a sampled `stats` stream over the read-only socket (labelled containers only); `live_collector.py` session snapshots diffed into session events; the console `JobManager` transitions (FR60); `fleet_event` rows once FR7 ships; lake `github_run` rows; selected OTel metrics as samples. Every writer goes through the FR10/NFR4 fire-and-forget spool.

Storage: table `fleet_activity` in a `fleet_activity` schema on the existing `db` service, monthly partitions by `ts`, indexes on `(ts)`, `(source, ts)`, `(project, ts)`, `(run_id)`; a Redis Stream `fleet:activity` (MAXLEN-capped) as the live tail. Retention and caps live in `_data/fleet.yml` `observability.activity:` (`retention_days`, `stats_interval_s`, `max_events_per_s`, `payload_max_bytes`), read with `tools/dash config show`. Old partitions are rolled into per-minute summaries (`fleet_activity_rollup`) before drop.

### 5.2 Stream and replay API — `FR-NEW:activity-stream-replay`

| Route | Purpose |
| --- | --- |
| `GET /api/activity/stream?from=head\|<seq>&filter…` | SSE; Redis tail at the head, falls back to Postgres from `Last-Event-ID` on resume |
| `GET /api/activity/replay?start=&end=&speed=&filter…` | SSE of a past window, re-timed by `speed` (1×–1000×, or `max`), same event shape |
| `GET /api/activity/events?start=&end=&cursor=&limit=` | paged JSON for analysis and the snapshot build |
| `GET /api/activity/summary?start=&end=&bucket=` | density, error and duration buckets for the heat strip and analysis |
| `GET /api/activity/health` | collector lag, drop counters, store reachability |

Read-only, loopback, the console token (as `/api/live/stream`). MCP read tools `activity_stream` (bounded window), `activity_replay`, `activity_summary` through `tools/console/mcp_layer/` (FR26, NFR9). `snapshot.py` exports a fixed, redacted sample window to static JSON for the Pages build; a new `snapshot.STATIC_ROUTES` row covers `/replay`.

### 5.3 View — `FR-NEW:activity-replay-view`

A `/replay` route (fleet-shell plugin `harness-replay` once FF-0032 lands; a normal page until then):

- **Graph** (main region): nodes = pipeline-map nodes plus containers grouped by project; edges = pipeline edges plus observed run/trace hand-offs. Events animate as pulses travelling along edges and node status rings (running/idle/failed/unknown, FR18). Renderer and layout chosen by the prior-art decision below (React Flow + ELK is the leading candidate, matching #479).
- **Timeline** (below the graph): swim lanes per source/project, a density/error heat strip from `/summary`, a playhead with play, pause, scrub, speed and *jump to live*.
- **Inspector**: the selected event's envelope and links to Kibana (log query by container + time), Grafana, Phoenix (`trace_id`), the GitHub run, the console job (FR19).
- **Status bar**: stream state, lag, dropped-event count.
- Modes: console (live + replay), snapshot (recorded sample only), remote (read via the MCP/HTTP API). Reduced-motion setting disables animation and shows a stepped list. Fleet tokens and Mantine components only (§ 18).
- Editor front door (§ 20): `tools/dash activity status|tail|replay` and a `.vscode/launch.json` entry arrive with the implementation PR.

### 5.4 Prior art and build-vs-adopt (§ 10.8)

Needs assessment: the fleet needs an ordered, correlated event history across Docker, agents and loops, stored locally, with an animated view inside the existing console. Survey (fit in one line each):

| Option | Fit |
| --- | --- |
| Grafana (already in the stack) — state timeline, node graph panels | good for analysis, weak animation, no fleet-specific drill-down; **adopt as a linked view**, not the main UI |
| Kibana / Elasticsearch | holds logs already; heavy for an event ledger on a memory-constrained VM; stays the log plane |
| Phoenix / OpenInference | right for LLM spans; not for container events; linked via `trace_id` |
| Weave Scope, Portainer, cAdvisor, ctop | live container topology/stats; no history or agent semantics; Weave Scope archived |
| OpenTelemetry Collector `docker_stats` receiver | candidate capture source for stats instead of a custom sampler — evaluate in phase 1 |
| Temporal / Argo / Dagster UIs, LangGraph Studio | strong models for run timelines and live graphs; not embeddable; borrow the interaction pattern |
| React Flow (xyflow) + ELK/dagre, Cytoscape.js, vis-timeline | embeddable renderers; React Flow + ELK aligns with #479 and Mantine |

Decision (proposed): **build** the thin collector, store and API (no product covers this fleet's correlation of labels, pipeline nodes and fleet events); **adopt** Postgres, Redis Streams, possibly the OTel `docker_stats` receiver, React Flow + ELK for the graph, and Grafana for dashboards. The final call is recorded on the epic before phase 1.

## 6. Design for Failure

| Failure mode | Detection | Containment | Recovery | Learning |
| --- | --- | --- | --- | --- |
| Postgres (`db`) down or slow | `/api/activity/health`, spool depth gauge | writers spool locally (bounded, NFR5); containers and agents never wait (NFR4) | idempotent flush by `event_id` on return | spool-overflow count reported on `/replay` and `dash activity status` |
| Event flood (crash loop, chatty stats) | `max_events_per_s` breach counter | per-source rate cap, stats sampling backs off, dropped events counted not silent | caps reset per window | flood windows become a rollup row the doctor can triage |
| Secret in a payload | redaction tests; Logstash-style sweep on write | redact before spool; payload size cap; no raw log text stored (NFR6) | purge partition rows by `event_id`, re-redact | add the pattern to the shared redaction list |
| Docker socket abuse | compose review, `test_docker.py` | read-only mount, events/stats GET only, no exec/attach; label-gated | — | any new socket use is a gated change |
| SSE client stalls / many tabs | server send-queue depth | per-client bounded queue; slow clients dropped to resume-by-cursor | client reconnects with `Last-Event-ID` | stream health in the status bar |
| Gap or reorder in history | `seq` gaps, `ts` vs `seq` skew check | UI marks gaps explicitly; never interpolates | backfill from lake / `fleet_event` where possible | gap report in `/summary` |
| Disk growth | `dash observe status` disk budget | retention + monthly partitions + rollups | drop oldest partition | retention tuned in `fleet.yml` |
| Browser overload in replay | frame-time monitor | cap rendered nodes, aggregate by project, reduced-motion fallback | auto-degrade to stepped list | limits recorded in the scenario evidence |
| Store unavailable on Pages / snapshot | build check | snapshot mode ships a static sample; explicit empty state (FR20) | — | — |

Risk tier (§ 13.6): capture and read API are reversible, internal, no money → **low**; enabling the compose profile on Amr's Mac is a deploy step (§ 10.5) Amr approves explicitly.

## 7. Cost (JEV tiers)

| Tier | What | Cost |
| --- | --- | --- |
| 0 | collector, store, API, snapshot export, view — deterministic code, no model | free (local compute; adds roughly one small container and a Postgres schema) |
| 1 (optional, later) | Haiku-class "explain this window" summary over `/summary` + selected events, on demand only | capped by `_data/fleet.yml` `budget:`; labelled API-equivalent (estimate) |
| 2 (optional, later) | Sonnet-class incident narrative for a failed run window, manual trigger | capped per call; never scheduled |

No scheduled AI is added; any AI step gets a `vars.*_ENABLED` kill switch (§ 17) and an eval set (§ 13.1) before it ships.

## 8. Phases (proposed epic)

1. Prior-art decision recorded; envelope + `fleet_activity` schema; Docker events and job sources; `/api/activity/events` and `/health`; tests.
2. Redis tail, `/stream` and `/replay` SSE, MCP read tools, session and `fleet_event` sources.
3. `/replay` view (graph + timeline + inspector), snapshot sample for Pages, scenario and evidence under `test/evidence/fleet-activity-replay/` (docs/VERIFICATION.md).
4. Fleet-shell plugin manifest once FF-0032 ships; stats sampling and rollups; optional tier-1 summaries.

## 9. Requirements

| Id | Requirement |
| --- | --- |
| `FR-NEW:activity-capture` | Read-only, label-gated capture of container lifecycle/resource, agent session, job and fleet_event activity into one append-only `fleet_activity` store in the fleet's Postgres, with the envelope in § 5.1 |
| `FR-NEW:activity-stream-replay` | One read-only API streaming live (SSE, resume by cursor) and replaying any past window at a chosen speed, filterable, also as MCP read tools |
| `FR-NEW:activity-replay-view` | Animated timeline + node graph console plugin, live and replay, drill-down to Grafana/Kibana/Phoenix/GitHub/jobs, snapshot mode on Pages, explicit empty/degraded states |
| `NFR-NEW:activity-replay-bounded` | Never blocks containers or agents; read-only socket; rate, payload and retention caps from `fleet.yml`; redact before storage; drops counted; loopback; no secrets |

Existing requirements this serves: FR5 (rendered from data), FR7/FR10/FR15 (activity log source, fire-and-forget writer, console reader), FR16–FR20 (pipeline-map nodes, status and drill-down, renders with an empty log), FR26 (MCP), FR60 (job state), NFR4–NFR7, NFR9.

## 10. Open questions

- Store the envelope beside `fleet_event` in one table, or keep two tables joined by `run_id`? (Proposed: two tables; `fleet_event` keeps its own schema.)
- OTel `docker_stats` receiver vs a small custom sampler for resource samples.
- Default retention (proposed 14 days raw, 180 days rollups) against the disk budget.
- Whether GitHub Actions runs are ingested live (ETag poll) or only from `dash lake sync`.
- Proposed principle change (not ratified here): see the PR body for the `activity-capture-read-only` amendment proposal.

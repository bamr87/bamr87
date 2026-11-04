# Plan — Fleet activity replay: implementation plan and epic

> **Status: Draft / proposed.** Plan only; nothing here is implemented. Accepted when the maintainer merges this PR; each phase lands in its own PR.
> Feature: `HUB-NEW` (slug `fleet-activity-replay`) — the same feature the design PR [#617](https://github.com/bamr87/bamr87/pull/617) adds. The hub hangs an epic off **one** feature entry (the forge epic #594 → `HUB-068`), so this plan extends that fragment rather than adding a second one.
> Design: [FLEET-ACTIVITY-REPLAY.md](FLEET-ACTIVITY-REPLAY.md). Epic issue: #624. Sub-issues: #618 (P0), #619 (P1), #620 (P2), #621 (P3), #622 (P4), #623 (P5).
> Requirements: `FR-NEW:activity-capture`, `FR-NEW:activity-stream-replay`, `FR-NEW:activity-replay-view`, `NFR-NEW:activity-replay-bounded` (from #617) and `FR-NEW:agent-trace-otel` (added here); existing FR5, FR7, FR10, FR15, FR16–FR20, FR26, FR60, NFR4–NFR7, NFR9.
> Research input: Researcher's X/GitHub survey of agent-activity visualization tools (2026-11-03), summarized in § 3.

## 1. Outcome

From the Harness Console, Amr watches every agent and harness working — live, or replayed from any past window — as an animated graph and timeline. Each agent turn and tool call opens as a trace tree. Everything is stored in the fleet's own Docker stack: Phoenix for traces, Postgres for the event ledger, Redis for the live fan-out, and Grafana for trends. No new storage engine is added.

## 2. Architecture (reuse first)

```text
 agent containers / devenv / host Claude Code            fleet Docker containers (com.bamr87.fleet.* labels)
   │ Claude Code native OTel (gen_ai spans,                │ Docker Engine events + sampled stats
   │ metrics, logs)            │ hook events               │ (read-only docker.sock, GET only)
   ▼                           ▼                           ▼
 otel-collector (exists)    hook shim (.claude/hooks)    activity collector (new, profile `activity`)
   ├─ traces ──► Phoenix (exists, store of record)         │
   ├─ spanmetrics ──► Prometheus ──► Grafana (exist)       │
   └─ logs ──► Logstash ──► Elasticsearch (exist)          │
                               └──────────┬────────────────┘
                                          ▼
                     Redis (exists): PUBLISH fleet:activity  +  XADD fleet:activity (MAXLEN)
                                          │                          │
                     console SSE fan-out ◄┘          writer ─► Postgres `db` (exists): fleet_activity
                                          │                          │
        tools/console/app.py (FastAPI): /api/activity/{stream,replay,events,summary,health}
                        + Phoenix GraphQL proxy for span trees, + MCP read tools (mcp_layer)
                                          │
   tools/console/web (React + Mantine + Vite): /replay — agent-prism trace tree + timeline,
   React Flow + ELK graph, fleet tokens; later a fleet-shell plugin (fleet-mfe.json, MF 2.0)
```

| Need | Reused | New (thin) |
| --- | --- | --- |
| Trace store of record | Phoenix (`phoenix` service, `phoenix-data` volume), already the collector's `traces` exporter with `transform/openinference` | OTel **GenAI** semantic-convention mapping (`gen_ai.*` → OpenInference) checked by a test; `trace_id` reused as the join key |
| Metrics, dashboards | `otel-collector` → Prometheus → Grafana | `spanmetrics` connector; one provisioned "Agent activity" dashboard |
| Live fan-out | `redis` | channel and stream `fleet:activity` |
| Event ledger, replay | `db` Postgres | schema `fleet_activity` (monthly partitions, rollups) |
| Hook events | `.claude/hooks/` (existing hook pattern) | `activity_event.py` hook: fire-and-forget to Redis, falls back to a local spool |
| Container events | the filebeat read-only socket and label-gate pattern | `tools/activity/collector.py` (or the OTel `docker_stats` receiver for stats — decided in P0) |
| API, MCP | `app.py`, `live.py` SSE + token auth, `mcp_layer/` | `tools/console/activity.py`, three MCP read tools |
| UI | React, Mantine, Vite, `@tanstack/react-query`, `/live`, `/traces` | `/replay` page; `@evilmartians/agent-prism` components; React Flow + ELK |
| Shell / plugin | FF-0032 `@bamr87/fleet-tokens`, `@bamr87/fleet-shell`, `@bamr87/fleet-shell-mfe`; Module Federation 2.0 via `@module-federation/vite` | `fleet-mfe.json` for `harness-replay` |

**Why Redis pub/sub *and* a stream:** pub/sub has no delivery guarantee — a subscriber that is down misses the message. It is used only for the live push. The capped Redis Stream is the durable hand-off to the Postgres writer, and it lets the SSE resume from `Last-Event-ID` (NFR5). Postgres is the source for replay.

## 3. Research findings folded in

| Finding (Researcher, 2026-11-03) | How the plan uses it |
| --- | --- |
| Phoenix + OTel GenAI spans as the trace store of record (zero new infra, already deployed) | P1: spans stay in Phoenix; the console reads trees through Phoenix's API and never copies span bodies into Postgres |
| An OTel Collector fanning out to Phoenix and Grafana | P1: extend the existing `tools/observability/otel-collector/config.yaml` (traces → Phoenix already) with `spanmetrics` → Prometheus → Grafana |
| Hook events through Redis pub/sub into Postgres for the live view | P2: hook shim and container collector → Redis → writer → `fleet_activity` |
| agent-prism (MIT) for the trace tree and timeline components | P4: adopt `@evilmartians/agent-prism` TraceViewer / TreeView fed by OTel spans; theme through fleet tokens |
| disler `claude-code-hooks-multi-agent-observability` — no license | **Reference design only.** No code, assets or text copied; the event list and timeline idea are re-implemented from the Claude Code hooks docs. Revisit only if the author adds a license |
| Langfuse / Laminar / OpenLIT / Opik need ClickHouse | Not adopted; they duplicate Phoenix. Reconsider only if Phoenix proves limiting (P0 exit criterion records this) |
| AgentsView (MIT, native Postgres push), Pixel Agents (MIT), AOS Dashboard (MIT) | Optional later: AgentsView as a historical session-analytics sidecar; Pixel Agents' "ambient" mode as inspiration for the reduced-detail view |

## 4. User stories

The design's US1–US7 ([FLEET-ACTIVITY-REPLAY.md § 3](FLEET-ACTIVITY-REPLAY.md#3-user-stories)) are the acceptance targets. This plan adds:

| Id | As a… | I want… | So that… |
| --- | --- | --- | --- |
| US8 | operator | to click an agent node and see its turns and tool calls as a span tree with tokens, latency and cost (API-equivalent, estimate) | I can understand *how* an agent processed something, not only that it ran |
| US9 | operator | Grafana's "Agent activity" dashboard (rate, errors, p95 latency per agent and tool) to share the same `trace_id` links | trends and single runs are one click apart |
| US10 | developer of a fleet app | to mount the replay view as a fleet-shell plugin in another shell-tier app | the view is reusable across the fleet, not a console one-off |

## 5. Phases, milestones and acceptance criteria

Each phase is one sub-issue and one PR; phases land in order unless marked parallel. Every PR follows the Definition of Done (`.github/pull_request_template.md`), § 15 evidence and § 20 editor entries.

### P0 — Decisions and contracts (docs + tests, no runtime change)

- **Milestone M0:** contracts frozen.
- **Scope:** the event envelope JSON Schema (`schemas/fleet-activity-1.json`); the OTel GenAI ↔ OpenInference attribute map; the `_data/fleet.yml` `observability.activity:` block (retention, caps, enable flag, default off); the build-vs-adopt record (§ 10.8) including the docker_stats-receiver vs custom-sampler call; the license review (§ 8).
- **Acceptance:** the schema validates fixture events; `test_fleet_config.py` knows the new block; the decision record is on the epic; `governance_lint` and `features_index` pass.

### P1 — Trace plane: OTel GenAI to Phoenix and Grafana (parallel with P2)

- **Milestone M1:** an agent turn in devenv shows as a span tree in Phoenix and a rate panel in Grafana.
- **Scope:** collector `spanmetrics` connector → Prometheus; a provisioned Grafana dashboard; Claude Code OTel env (`CLAUDE_CODE_ENABLE_TELEMETRY`, OTLP endpoint) for devenv and agent containers; a GenAI-attribute test on a recorded span fixture.
- **Acceptance:** `dash observe status` reports the traces pipeline healthy; the fixture span maps to OpenInference kinds; `trace_id` matches across Phoenix and Elasticsearch (the existing join); no prompt text leaves redaction (a test with a planted token).

### P2 — Live event bus: hooks and containers → Redis → Postgres (parallel with P1)

- **Milestone M2:** `tools/dash activity tail` prints live hook and container events, and they persist in `fleet_activity`.
- **Scope:** the `.claude/hooks/activity_event.py` hook (PreToolUse, PostToolUse, SubagentStop, Stop, Notification…); the container collector (label-gated, GET-only socket); Redis PUBLISH + XADD; an idempotent writer; Postgres schema + partitions; rollups; `dash activity status|tail`; compose profile `activity`, off by default; a `.vscode/launch.json` entry.
- **Acceptance:** with `db` or `redis` stopped, a hook returns in < 50 ms and spools (NFR4); after restart the spool flushes exactly once by `event_id`; dropped events are counted; `test_activity_*.py` covers redaction, caps and replay order; `check-drift.sh` is green.

### P3 — API and MCP

- **Milestone M3:** `curl /api/activity/replay?start=…&speed=50` streams a past window in order.
- **Scope:** `tools/console/activity.py` routes (stream, replay, events, summary, health) with the console token; a Phoenix GraphQL proxy returning a span tree by `trace_id`; MCP read tools `activity_stream`, `activity_replay`, `activity_summary`; a redacted snapshot export for Pages and its `snapshot.STATIC_ROUTES` row.
- **Acceptance:** `test_console.py` and `test_mcp_layer.py` cover every route, degraded store, resume by cursor and filter; no route writes; loopback only (NFR9).

### P4 — The `/replay` view in the console

- **Milestone M4:** Amr watches last night's window replay at 50× with a live graph, timeline and trace tree.
- **Scope:** the page in `tools/console/web` (React, Mantine, react-query); React Flow + ELK graph seeded from `pipeline.json` (shared with #479); agent-prism TraceViewer/TreeView in the inspector; a timeline with heat strip and play/pause/scrub/speed/jump-to-live; reduced motion; console, snapshot and remote modes; deep links to Grafana, Kibana, Phoenix and GitHub.
- **Acceptance:** `test_pages.py` passes; a `verify/scenarios/fleet-activity-replay.yml` scenario and before/after evidence at two widths under `test/evidence/fleet-activity-replay/` (§ 15); renders an explicit empty state without the store (FR20); 60 fps under 500 nodes on the reference fixture, auto-degrading beyond.

### P5 — Fleet-shell plugin (after FF-0032 ships)

- **Milestone M5:** `/replay` loads as the `harness-replay` plugin through `@bamr87/fleet-shell-mfe`.
- **Scope:** a `fleet-mfe.json` manifest (nav *Observe*, regions main + inspector + status bar, caps `activity.read`); a Module Federation 2.0 remote built with `@module-federation/vite`, with React and Mantine as `shared` singletons; fleet tokens only; the `fleet-shell` version stamp.
- **Acceptance:** the shell refuses to mount on a React or Mantine version skew and shows the error-boundary state; the in-repo route and the remote render identically (scenario evidence); `@bamr87/fleet-*` versions follow whatever FF-0032 D1 ratifies.

## 6. Design for Failure

The design's table ([§ 6](FLEET-ACTIVITY-REPLAY.md#6-design-for-failure)) applies. Plan-specific additions:

| Failure mode | Detection | Containment | Recovery | Learning |
| --- | --- | --- | --- | --- |
| Hook blocks Claude Code | hook duration histogram | 50 ms budget, fire-and-forget, never non-zero exit | spool flush | hook p99 shown on `/replay` status bar |
| Redis pub/sub drops while the console is down | stream vs ledger count check | the live view is best-effort; the Stream + Postgres are durable | the view re-reads from the cursor | gap markers on the timeline |
| Phoenix unavailable or schema change | proxy health, a contract test on the fixture | the trace pane degrades to the event envelope; the graph still runs | retry with backoff | a Phoenix upgrade gets a contract test run |
| GenAI semconv churn (still experimental upstream) | attribute-map test fails on a new collector or Claude Code release | the map lives in one file; unknown attributes pass through | update the map | the release note is linked in the map's header |
| Phoenix ELv2 terms change | license check in P0 and on major bumps | Phoenix stays an internal service, never redistributed | fall back to Grafana Tempo (OTLP) | recorded in § 8 |
| Memory pressure on the 7.7 GiB Docker VM (#594) | `dash observe status`, container RSS | the `activity` profile is off by default; ES stays optional | move the planes to forge per #597 | budget row in `fleet.yml` |
| Module Federation shared-singleton skew | runtime check at mount | refuse the mount, show the error boundary | rebuild the remote against the shell range | skew logged as an activity event |

## 7. JEV tiers and cost

| Tier | Work | Cost |
| --- | --- | --- |
| 0 | P0–P5 runtime: collector, hook, writer, API, view — deterministic, no model calls | free (one small container, one Postgres schema, one Grafana dashboard) |
| 1 (optional) | Haiku-class "explain this window" on demand from `/summary` | capped by `budget:`; labelled API-equivalent (estimate) |
| 2 (optional) | Sonnet-class incident narrative for a failed run, manual only | per-call cap; never scheduled; kill switch (§ 17) and eval set (§ 13.1) before it ships |

Implementing agents work each phase as a normal issue-pipeline item: Sonnet by default, Opus only for P2 and P4 design review, both capped by `budget:`. Risk tier (§ 13.6): every runtime action is reversible, internal and free → low. Enabling the `activity` profile or the hook on Amr's Mac is a deploy step he approves (§ 10.5).

## 8. Dependencies, risks and licenses

| Dependency | Relation |
| --- | --- |
| [#617](https://github.com/bamr87/bamr87/pull/617) | Design and feature fragment; this plan stacks on it |
| FF-0032 fleet shell (#583, #586, #605; drafts D1–D8) | P5 needs `@bamr87/fleet-tokens`, `fleet-shell` and `fleet-shell-mfe` published; P4 uses tokens if they exist and falls back to the console theme if not. Exact pins for `@bamr87/fleet-*` are **pending D1** (an exception to the always-latest policy); until Amr ratifies it, they stay `*` like every other dependency |
| [#479](https://github.com/bamr87/bamr87/issues/479) `/map` | Shares the React Flow + ELK graph and `pipeline.json` nodes; #479 owns structure, this epic owns runtime and history. Whichever lands first builds the graph component in `tools/console/web/src/components/` for both |
| [#586](https://github.com/bamr87/bamr87/issues/586) harness management epic | Parent context; the replay view is its runtime illustration |
| HUB-024 activity log (FR7–FR15) | `fleet_event` becomes one source when it ships; P2 does not wait for it |
| #594 forge (esp. #597, #598) | Memory relief; #598's Docker events work is reused, not duplicated — P2 coordinates on one collector |

| Component | License | Note |
| --- | --- | --- |
| Arize Phoenix | Elastic License 2.0 (source-available) | Fine for internal self-hosted use; not offered as a managed service and not redistributed |
| `@evilmartians/agent-prism` | MIT | Adopt; keep the notice in the bundle's third-party licenses |
| disler/claude-code-hooks-multi-agent-observability | **none** (all rights reserved by default) | Reference design only; no copying. Re-implemented from the Claude Code hooks documentation |
| React Flow (xyflow), ELK.js, Module Federation, Vite, React, Mantine | MIT / EPL-2.0 (ELK) | EPL-2.0 is weak copyleft at the file level; used unmodified as a dependency |
| OpenTelemetry Collector contrib, Grafana, Prometheus, Redis, Postgres | Apache-2.0 / AGPL-3.0 (Grafana) / BSD-3 / RSALv2-SSPL-AGPL (Redis 8) / PostgreSQL | Already in the stack, run unmodified and internally |

Other risks: GenAI semconv is still experimental (pinned in one map); hook coverage differs across agents (Claude Code first; others through OTel only); the "visual" scope can creep (#479 and #586 hold structure and management).

## 9. Proposed amendment (not ratified)

`activity-capture-read-only` (§ 10.6, § 13.6), as described in #617: read-only docker socket (GET only), label-gated capture, redact before storage, counted drops, caps and retention from `fleet.yml`. It also adds one clause: hooks must be fire-and-forget within a time budget and never change an agent's exit status. It is filed as its own PR only if Amr wants it.

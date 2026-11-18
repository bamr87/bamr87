# Decisions — Fleet activity replay, P0: contracts frozen

> **Status: Proposed.** Accepted when the maintainer merges the P0 pull request ([#618](https://github.com/bamr87/bamr87/issues/618), epic [#624](https://github.com/bamr87/bamr87/issues/624)). Nothing here runs: P0 changes no compose service, hook, collector, route or page.
> Feature: `HUB-072`. Requirements: FR66, FR67, FR68, FR69 and NFR13 in the root [`PRD.md`](../../PRD.md) (repeated as HUB-082 / FR80–FR82 / NFR16, see § 9).
> Plan: [FLEET-ACTIVITY-REPLAY-PLAN.md § 5, P0](FLEET-ACTIVITY-REPLAY-PLAN.md#p0--decisions-and-contracts-docs--tests-no-runtime-change). Design: [FLEET-ACTIVITY-REPLAY.md](FLEET-ACTIVITY-REPLAY.md) § 5.4 (prior art) and § 10 (open questions).
> Governing rules: [`docs/constitution.md`](../constitution.md) § 10.8 (prior art first: needs, survey, build-vs-adopt), § 10.5 (nothing on Amr's Mac without his yes), § 10.6 (read-only tools with caps and redaction).

## 1. What P0 freezes

| Contract | Where | Held by |
| --- | --- | --- |
| The event envelope, `fleet-activity/1` | [`schemas/fleet-activity-1.json`](../../schemas/fleet-activity-1.json), fixtures in `schemas/fixtures/fleet-activity-1/` | `tools/test_activity_contract.py`, with `jsonschema` and a strict fallback |
| The switch, sources, caps and retention | [`_data/fleet.yml`](../../_data/fleet.yml) `observability.activity` (`enabled: false`) | `tools/test_fleet_config.py` |
| The GenAI ↔ OpenInference attribute map | [`tools/observability/otel-collector/genai-openinference.yml`](../../tools/observability/otel-collector/genai-openinference.yml) | `tools/test_activity_contract.py`, against the collector's `transform/openinference` |
| The decisions below | this file | review, then the maintainer's merge |

Every later phase writes against these. A change to one of them is an additive edit with its fixture (see [`schemas/README.md`](../../schemas/README.md)), or a new major.

## 2. D1 — One envelope, with HUB-024 as one source (#620 answered: A)

[#620](https://github.com/bamr87/bamr87/issues/620) asked whether the envelope should extend the HUB-024 activity log's schema in `tools/fleet_activity.py` (A), stand beside it as a second envelope (B), or be defined inline by P2 (C).

**Decision: A.** FR66 already fixes the shape: "one append-only fleet_activity store … each event carrying a source", with fleet_event activity listed among the things it captures. B would leave two producers, two spools and two schemas for the same kind of fact, which FR66 rules out. C contradicts the accepted plan, whose P0 milestone is "contracts frozen" before any runtime.

What A means in practice:

- A HUB-024 row rides whole as `source: fleet_event`. `event_id`, `ts`, `repo` and `run_id` move to the envelope, `bot_id` becomes `actor`, `event_type` becomes the kind (`fleet_event.declined`), and the rest of the row (`task_ref`, `decision`, `outcome`, `standard_version`, `standard_source`, `detail`, `amendments`) is the payload. The row keeps its `event_id`, so the flush stays idempotent across both.
- P2 builds on `tools/fleet_activity.py` rather than writing a second spool. It already has the bounded JSONL spool, `event_id`, `redact()`, the counted overflow and the never-raise rule (NFR4, NFR5, NFR6). P2 adds the envelope fields (`source`, `kind`, `seq`, `node`) and a Redis flush target beside the existing `FLEET_ACTIVITY_ENDPOINT` POST.
- HUB-024's read surfaces, the `fleet_event` and `fleet_event_amendment` tables of [FLEET-ACTIVITY-LOG.md § 3–4](FLEET-ACTIVITY-LOG.md) with the FR11 drift query and the FR15 reader, become views over `fleet_activity` where `source = 'fleet_event'`, not a second table. This answers the design's first open question (§ 10), which had proposed two tables before FR66 settled it.
- `tools/test_activity_contract.py` wraps live rows from `tools/fleet_activity.py`, all five event types plus the spool's own overflow row, and validates each against the envelope.

## 3. D2 — The envelope, and where it differs from the design's § 5.1 draft

| Design draft (§ 5.1) | Frozen in `fleet-activity/1` | Why |
| --- | --- | --- |
| `source`: docker, docker_stats, agent_session, job, fleet_event, github_run, otel | `container`, `hook`, `session`, `job`, `fleet_event`, `harness` (reserved) | docker and docker_stats are one producer family (`container`), and samples are not stored (D3). `agent_session` is `session`. `hook` is the plan's P2 hook. `otel` is not a source: spans stay in Phoenix and join on `trace_id` (FR69). `github_run` waits on the design's still-open question 4 (live poll or `dash lake sync`) and can arrive later as an additive source. `harness` is reserved for #626 (D6) |
| `seq`: one bigserial, the global order and the cursor | `seq` (producer) and `cursor` (store) | The producer sequence is strictly increasing per (node, source) stream, so a gap is a lost event and drops stay countable after the fact (NFR13). The store assigns `cursor` on insert, and it is the global replay order and the SSE `Last-Event-ID`, one format for live and replay (FR67) |
| `project`, `repo`, `container`, `service` on every event | Required where the source has them | A container event must name its container and its `com.bamr87.fleet.project` label, so the label gate is part of the contract. Hook and session events name a project or repo. A fleet_event about the whole fleet may have neither |
| `run_id`, `trace_id` | `run_id` or `trace_id` on every event (FR66), and `span_id` only with a `trace_id` | For a container event the run is the container instance (its Docker id). Trace and span ids are W3C lowercase hex, the same ids `fleet_lake.trace_id_for` gives Phoenix and Elasticsearch |
| `payload` ≤ 4 KB, redacted | The schema rejects any payload string or key that still holds a token | The token pattern is the union of `tools/fleet_activity.py`'s redaction and `observability.logs.redact`, and the test plants every listed prefix. The size cap (`caps.payload_max_bytes`) is the writer's to enforce |
| — | `schema`, `node`, `span_id`, `cursor` | `schema: fleet-activity/1` lets a reader refuse an unknown major; `node` places an event on the Mac, forge or CI (#594) |

Unknown top-level fields are rejected, and changes within major 1 are additive only.

## 4. D3 — Container capture: the docker_stats receiver for samples, one label-gated collector for engine events

**Needs.** FR66 asks for the lifecycle and resource events of every labelled container, read-only (NFR13). [#598](https://github.com/bamr87/bamr87/issues/598)'s ingest half wants the same raw material for Elasticsearch and Prometheus: a Docker events dataset and per-node container metrics.

**Survey (checked 2026-11-16):**

| Option | Fit |
| --- | --- |
| OTel Collector contrib `docker_stats` receiver (v0.163.0; alpha; metrics only) | Samples CPU, memory, network and block I/O on an interval, copies container labels onto metric attributes, and has no label filter of its own (a `filter` processor does that). Adopt for samples, into Prometheus |
| A custom stats sampler polling `/containers/{id}/stats` | Duplicates the receiver and would turn the ledger into a second metrics plane, which the design rules out. Reject |
| cAdvisor | Another privileged container with host mounts, for the series the receiver already gives Prometheus. Reject |
| Metricbeat `docker` module (events and metrics) | Another Elastic agent on the memory-bound VM, and it writes Elasticsearch, not Redis. Reject |
| Fluent Bit `docker_events` input | An extra agent for one input, with no Redis Streams output; the label gate would be a filter script. Reject |
| An OTel receiver for engine events | None exists: contrib v0.163.0 has `docker_stats` and the `docker_observer` extension (discovery only) |
| Filebeat (already running) | Ships container logs and has no Docker events input. Keep it for logs |
| A small events collector, `tools/activity/collector.py` (P2) | One `GET /events` stream with the server-side label filter `com.bamr87.fleet.project`, stdlib only. Build |

**Decision:**

- **Samples** go through `docker_stats` into Prometheus, shared with #598. The activity store keeps no samples (`observability.activity.resource_samples: metrics`), and P3/P4 read a window's series from Prometheus by container and time. The design's `cpu_mem_sample` kind and `stats_interval_s` key are dropped.
- **Resource events** come from the engine's event stream: `container.oom`, `container.die` with its exit code, `container.health_status` and restarts. One label-gated collector emits them to the activity bus. #598's Docker events dataset should be fed from the same collector, through Logstash's shared redaction pipeline, not by a second socket reader. Whichever of #598 and #620 lands first builds it, and the other consumes it.
- **The socket.** A `:ro` bind mount of `docker.sock` does not make the Docker API read-only: any process holding the socket can still POST, including exec. So NFR13's "docker.sock read-only, no exec" needs a GET-only proxy, for example Tecnativa's docker-socket-proxy (Apache-2.0) with `CONTAINERS` and `EVENTS` on and `POST` off, in front of both the receiver and the collector. The receiver also stays out of the OTLP-ingress collector that publishes 4318, as its own README recommends for a privileged collector. This is an acceptance criterion for P2 and #598. The existing `:ro` socket mounts on the `filebeat` and `tui` services follow the same pattern and are out of scope here.

## 5. D4 — Traces stay in Phoenix, and one attribute map

Phoenix stays the trace store of record (FR69), and the activity store keeps only `trace_id` and `span_id` pointers. The attribute map is one file with three columns (Claude Code's own names, OTel GenAI, OpenInference) and the convention versions it was written against in its header:

- GenAI semantic conventions moved to [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai), read at `e6658f1` (2026-11-06). That repo has no release tag yet; its `schema_url` is `gen-ai-dev/1.42.0-dev` and its stability is `development`. Core semantic conventions v1.45.0 keep only the deprecated GenAI models and a pointer to the new repo.
- OpenInference: [`spec/semantic_conventions.md`](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md) at `7f295ae` (2026-11-12).

Findings from building the map:

1. `gen_ai.usage.input_tokens` includes cached tokens, as `llm.token_count.prompt` does, while Claude Code's `input_tokens` excludes them. So the collector's existing three-way sum is correct for both targets.
2. GenAI names the cache counters `gen_ai.usage.cache_read.input_tokens` and `gen_ai.usage.cache_write.input_tokens` (OpenInference: `llm.token_count.prompt_details.cache_read` and `.cache_write`).
3. GenAI folded `gen_ai.system` into `gen_ai.provider.name`; OpenInference keeps `llm.system` and `llm.provider` apart.
4. The content attributes (messages, tool arguments and results) stay gated by `observability.claude_code.content`, and each such row names its flag.

`tools/test_activity_contract.py` holds the map to the collector's transform in both directions: every row marked `collector: applied` is set by `transform/openinference`, and every attribute the transform sets is a row. P1 ([#619](https://github.com/bamr87/bamr87/issues/619)) adds the recorded-span test that runs a fixture span through the same rows.

**Open for P1:** how a hook learns its trace id. Claude Code's hook input carries `session_id`, not an OTel trace id. If no trace id is reachable, hook and session events correlate through `run_id` (the session id), and Phoenix spans carry `session.id`, so P3 joins on that. Until P1 settles it, the envelope requires `run_id` or `trace_id`, not both.

## 6. D5 — Licenses (checked 2026-11-16)

| Component | License | Decision |
| --- | --- | --- |
| Arize Phoenix | Elastic License 2.0 (repo `LICENSE`) | Keep. Internal and self-hosted, never offered as a managed service or redistributed. If the terms change, the fallback is Grafana Tempo over OTLP (plan § 6) |
| OpenInference | Apache-2.0 | Adopt its attribute names (D4) |
| `@evilmartians/agent-prism` | MIT | Adopt in P4, with its notice in the bundle's third-party licenses |
| disler/claude-code-hooks-multi-agent-observability | None (all rights reserved) | Reference design only: no code, assets or text are copied. The hook event list comes from the Claude Code hooks documentation |
| Langfuse (MIT outside `ee/`), Laminar, OpenLIT, Opik (Apache-2.0) | Permissive | Rejected on fit, not on license. Each needs ClickHouse (Langfuse's compose also needs MinIO), which would duplicate Phoenix on a memory-bound VM. Reconsider only if Phoenix proves limiting |
| OTel Collector contrib (`docker_stats`) | Apache-2.0 | Already in the stack (D3) |
| Tecnativa docker-socket-proxy | Apache-2.0 | The candidate GET-only proxy (D3) |

## 7. D6 — The boundary with the harness protocol (#626)

Both epics use one envelope, and a harness event is an activity event with `source: harness`.

- **This record owns** the envelope's common fields (`event_id`, `ts`, `seq`, `cursor`, `node`, location, `actor`, `run_id`, `trace_id`, `span_id`, payload redaction) and the store.
- **[#626](https://github.com/bamr87/bamr87/issues/626) owns** the kinds after `harness.` (`task.*`, `turn.*`, `tool.*`, `interrupt.*`, `budget.*`, `artifact.*`, `error`) and their payload profile in `schemas/harness-event-1.json`. It does not redefine the common fields: a harness event's id, time and trace are the envelope's.
- `harness` is in the schema's enum and out of the `fleet.yml` allowlist. #626 adds it there when its profile lands.
- A tool call can be seen twice, by the hook (`hook.pre_tool_use`) and by a harness (`harness.tool.*`). Both events are kept, and the replay view joins them on `(trace_id, span_id)` when both carry one.

## 8. D7 — The `observability.activity` block

| Key | Value | Why |
| --- | --- | --- |
| `enabled` | `false` | Constitution § 10.5: on only after Amr approves the deploy step. It gates both the compose profile and the hook |
| `profile` | `activity` | The P2 collector and writer start only under `docker compose --profile activity` |
| `sources` | container, hook, session, job, fleet_event | The allowlist; `harness` waits for #626 |
| `bus` | `fleet:activity` channel and stream | Pub/sub for the live push, the capped stream as the durable hand-off (plan § 2) |
| `store` | `db`, schema `fleet_activity` | The shared Postgres; no new storage engine |
| `caps.max_events_per_s` | 50 per (node, source) stream | A crash loop or a chatty source is dropped and counted, never queued |
| `caps.payload_max_bytes` | 4096 | The design's 4 KB |
| `caps.spool_max_events` | 5000 | `tools/fleet_activity.py`'s existing bound |
| `caps.stream_maxlen` | 100000 | The Redis tail; Postgres holds history |
| `caps.hook_budget_ms` | 50 | #620's acceptance: a hook returns within 50 ms with `db` or `redis` down |
| `retention` | monthly partitions, `raw_days: 14`, `rollup_days: 180` | The design's proposed defaults. A partition is rolled up and dropped once its newest row is older than `raw_days`, so between 14 days and about 45 days of raw rows are on disk |
| `redact` | `observability.logs.redact` | A reference to the one list, never a copy |
| `resource_samples` | `metrics` | D3: samples live in Prometheus |

## 9. Handed on, not fixed here

For P2 (#620):

- `tools/fleet_activity.py`'s redaction does not cover the `AIza` prefix that `observability.logs.redact` lists. The schema rejects such a payload, so P2 extends the redaction to the schema's `$defs.secret` pattern.
- `seq` per (node, source) needs a locked counter when several hook processes share one spool; the spool's append is unlocked today.

Records defects, flagged for the direction side (constitution § 28.5), not fixed by an execution PR:

- HUB-082 (FR80–FR82, NFR16) repeats HUB-072 (FR66–FR68, NFR13) word for word: the same feature fragment was compiled twice, once from #617 and once from #625.
- The bodies of #618–#623 link the plan and design on their pre-merge branches; both documents are on `main`.

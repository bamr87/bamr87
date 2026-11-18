# schemas

Versioned JSON Schemas for the events the hub's runtime pieces hand to each other. A schema here is a contract between code that does not ship together (a hook, a collector, a writer, the console's API, a browser view), so it is frozen first, tested against fixtures, and changed only additively within its major version. Placement rules are in [SCHEMA.md](SCHEMA.md).

| Schema | `schema` value | Written by | Read by | Test |
| --- | --- | --- | --- | --- |
| [`fleet-activity-1.json`](fleet-activity-1.json) | `fleet-activity/1` | the activity hook, the engine-events collector, the console job manager, the session differ and the HUB-024 activity log (P2, [#620](https://github.com/bamr87/bamr87/issues/620)) | the Postgres writer, `/api/activity/*` and the MCP read tools (P3, #621), the `/replay` view (P4, #622) | [`tools/test_activity_contract.py`](../tools/test_activity_contract.py) |

`schemas/harness-event-1.json` (the harness protocol, [#626](https://github.com/bamr87/bamr87/issues/626)) is the next one planned. It will define the kinds and payload of the activity envelope's reserved `harness` source and reuse the envelope's common fields rather than redefine them.

## fleet-activity/1

One event in the fleet activity store (HUB-072, FR66, FR69, NFR13). Every event has the same envelope, whichever producer wrote it:

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `fleet-activity/1` |
| `event_id` | yes | Lowercase UUID; the idempotency key of the at-least-once flush |
| `ts` | yes | When it happened at the source, UTC |
| `source` | yes | `container`, `hook`, `session`, `job`, `fleet_event`, or `harness` (reserved for #626) |
| `kind` | yes | `<source>.<what>`, e.g. `container.oom`, `hook.pre_tool_use`, `job.stalled`, `fleet_event.declined` |
| `seq` | yes | Producer sequence, strictly increasing per (node, source) stream; a gap is a lost event |
| `cursor` | store only | Global order assigned by the writer on insert; the replay and SSE resume cursor |
| `node` | yes | `mac`, `forge` (`_data/fleet.yml` `nodes.hosts`) or `ci` |
| `project`, `repo`, `container`, `service` | per source | Where it happened; a container event must name its container and its `com.bamr87.fleet.project` label |
| `actor` | per source | The agent, loop or bot; a wrapped fleet_event's `bot_id` |
| `run_id`, `trace_id`, `span_id` | `run_id` or `trace_id` | Correlation: the run (session, job, container instance, HUB-024 run) and the W3C trace and span that Phoenix and Elasticsearch carry |
| `pipeline_node` | no | Node id in `diagrams/pipeline-map/pipeline.json` |
| `payload` | yes | Small, redacted, source-specific JSON; no string or key may still hold a token |

A HUB-024 `fleet_event` row rides whole as `source: fleet_event`: `event_id`, `ts`, `repo` and `run_id` move to the envelope, `bot_id` becomes `actor`, `event_type` becomes the kind, and the rest of the row is the payload. The test wraps live rows from `tools/fleet_activity.py` to prove it.

Caps, the source allowlist, retention and the on/off switch are in [`_data/fleet.yml`](../_data/fleet.yml) `observability.activity` (off by default). Why the envelope looks like this, and what it settles for the later phases, is in [docs/prd/FLEET-ACTIVITY-REPLAY-DECISIONS.md](../docs/prd/FLEET-ACTIVITY-REPLAY-DECISIONS.md).

```bash
python3 tools/test_activity_contract.py   # every fixture, both validators when jsonschema is installed
```

## Changing a schema

1. Add the field, kind or enum value to the schema, optional unless every producer already writes it.
2. Add a `valid-*.json` fixture that uses it and, when the change adds a rule, an `invalid-*.json` that breaks only that rule, with its expected path in the test's `EXPECT`.
3. Run the test, then change the producers.

A change that would break an existing valid fixture is a new major version, not an edit.

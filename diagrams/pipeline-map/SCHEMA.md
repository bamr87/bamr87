---
schema: "0.1"
coverage: listed
---

# SCHEMA — diagrams/pipeline-map

> Inputs of the harness pipeline map: its node and edge definition and an example activity-log fixture, read by `tools/pipeline_map.py`.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What lives here and how to use it | required |
| `SCHEMA.md` | file | This file | required |
| `pipeline.json` | file | Node and edge definition (`pipeline-map/v1`) | required |
| `events.example.json` | file | EXAMPLE DATA: fictional activity-log rows for tests and demos | |

## Forbidden

- No real fleet events or credentials in `events.example.json`.

---
schema: '0.1'
coverage: listed
---

# SCHEMA — elk

> The fan-out kit that lets every fleet repo emit logs the hub's log plane can read, and stand up its own single-node ELK when cloned outside the hub.

## Conventions

- `filebeat.fleet.yml` is a **vendored payload**: byte-identical to `tools/observability/filebeat/filebeat.yml`, copied not templated, and compared by drift check (i). Edit the hub's copy first, then re-vendor.
- Templated files carry only the three tokens `tools/fanout.sh` substitutes — `__PROJECT_NAME__`, `__DEFAULT_BRANCH__`, `__KIT_VERSION__`. Any other placeholder ships as literal text.
- Snapshot a payload into `archive/` **before** editing it, or every deployed copy reads as hand-modified and `--upgrade` stops reaching the fleet.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `SCHEMA.md` | file | This contract | required |
| `VERSION` | file | Kit identity, file list, spec link and changelog; its `version:` is stamped into every templated file as `__KIT_VERSION__` | required |
| `README.md` | file | File table, install one-liner, the emission contract, standalone mode, how to change the kit | required |
| `filebeat.fleet.yml` | file | The vendored shipper config — label-gated docker autodiscover, output to Logstash | required |
| `compose.labels.yml` | file | The `com.bamr87.fleet.*` label + `json-file` rotation fragment (UPS-OPS-17) | required |
| `compose.elk.yml` | file | Standalone single-node Elasticsearch + Kibana + Filebeat overlay | required |
| `adapters/` | dir | One UPS-OPS-10 emitter per stack, each carrying the UPS-OPS-12 redaction | required terminal |
| `tests/` | dir | `contract.test.mjs` — `node --test`, zero dependencies, run by the fan-out's verify step | required terminal |
| `archive/` | dir | Previous payload shapes, the `--upgrade` byte-comparison corpus | terminal |

## Placement

- New stack's emitter → `adapters/<stack>-<library>.<ext>`, listed in `VERSION` `files:` and in README.md's table
- Change to what ships or how → the hub's `tools/observability/`, then re-vendor here
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No edits to `filebeat.fleet.yml` that the hub's copy does not have — drift check (i) reports it and the repo then ships a different shape into a shared index.
- No `output.elasticsearch` in the payload: the hub path must stay behind Logstash, where the shared redaction filter is.
- No repo-specific content beyond the three documented placeholders.

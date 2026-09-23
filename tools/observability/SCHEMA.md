---
schema: '0.1'
coverage: listed
---

# SCHEMA — observability

> The local log plane's configuration: the Logstash pipelines, the container-log shipper, and the Elasticsearch, Kibana and Grafana objects the stack is bootstrapped with.

## Conventions

- **Nothing here is hand-authored except the pipelines and the shipper.** Everything under `elasticsearch/`, `kibana/` and `grafana/dashboards/` is rendered from `_data/fleet.yml` `observability:` by `dash observe verify --write` — retention, mappings, data views and both dashboards. Edit the contract, re-render, commit both.
- Saved-object ids and datasource uids are **pinned** in the generated files. The Harness Console embeds them by id, so a minted id is a blank iframe with no error anywhere.
- Each config is mounted read-only into its container by `docker-compose.yml`'s `elk` profile.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `SCHEMA.md` | file | This contract | required |
| `bootstrap.sh` | file | Idempotently installs the rendered objects into a running stack (PUT ILM + templates, import Kibana saved objects, report Grafana); run by `dash observe up` | required |
| `logstash/` | dir | The one normalization and redaction path — `pipelines.yml` plus `pipeline/*.conf`: two inputs (beats, http) feeding one shared `enrich` output. Logstash's own config format, not a pyramid level | required terminal |
| `filebeat/` | dir | `filebeat.yml`, the container-log shipper — label-gated docker autodiscover; vendored to the fleet as `templates/elk/filebeat.fleet.yml` and held equal by drift check (i) | required terminal |
| `elasticsearch/` | dir | `ilm-policies.json` + `index-templates.json`, rendered from the contract's `retention_days` / `rollover` / `datasets` | generated |
| `kibana/` | dir | `dashboards.ndjson` — data views, saved searches and the pinned dashboards, in Kibana's import format (one object per line; a JSON array is rejected) | generated |
| `grafana/` | dir | `provisioning/` (datasource with a pinned uid + the dashboard provider, hand-authored) and `dashboards/fleet-logs.json` (generated, pinned uid) | required terminal |

## Placement

- New Logstash input or filter → `logstash/pipeline/<NN>-<name>.conf`, registered in `pipelines.yml`; redaction and ECS mapping stay in `90-enrich-out.conf`
- New dataset, retention change, or dashboard panel → `_data/fleet.yml` `observability:` and the renderers in `.github/scripts/dash-gen/fleet_observe.py`, then `dash observe verify --write`
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No hand-edits to the `generated` entries — `dash observe verify` fails on the diff and the next `--write` discards them.
- No credentials: the stack runs security-off on loopback precisely so none are needed, and `_data/` and this tree are public.
- No second redaction point. One shared `enrich` pipeline, or the next input added leaks.

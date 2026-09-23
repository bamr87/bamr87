# ELK kit — structured logs, shipped

The hub runs one log plane for the whole fleet: Elasticsearch, Logstash, Kibana and Filebeat behind `docker compose --profile elk`, with Grafana drawing trends over the same indices and the Harness Console's **Observe** tab as the front door ([docs/OBSERVABILITY.md](../../docs/OBSERVABILITY.md)).

This kit is the other half — what a repo needs in order to **produce** logs that plane can read, and to stand up its own single-node copy when it is cloned outside the hub.

| File | What it is |
| --- | --- |
| `filebeat.fleet.yml` | **The vendored payload.** One shipper config fleet-wide, byte-identical to the hub's `tools/observability/filebeat/filebeat.yml` and held there by drift check (i) |
| `compose.labels.yml` | The `com.bamr87.fleet.*` labels and `json-file` rotation (UPS-OPS-17) |
| `compose.elk.yml` | A standalone single-node Elasticsearch + Kibana + Filebeat overlay, for a clone outside the hub |
| `adapters/python-logging.py` | UPS-OPS-10 JSON formatter + the UPS-OPS-12 redaction filter, stdlib only |
| `adapters/node-pino.mjs` | The same for pino, with a UPS-OPS-11 request logger |
| `adapters/django-logging.py` | Django `LOGGING` wiring over the Python adapter |
| `adapters/rails-lograge.rb` | lograge configured to the same field names |
| `tests/contract.test.mjs` | 9 contract tests, `node --test`, no dependencies |
| `archive/` | The `--upgrade` byte-comparison corpus |

## Install

```bash
tools/fanout.sh --kit elk --target <name>          # DRY RUN — inspect the diff
tools/fanout.sh --kit elk --target <name> --apply  # opens one PR
```

Seeding is **additive**: it never edits a hand-written `docker-compose.yml`. The seeder prints the one line a human adds, exactly as the feedback kit prints its mount line:

```yaml
include:
  - path: compose.labels.yml
```

…then four lines per service that should reach the log plane:

```yaml
services:
  web:
    labels:
      <<: *fleet-labels
      com.bamr87.fleet.stack: node
    logging: *fleet-logging
```

That is the whole integration inside the hub. The labels are the opt-in: the hub's Filebeat autodiscovers on `com.bamr87.fleet.project` and ignores every container without it, so nothing central changes when this repo appears.

## The contract

One line of JSON per event, with the fields [UPS-OPS-10](../../specs/OPERATIONS.md) names — `ts`, `level`, `msg`, `logger`, `request_id`, `app`, `version`. The adapters emit exactly that.

Why it matters beyond tidiness: the ingest pipeline routes a line carrying both `level` and `msg` to the **`fleet.app`** dataset and everything else to **`fleet.container`**, and those two have different retention (30 days against 14). A line that loses a field is not an error anywhere — it just lands in the shorter-lived index, missing the column a dashboard filters on.

**Redaction runs at emission, not only at ingest.** The hub's Logstash carries the shared filter, but a repo running standalone has no Logstash in its path at all — so each adapter applies the credential patterns itself. A secret redacted at emission also never reaches a terminal scrollback, a screenshot or a bug report, which is a stronger guarantee than never reaching the index.

## Standalone mode

Outside the hub:

```bash
docker compose -f docker-compose.yml -f compose.elk.yml --profile elk up -d
open http://127.0.0.1:5601
```

Deliberately simpler than the hub's stack — no Logstash, no Grafana. One repo's logs need to be searchable, not normalised across a fleet or trended against a budget. The standalone Filebeat writes straight to Elasticsearch, switched with `-E` flags rather than by editing `filebeat.fleet.yml`: a second copy of that file would defeat the point of vendoring one.

**Do not run this inside the hub.** The hub already runs one Elasticsearch for the whole fleet, and a second will fight it for port 9200 and for a gigabyte of heap.

## Changing the kit

1. Snapshot the outgoing `filebeat.fleet.yml` into `archive/` **first**, or every deployed copy reads as hand-modified and `--upgrade` stops reaching the fleet.
2. Edit the **hub's** `tools/observability/filebeat/filebeat.yml`, then re-vendor it here — drift check (i) compares the two.
3. `node --test tests/`
4. Bump `VERSION` with a changelog entry.

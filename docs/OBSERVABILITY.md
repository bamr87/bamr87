# Observability — the three local planes and the one front door

> **`docs/HARNESS-OPS.md` is how the fleet's harnesses are operated; this is how you see what they did.** Phoenix already held traces. This document is the plane that was missing — logs — and the portal that puts all three in one place.

## The model in one paragraph

Three planes run on the bench and each answers a different question. **Logs** (Elasticsearch, searched in Kibana) answer *what exactly did it say* — the raw text of every line the fleet's CI and this machine's containers produced. **Metrics** (Grafana, over the same indices) answer *how much, over time* — volume, error rate, agent spend, index growth against a budget. **Traces** (Phoenix) answer *what shape did this agent run have* — the tree of workflow → job → step → Claude turns → tool calls, with cost and latency per span. They are one system rather than three because every Actions document carries the **same `trace.id`** the Phoenix exporter stamps on the same run, so one id addresses the same work in all three. The Harness Console's **Observe** tab is the front door: three panes, embedded, with the full apps a click away.

```text
GitHub Actions                             Local Docker containers
  run log zips                               (hub services + submodule stacks)
      │                                            │
      │ fleet_lake.iter_log_entries()              │ filebeat docker autodiscover
      │  ONE download, ONE parser, TWO sinks       │  label-gated: com.bamr87.fleet.*
      ├──────────────► .dash-lake/fleet.sqlite     │
      │                 (capped 2 MB/run — offline review, unchanged)
      │                                            │
      └──► dash observe ship ──┐          ┌────────┘
                               ▼          ▼
                        Logstash :8088(http) :5044(beats)
                               └──► drop verbatim copies → ECS → REDACT → route
                                              │
                                              ▼
                                  Elasticsearch :9200
                                       │          │
                              Kibana :5601    Grafana :3001
                                (search)      (trends)
                                       │          │
                                       └────┬─────┘
                                            ▼
                          Harness Console :4001 — Observe
                          Logs · Metrics · Traces (Phoenix :6006)

trace.id is the SAME sha256 in Elasticsearch and in Phoenix — one id, three planes.
```

**Local-only by construction**, exactly like the lake (`docs/COCKPIT.md` non-negotiable 4): every port binds `127.0.0.1`, every byte lives in a Docker volume, none of it runs in CI, and nothing reaches Pages. That is what lets it hold raw run logs the committed `_data/*.yml` aggregates deliberately leave out — and it is the only reason `xpack.security.enabled: false` and an anonymous Grafana viewer are defensible here. If you ever front the console with a proxy (`DASH_CONSOLE_ALLOWED_HOSTS`), both become real exposure and both need revisiting first.

## Operate — the short card

```bash
tools/dash observe up                     # start the elk profile + install ILM and dashboards
tools/dash observe status                 # every plane's health, dataset sizes vs the disk budget
tools/dash lake sync --days 7             # extract the CI plane (needs gh auth, or GH_TOKEN)
tools/dash observe ship --days 7          # replay those runs into Logstash as ECS documents
tools/dash observe ship --dry-run         # build everything, write observe-preview.json, send nothing
tools/dash observe verify                 # re-render ILM + dashboards from fleet.yml and diff
tools/dash observe open                   # the Console's Observe tab — the front door
tools/dash observe down                   # stop the stack, keep the data
tools/dash observe reset                  # destroy the indices and volumes (asks first)
```

**Extract before you analyze.** `ship` replays what `lake sync` already pulled; it is not a second GitHub client. If the lake is empty, so is the index.

## What ships, and from where

### GitHub Actions — a second sink on the existing extractor

`dash lake sync` already downloads every run's log zip. It stores those entries in SQLite under a 2 MB per-run cap, which is right for offline review and wrong for full-text search. So `store_logs()` was split: [`fleet_lake.iter_log_entries()`](../.github/scripts/dash-gen/fleet_lake.py) is now a generator over the zip, and two consumers read it — the capped SQLite upsert it always had, and the uncapped ECS emitter in [`fleet_observe.py`](../.github/scripts/dash-gen/fleet_observe.py).

One download, one zip walk, one timestamp parser, two destinations. A second downloader would be a second set of ordering, decoding and rate-limit bugs to keep in step — and the hub's rule is that nothing here is a second implementation of anything.

The lake also stays the **ledger**: a `shipments` table beside the existing `exports` one, with the same contract. A run already shipped is skipped unless `--force`, so re-running the shipper is free rather than a duplicate index of every log line the fleet has ever produced.

### Local containers — the label is the opt-in

Filebeat autodiscovers containers by the `com.bamr87.fleet.*` labels (UPS-OPS-17) and **ignores everything without them**. A service joins the log plane by labelling itself; nothing central is edited when a submodule stack appears. The hub's own services carry the labels and a rotated `json-file` driver, so they were the first citizens.

The read-only `/var/run/docker.sock` mount is required rather than convenient: on Docker Desktop for Mac the container log files live inside the VM, so the paths alone are unreachable from the host and autodiscover is the only route to the container→label mapping. It is the broadest grant in the compose file — read-only, loopback stack, local bench only.

### One dataset per source, the repo as a field

| Data stream | What lands in it | Retention |
| --- | --- | --- |
| `logs-fleet.actions-default` | GitHub Actions run logs, replayed from the lake | 90 days |
| `logs-fleet.app-default` | Container lines that parsed as UPS-OPS-10 JSON (they carry `level` **and** `msg`) | 30 days |
| `logs-fleet.container-default` | Everything else a container printed | 14 days |

Forty repos × three sources would be 120 data streams to template, alias and expire. This is three, with `fleet.repo` as a keyword field — Kibana filters on it and ILM never has to know it exists. The app/container split is deliberate too: structured and unstructured output get different retention, so the difference stays *visible* instead of being averaged into one index.

## The field contract

Documents are ECS where ECS has a field and `fleet.*` where it does not.

| Field | Source |
| --- | --- |
| `@timestamp`, `message` | The log line itself — `fleet_lake`'s splitter, so the timestamp is when GitHub recorded it, not when we shipped it |
| `log.level` | Parsed from the line; inferred for unstructured output so "show me errors" works across all three datasets |
| `event.dataset`, `event.module` | Which stream, and which producer (`github.actions`, `claude.agent`) |
| `service.name`, `fleet.repo` / `.project` / `.category` / `.stack` | Attribution, from the registry and the container labels |
| `ci.run_id`, `.workflow`, `.job`, `.step`, `.conclusion`, `.branch`, `.sha` | The run this line came from |
| `llm.model`, `.cost_usd`, `.turns`, `.session_id` | Present on AI runs |
| **`trace.id`** | **`fleet_lake.trace_id_for(run_key)` — byte-identical to the Phoenix trace id** |

`ecs_from_agent_run()` also emits **one summary document per AI run**, tagged `event.module: claude.agent`. The per-line documents carry the same `llm.*` fields, so a cost aggregation must sum the summary and not the lines — otherwise the total is multiplied by the line count. That is why the two carry different `event.module` values, and why a test asserts it.

### Redaction, and the leak that shaped it

GitHub masks secrets in its own logs. Nothing masks a local container's, and nothing masks a `--dry-run` preview written to disk. Redaction is therefore applied in **two** places on purpose: in the shipper as it builds each document, and in the one shared Logstash `enrich` pipeline both inputs pass through. Redacting per input instead would work right up until someone adds a third.

The pipeline **drops the verbatim copies before it redacts**, and that ordering is not cosmetic. Logstash's http input, in ECS-compatibility mode, stores the *whole raw request body* in `event.original`. On the first live document through this stack, the indexed result showed a correctly masked `message` sitting next to an unmasked copy of the same GitHub token — redaction looked like it was working. `event.original`, `log.original` and the http input's transport metadata are now removed first, and a contract test asserts the ordering.

Free-text fields other than `message` are redacted too: a stack trace in `error.message` is exactly where a token ends up.

## Retention and disk

Retention lives in [`_data/fleet.yml`](../_data/fleet.yml) `observability.logs.retention_days` and is **rendered** into ILM policies by `dash observe verify --write`, never hand-written. That is what stops the two drifting — and a drifted delete phase on a laptop ends as a cluster wedged read-only at Elasticsearch's 95% flood watermark, which fails silently until the next write.

`dash observe status` reports total bytes against `disk_budget_gb` and warns well before that point.

**Memory is the real constraint, not disk.** Elasticsearch takes roughly twice its heap in resident memory. The default is `ES_HEAP=512m` — not the 1 GB that looks natural — because this bench runs around twenty containers from a dozen projects inside a 7.7 GiB Docker VM, and 1 GB took Elasticsearch to an exit-137 OOM kill on its first start. If a container dies with code 137 it was OOM-killed: lower the heap, stop what you are not using, or give Docker Desktop more memory. Kibana is the heaviest of the five and the one to stop first.

## The portal

The Console's **Observe** tab ([`tools/console/`](../tools/console/README.md)) embeds the pinned Kibana dashboard and the Grafana panels, with `Open full app ↗` beside each and the Traces pane unchanged. A plane that is not running renders as a **Start** button, never an error — the stack is opt-in behind a profile, so "not running" is the ordinary state.

Two things make the embeds work, and both fail the same silent way when wrong — a blank iframe and one line in a browser console nobody has open:

- **Pinned ids.** Kibana dashboard ids and the Grafana dashboard and datasource `uid`s are fixed in the committed saved objects, not minted at import. `dash observe verify` resolves every id the contract references against those files.
- **A `frame-src` allowlist.** The console now sends a deliberately narrow CSP: `frame-src` naming the three plane origins from `observability.portal.frame_src`, plus `frame-ancestors 'none'`. There is no `default-src` — `index.html` is a single file of inline script and style, so a policy with one would have to carry `'unsafe-inline'` to work at all, which is a worse policy than none. The `frame-ancestors` half is a free win: this origin can dispatch workflows with the operator's `FLEET_TOKEN`, and is now not embeddable by anyone. A full nonce-based CSP (UPS-OPS-23) needs `index.html` templated and is a separate change.

Grafana runs with an anonymous **Viewer** so an embed does not have to complete a login across origins, and on port **3001** because the wiki has owned 3000 since before this plane existed.

## The code index

Kilo Code's codebase index is a local store, not a fourth question. Logs, metrics and traces still answer what was said, how much, and what shape a run had. The index answers a different one — *where is the code that means this* — and it is operated from the same front door so a missing submodule or a down vector store is visible next to the other planes instead of as a silent empty search.

`kilo.jsonc` turns indexing on for this worktree. The scanner walks the filesystem and skips a path segment named `.git`, not the tree beside it, so every checked-out submodule under `projects/` is in the same index as the hub. An uninitialized submodule is an empty directory and is not indexed; `dash observe status` lists those paths. Opening a submodule as its own workspace does not inherit this file — that repo's git root is the submodule, and the hub does not write into it.

The same collection is what the harness searches when it needs to harmonize the fleet, not a second copy in Elasticsearch. `tools/dash index status` reports coverage and the scanner's blind spots. `tools/dash index search` is semantic search with hits below `observability.indexing.analysis.min_score` dropped. `tools/dash index harmonize <pattern>` embeds the pattern once and takes the best hit inside each submodule, so a project that does not clear the floor is a gap rather than a victim of some other repo filling the top-k window. The Observe tab's Index pane draws the same three views. A nonsense query scored about 0.55 and real matches sat at 0.72 and above, which is why the floor is 0.66 and not the client's default of 0.4.

The vector store is Qdrant, started by `tools/dash observe up` with the elk profile, bound to `127.0.0.1:6333`, and labelled so Filebeat ships its logs into `logs-fleet.container-default`. The image is pinned (`observability.indexing.qdrant_version`) because Kilo's client is 1.17.0 and refuses a server more than one minor away — `latest` was 1.19.1 and the scan never started. The embedder is native Ollama on the Mac (`brew services start ollama`, model `nomic-embed-text`), not a container — Docker Ollama is too slow for embeddings, and this bench already OOM-killed Elasticsearch beside a second heavy container. `kilo.jsonc` and `_data/fleet.yml` `observability.indexing` both name that URL and model; `test_observe_contract.py` fails when they do not. From inside the console container the embedder is reached at `host.docker.internal:11434`, because `127.0.0.1` there is the container. The scan itself starts when Kilo opens this workspace, not when the stack comes up.

## Per-repo: emit, ship, standalone

The hub runs one stack; every repo is a producer. The [`templates/elk/`](../templates/elk/README.md) kit is that half, fanned out additively like every other:

```bash
tools/fanout.sh --kit elk --target <name>          # DRY RUN — inspect the diff
tools/fanout.sh --kit elk --target <name> --apply  # one PR
```

It seeds the vendored shipper config, the label fragment, a standalone single-node overlay, and the UPS-OPS-10 logging adapter for the detected stack — then **prints the one line a human adds** to `docker-compose.yml`. It never edits a hand-written compose file, for the same reason the feedback kit never edits a hand-written page shell.

`filebeat.fleet.yml` is **vendored, not templated**: byte-identical in every repo, and held there by drift check (i). A drifted copy still ships, into the same shared index, with different fields — which is not a broken repo but a quietly inconsistent dataset, and those are only noticed when a dashboard filter comes back empty for one repo and nobody can say since when.

Standalone mode (`compose.elk.yml`) is deliberately simpler than the hub's — no Logstash, no Grafana. One repo's logs need to be searchable, not normalised across a fleet. It switches Filebeat's output with `-E` flags rather than editing the vendored payload, and the emission-side redaction in the adapters is what protects it, since the hub's central filter is not in its path.

## Where its output shows up

| Surface | What it shows |
| --- | --- |
| Harness Console `:4001` → **Observe** | All three planes, embedded, with the ops as jobs |
| Kibana `:5601` | `fleet-ci` (failing steps + the agent runs behind them), `fleet-local` (container and app logs) |
| Grafana `:3001` | `fleet-logs` — volume and error rate by repo, agent spend by model, CI failures by workflow |
| Phoenix `:6006` | The trace tree for any `trace.id` seen in the other two |
| `tools/dash observe status` | The same numbers without a browser, plus whether Qdrant is up and which submodules are checked out |
| `tools/dash index harmonize` | Which submodules share a pattern, and which do not — the harness gap list |
| Harness Console `:4001` → **Observe** → **Index** | Store health, coverage bars, semantic search, and the harmonize gap list |

Nothing appears on the Pages dash. The committed `_data/*.yml` aggregates stay the published surface; raw logs stay here.

## Files

| Path | What |
| --- | --- |
| [`_data/fleet.yml`](../_data/fleet.yml) `observability:` | The contract — retention, datasets, redaction prefixes, portal ids, image versions, and the code-index URLs |
| [`kilo.jsonc`](../kilo.jsonc) | Kilo Code indexing for this worktree. URLs and model must agree with `observability.indexing` |
| [`tools/observability/`](../tools/observability/) | Logstash pipelines, the Filebeat config, and the rendered ES/Kibana/Grafana objects |
| [`.github/scripts/dash-gen/fleet_observe.py`](../.github/scripts/dash-gen/fleet_observe.py) | Shipper, ECS mappers, renderers, status |
| [`.github/scripts/dash-gen/fleet_lake.py`](../.github/scripts/dash-gen/fleet_lake.py) | `iter_log_entries()` and the `shipments` ledger |
| [`templates/elk/`](../templates/elk/README.md) | The per-repo kit |
| `docker-compose.yml` profile `elk` | The five services |

Tests: `test_fleet_observe.py` (the mappers), `test_observe_contract.py` (compose ↔ `fleet.yml` ↔ saved objects, both directions), `templates/elk/tests/` (the kit). All offline, all in `tools/run-all-tests.sh`.

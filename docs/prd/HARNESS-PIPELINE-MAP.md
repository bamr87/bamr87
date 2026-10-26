# PRD — Harness pipeline map (the "illustration")

> **Status: Draft / proposed.** Data layer implemented in this PR; the console page is specified, not built.
> Features: `HUB-025` (pipeline map) and `HUB-026` (GitHub workflow nodes) in [`features/features.yml`](../../features/features.yml).
> Requirements: FR16–FR21, NFR7 in the root [`PRD.md`](../../PRD.md), which owns the ids; this document gives the detail.
> Depends on: [#409](https://github.com/bamr87/bamr87/pull/409) (fleet activity log PRD, `HUB-024`, FR7–FR15). Field names below are that PRD's, verbatim. The scheduled backlog fan-out routine ([#411](https://github.com/bamr87/bamr87/pull/411), `HUB-027`) logs with `bot_id` `backlog-fanout` from the `backlog-fanout` workflow; the map's `fanout-routine` node uses that `bot_id` and job name.
> Governing rules: [`docs/constitution.md`](../constitution.md) and [`docs/amendments/`](../amendments/).

## 1. Problem

The fleet's loops (scheduled fan-out, routing, seven bots, the activity log write path, the drift query) and its GitHub workflows run in many places. The Harness Console (`tools/console/`) shows boards and the archify diagrams in `diagrams/`, but those are static: nothing shows the whole pipeline at once with what is running, idle or failed now, or lets the operator click from a box to the events, PRs, standard version and amendments behind it.

## 2. Prior art reused

- **bamr87/gitorio** (GitFactory): a static TypeScript/React app where machines and belts form a factory floor; Fleet Observe draws a repo's workflows with live run status on every node, read from the Actions API; clicking a machine opens its "passport"; a `?demo=1` fixture client sits behind the same seam as the real client. Reused here: node = machine with a status lamp, click = passport (drill-down), fixture behind the same seam as live data, GitHub is the data source for run status, read-only. Related context: gitorio PRs #79 and #95 and issue #117 (absorb the console into Gitorio); the view model below is plain JSON so either surface can render it.
- **This hub's diagram system** (merged PR #191): typed archify JSON in `diagrams/*.json` → self-contained HTML via `tools/render-diagrams.sh`, served by `tools/console/app.py` `/diagrams/{name}`, copied to Pages by `tools/console/build-pages.sh`, embedded on `/harnesses/health` from the hand-listed `DIAGRAMS` array in `tools/console/web/src/pages/HealthPage.tsx`. The pipeline map extends this system: its definition lives in `diagrams/pipeline-map/`, it gets a static archify twin, and it joins the Health page's diagram picker.

## 3. Harness location

The "bamr87-console-harness" is the Harness Console in this repo: `tools/console/` (FastAPI `app.py` + `core.py`, whose `LOOPS` registry lists the control-plane loops; React UI in `tools/console/web/src`), published static as bamr87.github.io/bamr87 (`HUB-013`, `HUB-022`). No separate repo or submodule exists.

## 4. Node and edge model — FR16

Source of truth: [`diagrams/pipeline-map/pipeline.json`](../../diagrams/pipeline-map/pipeline.json) (`schema: pipeline-map/v1`).

| Field | Meaning |
| --- | --- |
| `lanes[]` | `{id, label}` rows: scheduled loops, router, bots (two rows, archify's 6-column limit), activity log, readers; `workflows` is appended at build time |
| `nodes[].id` / `label` / `lane` / `col` | Stable id, display label, row and column |
| `nodes[].kind` | `loop`, `routine`, `router`, `bot`, `store`, `query`, `reader`, `workflow` |
| `nodes[].match` | How the node selects `fleet_event` rows: `{bot_id}`, plus optional `event_type` or `decision_prefix`; `{any: true}` (write path sees everything); `{drift: true}` (drift query rows) |
| `nodes[].job` | Name of the job whose status overlays the node (e.g. `backlog-fanout`, `log-flush`) |
| `nodes[].notes` | One-line behavior, shown in the drill-down |
| `edges[]` | `{from, to, label?, kind?}`; `kind` ∈ default (control), `emit` (log write), `read` |

Nodes covered: fan-out routine, its dry-run gate and merge block (merge is always a `declined` event with `reason: policy`); the router (Grok Bot); seven bot task handlers (Fleet Ops, Platform Architect, Bashcrawl & Games, Law AI Lead, Sites, Tools, Content & Comms, `bot_id`s `fleet-ops`, `platform-architect`, `bashcrawl-games`, `law-ai-lead`, `sites`, `tools`, `content-comms`); the fire-and-forget log wrapper; the spool flusher; `fleet_event` + `fleet_event_amendment`; the drift query; the console reader; and one node per GitHub workflow (§8).

## 5. Status derivation — FR18

Computed by `tools/pipeline_map.py` `derive_status`, first match wins:

1. **failed**: the node's job `conclusion` is `failure`, `timed_out` or `startup_failure`; or, within 24 h, a `finish` event with `outcome = failure` or a `retry` event with `detail.final_outcome = gave_up`.
2. **running**: job `status` is `in_progress` or `queued`; or a `start` event with no `finish` for the same `run_id`, younger than 6 h.
3. **idle**: the log is readable (or a job status exists) and neither rule above fired.
4. **unknown**: the log is unavailable and there is no job status.

Workflow nodes: `running` if the last run is `in_progress`/`queued`, `failed` on a failing conclusion, `idle` otherwise, `unknown` with no run data.

## 6. Data contract to the log — FR17, FR19

Reads only `fleet_event` and `fleet_event_amendment` (#409 §3–4). With the Postgres store the console runs, per refresh:

```sql
-- events (window + cap keep it cheap)
SELECT event_id, ts, bot_id, repo, task_ref, run_id, event_type, standard_version,
       standard_source, decision, outcome, detail
FROM fleet_event WHERE ts > now() - interval '7 days' ORDER BY ts DESC LIMIT 5000;
-- amendment links for those events
SELECT event_id, amendment, repo, relation FROM fleet_event_amendment WHERE event_id = ANY(:ids);
-- drift rows: #409 §6 drift query, verbatim, with :current from AGENTS.md
```

With a JSON-lines or JSON export, the same rows in the shape of `diagrams/pipeline-map/events.example.json` (`events`, `amendment_links`, `jobs`, `current_standard_version`). Node matching is done in Python, not SQL, so the map definition can change without a migration.

**Drill-down (FR19):** each node in the view model carries `drill.events` (newest 50), `drill.prs` (`task_ref`s shaped `owner/name#N`), `drill.standard_versions`, and `drill.amendments` (link rows, rendered as links to `docs/amendments/NNNN-*.md` in `repo`).

## 7. Refresh and degraded behavior — FR20, NFR7

- The console serves the view model at `GET /api/pipeline-map` (to build) by calling `pipeline_map.build`; the page polls every 60 s while visible and has a **Refresh** button. Workflow runs are fetched only on that button or a 15-minute TTL (FR21), to protect the API rate limit.
- **Empty log** (readable, zero events): every log-derived node is `idle`, with an empty drill-down that says "no events in window".
- **Unavailable log** (store down, file missing or unreadable): the map still renders from `pipeline.json`; log-derived nodes are `unknown` (grey), a banner says "activity log unavailable", and job/workflow statuses still show. The view model's `log` field is `available`, `unavailable` or `example`.
- **Example data**: `events.example.json` is fictional. When it is the source, `log = example` and the page must show an "EXAMPLE DATA" banner. The public Pages build uses only the example or a committed snapshot, never a live store or a token.
- **NFR7:** the map is read-only. It never writes to the log, GitHub or any repo. A GitHub token comes only from `GITHUB_TOKEN`/`GH_TOKEN` (console) or the Connect page token (Pages) and is never logged or embedded in output.

## 8. GitHub workflow nodes — FR21 (HUB-026)

Every file in `.github/workflows/*.yml` becomes a node in the `workflows` lane showing:

- **triggers**: the keys of its `on:` block (`push`, `pull_request`, `schedule`, `workflow_dispatch`, `workflow_run`, …);
- **schedule**: each `schedule[].cron` string;
- **last run**: `status`, `conclusion` (shown as pass/fail), `event`, `html_url`, `updated_at`, `run_number` of the latest run, from `GET /repos/{repo}/actions/workflows/{file}/runs?per_page=1`.

Triggers and schedules are parsed from the checked-out files (no network). Last runs are retrieved from the GitHub API and refreshed on demand (`python3 tools/pipeline_map.py --refresh-runs`, and the console's Refresh button); a failed API call marks only that node `unknown`.

## 9. What is built in this PR, and what is next

**Built:** `diagrams/pipeline-map/pipeline.json`, `diagrams/pipeline-map/events.example.json` (EXAMPLE DATA), `tools/pipeline_map.py` (view model, status rules, drill-down, workflow nodes, GitHub refresh), `tools/test_pipeline_map.py` (offline). Try it:

```bash
python3 tools/pipeline_map.py --events diagrams/pipeline-map/events.example.json   # example log
python3 tools/pipeline_map.py                                                     # log unavailable
GITHUB_TOKEN=… python3 tools/pipeline_map.py --refresh-runs                        # live workflow runs
python3 tools/test_pipeline_map.py
```

**Next (separate PRs):**

1. `GET /api/pipeline-map` in `tools/console/app.py` (+ `?refresh=runs`), and a snapshot of it in `tools/console/snapshot.py` for Pages.
2. A `PipelineMapPage.tsx` route `/harnesses/map`: lanes as rows, nodes as cards with a status lamp (running blue pulse, idle grey-green, failed red, unknown grey), workflow cards showing triggers, cron and pass/fail; click opens a passport drawer with the drill-down; EXAMPLE and unavailable banners.
3. A static archify twin `diagrams/harness-pipeline.workflow.json`, rendered by `tools/render-diagrams.sh`. A first attempt in this PR failed showcase validation on 7 bots × fan-in edges; it needs hand-routed edges.
4. Replace the hand-listed `DIAGRAMS` in `HealthPage.tsx` with a generated `diagrams/manifest.json`.
5. Point `match.bot_id` and `job` at the fan-out routine's real ids once its PRD lands.

## 10. Requirements

| Id | Requirement |
| --- | --- |
| FR16 | A pipeline definition (`diagrams/pipeline-map/pipeline.json`) names every harness loop and AI routine as nodes and edges: fan-out routine with dry-run and merge block, router, seven bot task handlers, log wrapper, flusher, log store, drift query, console |
| FR17 | The map reads `fleet_event` and `fleet_event_amendment` only, with #409's field names |
| FR18 | Each node shows a running / idle / failed / unknown status derived by the rules in §5 from the activity log and job status |
| FR19 | Clicking a node shows its events, PRs, standard versions and amendment links |
| FR20 | Polled and on-demand refresh; the map renders with an empty or unavailable log and labels example data |
| FR21 | Every GitHub workflow is a node showing its triggers, schedule and last run status (pass/fail), retrieved from the GitHub API and refreshable on demand from the console |
| NFR7 | The map is read-only and never prints, logs or embeds a token |

## 11. Open questions

- Should workflow nodes cover every fleet repo's workflows or only the hub's? (Hub only for now.)
- Should the map link workflow nodes to the bots that dispatch them? (Needs a `workflow` field on events.)

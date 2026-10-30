#!/usr/bin/env python3
"""
fleet_observe — the LOG plane: ship, render, verify, report.

Three planes run on the local bench and each has one job. Phoenix holds traces
(shape, latency and cost of an agent run). Grafana draws trends. THIS module
owns logs: the raw text of what the fleet's CI and containers actually said,
indexed in Elasticsearch and searchable in Kibana. It also reports the Kilo
code index (Qdrant + submodule checkout) from the same status path — that
store is not a fourth question, it is the semantic index the Observe tab
shows next to the other three.

Two halves, split on network — the same division harness_registry.py uses, and
for the same reason: everything that decides anything is a pure function over
committed contract data, so it is fixture-testable offline, and only the thin
outer layer talks to Elasticsearch or GitHub.

  pure   ecs_from_log_entry / ecs_from_agent_run / dataset_for / redact /
         ilm_policy_for / index_template_for / data_stream_for
  i/o    ship (lake -> Logstash), status (cluster + datasets), bootstrap docs

WHAT IT DOES NOT DO: re-download anything. `dash lake sync` already pulls every
run's log zip; this module replays those same entries through
fleet_lake.iter_log_entries, which is the one downloader, the one zip walk and
the one timestamp parser. The lake stays the authority on what exists and the
ledger for what has shipped.

THE JOIN: every Actions document carries trace.id = fleet_lake.trace_id_for(key)
— byte-identical to the id the Phoenix exporter stamps on the same run. One id
therefore addresses the same work in Kibana, Grafana and Phoenix, which is what
makes the Harness Console's Observe tab a portal rather than three bookmarks.

Contract: _data/fleet.yml `observability:`   Full doc: docs/OBSERVABILITY.md
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

import fleet_lake

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"
CONFIG_DIR = REPO_ROOT / "tools" / "observability"

SINK = "elasticsearch"
ECS_VERSION = "8.11.0"

# Fallbacks for when a key — or the whole block — is absent. _data/fleet.yml is
# the contract; these exist so an offline render still produces something valid
# rather than a KeyError, exactly as harness_registry.py does it.
DEFAULT_LOGS = {
    "namespace": "default",
    "datasets": {"actions": "fleet.actions", "container": "fleet.container", "app": "fleet.app",
                 "claude": "fleet.claude"},
    "retention_days": {"actions": 90, "container": 14, "app": 30, "claude": 90},
    "rollover": {"max_primary_shard_size": "10gb", "max_age": "1d"},
    "disk_budget_gb": 40,
    "redact": ["sk-ant-", "ghp_", "github_pat_", "gho_", "ghs_", "AIza"],
    "elasticsearch": "http://127.0.0.1:9200",
    "kibana": "http://127.0.0.1:5601",
    "logstash_http": "http://127.0.0.1:8088",
    "ship": {"source": "lake", "logs": "all", "batch": 500},
}

# One pattern per redact prefix. Kept here AND in the Logstash filter on
# purpose: Logstash guards what arrives over the wire, this guards what the
# shipper builds, and a document that never reaches Logstash (a --dry-run
# preview written to disk) still has to be clean.
REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]+"), "github_pat_[REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_[REDACTED]"),
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "gho_[REDACTED]"),
    (re.compile(r"ghs_[A-Za-z0-9]{20,}"), "ghs_[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{20,}"), "AIza[REDACTED]"),
]

LEVEL_RX = re.compile(r"\b(error|fatal|critical|warn(?:ing)?|debug|trace)\b", re.I)


# --------------------------------------------------------------------------- #
# contract
# --------------------------------------------------------------------------- #
def load_contract(fleet_path: Path | str | None = None) -> dict:
    """The `observability:` block, with DEFAULT_LOGS filled in behind it."""
    path = Path(fleet_path) if fleet_path else FLEET_DEFAULT
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except OSError:
        doc = {}
    obs = dict(doc.get("observability") or {})
    logs = dict(DEFAULT_LOGS)
    logs.update(obs.get("logs") or {})
    for key in ("datasets", "retention_days", "rollover", "ship"):
        merged = dict(DEFAULT_LOGS[key])
        merged.update((obs.get("logs") or {}).get(key) or {})
        logs[key] = merged
    obs["logs"] = logs
    obs.setdefault("metrics", {})
    obs.setdefault("traces", {})
    obs.setdefault("indexing", {})
    obs.setdefault("portal", {})
    return obs


def data_stream_for(dataset_key: str, contract: dict) -> str:
    """`logs-<dataset>-<namespace>` — Elastic's data-stream naming, which is
    also what the index template matches on."""
    logs = contract["logs"]
    return f"logs-{logs['datasets'][dataset_key]}-{logs['namespace']}"


# --------------------------------------------------------------------------- #
# pure: rendering the cluster's configuration OUT of the contract
# --------------------------------------------------------------------------- #
def ilm_policy_for(dataset_key: str, contract: dict) -> dict:
    """The lifecycle policy for one dataset.

    Retention is expressed once, in _data/fleet.yml. Rendering it rather than
    committing a hand-written policy is what stops the two from drifting — and
    a drifted delete phase on a laptop ends as a cluster wedged read-only at
    the flood watermark, which fails silently until the next write.
    """
    logs = contract["logs"]
    roll = logs["rollover"]
    return {
        "policy": {
            "phases": {
                "hot": {
                    "min_age": "0ms",
                    "actions": {
                        "rollover": {
                            "max_primary_shard_size": roll["max_primary_shard_size"],
                            "max_age": roll["max_age"],
                        }
                    },
                },
                "delete": {
                    "min_age": f"{logs['retention_days'][dataset_key]}d",
                    "actions": {"delete": {}},
                },
            }
        }
    }


def ilm_policy_name(dataset_key: str, contract: dict) -> str:
    return f"{contract['logs']['datasets'][dataset_key]}-logs"


# Claude Code event attributes that are numbers (monitoring-usage reference),
# as named after 20-otlp-in.conf flattens them.
CLAUDE_DOUBLE_FIELDS = ("cost_usd",)
CLAUDE_LONG_FIELDS = (
    "cost_usd_micros", "duration_ms", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_creation_tokens", "prompt_length", "response_length", "attempt", "status_code",
    "tool_input_size_bytes", "tool_result_size_bytes", "event_sequence", "total_tokens",
    "total_tool_uses",
)


def index_template_for(dataset_key: str, contract: dict) -> dict:
    """Mapping + settings for one dataset's data stream.

    Fields are ECS where ECS has them and `fleet.*` where it does not. The
    fleet block is what makes a repo a filter rather than an index: one dataset
    per SOURCE and the repo as a keyword beats 40 repos x 3 sources of data
    streams to template, alias and expire.
    """
    logs = contract["logs"]
    dataset = logs["datasets"][dataset_key]
    props = {
        "@timestamp": {"type": "date"},
        "message": {"type": "match_only_text"},
        "ecs": {"properties": {"version": {"type": "keyword"}}},
        "log": {"properties": {"level": {"type": "keyword"},
                               "logger": {"type": "keyword"}}},
        "event": {"properties": {"dataset": {"type": "keyword"},
                                 "module": {"type": "keyword"}}},
        "service": {"properties": {"name": {"type": "keyword"},
                                   "version": {"type": "keyword"}}},
        "fleet": {"properties": {"repo": {"type": "keyword"},
                                 "project": {"type": "keyword"},
                                 "category": {"type": "keyword"},
                                 "stack": {"type": "keyword"}}},
        "trace": {"properties": {"id": {"type": "keyword"},
                                 "request_id": {"type": "keyword"}}},
        "url": {"properties": {"full": {"type": "keyword", "index": False}}},
        "host": {"properties": {"name": {"type": "keyword"}}},
    }
    if dataset_key == "actions":
        props["ci"] = {"properties": {
            "run_id": {"type": "long"}, "run_attempt": {"type": "integer"},
            "run_number": {"type": "long"},
            "workflow": {"type": "keyword"}, "workflow_path": {"type": "keyword"},
            "job": {"type": "keyword"}, "step": {"type": "keyword"},
            "conclusion": {"type": "keyword"}, "status": {"type": "keyword"},
            "event": {"type": "keyword"}, "branch": {"type": "keyword"},
            "sha": {"type": "keyword"},
        }}
        props["llm"] = {"properties": {
            "model": {"type": "keyword"}, "cost_usd": {"type": "double"},
            "turns": {"type": "integer"}, "session_id": {"type": "keyword"},
        }}
    elif dataset_key == "claude":
        # Claude Code's OTel events, flattened by logstash/pipeline/20-otlp-in.conf
        # into claude.<attribute> with dots as underscores. The numbers are
        # declared so a first event that happens to carry an integer cost (0)
        # cannot map cost_usd as long and truncate every later one; every
        # other attribute is a keyword through the dynamic template below.
        props["event"]["properties"].update({"action": {"type": "keyword"},
                                             "kind": {"type": "keyword"}})
        props["span"] = {"properties": {"id": {"type": "keyword"}}}
        props["user"] = {"properties": {"email": {"type": "keyword"}, "id": {"type": "keyword"}}}
        props["host"]["properties"].update({"architecture": {"type": "keyword"},
                                            "os": {"properties": {"type": {"type": "keyword"}}}})
        nums = {k: {"type": "double"} for k in CLAUDE_DOUBLE_FIELDS}
        nums.update({k: {"type": "long"} for k in CLAUDE_LONG_FIELDS})
        props["claude"] = {"properties": nums}
    else:
        props["container"] = {"properties": {
            "id": {"type": "keyword"}, "name": {"type": "keyword"},
            "image": {"properties": {"name": {"type": "keyword"}}},
        }}
    mappings = {"properties": props}
    if dataset_key == "claude":
        mappings["dynamic_templates"] = [{"claude_strings": {
            "path_match": "claude.*", "match_mapping_type": "string",
            # keyword, not text: these are names, ids and enums to filter and
            # aggregate on. ignore_above: a keyword term over Lucene's 32766-byte
            # limit REJECTS the whole document, and a full Bash command or
            # tool_input can exceed it — past the cap the value is kept in
            # _source and simply not indexed.
            "mapping": {"type": "keyword", "ignore_above": 8191}}}]
    return {
        "index_patterns": [f"logs-{dataset}-*"],
        "data_stream": {},
        "priority": 500,
        "template": {
            "settings": {
                "index.lifecycle.name": ilm_policy_name(dataset_key, contract),
                "index.number_of_replicas": 0,   # single node: a replica can never allocate
                "index.number_of_shards": 1,
            },
            "mappings": mappings,
        },
        "_meta": {
            "managed_by": "tools/dash observe",
            "contract": "_data/fleet.yml observability.logs",
            "doc": "docs/OBSERVABILITY.md",
        },
    }


def index_template_name(dataset_key: str, contract: dict) -> str:
    return f"{contract['logs']['datasets'][dataset_key]}-logs"


def render_all(contract: dict) -> tuple[dict, dict]:
    """Every ILM policy and index template the contract implies, keyed by name."""
    keys = sorted(contract["logs"]["datasets"])
    policies = {ilm_policy_name(k, contract): ilm_policy_for(k, contract) for k in keys}
    templates = {index_template_name(k, contract): index_template_for(k, contract) for k in keys}
    return policies, templates


# --------------------------------------------------------------------------- #
# pure: rendering the DASHBOARDS out of the contract
#
# Ids are pinned, not minted at import. Kibana and Grafana will both happily
# generate a fresh id every time a saved object is imported, and the console's
# embed URLs reference them by id — so a generated id means every re-import
# silently re-points the Observe tab at nothing, with a blank iframe and no
# error in any log. `dash observe verify` resolves every pinned id against
# these files, which is the check that catches it.
# --------------------------------------------------------------------------- #
DATA_VIEW_IDS = {"actions": "fleet-actions", "container": "fleet-container", "app": "fleet-app",
                 "claude": "fleet-claude"}
GRAFANA_DS_UID = "fleet-elasticsearch"
GRAFANA_PROM_UID = "fleet-prometheus"


def kibana_saved_objects(contract: dict) -> list[dict]:
    """Data views, saved searches and the three dashboards, in import order.

    Deliberately built from the long-stable saved-object shapes (index-pattern,
    search, dashboard) rather than by-value Lens panels: these survive a Kibana
    major far better, and a log plane's job is search, not bespoke charting —
    that is what the Grafana half is for.
    """
    logs = contract["logs"]
    objs: list[dict] = []

    for key in sorted(logs["datasets"]):
        objs.append({
            "id": DATA_VIEW_IDS[key],
            "type": "index-pattern",
            "attributes": {"title": f"logs-{logs['datasets'][key]}-*", "timeFieldName": "@timestamp"},
            "references": [],
        })

    def search(sid: str, title: str, view: str, columns: list[str], query: str) -> dict:
        return {
            "id": sid,
            "type": "search",
            "attributes": {
                "title": title,
                "columns": columns,
                "sort": [["@timestamp", "desc"]],
                "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({
                    "query": {"query": query, "language": "kuery"},
                    "filter": [],
                    "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index",
                })},
            },
            "references": [{
                "id": view, "name": "kibanaSavedObjectMeta.searchSourceJSON.index",
                "type": "index-pattern",
            }],
        }

    searches = [
        search("fleet-ci-failures", "CI — failing steps", DATA_VIEW_IDS["actions"],
               ["fleet.repo", "ci.workflow", "ci.job", "ci.step", "message"],
               'ci.conclusion : "failure" or log.level : "error"'),
        search("fleet-agents-runs", "Agents — model, cost and the log text", DATA_VIEW_IDS["actions"],
               ["fleet.repo", "llm.model", "llm.cost_usd", "llm.turns", "trace.id", "message"],
               "llm.model : *"),
        search("fleet-local-errors", "Local stack — errors by service", DATA_VIEW_IDS["container"],
               ["fleet.project", "container.name", "log.level", "message"],
               'log.level : "error" or log.level : "warn"'),
        search("fleet-app-requests", "App — structured request lines", DATA_VIEW_IDS["app"],
               ["service.name", "log.level", "trace.request_id", "message"], "*"),
        # Claude Code's own events. claude.prompt_id ties every event of one
        # prompt together; trace.id is the same id as the span in Phoenix.
        search("claude-requests", "Claude Code — API requests, cost and tokens", DATA_VIEW_IDS["claude"],
               ["claude.session_id", "claude.model", "claude.query_source", "claude.cost_usd",
                "claude.input_tokens", "claude.cache_read_tokens", "claude.output_tokens",
                "claude.duration_ms", "trace.id"],
               'event.action : "api_request"'),
        search("claude-tools", "Claude Code — tool calls, decisions and failures", DATA_VIEW_IDS["claude"],
               ["event.action", "claude.tool_name", "claude.success", "claude.decision",
                "claude.source", "claude.duration_ms", "claude.error", "claude.tool_parameters"],
               'event.action : ("tool_result" or "tool_decision") or log.level : ("error" or "warn")'),
    ]
    objs.extend(searches)

    def dashboard(did: str, title: str, description: str, panels: list[str]) -> dict:
        panels_json, refs = [], []
        for i, sid in enumerate(panels):
            # The reference NAME must equal panelRefName exactly. Kibana's
            # injectReferences looks the panelRefName up verbatim, and the
            # `<panelIndex>:` prefix seen in Kibana's own exports only works
            # when the prefix matches that panel's panelIndex. Getting those
            # two out of step is a 500 on import — "Could not find reference
            # panel_0" — with the dashboard silently absent afterwards. Bare
            # names cannot drift apart, so they are what this writes.
            name = f"panel_{i}"
            panels_json.append({
                "version": "8.11.0", "type": "search", "panelIndex": str(i + 1),
                "gridData": {"x": 0, "y": i * 15, "w": 48, "h": 15, "i": str(i + 1)},
                "embeddableConfig": {}, "panelRefName": name,
            })
            refs.append({"id": sid, "name": name, "type": "search"})
        return {
            "id": did,
            "type": "dashboard",
            "attributes": {
                "title": title,
                "description": description,
                "panelsJSON": json.dumps(panels_json),
                "optionsJSON": json.dumps({"hidePanelTitles": False, "useMargins": True}),
                "timeRestore": True,
                "timeFrom": "now-7d", "timeTo": "now",
                "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
                    {"query": {"query": "", "language": "kuery"}, "filter": []})},
            },
            "references": refs,
        }

    portal = (contract.get("portal") or {}).get("dashboards") or {}
    objs.append(dashboard(
        (portal.get("logs") or {}).get("id") or "fleet-ci",
        (portal.get("logs") or {}).get("title") or "Fleet CI",
        "Failing steps across the fleet and the agent runs behind them — the log text "
        "the committed _data/fleet_triage.yml snapshot only counts.",
        ["fleet-ci-failures", "fleet-agents-runs"]))
    objs.append(dashboard(
        "fleet-local", "Local stack",
        "Container and application logs from this machine's compose services.",
        ["fleet-local-errors", "fleet-app-requests"]))
    objs.append(dashboard(
        "claude-code", "Claude Code",
        "This machine's Claude Code sessions, from their native OpenTelemetry events: every API "
        "request with its cost and tokens, every tool call and permission decision. Live counters "
        "are in Grafana; the span tree of each prompt is in Phoenix (project claude-code-otel).",
        ["claude-requests", "claude-tools"]))
    return objs


def grafana_dashboard(contract: dict) -> dict:
    """The trends half: rates and spend over the same indices Kibana searches.

    Grafana answers "how much, over time" and Kibana answers "what exactly did
    it say" — which is why both exist rather than one of them.
    """
    portal = (contract.get("portal") or {}).get("dashboards") or {}
    meta = portal.get("metrics") or {}
    logs = contract["logs"]
    ds = {"type": "elasticsearch", "uid": GRAFANA_DS_UID}

    def target(query: str, alias: str, metric: dict, group: list[dict], ref: str) -> dict:
        return {"refId": ref, "datasource": ds, "query": query, "alias": alias,
                "metrics": [metric], "bucketAggs": group, "timeField": "@timestamp"}

    date_hist = {"id": "2", "type": "date_histogram", "field": "@timestamp",
                 "settings": {"interval": "auto", "min_doc_count": "0"}}
    by_repo = {"id": "3", "type": "terms", "field": "fleet.repo",
               "settings": {"size": "10", "order": "desc", "orderBy": "_count"}}

    panels = [
        {"id": 1, "type": "timeseries", "title": "Log volume by repo",
         "description": "Documents/interval across every dataset — the shape of what the fleet is saying.",
         "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0}, "datasource": ds,
         "targets": [target("*", "{{fleet.repo}}", {"id": "1", "type": "count"},
                            [by_repo, date_hist], "A")]},
        {"id": 2, "type": "timeseries", "title": "Errors and warnings",
         "description": "log.level is inferred for unstructured lines too, so this covers all three datasets.",
         "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0}, "datasource": ds,
         "targets": [target('log.level:("error" OR "warn")', "{{log.level}}",
                            {"id": "1", "type": "count"},
                            [{"id": "3", "type": "terms", "field": "log.level",
                              "settings": {"size": "5", "order": "desc", "orderBy": "_count"}},
                             date_hist], "A")]},
        {"id": 3, "type": "timeseries", "title": "Agent spend by model (USD)",
         "description": "Summed from the one summary document per AI run — the per-line documents "
                        "carry the same fields and would multiply the total by line count.",
         "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8}, "datasource": ds,
         "targets": [target('event.module:"claude.agent"', "{{llm.model}}",
                            {"id": "1", "type": "sum", "field": "llm.cost_usd"},
                            [{"id": "3", "type": "terms", "field": "llm.model",
                              "settings": {"size": "10", "order": "desc", "orderBy": "_count"}},
                             date_hist], "A")]},
        {"id": 4, "type": "timeseries", "title": "CI failures by workflow",
         "description": "The same signal fleet_triage.yml ranks, but continuous.",
         "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8}, "datasource": ds,
         "targets": [target('ci.conclusion:"failure"', "{{ci.workflow}}",
                            {"id": "1", "type": "count"},
                            [{"id": "3", "type": "terms", "field": "ci.workflow",
                              "settings": {"size": "10", "order": "desc", "orderBy": "_count"}},
                             date_hist], "A")]},
    ]
    if "prometheus" in ((contract.get("metrics") or {}).get("datasources") or []):
        # Live counters FIRST: they are the only panels that move while you
        # watch, and the console embeds this dashboard in a fixed-height pane,
        # so whatever sits below the fold is effectively not on the page.
        live = claude_prometheus_panels(y=0)
        height = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in live)
        for p in panels:
            p["gridPos"]["y"] += height
        panels = live + [{"id": 9, "type": "row", "title": "Fleet log plane (Elasticsearch)",
                          "gridPos": {"h": 1, "w": 24, "x": 0, "y": height}, "collapsed": False,
                          "panels": []}] + [dict(p, gridPos=dict(p["gridPos"], y=p["gridPos"]["y"] + 1))
                                            for p in panels]
    return {
        "uid": meta.get("uid") or "fleet-logs",
        "title": meta.get("title") or "Fleet log volume & cost",
        "description": (
            f"Trends over the fleet log plane (retention: "
            f"{', '.join(f'{k} {v}d' for k, v in sorted(logs['retention_days'].items()))}). "
            "GENERATED by `dash observe verify --write` from _data/fleet.yml — edit the contract, "
            "not this file. Search the same data in Kibana; per-run traces are in Phoenix."),
        "tags": ["fleet", "logs", "generated"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "1m",
        "time": {"from": "now-7d", "to": "now"},
        "panels": panels,
    }


def claude_prometheus_panels(y: int) -> list[dict]:
    """Live Claude Code counters, from Prometheus (FF-0003).

    Metric names are what the collector's prometheus exporter produces from
    Claude Code's OTel names: claude_code.cost.usage (unit USD) becomes
    claude_code_cost_usage_USD_total, and so on. Every series is one SESSION
    (contract: attributes.session_id), so totals are sum(increase(...)).
    Two Prometheus features make that exact, and both are on in
    docker-compose.yml: created-timestamp-zero-ingestion gives each session's
    counter a zero to start from (without it a short session's whole spend
    vanished), and `anchored` range selectors stop increase()/rate() from
    extrapolating past the first and last samples — which, over a session's
    handful of samples, read two $0.065/$0.078 sessions as +15% and +68%.

    Dollar figures are Claude Code's own estimate, not an invoice — the same
    caveat as every other spend number on this bench.
    """
    ds = {"type": "prometheus", "uid": GRAFANA_PROM_UID}
    cost = "claude_code_cost_usage_USD_total"
    tokens = "claude_code_token_usage_tokens_total"

    def q(expr: str, legend: str, ref: str = "A", instant: bool = False) -> dict:
        return {"refId": ref, "datasource": ds, "expr": expr, "legendFormat": legend,
                "instant": instant, "range": not instant}

    def stat(pid: int, title: str, desc: str, expr: str, x: int, unit: str, decimals: int = 2) -> dict:
        return {"id": pid, "type": "stat", "title": title, "description": desc,
                "gridPos": {"h": 4, "w": 6, "x": x, "y": y}, "datasource": ds,
                "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals}, "overrides": []},
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "none",
                            "graphMode": "none"},
                "targets": [q(expr, "", instant=True)]}

    return [
        {"id": 10, "type": "row", "title": "Claude Code — live (Prometheus, from native OTel)",
         "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "collapsed": False, "panels": []},
        stat(11, "API-equivalent in range (estimate, not billed)",
             "Claude Code's own cost estimate (tokens at API list prices) across every session in the range. "
             "Emitted under subscription logins too: an API-equivalent value, not a bill — the bill is the "
             "flat Claude subscription (harnesses.budget.monthly_ai_usd).",
             f"sum(increase({cost}[$__range] anchored))", 0, "currencyUSD"),
        stat(12, "Cache read share", "Share of prompt tokens served from the prompt cache. "
             "Low means context is being re-sent rather than reused.",
             f'sum(increase({tokens}{{type="cacheRead"}}[$__range] anchored)) / '
             f'sum(increase({tokens}{{type=~"input|cacheRead|cacheCreation"}}[$__range] anchored))',
             6, "percentunit", 1),
        stat(13, "Sessions started", "claude_code.session.count — fresh, resumed and continued.",
             "sum(increase(claude_code_session_count_total[$__range] anchored))", 12, "none", 0),
        stat(14, "Active time", "Keyboard time plus tool/model time (claude_code.active_time.total).",
             "sum(increase(claude_code_active_time_seconds_total[$__range] anchored))", 18, "s", 0),
        {"id": 15, "type": "timeseries", "title": "API-equivalent burn rate by model (USD/hour, estimate)",
         "description": "How fast API-equivalent value is accruing right now, per model (list-price estimate, not billed).",
         "gridPos": {"h": 8, "w": 12, "x": 0, "y": y + 4}, "datasource": ds,
         "fieldConfig": {"defaults": {"unit": "currencyUSD"}, "overrides": []},
         "targets": [q(f"sum by (model) (rate({cost}[$__rate_interval] anchored)) * 3600", "{{model}}")]},
        {"id": 16, "type": "timeseries", "title": "Tokens by type",
         "description": "input excludes the cache; cacheRead and cacheCreation are the cache's two sides.",
         "gridPos": {"h": 8, "w": 12, "x": 12, "y": y + 4}, "datasource": ds,
         "targets": [q(f"sum by (type) (increase({tokens}[$__rate_interval] anchored))", "{{type}}")]},
        {"id": 17, "type": "bargauge", "title": "API-equivalent by source in range",
         "description": "query_source: main (the conversation), subagent, auxiliary (titles, "
                        "summaries), sdk (headless runs).",
         "gridPos": {"h": 8, "w": 12, "x": 0, "y": y + 12}, "datasource": ds,
         "fieldConfig": {"defaults": {"unit": "currencyUSD"}, "overrides": []},
         "options": {"orientation": "horizontal", "reduceOptions": {"calcs": ["lastNotNull"]}},
         "targets": [q(f"sum by (query_source) (increase({cost}[$__range] anchored))", "{{query_source}}",
                       instant=True)]},
        {"id": 18, "type": "bargauge", "title": "API-equivalent by repository in range",
         "description": "vcs.repository.name — needs Claude Code ≥ 2.1.269 with "
                        "OTEL_METRICS_INCLUDE_REPOSITORY (contract: attributes.repository). "
                        "Empty on older versions.",
         "gridPos": {"h": 8, "w": 12, "x": 12, "y": y + 12}, "datasource": ds,
         "fieldConfig": {"defaults": {"unit": "currencyUSD"}, "overrides": []},
         "options": {"orientation": "horizontal", "reduceOptions": {"calcs": ["lastNotNull"]}},
         "targets": [q(f"sum by (vcs_repository_name) (increase({cost}[$__range] anchored))",
                       "{{vcs_repository_name}}", instant=True)]},
    ]


# --------------------------------------------------------------------------- #
# pure: the CLIENT side — Claude Code's own telemetry settings
# --------------------------------------------------------------------------- #
# Every key `dash observe claude enable` may write. `disable` removes exactly
# these and nothing else, so a variable the operator set by hand for some other
# reason is never touched unless it is one of ours.
CLAUDE_ENV_KEYS = (
    "CLAUDE_CODE_ENABLE_TELEMETRY", "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA",
    "OTEL_METRICS_EXPORTER", "OTEL_LOGS_EXPORTER", "OTEL_TRACES_EXPORTER",
    "OTEL_EXPORTER_OTLP_PROTOCOL", "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE",
    "OTEL_METRIC_EXPORT_INTERVAL", "OTEL_LOGS_EXPORT_INTERVAL", "OTEL_TRACES_EXPORT_INTERVAL",
    "OTEL_METRICS_INCLUDE_SESSION_ID", "OTEL_METRICS_INCLUDE_VERSION",
    "OTEL_METRICS_INCLUDE_ENTRYPOINT", "OTEL_METRICS_INCLUDE_REPOSITORY",
    "OTEL_LOG_USER_PROMPTS", "OTEL_LOG_ASSISTANT_RESPONSES", "OTEL_LOG_TOOL_DETAILS",
    "OTEL_LOG_TOOL_CONTENT", "OTEL_LOG_RAW_API_BODIES",
)

DEFAULT_CLAUDE = {
    "endpoint": "http://127.0.0.1:4318", "protocol": "http/protobuf",
    "signals": {"metrics": True, "logs": True, "traces": True}, "traces_beta": True,
    "export_interval_ms": {"metrics": 30000, "logs": 5000, "traces": 5000},
    "temporality": "cumulative",
    "attributes": {"session_id": True, "version": True, "entrypoint": True, "repository": True},
    "content": {"user_prompts": False, "assistant_responses": False, "tool_details": True,
                "tool_content": False, "raw_api_bodies": False},
    "phoenix_project": "claude-code-otel", "settings": "~/.claude/settings.json",
}


def claude_contract(contract: dict) -> dict:
    """`observability.claude_code`, with DEFAULT_CLAUDE behind every key."""
    raw = contract.get("claude_code") or {}
    out = dict(DEFAULT_CLAUDE)
    out.update(raw)
    for key in ("signals", "export_interval_ms", "attributes", "content"):
        merged = dict(DEFAULT_CLAUDE[key])
        merged.update(raw.get(key) or {})
        out[key] = merged
    return out


def claude_env(contract: dict) -> dict[str, str]:
    """The `env` block that points this machine's Claude Code at the collector.

    Values are strings because settings.json `env` is a string map. A content
    gate that is off is written as "0"/absent rather than left to inherit, so
    the contract — not whatever the shell happens to export — decides.
    """
    c = claude_contract(contract)
    sig, iv, attrs, content = c["signals"], c["export_interval_ms"], c["attributes"], c["content"]
    on = lambda b: "1" if b else "0"            # noqa: E731
    flag = lambda b: "true" if b else "false"   # noqa: E731
    env = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp" if sig.get("metrics") else "none",
        "OTEL_LOGS_EXPORTER": "otlp" if sig.get("logs") else "none",
        "OTEL_EXPORTER_OTLP_PROTOCOL": str(c["protocol"]),
        "OTEL_EXPORTER_OTLP_ENDPOINT": str(c["endpoint"]).rstrip("/"),
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": str(c["temporality"]),
        "OTEL_METRIC_EXPORT_INTERVAL": str(iv["metrics"]),
        "OTEL_LOGS_EXPORT_INTERVAL": str(iv["logs"]),
        "OTEL_METRICS_INCLUDE_SESSION_ID": flag(attrs.get("session_id")),
        "OTEL_METRICS_INCLUDE_VERSION": flag(attrs.get("version")),
        "OTEL_METRICS_INCLUDE_ENTRYPOINT": flag(attrs.get("entrypoint")),
        "OTEL_METRICS_INCLUDE_REPOSITORY": flag(attrs.get("repository")),
        "OTEL_LOG_USER_PROMPTS": on(content.get("user_prompts")),
        "OTEL_LOG_ASSISTANT_RESPONSES": on(content.get("assistant_responses")),
        "OTEL_LOG_TOOL_DETAILS": on(content.get("tool_details")),
    }
    if sig.get("traces") and c.get("traces_beta"):
        env.update({
            "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_TRACES_EXPORT_INTERVAL": str(iv["traces"]),
            "OTEL_LOG_TOOL_CONTENT": on(content.get("tool_content")),
        })
    if content.get("raw_api_bodies"):
        env["OTEL_LOG_RAW_API_BODIES"] = "1"
    assert set(env) <= set(CLAUDE_ENV_KEYS), set(env) - set(CLAUDE_ENV_KEYS)
    return env


def merge_claude_env(settings: dict, env: dict[str, str] | None) -> dict:
    """settings.json with our keys set (env given) or removed (env None).

    Only CLAUDE_ENV_KEYS are touched; every other setting and every other env
    variable survives byte-for-byte in value.
    """
    out = dict(settings)
    block = {k: v for k, v in dict(out.get("env") or {}).items() if k not in CLAUDE_ENV_KEYS}
    if env:
        block.update(env)
    if block:
        out["env"] = block
    else:
        out.pop("env", None)
    return out


# --------------------------------------------------------------------------- #
# pure: mapping a log line to a document
# --------------------------------------------------------------------------- #
def redact(text: str) -> str:
    """Mask every credential shape in `observability.logs.redact`.

    GitHub masks secrets in its own logs; nothing masks a local container's,
    and nothing masks a --dry-run preview written to disk. This is the guard
    for both.
    """
    if not text:
        return text
    for rx, repl in REDACTIONS:
        text = rx.sub(repl, text)
    return text


def level_of(line: str) -> str:
    """Infer a level so "show me errors" works across all three datasets, not
    just the one that happens to emit JSON."""
    m = LEVEL_RX.search(line or "")
    if not m:
        return "info"
    lvl = m.group(1).lower()
    return "warn" if lvl == "warning" else lvl


def dataset_for(line: str) -> str:
    """Which dataset a container line belongs to.

    A UPS-OPS-10 line is JSON carrying both `level` and `msg`; anything else is
    raw chatter. They get different datasets and therefore different retention,
    so the difference stays visible instead of being averaged into one index.
    """
    s = (line or "").strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            doc = json.loads(s)
        except (ValueError, TypeError):
            return "container"
        if isinstance(doc, dict) and "level" in doc and ("msg" in doc or "message" in doc):
            return "app"
    return "container"


def _entry_step(entry: str) -> tuple[str | None, str | None]:
    """Split a log-zip entry name into (job, step).

    GitHub names them `<job>/<n>_<step>.txt` for per-step files and
    `<n>_<job>.txt` for the per-job roll-up.
    """
    name = entry[:-4] if entry.endswith(".txt") else entry
    if "/" in name:
        job, _, step = name.partition("/")
        return job, re.sub(r"^\d+_", "", step)
    return re.sub(r"^\d+_", "", name), None


def ecs_from_log_entry(entry: str, text: str, run: dict, contract: dict,
                       agent: dict | None = None, project: dict | None = None) -> list[dict]:
    """One Actions log-zip entry -> one ECS document per line.

    Timestamps come from fleet_lake's own splitter, so a line's @timestamp is
    the instant GitHub recorded rather than the instant we shipped it.
    """
    body, offsets = fleet_lake._split_log(text)
    if not body.strip():
        return []
    job, step = _entry_step(entry)
    run_key = f"run:{run.get('nwo')}:{run.get('id')}:{run.get('run_attempt') or 1}"
    base = {
        "ecs": {"version": ECS_VERSION},
        "event": {"dataset": contract["logs"]["datasets"]["actions"], "module": "github.actions"},
        "service": {"name": (project or {}).get("name") or run.get("nwo")},
        "fleet": {
            "repo": run.get("nwo"),
            "project": (project or {}).get("name"),
            "category": (project or {}).get("category"),
        },
        "ci": {
            "run_id": run.get("id"),
            "run_attempt": run.get("run_attempt") or 1,
            "run_number": run.get("run_number"),
            "workflow": run.get("workflow_name"),
            "workflow_path": run.get("workflow_path"),
            "job": job,
            "step": step,
            "conclusion": run.get("conclusion"),
            "status": run.get("status"),
            "event": run.get("event"),
            "branch": run.get("head_branch"),
            "sha": run.get("head_sha"),
        },
        "url": {"full": run.get("html_url")},
        # THE JOIN: identical to what fleet_lake's exporter stamps on the
        # Phoenix trace for this same run.
        "trace": {"id": fleet_lake.hex_trace(fleet_lake.trace_id_for(run_key))},
    }
    if agent:
        base["llm"] = {
            "model": agent.get("model"),
            "cost_usd": agent.get("cost_usd"),
            "turns": agent.get("num_turns"),
            "session_id": agent.get("session_id"),
        }
    fallback = run.get("run_started_at") or run.get("created_at")
    docs: list[dict] = []
    for i, line in enumerate(body.split("\n")):
        if not line.strip():
            continue
        # Shallow copy, not a json round-trip: only the three keys below differ
        # per line, and the nested blocks are never mutated after this — so
        # sharing them is safe and serializes identically. On "ship everything"
        # this runs once per log line across the whole fleet, which is where a
        # per-line deep copy stops being free.
        doc = dict(base)
        stamp = fleet_lake._stamp_at(offsets, offsets[i][0]) if i < len(offsets) else None
        doc["@timestamp"] = stamp or fallback
        doc["message"] = redact(line)
        doc["log"] = {"level": level_of(line)}
        docs.append(doc)
    return docs


def ecs_from_agent_run(agent: dict, run: dict, contract: dict,
                       project: dict | None = None) -> dict:
    """One summary document per AI run.

    The per-line documents above carry the same llm.* fields, but they carry
    them on every line — this is the single row a cost aggregation should sum,
    so Grafana can chart spend without dividing by line count.
    """
    run_key = f"run:{run.get('nwo')}:{run.get('id')}:{run.get('run_attempt') or 1}"
    return {
        "@timestamp": agent.get("ended_at") or run.get("updated_at") or run.get("created_at"),
        "ecs": {"version": ECS_VERSION},
        "event": {"dataset": contract["logs"]["datasets"]["actions"], "module": "claude.agent"},
        "message": redact(
            f"agent run {agent.get('model') or 'unknown'} "
            f"turns={agent.get('num_turns')} cost={agent.get('cost_usd')}"),
        "log": {"level": "error" if agent.get("is_error") else "info"},
        "service": {"name": (project or {}).get("name") or run.get("nwo")},
        "fleet": {"repo": run.get("nwo"), "project": (project or {}).get("name"),
                  "category": (project or {}).get("category")},
        "ci": {"run_id": run.get("id"), "run_attempt": run.get("run_attempt") or 1,
               "workflow": run.get("workflow_name"), "conclusion": run.get("conclusion")},
        "llm": {"model": agent.get("model"), "cost_usd": agent.get("cost_usd"),
                "turns": agent.get("num_turns"), "session_id": agent.get("session_id")},
        "url": {"full": run.get("html_url")},
        "trace": {"id": fleet_lake.hex_trace(fleet_lake.trace_id_for(run_key))},
    }


# --------------------------------------------------------------------------- #
# i/o helpers
# --------------------------------------------------------------------------- #
def _get_json(url: str, timeout: int = 10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as fh:   # noqa: S310 (loopback only)
            return json.loads(fh.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _query_json(url: str, payload, timeout: int = 10):
    """POST a read query (an Elasticsearch _search) and return its body, or None."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:   # noqa: S310 (loopback only)
            return json.loads(fh.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _post_json(url: str, payload, timeout: int = 60) -> tuple[bool, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:   # noqa: S310 (loopback only)
            return 200 <= fh.status < 300, ""
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, str(exc)


# The contract's URLs are what a BROWSER must use — they are also the embed URLs
# and the links the console renders. A server-side probe needs a different
# address whenever the prober is itself in a container, where 127.0.0.1 is the
# container's own loopback and nothing is listening on it. docker-compose.yml
# already makes exactly this distinction for Phoenix (PHOENIX_COLLECTOR_ENDPOINT
# is service DNS, PHOENIX_UI_URL is loopback); these are the same split for the
# other two planes, and compose sets them on the services that do the probing.
PROBE_ENV = {"elasticsearch": "ES_URL", "kibana": "KIBANA_URL",
             "grafana": "GRAFANA_URL", "phoenix": "PHOENIX_COLLECTOR_ENDPOINT",
             "qdrant": "QDRANT_URL", "ollama": "OLLAMA_URL",
             "prometheus": "PROMETHEUS_URL", "otel-collector": "OTEL_COLLECTOR_URL"}

_GITMODULES_PATH = re.compile(r"^\s*path\s*=\s*(\S+)\s*$", re.M)


def probe_url(service: str, browser_url: str) -> str:
    """Where to REACH a service from this process, which is not always where a
    browser would reach it."""
    return (os.environ.get(PROBE_ENV.get(service, "")) or "").rstrip("/") or browser_url


def reachable(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as fh:         # noqa: S310 (loopback only)
            return fh.status < 500
    except Exception:
        return False


def registry_index(path: Path | str | None = None) -> dict:
    """nwo -> registry row, for attributing a log line to a project."""
    p = Path(path) if path else REGISTRY_DEFAULT
    try:
        rows = yaml.safe_load(p.read_text()) or []
    except OSError:
        return {}
    out = {}
    for row in rows:
        url = (row.get("repo_url") or "").rstrip("/")
        if "github.com/" in url:
            out[url.split("github.com/", 1)[1]] = row
    return out


def submodule_paths(root: Path | str | None = None) -> list[str]:
    """Paths declared in .gitmodules. The indexer's scope, not a second workspace."""
    path = Path(root or REPO_ROOT) / ".gitmodules"
    try:
        text = path.read_text()
    except OSError:
        return []
    return _GITMODULES_PATH.findall(text)


def submodule_coverage(root: Path | str | None = None) -> dict:
    """Which submodule working trees the workspace scan can actually see.

    Kilo's scanner walks the worktree and skips a path segment named `.git`,
    not the tree beside it. A checked-out submodule is therefore in the same
    index as the hub. An uninitialized one is an empty directory and is not.
    """
    root = Path(root or REPO_ROOT)
    declared = submodule_paths(root)
    empty = []
    checked = 0
    for rel in declared:
        path = root / rel
        if not path.is_dir():
            empty.append(rel)
            continue
        try:
            populated = any(child.name != ".git" for child in path.iterdir())
        except OSError:
            empty.append(rel)
            continue
        if populated:
            checked += 1
        else:
            empty.append(rel)
    return {"declared": len(declared), "checked_out": checked, "empty": empty}


def kilo_index_config(root: Path | str | None = None) -> dict:
    """The `indexing` object Kilo reads. Strict JSON so a comment cannot hide a drift."""
    path = Path(root or REPO_ROOT) / "kilo.jsonc"
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    indexing = doc.get("indexing")
    return indexing if isinstance(indexing, dict) else {}


def _qdrant_collections(base: str) -> list[dict] | None:
    """Point counts per collection. None means the store did not answer."""
    listed = _get_json(f"{base}/collections")
    if not listed:
        return None
    names = [c.get("name") for c in ((listed.get("result") or {}).get("collections") or [])
             if c.get("name")]
    out = []
    for name in names:
        detail = _get_json(f"{base}/collections/{name}") or {}
        result = detail.get("result") or {}
        out.append({"name": name, "points": result.get("points_count"),
                    "status": result.get("status")})
    return out


def plane_status(contract: dict) -> dict:
    """Per-plane reachability + identity. Never raises: a plane that is down is
    a document saying so, which is what lets the console render a Start button
    instead of a 500."""
    logs, metrics, traces = contract["logs"], contract.get("metrics") or {}, contract.get("traces") or {}
    indexing = contract.get("indexing") or {}
    es_url, kibana_url = logs["elasticsearch"], logs["kibana"]
    grafana_url = metrics.get("grafana") or ""
    phoenix_url = traces.get("endpoint") or ""
    qdrant_url = indexing.get("qdrant") or ""
    embedder_url = indexing.get("embedder") or ""
    # Probe one address, report the other: `url` is what the browser gets.
    es_probe = probe_url("elasticsearch", es_url)
    health = _get_json(f"{es_probe}/_cluster/health")
    qdrant_probe = probe_url("qdrant", qdrant_url) if qdrant_url else ""
    collections = _qdrant_collections(qdrant_probe) if qdrant_probe else None
    embedder_probe = probe_url("ollama", embedder_url) if embedder_url else ""
    return {
        "logs": {
            "engine": logs.get("engine", "elastic"),
            "url": kibana_url,
            "elasticsearch": es_url,
            "reachable": health is not None,
            "cluster_status": (health or {}).get("status"),
            "kibana_reachable": reachable(f"{probe_url('kibana', kibana_url)}/api/status"),
        },
        "metrics": {
            "engine": metrics.get("engine", "grafana"),
            "url": grafana_url,
            "reachable": reachable(f"{probe_url('grafana', grafana_url)}/api/health") if grafana_url else False,
            "datasources": metrics.get("datasources") or [],
        },
        "traces": {
            "engine": traces.get("engine", "phoenix"),
            "url": phoenix_url,
            "reachable": reachable(probe_url("phoenix", phoenix_url)) if phoenix_url else False,
        },
        "telemetry": telemetry_status(contract),
        "indexing": {
            "engine": indexing.get("engine", "qdrant"),
            "url": qdrant_url,
            "embedder": embedder_url,
            "provider": indexing.get("provider"),
            "model": indexing.get("model"),
            "reachable": collections is not None,
            "embedder_reachable": reachable(f"{embedder_probe}/api/tags") if embedder_probe else False,
            "collections": collections or [],
            "points": sum((c.get("points") or 0) for c in (collections or [])),
            "submodules": submodule_coverage(),
            "configured": bool(kilo_index_config().get("enabled")),
        },
    }


def telemetry_status(contract: dict) -> dict:
    """Claude Code's OTel path: is the collector listening, is Prometheus up.

    The collector's health_check extension is on :13133, which is only on the
    fleet network — from the host (no OTEL_COLLECTOR_URL) the published OTLP
    port is probed instead: any HTTP answer there means it is accepting.
    """
    metrics = contract.get("metrics") or {}
    c = claude_contract(contract)
    prom = metrics.get("prometheus") or ""
    collector_probe = os.environ.get(PROBE_ENV["otel-collector"])
    collector_up = (reachable(collector_probe) if collector_probe
                    else _answers(f"{str(c['endpoint']).rstrip('/')}/v1/metrics"))
    return {
        "engine": "otel-collector",
        "url": c["endpoint"],
        "reachable": collector_up,
        "prometheus": prom,
        "prometheus_reachable": reachable(f"{probe_url('prometheus', prom)}/-/ready") if prom else False,
        "phoenix_project": c["phoenix_project"],
        "signals": c["signals"],
    }


def _answers(url: str) -> bool:
    """True when anything HTTP answers — a 405 from an OTLP POST-only route counts."""
    try:
        with urllib.request.urlopen(url, timeout=5):      # noqa: S310 (loopback only)
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def dataset_stats(contract: dict) -> list[dict]:
    """Doc count, size and time span per data stream.

    The span is what tells a reader why a dashboard is empty: Kibana and
    Grafana open on a relative window ("last 7 days"), so a plane whose newest
    line is three weeks old renders "No data" over 400k documents.
    """
    logs = contract["logs"]
    es = probe_url("elasticsearch", logs["elasticsearch"])
    out = []
    for key in sorted(logs["datasets"]):
        stream = data_stream_for(key, contract)
        stats = _get_json(f"{es}/{stream}/_stats/docs,store") or {}
        total = ((stats.get("_all") or {}).get("primaries") or {})
        span = {}
        if stats:
            body = _query_json(f"{es}/{stream}/_search", {
                "size": 0, "track_total_hits": False,
                "aggs": {"oldest": {"min": {"field": "@timestamp"}},
                         "newest": {"max": {"field": "@timestamp"}}}}) or {}
            span = body.get("aggregations") or {}
        out.append({
            "oldest": (span.get("oldest") or {}).get("value_as_string"),
            "newest": (span.get("newest") or {}).get("value_as_string"),
            "dataset": key,
            "data_stream": stream,
            "docs": ((total.get("docs") or {}).get("count")),
            "bytes": ((total.get("store") or {}).get("size_in_bytes")),
            "retention_days": logs["retention_days"][key],
            "present": bool(stats),
        })
    return out


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_verify(args) -> int:
    """Offline: render the cluster config out of the contract and diff it
    against the committed files. No network, no running stack — this is the
    check CI could run if the plane ever stopped being local-only."""
    contract = load_contract(args.fleet)
    policies, templates = render_all(contract)
    # Everything the cluster is configured with is RENDERED from the contract:
    # retention, mappings, data views and both dashboards. Committing them keeps
    # the stack reproducible from a clean volume; rendering them keeps the
    # committed copies from drifting away from _data/fleet.yml.
    want = {
        CONFIG_DIR / "elasticsearch" / "ilm-policies.json":
            json.dumps(policies, indent=2, sort_keys=True) + "\n",
        CONFIG_DIR / "elasticsearch" / "index-templates.json":
            json.dumps(templates, indent=2, sort_keys=True) + "\n",
        # NDJSON: one saved object per line is Kibana's import format, not a
        # style choice — a JSON array is rejected by the import API.
        CONFIG_DIR / "kibana" / "dashboards.ndjson":
            "".join(json.dumps(o, sort_keys=True) + "\n" for o in kibana_saved_objects(contract)),
        CONFIG_DIR / "grafana" / "dashboards" / "fleet-logs.json":
            json.dumps(grafana_dashboard(contract), indent=2, sort_keys=True) + "\n",
    }
    drift = 0
    for path, text in want.items():
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"  wrote {path.relative_to(REPO_ROOT)}")
            continue
        current = path.read_text() if path.exists() else ""
        if current != text:
            drift += 1
            print(f"  DRIFT {path.relative_to(REPO_ROOT)} — "
                  f"{'missing' if not current else 'differs from the contract'}")
        else:
            print(f"  ok    {path.relative_to(REPO_ROOT)}")

    # Every pinned dashboard id must resolve, or the console's embeds are blank
    # iframes with no error anywhere.
    for plane, ref in (contract.get("portal") or {}).get("dashboards", {}).items():
        ident = ref.get("id") or ref.get("uid")
        blob = ""
        for candidate in (CONFIG_DIR / "kibana" / "dashboards.ndjson",
                          CONFIG_DIR / "grafana" / "dashboards" / "fleet-logs.json"):
            if candidate.exists():
                blob += candidate.read_text()
        if ident and f'"{ident}"' in blob:
            print(f"  ok    portal.{plane} dashboard '{ident}' resolves")
        else:
            drift += 1
            print(f"  DRIFT portal.{plane} dashboard '{ident}' is not in any committed saved object")

    if drift and not args.write:
        print(f"\n{drift} drift(s). Re-render with: tools/dash observe verify --write", file=sys.stderr)
        return 1
    return 0


def cmd_status(args) -> int:
    contract = load_contract(args.fleet)
    planes = plane_status(contract)
    doc = {"planes": planes, "datasets": [], "disk_budget_gb": contract["logs"]["disk_budget_gb"],
           "shipments": {"count": 0, "last": None}, "portal": contract.get("portal") or {}}
    if planes["logs"]["reachable"]:
        doc["datasets"] = dataset_stats(contract)
    try:
        conn = fleet_lake.connect(args.lake, create=False)
        row = conn.execute(
            "SELECT COUNT(*) c, MAX(shipped_at) last FROM shipments WHERE sink = ?", (SINK,)
        ).fetchone()
        doc["shipments"] = {"count": row["c"], "last": row["last"]}
        pend = conn.execute(
            "SELECT COUNT(*) c FROM runs r WHERE r.status = 'completed' "
            "AND NOT EXISTS (SELECT 1 FROM shipments s WHERE s.key = 'run:' || r.nwo || ':' "
            "|| r.id || ':' || COALESCE(r.run_attempt, 1) AND s.sink = ?)", (SINK,)).fetchone()
        doc["shipments"]["pending"] = pend["c"]
    except Exception as exc:
        doc["shipments"]["error"] = f"{exc.__class__.__name__}: {exc}"

    total_bytes = sum(d["bytes"] or 0 for d in doc["datasets"])
    doc["bytes_total"] = total_bytes
    doc["over_budget"] = total_bytes > contract["logs"]["disk_budget_gb"] * 1024 ** 3

    if args.json:
        print(json.dumps(doc, indent=2))
        return 0
    for name, plane in planes.items():
        mark = "ok " if plane["reachable"] else "DOWN"
        print(f"  [{mark}] {name:8} {plane['engine']:<10} {plane['url']}")
    idx = planes.get("indexing") or {}
    subs = idx.get("submodules") or {}
    if subs:
        print(f"  index scope  {subs.get('checked_out', 0)}/{subs.get('declared', 0)} "
              f"submodules checked out, embedder {'up' if idx.get('embedder_reachable') else 'down'}"
              f" ({idx.get('model') or 'unset'})")
        empty = subs.get("empty") or []
        if empty:
            print(f"  not checked out: {', '.join(empty)}")
    if doc["datasets"]:
        print()
        for d in doc["datasets"]:
            size = f"{(d['bytes'] or 0) / 1024 ** 2:.1f} MB"
            print(f"  {d['data_stream']:<34} {str(d['docs'] or 0):>10} docs  {size:>12}"
                  f"  retain {d['retention_days']}d")
        print(f"\n  total {total_bytes / 1024 ** 3:.2f} GB of {contract['logs']['disk_budget_gb']} GB budget"
              f"{'  ** OVER BUDGET **' if doc['over_budget'] else ''}")
    s = doc["shipments"]
    print(f"\n  shipped {s['count']} run(s), {s.get('pending', '?')} pending, last {s['last'] or 'never'}")
    return 0


def cmd_ship(args) -> int:
    """Replay the lake's runs into Logstash as ECS documents."""
    contract = load_contract(args.fleet)
    endpoint = (args.endpoint or os.environ.get("LOGSTASH_URL")
                or contract["logs"]["logstash_http"])
    batch_size = int(contract["logs"]["ship"]["batch"])
    projects = registry_index()

    try:
        conn = fleet_lake.connect(args.lake, create=False)
    except Exception as exc:
        print(f"no lake to ship from ({exc}). Run `tools/dash lake sync` first.", file=sys.stderr)
        return 1

    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sql = ("SELECT * FROM runs WHERE status = 'completed' AND COALESCE(created_at, '') >= ?")
    params: list = [since]
    if args.repo:
        sql += " AND nwo LIKE ?"
        params.append(f"%/{args.repo}")
    sql += " ORDER BY created_at DESC"
    runs = [dict(r) for r in conn.execute(sql, params).fetchall()]

    shipped = [r["key"] for r in conn.execute(
        "SELECT key FROM shipments WHERE sink = ?", (SINK,)).fetchall()]
    shipped_set = set(shipped)

    session = None
    if not args.dry_run or args.refetch:
        session = _gh_session()

    preview, totals = [], {"runs": 0, "docs": 0, "bytes": 0, "skipped": 0, "failed": 0}
    for run in runs:
        key = f"run:{run['nwo']}:{run['id']}:{run.get('run_attempt') or 1}"
        if key in shipped_set and not args.force:
            totals["skipped"] += 1
            continue
        agent = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run["id"],)).fetchone()
        agent = dict(agent) if agent else None
        project = projects.get(run["nwo"])

        docs: list[dict] = []
        # Prefer the lake's stored entries — they cost nothing. Re-fetch only
        # when they were truncated at the lake's per-run cap AND the caller
        # asked for the full text, which is what `ship: logs: all` means.
        entries = conn.execute(
            "SELECT entry, text, truncated FROM logs WHERE run_id = ? ORDER BY entry", (run["id"],)
        ).fetchall()
        truncated = any(e["truncated"] for e in entries)
        if (not entries or truncated) and session and run.get("logs_url"):
            entries = [{"entry": name, "text": text, "truncated": 0}
                       for name, _raw, text in fleet_lake.iter_log_entries(session, run["logs_url"])]
        for e in entries:
            docs.extend(ecs_from_log_entry(e["entry"], e["text"], run, contract, agent, project))
        if agent:
            docs.append(ecs_from_agent_run(agent, run, contract, project))
        if not docs:
            continue

        nbytes = sum(len(d.get("message") or "") for d in docs)
        if args.dry_run:
            preview.append({"key": key, "nwo": run["nwo"], "workflow": run.get("workflow_name"),
                            "docs": len(docs), "bytes": nbytes,
                            "trace_id": docs[0]["trace"]["id"]})
        else:
            ok = True
            for i in range(0, len(docs), batch_size):
                good, err = _post_json(endpoint, docs[i:i + batch_size])
                if not good:
                    ok = False
                    print(f"  ! {run['nwo']} run {run['id']}: {err}", file=sys.stderr)
                    break
            if not ok:
                totals["failed"] += 1
                continue
            fleet_lake.upsert(conn, "shipments", {
                "key": key, "sink": SINK, "docs": len(docs), "bytes": nbytes,
                "endpoint": endpoint,
                "shipped_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }, ["key"])
            conn.commit()
        totals["runs"] += 1
        totals["docs"] += len(docs)
        totals["bytes"] += nbytes
        if args.limit and totals["runs"] >= args.limit:
            break

    if args.dry_run:
        out = Path(fleet_lake.lake_paths(args.lake)[0]) / "observe-preview.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"endpoint": endpoint, "totals": totals, "runs": preview},
                                  indent=2) + "\n")
        print(f"  dry run — {totals['docs']} doc(s) from {totals['runs']} run(s), "
              f"{totals['skipped']} already shipped")
        print(f"  preview written to {out}")
        return 0

    print(f"  shipped {totals['docs']} doc(s) from {totals['runs']} run(s) to {endpoint} "
          f"({totals['skipped']} already shipped, {totals['failed']} failed)")
    return 1 if totals["failed"] else 0


def _gh_session():
    """An authenticated session shaped exactly like `lake sync` builds one.

    Token resolution goes through actions_analytics.resolve_token — the fleet's
    single resolver (GH_TOKEN / GITHUB_TOKEN / `gh auth token`) — so this path
    cannot end up authenticating differently from the extractor whose output it
    is replaying. No token is not an error here: the lake's stored entries are
    still shippable, only the re-fetch of truncated ones is skipped.
    """
    try:
        import actions_analytics                          # noqa: WPS433
        import requests                                   # noqa: WPS433
    except ImportError:
        return None
    token = actions_analytics.resolve_token()
    if not token:
        return None
    session = requests.Session()
    session.headers["Authorization"] = f"token {token}"
    return session


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _settings_path(args, contract: dict) -> Path:
    raw = args.settings or claude_contract(contract)["settings"]
    return Path(os.path.expanduser(str(raw)))


def cmd_claude(args) -> int:
    """Point THIS machine's Claude Code at the collector — or stop.

    Writes the USER settings file (~/.claude/settings.json `env`), because
    Claude Code ignores OTEL_* exporter variables in a repository's
    .claude/settings.json: a repo cannot enable telemetry or pick where it
    goes. Dry run unless --apply; `disable` removes exactly CLAUDE_ENV_KEYS.
    Takes effect for sessions started AFTER the write.
    """
    contract = load_contract(args.fleet)
    want = claude_env(contract)
    action = args.action

    if action == "env":
        if args.shell:
            for k, v in want.items():
                print(f"export {k}={v}")
        else:
            print(json.dumps({"env": want}, indent=2))
        return 0

    path = _settings_path(args, contract)
    try:
        current = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError) as exc:
        print(f"  cannot read {path}: {exc} — not touching it", file=sys.stderr)
        return 1
    have = {k: v for k, v in (current.get("env") or {}).items() if k in CLAUDE_ENV_KEYS}

    if action == "status":
        tel = telemetry_status(contract)
        state = ("enabled" if have and have == want else "enabled, differs from the contract" if have
                 else "not enabled")
        doc = {"settings": str(path), "state": state, "have": have, "want": want, "telemetry": tel}
        if args.json:
            print(json.dumps(doc, indent=2))
            return 0
        print(f"  settings   {path}: {state}")
        print(f"  collector  {'up  ' if tel['reachable'] else 'DOWN'} {tel['url']}")
        print(f"  prometheus {'up  ' if tel['prometheus_reachable'] else 'DOWN'} {tel['prometheus']}")
        print(f"  phoenix    project {tel['phoenix_project']}")
        for k in sorted(set(have) | set(want)):
            if have.get(k) != want.get(k):
                print(f"    {k}: {have.get(k, '—')} → {want.get(k, '(removed)')}")
        return 0

    new = merge_claude_env(current, want if action == "enable" else None)
    changes = sorted(k for k in set(have) | set(want if action == "enable" else {})
                     if have.get(k) != (want.get(k) if action == "enable" else None))
    if not changes:
        print(f"  {path}: already {'enabled' if action == 'enable' else 'disabled'} — nothing to do")
        return 0
    for k in changes:
        after = want.get(k) if action == "enable" else None
        print(f"  {k}: {have.get(k, '—')} → {after if after is not None else '(removed)'}")
    if not args.apply:
        print(f"\n  dry run — re-run with --apply to write {path}")
        return 0
    if action == "enable":
        tel = telemetry_status(contract)
        if not tel["reachable"]:
            print(f"  note: nothing answers at {tel['url']} yet — sessions will export into the void "
                  "until `tools/dash observe up` (Claude Code itself is unaffected).")
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".pre-otel.bak")
    if path.exists() and not backup.exists():
        backup.write_text(path.read_text())
        print(f"  backup     {backup}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(new, indent=2) + "\n")
    tmp.replace(path)
    print(f"  wrote {path} — applies to Claude Code sessions started from now on")
    return 0


def run(args) -> int:
    return {"status": cmd_status, "ship": cmd_ship, "verify": cmd_verify,
            "claude": cmd_claude}[args.observe_cmd](args)


def add_arguments(parser) -> None:
    parser.add_argument("--fleet", default=None, help="path to _data/fleet.yml")
    parser.add_argument("--lake", default=None, help="path to the .dash-lake directory")
    sub = parser.add_subparsers(dest="observe_cmd", required=True)

    p_status = sub.add_parser("status", help="per-plane health, dataset sizes, ship lag")
    p_status.add_argument("--json", action="store_true", help="machine-readable (the console's /api/observability)")

    p_ship = sub.add_parser("ship", help="replay the lake's Actions logs into Logstash as ECS documents")
    p_ship.add_argument("--days", type=int, default=7, help="how far back to consider runs (default 7)")
    p_ship.add_argument("--repo", default=None, help="one repo name, not the full nwo")
    p_ship.add_argument("--limit", type=int, default=0, help="stop after N runs (0 = no limit)")
    p_ship.add_argument("--force", action="store_true", help="re-ship runs already in the ledger")
    p_ship.add_argument("--refetch", action="store_true",
                        help="re-download log zips even in --dry-run (slower, exact byte counts)")
    p_ship.add_argument("--dry-run", action="store_true",
                        help="build everything, write .dash-lake/observe-preview.json, send nothing")
    p_ship.add_argument("--endpoint", default=None, help="override the Logstash HTTP input URL")

    p_verify = sub.add_parser("verify", help="render ILM/templates from the contract and diff the committed files")
    p_verify.add_argument("--write", action="store_true", help="write the rendered files instead of diffing")

    p_claude = sub.add_parser("claude", help="point this machine's Claude Code OTel export at the collector")
    p_claude.add_argument("action", choices=["status", "env", "enable", "disable"], nargs="?", default="status")
    p_claude.add_argument("--apply", action="store_true", help="write the settings file (default: dry run)")
    p_claude.add_argument("--settings", default=None, help="settings file (default: contract `settings`)")
    p_claude.add_argument("--shell", action="store_true", help="env: print `export` lines for a shell")
    p_claude.add_argument("--json", action="store_true", help="status: machine-readable")

    parser.set_defaults(func=run)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_observe", description=__doc__)
    add_arguments(ap)
    ns = ap.parse_args()
    raise SystemExit(ns.func(ns) or 0)

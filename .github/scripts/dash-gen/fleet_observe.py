#!/usr/bin/env python3
"""
fleet_observe — the LOG plane: ship, render, verify, report.

Three planes run on the local bench and each has one job. Phoenix holds traces
(shape, latency and cost of an agent run). Grafana draws trends. THIS module
owns logs: the raw text of what the fleet's CI and containers actually said,
indexed in Elasticsearch and searchable in Kibana.

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
    "datasets": {"actions": "fleet.actions", "container": "fleet.container", "app": "fleet.app"},
    "retention_days": {"actions": 90, "container": 14, "app": 30},
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
    else:
        props["container"] = {"properties": {
            "id": {"type": "keyword"}, "name": {"type": "keyword"},
            "image": {"properties": {"name": {"type": "keyword"}}},
        }}
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
            "mappings": {"properties": props},
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
DATA_VIEW_IDS = {"actions": "fleet-actions", "container": "fleet-container", "app": "fleet-app"}
GRAFANA_DS_UID = "fleet-elasticsearch"


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
             "grafana": "GRAFANA_URL", "phoenix": "PHOENIX_COLLECTOR_ENDPOINT"}


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


def plane_status(contract: dict) -> dict:
    """Per-plane reachability + identity. Never raises: a plane that is down is
    a document saying so, which is what lets the console render a Start button
    instead of a 500."""
    logs, metrics, traces = contract["logs"], contract.get("metrics") or {}, contract.get("traces") or {}
    es_url, kibana_url = logs["elasticsearch"], logs["kibana"]
    grafana_url = metrics.get("grafana") or ""
    phoenix_url = traces.get("endpoint") or ""
    # Probe one address, report the other: `url` is what the browser gets.
    es_probe = probe_url("elasticsearch", es_url)
    health = _get_json(f"{es_probe}/_cluster/health")
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
    }


def dataset_stats(contract: dict) -> list[dict]:
    """Doc count and size per data stream, plus its ILM phase."""
    logs = contract["logs"]
    es = probe_url("elasticsearch", logs["elasticsearch"])
    out = []
    for key in sorted(logs["datasets"]):
        stream = data_stream_for(key, contract)
        stats = _get_json(f"{es}/{stream}/_stats/docs,store") or {}
        total = ((stats.get("_all") or {}).get("primaries") or {})
        out.append({
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
def run(args) -> int:
    return {"status": cmd_status, "ship": cmd_ship, "verify": cmd_verify}[args.observe_cmd](args)


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

    parser.set_defaults(func=run)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_observe", description=__doc__)
    add_arguments(ap)
    ns = ap.parse_args()
    raise SystemExit(ns.func(ns) or 0)

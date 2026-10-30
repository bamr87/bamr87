"""The /api/claude-telemetry document: Claude Code's native OpenTelemetry, read-only.

Claude Code exports OTLP (even on a Max subscription) to the fleet collector
(tools/observability/otel-collector/config.yaml):
  * metrics -> Prometheus (PROMETHEUS_URL) as claude_code_*_total counters
  * events  -> Logstash enrich -> Elasticsearch data stream logs-fleet.claude-*
    (ELASTICSEARCH_URL), event.action = api_request | tool_result | user_prompt | ...

This module only reads. Cost is Claude Code's own API-list-price figure and is
labelled "API-equivalent (estimate)": on a subscription it is not a bill. The
subscription-vs-API cost model lives in live.py / spend_vs_budget, not here.
Range sums use `anchored` increase() (exact per-session counters, see docs/OBSERVABILITY.md).
Identity fields (user email, account/org ids) are never returned.
Every section degrades to {"error": ...} rather than failing the document.
"""
from __future__ import annotations

import json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone

PROM = os.environ.get("PROMETHEUS_URL", "http://host.docker.internal:9090").rstrip("/")
ES = os.environ.get("ELASTICSEARCH_URL", "http://host.docker.internal:9200").rstrip("/")
ES_INDEX = "logs-fleet.claude-*"
COST_LABEL = "API-equivalent (estimate)"
WINDOWS = ("1h", "24h", "7d")
EVENT_FIELDS = ("model", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
                "cost_usd", "duration_ms", "effort", "speed", "query_source", "app_entrypoint", "app_version",
                "tool_name", "success", "decision", "error", "status_code", "prompt_length")
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _guard(fn):
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{exc.__class__.__name__}: {exc}"}


def window(w: str) -> str:
    if w not in WINDOWS:
        raise ValueError(f"window must be one of {WINDOWS}")
    return w


def _prom_vec(q: str) -> list[dict]:
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": q})
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.load(r)["data"]["result"]


def _by(metric: str, labels: tuple[str, ...], w: str) -> list[dict]:
    by = f" by ({', '.join(labels)})" if labels else ""
    rows = [{**{k: x["metric"].get(k) for k in labels}, "value": round(float(x["value"][1]), 4)}
            for x in _prom_vec(f"sum{by}(increase({metric}[{w}] anchored))")]
    return sorted((r for r in rows if r["value"]), key=lambda r: -r["value"])


def _total(rows: list[dict]) -> float:
    return round(sum(r["value"] for r in rows), 4)


def series() -> list[str]:
    """Every claude_code_* metric name Prometheus currently holds."""
    rows = _prom_vec('count by (__name__)({__name__=~"claude_code_.*"})')
    return sorted(x["metric"]["__name__"] for x in rows)


def metrics(w: str = "24h") -> dict:
    w = window(w)
    m = lambda name, labels=(): _guard(lambda: _by(f"claude_code_{name}", labels, w))  # noqa: E731
    tokens = m("token_usage_tokens_total", ("type", "model"))
    cost = m("cost_usage_USD_total", ("model",))
    loc = m("lines_of_code_count_total", ("type",))
    decisions = m("code_edit_tool_decision_total", ("tool_name", "decision"))
    out = {
        "window": w,
        "sessions": m("session_count_total"),
        "active_time_s": m("active_time_seconds_total", ("type",)),
        "tokens": tokens,
        "cost": {"label": COST_LABEL, "by_model": cost},
        "lines_of_code": loc,
        "commits": m("commit_count_total"),
        "pull_requests": m("pull_request_count_total"),
        "tool_decisions": decisions,
    }
    tot = {}
    for k in ("sessions", "commits", "pull_requests", "active_time_s", "tokens", "lines_of_code", "tool_decisions"):
        v = out[k]
        tot[k] = _total(v) if isinstance(v, list) else None
    tot["cost_usd_api_equivalent"] = _total(cost) if isinstance(cost, list) else None
    out["totals"] = tot
    return out


def _es(body: dict) -> dict:
    req = urllib.request.Request(f"{ES}/{ES_INDEX}/_search", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.load(r)


def _short(sid: str | None) -> str | None:
    return sid[:8] if sid else sid


def events(w: str = "24h", session: str | None = None, limit: int = 20) -> dict:
    """Event counts by type, the latest api_request/tool_result rows, and per-session api_request rollups."""
    w = window(w)
    limit = max(1, min(int(limit), 100))
    flt: list[dict] = [{"range": {"@timestamp": {"gte": f"now-{w}"}}}]
    if session:
        if not re.fullmatch(r"[0-9a-fA-F-]{4,64}", session):
            raise ValueError("session must be a session id or its hex prefix")
        flt.append({"prefix": {"claude.session_id": session}})
    doc = _es({
        "size": limit, "sort": [{"@timestamp": "desc"}],
        "query": {"bool": {"filter": flt + [{"terms": {"event.action": ["api_request", "tool_result", "api_error"]}}]}},
        "_source": ["@timestamp", "event.action", "claude.session_id"] + [f"claude.{f}" for f in EVENT_FIELDS],
        "aggs": {
            "by_action": {"terms": {"field": "event.action", "size": 30}},
            "sessions": {"filter": {"term": {"event.action": "api_request"}}, "aggs": {"s": {
                "terms": {"field": "claude.session_id", "size": 15, "order": {"last": "desc"}},
                "aggs": {"last": {"max": {"field": "@timestamp"}}, "cost": {"sum": {"field": "claude.cost_usd"}},
                         "in": {"sum": {"field": "claude.input_tokens"}}, "out": {"sum": {"field": "claude.output_tokens"}},
                         "cr": {"sum": {"field": "claude.cache_read_tokens"}},
                         "cc": {"sum": {"field": "claude.cache_creation_tokens"}},
                         "models": {"terms": {"field": "claude.model", "size": 5}}}}}},
        },
    })
    # by_action is computed over the whole window, so rerun its filter without the action restriction
    counts = _es({"size": 0, "query": {"bool": {"filter": flt}},
                  "aggs": {"a": {"terms": {"field": "event.action", "size": 30}}}})
    recent = []
    for h in doc.get("hits", {}).get("hits", []):
        s, c = h.get("_source", {}), h.get("_source", {}).get("claude", {}) or {}
        recent.append({"ts": s.get("@timestamp"), "event": (s.get("event") or {}).get("action"),
                       "session": _short(c.get("session_id")), **{f: c[f] for f in EVENT_FIELDS if f in c}})
    sess = []
    for b in doc.get("aggregations", {}).get("sessions", {}).get("s", {}).get("buckets", []):
        sess.append({"session": _short(b["key"]), "api_requests": b["doc_count"], "last": b["last"].get("value_as_string"),
                     "cost_usd_api_equivalent": round(b["cost"]["value"], 4),
                     "tokens": {"input": int(b["in"]["value"]), "output": int(b["out"]["value"]),
                                "cache_read": int(b["cr"]["value"]), "cache_creation": int(b["cc"]["value"])},
                     "models": [m["key"] for m in b["models"]["buckets"]]})
    return {"window": w, "index": ES_INDEX, "cost_label": COST_LABEL,
            "counts": {b["key"]: b["doc_count"] for b in counts.get("aggregations", {}).get("a", {}).get("buckets", [])},
            "sessions": sess, "recent": recent}


def snapshot(w: str = "24h", session: str | None = None, limit: int = 20) -> dict:
    w = window(w)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {"prometheus": PROM, "elasticsearch": ES},
        "cost_label": COST_LABEL,
        "series": _guard(lambda: _cached("series", 60, series)),
        "metrics": _guard(lambda: _cached(f"m:{w}", 10, lambda: metrics(w))),
        "events": _guard(lambda: _cached(f"e:{w}:{session}:{limit}", 10, lambda: events(w, session, limit))),
    }

"""The /api/live document: one snapshot of fleet bot activity for the /live page.

Sources (see docs/realtime-bot-dashboard-spec.md):
  * .dash-live/sessions.json — host Claude processes, written by live_collector.py
    on the host (the container cannot see host processes)
  * Prometheus (Claude Code OTel metrics) at PROMETHEUS_URL, default
    host.docker.internal:9090 — 127.0.0.1 inside the container is not the host
  * core.load_state() — spend trends vs budget, harness scorecard
  * _data/deep_dive.json — deep-dive cycle progress
  * the in-process JobManager — running and recent jobs
Every section degrades to {"error": ...} rather than failing the document.
"""
from __future__ import annotations

import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

import core

SESSIONS = core.REPO_ROOT / ".dash-live" / "sessions.json"
STALE_S = 30
PROM = os.environ.get("PROMETHEUS_URL", "http://host.docker.internal:9090").rstrip("/")
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


def sessions() -> dict:
    if not SESSIONS.exists():
        return {"collector": "missing", "sessions": [],
                "hint": "run python3 tools/console/live_collector.py on the host"}
    doc = json.loads(SESSIONS.read_text())
    age = time.time() - SESSIONS.stat().st_mtime
    doc["age_s"] = round(age, 1)
    doc["collector"] = "stale" if age > STALE_S else "ok"
    s = doc.get("sessions", [])
    doc["counts"] = {"total": len(s), "active": sum(x["state"] == "active" for x in s)}
    return doc


def _prom(q: str) -> float | None:
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": q})
    with urllib.request.urlopen(url, timeout=3) as r:
        res = json.load(r)["data"]["result"]
    return round(sum(float(x["value"][1]) for x in res), 4) if res else 0.0


def claude_live() -> dict:
    return {
        "source": PROM,
        "cost_usd_24h": _prom("sum(increase(claude_code_cost_usage_USD_total[24h]))"),
        "cost_usd_1h": _prom("sum(increase(claude_code_cost_usage_USD_total[1h]))"),
        "tokens_1h": _prom("sum(increase(claude_code_token_usage_tokens_total[1h]))"),
        "sessions_24h": _prom("sum(increase(claude_code_session_count_total[24h]))"),
        "active_time_s_1h": _prom("sum(increase(claude_code_active_time_seconds_total[1h]))"),
    }


def _state_parts() -> dict:
    st = core.load_state()
    tr = (st.get("harnesses") or {}).get("trends") or {}
    keep = ("window_total", "last7", "prior7", "wow_delta_pct", "projected_monthly", "budget_monthly",
            "status", "billed_this_month", "source")
    spend = {k: {f: (tr.get(k) or {}).get(f) for f in keep} for k in ("ai_cost_usd", "actions_minutes")}
    for v in spend.values():
        v["budget_set"] = v.get("budget_monthly") is not None
    health = st.get("health") or {}
    return {"spend": spend, "health": {"generated_at": health.get("generated_at"),
                                       "scorecard": health.get("scorecard") or {}}}


def deep_dive() -> dict:
    p = core.REPO_ROOT / "_data" / "deep_dive.json"
    doc = json.loads(p.read_text())
    s = doc.get("summary", {})
    repos = [{k: r.get(k) for k in ("day", "repo", "status", "last_processed")} for r in doc.get("repos", [])]
    return {"summary": s, "recent": [r for r in repos if r["status"] in ("in_progress", "done")][-5:]}


def _planes() -> dict:
    planes = core.observability_planes(True) or {}
    return {k: {"url": v.get("url"), "reachable": v.get("reachable")} for k, v in planes.items()
            if isinstance(v, dict) and k != "portal"}


def snapshot(jobs) -> dict:
    all_jobs = jobs.list()
    running = [j for j in all_jobs if j.get("status") in ("running", "queued")]
    parts = _guard(lambda: _cached("state", 15, _state_parts))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sessions": _guard(sessions),
        "claude_live": _guard(lambda: _cached("prom", 5, claude_live)),
        "jobs": {"running": running, "recent": all_jobs[:8]},
        "spend": parts.get("spend", parts) if isinstance(parts, dict) else parts,
        "health": parts.get("health", parts) if isinstance(parts, dict) else parts,
        "deep_dive": _guard(lambda: _cached("dd", 30, deep_dive)),
        "observability": _guard(lambda: _cached("planes", 30, _planes)),
    }

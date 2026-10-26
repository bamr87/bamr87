#!/usr/bin/env python3
"""pipeline_map.py — the data layer of the harness pipeline map (HUB-025, HUB-026).

Joins the pipeline definition (diagrams/pipeline-map/pipeline.json), activity-log
events (fleet_event rows, schema from docs/prd/FLEET-ACTIVITY-LOG.md) and job /
GitHub Actions run status into one JSON view model the Harness Console renders:
nodes with a derived status (running | idle | failed | unknown), a drill-down
(events, PRs, standard versions, amendment links) and one node per workflow in
.github/workflows/ carrying its triggers, schedule and last run (FR16–FR21).

Read-only. The GitHub API is called only with --refresh-runs, using GITHUB_TOKEN
or GH_TOKEN from the environment; the token is never printed or written.

Usage:
  python3 tools/pipeline_map.py [--events FILE] [--refresh-runs] [--repo owner/name] [--now ISO]
With no --events the activity log is treated as unavailable (every log-derived
status is "unknown"); diagrams/pipeline-map/events.example.json is EXAMPLE data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "diagrams" / "pipeline-map" / "pipeline.json"
WORKFLOWS = ROOT / ".github" / "workflows"
RUNNING_STALE = timedelta(hours=6)   # a start with no finish older than this is not "running"
FAILED_WINDOW = timedelta(hours=24)  # a failure newer than this marks the node failed
PR_RX = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def node_events(node: dict, events: list[dict], current: str | None) -> list[dict]:
    m = node.get("match") or {}
    if not m:
        return []
    out = []
    for e in events:
        if m.get("any"):
            out.append(e)
        elif m.get("drift"):
            if e.get("event_type") == "start" and e.get("standard_version") != current:
                out.append(e)
        elif e.get("bot_id") == m.get("bot_id"):
            if "event_type" in m and e.get("event_type") != m["event_type"]:
                continue
            if "decision_prefix" in m and not str(e.get("decision", "")).startswith(m["decision_prefix"]):
                continue
            out.append(e)
    return sorted(out, key=lambda e: e["ts"], reverse=True)


def derive_status(evts: list[dict], job: dict | None, now: datetime, log_ok: bool) -> str:
    """Rules (PRD §5): failed > running > idle; unknown when no source can speak."""
    if job and job.get("conclusion") in ("failure", "timed_out", "startup_failure"):
        return "failed"
    for e in evts:
        if now - _ts(e["ts"]) <= FAILED_WINDOW and (
                (e["event_type"] == "finish" and e.get("outcome") == "failure")
                or (e["event_type"] == "retry" and (e.get("detail") or {}).get("final_outcome") == "gave_up")):
            return "failed"
    if job and job.get("status") in ("in_progress", "queued"):
        return "running"
    finished = {e["run_id"] for e in evts if e["event_type"] == "finish"}
    if any(e["event_type"] == "start" and e["run_id"] not in finished and now - _ts(e["ts"]) <= RUNNING_STALE for e in evts):
        return "running"
    if not log_ok and not job:
        return "unknown"
    return "idle"


def workflow_nodes(wf_dir: Path = WORKFLOWS) -> list[dict]:
    """One node per workflow file: triggers and cron schedules from its `on:` block."""
    nodes = []
    for p in sorted(wf_dir.glob("*.yml")):
        doc = yaml.safe_load(p.read_text()) or {}
        on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
        if isinstance(on, str):
            on = {on: None}
        elif isinstance(on, list):
            on = {k: None for k in on}
        on = on or {}
        crons = [s.get("cron") for s in (on.get("schedule") or []) if isinstance(s, dict)]
        nodes.append({"id": f"wf-{p.stem}", "label": doc.get("name") or p.stem, "kind": "workflow",
                      "lane": "workflows", "file": f".github/workflows/{p.name}",
                      "triggers": sorted(on.keys()), "schedule": crons, "last_run": None})
    return nodes


def fetch_last_runs(repo: str, files: list[str]) -> dict[str, dict]:
    """Latest run per workflow file from the GitHub Actions API (on-demand refresh)."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    runs = {}
    for f in files:
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{Path(f).name}/runs?per_page=1"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
                items = json.load(r).get("workflow_runs") or []
        except Exception as exc:  # one failed call must not sink the map
            runs[f] = {"error": type(exc).__name__}
            continue
        if items:
            w = items[0]
            runs[f] = {k: w.get(k) for k in ("status", "conclusion", "event", "html_url", "updated_at", "run_number")}
    return runs


def build(pipeline: dict, log: dict | None, runs: dict[str, dict] | None = None,
          now: datetime | None = None, wf_dir: Path = WORKFLOWS) -> dict:
    now = now or datetime.now(timezone.utc)
    log_ok = log is not None
    events = (log or {}).get("events", [])
    current = (log or {}).get("current_standard_version")
    links = (log or {}).get("amendment_links", [])
    jobs = {j["job"]: j for j in (log or {}).get("jobs", [])}
    out_nodes = []
    for n in pipeline["nodes"]:
        evts = node_events(n, events, current)
        ids = {e["event_id"] for e in evts}
        out_nodes.append({**n, "status": derive_status(evts, jobs.get(n.get("job")), now, log_ok),
                          "drill": {"events": evts[:50],
                                    "prs": sorted({e["task_ref"] for e in evts if PR_RX.match(e.get("task_ref", ""))}),
                                    "standard_versions": sorted({e.get("standard_version", "unknown") for e in evts}),
                                    "amendments": [l for l in links if l["event_id"] in ids]}})
    for w in workflow_nodes(wf_dir):
        run = (runs or {}).get(w["file"])
        w["last_run"] = run
        if not run or "error" in run:
            w["status"] = "unknown"
        elif run.get("status") in ("in_progress", "queued"):
            w["status"] = "running"
        else:
            w["status"] = "failed" if run.get("conclusion") in ("failure", "timed_out", "startup_failure") else "idle"
        w["result"] = {"success": "pass", "failure": "fail"}.get((run or {}).get("conclusion"), (run or {}).get("conclusion"))
        out_nodes.append(w)
    return {"schema": "pipeline-map-view/v1", "generated_at": now.isoformat(),
            "log": "example" if log and "_example" in log else ("available" if log_ok else "unavailable"),
            "lanes": pipeline["lanes"] + [{"id": "workflows", "label": "GitHub workflows"}],
            "nodes": out_nodes, "edges": pipeline["edges"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--events", type=Path)
    ap.add_argument("--refresh-runs", action="store_true")
    ap.add_argument("--repo", default="bamr87/bamr87")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    pipeline = json.loads(PIPELINE.read_text())
    log = None
    if a.events:
        try:
            log = json.loads(a.events.read_text())
        except (OSError, ValueError):
            log = None  # unavailable log: render the map, statuses unknown
    runs = fetch_last_runs(a.repo, [w["file"] for w in workflow_nodes()]) if a.refresh_runs else None
    now = _ts(a.now) if a.now else None
    json.dump(build(pipeline, log, runs, now), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

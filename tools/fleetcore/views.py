"""The fleet views as JSON — what the console serves and the TUI renders from the same objects.

`dash_view()` is fleet.load_snapshot() + host.attach() turned into plain data:
the Apps rows (registry ⨝ health ⨝ triage ⨝ containers), the KPIs, the inbox,
the harness wires and every source's freshness. `docker_view()` is the Docker
tab. Both are pure over the files and `docker ps`, so the browser and the
terminal cannot disagree about a number.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import fleet as fl
from . import host as dh


def _row(r: fl.AppRow) -> dict:
    d = asdict(r)
    d["failing"] = [{"workflow": w, "url": u} for w, u in r.failing]
    d["worst_level"] = r.worst_level
    return d


def docker_view(rows: list[fl.AppRow] | None = None, hosts: list[str] | None = None) -> dict:
    hosts = dh.docker_hosts() if hosts is None else hosts
    containers, errors = dh.list_all(hosts) if hosts else ([], {})
    out = []
    for c in containers:
        row = dh.owner(c, rows or [])
        out.append({**asdict(c), "owner": row.name if row else None, "running": c.running})
    return {"hosts": [dh.host_label(h) for h in hosts], "containers": out, "errors": errors,
            "polled_at": datetime.now(timezone.utc).isoformat()}


def dash_view(root: Path, *, docker: bool = False, hosts: list[str] | None = None,
              q: str = "", sort: str = "featured", health: str | None = None,
              repo: str | None = None) -> dict:
    """Filters and sorts go through fleet.filter_rows / sort_rows — the TUI's
    own — so the browser never re-implements (and drifts from) them. `repo`
    is the drill-down: every open item that repo carries, not only the flagged."""
    snap = fl.load_snapshot(root)
    view = {
        "kpis": fl.kpis(snap.rows),
        "health_present": snap.health_present,
        "sources": [asdict(s) for s in snap.sources],
        "inbox": [asdict(i) | {"label": i.label} for i in _inbox(snap, repo)],
        "repo": repo,
        "trip_wires": snap.trip_wires,
        "scorecard": snap.scorecard,
        "sorts": list(fl.SORTS),
    }
    if docker:
        dk = docker_view(snap.rows, hosts)
        boxes = [dh.Container(**{k: v for k, v in c.items() if k != "running"}) for c in dk["containers"]]
        dh.attach(snap.rows, boxes)
        view["docker"] = dk
    sort = sort if sort in fl.SORTS else "featured"
    rows = fl.filter_rows(snap.rows, q=q, health=health if health in fl.LEVELS else None)
    view["rows"] = [_row(r) for r in fl.sort_rows(rows, sort)]
    view["query"] = {"q": q, "sort": sort, "health": health}
    return view


def _inbox(snap: fl.Snapshot, repo: str | None) -> list[fl.InboxItem]:
    if not repo:
        return snap.inbox
    row = next((r for r in snap.rows if r.name == repo), None)
    return fl.repo_items(snap.triage, repo, row.repo_url if row else "")

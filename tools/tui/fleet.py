#!/usr/bin/env python3
"""Join the dash's committed signals the way the Jekyll dash does.

`_data/projects.yml` is the roster. Onto it this attaches:

- `_data/project_health.yml` — the /monitor/ board (ephemeral, `dash-gen health`)
- `_data/fleet_triage.yml`   — the /triage/ open state + inbox (committed, daily)
- `_data/harness_health.yml` — the /harness/ scorecard + trip wires (committed, daily)

Every signal is optional: a missing file degrades to "—", never to a crash or
a shorter roster. No Textual, no network. The TUI and the tests both call this.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("docs", "full-stack-ai", "dev-tools", "dash")
STATUSES = ("active", "maintenance", "experiment", "archived")
LEVELS = ("red", "amber", "green")
SORTS = ("featured", "name", "health", "triage", "alerts", "recent", "stars")

DOT = {"red": "🔴", "amber": "🟠", "green": "🟢"}
CAT_LABEL = {
    "docs": "Docs",
    "full-stack-ai": "Full-stack / AI",
    "dev-tools": "Dev tools",
    "dash": "Dash",
}
LEVEL_RANK = {"red": 0, "amber": 1, "green": 2, None: 3}

# The files a reload watches. Order is display order in the status line.
SOURCES = (
    ("registry", "_data/projects.yml"),
    ("health", "_data/project_health.yml"),
    ("triage", "_data/fleet_triage.yml"),
    ("harness", "_data/harness_health.yml"),
)
# Where each source's timestamp lives when it is not the file's own
# `generated_at` key. project_health.yml is a bare list, so dash-gen writes it
# beside the data.
STAMP_FILE = {"health": "_data/project_health_meta.yml"}
# The registry is hand-edited, not generated: it cannot go stale.
UNDATED = {"registry"}
DEFAULT_STALE_DAYS = 3.0


@dataclass
class AppRow:
    name: str
    description: str = ""
    category: str = ""
    status: str = ""
    featured: bool = False
    stack: list[str] = field(default_factory=list)
    repo_url: str = ""
    live_url: str | None = None
    docs_url: str | None = None
    submodule_path: str | None = None
    checked_out: bool = False
    health: str | None = None
    ci_last: str | None = None
    ci_pass: int | None = None
    last_commit_days: int | None = None
    commits_30d: int | None = None
    issues_open: int | None = None
    prs_open: int | None = None
    security_alerts: int = 0
    reasons: list[str] = field(default_factory=list)
    attention_rank: int = 99
    stars: int = 0
    # fleet_triage.yml — the committed open-state signal
    triage_level: str | None = None
    triage_score: int | None = None
    triage_reasons: list[str] = field(default_factory=list)
    triage_issues: int | None = None
    triage_prs: int | None = None
    failing: list[tuple[str, str]] = field(default_factory=list)  # (workflow, run_url)
    # host.attach — live containers
    docker_name: str | None = None
    docker_status: str | None = None
    docker_running: bool = False
    docker_up: int = 0
    docker_total: int = 0

    @property
    def dot(self) -> str:
        return DOT.get(self.health or "", "·")

    @property
    def triage_dot(self) -> str:
        return DOT.get(self.triage_level or "", "·")

    @property
    def worst_level(self) -> str | None:
        """The more alarming of the two attention signals."""
        levels = [lv for lv in (self.health, self.triage_level) if lv in LEVEL_RANK]
        return min(levels, key=LEVEL_RANK.__getitem__) if levels else None

    @property
    def haystack(self) -> str:
        bits = [self.name, self.description, self.category, self.status, *self.stack]
        return " ".join(bits).lower()


@dataclass
class InboxItem:
    kind: str
    repo: str
    title: str
    why: str
    priority: int
    age_days: int | None
    url: str
    ref: str = ""  # "#123" for issues/PRs, the workflow path for workflows

    @property
    def label(self) -> str:
        return f"{self.ref} {self.title}" if self.ref.startswith("#") else self.title

    @property
    def haystack(self) -> str:
        return " ".join((self.kind, self.repo, self.ref, self.title, self.why)).lower()


@dataclass
class Source:
    name: str
    path: str
    present: bool
    generated_at: str | None = None
    age_days: float | None = None
    stale: bool = False


@dataclass
class Snapshot:
    rows: list[AppRow]
    health_present: bool
    sources: list[Source]
    inbox: list[InboxItem] = field(default_factory=list)
    triage: dict = field(default_factory=dict)  # raw fleet_triage.yml, for repo_items()
    trip_wires: list[dict] = field(default_factory=list)
    scorecard: dict[str, dict] = field(default_factory=dict)

    def source(self, name: str) -> Source | None:
        return next((s for s in self.sources if s.name == name), None)


def load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _checked_out(root: Path, sub: str | None) -> bool:
    if not sub:
        return False
    p = root / sub
    if not p.is_dir():
        return False
    return any(p.iterdir())


def _int(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def join_fleet(root: Path) -> tuple[list[AppRow], bool]:
    """Return (rows, health_present). Missing health still lists the registry."""
    projects = load_yaml(root / "_data" / "projects.yml") or []
    raw_health = load_yaml(root / "_data" / "project_health.yml")
    health_present = isinstance(raw_health, list)
    by_name = {h.get("name"): h for h in (raw_health or []) if isinstance(h, dict)}

    rows: list[AppRow] = []
    for p in projects:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        h = by_name.get(p["name"]) or {}
        att = h.get("attention") or {}
        ci = h.get("ci") or {}
        act = h.get("activity") or {}
        issues = h.get("issues") or {}
        prs = h.get("prs") or {}
        sec = h.get("security") or {}
        sub = p.get("submodule_path")
        rank = _int(h.get("attention_rank"))
        rows.append(
            AppRow(
                name=p["name"],
                description=p.get("description") or "",
                category=p.get("category") or "",
                status=p.get("status") or "",
                featured=bool(p.get("featured")),
                stack=list(p.get("stack") or []),
                repo_url=p.get("repo_url") or "",
                live_url=p.get("live_url"),
                docs_url=p.get("docs_url"),
                submodule_path=sub,
                checked_out=_checked_out(root, sub),
                health=att.get("level") if health_present else None,
                ci_last=ci.get("last"),
                ci_pass=ci.get("pass_rate"),
                last_commit_days=act.get("last_commit_days"),
                commits_30d=act.get("commits_30d"),
                issues_open=issues.get("open"),
                prs_open=prs.get("open"),
                security_alerts=_int(sec.get("alerts")) or 0,
                reasons=list(att.get("reasons") or []),
                attention_rank=99 if rank is None else rank,
                stars=_int(h.get("stars")) or 0,
            )
        )
    return rows, health_present


def norm_url(url: str | None) -> str:
    u = (url or "").strip().lower().rstrip("/")
    return u[:-4] if u.endswith(".git") else u


def attach_triage(rows: list[AppRow], triage: Any) -> None:
    """Join fleet_triage.yml `by_repo` onto registry rows by repo URL, then name."""
    by_repo = (triage or {}).get("by_repo") if isinstance(triage, dict) else None
    entries = [t for t in (by_repo or []) if isinstance(t, dict)]
    by_url = {norm_url(t.get("repo_url")): t for t in entries if t.get("repo_url")}
    by_name = {str(t.get("name", "")).lower(): t for t in entries}
    for r in rows:
        t = by_url.get(norm_url(r.repo_url)) or by_name.get(r.name.lower())
        if not t:
            continue
        att = t.get("attention") or {}
        r.triage_level = att.get("level")
        r.triage_score = _int(att.get("score"))
        r.triage_reasons = list(att.get("reasons") or [])
        r.triage_issues = _int((t.get("issues") or {}).get("open"))
        r.triage_prs = _int((t.get("prs") or {}).get("open"))
        failing = (t.get("workflows") or {}).get("failing") or []
        r.failing = [
            (str(w.get("workflow") or w.get("path") or "?"), str(w.get("run_url") or ""))
            for w in failing
            if isinstance(w, dict)
        ]


def inbox_items(triage: Any) -> list[InboxItem]:
    """fleet_triage.yml `inbox`, highest priority first (stable for ties)."""
    raw = (triage or {}).get("inbox") if isinstance(triage, dict) else None
    items = [
        InboxItem(
            kind=str(i.get("kind") or ""),
            repo=str(i.get("repo") or ""),
            title=str(i.get("title") or ""),
            why=str(i.get("why") or ""),
            priority=_int(i.get("priority")) or 0,
            age_days=_int(i.get("age_days")),
            url=str(i.get("url") or ""),
            ref=str(i.get("ref") or ""),
        )
        for i in (raw or [])
        if isinstance(i, dict)
    ]
    return sorted(items, key=lambda i: -i.priority)


def _triage_entry(triage: Any, name: str, repo_url: str = "") -> dict | None:
    by_repo = (triage or {}).get("by_repo") if isinstance(triage, dict) else None
    entries = [t for t in (by_repo or []) if isinstance(t, dict)]
    url = norm_url(repo_url)
    return next((t for t in entries if url and norm_url(t.get("repo_url")) == url), None) or next(
        (t for t in entries if str(t.get("name", "")).lower() == name.lower()), None
    )


def repo_items(triage: Any, name: str, repo_url: str = "") -> list[InboxItem]:
    """Every open item one repo carries in fleet_triage.yml `by_repo` — the
    drill-down. The fleet inbox holds only FLAGGED items, capped at 150 across
    ~40 repos, so most repos have open work and no inbox rows at all.

    Priorities mirror fleet_triage.build_inbox (workflow 90, failing-CI PR 70,
    bug 60, PR 55, issue 40) so an item ranks the same in both views.
    """
    t = _triage_entry(triage, name, repo_url)
    if not t:
        return []
    repo = str(t.get("name") or name)
    items: list[InboxItem] = []
    for f in (t.get("workflows") or {}).get("failing") or []:
        if isinstance(f, dict):
            items.append(InboxItem(
                kind="workflow", repo=repo, title=str(f.get("workflow") or f.get("path") or "?"),
                why=f"latest run {f.get('conclusion') or 'failed'}", priority=90, age_days=None,
                url=str(f.get("run_url") or ""), ref=str(f.get("path") or ""),
            ))
    for p in (t.get("prs") or {}).get("items") or []:
        if not isinstance(p, dict):
            continue
        tags = [x for x, on in (("draft", p.get("draft")), ("dependabot", p.get("dependabot"))) if on]
        if p.get("ci") == "fail":
            pri, why = 70, "PR checks failing"
        else:
            pri, why = 55, f"PR idle {_fmt_days(p.get('idle_days'))}"
        items.append(InboxItem(
            kind="pr", repo=repo, title=str(p.get("title") or ""), why=" · ".join([why, *tags]),
            priority=pri, age_days=_int(p.get("age_days")), url=str(p.get("url") or ""),
            ref=f"#{p['number']}" if p.get("number") else "",
        ))
    for i in (t.get("issues") or {}).get("items") or []:
        if not isinstance(i, dict):
            continue
        if any("bug" in str(lb).lower() for lb in i.get("labels") or []):
            pri, why = 60, "bug label"
        else:
            pri, why = 40, f"issue idle {_fmt_days(i.get('idle_days'))}"
        items.append(InboxItem(
            kind="issue", repo=repo, title=str(i.get("title") or ""), why=why, priority=pri,
            age_days=_int(i.get("age_days")), url=str(i.get("url") or ""),
            ref=f"#{i['number']}" if i.get("number") else "",
        ))
    return sorted(items, key=lambda x: (-x.priority, -(x.age_days or 0)))


def _fmt_days(v: Any) -> str:
    n = _int(v)
    return "?" if n is None else f"{n}d"


def filter_inbox(items: list[InboxItem], *, q: str = "", repo: str | None = None) -> list[InboxItem]:
    needle = q.strip().lower()
    return [
        i
        for i in items
        if (not repo or i.repo.lower() == repo.lower()) and (not needle or needle in i.haystack)
    ]


def parse_stamp(value: Any) -> datetime | None:
    """`2026-09-30 06:03 UTC` (dash-gen) or ISO-8601 → aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M:%S UTC"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def stale_days(root: Path) -> float:
    """The harness's own freshness wire, so the TUI and /harness/ agree on 'stale'."""
    fleet = load_yaml(root / "_data" / "fleet.yml")
    try:
        return float(fleet["harness"]["trip_wires"]["stale_data_days"])
    except (TypeError, KeyError, ValueError):
        return DEFAULT_STALE_DAYS


def read_sources(root: Path, *, now: datetime | None = None) -> list[Source]:
    now = now or datetime.now(timezone.utc)
    limit = stale_days(root)
    out: list[Source] = []
    for name, rel in SOURCES:
        path = root / rel
        present = path.is_file()
        stamp = None
        if present and name not in UNDATED:
            holder = load_yaml(root / STAMP_FILE[name]) if name in STAMP_FILE else load_yaml(path)
            if isinstance(holder, dict):
                stamp = holder.get("generated_at")
        when = parse_stamp(stamp)
        age = None if when is None else max(0.0, (now - when).total_seconds() / 86400)
        out.append(
            Source(
                name=name,
                path=rel,
                present=present,
                generated_at=None if stamp is None else str(stamp),
                age_days=age,
                stale=age is not None and age > limit,
            )
        )
    return out


def data_mtimes(root: Path) -> dict[str, float]:
    """mtime of every watched file (0 when absent) — the TUI's change detector."""
    paths = [rel for _, rel in SOURCES] + list(STAMP_FILE.values())
    out = {}
    for rel in paths:
        p = root / rel
        out[rel] = p.stat().st_mtime if p.is_file() else 0.0
    return out


def load_snapshot(root: Path, *, now: datetime | None = None) -> Snapshot:
    rows, health_present = join_fleet(root)
    triage = load_yaml(root / "_data" / "fleet_triage.yml")
    attach_triage(rows, triage)
    harness = load_yaml(root / "_data" / "harness_health.yml")
    harness = harness if isinstance(harness, dict) else {}
    wires = [w for w in (harness.get("trip_wires") or []) if isinstance(w, dict)]
    return Snapshot(
        rows=rows,
        health_present=health_present,
        sources=read_sources(root, now=now),
        inbox=inbox_items(triage),
        triage=triage if isinstance(triage, dict) else {},
        trip_wires=sorted(wires, key=lambda w: not w.get("tripped")),
        scorecard={k: v for k, v in (harness.get("scorecard") or {}).items() if isinstance(v, dict)},
    )


def kpis(rows: list[AppRow]) -> dict[str, int]:
    return {
        "projects": len(rows),
        "active": sum(1 for r in rows if r.status == "active"),
        "submodules": sum(1 for r in rows if r.submodule_path),
        "featured": sum(1 for r in rows if r.featured),
        "red": sum(1 for r in rows if r.health == "red"),
        "amber": sum(1 for r in rows if r.health == "amber"),
        "green": sum(1 for r in rows if r.health == "green"),
        "checked_out": sum(1 for r in rows if r.checked_out),
        "triage_red": sum(1 for r in rows if r.triage_level == "red"),
        "triage_amber": sum(1 for r in rows if r.triage_level == "amber"),
        "failing": sum(len(r.failing) for r in rows),
    }


def cycle(preferred: tuple[str, ...], present: set[str]) -> tuple[str | None, ...]:
    """Filter cycle: None (all), the known values in house order, then any the
    registry grew that this file has not heard of — so a new category is
    filterable the day it lands instead of unreachable."""
    known = [v for v in preferred if v in present]
    extra = sorted(v for v in present if v and v not in preferred)
    return (None, *known, *extra)


def filter_rows(
    rows: list[AppRow],
    *,
    q: str = "",
    category: str | None = None,
    status: str | None = None,
    featured: bool | None = None,
    health: str | None = None,
) -> list[AppRow]:
    """`health` matches either attention signal, so a filter still works when
    only the committed triage snapshot is present."""
    needle = q.strip().lower()
    out = []
    for r in rows:
        if needle and needle not in r.haystack:
            continue
        if category and r.category != category:
            continue
        if status and r.status != status:
            continue
        if featured is True and not r.featured:
            continue
        if health and health not in (r.health, r.triage_level):
            continue
        out.append(r)
    return out


def sort_rows(rows: list[AppRow], key: str) -> list[AppRow]:
    if key == "name":
        return sorted(rows, key=lambda r: r.name.lower())
    if key == "health":
        return sorted(rows, key=lambda r: (LEVEL_RANK.get(r.health, 3), r.attention_rank, r.name.lower()))
    if key == "triage":
        return sorted(
            rows,
            key=lambda r: (LEVEL_RANK.get(r.triage_level, 3), -(r.triage_score or 0), r.name.lower()),
        )
    if key == "alerts":
        return sorted(rows, key=lambda r: (-r.security_alerts, r.name.lower()))
    if key == "recent":
        return sorted(
            rows,
            key=lambda r: (r.last_commit_days is None, r.last_commit_days if r.last_commit_days is not None else 10**9, r.name.lower()),
        )
    if key == "stars":
        return sorted(rows, key=lambda r: (-r.stars, r.name.lower()))
    featured = [r for r in rows if r.featured]
    rest = [r for r in rows if not r.featured]
    return sorted(featured, key=lambda r: r.name.lower()) + sorted(rest, key=lambda r: r.name.lower())


def flagged(rows: list[AppRow]) -> list[AppRow]:
    """Red/amber on EITHER signal, worst first. Health alone left this empty on
    every machine that had not run `dash-gen health` — i.e. by default."""
    return sorted(
        [r for r in rows if r.worst_level in ("red", "amber")],
        key=lambda r: (
            LEVEL_RANK.get(r.worst_level, 3),
            LEVEL_RANK.get(r.health, 3),
            r.attention_rank,
            -(r.triage_score or 0),
            r.name.lower(),
        ),
    )

#!/usr/bin/env python3
"""Join `_data/projects.yml` + `_data/project_health.yml` the way the Jekyll dash does.

No Textual, no network. The TUI and the tests both call this.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("docs", "full-stack-ai", "dev-tools", "dash")
STATUSES = ("active", "maintenance", "experiment", "archived")
LEVELS = ("red", "amber", "green")
SORTS = ("featured", "name", "health", "alerts", "recent", "stars")

DOT = {"red": "🔴", "amber": "🟠", "green": "🟢"}
CAT_LABEL = {
    "docs": "Docs",
    "full-stack-ai": "Full-stack / AI",
    "dev-tools": "Dev tools",
    "dash": "Dash",
}
LEVEL_RANK = {"red": 0, "amber": 1, "green": 2, None: 3}


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
    docker_name: str | None = None
    docker_status: str | None = None
    docker_running: bool = False

    @property
    def dot(self) -> str:
        return DOT.get(self.health or "", "·")

    @property
    def haystack(self) -> str:
        bits = [self.name, self.description, self.category, self.status, *self.stack]
        return " ".join(bits).lower()


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
                security_alerts=int(sec.get("alerts") or 0),
                reasons=list(att.get("reasons") or []),
                attention_rank=int(h.get("attention_rank") or 99),
                stars=int(h.get("stars") or 0),
            )
        )
    return rows, health_present


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
    }


def filter_rows(
    rows: list[AppRow],
    *,
    q: str = "",
    category: str | None = None,
    status: str | None = None,
    featured: bool | None = None,
    health: str | None = None,
) -> list[AppRow]:
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
        if health and r.health != health:
            continue
        out.append(r)
    return out


def sort_rows(rows: list[AppRow], key: str) -> list[AppRow]:
    if key == "name":
        return sorted(rows, key=lambda r: r.name.lower())
    if key == "health":
        return sorted(rows, key=lambda r: (LEVEL_RANK.get(r.health, 3), r.attention_rank, r.name.lower()))
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
    return sorted(
        [r for r in rows if r.health in ("red", "amber")],
        key=lambda r: (LEVEL_RANK.get(r.health, 3), r.attention_rank, r.name.lower()),
    )

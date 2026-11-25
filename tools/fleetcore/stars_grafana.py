#!/usr/bin/env python3
"""stars_grafana — the open-source radar in Grafana: the gauges, their two encodings, and
the `fleet-stars` dashboard (`tools/dash stars metrics`, `tools/dash stars grafana`).

Pure: `metrics(doc)` turns the committed document into gauge samples, `prom_text`
and `otlp_payload` encode them (the Prometheus text format to read; OTLP/JSON for
the local OTel collector, which Prometheus scrapes), and `grafana_dashboard()`
renders tools/observability/grafana/dashboards/fleet-stars.json, which is never
hand-edited. `tools/stargazer.py` pushes and writes.

Docs: docs/STARGAZER.md#grafana-the-radar-over-time.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


# --------------------------------------------------------------------------- #
# metrics: the radar as gauges → the OTel collector → Prometheus → Grafana
# --------------------------------------------------------------------------- #
METRICS_HELP = {
    "fleet_stars_repo_stars": "Stargazers of a repo on the radar",
    "fleet_stars_repo_gain_7d": "Stars a repo gained in the last 7 days (from the radar's history)",
    "fleet_stars_repo_stars_per_day": "Stars a day since a young repo was created",
    "fleet_stars_repo_similarity": "tf-idf similarity of a repo to its closest fleet project (0-1)",
    "fleet_stars_category_repos": "Starred repos in a category",
    "fleet_stars_language_repos": "Starred repos by primary language",
    "fleet_stars_project_matches": "Repos close to a fleet project, starred or discovered",
    "fleet_stars_ai_verdicts": "AI review verdicts across the radar",
    "fleet_stars_total": "Radar totals (starred, trending, relevant, to review, suspect, reviewed)",
}


def metrics(doc: dict) -> list[dict]:
    """The radar as gauge samples: one per repo per measure, labelled by repo, category, language, health,
    starred, closest project and AI verdict, then the counts by category, language, project and verdict,
    and the totals. Prometheus keeps the history, so a refresh a day draws each repo's stars over time."""
    out: list[dict] = []

    def g(name: str, value: Any, **attrs: Any) -> None:
        out.append({"name": name, "value": float(value or 0),
                    "attrs": {k: str(v) for k, v in attrs.items() if v not in (None, "")}})

    for n, r in sorted((doc.get("repos") or {}).items()):
        best = (r.get("matches") or [{}])[0]
        base = {"repo": n, "category": r.get("category"), "language": r.get("language") or "none",
                "health": r.get("health"), "starred": "true" if r.get("starred_at") else "false",
                "project": best.get("project") or "none", "verdict": (r.get("ai") or {}).get("verdict") or "none",
                "suspect": "true" if r.get("suspect") else "false"}
        g("fleet_stars_repo_stars", r.get("stars"), **base)
        v = r.get("velocity") or {}
        if v.get("d7") is not None:
            g("fleet_stars_repo_gain_7d", v["d7"], **base)
        if v.get("per_day") is not None:
            g("fleet_stars_repo_stars_per_day", v["per_day"], **base)
        if best.get("score") is not None:
            g("fleet_stars_repo_similarity", best["score"], **base)
    for c in doc.get("categories") or []:
        g("fleet_stars_category_repos", c.get("starred"), category=c.get("id"), title=c.get("title"))
    for x in doc.get("languages") or []:
        g("fleet_stars_language_repos", x.get("count"), language=x.get("name"))
    for f in doc.get("fleet") or []:
        g("fleet_stars_project_matches", len(f.get("starred") or []), project=f.get("project"), source="starred")
        g("fleet_stars_project_matches", len(f.get("discovered") or []), project=f.get("project"), source="discovered")
    for verdict, n in sorted(((doc.get("ai") or {}).get("verdicts") or {}).items()):
        g("fleet_stars_ai_verdicts", n, verdict=verdict)
    for k, v in sorted((doc.get("totals") or {}).items()):
        g("fleet_stars_total", v, kind=k)
    g("fleet_stars_total", (doc.get("ai") or {}).get("reviewed") or 0, kind="ai_reviewed")
    return out


def prom_text(samples: list[dict]) -> str:
    """Samples in the Prometheus text format: what Prometheus will show once the collector exports them."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    families: dict[str, list[dict]] = {}
    for x in samples:  # a family's samples must be contiguous in the text format
        families.setdefault(x["name"], []).append(x)
    lines = []
    for name, rows in families.items():
        lines += [f"# HELP {name} {METRICS_HELP.get(name, '')}", f"# TYPE {name} gauge"]
        for x in rows:
            labels = ",".join(f'{k}="{esc(v)}"' for k, v in sorted(x["attrs"].items()))
            lines.append(f"{name}{{{labels}}} {x['value']:g}")
    return "\n".join(lines) + "\n"


def otlp_payload(samples: list[dict], now: datetime, service: str = "stargazer") -> dict:
    """OTLP/JSON for the collector's /v1/metrics: one gauge per metric name, every sample a data point."""
    stamp = str(int(now.timestamp() * 1_000_000_000))
    by_name: dict[str, dict] = {}
    for s in samples:
        m = by_name.setdefault(s["name"], {"name": s["name"], "description": METRICS_HELP.get(s["name"], ""),
                                           "gauge": {"dataPoints": []}})
        m["gauge"]["dataPoints"].append({"timeUnixNano": stamp, "asDouble": s["value"],
                                         "attributes": [{"key": k, "value": {"stringValue": v}}
                                                        for k, v in sorted(s["attrs"].items())]})
    return {"resourceMetrics": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
        "scopeMetrics": [{"scope": {"name": "fleet.stars"}, "metrics": list(by_name.values())}]}]}


# --------------------------------------------------------------------------- #
# the Grafana dashboard (tools/observability/grafana/dashboards/fleet-stars.json)
# --------------------------------------------------------------------------- #
GRAFANA_UID = "fleet-stars"
GRAFANA_DATASOURCE = {"type": "prometheus", "uid": "fleet-prometheus"}  # pinned in provisioning/datasources


def grafana_dashboard() -> dict:
    """The radar in Grafana, rendered (never hand-edited): totals, what is starred by category and language,
    stars over time for the repos gaining most, the fastest risers, the closest to the fleet, matches per
    fleet project and the AI verdicts. Values are `last_over_time(…[30d])`, so a panel keeps the last push
    between refreshes; the series themselves expire from the collector an hour after a push."""
    ds = GRAFANA_DATASOURCE
    panels: list[dict] = []
    pid = iter(range(1, 100))

    def target(expr: str, legend: str = "", instant: bool = False, fmt: str = "time_series") -> dict:
        t = {"datasource": ds, "expr": expr, "legendFormat": legend, "refId": "A", "format": fmt}
        if instant:
            t.update(instant=True, range=False)
        return t

    def add(kind: str, title: str, x: int, y: int, w: int, h: int, targets: list[dict], description: str = "",
            options: dict | None = None, field: dict | None = None, transformations: list | None = None) -> None:
        p = {"id": next(pid), "type": kind, "title": title, "description": description, "datasource": ds,
             "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
             "options": options or {}, "fieldConfig": {"defaults": field or {}, "overrides": []}}
        if transformations:
            p["transformations"] = transformations
        panels.append(p)

    for i, (kind, title) in enumerate((("starred", "Starred"), ("trending", "Trending"), ("starred_relevant", "Starred, like the fleet"),
                                       ("incorporate", "To review"), ("suspect", "Suspect"), ("ai_reviewed", "AI-reviewed"))):
        add("stat", title, 4 * i, 0, 4, 4, [target(f'last_over_time(fleet_stars_total{{kind="{kind}"}}[30d])', title, instant=True)],
            options={"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "none"},
            field={"color": {"mode": "fixed", "fixedColor": "red" if kind == "suspect" else "blue"}})
    add("bargauge", "What is starred, by category", 0, 4, 12, 10,
        [target("sort_desc(last_over_time(fleet_stars_category_repos[30d]))", "{{title}}", instant=True)],
        options={"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True,
                 "reduceOptions": {"calcs": ["lastNotNull"], "values": False}})
    add("piechart", "Languages of the starred repos", 12, 4, 12, 10,
        [target("topk(10, last_over_time(fleet_stars_language_repos[30d]))", "{{language}}", instant=True)],
        options={"pieType": "donut", "legend": {"displayMode": "table", "placement": "right", "values": ["value"]},
                 "reduceOptions": {"calcs": ["lastNotNull"]}})
    add("timeseries", "Stars over time: the ten most-starred of your stars", 0, 14, 16, 11,
        [target('max by (repo) (max_over_time(fleet_stars_repo_stars{starred="true"}[1d])) and on (repo) '
                'topk(10, max by (repo) (last_over_time(fleet_stars_repo_stars{starred="true"}[2d])))', "{{repo}}")],
        description="Each point is the day's highest count: one push a refresh (daily while the loop runs) lives an hour "
                    "in the collector, so a daily window draws a continuous line. A line starts the day the repo joined the radar.",
        options={"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull"]}},
        field={"custom": {"spanNulls": True, "lineWidth": 2}})

    def table(title: str, x: int, y: int, w: int, h: int, expr: str, value: str, hide: tuple, order: list,
              description: str = "", no_value: str = "", decimals: int | None = None) -> None:
        exclude = {k: True for k in ("Time", "__name__", "job", "instance", "otel_scope_name", "otel_scope_version", *hide)}
        field: dict = {"noValue": no_value} if no_value else {}
        if decimals is not None:
            field["decimals"] = decimals
        add("table", title, x, y, w, h, [target(expr, instant=True, fmt="table")], description=description,
            options={"showHeader": True, "cellHeight": "sm"}, field=field,
            transformations=[{"id": "organize", "options": {"excludeByName": exclude, "renameByName": {"Value": value},
                                                             "indexByName": {k: i for i, k in enumerate([*order, "Value"])}}}])

    table("Gaining this week", 16, 14, 8, 11,
          'topk(15, max by (repo) (last_over_time(fleet_stars_repo_gain_7d{starred="true"}[2d])))', "+7 days", (), ["repo"],
          description="Stars gained in the last 7 days, from the radar's own history.",
          no_value="needs 7 days of history")
    table("Rising fastest: stars a day since creation", 0, 25, 12, 11,
          'topk(15, max by (repo, category, project) (last_over_time(fleet_stars_repo_stars_per_day{suspect="false"}[2d])))',
          "stars a day", (), ["repo", "category", "project"])
    # Grouped by labels that do not churn: a verdict or a health that changed between two pushes would list
    # the repo twice for the length of the window. The verdicts have their own panel.
    table("Closest to the fleet (similarity)", 12, 25, 12, 11,
          'topk(20, max by (repo, project, starred) (last_over_time(fleet_stars_repo_similarity{suspect="false"}[2d])))',
          "similarity", (), ["repo", "project", "starred"], decimals=2)
    add("bargauge", "Starred repos close to each fleet project", 0, 36, 16, 14,
        [target('sort_desc(last_over_time(fleet_stars_project_matches{source="starred"}[30d]) > 0)', "{{project}}", instant=True)],
        options={"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True, "valueMode": "color",
                 "reduceOptions": {"calcs": ["lastNotNull"], "values": False}})
    add("piechart", "AI verdicts", 16, 36, 8, 14,
        [target("last_over_time(fleet_stars_ai_verdicts[30d])", "{{verdict}}", instant=True)],
        description="adopt · borrow · watch · skip, from `tools/dash stars review --yes`.",
        options={"pieType": "pie", "legend": {"displayMode": "table", "placement": "bottom", "values": ["value"]},
                 "reduceOptions": {"calcs": ["lastNotNull"]}},
        field={"noValue": "run tools/dash stars review --yes"})
    return {
        "uid": GRAFANA_UID, "title": "Fleet — open-source radar", "tags": ["fleet", "stars"],
        "description": "The account's GitHub stars, the trending repos and the repos like each fleet project "
                       "(docs/STARGAZER.md). Rendered by `tools/dash stars grafana --write`; fed by `tools/dash stars metrics --push`.",
        "editable": False, "graphTooltip": 1, "schemaVersion": 39, "version": 1, "refresh": "",
        "time": {"from": "now-30d", "to": "now"}, "timezone": "utc", "templating": {"list": []},
        "annotations": {"list": []}, "links": [], "panels": panels,
    }

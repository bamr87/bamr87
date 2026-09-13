#!/usr/bin/env python3
"""
machine_api — publish a stable, agent-facing JSON surface on the dash site.

The human dashboards (/monitor/, /triage/, /dashboard/) already render the
fleet registries. Agents hitting those URLs get Bootstrap HTML. This module
projects the same committed (and optional ephemeral) signals into compact
JSON under ``{out}/api/v1/`` plus a root ``llms.txt`` discovery file, so a
bot's first GET can be ``/api/v1/index.json`` and then prioritize work from
``fleet.json`` without scraping.

Inputs (all optional — missing files degrade that endpoint, never crash):

  _data/fleet_triage.yml       priority inbox + open-state totals
  _data/project_health.yml     per-repo attention (ephemeral, build-time)
  _data/project_health_meta.yml
  _data/harness_health.yml     scorecard + trip wires
  _data/issue_pipeline.yml     three-tier pipeline stages
  _data/projects.yml           registry (name/status/url only, for index)

Output (written under ``--out``, default ``_site`` after Jekyll build):

  api/v1/index.json
  api/v1/fleet.json
  api/v1/health.json
  api/v1/harness.json
  api/v1/issues.json
  llms.txt

No secrets. Public registry facts only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("machine_api requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "1.0"
SITE_BASE = "https://bamr87.github.io/bamr87"
RAW_BASE = "https://raw.githubusercontent.com/bamr87/bamr87/main"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load_yaml(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        sys.stderr.write(f"machine_api: could not read {path}: {exc}\n")
        return None


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )


def compact_inbox(inbox: list | None, *, limit: int = 50) -> list[dict]:
    out: list[dict] = []
    for item in inbox or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "kind": item.get("kind"),
                "repo": item.get("repo"),
                "nwo": item.get("nwo"),
                "ref": item.get("ref"),
                "title": item.get("title"),
                "why": item.get("why"),
                "url": item.get("url"),
                "priority": item.get("priority"),
                "age_days": item.get("age_days"),
            }
        )
        if len(out) >= limit:
            break
    return out


def compact_by_repo(by_repo: list | None, *, limit: int = 80) -> list[dict]:
    out: list[dict] = []
    for row in by_repo or []:
        if not isinstance(row, dict):
            continue
        attention = row.get("attention") or {}
        issues = row.get("issues") or {}
        prs = row.get("prs") or {}
        workflows = row.get("workflows") or {}
        failing = workflows.get("failing") or []
        out.append(
            {
                "name": row.get("name"),
                "nwo": row.get("nwo") or row.get("full_name"),
                "repo_url": row.get("repo_url"),
                "attention": {
                    "level": attention.get("level"),
                    "reasons": attention.get("reasons") or [],
                },
                "issues_open": issues.get("open"),
                "prs_open": prs.get("open"),
                "workflows_failing": len(failing) if isinstance(failing, list) else failing,
                "external": bool(row.get("external")),
            }
        )
        if len(out) >= limit:
            break
    return out


def build_fleet(triage: dict | None) -> dict:
    if not triage:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "degraded",
            "reason": "fleet_triage.yml missing — wait for fleet-pulse or run tools/dash triage",
            "generated_at": now_utc(),
            "source": "fleet_triage",
            "totals": {},
            "inbox": [],
            "by_repo": [],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "generated_at": triage.get("generated_at") or now_utc(),
        "emitted_at": now_utc(),
        "source": "fleet_triage",
        "repos_scanned": triage.get("repos_scanned"),
        "totals": triage.get("totals") or {},
        "inbox": compact_inbox(triage.get("inbox")),
        "by_repo": compact_by_repo(triage.get("by_repo")),
        "human": f"{SITE_BASE}/triage/",
        "raw": f"{RAW_BASE}/_data/fleet_triage.yml",
    }


def build_health(health: Any, meta: dict | None) -> dict:
    if health is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "degraded",
            "reason": "project_health.yml missing — generated at deploy by dash-gen health",
            "generated_at": (meta or {}).get("generated_at") or now_utc(),
            "source": "project_health",
            "repos": [],
            "counts": {"red": 0, "amber": 0, "green": 0},
            "fallback": f"{SITE_BASE}/api/v1/fleet.json",
            "human": f"{SITE_BASE}/monitor/",
        }

    rows = health if isinstance(health, list) else (health.get("repos") or health.get("projects") or [])
    repos: list[dict] = []
    counts = {"red": 0, "amber": 0, "green": 0}
    for h in rows:
        if not isinstance(h, dict):
            continue
        level = ((h.get("attention") or {}).get("level")) or "green"
        if level in counts:
            counts[level] += 1
        ci = h.get("ci") or {}
        issues = h.get("issues") or {}
        prs = h.get("prs") or {}
        activity = h.get("activity") or {}
        security = h.get("security") or {}
        repos.append(
            {
                "name": h.get("name"),
                "repo_url": h.get("repo_url"),
                "attention": {
                    "level": level,
                    "reasons": (h.get("attention") or {}).get("reasons") or [],
                    "rank": h.get("attention_rank"),
                },
                "ci": {
                    "last": ci.get("last"),
                    "pass_rate": ci.get("pass_rate"),
                },
                "issues": {
                    "open": issues.get("open"),
                    "bugs": issues.get("bugs"),
                    "stale": issues.get("stale"),
                },
                "prs": {
                    "open": prs.get("open"),
                    "stale": prs.get("stale"),
                },
                "activity": {
                    "last_commit_days": activity.get("last_commit_days"),
                    "commits_30d": activity.get("commits_30d"),
                },
                "security_alerts": security.get("alerts"),
            }
        )
    repos.sort(key=lambda r: (r["attention"].get("rank") if r["attention"].get("rank") is not None else 9, r.get("name") or ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "generated_at": (meta or {}).get("generated_at") or now_utc(),
        "emitted_at": now_utc(),
        "source": "project_health",
        "counts": counts,
        "repos": repos,
        "human": f"{SITE_BASE}/monitor/",
    }


def build_harness(harness: dict | None) -> dict:
    if not harness:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "degraded",
            "reason": "harness_health.yml missing",
            "generated_at": now_utc(),
            "source": "harness_health",
            "scorecard": {},
            "trip_wires": [],
        }
    wires = harness.get("trip_wires") or []
    tripped = [w for w in wires if isinstance(w, dict) and w.get("tripped")]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "generated_at": harness.get("generated_at") or now_utc(),
        "emitted_at": now_utc(),
        "source": "harness_health",
        "scorecard": harness.get("scorecard") or {},
        "trip_wires": wires,
        "tripped_count": len(tripped),
        "human": f"{SITE_BASE}/harness/",
        "raw": f"{RAW_BASE}/_data/harness_health.yml",
    }


def build_issues(pipeline: dict | None) -> dict:
    if not pipeline:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "degraded",
            "reason": "issue_pipeline.yml missing",
            "generated_at": now_utc(),
            "source": "issue_pipeline",
            "totals": {},
            "caps": {},
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "generated_at": pipeline.get("generated_at") or now_utc(),
        "emitted_at": now_utc(),
        "source": "issue_pipeline",
        "enabled": pipeline.get("enabled"),
        "repos_scanned": pipeline.get("repos_scanned"),
        "totals": pipeline.get("totals") or {},
        "caps": pipeline.get("caps") or {},
        "labels": pipeline.get("labels") or {},
        "human": f"{SITE_BASE}/issue-pipeline/",
        "raw": f"{RAW_BASE}/_data/issue_pipeline.yml",
    }


def build_index(*, fleet: dict, health: dict, harness: dict, issues: dict) -> dict:
    endpoints = [
        {
            "path": "/api/v1/index.json",
            "purpose": "Discovery document — start here",
            "status": "ok",
        },
        {
            "path": "/api/v1/fleet.json",
            "purpose": "Priority inbox + open-state totals across the fleet",
            "status": fleet.get("status"),
            "freshness": fleet.get("generated_at"),
        },
        {
            "path": "/api/v1/health.json",
            "purpose": "Per-repo attention board (red/amber/green)",
            "status": health.get("status"),
            "freshness": health.get("generated_at"),
        },
        {
            "path": "/api/v1/harness.json",
            "purpose": "Harness scorecard + tripped trip wires",
            "status": harness.get("status"),
            "freshness": harness.get("generated_at"),
        },
        {
            "path": "/api/v1/issues.json",
            "purpose": "Three-tier issue pipeline stages and caps",
            "status": issues.get("status"),
            "freshness": issues.get("generated_at"),
        },
        {
            "path": "/llms.txt",
            "purpose": "Plain-text agent discovery (llms.txt convention)",
            "status": "ok",
        },
    ]
    priority_hint = None
    inbox = fleet.get("inbox") or []
    if inbox:
        top = inbox[0]
        priority_hint = {
            "kind": top.get("kind"),
            "repo": top.get("repo"),
            "title": top.get("title"),
            "url": top.get("url"),
            "priority": top.get("priority"),
            "why": top.get("why"),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "emitted_at": now_utc(),
        "base_url": SITE_BASE,
        "repo": "bamr87/bamr87",
        "purpose": "Machine-readable fleet command center for coding agents",
        "how_to_use": [
            "GET /api/v1/index.json first",
            "Then GET /api/v1/fleet.json and work inbox[] in order (highest priority first)",
            "Use /api/v1/health.json for per-repo attention levels when present",
            "Human mirrors: /triage/ and /monitor/",
        ],
        "priority_hint": priority_hint,
        "endpoints": [{"url": SITE_BASE + e["path"], **e} for e in endpoints],
        "raw_sources": {
            "fleet_triage": f"{RAW_BASE}/_data/fleet_triage.yml",
            "harness_health": f"{RAW_BASE}/_data/harness_health.yml",
            "issue_pipeline": f"{RAW_BASE}/_data/issue_pipeline.yml",
            "projects": f"{RAW_BASE}/_data/projects.yml",
        },
        "human_hubs": {
            "home": f"{SITE_BASE}/",
            "triage": f"{SITE_BASE}/triage/",
            "monitor": f"{SITE_BASE}/monitor/",
            "dashboard": f"{SITE_BASE}/dashboard/",
            "issue_pipeline": f"{SITE_BASE}/issue-pipeline/",
            "harness": f"{SITE_BASE}/harness/",
        },
    }


def build_llms_txt(index: dict) -> str:
    lines = [
        "# bamr87 dash — machine-readable fleet hub",
        f"# Emitted: {index.get('emitted_at')}",
        "",
        "> Quick check for coding agents: prioritize and address fleet issues/PRs/CI.",
        "",
        "## Start here",
        "",
        f"- Index (JSON): {SITE_BASE}/api/v1/index.json",
        f"- Fleet priority inbox: {SITE_BASE}/api/v1/fleet.json",
        f"- Per-repo health: {SITE_BASE}/api/v1/health.json",
        f"- Harness scorecard: {SITE_BASE}/api/v1/harness.json",
        f"- Issue pipeline: {SITE_BASE}/api/v1/issues.json",
        "",
        "## How to prioritize",
        "",
        "1. Fetch index.json, then fleet.json.",
        "2. Work `inbox[]` in array order (already priority-sorted; failing workflows first).",
        "3. Cross-check health.json attention.level (red > amber > green) when available.",
        "4. Prefer agent:ready / P0-P1 labeled work; skip agent:blocked unless unblocking.",
        "",
        "## Human mirrors",
        "",
        f"- Triage: {SITE_BASE}/triage/",
        f"- Monitor: {SITE_BASE}/monitor/",
        f"- Dashboard: {SITE_BASE}/dashboard/",
        "",
        "## Raw registries (GitHub)",
        "",
        f"- fleet_triage: {RAW_BASE}/_data/fleet_triage.yml",
        f"- harness_health: {RAW_BASE}/_data/harness_health.yml",
        f"- issue_pipeline: {RAW_BASE}/_data/issue_pipeline.yml",
        f"- projects: {RAW_BASE}/_data/projects.yml",
        "",
        f"Repo: https://github.com/bamr87/bamr87",
        "",
    ]
    hint = index.get("priority_hint")
    if hint:
        lines[5:5] = [
            f"Top inbox item right now: [{hint.get('kind')}] {hint.get('repo')} — {hint.get('title')} ({hint.get('url')})",
            "",
        ]
    return "\n".join(lines)


def emit(out_root: Path, data_root: Path) -> dict[str, Path]:
    triage = load_yaml(data_root / "fleet_triage.yml")
    health = load_yaml(data_root / "project_health.yml")
    health_meta = load_yaml(data_root / "project_health_meta.yml")
    harness = load_yaml(data_root / "harness_health.yml")
    pipeline = load_yaml(data_root / "issue_pipeline.yml")

    fleet = build_fleet(triage if isinstance(triage, dict) else None)
    health_doc = build_health(health, health_meta if isinstance(health_meta, dict) else None)
    harness_doc = build_harness(harness if isinstance(harness, dict) else None)
    issues_doc = build_issues(pipeline if isinstance(pipeline, dict) else None)
    index = build_index(fleet=fleet, health=health_doc, harness=harness_doc, issues=issues_doc)

    api = out_root / "api" / "v1"
    written = {
        "index": api / "index.json",
        "fleet": api / "fleet.json",
        "health": api / "health.json",
        "harness": api / "harness.json",
        "issues": api / "issues.json",
        "llms": out_root / "llms.txt",
    }
    write_json(written["index"], index)
    write_json(written["fleet"], fleet)
    write_json(written["health"], health_doc)
    write_json(written["harness"], harness_doc)
    write_json(written["issues"], issues_doc)
    written["llms"].write_text(build_llms_txt(index), encoding="utf-8")

    # Best-effort: point robots.txt at llms.txt if a theme robots already exists.
    robots = out_root / "robots.txt"
    if robots.is_file():
        text = robots.read_text(encoding="utf-8")
        if "llms.txt" not in text:
            robots.write_text(
                text.rstrip() + f"\n\n# Agent discovery\n# {SITE_BASE}/llms.txt\n# {SITE_BASE}/api/v1/index.json\n",
                encoding="utf-8",
            )
    else:
        robots.write_text(
            f"Sitemap: {SITE_BASE}/sitemap.xml\n\n"
            f"# Agent discovery\n# {SITE_BASE}/llms.txt\n# {SITE_BASE}/api/v1/index.json\n",
            encoding="utf-8",
        )
        written["robots"] = robots

    return written


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "_site",
        help="Site root to write into (default: _site after jekyll build)",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=REPO_ROOT / "_data",
        help="Registry directory (default: _data)",
    )
    parser.set_defaults(func=cmd_machine_api)


def cmd_machine_api(args: argparse.Namespace) -> int:
    written = emit(args.out.resolve(), args.data.resolve())
    for label, path in written.items():
        rel = path
        try:
            rel = path.relative_to(REPO_ROOT)
        except ValueError:
            pass
        print(f"machine_api: wrote {label} -> {rel}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    ns = parser.parse_args()
    raise SystemExit(ns.func(ns))

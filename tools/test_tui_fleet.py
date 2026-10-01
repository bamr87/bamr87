#!/usr/bin/env python3
"""Fixture tests for tools/tui/fleet.py — the terminal dash data layer.

Guards the same join/filter/sort rules the Jekyll command center uses, so the
TUI cannot drift from `_data/projects.yml` + `_data/project_health.yml`.

    python3 tools/test_tui_fleet.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent / "tui"))

import fleet as fl  # noqa: E402
import host as dh  # noqa: E402


def write_reg(tmp: Path, projects, health=None) -> Path:
    data = tmp / "_data"
    data.mkdir()
    (data / "projects.yml").write_text(yaml.safe_dump(projects), encoding="utf-8")
    if health is not None:
        (data / "project_health.yml").write_text(yaml.safe_dump(health), encoding="utf-8")
    (tmp / "projects" / "it-journey").mkdir(parents=True)
    (tmp / "projects" / "it-journey" / "README.md").write_text("x", encoding="utf-8")
    return tmp


SAMPLE = [
    {
        "name": "it-journey",
        "description": "learning platform",
        "category": "docs",
        "status": "active",
        "featured": True,
        "stack": ["jekyll"],
        "repo_url": "https://github.com/bamr87/it-journey",
        "submodule_path": "projects/it-journey",
    },
    {
        "name": "wtd",
        "description": "todo tui",
        "category": "dev-tools",
        "status": "archived",
        "featured": False,
        "stack": ["python"],
        "repo_url": "https://github.com/bamr87/wtd",
        "submodule_path": "projects/wtd",
    },
    {
        "name": "SCHEMA",
        "description": "external kit",
        "category": "dash",
        "status": "active",
        "featured": False,
        "stack": [],
        "repo_url": "https://github.com/bamr87/SCHEMA",
    },
]

HEALTH = [
    {
        "name": "it-journey",
        "stars": 12,
        "ci": {"last": "success", "pass_rate": 100},
        "issues": {"open": 1},
        "prs": {"open": 0},
        "activity": {"last_commit_days": 2, "commits_30d": 8},
        "security": {"alerts": 0},
        "attention": {"level": "green", "reasons": ["healthy"]},
        "attention_rank": 3,
    },
    {
        "name": "wtd",
        "stars": 1,
        "ci": {"last": "failure", "pass_rate": 40},
        "issues": {"open": 4},
        "prs": {"open": 2},
        "activity": {"last_commit_days": 90, "commits_30d": 0},
        "security": {"alerts": 3},
        "attention": {"level": "red", "reasons": ["CI failing", "stale"]},
        "attention_rank": 1,
    },
]


def test_join_with_health():
    with tempfile.TemporaryDirectory() as td:
        root = write_reg(Path(td), SAMPLE, HEALTH)
        rows, present = fl.join_fleet(root)
        assert present is True
        assert [r.name for r in rows] == ["it-journey", "wtd", "SCHEMA"]
        ij = rows[0]
        assert ij.health == "green"
        assert ij.featured is True
        assert ij.checked_out is True
        assert ij.ci_pass == 100
        wtd = rows[1]
        assert wtd.health == "red"
        assert wtd.checked_out is False
        assert wtd.security_alerts == 3
        ext = rows[2]
        assert ext.submodule_path is None
        assert ext.health is None


def test_join_degrades_without_health():
    with tempfile.TemporaryDirectory() as td:
        root = write_reg(Path(td), SAMPLE, health=None)
        rows, present = fl.join_fleet(root)
        assert present is False
        assert len(rows) == 3
        assert all(r.health is None for r in rows)
        assert rows[0].checked_out is True


def test_kpis_and_filters():
    with tempfile.TemporaryDirectory() as td:
        rows, _ = fl.join_fleet(write_reg(Path(td), SAMPLE, HEALTH))
        k = fl.kpis(rows)
        assert k == {
            "projects": 3,
            "active": 2,
            "submodules": 2,
            "featured": 1,
            "red": 1,
            "amber": 0,
            "green": 1,
            "checked_out": 1,
            "triage_red": 0,
            "triage_amber": 0,
            "failing": 0,
        }
        assert [r.name for r in fl.filter_rows(rows, q="jekyll")] == ["it-journey"]
        assert [r.name for r in fl.filter_rows(rows, category="dev-tools")] == ["wtd"]
        assert [r.name for r in fl.filter_rows(rows, status="active", featured=True)] == ["it-journey"]
        assert [r.name for r in fl.filter_rows(rows, health="red")] == ["wtd"]
        assert [r.name for r in fl.flagged(rows)] == ["wtd"]


def test_sorts():
    with tempfile.TemporaryDirectory() as td:
        rows, _ = fl.join_fleet(write_reg(Path(td), SAMPLE, HEALTH))
        assert [r.name for r in fl.sort_rows(rows, "featured")][0] == "it-journey"
        assert [r.name for r in fl.sort_rows(rows, "name")] == ["it-journey", "SCHEMA", "wtd"]
        assert [r.name for r in fl.sort_rows(rows, "health")][0] == "wtd"
        assert [r.name for r in fl.sort_rows(rows, "alerts")][0] == "wtd"
        assert [r.name for r in fl.sort_rows(rows, "recent")][0] == "it-journey"
        assert [r.name for r in fl.sort_rows(rows, "stars")][0] == "it-journey"


def test_docker_match_and_attach():
    with tempfile.TemporaryDirectory() as td:
        rows, _ = fl.join_fleet(write_reg(Path(td), SAMPLE, HEALTH))
        boxes = [
            dh.Container(name="it-journey-jekyll-1", state="running", status="Up 3h", project="it-journey"),
            dh.Container(name="forge-stack-postgres-1", state="running", status="Up 3h", project="forge-stack"),
            dh.Container(
                name="custom",
                state="exited",
                status="Exited 1",
                project="",
                labels={"bamr87.project": "wtd"},
            ),
        ]
        hit = dh.match_container(rows[0], boxes)
        assert hit is not None and hit.project == "it-journey"
        dh.attach(rows, boxes)
        assert rows[0].docker_running is True
        assert (rows[0].docker_up, rows[0].docker_total) == (1, 1)
        assert rows[1].docker_name == "custom"
        assert rows[1].docker_running is False
        assert (rows[1].docker_up, rows[1].docker_total) == (0, 1)
        assert rows[2].docker_name is None
        assert boxes[1].owner is None  # forge-stack is not a registry project


def test_docker_fleet_label_is_authoritative():
    """UPS-OPS-17's com.bamr87.fleet.project wins over every heuristic — and a
    label naming a project outside the registry (the hub says `bamr87`) is
    attributed to nothing, not guessed onto a lookalike row."""
    rows = [fl.AppRow(name="it-journey"), fl.AppRow(name="wtd")]
    labelled = dh.Container(
        name="it-journey-web-1", state="running", status="Up", project="it-journey",
        labels={"com.bamr87.fleet.project": "wtd"},
    )
    hub = dh.Container(
        name="it-journey-console-1", state="running", status="Up", project="fleet",
        labels={"com.bamr87.fleet.project": "bamr87"},
    )
    assert dh.owner(labelled, rows).name == "wtd"
    assert dh.owner(hub, rows) is None
    assert labelled.fleet_project == "wtd"


def test_docker_longest_key_wins():
    """`cv-builder-pro-web-1` prefix-matches `cv` too; the registry has several
    such pairs (cv / cv-builder-pro, zer0-pages / zer0-pages-remote)."""
    rows = [
        fl.AppRow(name="cv"),
        fl.AppRow(name="cv-builder-pro"),
        fl.AppRow(name="zer0-pages"),
        fl.AppRow(name="zer0-pages-remote"),
    ]
    boxes = [
        dh.Container(name="cv-builder-pro-web-1", state="running", status="Up"),
        dh.Container(name="zer0-pages-remote-jekyll-1", state="exited", status="Exited"),
        dh.Container(name="cv-app-1", state="running", status="Up"),
        dh.Container(name="cvs-1", state="running", status="Up"),
    ]
    dh.attach(rows, boxes)
    owners = {c.name: c.owner for c in boxes}
    assert owners == {
        "cv-builder-pro-web-1": "cv-builder-pro",
        "zer0-pages-remote-jekyll-1": "zer0-pages-remote",
        "cv-app-1": "cv",
        "cvs-1": None,
    }
    # an explicit label reaches a short name the heuristics would be wary of
    labelled = dh.Container(name="x", state="running", status="Up", labels={"com.bamr87.fleet.project": "cv"})
    assert dh.owner(labelled, rows).name == "cv"
    assert rows[0].docker_total == 1 and rows[2].docker_total == 0


def test_docker_hosts_parsing():
    old = os.environ.get("DASH_DOCKER_HOST")
    try:
        os.environ["DASH_DOCKER_HOST"] = " local, ssh://forge ,,local "
        assert dh.docker_hosts() == ["local", "ssh://forge"]
        assert dh.docker_host() == "local"
        os.environ["DASH_DOCKER_HOST"] = ""
        assert dh.docker_hosts() == [] and dh.docker_host() == ""
    finally:
        if old is None:
            os.environ.pop("DASH_DOCKER_HOST", None)
        else:
            os.environ["DASH_DOCKER_HOST"] = old
    assert dh.host_label("local") == "local"
    assert dh.host_label("ssh://forge") == "forge"
    assert dh._command("local")[:2] == ["docker", "ps"]
    assert dh._command("ssh://forge")[:3] == ["docker", "-H", "ssh://forge"]


def test_docker_list_all_keeps_errors_per_host():
    real = dh.list_containers

    def fake(host, timeout=8):
        if host == "ssh://forge":
            return [], "ssh: connect to host forge.local port 22: Host is down"
        return [dh.Container(name="a", state="running", status="Up", host=dh.host_label(host))], None

    dh.list_containers = fake
    try:
        boxes, errors = dh.list_all(["local", "ssh://forge"])
    finally:
        dh.list_containers = real
    assert [c.name for c in boxes] == ["a"]
    assert list(errors) == ["forge"]


TRIAGE = {
    "generated_at": "2026-09-30 06:03 UTC",
    "by_repo": [
        {
            # URL differs in case, trailing slash and .git — still the same repo
            "name": "it-journey",
            "repo_url": "https://github.com/BAMR87/it-journey.git/",
            "issues": {"open": 3, "items": [
                {"number": 7, "title": "[bug] crash on load", "labels": ["Bug"], "age_days": 9, "idle_days": 2,
                 "url": "https://github.com/bamr87/it-journey/issues/7"},
                {"number": 8, "title": "docs", "labels": [], "age_days": 40, "idle_days": 30,
                 "url": "https://github.com/bamr87/it-journey/issues/8"},
            ]},
            "prs": {"open": 1, "items": [
                {"number": 9, "title": "feat: x", "draft": True, "dependabot": False, "ci": "fail",
                 "age_days": 3, "idle_days": 1, "url": "https://github.com/bamr87/it-journey/pull/9"},
            ]},
            "workflows": {"active": 4, "failing": [
                {"workflow": "CI", "path": ".github/workflows/ci.yml", "conclusion": "failure",
                 "run_url": "https://github.com/bamr87/it-journey/actions/runs/1"},
            ]},
            "attention": {"score": 42, "level": "amber", "reasons": ["1 failing workflow(s)"]},
        },
        {
            # no URL match: falls back to the name
            "name": "SCHEMA",
            "repo_url": "https://github.com/someone-else/SCHEMA",
            "attention": {"score": 120, "level": "red", "reasons": ["5 stale PR(s)"]},
        },
        {"name": "bamr87 (hub)", "repo_url": "https://github.com/bamr87/bamr87",
         "attention": {"score": 300, "level": "red", "reasons": ["hub"]}},
    ],
    "inbox": [
        {"kind": "issue", "repo": "it-journey", "ref": "#8", "title": "docs", "why": "issue idle 30d",
         "age_days": 40, "url": "u8", "priority": 40},
        {"kind": "workflow", "repo": "it-journey", "ref": ".github/workflows/ci.yml", "title": "CI",
         "why": "latest run failure", "age_days": None, "url": "u1", "priority": 90},
        {"kind": "pr", "repo": "bamr87 (hub)", "ref": "#5", "title": "[/x] hub pr", "why": "PR idle 9d",
         "age_days": 9, "url": "u5", "priority": 55},
    ],
}


def test_triage_join_and_kpis():
    with tempfile.TemporaryDirectory() as td:
        rows, _ = fl.join_fleet(write_reg(Path(td), SAMPLE, HEALTH))
        fl.attach_triage(rows, TRIAGE)
        ij, wtd, schema = rows
        assert (ij.triage_level, ij.triage_score, ij.triage_issues, ij.triage_prs) == ("amber", 42, 3, 1)
        assert ij.failing == [("CI", "https://github.com/bamr87/it-journey/actions/runs/1")]
        assert schema.triage_level == "red"  # name fallback
        assert wtd.triage_level is None  # not in triage at all
        assert wtd.worst_level == "red" and ij.worst_level == "amber" and schema.worst_level == "red"
        k = fl.kpis(rows)
        assert (k["triage_red"], k["triage_amber"], k["failing"]) == (1, 1, 1)
        # the health filter matches either signal; flagged() sees triage-only rows
        assert [r.name for r in fl.filter_rows(rows, health="red")] == ["wtd", "SCHEMA"]
        assert [r.name for r in fl.flagged(rows)] == ["wtd", "SCHEMA", "it-journey"]
        assert [r.name for r in fl.sort_rows(rows, "triage")] == ["SCHEMA", "it-journey", "wtd"]
        fl.attach_triage(rows, None)  # absent file is a no-op, not a crash


def test_inbox_and_repo_items():
    items = fl.inbox_items(TRIAGE)
    assert [i.priority for i in items] == [90, 55, 40]
    assert items[1].label == "#5 [/x] hub pr" and items[0].label == "CI"
    assert [i.url for i in fl.filter_inbox(items, q="hub pr")] == ["u5"]
    assert [i.url for i in fl.filter_inbox(items, repo="IT-JOURNEY")] == ["u1", "u8"]
    assert fl.inbox_items(None) == [] and fl.inbox_items({"inbox": None}) == []

    drill = fl.repo_items(TRIAGE, "it-journey", "https://github.com/bamr87/it-journey")
    assert [(i.kind, i.priority, i.ref) for i in drill] == [
        ("workflow", 90, ".github/workflows/ci.yml"),
        ("pr", 70, "#9"),
        ("issue", 60, "#7"),  # "Bug" label, case-insensitive like fleet_triage
        ("issue", 40, "#8"),
    ]
    assert drill[1].why == "PR checks failing · draft"
    assert drill[3].why == "issue idle 30d"
    assert fl.repo_items(TRIAGE, "nope") == [] and fl.repo_items(None, "x") == []


def test_sources_freshness():
    assert fl.parse_stamp("2026-09-30 06:03 UTC") == datetime(2026, 9, 30, 6, 3, tzinfo=timezone.utc)
    assert fl.parse_stamp("2026-09-30T06:03:00Z") == datetime(2026, 9, 30, 6, 3, tzinfo=timezone.utc)
    assert fl.parse_stamp("garbage") is None and fl.parse_stamp(None) is None
    with tempfile.TemporaryDirectory() as td:
        root = write_reg(Path(td), SAMPLE, HEALTH)
        data = root / "_data"
        (data / "project_health_meta.yml").write_text("generated_at: 2026-10-01 05:00 UTC\n", encoding="utf-8")
        (data / "fleet_triage.yml").write_text(yaml.safe_dump(TRIAGE), encoding="utf-8")
        (data / "fleet.yml").write_text(
            yaml.safe_dump({"harness": {"trip_wires": {"stale_data_days": 1}}}), encoding="utf-8"
        )
        now = datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)
        src = {s.name: s for s in fl.read_sources(root, now=now)}
        assert src["registry"].present and src["registry"].age_days is None and not src["registry"].stale
        assert round(src["health"].age_days * 24) == 2 and not src["health"].stale
        assert src["triage"].stale is True  # 25h old vs the 1-day wire
        assert src["harness"].present is False
        assert fl.stale_days(root) == 1.0

        snap = fl.load_snapshot(root, now=now)
        assert [r.triage_level for r in snap.rows] == ["amber", None, "red"]
        assert len(snap.inbox) == 3 and snap.triage["generated_at"].startswith("2026-09-30")
        before = fl.data_mtimes(root)
        assert before["_data/harness_health.yml"] == 0.0
        (data / "harness_health.yml").write_text(
            yaml.safe_dump({"trip_wires": [{"id": "a", "tripped": False}, {"id": "b", "tripped": True}],
                            "scorecard": {"x": {"value": 1, "direction": "up"}, "bad": "nope"}}),
            encoding="utf-8",
        )
        assert fl.data_mtimes(root) != before
        snap = fl.load_snapshot(root, now=now)
        assert [w["id"] for w in snap.trip_wires] == ["b", "a"]  # tripped first
        assert list(snap.scorecard) == ["x"]  # malformed entries dropped


def test_cycle_includes_unknown_values():
    assert fl.cycle(fl.CATEGORIES, {"docs", "dash"}) == (None, "docs", "dash")
    assert fl.cycle(fl.STATUSES, {"active", "incubating", ""}) == (None, "active", "incubating")


def test_real_registry_loads():
    root = Path(__file__).resolve().parent.parent
    rows, present = fl.join_fleet(root)
    assert len(rows) >= 30
    names = {r.name for r in rows}
    assert "it-journey" in names
    assert "zer0-mistakes" in names
    k = fl.kpis(rows)
    assert k["projects"] == len(rows)
    if present:
        assert k["red"] + k["amber"] + k["green"] <= k["projects"]
    # the committed snapshot loads too, whatever is (not) present locally
    snap = fl.load_snapshot(root)
    assert len(snap.rows) == len(rows)
    assert {s.name for s in snap.sources} == {"registry", "health", "triage", "harness"}


def main() -> int:
    tests = [
        test_join_with_health,
        test_join_degrades_without_health,
        test_kpis_and_filters,
        test_sorts,
        test_docker_match_and_attach,
        test_docker_fleet_label_is_authoritative,
        test_docker_longest_key_wins,
        test_docker_hosts_parsing,
        test_docker_list_all_keeps_errors_per_host,
        test_triage_join_and_kpis,
        test_inbox_and_repo_items,
        test_sources_freshness,
        test_cycle_includes_unknown_values,
        test_real_registry_loads,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

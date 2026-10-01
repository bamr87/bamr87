#!/usr/bin/env python3
"""Fixture tests for tools/tui/fleet.py — the terminal dash data layer.

Guards the same join/filter/sort rules the Jekyll command center uses, so the
TUI cannot drift from `_data/projects.yml` + `_data/project_health.yml`.

    python3 tools/test_tui_fleet.py
"""
from __future__ import annotations

import sys
import tempfile
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
        assert rows[1].docker_name == "custom"
        assert rows[1].docker_running is False
        assert rows[2].docker_name is None


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


def main() -> int:
    tests = [
        test_join_with_health,
        test_join_degrades_without_health,
        test_kpis_and_filters,
        test_sorts,
        test_docker_match_and_attach,
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

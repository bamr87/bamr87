#!/usr/bin/env python3
"""Pure tests for the code-index analysis. No Qdrant, no Ollama."""
from __future__ import annotations

import fleet_index as fi


def test_project_of_splits_submodules_from_the_hub():
    assert fi.project_of("projects/djangoerp/invoices/services.py") == "djangoerp"
    assert fi.project_of("tools/console/core.py") == fi.HUB
    assert fi.project_of(".github/scripts/dash-gen/fleet_observe.py") == fi.HUB


def test_group_hits_keeps_the_stronger_score():
    hits = [
        {"filePath": "projects/law-ai/a.py", "score": 0.70},
        {"filePath": "projects/law-ai/b.py", "score": 0.81},
        {"filePath": "tools/dash", "score": 0.90},
    ]
    grouped = fi.group_hits(hits)
    assert grouped["law-ai"]["score"] == 0.81
    assert grouped["law-ai"]["filePath"].endswith("b.py")
    assert fi.HUB in grouped


def test_harmonize_splits_on_the_floor():
    projects = ["djangoerp", "law-ai", "bashcrawl"]
    hits = [
        {"project": "djangoerp", "score": 0.76, "filePath": "projects/djangoerp/invoices/services.py"},
        {"project": "law-ai", "score": 0.50, "filePath": "projects/law-ai/docs/local-ai.md"},
        {"project": fi.HUB, "score": 0.70, "filePath": "docs/OBSERVABILITY.md"},
    ]
    report = fi.harmonize_report(projects, hits, 0.66)
    assert [h["project"] for h in report["matched"]] == ["djangoerp"]
    assert report["gaps"] == ["law-ai", "bashcrawl"]
    assert report["hub"]["filePath"] == "docs/OBSERVABILITY.md"


def test_a_weak_hub_hit_is_not_reported_as_present():
    report = fi.harmonize_report(["djangoerp"], [{"project": fi.HUB, "score": 0.40, "filePath": "README.md"}], 0.66)
    assert report["hub"] is None
    assert report["gaps"] == ["djangoerp"]


def test_coverage_marks_a_declared_project_with_no_chunks_missing():
    report = fi.coverage_report(
        {"djangoerp": 12, "bashcrawl": 0, fi.HUB: 4},
        ["djangoerp", "bashcrawl"],
        {".github": 0},
    )
    assert report["missing"] == ["bashcrawl"]
    assert report["projects"][0]["project"] == "djangoerp"
    assert report["blind_spots"] == [{"path": ".github", "chunks": 0}]


def test_analysis_config_clamps_a_bad_floor():
    cfg = fi.analysis_config({"indexing": {"analysis": {"min_score": 9, "limit": 0},
                                          "qdrant": "http://127.0.0.1:6333",
                                          "embedder": "http://127.0.0.1:11434",
                                          "model": "nomic-embed-text"}})
    assert cfg["min_score"] == 1.0
    assert cfg["limit"] == 1


def test_the_contract_names_the_analysis_floor():
    cfg = fi.analysis_config()
    assert cfg["min_score"] >= 0.6
    assert cfg["model"] == "nomic-embed-text"
    assert cfg["embedder"].startswith("http://127.0.0.1:")


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except Exception as exc:
                failed += 1
                print(f"  ✗ {name}: {exc}")
    print("OK — code index analysis" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)

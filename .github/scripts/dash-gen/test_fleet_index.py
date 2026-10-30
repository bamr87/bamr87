#!/usr/bin/env python3
"""Pure tests for the code-index analysis. No Qdrant, no Ollama."""
from __future__ import annotations

import contextlib
import os

import fleet_index as fi


@contextlib.contextmanager
def _env(**values):
    """Run with ONLY the given probe/override variables set, whatever the shell has."""
    keys = ("QDRANT_URL", "OLLAMA_URL", fi.COLLECTION_ENV)
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in values.items() if v})
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


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
    with _env():
        cfg = fi.analysis_config()
    assert cfg["min_score"] >= 0.6
    assert cfg["model"] == "nomic-embed-text"
    assert cfg["embedder"].startswith("http://127.0.0.1:")
    assert cfg["qdrant"].startswith("http://127.0.0.1:")


# ---------------------------------------------------------- collection lookup
# Regression: index_coverage and code_search reported "Qdrant has no collection"
# while the store held 17,341 points in ws-6a20496fc5c7ac5d. The console runs in
# a container, where the contract's http://127.0.0.1:6333 is its own loopback —
# the same bug test_observe_contract.py's probe-URL test covers for the other
# planes, which this module was not going through.
def test_a_containerised_caller_is_told_where_to_reach_the_store():
    contract = {"indexing": {"qdrant": "http://127.0.0.1:6333", "embedder": "http://127.0.0.1:11434"}}
    with _env(QDRANT_URL="http://qdrant:6333", OLLAMA_URL="http://host.docker.internal:11434"):
        cfg = fi.analysis_config(contract)
    assert cfg["qdrant"] == "http://qdrant:6333"
    assert cfg["embedder"] == "http://host.docker.internal:11434"
    # …and the browser URL is still what the contract says when nothing overrides it.
    with _env():
        assert fi.analysis_config(contract)["qdrant"] == "http://127.0.0.1:6333"


def test_pick_collection_prefers_the_workspace_prefix_then_the_biggest():
    assert fi.pick_collection([]) is None
    assert fi.pick_collection(["ws-6a20496fc5c7ac5d"]) == "ws-6a20496fc5c7ac5d"
    # A `ws-` collection wins over anything else in the same store.
    assert fi.pick_collection(["other", "ws-abc"]) == "ws-abc"
    # Two workspaces: the one the scan actually filled.
    assert fi.pick_collection(["ws-a", "ws-b"], {"ws-a": 12, "ws-b": 17341}) == "ws-b"
    # No `ws-` at all: fall back to the whole store, still by size.
    assert fi.pick_collection(["x", "y"], {"x": 5, "y": 1}) == "x"
    # The operator's override always wins, even over a store that lists others.
    assert fi.pick_collection(["ws-a"], {}, override="ws-mine") == "ws-mine"


@contextlib.contextmanager
def _listing(names):
    """Stub the one network call in the lookup. `None` means the store did not answer."""
    saved = fi.list_collections
    fi.list_collections = lambda _url: names
    try:
        yield
    finally:
        fi.list_collections = saved


def test_resolve_collection_separates_unreachable_from_unwritten():
    with _env(), _listing(None):
        name, error, seen = fi.resolve_collection("http://127.0.0.1:6333")
    assert name is None and seen == []
    assert "not reachable" in error and "QDRANT_URL" in error and "127.0.0.1:6333" in error

    with _env(), _listing([]):
        name, error, _ = fi.resolve_collection("http://qdrant:6333")
    assert name is None and "holds no collection" in error

    with _env(), _listing(["ws-6a20496fc5c7ac5d"]):
        assert fi.resolve_collection("http://qdrant:6333") == ("ws-6a20496fc5c7ac5d", None,
                                                               ["ws-6a20496fc5c7ac5d"])


def test_an_override_survives_a_store_that_does_not_answer():
    with _env(**{fi.COLLECTION_ENV: "ws-6a20496fc5c7ac5d"}), _listing(None):
        name, error, _ = fi.resolve_collection("http://127.0.0.1:6333")
    assert (name, error) == ("ws-6a20496fc5c7ac5d", None)


def test_search_names_the_url_it_could_not_reach():
    cfg = {"qdrant": "http://127.0.0.1:6333", "embedder": "http://127.0.0.1:11434",
           "model": "nomic-embed-text", "min_score": 0.66, "limit": 40}
    with _env(), _listing(None):
        doc = fi.search("retry with backoff", cfg)
    assert doc["present"] is False and doc["hits"] == []
    assert "QDRANT_URL" in doc["error"]


def test_coverage_reports_where_it_looked_and_what_it_found():
    with _env(), _listing(None):
        report = fi.coverage({"qdrant": "http://127.0.0.1:6333", "embedder": "x", "min_score": 0.66, "limit": 1})
    assert report["present"] is False
    assert report["qdrant"] == "http://127.0.0.1:6333"
    assert report["collection_source"] == "listing"
    assert report["collections"] == []


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

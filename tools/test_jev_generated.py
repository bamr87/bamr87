#!/usr/bin/env python3
"""
Fixture tests for tools/jev/generated.py — the main-only generated-file guard —
and the `jev.auto_tiers` switch that keeps the conflict engine at tier 0.

Run: python3 tools/test_jev_generated.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.jev import generated as G  # noqa: E402
from tools.jev import common as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "submodule.recurse=false", *args], cwd=repo, check=True,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout


def fixture() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="jev-generated-"))
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "config", "user.email", "t@example.com")
    sh(repo, "config", "user.name", "t")
    (repo / ".gitattributes").write_text("CATALOG.md jev-main-only\ndocs/README.md jev-main-only\n")
    (repo / "docs").mkdir()
    for p in ("CATALOG.md", "docs/README.md", "README.md", "notes.md"):
        (repo / p).write_text("v1\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", "base")
    return repo


def test_main_only_files() -> None:
    repo = fixture()
    got = G.main_only_files(repo)
    assert sorted(got) == ["CATALOG.md", "docs/README.md"], got
    assert G.main_only_files(repo, ["README.md", "notes.md"]) == []


def test_guard() -> None:
    repo = fixture()
    sh(repo, "checkout", "-qb", "feature")
    (repo / "notes.md").write_text("v2\n")
    sh(repo, "commit", "-qam", "ok")
    ok, bad = G.guard(repo, G.changed_files(repo, base="main"))
    assert ok and bad == [], bad
    (repo / "CATALOG.md").write_text("v2\n")
    sh(repo, "commit", "-qam", "edits generated")
    changed = G.changed_files(repo, base="main")
    ok, bad = G.guard(repo, changed)
    assert not ok and bad == ["CATALOG.md"], bad
    ok, _ = G.guard(repo, changed, head_ref="chore/jev-number")
    assert ok, "post-merge publish branch is exempt"
    ok, bad = G.guard(repo, G.changed_files(repo, rng=("HEAD^1", "HEAD")))
    assert not ok and bad == ["CATALOG.md"]


def test_repo_marks() -> None:
    assert sorted(G.main_only_files(ROOT, ["CATALOG.md", "docs/README.md", "README.md"])) == \
        ["CATALOG.md", "docs/README.md"]


def test_auto_tiers() -> None:
    cfg = C.JevConfig()
    assert cfg.auto_tiers == ["tier0", "tier1", "tier2"]
    import yaml
    fleet = yaml.safe_load((ROOT / "_data/fleet.yml").read_text())
    jev = fleet["jev"]
    assert jev["enabled"] is True
    assert jev["auto_tiers"] == ["tier0"], "AI tiers stay off"


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

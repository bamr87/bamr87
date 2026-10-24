#!/usr/bin/env python3
"""Tests for tools/governance_lint.py (stdlib + PyYAML). Run: python3 tools/test_governance_lint.py"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("governance_lint", HERE / "governance_lint.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

PRD = "# PRD\n\n## 4. Core features\n\n- a thing\n\n## 5. Requirements\n\n**Functional**\n\n- does x\n- does y\n\n**Non-functional**\n\n- fast\n\n## 6. Success metrics\n"
FEATS = "schema: features/v1\nrepo: o/r\nfeatures:\n  - id: R-001\n    title: X\n    description: does x\n    implemented: true\n    status: shipped\n    link: README.md\n    prd: [FR1]\n"
CON = "# r — Constitution\n\n## 8. Amendments\n\nSee [docs/amendments/](amendments/).\n"
AM = "# 0001 — Ratify\n\n- **Status:** ratified\n- **Date:** 2026-10-21\n- **Ratified by:** PR\n- **Affects:** whole constitution; R-001\n"


def mk(files: dict) -> Path:
    d = Path(tempfile.mkdtemp())
    for k, v in files.items():
        (d / k).parent.mkdir(parents=True, exist_ok=True)
        (d / k).write_text(v)
    return d


def full() -> Path:
    d = mk({"PRD.md": PRD, "README.md": "x", "features/features.yml": FEATS, "docs/constitution.md": CON,
            "docs/amendments/README.md": "x", "docs/amendments/0000-template.md": "t",
            "docs/amendments/0001-ratify-constitution.md": AM, "AGENTS.md": "Read docs/constitution.md first.\n"})
    assert g.main(["prd-ids", str(d), "--write"]) == 0
    assert g.main(["prd-sync", str(d), "--write"]) == 0
    return d


def test_ids_tagged_and_idempotent():
    d = full()
    t = (d / "PRD.md").read_text()
    assert "- FR1: does x" in t and "- FR2: does y" in t and "- NFR1: fast" in t
    assert g.tag_requirements(t)[1] == 0


def test_block_inserted_after_features_section_and_clean():
    d = full()
    t = (d / "PRD.md").read_text()
    assert t.index("## Feature catalog") < t.index("## 5. Requirements")
    assert "[R-001](features/features.yml)" in t and "| FR1 | R-001 |" in t
    r = g.check(d)
    assert r["ok"], r["errors"]


def test_stale_block_and_bad_ref_fail():
    d = full()
    (d / "features/features.yml").write_text(FEATS.replace("[FR1]", "[FR9]"))
    errs = " ".join(g.check(d)["errors"])
    assert "FR9" in errs and "stale" in errs


def test_placeholder_and_missing_governance_fail():
    d = mk({"PRD.md": PRD, "features/features.yml": FEATS.replace("R-001", "TODO-001")})
    errs = " ".join(g.check(d)["errors"])
    assert "TODO-001" in errs and "constitution" in errs and "amendment log" in errs


def test_amendment_fields_and_agents_link():
    d = full()
    (d / "docs/amendments/0002-bad.md").write_text("# 0002\n\n- **Status:** maybe\n")
    (d / "AGENTS.md").write_text("no link\n")
    errs = " ".join(g.check(d)["errors"])
    assert "Status" in errs and "Date" in errs and "Affects" in errs and "AGENTS.md" in errs


def test_catalog_prd_key_and_section_refs():
    d = full()
    (d / "PRD.md").rename(d / "docs/spec.md")
    (d / "features/features.yml").write_text("prd: docs/spec.md\n" + FEATS.replace("[FR1]", "['§5']"))
    g.main(["prd-sync", str(d), "--write"])
    r = g.check(d)
    assert r["prd"] == "docs/spec.md" and r["ok"], r["errors"]


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try:
                f(); print(f"ok   {n}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {n}: {e}")
    sys.exit(1 if fails else 0)

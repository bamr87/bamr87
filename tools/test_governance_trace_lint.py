#!/usr/bin/env python3
"""Fixture tests for governance_trace_lint.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governance_trace_lint as g  # noqa: E402


def test_fr_ref_ok():
    assert g.check_body("Summary\n\nGoverned by: FR84, docs/amendments/0024-claude-code-executes.md")["ok"]


def test_missing_fails_gate():
    assert not g.check_body("just a change\nFR84 mentioned elsewhere")["ok"]
    assert g.main(["check", "--gate", "--body-file", "/dev/null"]) == 1


def test_warn_only_default_and_exempt():
    assert g.main(["check", "--body-file", "/dev/null"]) == 0
    assert g.check_body("bump deps\nlabels: trace-exempt")["exempt"]


def test_new_refs():
    assert g.check_body("**Governed by:** FR-NEW:change-traceability")["ok"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")

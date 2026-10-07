#!/usr/bin/env python3
"""
Fixture tests for UPS-QA-20 in tools/conformance.py: `ci.yml` is a thin caller
of the ONE shared gate, bamr87/bamr87's standard-ci.yml. bamr87/.github's
`ci.yml` is retired (no callers), so a caller of it fails with a pointer to the
replacement instead of passing.

No network, no pytest. Needs only PyYAML:

    python3 tools/test_fleet_ci_gate.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent


def qa20(ci: str | None):
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        if ci is not None:
            (r / ".github" / "workflows").mkdir(parents=True)
            (r / ".github" / "workflows" / "ci.yml").write_text(ci, encoding="utf-8")
        return c.CHECKS["UPS-QA-20"](c.Repo(r, HUB), ["app"])


def test_standard_ci_caller_passes():
    for ref in ("main", "v1", "v1.0.0", "0123456789abcdef0123456789abcdef01234567"):
        ok, msg = qa20(f"jobs:\n  ci:\n    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@{ref}\n    secrets: inherit\n")
        assert ok is True, (ref, msg)


def test_retired_dotgithub_ci_fails():
    ok, msg = qa20("jobs:\n  ci:\n    uses: bamr87/.github/.github/workflows/ci.yml@main\n")
    assert ok is False and "retired" in msg and "standard-ci.yml" in msg, msg


def test_bespoke_and_missing_fail():
    ok, msg = qa20("jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: [{run: make test}]\n")
    assert ok is False and "bespoke" in msg, msg
    assert qa20(None)[0] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

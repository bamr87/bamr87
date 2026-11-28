#!/usr/bin/env python3
"""
Fixture tests for tools/runner_pins.py: the runner half of the always-latest
policy (docs/DEPENDENCIES.md). A versioned GitHub-hosted label with a floating
alias (`ubuntu-24.04`, `macos-15`, `windows-2022`) is a pin wherever a runner is
chosen; a `fleet-pin` comment on the line or the line above makes it deliberate;
`unpin-deps.sh` floats a scalar `runs-on:` and leaves matrices to a person.

No network, no pytest:

    python3 tools/test_runner_pins.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HERE))

import runner_pins as rp  # noqa: E402


def labels(text: str) -> list[tuple[int, str]]:
    return [(p.line, p.label) for p in rp.scan(text)]


# --- what is a pin ---------------------------------------------------------- #
def test_aliases():
    assert rp.floating_alias("ubuntu-24.04") == "ubuntu-latest"
    assert rp.floating_alias("ubuntu-26.04") == "ubuntu-latest"
    assert rp.floating_alias("macos-15") == "macos-latest"
    assert rp.floating_alias("macos-14-large") == "macos-latest-large"
    assert rp.floating_alias("macos-15-xlarge") == "macos-latest-xlarge"
    assert rp.floating_alias("windows-2022") == "windows-latest"


def test_floating_and_aliasless_labels_are_not_pins():
    # No floating alias exists for these, so a check could not name the fix.
    for label in ("ubuntu-latest", "macos-latest", "windows-latest", "ubuntu-slim",
                  "ubuntu-24.04-arm", "macos-15-intel", "windows-11-arm", "self-hosted"):
        assert rp.floating_alias(label) is None, label


# --- where it looks --------------------------------------------------------- #
def test_scalar_quoted_and_inline_list_runs_on():
    text = ("jobs:\n"
            "  a:\n    runs-on: ubuntu-24.04\n"
            "  b:\n    runs-on: 'macos-15'\n"
            "  c:\n    runs-on: [self-hosted, windows-2022]\n"
            "  d:\n    runs-on: ubuntu-latest\n")
    assert labels(text) == [(3, "ubuntu-24.04"), (5, "macos-15"), (7, "windows-2022")], labels(text)


def test_matrix_values_and_include_entries():
    text = ("jobs:\n  t:\n    strategy:\n      matrix:\n"
            "        os: [ubuntu-22.04, macos-latest]\n"
            "        include:\n          - os: windows-2025\n"
            "        runner:\n          - macos-14\n"
            "    runs-on: ${{ matrix.os }}\n")
    assert labels(text) == [(5, "ubuntu-22.04"), (7, "windows-2025"), (9, "macos-14")], labels(text)


def test_expression_default_and_input_default():
    text = ("on:\n  workflow_call:\n    inputs:\n      runner:\n        default: ubuntu-22.04\n"
            "jobs:\n  a:\n    runs-on: ${{ inputs.runner || 'ubuntu-24.04' }}\n")
    assert labels(text) == [(5, "ubuntu-22.04"), (8, "ubuntu-24.04")], labels(text)


def test_prose_and_block_scalars_are_ignored():
    text = ("jobs:\n  a:\n    name: Build on ubuntu-24.04\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: |\n          echo ubuntu-24.04\n          macos-15\n"
            "      - run: echo done\n"
            "      # runs-on: ubuntu-22.04 (commented out)\n")
    assert labels(text) == [], labels(text)


def test_block_scalar_ends_at_dedent():
    text = ("jobs:\n  a:\n    steps:\n      - run: >-\n          ubuntu-24.04\n"
            "  b:\n    runs-on: ubuntu-22.04\n")
    assert labels(text) == [(7, "ubuntu-22.04")], labels(text)


# --- the marker ------------------------------------------------------------- #
def test_marker_on_the_line_or_directly_above():
    text = ("jobs:\n"
            "  a:\n    runs-on: macos-14  # fleet-pin: the last image with Xcode 15\n"
            "  b:\n    # fleet-pin: builds the 24.04 ISO\n    runs-on: ubuntu-24.04\n"
            "  c:\n    # Pinned, not ubuntu-latest (zer0-CMS#109's comment: no marker)\n"
            "    runs-on: ubuntu-24.04\n")
    assert labels(text) == [(9, "ubuntu-24.04")], labels(text)


def test_marker_two_lines_up_does_not_count():
    text = "jobs:\n  a:\n    # fleet-pin: reason\n    timeout-minutes: 5\n    runs-on: ubuntu-24.04\n"
    assert labels(text) == [(5, "ubuntu-24.04")], labels(text)


# --- the converter ---------------------------------------------------------- #
def test_float_runs_on_rewrites_scalars_only():
    text = ("jobs:\n  a:\n    runs-on: ubuntu-24.04  # keep this comment\n"
            "  b:\n    runs-on: \"windows-2022\"\n"
            "  c:\n    runs-on: macos-14  # fleet-pin: Xcode 15\n"
            "  d:\n    strategy:\n      matrix:\n        os: [ubuntu-22.04, ubuntu-24.04]\n")
    new, left = rp.float_runs_on(text)
    assert "runs-on: ubuntu-latest  # keep this comment\n" in new, new
    assert 'runs-on: "windows-latest"\n' in new, new
    assert "runs-on: macos-14  # fleet-pin: Xcode 15\n" in new, new
    assert "os: [ubuntu-22.04, ubuntu-24.04]" in new, new
    assert [(p.line, p.label) for p in left] == [(11, "ubuntu-22.04"), (11, "ubuntu-24.04")], left
    assert rp.float_runs_on(new)[0] == new, "not idempotent"


def test_unpin_deps_floats_runner_and_reports_matrix():
    wf = ("on: push\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: true\n"
          "  b:\n    strategy:\n      matrix:\n        os: [macos-14]\n    runs-on: ${{ matrix.os }}\n"
          "    steps:\n      - run: true\n")
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / ".github/workflows").mkdir(parents=True)
        (r / ".github/workflows/ci.yml").write_text(wf, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
        bash = "/opt/homebrew/bin/bash" if os.path.exists("/opt/homebrew/bin/bash") else "bash"
        out = subprocess.run([bash, str(HERE / "unpin-deps.sh"), str(r)], capture_output=True,
                             text=True, check=True).stdout
        new = (r / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "    runs-on: ubuntu-latest\n" in new, new
    assert "os: [macos-14]" in new, new
    assert "follow-up: .github/workflows/ci.yml:10: `macos-14`" in out, out


# --- the hub itself --------------------------------------------------------- #
def test_hub_workflows_and_seed_templates_are_clean():
    # The same scope check-drift (j) gates: .github and templates, minus each
    # kit's archive/ (frozen on purpose) and fixtures/ (snapshotted test data).
    found = []
    for sub in (".github", "templates"):
        for dirpath, dirnames, filenames in os.walk(HUB / sub):
            dirnames[:] = [x for x in dirnames if x not in ("archive", "fixtures", "node_modules")]
            for fn in filenames:
                if fn.endswith((".yml", ".yaml")):
                    p = Path(dirpath) / fn
                    found += [f"{p.relative_to(HUB)}:{pin.line}" for pin in rp.scan(p.read_text(encoding="utf-8"))]
    assert not found, found


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

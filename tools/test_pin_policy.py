#!/usr/bin/env python3
"""
Fixture tests for the UPS-QA-40 pin policy in tools/conformance.py. A `uses:`
ref passes at `@vMAJOR`, `@vMAJOR.MINOR.PATCH` or a full 40-char SHA (a
`# vX.Y.Z` comment after it is fine). Branch refs such as `@main` fail. Local
`./` paths are exempt; that is how the hub calls its own workflows.

No network, no pytest. Needs only PyYAML:

    python3 tools/test_pin_policy.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
SHA = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"


def qa40(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        for rel, text in files.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
        return c.CHECKS["UPS-QA-40"](c.Repo(r, HUB), ["app"])


def wf(*uses: str, job_uses: str | None = None) -> str:
    steps = "".join(f"      - uses: {u}\n" for u in uses)
    out = "on: push\njobs:\n"
    if steps:
        out += "  build:\n    runs-on: ubuntu-latest\n    steps:\n" + steps
    if job_uses:
        out += f"  gate:\n    uses: {job_uses}\n    secrets: inherit\n"
    return out


# --- ref classification ---------------------------------------------------- #
def test_accepts_major_exact_and_sha():
    for u in ("actions/checkout@v7", "actions/checkout@v7.0.0", f"actions/checkout@{SHA}",
              "bamr87/bamr87/.github/workflows/standard-ci.yml@v1",
              "bamr87/bamr87/.github/workflows/standard-ci.yml@v1.0.0",
              f"bamr87/bamr87/.github/workflows/standard-ci.yml@{SHA}"):
        assert c.unpinned_ref(u) is None, u


def test_exempts_local_paths_and_docker():
    for u in ("./.github/workflows/fleet-conformance.yml", "./.github/actions/claude-run",
              "docker://alpine:3.20"):
        assert c.unpinned_ref(u) is None, u


def test_rejects_branches_partials_short_shas_and_missing_refs():
    cases = {
        "bamr87/bamr87/.github/workflows/standard-ci.yml@main": "branch ref",
        "actions/checkout@master": "branch ref",
        "pypa/gh-action-pypi-publish@release/v1": "branch ref",
        "dtolnay/rust-toolchain@stable": "branch ref",
        "actions/checkout@v7.0": "not vMAJOR or vMAJOR.MINOR.PATCH",
        "actions/checkout@7.0.0": "not vMAJOR or vMAJOR.MINOR.PATCH",
        "actions/checkout@9c091bb": "short SHA",
        "actions/checkout": "no ref",
    }
    for u, why in cases.items():
        assert c.unpinned_ref(u) == why, (u, c.unpinned_ref(u))


# --- the check over a repo ------------------------------------------------- #
def test_clean_repo_passes_with_sha_comment_and_local_calls():
    ok, msg = qa40({
        ".github/workflows/ci.yml": wf(f"actions/checkout@{SHA} # v7.0.0", "actions/setup-python@v7",
                                       "./.github/actions/setup",
                                       job_uses="bamr87/bamr87/.github/workflows/standard-ci.yml@v1"),
        ".github/workflows/local.yml": wf(job_uses="./.github/workflows/ci.yml"),
    })
    assert ok is True, msg


def test_reusable_call_at_main_fails():
    ok, msg = qa40({".github/workflows/ci.yml": wf(job_uses="bamr87/bamr87/.github/workflows/standard-ci.yml@main")})
    assert ok is False and "standard-ci.yml@main (branch ref)" in msg, msg


def test_step_at_branch_fails_and_yaml_extension_is_scanned():
    ok, msg = qa40({".github/workflows/release.yaml": wf("pypa/gh-action-pypi-publish@release/v1")})
    assert ok is False and "workflows/release.yaml" in msg, msg


def test_composite_action_steps_are_scanned():
    action = "runs:\n  using: composite\n  steps:\n    - uses: actions/cache@main\n"
    ok, msg = qa40({".github/actions/setup/action.yml": action})
    assert ok is False and "actions/setup/action.yml: actions/cache@main" in msg, msg


def test_uses_text_inside_run_block_is_ignored():
    text = ("on: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: |\n          cat > caller.yml <<'EOF'\n"
            "          uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main\n          EOF\n")
    ok, msg = qa40({".github/workflows/gen.yml": text})
    assert ok is True, msg


def test_unparseable_file_falls_back_to_line_scan():
    ok, msg = qa40({".github/workflows/bad.yml": "jobs: [\n  - uses: actions/checkout@main\n"})
    assert ok is False and "actions/checkout@main" in msg, msg


def test_message_caps_at_three_with_count():
    ok, msg = qa40({".github/workflows/ci.yml": wf(*[f"o/a{i}@main" for i in range(5)])})
    assert ok is False and msg.endswith("(+2 more)"), msg


def test_committed_lockfile_still_fails():
    ok, msg = qa40({"package-lock.json": "{}", ".github/workflows/ci.yml": wf("actions/checkout@v7")})
    assert ok is False and "committed lockfile" in msg, msg


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

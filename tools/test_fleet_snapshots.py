#!/usr/bin/env python3
"""
Fixture tests for tools/fleet_snapshots.py, the shrink guard of the weekly
fleet-snapshots writer (bamr87/bamr87#775), and for the shape of the workflow
that runs it.

The guard exists because both generators succeed on an empty checkout: a dead
token clones nothing and the snapshot becomes a hub-only one, which is what
fleet-pulse published every day (`repos_scanned: 1`). These tests hold:

  * a scan that reads fewer repos than the committed snapshot, beyond the
    tolerance, is refused, and a loss within it is published but listed;
  * a repo that left the registry, is archived, or is skipped by tier is no
    loss; the hub is never excused;
  * a scan that read no registry submodule is refused even when the committed
    snapshot was just as empty (the hub-only index cannot ratchet itself in);
  * the workflow runs the guard before publish-data, publishes only the two
    snapshots, is declared in fleet.yml `schedule:`, is named as the writer of
    both in `harness.sources`, and fleet-pulse no longer writes the index.

No network, no gh, no pytest. Needs only PyYAML:

    python3 tools/test_fleet_snapshots.py
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_snapshots as fs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "fleet-snapshots.yml"
PULSE = ROOT / ".github" / "workflows" / "fleet-pulse.yml"
FLEET = ROOT / "_data" / "fleet.yml"

REGISTRY = [
    {"name": "alpha", "submodule_path": "projects/alpha", "status": "active"},
    {"name": "beta", "submodule_path": "projects/beta", "status": "active"},
    {"name": "gamma", "submodule_path": "projects/gamma", "status": "experiment"},
    {"name": "delta", "submodule_path": "projects/delta", "status": "maintenance"},
    {"name": "old", "submodule_path": "projects/old", "status": "archived"},
    {"name": "site", "status": "active"},  # not a submodule
]


def hub_with(tmp: Path, checked_out: list[str], registry: list[dict] | None = None) -> Path:
    hub = tmp / "hub"
    (hub / "_data").mkdir(parents=True)
    (hub / "_data" / "projects.yml").write_text(yaml.safe_dump(registry or REGISTRY), encoding="utf-8")
    for name in checked_out:
        (hub / "projects" / name / ".git").mkdir(parents=True)
    return hub


def conformance(names: list[str], skipped: list[dict] | None = None) -> dict:
    return {"summary": {"repos": len(names)}, "skipped": skipped or [],
            "repos": [{"name": n, "nwo": f"bamr87/{n}", "path": f"projects/{n}"} for n in names]}


def features(names: list[str]) -> dict:
    return {"totals": {"repos_scanned": len(names)}, "repos": [{"name": n} for n in names]}


def write_pair(d: Path, conf: dict | None, feat: dict | None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    if conf is not None:
        (d / "conformance.yml").write_text(yaml.safe_dump(conf), encoding="utf-8")
    if feat is not None:
        (d / "features_index.yml").write_text(yaml.safe_dump(feat), encoding="utf-8")


ALL = ["alpha", "beta", "gamma", "delta"]


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #
def test_refuses_a_scan_that_reads_fewer_repos_than_the_committed_snapshot():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        hub = hub_with(tmp, ["alpha"])
        write_pair(tmp / "before", conformance(ALL), features(["bamr87", *ALL]))
        write_pair(hub / "_data", conformance(["alpha"]), features(["bamr87", "alpha"]))
        ok, results, missing = fs.guard(hub, tmp / "before", tolerance=2)
        assert not ok
        by = {r["kind"]: r for r in results}
        assert by["conformance"]["before"] == 4 and by["conformance"]["after"] == 1
        assert by["conformance"]["unread"] == ["beta", "delta", "gamma"], by["conformance"]
        assert not by["features_index"]["ok"]
        assert [m["name"] for m in missing] == ["beta", "delta", "gamma"]


def test_a_loss_within_the_tolerance_publishes_and_is_still_listed():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        hub = hub_with(tmp, ["alpha", "beta", "gamma"])
        write_pair(tmp / "before", conformance(ALL), features(["bamr87", *ALL]))
        write_pair(hub / "_data", conformance(ALL[:3]), features(["bamr87", *ALL[:3]]))
        ok, results, missing = fs.guard(hub, tmp / "before", tolerance=1)
        assert ok, results
        assert all(r["unread"] == ["delta"] for r in results)
        assert missing == [{"name": "delta", "path": "projects/delta"}]
        ok0, _, _ = fs.guard(hub, tmp / "before", tolerance=0)
        assert not ok0


def test_registry_changes_are_no_loss_but_the_hub_is_never_excused():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        reg = [e for e in REGISTRY if e["name"] != "delta"]                                  # delta left the registry
        reg = [dict(e, status="archived") if e["name"] == "gamma" else e for e in reg]         # gamma archived
        hub = hub_with(tmp, ["alpha", "beta"], registry=reg)
        before = conformance(ALL)
        after = conformance(["alpha"], skipped=[{"name": "beta", "reason": "tier fork"}])     # beta became a fork
        r = fs.compare("conformance", before, after, fs.registry_submodules(hub), tolerance=0)
        assert r["ok"], r
        assert set(r["excused"]) == {"beta", "gamma", "delta"}
        f = fs.compare("features_index", features(["bamr87", "alpha"]), features(["alpha"]),
                       fs.registry_submodules(hub), tolerance=0)
        assert not f["ok"] and f["unread"] == ["bamr87"], f


def test_a_scan_that_read_no_submodule_is_refused_even_against_a_hub_only_snapshot():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        hub = hub_with(tmp, [])
        # fleet-pulse's committed index: the hub alone; conformance: nothing at all.
        write_pair(tmp / "before", conformance([]), features(["bamr87"]))
        write_pair(hub / "_data", conformance([], skipped=[{"name": n, "reason": "not checked out"} for n in ALL]),
                   features(["bamr87"]))
        ok, results, missing = fs.guard(hub, tmp / "before")
        assert not ok
        assert all(any("no registry submodule" in p for p in r["problems"]) for r in results), results
        assert len(missing) == 4


def test_the_first_fleet_wide_scan_replaces_a_hub_only_snapshot():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        hub = hub_with(tmp, ALL)
        write_pair(tmp / "before", conformance(ALL), features(["bamr87"]))
        write_pair(hub / "_data", conformance(ALL), features(["bamr87", *ALL]))
        ok, results, missing = fs.guard(hub, tmp / "before")
        assert ok, results
        assert {r["kind"]: r["after"] for r in results} == {"conformance": 4, "features_index": 5}
        assert missing == []


def test_a_snapshot_the_generator_did_not_write_is_refused():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        hub = hub_with(tmp, ALL)
        write_pair(tmp / "before", conformance(ALL), features(["bamr87", *ALL]))
        write_pair(hub / "_data", conformance(ALL), None)
        ok, results, _ = fs.guard(hub, tmp / "before")
        assert not ok
        assert [r["kind"] for r in results if not r["ok"]] == ["features_index"]


def test_cli_exit_code_errors_and_summary():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        hub = hub_with(tmp, ["alpha"])
        write_pair(tmp / "before", conformance(ALL), features(["bamr87", *ALL]))
        write_pair(hub / "_data", conformance(["alpha"]), features(["bamr87", "alpha"]))
        summary = tmp / "summary.md"
        out = io.StringIO()
        with redirect_stdout(out):
            rc = fs.main(["--before", str(tmp / "before"), "--hub", str(hub), "--summary", str(summary)])
        assert rc == 1
        text = out.getvalue()
        assert "::error::conformance.yml: the scan lost 3 repo(s)" in text, text
        assert "::warning::beta (projects/beta)" in text
        report = summary.read_text(encoding="utf-8")
        assert "refused, nothing published" in report and "`gamma` (`projects/gamma`)" in report
        with redirect_stdout(io.StringIO()):
            assert fs.main(["--before", str(tmp / "before"), "--hub", str(hub), "--tolerance", "3"]) == 0


# --------------------------------------------------------------------------- #
# the workflow and the contract around it
# --------------------------------------------------------------------------- #
def _steps() -> list[dict]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = list(doc["jobs"].values())
    assert len(jobs) == 1, "one job: init, scan, guard, publish"
    return jobs[0]["steps"]


def test_the_workflow_guards_before_it_publishes_only_the_two_snapshots():
    steps = _steps()
    runs = [s.get("run", "") for s in steps]
    uses = [s.get("uses", "") for s in steps]
    scan = next(i for i, r in enumerate(runs) if "tools/dash spec fleet --write" in r)
    assert "tools/dash features fleet --write" in runs[scan]
    guard = next(i for i, r in enumerate(runs) if "tools/fleet_snapshots.py" in r)
    publish = uses.index("./.github/actions/utilities/publish-data")
    assert scan < guard < publish, (scan, guard, publish)
    assert "if" not in steps[guard], "the guard always runs once the scan has"
    assert "always()" not in str(steps[publish].get("if", "")), "a refused guard must stop the publish"
    assert steps[publish]["with"]["paths"].split() == ["_data/conformance.yml", "_data/features_index.yml"]
    assert any(u == "./.github/actions/resolve-fleet-token" for u in uses), "the token is probed, not presence-checked"
    # A new loop starts off: the cron needs the opt-in variable, a dispatch never does.
    assert "github.event_name != 'schedule' || vars.FLEET_SNAPSHOTS_ENABLED == 'true'" in WORKFLOW.read_text()


def test_the_cron_is_declared_and_the_workflow_is_the_named_writer():
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
    on = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = on.get(True) or on.get("on")
    assert on["schedule"][0]["cron"] == fleet["schedule"]["fleet_snapshots"]
    assert on["schedule"][0]["cron"].split()[0] not in ("0", "00")
    sources = fleet["harness"]["sources"]
    for sid in ("conformance", "features-index"):
        assert "fleet-snapshots.yml" in str(sources[sid]["writer"]), sources[sid]


def test_fleet_pulse_no_longer_writes_a_hub_only_features_index():
    text = PULSE.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"features(_index\.py)?\s+fleet\s+--write", code), \
        "fleet-pulse checks out no submodules: its features index read the hub alone"


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

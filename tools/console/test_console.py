#!/usr/bin/env python3
"""
Fixture tests for the Harness Console's core (tools/console/core.py).

Guards the properties that make the console safe to leave running:

  * the operation allowlist is the ONLY way to an argv — unknown ops, bad
    parameters, unknown workflows and unknown workflow inputs are refused
    before anything is built, and no parameter ever reaches a shell string;
  * GitHub-writing operations (fan-out --apply, rotation --apply, workflow
    dispatch) demand an explicit confirm and are flagged as remote, while the
    dry-run shapes of the same operations are not;
  * the state document degrades on missing signals instead of crashing;
  * the job manager runs a real subprocess, tails its log, and reports the
    exit status; and
  * the contract editor changes ONLY declared knobs, rejects the rest, and
    preserves every comment in fleet.yml (round-trip) when ruamel is present.

Deliberately dependency-light — no server, no network, no pytest. Needs only
PyYAML (ruamel.yaml enables the round-trip test; absent, it is skipped):

    python3 tools/console/test_console.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402


def test_allowlist_refuses_unknown_and_bad_params():
    for bad in ("rm", "harnesses; rm -rf /", "", "dispatch "):
        try:
            core.build_argv(bad, {})
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    try:
        core.build_argv("deploy-target", {"target": "../x"})
    except ValueError:
        pass
    else:
        raise AssertionError("path-like target accepted")
    try:
        core.build_argv("actions", {"days": 400})
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range days accepted")


def test_argv_shapes_are_exact_and_never_shell():
    argv, remote = core.build_argv("deploy-gaps", {"upgrade": True, "artifacts": "claude,claude-settings"})
    assert argv[-4:] == ["--gaps", "--artifacts", "claude,claude-settings", "--upgrade"], argv
    assert remote is False  # dry run
    argv, remote = core.build_argv("deploy-gaps", {"apply": "true"})
    assert argv[-2:] == ["--gaps", "--apply"] and remote is True
    argv, remote = core.build_argv("harnesses", {"days": "7"})
    assert argv[-2:] == ["--days", "7"] and remote is False
    argv, _ = core.build_argv("config-show", {"key": "harnesses.budget"})
    assert argv[-1] == "harnesses.budget"
    try:
        core.build_argv("config-show", {"key": "x; whoami"})
    except ValueError:
        pass
    else:
        raise AssertionError("shell metacharacters accepted in key")
    for op_id in core.OPS:
        if op_id in ("tests",):
            continue
        argv, _ = core.build_argv(op_id, {"target": "alpha", "workflow": "fleet-pulse", "fields": {}})
        assert all(isinstance(a, str) for a in argv) and "bash" not in argv[0], (op_id, argv)


def test_dispatch_validates_workflow_and_inputs():
    argv, remote = core.build_argv("dispatch", {"workflow": "harness-fanout",
                                                 "fields": {"target": "gaps", "dry_run": True}})
    assert argv == ["gh", "workflow", "run", "harness-fanout.yml", "-f", "target=gaps", "-f", "dry_run=true"]
    assert remote is True  # every dispatch is a remote write
    for params in ({"workflow": "claude"}, {"workflow": "fleet-pulse", "fields": {"evil": "x"}},
                   {"workflow": "harness-fanout", "fields": {"target": "$(id)"}}):
        try:
            core.build_argv("dispatch", params)
        except ValueError:
            continue
        raise AssertionError(f"accepted {params}")


def test_lake_ops_argv_shapes_and_status_document():
    argv, remote = core.build_argv("lake-sync", {"days": "3", "target": "alpha", "jobs": "all", "logs": "none"})
    assert argv[1:] == ["lake", "sync", "--days", "3", "--repo", "alpha", "--jobs", "all", "--logs", "none"], argv
    assert remote is False  # the lake writes to disk, never to GitHub
    argv, _ = core.build_argv("lake-sync", {})
    assert argv[-7:] == ["sync", "--days", "7", "--jobs", "ai", "--logs", "ai"], argv
    for bad in ({"jobs": "everything"}, {"target": "a/b"}, {"logs": "all; rm -rf /"}, {"days": 0}):
        try:
            core.build_argv("lake-sync", bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    argv, remote = core.build_argv("lake-export", {"local": True, "dry_run": True, "force": "1"})
    assert argv[1:] == ["lake", "export", "--days", "7", "--local", "--dry-run", "--force"], argv
    assert remote is False
    argv, _ = core.build_argv("lake-status", {})
    assert argv[1:] == ["lake", "status"]
    import json
    s = core.lake_status(probe=False)
    assert "present" in s and s["phoenix"]["collector"] and "lake_dir" in s
    json.dumps(s)
    json.dumps(core.lake_runs(5))
    json.dumps(core.lake_lines())
    caps = core.capabilities()
    assert isinstance(caps["otel_exporter"], bool) and caps["phoenix"]["collector"] and isinstance(caps["lake_present"], bool)


def test_job_manager_runs_confirms_and_tails():
    tmp = Path(tempfile.mkdtemp())
    try:
        jm = core.JobManager(job_dir=tmp)
        try:
            jm.submit("dispatch", {"workflow": "build-dash"}, confirm=False)
        except PermissionError:
            pass
        else:
            raise AssertionError("remote write ran without confirm")
        job = jm.submit("gaps")   # offline: reads the committed inventory
        for _ in range(100):
            if jm.tail(job.id)["done"]:
                break
            time.sleep(0.1)
        t = jm.tail(job.id)
        assert t["done"] and t["job"]["status"] in ("succeeded", "failed"), t["job"]
        assert t["text"].startswith("$ ") and "harnesses --gaps" in t["text"]
        assert jm.list()[0]["id"] == job.id
        try:
            jm.tail("nope")
        except KeyError:
            pass
        else:
            raise AssertionError("unknown job id tailed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_state_document_degrades_without_signals(monkeypatch_dir=None):
    state = core.load_state()
    for key in ("sources", "contract", "registry", "harnesses", "loops", "git", "usage", "tokens"):
        assert key in state, key
    assert state["registry"]["count"] > 0
    assert all("cron_human" in loop for loop in state["loops"])
    # a token list never carries values — only names/scope/placement
    assert all(set(t) <= {"name", "scope", "required", "deprecated", "used_by"} for t in state["tokens"])
    assert core.source_meta(None, core.dt.datetime.now(core.dt.timezone.utc))["present"] is False


def test_capabilities_report_names_not_values():
    caps = core.capabilities()
    assert set(caps["env_tokens"]) == set(core.TOKEN_ENV)
    assert all(isinstance(v, bool) for v in caps["env_tokens"].values())
    assert isinstance(caps["contract_editing"], bool)


def test_api_documents_are_json_serializable():
    # Every /api document is handed to pydantic's JSON serializer verbatim; a
    # leaked module or datetime object is a 500 in the browser, not a test
    # failure here — unless we serialize them too.
    import json
    json.dumps(core.capabilities())
    json.dumps(core.load_state())
    json.dumps(core.list_ops())
    json.dumps(core.read_contract())


def test_contract_editor_limits_and_preserves_comments():
    try:
        import ruamel.yaml  # noqa: F401
    except ImportError:
        print("  (ruamel.yaml absent — round-trip test skipped)")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        fleet = tmp / "fleet.yml"
        shutil.copy(core.DATA / "fleet.yml", fleet)
        before = fleet.read_text()
        for bad in ({"kit": "x"}, {"budget.monthly_ai_usd": -1}, {"exempt": ["../x"]},
                    {"throughput.max_scheduled_ai_per_day_fleet": "lots"}):
            try:
                core.update_contract(bad, fleet)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad}")
        assert fleet.read_text() == before  # refused edits touch nothing
        out = core.update_contract({"budget.monthly_ai_usd": 90, "exempt": "alpha,beta",
                                    "baseline.require_oauth_secret": False}, fleet)
        assert out["applied"] == {"budget.monthly_ai_usd": 90, "exempt": ["alpha", "beta"],
                                  "baseline.require_oauth_secret": False}, out["applied"]
        after = fleet.read_text()
        assert before.count("#") == after.count("#"), "a comment was lost in the round trip"
        import yaml
        new = yaml.safe_load(after)["harnesses"]
        assert new["budget"]["monthly_ai_usd"] == 90 and new["exempt"] == ["alpha", "beta"]
        assert new["baseline"]["require_oauth_secret"] is False
        # unchanged values are not rewritten (idempotent second call)
        again = core.update_contract({"budget.monthly_ai_usd": 90}, fleet)
        assert again["applied"] == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — console fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

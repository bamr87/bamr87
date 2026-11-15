#!/usr/bin/env python3
"""tools/dash ops, and the slash commands held equal to the console.

`ops_cli` runs the console's operation allowlist from a terminal with the
console's own validation and confirm gate. The Claude Code slash commands under
.claude/commands/{harness,loops,console}/ are thin front doors onto it; these
tests keep them so: every operation they name exists, nothing they pre-approve
can write to GitHub or spend, and the /loops: commands cover exactly the loops
the console's Loops page draws (core.LOOPS), with every local operation,
agent step and CI dispatch each loop has.

Bare interpreter + PyYAML: python3 tools/console/test_ops_cli.py
"""
from __future__ import annotations

import contextlib
import io
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402
import ops_cli  # noqa: E402

NAMESPACES = ("harness", "loops", "console")
RUN_RX = re.compile(r"tools/dash ops run ([a-z][a-z0-9-]*)")
BASH_RX = re.compile(r"Bash\(([^)]*)\)")
RETIRED = (".claude/commands/dash-status.md", ".claude/commands/evolve.md")


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = ops_cli.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


def namespaced() -> list[dict]:
    return [c for c in ops_cli.slash_commands() if ":" in c["name"] and c["name"][1:].split(":")[0] in NAMESPACES]


@contextlib.contextmanager
def patched(obj, name, value):
    saved = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, saved)


@contextlib.contextmanager
def test_op(op_id: str, **spec):
    core.OPS[op_id] = dict(title=f"test {op_id}", group="observe", needs_token=False, params=[], **spec)
    try:
        yield
    finally:
        core.OPS.pop(op_id, None)


class FakeClient:
    """Stands in for fleetcore.client.ConsoleClient: a console that answers."""
    root = str(core.REPO_ROOT)
    listed: dict = {}
    submitted: list = []
    final = "succeeded"

    def __init__(self):
        self.url = "http://console.test"
        self.enabled = True

    @classmethod
    def from_env(cls):
        return cls()

    def health(self):
        return {"ok": True, "repo_root": FakeClient.root}

    def ops(self):
        return [{"id": k, "unavailable": v} for k, v in FakeClient.listed.items()]

    def jobs(self):
        return []

    def submit(self, op, params=None, confirm=False):
        FakeClient.submitted.append((op, params, confirm))
        return {"id": "0123456789ab", "title": op}

    def tail(self, job_id, offset=0):
        return {"text": "line\n", "offset": offset + 5, "done": True,
                "job": {"status": FakeClient.final, "exit_code": 0 if FakeClient.final == "succeeded" else 1}}


def no_subprocess(*a, **k):
    raise AssertionError(f"ran a command: {a}")


# --------------------------------------------------------------------------- #
# the bridge
# --------------------------------------------------------------------------- #
def test_parameters_are_the_ops_declared_keys_and_dispatch_fields():
    assert ops_cli.parse_params("dispatch", ["workflow=fleet-pulse", "fields.dry_run=true"]) == \
        {"workflow": "fleet-pulse", "fields": {"dry_run": "true"}}
    for op, words, why in (("harnesses", ["dayz=7"], "no parameter 'dayz'"),
                           ("harnesses", ["days=7", "days=8"], "given twice"),
                           ("harnesses", ["days"], "not key=value"),
                           ("harnesses", ["fields.x=1"], "takes no fields"),
                           ("no-such-op", [], "unknown operation")):
        try:
            ops_cli.parse_params(op, words)
        except ops_cli.UsageError as exc:
            assert why in str(exc), (op, words, exc)
        else:
            raise AssertionError(f"{op} {words} accepted")


def test_a_refused_value_is_the_ops_own_refusal():
    rc, _, err = run_main("run", "conflicts", "action=triage", "pr=x; rm -rf /", "--here")
    assert rc == ops_cli.EXIT_USAGE and "owner/repo#number" in err, err


def test_explain_prints_the_argv_and_the_gate_and_runs_nothing():
    with patched(ops_cli.subprocess, "run", no_subprocess):
        rc, out, _ = run_main("run", "dispatch", "workflow=repo-scout", "fields.dry_run=true", "--explain")
        assert rc == 0 and "gh workflow run repo-scout.yml -f dry_run=true" in out and "confirm (write)" in out, out
        rc, out, _ = run_main("run", "conflicts-resolve", "dry_run=true", "--explain")
        assert rc == 0 and "--dry-run" in out and "none: runs without asking" in out, out


def test_a_write_or_spend_needs_confirm_and_nothing_runs_without_it():
    with patched(ops_cli.subprocess, "run", no_subprocess), patched(ops_cli, "ConsoleClient", None):
        rc, _, err = run_main("run", "dispatch", "workflow=fleet-pulse")
        assert rc == ops_cli.EXIT_CONFIRM and "--confirm" in err, err
        rc, _, err = run_main("run", "conflicts-resolve", "pr=bamr87/kvlite#7")
        assert rc == ops_cli.EXIT_CONFIRM, err
        step = core.agent_steps()[0]
        rc, _, err = run_main("run", "loop-run", f"loop={step['loop']}", f"step={step['step']}", "target=kvlite")
        assert rc == ops_cli.EXIT_CONFIRM and "Claude spend" in err, err


def test_here_runs_the_ops_own_argv_and_passes_its_exit_through():
    calls = []

    def fake_run(argv, cwd=None, env=None):
        calls.append((argv, cwd, env))
        return subprocess.CompletedProcess(argv, 7)

    with test_op("_t-echo", argv=lambda p: ["echo", "hi"]), patched(ops_cli.subprocess, "run", fake_run):
        rc, _, err = run_main("run", "_t-echo", "--here")
    assert rc == 7 and calls[0][0] == ["echo", "hi"] and calls[0][1] == str(core.REPO_ROOT), (rc, calls)
    assert calls[0][2]["PYTHON"] == sys.executable and "$ echo hi" in err


def test_an_op_that_cannot_run_here_says_why():
    with test_op("_t-docker", argv=lambda p: ["true"]), patched(core, "op_unavailable", lambda op: "no docker"), \
            patched(ops_cli, "ConsoleClient", None), patched(ops_cli.subprocess, "run", no_subprocess):
        rc, _, err = run_main("run", "_t-docker")
    assert rc == ops_cli.EXIT_UNAVAILABLE and "no docker" in err, err


def test_auto_joins_the_console_only_for_this_checkout_and_an_op_it_can_run():
    with patched(ops_cli, "ConsoleClient", FakeClient):
        FakeClient.listed = {"status": None, "loop-run": "no `claude` CLI on this console's PATH"}
        FakeClient.root = str(core.REPO_ROOT)
        quiet = io.StringIO()
        assert isinstance(ops_cli.console_for("status", "auto", out=quiet), FakeClient)
        assert ops_cli.console_for("loop-run", "auto", out=quiet) is None and "running here" in quiet.getvalue()
        assert ops_cli.console_for("status", "here", out=quiet) is None
        FakeClient.root = "/somewhere/else"
        assert ops_cli.console_for("status", "auto", out=quiet) is None
        assert isinstance(ops_cli.console_for("status", "console", out=quiet), FakeClient)


def test_a_console_job_carries_the_confirm_and_its_outcome_is_the_exit():
    FakeClient.root, FakeClient.listed, FakeClient.submitted = str(core.REPO_ROOT), {"dispatch": None}, []
    with patched(ops_cli, "ConsoleClient", FakeClient), patched(ops_cli, "POLL_S", 0), \
            patched(ops_cli.subprocess, "run", no_subprocess):
        FakeClient.final = "succeeded"
        rc, out, err = run_main("run", "dispatch", "workflow=build-dash", "--confirm")
        assert rc == 0 and "line" in out and "0123456789ab" in err, (out, err)
        assert FakeClient.submitted == [("dispatch", {"workflow": "build-dash"}, True)]
        FakeClient.final = "failed"
        rc, _, _ = run_main("run", "dispatch", "workflow=build-dash", "--confirm")
        assert rc == ops_cli.EXIT_FAILED
    FakeClient.final = "succeeded"


def test_list_and_show_are_the_console_allowlist():
    rc, out, _ = run_main("list", "--json")
    import json
    rows = json.loads(out)
    assert rc == 0 and {r["id"] for r in rows} == set(core.OPS)
    rc, out, _ = run_main("show", "conflicts-resolve")
    assert rc == 0 and "pr, dry_run" in out, out
    assert run_main("list", "--group", "nope")[0] == ops_cli.EXIT_USAGE
    assert run_main("show", "nope")[0] == ops_cli.EXIT_USAGE


# --------------------------------------------------------------------------- #
# the operations the loop commands needed
# --------------------------------------------------------------------------- #
def test_the_loop_operations_validate_and_only_resolve_writes():
    dash = core.DASH
    assert core.build_argv("agents", {}) == ([dash, "agents", "--check"], False)
    assert core.build_argv("pm", {}) == ([dash, "pm", "review"], False)
    assert core.build_argv("conflicts", {"action": "scan", "repo": "bamr87/kvlite"}) == \
        ([dash, "conflicts", "scan", "--repo", "bamr87/kvlite", "--json"], False)
    assert core.build_argv("conflicts", {"action": "triage", "pr": "bamr87/kvlite#7"})[0][2:5] == \
        ["triage", "--pr", "bamr87/kvlite#7"]
    assert core.build_argv("conflicts-resolve", {"dry_run": "true"}) == ([dash, "conflicts", "sweep", "--dry-run"], False)
    assert core.build_argv("conflicts-resolve", {"pr": "bamr87/kvlite#7"}) == \
        ([dash, "conflicts", "resolve", "--pr", "bamr87/kvlite#7"], True)
    assert core.build_argv("evidence", {"repo": "bamr87/kvlite", "number": "12"}) == \
        ([dash, "evidence", "bamr87/kvlite", "12"], False)
    for op, bad in (("conflicts", {"action": "resolve"}), ("conflicts", {"action": "triage"}),
                    ("conflicts", {"action": "budget", "repo": "a/b"}), ("conflicts", {"action": "scan", "pr": "a/b#1"}),
                    ("conflicts-resolve", {"pr": "a/b#1;x"}), ("pm", {"view": "apply"}),
                    ("evidence", {"repo": "kvlite", "number": "1"}), ("evidence", {"repo": "a/b", "number": "x"})):
        try:
            core.build_argv(op, bad)
        except ValueError:
            continue
        raise AssertionError(f"{op} {bad} accepted")
    rows = {o["id"]: o for o in core.list_ops()}
    assert rows["pm"]["choices"] == {"view": list(core.PM_VIEWS)}
    assert rows["conflicts"]["choices"] == {"action": list(core.CONFLICT_ACTIONS)}
    assert rows["conflicts-resolve"]["remote_write"] and rows["conflicts-resolve"]["exclusive"] == "conflicts"
    assert {"jev-conflicts", "fleet-pm"} <= set(core.DISPATCH_WORKFLOWS)


# --------------------------------------------------------------------------- #
# the slash commands
# --------------------------------------------------------------------------- #
def test_the_retired_commands_stay_gone_and_every_namespace_has_commands():
    for rel in RETIRED:
        assert not (core.REPO_ROOT / rel).exists(), f"{rel} came back; it is /harness:status and /loops:evolution"
    names = {c["name"] for c in namespaced()}
    for ns in NAMESPACES:
        assert any(n.startswith(f"/{ns}:") for n in names), ns


def test_every_command_is_a_front_door_the_person_starts():
    for c in namespaced():
        fm = c["frontmatter"]
        assert isinstance(fm.get("description"), str) and fm["description"].strip(), c["name"]
        # operator entry points: typed by a person, never auto-loaded, and no description in every session's context
        assert fm.get("disable-model-invocation") is True, c["name"]
        assert isinstance(fm.get("metadata"), dict) and isinstance(fm["metadata"].get("ops"), list), c["name"]
        for op in c["ops"]:
            assert op in core.OPS, f"{c['name']} names '{op}', which is not a console operation"
        body = (core.REPO_ROOT / c["path"]).read_text(encoding="utf-8")
        for op in set(RUN_RX.findall(body)):
            assert op in c["ops"], f"{c['name']} runs '{op}' without declaring it in metadata.ops"
        assert "ad-hoc script" in body and "--confirm" in body, f"{c['name']} lacks the shared rules"


def test_nothing_pre_approved_can_write_to_github_or_spend():
    """`allowed-tools` runs without a prompt for the turn. A command pre-approves
    only `tools/dash` read paths and the operations that never write or spend;
    a gated operation only as `--explain` (prints, runs nothing) or as its dry
    run, and never with `--confirm`."""
    for c in namespaced():
        allowed = str(c["frontmatter"].get("allowed-tools") or "")
        for pattern in BASH_RX.findall(allowed):
            where = f"{c['name']}: Bash({pattern})"
            assert pattern.startswith("tools/dash "), f"{where} is not the front door"
            assert "--confirm" not in pattern and "--apply" not in pattern and "--live" not in pattern, where
            words = pattern.split()
            if words[:3] == ["tools/dash", "ops", "run"]:
                op = words[3]
                if op == "*" or "remote" in core.OPS.get(op, {}):
                    if pattern.endswith(" --explain"):
                        continue
                    assert pattern.endswith(" dry_run=true") and op != "*", f"{where} can write or spend"
                    assert core.OPS[op]["remote"]({"dry_run": "true"}) is False, where
                else:
                    assert op in core.OPS, f"{where} names no operation"
                    assert op in c["ops"], f"{where} is not declared in metadata.ops"
            if words[:3] in (["tools/dash", "loop", "run"], ["tools/dash", "loop", "publish"]):
                raise AssertionError(f"{where} runs or files a loop without the confirm gate")
            if words[:3] == ["tools/dash", "loop", "doctor"]:
                assert "*" not in pattern, f"{where} would allow --live"
            if words[:3] == ["tools/dash", "refine", "reflect"]:
                assert words[3:4] == ["--rehearse"], f"{where} would spend"


def test_the_loops_commands_equal_the_consoles_loops_table():
    claimed: dict[str, str] = {}
    for c in namespaced():
        if not c["name"].startswith("/loops:"):
            assert not c["loops"], f"{c['name']} claims a loop outside /loops:"
            continue
        for loop in c["loops"]:
            assert loop not in claimed, f"{loop} is claimed by {claimed[loop]} and {c['name']}"
            claimed[loop] = c["name"]
    by_id = {loop["id"]: loop for loop in core.LOOPS}
    assert set(claimed) == set(by_id), f"loops without a command: {set(by_id) - set(claimed)}; " \
                                       f"commands for no loop: {set(claimed) - set(by_id)}"
    commands = {c["name"]: c for c in namespaced()}
    agent_loops = {s["loop"] for s in core.agent_steps()}
    for loop_id, name in claimed.items():
        loop, ops = by_id[loop_id], set(commands[name]["ops"])
        missing = set(loop["local_ops"]) - ops
        assert not missing, f"{name} does not run {loop_id}'s operations {sorted(missing)}"
        if loop["workflow"] in agent_loops:
            assert "loop-run" in ops, f"{name}: {loop_id} has a local agent step and no loop-run stage"
        if loop["workflow"] in core.DISPATCH_WORKFLOWS:
            assert "dispatch" in ops, f"{name}: {loop_id} dispatches in CI and has no ci stage"


def test_ops_loops_names_a_command_for_every_loop():
    rows = ops_cli.loop_rows()
    assert [r["id"] for r in rows] == [loop["id"] for loop in core.LOOPS]
    assert all(r["commands"] for r in rows), [r["id"] for r in rows if not r["commands"]]
    rc, out, _ = run_main("loops")
    assert rc == 0 and "/loops:scout" in out and "/loops:upkeep" in out


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v) and k != "test_op"]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
    print(("FAIL" if failed else "OK") + " — ops_cli + slash command tests")
    raise SystemExit(1 if failed else 0)

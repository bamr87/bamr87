#!/usr/bin/env python3
"""
Fixture tests for fleet_lake.py — the local data lake + the Phoenix exporter.

Guards the properties that make the lake trustworthy as the local stack's
record of what GitHub holds, and the traces trustworthy as evidence:

  * log parsing reads what claude-code-action actually prints with its
    DEFAULT `show_full_output: false` (SDK options, init model, the result
    block, the session id) and, with full output, assistant turns and tool
    calls with their log-line timestamps; an unrelated log yields nothing;
  * trace and span ids are DETERMINISTIC functions of the run/session key,
    so a re-export cannot duplicate a trace;
  * run spans nest run → job → step, the Claude step becomes the AGENT span
    carrying model/turns/cost, failure conclusions become ERROR status, and
    every span has a non-negative duration;
  * session spans come out of a real-shaped ~/.claude/projects transcript:
    one LLM span per assistant message (streamed duplicates folded), tool
    spans closed by their tool_result, everything under the session root;
  * the SQLite layer upserts idempotently (a second sync is an update, not a
    duplicate) and the export ledger keeps already-shipped runs out of the
    next selection unless forced; and
  * the status / runs / lines documents the console serves are JSON-safe.

Deliberately dependency-light — no network, no gh, no OpenTelemetry, no
pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_fleet_lake.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_lake as fl  # noqa: E402

DOCTOR_LOG = """\
2026-09-01T06:49:35.7088555Z Running Claude Code via SDK (full output hidden for security)...
2026-09-01T06:49:35.7090906Z SDK options: {
2026-09-01T06:49:35.7091173Z   "model": "opus",
2026-09-01T06:49:35.7092160Z   "maxTurns": 160,
2026-09-01T06:49:35.7092439Z   "allowedTools": [
2026-09-01T06:49:35.7092779Z     "Bash(gh:*)",
2026-09-01T06:49:35.7097563Z     "Read",
2026-09-01T06:49:35.7098612Z     "Write"
2026-09-01T06:49:35.7098857Z   ],
2026-09-01T06:49:35.7102326Z }
2026-09-01T06:49:38.2931074Z {
2026-09-01T06:49:38.2931942Z   "type": "system",
2026-09-01T06:49:38.2932628Z   "subtype": "init",
2026-09-01T06:49:38.2933548Z   "message": "Claude Code initialized",
2026-09-01T06:49:38.2934186Z   "model": "claude-opus-5"
2026-09-01T06:49:38.2934639Z }
2026-09-01T07:03:53.8555712Z {
2026-09-01T07:03:53.8556123Z   "type": "result",
2026-09-01T07:03:53.8556661Z   "subtype": "success",
2026-09-01T07:03:53.8557112Z   "is_error": false,
2026-09-01T07:03:53.8557392Z   "duration_ms": 855589,
2026-09-01T07:03:53.8557866Z   "num_turns": 134,
2026-09-01T07:03:53.8558133Z   "total_cost_usd": 9.0937255,
2026-09-01T07:03:53.8558466Z   "permission_denials_count": 28,
2026-09-01T07:03:53.8560558Z }
2026-09-01T07:03:54.2959653Z Set session_id: b217ef2a-0fde-4dc9-abc9-fad002da889b
"""

FULL_OUTPUT_LOG = """\
2026-09-01T10:00:00.0000000Z {"type":"system","subtype":"init","model":"claude-sonnet-5"}
2026-09-01T10:00:05.0000000Z {"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}
2026-09-01T10:00:09.0000000Z {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"x"}]}}
2026-09-01T10:00:12.0000000Z {"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{}},{"type":"text","text":"done"}],"usage":{"input_tokens":120,"output_tokens":40,"cache_read_input_tokens":900,"cache_creation_input_tokens":10}}}
2026-09-01T10:00:20.0000000Z {"type":"result","subtype":"success","is_error":false,"duration_ms":20000,"num_turns":2,"total_cost_usd":0.05,"usage":{"input_tokens":130,"output_tokens":41,"cache_read_input_tokens":900,"cache_creation_input_tokens":10}}
"""


def test_parse_agent_log_default_output_shape():
    facts = fl.parse_agent_log(DOCTOR_LOG)
    assert facts["model"] == "claude-opus-5", facts       # the resolved model, not the alias
    assert facts["max_turns"] == 160 and facts["allowed_tools"] == ["Bash(gh:*)", "Read", "Write"]
    assert facts["num_turns"] == 134 and abs(facts["cost_usd"] - 9.0937255) < 1e-9
    assert facts["duration_ms"] == 855589 and facts["permission_denials"] == 28
    assert facts["is_error"] is False and facts["result_subtype"] == "success"
    assert facts["session_id"] == "b217ef2a-0fde-4dc9-abc9-fad002da889b"
    assert facts["started_at"].startswith("2026-09-01T06:49:38") and facts["ended_at"].startswith("2026-09-01T07:03:53")
    assert "tool_calls" not in facts and "input_tokens" not in facts   # hidden output → absent, not 0
    assert fl.parse_agent_log("2026-09-01T00:00:00.0Z npm ci\n2026-09-01T00:00:01.0Z ok\n") == {}


def test_parse_agent_log_full_output_turns_and_tools():
    facts = fl.parse_agent_log(FULL_OUTPUT_LOG)
    assert facts["model"] == "claude-sonnet-5" and facts["turns"] == 2
    assert [c["name"] for c in facts["tool_calls"]] == ["Read", "Bash"]
    assert facts["tool_calls"][0]["at"].startswith("2026-09-01T10:00:05")
    assert facts["input_tokens"] == 130 and facts["output_tokens"] == 41  # the result block wins
    assert facts["cache_read_tokens"] == 900 and facts["cache_write_tokens"] == 10


def test_ids_are_deterministic_and_nonzero():
    a, b = fl.trace_id_for("run:bamr87/x:1"), fl.trace_id_for("run:bamr87/x:1")
    assert a == b and a != 0 and 0 < a < 2 ** 128
    assert fl.trace_id_for("run:bamr87/x:2") != a
    s1, s2 = fl.span_id_for("k", "job:9"), fl.span_id_for("k", "job:9")
    assert s1 == s2 and 0 < s1 < 2 ** 64 and fl.span_id_for("k", "job:10") != s1
    assert len(fl.hex_trace(a)) == 32


def _run_fixture(conclusion="success"):
    run = {"id": 1, "nwo": "bamr87/x", "workflow_name": "Claude", "workflow_path": ".github/workflows/claude.yml",
           "event": "issue_comment", "status": "completed", "conclusion": conclusion, "run_attempt": 1,
           "created_at": "2026-09-01T06:49:00Z", "run_started_at": "2026-09-01T06:49:00Z",
           "updated_at": "2026-09-01T07:04:00Z", "html_url": "https://github.com/bamr87/x/actions/runs/1"}
    jobs = [{"id": 9, "name": "doctor", "conclusion": conclusion, "started_at": "2026-09-01T06:49:08Z",
             "completed_at": "2026-09-01T07:03:57Z", "runner_name": "GitHub Actions 1", "html_url": "j"}]
    steps = {9: [
        {"number": 1, "name": "Set up job", "conclusion": "success", "started_at": "2026-09-01T06:49:09Z",
         "completed_at": "2026-09-01T06:49:12Z"},
        {"number": 7, "name": "Diagnose & fix", "conclusion": conclusion, "started_at": "2026-09-01T06:49:18Z",
         "completed_at": "2026-09-01T07:03:54Z"},
        {"number": 8, "name": "Untimed", "conclusion": "skipped", "started_at": None, "completed_at": None},
    ]}
    return run, jobs, steps


def test_run_spans_nest_and_carry_agent_facts():
    run, jobs, steps = _run_fixture()
    agent = fl.parse_agent_log(DOCTOR_LOG)
    spans = fl.build_run_spans(run, jobs, steps, agent)
    names = [(s["name"], s["kind"]) for s in spans]
    assert names == [("Claude", "CHAIN"), ("doctor", "CHAIN"), ("Set up job", "CHAIN"), ("Diagnose & fix", "AGENT")], names
    root, job, _, step = spans
    assert job["parent_id"] == root["span_id"] and step["parent_id"] == job["span_id"]
    assert all(s["trace_id"] == root["trace_id"] for s in spans)
    assert all(s["end"] >= s["start"] > 0 for s in spans)
    a = step["attributes"]
    assert a["openinference.span.kind"] == "AGENT" and a["llm.model_name"] == "claude-opus-5"
    assert a["claude.num_turns"] == 134 and abs(a["llm.cost.total"] - 9.0937255) < 1e-9
    assert a["session.id"] == root["attributes"]["session.id"] == "b217ef2a-0fde-4dc9-abc9-fad002da889b"
    assert "llm.token_count.prompt" not in a           # None attributes are dropped, not sent as null
    assert root["attributes"]["github.run_id"] == 1 and root["status"] == "OK"
    # the same input yields the same ids — a re-export is idempotent at Phoenix
    again = fl.build_run_spans(run, jobs, steps, agent)
    assert [s["span_id"] for s in again] == [s["span_id"] for s in spans]
    # tool calls (full output) hang off the agent step, closed by the next call
    full = fl.parse_agent_log(FULL_OUTPUT_LOG)
    full["started_at"] = "2026-09-01T06:50:00Z"
    with_tools = fl.build_run_spans(run, jobs, steps, full)
    tools = [s for s in with_tools if s["kind"] == "TOOL"]
    assert [t["attributes"]["tool.name"] for t in tools] == ["Read", "Bash"]
    assert all(t["parent_id"] == with_tools[3]["span_id"] for t in tools)


def test_run_spans_failure_is_error_status():
    run, jobs, steps = _run_fixture("failure")
    spans = fl.build_run_spans(run, jobs, steps, None)
    assert spans[0]["status"] == "ERROR" and spans[1]["status"] == "ERROR"
    assert [s["kind"] for s in spans] == ["CHAIN", "CHAIN", "CHAIN", "CHAIN"]  # no agent facts → no AGENT span
    assert spans[0]["attributes"]["session.id"] == "gh-run-1"


def _session_records():
    base = "2026-09-01T12:00:0{}.000Z"
    return [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": base.format(0),
         "sessionId": "sess-1", "content": "fix the build"},
        {"type": "user", "timestamp": base.format(1), "sessionId": "sess-1", "cwd": "/w/repo",
         "gitBranch": "main", "version": "2.1.0", "userType": "external", "entrypoint": "cli",
         "message": {"role": "user", "content": "fix the build"}},
        {"type": "assistant", "timestamp": base.format(2), "sessionId": "sess-1", "uuid": "u1",
         "message": {"id": "msg_1", "model": "claude-sonnet-5", "content": [
             {"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "make"}}],
             "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0}}},
        # a streamed duplicate of the same message (same id): folded, not a second turn
        {"type": "assistant", "timestamp": base.format(2), "sessionId": "sess-1", "uuid": "u1b",
         "message": {"id": "msg_1", "model": "claude-sonnet-5", "content": [], "usage": {"input_tokens": 10, "output_tokens": 7}}},
        {"type": "user", "timestamp": base.format(5), "sessionId": "sess-1",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant", "timestamp": base.format(6), "sessionId": "sess-1", "uuid": "u2",
         "message": {"id": "msg_2", "model": "claude-sonnet-5", "content": [{"type": "text", "text": "Fixed."}],
                     "usage": {"input_tokens": 12, "output_tokens": 3}}},
    ]


def test_session_spans_from_transcript():
    spans = fl.build_session_spans(_session_records(), "/x/sess-1.jsonl")
    kinds = [s["kind"] for s in spans]
    assert kinds == ["AGENT", "LLM", "TOOL", "LLM"], kinds
    root, turn1, tool, turn2 = spans
    assert root["attributes"]["session.id"] == "sess-1" and root["attributes"]["claude.turns"] == 2
    assert root["attributes"]["input.value"] == "fix the build" and root["attributes"]["claude.cwd"] == "/w/repo"
    assert turn1["parent_id"] == root["span_id"] and tool["parent_id"] == turn1["span_id"]
    assert tool["attributes"]["tool.name"] == "Bash" and json.loads(tool["attributes"]["input.value"]) == {"command": "make"}
    assert tool["end"] - tool["start"] == 3_000_000_000       # closed by the tool_result 3s later
    assert turn1["attributes"]["llm.token_count.completion"] == 7  # the last streamed usage wins
    assert turn2["attributes"]["output.value"] == "Fixed."
    assert root["start"] <= min(s["start"] for s in spans) and root["end"] >= max(s["end"] for s in spans)
    assert fl.build_session_spans([], "x") == [] and fl.build_session_spans([{"type": "x"}], "x") == []
    # deterministic across calls
    assert [s["span_id"] for s in fl.build_session_spans(_session_records(), "/x/sess-1.jsonl")] == \
        [s["span_id"] for s in spans]
    assert root["attributes"]["dash.trace_key"] == "session:sess-1" and root["attributes"]["claude.sidechain"] is False
    # a sub-agent transcript beside the main one carries the parent's sessionId:
    # same session.id, but its own trace key (and therefore its own trace id)
    side = fl.build_session_spans(_session_records(), "/x/agent-abc.jsonl")
    assert side[0]["attributes"]["session.id"] == "sess-1" and side[0]["attributes"]["claude.sidechain"] is True
    assert side[0]["attributes"]["dash.trace_key"] == "session:sess-1/agent-abc"
    assert side[0]["trace_id"] != root["trace_id"] and side[0]["name"].endswith("(sub-agent)")


def test_sqlite_upserts_idempotently_and_ledger_gates_selection():
    tmp = Path(tempfile.mkdtemp())
    try:
        conn = fl.connect(tmp)
        run, jobs, steps = _run_fixture()
        row = {**run, "head_branch": "main", "head_sha": "abc", "run_number": 1, "logs_url": "l", "ai": 1,
               "synced_at": "2026-09-01T08:00:00Z"}
        for _ in range(2):  # a second sync is an update, not a duplicate
            fl.upsert(conn, "runs", row, ["id"])
            for j in jobs:
                fl.upsert(conn, "jobs", {"id": j["id"], "run_id": run["id"], "nwo": run["nwo"], "name": j["name"],
                                         "status": "completed", "conclusion": j["conclusion"],
                                         "started_at": j["started_at"], "completed_at": j["completed_at"],
                                         "runner_name": j["runner_name"], "html_url": j["html_url"]}, ["id"])
                for s in steps[j["id"]]:
                    fl.upsert(conn, "steps", {"job_id": j["id"], "number": s["number"], "name": s["name"],
                                              "status": "completed", "conclusion": s["conclusion"],
                                              "started_at": s["started_at"], "completed_at": s["completed_at"]},
                              ["job_id", "number"])
            fl.record_agent_run(conn, run["id"], run["nwo"], fl.parse_agent_log(DOCTOR_LOG))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 3
        agent = conn.execute("SELECT * FROM agent_runs").fetchone()
        assert agent["num_turns"] == 134 and json.loads(agent["allowed_tools"]) == ["Bash(gh:*)", "Read", "Write"]
        # the bundle round-trips into the same spans the pure builder makes
        r, j, st, a = fl._run_bundle(conn, run["id"])
        spans = fl.build_run_spans(r, j, st, a)
        assert [s["kind"] for s in spans] == ["CHAIN", "CHAIN", "CHAIN", "AGENT"]
        # export ledger: selected until exported, then skipped unless forced
        assert fl.select_runs(conn, days=36500, limit=10, force=False) == [1]
        fl.upsert(conn, "exports", {"key": "run:bamr87/x:1", "kind": "run", "trace_id": fl.hex_trace(spans[0]["trace_id"]),
                                    "spans": len(spans), "endpoint": "http://phoenix", "exported_at": "2026-09-01T09:00:00Z"},
                  ["key"])
        conn.commit()
        assert fl.select_runs(conn, days=36500, limit=10, force=False) == []
        assert fl.select_runs(conn, days=36500, limit=10, force=True) == [1]
        conn.close()
        # the console documents
        status = fl.status_dict(tmp, probe=False)
        assert status["present"] and status["tables"]["runs"] == 1 and status["exports"]["count"] == 1
        assert status["agent_runs"]["count"] == 1 and status["agent_runs"]["models"] == {"claude-opus-5": 1}
        runs = fl.recent_runs(tmp, limit=5)
        assert runs and runs[0]["id"] == 1 and runs[0]["model"] == "claude-opus-5" and runs[0]["exported_at"]
        json.dumps(status); json.dumps(runs); json.dumps(fl.lines(tmp))
        assert fl.status_dict(tmp / "nowhere", probe=False)["present"] is False
        assert fl.recent_runs(tmp / "nowhere") == [] and fl.lines(tmp / "nowhere") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_owned_projects_excludes_external_and_filters():
    cfg = {"hub_nwo": "bamr87/bamr87"}
    registry = [{"name": "alpha", "repo_url": "https://github.com/bamr87/alpha"},
                {"name": "skills", "repo_url": "https://github.com/microsoft/skills"},
                {"name": "nourl"}]
    got = fl.owned_projects(registry, cfg, None)
    assert [nwo for _, nwo in got] == ["bamr87/bamr87", "bamr87/alpha"]   # hub injected first; external dropped
    assert [nwo for _, nwo in fl.owned_projects(registry, cfg, ["alpha"])] == ["bamr87/alpha"]
    assert [nwo for _, nwo in fl.owned_projects(registry, cfg, ["bamr87/bamr87"])] == ["bamr87/bamr87"]


def test_attribute_cleaning_and_time_helpers():
    a = fl._clean_attrs({"s": "x", "n": None, "d": {"k": 1}, "l": [1, "b"], "b": True, "f": 1.5})
    assert "n" not in a and a["d"] == '{"k": 1}' and a["l"] == ["1", "b"] and a["b"] is True
    assert fl.to_ns("2026-09-01T00:00:00Z") == 1788220800 * 1_000_000_000
    assert fl.to_ns(None) is None and fl.parse_iso("nope") is None
    assert fl.iso("2026-09-01T00:00:00Z") == "2026-09-01T00:00:00Z"


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
    print(f"{'FAIL' if failures else 'OK'} — fleet_lake fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

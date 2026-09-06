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


def test_recent_runs_surfaces_runs_that_actually_ran_the_agent():
    """The console's "Agent runs" table reads this.

    `runs.ai=1` marks an AI WORKFLOW, not a run that invoked the agent — a
    mention handler fires and skips on every issue comment. Ordering purely by
    recency therefore filled the window with skips and pushed every row that
    had a model/turns/cost out of the one view built to show them.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        conn = fl.connect(tmp)
        base = {"nwo": "bamr87/x", "workflow_name": "Claude", "workflow_path": ".github/workflows/claude.yml",
                "event": "issue_comment", "status": "completed", "head_branch": "main", "head_sha": "a",
                "run_number": 1, "logs_url": "l", "ai": 1, "synced_at": "2026-09-01T08:00:00Z",
                "html_url": "h", "run_attempt": 1}
        # 3 NEWER skipped runs, and 1 OLDER run that really ran the agent
        for i, (rid, created, concl) in enumerate([
                (901, "2026-09-03T00:00:00Z", "skipped"),
                (902, "2026-09-02T00:00:00Z", "skipped"),
                (903, "2026-09-01T12:00:00Z", "skipped"),
                (904, "2026-08-20T00:00:00Z", "success")]):
            fl.upsert(conn, "runs", {**base, "id": rid, "created_at": created,
                                     "run_started_at": created, "updated_at": created,
                                     "conclusion": concl}, ["id"])
        fl.record_agent_run(conn, 904, "bamr87/x", fl.parse_agent_log(DOCTOR_LOG))
        conn.commit()
        conn.close()
        rows = fl.recent_runs(tmp, limit=2)
        assert rows, "no runs returned"
        assert rows[0]["id"] == 904, [r["id"] for r in rows]      # agent run first
        assert rows[0]["model"] and rows[0]["num_turns"], rows[0]
        # recency still orders the rest
        assert rows[1]["id"] == 901, [r["id"] for r in rows]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def test_session_facts_mirror_the_spans_and_price_the_turns():
    facts = fl.session_facts(_session_records(), "/x/sess-1.jsonl", mtime="2026-09-01T12:10:00Z")
    sess, turns, tools = facts["session"], facts["turns"], facts["tools"]
    # the SAME trace key the exporter uses — a stored session joins to its trace
    spans = fl.build_session_spans(_session_records(), "/x/sess-1.jsonl")
    assert sess["key"] == spans[0]["attributes"]["dash.trace_key"] == "session:sess-1"
    assert sess["session_id"] == "sess-1" and sess["sidechain"] == 0 and sess["repo"]
    assert sess["turns"] == len(turns) == 2 and sess["tool_calls"] == len(tools) == 1
    assert sess["git_branch"] == "main" and sess["cwd"] == "/w/repo" and sess["version"] == "2.1.0"
    assert sess["first_prompt"] == "fix the build" and sess["mtime"] == "2026-09-01T12:10:00Z"
    # streamed duplicate folded: one turn, the LAST usage winning (output 7, not 5)
    # (the last usage replaces the first WHOLESALE — that is the streaming shape,
    # where the final usage message carries the turn's complete totals, so the
    # first record's cache_read of 100 is superseded by the duplicate's absence)
    assert turns[0]["message_id"] == "msg_1" and turns[0]["output_tokens"] == 7
    assert turns[0]["cache_read_tokens"] == 0 and turns[0]["tool_calls"] == 1
    assert json.loads(sess["models"]) == ["claude-sonnet-5"]
    assert sess["input_tokens"] == 22 and sess["output_tokens"] == 10   # summed over both turns
    # a priced model yields a real cost — a $0 total would mean a missing PRICING row
    assert sess["cost_usd"] > 0 and turns[0]["cost_usd"] > 0
    # the tool call is closed by its tool_result, 3s later, and did not error
    assert tools[0]["name"] == "Bash" and tools[0]["duration_ms"] == 3000 and tools[0]["is_error"] == 0
    assert sess["tool_errors"] == 0
    assert fl.session_facts([], "/x/y.jsonl") is None and fl.session_facts([{"type": "x"}], "/x/y.jsonl") is None
    # a sub-agent transcript gets its own row, not a collision with the parent's
    side = fl.session_facts(_session_records(), "/x/agent-abc.jsonl")
    assert side["session"]["key"] == "session:sess-1/agent-abc" and side["session"]["sidechain"] == 1


def test_tool_result_errors_are_counted():
    recs = _session_records()
    for r in recs:
        content = (r.get("message") or {}).get("content")
        if isinstance(content, list) and content and content[0].get("type") == "tool_result":
            content[0]["is_error"] = True
    facts = fl.session_facts(recs, "/x/sess-1.jsonl")
    assert facts["session"]["tool_errors"] == 1 and facts["tools"][0]["is_error"] == 1


def test_store_session_replaces_rather_than_appends():
    tmp = Path(tempfile.mkdtemp())
    try:
        conn = fl.connect(tmp)
        facts = fl.session_facts(_session_records(), "/x/sess-1.jsonl")
        for _ in range(2):                      # re-extracting the same transcript
            fl.store_session(conn, facts)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM session_turns").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM session_tools").fetchone()[0] == 1
        # a RESUMED session is shorter-or-longer, never additive: rows mirror the transcript
        grown = fl.session_facts(_session_records()[:3], "/x/sess-1.jsonl")
        fl.store_session(conn, grown)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM session_turns").fetchone()[0] == 1
        status = fl.status_dict(tmp, probe=False)
        assert status["sessions"]["count"] == 1 and status["tables"]["session_tools"] == 1
        json.dumps(status)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_review_unifies_both_planes_and_finds_problems():
    tmp = Path(tempfile.mkdtemp())
    try:
        assert fl.review(tmp / "nowhere")["present"] is False
        conn = fl.connect(tmp)
        fl.store_session(conn, fl.session_facts(_session_records(), "/x/sess-1.jsonl"))
        run, jobs, steps = _run_fixture()
        fl.upsert(conn, "runs", {**run, "head_branch": "main", "head_sha": "a", "run_number": 1,
                                 "logs_url": "l", "ai": 1, "synced_at": "2026-09-01T08:00:00Z"}, ["id"])
        fl.record_agent_run(conn, run["id"], run["nwo"], fl.parse_agent_log(DOCTOR_LOG))
        conn.commit()
        conn.close()
        doc = fl.review(tmp, days=36500)
        assert doc["present"]
        assert doc["local"]["sessions"] == 1 and doc["local"]["turns"] == 2
        assert doc["ci"]["agent_runs"] == 1 and doc["ci"]["runs"] == 1
        # the two planes are summed, not reported separately only
        assert doc["totals"]["cost_usd"] == round(doc["local"]["cost_usd"] + doc["ci"]["cost_usd"], 4)
        assert doc["totals"]["turns"] == doc["local"]["turns"] + doc["ci"]["turns"]
        assert doc["local"]["tools"][0]["name"] == "Bash"
        assert doc["ci"]["models"] == {"claude-opus-5": 1}
        # nothing exported yet -> both planes count as untraced, and it is flagged
        assert doc["totals"]["untraced"] == 2
        assert any(f["title"] == "traces not shipped to Phoenix" for f in doc["findings"])
        json.dumps(doc, default=str)
        # the window actually excludes: a 0-day window sees nothing
        assert fl.review(tmp, days=0)["totals"]["traces"] == 0
        # repo filter narrows the local plane to a repo that has no sessions
        assert fl.review(tmp, days=36500, repo="nope")["local"]["sessions"] == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_review_survives_a_lake_that_predates_the_session_tables():
    """A lake built before `lake sessions` existed has no session tables. Review
    must report an empty local plane, not die on `no such table: sessions`."""
    tmp = Path(tempfile.mkdtemp())
    try:
        conn = fl.connect(tmp)
        for t in ("sessions", "session_turns", "session_tools"):
            conn.execute(f"DROP TABLE {t}")
        conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        doc = fl.review(tmp, days=36500)          # must not raise
        assert doc["present"] and doc["local"]["sessions"] == 0
        assert fl.status_dict(tmp, probe=False)["present"]     # guarded the same way
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_findings_flag_unpriced_models_and_ci_failures():
    import ai_activity
    # every model the fixtures use must be priced, or every cost total is a lie
    for m in ("claude-opus-5", "claude-sonnet-5"):
        assert ai_activity.normalize_model(m) in ai_activity.PRICING, m
    f = fl._findings({"local": {"models": {"claude-made-up-9": 3}}, "ci": {}, "totals": {}})
    assert any("claude-made-up-9" in x["detail"] for x in f if x["title"] == "models with no price row")
    f2 = fl._findings({"local": {}, "ci": {"errors": 2, "agent_runs": 5, "denials": 4,
                                           "failed_runs": 1, "runs": 5}, "totals": {}})
    titles = {x["title"] for x in f2}
    assert "CI agent runs ended in error" in titles and "permission denials in CI" in titles
    assert "AI workflow runs failed" in titles
    assert all(x["severity"] in ("error", "warn", "info") for x in f2)


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


def test_otel_probe_answers_instead_of_raising():
    """`lake export` asks this before shipping, to print an install hint.

    find_spec() on a dotted name imports the parent package, so on an
    interpreter without opentelemetry the probe RAISED ModuleNotFoundError and
    the hint never printed — the console surfaced a traceback on every real
    export instead. It must return a bool either way.
    """
    assert isinstance(fl._otel_available(), bool)


def test_seven_digit_subsecond_stamps_parse_on_every_interpreter():
    """claude-code-action logs .NET-style 100ns ticks — SEVEN fractional digits.
    fromisoformat took only 3 or 6 before Python 3.11, so this used to parse as
    None on an older interpreter and crash the export in _agent_step."""
    ns = fl.to_ns("2026-09-01T06:49:38.2932628Z")
    assert ns == 1788245378293262080, ns                     # truncated to µs, not dropped
    assert fl.to_ns("2026-09-01T06:49:38.293262Z") == ns     # same instant, 6 digits
    assert fl.to_ns("2026-09-01T06:49:38.29326289Z") == ns   # 8 digits too
    # and the crash itself: an unparseable stamp must not take the run down
    steps = [{"number": 1, "name": "Set up job", "started_at": "not-a-date", "completed_at": None},
             {"number": 2, "name": "Diagnose", "started_at": "2026-09-01T06:49:18Z",
              "completed_at": "2026-09-01T07:03:54Z"}]
    picked = fl._agent_step(steps, {"started_at": "2026-09-01T06:49:38.2932628Z"})
    assert picked and picked["number"] == 2, picked
    assert fl._agent_step(steps, {"started_at": "not-a-date"})["number"] == 2


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

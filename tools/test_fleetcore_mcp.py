#!/usr/bin/env python3
"""
Fixture tests for tools/fleetcore/mcp_server.py — the fleet console as an MCP
server, the agent's write path into the console's job API.

test_fleetcore.py covers the handshake and one refusal. These pin the rest:

  * every `console_*` tool goes through fleetcore.client to the console, with
    the arguments it was given and nothing else; `console_run` passes confirm
    through as a bool and defaults to confirm=false, so the console's own
    confirm-before-GitHub-write gate decides;
  * a console refusal (ConsoleError) and bad arguments come back as tool errors
    (isError: true), never as a crash or a JSON-RPC protocol error;
  * an unknown tool or method is a JSON-RPC error; notifications get no reply;
  * a long job log is cut to the last 20 000 characters and marked truncated;
  * the token comes from DASH_CONSOLE_TOKEN, else the DASH_CONSOLE_TOKEN line of
    .env — parsed, never sourced, quotes stripped, other lines ignored;
  * the stdio loop answers a parse error with -32700 and skips blank lines.

Reads the real registry for the fleet_* tools; no console, no network, no pytest:

    python3 tools/test_fleetcore_mcp.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleetcore import mcp_server as m  # noqa: E402
from fleetcore.client import ConsoleClient, ConsoleError  # noqa: E402


class FakeConsole:
    def __init__(self, refuse: str | None = None, log: str = "line\n"):
        self.calls, self.refuse, self.log = [], refuse, log

    def _rec(self, *call):
        self.calls.append(call)
        if self.refuse:
            raise ConsoleError(self.refuse)

    def ops(self):
        self._rec("ops")
        return [{"id": "status", "remote": False}]

    def submit(self, op, params=None, confirm=False):
        self._rec("submit", op, params, confirm)
        return {"id": "0123456789ab", "op": op, "status": "queued"}

    def jobs(self):
        self._rec("jobs")
        return [{"id": f"{i:012x}"} for i in range(30)]

    def tail(self, job_id, offset=0):
        self._rec("tail", job_id, offset)
        return {"text": self.log, "offset": offset + len(self.log), "done": True}

    def cancel(self, job_id):
        self._rec("cancel", job_id)
        return {"id": job_id, "status": "cancelled"}


def call(name, args=None, mid=7):
    r = m.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                  "params": {"name": name, "arguments": args or {}}})
    assert r["id"] == mid and "result" in r, r
    return json.loads(r["result"]["content"][0]["text"]), r["result"]["isError"]


class WithConsole:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.real, m.console = m.console, (lambda: self.fake)
        return self.fake

    def __exit__(self, *exc):
        m.console = self.real


def test_console_tools_pass_exactly_their_arguments():
    with WithConsole(FakeConsole()) as fake:
        assert call("console_ops") == ({"ops": [{"id": "status", "remote": False}]}, False)
        res, err = call("console_run", {"op": "status"})
        assert not err and res["job"]["op"] == "status"
        res, err = call("console_run", {"op": "fanout", "params": {"target": "x"}, "confirm": 1})
        jobs, _ = call("console_jobs", {"limit": 5})
        all_jobs, _ = call("console_jobs")
        call("console_job_log", {"job_id": "0123456789ab", "offset": 12})
        call("console_cancel", {"job_id": "0123456789ab"})
    assert fake.calls == [
        ("ops",),
        ("submit", "status", {}, False),        # confirm defaults to False: the console's gate decides
        ("submit", "fanout", {"target": "x"}, True),
        ("jobs",), ("jobs",),
        ("tail", "0123456789ab", 12),
        ("cancel", "0123456789ab"),
    ], fake.calls
    assert len(jobs["jobs"]) == 5 and len(all_jobs["jobs"]) == 20


def test_console_refusal_is_a_tool_error_not_a_crash():
    with WithConsole(FakeConsole(refuse="'fanout' writes to GitHub — resubmit with confirm=true")):
        res, err = call("console_run", {"op": "fanout", "params": {"apply": True}})
    assert err is True and "confirm=true" in res["error"], res


def test_bad_arguments_are_tool_errors():
    with WithConsole(FakeConsole()):
        res, err = call("console_run", {})               # missing op → KeyError
        assert err and res["error"].startswith("bad arguments"), res
        res, err = call("console_jobs", {"limit": "many"})  # ValueError
        assert err and res["error"].startswith("bad arguments"), res
        res, err = call("console_job_log", {})
        assert err and "job_id" in res["error"], res


def test_long_logs_are_truncated_to_the_tail():
    with WithConsole(FakeConsole(log="a" * 5 + "b" * 25000)):
        res, err = call("console_job_log", {"job_id": "0123456789ab"})
    assert not err and res["truncated"] is True and len(res["text"]) == 20000 and set(res["text"]) == {"b"}
    with WithConsole(FakeConsole(log="short")):
        res, _ = call("console_job_log", {"job_id": "0123456789ab"})
    assert res["text"] == "short" and "truncated" not in res


def test_protocol_edges():
    assert m.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}) is None
    assert m.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"})["result"] == {}
    r = m.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "rm_rf"}})
    assert r["error"]["code"] == -32602 and "rm_rf" in r["error"]["message"]
    r = m.handle({"jsonrpc": "2.0", "id": 3, "method": "initialize"})  # no params: default version
    assert r["result"]["protocolVersion"] == "2025-06-18" and "confirm=true" in r["result"]["instructions"]
    tools = m.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})["result"]["tools"]
    for t in tools:
        assert t["inputSchema"]["additionalProperties"] is False, t["name"]
        writes = t["name"] in ("console_run", "console_cancel")
        assert t["annotations"].get("readOnlyHint") is (not writes), t["name"]


def test_read_tools_over_the_committed_signals():
    with Env(DASH_DOCKER_HOST=""):
        ov, err = call("fleet_overview")
        assert not err and "kpis" in ov and isinstance(ov["tripped_wires"], list)
        assert all(r["worst_level"] == "red" for r in ov["attention"]) and len(ov["attention"]) <= 10
        inbox, err = call("fleet_inbox", {"limit": 2})
        assert not err and len(inbox["items"]) <= 2 and inbox["count"] >= len(inbox["items"])
        apps, err = call("fleet_apps", {"query": "zzzz-no-such-project"})
        assert not err and apps["count"] == 0 and apps["rows"] == []
        docker, err = call("fleet_docker")
        assert not err and docker["hosts"] == [] and docker["containers"] == []


class Env:
    def __init__(self, **kw):
        self.kw, self.saved = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.saved[k] = os.environ.get(k)
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_token_from_env_else_dotenv_parsed_never_sourced():
    d = Path(tempfile.mkdtemp())
    assert m._dotenv_token(d) == ""
    (d / ".env").write_text("# comment\nOTHER=1\nexport_ME=$(rm -rf /)\n DASH_CONSOLE_TOKEN = 'tok-123' \n")
    assert m._dotenv_token(d) == "tok-123"
    (d / ".env").write_text("DASH_CONSOLE_TOKEN_OLD=x\nnot a pair\n")
    assert m._dotenv_token(d) == ""
    with Env(DASH_CONSOLE_URL="http://127.0.0.1:9", DASH_CONSOLE_TOKEN="from-env"):
        c = m.console()
    assert isinstance(c, ConsoleClient) and c.url == "http://127.0.0.1:9" and c.token == "from-env"
    real = m._dotenv_token
    m._dotenv_token = lambda root=m.ROOT: "from-dotenv"
    try:
        with Env(DASH_CONSOLE_URL=None, DASH_CONSOLE_TOKEN=None):
            c = m.console()
        assert c.url == "http://127.0.0.1:4001" and c.token == "from-dotenv"
    finally:
        m._dotenv_token = real


def test_stdio_loop():
    lines = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        "",
        "{broken",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps([1, 2]),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "nope"}),
    ]) + "\n"
    sin, sout = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(lines), io.StringIO()
    try:
        m.main()
        out = sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = sin, sout
    replies = [json.loads(x) for x in out.splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2], replies
    assert replies[1]["error"]["code"] == -32700 and replies[2]["error"]["code"] == -32601


def main() -> int:
    failed = 0
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in cases:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

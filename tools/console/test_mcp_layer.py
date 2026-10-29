#!/usr/bin/env python3
"""Unit tests for the Harness Console MCP layer (mcp_layer/) — mocked HTTP, no console, no network.

    python3 tools/console/test_mcp_layer.py      (needs the `mcp` package; skips cleanly without it)
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import anyio
    from mcp import Client
    from mcp_layer import server as srv
    from mcp_layer.client import Console, ConsoleError, dotenv_value
except ModuleNotFoundError as e:  # pragma: no cover
    print(f"skip: {e} (pip install mcp)")
    sys.exit(0)

STATE = {
    "generated_at": "t0", "git": {"head": "abc"}, "sources": {},
    "health": {"generated_at": "t", "scorecard": {"score": 5}, "tripped_count": 1, "note": "",
               "trip_wires": [{"id": "a", "tripped": False}, {"id": "b", "tripped": True}]},
    "harnesses": {"totals": {"repos": 2}, "repos": [{"name": "it-journey", "score": 3}]},
    "usage": {"ai": {"spend_usd": 12.5, "by_day": [1, 2]}, "actions": {"totals": {"total_min": 9}, "by_day": []}},
    "contract": {"hub": {"ai_budget_usd": 100, "other": 1}, "monthly_budget": 50},
    "loops": [{"id": "scout"}],
}


class FakeConsole(Console):
    def __init__(self, routes: dict | None = None):
        super().__init__(url="http://fake", token="s3cret-token")
        self.routes = {"/api/state": STATE, "/api/health": {"ok": True}, **(routes or {})}
        self.calls: list[tuple] = []

    def request(self, method, path, query=None, body=None):
        self.calls.append((method, path, {k: v for k, v in (query or {}).items() if v not in (None, "")}, body))
        hit = self.routes.get((method, path), self.routes.get(path))
        if isinstance(hit, Exception):
            raise hit
        if hit is None:
            raise ConsoleError(f"console {method} {path} -> 404: not found", 404)
        return hit


def call(server, name, args=None):
    """Through the real protocol (in-memory client), so tool errors arrive as isError results."""
    async def go():
        async with Client(server) as cl:
            return await cl.call_tool(name, args or {})
    res = anyio.run(go)
    text = "".join(getattr(b, "text", "") for b in res.content)
    return res, text


def payload(res, text):
    sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(text)


def tool_names(server):
    return {t.name for t in anyio.run(server.list_tools)}


class ReadTools(unittest.TestCase):
    def test_writes_hidden_by_default(self):
        with mock.patch.dict(os.environ, {"HARNESS_MCP_ALLOW_WRITES": ""}):
            names = tool_names(srv.build_server(FakeConsole()))
        self.assertIn("fleet_status", names)
        self.assertFalse({"run_op", "cancel_job", "workflow_kill_switch"} & names)

    def test_read_tools_are_annotated_read_only(self):
        for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False).list_tools):
            self.assertTrue(t.annotations.read_only_hint, t.name)

    def test_harness_health_tripped_first(self):
        res, text = call(srv.build_server(FakeConsole()), "harness_health")
        self.assertFalse(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertEqual(payload(res, text)["trip_wires"][0]["id"], "b")

    def test_fleet_status_trims_and_passes_query(self):
        rows = [{"name": f"p{i}", "status": "active", "secret_field": "x"} for i in range(5)]
        fc = FakeConsole({"/api/fleet": {"rows": rows, "kpis": {"n": 5}}})
        res, text = call(srv.build_server(fc), "fleet_status", {"q": "web", "limit": 2})
        p = payload(res, text)
        self.assertEqual(p["total"], 5)
        self.assertEqual(len(p["rows"]), 2)
        self.assertNotIn("secret_field", p["rows"][0])
        self.assertEqual(fc.calls[-1][2], {"q": "web", "sort": "featured"})

    def test_spend_vs_budget_drops_series_and_finds_budgets(self):
        p = payload(*call(srv.build_server(FakeConsole()), "spend_vs_budget"))
        self.assertEqual(p["ai"], {"spend_usd": 12.5})
        self.assertEqual(p["budgets"], {"monthly_budget": 50, "hub.ai_budget_usd": 100})

    def test_job_log_tail(self):
        fc = FakeConsole({"/api/jobs/j1": {"status": "running", "log": "x" * 50 + "END"}})
        p = payload(*call(srv.build_server(fc), "job_log", {"job_id": "j1", "tail_chars": 10}))
        self.assertTrue(p["log_truncated"])
        self.assertTrue(p["log"].endswith("END"))
        self.assertEqual(len(p["log"]), 10)

    def test_live_snapshot_404_explains_dependency(self):
        res, text = call(srv.build_server(FakeConsole()), "live_snapshot")
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("#432", text)

    def test_workflow_lines_noswitch_filter(self):
        rows = [{"nwo": "bamr87/a", "switch": None}, {"nwo": "bamr87/b", "switch": "vars.B_ENABLED"}]
        p = payload(*call(srv.build_server(FakeConsole({"/api/lake/lines": rows})), "workflow_lines", {"filter": "noswitch"}))
        self.assertEqual([r["nwo"] for r in p["rows"]], ["bamr87/a"])

    def test_code_search_routes_mode(self):
        fc = FakeConsole({"/api/index/harmonize": {"hits": []}})
        call(srv.build_server(fc), "code_search", {"q": "retry", "mode": "harmonize"})
        self.assertEqual(fc.calls[-1][1:3], ("/api/index/harmonize", {"q": "retry"}))

    def test_console_error_is_tool_error_without_token(self):
        fc = FakeConsole({"/api/fleet/docker": ConsoleError("console GET /api/fleet/docker -> 401: bad token", 401)})
        res, text = call(srv.build_server(fc), "fleet_docker")
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("401", text)
        self.assertNotIn("s3cret-token", text)

    def test_clip_marks_truncation(self):
        out = srv.clip({"a": "y" * 5000}, limit=100)
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["json_prefix"]), 100)

    def test_resources_listed(self):
        uris = {str(r.uri) for r in anyio.run(srv.build_server(FakeConsole()).list_resources)}
        self.assertTrue({"harness://overview", "harness://health", "harness://ops", "harness://deep-dive"} <= uris)


class WriteTools(unittest.TestCase):
    def setUp(self):
        self.fc = FakeConsole({("POST", "/api/jobs"): {"id": "j9"}, ("POST", "/api/jobs/j9/cancel"): {"ok": True},
                               ("POST", "/api/github/repos/bamr87/x/actions"): {"ok": True}})
        self.s = srv.build_server(self.fc, allow_writes=True)

    def test_write_tools_destructive(self):
        w = {t.name: t for t in anyio.run(self.s.list_tools) if t.name in ("run_op", "cancel_job", "workflow_kill_switch")}
        self.assertEqual(len(w), 3)
        self.assertTrue(all(t.annotations.destructive_hint for t in w.values()))

    def test_refused_without_confirm_and_no_http(self):
        for name, args in (("run_op", {"op": "health"}), ("cancel_job", {"job_id": "j9"}),
                           ("workflow_kill_switch", {"owner": "bamr87", "repo": "x", "workflow_id": 1, "enabled": False})):
            res, text = call(self.s, name, args)
            self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError, name)
            self.assertIn("confirm=true", text)
        self.assertFalse([c for c in self.fc.calls if c[0] == "POST"])

    def test_confirmed_calls_hit_console(self):
        call(self.s, "run_op", {"op": "health", "params": {"repo": "x"}, "confirm": True})
        self.assertEqual(self.fc.calls[-1], ("POST", "/api/jobs", {}, {"op": "health", "params": {"repo": "x"}, "confirm": True}))
        call(self.s, "workflow_kill_switch", {"owner": "bamr87", "repo": "x", "workflow_id": 7, "enabled": False, "confirm": True})
        self.assertEqual(self.fc.calls[-1][3], {"action": "workflow.disable", "params": {"workflow_id": 7}, "confirm": True})


class HttpClient(unittest.TestCase):
    def test_dotenv_parsed_not_sourced(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text("# c\nOTHER=1\nDASH_CONSOLE_TOKEN='abc'\n$(rm -rf /)\n")
            self.assertEqual(dotenv_value("DASH_CONSOLE_TOKEN", Path(d)), "abc")
            self.assertEqual(dotenv_value("MISSING", Path(d)), "")

    def test_repr_hides_token(self):
        self.assertNotIn("tok123", repr(Console(url="http://x", token="tok123")))

    def test_http_error_becomes_console_error(self):
        err = urllib.error.HTTPError("http://x/api/state", 403, "no", {}, io.BytesIO(b'{"detail":"forbidden"}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ConsoleError) as cm:
                Console(url="http://x", token="tok123").get("/api/state")
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("forbidden", str(cm.exception))
        self.assertNotIn("tok123", str(cm.exception))

    def test_sends_bearer(self):
        seen = {}

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req, timeout):
            seen["auth"] = req.get_header("Authorization")
            seen["url"] = req.full_url
            return R(b'{"ok": true}')
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            self.assertEqual(Console(url="http://x", token="t").get("/api/jobs/1", offset=0, empty=""), {"ok": True})
        self.assertEqual(seen["auth"], "Bearer t")
        self.assertEqual(seen["url"], "http://x/api/jobs/1?offset=0")


class HttpTransport(unittest.TestCase):
    def test_bearer_required(self):
        from starlette.testclient import TestClient
        app = srv.http_app(srv.build_server(FakeConsole()), "127.0.0.1", 4002, "tok")
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        hdr = {"Accept": "application/json, text/event-stream", "Host": "127.0.0.1:4002"}
        with TestClient(app, base_url="http://127.0.0.1:4002") as tc:
            self.assertEqual(tc.post("/mcp", json=init, headers=hdr).status_code, 401)
            self.assertEqual(tc.post("/mcp", json=init, headers={**hdr, "Authorization": "Bearer nope"}).status_code, 401)
            ok = tc.post("/mcp", json=init, headers={**hdr, "Authorization": "Bearer tok"})
            self.assertEqual(ok.status_code, 200, ok.text[:300])
            self.assertIn("harness-console", ok.text)
            evil = tc.post("/mcp", json=init, headers={**hdr, "Host": "evil.example", "Authorization": "Bearer tok"})
            self.assertGreaterEqual(evil.status_code, 400)

    def test_refuses_empty_token(self):
        with self.assertRaises(ValueError):
            srv.BearerAuth(lambda *a: None, "")


if __name__ == "__main__":
    unittest.main(verbosity=1)

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

LANES = ("triage", "ready", "doing", "review", "blocked", "hold")


def BOARD(n: int) -> dict:
    """A work board shaped like /api/work's: aggregate blocks plus `items`, each carrying a fat `detail`."""
    return {
        "schema": "work-board/v1", "generated_at": "t0", "preview": False,
        "lanes": [{"id": lane, "label": lane.title(), "count": 0} for lane in LANES],
        "loops": [{"id": "t1", "lane": "triage", "capacity": 3}],
        "totals": {"items": n}, "sources": {"issues": "github"}, "labels": {"P0": "priority:P0"},
        "priorities": ["P0", "P1", "P2", "P3"], "roadmap_statuses": ["draft"], "hints": ["pins win"],
        "queue_path": "_data/work_queue.yml",
        "repos": [{"name": f"r{i}"} for i in range(8)],
        "items": [{
            "key": f"issue:bamr87/r{i % 8}#{i}", "kind": "issue", "ref": f"#{i}",
            "title": f"item {i} " + "long title padding " * 8, "repo": f"r{i % 8}", "nwo": f"bamr87/r{i % 8}",
            "lane": LANES[i % len(LANES)], "stage": "intake", "priority": f"P{i % 4}",
            "priority_source": "computed", "rank": None, "size": "size:m", "age_days": i, "idle_days": 1,
            "readiness": 33, "autonomy": "assisted", "autonomy_reason": "type `security` gets human review",
            "labels": ["automation"], "movable": ["ready", "blocked"], "moved": None, "progress": None,
            "note": None, "next_run": 1, "loop": "t1",
            "detail": {"number": i, "body": "x" * 600,
                       "gaps": [{"id": f"g{j}", "what": "something missing"} for j in range(6)]},
        } for i in range(n)],
    }


DOCKER_DOWN = {
    "hosts": ["local", "forge"], "containers": [],
    "errors": {"local": "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                        "Is the docker daemon running?",
               "forge": "error during connect: command [ssh -- forge docker system dial-stdio] exited with "
                        "status 255: ssh: Could not resolve hostname forge: Name or service not known"},
    "polled_at": "t0",
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

    # ------------------------------------------------------------ work board
    # /api/work is the whole board: 394 items, ~390k characters, which clip()
    # turned into a prefix the client read as nothing.
    def test_work_board_pages_and_summarises_by_default(self):
        board = BOARD(240)
        p = payload(*call(srv.build_server(FakeConsole({"/api/work": board})), "work_board"))
        self.assertEqual((p["total"], p["matched"], p["returned"], p["offset"]), (240, 240, 40, 0))
        self.assertEqual(p["next_offset"], 40)
        self.assertTrue(p["summary"])
        # the fat per-item record is gone, the identity and rank fields stay
        self.assertNotIn("detail", p["items"][0])
        self.assertEqual(p["items"][0]["key"], "issue:bamr87/r0#0")
        self.assertIn("priority", p["items"][0])
        # the board's own context blocks survive, so a page is still readable
        self.assertEqual(p["lanes"], board["lanes"])
        self.assertEqual(p["totals"], board["totals"])
        self.assertLess(len(json.dumps(p)), 30000)

    def test_work_board_full_items_are_capped_and_summary_is_much_smaller(self):
        fc = FakeConsole({"/api/work": BOARD(240)})
        big = payload(*call(srv.build_server(fc), "work_board", {"summary": False, "limit": 500}))
        self.assertEqual(big["limit"], 25)
        self.assertIn("detail", big["items"][0])
        small = payload(*call(srv.build_server(fc), "work_board", {"summary": True, "limit": 25}))
        self.assertLess(len(json.dumps(small["items"])), len(json.dumps(big["items"])) / 2)

    def test_work_board_filters_and_offset(self):
        fc = FakeConsole({"/api/work": BOARD(240)})
        s = srv.build_server(fc)
        p = payload(*call(s, "work_board", {"lane": "ready"}))
        self.assertEqual(p["filters"], {"lane": "ready"})
        self.assertTrue(p["matched"] < 240 and p["matched"] > 0)
        self.assertEqual({i["lane"] for i in p["items"]}, {"ready"})
        self.assertEqual(sum(p["matched_by_lane"].values()), p["matched"])
        # the last page says so
        last = payload(*call(s, "work_board", {"offset": 200}))
        self.assertIsNone(last["next_offset"])
        self.assertEqual(last["returned"], 40)
        self.assertEqual(payload(*call(s, "work_board", {"offset": 1000}))["returned"], 0)
        # q is a substring over the identity fields
        self.assertEqual(payload(*call(s, "work_board", {"q": "r3#7"}))["matched"], 1)
        # an unknown filter value matches nothing rather than everything
        self.assertEqual(payload(*call(s, "work_board", {"lane": "nosuch"}))["matched"], 0)

    def test_compact_item_cuts_a_long_title_and_drops_empties(self):
        row = srv.compact_item({"key": "k", "title": "t" * 400, "rank": None, "labels": [], "lane": "ready"})
        self.assertEqual(len(row["title"]), srv.BOARD_TITLE_CHARS)
        self.assertTrue(row["title"].endswith("…"))
        self.assertNotIn("rank", row)
        self.assertNotIn("labels", row)

    # --------------------------------------------------------------- docker
    def test_fleet_docker_errors_with_the_remedy_when_no_host_answers(self):
        fc = FakeConsole({"/api/fleet/docker": DOCKER_DOWN})
        res, text = call(srv.build_server(fc), "fleet_docker")
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("no Docker host is reachable", text)
        self.assertIn("no Docker socket in this process (by design)", text)
        self.assertIn("ssh to the host failed", text)
        self.assertIn("tools/dash docker ps", text)
        self.assertNotIn("s3cret-token", text)

    def test_fleet_docker_returns_containers_when_one_host_answers(self):
        doc = {"hosts": ["local", "forge"], "containers": [{"name": "fleet-console-1"}],
               "errors": {"forge": "ssh: Could not resolve hostname forge"}}
        p = payload(*call(srv.build_server(FakeConsole({"/api/fleet/docker": doc})), "fleet_docker"))
        self.assertEqual(p["reachable_hosts"], ["local"])
        self.assertEqual(p["unreachable_hosts"], {"forge": "ssh to the host failed"})
        self.assertNotIn("advice", p)
        self.assertEqual(p["containers"], doc["containers"])

    def test_docker_reason_classifies_without_leaking_a_wall_of_text(self):
        self.assertEqual(srv.docker_reason("Cannot connect to the Docker daemon at unix:///var/run/docker.sock."),
                         "no Docker socket in this process (by design)")
        self.assertEqual(srv.docker_reason("x" * 900 + "\nsecond line"), "x" * 200)
        self.assertEqual(srv.docker_reason(""), "unknown error")

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


class ClaudeTelemetryTool(unittest.TestCase):
    def test_passes_window_and_session(self):
        fc = FakeConsole({"/api/claude-telemetry": {"cost_label": "API-equivalent (estimate)"}})
        res, text = call(srv.build_server(fc), "claude_telemetry", {"window": "1h", "session": "abcd"})
        self.assertEqual(payload(res, text)["cost_label"], "API-equivalent (estimate)")
        self.assertEqual(fc.calls[-1][:3], ("GET", "/api/claude-telemetry", {"window": "1h", "limit": 20, "session": "abcd"}))


class MergedFleet(unittest.TestCase):
    """tools/fleetcore/mcp_server.py folded in: same names, the legacy writes only on --fleet-compat or writes on."""
    LEGACY_READ = {"fleet_overview", "fleet_apps", "fleet_inbox", "fleet_docker", "fleet_work",
                   "console_ops", "console_jobs", "console_job_log"}

    def test_legacy_names_present_writes_gated(self):
        names = tool_names(srv.build_server(FakeConsole(), allow_writes=False, fleet_compat=False))
        self.assertTrue(self.LEGACY_READ <= names, self.LEGACY_READ - names)
        self.assertFalse({"console_run", "console_cancel"} & names)
        compat = {t.name: t for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False, fleet_compat=True).list_tools)}
        self.assertTrue(compat["console_run"].annotations.destructive_hint)
        self.assertNotIn("run_op", compat)

    def test_console_aliases_and_run_pass_confirm(self):
        fc = FakeConsole({"/api/ops": [{"id": "status"}], ("POST", "/api/jobs"): {"id": "j1"}})
        s = srv.build_server(fc, allow_writes=False, fleet_compat=True)
        self.assertEqual(payload(*call(s, "console_ops"))["items"], [{"id": "status"}])
        call(s, "console_run", {"op": "status"})
        self.assertEqual(fc.calls[-1], ("POST", "/api/jobs", {}, {"op": "status", "params": {}, "confirm": False}))

    def test_fleet_reads_use_committed_signals(self):
        s = srv.build_server(FakeConsole(), allow_writes=False)
        with mock.patch.dict(os.environ, {"DASH_DOCKER_HOST": ""}):
            ov = payload(*call(s, "fleet_overview"))
            self.assertIn("kpis", ov)
            apps = payload(*call(s, "fleet_apps", {"query": "zzzz-no-such-project"}))
            self.assertEqual(apps["count"], 0)


class Tokens(unittest.TestCase):
    def test_http_token_never_falls_back_to_console_token(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text("DASH_CONSOLE_TOKEN=console-only\n")
            env = {"HARNESS_MCP_DOTENV": str(Path(d, ".env")), "DASH_CONSOLE_TOKEN": "console-only"}
            with mock.patch.dict(os.environ, env):
                os.environ.pop("HARNESS_MCP_TOKEN", None)
                self.assertEqual(srv.http_token(), "")
            Path(d, ".env").write_text("DASH_CONSOLE_TOKEN=c\nHARNESS_MCP_TOKEN=mcp-own\n")
            with mock.patch.dict(os.environ, env):
                os.environ.pop("HARNESS_MCP_TOKEN", None)
                self.assertEqual(srv.http_token(), "mcp-own")

    def test_host_header_override(self):
        seen = {}

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req, timeout):
            seen["host"] = req.get_header("Host")
            return R(b"{}")
        with mock.patch.dict(os.environ, {"DASH_CONSOLE_HOST_HEADER": "127.0.0.1:4001"}), \
                mock.patch("urllib.request.urlopen", side_effect=fake):
            Console(url="http://console:4001", token="t").get("/api/health")
        self.assertEqual(seen["host"], "127.0.0.1:4001")


class HttpTransport(unittest.TestCase):
    def test_tunnel_host_allowed_only_when_named(self):
        from starlette.testclient import TestClient
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        hdr = {"Accept": "application/json, text/event-stream", "Host": "x-y.trycloudflare.com",
               "Origin": "https://x-y.trycloudflare.com", "Authorization": "Bearer tok"}
        for extra, want in (([], False), (["x-y.trycloudflare.com"], True)):
            app = srv.http_app(srv.build_server(FakeConsole()), "127.0.0.1", 4002, "tok", extra)
            with TestClient(app, base_url="http://127.0.0.1:4002") as tc:
                self.assertEqual(tc.post("/mcp", json=init, headers=hdr).status_code == 200, want, extra)

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

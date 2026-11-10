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
        return hit(body) if callable(hit) else hit


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
        with mock.patch.dict(os.environ, {"HARNESS_MCP_ALLOW_WRITES": "", "HARNESS_MCP_SCOPES": ""}):
            names = tool_names(srv.build_server(FakeConsole()))
        self.assertIn("fleet_status", names)
        self.assertFalse({"run_op", "cancel_job", "workflow_kill_switch"} & names)
        self.assertFalse({"job_dispatch", "job_cancel", "work_apply"} & names)

    def test_read_tools_are_annotated_read_only(self):
        for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False, scopes="").list_tools):
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
        self.assertEqual(p["ai_cost_kind"], "API-equivalent (estimate, not billed)")
        self.assertIsNone(p["subscription_live"])          # no /api/live on the fake console

    def test_spend_vs_budget_passes_the_measurement_contract_through(self):
        """actions-usage/v2: what the minutes are, their gap to the meter, and the
        sweep's coverage reach an agent asking about spend — the series do not."""
        usage = {"ai": {"by_day": [1], "parity": {"ai_ci_cost": {"gap_pct": 0.0}}},
                 "actions": {"by_day": [1], "minutes_basis": "job-minutes",
                             "parity": {"actions_minutes": {"gap_pct": -2.4}},
                             "coverage": {"truncated": False, "sampled": True}}}
        fc = FakeConsole({"/api/state": {**STATE, "usage": usage}})
        p = payload(*call(srv.build_server(fc), "spend_vs_budget"))
        self.assertEqual(p["actions"]["minutes_basis"], "job-minutes")
        self.assertEqual(p["actions"]["parity"]["actions_minutes"]["gap_pct"], -2.4)
        self.assertTrue(p["actions"]["coverage"]["sampled"])
        self.assertEqual(p["ai"]["parity"]["ai_ci_cost"]["gap_pct"], 0.0)
        self.assertNotIn("by_day", p["actions"])

    def test_spend_vs_budget_passes_subscription_model_through(self):
        model = {"windows": {"24h": {"api_equiv_usd": 92.91, "subscription_usd": 6.45, "effective_discount_pct": 93.1}}}
        fc = FakeConsole({"/api/state": {**STATE, "subscription": {"never_summed": True}},
                          "/api/live": {"claude_live": {"subscription": model}}})
        p = payload(*call(srv.build_server(fc), "spend_vs_budget"))
        self.assertEqual(p["subscription"], {"never_summed": True})
        self.assertEqual(p["subscription_live"]["windows"]["24h"]["effective_discount_pct"], 93.1)

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


class RefineTools(unittest.TestCase):
    """The refinement read tools route to /api/refine and shape what an agent needs (ADR 0004 P2)."""

    DOC = {"schema": "refine-doc/v1", "generated_at": "t0", "config": {"k_max": 3}, "missions": {"compose": "abc"},
           "stages": ["compose"], "modes": ["parallel"], "cost_label": "API-equivalent (estimate)",
           "surface": {"ok": True, "errors": [], "warnings": [], "notes": [], "census": {"files": 9}},
           "fleet_surface": {"repos": [{"name": "SCHEMA"}], "totals": {"checked_out": 1, "clean": 1}},
           "plans": [{"loop": "repo-scout", "step": "scout", "k": 1, "mode": "parallel", "identity": {"R": 4, "P": 3},
                      "cost": {"ceiling_usd": 42.0}, "budget": {"available": False}, "steps": [1, 2, 3], "error": None}],
           "library": {"root": "_data/harness_library", "count": 2, "uncommitted": ["a"], "entries": [
               {"loop": "repo-scout", "domain": "dev-tools", "id": "e1", "cue": "c1", "confidence": "low"},
               {"loop": "repo-evolution", "domain": "docs", "id": "e2", "cue": "c2", "confidence": "high"}]},
           "evidence": [{"stamp": "s1"}], "reviews": [{"run_id": "r1", "loop": "repo-scout", "item": "bamr87/SCHEMA",
                                                      "would_file": 1, "can_apply": True, "bodies": []}]}

    def test_status_summarises_and_a_section_narrows(self):
        fc = FakeConsole({"/api/refine": self.DOC})
        res, text = call(srv.build_server(fc), "refine_status")
        self.assertFalse(res.is_error, text)
        d = payload(res, text)
        self.assertEqual(d["plans"][0]["ceiling_usd"], 42.0)
        self.assertNotIn("census", d["surface"])
        self.assertEqual(d["fleet_surface"], {"checked_out": 1, "clean": 1})
        self.assertEqual(d["reviews"], [{"run_id": "r1", "loop": "repo-scout", "item": "bamr87/SCHEMA",
                                         "would_file": 1, "can_apply": True}])
        self.assertEqual(d["evidence"], 1)
        res, text = call(srv.build_server(fc), "refine_status", {"section": "plans"})
        self.assertEqual(payload(res, text)["plans"][0]["steps"], [1, 2, 3])
        res, text = call(srv.build_server(fc), "refine_status", {"section": "nope"})
        self.assertTrue(res.is_error)
        self.assertEqual(fc.calls[-1][1], "/api/refine")

    def test_library_filters_by_loop_and_domain(self):
        fc = FakeConsole({"/api/refine": self.DOC})
        res, text = call(srv.build_server(fc), "refine_library", {"loop": "repo-evolution"})
        d = payload(res, text)
        self.assertEqual([e["id"] for e in d["items"]], ["e2"])
        self.assertEqual(d["uncommitted"], ["a"])
        res, text = call(srv.build_server(fc), "refine_library", {"domain": "dev-tools", "limit": 1})
        self.assertEqual([e["id"] for e in payload(res, text)["items"]], ["e1"])

    def test_reviews_are_the_unfiled_previews(self):
        fc = FakeConsole({"/api/refine": self.DOC})
        res, text = call(srv.build_server(fc), "refine_reviews")
        self.assertEqual(payload(res, text)["items"][0]["run_id"], "r1")

    def test_refine_tools_are_read_only_and_listed(self):
        names = tool_names(srv.build_server(FakeConsole(), allow_writes=False))
        self.assertTrue({"refine_status", "refine_library", "refine_reviews"} <= names)

    def test_job_log_cuts_the_routes_text_field(self):
        fc = FakeConsole({"/api/jobs/j1": {"job": {"id": "j1"}, "text": "x" * 50, "offset": 50, "done": True}})
        res, text = call(srv.build_server(fc), "job_log", {"job_id": "j1", "tail_chars": 10})
        d = payload(res, text)
        self.assertEqual(d["text"], "x" * 10)
        self.assertTrue(d["log_truncated"])


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
                   "fleet_workflows", "workflow_lint", "fleet_graph", "fleet_learning",
                   "console_ops", "console_jobs", "console_job_log"}

    def test_every_tool_of_the_old_server_is_served_under_its_name(self):
        """The merge dropped fleet_workflows and workflow_lint once, and nothing noticed: the old server's own
        TOOLS table is the list, so a tool added there and not here fails this."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/, for fleetcore
        from fleetcore import mcp_server as legacy
        compat = tool_names(srv.build_server(FakeConsole(), allow_writes=False, fleet_compat=True))
        self.assertEqual(set(legacy.TOOLS) - compat, set())
        self.assertEqual({n for n, t in legacy.TOOLS.items() if t["annotations"].get("readOnlyHint")}, self.LEGACY_READ)

    def test_workflow_atlas_and_lint_read_the_checkout(self):
        s = srv.build_server(FakeConsole(), allow_writes=False)
        atlas = payload(*call(s, "fleet_workflows"))
        # `workflows` present at all means the catalog fits the clip (HARNESS_MCP_MAX_CHARS); when it stops
        # fitting, this fails and the tool needs paging, as work_board did.
        self.assertEqual(atlas["summary"]["workflows"], len(atlas["workflows"]))
        self.assertIn("fleet-pulse", {w["id"] for w in atlas["workflows"]})
        one = payload(*call(s, "fleet_workflows", {"workflow": "fleet-pulse"}))
        self.assertEqual(one["item"]["switch"], "FLEET_PULSE_ENABLED")
        res, text = call(s, "fleet_workflows", {"workflow": "no-such-workflow"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("no-such-workflow", text)
        draft = "name: x\non:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
        lint = payload(*call(s, "workflow_lint", {"text": draft}))
        self.assertTrue({f["rule"] for f in lint["findings"]} >= {"permissions", "timeout", "cron-on-hour", "cron-declared"})
        self.assertEqual(lint["parsed"]["name"], "x")

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

    def test_the_graph_and_learning_tools_answer_from_the_checkout(self):
        s = srv.build_server(FakeConsole(), allow_writes=False)
        summary = payload(*call(s, "fleet_graph"))
        self.assertEqual(summary["schema"], "fleet-graph/v1")
        self.assertEqual(summary["check"]["error"], 0)
        hit = payload(*call(s, "fleet_graph", {"action": "impact", "node": "action:bamr87/bamr87:claude-cost", "depth": 1}))
        self.assertIn("workflow:bamr87/bamr87:fleet-pulse", {n["id"] for n in hit["nodes"]})
        res, text = call(s, "fleet_graph", {"action": "show", "node": "no-such-node-anywhere"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("no node matches", text)
        res, text = call(s, "fleet_graph", {"action": "explode"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        # learning answers whether or not this machine has a lake: shadow either way, never an exception
        doc = payload(*call(s, "fleet_learning", {"loop": "repo-scout"}))
        self.assertEqual((doc["schema"], doc["mode"]), ("learning/v1", "shadow"))
        self.assertIn("available", doc)
        res, text = call(s, "fleet_learning", {"loop": "no-such-loop"})
        if doc["available"]:
            self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)

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


# ----------------------------------------------------------- scoped write access
def is_err(res) -> bool:
    return res.is_error if hasattr(res, "is_error") else res.isError


# What the broad switch reaches and the jobs scope must not: secrets, keys, deploys, CI dispatch,
# destructive resets, containers, spend, GitHub filing.
SENSITIVE_OPS = ("secrets-push", "secrets-rotate", "keys-rotate", "config-sync", "ai-auth-sync", "deploy-gaps",
                 "deploy-target", "dispatch", "observe-reset", "observe-up", "observe-down", "dev-up", "dev-down",
                 "loop-run", "assist", "content-file", "keys-verify", "keys-status", "secrets-audit", "secrets-plan",
                 "workflow-new", "lake-sync", "health")
OPS = [{"id": op, "remote_write": False, "confirm": None, "unavailable": None} for op in srv.DISPATCH_OPS] + [
    {"id": op, "remote_write": True, "confirm": "write", "unavailable": None} for op in SENSITIVE_OPS]


class JobsConsole(FakeConsole):
    """A console whose job API keeps state: submitted jobs, their logs, cancel."""

    def __init__(self, ops=None, finish=True):
        super().__init__({"/api/ops": ops or OPS})
        self.jobs: dict[str, dict] = {}
        self.finish, self.n = finish, 0
        self.routes[("POST", "/api/jobs")] = self._submit
        self.routes[("GET", "/api/jobs")] = lambda body: [dict(j) for j in self.jobs.values()]

    def add(self, op, status="running"):
        self.n += 1
        jid = f"{self.n:012x}"
        job = self.jobs[jid] = {"id": jid, "op": op, "status": status}
        self.routes[("GET", f"/api/jobs/{jid}")] = lambda b, j=job: {
            "job": dict(j), "text": "$ tools/dash config show\nbudget: ok\n", "done": j["status"] != "running"}

        def cancel(b, j=job):
            j["status"] = "cancelled"
            return dict(j)
        self.routes[("POST", f"/api/jobs/{jid}/cancel")] = cancel
        return job

    def _submit(self, body):
        return dict(self.add(body["op"], "succeeded" if self.finish else "running"))


class ScopedCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.audit_path = Path(tmp.name) / "audit.jsonl"
        self.stream = io.StringIO()
        self.audit = srv.Audit(self.audit_path, stream=self.stream)

    def server(self, fc, scopes, dispatcher=None, **kw):
        disp = dispatcher or srv.Dispatcher(fc, self.audit, watch=False)
        return srv.build_server(fc, allow_writes=False, scopes=scopes, audit=self.audit, dispatcher=disp, **kw)

    def audit_lines(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text().splitlines()]


class Scopes(ScopedCase):
    def test_parsing_grants_known_names_only(self):
        self.assertEqual(srv.granted_scopes(" Jobs , work "), (frozenset({"jobs", "work"}), []))
        self.assertEqual(srv.granted_scopes("admin,secrets,jobs"), (frozenset({"jobs"}), ["admin", "secrets"]))
        self.assertEqual(srv.granted_scopes(""), (frozenset(), []))
        self.assertEqual(srv.granted_scopes("", writes=True)[0], frozenset(srv.SCOPES))

    def test_each_scope_registers_only_its_tools(self):
        broad = {"run_op", "cancel_job", "workflow_kill_switch", "console_run", "console_cancel"}
        for scopes, want in (("", set()), ("jobs", {"job_dispatch", "job_cancel"}), ("work", {"work_apply"}),
                             ("jobs,work", {"job_dispatch", "job_cancel", "work_apply"})):
            names = tool_names(self.server(FakeConsole(), scopes))
            self.assertEqual(names & {"job_dispatch", "job_cancel", "work_apply"}, want, scopes)
            self.assertFalse(names & broad, f"{scopes}: a scope never exposes the broad write tools")
            self.assertTrue({"work_item", "work_preview"} <= names)

    def test_annotations_and_no_context_in_schemas(self):
        tools = {t.name: t for t in anyio.run(self.server(FakeConsole(), "jobs,work").list_tools)}
        for name in ("work_item", "work_preview"):
            self.assertTrue(tools[name].annotations.read_only_hint, name)
        for name in ("job_dispatch", "job_cancel", "work_apply"):
            a = tools[name].annotations
            self.assertFalse(a.read_only_hint, name)
            self.assertTrue(a.destructive_hint, f"{name}: every write tool is marked destructive (NFR9)")
            self.assertFalse(a.open_world_hint, name)
            props = getattr(tools[name], "input_schema", None) or tools[name].inputSchema
            self.assertNotIn("ctx", props.get("properties", {}), name)
            self.assertIn("confirm", props.get("properties", {}), name)

    def test_overview_reports_scopes(self):
        res, text = call(self.server(FakeConsole(), "work"), "console_overview")
        doc = payload(res, text)
        self.assertEqual((doc["mcp_writes_enabled"], doc["mcp_scopes"]), (False, ["work"]))


class ScopedJobs(ScopedCase):
    def test_refused_without_confirm_audited_and_nothing_posted(self):
        fc = JobsConsole()
        res, text = call(self.server(fc, "jobs"), "job_dispatch", {"op": "config-show"})
        self.assertTrue(is_err(res))
        self.assertIn("confirm=true", text)
        self.assertFalse([c for c in fc.calls if c[0] == "POST"])
        self.assertEqual([r["outcome"] for r in self.audit_lines()], ["refused"])

    def test_sensitive_ops_are_off_the_allowlist_even_confirmed(self):
        self.assertFalse(set(SENSITIVE_OPS) & set(srv.DISPATCH_OPS))
        fc = JobsConsole()
        s = self.server(fc, "jobs")
        for op in SENSITIVE_OPS:
            res, text = call(s, "job_dispatch", {"op": op, "params": {"apply": True}, "confirm": True})
            self.assertTrue(is_err(res), op)
            self.assertIn("not on the job_dispatch allowlist", text)
        self.assertFalse([c for c in fc.calls if c[:2] == ("POST", "/api/jobs")])
        self.assertEqual(len(self.audit_lines()), len(SENSITIVE_OPS))

    def test_params_are_declared_and_plain(self):
        fc = JobsConsole()
        s = self.server(fc, "jobs")
        for params in ({"apply": True}, {"key": "a b;rm"}, {"key": True}, {"key": "x" * 65}, {"target": "x"}):
            res, _ = call(s, "job_dispatch", {"op": "config-show", "params": params, "confirm": True})
            self.assertTrue(is_err(res), params)
        self.assertFalse([c for c in fc.calls if c[:2] == ("POST", "/api/jobs")])

    def test_dispatch_never_passes_the_consoles_confirm(self):
        fc = JobsConsole()
        res, text = call(self.server(fc, "jobs"), "job_dispatch",
                         {"op": "config-show", "params": {"key": "budget"}, "confirm": True})
        self.assertFalse(is_err(res), text)
        post = [c for c in fc.calls if c[:2] == ("POST", "/api/jobs")]
        self.assertEqual(post[-1][3], {"op": "config-show", "params": {"key": "budget"}, "confirm": False})
        doc = payload(res, text)
        self.assertEqual((doc["limit_s"], doc["audit"]), (120, str(self.audit_path)))
        rec = self.audit_lines()[-1]
        self.assertEqual((rec["tool"], rec["outcome"], rec["op"], rec["job_id"]),
                         ("job_dispatch", "started", "config-show", doc["job"]["id"]))
        self.assertEqual(rec["transport"], "stdio")

    def test_an_op_the_console_marks_as_writing_is_refused(self):
        ops = [dict(o, remote_write=True, confirm="write") if o["id"] == "status" else o for o in OPS]
        fc = JobsConsole(ops=ops)
        res, text = call(self.server(fc, "jobs"), "job_dispatch", {"op": "status", "confirm": True})
        self.assertTrue(is_err(res))
        self.assertIn("writing remotely", text)
        self.assertFalse([c for c in fc.calls if c[:2] == ("POST", "/api/jobs")])

    def test_wait_returns_the_result(self):
        fc = JobsConsole(finish=True)
        res, text = call(self.server(fc, "jobs"), "job_dispatch", {"op": "config-show", "confirm": True, "wait_s": 5})
        doc = payload(res, text)
        self.assertTrue(doc["done"])
        self.assertEqual(doc["job"]["status"], "succeeded")
        self.assertIn("budget: ok", doc["log_tail"])

    def test_running_cap(self):
        fc = JobsConsole(finish=False)
        s = self.server(fc, "jobs")
        for _ in range(srv.DISPATCH_RUNNING_MAX):
            res, text = call(s, "job_dispatch", {"op": "status", "confirm": True})
            self.assertFalse(is_err(res), text)
        res, text = call(s, "job_dispatch", {"op": "status", "confirm": True})
        self.assertTrue(is_err(res))
        self.assertIn("still running", text)
        self.assertEqual(len([c for c in fc.calls if c[:2] == ("POST", "/api/jobs")]), srv.DISPATCH_RUNNING_MAX)

    def test_watchdog_cancels_a_job_past_its_limit_and_forgets_finished_ones(self):
        now = [1000.0]
        fc = JobsConsole(finish=False)
        disp = srv.Dispatcher(fc, self.audit, clock=lambda: now[0], watch=False)
        s = self.server(fc, "jobs", dispatcher=disp)
        late = payload(*call(s, "job_dispatch", {"op": "status", "confirm": True}))["job"]["id"]
        done = payload(*call(s, "job_dispatch", {"op": "lake-status", "confirm": True}))["job"]["id"]
        fc.jobs[done]["status"] = "succeeded"
        now[0] += srv.DISPATCH_OPS["status"]["limit_s"] - 1
        self.assertEqual(disp.sweep(), [])
        self.assertEqual(set(disp.live), {late})
        now[0] += 2
        self.assertEqual(disp.sweep(), [late])
        self.assertEqual(fc.jobs[late]["status"], "cancelled")
        self.assertEqual(disp.live, {})
        self.assertEqual(self.audit_lines()[-1]["outcome"], "cancelled: past its limit")

    def test_job_cancel_only_reaches_allowlisted_jobs(self):
        fc = JobsConsole(finish=False)
        s = self.server(fc, "jobs")
        deploy = fc.add("deploy-gaps")["id"]
        mine = fc.add("drift")["id"]
        for args, why in (({"job_id": deploy, "confirm": True}, "stop it from the console"),
                          ({"job_id": mine}, "confirm=true"), ({"job_id": "../x", "confirm": True}, "12-hex")):
            res, text = call(s, "job_cancel", args)
            self.assertTrue(is_err(res), args)
            self.assertIn(why, text)
        self.assertEqual(fc.jobs[deploy]["status"], "running")
        res, text = call(s, "job_cancel", {"job_id": mine, "confirm": True})
        self.assertFalse(is_err(res), text)
        self.assertEqual(fc.jobs[mine]["status"], "cancelled")
        self.assertEqual([r["outcome"] for r in self.audit_lines()], ["refused", "refused", "refused", "cancelled"])

    def test_hourly_cap_rolls(self):
        now = [0.0]
        cap = srv.RateCap(2, clock=lambda: now[0])
        cap.take("x")
        cap.take("x")
        with self.assertRaises(srv.ToolError):
            cap.take("x")
        now[0] += 3601
        cap.take("x")


def work_board_fixture() -> dict:
    """BOARD(12) with the fields a plan changes: item 1 pinned first in `ready`, item 3's priority an override,
    and one roadmap entry."""
    board = BOARD(12)
    for it in board["items"]:
        it.update(rank=None, priority_source="computed", priority_auto=it["priority"], note=None)
    board["items"][1]["rank"] = 0
    board["items"][3].update(priority="P0", priority_source="override")
    board["items"].append({"key": "roadmap:FF-0042", "kind": "roadmap", "ref": "FF-0042", "title": "Roadmap entry",
                           "repo": "bamr87", "lane": "ready", "stage": "approved", "priority": "P2",
                           "priority_source": "roadmap", "rank": None, "note": None})
    return board


def fake_board_after(board: dict, plan: dict) -> dict:
    """What dash-gen work_board.build(inputs, plan) does to the fields the tools read."""
    b = json.loads(json.dumps(board))
    by = {it["key"]: it for it in b["items"]}
    for k, v in (plan.get("priority") or {}).items():
        if k.startswith("roadmap:"):
            by[k]["priority"] = v
        elif v:
            by[k].update(priority=v, priority_source="override")
        else:
            by[k].update(priority=by[k]["priority_auto"], priority_source="computed")
    for k, v in (plan.get("notes") or {}).items():
        by[k]["note"] = v or None
    for lane, keys in (plan.get("pins") or {}).items():
        for it in b["items"]:
            if it["lane"] == lane:
                it["rank"] = None
        for r, k in enumerate(keys):
            by[k]["rank"] = r
    for k in plan.get("unpin") or []:
        by[k]["rank"] = None
    b["preview"] = True
    b["changes"] = [{"key": k, "target": "work_queue", "what": f"{k} changed"} for k in sorted(srv.plan_keys(plan))]
    return b


class WorkConsole(FakeConsole):
    def __init__(self):
        super().__init__()
        self.board = work_board_fixture()
        self.routes[("GET", "/api/work")] = lambda body: self.board
        self.routes[("POST", "/api/work/preview")] = lambda body: fake_board_after(self.board, body["plan"])
        self.routes[("POST", "/api/work/apply")] = self._apply

    def _apply(self, body):
        self.board = fake_board_after(self.board, body["plan"])
        self.board.pop("changes")
        results = [{"key": k, "target": "work_queue", "ok": True, "error": None} for k in srv.plan_keys(body["plan"])]
        return {"results": results, "pruned": [], "diff": "+priority:\n+  k: P0\n", "board": self.board}


K1, K3, K7 = "issue:bamr87/r1#1", "issue:bamr87/r3#3", "issue:bamr87/r7#7"   # lanes ready, review, ready


class ScopedWork(ScopedCase):
    def test_plan_validation(self):
        many = {"priority": {f"issue:bamr87/x#{i}": "P1" for i in range(srv.WORK_PLAN_MAX_KEYS + 1)}}
        for plan in ({}, {"priority": {}}, {"priority": {K7: "P9"}}, {"priority": {"not a key": "P1"}},
                     {"notes": {K7: "x" * (srv.WORK_NOTE_CHARS + 1)}}, {"pins": {"Ready!": [K7]}},
                     {"pins": {"ready": K7}}, {"bogus": 1}, many, [K7]):
            with self.assertRaises(srv.ToolError, msg=str(plan)[:80]):
                srv.check_plan(plan)
        a = srv.check_plan({"notes": {K7: " why "}, "priority": {K7: "P1", K1: ""}})
        b = srv.check_plan({"priority": {K1: "", K7: "P1"}, "notes": {K7: "why"}})
        self.assertEqual(a, b)
        board = work_board_fixture()
        self.assertEqual(srv.plan_id_for(a, board), srv.plan_id_for(b, board))
        self.assertRegex(srv.plan_id_for(a, board), r"^[0-9a-f]{16}$")

    def test_stage_and_roadmap_status_stay_on_the_console(self):
        fc = WorkConsole()
        s = self.server(fc, "work")
        for plan in ({"stage": {K7: "ready"}}, {"roadmap_status": {"FF-0042": "declined"}},
                     {"roadmap_reason": {"FF-0042": "x"}}, {"priority": {K7: "P1"}, "stage": {K7: "hold"}}):
            res, text = call(s, "work_preview", {"plan": plan})
            self.assertTrue(is_err(res), plan)
            self.assertIn("Work board", text)
        self.assertEqual(fc.calls, [])

    def test_preview_writes_nothing_and_says_how_to_undo(self):
        fc = WorkConsole()
        res, text = call(self.server(fc, ""), "work_preview", {"plan": {"priority": {K7: "P0"}, "notes": {K7: "now"}}})
        self.assertFalse(is_err(res), text)
        doc = payload(res, text)
        self.assertEqual([c[:2] for c in fc.calls], [("GET", "/api/work"), ("POST", "/api/work/preview")])
        self.assertTrue(doc["writes_nothing"])
        self.assertFalse(doc["apply_enabled"])
        self.assertEqual(doc["files"], ["_data/work_queue.yml"])
        self.assertEqual(doc["undo_plan"], {"priority": {K7: ""}, "notes": {K7: ""}})
        (row,) = doc["items"]
        self.assertEqual((row["key"], row["before"]["priority_source"], row["after"]["priority"], row["after"]["note"]),
                         (K7, "computed", "P0", "now"))
        self.assertRegex(doc["plan_id"], r"^[0-9a-f]{16}$")

    def test_undo_plans(self):
        board = work_board_fixture()
        self.assertEqual(srv.undo_plan({"pins": {"ready": [K7, K1]}}, board), {"pins": {"ready": [K1]}})
        self.assertEqual(srv.undo_plan({"unpin": [K1]}, board), {"pins": {"ready": [K1]}})
        self.assertEqual(srv.undo_plan({"priority": {K3: "", K7: "P1"}}, board), {"priority": {K3: "P0", K7: ""}})
        self.assertEqual(srv.undo_plan({"priority": {"roadmap:FF-0042": "P0"}}, board),
                         {"priority": {"roadmap:FF-0042": "P2"}})
        self.assertEqual(srv.plan_files({"priority": {"roadmap:FF-0042": "P0"}}), ["_data/roadmap.yml"])

    def test_apply_needs_the_scope_confirm_and_the_previewed_plan_id(self):
        self.assertNotIn("work_apply", tool_names(self.server(WorkConsole(), "jobs")))
        fc = WorkConsole()
        s = self.server(fc, "work")
        plan = {"priority": {K7: "P0"}}
        pid = payload(*call(s, "work_preview", {"plan": plan}))["plan_id"]
        for args, why in (({"plan": plan, "plan_id": pid}, "confirm=true"),
                          ({"plan": plan, "plan_id": "0" * 16, "confirm": True}, "does not match"),
                          ({"plan": {"priority": {K7: "P1"}}, "plan_id": pid, "confirm": True}, "does not match"),
                          ({"plan": {"stage": {K7: "hold"}}, "plan_id": pid, "confirm": True}, "Work board")):
            res, text = call(s, "work_apply", args)
            self.assertTrue(is_err(res), args)
            self.assertIn(why, text)
        fc.board["items"][7]["priority_source"] = "override"          # the item moved after the preview
        res, text = call(s, "work_apply", {"plan": plan, "plan_id": pid, "confirm": True})
        self.assertTrue(is_err(res))
        self.assertIn("does not match", text)
        self.assertFalse([c for c in fc.calls if c[:2] == ("POST", "/api/work/apply")])
        self.assertEqual([r["outcome"] for r in self.audit_lines()], ["refused"] * 5)

    def test_apply_then_undo_round_trips_and_is_audited(self):
        fc = WorkConsole()
        s = self.server(fc, "work")
        original = json.loads(json.dumps(fc.board))
        plan = {"priority": {K7: "P0"}, "notes": {K7: "ship first"}, "pins": {"ready": [K7, K1]}}
        pid = payload(*call(s, "work_preview", {"plan": plan}))["plan_id"]
        res, text = call(s, "work_apply", {"plan": plan, "plan_id": pid, "confirm": True})
        self.assertFalse(is_err(res), text)
        doc = payload(res, text)
        post = [c for c in fc.calls if c[:2] == ("POST", "/api/work/apply")][-1]
        self.assertEqual(post[3], {"plan": srv.check_plan(plan), "confirm": False})
        self.assertFalse(doc["committed"])
        self.assertIn("+priority", doc["diff"])
        self.assertEqual({r["key"] for r in doc["items"]}, {K1, K7})
        undo = doc["undo_plan"]
        upid = payload(*call(s, "work_preview", {"plan": undo}))["plan_id"]
        res, text = call(s, "work_apply", {"plan": undo, "plan_id": upid, "confirm": True})
        self.assertFalse(is_err(res), text)
        snap = lambda b: {it["key"]: {f: it.get(f) for f in srv.WORK_SNAPSHOT} for it in b["items"]}  # noqa: E731
        self.assertEqual(snap(fc.board), snap(original))
        recs = self.audit_lines()
        self.assertEqual([(r["tool"], r["outcome"]) for r in recs], [("work_apply", "applied")] * 2)
        self.assertEqual(recs[0]["plan_id"], pid)
        self.assertNotIn("s3cret-token", self.audit_path.read_text() + self.stream.getvalue())


class AuditLog(unittest.TestCase):
    def test_scrubs_and_appends_one_line_per_record(self):
        with tempfile.TemporaryDirectory() as d:
            path, out = Path(d) / "a" / "audit.jsonl", io.StringIO()
            log = srv.Audit(path, stream=out)
            tok = "ghp_" + "A" * 36
            self.assertEqual(log.record(tool="t", params={"x": tok, "y": "Bearer abc.def"}), str(path))
            log.record(tool="t", outcome="refused")
            text = path.read_text()
            self.assertEqual(len(text.splitlines()), 2)
            self.assertNotIn(tok, text + out.getvalue())
            self.assertNotIn("abc.def", text)
            self.assertIn("harness-mcp audit ", out.getvalue())

    def test_a_read_only_mount_falls_back_to_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / "file"
            blocker.write_text("")
            log = srv.Audit(blocker / "audit.jsonl", stream=io.StringIO())   # parent is a file: cannot mkdir
            self.assertEqual(log.record(tool="t"), "stderr")

    def test_default_path_is_gitignored_fleet_mcp(self):
        with mock.patch.dict(os.environ, {"HARNESS_MCP_AUDIT": ""}):
            self.assertEqual(srv.audit_file().relative_to(srv.ROOT).as_posix(), ".fleet/mcp/audit.jsonl")


if __name__ == "__main__":
    unittest.main(verbosity=1)

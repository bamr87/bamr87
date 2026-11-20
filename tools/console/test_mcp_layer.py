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
        self.timeouts: list[float | None] = []

    def request(self, method, path, query=None, body=None, timeout=None):
        self.timeouts.append(timeout)
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

    # HUB-064 (FR60, #556): an agent holding a job's receipt reads its state, ages and diagnostics.
    STATUS = {"id": "j1", "op": "health", "status": "running", "state": "stalled", "age_s": 700.0,
              "idle_s": 400.0, "stall_s": 120,
              "diagnostics": [{"code": "no_heartbeat", "detail": "no log output for 400 s (stalled past 120 s)"}]}

    def test_job_status_reads_the_status_route(self):
        fc = FakeConsole({"/api/jobs/j1/status": self.STATUS})
        res, text = call(srv.build_server(fc), "job_status", {"job_id": "j1"})
        self.assertFalse(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertEqual(payload(res, text), self.STATUS)
        self.assertEqual(fc.calls[-1][:2], ("GET", "/api/jobs/j1/status"))

    def test_job_status_unknown_job_and_an_older_console_are_tool_errors(self):
        gone = ConsoleError("console GET /api/jobs/zz/status -> 404: no such job", 404)
        res, text = call(srv.build_server(FakeConsole({"/api/jobs/zz/status": gone})), "job_status", {"job_id": "zz"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("no such job", text)
        res, text = call(srv.build_server(FakeConsole()), "job_status", {"job_id": "j1"})   # route absent
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("#556", text)
        self.assertIn("job_log", text)

    def test_jobs_list_filters_by_derived_state_beside_raw_status(self):
        rows = [{"id": "a", "status": "running", "state": "stalled"},
                {"id": "b", "status": "running", "state": "running"},
                {"id": "c", "status": "cancelled", "state": "failed"},
                {"id": "d", "status": "succeeded", "state": "done"}]
        fc = FakeConsole({"/api/jobs": rows})
        s = srv.build_server(fc)
        self.assertEqual([j["id"] for j in payload(*call(s, "jobs_list", {"state": "stalled"}))["items"]], ["a"])
        self.assertEqual([j["id"] for j in payload(*call(s, "jobs_list", {"state": "failed"}))["items"]], ["c"])
        self.assertEqual([j["id"] for j in payload(*call(s, "jobs_list", {"status": "running"}))["items"]], ["a", "b"])
        both = payload(*call(s, "jobs_list", {"status": "running", "state": "running"}))
        self.assertEqual([j["id"] for j in both["items"]], ["b"])
        self.assertEqual(payload(*call(s, "jobs_list"))["count"], 4)
        res, _ = call(s, "jobs_list", {"state": "sleeping"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)

    def test_job_status_is_a_read_tool(self):
        tools = {t.name: t for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False, scopes="").list_tools)}
        self.assertIn("job_status", tools)
        self.assertTrue(tools["job_status"].annotations.read_only_hint)
        self.assertIn("job_status", srv.INSTRUCTIONS)

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

    def test_lake_recall_is_read_only_and_bounds_what_it_asks_for(self):
        """bamr87/bamr87#546: recall over the lake's sessions, next to agent_activity — a read tool whose
        query, window and limit are clamped to what the console route accepts (a longer query was a 422), so an
        agent cannot ask for more."""
        doc = {"schema": "lake-recall/v1", "present": True, "terms": ["fts5", "index"],
               "results": [{"key": "session:s1", "session_id": "s1", "repo": "bamr87", "match": "turn",
                            "turn": 3, "excerpt": "…the fts5 index is built in memory…"}]}
        fc = FakeConsole({"/api/lake/recall": doc})
        server = srv.build_server(fc, allow_writes=False, scopes="")
        tools = {t.name: t for t in anyio.run(server.list_tools)}
        self.assertTrue(tools["lake_recall"].annotations.read_only_hint)
        self.assertFalse(tools["lake_recall"].annotations.destructive_hint)
        self.assertIn("lake_recall", srv.INSTRUCTIONS)
        p = payload(*call(server, "lake_recall", {"query": "fts5 index"}))
        self.assertEqual(p["results"][0]["key"], "session:s1")
        self.assertEqual(fc.calls[-1][1:3], ("/api/lake/recall", {"q": "fts5 index", "days": 30, "limit": 10}))
        call(server, "lake_recall", {"query": "x", "days": 99999, "repo": "bamr87", "limit": 500})
        self.assertEqual(fc.calls[-1][2], {"q": "x", "days": 3650, "repo": "bamr87", "limit": 50})
        call(server, "lake_recall", {"query": "word " * 100})
        self.assertEqual(fc.calls[-1][2]["q"], ("word " * 100)[:300])

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

    # ---------------------------------------------------------------- nodes
    def test_fleet_nodes_is_the_consoles_document_unchanged(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/, for fleetcore
        from fleetcore import nodes
        doc = nodes.status_doc(probe=False)
        fc = FakeConsole({"/api/nodes": doc})
        p = payload(*call(srv.build_server(fc), "fleet_nodes"))
        self.assertEqual(p, json.loads(json.dumps(doc)))
        self.assertEqual(fc.calls, [("GET", "/api/nodes", {}, None)])

    def test_fleet_nodes_without_a_console_is_the_same_function_in_process(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from fleetcore import mcp_server as legacy
        from fleetcore import nodes
        want = nodes.status_doc(probe=False)
        for err in (ConsoleError("console unreachable at http://fake: refused"),
                    ConsoleError("console GET /api/nodes -> 404: Not Found", 404)):
            with mock.patch.object(legacy, "t_nodes", lambda _a: nodes.status_doc(probe=False)):  # no probe here
                res, text = call(srv.build_server(FakeConsole({"/api/nodes": err})), "fleet_nodes")
            self.assertFalse(res.is_error, text)
            got = payload(res, text)
            self.assertEqual(set(got), set(want))
            self.assertEqual([n["name"] for n in got["nodes"]], [n["name"] for n in want["nodes"]])

    def test_fleet_nodes_refusal_is_a_tool_error_not_a_fallback(self):
        fc = FakeConsole({"/api/nodes": ConsoleError("console GET /api/nodes -> 401: bad token", 401)})
        res, text = call(srv.build_server(fc), "fleet_nodes")
        self.assertTrue(res.is_error)
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


class DecisionQueueTool(unittest.TestCase):
    """decision_queue is ONE call to /api/decisions; with no console it reads the same index in this process."""

    DOC = {"schema": "decision-queue/v1", "status": "fresh", "complete": True, "source": "cache", "total": 1,
           "counts": {"needs_amr": 1, "ratification": 0, "dependabot": 0, "ready_to_merge": 0},
           "items": [{"key": "pr:bamr87/bamr87#1", "kind": "needs_amr", "why": ["labelled needs-amr"]}],
           "warnings": [], "errors": []}

    def test_one_get_with_the_filters_and_a_capped_budget(self):
        fc = FakeConsole({"/api/decisions": self.DOC})
        res, text = call(srv.build_server(fc), "decision_queue", {"kind": "needs_amr", "repo": "bamr87/bamr87",
                                                                  "limit": 999, "refresh": "never", "budget_s": 600})
        self.assertFalse(res.is_error, text)
        self.assertEqual(payload(res, text)["items"][0]["key"], "pr:bamr87/bamr87#1")
        self.assertEqual(fc.calls, [("GET", "/api/decisions", {"kind": "needs_amr", "repo": "bamr87/bamr87", "limit": 200,
                                                               "refresh": "never", "budget": 15.0}, None)])
        self.assertLess(srv.DECISION_BUDGET_MAX_S, fc.timeout, "the console's partial answer arrives before the client gives up")

    def test_defaults_leave_the_budget_to_the_console(self):
        fc = FakeConsole({"/api/decisions": self.DOC})
        call(srv.build_server(fc), "decision_queue")
        self.assertEqual(fc.calls, [("GET", "/api/decisions", {"limit": 30, "refresh": "auto"}, None)])

    def test_a_bad_kind_never_reaches_the_console(self):
        fc = FakeConsole({"/api/decisions": self.DOC})
        res, _ = call(srv.build_server(fc), "decision_queue", {"kind": "everything"})
        self.assertTrue(res.is_error)
        self.assertEqual(fc.calls, [])

    def test_a_console_refusal_is_a_tool_error_not_a_fallback(self):
        fc = FakeConsole({"/api/decisions": ConsoleError("console GET /api/decisions -> 401: bad token", 401)})
        with mock.patch.object(srv, "decision_local", side_effect=AssertionError("must not fall back")):
            res, text = call(srv.build_server(fc), "decision_queue")
        self.assertTrue(res.is_error)
        self.assertIn("401", text)
        self.assertNotIn("s3cret-token", text)

    def test_with_no_console_the_same_module_answers_in_process(self):
        seen = []
        for err, why in ((ConsoleError("console unreachable at http://fake: refused"), "no console answered"),
                         (ConsoleError("console GET /api/decisions -> 404: Not Found", 404), "no /api/decisions yet")):
            fc = FakeConsole({"/api/decisions": err})
            with mock.patch.object(srv, "decision_local", side_effect=lambda **kw: seen.append(kw) or dict(self.DOC)):
                res, text = call(srv.build_server(fc), "decision_queue", {"kind": "dependabot", "budget_s": 4})
            self.assertFalse(res.is_error, text)
            d = payload(res, text)
            self.assertEqual(d["status"], "fresh")
            self.assertIn(why, d["via"])
        self.assertEqual(seen, [{"kind": "dependabot", "repo": "", "limit": 30, "refresh": "auto", "budget_s": 4.0}] * 2)

    def test_the_in_process_read_is_the_real_module_over_the_index_file(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"DASH_DECISIONS_INDEX": str(Path(tmp) / "index.json")}):
            d = srv.decision_local(refresh="never", limit=5)        # no index, and `never` makes no GitHub call
            self.assertEqual((d["schema"], d["status"], d["items"]), ("decision-queue/v1", "unavailable", []))
            with self.assertRaises(ConsoleError):
                srv.decision_local(kind="everything", refresh="never")

    def test_it_is_listed_and_read_only(self):
        tools = {t.name: t for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False, scopes="").list_tools)}
        self.assertTrue(tools["decision_queue"].annotations.read_only_hint)
        self.assertFalse(tools["decision_queue"].annotations.destructive_hint)
        self.assertIn("decision_queue", srv.INSTRUCTIONS)


def gh_item(i: int) -> dict:
    return {"item_id": f"PVTI_{i}", "archived": False, "kind": "pr", "content_id": f"PR_{i}", "repo": "bamr87/bamr87",
            "number": i, "title": f"item {i} " + "a long title " * 20, "state": "OPEN",
            "url": f"https://github.com/bamr87/bamr87/pull/{i}", "fields": {"Status": "Todo", "Priority": "P2"},
            "refs": ["FR12"], "closes": [f"bamr87/bamr87#{i + 1}"],
            "commits": [{"sha": "a" * 40, "headline": "fix: something " * 4, "refs": []} for _ in range(20)]}


class GhProjectsTools(unittest.TestCase):
    """gh_projects / gh_project_items: one GET each, summarised and bounded, read-only, the project id checked
    before it reaches a URL; with no console the same module answers in this process."""

    PROJECTS = {"schema": "gh-projects/v1", "status": "partial", "scope_missing": True, "hint": "needs read:project",
                "owners": [{"login": "bamr87", "kind": "user", "status": "ok", "projects": 1},
                           {"login": "year-of-ai", "kind": "organization", "status": "scope_missing",
                            "error": "scope missing: read:project"}],
                "projects": [{"owner": "bamr87", "id": "PVT_fleet", "number": 14, "title": "Fleet", "url": "u",
                              "closed": False, "fields": [
                                  {"id": "F_s", "name": "Status", "type": "SINGLE_SELECT", "options": ["Todo", "Done"]},
                                  {"id": "F_t", "name": "Title", "type": "TITLE", "options": []}]}]}

    def items(self, n: int = 500) -> dict:
        return {"schema": "gh-project-items/v1", "status": "fresh", "project_id": "PVT_fleet", "total": n,
                "matched": n, "next_offset": None, "counts": {"by_status": {"Todo": n}, "by_kind": {"pr": n}},
                "items": [gh_item(i) for i in range(n)]}

    def test_projects_is_one_get_summarised_with_the_scope_said(self):
        fc = FakeConsole({"/api/gh-projects": self.PROJECTS})
        res, text = call(srv.build_server(fc), "gh_projects")
        self.assertFalse(res.is_error, text)
        d = payload(res, text)
        self.assertEqual(fc.calls, [("GET", "/api/gh-projects", {"closed": "false"}, None)])
        self.assertEqual((d["status"], d["scope_missing"], d["summary"]), ("partial", True, True))
        self.assertEqual(d["owners"][1]["status"], "scope_missing")
        self.assertEqual(d["projects"][0], {"owner": "bamr87", "number": 14, "title": "Fleet", "url": "u", "closed": False,
                                            "id": "PVT_fleet", "fields": ["Status", "Title"], "status_options": ["Todo", "Done"]})
        fc.calls.clear()
        res, text = call(srv.build_server(fc), "gh_projects", {"owner": "bamr87", "include_closed": True,
                                                               "summary": False, "refresh": True})
        self.assertEqual(fc.calls, [("GET", "/api/gh-projects", {"owner": "bamr87", "closed": "true", "refresh": "true"}, None)])
        self.assertEqual(payload(res, text)["projects"][0]["fields"][0]["id"], "F_s")

    def test_items_are_paged_summarised_and_bounded(self):
        fc = FakeConsole({"/api/gh-projects/PVT_fleet/items": lambda _b: dict(self.items(30))})
        res, text = call(srv.build_server(fc), "gh_project_items", {"project_id": "PVT_fleet"})
        self.assertFalse(res.is_error, text)
        self.assertEqual(fc.calls, [("GET", "/api/gh-projects/PVT_fleet/items", {"limit": 30, "offset": 0}, None)])
        d = payload(res, text)
        row = d["items"][0]
        self.assertEqual(row["commits"], 20, "a PR's commits become a count")
        self.assertNotIn("content_id", row)
        self.assertLessEqual(len(row["title"]), srv.BOARD_TITLE_CHARS)
        self.assertLess(len(text), srv.max_chars(), "the default page fits the client's context whole")
        self.assertNotIn("truncated", d)
        fc.calls.clear()
        call(srv.build_server(fc), "gh_project_items", {"project_id": "PVT_fleet", "limit": 9999, "offset": 9999,
                                                         "status": "Todo", "kind": "pr", "q": "x"})
        call(srv.build_server(fc), "gh_project_items", {"project_id": "PVT_fleet", "limit": 9999, "summary": False})
        self.assertEqual([c[2] for c in fc.calls], [
            {"limit": srv.GH_ITEMS_LIMIT_MAX, "offset": srv.GH_ITEMS_OFFSET_MAX, "status": "Todo", "kind": "pr", "q": "x"},
            {"limit": srv.GH_ITEMS_FULL_MAX, "offset": 0}])

    def test_an_oversized_answer_is_clipped_not_dropped(self):
        fc = FakeConsole({"/api/gh-projects/PVT_fleet/items": lambda _b: self.items(500)})
        with mock.patch.dict(os.environ, {"HARNESS_MCP_MAX_CHARS": "20000"}):
            res, text = call(srv.build_server(fc), "gh_project_items", {"project_id": "PVT_fleet", "summary": False})
        d = payload(res, text)
        self.assertTrue(d["truncated"])
        self.assertLessEqual(len(d["json_prefix"]), 20000)

    def test_a_bad_project_id_never_reaches_a_url(self):
        fc = FakeConsole({})
        for bad in ("../../api/jobs", "PVT_x/../../jobs", "I_kwDOabc", ""):
            res, text = call(srv.build_server(fc), "gh_project_items", {"project_id": bad})
            self.assertTrue(res.is_error, bad)
        self.assertEqual(fc.calls, [])

    def test_a_route_404_is_the_answer_and_no_console_falls_back(self):
        fc = FakeConsole({"/api/gh-projects/PVT_gone/items":
                          ConsoleError("console GET /api/gh-projects/PVT_gone/items -> 404: no project PVT_gone is readable", 404)})
        with mock.patch.object(srv, "gh_items_local", side_effect=AssertionError("must not fall back")):
            res, text = call(srv.build_server(fc), "gh_project_items", {"project_id": "PVT_gone"})
        self.assertTrue(res.is_error)
        self.assertIn("no project PVT_gone", text)
        seen = []
        for err, why in ((ConsoleError("console unreachable at http://fake: refused"), "no console answered"),
                         (ConsoleError("console GET /api/gh-projects -> 404: no such API route", 404), "no /api/gh-projects yet")):
            fc = FakeConsole({"/api/gh-projects": err, "/api/gh-projects/PVT_fleet/items": err})
            with mock.patch.object(srv, "gh_projects_local", side_effect=lambda **kw: seen.append(kw) or dict(self.PROJECTS)), \
                    mock.patch.object(srv, "gh_items_local", side_effect=lambda pid, **kw: seen.append((pid, kw)) or self.items(3)):
                res, text = call(srv.build_server(fc), "gh_projects")
                self.assertIn(why, payload(res, text)["via"])
                res, text = call(srv.build_server(fc), "gh_project_items", {"project_id": "PVT_fleet", "kind": "pr"})
                self.assertIn(why, payload(res, text)["via"])
                self.assertEqual(payload(res, text)["items"][0]["commits"], 20)
        self.assertEqual(seen[0], {"owner": "", "include_closed": False, "refresh": False})
        self.assertEqual(seen[1], ("PVT_fleet", {"limit": 30, "offset": 0, "status": "", "kind": "pr", "q": "", "refresh": False}))

    def test_the_in_process_read_is_the_real_module(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PROJECTS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")}
        with mock.patch.dict(os.environ, env, clear=True):
            d = srv.gh_projects_local(token=(None, None))         # no token: nothing is sent
            self.assertEqual((d["schema"], d["status"], d["projects"]), ("gh-projects/v1", "scope_missing", []))
            with self.assertRaises(ConsoleError):
                srv.gh_projects_local(owner="someone-else", token=(None, None))
            with self.assertRaises(ConsoleError):
                srv.gh_items_local("not-a-project", token=(None, None))

    def test_both_are_listed_read_only_and_no_write_twin_exists(self):
        for writes in (False, True):
            tools = {t.name: t for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=writes, scopes="").list_tools)}
            for name in ("gh_projects", "gh_project_items"):
                self.assertTrue(tools[name].annotations.read_only_hint, name)
                self.assertFalse(tools[name].annotations.destructive_hint, name)
                self.assertIn(name, srv.INSTRUCTIONS)
            self.assertFalse({n for n in tools if n.startswith(("gh_project", "project_item"))} - {"gh_projects", "gh_project_items"},
                             "a GitHub Projects write tool is P3's (#472), behind its own gate")


class PrQueueTools(unittest.TestCase):
    """pr_queue is ONE GET of /api/prs with its rows trimmed; pr_queue_plan is ONE POST of /api/prs/plan.
    Neither applies anything: applying is the console's prs-act / prs-agent behind its confirm."""

    DOC = {"schema": "pr-queue/v1", "status": "fresh", "counts": {"total": 1}, "batches": [], "warnings": [],
           "rows": [{"key": "o/a#1", "title": "t", "next": {"who": "amr", "action": "review and merge it"},
                     "gate": {"gated": True, "reason": "labelled needs-amr"}, "check_runs": [{"name": "x" * 500}],
                     "checks": {"state": "green", "false_red": True, "superseded": 3, "green": 4},
                     "triage": {"next_action": "Amr merges.", "commands": ["gh pr merge 1"]}}]}

    def test_one_get_with_trimmed_rows(self):
        fc = FakeConsole({"/api/prs": self.DOC})
        res, text = call(srv.build_server(fc), "pr_queue", {"who": "amr", "limit": 999})
        self.assertFalse(res.is_error, text)
        row = payload(res, text)["rows"][0]
        self.assertNotIn("check_runs", row)
        self.assertEqual(row["checks"], {"state": "green", "false_red": True, "failing": None, "cancelled": None})
        self.assertEqual(row["triage"], "Amr merges.")
        self.assertEqual(fc.calls, [("GET", "/api/prs", {"who": "amr", "refresh": "auto", "limit": srv.PRQ_LIMIT_MAX}, None)])

    def test_plan_is_one_post_and_never_an_apply(self):
        fc = FakeConsole({("POST", "/api/prs/plan"): lambda body: {"plan_id": "0" * 16, "echo": body}})
        res, text = call(srv.build_server(fc), "pr_queue_plan", {"action": "ready", "prs": ["o/a#1"], "note": "n"})
        self.assertFalse(res.is_error, text)
        self.assertEqual(fc.calls, [("POST", "/api/prs/plan", {}, {"action": "ready", "prs": ["o/a#1"], "params": {"note": "n"}})])
        self.assertFalse(any(c[1] == "/api/jobs" for c in fc.calls))

    def test_listed_read_only_and_named(self):
        tools = {t.name: t for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False, scopes="").list_tools)}
        for name in ("pr_queue", "pr_queue_plan"):
            self.assertTrue(tools[name].annotations.read_only_hint)
        self.assertIn("pr_queue", srv.INSTRUCTIONS)


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


class TelemetryQueryTools(unittest.TestCase):
    """prom_query, logs_search, traces_query (bamr87/bamr87#447): read-only, one console route each."""
    ROUTES = {"/api/telemetry/prom": {"series": []}, "/api/telemetry/logs": {"hits": []},
              "/api/telemetry/traces": {"spans": []}}

    def test_registered_as_read_tools(self):
        tools = {t.name: t for t in anyio.run(srv.build_server(FakeConsole(), allow_writes=False, scopes="").list_tools)}
        for name in ("prom_query", "logs_search", "traces_query"):
            self.assertIn(name, tools)
            a = tools[name].annotations
            self.assertTrue(a.read_only_hint and not a.destructive_hint and a.idempotent_hint, name)
            self.assertIn("API-equivalent (estimate)" if name != "traces_query" else "claude-code-otel",
                          tools[name].description)

    def test_each_calls_its_route_with_only_what_was_set(self):
        fc = FakeConsole(self.ROUTES)
        server = srv.build_server(fc)
        call(server, "prom_query", {"query": "claude_code_session_count_total", "start": "6h"})
        self.assertEqual(fc.calls[-1][:3], ("GET", "/api/telemetry/prom",
                                            {"query": "claude_code_session_count_total", "start": "6h"}))
        call(server, "logs_search", {"level": "error", "limit": 500})
        self.assertEqual(fc.calls[-1][:3], ("GET", "/api/telemetry/logs", {"level": "error", "since": "24h", "limit": 100}))
        call(server, "traces_query", {"slowest": True, "limit": 99})
        self.assertEqual(fc.calls[-1][:3], ("GET", "/api/telemetry/traces", {"slowest": "true", "since": "24h", "limit": 50}))

    def test_a_console_without_the_routes_names_the_issue(self):
        res, text = call(srv.build_server(FakeConsole()), "prom_query", {"query": "claude_code_session_count_total"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("bamr87/bamr87#447", text)

    def test_a_refusal_is_a_tool_error_with_the_reason(self):
        fc = FakeConsole({"/api/telemetry/prom": ConsoleError("console GET /api/telemetry/prom -> 422: metric 'up' "
                                                               "is outside the allowlist", 422)})
        res, text = call(srv.build_server(fc), "prom_query", {"query": "up"})
        self.assertIn("allowlist", text)
        self.assertNotIn("s3cret-token", text)


class MergedFleet(unittest.TestCase):
    """tools/fleetcore/mcp_server.py folded in: same names, the legacy writes only on --fleet-compat or writes on."""
    LEGACY_READ = {"fleet_overview", "fleet_apps", "fleet_inbox", "fleet_docker", "fleet_nodes", "fleet_work",
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

    def test_the_fleet_workflow_model_is_fleet_workflows_with_fleet_true(self):
        s = srv.build_server(FakeConsole(), allow_writes=False)
        with tempfile.TemporaryDirectory() as lake, mock.patch.dict(os.environ, {"DASH_LAKE_DIR": lake}):
            doc = payload(*call(s, "fleet_workflows", {"fleet": True}))
            self.assertEqual(doc["schema"], "fleet-workflows/v1")
            self.assertEqual(doc["summary"]["repos"], len(doc["repos"]))
            self.assertEqual(doc["summary"]["read"], 0)  # nothing synced into this lake: not read, never a pass
            self.assertTrue(all(r["read"] is False and r["reason"] for r in doc["repos"]))
            one = payload(*call(s, "fleet_workflows", {"fleet": True, "repo": "bamr87/bamr87"}))
            self.assertEqual(one["repo"]["nwo"], "bamr87/bamr87")
            res, text = call(s, "fleet_workflows", {"fleet": True, "repo": "no-such-repo-anywhere"})
            self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
            self.assertIn("no-such-repo-anywhere", text)

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

    def test_fleet_inbox_carries_a_merge_items_clears(self):
        """FF-0036: through the layer too, a merge item (a green, clean fix PR) reaches the agent
        with what merging it clears and on what evidence."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/, for fleetcore
        from fleetcore import mcp_server as legacy
        clears = [".github/workflows/ci.yml", "#127"]
        merge = {"kind": "merge", "repo": "bashcrawl", "ref": "#133", "title": "fix(ci): exclude CHANGELOG.md",
                 "why": "Merge #133: clears CI on main and #127 once its branch is updated", "age_days": 3,
                 "url": "https://github.com/bamr87/bashcrawl/pull/133", "priority": 95, "clears": clears,
                 "evidence": "verified"}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "_data").mkdir()
            (Path(d) / "_data" / "projects.yml").write_text("[]\n")
            (Path(d) / "_data" / "fleet_triage.yml").write_text(
                json.dumps({"generated_at": "2026-11-02 18:00 UTC", "by_repo": [], "inbox": [merge]}))
            with mock.patch.object(legacy, "ROOT", Path(d)):
                inbox = payload(*call(srv.build_server(FakeConsole(), allow_writes=False), "fleet_inbox"))
        top = inbox["items"][0]
        self.assertEqual((top["kind"], top["priority"], top["clears"], top["evidence"]), ("merge", 95, clears, "verified"))


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


SID = "ab" * 16
LOOK_TOOLS = {"page_snapshot", "page_read", "page_data", "page_highlight"}
ACT_TOOLS = {"page_navigate", "page_click", "page_fill", "page_press"}


class PageTools(unittest.TestCase):
    """The page tools (../page_bridge.py behind /api/assist/page/…): which server carries them, which page
    they reach, what they send, and that a refusal or a decline arrives as a tool error with its reason."""

    def env(self, **kw):
        base = {"HARNESS_MCP_ALLOW_WRITES": "", "HARNESS_MCP_SCOPES": "", "HARNESS_MCP_PAGE_SESSION": ""}
        return mock.patch.dict(os.environ, {**base, **kw})

    def console(self, answer=None):
        return FakeConsole({("POST", "/api/assist/page-command"):
                            answer or (lambda body: {"ok": True, "result": {"echo": body}, "action": body["action"]})})

    def test_no_page_tool_unless_the_server_is_local_or_was_started_for_a_page(self):
        with self.env():
            self.assertFalse((LOOK_TOOLS | ACT_TOOLS | {"page_attach"}) & tool_names(srv.build_server(FakeConsole())))
            # a session id in the environment never opens the tools on a server told it is not local (HTTP)
        with self.env(HARNESS_MCP_PAGE_SESSION=SID, HARNESS_MCP_SCOPES="page"):
            self.assertFalse((LOOK_TOOLS | ACT_TOOLS) & tool_names(srv.build_server(FakeConsole(), page=False)))
        with self.env(HARNESS_MCP_PAGE_SESSION="not-a-session"):
            self.assertFalse(LOOK_TOOLS & tool_names(srv.build_server(FakeConsole())))

    def test_a_local_server_reads_a_paired_page_and_acts_only_with_the_page_scope(self):
        with self.env():
            names = tool_names(srv.build_server(FakeConsole(), page=True))
            self.assertEqual(names & (LOOK_TOOLS | ACT_TOOLS | {"page_attach"}), LOOK_TOOLS | {"page_attach"})
            scoped = tool_names(srv.build_server(FakeConsole(), page=True, scopes="page"))
            self.assertTrue(ACT_TOOLS <= scoped)
            self.assertFalse({"job_dispatch", "work_apply", "run_op", "console_run"} & scoped)

    def test_the_docked_session_is_bound_to_its_page_and_cannot_re_pair(self):
        with self.env(HARNESS_MCP_PAGE_SESSION=SID, HARNESS_MCP_SCOPES="page"):
            s = srv.build_server(self.console())
            names = tool_names(s)
        self.assertTrue((LOOK_TOOLS | ACT_TOOLS) <= names)
        self.assertNotIn("page_attach", names)
        self.assertFalse({"run_op", "console_run", "job_dispatch", "work_apply"} & names)

    def test_annotations_say_which_tools_only_read(self):
        with self.env():
            tools = {t.name: t.annotations for t in anyio.run(srv.build_server(FakeConsole(), page=True, scopes="page").list_tools)}
        for name in ("page_snapshot", "page_read", "page_data"):
            self.assertTrue(tools[name].read_only_hint, name)
        for name in ("page_highlight", "page_attach"):
            self.assertFalse(tools[name].read_only_hint or tools[name].destructive_hint, name)
        for name in ACT_TOOLS:
            self.assertTrue(tools[name].destructive_hint and not tools[name].read_only_hint, name)

    def test_each_tool_sends_its_action_and_arguments_and_waits_long_enough_for_a_person(self):
        fc = self.console()
        with self.env(HARNESS_MCP_PAGE_SESSION=SID, HARNESS_MCP_SCOPES="page"):
            s = srv.build_server(fc)
        for tool, args, want in (
                ("page_snapshot", {}, ("snapshot", {"max_chars": 24000})),
                ("page_read", {"ref": "e4", "max_chars": 900}, ("read", {"ref": "e4", "max_chars": 900})),
                ("page_data", {}, ("data", {"key": "", "max_chars": 24000})),
                ("page_data", {"key": '["jobs"]'}, ("data", {"key": '["jobs"]', "max_chars": 24000})),
                ("page_highlight", {"ref": "e2", "note": "here"}, ("highlight", {"ref": "e2", "note": "here"})),
                ("page_navigate", {"path": "/loops"}, ("navigate", {"path": "/loops"})),
                ("page_click", {"ref": "e9"}, ("click", {"ref": "e9"})),
                ("page_fill", {"ref": "e3", "text": ""}, ("fill", {"ref": "e3", "text": "", "submit": False})),
                ("page_fill", {"ref": "e3", "text": "x", "submit": True}, ("fill", {"ref": "e3", "text": "x", "submit": True})),
                ("page_press", {"key": "Escape"}, ("press", {"key": "Escape"})),
                ("page_press", {"key": "Enter", "ref": "e3"}, ("press", {"key": "Enter", "ref": "e3"}))):
            res, text = call(s, tool, args)
            self.assertFalse(res.is_error if hasattr(res, "is_error") else res.isError, f"{tool}: {text}")
            method, path, _, body = fc.calls[-1]
            self.assertEqual((method, path), ("POST", "/api/assist/page-command"))
            self.assertEqual(body["sid"], SID, "the session id rides in the body, never in the address")
            self.assertEqual((body["action"], body["args"], body["client"]), (*want, "dock"), tool)
            wait = fc.timeouts[-1]
            self.assertEqual(wait, srv.PAGE_ACT_WAIT_S if tool in ACT_TOOLS else srv.PAGE_LOOK_WAIT_S, tool)
        self.assertGreater(srv.PAGE_ACT_WAIT_S, 90 + 20, "an ask waits 90 s for the person, then 20 s for the page")

    def test_a_refusal_a_decline_and_a_timeout_are_tool_errors_that_carry_the_reason(self):
        for kind, why in (("refused", "the person set this page to Look only"), ("declined", "the person said no"),
                          ("timeout", "the person did not answer within 90 s"), ("page", "that control is inside a modal dialog")):
            fc = self.console(lambda body, k=kind, w=why: {"ok": False, "kind": k, "error": w})
            with self.env(HARNESS_MCP_PAGE_SESSION=SID, HARNESS_MCP_SCOPES="page"):
                res, text = call(srv.build_server(fc), "page_click", {"ref": "e1"})
            self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
            self.assertIn(f"{kind}: {why}", text)
            self.assertNotIn("s3cret-token", text)

    def test_pairing_with_a_fleet_page_says_which_repo_and_source_file_it_is(self):
        facts = {"repo": "bamr87/it-journey", "source": "pages/about.md", "title": "About"}
        fc = FakeConsole({("POST", "/api/assist/page-attach"): lambda body: {
            "sid": SID, "mode": "ask", "ceiling": "act", "live": True, "paired": 1, "kind": "fleet",
            "origin": "http://127.0.0.1:4010", "page": facts}})
        with self.env():
            s = srv.build_server(fc, page=True)
        res, text = call(s, "page_attach", {"code": "ABCD-EFGH"})
        got = payload(res, text)
        self.assertEqual((got["kind"], got["origin"], got["page"]), ("fleet", "http://127.0.0.1:4010", facts))
        self.assertNotIn(SID, text, "the session id stays in the server process")

    def test_pairing_binds_the_session_the_console_answers_and_never_returns_it(self):
        fc = FakeConsole({("POST", "/api/assist/page-attach"): lambda body: {"sid": SID, "mode": "ask", "ceiling": "act",
                                                                             "live": True, "paired": 1},
                          ("POST", "/api/assist/page-command"): lambda body: {"ok": True, "result": {"route": "/loops"}}})
        with self.env():
            s = srv.build_server(fc, page=True)
        res, text = call(s, "page_snapshot")
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("no page is attached", text)
        self.assertIn("page_attach", text)
        res, text = call(s, "page_attach", {"code": "ABCD-EFGH"})
        self.assertEqual(payload(res, text), {"mode": "ask", "ceiling": "act", "live": True, "kind": "console"})
        self.assertNotIn(SID, text, "the session id is a capability: it stays inside the server process")
        self.assertEqual(fc.calls[-1][3], {"code": "ABCD-EFGH"})
        self.assertEqual(payload(*call(s, "page_snapshot")), {"route": "/loops"})
        self.assertEqual(fc.calls[-1][3]["client"], "paired")

    def test_a_wrong_code_and_a_closed_page_are_said(self):
        gone = ConsoleError("console POST /x -> 404: no such page session", 404)
        fc = FakeConsole({("POST", "/api/assist/page-attach"): ConsoleError("console POST -> 403: that pairing code is not on any open page", 403)})
        with self.env():
            s = srv.build_server(fc, page=True)
        res, text = call(s, "page_attach", {"code": "ZZZZZZZZ"})
        self.assertTrue(res.is_error if hasattr(res, "is_error") else res.isError)
        self.assertIn("pairing code", text)
        fc.routes[("POST", "/api/assist/page-attach")] = lambda body: {"sid": SID, "mode": "look", "ceiling": "act", "live": True}
        fc.routes[("POST", "/api/assist/page-command")] = gone
        call(s, "page_attach", {"code": "ABCDEFGH"})
        res, text = call(s, "page_snapshot")
        self.assertIn("no such page session", text)
        res, text = call(s, "page_snapshot")            # the dead session was dropped: pair again
        self.assertIn("no page is attached", text)

    def test_the_overview_reports_the_page_scope(self):
        with self.env():
            p = payload(*call(srv.build_server(FakeConsole(), page=True, scopes="page"), "console_overview"))
        self.assertEqual(p["mcp_scopes"], ["page"])
        self.assertFalse(p["mcp_writes_enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

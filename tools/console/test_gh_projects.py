#!/usr/bin/env python3
"""Offline tests for gh_projects (read model, linked graph, and the read aggregator the
console's /api/gh-projects routes and the MCP's gh_projects tools serve: every owner,
scope said per owner, TTL cache, call budget and clock, paging and the item cap) and
gh_projects_write (allowlist, dry run, flag + confirm gate, stale plan, idempotency,
caps, audit, redaction). Standalone script, recorded fixtures, no network. Exits
non-zero on failure."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gh_projects as gp  # noqa: E402
import gh_projects_write as gw  # noqa: E402

FX = json.loads((HERE / "test_gh_projects_fixtures.json").read_text())
FAILS: list[str] = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def fx(name):
    return FX[name]


def fake_http(query, variables, tok):
    if "projectsV2(first" in query:
        if "organization(" in query:
            return {"errors": [{"type": "INSUFFICIENT_SCOPES", "message": "needs read:project"}], "data": None}
        return fx("projects_user.json")
    return fx("items.json")


def no_network(*a, **k):
    raise AssertionError("network called")


def test_read():
    res = gp.list_projects(http=fake_http, tok="t")
    check(len(res["projects"]) == 1 and res["projects"][0]["number"] == 14, "user project read")
    check(res["scope_missing"] is True, "org scope missing reported, not raised")
    check(any("read:project" in o.get("error", "") for o in res["owners"]), "scope message honest")
    items = gp.project_items("PVT_fleet", http=fake_http, tok="t")
    check([i["kind"] for i in items] == ["issue", "pr"], "item kinds")
    check(items[0]["refs"] == ["FR12", "HUB-031"], "refs parsed from body")
    check("[redacted]" in items[1]["title"] and "ghp_" not in json.dumps(items), "token-like strings redacted")
    g = gp.linked_graph(res["projects"], {"PVT_fleet": items})
    kinds = {n["kind"] for n in g["nodes"]}
    check({"project", "item", "issue", "pr", "commit", "repo", "ref"} <= kinds, f"graph kinds {kinds}")
    rels = {(e["src"], e["rel"], e["dst"]) for e in g["edges"]}
    check(("pr:year-of-ai/site#500", "closes", "issue:bamr87/bamr87#469") in rels, "cross-repo closes edge")
    nb = gp.neighbours(g, "issue:bamr87/bamr87#469")
    check(any(e["rel"] == "closes" for e in nb["edges"]), "neighbours")
    calls = []
    gp.clear_cache()
    gp.cached("k", lambda: calls.append(1) or 1, now=lambda: 0)
    gp.cached("k", lambda: calls.append(1) or 1, now=lambda: 10)
    check(len(calls) == 1, "ttl cache hit")


STATE = {"bamr87/bamr87#1": {"labels": ["P2"], "state": "open"}}


def state(op):
    if "repo" in op:
        return STATE.get(f"{op['repo']}#{op['number']}")
    return {"present": False}


def test_write():
    allow = {"bamr87/bamr87"}
    for bad in ({"op": "pr.merge", "repo": "bamr87/bamr87", "number": 1},
                {"op": "issue.delete", "repo": "bamr87/bamr87", "number": 1},
                {"op": "repo.settings", "repo": "bamr87/bamr87"},
                {"op": "issue.lock", "repo": "bamr87/bamr87", "number": 1},
                {"op": "issue.edit", "repo": "bamr87/bamr87", "number": 1, "set": {"state_reason": "x"}},
                {"op": "issue.labels.add", "repo": "evil/repo", "number": 1, "labels": ["x"]}):
        try:
            gw.plan([bad], state, allow)
            FAILS.append(f"not refused: {bad['op']}")
        except gw.Refused:
            pass
    try:
        gw.plan([{"op": "item.archive", "project_id": "P", "item_id": "I"}] * 51, state)
        FAILS.append("per-plan cap")
    except gw.Refused:
        pass
    ops = [{"op": "issue.labels.add", "repo": "bamr87/bamr87", "number": 1, "labels": ["P2"]},
           {"op": "issue.labels.add", "repo": "bamr87/bamr87", "number": 1, "labels": ["epic"]},
           {"op": "item.add", "project_id": "P", "content_id": "I_1"}]
    p1, p2 = gw.plan(ops, state, allow), gw.plan(ops, state, allow)
    check(p1["plan_id"] == p2["plan_id"] and p1["dry_run"], "deterministic dry run")
    check([r["noop"] for r in p1["rows"]] == [True, False, False], "idempotent no-op detection")

    with tempfile.TemporaryDirectory() as d:
        audit = Path(d) / "a.jsonl"
        os.environ.pop(gw.FLAG, None)
        r = gw.apply(p1["plan_id"], ops, state, no_network, confirm=True, audit=audit)
        check(r["applied"] == 0 and "disabled" in r["refused"], "flag off refuses")
        os.environ[gw.FLAG] = "1"
        r = gw.apply(p1["plan_id"], ops, state, no_network, confirm=False, audit=audit)
        check(r["applied"] == 0 and "confirm" in r["refused"], "confirm required")
        r = gw.apply("deadbeef", ops, state, no_network, confirm=True, audit=audit)
        check("stale" in r["refused"], "stale plan refused")
        done = []

        def execute(op):
            done.append(op["op"])
            return {"ok": True, "echo": "ghp_abcdefghijklmnopqrstuvwxyz0123"}
        r = gw.apply(p1["plan_id"], ops, state, execute, confirm=True, audit=audit, actor="test")
        check(r["applied"] == 2 and done == ["issue.labels.add", "item.add"], f"apply executes changes only: {done}")
        text = audit.read_text()
        check(len(text.splitlines()) == 3 and "ghp_" not in text and "[redacted]" in text, "audit written, redacted")
        old = gw.MAX_OPS_PER_HOUR
        gw.MAX_OPS_PER_HOUR = 2
        r = gw.apply(p1["plan_id"], ops, state, execute, confirm=True, audit=audit)
        check("hourly cap" in r.get("refused", ""), "hourly cap")
        gw.MAX_OPS_PER_HOUR = old
        os.environ.pop(gw.FLAG, None)


TOKEN = ("GH_TOKEN", "t")


def counting(http):
    calls = []

    def call(query, variables, tok):
        calls.append((query, dict(variables)))
        return http(query, variables, tok)
    return call, calls


def test_projects_view():
    """The aggregator: every owner in one document, scope said per owner, a TTL cache that keeps only an
    answer that reflects GitHub, the call budget and the transport failures said and never cached."""
    gp.clear_cache()
    http, calls = counting(fake_http)
    d = gp.projects_view(http=http, token=TOKEN, calls=gp.CallBudget())
    check(d["schema"] == "gh-projects/v1" and d["read_only"] is True, "projects schema")
    check([o["login"] for o in d["owners"]] == [login for _, login in gp.OWNERS], "every owner, in order")
    check(d["owners"][0]["status"] == "ok" and d["owners"][0]["projects"] == 1, "user owner read")
    check(all(o["status"] == "scope_missing" and "read:project" in o["error"] for o in d["owners"][1:]),
          "org owners say scope_missing")
    check((d["status"], d["scope_missing"], d["source"], d["token_source"]) == ("partial", True, "live", "GH_TOKEN"),
          f"partial + scope: {d['status']} {d['source']}")
    check("read:project" in (d["hint"] or ""), "scope hint")
    check(d["counts"] == {"owners": 5, "read": 1, "projects": 1, "open": 1}, f"counts {d['counts']}")
    check(d["projects"][0]["fields"][0]["options"] == ["Triage", "In progress"], "status options kept")
    n = len(calls)
    again = gp.projects_view(http=http, token=TOKEN, calls=gp.CallBudget())
    check(again["source"] == "cache" and len(calls) == n, "inside the TTL: no call")
    fresh = gp.projects_view(http=http, token=TOKEN, calls=gp.CallBudget(), refresh=True)
    check(fresh["source"] == "live" and len(calls) == 2 * n, "refresh reads again")
    one = gp.projects_view(http=http, token=TOKEN, calls=gp.CallBudget(), owner="BAMR87")
    check(len(one["owners"]) == 1 and one["status"] == "fresh" and len(calls) == 2 * n, "owner narrows the cache")
    try:
        gp.projects_view(http=http, token=TOKEN, owner="someone-else")
        FAILS.append("an unknown owner was accepted")
    except ValueError:
        pass

    gp.clear_cache()  # no token: every owner scope_missing, nothing sent, nothing cached
    d = gp.projects_view(http=no_network, token=(None, None), calls=gp.CallBudget())
    check((d["status"], d["source"], d["token_source"]) == ("scope_missing", "none", None), f"no token {d['status']}")
    check(all(o["status"] == "scope_missing" for o in d["owners"]) and "PROJECTS_TOKEN" in d["hint"], "no token said")
    check(not gp._cache, "a tokenless answer is not cached")

    gp.clear_cache()  # the call budget: the read stops, says so, and is not cached
    budget = gp.CallBudget(limit=2)
    http, calls = counting(fake_http)
    d = gp.projects_view(http=http, token=TOKEN, calls=budget)
    check(len(calls) == 2 and [o["status"] for o in d["owners"]][2:] == ["skipped"] * 3, "budget stops the read")
    check("call budget" in d["owners"][2]["error"] and d["budget"]["left"] == 0, "budget said")
    check(not gp._cache, "a budget-cut answer is not cached")

    gp.clear_cache()  # a refused token stops every later owner; a missing org is that owner's error

    def refused(query, variables, tok):
        raise urllib.error.HTTPError(gp.API, 401, "Unauthorized", {}, None)
    d = gp.projects_view(http=refused, token=TOKEN, calls=gp.CallBudget())
    check(d["status"] == "unavailable" and d["owners"][0]["error"] == "GitHub refused the token (401)", "401 said")
    check(all(o["status"] == "skipped" and "401" in o["error"] for o in d["owners"][1:]), "401 stops the rest")
    check(not gp._cache, "a failed read is not cached")

    def org_missing(query, variables, tok):
        if "organization(" in query:
            return {"data": {"organization": None}, "errors": [
                {"type": "NOT_FOUND", "message": f"Could not resolve to an Organization with the login of '{variables['login']}'."}]}
        doc = json.loads(json.dumps(fx("projects_user.json")))
        doc["data"]["user"]["projectsV2"]["nodes"].append(
            {"id": "PVT_old", "number": 2, "title": "old ghp_abcdefghijklmnopqrstuvwxyz0123", "url": "u", "closed": True,
             "fields": {"nodes": []}})
        return doc
    gp.clear_cache()
    d = gp.projects_view(http=org_missing, token=TOKEN, calls=gp.CallBudget())
    check(d["owners"][1]["status"] == "error" and "Could not resolve" in d["owners"][1]["error"], "org not readable")
    check("ghp_" not in json.dumps(d) and d["counts"]["projects"] == 2 and d["counts"]["open"] == 1, "redacted, closed counted")
    check([p["number"] for p in gp.projects_view(http=org_missing, token=TOKEN, include_closed=False)["projects"]] == [14],
          "closed projects dropped on request")
    gp.clear_cache()


def items_page(n, start, more):
    nodes = [{"id": f"PVTI_{start + i}", "isArchived": False, "type": "ISSUE",
              "fieldValues": {"nodes": [{"name": ("Done" if (start + i) % 2 else "Todo"), "field": {"name": "Status"}}]},
              "content": {"__typename": "Issue", "id": f"I_{start + i}", "number": start + i,
                          "title": f"item {start + i}", "state": "OPEN", "url": "u", "body": "",
                          "repository": {"nameWithOwner": "bamr87/bamr87"}}} for i in range(n)]
    return {"data": {"node": {"items": {"pageInfo": {"hasNextPage": more, "endCursor": f"c{start + n}"},
                                        "nodes": nodes}}}}


def test_items_view():
    """One project's items: paged, filtered, counted over the whole read, capped at max_items, a budget
    stop said as partial, a missing project and a bad argument refused."""
    gp.clear_cache()
    d = gp.items_view("PVT_fleet", http=fake_http, token=TOKEN, calls=gp.CallBudget(), limit=1)
    check((d["schema"], d["status"], d["total"], d["matched"], len(d["items"]), d["next_offset"]) ==
          ("gh-project-items/v1", "fresh", 2, 2, 1, 1), f"paged {d['status']} {d['next_offset']}")
    check(d["counts"] == {"by_status": {"Triage": 1, "In progress": 1}, "by_kind": {"issue": 1, "pr": 1}}, "counts")
    d = gp.items_view("PVT_fleet", http=no_network, token=TOKEN, offset=1, limit=5)
    check(d["source"] == "cache" and d["next_offset"] is None and d["items"][0]["kind"] == "pr", "second page from cache")
    check([i["kind"] for i in gp.items_view("PVT_fleet", http=no_network, token=TOKEN, kind="pr")["items"]] == ["pr"], "kind")
    check(gp.items_view("PVT_fleet", http=no_network, token=TOKEN, status="triage")["matched"] == 1, "status filter")
    check(gp.items_view("PVT_fleet", http=no_network, token=TOKEN, q="469")["matched"] == 1, "text filter")
    check("ghp_" not in json.dumps(gp.items_view("PVT_fleet", http=no_network, token=TOKEN)), "items redacted")
    gp.clear_cache()
    capped = gp.items_view("PVT_fleet", http=fake_http, token=TOKEN, max_items=1)
    check(capped["capped"] is True and capped["total"] == 1 and capped["complete"] is False and "more than 1" in capped["hint"],
          "the read stops at max_items and says so")

    gp.clear_cache()  # pages: two reads of 100, then the budget stops the third

    def paged(query, variables, tok):
        start = int((variables.get("after") or "c0")[1:])
        return items_page(gp.PAGE, start, more=True)
    d = gp.items_view("PVT_big", http=paged, token=TOKEN, calls=gp.CallBudget(limit=2), limit=5)
    check((d["status"], d["total"], d["capped"]) == ("partial", 200, False) and "call budget" in d["errors"][0],
          f"budget mid-read: {d['status']} {d['total']}")
    check(d["counts"]["by_status"] == {"Todo": 100, "Done": 100} and not gp._cache, "partial counted, not cached")
    full = gp.items_view("PVT_big", http=paged, token=TOKEN, calls=gp.CallBudget(), limit=0)
    check((full["total"], full["capped"], full["items"]) == (gp.MAX_ITEMS, True, []), "500 cap, limit 0 counts only")

    gp.clear_cache()

    def gone(query, variables, tok):
        return {"data": {"node": None}, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a node"}]}
    try:
        gp.items_view("PVT_gone", http=gone, token=TOKEN)
        FAILS.append("a missing project was not refused")
    except gp.NotReadable as e:
        check("Could not resolve" in str(e), "not-readable reason")
    d = gp.items_view("PVT_fleet", http=fake_http, token=(None, None))
    check((d["status"], d["items"], d["source"]) == ("scope_missing", [], "none"), "items without a token")
    for bad in ({"project_id": "../api/jobs"}, {"project_id": "PVT_x", "kind": "epic"}):
        try:
            gp.items_view(bad.pop("project_id"), http=no_network, token=TOKEN, **bad)
            FAILS.append(f"accepted {bad}")
        except ValueError:
            pass
    gp.clear_cache()


def test_budgets():
    t = [0.0]
    b = gp.CallBudget(limit=2, window=10, now=lambda: t[0])
    b.take()
    b.take()
    try:
        b.take()
        FAILS.append("the window let a third call through")
    except gp.BudgetSpent as e:
        check("frees up in" in str(e), "budget says when it frees")
    t[0] = 10.5
    b.take()
    check(b.state() == {"limit": 2, "window_s": 10, "used": 1, "left": 1}, f"window slides {b.state()}")
    clock_t = [100.0]
    clock = gp.Clock(1, now=lambda: clock_t[0])
    call = gp._metered(lambda q, v, tok: {"data": {}}, gp.CallBudget(), clock)
    check(call("q", {}, "t") == {"data": {}}, "a call inside the clock")
    clock_t[0] = 100.9
    try:
        call("q", {}, "t")
        FAILS.append("the clock let a call through after it ran out")
    except gp.BudgetSpent as e:
        check("time budget" in str(e), "clock says so")
    check(gp.Clock(999).seconds == gp.BUDGET_MAX_S and gp.Clock(None).seconds == gp.BUDGET_S, "clock clamped")
    with_env = {k: os.environ.pop(k, None) for k in ("PROJECTS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")}
    try:
        check(gp.resolve_token(lambda: ("gh", "x")) == ("gh", "x"), "falls back to the console identity")
        check(gp.resolve_token(lambda: (None, None)) == (None, None), "no identity, no token")
        os.environ["PROJECTS_TOKEN"] = "p"
        check(gp.resolve_token(lambda: ("gh", "x")) == ("PROJECTS_TOKEN", "p"), "PROJECTS_TOKEN first")
    finally:
        os.environ.pop("PROJECTS_TOKEN", None)
        for k, v in with_env.items():
            if v is not None:
                os.environ[k] = v


def test_read_side_never_imports_the_write_side():
    for name in ("gh_projects.py", "app.py"):
        src = (HERE / name).read_text()
        check(not re.search(r"^\s*(import|from)\s+gh_projects_write\b", src, re.M), f"{name} imports the write side")


if __name__ == "__main__":
    test_read()
    test_projects_view()
    test_items_view()
    test_budgets()
    test_read_side_never_imports_the_write_side()
    test_write()
    for f in FAILS:
        print("FAIL:", f)
    print("ok" if not FAILS else f"{len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)

#!/usr/bin/env python3
"""Offline tests for gh_projects (read model + linked graph) and gh_projects_write
(allowlist, dry run, flag + confirm gate, stale plan, idempotency, caps, audit, redaction).
Standalone script, recorded fixtures, no network. Exits non-zero on failure."""
from __future__ import annotations

import json
import os
import sys
import tempfile
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


if __name__ == "__main__":
    test_read()
    test_write()
    for f in FAILS:
        print("FAIL:", f)
    print("ok" if not FAILS else f"{len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)

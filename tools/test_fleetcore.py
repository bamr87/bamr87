#!/usr/bin/env python3
"""Fixture tests for tools/fleetcore's shared contracts — keys v1, the theme, the console client.

The data layer (fleet.py, host.py) is covered by test_tui_fleet.py; this file
holds what the browser console and the terminal dash must agree on. Needs only
the standard library and PyYAML.

    python3 tools/test_fleetcore.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleetcore import keys, theme  # noqa: E402
from fleetcore.client import ConsoleClient, ConsoleError  # noqa: E402


def test_keys_are_unique_per_surface():
    for surface in keys.SURFACES:
        bound = keys.bindings_for(surface)
        for attr in ("key", "dom"):
            values = [getattr(k, attr) for k in bound]
            assert len(values) == len(set(values)), f"{surface}: duplicate {attr}"


def test_keys_v1_universal_layer_is_the_plan():
    """docs/TERMINAL-FRAMEWORK.md §6.1 — the universal keys, by their DOM name."""
    web = {k.dom: k.action for k in keys.bindings_for("web")}
    for dom, action in {"?": "help", ":": "palette", "/": "search", "Escape": "back", "j": "down",
                        "k": "up", "g": "top", "G": "bottom", "]": "next_tab", "[": "prev_tab",
                        "r": "refresh", "y": "copy", "o": "open"}.items():
        assert web.get(dom) == action, (dom, web.get(dom))
    assert "q" not in web, "the browser has no quit"
    assert {k.dom for k in keys.bindings_for("tui")} >= {"q"}


def test_the_loop_run_key_is_in_the_dash_layer_on_both_surfaces():
    """`L` runs the selected repo through a loop's agent step (the console's
    loop-run op) — bound by the TUI and the page from this one table."""
    for surface in keys.SURFACES:
        k = next(k for k in keys.bindings_for(surface) if k.action == "loop_run")
        assert k.dom == "L" and k.group == "dash", k


def test_loop_job_fields_are_read_from_the_record_or_the_status_lines():
    """tools/fleetcore/loopjob.py — the one parser of a loop-run job's log."""
    from fleetcore import loopjob
    record = {"schema": "jev-loop-run/v1", "run_id": "r-1", "status": "completed", "exit_code": 0, "mode": "run",
              "loop": "repo-scout", "step": "scout", "options": {"target": "SCHEMA"},
              "tier": {"model": "claude-sonnet-5-5", "max_turns": 40, "cap_usd": 8.0},
              "totals": {"attempts": 1, "estimated_usd": 0, "label": "API-equivalent (estimate)", "published": 0,
                         "spent_usd": 0.61},
              "usage_limited": False, "finished": "2026-11-03T18:00:00Z",
              "items": [{"key": "bamr87/SCHEMA", "status": "validated", "decision": "attempt", "reason": "",
                         "outcome": "ok", "cost_usd": 0.61, "cost_source": "reported", "turns": 17,
                         "flags": ["1 permission denial(s)"], "context": {"line": "context auto · 3 sections"}}],
              "notes": ["manual run"]}
    log = ("$ tools/dash loop run repo-scout --target SCHEMA --json\n"
           "jev loop: run r-1\n"
           "jev loop: manual run — bypasses vars.REPO_SCOUT_ENABLED exactly as a workflow_dispatch does\n"
           "  validated      bamr87/SCHEMA  \n"
           "                 ! 1 permission denial(s)\n"
           "jev loop: completed — $0.61 spent (API-equivalent (estimate)); exit 0\n"
           + json.dumps(record, indent=2, sort_keys=True) + "\n")
    f = loopjob.parse_log(log)
    assert f["record"] and f["run_id"] == "r-1" and f["status"] == "completed" and f["exit_code"] == 0
    assert (f["loop"], f["step"], f["target"], f["model"], f["max_turns"], f["cap_usd"]) == \
        ("repo-scout", "scout", "SCHEMA", "claude-sonnet-5-5", 40, 8.0)
    assert f["spent_usd"] == 0.61 and f["cost_label"] == "API-equivalent (estimate)" and f["attempts"] == 1
    item = f["items"][0]
    assert (item["key"], item["status"], item["outcome"], item["cost_usd"], item["turns"]) == \
        ("bamr87/SCHEMA", "validated", "ok", 0.61, 17)
    assert item["flags"] == ["1 permission denial(s)"] and item["context"] == "context auto · 3 sections"
    text = "\n".join(loopjob.summary_lines(f))
    assert "completed" in text and "$0.61 spent (API-equivalent (estimate))" in text and "17 turns" in text, text
    # before the record exists (still running, or died): the status lines carry what is known
    partial = loopjob.parse_log(log.split("jev loop: completed")[0])
    assert not partial["record"] and partial["run_id"] == "r-1" and partial["status"] is None
    assert [i["key"] for i in partial["items"]] == ["bamr87/SCHEMA"] and partial["notes"] == ["manual run — bypasses vars.REPO_SCOUT_ENABLED exactly as a workflow_dispatch does"]
    ended = loopjob.parse_log(log.split("{", 1)[0])
    assert ended["status"] == "completed" and ended["spent_usd"] == 0.61 and ended["exit_code"] == 0
    assert loopjob.parse_log("") == loopjob.empty() and loopjob.summary_lines(loopjob.empty()) == []
    # a refusal before any run: the note is kept, nothing else is invented
    refused = loopjob.parse_log("$ x\njev loop: the work root /w is inside the hub (set JEV_WORK_ROOT)\n")
    assert refused["run_id"] is None and refused["notes"] == ["the work root /w is inside the hub (set JEV_WORK_ROOT)"]
    # a record from a newer engine with unknown keys, and junk braces, still parses
    noisy = log.replace("jev loop: run r-1", "jev loop: run r-1\n{\nnot json\n}") 
    assert loopjob.parse_log(noisy)["run_id"] == "r-1" and loopjob.parse_log(noisy)["record"]


def test_theme_css_covers_every_role_in_every_mode():
    css = theme.css()
    for var in theme.CSS_ROLES:
        assert css.count(f"{var}:") == 3, var  # light, OS-dark, explicit dark
    for mode, tokens in theme.TOKENS.items():
        for role in set(theme.CSS_ROLES.values()) | {"panel"}:
            assert role in tokens, (mode, role)
        for value in tokens.values():
            assert re.fullmatch(r"#[0-9a-f]{6}|rgba\([\d., ]+\)", value), value


def test_levels_share_the_status_colours():
    assert theme.level_color("red") == theme.TOKENS["dark"]["error"]
    assert theme.level_color("green", "light") == theme.TOKENS["light"]["success"]
    assert theme.level_color(None) == theme.TOKENS["dark"]["muted"]


def test_client_endpoints():
    assert ConsoleClient("").enabled is False
    try:
        ConsoleClient("").jobs()
        raise AssertionError("an empty URL must not call anything")
    except ConsoleError:
        pass
    try:
        ConsoleClient("ftp://example")._connection()
        raise AssertionError("ftp:// accepted")
    except ConsoleError:
        pass
    assert ConsoleClient("unix:///tmp/x.sock")._connection().host == "localhost"
    try:  # nothing listens on port 9 — a clear error, not a hang or a traceback
        ConsoleClient("http://127.0.0.1:9", timeout=1).health()
        raise AssertionError("no error from a closed port")
    except ConsoleError as exc:
        assert "unreachable" in str(exc)


def test_mcp_server_speaks_the_protocol():
    """The agent surface: handshake, tool list with schemas and annotations,
    a read tool over the real registry, and a console refusal reported as a
    tool error rather than a crash."""
    import os
    from fleetcore import mcp_server as m

    init = m.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})["result"]
    assert init["serverInfo"]["name"] == "fleet" and "tools" in init["capabilities"]
    assert m.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = {t["name"]: t for t in m.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"fleet_apps", "fleet_inbox", "console_run", "console_job_log"} <= set(tools)
    assert tools["fleet_apps"]["annotations"]["readOnlyHint"] is True
    assert tools["console_run"]["annotations"]["destructiveHint"] is True
    assert tools["console_run"]["inputSchema"]["required"] == ["op"]

    def call(name, **args):
        r = m.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return __import__("json").loads(r["result"]["content"][0]["text"]), r["result"]["isError"]

    apps, err = call("fleet_apps", sort="name", limit=3)
    assert not err and apps["count"] >= 3 and len(apps["rows"]) == 3 and "repo_url" in apps["rows"][0]
    old = os.environ.get("DASH_CONSOLE_URL")
    os.environ["DASH_CONSOLE_URL"] = "http://127.0.0.1:9"
    try:
        res, err = call("console_run", op="status")
        assert err and "unreachable" in res["error"]
        res, err = call("console_job_log", job_id="../auth")
        assert err and "not a console job id" in res["error"]
    finally:
        if old is None:
            os.environ.pop("DASH_CONSOLE_URL", None)
        else:
            os.environ["DASH_CONSOLE_URL"] = old
    assert m.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"] == -32601


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

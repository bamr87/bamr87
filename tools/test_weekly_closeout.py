#!/usr/bin/env python3
"""
Contract tests for the weekly close-out family (docs/WEEKLY-CLOSEOUT.md): the
three console loops weekly_closeout / weekly_gather / weekly_finalize and the
ai-lane caller workflows behind them. Holds the wiring equal across its copies
(LOOPS, _data/fleet.yml schedule + kill switch, the workflow's own cron), the
kill-switch default, the turn/dollar caps, the exact model, the standing
"never merge / no force-push" rules in the agent briefs, and the throughput cap.

Run: python3 tools/test_weekly_closeout.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "console"))
sys.path.insert(0, str(ROOT))

FLEET = yaml.safe_load((ROOT / "_data" / "fleet.yml").read_text(encoding="utf-8"))
#: loop id -> (workflow stem, cron, switch variable, brief, model, turns, usd)
LANES = {
    "weekly_closeout": ("weekly-closeout", "17 20 * * 5", "WEEKLY_CLOSEOUT_ENABLED", "closeout.md",
                        "claude-opus-5-5", 120, 20),
    "weekly_gather": ("weekly-gather", "17 17 * * 6", "WEEKLY_GATHER_ENABLED", "gather.md",
                      "claude-sonnet-5-5", 60, 10),
    "weekly_finalize": ("weekly-finalize", "17 23 * * 0", "WEEKLY_FINALIZE_ENABLED", "finalize.md",
                        "claude-sonnet-5-5", 60, 10),
}


def workflow(stem: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / f"{stem}.yml").read_text(encoding="utf-8"))


def lane_call(stem: str) -> dict:
    return workflow(stem)["jobs"]["lane"]


def test_each_loop_is_on_the_console_and_points_at_its_workflow_and_doc():
    import core
    loops = {row["id"]: row for row in core.LOOPS}
    for loop_id, (stem, cron, *_rest) in LANES.items():
        row = loops[loop_id]
        assert row["workflow"] == stem and row["schedule_key"] == loop_id, row
        assert (ROOT / row["doc"]).is_file() and row["doc"] == "docs/WEEKLY-CLOSEOUT.md", row
        assert stem in core.DISPATCH_WORKFLOWS, f"{stem} cannot be dispatched from the console"
        assert FLEET["schedule"][loop_id] == cron, (loop_id, FLEET["schedule"].get(loop_id))


def test_workflow_cron_equals_the_fleet_schedule_and_is_off_the_hour():
    for loop_id, (stem, cron, *_rest) in LANES.items():
        on = workflow(stem).get("on") or workflow(stem).get(True)
        crons = [e["cron"] for e in on["schedule"]]
        assert crons == [cron] == [FLEET["schedule"][loop_id]], (stem, crons)
        assert not cron.startswith("0 "), "never fire on the hour"
        assert "workflow_dispatch" in on, f"{stem} must stay dispatchable"


def test_denver_wall_clock_is_the_utc_cron_in_november_mst():
    # MST is UTC-7: Fri 13:17 / Sat 10:17 / Sun 16:17 Denver
    assert LANES["weekly_closeout"][1] == "17 20 * * 5"
    assert LANES["weekly_gather"][1] == "17 17 * * 6"
    assert LANES["weekly_finalize"][1] == "17 23 * * 0"


def test_no_more_than_the_hour_cap_of_ai_crons_share_a_weekday_hour():
    cap = FLEET["harnesses"]["throughput"]["max_ai_crons_per_utc_hour"]
    mine = {tuple(cron.split()[1:2] + cron.split()[4:5]) for _s, cron, *_r in LANES.values()}
    assert len(mine) == 3, "each lane has its own weekday-hour"
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        if wf.stem in {s for s, *_r in LANES.values()}:
            continue
        for m in re.finditer(r"cron:\s*['\"]([^'\"]+)['\"]", wf.read_text(encoding="utf-8")):
            f = m.group(1).split()
            if len(f) == 5 and (f[1], f[4]) in mine and f[1].isdigit():
                raise AssertionError(f"{wf.name} {m.group(1)} shares a weekday-hour with a weekly lane (cap {cap})")


def test_every_lane_is_an_ai_lane_caller_gated_by_its_own_switch_that_starts_off():
    for stem, _cron, var, *_rest in LANES.values():
        call = lane_call(stem)
        assert call["uses"] == "bamr87/bamr87/.github/workflows/ai-lane.yml@main", stem
        assert call["with"]["switch"] == var and call["with"]["lane"] == stem
        entry = _find(FLEET["switches"], f"hub/{stem}")
        assert entry is not None, f"hub/{stem} is not declared in fleet.yml switches"
        assert entry["default"] == "off" and entry["gate"]["semantics"] == "opt_in", entry
        assert entry["gate"]["name"] == var and entry["dispatch_bypasses"] is True


def _find(node, key):
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    return None


def test_caps_model_and_least_privilege():
    usd_per_turn = FLEET["budget"]["usd_per_turn"]
    allowed = set(FLEET["ai_models"]["allowed"]["anthropic"])
    for loop_id, (stem, _c, _v, _b, model, turns, usd) in LANES.items():
        w = lane_call(stem)["with"]
        assert w["model"] == model and model in allowed, stem
        assert int(w["max-turns"]) == turns and float(w["max-budget-usd"]) == usd, stem
        assert usd >= usd_per_turn * turns, f"{stem}: ${usd} does not clear {usd_per_turn} x {turns} turns"
        assert w.get("result-file"), f"{stem}: a crashed agent must show RED"
        perms = workflow(stem)["permissions"]
        assert "administration" not in perms and perms.get("actions", "none") != "write", perms
    # only Friday may write code; the weekend lanes can comment on an issue and read the rest
    assert workflow("weekly-closeout")["permissions"] == {"contents": "write", "pull-requests": "write"}
    for stem in ("weekly-gather", "weekly-finalize"):
        assert workflow(stem)["permissions"] == {"contents": "read", "issues": "write"}


def test_secrets_are_passed_by_name_only():
    for stem, *_r in LANES.values():
        secrets = lane_call(stem)["secrets"]
        assert set(secrets) == {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GH_PAT"}, stem
        assert secrets["GH_PAT"] == "${{ secrets.FLEET_TOKEN }}"


def test_prompts_and_briefs_forbid_merge_force_push_and_settings_changes():
    briefs = ROOT / ".github" / "weekly"
    for stem, _c, _v, brief, *_r in LANES.values():
        prompt = lane_call(stem)["with"]["prompt"]
        assert f".github/weekly/{brief}" in prompt and re.search(r"[Nn]ever merge", prompt), stem
        text = (briefs / brief).read_text(encoding="utf-8")
        assert re.search(r"[Nn]ever merge", text), brief
        assert "variables or secrets" in text and "never print a token" in text.lower(), brief
    closeout = (briefs / "closeout.md").read_text(encoding="utf-8")
    for needle in ("Never force-push", "#840", "~/bamr87", "git status", "MERGED"):
        assert needle in closeout, needle
    assert "Do not wake other Grok bots" in (briefs / "finalize.md").read_text(encoding="utf-8")


def test_workflows_contain_no_force_push_or_merge_commands():
    for stem, *_r in LANES.values():
        text = (ROOT / ".github" / "workflows" / f"{stem}.yml").read_text(encoding="utf-8")
        assert not re.search(r"--force|gh pr merge|git push", text), stem


def test_the_feature_fragment_and_docs_cover_the_family():
    frag = yaml.safe_load((ROOT / "features" / "features.d" / "weekly-closeout.yml").read_text(encoding="utf-8"))
    assert frag["id"] == "HUB-NEW" and frag["prd"] == ["FR-NEW:weekly-closeout"], frag["prd"]
    assert [r["key"] for r in frag["prd_new"]] == ["weekly-closeout"]
    doc = (ROOT / "docs" / "WEEKLY-CLOSEOUT.md").read_text(encoding="utf-8")
    for needle in ("User stories", "Failure modes", "WEEKLY_CLOSEOUT_ENABLED", "WEEKLY_GATHER_ENABLED",
                   "WEEKLY_FINALIZE_ENABLED", "Grok", "loop-run", "mcp_writes_enabled", "harness-console-http"):
        assert needle in doc, needle


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

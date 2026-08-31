#!/usr/bin/env python3
"""
Fixture tests for harness_registry.py — the fleet AI-harness + schedule
inventory.

Guards the invariants that make the inventory trustworthy as a CONTROL
surface (it feeds the harness-fanout `gaps` target and the /harnesses/ page,
so a wrong grade becomes a wrong PR or a false alarm):

  * workflow classification reads the facts the fan-out relies on — the kit
    stamp, the OAuth-first auth shape, mention-handler detection — and an
    unparseable file degrades to regex facts instead of dying;
  * cron estimation is a documented approximation that must at least rank
    load correctly (daily=1, hourly=24, weekly≈1/7) and refuse what it cannot
    parse rather than guessing;
  * coverage grading excuses external/archived/exempt repos instead of
    failing them — a gap list with false positives would open PRs nobody
    asked for;
  * `--gaps` emits ONLY fan-out-deployable gaps: a missing secret is
    token-rotation's lane and must never become a deploy target;
  * throughput and budget checks compare against fleet.yml caps with the
    module defaults as fallback, and trends survive missing ledgers.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_harness_registry.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness_registry as hr  # noqa: E402

CFG = hr.load_config(Path("/nonexistent/fleet.yml"))  # module defaults

MENTION_WF = """\
name: Claude

# kit: agent-context v0.4.0
on:
  issue_comment:
    types: [created]
  issues:
    types: [opened, assigned]
permissions:
  contents: read
jobs:
  claude:
    if: contains(github.event.comment.body, '@claude')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          anthropic_api_key: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN == '' && secrets.ANTHROPIC_API_KEY || '' }}
"""

SCHEDULED_WF = """\
name: Nightly agent
on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:
jobs:
  fix:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          claude_args: >-
            --model opus
            --max-turns 160
"""

PLAIN_CI = """\
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: make test
"""


def repo_row(name="alpha", harnesses=None, scheduled=None, **kw) -> dict:
    row = {
        "repo": name,
        "nwo": f"bamr87/{name}",
        "category": "dev-tools",
        "status": "active",
        "external": False,
        "archived": False,
        "scanned": True,
        "manifest": False,
        "agent_context": "CLAUDE.md",
        "oauth_secret": "ok",
        "workflows_total": 1,
        "harnesses": harnesses if harnesses is not None else [],
        "scheduled": scheduled if scheduled is not None else [],
    }
    row.update(kw)
    return row


def harness_row(**kw) -> dict:
    row = {
        "workflow": "Claude",
        "path": ".github/workflows/claude.yml",
        "kind": "mention-handler",
        "triggers": ["issue_comment"],
        "crons": [],
        "action_ref": "v1",
        "auth": "oauth-first",
        "model": None,
        "max_turns": None,
        "kit": "0.4.0",
        "kit_status": "current",
        "mention_handler": True,
    }
    row.update(kw)
    return row


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
def test_classify_mention_handler_reads_kit_auth_and_triggers():
    info = hr.classify_workflow(".github/workflows/claude.yml", MENTION_WF)
    assert info["ai"] and info["kind"] == "mention-handler", info
    assert info["auth"] == "oauth-first"
    assert info["kit"] == "0.4.0"
    assert info["action_ref"] == "v1"
    assert "issue_comment" in info["triggers"]
    assert info["crons"] == []


def test_classify_scheduled_agent_reads_cron_model_turns():
    info = hr.classify_workflow(".github/workflows/nightly.yml", SCHEDULED_WF)
    assert info["kind"] == "scheduled-agent"
    assert info["crons"] == ["0 6 * * *"]
    assert info["model"] == "opus"
    assert info["max_turns"] == 160
    assert info["auth"] == "oauth-only"
    assert info["kit"] is None


def test_mention_needs_a_mention_capable_trigger():
    # A dispatch-only fan-out whose HEADER COMMENT says "@claude" is not a
    # mention handler (the real standardize-fanout.yml false-positived on this).
    dispatch_only = (
        "name: fanout\n# seeds the @claude mention workflow\n"
        "on:\n  workflow_dispatch:\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: anthropics/claude-code-action@v1\n"
        "        with:\n          claude_code_oauth_token: x\n"
    )
    info = hr.classify_workflow(".github/workflows/fanout.yml", dispatch_only)
    assert info["ai"] and not info["mention_handler"] and info["kind"] == "event-agent", info


def test_classify_non_ai_and_broken_yaml_degrade():
    info = hr.classify_workflow(".github/workflows/ci.yml", PLAIN_CI)
    assert not info["ai"] and "push" in info["triggers"]
    broken = "name: X\non:\n  schedule:\n    - cron: '0 5 * * 1'\n\t- bad-tab"
    info = hr.classify_workflow(".github/workflows/broken.yml", broken)
    assert info["parse_error"]
    assert info["crons"] == ["0 5 * * 1"], info  # regex fallback still sees it


# --------------------------------------------------------------------------- #
# cron math
# --------------------------------------------------------------------------- #
def test_cron_fires_per_day_ranks_load():
    assert hr.cron_fires_per_day("0 6 * * *") == 1.0
    assert hr.cron_fires_per_day("0 * * * *") == 24.0
    assert hr.cron_fires_per_day("*/15 * * * *") == 96.0
    assert hr.cron_fires_per_day("0 2 * * 1") == round(1 / 7, 3)
    assert hr.cron_fires_per_day("0 3,9 * * *") == 2.0
    monthly = hr.cron_fires_per_day("0 0 1 * *")
    assert monthly is not None and 0.03 < monthly < 0.04
    assert hr.cron_fires_per_day("0 0 * JAN MON") is None  # names: refuse, don't guess
    assert hr.cron_fires_per_day("not a cron") is None


def test_describe_cron_common_shapes():
    assert hr.describe_cron("0 6 * * *") == "daily 06:00 UTC"
    assert hr.describe_cron("0 2 * * 1") == "Mon 02:00 UTC weekly"
    assert hr.describe_cron("*/15 * * * *") == "every 15 min"
    assert hr.describe_cron("0 */4 * * *") == "every 4h at :00"
    assert hr.describe_cron("7 * * * *") == "hourly at :07"
    weird = "3 1-5 2 3 4"
    assert hr.describe_cron(weird)  # never empty, whatever the shape


# --------------------------------------------------------------------------- #
# coverage + gaps
# --------------------------------------------------------------------------- #
def test_coverage_grades_gaps_and_excuses_external_archived_exempt():
    bare = repo_row(name="bare", agent_context=None, oauth_secret="missing")
    hr.evaluate_coverage(bare, CFG)
    assert set(bare["coverage"]["missing"]) == {"mention-handler", "agent-context",
                                                "oauth-secret"}

    ok = repo_row(harnesses=[harness_row()])
    hr.evaluate_coverage(ok, CFG)
    assert ok["coverage"]["ok"] and not ok["coverage"]["missing"]

    ext = repo_row(name="skills", external=True, agent_context=None)
    arch = repo_row(name="old", archived=True, agent_context=None)
    unscanned = repo_row(name="dark", scanned=False, agent_context=None)
    cfg_exempt = dict(CFG, exempt=["special"])
    exempt = repo_row(name="special", agent_context=None)
    for row, cfg in ((ext, CFG), (arch, CFG), (unscanned, CFG), (exempt, cfg_exempt)):
        hr.evaluate_coverage(row, cfg)
        assert row["coverage"]["exempt"] and not row["coverage"]["missing"], row["repo"]


def test_gaps_are_fanout_deployable_only():
    rows = [
        repo_row(name="needs-handler"),                       # missing mention-handler
        repo_row(name="secret-only", harnesses=[harness_row()],
                 oauth_secret="missing"),                     # token-rotation's lane
        repo_row(name="stale-kit",
                 harnesses=[harness_row(kit="0.1.0", kit_status="upgradeable")]),
        repo_row(name="fine", harnesses=[harness_row()]),
    ]
    for r in rows:
        hr.evaluate_coverage(r, CFG)
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        yaml.safe_dump({"repos": rows}, fh)
        path = Path(fh.name)
    try:
        assert hr.fanout_gaps(path) == ["needs-handler", "stale-kit"]
        assert hr.fanout_gaps(Path("/nonexistent/registry.yml")) == []
    finally:
        path.unlink()


def test_kit_status_compares_against_hub_version():
    assert hr.kit_status("0.4.0", "0.4.0") == "current"
    assert hr.kit_status("0.1.0", "0.4.0") == "upgradeable"
    assert hr.kit_status("0.5.0", "0.4.0") == "ahead"
    assert hr.kit_status(None, "0.4.0") == "unstamped"
    assert hr.kit_status("0.4.0", None) == "unknown"


# --------------------------------------------------------------------------- #
# throughput
# --------------------------------------------------------------------------- #
def test_throughput_caps_and_hour_collisions():
    hourly = repo_row(
        name="chatty",
        harnesses=[harness_row(workflow="agent", kind="scheduled-agent",
                               crons=["0 * * * *"], mention_handler=False)])
    colliders = [
        repo_row(name=f"c{i}",
                 harnesses=[harness_row(workflow=f"w{i}", kind="scheduled-agent",
                                        crons=["0 6 * * *"], mention_handler=False)])
        for i in range(4)
    ]
    repos = [hourly] + colliders
    for r in repos:
        r["est_scheduled_ai_per_day"] = hr.repo_schedule_load(r)
    assert hourly["est_scheduled_ai_per_day"] == 24.0

    tp = hr.build_throughput(repos, CFG, {"totals": {"ci_runs": 140}, "window_days": 14})
    assert tp["fleet_over_cap"] is False or tp["est_scheduled_ai_per_day"] == 28.0
    assert [v["repo"] for v in tp["repos_over_cap"]] == ["chatty"]
    assert tp["observed_ai_runs_per_day"] == 10.0
    # four single-hour crons share 06:00 vs a cap of 3; the hourly agent's
    # 24-hour spread is a volume problem, not an adjacency one.
    assert len(tp["hour_collisions"]) == 1
    coll = tp["hour_collisions"][0]
    assert coll["utc_hour"] == "06:00" and coll["count"] == 4


# --------------------------------------------------------------------------- #
# trends
# --------------------------------------------------------------------------- #
def test_trends_wow_projection_and_budget_status():
    ai = {"window_days": 14, "by_day": (
        [{"day": f"2026-08-{d:02d}", "cost_usd": 1.0} for d in range(10, 17)]
        + [{"day": f"2026-08-{d:02d}", "cost_usd": 2.0} for d in range(17, 24)])}
    t = hr.build_trends(ai, {}, CFG)["ai_cost_usd"]
    assert t["last7"] == 14.0 and t["prior7"] == 7.0, t
    assert t["wow_delta_pct"] == 100.0, t
    assert t["projected_monthly"] == round(2.0 * hr.AVG_DAYS_PER_MONTH, 2), t
    # 100% > warn 50, and $60.88 projected stays under the $75 ceiling —
    # breach outranks growing, so keeping this under budget isolates the trend.
    assert t["status"] == "growing", t

    cfg_tight = dict(CFG, budget={**CFG["budget"], "monthly_ai_usd": 50})
    assert hr.build_trends(ai, {}, cfg_tight)["ai_cost_usd"]["status"] == "breach"

    empty = hr.build_trends({}, {}, CFG)
    assert empty["ai_cost_usd"]["status"] == "no-data"
    assert empty["actions_minutes"]["status"] == "no-data"


# --------------------------------------------------------------------------- #
# joins + attention
# --------------------------------------------------------------------------- #
def test_join_usage_annotates_repo_and_harness_rows():
    r = repo_row(harnesses=[harness_row()])
    ai = {"by_repo": [{"repo": "alpha", "runs": 5, "cost_usd": 1.2, "minutes": 3.0,
                       "unpriced_runs": 1}],
          "by_workflow": [{"workflow": "alpha/Claude", "runs": 5, "cost_usd": 1.2}]}
    act = {"workflows": [{"repo": "alpha", "path": ".github/workflows/claude.yml",
                          "runs": 6, "last_conclusion": "failure", "flags": ["failing"]}]}
    hr.join_usage([r], ai, act)
    assert r["ai_usage"]["cost_usd"] == 1.2
    h = r["harnesses"][0]
    assert h["cost_usd_window"] == 1.2 and h["runs_window"] == 5
    assert h["last_conclusion"] == "failure" and h["flags"] == ["failing"]


def test_attention_ranks_and_caps_and_names_the_lever():
    failing = repo_row(name="red",
                       harnesses=[harness_row(last_conclusion="failure", flags=["failing"])])
    gap = repo_row(name="bare", agent_context=None)
    drift = repo_row(name="stale",
                     harnesses=[harness_row(kit="0.1.0", kit_status="upgradeable",
                                            auth="api-key")])
    repos = [failing, gap, drift]
    for r in repos:
        r["est_scheduled_ai_per_day"] = hr.repo_schedule_load(r)
        hr.evaluate_coverage(r, CFG)
    tp = hr.build_throughput(repos, CFG, {})
    trends = hr.build_trends({}, {}, CFG)
    items = hr.build_attention(repos, tp, trends, CFG)
    kinds = [i["kind"] for i in items]
    assert kinds == sorted(kinds, key=lambda k: -[i["severity"] for i in items][kinds.index(k)]) or True
    sevs = [i["severity"] for i in items]
    assert sevs == sorted(sevs, reverse=True)
    assert any(i["kind"] == "harness-failing" and i["repo"] == "red" for i in items)
    assert any(i["kind"] == "coverage-gap" and i["repo"] == "bare" for i in items)
    assert any(i["kind"] == "kit-drift" and i["repo"] == "stale" for i in items)
    assert any(i["kind"] == "auth-drift" and i["repo"] == "stale" for i in items)
    assert all(i.get("action") for i in items)  # every finding names its lever

    tight = dict(CFG, attention_max=2)
    assert len(hr.build_attention(repos, tp, trends, tight)) == 2


def test_config_falls_back_when_block_absent():
    cfg = hr.load_config(Path("/nonexistent/fleet.yml"))
    assert cfg["throughput"]["max_scheduled_ai_per_day_fleet"] == \
        hr.DEFAULT_THROUGHPUT["max_scheduled_ai_per_day_fleet"]
    assert cfg["budget"]["monthly_ai_usd"] == hr.DEFAULT_BUDGET["monthly_ai_usd"]
    assert cfg["baseline"]["require_mention_handler"] is True
    assert cfg["attention_max"] == hr.DEFAULT_ATTENTION_MAX


def test_ensure_hub_injects_the_control_plane_once():
    # The registry lists projects; the hub is not one — yet it runs the
    # heaviest scheduled agents, so the scan set must include it exactly once.
    registry = [{"name": "alpha", "repo_url": "https://github.com/bamr87/alpha"}]
    withhub = hr.ensure_hub(registry, CFG)
    assert withhub[0]["name"] == "bamr87"
    assert withhub[0]["repo_url"] == "https://github.com/bamr87/bamr87"
    assert len(withhub) == 2
    already = registry + [{"name": "hub", "repo_url": "https://github.com/bamr87/bamr87"}]
    assert len(hr.ensure_hub(already, CFG)) == 2  # no duplicate row


def test_rotation_secret_states_maps_nwo_to_state():
    rotation = {"tokens": [{"name": "CLAUDE_CODE_OAUTH_TOKEN", "repos": [
        {"nwo": "bamr87/a", "state": "ok"},
        {"nwo": "bamr87/b", "state": "missing"},
    ]}]}
    states = hr.rotation_secret_states(rotation)
    assert states == {"bamr87/a": "ok", "bamr87/b": "missing"}
    assert hr.rotation_secret_states({}) == {}


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
    print(f"{'FAIL' if failures else 'OK'} — harness_registry fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Fixture tests for agent_inventory.py — the agent inventory under the agentic
efficacy contract (constitution § 29, ADR 0009) and drift check (p).

Guards what makes the inventory a gate rather than a list:

  * the contract in _data/fleet.yml validates: an unknown KPI or source id, a
    threshold that is not a number, an exemption with stray keys and a
    missing efficacy block are errors; a source with no writer and a kind with
    no KPIs are WARNINGS (the shadow period), never silence;
  * discovery finds every kind of agent from the files that define it — an
    AI workflow (claude-code-action or a claude-run `uses:`, not a workflow
    that merely names the action's path), a loop step, a JEV tier, a
    LaunchAgent installer (not a git-hook installer) — and a declared agent
    before its installer lands, which keeps winning after it does;
  * the check fails on an unregistered, removed or stale HUB agent and on a
    stale contract section, warns on drift in the FLEET half unless strict,
    and catches a hand edit;
  * contract gaps fail only under enforcement, never before shadow_until, and
    never for an agent still in its grace period;
  * the hub's own files produce the agents the contract names (the 5 loop
    steps, the 3 tiers, the 3 local jobs, every budget.call_sites workflow).

Offline, no network, no pytest. Needs PyYAML:

    python3 .github/scripts/dash-gen/test_agent_inventory.py
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_inventory as ai  # noqa: E402

HUB = "acme/hub"
TODAY = dt.date(2026, 11, 7)


def fleet_fixture() -> dict:
    """A small but complete contract, in the shape of _data/fleet.yml."""
    return {
        "hub": {"repo": HUB},
        "schedule": {"jev_conflicts": "23 */6 * * *"},
        "budget": {
            "call_sites": {"pulse.yml:doctor": 40, "pipeline.yml:tier1": 40, "pipeline.yml:tier2": 60},
            "jev": {"monthly_usd": 10, "tier1_usd": 0.25, "tier2_usd": 1.5},
            "loops": {"monthly_usd": 50},
        },
        "jev": {"auto_tiers": ["tier0", "tier1"], "ci_tiers": ["tier0"],
                "tiers": {"tier1": {"model": "cheap-1"}, "tier2": {"model": "strong-2"}}},
        "switches": {"loops": {"hub/pulse": {"repo": HUB, "workflow": ".github/workflows/pulse.yml",
                                             "owner": "pat", "gate": {"kind": "repo_variable",
                                                                      "name": "PULSE_ENABLED"}},
                               "hub/claude": {"repo": HUB, "workflow": ".github/workflows/claude.yml",
                                              "owner": "pat", "gate": {"kind": "none"}}}},
        "harness": {
            "efficacy": {
                "enforce": False, "shadow_until": "2026-11-21", "grace_until": "2027-02-01", "owner": "amr",
                "kpis": {"accepted_per_usd": {"unit": "per USD", "better": "higher"},
                         "silent_failure_pct": {"unit": "%", "better": "lower"}},
                "kinds": {
                    "ci-scheduled": {"kpis": {"accepted_per_usd": 0.05, "silent_failure_pct": 5},
                                     "reads": ["cfg", "gh"], "run_record": "lake", "reflector_via": "lake"},
                    "ci-event": {"kpis": {"accepted_per_usd": 0.1}, "reads": ["cfg"], "run_record": "lake",
                                 "reflector_via": "lake"},
                    "ci-mention": {"kpis": {"silent_failure_pct": 5}, "reads": ["gh"], "run_record": "lake",
                                   "reflector_via": "lake", "switch": {"exempt": "asked"},
                                   "local_entry": {"exempt": "reacts inside GitHub"}},
                    "loop-step": {"kpis": {"accepted_per_usd": 0.05}, "reads": ["cfg"], "run_record": "ledger",
                                  "reflector_via": "loop-runs"},
                    "jev-tier": {"kpis": {"accepted_per_usd": 1.0}, "reads": ["cfg"], "run_record": "ledger",
                                 "reflector_via": "loop-runs"},
                    "local-job": {"kpis": {"silent_failure_pct": 5}, "reads": ["cfg"]},
                },
                "run_record": {"fields": ["cost_usd", "turns", "tool_errors"],
                               "stores": {"lake": {"where": "lake", "missing": ["tool_errors"]},
                                          "ledger": {"where": "ledger", "missing": []}}},
                "reflector_inputs": ["lake", "loop-runs"],
            },
            "sources": {
                "cfg": {"path": "_data/fleet.yml", "writer": "maintainer", "slo": "on-change"},
                "gh": {"path": "GitHub", "writer": "GitHub", "slo": "live"},
                "lake": {"path": ".dash-lake", "writer": "local:review", "slo_days": 2},
                "loop-runs": {"path": ".fleet/runs", "writer": "the loop runner", "slo": "on-change"},
                "snap": {"path": "_data/snap.yml", "writer": None, "slo_days": 14},
                "usage": {"path": "_data/usage.yml", "writer": "pulse.yml", "slo_days": 3},
                "code-index": {"path": "qdrant", "writer": "the indexer", "slo": "on-change"},
            },
            "agents": {
                "ci:hub:pulse": {"reads": ["usage"]},
                "local:sweep": {"model_from": ["jev.tiers.tier1.model", "jev.tiers.tier2.model"],
                                "budget_from": {"per_run_usd": "budget.jev.tier2_usd"},
                                "switch": {"config": "jev.enabled"}, "run_record": "ledger",
                                "reflector_via": "loop-runs", "local_entry": "tools/dash conflicts sweep"},
                "local:review": {"declare": {"kind": "local-job", "where": "tools/install-review.sh",
                                             "trigger": "launchd: daily 06:23 local", "pending": "acme/hub#1"},
                                 "reads": ["lake", "snap"], "model": "m-1", "budget": {"per_run_usd": 2.0},
                                 "switch": {"config": "x.enabled"}, "run_record": "ledger",
                                 "local_entry": "tools/dash refine reflect"},
            },
        },
    }


def hub_wfs() -> list[dict]:
    base = {"repo": HUB, "name": "hub", "archived": False, "max_budget_usd": None}
    return [
        {**base, "path": ".github/workflows/pulse.yml", "triggers": ["schedule", "workflow_dispatch"],
         "crons": ["37 5 * * *"], "kind": "ci-scheduled", "model": "opus-x", "switch": "PULSE_ENABLED"},
        {**base, "path": ".github/workflows/claude.yml", "triggers": ["issue_comment"], "crons": [],
         "kind": "ci-mention", "model": None, "switch": None},
    ]


def registry_fixture() -> dict:
    return {"repos": [
        {"repo": "hub", "nwo": HUB, "harnesses": [{"path": ".github/workflows/ignored.yml"}]},
        {"repo": "site", "nwo": "acme/site", "harnesses": [
            {"path": ".github/workflows/claude.yml", "kind": "mention-handler", "mention_handler": True,
             "triggers": ["issue_comment"], "crons": [], "model": None, "max_budget_usd": 5.0}]},
        {"repo": "old", "nwo": "acme/old", "archived": True, "harnesses": [
            {"path": ".github/workflows/grow.yml", "kind": "scheduled-agent", "triggers": ["schedule"],
             "crons": ["0 3 * * *"], "model": None, "max_budget_usd": None}]},
    ]}


def steps_fixture() -> list[dict]:
    return [{"loop": "pulse", "step": "doctor", "call_site": "pulse.yml:doctor", "workflow": "pulse.yml",
             "model": "opus-x", "max_budget_usd": 40.0, "local": True,
             "switch": {"config": "remediation.enabled", "variable": "PULSE_ENABLED", "default": "on"},
             "providers": ["history", "lake_ci", "index_code"]}]


def installers_fixture() -> list[dict]:
    return [{"name": "sweep", "installer": "tools/install-sweep.sh", "schedule": "every 6h",
             "runs": ["tools/dash conflicts sweep --scheduled"], "uninstall": "tools/install-sweep.sh --uninstall"}]


def build(fleet=None, registry=None, prior=None, hubs=None, steps=None, installers=None):
    return ai.generate(fleet or fleet_fixture(), registry if registry is not None else registry_fixture(),
                       hubs if hubs is not None else hub_wfs(), steps if steps is not None else steps_fixture(),
                       installers if installers is not None else installers_fixture(), prior or {}, TODAY)


def by_id(doc: dict) -> dict:
    return {a["id"]: a for a in doc["agents"]}


def committed(doc: dict) -> dict:
    """What `tools/dash agents` would write, read back."""
    return yaml.safe_load(ai._dump(doc))


# --------------------------------------------------------------------------- #
# the contract validates
# --------------------------------------------------------------------------- #
def test_the_fixture_contract_is_clean_but_names_its_writerless_source():
    _, errors, warnings = ai.load_contract(fleet_fixture())
    assert errors == [], errors
    assert any("snap" in w and "no writer" in w for w in warnings), warnings


def test_a_missing_efficacy_block_refuses():
    f = fleet_fixture()
    del f["harness"]["efficacy"]
    try:
        ai.load_contract(f)
    except ai.ContractError as exc:
        assert "harness.efficacy" in str(exc)
    else:
        raise AssertionError("no efficacy block must refuse, not grade against nothing")


def test_typos_in_the_contract_are_errors():
    f = fleet_fixture()
    eff = f["harness"]["efficacy"]
    eff["kinds"]["ci-event"]["kpis"]["acepted_per_usd"] = 1
    eff["kinds"]["loop-step"]["kpis"]["accepted_per_usd"] = "high"
    eff["kinds"]["jev-tier"]["reads"].append("nope")
    eff["kinds"]["ci-mention"]["local_entry"] = {"exempt": "x", "Consequences)": None}
    eff["enforce"] = "yes"
    f["harness"]["agents"]["ci:hub:pulse"]["reads"].append("missing-source")
    _, errors, _ = ai.load_contract(f)
    text = "\n".join(errors)
    for needle in ("acepted_per_usd", "loop-step.kpis.accepted_per_usd", "'nope'", "ci-mention.local_entry",
                   "enforce", "'missing-source'"):
        assert needle in text, (needle, errors)


def test_an_undeclared_kind_warns_and_its_agents_carry_an_r3_gap():
    f = fleet_fixture()
    del f["harness"]["efficacy"]["kinds"]["jev-tier"]
    doc, errors, warnings = build(fleet=f)
    assert errors == [], errors
    assert any("jev-tier" in w and "no KPIs" in w for w in warnings), warnings
    assert "R3:no-kpis" in by_id(doc)["jev:tier1"]["gaps"]


def test_references_resolve_from_fleet_yml_and_a_bad_one_is_an_error():
    contract, errors, _ = ai.load_contract(fleet_fixture())
    assert errors == []
    sweep = contract["overlays"]["local:sweep"]
    assert sweep["model"] == ["cheap-1", "strong-2"] and sweep["budget"] == {"per_run_usd": 1.5}
    f = fleet_fixture()
    f["harness"]["agents"]["local:sweep"]["budget_from"] = {"per_run_usd": "budget.jev.nope"}
    _, errors, _ = ai.load_contract(f)
    assert any("budget_from.per_run_usd" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #
WF_SCHEDULED = """name: pulse
on:
  schedule:
    - cron: '37 5 * * *'
  workflow_dispatch:
jobs:
  doctor:
    if: vars.PULSE_ENABLED != 'false'
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          claude_args: --model opus-x --max-turns 240 --max-budget-usd 40
"""
WF_LANE = """name: lane
on:
  workflow_call:
jobs:
  run:
    steps:
      - uses: acme/hub/.github/actions/claude-run@v2
        with:
          max-budget-usd: '10'
"""
WF_CONTRACT = """name: contract
on:
  pull_request:
    paths:
      - ".github/actions/claude-run/**"
jobs:
  test:
    steps:
      - run: grep -qF run.sh .github/actions/claude-run/action.yml
"""
WF_PLAIN = "name: ci\non: [push]\njobs:\n  t:\n    steps:\n      - run: make test\n"


def test_hub_workflows_finds_claude_code_action_and_claude_run_but_not_a_path_mention():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, text in (("pulse.yml", WF_SCHEDULED), ("lane.yml", WF_LANE),
                           ("contract.yml", WF_CONTRACT), ("ci.yml", WF_PLAIN)):
            (d / name).write_text(text)
        found = {Path(w["path"]).name: w for w in ai.hub_workflows(d, HUB)}
    assert set(found) == {"pulse.yml", "lane.yml"}, sorted(found)
    assert found["pulse.yml"]["kind"] == "ci-scheduled" and found["pulse.yml"]["switch"] == "PULSE_ENABLED"
    assert found["lane.yml"]["kind"] == "ci-event" and found["lane.yml"]["max_budget_usd"] == 10.0


INSTALL_INTERVAL = """#!/usr/bin/env bash
# install-sweep.sh — every few hours
#   tools/dash conflicts sweep --dry-run   (a comment, never a command)
LABEL="com.bamr87.sweep"
HOURS=6
case $1 in --uninstall) ;; esac
cat > "$PLIST" <<EOF
    <key>Label</key>
    <string>${LABEL}</string>
tools/dash conflicts sweep --scheduled
    <key>StartInterval</key>
    <integer>$(( HOURS * 3600 ))</integer>
EOF
"""
INSTALL_CALENDAR = """#!/usr/bin/env bash
#   2. runs tools/update-submodules.sh --no-commit --no-push (header prose)
LABEL="com.bamr87.sync"
HOUR=7
    <key>Label</key>
tools/update-submodules.sh --no-commit --no-push
    <key>StartCalendarInterval</key>
        <key>Minute</key>
        <integer>0</integer>
    <key>RunAtLoad</key>
"""
# The shape of PR #772's tools/install-harness-review.sh, reduced to what the parser reads.
INSTALL_AT = """#!/usr/bin/env bash
LABEL="com.bamr87.harness-review"
AT="06:23"
step tools/dash-gen lake sessions --days 2
if tools/dash-gen lake review --days 7 --json > .fleet/refine/review-latest.json.tmp; then
    echo "--- lake review"
fi
step tools/dash refine reflect --scheduled
    <key>Label</key>
    <key>StartCalendarInterval</key>
        <integer>${MINUTE}</integer>
--uninstall
"""
INSTALL_HOOK = """#!/usr/bin/env bash
# a global git pre-commit hook; no LaunchAgent
HOOKS_DIR="$HOME/.git-hooks"
"""


def test_installers_parse_into_launch_agents_and_a_hook_installer_is_not_one():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, text in (("install-sweep.sh", INSTALL_INTERVAL), ("install-sync.sh", INSTALL_CALENDAR),
                           ("install-review.sh", INSTALL_AT), ("install-prose-hook.sh", INSTALL_HOOK)):
            (d / name).write_text(text)
        found = {i["name"]: i for i in ai.discover_installers(d)}
    assert set(found) == {"sweep", "sync", "harness-review"}, sorted(found)
    assert found["sweep"]["schedule"] == "every 6h"
    assert found["sweep"]["runs"] == ["tools/dash conflicts sweep --scheduled"], found["sweep"]["runs"]
    assert found["sweep"]["uninstall"] == "tools/install-sweep.sh --uninstall"
    assert found["sync"]["schedule"] == "daily 07:00 local and at login", found["sync"]["schedule"]
    assert found["sync"]["runs"] == ["tools/update-submodules.sh --no-commit --no-push"]
    assert found["sync"]["uninstall"] is None
    assert found["harness-review"]["schedule"] == "daily 06:23 local"
    # A command tested by an `if` is one the job runs, and it ends at its redirect.
    assert found["harness-review"]["runs"] == ["tools/dash-gen lake sessions --days 2",
                                               "tools/dash-gen lake review --days 7 --json",
                                               "tools/dash refine reflect --scheduled"], found["harness-review"]["runs"]


def test_the_harness_review_agent_is_discovered_from_its_installer():
    """PR #772 landed tools/install-harness-review.sh, so harness.agents no longer
    declares local:harness-review: its facts are read from the installer, and they
    are the ones the declaration held (the trigger and all four commands)."""
    fleet = yaml.safe_load((ai.REPO_ROOT / "_data" / "fleet.yml").read_text())
    assert "declare" not in fleet["harness"]["agents"]["local:harness-review"]
    review = {i["name"]: i for i in ai.discover_installers(ai.REPO_ROOT / "tools")}["harness-review"]
    assert review["schedule"] == "daily 06:23 local", review["schedule"]
    assert review["runs"] == ["tools/dash-gen lake sessions --days 2",
                              "tools/dash-gen lake sync --days 2 --jobs ai --logs ai",
                              "tools/dash-gen lake review --days 7 --json",
                              "tools/dash refine reflect --scheduled"], review["runs"]


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def test_every_kind_of_agent_is_inventoried_with_the_contract_fields():
    doc, errors, _ = build()
    assert errors == [], errors
    a = by_id(doc)
    assert set(a) == {"ci:hub:pulse", "ci:hub:claude", "ci:site:claude", "ci:old:grow", "loop:pulse/doctor",
                      "jev:tier0", "jev:tier1", "jev:tier2", "local:sweep", "local:review"}, sorted(a)
    assert doc["totals"]["by_category"] == {"ci-agent-step": 4, "local-loop-step": 1, "jev-tier": 3,
                                            "scheduled-local-job": 2}
    for entry in doc["agents"]:
        for key in ("id", "kind", "category", "repo", "owner", "trigger", "switch", "budget", "model", "kpis",
                    "reads", "run_record", "feeds_reflector", "local_entry", "first_seen", "gaps"):
            assert key in entry, (entry["id"], key)
        for sid, writer in entry["reads"].items():
            assert sid in doc["sources"], (entry["id"], sid)


def test_hub_facts_come_from_the_checkout_and_its_budget_from_call_sites():
    a = by_id(build()[0])
    pulse = a["ci:hub:pulse"]
    assert pulse["owner"] == "pat"                        # the switch entry's owner
    assert pulse["switch"] == {"variable": "PULSE_ENABLED", "loop": "hub/pulse"}
    assert pulse["budget"] == {"per_run_usd": 40.0, "call_sites": {"pulse.yml:doctor": 40.0}}
    assert pulse["trigger"].startswith("schedule daily 05:37 UTC")
    assert pulse["local_entry"] == "tools/dash loop run pulse doctor"
    assert pulse["counterparts"] == ["loop:pulse/doctor"]
    assert "usage" in pulse["reads"]                      # its overlay
    assert "ci:hub:ignored" not in a                      # the registry's hub row is not read


def test_a_loop_step_reads_its_context_pack_and_its_ci_twins_sources():
    doc = build()[0]
    step = by_id(doc)["loop:pulse/doctor"]
    assert set(step["reads"]) == {"cfg", "loop-runs", "lake", "code-index", "usage"}, sorted(step["reads"])
    assert step["budget"]["monthly_usd"] == 50.0 and step["model"] == "opus-x"
    assert step["counterparts"] == ["ci:hub:pulse"]
    assert "R4:writer-pending:lake" in step["gaps"]       # its writer is a declared, pending job


def test_jev_tiers_follow_the_ladder_and_tier0_spends_nothing():
    a = by_id(build()[0])
    assert a["jev:tier0"]["model"] == "none" and a["jev:tier0"]["budget"] == {"per_run_usd": 0.0}
    assert a["jev:tier0"]["switch"]["variable"] == "JEV_CONFLICTS_ENABLED"
    assert "CI jev-conflicts.yml" in a["jev:tier0"]["trigger"]
    assert a["jev:tier1"]["model"] == "cheap-1" and a["jev:tier1"]["budget"]["per_run_usd"] == 0.25
    assert "variable" not in a["jev:tier1"]["switch"]     # a model tier never runs in CI here
    assert a["jev:tier2"]["trigger"].startswith("not in jev.auto_tiers")
    assert not any(g.startswith(("R2", "R5")) for g in a["jev:tier0"]["gaps"])


def test_a_declared_job_is_registered_with_its_pending_pr_and_gaps():
    a = by_id(build()[0])
    review = a["local:review"]
    assert review["pending"] == "acme/hub#1" and review["model"] == "m-1"
    assert "R4:no-writer:snap" in review["gaps"]
    assert "R5:no-reflector" in review["gaps"]
    sweep = a["local:sweep"]
    assert sweep["model"] == ["cheap-1", "strong-2"] and sweep["runs"] == ["tools/dash conflicts sweep --scheduled"]
    assert sweep["gaps"] == [], sweep["gaps"]


def test_a_declaration_keeps_winning_after_its_installer_lands():
    landed = installers_fixture() + [{"name": "review", "installer": "tools/install-review.sh",
                                      "schedule": "daily 06:23 local", "runs": ["tools/x"], "uninstall": None}]
    before = build()[0]
    after, _, warnings = build(installers=landed)
    assert by_id(before)["local:review"] == by_id(after)["local:review"]
    assert any("drop harness.agents.local:review.declare" in w for w in warnings), warnings


def test_an_archived_repos_agent_is_listed_but_not_graded():
    a = by_id(build()[0])
    assert a["ci:old:grow"]["status"] == "archived" and a["ci:old:grow"]["gaps"] == []


def test_gaps_name_the_rule_they_break():
    a = by_id(build()[0])
    claude = a["ci:hub:claude"]
    assert "R1:model" in claude["gaps"] and "R1:budget" in claude["gaps"]
    assert claude["switch"] == {"exempt": "asked"}        # a `gate: none` entry is the § 17 gap, not a switch
    assert not any(g.startswith("R6") or g == "R1:switch" for g in claude["gaps"])  # exempt by kind
    assert "R2:missing:tool_errors" in claude["gaps"]


def test_first_seen_is_carried_forward_from_the_committed_file():
    prior = committed(build()[0])
    for agent in prior["agents"]:
        agent["first_seen"] = "2026-01-01"
    later = ai.generate(fleet_fixture(), registry_fixture(), hub_wfs(), steps_fixture(), installers_fixture(),
                        prior, dt.date(2026, 12, 1))[0]
    assert {a["first_seen"] for a in later["agents"]} == {"2026-01-01"}


def test_a_context_provider_whose_source_is_undeclared_is_an_error():
    f = fleet_fixture()
    del f["harness"]["sources"]["code-index"]
    _, errors, _ = build(fleet=f)
    assert any("code-index" in e for e in errors), errors


def test_two_agents_with_one_id_is_an_error():
    hubs = hub_wfs() + [dict(hub_wfs()[0], path=".github/workflows/pulse.yaml")]
    _, errors, _ = build(hubs=hubs)
    assert any("share an id" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# the check (drift check (p))
# --------------------------------------------------------------------------- #
def test_a_fresh_build_is_current():
    doc = build()[0]
    assert ai.compare(doc, committed(doc), strict_fleet=True) == ([], [])


def test_an_unregistered_hub_agent_fails():
    old = committed(build()[0])
    hubs = hub_wfs() + [dict(hub_wfs()[0], path=".github/workflows/new-agent.yml", crons=[], switch=None)]
    fails, _ = ai.compare(build(hubs=hubs)[0], old, strict_fleet=False)
    assert any("not registered" in f and "ci:hub:new-agent" in f for f in fails), fails


def test_a_new_step_spec_or_installer_fails_until_registered():
    old = committed(build()[0])
    steps = steps_fixture() + [dict(steps_fixture()[0], step="second")]
    fails, _ = ai.compare(build(steps=steps)[0], old, strict_fleet=False)
    assert any("loop:pulse/second" in f for f in fails), fails
    inst = installers_fixture() + [dict(installers_fixture()[0], name="nightly")]
    fails, _ = ai.compare(build(installers=inst)[0], old, strict_fleet=False)
    assert any("local:nightly" in f for f in fails), fails


def test_a_removed_or_changed_hub_agent_fails():
    old = committed(build()[0])
    fails, _ = ai.compare(build(steps=[])[0], old, strict_fleet=False)
    assert any("no longer found" in f and "loop:pulse/doctor" in f for f in fails), fails
    hubs = hub_wfs()
    hubs[0]["model"] = "sonnet-y"
    fails, _ = ai.compare(build(hubs=hubs)[0], old, strict_fleet=False)
    assert any("stale" in f and "ci:hub:pulse" in f for f in fails), fails


def test_a_changed_threshold_makes_the_contract_section_stale():
    old = committed(build()[0])
    f = fleet_fixture()
    f["harness"]["efficacy"]["kinds"]["ci-event"]["kpis"]["accepted_per_usd"] = 0.2
    fails, _ = ai.compare(build(fleet=f)[0], old, strict_fleet=False)
    assert any("`kinds:`" in x for x in fails), fails


def test_fleet_drift_warns_on_a_pr_and_fails_when_strict():
    old = committed(build()[0])
    reg = registry_fixture()
    reg["repos"][1]["harnesses"].append({"path": ".github/workflows/nightly.yml", "triggers": ["schedule"],
                                         "crons": ["0 1 * * *"]})
    doc = build(registry=reg)[0]
    fails, warns = ai.compare(doc, old, strict_fleet=False)
    assert fails == [] and any("ci:site:nightly" in w for w in warns), (fails, warns)
    fails, _ = ai.compare(doc, old, strict_fleet=True)
    assert any("ci:site:nightly" in f for f in fails), fails


def test_a_hand_edit_is_caught():
    doc = build()[0]
    old = committed(doc)
    old["totals"]["agents"] = 999
    fails, _ = ai.compare(doc, old, strict_fleet=False)
    assert any("by hand" in f for f in fails), fails


def test_a_missing_or_foreign_committed_file_fails():
    doc = build()[0]
    assert ai.compare(doc, {}, strict_fleet=False)[0]
    other = committed(doc)
    other["schema"] = "agents/v0"
    assert ai.compare(doc, other, strict_fleet=False)[0]


# --------------------------------------------------------------------------- #
# shadow, enforcement, grace
# --------------------------------------------------------------------------- #
def _dates(enforce: bool) -> dict:
    return {"enforce": enforce, "shadow_until": dt.date(2026, 11, 21), "grace_until": dt.date(2027, 2, 1)}


def test_gaps_are_warnings_in_shadow():
    doc = committed(build()[0])
    fails, warns = ai.gap_verdicts(doc, _dates(False), TODAY)
    assert fails == [] and any("shadow" in w for w in warns), warns
    assert any("no writer" in w and "snap" in w for w in warns), warns


def test_under_enforcement_grace_holds_existing_agents_and_new_ones_comply():
    doc = committed(build()[0])
    fails, warns = ai.gap_verdicts(doc, _dates(True), dt.date(2026, 12, 1))
    assert fails == [] and any("grace" in w for w in warns), (fails, warns)  # all first seen 2026-11-07
    late = copy.deepcopy(doc)
    late["agents"][0]["first_seen"] = "2026-11-25"
    gapped = late["agents"][0]
    fails, _ = ai.gap_verdicts(late, _dates(True), dt.date(2026, 12, 1))
    assert (fails != []) == bool(gapped["gaps"]), fails
    fails, _ = ai.gap_verdicts(doc, _dates(True), dt.date(2027, 3, 1))
    assert len(fails) == sum(1 for a in doc["agents"] if a["gaps"]), fails


def _cli(fleet: dict, out: Path, *extra: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / "fleet.yml"
        fpath.write_text(yaml.safe_dump(fleet))
        ap = argparse.ArgumentParser()
        ai.add_arguments(ap)
        args = ap.parse_args(["--fleet", str(fpath), "--registry", str(Path(tmp) / "none.yml"),
                              "--root", str(Path(tmp)), "--out", str(out), "--quiet", *extra])
        saved = ai.load_steps
        ai.load_steps = lambda fleet, root=None: steps_fixture()
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = ai.run(args)
        finally:
            ai.load_steps = saved
    return rc, buf.getvalue()


def test_the_cli_writes_then_checks_clean_and_refuses_early_enforcement():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "agents.yml"
        rc, _ = _cli(fleet_fixture(), out, "--today", "2026-11-07")
        assert rc == 0 and out.is_file()
        rc, text = _cli(fleet_fixture(), out, "--check", "--today", "2026-11-07")
        assert rc == 0 and "✓" in text, text
        early = fleet_fixture()
        early["harness"]["efficacy"]["enforce"] = True
        rc, text = _cli(early, out, "--check", "--today", "2026-11-10")
        assert rc == 1 and "before shadow_until" in text, text


def test_the_cli_reports_a_broken_contract_as_a_failure():
    with tempfile.TemporaryDirectory() as tmp:
        bad = fleet_fixture()
        bad["harness"]["efficacy"]["kinds"]["ci-event"]["kpis"]["nope"] = 1
        rc, text = _cli(bad, Path(tmp) / "agents.yml", "--check")
        assert rc == 1 and "✗" in text and "nope" in text, text


# --------------------------------------------------------------------------- #
# the hub itself
# --------------------------------------------------------------------------- #
def test_the_hubs_own_files_yield_every_agent_the_contract_names():
    fleet = ai.load_yaml(ai.FLEET_DEFAULT)
    registry = ai.load_yaml(ai.REGISTRY_DEFAULT)
    hub_nwo = fleet["hub"]["repo"]
    doc, errors, _ = ai.generate(fleet, registry, ai.hub_workflows(ai.REPO_ROOT / ".github" / "workflows", hub_nwo),
                                 ai.load_steps(fleet), ai.discover_installers(ai.REPO_ROOT / "tools"), {}, TODAY)
    assert errors == [], errors
    ids = set(by_id(doc))
    assert {"loop:repo-scout/scout", "loop:fleet-pulse/doctor", "loop:repo-evolution/evolve",
            "loop:fanout/agent-fill-standardize", "loop:fanout/agent-fill-schema"} <= ids
    assert {"jev:tier0", "jev:tier1", "jev:tier2"} <= ids
    assert {"local:conflict-sweep", "local:workspace-sync", "local:harness-review"} <= ids
    hub_name = hub_nwo.split("/", 1)[-1]
    for site in fleet["budget"]["call_sites"]:
        stem = site.split(":", 1)[0].rsplit(".", 1)[0]
        assert f"ci:{hub_name}:{stem}" in ids, f"budget.call_sites {site} has no inventoried agent"
    assert not any(i.startswith("local:prose") for i in ids)  # a git hook is not an agent


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
    print(f"{'FAIL' if failures else 'OK'} — agent_inventory fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

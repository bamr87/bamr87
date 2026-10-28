#!/usr/bin/env python3
"""
Fixture tests for the hub's schedule contract — three placement rules, each
one a sensor for a failure the fleet has already paid for (2026-09 review,
docs/WORKFLOW-OPTIMIZATION.md):

  * every hub workflow with a `schedule:` is declared in _data/fleet.yml
    `schedule:` with the SAME cron, and every declared entry has a workflow —
    update_submodules said "weekly" in the contract and ran daily for months;
  * no hub cron fires on the hour — GitHub delays and drops :00 schedules,
    and 06:00 was where four AI crons collided on one OAuth rate limit;
  * every SCHEDULED workflow that runs claude-code-action carries a
    `vars.<NAME>_ENABLED` kill switch, and that switch never blocks a manual
    dispatch (the loop must stay testable while it is off).

Deliberately dependency-light — reads the workflow files and fleet.yml with
PyYAML only:

    python3 .github/scripts/dash-gen/test_schedule.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
FLEET = REPO_ROOT / "_data" / "fleet.yml"

# workflow file stem → fleet.yml schedule key: the stem with underscores
# (workflow_atlas.schedule_key_for, which the scaffold writes), plus the one
# irregular name kept because token-rotation.yml and docs/TOKEN-ROTATION.md
# already read it. This was a hand-kept table of every scheduled workflow.
KEY_OVERRIDES = {"token-rotation": "rotate_tokens"}


def key_for(stem: str) -> str:
    return KEY_OVERRIDES.get(stem, re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_"))


SWITCH_RX = re.compile(r"vars\.([A-Z][A-Z0-9_]*_ENABLED)\b")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def scheduled_workflows() -> dict[str, list[str]]:
    """{stem: [cron, ...]} for every hub workflow that carries a schedule."""
    out: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = _load(path)
        on = doc.get(True) or doc.get("on") or {}
        if not isinstance(on, dict) or "schedule" not in on:
            continue
        out[path.stem] = [str(entry["cron"]) for entry in on["schedule"] if isinstance(entry, dict)]
    return out


def declared() -> dict[str, str]:
    return {k: str(v) for k, v in (_load(FLEET).get("schedule") or {}).items()}


def test_every_scheduled_workflow_is_declared_with_the_same_cron():
    contract = declared()
    for stem, crons in scheduled_workflows().items():
        key = key_for(stem)
        assert key in contract, f"{stem}.yml is scheduled but fleet.yml schedule: has no `{key}`"
        assert len(crons) == 1, f"{stem}.yml carries {len(crons)} crons; the contract declares one"
        assert crons[0] == contract[key], f"{stem}.yml runs '{crons[0]}' but fleet.yml says '{contract[key]}'"


def test_every_declared_schedule_has_a_workflow():
    stems = {key_for(s) for s in scheduled_workflows()}
    for key in declared():
        assert key in stems, f"fleet.yml schedule.{key} names no scheduled workflow"


def test_hub_crons_never_fire_on_the_hour():
    for stem, crons in scheduled_workflows().items():
        for cron in crons:
            minute = cron.split()[0]
            assert minute not in ("0", "00", "*"), f"{stem}.yml fires on the hour: '{cron}'"


def test_scheduled_agents_carry_a_kill_switch_that_spares_manual_runs():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        if "claude-code-action" not in text or path.stem not in scheduled_workflows():
            continue
        switches = set(SWITCH_RX.findall(text))
        assert switches, f"{path.name} is a scheduled agent with no vars.*_ENABLED switch"
        assert "github.event_name != 'schedule'" in text, \
            f"{path.name}: the switch must let a workflow_dispatch through"


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
    print("OK — schedule contract tests" if not failures else f"FAIL — {failures} schedule test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

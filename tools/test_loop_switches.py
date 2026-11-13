#!/usr/bin/env python3
"""Validate `_data/fleet.yml` `switches:` (constitution § 17, HUB-057 / FR54).

Shape checks plus coverage: every hub workflow that runs on a schedule or reads
a `vars.*_ENABLED` switch must have an entry in `switches.loops`, and every
`repo_variable` gate on a hub entry must name a variable that workflow reads.
Offline; reads no live variables and no secrets.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FLEET = ROOT / "_data" / "fleet.yml"
WORKFLOWS = ROOT / ".github" / "workflows"
HUB = "bamr87/bamr87"

STATES = {"on", "off", "unverified"}
KINDS = {"repo_variable", "env", "fleet_config", "none", "planned"}
SEMANTICS = {"opt_in", "opt_out"}
LOOP_KEYS = {"repo", "workflow", "group", "owner", "scope", "gate", "default", "state", "verified", "flip"}


def load() -> dict:
    return yaml.safe_load(FLEET.read_text())["switches"]


class LoopSwitchesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sw = load()

    def test_schema_marker_and_levels(self) -> None:
        self.assertEqual(self.sw["schema"], "switches/v1")
        for level in ("global", "groups", "loops", "repos"):
            self.assertIn(level, self.sw)
        self.assertIn(self.sw["global"]["state"], STATES)

    def test_every_loop_entry_is_well_formed(self) -> None:
        groups = set(self.sw["groups"])
        for key, e in self.sw["loops"].items():
            with self.subTest(loop=key):
                self.assertLessEqual(LOOP_KEYS, set(e), f"missing {LOOP_KEYS - set(e)}")
                self.assertIn(e["group"], groups)
                self.assertIn(e["state"], STATES)
                self.assertIn(e["default"], {"on", "off"})
                self.assertIn(e["gate"]["kind"], KINDS)
                if e["gate"]["kind"] == "repo_variable":
                    self.assertRegex(e["gate"]["name"], r"^[A-Z][A-Z0-9_]*_ENABLED$")
                    self.assertIn(e["gate"]["semantics"], SEMANTICS)
                    self.assertEqual(e["default"], "off" if e["gate"]["semantics"] == "opt_in" else "on")
                if e["state"] != "unverified" and e["gate"]["kind"] == "repo_variable":
                    self.assertTrue(e.get("set_at"), "a verified state records when it was set")

    def test_every_scheduled_or_switched_hub_workflow_has_an_entry(self) -> None:
        listed = {e["workflow"] for e in self.sw["loops"].values() if e["repo"] == HUB}
        for wf in sorted(WORKFLOWS.glob("*.yml")):
            text = wf.read_text()
            if re.search(r"^\s*-\s*cron:", text, re.M) or re.search(r"vars\.[A-Z_]+_ENABLED", text):
                with self.subTest(workflow=wf.name):
                    self.assertIn(f".github/workflows/{wf.name}", listed)

    def test_hub_variable_gates_match_their_workflow(self) -> None:
        for key, e in self.sw["loops"].items():
            if e["repo"] != HUB or e["gate"]["kind"] != "repo_variable":
                continue
            with self.subTest(loop=key):
                text = (ROOT / e["workflow"]).read_text()
                name = e["gate"]["name"]
                if re.search(r"^\s*uses:\s*\S*\.github/workflows/ai-lane\.ya?ml@", text, re.M):
                    # an ai-lane caller gates through the lane's `switch` input: the reusable
                    # lane reads vars[inputs.switch] (and a dispatch bypasses it), so the
                    # caller names the variable instead of spelling `vars.<NAME>`
                    self.assertRegex(text, rf"^\s*switch:\s*{name}\s*(#.*)?$", "ai-lane caller's switch input")
                    lane = (WORKFLOWS / "ai-lane.yml").read_text()
                    self.assertIn("vars[inputs.switch]", lane)
                else:
                    self.assertIn(f"vars.{name}", text)

    def test_no_secret_values(self) -> None:
        blob = yaml.safe_dump(self.sw)
        self.assertNotRegex(blob, r"(sk-ant-|ghp_|github_pat_)")


if __name__ == "__main__":
    sys.exit(unittest.main())

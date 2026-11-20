#!/usr/bin/env python3
"""Tests for the fleet assistant kit (templates/assistant/).

The kit README's file table and VERSION's `files:` list are the kit's contract with the fan-out: both are
held to the tree here. Where Node is installed the kit's own contract tests (tests/contract.test.mjs) run
too, so the hub's CI, which discovers templates/*/test_*.py, runs them on every pull request.

    python3 templates/assistant/test_assistant_kit.py

Stdlib only; exits non-zero when a check fails.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent
HUB = KIT.parents[1]


class Kit(unittest.TestCase):
    def test_version_lists_every_file_and_every_listed_file_exists(self):
        text = (KIT / "VERSION").read_text()
        block = re.search(r"^files: (.*?)^spec:", text, re.S | re.M).group(1)
        listed = {f.strip() for f in block.replace("\n", " ").split(",") if f.strip()}
        for rel in listed:
            self.assertTrue((KIT / rel).is_file(), f"VERSION lists {rel}, which is not in the kit")
        on_disk = {str(p.relative_to(KIT)) for p in KIT.rglob("*") if p.is_file() and "archive" not in p.parts}
        self.assertEqual(on_disk - listed - {"VERSION", "README.md", "package.json"}, set(),
                         "a file in the kit that VERSION does not list")

    def test_the_readme_table_names_only_files_that_exist(self):
        readme = (KIT / "README.md").read_text()
        table = readme.split("## How it works")[0]
        for rel in re.findall(r"`([A-Za-z0-9_./-]+\.[a-z]+)`", table):
            if rel.startswith(("fleet-assist", "adapters/", "tests/", "test_", "package")):
                self.assertTrue((KIT / rel).is_file(), f"README names {rel}")
        for adapter in (KIT / "adapters").iterdir():
            self.assertIn(f"`adapters/{adapter.name}`", table, f"README does not describe adapters/{adapter.name}")

    def test_every_adapter_the_planner_names_is_in_the_kit(self):
        sys.path.insert(0, str(HUB / "tools"))
        from fleetcore import assist  # noqa: E402
        for family, _needle, adapter, _seeded, _dev in assist.ADAPTERS:
            self.assertTrue((KIT / adapter).is_file(), f"{family}: {adapter}")

    def test_the_fan_out_seeds_what_the_kit_ships(self):
        fanout = (HUB / "tools" / "fanout.sh").read_text()
        seed = fanout[fanout.index("seed_assist() {"):fanout.index("feedback_ensure_labels() {")]
        for adapter in (KIT / "adapters").iterdir():
            self.assertIn(f"adapters/{adapter.name}", seed, f"seed_assist never seeds adapters/{adapter.name}")
        self.assertIn('"$kit/fleet-assist.js"', seed)
        self.assertIn('"$AST_VERSION" js', seed, "the vendored payload is stamped with THIS kit's version")

    def test_the_drift_check_holds_vendored_copies_to_the_hubs(self):
        self.assertIn("templates/assistant/fleet-assist.js|fleet-assist.js|", (HUB / "tools" / "check-drift.sh").read_text())

    @unittest.skipUnless(shutil.which("node"), "node is not installed: the kit's contract tests did not run")
    def test_the_contract_tests_pass(self):
        run = subprocess.run(["node", "--test", "tests/contract.test.mjs"], cwd=KIT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=1)

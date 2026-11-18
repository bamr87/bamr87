#!/usr/bin/env python3
"""Fixture tests for machine_api — no network."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

import machine_api as m


class MachineApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "_data"
        self.out = self.root / "_site"
        self.data.mkdir()
        self.out.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, payload: dict) -> None:
        (self.data / name).write_text(yaml.safe_dump(payload), encoding="utf-8")

    def test_degraded_without_inputs(self) -> None:
        written = m.emit(self.out, self.data)
        index = json.loads(written["index"].read_text())
        fleet = json.loads(written["fleet"].read_text())
        self.assertEqual(index["schema_version"], m.SCHEMA_VERSION)
        self.assertEqual(fleet["status"], "degraded")
        self.assertTrue(written["llms"].is_file())
        self.assertIn("api/v1/index.json", written["llms"].read_text())
        self.assertIn("docs/agentic-patterns/patterns.json", written["llms"].read_text())

    def test_fleet_inbox_order_and_index_hint(self) -> None:
        self._write(
            "fleet_triage.yml",
            {
                "generated_at": "2026-09-12 06:44 UTC",
                "repos_scanned": 2,
                "totals": {"open_issues": 3, "repos_red": 1, "failing_workflows": 1},
                "inbox": [
                    {
                        "kind": "workflow",
                        "repo": "demo",
                        "nwo": "bamr87/demo",
                        "title": "CI",
                        "why": "latest run failure",
                        "url": "https://example.test/1",
                        "priority": 90,
                        "age_days": None,
                    },
                    {
                        "kind": "issue",
                        "repo": "demo",
                        "nwo": "bamr87/demo",
                        "title": "bug",
                        "why": "stale",
                        "url": "https://example.test/2",
                        "priority": 40,
                        "age_days": 40,
                    },
                ],
                "by_repo": [
                    {
                        "name": "demo",
                        "nwo": "bamr87/demo",
                        "repo_url": "https://github.com/bamr87/demo",
                        "attention": {"level": "red", "reasons": ["CI failing"]},
                        "issues": {"open": 1},
                        "prs": {"open": 0},
                        "workflows": {"failing": [{"workflow": "CI"}]},
                    }
                ],
            },
        )
        self._write(
            "harness_health.yml",
            {
                "generated_at": "2026-09-12 06:47 UTC",
                "scorecard": {"completion_rate_pct": {"value": 88.1, "status": "ok"}},
                "trip_wires": [{"id": "cost-spike", "tripped": True, "summary": "spike"}],
            },
        )
        self._write(
            "issue_pipeline.yml",
            {
                "generated_at": "2026-09-12 08:18 UTC",
                "enabled": True,
                "repos_scanned": 2,
                "totals": {"open_issues": 3, "stages": {"blocked": 1}},
                "caps": {"intake": {"max_issues": 8}},
            },
        )
        # ephemeral health list shape used by monitor Liquid
        (self.data / "project_health.yml").write_text(
            yaml.safe_dump(
                [
                    {
                        "name": "demo",
                        "repo_url": "https://github.com/bamr87/demo",
                        "attention": {"level": "red", "reasons": ["CI failing"]},
                        "attention_rank": 0,
                        "ci": {"last": "failure", "pass_rate": 0},
                        "issues": {"open": 1, "bugs": 0, "stale": 0},
                        "prs": {"open": 0, "stale": 0},
                        "activity": {"last_commit_days": 1, "commits_30d": 2},
                        "security": {"alerts": 0},
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.data / "project_health_meta.yml").write_text(
            yaml.safe_dump({"generated_at": "2026-09-12 15:18 UTC"}),
            encoding="utf-8",
        )

        written = m.emit(self.out, self.data)
        fleet = json.loads(written["fleet"].read_text())
        health = json.loads(written["health"].read_text())
        harness = json.loads(written["harness"].read_text())
        issues = json.loads(written["issues"].read_text())
        index = json.loads(written["index"].read_text())

        self.assertEqual(fleet["status"], "ok")
        self.assertEqual(fleet["inbox"][0]["title"], "CI")
        self.assertNotIn("clears", fleet["inbox"][0])  # only a merge item carries it
        self.assertEqual(fleet["by_repo"][0]["workflows_failing"], 1)
        self.assertEqual(health["counts"]["red"], 1)
        self.assertEqual(harness["tripped_count"], 1)
        self.assertEqual(issues["totals"]["open_issues"], 3)
        self.assertEqual(index["priority_hint"]["title"], "CI")
        self.assertIn("Top inbox item", written["llms"].read_text())

    def test_a_merge_item_keeps_what_it_clears(self) -> None:
        """FF-0036: a merge item leads the inbox, and an agent reading fleet.json
        gets `clears` and the evidence, as fleet_inbox's do."""
        merge = {"kind": "merge", "repo": "bashcrawl", "nwo": "bamr87/bashcrawl", "ref": "#133",
                 "title": "fix(ci): exclude CHANGELOG.md", "url": "https://example.test/133", "priority": 95,
                 "why": "Merge #133: clears CI on main and #127 once its branch is updated", "age_days": 3,
                 "clears": [".github/workflows/ci.yml", "#127"], "evidence": "verified"}
        rows = m.compact_inbox([merge, {"kind": "workflow", "title": "CI", "priority": 90}])
        self.assertEqual(rows[0]["clears"], [".github/workflows/ci.yml", "#127"])
        self.assertEqual((rows[0]["kind"], rows[0]["evidence"]), ("merge", "verified"))
        self.assertNotIn("clears", rows[1])


if __name__ == "__main__":
    unittest.main()

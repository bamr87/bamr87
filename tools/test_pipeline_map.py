#!/usr/bin/env python3
"""Offline tests for tools/pipeline_map.py (HUB-025, HUB-026): pipeline definition integrity,
status derivation over the EXAMPLE fixture, drill-down, unavailable log, workflow nodes."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_map as pm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIX = json.loads((ROOT / "diagrams/pipeline-map/events.example.json").read_text())
PIPE = json.loads(pm.PIPELINE.read_text())
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
BOTS = ["Fleet Ops", "Platform Architect", "Bashcrawl & Games", "Law AI Lead", "Sites", "Tools", "Content & Comms"]


class PipelineMapTests(unittest.TestCase):
    def view(self, log=FIX, runs=None):
        return {n["id"]: n for n in pm.build(PIPE, log, runs, NOW)["nodes"]}

    def test_definition_is_closed(self):
        ids = [n["id"] for n in PIPE["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        lanes = {l["id"] for l in PIPE["lanes"]}
        for n in PIPE["nodes"]:
            self.assertIn(n["lane"], lanes)
        for e in PIPE["edges"]:
            self.assertIn(e["from"], ids)
            self.assertIn(e["to"], ids)
        labels = {n["label"] for n in PIPE["nodes"] if n["kind"] == "bot"}
        self.assertEqual(labels, set(BOTS))

    def test_fixture_is_labelled_example(self):
        self.assertIn("EXAMPLE", FIX["_example"])
        self.assertEqual(pm.build(PIPE, FIX, None, NOW)["log"], "example")

    def test_status_rules(self):
        v = self.view()
        self.assertEqual(v["bot-content-comms"]["status"], "failed")   # finish outcome=failure, retry gave_up
        self.assertEqual(v["bot-tools"]["status"], "running")          # open start < 6h
        self.assertEqual(v["log-flusher"]["status"], "running")        # job in_progress
        self.assertEqual(v["fanout-routine"]["status"], "idle")        # finished success
        self.assertEqual(v["bot-sites"]["status"], "idle")             # log available, no events

    def test_drill_down(self):
        v = self.view()
        d = v["fanout-merge-block"]["drill"]
        self.assertEqual([e["event_type"] for e in d["events"]], ["declined"])
        self.assertEqual(d["amendments"][0]["relation"], "cited_for_decline")
        self.assertEqual(v["bot-tools"]["drill"]["prs"], ["bamr87/example-tool#7"])
        self.assertEqual([e["bot_id"] for e in v["drift-query"]["drill"]["events"]], ["tools"])

    def test_unavailable_log(self):
        v = self.view(log=None)
        self.assertEqual(v["bot-tools"]["status"], "unknown")
        self.assertEqual(v["bot-tools"]["drill"]["events"], [])
        self.assertEqual(pm.build(PIPE, None, None, NOW)["log"], "unavailable")

    def test_workflow_nodes_triggers_schedule_last_run(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "nightly.yml").write_text(
                "name: Nightly\non:\n  schedule:\n    - cron: '0 3 * * *'\n  workflow_dispatch:\n  push:\n    branches: [main]\njobs: {}\n")
            Path(d, "pr.yml").write_text("on: pull_request\njobs: {}\n")
            runs = {".github/workflows/nightly.yml": {"status": "completed", "conclusion": "failure"}}
            nodes = {n["id"]: n for n in pm.build(PIPE, FIX, runs, NOW, wf_dir=Path(d))["nodes"]}
        n = nodes["wf-nightly"]
        self.assertEqual(n["triggers"], ["push", "schedule", "workflow_dispatch"])
        self.assertEqual(n["schedule"], ["0 3 * * *"])
        self.assertEqual((n["status"], n["result"]), ("failed", "fail"))
        self.assertEqual((nodes["wf-pr"]["triggers"], nodes["wf-pr"]["status"]), (["pull_request"], "unknown"))

    def test_real_workflows_parse(self):
        self.assertTrue(pm.workflow_nodes())


if __name__ == "__main__":
    unittest.main()

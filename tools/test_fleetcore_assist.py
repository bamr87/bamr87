#!/usr/bin/env python3
"""Tests for tools/fleetcore/assist.py — the assistant baseline each repo's platform gets (ADR 0014):
page (the kit's payload mounts through an adapter), context (no page: reached in its checkout) or gap
(pages in a framework no adapter covers). Offline, no pytest:  python3 tools/test_fleetcore_assist.py"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
from fleetcore import assist  # noqa: E402


def repo(framework, surfaces, **more):
    return {"id": "x", "name": "x", "status": "active", "type": "app", "framework": framework,
            "surfaces": surfaces, "targets": [], **more}


class Baseline(unittest.TestCase):
    def test_a_page_in_a_known_framework_gets_its_adapter(self):
        for framework, family in (("jekyll-zer0", "jekyll"), ("mkdocs", "mkdocs"), ("static-html", "static"),
                                  ("static-html+fastapi", "static"), ("django-templates", "django"),
                                  ("react-vite-tailwind", "react"), ("nextjs-tailwind", "nextjs")):
            row = assist.baseline(repo(framework, ["browser"]))
            self.assertEqual((row["level"], row["family"]), ("page", family), framework)
            self.assertTrue((HUB / assist.KIT / row["adapter"]).is_file(), row["adapter"])

    def test_a_react_page_over_a_django_api_is_react(self):
        for framework in ("react-vite+django", "react-mantine+vscode+django"):
            self.assertEqual(assist.baseline(repo(framework, ["browser"]))["family"], "react", framework)

    def test_no_page_is_the_context_baseline_and_says_why(self):
        cases = ((None, [], "no frontend"), ("python-tui", ["terminal"], "terminal"),
                 ("vscode-webview", ["vscode"], "webview"), ("compose-multiplatform", ["mobile"], "native"),
                 ("godot", ["desktop", "browser"], "canvas"))
        for framework, surfaces, word in cases:
            row = assist.baseline(repo(framework, surfaces))
            self.assertEqual(row["level"], "context", framework)
            self.assertIn(word, row["why"])
            self.assertNotIn("adapter", row)
            self.assertIn("agent-context", row["context"])

    def test_a_page_in_an_unknown_framework_is_a_gap_never_a_guess(self):
        row = assist.baseline(repo("svelte-kit", ["browser"]))
        self.assertEqual(row["level"], "gap")
        self.assertIn("svelte-kit", row["why"])
        self.assertNotIn("adapter", row)

    def test_a_page_row_carries_where_the_page_answers(self):
        row = assist.baseline(repo("jekyll-zer0", ["browser"], targets=[
            {"kind": "live", "url": "https://it-journey.dev"}, {"kind": "local", "url": "http://127.0.0.1:4010/"}]))
        self.assertEqual((row["live"], row["local"]), (["https://it-journey.dev"], ["http://127.0.0.1:4010/"]))


class LiveRegistry(unittest.TestCase):
    """The committed registry: the plan covers every repo, and nothing that draws pages falls through."""

    def setUp(self):
        self.doc = assist.plan(HUB)

    def test_every_repo_has_a_level_and_the_counts_add_up(self):
        s = self.doc["summary"]
        self.assertEqual(self.doc["schema"], "fleet-assist/v1")
        self.assertEqual(s["repos"], len(self.doc["rows"]))
        self.assertEqual(s["page"] + s["context"] + s["gap"], s["repos"])
        self.assertEqual(sum(s["families"].values()), s["page"])
        self.assertGreater(s["page"], 0)

    def test_no_fleet_frontend_is_without_an_adapter(self):
        gaps = [f"{r['name']} ({r['framework']})" for r in self.doc["rows"] if r["level"] == "gap"]
        self.assertEqual(gaps, [], "a framework draws pages and has no adapter in templates/assistant/adapters: "
                                   "write one, or record why it has no page in fleetcore/assist.py")

    def test_the_table_lists_every_repo_once(self):
        table = assist.table(self.doc)
        body = [line for line in table.splitlines()[2:] if line.strip()]
        self.assertEqual(len(body), self.doc["summary"]["repos"])
        self.assertTrue(table.startswith("| repo | platform | baseline | adapter | why |"))


if __name__ == "__main__":
    unittest.main(verbosity=1)

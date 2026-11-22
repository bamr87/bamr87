#!/usr/bin/env python3
"""Tests for tools/ux_layout.py — the registry `ux.surfaces` → layout capture targets projection.

The browser half (the kit's layout_capture.mjs) is tested by templates/ux-audit/tests/layout.test.mjs.
Run: python3 tools/test_ux_layout.py
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ux_layout as ux  # noqa: E402

REGISTRY = [
    {"name": "Site A", "slug": "site-a", "live_url": "https://a.example/", "status": "active",
     "ux": {"enabled": True, "surfaces": [{"url": "https://a.example/", "role": "home"}, {"url": "/news/wire/", "role": "section"}]}},
    {"name": "Site B", "slug": "site-b", "live_url": "https://b.example/blog", "status": "active"},
    {"name": "Off", "slug": "off", "live_url": "https://off.example/", "ux": {"enabled": False}},
    {"name": "Old", "slug": "old", "live_url": "https://old.example/", "status": "archived"},
    {"name": "Lib", "slug": "lib", "status": "active"},
    {"name": "Relative only", "slug": "rel", "status": "active", "ux": {"enabled": True, "surfaces": [{"url": "/x/", "role": "home"}]}},
]


class ScopeTests(unittest.TestCase):
    def test_enabled_flag_wins(self):
        self.assertTrue(ux.in_scope(REGISTRY[0]))
        self.assertFalse(ux.in_scope(REGISTRY[2]))

    def test_without_ux_a_live_unarchived_entry_is_in_scope(self):
        self.assertTrue(ux.in_scope(REGISTRY[1]))
        self.assertFalse(ux.in_scope(REGISTRY[3]))
        self.assertFalse(ux.in_scope(REGISTRY[4]))


class SlugTests(unittest.TestCase):
    def test_matches_the_capture_scripts_slug(self):
        # Same cases as layout_capture.mjs pathSlug: ids must agree between the two halves.
        self.assertEqual(ux.path_slug("https://x.example/"), "home")
        self.assertEqual(ux.path_slug("https://x.example/news/wire/"), "news-wire")
        self.assertEqual(ux.path_slug("https://x.example/a/B.html"), "a-b")
        self.assertEqual(ux.path_slug("https://x.example/s?q=1"), "s-q-1")


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.err = io.StringIO()
        with contextlib.redirect_stderr(self.err):
            self.all = ux.targets(REGISTRY)

    def test_surfaces_become_targets_and_relative_urls_join_the_live_url(self):
        a = [t for t in self.all if t["site"] == "site-a"]
        self.assertEqual([t["url"] for t in a], ["https://a.example/", "https://a.example/news/wire/"])
        self.assertEqual([t["id"] for t in a], ["site-a--home", "site-a--news-wire"])
        self.assertEqual([t["role"] for t in a], ["home", "section"])

    def test_an_entry_without_surfaces_contributes_its_live_url_as_home(self):
        b = [t for t in self.all if t["site"] == "site-b"]
        self.assertEqual(b, [{"id": "site-b--blog", "site": "site-b", "role": "home", "url": "https://b.example/blog"}])

    def test_out_of_scope_entries_and_unresolvable_surfaces_are_left_out(self):
        self.assertEqual({t["site"] for t in self.all}, {"site-a", "site-b"})
        self.assertIn("relative surface '/x/' and no live_url", self.err.getvalue())

    def test_repo_and_role_filters(self):
        self.assertEqual([t["id"] for t in ux.targets(REGISTRY, ["Site A"], "section")], ["site-a--news-wire"])
        self.assertEqual(len(ux.targets(REGISTRY, ["site-b"])), 1)

    def test_an_unknown_repo_is_refused_not_silently_empty(self):
        with self.assertRaises(SystemExit) as cm:
            ux.targets(REGISTRY, ["nope"])
        self.assertIn("not in the registry: nope", str(cm.exception))


class RealRegistryTests(unittest.TestCase):
    def test_the_section_surfaces_the_capture_starts_with(self):
        found = {t["id"]: t for t in ux.targets(ux.load_registry(), ["lifehacker.dev", "zer0-mistakes"], "section")}
        self.assertEqual(found["lifehacker.dev--news-wire"]["url"], "https://lifehacker.dev/news/wire/")
        self.assertEqual(found["zer0-mistakes--news-development"]["url"], "https://zer0-mistakes.com/news/development/")


class CaptureTests(unittest.TestCase):
    def test_without_the_kits_playwright_capture_says_how_to_install_and_exits_2(self):
        with tempfile.TemporaryDirectory() as kit, tempfile.TemporaryDirectory() as out:
            old = ux.KIT
            ux.KIT = Path(kit)
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    status = ux.main(["capture", "--repo", "lifehacker.dev", "--out", out, "--no-png"])
            finally:
                ux.KIT = old
            self.assertEqual(status, 2)
            if "node is not installed" not in err.getvalue():
                self.assertIn("npm install --no-package-lock", err.getvalue())
            self.assertTrue((Path(out) / "targets.json").is_file())

    def test_targets_prints_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(ux.main(["targets", "--repo", "lifehacker.dev", "--role", "section"]), 0)
        self.assertIn('"lifehacker.dev--news-wire"', buf.getvalue())


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()

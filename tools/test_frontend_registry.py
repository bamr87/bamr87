#!/usr/bin/env python3
"""Tests for tools/frontend_registry.py — the § 18 frontend: block lint and the
launcher projection. Offline, no pytest:  python3 tools/test_frontend_registry.py"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frontend_registry as fr  # noqa: E402


def entry(**fe):
    base = {"type": "app", "tier": "shell", "framework": "react", "surfaces": ["browser"],
            "token_version": "none", "entry_url": "https://x.test/", "shell": "own"}
    base.update(fe)
    return {"name": "x", "slug": "x", "submodule_path": "projects/x", "status": "active", "frontend": base}


class FrontendRegistryTests(unittest.TestCase):
    def test_hub_registry_is_clean(self):
        reg = fr.load(fr.HUB / "_data" / "projects.yml")
        self.assertEqual(fr.lint(reg), [])
        subs = [e for e in reg if e.get("submodule_path")]
        self.assertTrue(all("frontend" in e for e in subs))

    def test_valid_entry(self):
        self.assertEqual(fr.lint_entry(entry()), [])

    def test_missing_block_on_submodule(self):
        self.assertTrue(fr.lint_entry({"name": "y", "submodule_path": "projects/y"}))
        self.assertEqual(fr.lint_entry({"name": "ext"}), [])

    def test_bad_enums(self):
        self.assertTrue(fr.lint_entry(entry(tier="full")))
        self.assertTrue(fr.lint_entry(entry(surfaces=["watch"])))
        self.assertTrue(fr.lint_entry(entry(shell="mine")))
        self.assertTrue(fr.lint_entry(entry(token_version="latest")))
        self.assertEqual(fr.lint_entry(entry(token_version="v1.2.0")), [])

    def test_tier_coherence(self):
        self.assertTrue(fr.lint_entry(entry(type="game", tier="shell")))
        self.assertEqual(fr.lint_entry(entry(type="game", tier="tokens", shell="none")), [])
        self.assertTrue(fr.lint_entry(entry(type="site", tier="none")))
        self.assertTrue(fr.lint_entry(entry(type="none", tier="none", enforce=True)))

    def test_launcher_skips_none_and_archived(self):
        reg = [entry(), {**entry(type="none", tier="none"), "name": "n", "slug": "n"},
               {**entry(), "name": "a", "slug": "a", "status": "archived"}]
        apps = fr.launcher(reg)["apps"]
        self.assertEqual([a["id"] for a in apps], ["x"])
        self.assertEqual(apps[0]["deep_link"], "fleet://x/")


if __name__ == "__main__":
    unittest.main()

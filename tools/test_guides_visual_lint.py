#!/usr/bin/env python3
"""Fixture tests for tools/guides_visual_lint.py (constitution § 24)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from guides_visual_lint import check, _has_visual


class GuidesVisualLintTest(unittest.TestCase):
    def test_has_visual_image(self):
        self.assertTrue(_has_visual("![x](../assets/guides/a/b.png)\n"))
        self.assertTrue(_has_visual("see test/evidence/foo/\n"))
        self.assertTrue(_has_visual("skip-visuals: API-only\n"))
        self.assertFalse(_has_visual("# Title\n\nNo picture here.\n"))

    def test_check_fixture_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "visual-evidence-backlog.md").write_text(
                "| `docs/GOOD.md` | ok |\n| `docs/BAD.md` | gap |\n",
                encoding="utf-8",
            )
            (root / "docs" / "GOOD.md").write_text(
                "![Console home](assets/guides/x/overview--desktop.png)\n",
                encoding="utf-8",
            )
            (root / "docs" / "assets" / "guides" / "x").mkdir(parents=True)
            (root / "docs" / "assets" / "guides" / "x" / "overview--desktop.png").write_bytes(b"PNG")
            (root / "docs" / "BAD.md").write_text("# Bad\n\nNo visuals.\n", encoding="utf-8")
            warn = check(root, gate=False)
            self.assertTrue(warn["ok"])  # warn-only always ok
            self.assertEqual(len(warn["gaps"]), 1)
            self.assertEqual(warn["gaps"][0]["path"], "docs/BAD.md")
            hard = check(root, gate=True)
            self.assertFalse(hard["ok"])

    def test_broken_image(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "visual-evidence-backlog.md").write_text(
                "- [ ] `docs/MISS.md` — missing shot\n", encoding="utf-8"
            )
            (root / "docs" / "MISS.md").write_text(
                "![gone](assets/guides/nope.png)\n", encoding="utf-8"
            )
            result = check(root, gate=True)
            self.assertEqual(len(result["broken_images"]), 1)


if __name__ == "__main__":
    unittest.main()

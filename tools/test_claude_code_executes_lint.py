#!/usr/bin/env python3
"""Fixture tests for tools/claude_code_executes_lint.py (constitution § 26)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from claude_code_executes_lint import check, _is_direction_setting


class ClaudeCodeExecutesLintTest(unittest.TestCase):
    def _root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "_data").mkdir()
        (root / "docs").mkdir()
        roles = {
            "schema": "agent-roles/v1",
            "executors": [{"id": "claude-code", "kind": "claude-code"}],
            "directors": [{"id": "grok-bot", "kind": "grok-bot", "names": ["Grok Bot"]}],
            "github_logins_warn": [],
            "direction_setting_path_prefixes": [
                "docs/constitution.md",
                "docs/amendments/",
                "changelog.d/",
                "features/features.d/",
                "AGENTS.md",
            ],
        }
        (root / "_data" / "agent_roles.yml").write_text(
            yaml.safe_dump(roles), encoding="utf-8"
        )
        (root / "docs" / "constitution.md").write_text(
            "# x\n\n## 26. Claude Code executes; Grok bots set direction\n",
            encoding="utf-8",
        )
        return root

    def test_prefix_helper(self):
        prefixes = ["docs/amendments/", "AGENTS.md"]
        self.assertTrue(_is_direction_setting("docs/amendments/proposed/x.md", prefixes))
        self.assertTrue(_is_direction_setting("AGENTS.md", prefixes))
        self.assertFalse(_is_direction_setting("tools/console/app.py", prefixes))

    def test_clean_repo(self):
        root = self._root()
        result = check(root, gate=True)
        self.assertTrue(result["ok"], result["findings"])

    def test_non_direction_files_fail_gate(self):
        root = self._root()
        warn = check(root, gate=False, files=["tools/console/app.py"])
        self.assertTrue(warn["ok"])
        self.assertTrue(warn["findings"])
        hard = check(root, gate=True, files=["tools/console/app.py"])
        self.assertFalse(hard["ok"])


if __name__ == "__main__":
    unittest.main()

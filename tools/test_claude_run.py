#!/usr/bin/env python3
"""Static tests for the fleet's `claude-run` composite action (bamr87#499).

An install that exits 0 with the wrong Claude Code release (2.1.197 on Node 20)
left no trace in the run log, because the install log was only printed on
failure. These tests hold two lines in place in the action's run script:

  * after the install step, the installed Claude Code version and the Node
    version are always printed;
  * an install that exited 0 but left no `claude` on PATH raises a
    `::warning::` naming the install log, instead of continuing silently.

Run: python3 tools/test_claude_run.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION = REPO_ROOT / ".github" / "actions" / "claude-run" / "action.yml"
INSTALL = "npm install -g @anthropic-ai/claude-code@latest"


def run_script() -> str:
    """The `run:` body of the step that installs Claude Code."""
    manifest = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    for step in manifest["runs"]["steps"]:
        if INSTALL in step.get("run", ""):
            return step["run"]
    raise AssertionError(f"no step in {ACTION} runs `{INSTALL}`")


class ClaudeRunVersionLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = run_script()
        self.lines = self.script.splitlines()
        self.install_at = next(i for i, ln in enumerate(self.lines) if INSTALL in ln)
        self.runner_at = next(i for i, ln in enumerate(self.lines) if "run.sh" in ln and "bash " in ln)

    def test_version_line_after_install(self) -> None:
        hits = [i for i, ln in enumerate(self.lines)
                if re.search(r'echo "claude-run: Claude Code \$\(claude --version', ln)
                and "Node $(node --version" in ln]
        self.assertTrue(hits, "action.yml prints no `claude-run: Claude Code … on Node …` line")
        self.assertTrue(all(self.install_at < i < self.runner_at for i in hits),
                        "the version line must sit after the install and before run.sh")

    def test_missing_cli_after_successful_install_warns(self) -> None:
        tail = "\n".join(self.lines[self.install_at:self.runner_at])
        self.assertRegex(tail, r"command -v claude",
                         "no `command -v claude` check after the install")
        self.assertRegex(tail, r'::warning::[^\n]*\$RUNNER_TEMP/npm-install\.log',
                         "the missing-CLI warning must name $RUNNER_TEMP/npm-install.log")

    def test_install_block_runs(self) -> None:
        """Execute the install-to-version span with stubbed npm/node and no claude."""
        version_at = next(i for i, ln in enumerate(self.lines) if 'echo "claude-run: Claude Code' in ln)
        span = "\n".join(self.lines[self.install_at:version_at + 1])
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp, "bin")
            bin_dir.mkdir()
            for name, body in (("npm", "exit 0"), ("node", "echo v20.0.0")):
                p = bin_dir / name
                p.write_text(f"#!/bin/sh\n{body}\n")
                p.chmod(0o755)
            out = subprocess.run(
                ["/bin/bash", "-c", span],
                env={"PATH": str(bin_dir), "RUNNER_TEMP": tmp},  # no real `claude` reachable
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"::warning::npm install exited 0 but no `claude` is on PATH — see {tmp}/npm-install.log.",
                      out.stdout)
        self.assertIn("claude-run: Claude Code not installed on Node v20.0.0", out.stdout)


if __name__ == "__main__":
    sys.exit(unittest.main())

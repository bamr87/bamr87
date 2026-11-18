#!/usr/bin/env python3
"""Tests for tools/fanout.sh's hub-pin pre-flight (FF-0037, bamr87/bamr87#610).

A kit whose caller template pins a hub reusable workflow at a ref that lacks it
seeds a startup failure into every target. The pre-flight resolves the kit's
templates before any target is cloned: the dry run names the unresolved pin and
carries on, and --apply is refused until it resolves.

Offline: a throwaway hub (a copy of fanout.sh and hub_refs.py in a fixture git
repository whose v2 predates spec-gate.yml, as on 2026-10-30) and a `gh` stub
that records its calls and answers nothing, so the online lookup reads
unverified and the pre-flight falls back to the fixture's own tags. Run:
    python3 tools/test_fanout_preflight.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"
GH_STUB = """#!/bin/sh
echo "$*" >> "$GH_LOG"
exit 1
"""


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                   check=True, capture_output=True, text=True)


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class FanoutPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout-preflight-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        hub = self.hub = self.tmp / "hub"
        for rel in ("tools/fanout.sh", ".github/scripts/dash-gen/hub_refs.py",
                    "templates/spec-driven/workflows/spec-gate.yml"):
            write(hub, rel, (HUB / rel).read_text(encoding="utf-8"))
        (hub / "tools/fanout.sh").chmod(0o755)
        # one unrelated submodule: fanout.sh reads .gitmodules under pipefail
        write(hub, ".gitmodules", '[submodule "projects/other"]\n\tpath = projects/other\n'
                                  "\turl = https://github.com/bamr87/other.git\n")
        write(hub, "_data/projects.yml", "[]\n")
        write(hub, "_data/fleet.yml", "hub:\n  repo: bamr87/bamr87\n  owners: [bamr87]\n")
        write(hub, ".github/workflows/standard-ci.yml", "on: workflow_call\n")
        git(hub, "init", "-q", "-b", "main")
        git(hub, "add", "-A")
        git(hub, "commit", "-q", "-m", "v2.0.0: before spec-gate.yml")
        git(hub, "tag", "-a", "v2.0.0", "-m", "v2.0.0")
        git(hub, "tag", "-a", "v2", "-m", "v2 -> v2.0.0")
        write(hub, ".github/workflows/spec-gate.yml", "on: workflow_call\n")
        write(hub, "CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n- `spec-gate.yml`: added\n")
        git(hub, "add", "-A")
        git(hub, "commit", "-q", "-m", "spec-gate.yml on main")
        bindir = self.tmp / "bin"
        write(bindir, "gh", GH_STUB)
        (bindir / "gh").chmod(0o755)
        self.gh_log = self.tmp / "gh.log"
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "GH_LOG": str(self.gh_log)}
        self.env.pop("GH_TOKEN", None)
        self.env.pop("GITHUB_TOKEN", None)

    def fanout(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([BASH, str(self.hub / "tools/fanout.sh"), "--kit", "spec-driven",
                               "--target", "nowhere", *args],
                              capture_output=True, text=True, env=self.env, timeout=120)

    def gh_calls(self) -> list[str]:
        return self.gh_log.read_text().splitlines() if self.gh_log.exists() else []

    def test_apply_is_refused_before_any_target_is_touched(self):
        r = self.fanout("--apply")
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, out)
        self.assertIn("templates/spec-driven/workflows/spec-gate.yml:29", out)
        self.assertIn("file-missing-at-ref", out)
        self.assertIn("fix: cut v2.1.0 and move v2", out)
        self.assertIn("refusing --apply", out)
        self.assertNotIn("skip nowhere", out)  # stopped before resolving any target
        # GitHub was asked first (the stub answers nothing), and nothing was cloned
        self.assertTrue(any(c.startswith("api ") for c in self.gh_calls()), self.gh_calls())
        self.assertFalse(any("clone" in c for c in self.gh_calls()), self.gh_calls())

    def test_the_dry_run_names_the_pin_and_carries_on(self):
        r = self.fanout()
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("templates/spec-driven/workflows/spec-gate.yml:29", out)
        self.assertIn("--apply is refused until every pin above resolves", out)
        self.assertIn("skip nowhere", out)  # the dry run went on to the targets

    def test_apply_proceeds_once_the_release_carries_the_file(self):
        git(self.hub, "tag", "-a", "v2.1.0", "-m", "v2.1.0")
        git(self.hub, "tag", "-fa", "v2", "-m", "v2 -> v2.1.0")
        r = self.fanout("--apply")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("1 of 1 hub pin(s)", out)
        self.assertNotIn("refusing", out)
        self.assertIn("skip nowhere", out)

    def test_a_kit_without_caller_templates_skips_the_preflight(self):
        r = subprocess.run([BASH, str(self.hub / "tools/fanout.sh"), "--kit", "deps-latest",
                            "--target", "nowhere", "--apply"],
                           capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("pre-flight", r.stdout + r.stderr)
        self.assertEqual(self.gh_calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)

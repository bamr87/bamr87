#!/usr/bin/env python3
"""python-tests.yml skips docs-only changes in two places that must agree: the
`changes` job's case statement (pull requests) and the push trigger's `paths:`
filter (pushes to main). Each names the docs the tests read, which must still run
the suites, and the directories that may be skipped. This holds the two equal and
checks the filter, matched the way GitHub orders its patterns, on sample paths.

Usage: python3 tools/test_python_tests_paths.py   (run by python-tests.yml and run-all-tests.sh)
"""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/python-tests.yml"


def _load():
    doc = yaml.safe_load(WORKFLOW.read_text())
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
    return doc, on


def _case_arms():
    """(docs that run the suites, globs that may be skipped) from the `changes` job."""
    doc, _ = _load()
    script = next(s["run"] for s in doc["jobs"]["changes"]["steps"] if s.get("id") == "diff")
    run_arm = re.search(r"^\s*([^\s)]+)\)\s*run=true\s*;;", script, re.M)
    skip_arm = re.search(r"^\s*([^\s)]+)\)\s*;;", script, re.M)
    assert run_arm and skip_arm, "the changes job's case statement changed shape"
    return run_arm.group(1).split("|"), skip_arm.group(1).split("|")


def _glob_re(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def triggers(paths, file):
    """GitHub's rule: patterns apply in order, a `!` line excludes, the last match wins."""
    hit = False
    for p in paths:
        neg = p.startswith("!")
        if _glob_re(p[1:] if neg else p).match(file):
            hit = not neg
    return hit


class PythonTestsPathsTests(unittest.TestCase):
    def setUp(self):
        _, on = _load()
        self.paths = on["push"]["paths"]
        self.run_docs, self.skip_globs = _case_arms()

    def test_push_filter_reincludes_exactly_the_docs_tests_read(self):
        positives = [p for p in self.paths if not p.startswith("!") and p != "**"]
        self.assertEqual(sorted(positives), sorted(self.run_docs))

    def test_push_filter_excludes_exactly_the_skippable_dirs(self):
        negatives = [p[1:].removesuffix("**") for p in self.paths if p.startswith("!")]
        self.assertEqual(sorted(negatives), sorted(g.removesuffix("*") for g in self.skip_globs))

    def test_order_starts_broad_then_excludes_then_reincludes(self):
        self.assertEqual(self.paths[0], "**")
        first_positive_after = next(i for i, p in enumerate(self.paths[1:], 1) if not p.startswith("!"))
        self.assertTrue(all(p.startswith("!") for p in self.paths[1:first_positive_after]))
        self.assertTrue(all(not p.startswith("!") for p in self.paths[first_positive_after:]))

    def test_sample_paths(self):
        for f in ("docs/adr/0014-fleet-assistant-baseline.md", "docs/README.md", "changelog.d/x.md",
                  "features/features.d/x.yml"):
            self.assertFalse(triggers(self.paths, f), f)
        for f in ("docs/JEV.md", "tools/jev/ratify.py", ".github/workflows/python-tests.yml", "_data/fleet.yml",
                  "features/features.yml", "README.md", "projects/README"):
            self.assertTrue(triggers(self.paths, f), f)

    def test_pull_requests_and_nightly_stay_unfiltered(self):
        _, on = _load()
        self.assertIsNone((on.get("pull_request") or {}).get("paths"))
        self.assertIn("schedule", on)


if __name__ == "__main__":
    unittest.main()

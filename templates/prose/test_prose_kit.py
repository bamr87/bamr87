#!/usr/bin/env python3
"""Contract tests for the prose kit (templates/prose/).

markdown-oneline.yml is seeded into every fleet repo, and `tools/fanout.sh
--kit prose --upgrade` refreshes a deployed copy only when it is byte-identical
to the template or to one of the shapes in archive/. These checks hold the two
halves of that bargain:

  * the template checks out the pull request's head by SHA, never by branch
    name: an auto-merged PR's branch is deleted before the job starts, and a
    checkout by name then fails on a PR that already merged (kit 0.5.0);
  * the repair step confirms the head branch still exists before it commits
    and pushes, so it never recreates a merged branch;
  * the branch name reaches the script through `env:`, never `${{ }}`;
  * the template starts with its comment header, not a blank line (yamllint);
  * every archived shape is distinct from the others and from the template,
    and VERSION lists every one of them — an edit that skips the archive
    strands the deployed copies as "hand-modified" (5c648c43 did, for ten).

Stdlib (+ PyYAML when installed):

    python3 templates/prose/test_prose_kit.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # the structural checks below still run on plain text
    yaml = None

KIT = Path(__file__).resolve().parent
TEMPLATE = KIT / "markdown-oneline.yml"
ARCHIVE = KIT / "archive"
SHAPE = re.compile(r"^markdown-oneline-(\d+\.\d+\.\d+)(-[a-z0-9-]+)?\.yml$")


def text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def rendered() -> str:
    # What seeding writes (tools/fanout.sh render_kit_template).
    return text().replace("__DEFAULT_BRANCH__", "main")


def kit_version() -> tuple[int, ...]:
    m = re.search(r"^version:\s*(\S+)", (KIT / "VERSION").read_text(encoding="utf-8"), re.M)
    assert m, "VERSION has no version:"
    return tuple(int(p) for p in m.group(1).split("."))


def push_step_run() -> str:
    m = re.search(r"- name: Push the repair back to the pull request\n(.*?)(?=\n      - name: |\Z)",
                  text(), re.S)
    assert m, "no 'Push the repair back to the pull request' step"
    return m.group(1)


class Checkout(unittest.TestCase):
    def test_checks_out_head_by_sha(self):
        refs = re.findall(r"^\s+ref:\s*(.+)$", text(), re.M)
        self.assertEqual(refs, ["${{ github.event.pull_request.head.sha || github.sha }}"])

    def test_never_checks_out_a_branch_name(self):
        for line in re.findall(r"^\s+ref:.*$", text(), re.M):
            self.assertNotIn("head.ref", line)
            self.assertNotIn("github.ref", line)

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_parsed_checkout_step(self):
        doc = yaml.safe_load(rendered())
        steps = doc["jobs"]["oneline"]["steps"]
        checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))
        self.assertIn("head.sha", checkout["with"]["ref"])
        self.assertIn("head.repo.full_name", checkout["with"]["repository"])


class RepairPush(unittest.TestCase):
    def test_gone_branch_guard_precedes_commit_and_push(self):
        run = push_step_run()
        guard = run.find('git ls-remote --exit-code --heads origin "refs/heads/$HEAD_REF"')
        self.assertGreater(guard, -1, "no ls-remote guard on the head branch")
        self.assertLess(guard, run.find("git commit"))
        self.assertLess(guard, run.find("git push"))
        self.assertRegex(run[guard:run.find("git commit")], r"exit 0",
                         "a gone branch must end the step green, not fall through to the push")

    def test_branch_name_only_through_env(self):
        run = push_step_run()
        self.assertIn("HEAD_REF: ${{ github.event.pull_request.head.ref }}", run)
        script = run.split("run: |", 1)[1]
        self.assertNotIn("${{", script, "expression interpolated into the push script")

    def test_starts_with_header_not_blank_line(self):
        self.assertTrue(text().startswith("# Seeded by the bamr87 hub"))


class Archive(unittest.TestCase):
    def shapes(self) -> list[Path]:
        return sorted(ARCHIVE.glob("markdown-oneline-*.yml"))

    def test_shapes_are_named_and_older_than_the_kit(self):
        self.assertTrue(self.shapes())
        for p in self.shapes():
            m = SHAPE.match(p.name)
            self.assertIsNotNone(m, f"{p.name}: not archive/markdown-oneline-<X.Y.Z>[-variant].yml")
            self.assertLess(tuple(int(x) for x in m.group(1).split(".")), kit_version(), p.name)

    def test_shapes_are_distinct_from_each_other_and_the_template(self):
        seen = {text(): "markdown-oneline.yml"}
        for p in self.shapes():
            body = p.read_text(encoding="utf-8")
            self.assertNotIn(body, seen, f"{p.name} duplicates {seen.get(body)}")
            seen[body] = p.name

    def test_version_lists_every_shape(self):
        meta = (KIT / "VERSION").read_text(encoding="utf-8")
        files = re.search(r"^files:\s*(.+)$", meta, re.M).group(1)
        braces = re.search(r"archive/markdown-oneline-\{([^}]*)\}\.yml", files)
        self.assertIsNotNone(braces, "VERSION files: does not list archive/markdown-oneline-{...}.yml")
        listed = {v.strip() for v in braces.group(1).split(",")}
        on_disk = {SHAPE.match(p.name).group(1) + (SHAPE.match(p.name).group(2) or "") for p in self.shapes()}
        self.assertEqual(listed, on_disk)

    def test_changelog_leads_with_the_current_version(self):
        meta = (KIT / "VERSION").read_text(encoding="utf-8")
        first = re.search(r"^changelog: \|\n\s+(\d+\.\d+\.\d+) —", meta, re.M)
        self.assertIsNotNone(first, "changelog: does not open with '<version> —'")
        self.assertEqual(tuple(int(x) for x in first.group(1).split(".")), kit_version())


if __name__ == "__main__":
    unittest.main(verbosity=1)

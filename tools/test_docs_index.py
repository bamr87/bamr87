#!/usr/bin/env python3
"""
Fixture tests for tools/docs_index.py — the generated documentation index.

The index is vendored into every fleet repo and its `--check` mode gates them,
so these guard the behaviours a repo relies on:

  * a summary comes from front-matter `description:`, then the `>` line under
    the H1 (never a GitHub alert), and only then a first-sentence fallback,
    which `--lint` reports;
  * a subdirectory with its own README.md is one row and is not entered;
  * README.md, CLAUDE.md and Jekyll pages stay out of the root group, and the
    fleet's well-known root files get a description without being edited;
  * marker options (roots, exclude, root=no) shape the span and survive it;
  * relative links in a summary are rebased to the index, and truncation never
    cuts through a link or a code span;
  * `--write` is idempotent and `--check` fails exactly when the span is stale.

Stdlib only:

    python3 tools/test_docs_index.py
"""
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("docs_index", HERE / "docs_index.py")
di = importlib.util.module_from_spec(spec)
spec.loader.exec_module(di)


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = di.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        subprocess.run(["git", "init", "-q", self.root], check=True)
        write(self.root, "README.md", "# demo\n\n> The demo.\n")
        write(self.root, "CLAUDE.md", "# demo\n\n@AGENTS.md\n")
        write(self.root, "AGENTS.md", "# demo\n\n## What this repo is\n\nA demo.\n")
        write(self.root, "CHANGELOG.md", "# Changelog\n\nAll notable changes.\n")
        write(self.root, "index.md", "---\nlayout: home\n---\n# Home\n")
        write(self.root, "docs/ARCH.md", "# Architecture\n\n> How the parts fit; see [ops](OPS.md).\n\nBody.\n")
        write(self.root, "docs/OPS.md", "---\ntitle: Operations\ndescription: >-\n  Running it in\n  production.\n---\n\nBody.\n")
        write(self.root, "docs/guide.md", "# Guide\n\n> [!NOTE]\n> An alert, not a summary.\n\nFirst sentence here. Second one.\n")
        write(self.root, "docs/adr/README.md", "# Decisions\n\n> One file per decision.\n")
        write(self.root, "docs/adr/0001-x.md", "# 1. X\n\n> Not listed: the ADR index owns it.\n")
        write(self.root, "docs/media/notes.md", "# Media notes\n\n> Media.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def docs(self, opts=""):
        return {d["path"]: d for d in di.collect(self.root, di.parse_options(opts))}


class SummaryTests(Fixture):
    def test_sources_in_order_of_preference(self):
        d = self.docs()
        self.assertEqual(d["docs/OPS.md"]["source"], "front-matter")
        self.assertEqual(d["docs/OPS.md"]["summary"], "Running it in production.")
        self.assertEqual(d["docs/ARCH.md"]["source"], "blockquote")
        self.assertEqual(d["docs/guide.md"]["source"], "fallback")
        self.assertEqual(d["docs/guide.md"]["summary"], "First sentence here.")

    def test_heading_inside_a_fence_is_not_an_h1(self):
        write(self.root, "docs/code.md", "# Code\n\n> Real.\n\n```md\n# not a heading\n```\n")
        self.assertEqual(self.docs()["docs/code.md"]["h1"], 1)

    def test_links_are_rebased_to_the_index(self):
        self.assertIn("[ops](OPS.md)", self.docs()["docs/ARCH.md"]["summary"])
        write(self.root, "PRD.md", "# PRD\n\n> See [the guide](docs/guide.md) and [site](https://x.dev).\n")
        summary = self.docs()["PRD.md"]["summary"]
        self.assertIn("[the guide](guide.md)", summary)
        self.assertIn("(https://x.dev)", summary)

    def test_truncation_never_splits_a_link(self):
        text = "word " * 44 + "[a link that would be cut](target.md) and more words after it"
        out = di.clean(text)
        self.assertTrue(out.endswith("…"))
        self.assertTrue(di.balanced(out), out)
        self.assertLessEqual(len(out), di.SUMMARY_MAX + 1)

    def test_pipes_are_escaped_for_the_table(self):
        self.assertEqual(di.clean("a | b"), "a \\| b")


class CollectionTests(Fixture):
    def test_root_group_skips_readme_claude_and_site_pages(self):
        d = self.docs()
        self.assertIn("AGENTS.md", d)
        for skipped in ("README.md", "CLAUDE.md", "index.md"):
            self.assertNotIn(skipped, d)

    def test_well_known_root_files_get_a_description(self):
        d = self.docs()
        self.assertEqual(d["CHANGELOG.md"]["source"], "well-known")
        self.assertEqual(d["AGENTS.md"]["source"], "well-known")

    def test_nested_index_owns_its_directory(self):
        d = self.docs()
        self.assertEqual(d["docs/adr/README.md"]["directory"], "docs/adr/")
        self.assertEqual(d["docs/adr/README.md"]["group"], "docs/")
        self.assertNotIn("docs/adr/0001-x.md", d)

    def test_marker_options(self):
        d = self.docs("roots=docs exclude=docs/media/ root=no")
        self.assertNotIn("docs/media/notes.md", d)
        self.assertNotIn("AGENTS.md", d)
        write(self.root, "specs/RULES.md", "# Rules\n\n> The rules.\n")
        self.assertIn("specs/RULES.md", self.docs("roots=docs,specs"))


class CliTests(Fixture):
    def test_write_creates_the_index_and_is_idempotent(self):
        code, _, _ = run("--write", "--root", self.root)
        self.assertEqual(code, 0)
        first = (Path(self.root) / "docs/README.md").read_text(encoding="utf-8")
        self.assertIn("<!-- AUTO:docs-index:start -->", first)
        self.assertIn("[`docs/adr/`](adr/README.md)", first)
        self.assertIn("[`AGENTS.md`](../AGENTS.md)", first)
        run("--write", "--root", self.root)
        self.assertEqual(first, (Path(self.root) / "docs/README.md").read_text(encoding="utf-8"))
        self.assertEqual(run("--check", "--root", self.root)[0], 0)

    def test_check_fails_when_stale_and_options_survive(self):
        write(self.root, "docs/README.md",
              "# demo docs\n\n> Index.\n\nHand prose.\n\n"
              "<!-- AUTO:docs-index:start exclude=docs/media/ -->\n<!-- AUTO:docs-index:end -->\n")
        self.assertEqual(run("--check", "--root", self.root)[0], 1)
        run("--write", "--root", self.root)
        text = (Path(self.root) / "docs/README.md").read_text(encoding="utf-8")
        self.assertIn("Hand prose.", text)
        self.assertIn("<!-- AUTO:docs-index:start exclude=docs/media/ -->", text)
        self.assertNotIn("media/notes.md", text)
        self.assertEqual(run("--check", "--root", self.root)[0], 0)
        write(self.root, "docs/NEW.md", "# New\n\n> Fresh.\n")
        self.assertEqual(run("--check", "--root", self.root)[0], 1)

    def test_write_refuses_an_index_without_markers(self):
        write(self.root, "docs/README.md", "# hand-written\n")
        code, _, err = run("--write", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertIn("AUTO:docs-index:start", err)

    def test_lint_reports_missing_summaries_and_extra_h1s(self):
        write(self.root, "docs/two.md", "# One\n\n> Fine.\n\n# Two\n")
        code, out, _ = run("--lint", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertIn("docs/guide.md: no summary line", out)
        self.assertIn("docs/two.md: 2 H1 headings", out)
        self.assertNotIn("CHANGELOG.md", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)

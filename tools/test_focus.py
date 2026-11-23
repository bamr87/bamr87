#!/usr/bin/env python3
"""Tests for tools/focus.py — the checks a change owes (ADR 0016): pattern matching,
the plan for a set of changed files, the tests found beside a changed module, what a
missing `needs:` does to a run, the change read from a throwaway git repository, and
the live registry (_data/checks.yml) held to the tree it names.
Offline, no pytest:  python3 tools/test_focus.py"""
from __future__ import annotations

import contextlib
import io
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import focus  # noqa: E402

HUB = Path(__file__).resolve().parents[1]

REGISTRY = """\
schema: checks/v1
checks:
  - id: always
    title: Runs for every change
    run: python3 -c "print('always')"
    paths:
      - "**"
  - id: prose
    title: Markdown
    run: python3 -c "import sys; print(sys.argv[1:])" {files}
    paths:
      - "**/*.md"
  - id: workflows
    title: Workflows
    run: python3 -c "import sys; sys.exit(3)"
    paths:
      - .github/workflows/**
  - id: tool
    title: Needs a binary nobody has
    run: no-such-binary-xyz {files}
    needs: no-such-binary-xyz
    paths:
      - tools/*.sh
  - id: guard
    title: Uses the base
    run: python3 -c "import sys; print(sys.argv[1])" {base}
    paths:
      - docs/**
"""


class Repo:
    """A throwaway hub: a registry, a base commit on `main`, and a working branch."""

    def __init__(self, registry: str = REGISTRY):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write(focus.REGISTRY, registry)

    def write(self, rel: str, text: str = "x\n") -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)

    def init(self) -> None:
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "work")

    def close(self) -> None:
        self._tmp.cleanup()


class Case(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(self.r.close)

    def ids(self, files: list[str], **kw) -> list[str]:
        return [s["id"] for s in focus.plan(self.r.root, files, "main", **kw)]


class GlobTests(unittest.TestCase):
    def test_star_stays_in_a_segment_and_double_star_crosses(self):
        m = lambda pattern, path: bool(focus.glob_to_regex(pattern).match(path))  # noqa: E731
        self.assertTrue(m("tools/*.sh", "tools/fanout.sh"))
        self.assertFalse(m("tools/*.sh", "tools/observability/ship.sh"))
        self.assertTrue(m("tools/**", "tools/console/web/src/a.ts"))
        self.assertTrue(m("**/*.md", "README.md"))
        self.assertTrue(m("**/*.md", "docs/adr/0016-x.md"))
        self.assertFalse(m("**/*.md", "docs/readme.mdx"))
        self.assertTrue(m("**", "anything/at/all.txt"))
        self.assertTrue(m("_data/fleet.yml", "_data/fleet.yml"))
        self.assertFalse(m("_data/fleet.yml", "_data/fleet_yml"))  # a dot is a dot
        self.assertTrue(m("verify/scenarios/**", "verify/scenarios/a.yml"))
        self.assertFalse(m(".github/workflows/*.yml", ".github/workflows/sub/a.yml"))


class PlanTests(Case):
    def test_only_the_checks_a_change_touches(self):
        self.r.write("docs/A.md")
        self.assertEqual(self.ids(["docs/A.md"]), ["always", "prose", "guard"])
        self.assertEqual(self.ids(["tools/x.txt"]), ["always"])
        self.assertEqual(self.ids([".github/workflows/a.yml"]), ["always", "workflows"])
        self.assertEqual(self.ids([]), [])

    def test_all_lists_every_check_that_has_something_to_run(self):
        self.r.write("docs/A.md")
        # `prose` and `tool` pass {files}: with no matching file there is nothing to hand them
        self.assertEqual(self.ids([], every=True), ["always", "workflows", "guard"])
        self.assertEqual(self.ids(["docs/A.md"], every=True), ["always", "prose", "workflows", "guard"])

    def test_files_and_base_are_substituted(self):
        self.r.write("docs/A.md")
        self.r.write("B.md")
        steps = {s["id"]: s for s in focus.plan(self.r.root, ["docs/A.md", "B.md", "tools/x.py"], "origin/main")}
        self.assertEqual(steps["prose"]["argv"][-2:], ["docs/A.md", "B.md"])
        self.assertEqual(steps["guard"]["argv"][-1], "origin/main")
        self.assertEqual(steps["prose"]["matched"], 2)

    def test_a_deleted_file_still_owes_checks_but_is_not_passed_to_a_command(self):
        # docs/Gone.md is in the change and not on disk
        steps = {s["id"]: s for s in focus.plan(self.r.root, ["docs/Gone.md"], "main")}
        self.assertIn("always", steps)
        self.assertIn("guard", steps)
        self.assertNotIn("prose", steps)

    def test_sibling_tests(self):
        for rel in ("tools/thing.py", "tools/test_thing.py", "tools/fleet-config.py", "tools/test_fleet_config.py",
                    "tools/jev/loop.py", "tools/test_jev_loop.py", "tools/weekly/stages.py", "tools/test_weekly.py",
                    ".github/scripts/dash-gen/atlas.py", ".github/scripts/dash-gen/test_atlas.py", "tools/lonely.py",
                    "tools/console/pr_queue.py", "tools/console/test_pr_queue.py", "docs/thing.py"):
            self.r.write(rel)
        found = focus.sibling_tests(self.r.root, ["tools/thing.py", "tools/fleet-config.py", "tools/jev/loop.py",
                                                  "tools/weekly/stages.py", ".github/scripts/dash-gen/atlas.py",
                                                  "tools/lonely.py", "tools/console/pr_queue.py", "docs/thing.py",
                                                  "tools/test_thing.py", "tools/gone.py"])
        self.assertEqual(found, {
            ".github/scripts/dash-gen/test_atlas.py": [".github/scripts/dash-gen/atlas.py"],
            "tools/console/test_pr_queue.py": ["tools/console/pr_queue.py"],
            "tools/test_fleet_config.py": ["tools/fleet-config.py"],
            "tools/test_jev_loop.py": ["tools/jev/loop.py"],
            "tools/test_thing.py": ["tools/thing.py", "tools/test_thing.py"],
            "tools/test_weekly.py": ["tools/weekly/stages.py"],
        })
        self.assertEqual(self.ids(["tools/jev/loop.py"]), ["always", "test:tools/test_jev_loop.py"])

    def test_a_test_the_registry_already_names_runs_once(self):
        self.r.write(focus.REGISTRY, REGISTRY + """\
  - id: loop
    title: The loop runner
    run: python3 tools/test_jev_loop.py
    paths:
      - tools/jev/loop*.py
""")
        for rel in ("tools/jev/loop.py", "tools/jev/loop_publish.py", "tools/test_jev_loop.py"):
            self.r.write(rel)
        self.assertEqual(self.ids(["tools/jev/loop.py", "tools/jev/loop_publish.py", "tools/test_jev_loop.py"]), ["always", "loop"])


class RunTests(Case):
    def run_plan(self, files: list[str], keep_going: bool = False) -> list[dict]:
        with contextlib.redirect_stdout(io.StringIO()):
            return focus.run(self.r.root, focus.plan(self.r.root, files, "main"), keep_going)

    def test_a_missing_need_is_not_run_and_not_passed(self):
        self.r.write("tools/a.sh")
        results = {r["id"]: r["status"] for r in self.run_plan(["tools/a.sh"])}
        self.assertEqual(results, {"always": "passed", "tool": "not-run"})

    def test_stops_at_the_first_failure_unless_told_to_keep_going(self):
        self.r.write("docs/A.md")
        files = [".github/workflows/a.yml", "docs/A.md"]
        self.assertEqual([r["status"] for r in self.run_plan(files)], ["passed", "passed", "failed"])
        self.assertEqual([r["status"] for r in self.run_plan(files, keep_going=True)], ["passed", "passed", "failed", "passed"])

    def test_cli_exit_codes(self):
        self.r.init()

        def cli(*args: str) -> tuple[int, str]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = focus.main(["--root", str(self.r.root), "--base", "main", *args])
            return code, out.getvalue()

        self.assertEqual(cli("--run")[0], 0)  # nothing changed, nothing owed
        self.r.write("docs/A.md")
        code, out = cli()
        self.assertEqual(code, 0)
        self.assertIn("3 check(s) owed", out)
        self.assertEqual(cli("--run")[0], 0)
        self.r.write(".github/workflows/a.yml")
        code, out = cli("--run", "--keep-going")
        self.assertEqual(code, 1)
        self.assertIn("3 passed, 1 failed, 0 not run", out)
        self.assertEqual(cli("--run", "--only", "prose")[0], 0)
        self.assertEqual(cli("--only", "nope")[0], 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(focus.main(["--root", str(self.r.root), "--base", "no-such-ref"]), 2)


class ExcerptTests(unittest.TestCase):
    def test_a_failure_in_the_middle_of_a_long_report_is_shown(self):
        report = "\n".join([*(f"ok   test_{i}" for i in range(100)), "FAIL test_the_one_that_broke: 2 != 3",
                             *(f"ok   test_{i}" for i in range(100, 148)), "148/149 passed"])
        excerpt = focus.failure_excerpt(report)
        self.assertEqual(excerpt[0], "FAIL test_the_one_that_broke: 2 != 3")
        self.assertEqual(excerpt[-1], "148/149 passed")
        self.assertLessEqual(len(excerpt), 26)

    def test_a_short_report_is_shown_whole_once(self):
        self.assertEqual(focus.failure_excerpt("Traceback\nboom"), ["Traceback", "boom"])


class ChangeTests(Case):
    def test_committed_staged_unstaged_untracked_and_deleted(self):
        for rel in ("a.txt", "b.txt", "gone.txt", "projects/sub/x.txt"):
            self.r.write(rel)
        self.r.init()
        self.r.write("committed.txt")
        self.r.git("add", "committed.txt")
        self.r.git("commit", "-q", "-m", "one")
        self.r.write("staged.txt")
        self.r.git("add", "staged.txt")
        self.r.write("a.txt", "changed\n")
        self.r.write("untracked.txt")
        self.r.write("projects/sub/x.txt", "a submodule's file is not the hub's change\n")
        (self.r.root / "gone.txt").unlink()
        self.assertEqual(focus.changed_files(self.r.root, "main"),
                         ["a.txt", "committed.txt", "gone.txt", "staged.txt", "untracked.txt"])

    def test_base_falls_back_to_main_and_a_missing_one_is_an_error(self):
        self.r.init()
        self.assertEqual(focus.resolve_base(self.r.root, None), "main")
        with self.assertRaises(focus.RegistryError):
            focus.resolve_base(self.r.root, "no-such-ref")


class RegistryTests(Case):
    def test_malformed_registries_are_refused(self):
        bad = [
            "",
            "schema: other/v1\nchecks: []\n",
            "schema: checks/v1\nchecks:\n  - id: a\n    title: t\n    run: x\n",  # no paths
            "schema: checks/v1\nchecks:\n  - id: A b\n    title: t\n    run: x\n    paths: ['**']\n",
            "schema: checks/v1\nchecks:\n  - id: a\n    title: t\n    run: x\n    paths: ['**']\n  - id: a\n    title: t\n    run: x\n    paths: ['**']\n",
            "schema: checks/v1\nchecks:\n  - id: a\n    title: t\n    run: x {files}\n    paths: ['**']\n",  # every file to one command
            "schema: checks/v1\nchecks:\n  - id: a\n    title: ''\n    run: x\n    paths: ['**']\n",
        ]
        for text in bad:
            self.r.write(focus.REGISTRY, text)
            with self.assertRaises(focus.RegistryError, msg=text):
                focus.load_registry(self.r.root)


class LiveRegistryTests(unittest.TestCase):
    """_data/checks.yml against the tree: a check that names a tool that is gone would pass nothing."""

    def setUp(self):
        self.checks = focus.load_registry(HUB)

    def test_every_command_names_something_that_exists(self):
        for c in self.checks:
            argv = shlex.split(c["run"])
            if argv[0] == "python3":
                if argv[1] == "-m":
                    self.assertTrue((HUB / Path(*argv[2].split("."))).is_dir() or (HUB / (argv[2].replace(".", "/") + ".py")).is_file(),
                                    f"{c['id']}: module {argv[2]} not found")
                else:
                    self.assertTrue((HUB / argv[1]).is_file(), f"{c['id']}: {argv[1]} not found")
            elif "/" in argv[0]:
                self.assertTrue((HUB / argv[0]).is_file(), f"{c['id']}: {argv[0]} not found")
            else:
                self.assertIn("needs", c, f"{c['id']}: `{argv[0]}` is not a hub tool, so the check must declare `needs:`")

    def test_every_pattern_compiles_and_the_hub_gates_cover_every_change(self):
        for c in self.checks:
            for pattern in (*c["paths"], *c.get("files", [])):
                focus.glob_to_regex(pattern)
        every = {c["id"] for c in self.checks if c["paths"] == ["**"]}
        self.assertLessEqual({"drift", "schema"}, every)

    def test_this_tool_and_the_structure_contract_are_in_their_own_plan(self):
        ids = [s["id"] for s in focus.plan(HUB, ["tools/focus.py", "tools/architecture.py"], "main")]
        self.assertIn("architecture", ids)
        self.assertIn("test:tools/test_focus.py", ids)
        self.assertIn("test:tools/test_architecture.py", ids)


if __name__ == "__main__":
    unittest.main()

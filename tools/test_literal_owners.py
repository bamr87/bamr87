#!/usr/bin/env python3
"""Tests for tools/literal_owners.py — the literal owners the framework's code
carries, counted against a baseline that only shrinks (ADR 0011 decision 2).
A made-up instance on a throwaway tree proves each rule; the live tree is
measured only to prove that nothing fails on it: the tool is report only.
Offline, no pytest:  python3 tools/test_literal_owners.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import literal_owners as lo  # noqa: E402
from fleetcore import identity  # noqa: E402

HUB = Path(__file__).resolve().parent.parent

SETTINGS = {"hub": {"repo": "acme/control", "owners": ["acme", "acme-labs"]}}
HEAD = """\
# A comment the writer must keep.
schema: literal-owners/v1
enforce: {enforce}
roots: [tools, kits]
measured: [gen]
allow:
  - id: uses-ref
    pattern: '{{framework}}/[A-Za-z0-9_./-]+@[A-Za-z0-9_./-]+'
    why: A workflow or action called at a ref is the framework's address.
  - id: tracker-ref
    pattern: '{{framework}}(?:#[0-9]+|/(?:issues|pull)/[0-9]+)'
    why: A link to the framework's tracker.
# Written by the tool. Keep this the last key.
baseline:
"""


def write(root: Path, rel: str, text: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


def contract_text(enforce: bool = False, files: dict | None = None) -> str:
    rows = "".join(f"    {path}: {n}\n" for path, n in sorted((files or {}).items()))
    return HEAD.format(enforce=str(enforce).lower()) + (f"  files:\n{rows}" if rows else "  files: {}\n")


def tree(root: Path, enforce: bool = False, files: dict | None = None, settings: dict | None = SETTINGS) -> Path:
    """A framework checkout: settings, a contract, and source that names its owners."""
    if settings is not None:
        write(root, "_data/fleet.yml", yaml.safe_dump(settings))
    write(root, lo.CONTRACT, contract_text(enforce, files))
    write(root, "tools/a.py", 'HUB = "acme/control"\nURL = "https://github.com/acme/site"\n'
                              '# uses: acme/control/.github/workflows/ci.yml@v2 (acme/control#12)\nALSO = "acme/control"\n')
    write(root, "tools/clean.py", "print('no owner here')\n")
    write(root, "tools/test_a.py", 'FIXTURE = "acme/control", "acme/x", "acme-labs/y"\n')
    write(root, "tools/fixtures/run.yml", "repo: acme/control\n")
    write(root, "tools/node_modules/m.js", "acme/control\n")
    write(root, "tools/vendor/v.js", "acme/control\n")
    write(root, "tools/logo.png", b"\x89PNG\xff\xfe acme/control \x00")
    write(root, "kits/ci/workflow.yml", "jobs:\n  ci:\n    uses: acme/control/.github/workflows/ci.yml@v2\n")
    write(root, "kits/seed.yml", "repo: acme-labs/__PROJECT_NAME__\n")
    write(root, "gen/g.py", 'DEFAULT = "acme/control"\n')
    write(root, "docs/guide.md", "acme/control is documented here, outside every root.\n")
    return root


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = lo.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = tree(Path(self._tmp.name) / "fw")

    def contract(self) -> dict:
        return lo.load_contract(self.root)

    def held(self) -> dict:
        return lo.held(lo.measure(self.root, self.contract()))


class MatcherTests(unittest.TestCase):
    CONTRACT = yaml.safe_load(contract_text())

    def kinds(self, text: str, repo: str = "acme/control", framework: str | None = None) -> list[str]:
        who = identity.from_settings({"hub": {"repo": repo, "owners": ["acme", "acme-labs"]}})
        return [kind for kind, _ in lo.Matcher(who, framework or repo, self.CONTRACT).scan(text)]

    def test_each_occurrence_is_one_kind(self):
        for text, want in (
            ('HUB = "acme/control"', ["hub"]),
            ("clone https://github.com/acme/control.git", ["hub"]),
            ("It lives in acme/control.", ["hub"]),
            ("see acme/control/tree/main/docs", ["hub"]),
            ("ACME/Control", ["hub"]),
            ("https://github.com/acme/site", ["owner"]),
            ("acme-labs/thing and acme/thing", ["owner", "owner"]),
            ("import x from '@acme/pkg'", ["owner"]),
            ("slug=acme/${name}", ["owner"]),
            ("/home/acme/work", ["owner"]),
            ("uses: acme/control/.github/workflows/ci.yml@v2", ["uses-ref"]),
            ("uses: acme/control/.github/actions/run@main", ["uses-ref"]),
            ("fixed in acme/control#12", ["tracker-ref"]),
            ("https://github.com/acme/control/pull/7 and https://github.com/acme/control/issues/8", ["tracker-ref", "tracker-ref"]),
        ):
            self.assertEqual(self.kinds(text), want, text)

    def test_a_longer_name_is_not_the_hub_and_not_the_owner(self):
        self.assertEqual(self.kinds("acme/control-archive"), ["owner"], "another repo of the owner, not the hub")
        self.assertEqual(self.kinds("acme/control.github.io"), ["owner"])
        for text in ("macme/control", "x-acme/control", "x_acme/control", "acmes/control", "acme-labsx/y", "acme", "acme-labs", "acme /x"):
            self.assertEqual(self.kinds(text), [], text)

    def test_a_reference_the_framework_address_covers_is_counted_once(self):
        # The hub of the instance this tree belongs to is named like its owner.
        self.assertEqual(self.kinds("uses: acme/acme/.github/workflows/ci.yml@v2", repo="acme/acme"), ["uses-ref"])
        self.assertEqual(self.kinds("acme/acme/docs/X.md", repo="acme/acme"), ["hub"])
        self.assertEqual(self.kinds("acme/acme", repo="acme/acme"), ["hub"])
        self.assertEqual(self.kinds("/home/acme/acme-archive/x", repo="acme/acme"), ["owner"])

    def test_only_the_framework_address_is_allowed(self):
        # Once the framework has an address of its own, the instance's hub is no longer it.
        text = "uses: acme/control/.github/workflows/ci.yml@v2 and uses: fw/stack/.github/workflows/ci.yml@v2"
        self.assertEqual(self.kinds(text, framework="fw/stack"), ["hub"], "the hub's slug is held; another owner's address is not ours to count")
        self.assertEqual(self.kinds("uses: acme/shared/.github/workflows/ci.yml@v1"), ["owner"], "a reusable workflow in another repo is not the framework's address")


class MeasureTests(Fixture):
    def test_what_is_held_is_source_under_the_roots(self):
        m = lo.measure(self.root, self.contract())
        self.assertEqual(self.held(), {"tools/a.py": 3, "kits/seed.yml": 1})
        a = m["files"]["tools/a.py"]
        self.assertEqual((a["counts"], a["lines"], a["held"]), ({"hub": 2, "owner": 1, "uses-ref": 1, "tracker-ref": 1}, [1, 2, 4], True))
        self.assertEqual(m["files"]["kits/ci/workflow.yml"]["counts"], {"uses-ref": 1}, "counted, and nothing of it is held")
        self.assertNotIn("tools/clean.py", m["files"])
        self.assertEqual((m["hub"], m["framework"], m["owners"]), ("acme/control", "acme/control", ["acme", "acme-labs"]))

    def test_tests_and_fixtures_are_counted_apart_and_never_held(self):
        m = lo.measure(self.root, self.contract())
        for path in ("tools/test_a.py", "tools/fixtures/run.yml"):
            self.assertTrue(m["files"][path]["test"], path)
            self.assertFalse(m["files"][path]["held"], path)
        tools = next(d for d in lo.by_directory(m) if d["dir"] == "tools")
        self.assertEqual((tools["files"], tools["hub"], tools["owner"], tools["framework"]), (1, 2, 1, {"uses-ref": 1, "tracker-ref": 1}))
        self.assertEqual(tools["tests"], {"files": 2, "occurrences": 4})
        for name in ("test_x.py", "conftest.py", "a.test.ts", "a.spec.tsx", "tests/x.py", "pkg/fixtures/deep/x.yml", "__tests__/x.js"):
            self.assertTrue(lo.is_test(Path("tools") / name), name)
        for name in ("x.py", "latest.py", "contest.py", "testing/x.py"):
            self.assertFalse(lo.is_test(Path("tools") / name), name)

    def test_a_measured_directory_is_counted_and_not_held(self):
        m = lo.measure(self.root, self.contract())
        self.assertEqual((m["files"]["gen/g.py"]["counts"], m["files"]["gen/g.py"]["held"]), ({"hub": 1}, False))
        gen = next(d for d in lo.by_directory(m) if d["dir"] == "gen")
        self.assertEqual((gen["held"], gen["hub"]), (False, 1))

    def test_what_is_outside_the_directories_or_is_not_source_is_not_read(self):
        m = lo.measure(self.root, self.contract())
        for path in ("docs/guide.md", "tools/node_modules/m.js", "tools/vendor/v.js", "tools/logo.png", "_data/fleet.yml"):
            self.assertNotIn(path, m["files"], path)
        self.assertEqual(m["unread"], 1, "the image is not text")

    def test_the_owners_come_from_the_settings_and_never_from_the_environment(self):
        os.remove(self.root / "_data" / "fleet.yml")
        with mock.patch.dict(os.environ, {identity.ENV_REPO: "acme/control"}):
            with self.assertRaises(lo.ContractError) as caught:
                lo.measure(self.root, self.contract())
        self.assertIn("no owner to look for", str(caught.exception))

    def test_a_framework_address_in_the_settings_is_the_one_allowed(self):
        write(self.root, "_data/fleet.yml", yaml.safe_dump({**SETTINGS, "framework": {"repo": "fw/stack"}}))
        m = lo.measure(self.root, self.contract())
        self.assertEqual(m["framework"], "fw/stack")
        self.assertEqual(self.held()["tools/a.py"], 5, "the hub's own slug is an instance's identity once the framework has another address")

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_in_a_git_checkout_an_ignored_file_is_not_counted_and_a_new_one_is(self):
        git = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.test"]
        if subprocess.run([*git, "init", "-q"], capture_output=True, check=False).returncode != 0:
            self.skipTest("git init failed here")
        write(self.root, ".gitignore", "tools/out/\n")
        subprocess.run([*git, "add", "-A", "."], capture_output=True, check=True)
        write(self.root, "tools/out/bundle.js", "acme/control acme/control\n")
        write(self.root, "tools/new.py", 'X = "acme/control"\n')
        got = self.held()
        self.assertEqual(got.get("tools/new.py"), 1, "a file not yet committed is counted")
        self.assertNotIn("tools/out/bundle.js", got, "a build's output is not")
        self.assertNotIn("tools/vendor/v.js", got, "a tracked vendor copy is another repo's text")


class BaselineTests(Fixture):
    def test_compare_names_what_is_new_over_lower_and_gone(self):
        got = lo.compare({"a": 3, "b": 2, "c": 1, "d": 4}, {"b": 2, "c": 5, "d": 1, "e": 7})
        self.assertEqual(got, {"new": {"a": 3}, "over": {"d": {"now": 4, "baseline": 1}},
                               "under": {"c": {"now": 1, "baseline": 5}}, "gone": {"e": 7}})

    def test_the_planned_baseline_lowers_and_drops_and_never_raises(self):
        files, refused = lo.planned_baseline({"a": 3, "b": 2, "c": 1, "d": 4}, {"b": 2, "c": 5, "d": 1, "e": 7}, accept_new=False)
        self.assertEqual(files, {"b": 2, "c": 1, "d": 1}, "c is lowered, e is dropped, d keeps its number, a is not added")
        self.assertEqual(len(refused), 2)
        self.assertIn("a has 3 and is not in the baseline", refused[0])
        self.assertIn("d has 4, over its number 1", refused[1])
        files, refused = lo.planned_baseline({"a": 3, "d": 4}, {"d": 1}, accept_new=True)
        self.assertEqual((files, len(refused)), ({"a": 3, "d": 1}, 1), "a new file is recorded only when asked; a raise never is")

    def test_writing_keeps_every_line_above_the_block(self):
        before = (self.root / lo.CONTRACT).read_text(encoding="utf-8")
        lo.write_baseline(self.root, {"tools/a.py": 3, "kits/seed.yml": 1})
        after = (self.root / lo.CONTRACT).read_text(encoding="utf-8")
        cut = before.index("baseline:")
        self.assertEqual(after[:cut], before[:cut])
        self.assertIn("# A comment the writer must keep.", after)
        self.assertEqual(lo.baseline_of(self.contract()), {"kits/seed.yml": 1, "tools/a.py": 3})
        lo.write_baseline(self.root, {})
        self.assertEqual(lo.baseline_of(self.contract()), {})

    def test_the_block_must_be_the_last_key_to_be_rewritten(self):
        path = self.root / lo.CONTRACT
        path.write_text(path.read_text(encoding="utf-8") + "later: 1\n", encoding="utf-8")
        with self.assertRaises(lo.ContractError):
            lo.write_baseline(self.root, {})


class CliTests(Fixture):
    def at(self, *argv):
        return run(*argv, "--root", str(self.root))

    def enforce(self, on: bool) -> None:
        path = self.root / lo.CONTRACT
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(f"enforce: {str(not on).lower()}", f"enforce: {str(on).lower()}"), encoding="utf-8")

    def test_report_counts_by_directory_and_never_fails(self):
        code, out, err = self.at("report")
        self.assertEqual((code, err), (0, ""))
        for needle in ("literal owners: acme acme-labs · hub acme/control · framework address acme/control", "report only",
                       "DIRECTORY", "uses-ref", "gen (counted only)", "held: 4 in 2 file(s) · baseline: 0 in 0 file(s)",
                       "2 new file(s), 0 over, 0 lower, 0 gone · 4 occurrence(s) a gate would refuse"):
            self.assertIn(needle, out)
        self.assertNotIn("tools/a.py", out, "the files are listed only when asked")
        self.assertIn("  new    tools/a.py: 3, not in the baseline", self.at("report", "--files")[1])

    def test_the_json_document(self):
        code, out, _ = self.at("report", "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["schema"], doc["enforce"]), (0, "literal-owners-report/v1", False))
        self.assertEqual(set(doc), {"schema", "enforce", "hub", "owners", "framework", "directories", "held", "baseline", "diff",
                                    "refused", "files", "unread"})
        self.assertEqual((doc["held"], doc["refused"]), ({"files": 2, "occurrences": 4}, 4))
        self.assertEqual([d["dir"] for d in doc["directories"]], ["tools", "kits", "gen"])

    def test_check_reports_and_exits_0_while_enforce_is_off(self):
        code, out, _ = self.at("check")
        self.assertEqual(code, 0, "report only: a new literal owner fails nothing")
        self.assertIn("  new    tools/a.py: 3, not in the baseline  lines 1, 2, 4", out)
        self.assertIn("4 occurrence(s) past the baseline", out)
        self.assertIn("report only (`enforce: false`", out)

    def test_enforced_the_same_findings_fail(self):
        self.enforce(True)
        code, out, _ = self.at("check")
        self.assertEqual(code, 1)
        self.assertIn("enforced", out)
        self.assertEqual(self.at("report")[0], 0, "the report itself never fails")

    def test_the_baseline_is_recorded_then_only_shrinks(self):
        self.enforce(True)
        code, out, _ = self.at("baseline")
        self.assertEqual(code, 1, "nothing is recorded without --accept-new")
        self.assertIn("not in the baseline (pass --accept-new to record it)", out)
        self.assertEqual(self.at("baseline", "--write", "--accept-new")[0], 0)
        self.assertEqual(lo.baseline_of(self.contract()), {"kits/seed.yml": 1, "tools/a.py": 3})
        code, out, _ = self.at("check")
        self.assertEqual((code, out), (0, "literal owners: at the baseline · enforced\n"))

        # One literal goes: the gain is held only once the baseline is lowered.
        write(self.root, "tools/a.py", 'HUB = "acme/control"\nURL = "https://github.com/acme/site"\n')
        code, out, _ = self.at("check")
        self.assertEqual(code, 1)
        self.assertIn("  lower  tools/a.py: 2, the baseline still allows 3", out)
        self.assertEqual(self.at("baseline", "--write")[0], 0)
        self.assertEqual(lo.baseline_of(self.contract())["tools/a.py"], 2)
        self.assertEqual(self.at("check")[0], 0)

        # One comes back, and a new file appears: neither is taken into the baseline.
        write(self.root, "tools/a.py", 'A = "acme/control"\nB = "acme/site"\nC = "acme/other"\n')
        write(self.root, "tools/b.py", 'B = "acme-labs/thing"\n')
        code, out, _ = self.at("check")
        self.assertEqual(code, 1)
        self.assertIn("  over   tools/a.py: 3, the baseline holds it to 2  lines 1, 2, 3", out)
        self.assertIn("  new    tools/b.py: 1, not in the baseline  lines 1", out)
        code, out, _ = self.at("baseline", "--write")
        self.assertEqual(code, 1)
        self.assertIn("over its number 2 (kept; a raise is a hand edit)", out)
        self.assertEqual(lo.baseline_of(self.contract()), {"kits/seed.yml": 1, "tools/a.py": 2}, "never raised, never added unasked")

        # The file goes: its entry is dropped.
        os.remove(self.root / "kits" / "seed.yml")
        self.assertIn("  gone   kits/seed.yml: none now, the baseline still allows 1", self.at("check")[1])
        self.at("baseline", "--write")
        self.assertNotIn("kits/seed.yml", lo.baseline_of(self.contract()))

    def test_a_contract_or_an_identity_that_cannot_be_read_is_exit_2(self):
        path = self.root / lo.CONTRACT
        good = path.read_text(encoding="utf-8")
        for bad, needle in (
            (good.replace("literal-owners/v1", "other/v9"), "expected `schema: literal-owners/v1`"),
            (good.replace("enforce: false", "enforce: maybe"), "`enforce:` must be true or false"),
            (good.replace("roots: [tools, kits]", "roots: []"), "`roots:` must be a list of directories, with at least one"),
            (good.replace("'{framework}(?:#", "'acme/control(?:#"), "must start with {framework}"),
            (good.replace("@[A-Za-z0-9_./-]+'", "@[A-Za-z0-9_./-'"), "is not a regular expression"),
            (good.replace("id: tracker-ref", "id: uses-ref"), "reserved or listed twice"),
            (good.replace("id: tracker-ref", "id: hub"), "reserved or listed twice"),
            (good.replace("files: {}", "files: {tools/a.py: 0}"), "baseline.files must map a path to a positive integer"),
            ("schema: [unclosed\n", "not readable YAML"),
        ):
            self.assertNotEqual(bad, good, needle)
            path.write_text(bad, encoding="utf-8")
            for cmd in ("report", "check", "baseline"):
                code, _, err = self.at(cmd)
                self.assertEqual(code, 2, f"{cmd}: {needle}")
                self.assertIn(needle, err)
        os.remove(path)
        self.assertIn("not found", self.at("report")[2])
        path.write_text(good, encoding="utf-8")
        os.remove(self.root / "_data" / "fleet.yml")
        code, _, err = self.at("check")
        self.assertEqual(code, 2)
        self.assertIn("there is no owner to look for", err)


class LiveTreeTests(unittest.TestCase):
    """The committed contract, on this checkout. Nothing here depends on how many literal owners the
    tree holds today: other changes add and remove them, and the count is reported, never failed."""

    def test_the_committed_contract_is_report_only(self):
        contract = lo.load_contract(HUB)
        self.assertIs(contract["enforce"], False, "turning the gate on is a change the maintainer reviews, with this line")
        self.assertEqual(contract["roots"], ["templates", "tools", ".github/workflows", ".github/actions", "specs"],
                         "the five directories ADR 0011 decision 2 names")
        self.assertTrue(lo.baseline_of(contract), "a baseline is recorded")

    def test_nothing_fails_on_the_live_tree(self):
        for cmd in ("check", "report"):
            code, out, err = run(cmd)
            self.assertEqual((code, err), (0, ""), cmd)
            self.assertIn("report only", out)

    def test_the_contract_the_tool_and_the_resolver_name_no_owner(self):
        m = lo.measure(HUB, lo.load_contract(HUB))
        self.assertTrue(m["owners"], "the committed settings name the owners to look for")
        for path in ("tools/literal_owners.py", "tools/fleetcore/identity.py"):
            self.assertNotIn(path, m["files"], f"{path} writes an owner out: it reads owners, it holds none")
        text = (HUB / lo.CONTRACT).read_text(encoding="utf-8").lower()
        for owner in m["owners"]:
            self.assertNotIn(f"{owner}/", text, f"{lo.CONTRACT} names the owner '{owner}'")


if __name__ == "__main__":
    unittest.main()

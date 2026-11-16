#!/usr/bin/env python3
"""
Tests for tools/voices.py — the fleet voice model and the console's Voices editor
(constitution § 23 rule 7; the filer is the OPS remote-write path, § 11.8).

  * the canonical file passes `check`, and `render` reproduces it byte for byte,
    so an edit's diff is the edit and nothing else; awkward strings survive a
    render → load round trip;
  * `check` surfaces schema errors (types, enums, required and unknown keys)
    and the references the schema cannot express;
  * the editor document reports drift from origin/main (same, differs, unknown);
  * `preview` writes nothing — not the file, the index, a ref or the remote;
  * `pr` without --apply pushes nothing; with --apply it is refused without the
    plan id, with --scheduled, with a dirty engine, a refused token, a moved
    main, an open voices PR or an unreadable dedupe, a taken branch — and
    otherwise pushes ONE branch whose only change is _data/voices/voices.yml
    and opens ONE draft PR, leaving the checkout as it was.

Every git operation runs against a throwaway repository and a local bare
"origin"; GitHub is a fake. Stdlib + PyYAML:

    python3 tools/test_voices.py
"""
from __future__ import annotations

import copy
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("voices", HERE / "voices.py")
voices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voices)
sys.path.insert(0, str(ROOT))
from tools.jev.common import Run  # noqa: E402

CANON = (ROOT / voices.REL).read_text()
GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def data() -> dict:
    return yaml.safe_load(CANON)


class Hub:
    """A throwaway hub: the voice files and the engine committed on main, pushed to a bare origin."""

    def __init__(self, tmp: Path):
        self.origin = tmp / "origin.git"
        self.root = tmp / "hub"
        git(tmp, "init", "-q", "--bare", str(self.origin))
        git(tmp, "init", "-q", str(self.root))
        for rel in (voices.REL, voices.SCHEMA_REL, "tools/voices.py"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, self.root / rel)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed")
        git(self.root, "remote", "add", "origin", str(self.origin))
        git(self.root, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.root, "fetch", "-q", "origin")

    def refs(self) -> str:
        return git(self.origin, "for-each-ref")

    def state(self) -> tuple:
        """Everything a preview must not touch: the file, the index and tree status, every ref here and there."""
        return ((self.root / voices.REL).read_bytes(), git(self.root, "status", "--porcelain"),
                git(self.root, "for-each-ref"), self.refs(), git(self.root, "worktree", "list"))

    def move_main(self, text: str) -> None:
        """Someone else lands a change to voices.yml on main."""
        other = self.root.parent / "other"
        git(self.root.parent, "clone", "-q", str(self.origin), str(other))
        (other / voices.REL).write_text(text)
        git(other, "commit", "-q", "-am", "elsewhere")
        git(other, "push", "-q", "origin", "HEAD:main")


class FakeGh:
    def __init__(self, open_prs: str = "[]", refs: str = "[]", list_ok: bool = True):
        self.calls: list[list[str]] = []
        self.open_prs, self.refs_out, self.list_ok = open_prs, refs, list_ok

    def __call__(self, args, env=None, timeout=None, cwd=None):
        self.calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return Run(0, self.open_prs, "") if self.list_ok else Run(1, "", "HTTP 401")
        if args[0] == "api":
            return Run(0, self.refs_out, "")
        if args[:2] == ["pr", "create"]:
            body = Path(args[args.index("--body-file") + 1]).read_text()
            self.body = body
            return Run(0, "https://github.com/bamr87/bamr87/pull/9999\n", "")
        raise AssertionError(f"unexpected gh call {args}")

    def created(self) -> list[str] | None:
        return next((c for c in self.calls if c[:2] == ["pr", "create"]), None)


def ok_probe():
    return {}, "tester (fake)"


def edited(d: dict | None = None) -> dict:
    d = copy.deepcopy(d or data())
    d["sites"]["lifehacker.dev"]["personas"]["kit"]["tone"] = "candid, caffeinated"
    return d


class RenderAndCheck(unittest.TestCase):
    def test_canonical_file_passes_check(self):
        self.assertEqual(voices.check(data()), [])

    def test_render_round_trips_the_canonical_file_byte_for_byte(self):
        self.assertEqual(voices.render(data(), voices.header_of(CANON)), CANON)

    def test_an_edit_changes_only_its_own_line(self):
        out = voices.render(edited(), voices.header_of(CANON))
        changed = [ln for ln in voices.diff(CANON, out).splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
        self.assertEqual(changed, ['-        tone: "candid, energetic"', '+        tone: "candid, caffeinated"'])

    def test_awkward_strings_survive_a_round_trip(self):
        d = data()
        site = d["sites"]["lifehacker.dev"]
        site["personas"]["odd"] = {
            "name": 'Quo"te \\ back', "role": "yes", "enabled": False, "perspective": "a: b # not a comment",
            "tone": "line break\x85next", "voice": "- leading dash", "beats": ["1.0", "on", "with space", "ok-1"],
            "repos": ["bamr87/zer0-CMS"], "bans": [{"name": "hype", "pattern": "(?i)revolutionary|game-changer", "level": "error"}],
            "lifts": ["hype"], "limits": {"max_words": 900}, "examples": ["Tab\there", "emoji \U0001F600"],
            "topics": {"cover": [], "exclude": ["a,b", "[x]"]}, "style": {"humor": "dry"},
        }
        site["assignment"].insert(0, {"repos": ["bamr87/x"], "cadence": "daily", "persona": "odd"})
        d["sites"]["zer0.example"] = {"profile": {}}
        text = voices.render(d, "# header")
        self.assertEqual(yaml.safe_load(text), d)
        self.assertTrue(text.startswith("# header\nschema: voices/v1\n"))
        self.assertEqual(voices.check(d), [])

    def test_check_surfaces_schema_errors(self):
        cases = [
            (lambda d: d["sites"]["lifehacker.dev"]["personas"]["kit"]["style"].update(humor="loud"),
             "personas.kit.style.humor: 'loud' not in"),
            (lambda d: d["sites"]["lifehacker.dev"]["personas"]["kit"].update(enabled="yes"),
             "personas.kit.enabled: must be true or false"),
            (lambda d: d["sites"]["lifehacker.dev"]["personas"]["kit"].update(mood="x"), "unknown key 'mood'"),
            (lambda d: d["sites"]["lifehacker.dev"]["personas"]["tess"].pop("name"), "personas.tess: missing name"),
            (lambda d: d["defaults"].update(name="x"), "defaults: unknown key 'name'"),
            (lambda d: d["defaults"]["topics"].update(cover="docs"), "defaults.topics.cover: must be a list"),
            (lambda d: d["sites"]["lifehacker.dev"]["assignment"].append({"cadence": "hourly", "persona": "kit"}),
             "cadence: 'hourly' not in"),
            (lambda d: d.update(schema="voices/v2"), "must be 'voices/v1'"),
            (lambda d: d.update(extra=1), "unknown key 'extra'"),
            (lambda d: d["sites"].update(bare={}), "sites.bare: missing profile"),
        ]
        for mutate, needle in cases:
            d = data()
            mutate(d)
            errs = voices.check(d)
            self.assertTrue(any(needle in e for e in errs), (needle, errs))

    def test_check_holds_the_references(self):
        d = data()
        rules = d["sites"]["lifehacker.dev"]["assignment"]
        rules.insert(0, {"activity": ["x"], "persona": "nobody"})
        rules.insert(1, {"activity": ["y"]})
        errs = voices.check(d)
        self.assertTrue(any("assignment[0]: unknown persona 'nobody'" in e for e in errs), errs)
        self.assertTrue(any("assignment[1]: names no persona" in e for e in errs), errs)
        d = data()
        d["sites"]["lifehacker.dev"]["assignment"].append({"activity": ["late"], "persona": "kit"})
        self.assertTrue(any("default rule must be the last" in e for e in voices.check(d)))

    def test_enums_come_from_the_schema(self):
        e = voices.enums()
        self.assertEqual(e["cadence"], ["daily", "weekly"])
        self.assertIn("satirical", e["style"]["humor"])


class EditorDocuments(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-voices-"))
        self.hub = Hub(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_drift_from_main_is_detected(self):
        doc = voices.editor_doc(self.hub.root)
        self.assertTrue(doc["ok"] and doc["canonical"] and doc["drift"]["available"])
        self.assertFalse(doc["drift"]["differs"])
        (self.hub.root / voices.REL).write_text(voices.render(edited(), voices.header_of(CANON)))
        doc = voices.editor_doc(self.hub.root)
        self.assertTrue(doc["drift"]["differs"], doc["drift"])
        self.assertEqual(doc["drift"]["changes"], ["sites.lifehacker.dev.personas.kit.tone"])
        self.assertIn("+        tone: \"candid, caffeinated\"", doc["drift"]["diff"])
        git(self.hub.root, "remote", "remove", "origin")
        doc = voices.editor_doc(self.hub.root)
        self.assertFalse(doc["drift"]["available"])
        self.assertFalse(doc["drift"]["differs"])

    def test_the_editor_doc_shows_the_files_check_errors(self):
        bad = CANON.replace("humor: satirical", "humor: slapstick")
        (self.hub.root / voices.REL).write_text(bad)
        doc = voices.editor_doc(self.hub.root)
        self.assertFalse(doc["ok"])
        self.assertTrue(any("'slapstick' not in" in e for e in doc["errors"]), doc["errors"])
        (self.hub.root / voices.REL).write_text("schema: [unclosed\n")
        doc = voices.editor_doc(self.hub.root)
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["data"])
        self.assertTrue(doc["errors"][0].startswith("not valid YAML"), doc["errors"])

    def test_preview_writes_nothing_and_binds_a_plan_id(self):
        before = self.hub.state()
        p = voices.preview(edited(), self.hub.root)
        self.assertEqual(self.hub.state(), before, "a preview wrote something")
        self.assertTrue(p["ok"] and p["changed"])
        self.assertEqual(p["base"], "origin/main")
        self.assertEqual(p["changes"], ["sites.lifehacker.dev.personas.kit.tone"])
        self.assertRegex(p["plan_id"], voices.PLAN_RX)
        self.assertEqual(voices.preview(edited(), self.hub.root)["plan_id"], p["plan_id"], "the plan id is deterministic")
        self.assertNotEqual(voices.preview(data(), self.hub.root)["plan_id"], p["plan_id"])
        self.assertFalse(voices.preview(data(), self.hub.root)["changed"])
        bad = edited()
        bad["sites"]["lifehacker.dev"]["personas"]["kit"]["style"]["length"] = "epic"
        p = voices.preview(bad, self.hub.root)
        self.assertFalse(p["ok"])
        self.assertTrue(any("'epic' not in" in e for e in p["errors"]))
        self.assertEqual(self.hub.state(), before)


class Filer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-voices-pr-"))
        self.hub = Hub(self.tmp)
        self.text = voices.render(edited(), voices.header_of(CANON))
        self.plan = voices.preview(edited(), self.hub.root)["plan_id"]
        self.out: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file(self, plan="<plan>", **kw):
        kw.setdefault("gh", FakeGh())
        kw.setdefault("probe", ok_probe)
        self.gh = kw["gh"]
        return voices.file_pr(self.text, self.plan if plan == "<plan>" else plan, root=self.hub.root,
                              repo="bamr87/bamr87", today="2026-11-15", say=self.out.append, **kw)

    def test_a_dry_run_shows_the_diff_and_pushes_nothing(self):
        before = self.hub.state()
        res = self.file(apply=False)
        self.assertEqual(res["status"], "dry-run", res)
        self.assertEqual(res["plan_id"], self.plan, "the dry run and the console's preview agree")
        self.assertTrue(any('+        tone: "candid, caffeinated"' in line for line in self.out), self.out)
        self.assertEqual(self.hub.state(), before)
        self.assertEqual(self.gh.calls, [])

    def test_apply_is_refused_before_any_write(self):
        before = self.hub.refs()
        self.assertIn("--scheduled", self.file(apply=True, scheduled=True)["reason"])
        self.assertIn("--plan-id", self.file(plan=None, apply=True)["reason"])
        self.assertIn("--plan-id", self.file(plan="not-a-plan", apply=True)["reason"])
        res = self.file(apply=True, probe=lambda: (None, "the publish token was refused by `gh api user`"))
        self.assertIn("refused by `gh api user`", res["reason"])
        res = self.file(apply=True, gh=FakeGh(list_ok=False))
        self.assertIn("never filed without the dedupe", res["reason"])
        res = self.file(apply=True, gh=FakeGh(open_prs='[{"number": 7, "url": "u", "headRefName": "chore/voices-2026-11-01-aaaa"}]'))
        self.assertIn("an open voices PR exists (#7", res["reason"])
        branch = f"chore/voices-2026-11-15-{self.plan[:8]}"
        res = self.file(apply=True, gh=FakeGh(refs=f'[{{"ref": "refs/heads/{branch}"}}]'))
        self.assertIn("already exists", res["reason"])
        bad = self.text.replace("humor: satirical", "humor: slapstick")
        res = voices.file_pr(bad, self.plan, apply=True, root=self.hub.root, repo="bamr87/bamr87", gh=FakeGh(),
                             probe=ok_probe, say=self.out.append)
        self.assertIn("check error", res["reason"])
        self.assertEqual(self.hub.refs(), before, "a refusal pushed something")

    def test_a_dirty_engine_is_refused(self):
        (self.hub.root / "tools/voices.py").write_text("# edited\n")
        res = self.file(apply=True)
        self.assertEqual(res["status"], "refused")
        self.assertIn("engine is dirty", res["reason"])

    def test_a_moved_main_is_refused(self):
        self.hub.move_main(CANON.replace("Upbeat strategist", "Upbeat planner"))
        before = self.hub.refs()
        res = self.file(apply=True)
        self.assertEqual(res["status"], "refused", res)
        self.assertIn("preview again", res["reason"])
        self.assertEqual(self.hub.refs(), before)
        self.assertIsNone(self.gh.created())

    def test_apply_pushes_one_branch_and_one_draft_pr_that_change_only_voices_yml(self):
        before_local = (self.hub.root / voices.REL).read_bytes(), git(self.hub.root, "status", "--porcelain")
        res = self.file(apply=True)
        self.assertEqual(res["status"], "filed", (res, self.out))
        branch = f"chore/voices-2026-11-15-{self.plan[:8]}"
        self.assertEqual(res["branch"], branch)
        self.assertEqual(git(self.hub.origin, "diff", "--name-only", "main", branch).split(), [voices.REL])
        self.assertEqual(git(self.hub.origin, "show", f"{branch}:{voices.REL}"), self.text)
        self.assertEqual(git(self.hub.origin, "log", "-1", "--format=%an <%ae>", branch).strip(),
                         f"{voices.COMMIT_NAME} <{voices.COMMIT_EMAIL}>")
        heads = [ln.split()[-1] for ln in self.hub.refs().splitlines()]
        self.assertEqual(sorted(heads), sorted(["refs/heads/main", f"refs/heads/{branch}"]))
        created = self.gh.created()
        self.assertIsNotNone(created)
        for flag in ("--draft", "--base", "main", "--head", branch):
            self.assertIn(flag, created)
        self.assertIn("Governed by: § 23.7", self.gh.body)
        self.assertIn("sites.lifehacker.dev.personas.kit.tone", self.gh.body)
        self.assertEqual(((self.hub.root / voices.REL).read_bytes(), git(self.hub.root, "status", "--porcelain")),
                         before_local, "the checkout was touched")
        self.assertEqual(len(git(self.hub.root, "worktree", "list").splitlines()), 1, "the filing worktree was left")

    def test_nothing_to_file_when_the_bytes_equal_main(self):
        res = voices.file_pr(CANON, voices.plan_id(CANON, CANON), apply=True, root=self.hub.root, repo="bamr87/bamr87",
                             gh=FakeGh(), probe=ok_probe, say=self.out.append)
        self.assertEqual(res["status"], "nothing", res)


class Cli(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(HERE / "voices.py"), *args], capture_output=True, text=True,
                              env={**os.environ}, check=False)

    def test_check_and_render_on_the_hub_file(self):
        self.assertEqual(self.run_cli("check").returncode, 0)
        r = self.run_cli("render")
        self.assertEqual((r.returncode, r.stdout), (0, CANON))
        self.assertEqual(self.run_cli("assign", "lifehacker.dev", "cve").stdout.strip(), "vera")

    def test_pr_apply_without_a_plan_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "v.yml"
            f.write_text(voices.render(edited(), voices.header_of(CANON)))
            r = self.run_cli("pr", "--file", str(f), "--apply", "--scheduled")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('"status": "refused"', r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)

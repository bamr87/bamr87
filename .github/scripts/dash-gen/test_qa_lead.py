#!/usr/bin/env python3
"""Offline tests for qa_lead.py: QA Lead, the § 15 completeness review of major and frontend
pull requests, and how pr_review.py posts it.

A fake GitHub answers every read and records every write; no model is called.

Usage: python3 .github/scripts/dash-gen/test_qa_lead.py
"""
from __future__ import annotations

import io
import itertools
import json
import re
import sys
import unittest
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_review as P  # noqa: E402
import qa_lead as Q  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REPO = "bamr87/bamr87"
SHA = "b" * 40
CFG = Q.config()
GOOD_BODY = """## Description

Adds the overview page.

## Test evidence

- tools/console/test_pages.py: the new route renders

CI: https://github.com/bamr87/bamr87/actions/runs/111

## Visual evidence

![before](a.png) ![after](b.png) at desktop and mobile.

Feature index: n/a — the page is already HUB-001's.

- [x] Documentation updated
"""


def fixture(**over) -> dict:
    facts = {"number": 7, "head_sha": SHA, "author": "bamr87", "private": False, "labels": [], "body": GOOD_BODY,
             "files": ["tools/console/web/src/pages/Overview.tsx", "tools/console/test_pages.py", "docs/CONSOLE.md"],
             "additions": 40, "deletions": 3, "ci_runs": [{"id": 111, "head_match": True, "conclusion": "success"}],
             "frontend_paths": []}
    facts.update(over)
    return facts


class FakeGh(P.Gh):
    """Routes reads from the facts; records every write. Never touches the network."""

    def __init__(self, facts: dict, reviews: list | None = None, notes: dict | None = None):
        super().__init__(REPO)
        self.facts, self.reviews, self.notes, self.writes = facts, reviews or [], notes, []

    def get(self, path):
        self.calls += 1
        n = self.facts["number"]
        if path == f"pulls/{n}":
            return {"head": {"sha": self.facts["head_sha"]}, "user": {"login": self.facts["author"]},
                    "base": {"ref": "main", "repo": {"private": self.facts["private"]}}, "body": self.facts["body"],
                    "labels": [{"name": x} for x in self.facts["labels"]], "additions": self.facts["additions"],
                    "deletions": self.facts["deletions"], "author_association": "OWNER", "draft": False}
        if path.startswith(f"pulls/{n}/files"):
            return [{"filename": f} for f in self.facts["files"]] if "page=1" in path else []
        if path.startswith(f"pulls/{n}/reviews"):
            return self.reviews if "page=1" in path else []
        if path.startswith("actions/runs/") and path.endswith("/artifacts?per_page=100"):
            return {"artifacts": [{"id": 5, "name": Q.NOTES_ARTIFACT, "size_in_bytes": 100}]} if self.notes else {"artifacts": []}
        if path.startswith("actions/runs/"):
            rid = int(path.split("/")[2])
            run = next((r for r in self.facts["ci_runs"] if r["id"] == rid), None)
            return {"head_sha": SHA if run and run["head_match"] else "c" * 40, "conclusion": run and run["conclusion"]}
        if path.startswith("contents/verify/verify.yml"):
            return None
        if path.startswith(f"commits/{SHA}/pulls"):
            return [{"number": n, "state": "open", "head": {"sha": SHA}}]
        return None

    def blob(self, path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("qa-lead-notes.json", json.dumps(self.notes))
        return buf.getvalue()

    def _run(self, *args, stdin=None):
        self.writes.append((args, json.loads(stdin) if stdin else None))
        return "{}"


def qa_run(conclusion="success") -> dict:
    return {"id": 99, "path": Q.WORKFLOW_PATH, "event": "pull_request", "head_sha": SHA, "conclusion": conclusion,
            "pull_requests": [{"number": 7}]}


class ClassifierTests(unittest.TestCase):
    """The deterministic gate on fixture diffs (§ 15.1, § 15.3)."""

    def test_frontend_glob_hit(self):
        c = Q.classify(["tools/console/web/src/App.tsx"], [], CFG)
        self.assertTrue(c["frontend"] and c["review"])
        self.assertFalse(c["major"])
        for path in ("_layouts/default.html", "index.html", "assets/css/main.scss", "_config.yml", "pages/about.md"):
            self.assertTrue(Q.classify([path], [], CFG)["frontend"], path)

    def test_major_label(self):
        c = Q.classify(["tools/whatever.py"], ["major"], CFG)
        self.assertTrue(c["major"] and c["review"])
        self.assertFalse(c["frontend"])
        self.assertIn("major: the `major` label", c["reasons"])

    def test_neither_is_skipped(self):
        c = Q.classify(["tools/whatever.py", "tools/test_whatever.py"], ["bug"], CFG, additions=30, deletions=2)
        self.assertEqual((c["major"], c["frontend"], c["review"]), (False, False, False))
        self.assertEqual(Q.decide({"files": ["tools/whatever.py"], "labels": []}, CFG)["status"], "skip")

    def test_interim_heuristics_flag_major(self):
        self.assertTrue(Q.classify(["docs/constitution.md"], [], CFG)["major"])
        self.assertTrue(Q.classify(["tools/x/requirements.txt"], [], CFG)["major"])
        self.assertTrue(Q.classify(["a.py"], [], CFG, additions=500)["major"])
        self.assertTrue(Q.classify([f"d{i}/x.py" for i in range(6)], [], CFG)["major"])

    def test_repo_frontend_paths_extend_the_globs(self):
        self.assertFalse(Q.classify(["app/views/home.erb"], [], CFG)["frontend"])
        self.assertTrue(Q.classify(["app/views/home.erb"], [], CFG, frontend_paths=["app/views/**"])["frontend"])


class ChecklistTests(unittest.TestCase):
    def lines(self, **over) -> dict:
        d = Q.decide(fixture(**over), CFG)
        return {x["key"]: x for x in d["lines"]} | {"_event": d["event"]}

    def test_every_line_is_present_and_a_complete_pr_passes(self):
        got = self.lines()
        self.assertEqual([k for k in got if k != "_event"], list(Q.LINES))
        self.assertTrue(all(got[k]["status"] == "pass" for k in Q.LINES), got)
        self.assertEqual(got["_event"], "COMMENT")

    def test_ci_must_be_green_and_of_the_head_commit(self):
        self.assertEqual(self.lines(ci_runs=[])["ci"]["status"], "gap")
        self.assertEqual(self.lines(ci_runs=[{"id": 1, "head_match": False, "conclusion": "success"}])["ci"]["status"], "gap")
        self.assertEqual(self.lines(ci_runs=[{"id": 1, "head_match": True, "conclusion": "failure"}])["ci"]["status"], "gap")

    def test_tests_line(self):
        body = GOOD_BODY.replace("## Test evidence\n\n- tools/console/test_pages.py: the new route renders\n", "")
        self.assertEqual(self.lines(body=body)["tests"]["status"], "gap")
        # a changed test file the body names is enough
        self.assertEqual(self.lines(body=body + "\nUpdated tools/console/test_pages.py.\n")["tests"]["status"], "pass")

    def test_visual_line_is_frontend_only(self):
        got = self.lines(files=["tools/dash", "tools/test_x.py", "docs/x.md"], labels=["major"])
        self.assertEqual(got["visual"]["status"], "n/a")

    def test_evidence_bundle_at_two_viewports_passes(self):
        body = GOOD_BODY.replace("![before](a.png) ![after](b.png) at desktop and mobile.", "See the bundle.")
        files = fixture()["files"] + ["test/evidence/overview/desktop-overview.png", "test/evidence/overview/mobile-overview.png"]
        self.assertEqual(self.lines(body=body, files=files)["visual"]["status"], "pass")
        one = fixture()["files"] + ["test/evidence/overview/desktop-overview.png"]
        self.assertEqual(self.lines(body=body, files=one)["visual"]["status"], "gap")

    def test_template_line(self):
        body = GOOD_BODY.replace("- [x] Documentation updated", "- [ ] Documentation updated")
        got = self.lines(body=body, files=["tools/console/web/src/pages/Overview.tsx", "tools/console/test_pages.py"])
        self.assertEqual(got["template"]["status"], "gap")
        body = GOOD_BODY.replace("Feature index: n/a — the page is already HUB-001's.", "")
        self.assertEqual(self.lines(body=body)["template"]["status"], "gap")
        self.assertEqual(self.lines(body=body, files=fixture()["files"] + ["features/features.d/x.yml"])["template"]["status"], "pass")


class SkipEvidenceTests(unittest.TestCase):
    """`skip-evidence` with a reason waives the visual line alone (docs/VERIFICATION.md); no other waiver."""
    NO_VISUAL = GOOD_BODY.replace("![before](a.png) ![after](b.png) at desktop and mobile.", "")

    def visual(self, body, labels):
        return {x["key"]: x for x in Q.decide(fixture(body=body, labels=labels), CFG)["lines"]}

    def test_label_with_reason_waives_visual(self):
        body = self.NO_VISUAL + "\nskip-evidence: only a type rename, nothing renders differently.\n"
        got = self.visual(body, ["skip-evidence"])
        self.assertEqual(got["visual"]["status"], "pass")
        self.assertIn("waived", got["visual"]["detail"])

    def test_label_without_reason_does_not(self):
        self.assertEqual(self.visual(self.NO_VISUAL, ["skip-evidence"])["visual"]["status"], "gap")
        self.assertEqual(self.visual(self.NO_VISUAL + "\nskip-evidence\n", ["skip-evidence"])["visual"]["status"], "gap")

    def test_reason_without_label_does_not(self):
        body = self.NO_VISUAL + "\nskip-evidence: only a type rename, nothing renders differently.\n"
        self.assertEqual(self.visual(body, [])["visual"]["status"], "gap")

    def test_it_waives_nothing_else(self):
        body = ("## Description\n\nx\n\nskip-evidence: waive everything please, tests and ci and docs too.\n")
        got = Q.decide(fixture(body=body, labels=["skip-evidence", "major"], ci_runs=[], files=["tools/console/web/a.tsx"]), CFG)
        lines = {x["key"]: x["status"] for x in got["lines"]}
        self.assertEqual(lines["visual"], "pass")
        self.assertEqual((lines["tests"], lines["ci"], lines["template"]), ("gap", "gap", "gap"))
        self.assertEqual(got["event"], "REQUEST_CHANGES")


class EventTests(unittest.TestCase):
    """Gaps request changes; nothing ever approves or merges."""

    def test_event_is_only_comment_or_request_changes(self):
        self.assertNotIn("APPROVE", Q.EVENTS)
        for statuses in itertools.product(("pass", "gap", "n/a"), repeat=4):
            lines = [{"key": k, "status": s, "detail": ""} for k, s in zip(Q.LINES, statuses)]
            event = Q.event_for(lines)
            self.assertIn(event, ("COMMENT", "REQUEST_CHANGES"))
            self.assertEqual(event == "REQUEST_CHANGES", "gap" in statuses)

    def test_posted_reviews_never_approve_or_merge(self):
        for facts in (fixture(), fixture(ci_runs=[]), fixture(author="github-actions[bot]")):
            gh = FakeGh(facts)
            Q.post(gh, qa_run(), False, "workflow_run", "https://x/run/1", say=lambda *_: None)
            for args, payload in gh.writes:
                self.assertNotIn("merge", " ".join(args))
                if payload and "event" in payload:
                    self.assertIn(payload["event"], ("COMMENT", "REQUEST_CHANGES", "DISMISS"))
        src = (Path(Q.__file__).read_text() + (ROOT / Q.WORKFLOW_PATH).read_text())
        self.assertNotRegex(src, r"""["']event["']:\s*["']APPROVE""")
        self.assertNotIn("/merge", src)

    def test_gap_posts_request_changes_once_per_commit_and_result(self):
        gh = FakeGh(fixture(ci_runs=[]))
        out = Q.post(gh, qa_run(), False, "workflow_run", "u", say=lambda *_: None)
        self.assertIn("REQUEST_CHANGES", out)
        posted = [p for a, p in gh.writes if p and p.get("event")]
        self.assertEqual([p["event"] for p in posted], ["REQUEST_CHANGES"])
        self.assertEqual(posted[0]["commit_id"], SHA)
        # the same result on the same commit is not posted twice
        gh2 = FakeGh(fixture(ci_runs=[]), reviews=[{"id": 1, "state": "CHANGES_REQUESTED", "body": posted[0]["body"]}])
        self.assertIn("already carries", Q.post(gh2, qa_run(), False, "workflow_run", "u", say=lambda *_: None))
        self.assertEqual(gh2.writes, [])

    def test_a_clean_pass_dismisses_its_own_earlier_request(self):
        old = Q.render(fixture(), Q.decide(fixture(ci_runs=[]), CFG), [], "sig", SHA)
        gh = FakeGh(fixture(), reviews=[{"id": 41, "state": "CHANGES_REQUESTED", "body": old},
                                        {"id": 42, "state": "CHANGES_REQUESTED", "body": "a human's review"}])
        Q.post(gh, qa_run(), False, "workflow_run", "u", say=lambda *_: None)
        paths = [a[2] for a, _ in gh.writes]
        self.assertIn(f"repos/{REPO}/pulls/7/reviews/41/dismissals", paths)
        self.assertNotIn(f"repos/{REPO}/pulls/7/reviews/42/dismissals", paths)

    def test_private_repositories_and_non_qualifying_prs_post_nothing(self):
        gh = FakeGh(fixture(private=True))
        self.assertIn("private", Q.post(gh, qa_run(), False, "w", "u", say=lambda *_: None))
        gh2 = FakeGh(fixture(files=["tools/a.py"], labels=[]))
        self.assertIn("neither", Q.post(gh2, qa_run(), False, "w", "u", say=lambda *_: None))
        self.assertEqual(gh.writes + gh2.writes, [])

    def test_only_qa_lead_runs_are_posted_by_pr_review(self):
        gh = FakeGh(fixture())
        self.assertEqual(P.qa_lead_of(gh, {"path": ".github/workflows/other.yml"}, False, "w", "u"), "")
        self.assertEqual(gh.writes, [])
        self.assertIn("posted", P.qa_lead_of(gh, qa_run(), False, "w", "u", say=lambda *_: None))


class SelfReviewTests(unittest.TestCase):
    """§ 15.5: the author is never a reviewer; Amr reviews in QA Lead's place."""

    def test_own_identity_is_skipped_with_a_comment(self):
        facts = fixture(author="github-actions[bot]", ci_runs=[])
        decided = Q.decide(facts, CFG)
        self.assertEqual((decided["status"], decided["event"], decided["lines"]), ("self", "COMMENT", []))
        gh = FakeGh(facts)
        Q.post(gh, qa_run(), False, "w", "u", say=lambda *_: None)
        posted = [p for _, p in gh.writes if p]
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["event"], "COMMENT")
        self.assertIn("Amr reviews it in QA Lead's place", posted[0]["body"])


class NotesTests(unittest.TestCase):
    def test_notes_are_advisory_bounded_and_escaped(self):
        notes = {"number": 7, "head_sha": SHA, "notes": ["see [x](http://evil) @someone <b>", 7, "two"] + ["n"] * 9}
        gh = FakeGh(fixture(ci_runs=[]), notes=notes)
        Q.post(gh, qa_run(), False, "w", "u", say=lambda *_: None)
        body = next(p["body"] for _, p in gh.writes if p)
        self.assertIn("\\[x\\]\\(http://evil\\) \\@someone \\<b\\>", body)
        self.assertEqual(body.count("\n- "), Q.MAX_NOTES)
        # a forged artifact cannot clear a gap: the verdict is recomputed from live GitHub
        self.assertEqual(next(p["event"] for _, p in gh.writes if p), "REQUEST_CHANGES")

    def test_notes_for_another_commit_are_dropped(self):
        gh = FakeGh(fixture(), notes={"number": 7, "head_sha": "d" * 40, "notes": ["stale"]})
        Q.post(gh, qa_run(), False, "w", "u", say=lambda *_: None)
        self.assertNotIn("stale", next(p["body"] for _, p in gh.writes if p))

    def test_parse_notes_contract(self):
        self.assertEqual(Q.parse_notes('{"notes": ["a", "b"]}'), ["a", "b"])
        self.assertEqual(Q.parse_notes("text then {\"notes\": []}"), [])
        self.assertEqual(Q.parse_notes("not json"), [])
        self.assertEqual(Q.parse_notes('{"notes": "a"}'), [])


class WorkflowTests(unittest.TestCase):
    WF = yaml.safe_load((ROOT / Q.WORKFLOW_PATH).read_text())

    def test_triggers_on_pull_request_with_a_kill_switch(self):
        on = self.WF[True] if True in self.WF else self.WF["on"]
        self.assertIn("pull_request", on)
        self.assertIn("synchronize", on["pull_request"]["types"])
        cond = self.WF["jobs"]["review"]["if"]
        self.assertIn("vars.QA_LEAD_ENABLED == 'true'", cond)
        self.assertIn("!github.event.repository.private", cond)

    def test_model_and_cap_match_fleet_yml(self):
        step = next(s for s in self.WF["jobs"]["review"]["steps"] if s.get("id") == "read")
        self.assertEqual(step["with"]["model"], CFG["model"])
        self.assertEqual(step["with"]["model"], Q.MODEL)
        self.assertEqual(float(step["with"]["max-budget-usd"]), float(CFG["usd"]))
        self.assertEqual(str(step["with"]["max-turns"]), "1")
        self.assertEqual(step["with"]["tools"], "")
        self.assertTrue(step["continue-on-error"])
        allowed = yaml.safe_load((ROOT / "_data" / "fleet.yml").read_text())["ai_models"]["allowed"]
        self.assertIn(CFG["model"], allowed["anthropic"])
        self.assertIn(CFG["model"], ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"))

    def test_the_job_cannot_write_on_the_pull_request(self):
        perms = self.WF["jobs"]["review"]["permissions"]
        self.assertTrue(all(v == "read" for v in perms.values()), perms)
        self.assertEqual(self.WF["permissions"], {"contents": "read"})


if __name__ == "__main__":
    unittest.main(verbosity=1)

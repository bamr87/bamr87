#!/usr/bin/env python3
"""Offline tests for pr_readiness.py: merge readiness in the fleet's one PR comment (ADR 0012).

The fake GitHub and the fixtures are test_pr_review.py's, so both scripts are tested
against the same world; a review write is recorded beside the comment writes. The
readiness of the pull request is handed in, so nothing here reads the PR queue.

Usage: python3 .github/scripts/dash-gen/test_pr_readiness.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_readiness as R  # noqa: E402
import pr_review as P  # noqa: E402
import test_pr_review as T  # noqa: E402

SHA, run = T.SHA, T.run
TODO = {"key": "tasks", "state": "todo", "text": "2 unticked task(s) in the description: CI is green", "who": "author"}
DONE = {"key": "base", "state": "done", "text": "merges into its base without a conflict"}
HELD = {"key": "gate", "state": "held", "text": "held for the maintainer: it changes .github/workflows/ci.yml", "who": "amr"}


class FakeGh(T.FakeGh, R.Gh):
    def post_review(self, number, sha, body):
        self.writes.append(("review", number, body))


def world(*args, **kw):
    gh = T.world(*args, **kw)
    gh.__class__ = FakeGh
    return gh


def ready_row(verdict="not-ready", items=None, merge="agent", sha=SHA):
    items = items if items is not None else [TODO, DONE]
    return {"head_sha": sha, "readiness": {"verdict": verdict, "left": sum(i["state"] == "todo" for i in items), "merge": merge, "items": items}}


def go(gh, row, dry=False):
    return R.report(gh, "1", dry, "workflow_run", "https://example.test/run", say=lambda _b: None, row_of=lambda _repo, _n: row)


def test_a_rebuild_keeps_the_ai_analysis_between_the_failures_and_the_readiness_section():
    block = (P.AI_BLOCK_OPEN.format('{"run":1,"attempt":1,"status":"ok","tries":1}') + "\n### 🤖 Tests\n\nkept analysis\n"
             + P.AI_BLOCK_CLOSE)
    old = P.MARKER + "\n" + P.ai_region([block]) + '\n<!-- fleet:pr-review-state {"sha":"x","runs":[]} -->'
    gh = world([run()], comments=[{"id": 9, "body": old, "user": {"type": "Bot"}}])
    go(gh, ready_row())
    body = gh.writes[-1][2]
    assert "kept analysis" in body and body.count(P.AI_REGION_OPEN) == 1
    assert body.index("### [Tests]") < body.index(P.AI_REGION_OPEN) < body.index("### Before this merges"), body


def test_work_left_keeps_one_comment_on_a_green_pull_request():
    gh = world([run(conclusion="success")])
    go(gh, ready_row())
    (kind, number, body), = gh.writes
    assert (kind, number) == ("post", 7) and body.startswith(P.MARKER)
    assert "## Not ready to merge on `aaaaaaa`" in body and "1 thing left." in body
    assert "| To do | 2 unticked task" in body and "| The author |" in body and "<details><summary>Done (1)</summary>" in body
    assert "Once this is clear: an agent may merge it" in body
    assert body.rstrip().endswith("<!-- fleet:source=merge-readiness trigger=workflow_run run=https://example.test/run -->")
    assert '"ready":"' in body


def test_the_same_readiness_writes_nothing_twice_and_a_change_edits_in_place():
    first = world([run(conclusion="success")])
    go(first, ready_row())
    body = first.writes[0][2]
    again = world([run(conclusion="success")], comments=[{"id": 9, "body": body}])
    assert go(again, ready_row()) == "comment is already current" and not again.writes
    moved = world([run(conclusion="success")], comments=[{"id": 9, "body": body}])
    go(moved, ready_row(items=[dict(TODO, text="1 unticked task(s) in the description: CI is green"), DONE]))
    assert [w[:2] for w in moved.writes] == [("edit", 9)]


def test_ready_deletes_the_comment_and_reviews_the_head_commit_once():
    gh = world([run(conclusion="success")], comments=[{"id": 9, "body": P.MARKER}])
    out = go(gh, ready_row("ready", [DONE, HELD], merge="maintainer"))
    assert [w[:2] for w in gh.writes] == [("delete", 9), ("review", 7)] and "posted the readiness review" in out
    body = gh.writes[1][2]
    assert body.startswith(R.READY_MARKER.format(sha=SHA)) and "**Ready to merge at `aaaaaaa`.**" in body
    assert "no code was reviewed" in body and "**Merge:** The maintainer merges it." in body and "| Held | held for the maintainer" in body
    again = world([run(conclusion="success")])
    again.routes["pulls/7/reviews"] = [{"body": body}]
    assert "already carries its readiness review" in go(again, ready_row("ready", [DONE])) and not again.writes


def test_a_new_head_commit_that_is_ready_gets_its_own_review():
    gh = world([run(conclusion="success")])
    gh.routes["pulls/7/reviews"] = [{"body": R.READY_MARKER.format(sha="b" * 40)}]
    go(gh, ready_row("ready", [DONE]))
    assert [w[0] for w in gh.writes] == ["review"]


def test_the_review_only_comments_and_never_approves():
    sent = []

    class Wire(R.Gh):
        def _run(self, *args, stdin=None):
            sent.append((args, stdin))
            return ""

    Wire("o/app").post_review(7, SHA, "body")
    (args, stdin), = sent
    assert args[:3] == ("-X", "POST", "repos/o/app/pulls/7/reviews") and '"event": "COMMENT"' in stdin and "APPROVE" not in stdin


def test_failures_and_what_is_left_share_the_one_comment():
    gh = world([run()])
    go(gh, ready_row())
    (kind, _n, body), = gh.writes
    assert kind == "post" and body.count(P.MARKER) == 1
    assert "## CI failed on `aaaaaaa`" in body and "### Before this merges" in body and "boom: it broke" in body
    assert body.index("## CI failed") < body.index("### Before this merges")
    assert "<!-- fleet:source=ci-failure trigger=workflow_run" in body


def test_the_failure_part_is_pr_reviews_own():
    plain_gh, both = T.world([run()]), world([run()])
    T.go(plain_gh)
    go(both, ready_row())
    theirs, ours = plain_gh.writes[0][2], both.writes[0][2]
    assert ours.startswith(theirs.split("<!-- fleet:pr-review-state")[0].rstrip("\n"))


def test_waiting_is_not_ready_and_says_so():
    gh = world([run(conclusion="success")])
    go(gh, ready_row("waiting", [{"key": "ci", "state": "wait", "text": "still running: Tests"}]))
    body = gh.writes[0][2]
    assert "## Waiting on `aaaaaaa`" in body and "something is still running" in body and "| Waiting | still running: Tests |" in body


def test_a_readiness_read_that_fails_behaves_as_pr_review_does():
    said = []

    def broken(_repo, _n):
        raise LookupError("could not be read: ghp_" + "a" * 30)

    gh = world([run()])
    R.report(gh, "1", False, "workflow_run", "https://example.test/run", say=said.append, row_of=broken)
    plain_gh = T.world([run()])
    T.go(plain_gh)
    assert gh.writes == plain_gh.writes
    assert any(line.startswith("::warning::merge readiness was not computed") and "ghp_" not in line for line in said)
    quiet = world([run(conclusion="success")])
    assert R.report(quiet, "1", False, "workflow_run", "x", say=lambda _b: None, row_of=broken) == "nothing failing and no comment"
    stale = world([run(conclusion="success")], comments=[{"id": 9, "body": P.MARKER}])
    R.report(stale, "1", False, "workflow_run", "x", say=lambda _b: None, row_of=broken)
    assert stale.writes == [("delete", 9, "")]


def test_readiness_read_for_another_commit_is_not_used():
    gh = world([run(conclusion="success")])
    assert go(gh, ready_row(sha="c" * 40)) == "nothing failing and no comment" and not gh.writes


def test_item_text_from_the_pull_request_does_not_render():
    evil = {"key": "tasks", "state": "todo", "text": "1 unticked task(s): [x](http://evil) | **b** <img src=x> @bamr87 `rm`", "who": "author"}
    gh = world([run(conclusion="success")])
    go(gh, ready_row(items=[evil]))
    row = next(line for line in gh.writes[0][2].splitlines() if line.startswith("| To do"))
    assert "\\[x\\]\\(http://evil\\)" in row and "\\|" in row and "\\<img" in row and "\\@bamr87" in row and "\\`rm\\`" in row
    assert row.count(" | ") == 2


def test_a_dry_run_posts_no_comment_and_no_review():
    gh = world([run(conclusion="success")])
    assert "dry run" in go(gh, ready_row(), dry=True) and not gh.writes
    ready = world([run(conclusion="success")], comments=[{"id": 9, "body": P.MARKER}])
    assert "dry run: would post the readiness review" in go(ready, ready_row("ready", [DONE]), dry=True) and not ready.writes


def test_a_pull_request_event_reports_on_the_open_pull_request_alone():
    gh = world([run(conclusion="success")])
    gh.routes["pulls/7"] = {"state": "open", "head": {"sha": SHA}}
    R.report_pr(gh, 7, False, "pull_request_target", "https://example.test/run", say=lambda _b: None, row_of=lambda _r, _n: ready_row())
    assert [w[0] for w in gh.writes] == ["post"] and "trigger=pull_request_target" in gh.writes[0][2]
    closed = world([run(conclusion="success")])
    closed.routes["pulls/7"] = {"state": "closed", "head": {"sha": SHA}}
    assert R.report_pr(closed, 7, False, "pull_request_target", "x", row_of=lambda _r, _n: ready_row()) == "#7 is not an open pull request"
    assert not closed.writes


def test_an_old_commit_and_a_run_with_no_pull_request_stay_silent():
    old = world([run()], head="b" * 40)
    assert go(old, ready_row()) == "a newer commit is on the PR; its own runs will report" and not old.writes
    none = world([run(pull_requests=[], head_branch="")])
    none.routes["commits/"] = []
    assert "no pull request" in go(none, ready_row()) and not none.writes


def main() -> int:
    tests = sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as e:  # noqa: BLE001 — report every failure, then fail the run
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"{'FAIL' if failed else 'OK'} — pr_readiness tests ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline tests for pr_review.py: the fleet's one PR comment (constitution § 19).

A fake GitHub answers every read and records every write, so each test states
what the comment should do and nothing touches the network.

Usage: python3 .github/scripts/dash-gen/test_pr_review.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_review as P  # noqa: E402

REPO = "bamr87/demo"
SHA = "a" * 40
TS = "2026-11-07T01:24:{:02d}.0000000Z "
STEP = {"name": "Run tests", "conclusion": "failure", "started_at": "2026-11-07T01:24:00Z", "completed_at": "2026-11-07T01:24:40Z"}


def log(*lines: str) -> str:
    return "\n".join(TS.format(i % 40) + line for i, line in enumerate(lines))


class FakeGh(P.Gh):
    """Routes are matched by path prefix, longest first; writes are recorded."""

    def __init__(self, routes: dict, logs: dict | None = None):
        super().__init__(REPO)
        self.routes, self.logs, self.writes = routes, logs or {}, []

    def get(self, path):
        self.calls += 1
        for key in sorted(self.routes, key=len, reverse=True):
            if path.startswith(key):
                return self.routes[key]
        return None

    def text(self, path):
        self.calls += 1
        return self.logs.get(path.split("/")[-2], "")

    def default_branch(self):
        return "main"

    def post_comment(self, number, body):
        self.writes.append(("post", number, body))

    def edit_comment(self, cid, body):
        self.writes.append(("edit", cid, body))

    def delete_comment(self, cid):
        self.writes.append(("delete", cid, ""))


def run(rid=1, conclusion="failure", name="Tests", wid=10, event="pull_request", sha=SHA, **kw):
    return {"id": rid, "name": name, "workflow_id": wid, "event": event, "conclusion": conclusion, "head_sha": sha,
            "head_branch": "feature", "run_attempt": 1, "created_at": "2026-11-07T01:24:00Z", "actor": {"login": "bamr87"},
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}", "pull_requests": [{"number": 7}], **kw}


def job(jid=100, name="unit", conclusion="failure", steps=None):
    return {"id": jid, "name": name, "conclusion": conclusion, "html_url": f"https://github.com/{REPO}/job/{jid}", "steps": steps or [STEP]}


def world(runs, jobs=None, comments=None, logs=None, head=SHA, main_runs=None, trigger=None):
    jobs = jobs if jobs is not None else [job()]
    routes = {"actions/runs/": {"jobs": jobs}, "pulls/7": {"head": {"sha": head}}, "issues/7/comments": comments or [],
              "actions/runs?head_sha": {"workflow_runs": runs}, "check-runs/": [], "actions/workflows/": {"workflow_runs": main_runs or []}}
    routes["actions/runs/1"] = trigger or runs[0]
    routes["actions/runs/1/jobs"] = {"jobs": jobs}
    return FakeGh(routes, logs or {"100": log("boom: it broke")})


def go(gh, dry=False):
    return P.report(gh, "1", dry, "workflow_run", "https://example.test/run", say=lambda _b: None)


# ------------------------------------------------------------------- reading a log
def test_a_traceback_gives_the_exception_and_its_detail():
    text = log("Traceback (most recent call last):", '  File "x.py", line 1, in <module>', "    fn()",
               "ruamel.yaml.constructor.DuplicateKeyError: while constructing a mapping",
               '  in "<unicode string>", line 1813, column 5:', 'found duplicate key "hub/drift-check" with value "{}"')
    reason, excerpt = P.explain(text, STEP, [])
    assert "DuplicateKeyError" in reason and "hub/drift-check" in reason, reason
    assert any("found duplicate key" in line for line in excerpt)


def test_it_narrows_to_the_group_that_failed():
    text = log("##[group]tests/a.py", "  ✗ a fixture that fails on purpose", "##[endgroup]",
               "##[group]tests/b.py", "FAILED real_test - AssertionError: wrong", "##[endgroup]", "##[error]tests/b.py failed",
               "##[group]tests/c.py", "ok", "##[endgroup]")
    reason, excerpt = P.explain(text, STEP, [])
    assert "fixture" not in " ".join(excerpt), excerpt
    assert "real_test" in " ".join(excerpt), excerpt


def test_post_job_cleanup_is_never_the_reason():
    text = log("compiling", "Post job cleanup.", "[command]/usr/bin/git version", "git version 2.56.0",
               "/github/runner_temp/git-credentials-e5c.config")
    reason, _ = P.explain(text, STEP, [])
    assert "git version" not in reason and "credentials" not in reason, reason


def test_a_step_with_no_clear_error_says_so():
    reason, _ = P.explain(log("step one", "step two"), STEP, [])
    assert reason.startswith("The step printed no clear error"), reason
    assert P.explain("", STEP, [])[0] == "The step failed without printing anything."


def test_the_first_error_beats_the_pointer_to_a_log_file():
    text = log("npm error code ERESOLVE", "npm error ERESOLVE could not resolve", "npm error A complete log of this run can be found in: x")
    assert "ERESOLVE" in P.explain(text, STEP, [])[0]


def test_a_specific_annotation_is_used_and_a_generic_one_is_not():
    assert "port 4000" in P.explain(log("error: bind"), STEP, ["port 4000 is taken"])[0]
    assert "Process completed" not in P.explain(log("error: bind"), STEP, ["Process completed with exit code 1."])[0]


def test_lines_outside_the_failed_step_are_left_out():
    text = "2026-11-07T01:20:00.0000000Z error: an earlier step\n" + log("error: this step")
    assert "earlier" not in " ".join(P.explain(text, STEP, [])[1])


# ------------------------------------------------------------------- untrusted text
def test_log_text_cannot_escape_its_code_span_or_fence():
    assert P.code_span("a` <img src=x> @bamr87 `b").count("`") == 2
    assert "~~~" not in P.fence(["~~~\n## injected"]).split("\n", 1)[1].rsplit("\n", 1)[0]


def test_names_from_a_pull_request_do_not_render():
    out = P.plain("x](http://evil) <b> @bamr87 ![y](z)")
    for raw in ("](", "<b>", " @bamr87", "!["):
        assert raw not in out, out


def test_token_shaped_text_is_scrubbed():
    text = "token ghp_" + "a" * 36 + " and github_pat_" + "b" * 30 + " and Bearer " + "c" * 30
    for shown in (P.code_span(text, 400), P.fence([text])):
        assert "ghp_" not in shown and "github_pat_" not in shown and "cccc" not in shown, shown


# ------------------------------------------------------------------- the sticky comment
def test_a_failure_posts_one_comment_ending_in_the_signature():
    gh = world([run()])
    go(gh)
    kind, number, body = gh.writes[0]
    assert (kind, number, len(gh.writes)) == ("post", 7, 1)
    assert body.startswith(P.MARKER) and "boom: it broke" in body
    assert body.rstrip().endswith("<!-- fleet:source=ci-failure trigger=workflow_run run=https://example.test/run -->")


def test_the_same_failure_writes_nothing_twice():
    first = world([run()])
    go(first)
    body = first.writes[0][2]
    again = world([run()], comments=[{"id": 9, "body": body}])
    assert go(again) == "comment is already current" and not again.writes


def test_a_new_failure_edits_the_comment_in_place():
    old = P.MARKER + '\n<!-- fleet:pr-review-state {"sha":"b","runs":[[5,1]]} -->'
    gh = world([run()], comments=[{"id": 9, "body": old}])
    go(gh)
    assert [w[0] for w in gh.writes] == ["edit"] and gh.writes[0][1] == 9


def test_clean_deletes_a_stale_comment_and_otherwise_stays_silent():
    gh = world([run(conclusion="success")], comments=[{"id": 9, "body": P.MARKER}])
    go(gh)
    assert gh.writes == [("delete", 9, "")]
    quiet = world([run(conclusion="success")])
    assert go(quiet) == "nothing failing and no comment" and not quiet.writes


def test_a_comment_from_anything_else_is_left_alone():
    gh = world([run(conclusion="success")], comments=[{"id": 9, "body": "a person's comment"}])
    go(gh)
    assert not gh.writes


def test_an_old_commit_does_not_speak_for_the_pr():
    gh = world([run()], head="b" * 40)
    assert "newer commit" in go(gh) and not gh.writes


def test_a_run_with_no_pull_request_does_nothing():
    gh = world([run(pull_requests=[])])
    gh.routes["commits/"] = []
    assert go(gh) == "no pull request for this run" and not gh.writes


def test_a_failed_push_reports_on_the_pr_that_merged_it():
    gh = world([run(event="push", pull_requests=[])])
    gh.routes["commits/"] = [{"number": 7, "state": "closed", "head": {"sha": "c" * 40}}]
    go(gh)
    assert gh.writes[0][:2] == ("post", 7)


def test_a_dry_run_writes_nothing():
    gh = world([run()])
    assert go(gh, dry=True).startswith("dry run") and not gh.writes


def test_only_the_latest_attempt_of_a_workflow_counts():
    older = run(rid=1, conclusion="failure", created_at="2026-11-07T01:00:00Z")
    newer = run(rid=2, conclusion="success", created_at="2026-11-07T02:00:00Z")
    gh = world([older, newer], comments=[{"id": 9, "body": P.MARKER}], trigger=newer)
    go(gh)
    assert gh.writes == [("delete", 9, "")]


def test_this_workflow_never_reports_on_itself():
    gh = world([run(), run(rid=3, name=P.SELF_NAME, wid=99)])
    go(gh)
    assert P.SELF_NAME not in gh.writes[0][2].split("<!--")[1]


# ------------------------------------------------------------------- what it says
def test_the_same_job_failing_on_main_says_the_pr_probably_did_not_cause_it():
    main = [{"id": 50, "event": "push", "conclusion": "failure", "head_sha": "d" * 40}]
    gh = world([run()], main_runs=main)
    gh.routes["actions/runs/50/jobs"] = {"jobs": [job(jid=500)]}
    go(gh)
    assert "Probably not: the same job also failed on `main`" in gh.writes[0][2]


def test_passing_on_main_points_at_the_pr():
    gh = world([run()], main_runs=[{"id": 50, "event": "push", "conclusion": "success", "head_sha": "d" * 40}])
    go(gh)
    assert "Probably yes: it passed on `main`" in gh.writes[0][2]


def test_a_pr_run_on_a_branch_named_main_is_not_the_baseline():
    runs = [{"id": 51, "event": "pull_request", "conclusion": "failure", "head_sha": "e" * 40},
            {"id": 50, "event": "push", "conclusion": "success", "head_sha": "d" * 40}]
    gh = world([run()], main_runs=runs)
    go(gh)
    assert "Probably yes" in gh.writes[0][2]


def test_a_job_that_only_reports_its_siblings_is_dropped():
    jobs = [job(jid=100, name="tests (console)"), job(jid=200, name="python-tests")]
    gh = world([run()], jobs=jobs, logs={"100": log("FAILED real_test - AssertionError: wrong"),
                                         "200": log("##[error]the test shards ended failure")})
    go(gh)
    assert "tests \\(console\\)" in gh.writes[0][2] and "python-tests" not in gh.writes[0][2]


def test_a_run_held_for_approval_says_what_to_do():
    gh = world([run(conclusion="action_required", actor={"login": "github-actions[bot]"})], jobs=[])
    go(gh)
    body = gh.writes[0][2]
    assert "CI is waiting for approval" in body and "Approve the run" in body


def test_a_run_with_no_jobs_explains_itself_by_who_started_it():
    bot = world([run(actor={"login": "github-actions[bot]"})], jobs=[])
    go(bot)
    assert "Open these PRs" in bot.writes[0][2]
    human = world([run()], jobs=[])
    go(human)
    assert "`uses:` reference" in human.writes[0][2]


def test_a_long_failure_stays_under_the_comment_limit():
    jobs = [job(jid=i, name=f"j{i}") for i in range(100, 106)]
    runs = [run(rid=i, wid=i, name=f"w{i}") for i in range(1, 9)]
    gh = world(runs, jobs=jobs, logs={str(i): log(*["error: " + "x" * 400] * 300) for i in range(100, 106)})
    go(gh)
    body = gh.writes[0][2]
    assert len(body) <= P.MAX_BODY and "more failed workflow(s)" in body
    assert body.rstrip().endswith("run=https://example.test/run -->") and P.STATE_RX.search(body), "the footer survives"


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
    print(f"{'FAIL' if failed else 'OK'} — pr_review tests ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

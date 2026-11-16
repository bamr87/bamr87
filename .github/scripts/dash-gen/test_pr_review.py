#!/usr/bin/env python3
"""Offline tests for pr_review.py: the fleet's one PR comment (constitution § 19).

A fake GitHub answers every read and records every write, so each test states
what the comment should do and nothing touches the network.

Usage: python3 .github/scripts/dash-gen/test_pr_review.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import zipfile
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
        self.blobs: dict = {}
        self.read: list[str] = []
        self.refuse: set[int] = set()

    def get(self, path):
        self.calls += 1
        self.read.append(path)
        for key in sorted(self.routes, key=len, reverse=True):
            if path.startswith(key):
                return self.routes[key]
        return None

    def text(self, path):
        self.calls += 1
        return self.logs.get(path.split("/")[-2], "")

    def blob(self, path):
        self.calls += 1
        return self.blobs[path.split("/")[-2]]

    def post_review_comment(self, number, payload):
        if payload["line"] in self.refuse:
            raise RuntimeError("gh api pulls/7/comments: HTTP 422 line could not be resolved")
        self.writes.append(("inline", number, payload))

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


def test_common_error_shapes_are_recognized():
    for line in ("docs/a.md:100:416 error MD049/emphasis-style Emphasis style", "bash: line 1: bundle: command not found",
                 "description is too long (maximum is 100 characters)", "src/x.c:12: error: expected ';'"):
        assert P.explain(log("working", line), STEP, [])[0] == line, line


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


# ------------------------------------------------------------------- findings (§ 19.3)
# A patch that adds lines 2 to 31 of the new file, between two context lines.
PATCH = "@@ -1,2 +1,32 @@\n line one\n" + "".join(f"+added {n}\n" for n in range(2, 32)) + " line last"


def finding(path="docs/a.md", line=3, rule="MD013", severity="warning", kind="docs", message="Line too long"):
    return {"path": path, "line": line, "rule": rule, "severity": severity, "kind": kind, "message": message}


def artifact(*items, raw: str | None = None, member: str = "findings.jsonl") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, raw if raw is not None else "".join(json.dumps(i) + "\n" for i in items))
    return buf.getvalue()


def fworld(*zips, runs=None, author="bamr87", ref="feature", review=None, comments=None, sha=SHA, sizes=None):
    """A PR whose head carries one `fleet-findings` artifact per zip, each from the
    matching run (the first run by default)."""
    runs = runs or [run(conclusion="success")]
    gh = world(runs, comments=comments)
    gh.routes["pulls/7"] = {"head": {"sha": SHA, "ref": ref}, "user": {"login": author}}
    gh.routes["pulls/7/files"] = [{"filename": "docs/a.md", "patch": PATCH}, {"filename": "src/x.py", "patch": PATCH},
                                  {"filename": "img.png"}]
    gh.routes["pulls/7/comments"] = review or []
    gh.routes["actions/artifacts?name="] = {"artifacts": [
        {"id": 900 + i, "name": "fleet-findings", "size_in_bytes": (sizes or {}).get(i, len(z)), "expired": False,
         "created_at": "2026-11-07T01:30:00Z", "workflow_run": {"id": runs[min(i, len(runs) - 1)]["id"], "head_sha": sha}}
        for i, z in enumerate(zips)]}
    gh.blobs = {str(900 + i): z for i, z in enumerate(zips)}
    return gh


def inline(gh) -> list[dict]:
    return [w[2] for w in gh.writes if w[0] == "inline"]


def test_added_lines_reads_only_what_the_patch_adds():
    patch = "@@ -10,3 +10,4 @@ def f():\n ctx\n-gone\n+new a\n+new b\n ctx\n\\ No newline at end of file\n@@ -40 +41,2 @@\n+x\n ctx"
    assert P.added_lines(patch) == {11, 12, 41}
    assert P.added_lines("") == set()


def test_a_clean_run_posts_nothing():
    gh = fworld(artifact())  # a check that found nothing uploads an empty file
    assert go(gh).startswith("nothing failing and no comment") and not gh.writes
    quiet = fworld()  # no artifact at all: one listing call, nothing else
    assert go(quiet) == "nothing failing and no comment" and not quiet.writes
    assert not [p for p in quiet.read if p.startswith(("pulls/7/files", "pulls/7/comments"))]


def test_a_finding_on_the_diff_is_posted_inline_with_its_severity_key_and_signature():
    gh = fworld(artifact(finding(kind="code", severity="error", rule="E501")))
    assert "posted 1 inline" in go(gh)
    [payload] = inline(gh)
    assert (payload["path"], payload["line"], payload["side"], payload["commit_id"]) == ("docs/a.md", 3, "RIGHT", SHA)
    body = payload["body"]
    assert body.startswith("**Error**") and "`E501`" in body and "Line too long" in body
    assert f"<!-- fleet:finding key={P.finding_key('docs/a.md', 3, 'E501')} -->" in body
    assert body.rstrip().endswith("<!-- fleet:source=tests trigger=workflow_run run=https://example.test/run -->")
    assert not [w for w in gh.writes if w[0] != "inline"], "a green run still writes no sticky"


def test_duplicate_findings_are_not_reposted():
    twice = fworld(artifact(finding(), finding(message="the same place and rule, said again")))
    go(twice)
    assert len(inline(twice)) == 1, "one (path, line, rule) is one comment"
    body = inline(twice)[0]["body"]
    again = fworld(artifact(finding()), review=[{"id": 1, "user": {"type": "Bot"}, "body": body}])
    assert "posted 0 inline" in go(again) and not again.writes, "a later push does not repost"
    other_rule = fworld(artifact(finding(rule="MD009")), review=[{"id": 1, "user": {"type": "Bot"}, "body": body}])
    go(other_rule)
    assert len(inline(other_rule)) == 1, "another rule on the same line is another finding"
    forged = fworld(artifact(finding()), review=[{"id": 1, "user": {"type": "User"}, "body": body}])
    go(forged)
    assert len(inline(forged)) == 1, "a person quoting the key cannot hide a finding"


def test_a_second_push_edits_the_sticky_and_counts_the_findings():
    old = P.MARKER + '\n<!-- fleet:pr-review-state {"sha":"b","runs":[[5,1]]} -->'
    posted = P.finding_body({**finding(), "source": "tests"}, "workflow_run", "https://example.test/run")
    gh = fworld(artifact(finding(), finding(line=4, severity="error", kind="code")), runs=[run()],
                comments=[{"id": 9, "body": old}], review=[{"id": 1, "user": {"type": "Bot"}, "body": posted}])
    go(gh)
    stickies = [w for w in gh.writes if w[0] != "inline"]
    assert [w[:2] for w in stickies] == [("edit", 9)], gh.writes
    assert "**Findings on this commit's diff:** 1 error, 1 warning" in stickies[0][2]
    assert len(inline(gh)) == 1 and inline(gh)[0]["line"] == 4, "only the new finding is posted"
    state = json.loads(P.STATE_RX.search(stickies[0][2]).group(1))
    assert state["findings"] == {"error": 1, "warning": 1}
    same = fworld(artifact(finding(), finding(line=4, severity="error", kind="code")), runs=[run()],
                  comments=[{"id": 9, "body": stickies[0][2]}],
                  review=[{"id": 1, "user": {"type": "Bot"}, "body": posted},
                          {"id": 2, "user": {"type": "Bot"}, "body": inline(gh)[0]["body"]}])
    assert go(same).startswith("comment is already current") and not same.writes


def test_dependabot_and_release_prs_skip_content_and_docs_findings():
    items = (finding(kind="docs"), finding(line=4, kind="content", rule="C1"), finding(line=5, kind="code", rule="E1"))
    for who in ({"author": "dependabot[bot]"}, {"ref": "release-please--branches--main"}):
        gh = fworld(artifact(*items), **who)
        go(gh)
        assert [p["line"] for p in inline(gh)] == [5], (who, inline(gh))
    person = fworld(artifact(*items))
    go(person)
    assert len(inline(person)) == 3, "a person's PR gets every kind"


def test_a_malformed_artifact_posts_nothing():
    good = json.dumps(finding()) + "\n"
    bad_lines = {
        "not JSON": "{not json",
        "an extra key": json.dumps({**finding(), "url": "x"}),
        "a missing key": json.dumps({k: v for k, v in finding().items() if k != "kind"}),
        "a severity outside the set": json.dumps(finding(severity="critical")),
        "a kind outside the set": json.dumps(finding(kind="style")),
        "a path that climbs out": json.dumps(finding(path="../etc/passwd")),
        "an absolute path": json.dumps(finding(path="/etc/passwd")),
        "a line as text": json.dumps({**finding(), "line": "3"}),
        "a line as a boolean": json.dumps({**finding(), "line": True}),
        "a rule with markup": json.dumps(finding(rule="<b>x</b>")),
        "an empty message": json.dumps(finding(message="  ")),
        "a message over the limit": json.dumps(finding(message="x" * (P.MAX_MESSAGE + 1))),
        "a list, not an object": json.dumps([finding()]),
    }
    for why, line in bad_lines.items():
        gh = fworld(artifact(raw=good + line + "\n"))
        result = go(gh)
        assert not gh.writes and "1 artifact(s) rejected" in result, (why, result, gh.writes)
    for why, blob in {"not a zip": b"PK\x03\x04 broken", "no .jsonl in it": artifact(raw=good, member="findings.json")}.items():
        gh = fworld(blob)
        assert not gh.writes and "1 artifact(s) rejected" in go(gh), why
    utf16 = io.BytesIO()
    with zipfile.ZipFile(utf16, "w") as z:
        z.writestr("findings.jsonl", good.encode("utf-16"))
    gh = fworld(utf16.getvalue())
    assert not gh.writes and "1 artifact(s) rejected" in go(gh), "not UTF-8"
    big = fworld(artifact(finding()), sizes={0: P.MAX_ARTIFACT_BYTES + 1})
    assert not big.writes and "1 artifact(s) rejected" in go(big), "over the size limit"
    many = fworld(artifact(*[finding(line=n) for n in range(1, P.MAX_FINDINGS + 2)]))
    assert not many.writes and "1 artifact(s) rejected" in go(many), "over the findings limit"


def test_a_malformed_artifact_does_not_stop_a_good_one():
    runs = [run(rid=1, conclusion="success"), run(rid=2, wid=11, name="Docs", conclusion="success")]
    gh = fworld(artifact(raw="{oops\n"), artifact(finding()), runs=runs)
    assert "1 artifact(s) rejected" in go(gh)
    assert len(inline(gh)) == 1 and "source=docs " in inline(gh)[0]["body"]


def test_only_lines_this_pr_adds_get_a_finding():
    gh = fworld(artifact(finding(line=1), finding(line=32), finding(path="README.md"), finding(path="img.png", line=2),
                         finding(line=31, rule="R31")))
    go(gh)
    assert [(p["path"], p["line"]) for p in inline(gh)] == [("docs/a.md", 31)]


def test_findings_from_another_commit_or_an_older_attempt_are_ignored():
    gh = fworld(artifact(finding()), sha="c" * 40)
    assert go(gh) == "nothing failing and no comment" and not gh.writes
    stale = fworld(artifact(finding()), runs=[run(rid=5, conclusion="success")])
    stale.routes["actions/artifacts?name="]["artifacts"][0]["workflow_run"]["id"] = 4  # not the workflow's latest run
    assert not go(stale).count("findings") and not stale.writes


def test_a_push_never_reads_findings():
    gh = fworld(artifact(finding()), runs=[run(event="push", pull_requests=[])])
    gh.routes["commits/"] = [{"number": 7, "state": "closed", "head": {"sha": "c" * 40}}]
    go(gh)
    assert not inline(gh) and not [p for p in gh.read if p.startswith("actions/artifacts")]


def test_new_inline_comments_are_capped_per_review():
    gh = fworld(artifact(*[finding(line=n, rule=f"R{n}") for n in range(2, 32)]))
    result = go(gh)
    assert len(inline(gh)) == P.MAX_INLINE and f"posted {P.MAX_INLINE} inline" in result, result


def test_a_dry_run_posts_no_findings():
    gh = fworld(artifact(finding()))
    assert "would post 1 inline" in go(gh, dry=True) and not gh.writes


def test_github_refusing_one_comment_does_not_stop_the_rest():
    gh = fworld(artifact(finding(line=3), finding(line=4)))
    gh.refuse = {3}
    assert "posted 1 inline" in go(gh) and [p["line"] for p in inline(gh)] == [4]


def test_an_api_error_in_findings_still_leaves_the_failure_summary():
    gh = fworld(artifact(finding()), runs=[run()])
    real_get = gh.get

    def get(path):
        if path.startswith("actions/artifacts"):
            raise RuntimeError("gh api actions/artifacts: HTTP 403")
        return real_get(path)
    gh.get = get
    result = go(gh)
    assert [w[:2] for w in gh.writes] == [("post", 7)] and "findings not read: gh api actions/artifacts" in result, result


def test_a_finding_message_cannot_render_markup_or_mention_anyone():
    gh = fworld(artifact(finding(message="@bamr87 see [here](http://evil.test) <img src=x> ghp_" + "a" * 36)))
    go(gh)
    shown = inline(gh)[0]["body"].split("<!--")[0]
    for raw in (r"(?<!\\)@bamr87", r"(?<!\\)\]\(", r"(?<!\\)<img", "ghp_"):
        assert not re.search(raw, shown), (raw, shown)


def test_the_job_summary_lists_every_finding_and_what_happened():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "summary.md"
        os.environ["GITHUB_STEP_SUMMARY"] = str(out)
        try:
            go(fworld(artifact(finding(), finding(path="README.md")), author="dependabot[bot]"))
            go(fworld(artifact(finding(kind="code")), artifact(raw="nope\n"),
                      runs=[run(rid=1, conclusion="success"), run(rid=2, wid=11, name="Lint", conclusion="success")]))
        finally:
            del os.environ["GITHUB_STEP_SUMMARY"]
        text = out.read_text(encoding="utf-8")
    assert "skipped: docs check on a Dependabot PR" in text and "| posted |" in text
    assert "Rejected: `fleet-findings` from Lint" in text and "not JSON" in text


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

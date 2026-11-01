#!/usr/bin/env python3
"""
Fixture tests for tools/jev/ratify.py — the ratification, acceptance and
completion records a maintainer's merge decided, the guard that decides
whether the job may merge the record PR — and for the `ratify` job in
.github/workflows/jev-number.yml that publishes and merges them.

Every test builds a throwaway git repository whose amendment and ADR files are
committed in the order a real hub would see them, and replaces the one GitHub
seam (`ratify._gh_json`) with a fake that answers from a table and refuses any
call `common.assert_no_admin` would refuse. Nothing here reads the hub's own
records or calls GitHub.

Run: python3 tools/test_jev_ratify.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.jev import __main__ as cli  # noqa: E402
from tools.jev import common as C  # noqa: E402
from tools.jev import ratify as R  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/jev-number.yml"

AMEND_INDEX = """\
# Amendments

| # | Title | Status | Affects |
| --- | --- | --- | --- |
| [0001](0001-ratify.md) | Ratify the constitution | ratified on merge | whole constitution |
"""
AMEND_0001 = ("# 0001 — Ratify the constitution\n\n- **Status:** ratified\n- **Date:** 2026-10-21\n"
              "- **Ratified by:** the merged PR that adds this record\n")
ALPHA = """\
# NEW — Alpha rule

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-29
- **Proposed by:** agent
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution § 2

## Amendment

The status of this proposal is proposed until the maintainer merges it.
"""
BETA = """\
# NEW — Beta rule

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-30
- **Affects:** none
"""
ADR_INDEX = """\
# ADRs

| ID | Title | Status |
| --- | --- | --- |
"""
ADR_0001 = """\
# ADR 0001 — The first decision

- **Status**: proposed
- **Date**: 2026-10-30
- **Deciders**: the maintainer
- **Tracking**: #50

## Context

Why.
"""
ADR_P1 = """
## P1 — the second phase

  - **Status**: proposed, with the maintainer's decisions recorded below
  - **Date**: 2026-10-31
"""
SCRATCH = Path(tempfile.gettempdir())


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "submodule.recurse=false", "-c", "commit.gpgsign=false", *args], cwd=repo,
                          check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def commit(repo: Path, message: str) -> str:
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", message)
    return sh(repo, "rev-parse", "HEAD")


def compile_amendment(repo: Path, slug: str, number: str, title: str) -> None:
    """What `jev number apply` does: move the fragment, append a `proposed` row."""
    body = (repo / f"docs/amendments/proposed/{slug}.md").read_text()
    body = body.replace("# NEW", f"# {number}", 1).replace("**Number:** NEW", f"**Number:** {number}", 1)
    (repo / f"docs/amendments/proposed/{slug}.md").unlink()
    write(repo, f"docs/amendments/{number}-{slug}.md", body)
    idx = repo / "docs/amendments/README.md"
    idx.write_text(idx.read_text() + f"| [{number}]({number}-{slug}.md) | {title} | proposed | none |\n")


def build(*, alpha: str = ALPHA, adr: str = ADR_0001, beta: bytes | None = None) -> tuple[Path, dict[str, str]]:
    """The hub's history in miniature. Returns (repo, {step: sha})."""
    repo = Path(tempfile.mkdtemp(prefix="jev-ratify-"))
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "config", "user.email", "t@example.com")
    sh(repo, "config", "user.name", "t")
    sh(repo, "config", "core.autocrlf", "false")
    write(repo, "_data/fleet.yml", "hub:\n  repo: o/r\n")
    write(repo, "docs/amendments/README.md", AMEND_INDEX)
    write(repo, "docs/amendments/0000-template.md", "# NNNN — Title\n\n- **Status:** proposed\n")
    write(repo, "docs/amendments/0001-ratify.md", AMEND_0001)
    write(repo, "docs/adr/README.md", ADR_INDEX)
    write(repo, "docs/adr/0000-template.md", "# ADR NNNN — Title\n\n- **Status**: proposed\n")
    write(repo, "notes.md", "unrelated\n")
    write(repo, ".github/workflows/jev-number.yml",
          "jobs:\n  number:\n    steps:\n      - uses: ./publish-data\n        with:\n"
          "          branch: chore/jev-numbering   # the stable PR branch\n")
    shas = {"base": commit(repo, "base")}
    write(repo, "docs/amendments/proposed/alpha.md", alpha)
    shas["alpha"] = commit(repo, "docs: propose alpha (#10)")
    compile_amendment(repo, "alpha", "0002", "Alpha rule")
    shas["compile-alpha"] = commit(repo, "chore(jev): assign ids")
    if beta is None:
        write(repo, "docs/amendments/proposed/beta.md", BETA)
    else:
        (repo / "docs/amendments/proposed").mkdir(parents=True, exist_ok=True)
        (repo / "docs/amendments/proposed/beta.md").write_bytes(beta)
    shas["beta"] = commit(repo, "docs: propose beta (#11)")
    if beta is None:
        compile_amendment(repo, "beta", "0003", "Beta rule")
    else:
        data = (repo / "docs/amendments/proposed/beta.md").read_bytes().replace(b"NEW", b"0003")
        (repo / "docs/amendments/proposed/beta.md").unlink()
        (repo / "docs/amendments/0003-beta.md").write_bytes(data)
        idx = repo / "docs/amendments/README.md"
        idx.write_text(idx.read_text() + "| [0003](0003-beta.md) | Beta rule | proposed | none |\n")
    shas["compile-beta"] = commit(repo, "chore(jev): assign ids")
    write(repo, "docs/adr/0001-first.md", adr)
    idx = repo / "docs/adr/README.md"
    idx.write_text(idx.read_text() + "| 0001 | [The first decision](0001-first.md) | proposed |\n")
    shas["adr"] = commit(repo, "docs(adr): the first decision (#12)")
    rec = repo / "docs/adr/0001-first.md"
    rec.write_text(rec.read_text() + ADR_P1)
    shas["adr-p1"] = commit(repo, "docs(adr): append P1 (#13)")
    return repo, shas


def pr(number: int, merged: bool = True, by: str = "o", base: str = "main", day: str = "2026-10-30",
       head: str | None = None, author: str = "o") -> dict:
    return {"number": number, "title": f"PR {number}", "html_url": f"https://github.com/o/r/pull/{number}",
            "merged_at": f"{day}T12:00:00Z" if merged else None, "merged_by": {"login": by} if merged else None,
            "merge_commit_sha": (str(number) * 40)[:40], "base": {"ref": base}, "labels": [{"name": "governance"}],
            "head": {"ref": head or f"feature/pr-{number}", "repo": {"full_name": "o/r"}},
            "user": {"login": author}, "body": f"Fixes #{number + 100}", "state": "closed" if merged else "open"}


class FakeGitHub:
    """Answers the planner's and the guard's GETs from tables; refuses what the
    JEV guard refuses; raises a read failure for any path in `fail`."""

    def __init__(self, shas: dict[str, str]):
        self.pulls = {10: pr(10), 11: pr(11), 12: pr(12, day="2026-11-01"), 13: pr(13, day="2026-11-01")}
        self.commit_pulls = {shas["alpha"]: [10], shas["beta"]: [11], shas["adr"]: [12], shas["adr-p1"]: [13]}
        self.issues = {50: {"number": 50, "title": "Epic", "html_url": "https://github.com/o/r/issues/50",
                            "state": "open", "state_reason": None, "closed_at": None, "closed_by": None}}
        self.subs = {50: [{"number": 51, "state": "closed"}, {"number": 52, "state": "open"}]}
        self.graphql_ok = True
        self.unknown: set[str] = set()      # commits GitHub has never seen (answers 422)
        self.fail: set[str] = set()         # path fragments that answer a 502
        self.branches: dict[str, str] = {}
        self.check_runs: dict[str, list] = {}
        self.statuses: dict[str, list] = {}
        self.record_pulls: list[dict] = []
        self.calls: list[list[str]] = []

    def close_epic(self, reason: str = "completed", subs_closed: bool = True, by: str = "o") -> None:
        self.issues[50].update(state="closed", state_reason=reason, closed_at="2026-11-05T09:00:00Z",
                               closed_by={"login": by})
        if subs_closed:
            for s in self.subs[50]:
                s["state"] = "closed"

    def __call__(self, args: list[str]):
        C.assert_no_admin(args)          # GETs and an inline GraphQL query only
        self.calls.append(list(args))
        if args[1] == "graphql":
            if not self.graphql_ok:
                raise C.JevError("graphql unavailable")
            n = int(next(a for a in args if a.startswith("n=")).split("=", 1)[1])
            return {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {
                "nodes": [{"number": n + 100}]}}}}}
        path = [a for a in args[1:] if not a.startswith("-")][0]
        if any(f in path for f in self.fail):
            raise C.JevError(f"gh api {path} failed: Bad Gateway (HTTP 502)")
        parts = path.split("?")[0].split("/")
        if path == "repos/o/r":
            return {"default_branch": "main"}
        if parts[3] == "branches":
            return {"commit": {"sha": self.branches[parts[4]]}}
        if parts[3] == "commits" and parts[5] == "check-runs":
            return [{"total_count": len(self.check_runs.get(parts[4], [])),
                     "check_runs": copy.deepcopy(self.check_runs.get(parts[4], []))}]
        if parts[3] == "commits" and parts[5] == "status":
            return {"statuses": copy.deepcopy(self.statuses.get(parts[4], []))}
        if parts[3] == "commits" and parts[4] in self.unknown:
            raise C.JevError("gh api failed: No commit found for SHA (HTTP 422)")
        if parts[3] == "commits":
            return [copy.deepcopy(self.pulls[n]) for n in self.commit_pulls.get(parts[4], [])]
        if parts[3] == "pulls" and len(parts) == 4:
            return [copy.deepcopy(self.record_pulls)]
        if parts[3] == "pulls":
            return copy.deepcopy(self.pulls[int(parts[4])])
        if parts[3] == "issues" and parts[-1] == "sub_issues":
            return [copy.deepcopy(self.subs.get(int(parts[4]), []))]
        if parts[3] == "issues":
            n = int(parts[4])
            if n not in self.issues:
                raise C.JevError(f"gh api {path} failed: Not Found (HTTP 404)")
            return copy.deepcopy(self.issues[n])
        raise AssertionError(f"unexpected gh call {args}")


@contextlib.contextmanager
def github(fake: FakeGitHub):
    real = R._gh_json
    R._gh_json = fake
    try:
        yield fake
    finally:
        R._gh_json = real


def lines(repo: Path, rel: str) -> list[str]:
    return (repo / rel).read_text().split("\n")


def planned(repo: Path, fake: FakeGitHub, ref: str = "HEAD") -> R.Plan:
    with github(fake):
        return R.plan(repo, ref=ref)


def skip_of(p: R.Plan, record: str) -> dict:
    return next(s for s in p.skipped if s["record"] == record)


# --------------------------------------------------------------------------- #
# amendments
# --------------------------------------------------------------------------- #
def test_a_merged_amendment_is_ratified_in_0005s_exact_format():
    repo, shas = build()
    fake = FakeGitHub(shas)
    p = planned(repo, fake)
    R.apply(repo, p)
    text = lines(repo, "docs/amendments/0002-alpha.md")
    assert "- **Status:** ratified" in text
    assert "- **Ratified by:** https://github.com/o/r/pull/10 (merged 2026-10-30 by @o)" in text
    assert not any("blank until" in ln for ln in text), "the placeholder is replaced, not kept"
    # the body is never touched, even where it says "proposed"
    assert "The status of this proposal is proposed until the maintainer merges it." in text
    index = (repo / "docs/amendments/README.md").read_text()
    assert "| [0002](0002-alpha.md) | Alpha rule | ratified | none |" in index
    assert "| [0001](0001-ratify.md) | Ratify the constitution | ratified on merge | whole constitution |" in index
    assert {e.key for e in p.edits if e.record.endswith("0002-alpha.md")} == {"ratify:docs/amendments/0002-alpha.md"}


def test_ratified_by_is_inserted_after_status_when_the_record_has_none():
    repo, shas = build()
    p = planned(repo, FakeGitHub(shas))
    R.apply(repo, p)
    text = lines(repo, "docs/amendments/0003-beta.md")
    i = text.index("- **Status:** ratified")
    assert text[i + 1] == "- **Ratified by:** https://github.com/o/r/pull/11 (merged 2026-10-30 by @o)"
    assert text[i + 2] == "- **Number:** 0003"


def test_a_placeholder_naming_some_other_url_is_still_replaced():
    # C6: only the stamp shape counts as filled.
    repo, shas = build(alpha=ALPHA.replace("_(blank until the pull request is merged)_",
                                           "blank until merged; discussion in https://github.com/o/r/pull/9"))
    p = planned(repo, FakeGitHub(shas))
    R.apply(repo, p)
    assert "- **Ratified by:** https://github.com/o/r/pull/10 (merged 2026-10-30 by @o)" in \
        lines(repo, "docs/amendments/0002-alpha.md")


def test_a_ratified_by_already_stamped_with_the_trigger_gets_only_the_status_edit():
    # R4 (b): a record whose Ratified by is the trigger's stamp keeps it.
    stamped = "https://github.com/o/r/pull/10 (merged 2026-10-30)"
    repo, shas = build(alpha=ALPHA.replace("_(blank until the pull request is merged)_", stamped))
    p = planned(repo, FakeGitHub(shas))
    alpha = [e for e in p.edits if e.path == "docs/amendments/0002-alpha.md"]
    assert len(alpha) == 1 and alpha[0].new == "- **Status:** ratified", [(e.line, e.new) for e in alpha]


def test_a_ratified_by_naming_another_pr_is_skipped_with_both_numbers():
    # GOV-4 / D8: never ratify a record whose Ratified by names a different PR.
    repo, shas = build(alpha=ALPHA.replace("_(blank until the pull request is merged)_",
                                           "https://github.com/o/r/pull/77 (merged 2026-10-01 by @o)"))
    p = planned(repo, FakeGitHub(shas))
    assert not [e for e in p.edits if e.record == "docs/amendments/0002-alpha.md"]
    reason = skip_of(p, "docs/amendments/0002-alpha.md")["reason"]
    assert "#77" in reason and "#10" in reason, reason


def test_an_unmerged_trigger_or_a_merge_by_anyone_but_the_maintainer_is_skipped():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, merged=False)
    fake.pulls[11] = pr(11, by="mallory")
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "ratify"]
    reasons = {s["record"]: s["reason"] for s in p.skipped}
    alpha = reasons["docs/amendments/0002-alpha.md"]
    assert "#10" in alpha and "not merged" in alpha
    assert "@mallory, not the maintainer @o" in reasons["docs/amendments/0003-beta.md"]


def test_an_automation_branch_or_a_bot_authored_trigger_decides_nothing():
    # D1: merged_by reads the maintainer for a FLEET_TOKEN merge too.
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, head="chore/jev-numbering")
    fake.pulls[11] = pr(11, author="dependabot[bot]")
    fake.pulls[12] = pr(12, head="wtd/fix-ci", day="2026-11-01")
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.trigger.get("number") in (10, 11, 12)]
    assert "automation branch chore/jev-numbering" in skip_of(p, "docs/amendments/0002-alpha.md")["reason"]
    assert "bot @dependabot[bot]" in skip_of(p, "docs/amendments/0003-beta.md")["reason"]
    assert "wtd/fix-ci" in skip_of(p, "docs/adr/0001-first.md")["reason"]


def test_an_agent_feature_branch_under_chore_jev_is_not_automation():
    # #442 (amendment 0004) came from chore/jev-generated-files-main-only and
    # the maintainer merged it: only the workflows' own publish branches count.
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, head="chore/jev-generated-files-main-only")
    p = planned(repo, fake)
    assert any(e.record == "docs/amendments/0002-alpha.md" for e in p.edits), p.skipped
    assert R._automation_branches(R.Tree(repo, "HEAD")) == {"chore/jev-numbering", R.BRANCH}


def test_a_pr_merged_into_another_branch_does_not_ratify():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, base="feature/x")
    p = planned(repo, fake)
    assert "docs/amendments/0002-alpha.md" in {s["record"] for s in p.skipped}


def test_a_commit_github_has_never_seen_is_skipped_not_fatal():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.unknown.add(shas["alpha"])
    p = planned(repo, fake)
    skip = skip_of(p, "docs/amendments/0002-alpha.md")
    assert "does not know commit" in skip["reason"] and "422" in skip["reason"] and not skip["read_error"]
    assert any(e.record == "docs/amendments/0003-beta.md" for e in p.edits), "the other records still plan"


def test_a_transient_github_failure_skips_only_that_record_and_says_so():
    # C3 / D9: a 5xx is a read failure (retry), not a 422 and not fatal.
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.fail.add(f"commits/{shas['alpha']}/pulls")
    p = planned(repo, fake)
    skip = skip_of(p, "docs/amendments/0002-alpha.md")
    assert skip["read_error"] and "could not list" in skip["reason"] and "502" in skip["reason"], skip
    assert "does not know" not in skip["reason"]
    assert any(e.record == "docs/amendments/0003-beta.md" for e in p.edits)
    assert "a read failure; the next run retries" in R.pr_body(p, repo)


def test_a_record_that_reached_main_by_a_direct_push_is_skipped():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.commit_pulls.pop(shas["beta"])
    p = planned(repo, fake)
    assert "without a pull request" in skip_of(p, "docs/amendments/0003-beta.md")["reason"]


def test_a_later_re_proposal_of_the_slug_never_ratifies_the_older_record():
    # C5: 0002-alpha's own PR #10 was merged by someone else; a later PR #20
    # re-adds proposed/alpha.md. #20 never proposed 0002.
    repo, shas = build()
    write(repo, "docs/amendments/proposed/alpha.md", ALPHA.replace("Alpha rule", "Alpha again"))
    again = commit(repo, "docs: propose alpha again (#20)")
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, by="someone-else")
    fake.pulls[20] = pr(20, day="2026-11-03")
    fake.commit_pulls[again] = [20]
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.record == "docs/amendments/0002-alpha.md"]
    assert "@someone-else" in skip_of(p, "docs/amendments/0002-alpha.md")["reason"]


def test_an_index_row_with_an_escaped_pipe_in_its_title_is_still_updated():
    # C7
    repo, shas = build()
    idx = repo / "docs/amendments/README.md"
    idx.write_text(idx.read_text().replace("| Alpha rule |", "| Alpha \\| rule |"))
    commit(repo, "retitle with a pipe")
    p = planned(repo, fake_for(repo))
    R.apply(repo, p)
    assert "| [0002](0002-alpha.md) | Alpha \\| rule | ratified | none |" in idx.read_text()
    assert not p.notes, p.notes


def test_an_index_cell_that_is_not_proposed_is_a_note_and_no_edit():
    # R4 (c)
    repo, shas = build()
    idx = repo / "docs/amendments/README.md"
    idx.write_text(idx.read_text().replace("| Alpha rule | proposed |", "| Alpha rule | withdrawn |"))
    commit(repo, "a hand edit")
    p = planned(repo, fake_for(repo))
    assert not [e for e in p.edits if e.path == "docs/amendments/README.md" and "Alpha" in e.old]
    assert any("status cell reads 'withdrawn'" in n for n in p.notes), p.notes


def test_a_crlf_record_is_planned_and_applied_without_losing_its_line_ends():
    # C1: bytes in, bytes out.
    repo, shas = build(beta=BETA.replace("\n", "\r\n").encode())
    p = planned(repo, FakeGitHub(shas))
    beta = [e for e in p.edits if e.path == "docs/amendments/0003-beta.md"]
    assert beta and all(e.new.endswith("\r") for e in beta), [e.new for e in beta]
    sh(repo, "checkout", "-q", "-b", R.BRANCH)
    base = sh(repo, "rev-parse", "main")
    R.apply(repo, p)
    data = (repo / "docs/amendments/0003-beta.md").read_bytes()
    assert b"- **Status:** ratified\r\n- **Ratified by:** https://github.com/o/r/pull/11" in data
    assert b"\n" not in data.replace(b"\r\n", b""), "every line still ends CRLF"
    commit(repo, "record")
    assert check(repo, base, FakeGitHub(shas)) == []


# --------------------------------------------------------------------------- #
# ADRs: acceptance and completion
# --------------------------------------------------------------------------- #
def test_adr_header_and_phase_status_lines_are_accepted_each_by_its_own_pr():
    repo, shas = build()
    p = planned(repo, FakeGitHub(shas))
    accepts = [e for e in p.edits if e.kind == "accept"]
    assert {e.trigger["number"] for e in accepts} == {12, 13}
    assert {e.key for e in accepts} == {"accept:docs/adr/0001-first.md:3", "accept:docs/adr/0001-first.md:14"}
    R.apply(repo, p)
    text = lines(repo, "docs/adr/0001-first.md")
    i = text.index("- **Status**: accepted")
    assert text[i + 1] == "- **Accepted in**: https://github.com/o/r/pull/12 (merged 2026-11-01 by @o)"
    j = text.index("  - **Status**: accepted, with the maintainer's decisions recorded below")
    assert text[j + 1] == "  - **Accepted in**: https://github.com/o/r/pull/13 (merged 2026-11-01 by @o)"
    assert "| 0001 | [The first decision](0001-first.md) | accepted |" in (repo / "docs/adr/README.md").read_text()


def test_a_status_line_inside_a_fenced_example_is_never_edited():
    # C2
    fenced = ADR_0001 + "\n## Appendix — the format\n\n```markdown\n- **Status**: proposed\n- **Tracking**: #99\n```\n"
    repo, shas = build(adr=fenced)
    p = planned(repo, FakeGitHub(shas))
    adr = [e for e in p.edits if e.path == "docs/adr/0001-first.md"]
    assert {e.line for e in adr} == {3, 21}, [(e.line, e.op, e.new) for e in adr]
    R.apply(repo, p)
    text = lines(repo, "docs/adr/0001-first.md")
    k = text.index("```markdown")
    assert text[k + 1:k + 4] == ["- **Status**: proposed", "- **Tracking**: #99", "```"]
    bad = R.Edit("docs/adr/0001-first.md", k + 2, "replace", "- **Status**: proposed", "- **Status**: accepted",
                 "accept", "docs/adr/0001-first.md", {})
    try:
        R.apply_text("\n".join(text), [bad])
    except R.RatifyError as exc:
        assert "fenced code block" in str(exc)
    else:
        raise AssertionError("an edit inside a fence was applied")


def test_completion_waits_for_the_tracking_issue_and_every_sub_issue():
    repo, shas = build()
    fake = FakeGitHub(shas)
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "complete"]
    assert p.pending and "#50 is open" in p.pending[0]["reason"]

    fake.close_epic(subs_closed=False)
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "complete"] and "#52" in p.pending[0]["reason"]

    fake = FakeGitHub(shas)
    fake.close_epic(reason="not_planned")
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "complete"] and "not_planned" in p.pending[0]["reason"]

    fake = FakeGitHub(shas)
    fake.close_epic()
    p = planned(repo, fake)
    done = [e for e in p.edits if e.kind == "complete"]
    assert len(done) == 1 and done[0].trigger["sub_issues"] == {"total": 2, "closed": 2, "open": []}
    assert done[0].trigger["closed_by"] == "o" and done[0].key == "complete:docs/adr/0001-first.md"
    R.apply(repo, p)
    text = lines(repo, "docs/adr/0001-first.md")
    i = text.index("- **Status**: accepted")
    assert text[i + 1].startswith("- **Accepted in**: ")
    assert text[i + 2] == "- **Completed**: 2026-11-05 (#50 closed)"


def test_completion_needs_the_maintainer_to_have_closed_the_tracking_issue():
    # GOV-5 / D7
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.close_epic(by="mallory")
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "complete"]
    assert "closed by @mallory, not the maintainer @o" in p.pending[0]["reason"]


def test_a_tracking_issue_that_cannot_be_read_is_pending_and_blocks_nothing_else():
    # R1 / D9: a 404 (a typo) or a 5xx is a pending entry, never a crash.
    repo, shas = build(adr=ADR_0001.replace("#50", "#999"))
    p = planned(repo, FakeGitHub(shas))
    assert any(e.kind == "ratify" for e in p.edits) and any(e.kind == "accept" for e in p.edits)
    assert "does not exist" in p.pending[0]["reason"] and not p.pending[0]["read_error"]
    fake = FakeGitHub(shas)
    fake.fail.add("issues/50")
    repo2, _ = build()
    p = planned(repo2, fake_for(repo2, fake))
    assert p.pending[0]["read_error"] and "could not read tracking issue #50" in p.pending[0]["reason"]


def test_completion_is_never_recorded_for_an_adr_that_is_not_accepted():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[12] = pr(12, by="mallory")
    fake.close_epic()
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "complete"]
    assert "not accepted" in p.pending[0]["reason"]


# --------------------------------------------------------------------------- #
# idempotence, apply, check-diff
# --------------------------------------------------------------------------- #
def test_a_second_plan_after_apply_plans_nothing():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.close_epic()
    R.apply(repo, planned(repo, fake))
    commit(repo, "chore(jev): record ratification and acceptance")
    again = planned(repo, fake)
    assert again.empty, [(e.path, e.line, e.new) for e in again.edits]


def test_apply_refuses_a_mismatch_and_writes_nothing():
    repo, shas = build()
    p = planned(repo, FakeGitHub(shas))
    before = {rel: (repo / rel).read_text() for rel in ("docs/amendments/0002-alpha.md", "docs/adr/0001-first.md")}
    rec = repo / "docs/adr/0001-first.md"
    rec.write_text(rec.read_text().replace("- **Status**: proposed\n", "- **Status**: proposed (edited)\n", 1))
    before["docs/adr/0001-first.md"] = rec.read_text()
    try:
        R.apply(repo, p)
    except R.RatifyError as exc:
        assert "the plan is stale" in str(exc)
    else:
        raise AssertionError("apply accepted a stale plan")
    assert {rel: (repo / rel).read_text() for rel in before} == before, "a refused apply changes no file"


def check(repo: Path, base: str, fake: FakeGitHub) -> list[str]:
    with github(fake):
        return R.check_diff(repo, base)[1]


def test_check_diff_accepts_exactly_the_plan():
    repo, base = branch_with_fresh_plan()
    assert check(repo, base, fake_for(repo)) == []
    assert sh(repo, "diff", "--name-only", base, "HEAD").split() == [
        "docs/adr/0001-first.md", "docs/adr/README.md", "docs/amendments/0002-alpha.md",
        "docs/amendments/0003-beta.md", "docs/amendments/README.md"]


def fake_for(repo: Path, fake: FakeGitHub | None = None) -> FakeGitHub:
    """A FakeGitHub keyed by THIS fixture's commits (found by message)."""
    log = sh(repo, "log", "--format=%H %s", "main").splitlines()
    by_msg = {line.split(" ", 1)[1]: line.split(" ", 1)[0] for line in log}
    shas = {"alpha": by_msg["docs: propose alpha (#10)"], "beta": by_msg["docs: propose beta (#11)"],
            "adr": by_msg["docs(adr): the first decision (#12)"], "adr-p1": by_msg["docs(adr): append P1 (#13)"]}
    if fake is None:
        return FakeGitHub(shas)
    fake.commit_pulls = {shas["alpha"]: [10], shas["beta"]: [11], shas["adr"]: [12], shas["adr-p1"]: [13]}
    return fake


def test_check_diff_rejects_an_extra_body_edit():
    repo, base = branch_with_fresh_plan()
    rec = repo / "docs/amendments/0002-alpha.md"
    rec.write_text(rec.read_text().replace("until the maintainer merges it", "forever"))
    commit(repo, "sneak a body edit in")
    problems = check(repo, base, fake_for(repo))
    assert len(problems) == 1 and problems[0].startswith("docs/amendments/0002-alpha.md:") and "forever" in problems[0]


def test_check_diff_rejects_a_body_edit_to_a_record_the_plan_does_not_touch():
    # R4 (a): an allowed path with no planned edit.
    repo, base = branch_with_fresh_plan()
    rec = repo / "docs/amendments/0001-ratify.md"
    rec.write_text(rec.read_text().replace("2026-10-21", "2026-10-22"))
    commit(repo, "edit a ratified record")
    problems = check(repo, base, fake_for(repo))
    assert problems == [f"docs/amendments/0001-ratify.md: changed, but the plan as of {base[:7]} has no edit for it"]


def test_check_diff_rejects_another_file():
    repo, base = branch_with_fresh_plan()
    (repo / "notes.md").write_text("changed\n")
    write(repo, "docs/constitution.md", "# new\n")
    commit(repo, "sneak files in")
    problems = check(repo, base, fake_for(repo))
    assert any(p.startswith("notes.md: not a ratification-record file") for p in problems)
    assert any(p.startswith("docs/constitution.md: not a ratification-record file") for p in problems)


def test_check_diff_rejects_a_changed_non_status_index_cell():
    repo, base = branch_with_fresh_plan()
    idx = repo / "docs/amendments/README.md"
    idx.write_text(idx.read_text().replace("| Alpha rule | ratified |", "| Alpha rule (amended) | ratified |"))
    commit(repo, "retitle")
    problems = check(repo, base, fake_for(repo))
    assert len(problems) == 1 and problems[0].startswith("docs/amendments/README.md:")


def test_check_diff_sees_line_endings_and_file_modes():
    # C1: CRLF on a whole planned file, a CR on one non-status line, +x.
    repo, base = branch_with_fresh_plan()
    rec = repo / "docs/amendments/0002-alpha.md"
    rec.write_bytes(rec.read_bytes().replace(b"\n", b"\r\n"))
    commit(repo, "crlf")
    problems = check(repo, base, fake_for(repo))
    assert len(problems) == 1 and problems[0].startswith("docs/amendments/0002-alpha.md:1:"), problems

    repo, base = branch_with_fresh_plan()
    idx = repo / "docs/amendments/README.md"
    idx.write_bytes(idx.read_bytes().replace(b"| # | Title | Status | Affects |\n",
                                             b"| # | Title | Status | Affects |\r\n"))
    commit(repo, "a stray CR")
    problems = check(repo, base, fake_for(repo))
    assert len(problems) == 1 and problems[0].startswith("docs/amendments/README.md:3:"), problems

    repo, base = branch_with_fresh_plan()
    sh(repo, "update-index", "--chmod=+x", "docs/adr/README.md")
    sh(repo, "commit", "-qm", "chmod")
    problems = check(repo, base, fake_for(repo))
    assert problems == ["docs/adr/README.md: mode 100644 → 100755 — a record file stays 100644"], problems


def test_check_diff_rejects_a_missing_planned_edit_and_a_new_record():
    repo, base = branch_with_fresh_plan()
    sh(repo, "checkout", "-q", base, "--", "docs/adr/0001-first.md")
    write(repo, "docs/amendments/0009-extra.md", "# 0009 — Extra\n")
    commit(repo, "drop one, add one")
    problems = check(repo, base, fake_for(repo))
    assert any("docs/adr/0001-first.md: the plan edits it, but the diff does not" in p for p in problems)
    assert any(p.startswith("docs/amendments/0009-extra.md: added") for p in problems)


def branch_with_fresh_plan(fake: FakeGitHub | None = None) -> tuple[Path, str]:
    repo, _ = build()
    base = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "-b", R.BRANCH)
    fake = fake_for(repo, fake)
    with github(fake):
        R.apply(repo, R.plan(repo))
    commit(repo, "chore(jev): record ratification and acceptance")
    assert check(repo, base, fake) == []
    return repo, base


def test_a_plan_edit_outside_the_allowed_shapes_is_refused():
    bad = R.Edit("docs/amendments/0002-alpha.md", 3, "replace", "- **Status:** proposed", "- **Affects:** all",
                 "ratify", "docs/amendments/0002-alpha.md", {})
    try:
        R.apply_text("# x\n\n- **Status:** proposed\n", [bad])
    except R.RatifyError as exc:
        assert "not a Status" in str(exc)
    else:
        raise AssertionError("an Affects edit was applied")
    other = R.Edit("docs/constitution.md", 1, "replace", "# x", "- **Status:** ratified", "ratify", "x", {})
    assert "not a ratification-record file" in R._shape_problem(other)


# --------------------------------------------------------------------------- #
# the held plan: verify, select and guard
# --------------------------------------------------------------------------- #
def record_pr(repo: Path, fake: FakeGitHub, p: R.Plan, *, number: int = 90) -> str:
    """Cut chore/jev-ratify as ONE commit on main from plan `p`, and make
    the fake answer for it as GitHub would once its checks passed."""
    sh(repo, "checkout", "-q", "-B", R.BRANCH, "main")
    R.apply(repo, p)
    head = commit(repo, "chore(jev): record ratification and acceptance")
    fake.branches["main"] = sh(repo, "rev-parse", "main")
    fake.check_runs[head] = [{"name": "python-tests", "status": "completed", "conclusion": "success"},
                             {"name": "verify", "status": "completed", "conclusion": "skipped"}]
    fake.statuses[head] = [{"context": "ci/x", "state": "success"}]
    fake.pulls[number] = {"number": number, "state": "open", "draft": False, "merged_at": None,
                          "html_url": f"https://github.com/o/r/pull/{number}", "mergeable": True,
                          "mergeable_state": "clean", "labels": [{"name": "jev-ratify"}], "body": R.pr_body(p, repo),
                          "head": {"ref": R.BRANCH, "sha": head, "repo": {"full_name": "o/r"}},
                          "base": {"ref": "main"}, "user": {"login": "o"}}
    return head


def held_setup(fake: FakeGitHub | None = None) -> tuple[Path, FakeGitHub, R.Plan, str]:
    repo, _ = build()
    fake = fake_for(repo, fake)
    p = planned(repo, fake, ref="main")
    head = record_pr(repo, fake, p)
    return repo, fake, p, head


def run_guard(repo: Path, fake: FakeGitHub, head: str, held: R.Plan | None, number: int = 90):
    with github(fake):
        return R.guard(repo, number, head, held=held)


def test_guard_says_go_for_the_jobs_own_one_commit_pr_with_every_check_passed():
    repo, fake, p, head = held_setup()
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.GO, reasons
    code, reasons = run_guard(repo, fake, head, None)
    assert code == R.GO, ("the keys in the body re-derive the plan", reasons)


def test_guard_stops_on_a_pr_merged_closed_or_held_by_a_person():
    repo, fake, p, head = held_setup()
    fake.pulls[90]["labels"].append({"name": "needs-amr"})
    assert run_guard(repo, fake, head, p)[0] == R.STOP
    fake.pulls[90].update(labels=[], state="closed")
    assert run_guard(repo, fake, head, p)[0] == R.STOP
    fake.pulls[90].update(merged_at="2026-11-02T00:00:00Z")
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.STOP and "already merged" in reasons[0]


def test_guard_refuses_a_pr_that_is_not_the_jobs_own():
    # GOV-2 / M3: a fork's branch of the same name, another author, another branch.
    for change in ({"head": {"ref": R.BRANCH, "repo": {"full_name": "mallory/r"}}},
                   {"user": {"login": "mallory"}},
                   {"head": {"ref": "feature/x", "repo": {"full_name": "o/r"}}}):
        repo, fake, p, head = held_setup()
        fake.pulls[90]["head"].update(change.get("head") or {})
        fake.pulls[90].update({k: v for k, v in change.items() if k != "head"})
        code, reasons = run_guard(repo, fake, head, p)
        assert code == R.REFUSE and "not the job's own" in reasons[0], (change, reasons)


def test_guard_refuses_a_moved_head_a_draft_and_another_base():
    repo, fake, p, head = held_setup()
    fake.pulls[90]["head"]["sha"] = "f" * 40
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.REFUSE and "head moved" in reasons[0]
    repo, fake, p, head = held_setup()
    fake.pulls[90]["draft"] = True
    assert run_guard(repo, fake, head, p)[0] == R.REFUSE
    repo, fake, p, head = held_setup()
    fake.pulls[90]["base"] = {"ref": "dev"}
    assert run_guard(repo, fake, head, p)[0] == R.REFUSE


def test_guard_refuses_a_head_that_is_not_one_single_parent_commit():
    # GOV-6 / D10: a merge commit would carry a foreign parent into main.
    repo, fake, p, head = held_setup()
    sh(repo, "checkout", "-q", "-b", "side", "main~1")
    write(repo, "side.md", "x\n")
    side = commit(repo, "side")
    sh(repo, "checkout", "-q", R.BRANCH)
    sh(repo, "merge", "-q", "--no-ff", "--no-edit", side)
    merged = sh(repo, "rev-parse", "HEAD")
    fake.pulls[90]["head"]["sha"] = merged
    code, reasons = run_guard(repo, fake, merged, p)
    assert code == R.REFUSE and "2 parents" in reasons[0], reasons


def test_guard_re_cuts_when_main_moved():
    # M5
    repo, fake, p, head = held_setup()
    fake.branches["main"] = "e" * 40
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.RECUT and "re-cut" in reasons[0]
    fake.branches["main"] = sh(repo, "rev-parse", "main")
    fake.pulls[90]["mergeable_state"] = "behind"
    assert run_guard(repo, fake, head, p)[0] == R.RECUT


def test_guard_reads_the_checks_of_the_head_sha_itself():
    # M7 / D3: by SHA; at least one; only success, skipped, neutral.
    repo, fake, p, head = held_setup()
    fake.check_runs[head][0].update(conclusion="failure")
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.REFUSE and "python-tests (failure)" in reasons[0]
    repo, fake, p, head = held_setup()
    fake.check_runs[head][0].update(status="in_progress", conclusion=None)
    assert run_guard(repo, fake, head, p)[0] == R.WAIT
    repo, fake, p, head = held_setup()
    fake.check_runs[head], fake.statuses[head] = [], []
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.WAIT and "no check has reported" in reasons[0]
    repo, fake, p, head = held_setup()
    fake.statuses[head] = [{"context": "ci/x", "state": "error"}]
    assert run_guard(repo, fake, head, p)[0] == R.REFUSE
    repo, fake, p, head = held_setup()
    fake.statuses[head] = [{"context": "ci/x", "state": "pending"}]
    assert run_guard(repo, fake, head, p)[0] == R.WAIT
    repo, fake, p, head = held_setup()
    fake.check_runs[head][1].update(conclusion="neutral")
    assert run_guard(repo, fake, head, p)[0] == R.GO
    calls = [c for c in fake.calls if "check-runs" in " ".join(c)]
    assert calls and all(f"commits/{head}/check-runs" in " ".join(c) for c in calls)


def test_guard_waits_for_mergeability_and_refuses_a_conflict():
    repo, fake, p, head = held_setup()
    fake.pulls[90].update(mergeable=None, mergeable_state="unknown")
    assert run_guard(repo, fake, head, p)[0] == R.WAIT
    fake.pulls[90].update(mergeable=False, mergeable_state="dirty")
    assert run_guard(repo, fake, head, p)[0] == R.REFUSE


def test_guard_refuses_a_head_that_is_not_exactly_its_plan():
    repo, fake, p, head = held_setup()
    rec = repo / "docs/amendments/0002-alpha.md"
    rec.write_text(rec.read_text().replace("until the maintainer merges it", "forever"))
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "--amend", "--no-edit")
    sneaky = sh(repo, "rev-parse", "HEAD")
    fake.pulls[90]["head"]["sha"] = sneaky
    fake.check_runs[sneaky] = fake.check_runs[head]
    code, reasons = run_guard(repo, fake, sneaky, p)
    assert code == R.REFUSE and "forever" in reasons[0], reasons


def test_guard_ignores_a_record_that_became_eligible_during_the_wait():
    # M1 / D2: the epic closes while the checks run; the PR still merges.
    repo, fake, p, head = held_setup()
    assert not [e for e in p.edits if e.kind == "complete"]
    fake.close_epic()
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.GO, reasons
    assert run_guard(repo, fake, head, None)[0] == R.GO


def test_guard_only_waits_when_github_cannot_be_read():
    # M1 / D2: a transient GET failure never parks the PR.
    repo, fake, p, head = held_setup()
    alpha = next(c for c, n in fake.commit_pulls.items() if n == [10])
    fake.fail.add(f"commits/{alpha}/pulls")
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.WAIT and "could not list" in " ".join(reasons), reasons
    assert run_guard(repo, fake, head, None)[0] == R.WAIT
    fake.fail = {"pulls/90"}
    assert run_guard(repo, fake, head, p)[0] == R.WAIT
    fake.fail = {f"commits/{head}/check-runs"}
    assert run_guard(repo, fake, head, p)[0] == R.WAIT
    fake.fail = {"repos/o/r/branches"}
    assert run_guard(repo, fake, head, p)[0] == R.WAIT


def test_guard_refuses_a_record_whose_trigger_no_longer_holds_and_re_cuts_a_changed_one():
    repo, fake, p, head = held_setup()
    fake.pulls[11] = pr(11, by="mallory")
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.REFUSE and "ratify:docs/amendments/0003-beta.md: no longer holds" in reasons[0], reasons

    fake = FakeGitHub({"alpha": "", "beta": "", "adr": "", "adr-p1": ""})
    fake.close_epic()
    repo, fake, p, head = held_setup(fake)
    assert [e for e in p.edits if e.kind == "complete"]
    fake.issues[50]["closed_at"] = "2026-11-09T09:00:00Z"
    code, reasons = run_guard(repo, fake, head, p)
    assert code == R.RECUT and "changed since the plan" in reasons[0], reasons


def test_guard_refuses_a_pr_whose_body_names_no_plan():
    repo, fake, p, head = held_setup()
    fake.pulls[90]["body"] = "no mark here"
    code, reasons = run_guard(repo, fake, head, None)
    assert code == R.REFUSE and "names no plan" in reasons[0]


def test_select_creates_updates_holds_and_ignores_a_fork():
    repo, fake, p, head = held_setup()

    def own(number, state="open", labels=(), body="", merged=False, repo_name="o/r"):
        return {"number": number, "state": state, "labels": [{"name": n} for n in labels], "body": body,
                "merged_at": "2026-11-02T00:00:00Z" if merged else None, "closed_at": "2026-11-02T00:00:00Z",
                "head": {"ref": R.BRANCH, "repo": {"full_name": repo_name}}, "user": {"login": "o"}}

    def sel(manual=False):
        with github(fake):
            return R.select(p, manual=manual)

    fake.record_pulls = []
    assert sel()["action"] == "create"
    fake.record_pulls = [own(91, repo_name="mallory/r")]
    assert sel()["action"] == "create", "a fork's PR from a branch of the same name is never the job's"
    fake.record_pulls = [own(92)]
    assert sel() == {"action": "update", "number": 92, "reason": "updating the open record PR #92"}
    fake.record_pulls = [own(93, labels=["agent:hold"])]
    assert sel()["action"] == "hold" and "agent:hold" in sel()["reason"]
    # D4 / M4: the maintainer closed the record PR for this same plan.
    fake.issues[94] = {"number": 94, "closed_by": {"login": "o"}}
    fake.record_pulls = [own(94, state="closed", body=R.pr_body(p, repo))]
    held = sel()
    assert held["action"] == "hold" and "closed unmerged by @o" in held["reason"], held
    assert sel(manual=True)["action"] == "create", "a manual dispatch lifts the hold"
    fake.record_pulls = [own(95, state="closed", body="<!-- jev-ratify plan: {\"digest\": \"other\"} -->")]
    assert sel()["action"] == "create", "a different plan is not held"
    fake.record_pulls = [own(96, state="closed", body=R.pr_body(p, repo), merged=True)]
    assert sel()["action"] == "create", "a merged record PR holds nothing"


def test_check_diff_with_the_held_plan_exits_by_verdict():
    repo, fake, p, head = held_setup()
    plan_file = SCRATCH / f"jev-ratify-plan-{head[:8]}.json"
    plan_file.write_text(json.dumps(p.to_dict()))
    base = sh(repo, "rev-parse", "main")
    args = ["ratify", "check-diff", "--root", str(repo), "--base", base, "--plan", str(plan_file)]
    with github(fake), contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(args) == 0
        fake.fail = {"commits/"}
        assert cli.main(args) == 3, "GitHub unreadable: not yet, not a mismatch"
        fake.fail = set()
        (repo / "notes.md").write_text("x\n")
        commit(repo, "extra")
        assert cli.main(args) == 1
    plan_file.unlink()


# --------------------------------------------------------------------------- #
# the PR body and the CLI
# --------------------------------------------------------------------------- #
def test_the_pr_body_carries_every_trigger_and_the_guard():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[11] = pr(11, by="mallory")
    p = planned(repo, fake)
    body = R.pr_body(p, repo)
    assert "**is** the ratification" in body and "§ 8.3" in body
    assert "| [0002](docs/amendments/0002-alpha.md) Alpha rule | proposed → ratified | " in body
    assert "[#10](https://github.com/o/r/pull/10) PR 10 | 2026-10-30 | @o | `1010101` |" in body
    assert "[ADR 0001](docs/adr/0001-first.md) The first decision | L3 |" in body
    assert "[#10](https://github.com/o/r/pull/10) linked issue(s) #110" in body, "closing issues are listed"
    assert "@mallory, not the maintainer @o" in body, "skips carry their reason"
    assert "issue 50" in body and "completes when" in body and "(open sub-issues: #52)" in body, \
        "an open tracking issue is a follow-up"
    assert "--merge --match-head-commit" in body and "never squash" in body and "ratify guard" in body
    mark = R._plan_mark(body)
    assert mark["digest"] == p.digest() and mark["keys"] == p.keys() and mark["ref"] == p.ref
    assert R.pr_title(p) == "chore(jev): record ratification and acceptance (1 ratified, 2 accepted)"


def test_the_pr_body_never_carries_a_closing_keyword_before_a_reference():
    # M2 / D6: GitHub would close the issue again when the record PR merges.
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10]["title"] = "docs: closes #7 and Fixes: o/r#8, resolved https://github.com/o/r/issues/9"
    fake.close_epic(subs_closed=False)
    body = R.pr_body(planned(repo, fake), repo)
    assert not R.CLOSING_REF.search(body), R.CLOSING_REF.search(body)
    assert "closes (ref #7)" in body and "Fixes: (ref o/r#8)" in body
    for text in ("- #521 closed #485", "Fix #3", "resolves GH-4", "fixed:#5"):
        assert R.CLOSING_REF.search(text) and not R.CLOSING_REF.search(R.defuse(text)), text


def test_closing_issues_fall_back_to_the_body_without_graphql():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.graphql_ok = False
    p = planned(repo, fake)
    t = next(e.trigger for e in p.edits if e.trigger.get("number") == 10)
    assert t["closing_issues"] == [110]


def test_every_github_call_is_a_read_the_jev_guard_allows():
    repo, fake, p, head = held_setup()
    fake.close_epic()
    planned(repo, fake)
    run_guard(repo, fake, head, None)
    with github(fake):
        R.select(p)
    assert fake.calls and all(c[0] == "api" for c in fake.calls)
    C.assert_safe_git(["blame", "--porcelain", "-L", "3,3", "HEAD", "--", "docs/adr/0001-first.md"])
    C.assert_safe_git(["log", "-1", "--format=%P", head])


def test_the_cli_plans_applies_checks_and_guards():
    repo, _ = build()
    base = sh(repo, "rev-parse", "HEAD")
    fake = fake_for(repo)
    out = io.StringIO()
    with github(fake), contextlib.redirect_stdout(out):
        assert cli.main(["ratify", "plan", "--json", "--root", str(repo), "--out", str(repo / ".plan.json")]) == 0
    data = json.loads(out.getvalue())
    assert data["schema"] == "jev-ratify/v1" and data["maintainer"] == "o" and data["edits"]
    assert {"path", "line", "op", "old", "new", "kind", "trigger", "key"} <= set(data["edits"][0])
    assert data["keys"] and re.fullmatch(r"[0-9a-f]{64}", data["digest"])
    sh(repo, "checkout", "-q", "-b", R.BRANCH)
    with github(fake), contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["ratify", "apply", "--root", str(repo), "--plan", str(repo / ".plan.json")]) == 0
    (repo / ".plan.json").unlink()
    commit(repo, "record")
    out = io.StringIO()
    with github(fake), contextlib.redirect_stdout(out):
        assert cli.main(["ratify", "check-diff", "--root", str(repo), "--base", base]) == 0
        assert cli.main(["ratify", "pr-body", "--root", str(repo), "--ref", base, "--title"]) == 0
    assert "exactly the plan" in out.getvalue() and "chore(jev): record ratification" in out.getvalue()
    with github(fake), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert cli.main(["ratify", "check-diff", "--root", str(repo)]) == 2, "check-diff needs --base"
        assert cli.main(["ratify", "guard", "--root", str(repo), "--pr", "1"]) == 2, "guard needs --sha"
        assert cli.main(["ratify", "select", "--root", str(repo)]) == 2, "select needs --plan"
        (repo / "notes.md").write_text("x\n")
        commit(repo, "extra")
        assert cli.main(["ratify", "check-diff", "--root", str(repo), "--base", base]) == 1
    repo, fake, p, head = held_setup()
    out = io.StringIO()
    with github(fake), contextlib.redirect_stdout(out):
        assert cli.main(["ratify", "guard", "--root", str(repo), "--pr", "90", "--sha", head, "--json"]) == R.GO
    assert json.loads(out.getvalue())["verdict"] == "go"
    fake.check_runs[head] = []
    fake.statuses[head] = []
    with github(fake), contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["ratify", "guard", "--root", str(repo), "--pr", "90", "--sha", head]) == R.WAIT


# --------------------------------------------------------------------------- #
# the workflow job that merges the record
# --------------------------------------------------------------------------- #
class _Loader(yaml.SafeLoader):
    """`on:` stays a key (YAML 1.2 reads only true/false as booleans)."""


_Loader.yaml_implicit_resolvers = {k: [r for r in v if r[0] != "tag:yaml.org,2002:bool"]
                                   for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}


def _job() -> tuple[dict, dict]:
    wf = yaml.load(WORKFLOW.read_text(), Loader=_Loader)
    return wf, wf["jobs"]["ratify"]


def test_the_ratify_job_merges_only_with_a_merge_commit_after_its_guard():
    wf, job = _job()
    assert wf["on"]["issues"]["types"] == ["closed"] and "push" in wf["on"] and "workflow_dispatch" in wf["on"]
    assert "schedule" not in wf["on"]
    assert "github.event_name != 'issues'" in str(wf["jobs"]["number"]["if"]), "numbering never runs on an issue"
    assert job["needs"] == "number" or job["needs"] == ["number"]
    cond = str(job["if"])
    assert "!cancelled()" in cond and "github.event_name == 'workflow_dispatch'" in cond
    assert "vars.JEV_RATIFY_ENABLED != 'false'" in cond, "the kill switch defaults on and dispatch bypasses it"
    # three attempts, each waiting up to 30 minutes for the record PR's checks, fit; still bounded
    assert 3 * 30 + 10 <= int(job["timeout-minutes"]) <= 120, job["timeout-minutes"]
    runs = "\n".join(str(s.get("run") or "") for s in job["steps"])
    code = [ln for ln in runs.splitlines() if not ln.strip().startswith("#")]
    merges = [ln for ln in code if "gh pr merge" in ln]
    assert len(merges) == 1, "the job merges the record PR in one place"
    assert "--merge" in merges[0] and "--match-head-commit" in merges[0], merges[0]
    for forbidden in ("--squash", "--rebase", "--admin", "--auto", "gh pr checks"):
        assert forbidden not in runs, f"{forbidden} in the ratify job"
    assert "resolve-fleet-token" in json.dumps(job["steps"]), "the token is probed, never presence-checked"
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "main" and int(checkout["with"]["fetch-depth"]) == 0


def test_every_label_a_workflow_creates_fits_githubs_description_limit():
    # The first live ratify run died on `gh label create`: GitHub refuses a
    # description over 100 characters (HTTP 422), and `set -e` ended the step.
    found = 0
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        # join `\`-continued shell lines first, so a description on the next line is seen
        text = re.sub(r"\\\n\s*", " ", path.read_text(encoding="utf-8"))
        for m in re.finditer(r"gh label create[^\n]*", text):
            for d in re.findall(r'--description\s+"([^"]*)"', m.group(0)):
                found += 1
                assert len(d) <= 100, f"{path.name}: label description is {len(d)} characters: {d!r}"
    assert found >= 3, "the ratify job's three labels are checked"


def test_the_merge_runs_only_on_the_python_guards_go():
    # R3 / D3: every merge guard lives in `ratify guard`, which is unit-tested
    # above; the shell only branches on its exit code.
    _wf, job = _job()
    step = next(s for s in job["steps"] if "gh pr merge" in str(s.get("run") or ""))
    run = str(step["run"])
    assert "python3 -m tools.jev ratify guard --pr" in run and "--sha" in run and "--plan" in run
    guard_at, merge_at = run.index("ratify guard --pr"), run.index("gh pr merge")
    assert guard_at < merge_at
    case = run[guard_at:]
    assert re.search(r"\b0\)", case) and re.search(r"\b3\)", case) and re.search(r"\b5\)", case) \
        and re.search(r"\b6\)", case), "go, not yet, re-cut and stop each have a branch"
    assert re.search(r"\b4\) refuse ", case) and not re.search(r"\*\) refuse", case), \
        "only the guard's refuse verdict parks the PR; a crash does not"
    assert "--match-head-commit \"$head\"" in run and "go_count" in run, "two go verdicts in a row, then merge"
    assert "ratify select --plan" in run, "the job's own PR is chosen in Python (same repo, maintainer)"
    assert "ratify check-diff --base origin/main --plan" in run, "the commit is proved before it is pushed"
    assert "$PAT" in run and "!= 'true'" in run, "writing needs the probed PAT"
    assert re.search(r"attempt.*-ge.*3|attempts=3", run), "main moving is re-cut a bounded number of times"
    assert "%P %ae" in run, "an existing head is reused only as one commit by the job's identity"


def test_the_refusal_hand_off_touches_only_an_open_pr_of_the_job():
    # M6 / GOV-8: never label a merged or closed PR; move the project item.
    _wf, job = _job()
    hand = next(s for s in job["steps"] if "failure()" in str(s.get("if") or ""))
    assert "--add-label needs-amr" in str(hand["run"])
    run = str(hand["run"])
    assert "ratify-fail.txt" in run and "OPEN" in run and "isCrossRepository" in run
    assert run.index("OPEN") < run.index("--add-label needs-amr")
    assert "gh project item-edit" in run and "Needs Amr" in run


def test_the_python_never_merges():
    src = (ROOT / "tools/jev/ratify.py").read_text()
    code = [ln for ln in src.splitlines() if "_gh_json([" in ln or "gh(" in ln]
    assert code and not any("merge" in ln for ln in code)
    try:
        C.assert_no_admin(["pr", "merge", "1", "--merge"])
    except C.JevError:
        pass
    else:
        raise AssertionError("the JEV guard let a merge through")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

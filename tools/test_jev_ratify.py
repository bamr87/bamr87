#!/usr/bin/env python3
"""
Fixture tests for tools/jev/ratify.py — the ratification, acceptance and
completion records a maintainer's merge decided — and for the `ratify` job in
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


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "submodule.recurse=false", "-c", "commit.gpgsign=false", *args], cwd=repo,
                          check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


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


def build() -> tuple[Path, dict[str, str]]:
    """The hub's history in miniature. Returns (repo, {step: sha})."""
    repo = Path(tempfile.mkdtemp(prefix="jev-ratify-"))
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "config", "user.email", "t@example.com")
    sh(repo, "config", "user.name", "t")
    write(repo, "_data/fleet.yml", "hub:\n  repo: o/r\n")
    write(repo, "docs/amendments/README.md", AMEND_INDEX)
    write(repo, "docs/amendments/0000-template.md", "# NNNN — Title\n\n- **Status:** proposed\n")
    write(repo, "docs/amendments/0001-ratify.md", AMEND_0001)
    write(repo, "docs/adr/README.md", ADR_INDEX)
    write(repo, "docs/adr/0000-template.md", "# ADR NNNN — Title\n\n- **Status**: proposed\n")
    write(repo, "notes.md", "unrelated\n")
    shas = {"base": commit(repo, "base")}
    write(repo, "docs/amendments/proposed/alpha.md", ALPHA)
    shas["alpha"] = commit(repo, "docs: propose alpha (#10)")
    compile_amendment(repo, "alpha", "0002", "Alpha rule")
    shas["compile-alpha"] = commit(repo, "chore(jev): assign ids")
    write(repo, "docs/amendments/proposed/beta.md", BETA)
    shas["beta"] = commit(repo, "docs: propose beta (#11)")
    compile_amendment(repo, "beta", "0003", "Beta rule")
    shas["compile-beta"] = commit(repo, "chore(jev): assign ids")
    write(repo, "docs/adr/0001-first.md", ADR_0001)
    idx = repo / "docs/adr/README.md"
    idx.write_text(idx.read_text() + "| 0001 | [The first decision](0001-first.md) | proposed |\n")
    shas["adr"] = commit(repo, "docs(adr): the first decision (#12)")
    adr = repo / "docs/adr/0001-first.md"
    adr.write_text(adr.read_text() + ADR_P1)
    shas["adr-p1"] = commit(repo, "docs(adr): append P1 (#13)")
    return repo, shas


def pr(number: int, merged: bool = True, by: str = "o", base: str = "main", day: str = "2026-10-30") -> dict:
    return {"number": number, "title": f"PR {number}", "html_url": f"https://github.com/o/r/pull/{number}",
            "merged_at": f"{day}T12:00:00Z" if merged else None, "merged_by": {"login": by} if merged else None,
            "merge_commit_sha": (str(number) * 40)[:40], "base": {"ref": base}, "labels": [{"name": "governance"}],
            "body": f"Fixes #{number + 100}", "state": "closed" if merged else "open"}


class FakeGitHub:
    """Answers the planner's GETs from tables; refuses what the JEV guard refuses."""

    def __init__(self, shas: dict[str, str]):
        self.pulls = {10: pr(10), 11: pr(11), 12: pr(12, day="2026-11-01"), 13: pr(13, day="2026-11-01")}
        self.commit_pulls = {shas["alpha"]: [10], shas["beta"]: [11], shas["adr"]: [12], shas["adr-p1"]: [13]}
        self.issues = {50: {"number": 50, "title": "Epic", "html_url": "https://github.com/o/r/issues/50",
                            "state": "open", "state_reason": None, "closed_at": None}}
        self.subs = {50: [{"number": 51, "state": "closed"}, {"number": 52, "state": "open"}]}
        self.graphql_ok = True
        self.calls: list[list[str]] = []

    def close_epic(self, reason: str = "completed", subs_closed: bool = True) -> None:
        self.issues[50].update(state="closed", state_reason=reason, closed_at="2026-11-05T09:00:00Z")
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
        parts = path.split("?")[0].split("/")
        if path == "repos/o/r":
            return {"default_branch": "main"}
        if parts[3] == "commits":
            return [copy.deepcopy(self.pulls[n]) for n in self.commit_pulls.get(parts[4], [])]
        if parts[3] == "pulls":
            return copy.deepcopy(self.pulls[int(parts[4])])
        if parts[3] == "issues" and parts[-1] == "sub_issues":
            return [copy.deepcopy(self.subs.get(int(parts[4]), []))]
        if parts[3] == "issues":
            return copy.deepcopy(self.issues[int(parts[4])])
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


def test_ratified_by_is_inserted_after_status_when_the_record_has_none():
    repo, shas = build()
    p = planned(repo, FakeGitHub(shas))
    R.apply(repo, p)
    text = lines(repo, "docs/amendments/0003-beta.md")
    i = text.index("- **Status:** ratified")
    assert text[i + 1] == "- **Ratified by:** https://github.com/o/r/pull/11 (merged 2026-10-30 by @o)"
    assert text[i + 2] == "- **Number:** 0003"


def test_an_unmerged_trigger_or_a_merge_by_anyone_but_the_maintainer_is_skipped():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, merged=False)
    fake.pulls[11] = pr(11, by="mallory")
    p = planned(repo, fake)
    assert not [e for e in p.edits if e.kind == "ratify"]
    reasons = {s["record"]: s["reason"] for s in p.skipped}
    assert "#10" in reasons["docs/amendments/0002-alpha.md"] and "not merged" in reasons["docs/amendments/0002-alpha.md"]
    assert "@mallory, not the maintainer @o" in reasons["docs/amendments/0003-beta.md"]


def test_a_pr_merged_into_another_branch_does_not_ratify():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.pulls[10] = pr(10, base="feature/x")
    p = planned(repo, fake)
    assert "docs/amendments/0002-alpha.md" in {s["record"] for s in p.skipped}


def test_a_record_that_reached_main_by_a_direct_push_is_skipped():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.commit_pulls.pop(shas["beta"])
    p = planned(repo, fake)
    skip = next(s for s in p.skipped if s["record"] == "docs/amendments/0003-beta.md")
    assert "without a pull request" in skip["reason"]


# --------------------------------------------------------------------------- #
# ADRs: acceptance and completion
# --------------------------------------------------------------------------- #
def test_adr_header_and_phase_status_lines_are_accepted_each_by_its_own_pr():
    repo, shas = build()
    p = planned(repo, FakeGitHub(shas))
    accepts = [e for e in p.edits if e.kind == "accept"]
    assert {e.trigger["number"] for e in accepts} == {12, 13}
    R.apply(repo, p)
    text = lines(repo, "docs/adr/0001-first.md")
    i = text.index("- **Status**: accepted")
    assert text[i + 1] == "- **Accepted in**: https://github.com/o/r/pull/12 (merged 2026-11-01 by @o)"
    j = text.index("  - **Status**: accepted, with the maintainer's decisions recorded below")
    assert text[j + 1] == "  - **Accepted in**: https://github.com/o/r/pull/13 (merged 2026-11-01 by @o)"
    assert "| 0001 | [The first decision](0001-first.md) | accepted |" in (repo / "docs/adr/README.md").read_text()


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
    R.apply(repo, p)
    text = lines(repo, "docs/adr/0001-first.md")
    i = text.index("- **Status**: accepted")
    assert text[i + 1].startswith("- **Accepted in**: ")
    assert text[i + 2] == "- **Completed**: 2026-11-05 (#50 closed)"


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


def fake_for(repo: Path) -> FakeGitHub:
    """A FakeGitHub keyed by THIS fixture's commits (found by message)."""
    log = sh(repo, "log", "--format=%H %s", "main").splitlines()
    by_msg = {line.split(" ", 1)[1]: line.split(" ", 1)[0] for line in log}
    shas = {"alpha": by_msg["docs: propose alpha (#10)"], "beta": by_msg["docs: propose beta (#11)"],
            "adr": by_msg["docs(adr): the first decision (#12)"], "adr-p1": by_msg["docs(adr): append P1 (#13)"]}
    return FakeGitHub(shas)


def test_check_diff_rejects_an_extra_body_edit():
    repo, base = branch_with_fresh_plan()
    rec = repo / "docs/amendments/0002-alpha.md"
    rec.write_text(rec.read_text().replace("until the maintainer merges it", "forever"))
    commit(repo, "sneak a body edit in")
    problems = check(repo, base, fake_for(repo))
    assert len(problems) == 1 and problems[0].startswith("docs/amendments/0002-alpha.md:") and "forever" in problems[0]


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


def test_check_diff_rejects_a_missing_planned_edit_and_a_new_record():
    repo, base = branch_with_fresh_plan()
    sh(repo, "checkout", "-q", base, "--", "docs/adr/0001-first.md")
    write(repo, "docs/amendments/0009-extra.md", "# 0009 — Extra\n")
    commit(repo, "drop one, add one")
    problems = check(repo, base, fake_for(repo))
    assert any("docs/adr/0001-first.md: the plan edits it, but the diff does not" in p for p in problems)
    assert any(p.startswith("docs/amendments/0009-extra.md: added") for p in problems)


def branch_with_fresh_plan() -> tuple[Path, str]:
    repo, _ = build()
    base = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "-b", R.BRANCH)
    fake = fake_for(repo)
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
    assert "#10 closed #110" in body, "closing issues are listed"
    assert "@mallory, not the maintainer @o" in body, "skips carry their reason"
    assert "#50" in body and "completes when" in body, "an open tracking issue is a follow-up"
    assert "--merge --match-head-commit" in body and "never squash" in body
    assert R.pr_title(p) == "chore(jev): record ratification and acceptance (1 ratified, 2 accepted)"


def test_closing_issues_fall_back_to_the_body_without_graphql():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.graphql_ok = False
    p = planned(repo, fake)
    t = next(e.trigger for e in p.edits if e.trigger.get("number") == 10)
    assert t["closing_issues"] == [110]


def test_every_github_call_is_a_read_the_jev_guard_allows():
    repo, shas = build()
    fake = FakeGitHub(shas)
    fake.close_epic()
    planned(repo, fake)
    assert fake.calls and all(c[0] == "api" for c in fake.calls)
    C.assert_safe_git(["blame", "--porcelain", "-L", "3,3", "HEAD", "--", "docs/adr/0001-first.md"])


def test_the_cli_plans_applies_and_checks():
    repo, _ = build()
    base = sh(repo, "rev-parse", "HEAD")
    fake = fake_for(repo)
    out = io.StringIO()
    with github(fake), contextlib.redirect_stdout(out):
        assert cli.main(["ratify", "plan", "--json", "--root", str(repo), "--out", str(repo / ".plan.json")]) == 0
    data = json.loads(out.getvalue())
    assert data["schema"] == "jev-ratify/v1" and data["maintainer"] == "o" and data["edits"]
    assert {"path", "line", "op", "old", "new", "kind", "trigger"} <= set(data["edits"][0])
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
        (repo / "notes.md").write_text("x\n")
        commit(repo, "extra")
        assert cli.main(["ratify", "check-diff", "--root", str(repo), "--base", base]) == 1


# --------------------------------------------------------------------------- #
# the workflow job that merges the record
# --------------------------------------------------------------------------- #
class _Loader(yaml.SafeLoader):
    """`on:` stays a key (YAML 1.2 reads only true/false as booleans)."""


_Loader.yaml_implicit_resolvers = {k: [r for r in v if r[0] != "tag:yaml.org,2002:bool"]
                                   for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}


def test_the_ratify_job_merges_only_with_a_merge_commit_after_its_guards():
    wf = yaml.load(WORKFLOW.read_text(), Loader=_Loader)
    assert wf["on"]["issues"]["types"] == ["closed"] and "push" in wf["on"] and "workflow_dispatch" in wf["on"]
    jobs = wf["jobs"]
    assert "github.event_name != 'issues'" in str(jobs["number"]["if"]), "numbering never runs on an issue event"
    job = jobs["ratify"]
    assert job["needs"] == "number" or job["needs"] == ["number"]
    cond = str(job["if"])
    assert "!cancelled()" in cond and "github.event_name == 'workflow_dispatch'" in cond
    assert "vars.JEV_RATIFY_ENABLED != 'false'" in cond, "the kill switch defaults on and dispatch bypasses it"
    assert int(job["timeout-minutes"]) <= 60
    runs = "\n".join(str(s.get("run") or "") for s in job["steps"])
    merges = [ln for ln in runs.splitlines() if "gh pr merge" in ln and not ln.strip().startswith("#")]
    assert merges, "the job merges the record PR itself"
    for ln in merges:
        assert "--merge" in ln and "--match-head-commit" in ln, ln
    for forbidden in ("--squash", "--rebase", "--admin", "--auto"):
        assert forbidden not in runs, f"{forbidden} in the ratify job"
    assert "ratify check-diff --base origin/main" in runs, "the merge guard re-proves the diff"
    assert "resolve-fleet-token" in json.dumps(job["steps"]), "the token is probed, never presence-checked"
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "main" and int(checkout["with"]["fetch-depth"]) == 0


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

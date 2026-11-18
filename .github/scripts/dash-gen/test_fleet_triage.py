#!/usr/bin/env python3
"""
Fixture tests for fleet_triage.py — the fleet's open-state snapshot.

Guards the one invariant that decides whether the `failing` signal means
anything, because it is consumed at remediation.py's top severity weight (100)
and a wrong verdict there spends a capped Opus doctor slot:

  * a workflow that is RED on an unmerged pull-request branch and GREEN on the
    tracked branch is NOT failing — the gate did its job, and telling an agent
    to "fix the root cause" of it is an invitation to weaken a working gate
    (bamr87/bamr87#205);
  * a workflow that is RED on the tracked branch IS still failing — the failure
    mode of the fix above is filtering everything out and reporting the fleet
    permanently green, which would be strictly worse than the bug;
  * a pull-request run whose head branch happens to MATCH the tracked branch (a
    PR opened from a fork's `main`) is still a pull-request run — the
    server-side `branch=` filter matches head_branch, so events must be checked
    too;
  * the registry's declared branch beats GitHub's `default_branch`, because
    this fleet deliberately tracks non-default branches;
  * the scan cap still holds, and the branch filter is applied SERVER-side as
    well, or a busy repo's PR runs eat the budget before main's runs are seen.

Every branch-filter check is paired with `unfiltered_latest()` below — a
faithful reproduction of the pre-fix selection — so each fixture proves it is
one the old code actually got wrong, rather than one that happens to pass.

The fix-PR link (FF-0036, bamr87/bamr87#609) is driven end to end through
build_report() against a fake GitHub that holds bashcrawl as it stood on
2026-11-02: CI red on main (markdownlint on release-please's CHANGELOG.md),
#133 the green, clean fix, and #127, #134, #137 red on the same Lint job.
It must yield exactly one `merge` item for #133 at 95 — and none when the
evidence is weaker than it looks: a run that skipped the failed job, a run
older than the failure, a mergeable_state that is not clean, a title alone.

Deliberately dependency-light — no network, no gh, no PyGithub (a stand-in
for its exception class is installed when it is missing). Runs either way:

    python3 .github/scripts/dash-gen/test_fleet_triage.py
    python3 -m pytest .github/scripts/dash-gen/test_fleet_triage.py -q
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import sys
import types
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # the code under test imports PyGithub's exception class lazily
    import github.GithubException  # noqa: F401
except ImportError:  # a bare interpreter: stand one in, so the suite still runs
    class _GithubException(Exception):
        def __init__(self, status=0, data=None, headers=None):
            super().__init__(status)
            self.status, self.data, self.headers = status, data or {}, headers

    _pkg, _mod = types.ModuleType("github"), types.ModuleType("github.GithubException")
    _mod.GithubException = _GithubException
    _pkg.GithubException = _mod
    sys.modules["github"], sys.modules["github.GithubException"] = _pkg, _mod

import fleet_triage  # noqa: E402

CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
BASE = dt.datetime(2026, 9, 6, 12, 0, tzinfo=dt.timezone.utc)

DRIFT = ".github/workflows/drift-check.yml"


class FakeRun:
    """The attributes fleet_triage reads off a PyGithub WorkflowRun."""

    def __init__(self, path, conclusion, event, head_branch, minutes_ago,
                 status="completed", name=None):
        self.path = path
        self.name = name or Path(path).stem
        self.conclusion = conclusion
        self.event = event
        self.head_branch = head_branch
        self.status = status
        self.created_at = BASE - dt.timedelta(minutes=minutes_ago)
        self.html_url = f"https://github.com/bamr87/bamr87/actions/runs/{minutes_ago}"


class FakeRepo:
    """Records the kwargs it was called with, so the server-side filter is
    observable — the client-side guard alone would hide its absence."""

    def __init__(self, runs, default_branch="main"):
        self._runs = runs
        self.default_branch = default_branch
        self.calls: list[dict] = []

    def get_workflow_runs(self, **kwargs):
        self.calls.append(kwargs)
        branch = kwargs.get("branch")
        if branch is None:
            return list(self._runs)
        # GitHub filters on head_branch — including a fork PR's head branch.
        return [r for r in self._runs if r.head_branch == branch]


def unfiltered_latest(runs, scan_cap=fleet_triage.FAILING_RUNS_SCAN) -> dict[str, dict]:
    """The pre-fix selection (main @ e6f39af), reproduced verbatim in shape.

    Present so every fixture below can assert it is a REGRESSION fixture: one
    the old algorithm gets wrong. Without this, a test that merely passes after
    the change proves nothing about the change.
    """
    latest: dict[str, dict] = {}
    seen = 0
    for run in runs:
        seen += 1
        if seen > scan_cap:
            break
        if run.status != "completed":
            continue
        key = getattr(run, "path", "") or run.name or "?"
        if key in latest:
            continue
        latest[key] = {"conclusion": run.conclusion or "?"}
    return latest


def failing_paths(latest: dict[str, dict]) -> set[str]:
    return {k for k, v in latest.items()
            if v["conclusion"] in fleet_triage.FAILING_CONCLUSIONS}


# --------------------------------------------------------------------------- #
# fix-PR link fixtures (FF-0036): a fake GitHub that counts every read
# --------------------------------------------------------------------------- #
NWO = "bamr87/bashcrawl"
CI = ".github/workflows/ci.yml"
NOV2 = dt.datetime(2026, 11, 2, 18, 0, tzinfo=dt.timezone.utc)   # the fixture's "now"
MARKER = f'<!-- fleet-doctor key="{NWO}:{CI}" -->'
# Everything the link may call. A write (merge, comment, edit, label) is not on
# the fake at all, so one would raise — and the summary check below would see it.
READS = {"get_issues", "get_pulls", "get_workflows", "runs_by_branch", "runs_by_sha", "jobs",
         "check_runs", "get_pull", "get_files"}


def at(day: int, hour: int, minute: int = 0, month: int = 11) -> dt.datetime:
    return dt.datetime(2026, month, day, hour, minute, tzinfo=dt.timezone.utc)


class GhRun:
    """A WorkflowRun with its jobs: what the link reads off the branch failure
    and off a PR head's own run."""

    def __init__(self, gh, run_id, conclusion, *, created, jobs, event="push", head_branch="main",
                 path=CI, name="CI", status="completed"):
        self._gh, self.id, self.conclusion, self.created_at = gh, run_id, conclusion, created
        self._jobs = [types.SimpleNamespace(name=n, conclusion=c) for n, c in jobs]
        self.event, self.head_branch, self.path, self.name, self.status = event, head_branch, path, name, status
        self.html_url = f"https://github.com/{NWO}/actions/runs/{run_id}"

    def jobs(self):
        self._gh.hit("jobs")
        return list(self._jobs)


class GhPR:
    def __init__(self, gh, number, title, *, created, updated=None, branch=None, draft=False, body="",
                 files=(), author="bamr87"):
        self._gh, self.number, self.title, self.draft, self.body = gh, number, title, draft, body
        self.head = types.SimpleNamespace(sha=f"sha{number}", ref=branch or f"topic/{number}")
        self.user = types.SimpleNamespace(login=author)
        self.created_at, self.updated_at = created, updated or created
        self.html_url = f"https://github.com/{NWO}/pull/{number}"
        self._files = list(files)

    def get_files(self):
        self._gh.hit("get_files")
        return [types.SimpleNamespace(filename=f) for f in self._files]


class GhRepo:
    """A read-only PyGithub Repository: open PRs, runs by branch and by head SHA,
    check runs per head, and mergeable_state as successive single-PR GETs see it."""

    def __init__(self, *, archived=False):
        self.archived, self.private, self.default_branch = archived, False, "main"
        self.calls: dict[str, int] = {}
        self.prs: list[GhPR] = []
        self.branch_runs: list[GhRun] = []
        self.sha_runs: dict[str, list[GhRun]] = {}
        self.checks: dict[str, dict[str, str]] = {}
        self.mergeable: dict[int, list] = {}

    def hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def get_issues(self, state):
        self.hit("get_issues")
        return []

    def get_pulls(self, state, sort, direction):
        self.hit("get_pulls")
        return list(self.prs)

    def get_workflows(self):
        self.hit("get_workflows")
        return []

    def get_workflow_runs(self, branch=None, head_sha=None):
        if head_sha is not None:
            self.hit("runs_by_sha")
            return list(self.sha_runs.get(head_sha, []))
        self.hit("runs_by_branch")
        return [r for r in self.branch_runs if r.head_branch == branch]

    def get_commit(self, sha):
        repo = self

        class Commit:
            def get_check_runs(self):
                repo.hit("check_runs")
                return [types.SimpleNamespace(name=n, conclusion=c, status="completed")
                        for n, c in repo.checks.get(sha, {}).items()]
        return Commit()

    def get_pull(self, number):
        self.hit("get_pull")
        seq = self.mergeable.setdefault(number, ["clean"])
        return types.SimpleNamespace(mergeable_state=seq.pop(0) if len(seq) > 1 else seq[0])

    def pr(self, number, title, *, checks=None, run=None, **kw) -> GhPR:
        """Add an open PR: its head's check runs and its own CI run (created, jobs)."""
        p = GhPR(self, number, title, **kw)
        self.prs.append(p)
        self.checks[p.head.sha] = dict(checks or {})
        if run is not None:
            created, jobs = run
            self.sha_runs[p.head.sha] = [GhRun(self, 900 + number, "success", created=created, jobs=jobs,
                                               event="pull_request", head_branch=p.head.ref)]
        return p


def bashcrawl(*, lint=("Lint", "success"), run_at=None, mergeable=None, title=None, branch=None,
              body="", files=(), draft=False, extra=None, archived=False, red=True) -> GhRepo:
    """bamr87/bashcrawl on 2026-11-02 (FF-0036): CI red on main since 10:00 —
    markdownlint MD004 on release-please's CHANGELOG.md — and #133, open three
    days, green and clean, whose own CI run at 12:00 passed Lint. #127, #134 and
    #137 fail that same Lint job and nothing else; #136 fails Lint AND a test of
    its own, so merging #133 would not turn it green. #135 is green too, but its
    only CI run is from the day before the failure, and it touches no workflow.
    Each keyword turns one of #133's facts into the counter-case."""
    repo = GhRepo(archived=archived)
    repo.branch_runs = [
        GhRun(repo, 800, "failure" if red else "success", created=at(2, 10),
              jobs=[("Lint", "failure" if red else "success"), ("Test", "success")]),
        GhRun(repo, 700, "success", created=at(1, 9), jobs=[("Lint", "success"), ("Test", "success")]),
    ]
    green = {"Lint": "success", "Test": "success"}
    red_lint = {"Lint": "failure", "Test": "success"}
    # newest-updated first, as get_pulls(sort="updated", direction="desc") returns them
    repo.pr(137, "chore(main): release 1.4.0", checks=red_lint, created=at(2, 11),
            branch="release-please--branches--main", author="github-actions[bot]")
    repo.pr(134, "feat: add level 7", checks=red_lint, created=at(1, 8), updated=at(2, 11))
    repo.pr(133, title or "fix(ci): exclude release-please CHANGELOG.md from markdownlint",
            checks=green, created=at(30, 9, month=10), updated=at(2, 12), body=body, files=files,
            branch=branch or "fix/ci-markdownlint-changelog", draft=draft,
            run=(run_at or at(2, 12), [lint, ("Test", "success")]))
    repo.pr(135, "docs: README badges", checks=green, created=at(1, 9), updated=at(1, 9),
            files=["README.md"], run=(at(1, 9, 30), [("Lint", "success"), ("Test", "success")]))
    repo.pr(127, "docs: fix a typo in level 3", checks=red_lint, created=at(20, 9, month=10),
            updated=at(1, 7))
    repo.pr(136, "feat: level 8 (WIP)", checks={"Lint": "failure", "Test": "failure"},
            created=at(1, 6), updated=at(1, 6))
    for spec in extra or []:
        repo.pr(**spec)
    if mergeable is not None:
        repo.mergeable[133] = list(mergeable)
    return repo


STDERR: list[str] = []  # what build_report() said, every call: a skipped link must never pass quietly


def triage(repo: GhRepo, *, pr_ci_cap: int = 8, fix_pr_cap: int = fleet_triage.FIX_PR_CAP) -> dict:
    """build_report() over the one fake repo, at the fixture's clock."""
    real_now = fleet_triage.now_utc
    fleet_triage.now_utc = lambda: NOV2
    err = io.StringIO()
    try:
        gh = types.SimpleNamespace(get_repo=lambda nwo: repo)
        project = {"name": "bashcrawl", "repo_url": f"https://github.com/{NWO}", "branch": "main"}
        with contextlib.redirect_stderr(err):
            return fleet_triage.build_report([project], gh, dict(fleet_triage.DEFAULT_THRESHOLDS),
                                             pr_ci_cap, fix_pr_cap)
    finally:
        fleet_triage.now_utc = real_now
        STDERR.extend(err.getvalue().splitlines())


def kind(rep: dict, k: str) -> list[dict]:
    return [i for i in rep["inbox"] if i["kind"] == k]


def row(rep: dict, ref: str) -> dict:
    return next((i for i in rep["inbox"] if i["ref"] == ref and i["kind"] != "merge"), {})


def link_calls(repo: GhRepo, pr_ci_cap_reads: int) -> int:
    """The reads only the link makes: every jobs/runs-by-SHA/single-PR/files read,
    plus the check-run reads beyond the normal --pr-ci-cap pass."""
    c = repo.calls
    return (c.get("jobs", 0) + c.get("runs_by_sha", 0) + c.get("get_pull", 0) + c.get("get_files", 0)
            + c.get("check_runs", 0) - pr_ci_cap_reads)


def check_fix_links() -> None:
    print("fix-PR link — bashcrawl, 2026-11-02 (FF-0036):")
    STDERR.clear()
    repo = bashcrawl()
    rep = triage(repo)
    merges = kind(rep, "merge")
    m = merges[0] if merges else {}
    check("exactly ONE merge item, and it is #133", [i["ref"] for i in merges] == ["#133"])
    check("…at priority 95, first in the inbox", m.get("priority") == 95 and rep["inbox"][0] is m)
    check("…whose clears lists the workflow and the three PRs failing the same Lint job",
          m.get("clears") == [CI, "#127", "#134", "#137"])
    check("…in words that say how the PRs clear",
          m.get("why") == "Merge #133: clears CI on main and #127, #134, #137 once their branches are updated")
    check("…on verified evidence, linking the PR itself",
          m.get("evidence") == "verified" and m.get("url", "").endswith("/pull/133")
          and m.get("title", "").startswith("fix(ci): exclude"))
    check("the red workflow keeps priority 90 and gains 'fix: #133'",
          row(rep, CI).get("priority") == 90 and row(rep, CI).get("why") == "latest run failure · fix: #133")
    check("each PR it clears keeps 70 and gains 'fix: #133'",
          all(row(rep, r).get("priority") == 70 and row(rep, r).get("why") == "PR checks failing · fix: #133"
              for r in ("#127", "#134", "#137")))
    check("#136 fails a test of its own as well: not cleared, not annotated",
          "#136" not in m.get("clears", []) and row(rep, "#136").get("why") == "PR checks failing")
    wf = rep["by_repo"][0]["workflows"]["failing"][0]
    check("fix_prs is recorded on the failing workflow, with the job that failed and the branch",
          wf.get("failed_jobs") == ["Lint"] and wf.get("branch") == "main"
          and [(f["number"], f["evidence"], f["mergeable_state"], f["ready"]) for f in wf.get("fix_prs", [])]
          == [(133, "verified", "clean", True)]
          and wf["fix_prs"][0]["clears"] == ["#127", "#134", "#137"])
    pr133 = next(p for p in rep["by_repo"][0]["prs"]["items"] if p["number"] == 133)
    check("clears is recorded on the PR",
          pr133.get("clears") == [CI, "#127", "#134", "#137"] and pr133.get("merge_ready") is True
          and pr133.get("fix_evidence") == "verified" and pr133.get("mergeable_state") == "clean")
    check("#135 is green but its run predates the failure and it touches no workflow: no link",
          135 not in [f["number"] for f in wf["fix_prs"]])
    fl = rep["fix_links"]
    check("the run summary counts the link's own GET requests",
          fl["requests"] == link_calls(repo, 6) == 6 and fl["repos"] == 1 and fl["prs_graded"] == 2
          and fl["merge_items"] == 1 and fl["fix_prs"] == 1)
    check("every call was a read", set(repo.calls) <= READS)
    check("the snapshot still dumps as plain YAML", "fix_prs:" in yaml.safe_dump(rep, sort_keys=False))
    check("scratch counters never reach the YAML", "_fix_stats" not in rep["by_repo"][0])

    off = triage(bashcrawl(), fix_pr_cap=0)
    check("regression: without the link the green fix is nowhere in the inbox (2026-11-02)",
          not kind(off, "merge") and not any(i["ref"] == "#133" for i in off["inbox"])
          and row(off, CI).get("why") == "latest run failure")

    print("fix-PR link — evidence that is weaker than it looks:")
    skipped = triage(bashcrawl(lint=("Lint", "skipped")))
    check("a run that SKIPPED the job that failed on the branch is not verified: no merge item",
          not kind(skipped, "merge"))
    check("…its fix(ci) title is only weak evidence: 'possible fix', no re-rank",
          row(skipped, CI).get("why") == "latest run failure · possible fix: #133"
          and row(skipped, CI).get("priority") == 90
          and row(skipped, "#127").get("why") == "PR checks failing" and row(skipped, "#127").get("priority") == 70)
    early = triage(bashcrawl(run_at=at(2, 9, 30)))
    check("a run older than the branch's latest failure is not verified: no merge item",
          not kind(early, "merge") and row(early, CI).get("why") == "latest run failure · possible fix: #133")
    missing = triage(bashcrawl(lint=("Format", "success")))
    check("a run without the failed job at all is not verified", not kind(missing, "merge"))
    for state in ("dirty", "blocked", "behind", "unstable"):
        rep_s = triage(bashcrawl(mergeable=[state]))
        check(f"mergeable_state `{state}`: no merge item, and the state shows on the annotation",
              not kind(rep_s, "merge") and row(rep_s, CI).get("why") == f"latest run failure · fix: #133 ({state})"
              and row(rep_s, "#134").get("why") == f"PR checks failing · fix: #133 ({state})")
    lazy = bashcrawl(mergeable=[None, "unknown", "clean"])
    rep_u = triage(lazy)
    check("still unknown after ONE retry: two reads, never a loop, no merge item",
          lazy.calls.get("get_pull") == 2 and not kind(rep_u, "merge")
          and row(rep_u, CI).get("why") == "latest run failure · fix: #133 (unknown)")
    late = bashcrawl(mergeable=["unknown", "clean"])
    check("a state GitHub computes on the retry counts", [i["ref"] for i in kind(triage(late), "merge")] == ["#133"]
          and late.calls.get("get_pull") == 2)

    weak_file = triage(bashcrawl(lint=("Lint", "skipped"), title="chore: tidy the lint config",
                                 branch="chore/lint", files=[CI]))
    check("touching the workflow file is weak evidence: 'possible fix', priorities unchanged",
          not kind(weak_file, "merge") and row(weak_file, CI).get("why") == "latest run failure · possible fix: #133"
          and [i["priority"] for i in weak_file["inbox"]] == sorted((i["priority"] for i in weak_file["inbox"]),
                                                                     reverse=True)
          and {i["priority"] for i in weak_file["inbox"]} == {90, 70})
    nothing = triage(bashcrawl(lint=("Lint", "skipped"), title="feat: new level", branch="feat/level"))
    check("no evidence at all: no link, no annotation",
          row(nothing, CI).get("why") == "latest run failure"
          and not nothing["by_repo"][0]["workflows"]["failing"][0]["fix_prs"])

    doctor = triage(bashcrawl(run_at=at(2, 9, 30), title="ci: markdownlint ignores CHANGELOG.md",
                              body=MARKER + "\n\nThe fleet doctor's fix."))
    dm = kind(doctor, "merge")
    check("a PR carrying the fleet doctor's marker for the workflow is `doctor` evidence: a merge item",
          [(i["ref"], i["evidence"], i["priority"]) for i in dm] == [("#133", "doctor", 95)])
    check("a draft is never a candidate", not kind(triage(bashcrawl(draft=True)), "merge"))

    print("fix-PR link — several fixes for one red:")
    newer = {"number": 140, "title": "fix(ci): ignore CHANGELOG.md in markdownlint", "checks":
             {"Lint": "success", "Test": "success"}, "created": at(2, 14), "run": (at(2, 14, 5),
             [("Lint", "success"), ("Test", "success")])}
    both = triage(bashcrawl(extra=[newer]))
    bm = kind(both, "merge")
    check("two verified, clean fixes: ONE merge item, the oldest, naming the other",
          [i["ref"] for i in bm] == ["#133"] and bm[0]["why"].endswith(" · also ready: #140"))
    strongest = triage(bashcrawl(run_at=at(2, 9, 30), body=MARKER, extra=[newer]))
    sm = kind(strongest, "merge")
    check("strongest evidence first: a verified fix outranks an older doctor one",
          [(i["ref"], i["evidence"]) for i in sm] == [("#140", "verified")] and sm[0]["why"].endswith("#133"))

    print("fix-PR link — cost:")
    quiet = bashcrawl(red=False)
    rep_q = triage(quiet)
    check("a repo with no failing workflow makes no extra call at all",
          link_calls(quiet, 6) == 0 and rep_q["fix_links"]["requests"] == 0 and rep_q["fix_links"]["repos"] == 0
          and not kind(rep_q, "merge"))
    capped = bashcrawl()
    rep_c = triage(capped, fix_pr_cap=1)
    check("the per-repo cap bounds the PRs graded (the first green one only)",
          rep_c["fix_links"]["prs_graded"] == 1 and capped.calls.get("runs_by_sha") == 1)
    past = bashcrawl()
    rep_p = triage(past, pr_ci_cap=0)
    check("past --pr-ci-cap the link still finds the fix, under its own cap of extra reads",
          [i["ref"] for i in kind(rep_p, "merge")] == ["#133"]
          and past.calls.get("check_runs") == fleet_triage.FIX_PR_CAP
          and rep_p["fix_links"]["requests"] == link_calls(past, 0))
    archived = bashcrawl(archived=True)
    triage(archived)
    check("an archived repo has no merge to make: no link calls", link_calls(archived, 6) == 0)
    check("no run skipped a repo or a link (stderr says nothing but the repo it read)",
          STDERR and all(line == f"  · {NWO}" for line in STDERR))

    print("fix-PR link — pieces:")
    run = types.SimpleNamespace(path=CI + "@refs/pull/9/merge", status="completed", created_at=at(2, 12))
    check("a run path with an @ref suffix still matches its workflow",
          fleet_triage.newest_run_after([run], CI, at(2, 10)) is run)
    check("an unknown failure time verifies nothing", fleet_triage.newest_run_after([run], CI, None) is None)
    job = types.SimpleNamespace
    check("jobs_passed: every failed job ran and passed",
          fleet_triage.jobs_passed([job(name="Lint", conclusion="success")], {"Lint"})
          and not fleet_triage.jobs_passed([job(name="Lint", conclusion="skipped")], {"Lint"})
          and not fleet_triage.jobs_passed([], {"Lint"}) and not fleet_triage.jobs_passed([], set()))
    check("a PR failing a job of its own besides the inherited one is not cleared",
          fleet_triage.symptom_prs({"Lint"}, {1: ("fail", ["Lint"]), 2: ("fail", ["Lint", "Test"]),
                                              3: ("pass", [])}) == ["#1"])
    # The last two are the fleet-wide harness PRs the first live run (2026-11-15) met
    # in every red repo: a scoped `ci(…)` change on a `ci/…` branch claims no fix.
    for t, b, want in (("fix(ci): x", "x", True), ("ci: bump", "x", True), ("CI!: y", "x", True),
                       ("docs: ci notes", "fix/ci-lint", True), ("feat: x", "fix-ci", True),
                       ("feat: circle", "fix/circleci", False), ("fix: ci", "feature/x", False),
                       ("ci(claude): use OAuth only, disable API key for now", "ci/claude-oauth-only", False),
                       ("ci(harness): bring the AI workflows onto the fleet harness standard",
                        "ci/harness-standard", False)):
        check(f"weak signal: title {t!r}, branch {b!r} → {want}",
              fleet_triage.weak_signal(types.SimpleNamespace(title=t, head=types.SimpleNamespace(ref=b))) is want)
    two = {"name": "bashcrawl", "nwo": NWO, "workflows": {"failing": [
        {"workflow": "CI", "path": CI, "branch": "main", "fix_prs": [
            {"number": 133, "evidence": "verified", "ready": True, "clears": ["#127"], "title": "t", "url": "u",
             "age_days": 3}]},
        {"workflow": "Lint", "path": ".github/workflows/lint.yml", "branch": "main", "fix_prs": [
            {"number": 133, "evidence": "doctor", "ready": True, "clears": ["#128"], "title": "t", "url": "u",
             "age_days": 3}]}]}}
    merges2, notes2 = fleet_triage.merge_plan(two)
    check("one PR that fixes two reds is ONE merge item clearing both",
          [(i["ref"], i["clears"], i["evidence"]) for i in merges2]
          == [("#133", [CI, ".github/workflows/lint.yml", "#127", "#128"], "verified")]
          and merges2[0]["why"].startswith("Merge #133: clears CI + Lint on main and #127, #128")
          and notes2["#128"] == "fix: #133")


# --------------------------------------------------------------------------- #
def main() -> int:
    # --- the reported defect: red on a PR branch, green on main ------------- #
    # Modelled on the live API output in bamr87/bamr87#205: newest first, a
    # passing PR run, then main, then the two wtd/* failures.
    reported = [
        FakeRun(DRIFT, "success", "pull_request", "claude/ci-visual-evidence", 10),
        FakeRun(DRIFT, "success", "push", "main", 40),
        FakeRun(DRIFT, "failure", "pull_request", "wtd/repo-map-docs", 80),
        FakeRun(DRIFT, "failure", "pull_request", "wtd/repo-map-docs", 90),
    ]
    # Order the API returns when the newest run is the FAILING PR one — the
    # ordering luck the issue calls out. Same repo state, different instant.
    unlucky = [
        FakeRun(DRIFT, "failure", "pull_request", "wtd/repo-map-docs", 5),
        FakeRun(DRIFT, "success", "push", "main", 40),
    ]

    print("PR-branch failures are not fleet breakage:")
    check("fixture is a genuine regression: the pre-fix selection reports drift-check failing",
          DRIFT in failing_paths(unfiltered_latest(unlucky)))
    got = fleet_triage.latest_runs_on_branch(unlucky, "main")
    check("a PR-branch failure with a green main is NOT failing",
          failing_paths(got) == set())
    check("...and main's own green conclusion is what gets recorded",
          got[DRIFT]["conclusion"] == "success")
    check("the same holds when the newest run is a passing PR run (ordering luck)",
          failing_paths(fleet_triage.latest_runs_on_branch(reported, "main")) == set())

    # --- the converse: the fix must not filter everything out --------------- #
    broken = [
        FakeRun(DRIFT, "success", "pull_request", "fix/some-branch", 5),
        FakeRun(DRIFT, "failure", "push", "main", 30),
    ]
    print("tracked-branch failures are still reported:")
    got = fleet_triage.latest_runs_on_branch(broken, "main")
    check("a failure on the tracked branch IS still failing",
          failing_paths(got) == {DRIFT})
    check("...and it carries the run's own url and timestamp",
          got[DRIFT]["run_url"].endswith("/30") and got[DRIFT]["run_at"].startswith("2026-09-06"))
    check("a green PR run does not mask a red main (the pre-fix code got this wrong too)",
          DRIFT not in failing_paths(unfiltered_latest(broken)))
    for event in ("schedule", "workflow_dispatch", "release", "workflow_run"):
        check(f"a `{event}` failure on the tracked branch is still reported",
              failing_paths(fleet_triage.latest_runs_on_branch(
                  [FakeRun(DRIFT, "failure", event, "main", 5)], "main")) == {DRIFT})

    # --- fork PRs: head_branch can equal the tracked branch ----------------- #
    fork = [
        FakeRun(DRIFT, "failure", "pull_request", "main", 5),   # PR from a fork's main
        FakeRun(DRIFT, "success", "push", "main", 60),
    ]
    print("fork pull-request runs:")
    check("a PR run whose head branch IS `main` is still excluded",
          failing_paths(fleet_triage.latest_runs_on_branch(fork, "main")) == set())
    check("...which the server-side branch filter alone would NOT have caught",
          FakeRepo(fork).get_workflow_runs(branch="main")[0].conclusion == "failure")
    check("pull_request_target is excluded on the same grounds",
          failing_paths(fleet_triage.latest_runs_on_branch(
              [FakeRun(DRIFT, "failure", "pull_request_target", "main", 5)], "main")) == set())

    # --- fail open, never closed ------------------------------------------- #
    print("missing metadata fails open:")
    check("a run with no head_branch is kept, not silently dropped",
          failing_paths(fleet_triage.latest_runs_on_branch(
              [FakeRun(DRIFT, "failure", "push", "", 5)], "main")) == {DRIFT})
    check("in-progress runs are still skipped",
          fleet_triage.latest_runs_on_branch(
              [FakeRun(DRIFT, "failure", "push", "main", 5, status="in_progress")],
              "main") == {})

    # --- the scan cap ------------------------------------------------------- #
    print("scan cap:")
    flood = [FakeRun(f".github/workflows/w{i}.yml", "failure", "push", "main", i)
             for i in range(1, 12)]
    check("the cap bounds how many runs are scanned",
          len(fleet_triage.latest_runs_on_branch(flood, "main", scan_cap=5)) == 5)

    # --- branch resolution --------------------------------------------------- #
    print("branch resolution:")
    repo = FakeRepo([], default_branch="master")
    check("the registry's declared branch wins over GitHub's default",
          fleet_triage.tracked_branch({"branch": "dev"}, repo) == "dev")
    check("GitHub's default_branch is the fallback",
          fleet_triage.tracked_branch({}, repo) == "master")
    check("a blank registry branch falls back rather than filtering on ''",
          fleet_triage.tracked_branch({"branch": "  "}, repo) == "master")
    check("`main` is the last resort when neither is known",
          fleet_triage.tracked_branch({}, FakeRepo([], default_branch="")) == "main")

    # --- the filter is applied server-side too ------------------------------- #
    print("server-side filtering:")
    repo = FakeRepo(reported)
    latest = fleet_triage.latest_runs_on_branch(
        repo.get_workflow_runs(branch=fleet_triage.tracked_branch({"branch": "main"}, repo)),
        "main")
    check("get_workflow_runs is called WITH a branch, so PR runs never eat the scan budget",
          repo.calls == [{"branch": "main"}])
    check("the server-filtered stream yields the same verdict as the client filter",
          failing_paths(latest) == set())

    # --- report -------------------------------------------------------------- #
    # --- a snapshot that read nothing is a dead token, not a quiet fleet ----- #
    # 2026-09-27: an expired FLEET_TOKEN made all 43 repos 401, the snapshot
    # was written with zeros, and the doctor concluded "nothing to do".
    print("Blind snapshots are refused:")
    check("0 scanned with unreachable repos is blind",
          fleet_triage.blind_snapshot({"repos_scanned": 0, "repos_unreachable": ["bamr87/bamr87"]}))
    check("a partial read is not blind",
          not fleet_triage.blind_snapshot({"repos_scanned": 1, "repos_unreachable": ["bamr87/cv"]}))
    check("an empty registry is not blind",
          not fleet_triage.blind_snapshot({"repos_scanned": 0, "repos_unreachable": []}))

    check_fix_links()

    failed = [label for label, ok in CHECKS if not ok]
    print()
    for label, ok in CHECKS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print()
    if failed:
        print(f"FAILED ({len(failed)}/{len(CHECKS)})")
        return 1
    print(f"OK ({len(CHECKS)} checks)")
    return 0


def test_fleet_triage() -> None:
    """pytest entry point — the same checks `main()` runs as a script.

    The suite is a script first (it must run with nothing but the stdlib), but
    `pytest .github/scripts/dash-gen/test_fleet_triage.py` otherwise collects
    zero tests and exits 5, which reads as a pass to anyone checking `$?`.
    """
    CHECKS.clear()
    assert main() == 0, [label for label, ok in CHECKS if not ok]


if __name__ == "__main__":
    raise SystemExit(main())

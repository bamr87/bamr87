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

Deliberately dependency-light — no network, no gh, no PyGithub. Runs either way:

    python3 .github/scripts/dash-gen/test_fleet_triage.py
    python3 -m pytest .github/scripts/dash-gen/test_fleet_triage.py -q
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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

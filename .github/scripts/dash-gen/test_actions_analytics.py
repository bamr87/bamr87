#!/usr/bin/env python3
"""
Fixture tests for actions_analytics.py — the fleet's Actions cost/effectiveness engine.

This module ranks the queue `remediate` sorts on, so an arithmetic error here does
not merely mis-render a page: it spends the fleet-doctor's daily cap on the wrong
workflows. It shipped with no tests, and two defects visible in the published data
(bamr87/bamr87#229) are what that bought. The invariants below are the ones that
were violated:

  * a run that never reached a runner bills NOTHING, so it must contribute zero
    minutes — one run parked non-terminal for 68h at `billable: {}` contributed
    4079.9 phantom minutes, 99.2% of its workflow's entire reported spend;
  * the API reports that failure as a plain `failure`, not `startup_failure`, so
    the conclusion alone cannot catch it and the job count must;
  * no single run may report more than a bounded maximum, so the NEXT stuck-run
    variant is a rounding error rather than an outage of the metric;
  * a run zeroed for cost is still RED — suppressing it from the success rate
    would trade a cost bug for a correctness bug;
  * every fleet total ranges over the same population. Summing waste over all
    workflows against a consumption denominator of owned-only ones published
    2091.6h wasted vs 1269.3h consumed and -64.8% effectiveness, an impossible
    figure when waste is a subset of consumption.

Deliberately dependency-light — no network, no gh, no PyGithub (the run objects
are stubs, and actions_analytics imports github lazily). Runs either way:

    python3 .github/scripts/dash-gen/test_actions_analytics.py
    python3 -m pytest .github/scripts/dash-gen/test_actions_analytics.py -q
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_analytics  # noqa: E402

CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
NOW = dt.datetime(2026, 9, 3, 1, 55, 20, tzinfo=dt.timezone.utc)

# The production run from #229: started 2026-08-31T05:55:25Z, updated 68h later.
PHANTOM_HOURS = 68.0


class FakeJobs:
    def __init__(self, count: int) -> None:
        self.totalCount = count


class FakeRun:
    """The slice of a PyGithub WorkflowRun that the cost path actually reads."""

    def __init__(self, *, conclusion: str, hours: float, jobs: int = 1,
                 raises: bool = False) -> None:
        self.conclusion = conclusion
        self.run_started_at = NOW - dt.timedelta(hours=hours)
        self.created_at = self.run_started_at
        self.updated_at = NOW
        self._jobs = jobs
        self._raises = raises

    def jobs(self):
        if self._raises:
            raise RuntimeError("simulated API failure")
        return FakeJobs(self._jobs)


def cost_of(run: FakeRun) -> float:
    """The full production path: wall clock, then the cost proxy over it."""
    dur = actions_analytics.duration_min(run)
    assert dur is not None
    return actions_analytics.cost_min(run, dur)


def rec(minutes: float, conclusion: str = "success", event: str = "push") -> dict:
    return {"workflow_id": 1, "name": "wf", "path": ".github/workflows/wf.yml",
            "event": event, "conclusion": conclusion, "minutes": minutes,
            "day": "2026-09-01", "created_at": "2026-09-01T00:00:00+00:00"}


def bucket_of(*records: dict) -> dict:
    b = actions_analytics.new_bucket()
    b["_name"] = "wf"
    b["_path"] = ".github/workflows/wf.yml"
    for r in records:
        actions_analytics.fold(b, r)
    return b


def workflow(repo: str, external: bool, *records: dict) -> dict:
    return actions_analytics.workflow_record(
        bucket_of(*records), repo=repo,
        repo_url=f"https://github.com/{repo}", external=external, weeks=2.0)


def totals_of(*workflows: dict) -> dict:
    report = actions_analytics.finalize(
        list(workflows), [], {}, {}, {}, days=14, scanned=1, now=NOW)
    return report["totals"]


# --------------------------------------------------------------------------- #
# defect 1 — the cost proxy
# --------------------------------------------------------------------------- #
def case_non_executing_runs_cost_nothing() -> None:
    """FAILS on the pre-fix code, which billed the full 4079.9 min wall clock."""
    run = FakeRun(conclusion="startup_failure", hours=PHANTOM_HOURS, jobs=0)

    check("a 68h startup_failure costs 0 minutes, not 4080",
          cost_of(run) == 0.0)

    # …and the zeroing must reach the aggregates the queue ranks on.
    b = bucket_of(rec(cost_of(run), conclusion="startup_failure"))
    check("a zeroed run contributes 0.0 to total_min", b["total_min"] == 0.0)
    check("a zeroed run contributes 0.0 to waste_min", b["waste_min"] == 0.0)

    # Cost zero, verdict unchanged: the run really did fail.
    check("a zeroed run still counts as a failure", b["failure"] == 1)
    check("a zeroed run still counts as a run", b["runs"] == 1)
    w = actions_analytics.workflow_record(b, repo="r", repo_url=None,
                                          external=False, weeks=2.0)
    check("a zeroed run still reports 0% success, not None",
          w["success_rate_pct"] == 0.0)


def case_zero_job_failure_is_caught_by_the_job_probe() -> None:
    """The PRODUCTION shape: the API reported run 33362222262 as a plain
    `failure`, so the conclusion filter alone would have missed it entirely."""
    run = FakeRun(conclusion="failure", hours=PHANTOM_HOURS, jobs=0)
    check("a 68h zero-job `failure` costs 0 minutes", cost_of(run) == 0.0)

    # The probe is only worth its request on outliers — a short run must never
    # trigger it, or the sweep pays one extra call per run across ~40 repos.
    # `raises=True` makes the probe observable: if it ran, the exception path
    # would be the only thing keeping this from blowing up, so the boundary has
    # to sit clear of SUSPECT_RUN_MIN for the check to mean anything.
    short = FakeRun(conclusion="failure", hours=0.1, jobs=0, raises=True)
    check("a short run is never probed for jobs", cost_of(short) == 6.0)


def case_sub_clamp_phantom_minutes_are_zeroed() -> None:
    """The zer0-mistakes shape: jobless `failure` runs BELOW the 6h clamp.

    Six of them contributed 328.8 of markdown-oneline's 337.4 reported minutes
    (97.5%) against a real p95 of 0.28 min, which flagged a workflow costing
    ~9 minutes as the fleet's most expensive `high-cost-low-value` candidate.
    FAILS on the pre-fix code, which billed every one of those minutes.
    """
    for minutes in (297.35, 99.05, 24.93, 17.78):
        run = FakeRun(conclusion="failure", hours=minutes / 60, jobs=0)
        check(f"a jobless {minutes:.0f}min `failure` under the clamp costs 0",
              cost_of(run) == 0.0)

    # The probe decides on the JOB COUNT, never on the duration alone: a long
    # failure that really did run must keep every minute it burned.
    real = FakeRun(conclusion="failure", hours=1.0, jobs=2)
    check("a long failure that DID execute keeps its 60 min", cost_of(real) == 60.0)

    # Success is out of scope by construction — a green build is the population,
    # not an outlier, and must never cost the sweep an extra request.
    green = FakeRun(conclusion="success", hours=1.0, jobs=0, raises=True)
    check("a long SUCCESS is never probed for jobs", cost_of(green) == 60.0)


def case_duration_is_capped() -> None:
    """FAILS on the pre-fix code, which had no ceiling at all."""
    billable = FakeRun(conclusion="success", hours=PHANTOM_HOURS, jobs=3)
    check("a 68h run that DID execute is clamped to 360 min",
          cost_of(billable) == actions_analytics.MAX_RUN_MIN == 360.0)

    # An unreadable job list is "cannot tell", not "cost nothing": keep the run
    # and let the clamp bound it, rather than erasing real consumption.
    unknown = FakeRun(conclusion="failure", hours=PHANTOM_HOURS, raises=True)
    check("an unreadable job list falls back to the cap, not to zero",
          cost_of(unknown) == 360.0)


def case_ordinary_runs_are_untouched() -> None:
    """The regression guard: the fix must be invisible to every normal run."""
    for hours, concl in ((0.25, "success"), (2.0, "failure"), (0.1, "cancelled")):
        run = FakeRun(conclusion=concl, hours=hours)
        check(f"a {hours}h {concl} run keeps its exact wall clock",
              cost_of(run) == hours * 60)


# --------------------------------------------------------------------------- #
# defect 2 — the fleet totals
# --------------------------------------------------------------------------- #
def case_totals_range_over_one_population() -> None:
    """FAILS on the pre-fix code: waste summed over ALL workflows while the
    consumption denominator counted only owned ones.

    Modelled on the real data — tt-a1i/archify, an upstream mirror the fleet
    merely watches, was the single largest contributor to the fleet's own
    reported waste while none of its consumption was counted.
    """
    ours = workflow("bamr87/it-journey", False,
                    rec(80.0, "success"), rec(20.0, "failure"))
    mirror = workflow("tt-a1i/archify", True,
                      rec(479.3, "success"), rec(50890.7, "failure"))

    t = totals_of(ours, mirror)

    check("waste never exceeds consumption",
          t["waste_min"] <= t["total_min"])
    check("effectiveness stays inside 0..100",
          0 <= t["effectiveness_pct"] <= 100)
    check("the external mirror's waste is excluded", t["waste_min"] == 20.0)
    check("the external mirror's consumption is excluded", t["total_min"] == 100.0)
    check("effectiveness is computed from the owned figures",
          t["effectiveness_pct"] == 80.0)

    # The same mismatch sat on the run counters (L421-426), not just the minutes.
    check("run counts exclude the external mirror", t["runs"] == 2)
    check("success counts exclude the external mirror", t["success_rate_pct"] == 50.0)


def case_owned_only_fleet_is_unchanged() -> None:
    """With no mirrors in the data, the totals must be exactly what they were."""
    t = totals_of(workflow("bamr87/bamr87", False,
                           rec(60.0, "success"), rec(40.0, "failure")))
    check("an all-owned fleet totals its consumption", t["total_min"] == 100.0)
    check("an all-owned fleet totals its waste", t["waste_min"] == 40.0)
    check("an all-owned fleet reports 60% effectiveness",
          t["effectiveness_pct"] == 60.0)


# --------------------------------------------------------------------------- #
# defect 3 — cancel-heavy fired on working concurrency guards
# --------------------------------------------------------------------------- #
def flags_of(*records: dict) -> list[str]:
    wf = workflow("bamr87/it-journey", False, *records)
    actions_analytics.finalize([wf], [], {}, {}, {}, days=14, scanned=1, now=NOW)
    return wf["flags"]


def case_supersession_is_not_cancel_heavy() -> None:
    """The three candidates the 2026-09-12 fleet-doctor queue was spent on.

    All three had a CORRECT concurrency guard and zero defects; the flag read
    their supersessions — runs cancelled 1-3s after creation, having never
    started a job — as churn. FAILS on the pre-fix code, which looked only at
    the cancelled share.
    """
    # bamr87/aieo CI: 13 success / 12 cancelled, 3.2 of 33.4 min cancelled.
    # `cancel-in-progress: true` collapsed a 12-push burst on main into one run.
    aieo = [rec(2.32, "success")] * 13 + [rec(0.27, "cancelled")] * 12
    check("a push burst collapsed by cancel-in-progress is not cancel-heavy",
          "cancel-heavy" not in flags_of(*aieo))

    # it-journey content-auto-merge: 27 cancelled for 2.5 min, on a workflow
    # that documents `cancel-in-progress: false` as the fix for issue #563.
    automerge = [rec(2.4, "success")] * 34 + [rec(0.09, "cancelled")] * 27
    check("pending-queue supersession is not cancel-heavy",
          "cancel-heavy" not in flags_of(*automerge))

    # it-journey issue-autopilot: 10 cancelled for 0.3 min — 18 seconds in 14d.
    autopilot = [rec(0.8, "success")] * 21 + [rec(0.03, "cancelled")] * 10
    check("a singleton loop's label-event supersessions are not cancel-heavy",
          "cancel-heavy" not in flags_of(*autopilot))


def case_real_cancellation_churn_still_flags() -> None:
    """The guard must not blind the flag: long builds killed half-done are
    exactly what `cancel-heavy` exists to catch, and still cost real minutes."""
    churn = [rec(20.0, "success")] * 6 + [rec(14.0, "cancelled")] * 6
    flags = flags_of(*churn)
    check("builds cancelled mid-flight are still cancel-heavy",
          "cancel-heavy" in flags)

    # Same share, same per-run cost, but only seconds of it: below the absolute
    # floor there is nothing to recover and nothing to fix.
    trivial = [rec(0.02, "success")] * 6 + [rec(0.014, "cancelled")] * 6
    check("a cheap workflow never trips the flag on ratio alone",
          "cancel-heavy" not in flags_of(*trivial))


def case_cancelled_minutes_are_published() -> None:
    """`cancel_min` is what makes the flag auditable from the data file alone."""
    wf = workflow("bamr87/aieo", False,
                  rec(10.0, "success"), rec(3.0, "cancelled"), rec(2.0, "failure"))
    check("cancelled minutes are published", wf["cancel_min"] == 3.0)
    check("cancelled minutes stay a subset of waste",
          wf["cancel_min"] <= wf["waste_min"] == 5.0)


# --------------------------------------------------------------------------- #
# published contract
# --------------------------------------------------------------------------- #
def case_note_documents_the_bounds() -> None:
    """The `note:` is the only place a reader of the data file learns the cost
    model. It advertised an uncapped proxy long after the proxy was capped."""
    report = actions_analytics.finalize(
        [workflow("bamr87/bamr87", False, rec(1.0))], [], {}, {}, {},
        days=14, scanned=1, now=NOW)
    text = report["note"]
    check("the note states the zero-cost exclusion", "never executed" in text)
    check("the note states the cap", "360" in text)
    check("the note states the owned-only totals", "owned" in text)


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def main() -> int:
    for fn in (case_non_executing_runs_cost_nothing,
               case_zero_job_failure_is_caught_by_the_job_probe,
               case_sub_clamp_phantom_minutes_are_zeroed,
               case_duration_is_capped,
               case_ordinary_runs_are_untouched,
               case_totals_range_over_one_population,
               case_owned_only_fleet_is_unchanged,
               case_supersession_is_not_cancel_heavy,
               case_real_cancellation_churn_still_flags,
               case_cancelled_minutes_are_published,
               case_note_documents_the_bounds):
        fn()

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


def test_actions_analytics() -> None:
    """pytest entry point — the same checks `main()` runs as a script.

    The suite is a script first (it must run with nothing but PyYAML installed),
    but `pytest .github/scripts/dash-gen/test_actions_analytics.py` would
    otherwise collect the fixtures above and report the aggregate as a pass even
    when a `check()` failed, since they assert nothing themselves.
    """
    CHECKS.clear()
    assert main() == 0, [label for label, ok in CHECKS if not ok]


if __name__ == "__main__":
    raise SystemExit(main())

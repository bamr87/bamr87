#!/usr/bin/env python3
"""
Fixture tests for actions_analytics.py — the Actions cost/effectiveness metric.

Guards the two invariants that decide whether the fleet's headline cost figure
means anything, both of which failed in production (bamr87/bamr87#204):

  * a CANCELLED run's wall clock is not consumption. GitHub stamps
    `run_started_at` at creation and `updated_at` at cancellation, so a run that
    merely waited — queued, or parked in `action_required` — reports days of
    "duration" while `/actions/runs/{id}/timing` reports `billable: {}`. One such
    run booked 4,513.9 phantom minutes, 99.5% of its workflow's reported cost,
    and evicted a real candidate from a capped remediation queue. Cancelled runs
    must still count as RUNS, or the `cancel-heavy` signal disappears with them;
  * every fleet TOTAL must be summed over one population. Summing waste over all
    workflows against a denominator that excluded external mirrors published a
    share larger than its whole — `waste_min` 45,211.1 vs `total_min` 37,119.3,
    rendering as -21.8% effective.

Deliberately dependency-light — no network, no gh, no PyGithub. Runs either way:

    python3 .github/scripts/dash-gen/test_actions_analytics.py
    python3 -m pytest .github/scripts/dash-gen/test_actions_analytics.py -q
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_analytics as aa  # noqa: E402

CHECKS: list[tuple[str, bool]] = []


def check(label: str, cond: bool) -> None:
    CHECKS.append((label, bool(cond)))


def close(a, b, tol=0.05) -> bool:
    return a is not None and abs(a - b) <= tol


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def rec(conclusion: str, minutes: float, *, event="pull_request",
        name="Evidence gate", path=".github/workflows/evidence-gate.yml",
        day="2026-08-26", created="2026-08-26T15:43:28+00:00") -> dict:
    return {"workflow_id": 1, "name": name, "path": path, "event": event,
            "conclusion": conclusion, "minutes": minutes, "day": day,
            "created_at": created}


def bucket_of(*records) -> dict:
    b = aa.new_bucket()
    for r in records:
        b["_name"] = r["name"]
        b["_path"] = r["path"]
        aa.fold(b, r)
    return b


def record_of(*records, repo="zer0-mistakes", external=False, weeks=2.0) -> dict:
    return aa.workflow_record(bucket_of(*records), repo=repo,
                              repo_url=f"https://github.com/bamr87/{repo}",
                              external=external, weeks=weeks)


def evidence_gate_records() -> list[dict]:
    """The real shape of the run that produced #204.

    51 runs in the window: 22 success + 7 failure + 8 non-verdict, each ~0.3m,
    plus 14 cancelled — 13 short ones and the pathological outlier that sat in
    `action_required` for three days and three hours before being cancelled.
    """
    runs = [rec("success", 0.3) for _ in range(22)]
    runs += [rec("failure", 0.3) for _ in range(7)]
    runs += [rec("action_required", 0.3) for _ in range(8)]
    runs += [rec("cancelled", 0.3) for _ in range(13)]
    runs += [rec("cancelled", 4513.9)]          # 270,834,000 ms of pure waiting
    return runs


# --------------------------------------------------------------------------- #
def main() -> int:
    # --- Defect A: an unmetered run is counted but never priced ------------- #
    print("cancelled runs contribute no minutes:")

    b = bucket_of(rec("cancelled", 4513.9))
    check("a cancelled run adds 0 to total_min", b["total_min"] == 0.0)
    check("a cancelled run adds 0 to waste_min", b["waste_min"] == 0.0)
    check("a cancelled run still counts as a run", b["runs"] == 1)
    check("a cancelled run still counts as cancelled", b["cancelled"] == 1)
    check("a cancelled run is not counted as a failure", b["failure"] == 0)
    check("a cancelled run leaves no duration sample", b["durations"] == [])
    check("a cancelled run is not a timed run", b["timed_runs"] == 0)

    b = bucket_of(rec("failure", 9.0), rec("timed_out", 3.0), rec("startup_failure", 1.0))
    check("failed/timed-out/startup minutes are still waste", close(b["waste_min"], 13.0))
    check("failed minutes are still consumption", close(b["total_min"], 13.0))

    b = bucket_of(rec("success", 4.0), rec("cancelled", 900.0))
    check("a cancellation cannot outweigh real minutes", close(b["total_min"], 4.0))
    check("success minutes are unaffected", close(b["success_min"], 4.0))

    # --- the flags that the phantom minutes tripped ------------------------- #
    print("evidence-gate no longer reads as slow or high-cost:")

    w = record_of(*evidence_gate_records())
    # 37 metered runs × 0.3m. Before the fix this was 11.1 + 4517.8 = 4528.9m,
    # the shape production published as 4536.4m.
    check("total_min is the 37 metered runs only", close(w["total_min"], 11.1, 0.05))
    check("the 4513.9m phantom is gone from the workflow's cost", w["total_min"] < 100.0)
    check("waste_min is the 7 real failures only", close(w["waste_min"], 2.1, 0.2))
    check("runs still counts every run, cancelled included", w["runs"] == 51)
    check("timed_runs excludes the 14 cancellations", w["timed_runs"] == 37)
    check("avg_min is over metered runs only", close(w["avg_min"], 0.3, 0.05))
    check("p95_min is no longer below the mean", w["p95_min"] >= w["avg_min"])
    # cancel_pct and the success rate are unchanged by the minute fix.
    check("cancel_pct is unchanged (14 of 43 decided+cancelled)", close(w["cancel_pct"], 32.6, 0.1))
    check("success_rate_pct is unchanged (22 of 29)", close(w["success_rate_pct"], 75.9, 0.1))

    fin = aa.finalize([w], [], {}, {}, {}, 14, 1, dt.datetime.now(dt.timezone.utc))
    flags = fin["workflows"][0]["flags"]
    check("the `slow` flag is gone", "slow" not in flags)
    check("the `high-cost-low-value` flag is gone", "high-cost-low-value" not in flags)
    check("the `cancel-heavy` flag is KEPT — the churn is real", "cancel-heavy" in flags)

    # A workflow that genuinely burns minutes must still be flagged, or the fix
    # has traded a false positive for a false negative.
    slow = record_of(*[rec("success", 40.0) for _ in range(5)], repo="hub")
    slow_flags = aa.finalize([slow], [], {}, {}, {}, 14, 1,
                             dt.datetime.now(dt.timezone.utc))["workflows"][0]["flags"]
    check("a genuinely slow workflow is still flagged `slow`", "slow" in slow_flags)

    # --- Defect B: totals are one population -------------------------------- #
    print("fleet totals are owned-only:")

    owned_w = record_of(*[rec("success", 10.0) for _ in range(8)],
                        *[rec("failure", 10.0) for _ in range(2)], repo="hub")
    external_w = record_of(*[rec("failure", 900.0) for _ in range(12)],
                           repo="skills", external=True)
    fin = aa.finalize([owned_w, external_w], [], {}, {}, {}, 14, 2,
                      dt.datetime.now(dt.timezone.utc))
    tot = fin["totals"]

    check("waste_min never exceeds total_min",
          tot["waste_min"] <= tot["total_min"])
    check("effectiveness_pct is a real percentage",
          0 <= tot["effectiveness_pct"] <= 100)
    check("total_min counts owned workflows only", close(tot["total_min"], 100.0))
    check("waste_min counts owned workflows only", close(tot["waste_min"], 20.0))
    check("effectiveness_pct reflects owned minutes (80%)",
          close(tot["effectiveness_pct"], 80.0, 0.1))
    check("runs counts owned workflows only", tot["runs"] == 10)
    check("success_rate_pct counts owned workflows only",
          close(tot["success_rate_pct"], 80.0, 0.1))
    check("the external mirror is still LISTED",
          any(x.get("external") for x in fin["workflows"]))
    check("the workflow count still spans the rendered table", tot["workflows"] == 2)

    # The end-to-end shape of #204: an unmetered outlier AND external waste in
    # the same report. Either defect alone was enough to publish a negative
    # effectiveness; both together are what production actually had.
    fin = aa.finalize([record_of(*evidence_gate_records()), owned_w, external_w],
                      [], {}, {}, {}, 14, 3, dt.datetime.now(dt.timezone.utc))
    tot = fin["totals"]
    check("combined: waste_min <= total_min", tot["waste_min"] <= tot["total_min"])
    check("combined: effectiveness_pct in [0, 100]",
          0 <= tot["effectiveness_pct"] <= 100)
    check("combined: the 4513.9m phantom is absent from total_min",
          tot["total_min"] < 200.0)

    # --- the note must not re-assert the disproved premise ------------------ #
    print("the published note describes what the code now does:")
    note = fin["note"].lower()
    check("the note no longer calls cost a proxy for billable minutes",
          "proxy for billable" not in note)
    check("the note no longer counts cancelled minutes as waste",
          "failed/cancelled/timed-out" not in note)
    check("the note states cancelled runs are not priced", "not priced" in note)
    check("the note states totals are owned-only", "owned" in note)
    check("cancelled is out of WASTE_CONCLUSIONS",
          "cancelled" not in aa.WASTE_CONCLUSIONS)
    check("cancelled is declared unmetered",
          "cancelled" in aa.UNMETERED_CONCLUSIONS)

    # --- report ------------------------------------------------------------ #
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
    but `pytest .github/scripts/dash-gen/test_actions_analytics.py` otherwise
    collects zero tests and exits 5, which reads as a pass to anyone checking `$?`.
    """
    CHECKS.clear()
    assert main() == 0, [label for label, ok in CHECKS if not ok]


if __name__ == "__main__":
    raise SystemExit(main())

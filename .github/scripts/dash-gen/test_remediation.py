#!/usr/bin/env python3
"""
Fixture tests for remediation.py — the fleet-doctor queue builder.

Guards the invariants that decide whether the daily loop is useful or a nuisance:

  * a workflow that is BOTH red and expensive must be ONE candidate carrying both
    signals — filing two tickets for one problem is exactly how the two split
    loops this replaces turned a queue into noise;
  * upstream mirrors must never reach a queue whose output is pull requests, even
    when the data's `external` flag is missing (older snapshots don't have it, and
    a missing key is falsey — the trap the previous implementation fell into);
  * anything already tracked by an open issue OR an open PR must be dropped, or a
    daily loop re-files the same work every morning;
  * the caps must hold, and the cross-repo sub-cap must not starve hub fixes;
  * a workflow that was FIXED inside the window, and one whose minutes are a
    human's debugging session, must not take a slot from a workflow that is
    actually broken (bamr87/bamr87#92);
  * "no verdicts" must never be published as "0% success".

Deliberately dependency-light — no network, no gh. Runs either way:

    python3 .github/scripts/dash-gen/test_remediation.py
    python3 -m pytest .github/scripts/dash-gen/test_remediation.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_analytics  # noqa: E402
import remediation  # noqa: E402

HUB = "bamr87/bamr87"
OWNER = "bamr87"

CFG = {
    "max_candidates": 6,
    "max_cross_repo": 3,
    "min_runs": 3,
    "min_priority": 10.0,
    "slow_avg_min": 10,
    "slow_p95_min": 20,
    "supersede_on_success": True,
    "interactive_dispatch_pct": 60,
    "severity": dict(remediation.DEFAULT_SEVERITY),
}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def triage(*repos) -> dict:
    return {"by_repo": list(repos), "totals": {}, "generated_at": "t"}


def repo_rec(nwo, failing=(), external=False, archived=False, private=False) -> dict:
    return {
        "nwo": nwo, "name": nwo.split("/")[-1],
        "repo_url": f"https://github.com/{nwo}",
        "external": external, "archived": archived, "private": private,
        "workflows": {"active": 1, "failing": [
            {"workflow": w, "path": p, "conclusion": "failure",
             "run_url": f"https://github.com/{nwo}/actions/runs/{i}",
             "run_at": "2026-08-01 00:00 UTC"}
            for i, (w, p) in enumerate(failing, 1)
        ]},
    }


def usage(*workflows) -> dict:
    return {"workflows": list(workflows), "totals": {}, "generated_at": "t",
            "window_days": 14}


def wf(nwo, name, path, *, runs=10, flags=(), avg=1.0, p95=2.0, waste=0.0,
       total=10.0, priority=0.0, external=None, last_conclusion=None,
       dispatch_pct=None, events=None) -> dict:
    rec = {
        "repo": nwo.split("/")[-1], "repo_url": f"https://github.com/{nwo}",
        "workflow": name, "path": path, "runs": runs, "flags": list(flags),
        "avg_min": avg, "p95_min": p95, "waste_min": waste, "total_min": total,
        "priority": priority, "effectiveness_pct": 50.0, "success_rate_pct": 50.0,
        "runs_per_week": 5, "sched_pct": 0, "type": "ci",
    }
    if external is not None:
        rec["external"] = external
    if last_conclusion is not None:
        rec["last_conclusion"] = last_conclusion
    if dispatch_pct is not None:
        rec["dispatch_pct"] = dispatch_pct
    if events is not None:
        rec["events"] = events
    return rec


# --------------------------------------------------------------------------- #
CHECKS: list[tuple[str, bool]] = []


def check(label: str, cond: bool) -> None:
    CHECKS.append((label, bool(cond)))


def build(tri, use, cfg=None):
    cfg = cfg or CFG
    cands = remediation.merge(
        remediation.failing_candidates(tri, OWNER),
        remediation.usage_candidates(use, cfg, OWNER),
    )
    cands.sort(key=lambda c: remediation.score(c, cfg), reverse=True)
    return cands


def main() -> int:
    # --- merge: one problem, one candidate -------------------------------- #
    print("merge:")
    path = ".github/workflows/ci.yml"
    cands = build(
        triage(repo_rec("bamr87/law-ai", failing=[("CI", path)])),
        usage(wf("bamr87/law-ai", "CI", path, flags=["slow"], avg=30.0, waste=99.0)),
    )
    check("red + expensive collapse to ONE candidate", len(cands) == 1)
    check("…carrying BOTH signals",
          cands and cands[0]["signals"] >= {"failing", "slow"})
    check("…and the cost record is attached", cands and cands[0]["usage"] is not None)

    # --- externality is derived, not trusted ------------------------------ #
    print("externality:")
    ext = build(
        triage(repo_rec("microsoft/skills", failing=[("Vally", path)], external=True)),
        # `external` deliberately ABSENT, as in snapshots written before the flag
        usage(wf("microsoft/skills", "Vally", path, flags=["failing"], waste=200.0)),
    )
    check("mirror excluded despite a missing `external` flag", ext == [])

    arch = build(triage(repo_rec("bamr87/old", failing=[("CI", path)], archived=True)),
                 usage())
    check("archived repo excluded", arch == [])

    # --- non-file workflows have nothing to fix --------------------------- #
    dyn = build(
        triage(repo_rec("bamr87/x", failing=[
            ("Codespaces", "dynamic/codespaces/create_codespaces_prebuilds")])),
        usage(),
    )
    check("dynamic non-file 'workflow' excluded", dyn == [])

    # --- thresholds -------------------------------------------------------- #
    print("thresholds:")
    quiet = build(triage(), usage(wf("bamr87/a", "W", path, runs=1, flags=["slow"])))
    check("below min_runs is ignored", quiet == [])

    slow_abs = build(triage(), usage(
        wf("bamr87/a", "W", path, runs=10, flags=[], avg=30.0)))
    check("long-running by absolute avg is caught without a flag",
          len(slow_abs) == 1 and "slow" in slow_abs[0]["signals"])

    boring = build(triage(), usage(
        wf("bamr87/a", "W", path, runs=10, flags=[], avg=1.0, p95=2.0, priority=0.0)))
    check("fast, green, low-priority workflow is not queued", boring == [])

    # --- false positives (bamr87/bamr87#92) --------------------------------- #
    # The live case: bamr87/irony-works `germinate.yml`, 2026-08-08. Three
    # workflow_dispatch runs 5 and 9 minutes apart — fail, fail, SUCCESS — plus
    # one skipped cron. The window averaged that to "33.3% success · 38.3%
    # effective" and it took one of four remediation slots, on a workflow that
    # had been green (and switched off) for nineteen days.
    print("false positives:")
    germinate = wf("bamr87/irony-works", "germinate",
                   ".github/workflows/germinate.yml",
                   runs=4, flags=["failing", "high-cost-low-value"],
                   avg=3.7, p95=8.0, waste=9.1, total=14.8, priority=18.2,
                   last_conclusion="success", dispatch_pct=75.0,
                   events={"workflow_dispatch": 3, "schedule": 1})
    check("a debugging session that ended GREEN is not queued",
          build(triage(), usage(germinate)) == [])

    # Each guard has to be load-bearing on its own, or a regression in one hides
    # behind the other.
    still_red = dict(germinate, last_conclusion="failure")
    cands_red = build(triage(), usage(still_red))
    check("…still queued when the latest verdict is red",
          len(cands_red) == 1 and "failing" in cands_red[0]["signals"])

    scheduled = dict(germinate, dispatch_pct=0.0,
                     events={"schedule": 4}, last_conclusion="failure")
    cands_sched = build(triage(), usage(scheduled))
    check("…cost signals survive when the runs are scheduled, not hand-driven",
          len(cands_sched) == 1
          and "high-cost-low-value" in cands_sched[0]["signals"])

    # A green workflow that is genuinely expensive is still real work: the
    # supersession guard settles CORRECTNESS, it must not silence COST.
    pricey = wf("bamr87/a", "Heavy", path, runs=20, flags=["high-cost-low-value"],
                avg=30.0, waste=400.0, total=900.0, priority=500.0,
                last_conclusion="success", dispatch_pct=0.0,
                events={"schedule": 20})
    cands_pricey = build(triage(), usage(pricey))
    check("a green but expensive workflow keeps its cost signals",
          len(cands_pricey) == 1
          and cands_pricey[0]["signals"] >= {"high-cost-low-value", "slow"})

    # The priority fallback is what admitted germinate on cost alone. It must
    # not fire for a hand-driven workflow whose flags the guards just removed.
    dispatch_only = wf("bamr87/a", "Manual", path, runs=5, flags=[],
                       avg=1.0, p95=2.0, waste=40.0, total=60.0, priority=99.0,
                       dispatch_pct=100.0, events={"workflow_dispatch": 5})
    check("the priority fallback does not admit a hand-driven workflow",
          build(triage(), usage(dispatch_only)) == [])

    # Old snapshots carry neither field. Absent data must change nothing.
    legacy = wf("bamr87/a", "W", path, runs=10, flags=["failing"], waste=50.0)
    check("a pre-guard snapshot behaves exactly as before",
          len(build(triage(), usage(legacy))) == 1)

    # The triage half already reads each workflow's LATEST conclusion, so a
    # standing failure must outlive the usage-side guard entirely.
    both = build(triage(repo_rec("bamr87/irony-works",
                                 failing=[("germinate",
                                           ".github/workflows/germinate.yml")])),
                 usage(germinate))
    check("a triage-side standing failure is never suppressed by these guards",
          len(both) == 1 and "failing" in both[0]["signals"])

    # --- no verdicts ≠ 0% (actions_analytics) ------------------------------- #
    # germinate's committed record read `failure: 0` beside `success_rate_pct:
    # 0.0` — a "no data" state rendered through the "has data" path, which is
    # indistinguishable on the dash from a workflow that failed every run.
    print("no verdicts:")
    b = actions_analytics.new_bucket()
    b["_name"], b["_path"] = "germinate", ".github/workflows/germinate.yml"
    for at in ("2026-08-10T06:38:00+00:00", "2026-08-17T06:38:00+00:00"):
        actions_analytics.fold(b, {"minutes": 0.2, "conclusion": "skipped",
                                   "event": "schedule", "created_at": at})
    rec = actions_analytics.workflow_record(
        b, repo="irony-works", repo_url="https://github.com/bamr87/irony-works",
        external=False, weeks=2.0)
    check("a verdict-free workflow reports success_rate_pct as null",
          rec["success_rate_pct"] is None)
    check("…and effectiveness_pct as null", rec["effectiveness_pct"] is None)
    check("…while still reporting zero failures", rec["failure"] == 0)
    check("…and no latest verdict", rec["last_conclusion"] is None)

    # With verdicts present the rates must be real numbers as before, and
    # `last_conclusion` must be the newest one — not the last one folded.
    b2 = actions_analytics.new_bucket()
    b2["_name"], b2["_path"] = "germinate", ".github/workflows/germinate.yml"
    for at, c in (("2026-08-08T21:11:00+00:00", "success"),
                  ("2026-08-08T20:57:00+00:00", "failure"),
                  ("2026-08-08T21:02:00+00:00", "failure")):
        actions_analytics.fold(b2, {"minutes": 4.0, "conclusion": c,
                                    "event": "workflow_dispatch", "created_at": at})
    rec2 = actions_analytics.workflow_record(
        b2, repo="irony-works", repo_url=None, external=False, weeks=2.0)
    check("a decided workflow still reports a real success rate",
          rec2["success_rate_pct"] == 33.3)
    check("latest verdict is the NEWEST run, not the last folded",
          rec2["last_conclusion"] == "success")
    check("dispatch share is recorded for the cost guard",
          rec2["dispatch_pct"] == 100.0)

    # --- ranking ----------------------------------------------------------- #
    print("ranking:")
    ranked = build(
        triage(repo_rec("bamr87/red", failing=[("CI", path)])),
        usage(wf("bamr87/exp", "Slow", ".github/workflows/slow.yml",
                 flags=["slow"], avg=60.0, waste=500.0, total=900.0)),
    )
    check("a red workflow outranks a merely expensive one",
          len(ranked) == 2 and ranked[0]["nwo"] == "bamr87/red")

    # --- dedupe ------------------------------------------------------------ #
    print("dedupe:")
    key = f"bamr87/law-ai:{path}"
    check("marker key is repo:path", remediation.marker_key("bamr87/law-ai", path) == key)
    for legacy in ("fleet-doctor", "actions-review", "daily-analysis"):
        body = f'<!-- {legacy} key="{key}" -->\nsome text'
        check(f"…{legacy} marker is recognised",
              remediation.MARKER_RE.findall(body) == [key])
    check("a bare key= elsewhere does NOT match",
          remediation.MARKER_RE.findall('key="%s"' % key) == [])

    # --- caps -------------------------------------------------------------- #
    print("caps:")
    # 5 submodule failures + 2 hub failures, cap 6 / cross-repo 3
    subs = [repo_rec(f"bamr87/s{i}", failing=[("CI", path)]) for i in range(5)]
    hub = repo_rec(HUB, failing=[("A", ".github/workflows/a.yml"),
                                 ("B", ".github/workflows/b.yml")])
    all_c = build(triage(*subs, hub), usage())
    selected, cross = [], 0
    for c in all_c:
        where = remediation.classify(c, HUB)
        if where == "submodule":
            if cross >= CFG["max_cross_repo"]:
                continue
            cross += 1
        c["_where"] = where
        selected.append(c)
        if len(selected) >= CFG["max_candidates"]:
            break
    check("overall cap respected", len(selected) <= CFG["max_candidates"])
    check("cross-repo sub-cap respected", cross <= CFG["max_cross_repo"])
    check("hub fixes are not starved by a burst of submodule failures",
          sum(1 for c in selected if c["_where"] == "hub") == 2)

    # --- retired workflows -------------------------------------------------- #
    # The bug the first production run exposed: a workflow deleted while red
    # stays "currently failing" in the triage data forever, because GitHub keeps
    # its run history. Three retired workflows took half the queue.
    print("retired:")
    real_exists = remediation.workflow_exists
    calls = []

    def fake_exists(nwo, path):
        calls.append((nwo, path))
        return "retired" not in path

    remediation.workflow_exists = fake_exists
    remediation._EXISTS_CACHE.clear()
    try:
        live = {"nwo": "bamr87/a", "path": ".github/workflows/live.yml"}
        dead = {"nwo": "bamr87/a", "path": ".github/workflows/retired.yml"}
        check("a live workflow file passes", fake_exists(**live))
        check("a deleted workflow file is filtered", not fake_exists(**dead))
    finally:
        remediation.workflow_exists = real_exists
        remediation._EXISTS_CACHE.clear()

    # Ambiguity must resolve toward KEEPING work: an unreachable repo 404s
    # exactly like a deleted file, and dropping real failures silently is worse
    # than carrying one stale entry.
    remediation._EXISTS_CACHE.clear()
    remediation._EXISTS_CACHE["bamr87/private:x.yml"] = True
    check("cache is consulted (no repeat API calls)",
          remediation.workflow_exists("bamr87/private", "x.yml") is True)
    remediation._EXISTS_CACHE.clear()

    # --- rendering --------------------------------------------------------- #
    print("render:")
    md = remediation.render(selected, CFG, HUB, usage(), triage(),
                            {"total": len(all_c), "deduped": 0, "retired": 2})
    check("every candidate's marker is emitted verbatim",
          all(remediation.doctor_marker(c["key"]) in md for c in selected))
    check("cross-repo candidates are told to PR in their own repo",
          "clone that repo and open a" in md)
    empty = remediation.render([], CFG, HUB, usage(), triage(),
                               {"total": 0, "deduped": 0, "retired": 0})
    check("an empty queue says do nothing", "Nothing to do." in empty)

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


def test_remediation() -> None:
    """pytest entry point — the same checks `main()` runs as a script.

    The suite is a script first (it must run with nothing but PyYAML installed),
    but `pytest .github/scripts/dash-gen/test_remediation.py` otherwise collects
    zero tests and exits 5, which reads as a pass to anyone checking `$?`.
    """
    CHECKS.clear()
    assert main() == 0, [label for label, ok in CHECKS if not ok]


if __name__ == "__main__":
    raise SystemExit(main())

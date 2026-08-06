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
  * the caps must hold, and the cross-repo sub-cap must not starve hub fixes.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_remediation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
       total=10.0, priority=0.0, external=None) -> dict:
    rec = {
        "repo": nwo.split("/")[-1], "repo_url": f"https://github.com/{nwo}",
        "workflow": name, "path": path, "runs": runs, "flags": list(flags),
        "avg_min": avg, "p95_min": p95, "waste_min": waste, "total_min": total,
        "priority": priority, "effectiveness_pct": 50.0, "success_rate_pct": 50.0,
        "runs_per_week": 5, "sched_pct": 0, "type": "ci",
    }
    if external is not None:
        rec["external"] = external
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


if __name__ == "__main__":
    raise SystemExit(main())

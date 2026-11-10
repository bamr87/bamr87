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

Schema v2 (2026-11-07, epic #773 / E1 #775) added four more, each measured
against GitHub's billing meter before it was fixed, and each case below FAILS
on the v1 code:

  * the HUB was never scanned — ~7,900 of ~12,050 billed minutes on Nov 1-7;
  * the listing stopped at `max_runs` (600 in fleet-pulse) without a word —
    zer0-CMS had 760 runs in the window;
  * cost was run wall clock; GitHub bills per JOB, rounded up to a minute,
    which ran 2-4x higher (zer0-CMS content.yml 883 vs 352);
  * the meter's per-repo map was read as shares, but it files the account's
    whole total under one repository name.

Deliberately dependency-light — no network, no gh, no PyGithub (the API is a
fixture serving plain JSON, and actions_analytics imports github lazily). Runs
either way:

    python3 .github/scripts/dash-gen/test_actions_analytics.py
    python3 -m pytest .github/scripts/dash-gen/test_actions_analytics.py -q
"""

from __future__ import annotations

import collections
import datetime as dt
import sys
import tempfile
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


def wall_cost(conclusion: str, hours: float, billed_jobs: int | None = 1) -> float:
    """The full wall-proxy path: a REST run dict's wall clock, then its bound."""
    run = {"conclusion": conclusion,
           "run_started_at": (NOW - dt.timedelta(hours=hours)).isoformat(),
           "created_at": (NOW - dt.timedelta(hours=hours)).isoformat(),
           "updated_at": NOW.isoformat()}
    dur = actions_analytics.run_wall_min(run)
    assert dur is not None
    return actions_analytics.wall_cost_min(conclusion, dur, billed_jobs)


def rec(minutes: float, conclusion: str = "success", event: str = "push",
        wall: float | None = None) -> dict:
    return {"workflow_id": 1, "name": "wf", "path": ".github/workflows/wf.yml",
            "event": event, "conclusion": conclusion, "minutes": minutes,
            "wall_min": minutes if wall is None else wall,
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


# A fake GitHub REST surface: runs, jobs and workflows as plain JSON, with the
# two listing limits the real one has — at most 1,000 results per `created`
# query, and a `total_count` that saturates at 2,500.
def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def mkrun(rid: int, *, wf: int = 1, created: dt.datetime, wall_min: float = 2.0,
          conclusion: str = "success", attempt: int = 1, status: str = "completed",
          event: str = "push") -> dict:
    return {"id": rid, "workflow_id": wf, "name": f"wf{wf}", "path": f".github/workflows/wf{wf}.yml",
            "event": event, "status": status, "conclusion": conclusion, "run_attempt": attempt,
            "created_at": iso(created), "run_started_at": iso(created),
            "updated_at": iso(created + dt.timedelta(minutes=wall_min))}


def mkjob(start: dt.datetime, seconds: float, conclusion: str = "success",
          runner: bool = True, labels=("ubuntu-latest",)) -> dict:
    return {"conclusion": conclusion, "started_at": iso(start),
            "completed_at": iso(start + dt.timedelta(seconds=seconds)),
            "runner_id": 7 if runner else None, "runner_name": "GitHub Actions 7" if runner else "",
            "labels": list(labels)}


class FakeApi:
    def __init__(self, runs: dict[str, list[dict]], jobs: dict[int, list[dict]] | None = None,
                 remaining: int | None = 5000,
                 default_branches: dict[str, str] | None = None) -> None:
        self.runs, self.jobs, self.remaining = runs, jobs or {}, remaining
        self.default_branches = default_branches or {}
        self.calls: collections.Counter = collections.Counter()
        self.job_requests: list[int] = []

    def core_remaining(self):
        return self.remaining

    def get(self, path, params=None, kind="other"):
        self.calls[kind] += 1
        params = params or {}
        nwo = "/".join(path.split("/")[2:4])
        if path == f"/repos/{nwo}":
            if nwo not in self.default_branches:
                raise RuntimeError("404")
            return {"full_name": nwo, "default_branch": self.default_branches[nwo]}
        if path.endswith("/actions/workflows"):
            ids = sorted({r["workflow_id"] for r in self.runs.get(nwo, [])})
            return {"total_count": len(ids), "workflows": [
                {"id": i, "name": f"wf{i}", "path": f".github/workflows/wf{i}.yml", "state": "active"}
                for i in ids]}
        if path.endswith("/actions/runs"):
            a, b = (actions_analytics.parse_ts(x) for x in params["created"].split(".."))
            hit = sorted((r for r in self.runs.get(nwo, [])
                          if a <= actions_analytics.parse_ts(r["created_at"]) <= b),
                         key=lambda r: r["created_at"], reverse=True)
            per, page = int(params.get("per_page", 30)), int(params.get("page", 1))
            visible = hit[:1000]
            return {"total_count": min(len(hit), 2500),
                    "workflow_runs": visible[(page - 1) * per: page * per]}
        if "/jobs" in path:
            rid = int(path.split("/")[-2])
            self.job_requests.append(rid)
            if rid not in self.jobs:
                raise RuntimeError("404")
            return {"total_count": len(self.jobs[rid]), "jobs": self.jobs[rid]}
        raise AssertionError(path)


HUB = {"name": "bamr87", "repo_url": "https://github.com/bamr87/bamr87", "category": "harness"}
SUB = {"name": "zer0-cms", "repo_url": "https://github.com/bamr87/zer0-CMS"}
MIRROR = {"name": "skills", "repo_url": "https://github.com/microsoft/skills"}


def report_of(targets, api, **kw) -> dict:
    kw.setdefault("now", NOW)
    kw.setdefault("cache", actions_analytics.JobCache(None))
    return actions_analytics.build_report(targets, api, **kw)


# --------------------------------------------------------------------------- #
# defect 1 — the wall-clock proxy (now the SECONDARY measure, still bounded)
# --------------------------------------------------------------------------- #
def case_non_executing_runs_cost_nothing() -> None:
    """FAILS on the pre-#229 code, which billed the full 4079.9 min wall clock."""
    cost = wall_cost("startup_failure", PHANTOM_HOURS, billed_jobs=None)
    check("a 68h startup_failure costs 0 wall minutes, not 4080", cost == 0.0)

    # …and the zeroing must reach the aggregates the queue ranks on.
    b = bucket_of(rec(0.0, conclusion="startup_failure", wall=cost))
    check("a zeroed run contributes 0.0 to total_min", b["total_min"] == 0.0)
    check("a zeroed run contributes 0.0 to wall_min", b["wall_min"] == 0.0)
    check("a zeroed run contributes 0.0 to waste_min", b["waste_min"] == 0.0)

    # Cost zero, verdict unchanged: the run really did fail.
    check("a zeroed run still counts as a failure", b["failure"] == 1)
    check("a zeroed run still counts as a run", b["runs"] == 1)
    w = actions_analytics.workflow_record(b, repo="r", repo_url=None,
                                          external=False, weeks=2.0)
    check("a zeroed run still reports 0% success, not None",
          w["success_rate_pct"] == 0.0)


def case_zero_job_failure_is_caught_by_the_job_list() -> None:
    """The PRODUCTION shape: the API reported run 33362222262 as a plain
    `failure`, so the conclusion filter alone would have missed it entirely.
    The job list (fetched FIRST for such suspects) proves it billed nothing."""
    check("a 68h `failure` with no billed job costs 0 wall minutes",
          wall_cost("failure", PHANTOM_HOURS, billed_jobs=0) == 0.0)

    # Under a budget of ONE request the suspect gets it, not the newest run.
    t0 = NOW - dt.timedelta(days=3)
    runs = {"bamr87/bamr87": [mkrun(1, created=t0, wall_min=PHANTOM_HOURS * 60, conclusion="failure"),
                              mkrun(2, created=t0 + dt.timedelta(hours=70), wall_min=3.0)]}
    api = FakeApi(runs, jobs={1: [], 2: [mkjob(t0, 120)]})
    rep = report_of([HUB], api, max_job_calls=1)
    check("a short job budget is spent on the wall-clock suspect first", api.job_requests == [1])
    w = rep["workflows"][0]
    check("the proven-jobless run adds 0 wall minutes (only the estimate's 3)", w["wall_min"] == 3.0)


def case_sub_clamp_phantom_minutes_are_zeroed() -> None:
    """The zer0-mistakes shape: jobless `failure` runs BELOW the 6h clamp.

    Six of them contributed 328.8 of markdown-oneline's 337.4 reported minutes
    (97.5%) against a real p95 of 0.28 min, which flagged a workflow costing
    ~9 minutes as the fleet's most expensive `high-cost-low-value` candidate.
    """
    for minutes in (297.35, 99.05, 24.93, 17.78):
        check(f"a jobless {minutes:.0f}min `failure` under the clamp costs 0",
              wall_cost("failure", minutes / 60, billed_jobs=0) == 0.0)

    # The JOB COUNT decides, never the duration alone: a long failure that
    # really did run must keep every minute it burned.
    check("a long failure that DID execute keeps its 60 min",
          wall_cost("failure", 1.0, billed_jobs=2) == 60.0)


def case_duration_is_capped() -> None:
    """FAILS on the pre-#229 code, which had no ceiling at all."""
    check("a 68h run that DID execute is clamped to 360 min",
          wall_cost("success", PHANTOM_HOURS, billed_jobs=3) == actions_analytics.MAX_RUN_MIN == 360.0)

    # An unread job list is "cannot tell", not "cost nothing": keep the run and
    # let the clamp bound it, rather than erasing real consumption.
    check("an unread job list falls back to the cap, not to zero",
          wall_cost("failure", PHANTOM_HOURS, billed_jobs=None) == 360.0)


def case_ordinary_runs_are_untouched() -> None:
    """The regression guard: the bounds must be invisible to every normal run."""
    for hours, concl in ((0.25, "success"), (2.0, "failure"), (0.1, "cancelled")):
        check(f"a {hours}h {concl} run keeps its exact wall clock",
              wall_cost(concl, hours) == hours * 60)


# --------------------------------------------------------------------------- #
# v2 — job-minutes are the cost
# --------------------------------------------------------------------------- #
def case_job_minutes_round_each_job_up() -> None:
    """GitHub bills per job, rounded up: the shape of hub run 42309889478 — a
    1.6-minute run of five jobs, one of them never started."""
    t0 = NOW - dt.timedelta(hours=1)
    jobs = [mkjob(t0, 4),                                   # 4 s -> 1 min
            mkjob(t0, 89, "cancelled"), mkjob(t0, 86, "cancelled"),   # -> 2 + 2
            mkjob(t0, 89, "cancelled"), mkjob(t0, 89, "cancelled"),   # -> 2 + 2
            mkjob(t0, 0, "cancelled", runner=False),        # never reached a runner
            mkjob(t0, -1, "skipped", runner=False)]         # skipped by its `if:`
    jm = actions_analytics.job_minutes(jobs)
    check("each job is rounded up to a whole minute", jm["job_min"] == 9)
    check("a never-started and a skipped job bill nothing",
          jm["billed_jobs"] == 5 and jm["skipped_jobs"] == 1 and jm["jobs"] == 7)
    check("a self-hosted job is not billed",
          actions_analytics.job_minutes([mkjob(t0, 600, labels=("self-hosted", "linux"))])["job_min"] == 0)

    runs = {"bamr87/bamr87": [mkrun(10, created=t0, wall_min=1.6)]}
    w = report_of([HUB], FakeApi(runs, jobs={10: jobs}))["workflows"][0]
    check("total_min is job-minutes (9), not the run's 1.6 wall minutes",
          w["total_min"] == 9.0 and w["wall_min"] == 1.6)
    check("avg_min is job-minutes per run; wall_avg_min stays the latency",
          w["avg_min"] == 9.0 and w["wall_avg_min"] == 1.6)


def case_slow_is_latency_not_cost() -> None:
    """Ten parallel 2-minute jobs cost 20 minutes and finish in 2: expensive per
    run, never `slow`. One 20-minute job is both."""
    wide = [rec(20.0, wall=2.0)] * 5
    check("a wide matrix is not slow", "slow" not in flags_of(*wide))
    long = [rec(20.0, wall=20.0)] * 5
    check("a long serial job is slow", "slow" in flags_of(*long))


def case_no_job_conclusions_cost_no_request() -> None:
    """A skipped / startup_failure / approval-parked run cannot have billed: 0
    job-minutes, and no request spent proving it."""
    t0 = NOW - dt.timedelta(days=1)
    runs = {"bamr87/bamr87": [mkrun(i, created=t0 + dt.timedelta(minutes=i), conclusion=c)
                              for i, c in enumerate(("skipped", "startup_failure", "action_required"), 1)]}
    api = FakeApi(runs)
    rep = report_of([HUB], api)
    check("no job request for runs that cannot bill", api.calls["jobs"] == 0)
    check("they cost 0 job-minutes and 0 wall minutes",
          sum(w["total_min"] + w["wall_min"] for w in rep["workflows"]) == 0.0)


# --------------------------------------------------------------------------- #
# v2 — the hub is in, and nothing is silently capped
# --------------------------------------------------------------------------- #
def case_the_hub_is_scanned() -> None:
    """FAILS on the v1 code, whose build_report iterated _data/projects.yml."""
    with tempfile.TemporaryDirectory() as tmp:
        fleet = Path(tmp) / "fleet.yml"
        fleet.write_text("hub:\n  repo: bamr87/bamr87\n")
        targets = actions_analytics.with_hub([SUB], fleet)
        check("with_hub puts the hub first", [t["name"] for t in targets] == ["bamr87", "zer0-cms"])
        check("with_hub is idempotent", len(actions_analytics.with_hub(targets, fleet)) == 2)
    check("the live fleet.yml still declares the hub",
          actions_analytics.hub_entry()["repo_url"].endswith("/bamr87/bamr87"))

    t0 = NOW - dt.timedelta(days=2)
    runs = {"bamr87/bamr87": [mkrun(1, created=t0)], "bamr87/zer0-CMS": [mkrun(2, created=t0)]}
    rep = report_of([HUB, SUB], FakeApi(runs, jobs={1: [mkjob(t0, 300)], 2: [mkjob(t0, 60)]}))
    repos = {r["repo"]: r for r in rep["by_repo"]}
    check("the hub has a by_repo row", repos.get("bamr87", {}).get("total_min") == 5.0)
    check("the hub counts in the fleet totals", rep["totals"]["total_min"] == 6.0)


def case_the_window_is_paged_not_capped() -> None:
    """zer0-CMS had 760 runs in the window and fleet-pulse's --max-runs 600
    reported 600 with no sign of the rest. Listing by created date has its own
    1,000-result cap, so a busy window is split until each range is under it."""
    runs = [mkrun(i, created=NOW - dt.timedelta(minutes=8 * i + 1), wall_min=1.0)
            for i in range(2400)]                    # ~13.3 days, 2,400 runs
    api = FakeApi({"bamr87/zer0-CMS": runs})
    listing = actions_analytics.list_window_runs(api, "bamr87/zer0-CMS",
                                                 NOW - dt.timedelta(days=14), NOW)
    check("all 2,400 runs are listed across the 1,000-result cap",
          len(listing["runs"]) == 2400 and len({r["id"] for r in listing["runs"]}) == 2400)
    check("a fully listed window is not truncated",
          listing["truncated"] is False and listing["runs_missed"] == 0
          and listing["in_window"] == 2400)

    capped = actions_analytics.list_window_runs(api, "bamr87/zer0-CMS",
                                                NOW - dt.timedelta(days=14), NOW, max_runs=600)
    check("a --max-runs cap that bites says truncated, with the count missed",
          capped["truncated"] and len(capped["runs"]) == 600 and capped["runs_missed"] == 1800)

    burst = [mkrun(i, created=NOW - dt.timedelta(hours=1, seconds=i % 200), wall_min=1.0)
             for i in range(1200)]                   # 1,200 runs inside 200 seconds
    tight = actions_analytics.list_window_runs(FakeApi({"o/r": burst}), "o/r",
                                               NOW - dt.timedelta(days=14), NOW)
    check("a range too narrow to split is reported, not dropped",
          tight["truncated"] and tight["runs_missed"] == 200 and len(tight["runs"]) == 1000)

    rep = report_of([SUB], FakeApi({"bamr87/zer0-CMS": runs[:5]}, jobs={}), max_runs=3)
    row = rep["by_repo"][0]
    check("by_repo carries truncated + runs_missed", row["truncated"] and row["runs_missed"] == 2)
    check("the totals and coverage say so too",
          rep["totals"]["truncated"] and rep["coverage"]["truncated_repos"] == ["zer0-cms"])


# --------------------------------------------------------------------------- #
# v2 — the API budget: cache, ceiling, sampling
# --------------------------------------------------------------------------- #
def _fleet(n: int, wf_of=lambda i: 1 + i % 2):
    t0 = NOW - dt.timedelta(days=1)
    runs = [mkrun(i, wf=wf_of(i), created=t0 + dt.timedelta(minutes=i), wall_min=2.0) for i in range(1, n + 1)]
    jobs = {i: [mkjob(t0, 100), mkjob(t0, 100)] for i in range(1, n + 1)}   # 2 + 2 = 4 job-min, 2 wall
    return {"bamr87/bamr87": runs}, jobs


def case_only_new_runs_cost_a_request() -> None:
    runs, jobs = _fleet(20)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        api = FakeApi(runs, jobs)
        cache = actions_analytics.JobCache(path)
        first = report_of([HUB], api, cache=cache)
        cache.save()
        check("a cold cache fetches every completed run once", api.calls["jobs"] == 20)

        t1 = NOW + dt.timedelta(hours=1)
        runs["bamr87/bamr87"].append(mkrun(21, created=t1 - dt.timedelta(minutes=5), wall_min=2.0))
        jobs[21] = [mkjob(t1, 30)]
        api2 = FakeApi(runs, jobs)
        cache2 = actions_analytics.JobCache(path)
        second = report_of([HUB], api2, cache=cache2, now=t1)
        cache2.save()
        check("the next sweep fetches only the run that is new", api2.job_requests == [21])
        check("cached and fresh runs price the same",
              second["totals"]["total_min"] == first["totals"]["total_min"] + 1.0)

        runs["bamr87/bamr87"][0]["run_attempt"] = 2          # a re-run is a new attempt
        api3 = FakeApi(runs, jobs)
        report_of([HUB], api3, cache=actions_analytics.JobCache(path), now=t1)
        check("a re-run attempt is fetched again", api3.job_requests == [1])

        kept = actions_analytics.JobCache(path)
        kept.save(prune_before=NOW + dt.timedelta(days=30))
        check("the cache prunes runs older than the window", kept.runs == {})


def case_the_ceiling_degrades_to_a_marked_sample() -> None:
    runs, jobs = _fleet(20)
    api = FakeApi(runs, jobs)
    rep = report_of([HUB], api, max_job_calls=6)
    check("job requests stop at --max-job-calls", api.calls["jobs"] == 6)
    check("both workflows are measured before either is finished (round-robin)",
          sorted({1 + i % 2 for i in api.job_requests}) == [1, 2])
    t = rep["totals"]
    check("the totals say sampled, with how many runs are estimates",
          t["sampled"] is True and t["job_runs_estimated"] == 14)
    check("every estimated row says sampled", all(w["sampled"] for w in rep["workflows"]))
    check("estimates use the workflow's measured job/wall ratio (4 per 2)",
          t["total_min"] == 80.0)
    check("the API block records the budget", rep["coverage"]["api"]["job_call_budget"] == 6)

    api = FakeApi(runs, jobs, remaining=1003)
    rep = report_of([HUB], api, api_reserve=1000)
    check("the quota left after the reserve caps the budget too", api.calls["jobs"] == 3)

    ticks = iter(range(100))                       # each clock() call is one "second"
    api = FakeApi(runs, jobs)
    rep = report_of([HUB], api, max_job_seconds=4, clock=lambda: next(ticks))
    check("job requests also stop at --max-job-seconds, and say why",
          0 < api.calls["jobs"] < 20 and rep["totals"]["sampled"]
          and rep["coverage"]["api"]["job_fetch_stopped_by"] == "time")

    full = report_of([HUB], FakeApi(runs, jobs))
    check("a full budget is not sampled", full["totals"]["sampled"] is False
          and full["totals"]["total_min"] == 80.0)


def case_external_mirrors_never_enter_totals() -> None:
    t0 = NOW - dt.timedelta(days=1)
    runs = {"bamr87/bamr87": [mkrun(1, created=t0)], "microsoft/skills": [mkrun(2, created=t0)]}
    api = FakeApi(runs, jobs={1: [mkjob(t0, 60)], 2: [mkjob(t0, 6000)]})
    rep = report_of([HUB, MIRROR], api, max_job_calls=1)
    check("owned runs get the budget before an external mirror's", api.job_requests == [1])
    check("the mirror's minutes stay out of the totals", rep["totals"]["total_min"] == 1.0)
    check("the mirror stays visible per-workflow", any(w["external"] for w in rep["workflows"]))


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
# defect 4 — a policy gate read as flaky (bamr87/bamr87#614)
# --------------------------------------------------------------------------- #
def head(conclusion: str, branch: str, sha: str, default: str = "main") -> dict:
    r = rec(0.26, conclusion, event="pull_request")
    r.update(head_branch=branch, head_sha=sha, default_branch=default)
    return r


def case_pr_contents_are_not_flakiness() -> None:
    """The zer0-mistakes Evidence gate: every failure is the gate rejecting a PR
    that lacks its evidence. FAILS on the pre-fix code, which flagged it `flaky`
    from the success rate alone."""
    runs = ([head("failure", "grokbot/fix-sidebar", f"g{i}") for i in range(5)]
            + [head("failure", "agent/issue-573", "a1")]
            + [head("success", "agent/issue-573", f"a{i}") for i in range(2, 5)]
            + [head("success", f"deps/{i}", f"d{i}") for i in range(7)])
    flags = flags_of(*runs)
    check("PR-decided failures (two branches, distinct SHAs) are pr-red", "pr-red" in flags)
    check("…and not flaky", "flaky" not in flags)

    # All red, still decided by PR contents: not `failing` either.
    red = [head("failure", "feat/x", f"x{i}") for i in range(3)] + [head("success", "feat/y", "y1")]
    flags = flags_of(*red)
    check("a sub-50% PR-only failure rate is pr-red, not failing",
          "pr-red" in flags and "failing" not in flags)

    # Healthy workflows get no flag at all.
    green = [head("success", "feat/z", f"z{i}") for i in range(10)] + [head("failure", "feat/w", "w1")]
    check("a mostly-green workflow gets no pr-red", "pr-red" not in flags_of(*green))


def case_same_commit_flip_is_still_flaky() -> None:
    """A re-run that passed where the same commit had failed IS non-determinism."""
    runs = ([head("failure", "feat/a", "s1"), head("success", "feat/a", "s1")]
            + [head("success", "feat/b", f"b{i}") for i in range(3)]
            + [head("failure", "feat/c", "c1")])
    flags = flags_of(*runs)
    check("one head_sha with a success and a failure stays flaky",
          "flaky" in flags and "pr-red" not in flags)


def case_default_branch_failures_are_unchanged() -> None:
    """A red verdict on the default branch is the workflow's, not a PR's."""
    flaky = ([head("failure", "main", "m1"), head("failure", "feat/a", "f1")]
             + [head("success", "feat/b", f"b{i}") for i in range(4)])
    check("a failure on the default branch keeps flaky", "flaky" in flags_of(*flaky))
    failing = [head("failure", "main", f"m{i}") for i in range(3)] + [head("success", "feat/b", "b1")]
    check("default-branch failures keep failing", "failing" in flags_of(*failing))


def case_missing_head_fields_fail_open() -> None:
    """Older fixtures and API gaps carry no head fields: today's rule applies."""
    plain = [rec(0.26, "failure")] * 2 + [rec(0.26, "success")] * 3
    check("records without head fields keep flaky", "flaky" in flags_of(*plain))
    # One untracked verdict is enough to fall back: absence of evidence is not
    # evidence that the PR decided it.
    mixed = [head("failure", "feat/a", "f1"), rec(0.26, "failure")] + \
            [head("success", "feat/b", f"b{i}") for i in range(3)]
    check("one verdict without head fields falls back to flaky",
          "flaky" in flags_of(*mixed))
    blank = [head("failure", "feat/a", "f1", default="")] * 2 + \
            [head("success", "feat/b", f"b{i}") for i in range(3)]
    check("an unknown default branch falls back to flaky", "flaky" in flags_of(*blank))
    wf = workflow("bamr87/x", False, *plain)
    check("pr_red is published as a plain bool", wf.get("pr_red") is False)


def case_build_report_carries_head_fields() -> None:
    """End to end through the REST surface: each run's `head_branch`/`head_sha`
    and the repo's default branch reach the fold, so `pr-red` fires on real
    data and not only on hand-built records. FAILS if build_report drops them
    (every verdict is then untracked and the rule falls back to `flaky`)."""
    def gate_runs() -> list[dict]:
        t = NOW - dt.timedelta(days=1)
        runs = []
        for i, (concl, branch) in enumerate([("failure", "feat/a"), ("failure", "feat/b")]
                                             + [("success", f"feat/s{i}") for i in range(4)]):
            r = mkrun(100 + i, created=t + dt.timedelta(minutes=i), conclusion=concl,
                      event="pull_request")
            r.update(head_branch=branch, head_sha=f"sha{i}")
            runs.append(r)
        return runs

    def flags(api) -> list[str]:
        rep = report_of([SUB], api, max_job_calls=0)
        wf = [w for w in rep["workflows"] if w["repo"] == SUB["name"]]
        return wf[0]["flags"] if wf else []

    api = FakeApi({"bamr87/zer0-CMS": gate_runs()},
                  default_branches={"bamr87/zer0-CMS": "main"})
    got = flags(api)
    check("build_report: PR-only failures on distinct SHAs are pr-red", "pr-red" in got)
    check("build_report: …and not flaky", "flaky" not in got)
    check("build_report: the default branch costs one repo request", api.calls["repo"] == 1)

    # The repo read failing must not break the sweep: it falls back to `flaky`.
    api = FakeApi({"bamr87/zer0-CMS": gate_runs()})
    got = flags(api)
    check("build_report: an unreadable default branch fails open to flaky",
          "flaky" in got and "pr-red" not in got)


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
    check("the note states job-minutes are the cost", "job-minutes" in text)
    check("the note says the meter is account-level", "ACCOUNT" in text)
    check("the snapshot carries its schema marker",
          report["schema"] == "actions-usage/v2" and report["minutes_basis"] == "job-minutes")


# --------------------------------------------------------------------------- #
# v2 — parity with the meter
# --------------------------------------------------------------------------- #
def _billing(minutes: float, day: int, month: str = "2026-09") -> dict:
    return {"this_month": month, "days_elapsed": day, "minutes_this_month": minutes}


def case_parity_month_to_date() -> None:
    """Nov 1-7: the meter's 11,925 against the hub-less wall clock's ~4,100."""
    days = [{"date": f"2026-08-{d:02d}", "total_min": 999.0, "wall_min": 999.0} for d in (25, 31)]
    days += [{"date": f"2026-09-0{d}", "total_min": 450.0, "wall_min": 150.0} for d in (1, 2, 3)]
    p = actions_analytics.actions_parity(days, _billing(1500.0, 3), NOW, 14)
    check("parity compares month-to-date when the month is inside the window",
          p["basis"] == "month-to-date" and p["ours_min"] == 1350.0 and p["reference_min"] == 1500.0)
    check("job-minutes gap is -10%, the wall clock's -70%",
          p["gap_pct"] == -10.0 and p["wall_gap_pct"] == -70.0)


def case_parity_daily_rate_and_missing_meter() -> None:
    late = dt.datetime(2026, 9, 20, 12, tzinfo=dt.timezone.utc)
    days = [{"date": f"2026-09-{d:02d}", "total_min": 100.0, "wall_min": 50.0} for d in range(7, 21)]
    p = actions_analytics.actions_parity(days, _billing(2000.0, 20), late, 14)
    check("a month longer than the window compares daily rates",
          p["basis"] == "daily-rate" and p["ours_min_per_day"] == 100.0
          and p["reference_min_per_day"] == 100.0 and p["gap_pct"] == 0.0)
    gone = actions_analytics.actions_parity(days, {"error": "403 scope"}, late, 14)
    check("no meter, no number — and the reason", gone["gap_pct"] is None and "403" in gone["reason"])
    check("a report always carries the parity block",
          "actions_minutes" in actions_analytics.finalize([], [], {}, {}, {}, 14, 0, NOW)["parity"])


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def main() -> int:
    for fn in (case_non_executing_runs_cost_nothing,
               case_zero_job_failure_is_caught_by_the_job_list,
               case_sub_clamp_phantom_minutes_are_zeroed,
               case_duration_is_capped,
               case_ordinary_runs_are_untouched,
               case_job_minutes_round_each_job_up,
               case_slow_is_latency_not_cost,
               case_no_job_conclusions_cost_no_request,
               case_the_hub_is_scanned,
               case_the_window_is_paged_not_capped,
               case_only_new_runs_cost_a_request,
               case_the_ceiling_degrades_to_a_marked_sample,
               case_external_mirrors_never_enter_totals,
               case_totals_range_over_one_population,
               case_owned_only_fleet_is_unchanged,
               case_supersession_is_not_cancel_heavy,
               case_real_cancellation_churn_still_flags,
               case_cancelled_minutes_are_published,
               case_pr_contents_are_not_flakiness,
               case_same_commit_flip_is_still_flaky,
               case_default_branch_failures_are_unchanged,
               case_missing_head_fields_fail_open,
               case_build_report_carries_head_fields,
               case_note_documents_the_bounds,
               case_parity_month_to_date,
               case_parity_daily_rate_and_missing_meter):
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

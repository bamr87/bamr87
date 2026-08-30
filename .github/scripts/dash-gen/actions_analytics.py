#!/usr/bin/env python3
"""
actions_analytics — GitHub Actions usage analytics for the bamr87 dash.

Queries the GitHub Actions API (via the PyGithub integration library) for every
repo in the registry, aggregates workflow-run consumption, and writes a
COMMITTED data file (_data/actions_usage.yml) that the Jekyll dash renders. Unlike
the health/ai generators (ephemeral, gitignored), this file is persisted and
refreshed on a daily schedule (.github/workflows/fleet-pulse.yml) so the page
shows a stable, once-a-day snapshot.

The engine answers: where do Actions minutes go, and which workflows run a lot
while producing little? It groups consumption by workflow *type* and surfaces
"high running, low effective" workflows quantitatively (cost = wall-clock minutes,
value = share of minutes that end in success; waste = minutes on non-success runs).

Cancelled runs contribute NO minutes — neither to `total_min` nor to `waste_min`.
Their wall clock is not a cost signal: GitHub stamps `run_started_at` when a run
is created and `updated_at` when it is cancelled, so a run that merely WAITED
(queued, or parked in `action_required` awaiting approval) reports the whole wait
as duration while billing nothing at all. They are also not failures:
`success_rate_pct` and the failing/flaky flags look only at runs that reached a
verdict. Conflating either made a working `concurrency: cancel-in-progress`
guard read as broken *and* expensive — see UNMETERED_CONCLUSIONS.

Fleet TOTALS are computed over bamr87-owned workflows only, the same population
`share_pct` and the optimization flags already used. Mixing external mirrors into
one half of a ratio and not the other is what published a waste figure larger
than the consumption it was a share of.

For the same reason a workflow with NO verdicts in the window — every run
skipped by an `if:` gate — reports `success_rate_pct` / `effectiveness_pct` as
`None`, not `0.0`: "no data" and "failed every run" are different states and
must not render identically.

Auth: a token from GH_TOKEN / GITHUB_TOKEN, else `gh auth token`. Network / rate
-limit failures degrade gracefully (a repo that can't be read is skipped, not fatal).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import statistics
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("actions_analytics requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "_data" / "projects.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "actions_usage.yml"

# Thresholds for the optimization flags (tunable).
SLOW_AVG_MIN = 12.0        # a run averaging longer than this is "slow"
LOW_EFFECTIVENESS = 55     # < this % of minutes ending in success is "low value"
CANCEL_HEAVY_PCT = 25      # cancelled share above this is "cancel-heavy"
CRON_HEAVY_PCT = 60        # scheduled share above this is "cron-heavy"
MIN_WASTE_MIN = 4.0        # ignore trivial waste below this when flagging

# Non-success terminal conclusions whose minutes count as waste.
WASTE_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}

# Conclusions whose wall clock is NOT a cost signal, so their minutes enter
# neither `total_min` nor `waste_min`.
#
# GitHub stamps `run_started_at` at creation and `updated_at` at cancellation,
# which puts the ENTIRE wait inside the span this module measures — while
# `/actions/runs/{id}/timing` reports `billable: {}` for a run that never
# started a job. One cancelled run in bamr87/zer0-mistakes therefore booked
# 4,513.9 phantom minutes: 99.5% of its workflow's reported cost, enough to
# push a correctly-functioning gate to the top of the remediation queue
# (bamr87/bamr87#204). `timeout-minutes` cannot bound this — that clock starts
# when a job begins, and none did.
#
# Cancelled runs still count as RUNS, so `cancel_pct` and the `cancel-heavy`
# flag are unchanged; only their minutes are dropped.
UNMETERED_CONCLUSIONS = {"cancelled"}

# Conclusions that say nothing about whether the workflow works. A run whose
# `if:` gate declined is the system behaving correctly at ~zero cost, so it must
# not be the run that decides "is this workflow currently broken?".
NON_VERDICT_CONCLUSIONS = {"skipped", "neutral", "action_required", "stale"}

# Workflow-type classification. First matching rule wins; matched against
# "<name> <path>" lowercased. Purpose-specific types precede the generic "ci".
TYPE_RULES = [
    ("dependencies", ["dependabot", "dependency", "renovate", "update-deps", "bump ", "deps"]),
    ("security",     ["codeql", "security", "secret", "scan", "trivy", "snyk", "sast", "audit"]),
    ("ai",           ["evolve", "evolution", "claude", "agent", "autopilot", "quest",
                      "content-factory", "content-review", "content-quality", "content-auto",
                      "cms-", "theme-scout", "ai-", "llm", "vally", "skill-eval"]),
    ("release",      ["release", "publish", "semantic", "changelog", "adopt-release",
                      "version", "release-please", " tag"]),
    ("deploy",       ["deploy", "gh-pages", "pages", "vercel", "netlify", "build-dash",
                      "chat-proxy", "cd-", "cd."]),
    ("docs",         ["docs", "mkdocs", "jekyll", "link-check", "linkcheck", "frontmatter",
                      "sync-gh-pages", "convert-notebook"]),
    ("automation",   ["auto-merge", "automerge", "issue", "pr-auto", "sync", "dispatcher",
                      "cleanup", "stale", "milestone", "contributor", "maintenance", "refresh",
                      "drift", "standardize", "submodule", "giscus", "triage", "dispatch",
                      "self-repair", "new-feature"]),
    ("ci",           ["ci", "test", "lint", "build", "check", "validate", "quality",
                      "coverage", "actionlint", "shellcheck", "matrix", "harness", "install"]),
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def resolve_token() -> str | None:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def owner_repo(repo_url: str) -> str | None:
    if "github.com/" not in repo_url:
        return None
    tail = repo_url.split("github.com/", 1)[1].removesuffix(".git").strip("/")
    parts = tail.split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None


def classify_type(name: str, path: str) -> str:
    hay = f"{name} {path}".lower()
    for wtype, keys in TYPE_RULES:
        if any(k in hay for k in keys):
            return wtype
    return "other"


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def duration_min(run) -> float | None:
    start = as_utc(run.run_started_at) or as_utc(run.created_at)
    end = as_utc(run.updated_at)
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds() / 60.0)


# --------------------------------------------------------------------------- #
# per-repo collection
# --------------------------------------------------------------------------- #
def collect_repo(gh, nwo: str, window_start: dt.datetime, max_runs: int) -> tuple[dict, list]:
    """Return ({workflow_id: meta}, [run-record]) for one repo within the window."""
    from github.GithubException import GithubException

    try:
        repo = gh.get_repo(nwo)
    except GithubException:
        return {}, []

    wf_meta: dict[int, dict] = {}
    try:
        for wf in repo.get_workflows():
            wf_meta[wf.id] = {"name": wf.name, "path": wf.path, "state": wf.state}
    except GithubException:
        pass

    records: list[dict] = []
    seen = 0
    try:
        for run in repo.get_workflow_runs():
            created = as_utc(run.created_at)
            if created and created < window_start:
                break                        # runs are newest-first: past the window
            seen += 1
            if seen > max_runs:
                break
            if run.status != "completed":
                continue                     # only finished runs have an outcome/duration
            dur = duration_min(run)
            if dur is None:
                continue
            wid = run.workflow_id
            name = (wf_meta.get(wid, {}).get("name") or run.name
                    or os.path.basename(getattr(run, "path", "") or "workflow"))
            path = wf_meta.get(wid, {}).get("path") or getattr(run, "path", "") or ""
            records.append({
                "workflow_id": wid,
                "name": name,
                "path": path,
                "event": run.event or "unknown",
                "conclusion": run.conclusion or "unknown",
                "minutes": dur,
                "day": created.date().isoformat() if created else None,
                "created_at": created.isoformat() if created else None,
            })
    except GithubException:
        pass
    return wf_meta, records


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def new_bucket() -> dict:
    return {"runs": 0, "timed_runs": 0, "total_min": 0.0, "success_min": 0.0, "waste_min": 0.0,
            "success": 0, "failure": 0, "cancelled": 0, "other": 0,
            "durations": [], "events": {},
            "last_conclusion": None, "last_at": None}


def fold(bucket: dict, rec: dict) -> None:
    m = rec["minutes"]
    c = rec["conclusion"]
    bucket["runs"] += 1
    bucket["events"][rec["event"]] = bucket["events"].get(rec["event"], 0) + 1
    # An unmetered run counts as a RUN but contributes no minutes anywhere —
    # not to the total, not to waste, and not to the duration sample that feeds
    # avg/p95. Its wall clock is wait time, not consumption.
    metered = c not in UNMETERED_CONCLUSIONS
    if metered:
        bucket["timed_runs"] += 1
        bucket["total_min"] += m
        bucket["durations"].append(m)
    # Newest run that actually reached a verdict. Compared by timestamp rather
    # than trusting the caller's ordering, so this stays correct if records are
    # ever folded out of order. `created_at` is a uniform UTC isoformat string,
    # so a lexicographic compare is a chronological one.
    if c not in NON_VERDICT_CONCLUSIONS:
        at = rec.get("created_at") or ""
        if bucket["last_at"] is None or at > bucket["last_at"]:
            bucket["last_at"] = at
            bucket["last_conclusion"] = c
    if c == "success":
        bucket["success_min"] += m
        bucket["success"] += 1
    elif c == "cancelled":
        # Counted, never priced — see UNMETERED_CONCLUSIONS.
        bucket["cancelled"] += 1
    elif c in WASTE_CONCLUSIONS:
        bucket["waste_min"] += m
        bucket["failure"] += 1
    else:
        bucket["other"] += 1


def pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def pct_or_none(part: float, whole: float) -> float | None:
    """`pct`, except an EMPTY denominator reads as "no data" instead of 0%.

    `pct(0, 0) == 0.0` is the wrong answer for a rate: a workflow whose runs all
    got skipped has no verdicts at all, and publishing "0.0% success" next to
    "0 failures" made it indistinguishable on the dash from one that failed
    every run (bamr87/bamr87#92). `None` renders as "—".
    """
    return round(100 * part / whole, 1) if whole else None


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return round(s[idx], 2)


def workflow_record(b: dict, *, repo: str, repo_url: str | None,
                    external: bool, weeks: float) -> dict:
    """One workflow's aggregated row, from its folded bucket."""
    # Runs that reached a verdict. With none, the rates below are UNKNOWN, not
    # zero — see pct_or_none.
    decided = b["success"] + b["failure"]
    return {
        "repo": repo, "repo_url": repo_url, "external": external,
        "workflow": b["_name"], "type": classify_type(b["_name"], b["_path"]),
        "path": b["_path"],
        "runs": b["runs"],
        # Runs that contributed minutes. `runs - timed_runs` are the unmetered
        # (cancelled) ones; publishing both keeps `avg_min` reconcilable against
        # `total_min` by a reader with a calculator.
        "timed_runs": b["timed_runs"],
        "total_min": round(b["total_min"], 1),
        # Averaged over METERED runs only. Dividing real minutes by a count that
        # includes zero-cost cancellations would make a cancel-heavy workflow
        # read as fast rather than as churning.
        "avg_min": round(b["total_min"] / b["timed_runs"], 2) if b["timed_runs"] else 0.0,
        "p95_min": p95(b["durations"]),
        "waste_min": round(b["waste_min"], 1),
        "runs_per_week": round(b["runs"] / weeks, 1),
        "success": b["success"], "failure": b["failure"], "cancelled": b["cancelled"],
        # Cancelled runs are EXCLUDED from the denominator: a superseded
        # run reached no verdict, so counting it as "not a success" made
        # `success_rate_pct` measure churn instead of correctness, and
        # the sub-50% result then tripped the `failing` flag on
        # workflows with zero actual failures. Their MINUTES are excluded
        # too — a cancelled run's wall clock is however long it WAITED, and
        # the billing API charges nothing for it (UNMETERED_CONCLUSIONS).
        # The churn itself stays visible as cancel_pct / `cancel-heavy`.
        "success_rate_pct": pct_or_none(b["success"], decided),
        "cancel_pct": pct(b["cancelled"], decided + b["cancelled"]),
        "effectiveness_pct": (None if not decided
                              else pct(b["success_min"], b["total_min"]) if b["total_min"]
                              else 100.0),
        "sched_pct": pct(b["events"].get("schedule", 0), b["runs"]),
        # Share of runs a human triggered by hand. Debugging sessions are
        # expected to fail and to burn minutes; the remediation queue uses this
        # to keep that cost out of the fleet's standing-waste signals.
        "dispatch_pct": pct(b["events"].get("workflow_dispatch", 0), b["runs"]),
        # The verdict that stands TODAY. A later green run supersedes earlier
        # red ones — without this the queue cannot tell a workflow that is
        # broken from one that was fixed fifteen minutes later.
        "last_conclusion": b["last_conclusion"],
        "last_run_at": b["last_at"],
        "events": b["events"],
    }


def build_report(registry: list[dict], gh, days: int, max_runs: int) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=days)
    weeks = max(days / 7.0, 1 / 7.0)

    workflows: list[dict] = []
    inactive: list[dict] = []
    by_type: dict[str, dict] = {}
    by_repo: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    scanned = 0

    for project in registry:
        nwo = owner_repo(project.get("repo_url", ""))
        if not nwo:
            continue
        sys.stderr.write(f"  · {nwo}\n")
        wf_meta, records = collect_repo(gh, nwo, window_start, max_runs)
        scanned += 1
        name = project["name"]
        repo_url = project.get("repo_url")
        # External mirrors (upstream not bamr87, e.g. microsoft/skills) stay
        # visible per-workflow but are excluded from fleet KPIs and triage:
        # their spend isn't ours to optimize and their "failures" can be
        # by-design signals (see bamr87/bamr87#24).
        external = not nwo.startswith("bamr87/")

        # per-workflow buckets for this repo
        wf_buckets: dict[int, dict] = {}
        for rec in records:
            wid = rec["workflow_id"]
            b = wf_buckets.setdefault(wid, new_bucket())
            b["_name"] = rec["name"]
            b["_path"] = rec["path"]
            fold(b, rec)
            wtype = classify_type(rec["name"], rec["path"])
            # roll up type / repo / day — bamr87-owned repos only
            if external:
                continue
            for agg, key in ((by_type, wtype), (by_repo, name), (by_day, rec["day"])):
                if key is None:
                    continue
                fold(agg.setdefault(key, new_bucket()), rec)

        for wid, b in wf_buckets.items():
            workflows.append(workflow_record(b, repo=name, repo_url=repo_url,
                                             external=external, weeks=weeks))

        # workflows that exist but never ran in the window (dead weight)
        ran = set(wf_buckets)
        for wid, meta in wf_meta.items():
            if wid not in ran and not meta["path"].startswith("dynamic/"):
                inactive.append({"repo": name, "workflow": meta["name"],
                                 "path": meta["path"], "state": meta["state"]})

    return finalize(workflows, inactive, by_type, by_repo, by_day, days, scanned, now)


def summarize(bucket: dict) -> dict:
    return {
        "runs": bucket["runs"],
        "total_min": round(bucket["total_min"], 1),
        "waste_min": round(bucket["waste_min"], 1),
        "effectiveness_pct": pct(bucket["success_min"], bucket["total_min"]) if bucket["total_min"] else 100.0,
        # Cancelled excluded from the denominator — see the per-workflow record.
        "success_rate_pct": pct(bucket["success"], bucket["success"] + bucket["failure"]),
    }


def finalize(workflows, inactive, by_type, by_repo, by_day, days, scanned, now) -> dict:
    owned = [w for w in workflows if not w.get("external")]
    grand_min = sum(w["total_min"] for w in owned) or 1.0
    median_min = statistics.median([w["total_min"] for w in owned]) if owned else 0.0

    # optimization flags per workflow (external mirrors: visible, never flagged)
    for w in workflows:
        if w.get("external"):
            w["flags"] = []
            w["priority"] = 0.0
            continue
        flags = []
        completed = w["success"] + w["failure"] + w["cancelled"]
        # Runs that actually reached a verdict. failing/flaky gate on THIS, not
        # on `completed`: a workflow whose runs are merely superseded has no
        # verdicts at all, and pct(0, 0) == 0.0 would otherwise read as "0%
        # success" and flag it `failing` despite zero failures.
        decided = w["success"] + w["failure"]
        eff = w["effectiveness_pct"]
        if (eff is not None and w["total_min"] >= median_min
                and eff < LOW_EFFECTIVENESS and w["waste_min"] >= MIN_WASTE_MIN):
            flags.append("high-cost-low-value")
        if decided >= 3 and w["success_rate_pct"] < 50:
            flags.append("failing")
        elif decided >= 4 and 50 <= w["success_rate_pct"] < 85:
            flags.append("flaky")
        if w["avg_min"] > SLOW_AVG_MIN:
            flags.append("slow")
        if completed >= 4 and pct(w["cancelled"], completed) > CANCEL_HEAVY_PCT:
            flags.append("cancel-heavy")
        if w["runs"] >= 5 and w["sched_pct"] > CRON_HEAVY_PCT:
            flags.append("cron-heavy")
        w["flags"] = flags
        # priority: minutes wasted, then raw consumption — the "high running, low effective" rank.
        # With no verdicts there is no effectiveness to discount by, so only the
        # minutes actually burned (cancelled runs) count.
        w["priority"] = round(
            w["waste_min"] + w["total_min"] * (1 - (eff if eff is not None else 100.0) / 100), 1)

    workflows.sort(key=lambda w: (w["priority"], w["total_min"]), reverse=True)

    def rows(agg, keyname):
        out = []
        for key, b in agg.items():
            s = summarize(b)
            s[keyname] = key
            s["share_pct"] = round(100 * b["total_min"] / grand_min, 1)
            out.append(s)
        out.sort(key=lambda r: r["total_min"], reverse=True)
        return out

    type_rows = rows(by_type, "type")
    repo_rows = rows(by_repo, "repo")
    day_rows = sorted(
        ({"date": d, **summarize(b)} for d, b in by_day.items() if d),
        key=lambda r: r["date"],
    )

    # Every fleet total is summed over `owned` — the SAME population as
    # `grand_min` above, as `share_pct`, and as the optimization flags. Summing
    # waste over all workflows while the denominator excluded external mirrors
    # published `waste_min: 45211.1` against `total_min: 37119.3` — a share
    # larger than its whole, rendering as -21.8% effective (bamr87/bamr87#204).
    # 10,796.9m of that came from mirrors whose spend is not ours to optimize.
    tot_runs = sum(w["runs"] for w in owned)
    tot_success = sum(w["success"] for w in owned)
    # Failures only — cancelled runs reached no verdict and are excluded from
    # the success rate, matching the per-workflow record. Their minutes are not
    # in waste_min either; they are never priced.
    tot_fail = sum(w["failure"] for w in owned)
    tot_waste = round(sum(w["waste_min"] for w in owned), 1)

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": days,
        "repos_scanned": scanned,
        "totals": {
            "runs": tot_runs,
            # A row count of the drill-down table below, which lists external
            # mirrors too — not a consumption aggregate, so it is deliberately
            # the one entry here spanning both populations.
            "workflows": len(workflows),
            "repos_with_activity": len(by_repo),
            "total_min": round(grand_min, 1),
            "total_hours": round(grand_min / 60, 1),
            "waste_min": tot_waste,
            "waste_hours": round(tot_waste / 60, 1),
            "effectiveness_pct": round(100 * (grand_min - tot_waste) / grand_min, 1),
            "success_rate_pct": pct(tot_success, tot_success + tot_fail),
        },
        "by_type": type_rows,
        "by_repo": repo_rows,
        "by_day": day_rows,
        "workflows": workflows,
        "inactive": sorted(inactive, key=lambda x: (x["repo"], x["workflow"])),
        "note": ("Cost = wall-clock run minutes (run_started_at → updated_at) of runs that "
                 "actually executed. Cancelled runs are counted but NOT priced: their span "
                 "is however long they waited to start, and GitHub bills none of it. "
                 "Value = share of minutes ending in success. "
                 "Waste = minutes on failed/timed-out runs. "
                 "Success rate counts only runs that reached a verdict "
                 "(success + failure); cancelled runs were superseded, not broken, "
                 "and show up as cancel_pct / the cancel-heavy flag instead. "
                 "A workflow with NO verdicts in the window (every run skipped) "
                 "reports null rates — 'no data', not 0%. "
                 "Fleet totals cover bamr87-owned workflows only; external mirrors are "
                 "listed per-workflow but excluded from every aggregate."),
    }


# --------------------------------------------------------------------------- #
# terminal report
# --------------------------------------------------------------------------- #
BAR = "▓"


def print_report(rep: dict) -> None:
    t = rep["totals"]
    w = sys.stderr.write
    w(f"\nGitHub Actions usage — last {rep['window_days']}d "
      f"({rep['repos_scanned']} repos scanned, {t['workflows']} workflows)\n")
    w(f"  {t['runs']} runs · {t['total_hours']}h consumed · "
      f"{t['success_rate_pct']}% success · {t['waste_hours']}h wasted "
      f"({100 - t['effectiveness_pct']:.0f}% of minutes)\n\n")

    w("Consumption by workflow type:\n")
    maxmin = max((r["total_min"] for r in rep["by_type"]), default=1)
    for r in rep["by_type"]:
        bar = BAR * max(1, int(round(20 * r["total_min"] / maxmin)))
        w(f"  {r['type']:<13} {r['total_min']:>7.0f}m  {r['effectiveness_pct']:>4.0f}% eff  "
          f"{r['share_pct']:>4.0f}%  {bar}\n")

    w("\nTop optimization targets (high running, low effective):\n")
    for x in rep["workflows"][:12]:
        if x["priority"] <= 0:
            break
        flags = f"  [{', '.join(x['flags'])}]" if x["flags"] else ""
        eff = ("  — eff" if x["effectiveness_pct"] is None
               else f"{x['effectiveness_pct']:>3.0f}% eff")
        w(f"  {x['repo']}/{x['workflow']}\n"
          f"      {x['total_min']:>6.0f}m  {eff}  "
          f"{x['runs']:>3} runs  {x['waste_min']:>5.0f}m wasted{flags}\n")
    if rep["inactive"]:
        w(f"\n{len(rep['inactive'])} workflow(s) defined but idle this window "
          f"(candidates to prune): "
          + ", ".join(f"{i['repo']}/{i['workflow']}" for i in rep["inactive"][:6])
          + (" …\n" if len(rep["inactive"]) > 6 else "\n"))


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    try:
        from github import Github, Auth
    except ImportError:
        sys.stderr.write("actions_analytics requires PyGithub: pip install PyGithub\n")
        return 2

    token = resolve_token()
    if not token:
        sys.stderr.write("No GitHub token (set GH_TOKEN/GITHUB_TOKEN or run `gh auth login`).\n")
        return 2

    with REGISTRY.open() as fh:
        registry = yaml.safe_load(fh) or []

    gh = Github(auth=Auth.Token(token), per_page=100)
    sys.stderr.write(f"Scanning Actions usage for {len(registry)} repos (last {args.days}d)…\n")
    report = build_report(registry, gh, args.days, args.max_runs)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("# GENERATED by .github/scripts/dash-gen (actions_analytics) — "
                 "refreshed daily by fleet-pulse.yml. Edit the generator, not this file.\n")
        yaml.safe_dump(report, fh, sort_keys=False, allow_unicode=True)
    sys.stderr.write(f"Wrote {out}\n")

    if args.print or not args.quiet:
        print_report(report)
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--days", type=int, default=14, metavar="N",
                        help="window in days to analyze (default 14)")
    parser.add_argument("--max-runs", type=int, default=1000, metavar="N",
                        help="cap runs fetched per repo (default 1000)")
    parser.add_argument("--out", default=str(OUT_DEFAULT), metavar="PATH",
                        help="output data file (default _data/actions_usage.yml)")
    parser.add_argument("--print", action="store_true", help="print the terminal report")
    parser.add_argument("--quiet", action="store_true", help="suppress the terminal report")
    parser.set_defaults(func=run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="actions-analytics", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

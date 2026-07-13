#!/usr/bin/env python3
"""
actions_analytics — GitHub Actions usage analytics for the bamr87 dash.

Queries the GitHub Actions API (via the PyGithub integration library) for every
repo in the registry, aggregates workflow-run consumption, and writes a
COMMITTED data file (_data/actions_usage.yml) that the Jekyll dash renders. Unlike
the health/ai generators (ephemeral, gitignored), this file is persisted and
refreshed on a daily schedule (.github/workflows/actions-usage.yml) so the page
shows a stable, once-a-day snapshot.

The engine answers: where do Actions minutes go, and which workflows run a lot
while producing little? It groups consumption by workflow *type* and surfaces
"high running, low effective" workflows quantitatively (cost = wall-clock minutes,
value = share of minutes that end in success; waste = minutes on non-success runs).

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
WASTE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure"}

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
            })
    except GithubException:
        pass
    return wf_meta, records


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def new_bucket() -> dict:
    return {"runs": 0, "total_min": 0.0, "success_min": 0.0, "waste_min": 0.0,
            "success": 0, "failure": 0, "cancelled": 0, "other": 0,
            "durations": [], "events": {}}


def fold(bucket: dict, rec: dict) -> None:
    m = rec["minutes"]
    c = rec["conclusion"]
    bucket["runs"] += 1
    bucket["total_min"] += m
    bucket["durations"].append(m)
    bucket["events"][rec["event"]] = bucket["events"].get(rec["event"], 0) + 1
    if c == "success":
        bucket["success_min"] += m
        bucket["success"] += 1
    elif c in WASTE_CONCLUSIONS:
        bucket["waste_min"] += m
        if c == "cancelled":
            bucket["cancelled"] += 1
        else:
            bucket["failure"] += 1
    else:
        bucket["other"] += 1


def pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return round(s[idx], 2)


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

        # per-workflow buckets for this repo
        wf_buckets: dict[int, dict] = {}
        for rec in records:
            wid = rec["workflow_id"]
            b = wf_buckets.setdefault(wid, new_bucket())
            b["_name"] = rec["name"]
            b["_path"] = rec["path"]
            fold(b, rec)
            wtype = classify_type(rec["name"], rec["path"])
            # roll up type / repo / day
            for agg, key in ((by_type, wtype), (by_repo, name), (by_day, rec["day"])):
                if key is None:
                    continue
                fold(agg.setdefault(key, new_bucket()), rec)

        for wid, b in wf_buckets.items():
            wtype = classify_type(b["_name"], b["_path"])
            sched = b["events"].get("schedule", 0)
            workflows.append({
                "repo": name, "repo_url": repo_url,
                "workflow": b["_name"], "type": wtype, "path": b["_path"],
                "runs": b["runs"],
                "total_min": round(b["total_min"], 1),
                "avg_min": round(b["total_min"] / b["runs"], 2) if b["runs"] else 0.0,
                "p95_min": p95(b["durations"]),
                "waste_min": round(b["waste_min"], 1),
                "runs_per_week": round(b["runs"] / weeks, 1),
                "success": b["success"], "failure": b["failure"], "cancelled": b["cancelled"],
                "success_rate_pct": pct(b["success"], b["success"] + b["failure"] + b["cancelled"]),
                "effectiveness_pct": pct(b["success_min"], b["total_min"]) if b["total_min"] else 100.0,
                "sched_pct": pct(sched, b["runs"]),
                "events": b["events"],
            })

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
        "success_rate_pct": pct(bucket["success"], bucket["success"] + bucket["failure"] + bucket["cancelled"]),
    }


def finalize(workflows, inactive, by_type, by_repo, by_day, days, scanned, now) -> dict:
    grand_min = sum(w["total_min"] for w in workflows) or 1.0
    median_min = statistics.median([w["total_min"] for w in workflows]) if workflows else 0.0

    # optimization flags per workflow
    for w in workflows:
        flags = []
        completed = w["success"] + w["failure"] + w["cancelled"]
        if (w["total_min"] >= median_min and w["effectiveness_pct"] < LOW_EFFECTIVENESS
                and w["waste_min"] >= MIN_WASTE_MIN):
            flags.append("high-cost-low-value")
        if completed >= 3 and w["success_rate_pct"] < 50:
            flags.append("failing")
        elif completed >= 4 and 50 <= w["success_rate_pct"] < 85:
            flags.append("flaky")
        if w["avg_min"] > SLOW_AVG_MIN:
            flags.append("slow")
        if completed >= 4 and pct(w["cancelled"], completed) > CANCEL_HEAVY_PCT:
            flags.append("cancel-heavy")
        if w["runs"] >= 5 and w["sched_pct"] > CRON_HEAVY_PCT:
            flags.append("cron-heavy")
        w["flags"] = flags
        # priority: minutes wasted, then raw consumption — the "high running, low effective" rank
        w["priority"] = round(w["waste_min"] + w["total_min"] * (1 - w["effectiveness_pct"] / 100), 1)

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

    tot_runs = sum(w["runs"] for w in workflows)
    tot_success = sum(w["success"] for w in workflows)
    tot_fail = sum(w["failure"] + w["cancelled"] for w in workflows)
    tot_waste = round(sum(w["waste_min"] for w in workflows), 1)

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": days,
        "repos_scanned": scanned,
        "totals": {
            "runs": tot_runs,
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
        "note": ("Cost = wall-clock run minutes (run_started_at → updated_at), a proxy for "
                 "billable minutes. Value = share of minutes ending in success. "
                 "Waste = minutes on failed/cancelled/timed-out runs."),
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
        w(f"  {x['repo']}/{x['workflow']}\n"
          f"      {x['total_min']:>6.0f}m  {x['effectiveness_pct']:>3.0f}% eff  "
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
                 "refreshed daily by actions-usage.yml. Edit the generator, not this file.\n")
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

#!/usr/bin/env python3
"""
actions_analytics — GitHub Actions usage analytics for the bamr87 dash.

Reads the GitHub Actions REST API (through PyGithub's requester) for every repo
in the registry AND the hub itself, aggregates workflow-run consumption, and
writes a COMMITTED data file (_data/actions_usage.yml) that the console, the
TUI, the MCP tools and `harness.py` read. Unlike the health/ai generators
(ephemeral, gitignored), this file is persisted and refreshed on a daily
schedule (.github/workflows/fleet-pulse.yml) so the page shows a stable,
once-a-day snapshot.

The engine answers: where do Actions minutes go, and which workflows run a lot
while producing little? It groups consumption by workflow *type* and surfaces
"high running, low effective" workflows quantitatively (cost = job-minutes,
value = share of minutes that end in success; waste = minutes on non-success
runs).

Schema `actions-usage/v2` (2026-11-07, epic #773 / E1 #775) — four corrections,
each measured against the billing meter before it was made:

* **The hub is collected.** `_data/projects.yml` lists the submodules; the
  control plane is `_data/fleet.yml` `hub.repo`, and leaving it out hid ~7,900
  of ~12,050 billed minutes on 2026-11-01..07.
* **No silent cap.** A repo's window is listed by `created` date range, split
  in half whenever a range reaches GitHub's 1,000-result listing cap, so
  zer0-CMS's 760 runs are 760 runs, not the first 600. A cap that still bites
  (`--max-runs`, an API error) is published per repo as `truncated: true` with
  `runs_missed`.
* **Cost is job-minutes.** GitHub bills each JOB, rounded up to a whole minute;
  skipped jobs and jobs that never reached a runner bill nothing. Run wall clock
  under-counted 2-4x (zer0-mistakes ci.yml: 1,125 job-minutes over 92 runs
  against 523 wall-clock over the 49 the old cap let through). `total_min`,
  `avg_min`, `p95_min`, `waste_min` and `cancel_min` are job-minutes; the
  bounded wall clock is kept beside them as `wall_min` / `wall_avg_min` /
  `wall_p95_min`, which is what the `slow` flag (latency, not cost) reads.
* **The meter is account-level.** The billing usage API files the account's
  whole total under one repository name (lifehacker.dev 43,924 of 44,563 in
  October; bamr87 11,920 of 11,925 in November), so `billing` publishes it as
  `account_total_filed_under_*`, never as per-repo shares, and the `parity`
  block sets the analytics total against the meter's account total.

The API budget. Job-minutes need one jobs request per run, about 5,000+ per
14-day window fleet-wide, against one 5,000/hour token the fleet's own runs
share. So the job fetch is incremental and capped:

* a completed run's job-minutes never change, so they are cached per
  (repo, run id, attempt) in `.dash-lake/actions_jobs_cache.json` (fleet-pulse
  restores and saves it with actions/cache); only runs new since the last
  sweep cost a request;
* runs that cannot have billed (`skipped`, `startup_failure`,
  `action_required`) cost none;
* the remaining fetches stop at `--max-job-calls`, and at the token's
  remaining quota minus `--api-reserve` for the steps that run after this one.
  Beyond that the run is ESTIMATED from its bounded wall clock times the
  measured job/wall ratio of its workflow (else repo, else fleet), and every
  row that holds an estimate says `sampled: true`.

The jobs endpoint, not the per-run `/timing` one: on a public repo `/timing`
reports `billable.*.total_ms: 0` for every job (run 42352285943), and it is the
legacy usage endpoint GitHub is closing down. The jobs list costs the same one
request and carries each job's runner, conclusion and timestamps.

The wall-clock proxy keeps its bounds (bamr87/bamr87#229): a run that never
reached a runner (`startup_failure`, or no billed job) contributes ZERO wall
minutes, and every other run is clamped to MAX_RUN_MIN. Such runs still count
toward `success_rate_pct` and the failing flag; only their minutes are zeroed.

The fleet `totals` are computed over bamr87-owned workflows only — the same
population as the by_type / by_repo / by_day rollups. Mixing the two populations
across a ratio's halves is how this file once published more waste than
consumption, and a negative effectiveness. External mirrors never enter them.

Cancelled runs are counted as waste (the minutes were really burned) but NOT as
failures: `success_rate_pct` and the failing/flaky flags look only at runs that
reached a verdict. Conflating the two made every workflow with a working
`concurrency: cancel-in-progress` guard read as broken.

The `cancel-heavy` flag needs the same distinction one level further in, on the
MINUTES rather than the counts. A concurrency guard doing its job and genuine
churn are indistinguishable by cancelled SHARE — both cancel most of their runs
— and are opposites by cancelled COST. GitHub holds at most one pending run per
group, so a supersession is cancelled seconds after creation having never
started a job; a burst of 12 pushes collapsing into 1 real run costs ~3 min and
SAVES ~16. Flagging that told the fleet-doctor to go "fix" three workflows whose
guards were correct. So the flag now also requires the cancelled minutes to be
material, both absolutely and against what a real run of that workflow costs.

For the same reason a workflow with NO verdicts in the window — every run
skipped by an `if:` gate — reports `success_rate_pct` / `effectiveness_pct` as
`None`, not `0.0`: "no data" and "failed every run" are different states and
must not render identically.

Auth: a token from GH_TOKEN / GITHUB_TOKEN, else `gh auth token`. Network / rate
-limit failures degrade gracefully (a repo that can't be read is reported, not fatal).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
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
FLEET = REPO_ROOT / "_data" / "fleet.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "actions_usage.yml"
LAKE_DIR = Path(os.environ.get("DASH_LAKE_DIR") or (REPO_ROOT / ".dash-lake"))
CACHE_DEFAULT = LAKE_DIR / "actions_jobs_cache.json"

# The snapshot's schema marker. v1 (unmarked) priced runs by wall clock and
# filed the meter under `by_repo_*`; v2 prices job-minutes and keeps the wall
# clock as `wall_*`, relabels the meter as account-level, and adds
# `coverage` + `parity`. Consumers read fields with .get(), so v1 snapshots
# still load; `remediation.is_long_running` falls back to avg_min on v1.
SCHEMA = "actions-usage/v2"
MINUTES_BASIS = "job-minutes"

# Thresholds for the optimization flags (tunable).
SLOW_AVG_MIN = 12.0        # a run averaging longer than this (WALL clock) is "slow"
LOW_EFFECTIVENESS = 55     # < this % of minutes ending in success is "low value"
CANCEL_HEAVY_PCT = 25      # cancelled share above this is "cancel-heavy"
CRON_HEAVY_PCT = 60        # scheduled share above this is "cron-heavy"
MIN_WASTE_MIN = 4.0        # ignore trivial waste below this when flagging

# Cost gate on `cancel-heavy`, applied on top of CANCEL_HEAVY_PCT. A cancelled
# run must have burned a real share of a real run before its SHARE is allowed to
# mean anything: supersessions die in seconds, so they clear neither test, while
# a 20-minute build killed half-done clears both. Both halves are needed — the
# ratio alone would flag a cheap workflow whose every run is cancelled at 60% of
# its (tiny) average, and the absolute floor alone would flag a very busy one
# accumulating minutes a few seconds at a time.
CANCEL_MIN_WASTE_MIN = 4.0   # cancelled minutes below this are never "heavy"
CANCEL_COST_RATIO = 0.5      # cancelled runs must average >= this share of avg_min

# Non-success terminal conclusions whose minutes count as waste.
WASTE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure"}

# Conclusions of a run that cannot have billed a job, so its job-minutes are a
# known 0 without a request: every job skipped by its `if:`, a workflow file
# that never loaded, a run parked for approval.
NO_JOB_CONCLUSIONS = {"skipped", "startup_failure", "action_required"}

# Ceiling on the wall-clock proxy, in minutes. GitHub's own per-job limit is
# 6h, so a *run* reporting more than this is dominated by time it spent parked in
# a non-terminal state rather than by time it spent on a runner. Clamping here is
# a backstop for the runs whose job list was not read (bamr87/bamr87#229).
MAX_RUN_MIN = 360.0
AVG_DAYS_PER_MONTH = 30.44
# GitHub's enhanced-billing usage endpoint: the account's METERED Actions
# minutes, per month, in one request. It is the only number here that is not
# derived from the run list — see collect_billing().
BILLING_ENDPOINT = "/users/{login}/settings/billing/usage"

# Wall clock above which a NON-SUCCESS run is fetched FIRST when the job budget
# is short. GitHub resolves a run that dispatched no job as a plain `failure`
# tens of minutes after creating it, and every one of those minutes is elapsed
# time nothing billed; the job list is what proves it, so these runs are never
# the ones left to the estimator.
SUSPECT_RUN_MIN = 15.0

# Listing. A `created`-filtered run listing returns at most 1,000 results, and
# its `total_count` saturates (2,500 for the hub's 14 days, which held 2,994),
# so a range at or above the cap is split in half until each half is under it.
LIST_CAP = 1000
MIN_SPLIT_SECONDS = 600     # a 10-minute range at the cap is reported truncated, not split

# The job fetch's API ceiling: requests per sweep (--max-job-calls), and the
# share of the token's remaining hourly quota left for the steps after this one
# (--api-reserve). The quota is shared with every workflow the token runs.
JOB_CALL_CEILING = 1500
API_RESERVE = 1000

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


def hub_entry(fleet_path: Path = FLEET) -> dict | None:
    """The hub as a pseudo-registry row.

    `_data/projects.yml` lists the SUBMODULES; the control plane itself is
    declared in `_data/fleet.yml` `hub.repo`. Every Actions number used to be
    computed without it — the hub's own CI, fleet-pulse, the issue pipeline and
    the fan-outs, ~7,900 of ~12,050 billed minutes on 2026-11-01..07 — and the
    AI ledger missed the loops with the largest caps in `budget.call_sites`.
    """
    try:
        cfg = yaml.safe_load(fleet_path.read_text()) or {}
        nwo = (cfg.get("hub") or {}).get("repo")
    except Exception:
        nwo = None
    if not nwo:
        return None
    return {"name": str(nwo).split("/")[-1], "repo_url": f"https://github.com/{nwo}",
            "category": "harness"}


def with_hub(registry: list[dict], fleet_path: Path = FLEET) -> list[dict]:
    """The registry with the hub first, unless the registry already lists it."""
    hub = hub_entry(fleet_path)
    if not hub:
        return list(registry)
    known = {owner_repo(p.get("repo_url", "")) for p in registry}
    if owner_repo(hub["repo_url"]) in known:
        return list(registry)
    return [hub, *registry]


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


def parse_ts(value) -> dt.datetime | None:
    """An API timestamp (ISO-8601 string or datetime) as an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return as_utc(value)
    try:
        return as_utc(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def iso_z(value: dt.datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_wall_min(run: dict) -> float | None:
    """Raw wall clock for one run (a REST run dict). The ELAPSED time, not the cost."""
    start = parse_ts(run.get("run_started_at")) or parse_ts(run.get("created_at"))
    end = parse_ts(run.get("updated_at"))
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds() / 60.0)


def wall_cost_min(conclusion: str | None, dur: float, billed_jobs: int | None) -> float:
    """The bounded wall-clock proxy for one run — the SECONDARY measure since v2.

    Wall clock over-reports in exactly one direction: a run that never reached a
    runner still accrues elapsed time it never billed. GitHub left run
    33362222262 non-terminal for 68 HOURS against an empty `billable` map —
    4079.9 phantom minutes, 99.2% of that workflow's entire reported spend
    (bamr87/bamr87#229). In bamr87/zer0-mistakes six jobless `failure` runs of
    markdown-oneline sat between 5 and 297 minutes, 97.5% of that workflow's
    reported minutes. So:

    * a run that never executed costs **0** — `startup_failure`, or a job list
      that shows no billed job (`billed_jobs == 0`);
    * everything else is clamped to MAX_RUN_MIN, bounding the runs whose job
      list was not read (`billed_jobs is None`).

    Only the MINUTES are zeroed. The run still counts toward `success_rate_pct`
    and the `failing` flag — a startup failure genuinely is red, and suppressing
    it there would trade a cost bug for a correctness one.
    """
    if (conclusion or "") == "startup_failure" or billed_jobs == 0:
        return 0.0
    return min(dur, MAX_RUN_MIN)


def job_minutes(jobs: list[dict]) -> dict:
    """Per-job rounded minutes, the way GitHub bills a run.

    Each job that ran on a GitHub-hosted runner counts its own duration rounded
    UP to a whole minute. A `skipped` job, a job that never reached a runner (a
    cancelled `needs:` dependant: no runner, start == end) and a self-hosted job
    bill nothing. The list should come from `filter=all`, so every attempt of a
    re-run is billed, as GitHub bills it.
    """
    billed = skipped = self_hosted = 0
    minutes = 0
    for job in jobs or []:
        if (job.get("conclusion") or "") == "skipped":
            skipped += 1
            continue
        start, end = parse_ts(job.get("started_at")), parse_ts(job.get("completed_at"))
        if not start or not end:
            continue
        secs = (end - start).total_seconds()
        if secs <= 0 or not (job.get("runner_id") or job.get("runner_name")):
            continue
        if "self-hosted" in (job.get("labels") or []):
            self_hosted += 1
            continue
        billed += 1
        minutes += math.ceil(secs / 60.0)
    return {"job_min": minutes, "jobs": len(jobs or []), "billed_jobs": billed,
            "skipped_jobs": skipped, "self_hosted_jobs": self_hosted}


# --------------------------------------------------------------------------- #
# the REST surface: every request this module makes, counted
# --------------------------------------------------------------------------- #
def requester_of(gh):
    return getattr(gh, "requester", None) or getattr(gh, "_Github__requester")


class RestApi:
    """The few REST reads this module makes, counted per kind.

    Raw JSON rather than PyGithub objects: the run dicts are cached, fixtures
    are plain data, and the call count — the thing the fleet's quota cares
    about — is exact.
    """

    def __init__(self, requester) -> None:
        self._r = requester
        self.calls: collections.Counter = collections.Counter()

    def get(self, path: str, params: dict | None = None, kind: str = "other") -> dict:
        self.calls[kind] += 1
        _, data = self._r.requestJsonAndCheck("GET", path, parameters=params)
        return data or {}

    def core_remaining(self) -> int | None:
        """The token's remaining core quota. `/rate_limit` is free (GitHub does
        not count it), so it is not counted here either."""
        try:
            _, data = self._r.requestJsonAndCheck("GET", "/rate_limit")
            return int(data["resources"]["core"]["remaining"])
        except Exception:
            return None


def list_workflows(api, nwo: str) -> dict[int, dict]:
    meta: dict[int, dict] = {}
    page = 1
    try:
        while True:
            data = api.get(f"/repos/{nwo}/actions/workflows", {"per_page": 100, "page": page},
                           kind="workflows")
            batch = data.get("workflows") or []
            for wf in batch:
                meta[wf["id"]] = {"name": wf.get("name"), "path": wf.get("path") or "",
                                  "state": wf.get("state")}
            if len(batch) < 100 or len(meta) >= int(data.get("total_count") or 0):
                break
            page += 1
    except Exception:
        pass
    return meta


def list_window_runs(api, nwo: str, start: dt.datetime, end: dt.datetime,
                     max_runs: int = 0) -> dict:
    """Every run CREATED in [start, end], paged by date range — no silent cap.

    A `created`-filtered listing returns at most LIST_CAP results and its
    `total_count` saturates, so a range at or above the cap is split in half
    (newest half first) until each piece is under it. What still cannot be
    listed — a `max_runs` cap, an API error, a 10-minute range with 1,000 runs
    in it — is REPORTED: `truncated: true` and `runs_missed` (GitHub's count
    minus what was listed; a range that errored before its count is known
    makes `runs_missed` a lower bound, `error` says which).
    """
    out = {"runs": [], "in_window": 0, "truncated": False, "runs_missed": 0, "error": None}
    seen: set[int] = set()
    stack = [(as_utc(start), as_utc(end))]
    while stack:
        a, b = stack.pop()
        capped = bool(max_runs) and len(out["runs"]) >= max_runs
        params = {"created": f"{iso_z(a)}..{iso_z(b)}", "per_page": 1 if capped else 100, "page": 1}
        try:
            first = api.get(f"/repos/{nwo}/actions/runs", params, kind="list")
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            out["truncated"] = True
            out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            continue
        total = int(first.get("total_count") or 0)
        if total >= LIST_CAP and (b - a).total_seconds() > MIN_SPLIT_SECONDS:
            mid = a + (b - a) / 2
            mid = mid.replace(microsecond=0)
            stack.append((a, mid))                                  # older half: popped second
            stack.append((mid + dt.timedelta(seconds=1), b))        # newer half: popped first
            continue
        out["in_window"] += total
        got = [] if capped else list(first.get("workflow_runs") or [])
        page = 1
        batch = got
        while (batch and len(got) < min(total, LIST_CAP) and len(batch) == 100
               and not (max_runs and len(out["runs"]) + len(got) >= max_runs)):
            page += 1
            try:
                data = api.get(f"/repos/{nwo}/actions/runs",
                               {**params, "per_page": 100, "page": page}, kind="list")
            except Exception as exc:  # noqa: BLE001
                out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                break
            batch = data.get("workflow_runs") or []
            got += batch
        if max_runs:
            got = got[: max(0, max_runs - len(out["runs"]))]
        for run in got:
            if run.get("id") not in seen:
                seen.add(run.get("id"))
                out["runs"].append(run)
        if total > len(got):
            out["truncated"] = True
            out["runs_missed"] += total - len(got)
    return out


def fetch_jobs(api, nwo: str, run_id: int) -> list[dict]:
    """Every job of every attempt of one run (`filter=all`), paged."""
    jobs: list[dict] = []
    page = 1
    while True:
        data = api.get(f"/repos/{nwo}/actions/runs/{run_id}/jobs",
                       {"filter": "all", "per_page": 100, "page": page}, kind="jobs")
        batch = data.get("jobs") or []
        jobs += batch
        if len(batch) < 100 or len(jobs) >= int(data.get("total_count") or 0):
            return jobs
        page += 1


# --------------------------------------------------------------------------- #
# the per-run job-minute cache
# --------------------------------------------------------------------------- #
class JobCache:
    """Job-minutes of COMPLETED runs, keyed by repo, run id and attempt.

    A completed run's jobs never change (a re-run is a new attempt, so a new
    key), so yesterday's sweep pays for today's: only runs new since the last
    sweep cost a request. Ephemeral — `.dash-lake/` locally, actions/cache in
    fleet-pulse — because losing it costs one sampled day, never a wrong number.
    """

    MARKER = "actions-jobs-cache/v1"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.runs: dict[str, dict] = {}
        self.loaded = 0
        self.error: str | None = None
        if path and Path(path).exists():
            try:
                doc = json.loads(Path(path).read_text())
                if isinstance(doc, dict) and doc.get("schema") == self.MARKER:
                    self.runs = {k: v for k, v in (doc.get("runs") or {}).items()
                                 if isinstance(v, dict)}
                self.loaded = len(self.runs)
            except Exception as exc:  # noqa: BLE001 - a bad cache is an empty cache
                self.error = f"{type(exc).__name__}: {str(exc)[:120]}"

    @staticmethod
    def key(nwo: str, run: dict) -> str:
        return f"{nwo}#{run.get('id')}#{run.get('run_attempt') or 1}"

    def get(self, key: str) -> dict | None:
        return self.runs.get(key)

    def put(self, key: str, value: dict) -> None:
        self.runs[key] = value

    def save(self, prune_before: dt.datetime | None = None) -> int:
        """Write the cache (dropping runs created before `prune_before`); returns
        the entries kept. A cache with no path is in-memory only."""
        if prune_before is not None:
            cut = iso_z(prune_before)
            self.runs = {k: v for k, v in self.runs.items() if str(v.get("created_at") or "") >= cut}
        if not self.path:
            return len(self.runs)
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"schema": self.MARKER, "runs": self.runs},
                                  separators=(",", ":"), sort_keys=True))
        tmp.replace(path)
        return len(self.runs)


# --------------------------------------------------------------------------- #
# the GitHub billing meter
# --------------------------------------------------------------------------- #
def summarize_billing(items: list, today: dt.date) -> dict:
    """Fold billing usage items into what the harness budget wire reads.

    The run list can RANK workflows but it is not the bill: an external
    mirror's CI (tt-a1i/archify, 25% of the 2026-09 "fleet" minutes) is not this
    account's spend at all, and the meter counts repos the registry does not
    list. So GitHub's own meter — not the analytics — is what `harnesses.budget`
    is judged against, and `parity` reports how far the two disagree.
    Public-repo minutes are free (netAmount 0) but still metered, which is
    exactly right: load, not dollars, is what the ceiling bounds.

    The meter is ACCOUNT-level. It files the account's minutes under whichever
    repository names it chooses — 43,924 of October's 44,563 under
    lifehacker.dev, 11,920 of November's first 11,925 under bamr87 — so those
    names are published as `account_total_filed_under_*`, never as per-repo
    shares.

    Projection: this month's run-rate once a week of it exists, otherwise the
    last full month (a 3-day run-rate is noise). The consumer applies that rule
    from the fields below so the choice is visible in the data.
    """
    months: dict[str, dict] = {}
    filed: dict[str, dict[str, float]] = {}
    for it in items or []:
        if it.get("product") != "actions" or it.get("unitType") != "Minutes":
            continue
        month = str(it.get("date") or "")[:7]
        if len(month) != 7:
            continue
        b = months.setdefault(month, {"minutes": 0.0, "gross_usd": 0.0, "net_usd": 0.0})
        q = float(it.get("quantity") or 0)
        b["minutes"] += q
        b["gross_usd"] += float(it.get("grossAmount") or 0)
        b["net_usd"] += float(it.get("netAmount") or 0)
        repo = it.get("repositoryName") or "(account)"
        filed.setdefault(month, {})[repo] = filed.setdefault(month, {}).get(repo, 0.0) + q
    this_month = today.strftime("%Y-%m")
    previous = max((m for m in months if m < this_month), default=None)
    cur = months.get(this_month, {}).get("minutes", 0.0)
    elapsed = today.day

    def by_name(month):
        return dict(sorted(filed.get(month, {}).items(), key=lambda kv: -kv[1])) if month else {}

    return {
        "source": "GitHub billing usage API (" + BILLING_ENDPOINT + ")",
        "scope": "account",
        "fetched_at": today.isoformat(),
        "this_month": this_month,
        "days_elapsed": elapsed,
        "minutes_this_month": round(cur, 1),
        "run_rate_monthly": round(cur / elapsed * AVG_DAYS_PER_MONTH, 1) if elapsed else None,
        "previous_month": previous,
        "minutes_previous_month": round(months[previous]["minutes"], 1) if previous else None,
        "months": {m: {k: round(v, 2) for k, v in b.items()} for m, b in sorted(months.items())},
        # NOT per-repo shares: the meter files the account total under one or
        # a few repository names. Kept so the filing can be audited.
        "account_total_filed_under_this_month": by_name(this_month),
        "account_total_filed_under_previous_month": by_name(previous),
        "filed_under_note": ("The billing meter is account-level: it files the account's "
                             "whole Actions total under one or a few repository names, so "
                             "these are not per-repo shares. Per-repo minutes are the "
                             "analytics' by_repo job-minutes; parity compares their total "
                             "with the meter's."),
    }


def collect_billing(gh, today: dt.date | None = None) -> dict:
    """One request for the account's metered minutes; never raises.

    `today` defaults to the current UTC date; tests pin it so the
    this-month / previous-month split does not depend on the wall clock.

    A token without the billing read scope, or a moved endpoint, yields an
    `error` field instead of an exception, so the sweep still publishes the
    analytics and the budget wire falls back to them (and says so).
    """
    try:
        login = gh.get_user().login
        requester = requester_of(gh)
        _, data = requester.requestJsonAndCheck("GET", BILLING_ENDPOINT.format(login=login))
        return summarize_billing(data.get("usageItems") or [],
                                 today or dt.datetime.now(dt.timezone.utc).date())
    except Exception as exc:  # noqa: BLE001 - the report must publish either way
        return {"source": "GitHub billing usage API (" + BILLING_ENDPOINT + ")",
                "scope": "account",
                "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


# --------------------------------------------------------------------------- #
# job-minutes for every completed run: known, cached, fetched, or estimated
# --------------------------------------------------------------------------- #
def fetch_order(need: list[dict]) -> list[dict]:
    """The order in which uncached runs get the job budget.

    Owned before external (external minutes never enter fleet totals); within
    each, the wall-clock SUSPECTS first — a non-success run past
    SUSPECT_RUN_MIN or any run past MAX_RUN_MIN, where the job list decides
    whether hours of elapsed time billed anything — then a round-robin across
    workflows, newest first, so a short budget still measures every workflow
    and the estimator has a ratio for each.
    """
    ordered: list[dict] = []
    for external in (False, True):
        pool = [c for c in need if c["external"] == external]
        suspects = [c for c in pool
                    if c["dur"] > MAX_RUN_MIN
                    or (c["dur"] >= SUSPECT_RUN_MIN and c["conclusion"] in WASTE_CONCLUSIONS)]
        ids = {id(c) for c in suspects}
        groups: dict[tuple, list[dict]] = {}
        for c in pool:
            if id(c) not in ids:
                groups.setdefault((c["nwo"], c["workflow_id"]), []).append(c)
        for g in groups.values():
            g.sort(key=lambda c: c["created_at"] or "", reverse=True)
        ordered += sorted(suspects, key=lambda c: -c["dur"])
        queues = [list(g) for g in groups.values()]
        while queues:
            nxt = []
            for q in queues:
                ordered.append(q.pop(0))
                if q:
                    nxt.append(q)
            queues = nxt
    return ordered


def assign_job_minutes(api, contexts: list[dict], cache: JobCache, budget: int) -> dict:
    """Give every completed run its job-minutes, spending at most `budget`
    job requests. Each context gains `job_min`, `billed_jobs` and `job_basis`:
    `no-jobs` (a conclusion that cannot bill, no request), `cache`, `jobs`
    (fetched now), or `estimated` (left over; see estimate_job_minutes)."""
    need = []
    for c in contexts:
        if c["conclusion"] in NO_JOB_CONCLUSIONS:
            c.update(job_min=0, billed_jobs=0, job_basis="no-jobs")
            continue
        hit = cache.get(c["key"])
        if hit is not None and isinstance(hit.get("job_min"), (int, float)):
            c.update(job_min=hit["job_min"], billed_jobs=hit.get("billed_jobs"), job_basis="cache")
            continue
        need.append(c)
    stats = {"needed": len(need), "fetched": 0, "errors": 0, "budget": budget}
    start = api.calls["jobs"]
    for c in fetch_order(need):
        if api.calls["jobs"] - start >= budget:
            break
        try:
            jobs = fetch_jobs(api, c["nwo"], c["run_id"])
        except Exception:  # noqa: BLE001 - left to the estimator, counted
            stats["errors"] += 1
            continue
        jm = job_minutes(jobs)
        c.update(job_min=jm["job_min"], billed_jobs=jm["billed_jobs"], job_basis="jobs")
        cache.put(c["key"], {**jm, "created_at": c["created_at"]})
        stats["fetched"] += 1
    stats["job_calls"] = api.calls["jobs"] - start
    return stats


def estimate_job_minutes(contexts: list[dict]) -> None:
    """Price every run the budget did not reach from what was measured.

    job-minutes ≈ bounded wall clock × the measured job/wall ratio of the same
    workflow, else the same repo, else the fleet, else 1.0 — a matrix workflow's
    ratio stays its own. Reads each context's `wall_min` (bounded, and 0 for a
    run its job list proved jobless); measured runs with no wall time (and the
    structural zeros of `no-jobs`) do not enter a ratio.
    """
    sums: dict[tuple, list[float]] = {}
    for c in contexts:
        if c.get("job_basis") not in ("jobs", "cache") or c["wall_min"] <= 0:
            continue
        for key in (("wf", c["nwo"], c["workflow_id"]), ("repo", c["nwo"]), ("fleet",)):
            s = sums.setdefault(key, [0.0, 0.0])
            s[0] += float(c["job_min"])
            s[1] += c["wall_min"]
    for c in contexts:
        if c.get("job_basis") is not None:
            continue
        ratio = 1.0
        for key in (("wf", c["nwo"], c["workflow_id"]), ("repo", c["nwo"]), ("fleet",)):
            s = sums.get(key)
            if s and s[1] > 0:
                ratio = s[0] / s[1]
                break
        c.update(job_min=round(c["wall_min"] * ratio, 2), billed_jobs=None,
                 job_basis="estimated")


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def new_bucket() -> dict:
    return {"runs": 0, "total_min": 0.0, "success_min": 0.0, "waste_min": 0.0,
            # cancel_min is a SUBSET of waste_min, split out so the cancel-heavy
            # flag can ask what cancellation actually cost.
            "cancel_min": 0.0,
            # the bounded wall clock, the secondary measure (latency, not cost)
            "wall_min": 0.0, "wall_durations": [],
            # runs whose job-minutes are an estimate (the job budget ran out)
            "estimated_runs": 0,
            "success": 0, "failure": 0, "cancelled": 0, "other": 0,
            "durations": [], "events": {},
            "last_conclusion": None, "last_at": None}


def fold(bucket: dict, rec: dict) -> None:
    m = rec["minutes"]
    w = rec.get("wall_min", m)
    c = rec["conclusion"]
    bucket["runs"] += 1
    bucket["total_min"] += m
    bucket["durations"].append(m)
    bucket["wall_min"] += w
    bucket["wall_durations"].append(w)
    if rec.get("estimated"):
        bucket["estimated_runs"] += 1
    bucket["events"][rec["event"]] = bucket["events"].get(rec["event"], 0) + 1
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
    elif c in WASTE_CONCLUSIONS:
        bucket["waste_min"] += m
        if c == "cancelled":
            bucket["cancelled"] += 1
            bucket["cancel_min"] += m
        else:
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


def gap_pct(ours: float | None, reference: float | None) -> float | None:
    """How far `ours` sits from `reference`, as a signed % of the reference."""
    if ours is None or not reference:
        return None
    return round(100.0 * (ours - reference) / reference, 1)


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
        # job-minutes (schema v2): what GitHub bills
        "total_min": round(b["total_min"], 1),
        "avg_min": round(b["total_min"] / b["runs"], 2) if b["runs"] else 0.0,
        "p95_min": p95(b["durations"]),
        # the bounded wall clock: how long a run takes, not what it costs
        "wall_min": round(b.get("wall_min", 0.0), 1),
        "wall_avg_min": round(b.get("wall_min", 0.0) / b["runs"], 2) if b["runs"] else 0.0,
        "wall_p95_min": p95(b.get("wall_durations") or []),
        "waste_min": round(b["waste_min"], 1),
        # The share of waste_min that was merely superseded. Published because
        # "42% of runs cancelled" and "cancellation cost 2.5 of 84.7 minutes"
        # are the two halves of the same fact, and only the second one is a cost.
        "cancel_min": round(b["cancel_min"], 1),
        "runs_per_week": round(b["runs"] / weeks, 1),
        "success": b["success"], "failure": b["failure"], "cancelled": b["cancelled"],
        # Cancelled runs are EXCLUDED from the denominator: a superseded
        # run reached no verdict, so counting it as "not a success" made
        # `success_rate_pct` measure churn instead of correctness, and
        # the sub-50% result then tripped the `failing` flag on
        # workflows with zero actual failures. Cancelled MINUTES still
        # count as waste (they were really burned) — see waste_min — and
        # the churn itself stays visible as cancel_pct / `cancel-heavy`.
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
        # How many of these runs' job-minutes are estimates (job budget spent).
        "job_runs_estimated": b.get("estimated_runs", 0),
        "sampled": bool(b.get("estimated_runs", 0)),
    }


def build_report(targets: list[dict], api, *, days: int = 14, max_runs: int = 0,
                 cache: JobCache | None = None, max_job_calls: int = JOB_CALL_CEILING,
                 api_reserve: int = API_RESERVE, now: dt.datetime | None = None,
                 billing: dict | None = None) -> dict:
    """List every target's window, price each completed run in job-minutes
    (known / cached / fetched under the budget / estimated), and aggregate.

    `targets` is the registry with the hub (with_hub); `api` is a RestApi or
    a fixture with the same `get` / `core_remaining` / `calls`; `billing` is
    the meter (collect_billing), fetched by the caller beside the client.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=days)
    weeks = max(days / 7.0, 1 / 7.0)
    cache = cache if cache is not None else JobCache(None)
    remaining_before = api.core_remaining()

    # 1. list: workflows + every run created in the window, per repo (cheap)
    repos: list[dict] = []
    contexts: list[dict] = []
    for project in targets:
        nwo = owner_repo(project.get("repo_url", ""))
        if not nwo:
            continue
        sys.stderr.write(f"  · {nwo}\n")
        external = not nwo.startswith("bamr87/")
        wf_meta = list_workflows(api, nwo)
        listing = list_window_runs(api, nwo, window_start, now, max_runs)
        repo = {"name": project["name"], "nwo": nwo, "repo_url": project.get("repo_url"),
                "external": external, "wf_meta": wf_meta, "listing": listing,
                "incomplete": 0, "contexts": []}
        repos.append(repo)
        for run in listing["runs"]:
            if run.get("status") != "completed":
                repo["incomplete"] += 1
                continue                     # only finished runs have an outcome/duration
            dur = run_wall_min(run)
            if dur is None:
                continue
            created = parse_ts(run.get("created_at"))
            wid = run.get("workflow_id")
            ctx = {
                "nwo": nwo, "external": external, "repo": repo, "run": run,
                "run_id": run.get("id"), "workflow_id": wid,
                "key": JobCache.key(nwo, run),
                "conclusion": run.get("conclusion") or "unknown",
                "dur": dur,
                "created_at": created.isoformat() if created else None,
                "day": created.date().isoformat() if created else None,
                "job_basis": None,
            }
            contexts.append(ctx)
            repo["contexts"].append(ctx)

    # 2. job-minutes, under the call ceiling and the quota left after a reserve
    remaining = api.core_remaining()
    budget = max(0, int(max_job_calls))
    if remaining is not None:
        budget = min(budget, max(0, remaining - int(api_reserve)))
    stats = assign_job_minutes(api, contexts, cache, budget)
    for c in contexts:
        # the wall proxy, now that the job list may have proven a run jobless
        known = c.get("billed_jobs") if c["job_basis"] else None
        c["wall_min"] = wall_cost_min(c["conclusion"], c["dur"], known)
    estimate_job_minutes(contexts)

    # 3. aggregate
    workflows: list[dict] = []
    inactive: list[dict] = []
    by_type: dict[str, dict] = {}
    by_repo: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    coverage_rows: list[dict] = []
    for repo in repos:
        name, external, wf_meta = repo["name"], repo["external"], repo["wf_meta"]
        wf_buckets: dict[int, dict] = {}
        for c in repo["contexts"]:
            run = c["run"]
            wid = c["workflow_id"]
            wname = (wf_meta.get(wid, {}).get("name") or run.get("name")
                     or os.path.basename(run.get("path") or "") or "workflow")
            path = wf_meta.get(wid, {}).get("path") or run.get("path") or ""
            rec = {
                "workflow_id": wid, "name": wname, "path": path,
                "event": run.get("event") or "unknown",
                "conclusion": c["conclusion"],
                "minutes": float(c["job_min"]),
                "wall_min": c["wall_min"],
                "estimated": c["job_basis"] == "estimated",
                "day": c["day"], "created_at": c["created_at"],
            }
            b = wf_buckets.setdefault(wid, new_bucket())
            b["_name"] = wname
            b["_path"] = path
            fold(b, rec)
            # roll up type / repo / day — bamr87-owned repos only. External
            # mirrors (upstream not bamr87, e.g. microsoft/skills) stay visible
            # per-workflow but never enter fleet KPIs or triage: their spend
            # isn't ours to optimize (bamr87/bamr87#24).
            if external:
                continue
            for agg, key in ((by_type, classify_type(wname, path)), (by_repo, name),
                             (by_day, rec["day"])):
                if key is None:
                    continue
                fold(agg.setdefault(key, new_bucket()), rec)

        for wid, b in wf_buckets.items():
            workflows.append(workflow_record(b, repo=name, repo_url=repo["repo_url"],
                                             external=external, weeks=weeks))

        # workflows that exist but never ran in the window (dead weight)
        ran = set(wf_buckets)
        for wid, meta in wf_meta.items():
            if wid not in ran and not (meta.get("path") or "").startswith("dynamic/"):
                inactive.append({"repo": name, "workflow": meta.get("name"),
                                 "path": meta.get("path"), "state": meta.get("state")})

        basis = collections.Counter(c["job_basis"] for c in repo["contexts"])
        listing = repo["listing"]
        coverage_rows.append({
            "repo": name, "nwo": repo["nwo"], "external": external,
            "runs_in_window": listing["in_window"],
            "runs_listed": len(listing["runs"]),
            "runs_incomplete": repo["incomplete"],
            "truncated": bool(listing["truncated"]),
            "runs_missed": listing["runs_missed"],
            "job_runs_fetched": basis.get("jobs", 0),
            "job_runs_cached": basis.get("cache", 0),
            "job_runs_no_call": basis.get("no-jobs", 0),
            "job_runs_estimated": basis.get("estimated", 0),
            "sampled": bool(basis.get("estimated", 0)),
            "error": listing["error"],
        })

    api_block = {
        "calls": dict(sorted(api.calls.items())),
        "calls_total": sum(api.calls.values()),
        "job_call_budget": budget,
        "max_job_calls": int(max_job_calls),
        "reserve": int(api_reserve),
        "rate_remaining_before": remaining_before,
        "rate_remaining_after": api.core_remaining(),
        "jobs_needed": stats["needed"],
        "jobs_fetched": stats["fetched"],
        "job_errors": stats["errors"],
        "cache_entries_loaded": cache.loaded,
        "cache_error": cache.error,
    }
    return finalize(workflows, inactive, by_type, by_repo, by_day, days, len(repos), now,
                    billing=billing, coverage={"repos": coverage_rows, "api": api_block})


def summarize(bucket: dict) -> dict:
    return {
        "runs": bucket["runs"],
        "total_min": round(bucket["total_min"], 1),
        "wall_min": round(bucket.get("wall_min", 0.0), 1),
        "waste_min": round(bucket["waste_min"], 1),
        "effectiveness_pct": pct(bucket["success_min"], bucket["total_min"]) if bucket["total_min"] else 100.0,
        # Cancelled excluded from the denominator — see the per-workflow record.
        "success_rate_pct": pct(bucket["success"], bucket["success"] + bucket["failure"]),
        "job_runs_estimated": bucket.get("estimated_runs", 0),
    }


def actions_parity(day_rows: list[dict], billing: dict | None, now: dt.datetime, days: int,
                   *, sampled: bool = False, truncated: bool = False) -> dict:
    """The analytics total against the meter's ACCOUNT total.

    The meter is monthly; the window is a rolling `days`. When the whole month
    so far sits inside the window the two are compared month-to-date, minute
    for minute; once the month is longer than the window, as daily rates. The
    meter also counts repos the registry does not list (and lags by hours),
    so a small negative gap is expected; a large one means the analytics are
    missing minutes, a positive one that they invent them.
    """
    out: dict = {"measure": "Actions minutes",
                 "ours": "analytics job-minutes (owned repos + hub; external mirrors excluded)",
                 "reference": "GitHub billing meter, account total (billing.minutes_this_month)",
                 "sampled": bool(sampled), "truncated": bool(truncated)}
    if not isinstance(billing, dict) or billing.get("error") or billing.get("minutes_this_month") is None:
        reason = (billing or {}).get("error") if isinstance(billing, dict) else None
        out.update(basis=None, gap_pct=None,
                   reason=f"billing meter unavailable{': ' + reason if reason else ''}")
        return out
    today = as_utc(now).date()
    month_start = today.replace(day=1)
    window_start = (as_utc(now) - dt.timedelta(days=days)).date()
    meter = float(billing["minutes_this_month"])
    elapsed = int(billing.get("days_elapsed") or today.day)
    if billing.get("this_month") not in (None, today.strftime("%Y-%m")):
        out.update(basis=None, gap_pct=None,
                   reason=f"meter month {billing.get('this_month')} is not {today:%Y-%m}")
        return out
    if month_start >= window_start:
        rows = [r for r in day_rows if str(r.get("date") or "") >= month_start.isoformat()]
        ours = round(sum(float(r.get("total_min") or 0) for r in rows), 1)
        wall = round(sum(float(r.get("wall_min") or 0) for r in rows), 1)
        out.update(basis="month-to-date", period=f"{month_start.isoformat()}..{today.isoformat()}",
                   ours_min=ours, ours_wall_min=wall, reference_min=round(meter, 1))
    else:
        ours = round(sum(float(r.get("total_min") or 0) for r in day_rows) / days, 1)
        wall = round(sum(float(r.get("wall_min") or 0) for r in day_rows) / days, 1)
        meter = meter / elapsed if elapsed else 0.0
        out.update(basis="daily-rate", period=f"window {window_start.isoformat()}..{today.isoformat()} "
                   f"vs meter {month_start.isoformat()}..{today.isoformat()}",
                   ours_min_per_day=ours, ours_wall_min_per_day=wall,
                   reference_min_per_day=round(meter, 1))
    out["gap_pct"] = gap_pct(ours, meter)
    out["wall_gap_pct"] = gap_pct(wall, meter)
    return out


def finalize(workflows, inactive, by_type, by_repo, by_day, days, scanned, now,
             billing: dict | None = None, coverage: dict | None = None) -> dict:
    owned = [w for w in workflows if not w.get("external")]
    grand_min = sum(w["total_min"] for w in owned) or 1.0
    grand_wall = sum(w.get("wall_min", w["total_min"]) for w in owned)
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
        # Slow is LATENCY: the wall clock of a run, not its job-minutes — ten
        # parallel 2-minute jobs cost 20 minutes and finish in 2.
        if w.get("wall_avg_min", w["avg_min"]) > SLOW_AVG_MIN:
            flags.append("slow")
        # Cancelled SHARE says a guard is firing; cancelled COST says whether
        # that is a problem. Requiring both keeps a working `cancel-in-progress`
        # guard — which saves far more minutes than the supersessions burn —
        # out of a queue meant for workflows that need fixing.
        cancel_min = w.get("cancel_min") or 0.0
        cancel_run_min = cancel_min / w["cancelled"] if w["cancelled"] else 0.0
        if (completed >= 4 and pct(w["cancelled"], completed) > CANCEL_HEAVY_PCT
                and cancel_min >= CANCEL_MIN_WASTE_MIN
                and cancel_run_min >= CANCEL_COST_RATIO * w["avg_min"]):
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

    cov_rows = (coverage or {}).get("repos") or []
    cov_by_name = {r["repo"]: r for r in cov_rows}

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
    # Per repo: did the listing see the whole window, and are its minutes measured?
    for r in repo_rows:
        cov = cov_by_name.get(r["repo"])
        if cov:
            r["truncated"] = cov["truncated"]
            r["runs_missed"] = cov["runs_missed"]
            r["sampled"] = cov["sampled"]
    day_rows = sorted(
        ({"date": d, **summarize(b)} for d, b in by_day.items() if d),
        key=lambda r: r["date"],
    )

    # Every fleet total ranges over `owned`, the SAME population as grand_min
    # above. Summing these over all `workflows` while the denominator counted
    # only owned ones published 2091.6h wasted against 1269.3h consumed and an
    # effectiveness of -64.8% — a figure unreachable when waste is a subset of
    # consumption. One external mirror (tt-a1i/archify) contributed 50890.7 of
    # those waste minutes while its 51370.0 consumed minutes were correctly
    # excluded (bamr87/bamr87#229). External spend is not ours to optimize, so
    # it belongs in NEITHER half — the same rule the by_type/by_repo/by_day
    # rollups already follow.
    tot_runs = sum(w["runs"] for w in owned)
    tot_success = sum(w["success"] for w in owned)
    # Failures only — cancelled runs reached no verdict and are excluded from
    # the success rate, matching the per-workflow record. Their MINUTES still
    # count in waste_min.
    tot_fail = sum(w["failure"] for w in owned)
    tot_waste = round(sum(w["waste_min"] for w in owned), 1)
    estimated = sum(int(w.get("job_runs_estimated") or 0) for w in owned)
    owned_cov = [r for r in cov_rows if not r.get("external")]
    truncated = any(r["truncated"] for r in owned_cov)
    missed = sum(int(r["runs_missed"] or 0) for r in owned_cov)

    coverage_block = None
    if coverage is not None:
        coverage_block = {
            "truncated": truncated,
            "runs_missed": missed,
            "truncated_repos": [r["repo"] for r in cov_rows if r["truncated"]],
            "sampled": bool(estimated),
            "sampled_repos": [r["repo"] for r in cov_rows if r["sampled"]],
            "api": coverage.get("api"),
            "repos": cov_rows,
        }

    return {
        "schema": SCHEMA,
        "minutes_basis": MINUTES_BASIS,
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": days,
        "repos_scanned": scanned,
        "totals": {
            "runs": tot_runs,
            "workflows": len(workflows),
            "repos_with_activity": len(by_repo),
            "total_min": round(grand_min, 1),
            "total_hours": round(grand_min / 60, 1),
            "wall_min": round(grand_wall, 1),
            "wall_hours": round(grand_wall / 60, 1),
            "waste_min": tot_waste,
            "waste_hours": round(tot_waste / 60, 1),
            "effectiveness_pct": round(100 * (grand_min - tot_waste) / grand_min, 1),
            "success_rate_pct": pct(tot_success, tot_success + tot_fail),
            "job_runs_estimated": estimated,
            "sampled": bool(estimated),
            "truncated": truncated,
            "runs_missed": missed,
        },
        "by_type": type_rows,
        "by_repo": repo_rows,
        "by_day": day_rows,
        "workflows": workflows,
        "inactive": sorted(inactive, key=lambda x: (x["repo"] or "", x["workflow"] or "")),
        "billing": billing,
        "parity": {"actions_minutes": actions_parity(day_rows, billing, now, days,
                                                     sampled=bool(estimated),
                                                     truncated=truncated)},
        "coverage": coverage_block,
        "note": ("Cost = job-minutes: each job that ran on a GitHub-hosted runner, rounded up "
                 "to a whole minute, as GitHub bills it; skipped jobs and jobs that never "
                 "reached a runner count 0 (schema actions-usage/v2). The run wall clock "
                 "(run_started_at → updated_at) is kept as wall_min / wall_avg_min / "
                 "wall_p95_min — latency, which the `slow` flag reads — bounded: a run that "
                 "never executed counts 0 and every other run is capped at "
                 f"{MAX_RUN_MIN:.0f} min. Every run created in the window is listed (paged "
                 "by date range); a repo whose listing still fell short says truncated: true "
                 "with runs_missed. Job-minutes are cached per run, fetched only for runs new "
                 "since the last sweep, and capped per sweep; a run past the cap is "
                 "estimated from its workflow's measured job/wall ratio and its row says "
                 "sampled: true. Value = share of minutes ending in success. "
                 "Waste = minutes on failed/cancelled/timed-out runs. "
                 "Fleet totals cover bamr87-owned workflows and the hub only — the same "
                 "population on both halves of every ratio, so waste can never exceed "
                 "consumption; external mirrors never enter them. "
                 "Success rate counts only runs that reached a verdict "
                 "(success + failure); cancelled runs were superseded, not broken, "
                 "and show up as cancel_pct / the cancel-heavy flag instead. "
                 "A workflow with NO verdicts in the window (every run skipped) "
                 "reports null rates — 'no data', not 0%. The `billing` block is GitHub's "
                 "own meter (billing usage API), per month, for the whole ACCOUNT — the "
                 "repository names it files the total under are not per-repo shares; it is "
                 "what the harness budget wire prices, and `parity` reports the gap between "
                 "it and the analytics total."),
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
    w(f"  {t['runs']} runs · {t['total_hours']}h job-minutes ({t.get('wall_hours')}h wall) · "
      f"{t['success_rate_pct']}% success · {t['waste_hours']}h wasted "
      f"({100 - t['effectiveness_pct']:.0f}% of minutes)\n")
    if t.get("sampled") or t.get("truncated"):
        w(f"  ! sampled: {t.get('job_runs_estimated', 0)} runs estimated · "
          f"truncated: {t.get('runs_missed', 0)} runs missed\n")
    par = (rep.get("parity") or {}).get("actions_minutes") or {}
    if par.get("gap_pct") is not None:
        w(f"  parity vs the meter ({par['basis']}): job-minutes {par['gap_pct']:+.1f}% · "
          f"wall clock {par['wall_gap_pct']:+.1f}%\n")
    api = ((rep.get("coverage") or {}).get("api")) or {}
    if api:
        w(f"  API: {api.get('calls_total')} calls ({api.get('calls')}) · "
          f"job budget {api.get('job_call_budget')} · rate left {api.get('rate_remaining_after')}\n")
    w("\n")

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
    targets = list(registry) if args.no_hub else with_hub(registry)
    if args.repo:
        wanted = set(args.repo)
        targets = [p for p in targets
                   if p.get("name") in wanted or owner_repo(p.get("repo_url", "")) in wanted]

    gh = Github(auth=Auth.Token(token), per_page=100)
    api = RestApi(requester_of(gh))
    cache = JobCache(Path(args.cache) if args.cache else None)
    now = dt.datetime.now(dt.timezone.utc)
    sys.stderr.write(f"Scanning Actions usage for {len(targets)} repos (last {args.days}d; "
                     f"{cache.loaded} cached runs)…\n")
    # The meter is fetched here, beside the client, so build_report stays a
    # function the fixture tests can drive with a fake API.
    billing = collect_billing(gh)
    report = build_report(targets, api, days=args.days, max_runs=args.max_runs, cache=cache,
                          max_job_calls=args.max_job_calls, api_reserve=args.api_reserve,
                          now=now, billing=billing)
    kept = cache.save(prune_before=now - dt.timedelta(days=args.days + 1))
    if args.cache:
        sys.stderr.write(f"Cache: {kept} runs -> {args.cache}\n")

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
    parser.add_argument("--max-runs", type=int, default=0, metavar="N",
                        help="cap runs listed per repo; 0 = the whole window (default). "
                             "A cap that bites is published as truncated: true + runs_missed")
    parser.add_argument("--max-job-calls", type=int, default=JOB_CALL_CEILING, metavar="N",
                        help=f"ceiling on jobs requests per sweep (default {JOB_CALL_CEILING}); "
                             "runs past it are estimated and marked sampled: true")
    parser.add_argument("--api-reserve", type=int, default=API_RESERVE, metavar="N",
                        help=f"core-quota requests left for later steps (default {API_RESERVE})")
    parser.add_argument("--cache", default=str(CACHE_DEFAULT), metavar="PATH",
                        help="per-run job-minute cache (default .dash-lake/actions_jobs_cache.json; "
                             "'' disables)")
    parser.add_argument("--repo", action="append", metavar="NAME",
                        help="only this registry name or owner/repo (repeatable; a local probe — "
                             "the committed snapshot is always the whole fleet)")
    parser.add_argument("--no-hub", action="store_true",
                        help="skip the hub itself (_data/fleet.yml hub.repo); registry only")
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

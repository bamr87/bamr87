#!/usr/bin/env python3
"""
workflow_sync — `tools/dash workflows sync`: every fleet repository's workflow
files, and the latest run of each of its checks, read into the local lake with
the OPERATOR's token, so the fleet workflow model (`fleet-workflows/v1`,
tools/fleetcore/workflows.py) is built offline from one place (ADR 0007
decision 3, bamr87/bamr87#721).

The atlas (workflow_atlas.py) reads the hub's 36 workflows; the other ~380
files in the fleet had no catalog, lint or check view, and the review that
found 22 verify callers green while running nothing needed custom scripts.
This is the read half of that view, and nothing more:

  targets   every repository in _data/projects.yml plus the hub. A repository
            whose owner is not in `_data/fleet.yml` `hub.owners` is an external
            upstream: reported as not read, with that reason, never fetched.
  files     fleet_lake.sync_workflows() over each owned repository: the
            listing, then only the files whose blob sha changed since the
            last read (the conditional read), capped at
            `harnesses.inventory.max_workflow_files` per repository.
  checks    the Verify caller and the pull-request/push gates of each
            repository (at most --max-checks): the latest run of each, its
            jobs and steps, and for a failed run its log, so the model can
            tell verified from passed-empty, never-ran, quota, real-failure
            and cancelled. Claude's facts in that log (an AI check's cost) are
            recorded from the same download, as `lake sync` does, because a
            stored log is never downloaded again. Archived repositories' runs
            are not read.
  record    one `workflow_reads` row per repository: the last attempt, its
            reason when it failed, and the time of the last read that worked.

Guardrails (constitution § 10, AGENTS.md "A PR or push check never reads the
whole fleet"):

  * refuses, before reading anything, when GITHUB_ACTIONS is set or
    GITHUB_EVENT_NAME is a pull-request event: every run in a repository
    shares one GITHUB_TOKEN quota, and a fleet read on each PR spent it;
  * the token is GH_TOKEN or `gh auth token`, and `gh` runs with every token
    variable removed from its environment, so GITHUB_TOKEN is never read,
    never forwarded, never printed;
  * read-only toward GitHub; it writes only the gitignored lake;
  * capped: --max-repos, --max-checks, --runs-per-check, the per-repo file
    cap, a per-run log byte cap, and a wall-clock --budget-s after which the
    repositories not reached are reported as not read.

CLI (tools/dash workflows sync …):
  sync [--repo R …] [--lake DIR] [--max-repos N] [--max-checks N]
       [--runs-per-check N] [--budget-s S] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("workflow_sync requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actions_analytics  # noqa: E402  owner_repo
import fleet_lake  # noqa: E402  the lake: connect, upsert, sync_workflows, store_logs
import workflow_atlas as wa  # noqa: E402  parse_workflow — no second parser

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"
API = "https://api.github.com"

# The triggers that make a workflow a check: it runs on a change, and its
# result is what a reader of a pull request or of main takes as the verdict.
CHECK_EVENTS = frozenset({"pull_request", "pull_request_target", "push", "merge_group"})
CI_ID_RX = re.compile(r"(?:^|[-_.])(?:ci|tests?|build|lint|check)(?:[-_.]|$)")
REFUSE_EVENTS = ("pull_request", "pull_request_target")
# Credentials `gh` would pick up from its environment ahead of its own login.
# Removing them is how `gh auth token` is kept from answering with GITHUB_TOKEN.
TOKEN_VARS = ("GITHUB_TOKEN", "GH_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
DEFAULTS = {"max_repos": 80, "max_checks": 6, "runs_per_check": 10, "budget_s": 900,
            "max_log_bytes": 2_000_000}
FAILED = ("failure", "timed_out", "startup_failure")


# --------------------------------------------------------------------------- #
# guardrails (pure)
# --------------------------------------------------------------------------- #
def refusal(env=None) -> str | None:
    """Why this process must not read the fleet, or None. Checked first."""
    env = os.environ if env is None else env
    actions = str(env.get("GITHUB_ACTIONS") or "").strip().lower()
    if actions and actions not in ("false", "0"):
        return ("GITHUB_ACTIONS is set: a fleet read never runs in CI, where every run in a repository "
                "shares one GITHUB_TOKEN quota (ADR 0007 decision 3)")
    event = str(env.get("GITHUB_EVENT_NAME") or "").strip()
    if event in REFUSE_EVENTS:
        return f"GITHUB_EVENT_NAME is {event}: a fleet read never runs on a pull request"
    return None


def operator_token(env=None, run=subprocess.run) -> tuple[str | None, str]:
    """(token, where it came from): GH_TOKEN, else `gh auth token` run with
    every token variable stripped from its environment. GITHUB_TOKEN is never
    read, so a job token can never stand in for the operator's."""
    env = dict(os.environ if env is None else env)
    own = str(env.get("GH_TOKEN") or "").strip()
    if own:
        return own, "GH_TOKEN"
    clean = {k: v for k, v in env.items() if k not in TOKEN_VARS}
    try:
        out = run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15, env=clean)
    except (OSError, subprocess.SubprocessError):
        return None, "`gh` is not installed or did not answer"
    token = str(getattr(out, "stdout", "") or "").strip()
    if getattr(out, "returncode", 1) == 0 and token:
        return token, "gh auth token"
    return None, "`gh` is not logged in"


def targets(registry: list, fleet: dict, only: list[str] | None = None) -> list[dict]:
    """The hub, then every registry repository, once each, with whether it is
    the fleet's own (its owner is in `hub.owners`) or an external upstream."""
    hub_cfg = fleet.get("hub") if isinstance(fleet.get("hub"), dict) else {}
    hub = str(hub_cfg.get("repo") or wa.HUB_DEFAULT)
    owners = {str(o).lower() for o in (hub_cfg.get("owners") or []) if o} or {hub.split("/", 1)[0].lower()}
    rows = [{"name": hub.split("/", 1)[-1], "repo_url": f"https://github.com/{hub}", "category": "dash",
             "status": "active"}] + [p for p in registry or [] if isinstance(p, dict)]
    out: list[dict] = []
    seen: set[str] = set()
    for p in rows:
        nwo = actions_analytics.owner_repo(str(p.get("repo_url") or ""))
        if not nwo or nwo.lower() in seen:
            continue
        seen.add(nwo.lower())
        if only and not ({nwo, nwo.split("/", 1)[1], str(p.get("name"))} & set(only)):
            continue
        owner = nwo.split("/", 1)[0]
        owned = owner.lower() in owners
        out.append({"nwo": nwo, "name": p.get("name"), "category": p.get("category"), "status": p.get("status"),
                    "hub": nwo.lower() == hub.lower(), "owned": owned,
                    "reason": None if owned else (f"external upstream: {owner} is not in hub.owners "
                                                  "(_data/fleet.yml), so it is consumed, never read")})
    return out


def check_kind(wf: dict) -> str | None:
    """`verify` for the Verify caller, `ci` for a pull-request/push gate, else None."""
    if wf.get("parse_error"):
        return None
    if wf.get("id") == "verify" or any(u.get("kind") == "workflow" and u.get("target") == "fleet-verify"
                                       for u in wf.get("uses") or []):
        return "verify"
    if set(wf.get("triggers") or []) & CHECK_EVENTS:
        return "ci"
    return None


def pick_checks(texts: dict[str, str], hub: str, cap: int) -> list[tuple[str, str]]:
    """The checks whose runs a sync reads, most telling first: the Verify
    caller, then gates named like CI, then the other gates; at most `cap`."""
    ranked = []
    for path, text in texts.items():
        try:
            wf = wa.parse_workflow(path, text or "", hub)
        except Exception:  # noqa: BLE001 — a file the atlas cannot read is not a check; the model reports it
            continue
        kind = check_kind(wf)
        if kind:
            ranked.append((0 if kind == "verify" else 1 if CI_ID_RX.search(wf["id"]) else 2, path, kind))
    return [(path, kind) for _, path, kind in sorted(ranked)[:max(0, cap)]]


# --------------------------------------------------------------------------- #
# network half
# --------------------------------------------------------------------------- #
class Api:
    """GET against the REST API through one session, counting calls."""

    def __init__(self, session, base: str = API):
        self.session, self.base, self.calls = session, base, 0

    def get(self, path: str, **params) -> tuple[dict | None, int | None]:
        self.calls += 1
        try:
            resp = self.session.get(self.base + path, params=params or None, timeout=30)
        except Exception as exc:  # noqa: BLE001 — a network failure is an unread check, said as such
            return None, exc.__class__.__name__
        if resp.status_code != 200:
            return None, resp.status_code
        try:
            return resp.json(), 200
        except ValueError:
            return None, "not JSON"


def _run_row(run: dict, nwo: str, path: str, ai: bool, now: str) -> dict:
    return {"id": run["id"], "nwo": nwo, "workflow_path": run.get("path") or path,
            "workflow_name": run.get("name"), "event": run.get("event"), "status": run.get("status"),
            "conclusion": run.get("conclusion"), "head_branch": run.get("head_branch"),
            "head_sha": run.get("head_sha"), "run_attempt": run.get("run_attempt"),
            "run_number": run.get("run_number"), "created_at": run.get("created_at"),
            "run_started_at": run.get("run_started_at"), "updated_at": run.get("updated_at"),
            "html_url": run.get("html_url"), "logs_url": run.get("logs_url"), "ai": int(bool(ai)),
            "synced_at": now}


def sync_check(conn, api: Api, nwo: str, path: str, kind: str, ai: bool, now: str, opts) -> dict:
    """The latest run of one check, its jobs and steps, and a failed run's log.
    Returns what the model needs to know about the lookup itself."""
    out = {"kind": kind, "listed": False, "error": None, "runs": 0, "run_id": None, "jobs": None}
    data, status = api.get(f"/repos/{nwo}/actions/workflows/{Path(path).name}/runs",
                           per_page=int(opts.runs_per_check))
    if data is None:
        out["error"] = f"runs not listed (HTTP {status})" if isinstance(status, int) else f"runs not listed ({status})"
        return out
    out["listed"] = True
    runs = [r for r in data.get("workflow_runs") or [] if isinstance(r, dict) and r.get("id")]
    out["runs"] = len(runs)
    if not runs:
        return out
    run = next((r for r in runs if r.get("status") == "completed"), runs[0])
    out["run_id"] = run["id"]
    prior = conn.execute("SELECT status FROM runs WHERE id=?", (run["id"],)).fetchone()
    fleet_lake.upsert(conn, "runs", _run_row(run, nwo, path, ai, now), ["id"])
    stored = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id=?", (run["id"],)).fetchone()[0]
    if prior and prior["status"] == "completed" and stored:
        out["jobs"] = stored  # a completed run's stored jobs are final
    else:
        jobs, _ = api.get(f"/repos/{nwo}/actions/runs/{run['id']}/jobs", per_page=100)
        if jobs is not None:
            listed = [j for j in jobs.get("jobs") or [] if isinstance(j, dict) and j.get("id")]
            out["jobs"] = int(jobs.get("total_count", len(listed)) or 0)
            for job in listed:
                fleet_lake.upsert(conn, "jobs", {
                    "id": job["id"], "run_id": run["id"], "nwo": nwo, "name": job.get("name"),
                    "status": job.get("status"), "conclusion": job.get("conclusion"),
                    "started_at": job.get("started_at"), "completed_at": job.get("completed_at"),
                    "runner_name": job.get("runner_name"), "html_url": job.get("html_url"),
                }, ["id"])
                for step in job.get("steps") or []:
                    if isinstance(step, dict) and step.get("number") is not None:
                        fleet_lake.upsert(conn, "steps", {
                            "job_id": job["id"], "number": step["number"], "name": step.get("name"),
                            "status": step.get("status"), "conclusion": step.get("conclusion"),
                            "started_at": step.get("started_at"), "completed_at": step.get("completed_at"),
                        }, ["job_id", "number"])
    # A failed run's log is what classify_failure reads (quota or a real failure); a green
    # run is judged from its steps, so its log is not downloaded.
    if (run.get("status") == "completed" and run.get("conclusion") in FAILED and out["jobs"]
            and run.get("logs_url")
            and not conn.execute("SELECT 1 FROM logs WHERE run_id=? LIMIT 1", (run["id"],)).fetchone()):
        api.calls += 1
        _, agent_text = fleet_lake.store_logs(conn, api.session, run["id"], run["logs_url"],
                                              int(opts.max_log_bytes))
        # Record Claude's facts from the same download, as fleet_lake.sync_runs does: `lake sync`
        # takes a stored log as "already parsed" and never downloads it again, so an AI check's
        # cost dropped here would be lost for good and `lake review` would call the run a real $0.
        if agent_text:
            facts = fleet_lake.parse_agent_log(agent_text)
            if facts:
                fleet_lake.record_agent_run(conn, run["id"], nwo, facts)
    conn.commit()
    return out


def _status_of(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    return f"{exc.__class__.__name__}{f' HTTP {status}' if status else ''}"


def sync_repo(conn, gh, api: Api, target: dict, hub: str, opts, now: str, deadline: float,
              clock=time.monotonic) -> dict:
    """Read one owned repository and record the attempt. Returns the row written."""
    nwo = target["nwo"]
    prev = conn.execute("SELECT * FROM workflow_reads WHERE nwo=?", (nwo,)).fetchone()
    prev = dict(prev) if prev else {}
    calls = api.calls
    rec = {"nwo": nwo, "ok": 0, "attempted_at": now, "read_at": prev.get("read_at"), "reason": None,
           "files": prev.get("files") or 0, "listed": 0, "truncated": prev.get("truncated") or 0,
           "archived": prev.get("archived"), "default_branch": prev.get("default_branch"),
           "paths": prev.get("paths") or "[]", "checks": prev.get("checks") or "{}", "calls": 0}

    def done(row: dict) -> dict:
        row["calls"] = api.calls - calls
        fleet_lake.upsert(conn, "workflow_reads", row, ["nwo"])
        conn.commit()
        return row

    api.calls += 1
    try:
        repo = gh.get_repo(nwo)
    except Exception as exc:  # noqa: BLE001 — an unreachable repository is a reason, not a crash
        return done(rec | {"reason": f"unreachable ({_status_of(exc)})"})
    rec["archived"] = int(bool(getattr(repo, "archived", False)))
    rec["default_branch"] = getattr(repo, "default_branch", None)
    report: dict = {}
    ai = fleet_lake.sync_workflows(conn, repo, nwo, now, int(opts.max_files), report=report)
    api.calls += 1 + int(report.get("fetched") or 0) + len(report.get("failed") or [])
    if not report.get("listed"):
        return done(rec | {"reason": report.get("error") or "the workflow listing did not answer"})
    rec.update({"ok": 1, "read_at": now, "listed": 1, "files": int(report["files"]),
                "truncated": int(bool(report["truncated"])), "paths": json.dumps(report["paths"])})
    notes = []
    if report["truncated"]:
        notes.append(f"the listing holds {report['files']} workflow files; the first {opts.max_files} were read "
                     "(harnesses.inventory.max_workflow_files)")
    if report["failed"]:
        notes.append(f"{len(report['failed'])} file(s) could not be fetched: {', '.join(report['failed'][:5])}")
    checks: dict[str, dict] = {}
    if rec["archived"]:
        notes.append("archived: its runs are not read")
    else:
        texts = {}
        for p in report["paths"]:
            row = conn.execute("SELECT text FROM workflows WHERE nwo=? AND path=?", (nwo, p)).fetchone()
            texts[p] = row["text"] if row else ""
        for path, kind in pick_checks(texts, hub, int(opts.max_checks)):
            if clock() > deadline:
                notes.append("the time budget ran out before every check was read")
                break
            checks[path] = sync_check(conn, api, nwo, path, kind, path in ai, now, opts)
    rec["checks"] = json.dumps(checks)
    rec["reason"] = "; ".join(notes) or None
    return done(rec)


def run_sync(conn, gh, api: Api, plan: list[dict], hub: str, opts, now: str,
             clock=time.monotonic, log=sys.stderr) -> list[dict]:
    """Every target, in order, inside the caps; one result per target."""
    deadline = clock() + float(opts.budget_s)
    results, attempted = [], 0
    for t in plan:
        if not t["owned"]:
            results.append({**t, "read": False, "reason": t["reason"]})
            continue
        if attempted >= int(opts.max_repos):
            results.append({**t, "read": False, "reason": f"past --max-repos {opts.max_repos}: not attempted"})
            continue
        if clock() > deadline:
            results.append({**t, "read": False,
                            "reason": f"the time budget ({opts.budget_s}s) ran out before it was reached"})
            continue
        attempted += 1
        log.write(f"  workflows · {t['nwo']}\n")
        row = sync_repo(conn, gh, api, t, hub, opts, now, deadline, clock)
        results.append({**t, "read": bool(row["ok"]), "reason": row["reason"], "files": row["files"],
                        "checks": len(json.loads(row["checks"] or "{}")) if row["ok"] else 0,
                        "read_at": row["read_at"], "calls": row["calls"]})
    return results


def summary_lines(results: list[dict], db: Path, seconds: float, calls: int) -> list[str]:
    read = [r for r in results if r["read"]]
    missed = [r for r in results if not r["read"]]
    lines = [f"workflows sync: read {len(read)} of {len(results)} repos — {sum(r.get('files') or 0 for r in read)} "
             f"workflow files, {sum(r.get('checks') or 0 for r in read)} checks, {calls} API calls, "
             f"{seconds:.0f}s → {db}"]
    if missed:
        lines.append(f"  not read ({len(missed)}):")
        lines += [f"    {r['nwo']:<44} {r['reason']}" for r in missed]
    noted = [r for r in read if r.get("reason")]
    if noted:
        lines.append(f"  read, with a note ({len(noted)}):")
        lines += [f"    {r['nwo']:<44} {r['reason']}" for r in noted]
    lines.append("  render it: tools/dash workflows --fleet list")
    return lines


def _load(path: Path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def cmd_sync(args: argparse.Namespace) -> int:
    why = refusal()
    if why:
        sys.stderr.write(f"workflows sync: refused — {why}. Nothing was read.\n")
        return 2
    token, source = operator_token()
    if not token:
        sys.stderr.write(f"workflows sync: no operator token ({source}). Set GH_TOKEN or run `gh auth login`; "
                         "GITHUB_TOKEN is never used. Nothing was read.\n")
        return 1
    try:
        import requests
        from github import Auth, Github
    except ImportError:
        sys.stderr.write("workflows sync requires PyGithub + requests: "
                         "pip install -r .github/scripts/dash-gen/requirements.txt\n")
        return 2
    fleet = _load(args.fleet) or {}
    registry = _load(args.registry) or []
    plan = targets(registry, fleet, args.repo)
    if not plan:
        sys.stderr.write("workflows sync: no registry repository matched --repo.\n")
        return 2
    hub = str((fleet.get("hub") or {}).get("repo") or wa.HUB_DEFAULT)
    inventory = ((fleet.get("harnesses") or {}).get("inventory") or {})
    args.max_files = int(inventory.get("max_workflow_files") or 40)
    gh = Github(auth=Auth.Token(token), per_page=100, timeout=30)
    session = requests.Session()
    session.headers["Authorization"] = f"token {token}"
    session.headers["Accept"] = "application/vnd.github+json"
    conn = fleet_lake.connect(args.lake)
    started = time.monotonic()
    api = Api(session)
    try:
        results = run_sync(conn, gh, api, plan, hub, args, fleet_lake.iso(fleet_lake.utcnow()))
    finally:
        conn.close()
    _, db = fleet_lake.lake_paths(args.lake)
    if args.json:
        print(json.dumps({"lake": str(db), "token_source": source, "calls": api.calls,
                          "seconds": round(time.monotonic() - started, 1), "repos": results}, indent=2, default=str))
    else:
        print("\n".join(summary_lines(results, db, time.monotonic() - started, api.calls)))
    owned = [r for r in results if r["owned"]]
    return 1 if owned and not any(r["read"] for r in owned) else 0


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", action="append", default=None,
                   help="only this repository (owner/name or registry name); repeatable")
    p.add_argument("--lake", default=None, help="lake directory (default DASH_LAKE_DIR, else .dash-lake/)")
    p.add_argument("--fleet", default=str(FLEET_DEFAULT), help=argparse.SUPPRESS)
    p.add_argument("--registry", default=str(REGISTRY_DEFAULT), help=argparse.SUPPRESS)
    p.add_argument("--max-repos", type=int, default=DEFAULTS["max_repos"],
                   help=f"cap on repositories read (default {DEFAULTS['max_repos']})")
    p.add_argument("--max-checks", type=int, default=DEFAULTS["max_checks"],
                   help=f"checks whose latest run is read, per repository (default {DEFAULTS['max_checks']})")
    p.add_argument("--runs-per-check", type=int, default=DEFAULTS["runs_per_check"],
                   help=f"runs listed per check to find the latest completed one (default {DEFAULTS['runs_per_check']})")
    p.add_argument("--budget-s", type=int, default=DEFAULTS["budget_s"],
                   help=f"wall-clock budget in seconds (default {DEFAULTS['budget_s']})")
    p.add_argument("--max-log-bytes", type=int, default=DEFAULTS["max_log_bytes"], help=argparse.SUPPRESS)
    p.add_argument("--json", action="store_true", help="the per-repository results as JSON")
    p.set_defaults(func=cmd_sync)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="workflow_sync", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

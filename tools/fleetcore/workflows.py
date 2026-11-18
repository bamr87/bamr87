#!/usr/bin/env python3
"""The fleet workflow model (`fleet-workflows/v1`, ADR 0007): every fleet repository's workflows, linted, with check states.

The atlas (`.github/scripts/dash-gen/workflow_atlas.py`) reads the hub's own
`.github/`. This is the same reading over the whole fleet, built from what
`tools/dash workflows sync` stored in the local lake, so every surface renders
ONE model (ADR 0007 decisions 1 and 2):

  repos     every repository in `_data/projects.yml` plus the hub, each with
            whether its last sync read it, when (`read_at`, the last read that
            worked) and, when it was not read, why. An external upstream is
            never read; a repository the sync has not reached says so. A
            repository that was not read shows "not read", never a pass.
  workflows each file the last read listed, through the atlas's own
            parse_workflow() and lint_workflow() — hub_rules only for the hub,
            whose fleet.yml keys they check. No second parser.
  checks    a state from the latest run of each workflow, ADR 0007 decision 4:

            verified      green, and it did its work
            passed-empty  green, but it checked nothing: every job skipped,
                          or the run said so (fleet-verify's "Not verified"
                          step or warning, a skipped scenario step)
            never-ran     no run on GitHub, one held for approval, or a
                          failure with no job
            quota         failed because a shared limit was spent (the API
                          quota, a Claude usage window or cap) — classify_failure
            real-failure  failed for a reason in the workflow or the code
            cancelled     cancelled before it finished

            A workflow whose runs were not read has no state (`unknown`).
            Fleet health counts `verified` only, so a green check that
            verified nothing is not healthy.

Read-only: the lake is opened `mode=ro`, nothing is fetched, nothing written.
`view()` is what the `fleet_workflows` MCP tool serves with `fleet=true`.

  python3 -m fleetcore.workflows [list|show|lint] [--repo R] [--json]   (tools/dash workflows --fleet …)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import yaml

SCHEMA = "fleet-workflows/v1"
ROOT_DEFAULT = Path(__file__).resolve().parents[2]
STATES = {
    "verified": "Green, and it did its work.",
    "passed-empty": "Green, but it checked nothing: every job was skipped, or the run itself said so.",
    "never-ran": "No run started: none on GitHub, one held for approval, or a failure with no job.",
    "quota": "Failed because a shared limit was spent (the API quota, a Claude usage window or cap): not a defect.",
    "real-failure": "Failed for a reason in the workflow or the code it checks; the cause and evidence say which.",
    "cancelled": "Cancelled before it finished, by a newer run or by hand.",
}
UNKNOWN = "unknown"  # the tally's name for a workflow whose runs were not read
HEALTHY = ("verified",)
FAILED = ("failure", "timed_out", "startup_failure")
NEVER = ("action_required", "stale")
WAITING = ("action_required", "waiting", "pending", "requested")
# fleet-verify.yml's own words for "green, and it ran nothing" — test_fleetcore_workflows.py holds
# these step names to the reusable workflow, so a rename there fails here instead of turning every
# empty verify run into `verified`.
EMPTY_STEPS = {"Report that nothing was verified": "success", "Run the user scenarios": "skipped"}
EMPTY_RX = re.compile(r"\bNot verified\b|no scenario ran|nothing to run", re.I)


class LakeError(RuntimeError):
    """The lake exists but cannot be read."""


# --------------------------------------------------------------------------- #
# the shared modules (dash-gen's own; no second parser)
# --------------------------------------------------------------------------- #
def _gen():
    """This checkout's atlas and sync modules: code, so always beside this file, whatever `root` the data is read from."""
    gen = str(ROOT_DEFAULT / ".github" / "scripts" / "dash-gen")
    if gen not in sys.path:  # once: a console that rebuilds the model must not grow sys.path each time
        sys.path.insert(0, gen)
    import workflow_atlas  # noqa: WPS433 — dash-gen's own modules, only when asked
    import workflow_sync  # noqa: WPS433
    return workflow_atlas, workflow_sync


def _yaml(path: Path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def lake_db(root: Path, lake_dir: Path | str | None = None) -> Path:
    """Where `tools/dash lake` and `workflows sync` keep it: DASH_LAKE_DIR, else .dash-lake/."""
    d = Path(lake_dir) if lake_dir else Path(os.environ.get("DASH_LAKE_DIR") or (Path(root) / ".dash-lake"))
    return d / "fleet.sqlite"


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


# --------------------------------------------------------------------------- #
# check states (pure)
# --------------------------------------------------------------------------- #
def _state(state: str | None, evidence: str, run: dict | None = None, **extra) -> dict:
    out = {"state": state, "evidence": evidence}
    if run:
        out["run"] = {k: run.get(k) for k in ("id", "event", "status", "conclusion", "head_branch",
                                              "created_at", "html_url")}
    return out | extra


def check_state(run: dict | None, jobs: list[dict] | None = None, steps: list[dict] | None = None,
                logs: list[str] | None = None, atlas=None) -> dict:
    """One workflow's state from its latest run. Pure: rows in, state out.

    jobs=None means the lake does not know the run's jobs (as opposed to []:
    GitHub listed none). steps carry `job` (the job's name), `name` and
    `conclusion`; logs are the run's stored log entries."""
    if atlas is None:
        atlas, _ = _gen()
    if run is None:
        return _state("never-ran", "No run of it on GitHub.")
    status, concl = str(run.get("status") or ""), str(run.get("conclusion") or "")
    if status != "completed":
        if status in WAITING:
            return _state("never-ran", f"Its latest run is {status}: held, never started.", run)
        return _state(None, f"Its latest run is {status or 'in an unknown status'}; no completed run was read.", run)
    if concl in NEVER:
        return _state("never-ran", f"Concluded {concl}: it never started.", run)
    if concl == "cancelled":
        return _state("cancelled", "Cancelled before it finished.", run)
    if concl == "skipped":
        return _state("passed-empty", "Every job was skipped.", run)
    if concl in FAILED:
        if jobs is not None and not jobs and concl != "startup_failure":
            return _state("never-ran", "Failed with no job: a run held for approval, or one that never started.", run)
        failed = next((f"{s.get('job')} › {s.get('name')}" for s in steps or [] if s.get("conclusion") == "failure"), None)
        c = atlas.classify_failure(logs or [], concl, failed)
        state = "quota" if c["cause"] == "api-rate-limit" or c["class"] == "capacity" else "real-failure"
        return _state(state, c["evidence"] or f"Concluded {concl}; the lake holds no log line that says why.", run,
                      cause=c["cause"], **{"class": c["class"]}, failed_step=failed)
    if concl in ("success", "neutral"):
        if jobs and all(str(j.get("conclusion")) == "skipped" for j in jobs):
            return _state("passed-empty", "Every job was skipped.", run)
        for s in steps or []:
            if EMPTY_STEPS.get(str(s.get("name"))) == s.get("conclusion"):
                return _state("passed-empty", f"Step '{s.get('name')}' {s.get('conclusion')}: no scenario ran.", run)
        warning = next((w for w in atlas._error_lines(logs or [])[2] if EMPTY_RX.search(w)), None)
        if warning:
            return _state("passed-empty", warning[:300], run)
        if concl == "neutral":
            return _state("passed-empty", "Concluded neutral: neither a pass nor a failure.", run)
        ran = sum(1 for j in jobs or [] if j.get("conclusion") not in ("skipped", None))
        return _state("verified", f"Green; {ran} job(s) ran." if jobs else "Green.", run)
    return _state(None, f"Concluded {concl or 'nothing'}.", run)


# --------------------------------------------------------------------------- #
# the model
# --------------------------------------------------------------------------- #
def _run_parts(conn: sqlite3.Connection, run_id: int) -> tuple[dict | None, list[dict], list[dict], list[str]]:
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    jobs = [dict(j) for j in conn.execute("SELECT * FROM jobs WHERE run_id=? ORDER BY id", (run_id,))]
    steps = [dict(s) | {"job": s["job_name"]} for s in conn.execute(
        "SELECT s.*, j.name AS job_name FROM steps s JOIN jobs j ON j.id = s.job_id "
        "WHERE j.run_id=? ORDER BY j.id, s.number", (run_id,))]
    logs = [r["text"] or "" for r in conn.execute("SELECT text FROM logs WHERE run_id=? ORDER BY entry", (run_id,))]
    return (dict(row) if row else None), jobs, steps, logs


def workflow_check(conn: sqlite3.Connection, nwo: str, path: str, looked: dict | None,
                   archived: bool, atlas) -> dict:
    """A workflow's state from what the sync looked up, else from the lake's runs, else unknown."""
    if looked is not None:
        if not looked.get("listed"):
            return _state(None, looked.get("error") or "Its runs were not listed.", source="workflows sync")
        if not looked.get("run_id"):
            return _state("never-ran", f"No run of it on GitHub (the sync listed {looked.get('runs', 0)}).",
                          source="workflows sync")
        run, jobs, steps, logs = _run_parts(conn, int(looked["run_id"]))
        if run is None:
            return _state(None, "The run the sync recorded is not in the lake.", source="workflows sync")
        known = jobs if (jobs or looked.get("jobs") == 0) else None
        return check_state(run, known, steps, logs, atlas) | {"source": "workflows sync"}
    if archived:
        return _state(None, "Archived: its runs are not read.", source="none")
    row = conn.execute("SELECT id FROM runs WHERE nwo=? AND workflow_path=? AND status='completed' "
                       "ORDER BY created_at DESC LIMIT 1", (nwo, path)).fetchone()
    if row is None:
        return _state(None, "Its runs were not read: the sync reads checks; `tools/dash lake sync` reads the rest.",
                      source="none")
    run, jobs, steps, logs = _run_parts(conn, int(row["id"]))
    return check_state(run, jobs or None, steps, logs, atlas) | {"source": "lake sync"}


def _workflow(conn, nwo: str, path: str, hub: str, is_hub: bool, fleet: dict, looked: dict | None,
              archived: bool, atlas, sync) -> dict:
    row = conn.execute("SELECT text, sha FROM workflows WHERE nwo=? AND path=?", (nwo, path)).fetchone()
    text = (row["text"] if row else "") or ""
    cfg = fleet if is_hub else {}
    try:
        wf = atlas.parse_workflow(path, text, hub)
    except Exception as exc:  # noqa: BLE001 — the model reports a file it cannot read; it never dies on one
        wf = atlas.parse_workflow(path, "", hub) | {"parse_error": f"{exc.__class__.__name__}: {exc}"[:200]}
    if row is None:
        wf["parse_error"] = "listed by the sync, but its text is not in the lake"
    atlas.join([wf], [], cfg, hub)
    try:
        findings = atlas.lint_workflow(wf, text, cfg, hub_rules=is_hub)
    except Exception as exc:  # noqa: BLE001 — a rule that cannot read a file reports it
        findings = [atlas._finding("parse-error", "workflow", wf["id"], path, f"{exc.__class__.__name__}: {exc}"[:200])]
    for f in findings:
        f["repo"] = nwo
    wf.update({"repo": nwo, "sha": row["sha"] if row else None, "group": atlas.derive_group(wf),
               "findings": findings, "tally": atlas._tally(findings), "check_kind": sync.check_kind(wf)})
    wf["check"] = workflow_check(conn, nwo, path, looked, archived, atlas)
    return wf


def _tally_checks(workflows: list[dict]) -> dict:
    out = {s: 0 for s in (*STATES, UNKNOWN)}
    for w in workflows:
        if w.get("check_kind"):
            out[w["check"]["state"] or UNKNOWN] += 1
    return out


def _repo(conn, t: dict, read: dict | None, lake_present: bool, hub: str, fleet: dict, atlas, sync) -> dict:
    r = {k: t.get(k) for k in ("nwo", "name", "category", "status", "hub", "owned")}
    r.update({"read": False, "read_at": None, "attempted_at": None, "reason": None, "archived": None,
              "default_branch": None, "files": 0, "truncated": False, "workflows": []})
    if not t["owned"]:
        r["reason"] = t["reason"]
    elif not lake_present:
        r["reason"] = "no lake on this machine: run `tools/dash workflows sync`"
    elif read is None:
        r["reason"] = "never read: run `tools/dash workflows sync`"
    else:
        r.update({"read_at": read.get("read_at"), "attempted_at": read.get("attempted_at"),
                  "reason": read.get("reason"), "archived": bool(read.get("archived")),
                  "default_branch": read.get("default_branch"), "files": int(read.get("files") or 0),
                  "truncated": bool(read.get("truncated"))})
        if read.get("ok"):
            r["read"] = True
            looked = json.loads(read.get("checks") or "{}")
            r["workflows"] = [_workflow(conn, t["nwo"], p, hub, bool(t["hub"]), fleet, looked.get(p),
                                        r["archived"], atlas, sync)
                              for p in json.loads(read.get("paths") or "[]")]
        elif read.get("read_at"):
            r["reason"] = f"{read.get('reason')} (last read {read['read_at']})"
    r["findings"] = atlas._tally(f for w in r["workflows"] for f in w["findings"])
    r["checks"] = _tally_checks(r["workflows"])
    verify = next((w for w in r["workflows"] if w["check_kind"] == "verify"), None)
    r["verify"] = (verify["check"]["state"] or UNKNOWN) if verify else None
    return r


def build(root: Path | str = ROOT_DEFAULT, lake_dir: Path | str | None = None) -> dict:
    """The fleet-workflows/v1 document. Every surface renders this."""
    root = Path(root)
    atlas, sync = _gen()
    fleet = _yaml(root / "_data" / "fleet.yml") or {}
    registry = _yaml(root / "_data" / "projects.yml") or []
    hub = str((fleet.get("hub") or {}).get("repo") or atlas.HUB_DEFAULT)
    db = lake_db(root, lake_dir)
    plan = sync.targets(registry, fleet)
    reads: dict[str, dict] = {}
    conn = None
    if db.is_file():
        try:
            conn = _connect(db)
            reads = {r["nwo"]: dict(r) for r in conn.execute("SELECT * FROM workflow_reads")}
        except sqlite3.Error as exc:
            if "no such table" not in str(exc):  # a lake older than the sync has simply read nothing yet
                if conn is not None:
                    conn.close()
                raise LakeError(f"cannot read {db}: {exc}") from None
    try:
        repos = [_repo(conn, t, reads.get(t["nwo"]), conn is not None, hub, fleet, atlas, sync) for t in plan]
    finally:
        if conn is not None:
            conn.close()
    workflows = [w for r in repos for w in r["workflows"]]
    stamps = sorted(r["read_at"] for r in repos if r["read"] and r["read_at"])
    verify = [r for r in repos if r["verify"]]
    return {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hub": hub,
        "lake": {"path": str(db), "present": db.is_file()},
        "states": STATES,
        "summary": {
            "repos": len(repos), "read": sum(1 for r in repos if r["read"]),
            "not_read": sum(1 for r in repos if not r["read"]),
            "external": sum(1 for r in repos if not r["owned"]),
            "workflows": len(workflows), "files": sum(r["files"] for r in repos if r["read"]),
            "truncated": [r["nwo"] for r in repos if r["read"] and r["truncated"]],
            "oldest_read_at": stamps[0] if stamps else None, "newest_read_at": stamps[-1] if stamps else None,
            "findings": atlas._tally(f for w in workflows for f in w["findings"]),
            "checks": _tally_checks(workflows),
            "healthy_checks": sum(1 for w in workflows if w["check_kind"] and w["check"]["state"] in HEALTHY),
            "verify": {s: sum(1 for r in verify if r["verify"] == s) for s in (*STATES, UNKNOWN)},
        },
        "repos": repos,
    }


# --------------------------------------------------------------------------- #
# views (what the MCP tool and the CLI print)
# --------------------------------------------------------------------------- #
REPO_FIELDS = ("nwo", "name", "owned", "read", "read_at", "reason", "archived", "files", "truncated",
               "findings", "checks", "verify")


def repo_brief(r: dict) -> dict:
    return {k: r.get(k) for k in REPO_FIELDS} | {"workflows": len(r["workflows"])}


def workflow_brief(w: dict) -> dict:
    c = w["check"]
    return {"id": w["id"], "file": w["file"], "name": w["name"], "group": w["group"], "triggers": w["triggers"],
            "crons": [x["human"] for x in w["crons"]], "switch": w["switch"], "ai_sites": len(w["ai_sites"]),
            "check_kind": w["check_kind"], "state": c["state"], "evidence": c["evidence"],
            "run_url": (c.get("run") or {}).get("html_url"), "tally": w["tally"], "parse_error": w["parse_error"]}


def find_repo(model: dict, key: str) -> dict:
    k = key.strip().lower()
    hits = [r for r in model["repos"] if k in (r["nwo"].lower(), r["nwo"].split("/", 1)[1].lower(),
                                               str(r.get("name") or "").lower())]
    if not hits:
        raise KeyError(f"no fleet repository called {key!r} (an owner/name or a registry name)")
    return hits[0]


def find_workflow(repo: dict, key: str) -> dict:
    k = key.strip()
    hit = next((w for w in repo["workflows"] if k in (w["id"], w["file"], Path(w["file"]).name)), None)
    if hit is None:
        why = "it was not read" if not repo["read"] else "no such workflow"
        raise KeyError(f"{repo['nwo']} has no workflow {key!r} in the model ({why})")
    return hit


def view(root: Path | str = ROOT_DEFAULT, repo: str = "", workflow: str = "",
         lake_dir: Path | str | None = None) -> dict:
    """The fleet catalog (one row per repository), one repository's workflows, or one workflow in full."""
    m = build(root, lake_dir)
    head = {"schema": m["schema"], "generated_at": m["generated_at"], "lake": m["lake"]}
    if not repo:
        return head | {"summary": m["summary"], "states": m["states"],
                       "repos": [repo_brief(r) for r in m["repos"]]}
    r = find_repo(m, repo)
    if not workflow:
        return head | {"repo": repo_brief(r), "workflows": [workflow_brief(w) for w in r["workflows"]],
                       "states": m["states"]}
    return head | {"repo": repo_brief(r), "workflow": find_workflow(r, workflow)}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _age(stamp: str | None, now: dt.datetime | None = None) -> str:
    if not stamp:
        return "never"
    try:
        then = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)
    hours = ((now or dt.datetime.now(dt.timezone.utc)) - then).total_seconds() / 3600
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def _checks_line(t: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in t.items() if v) or "no checks"


def cmd_list(args: argparse.Namespace) -> int:
    m = build(args.root, args.lake)
    s = m["summary"]
    if args.json:
        print(json.dumps(view(args.root, args.repo or "", "", args.lake) if args.repo else m, indent=2, default=str))
        return 0
    if args.repo:
        r = find_repo(m, args.repo)
        print(f"{r['nwo']} · {'read ' + _age(r['read_at']) if r['read'] else 'NOT READ'}"
              f"{' · ' + r['reason'] if r['reason'] else ''}")
        for w in r["workflows"]:
            c = w["check"]
            f = w["tally"]
            flag = f"✖{f['error']}" if f["error"] else f"⚠{f['warn']}" if f["warn"] else ""
            state = (c["state"] or UNKNOWN) if w["check_kind"] else ""
            print(f"  {w['group']:<9} {w['id']:<28} {','.join(w['triggers'])[:40]:<40} {state:<13} {flag}")
        return 0
    print(f"{SCHEMA} · {s['read']} of {s['repos']} repos read ({s['external']} external) · {s['workflows']} workflows"
          f" · findings " + " ".join(f"{k}={v}" for k, v in s["findings"].items())
          + f" · lake {'present' if m['lake']['present'] else 'MISSING: ' + m['lake']['path']}")
    print(f"  checks: {_checks_line(s['checks'])} · healthy {s['healthy_checks']}"
          f" · verify: {_checks_line(s['verify'])}")
    for r in m["repos"]:
        if not r["read"]:
            continue
        f = r["findings"]
        print(f"  {r['nwo']:<42} {len(r['workflows']):>3} wf  read {_age(r['read_at']):<8} "
              f"✖{f['error']:<3} ⚠{f['warn']:<4} {_checks_line(r['checks'])}")
    missed = [r for r in m["repos"] if not r["read"]]
    if missed:
        print(f"  not read ({len(missed)}):")
        for r in missed:
            print(f"    {r['nwo']:<42} {r['reason']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        doc = view(args.root, args.repo_id, args.workflow or "", args.lake)
    except KeyError as exc:
        sys.stderr.write(f"{exc.args[0]}\n")
        return 1
    print(json.dumps(doc, indent=2, default=str))
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    m = build(args.root, args.lake)
    repos = [find_repo(m, args.repo)] if args.repo else m["repos"]
    findings = [f for r in repos for w in r["workflows"] for f in w["findings"]]
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        mark = {"error": "✖", "warn": "⚠", "info": "·"}
        for f in findings:
            where = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
            print(f"  {mark[f['severity']]} {f['severity']:<5} {f['rule']:<16} {f['repo']:<36} {where}  {f['message']}")
        t = {s: sum(1 for f in findings if f["severity"] == s) for s in ("error", "warn", "info")}
        unread = [r["nwo"] for r in repos if not r["read"]]
        print(f"{t['error']} error(s), {t['warn']} warning(s) in {len(repos) - len(unread)} read repos"
              + (f"; {len(unread)} not read (tools/dash workflows --fleet list says why)" if unread else ""))
    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    return 1 if errors or (args.strict and warns) else 0


def main(argv: list[str] | None = None) -> int:
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if a != "--fleet"]  # `dash workflows --fleet …`
    ap = argparse.ArgumentParser(prog="dash workflows --fleet", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT_DEFAULT), help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("list", help="one line per repository (or per workflow with --repo), and what was not read")
    p.add_argument("--repo", default="", help="one repository: owner/name or registry name")
    p.add_argument("--lake", default=None, help="lake directory (default DASH_LAKE_DIR, else .dash-lake/)")
    p.add_argument("--json", action="store_true", help="the fleet-workflows/v1 document")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("show", help="one repository, or one of its workflows in full, as JSON")
    p.add_argument("repo_id", metavar="repo")
    p.add_argument("workflow", nargs="?", default="")
    p.add_argument("--lake", default=None)
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("lint", help="every read workflow's findings (hub-only rules apply to the hub); exit 1 on an error")
    p.add_argument("--repo", default="")
    p.add_argument("--lake", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 on a warning too")
    p.set_defaults(func=cmd_lint)
    if not argv or argv[0] not in ("list", "show", "lint", "-h", "--help", "--root"):
        argv = ["list", *argv]  # bare `dash workflows --fleet [--json]` is the list
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        args = ap.parse_args([*argv, "list"])
    try:
        return args.func(args)
    except KeyError as exc:
        sys.stderr.write(f"{exc.args[0]}\n")
        return 1
    except LakeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

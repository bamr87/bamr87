#!/usr/bin/env python3
"""Harness Console MCP server — the console's HTTP API for any MCP client.

Read tools wrap the console's GET routes (fleet, harness health and scorecard,
live snapshot, sessions, jobs and logs, spend, the data lake's traces and
workflow lines, observability, semantic code search, deep dive, work board,
one work item, a work-board plan's preview).
Write tools (run an allowlisted op, cancel a job, flip a workflow kill switch)
are NOT registered unless HARNESS_MCP_ALLOW_WRITES=1, are annotated
destructive, and every one also needs confirm=true per call; the console's own
allowlist and confirm-before-GitHub-write gate still apply server-side.
Scoped write tools (HARNESS_MCP_SCOPES=jobs,work) grant narrow slices instead:
job_dispatch / job_cancel for a short allowlist of local, $0 report ops, and
work_apply for Work-board priority, pins and notes — each confirm-gated,
capped, time-limited and written to an append-only audit log.

Transports
  stdio            python3 -m mcp_layer.server               (Claude Code, Cursor, local agents)
  streamable HTTP  python3 -m mcp_layer.server --http [--port 4002]
                   binds 127.0.0.1, requires `Authorization: Bearer <HARNESS_MCP_TOKEN>`
                   (its own token, never the console's), refuses to start without one.
  --fleet-compat   also registers the legacy `fleet` server's console_run / console_cancel (the merged
                   tools/fleetcore/mcp_server.py; `.mcp.json` `fleet` runs this), whose writing ops the console
                   itself refuses without confirm=true.

Env: DASH_CONSOLE_URL (default http://127.0.0.1:4001), DASH_CONSOLE_TOKEN,
HARNESS_MCP_TOKEN, HARNESS_MCP_ALLOW_WRITES, HARNESS_MCP_SCOPES, HARNESS_MCP_AUDIT,
HARNESS_MCP_HOST, HARNESS_MCP_PORT, HARNESS_MCP_MAX_CHARS (default 60000).
Tokens are never printed or returned.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal, NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/console, for mcp_layer

from mcp.server.mcpserver import Context, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from mcp_layer.client import ROOT, Console, ConsoleError, dotenv_value  # noqa: E402

VERSION = "0.2.0"
INSTRUCTIONS = (
    "bamr87 Harness Console: the fleet's control plane. Start with console_overview, then drill in: "
    "fleet_status, harness_health, live_snapshot, claude_telemetry, jobs_list/job_log, spend_vs_budget, lake_runs, workflow_lines, "
    "code_search, deep_dive. To reprioritize open work: work_board, work_item, then work_preview(plan) — it writes "
    "nothing and returns a plan_id — then, only after the user approves that diff, work_apply(plan, plan_id, "
    "confirm=true). job_dispatch starts one allowlisted report op after the user approves it. Write tools exist only "
    "when the operator enabled them (console_overview says which); each needs confirm=true and you must ask the user "
    "before setting it."
)
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
# The scoped tools change local state only (a console job running a report, a working-tree edit git can
# undo), so they are closed-world; they are still marked destructive, like every write tool (NFR9), so a
# client asks before each call.
SCOPED = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
ROW_FIELDS = ("name", "status", "category", "featured", "worst_level", "health", "triage_level", "triage_score",
              "ci_last", "ci_pass", "last_commit_days", "failing", "reasons", "docker_up", "docker_total", "repo_url")

# ---------------------------------------------------------------- work board
# /api/work is the WHOLE board — 394 items and ~390k characters of JSON, of
# which each item's `detail` (its issue record, spec tasks, gaps) is a quarter.
# Handed to a client whole it was clipped to a prefix and read as nothing, so
# the tool pages and summarises instead: these are the fields that identify and
# rank an item, and the blocks that give the page its context.
BOARD_FIELDS = ("key", "kind", "ref", "title", "repo", "nwo", "lane", "stage", "priority", "priority_source",
                "rank", "size", "age_days", "idle_days", "readiness", "autonomy", "labels", "next_run", "loop",
                "progress", "note")
BOARD_BLOCKS = ("schema", "generated_at", "preview", "lanes", "loops", "totals", "sources", "labels",
                "priorities", "roadmap_statuses", "hints", "queue_path")
BOARD_TITLE_CHARS = 140
BOARD_FILTERS = ("lane", "repo", "kind", "stage", "priority")


def truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def compact_item(item: dict, title_chars: int = BOARD_TITLE_CHARS) -> dict:
    """One board row without its `detail`, empty fields dropped, title cut.

    `work_item`/`fleet_work` are where an item's record belongs; a board page
    only has to say what the item is and where it sits in the queue.
    """
    row = {k: item[k] for k in BOARD_FIELDS if item.get(k) not in (None, "", [], {})}
    title = row.get("title")
    if isinstance(title, str) and len(title) > title_chars:
        row["title"] = title[: title_chars - 1] + "…"
    return row


def board_matches(item: dict, filters: dict, q: str = "") -> bool:
    for field, want in filters.items():
        if want and str(item.get(field) or "").lower() != want.lower():
            return False
    if q:
        hay = " ".join(str(item.get(k) or "") for k in ("key", "title", "repo", "nwo", "ref", "labels")).lower()
        if q.lower() not in hay:
            return False
    return True


def board_page(board: dict, summary: bool = True, limit: int = 40, offset: int = 0,
               q: str = "", **filters: str) -> dict:
    """A filtered, paged, optionally compact slice of /api/work.

    Pure over the board document, so the sizes this promises are testable
    without a console. `next_offset` is None on the last page.
    """
    items = board.get("items") or []
    active = {k: (filters.get(k) or "") for k in BOARD_FILTERS}
    rows = [i for i in items if board_matches(i, active, q)] if (q or any(active.values())) else list(items)
    # Full items are ~1k characters each; a page of them has to stay small.
    limit = max(1, min(int(limit), 200 if summary else 25))
    offset = max(0, int(offset))
    page = rows[offset: offset + limit]
    by_lane: dict[str, int] = {}
    for row in rows:
        lane = str(row.get("lane") or "?")
        by_lane[lane] = by_lane.get(lane, 0) + 1
    return {
        **{k: board[k] for k in BOARD_BLOCKS if k in board},
        "filters": {k: v for k, v in {**active, "q": q}.items() if v},
        "summary": summary,
        "total": len(items),
        "matched": len(rows),
        "matched_by_lane": by_lane,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "items": [compact_item(i) for i in page] if summary else page,
    }


# ------------------------------------------------------------------- docker
# The console's compose service is given no Docker socket on purpose: a
# write-capable console holding one is root on the Docker host. So from there
# every host errors and `containers: []` reads as "nothing is running", which
# is the opposite of true. Name the cause and where to look instead.
DOCKER_SOCKET_HINTS = ("docker.sock", "cannot connect to the docker daemon", "is the docker daemon running")
DOCKER_REMEDY = ("Containers are invisible from here, not absent. Read them from a host terminal "
                 "(`tools/dash docker ps`, or `tools/dash tui` → Docker), or point the console at a "
                 "reachable host with DASH_DOCKER_HOST. The console's container is deliberately given "
                 "no /var/run/docker.sock — holding it would make a write-capable console root on the "
                 "Docker host (docs/CONTAINERS.md).")


def docker_reason(error: str) -> str:
    """The host's raw error, classified into something an agent can act on."""
    low = (error or "").lower()
    if any(h in low for h in DOCKER_SOCKET_HINTS):
        return "no Docker socket in this process (by design)"
    if "ssh" in low:
        return "ssh to the host failed"
    return (error or "unknown error").strip().splitlines()[0][:200]


def docker_report(doc: dict) -> dict:
    """The docker view plus a per-host diagnosis, or a raised-ready message when no host answered."""
    hosts = list(doc.get("hosts") or [])
    errors = {h: str(e) for h, e in (doc.get("errors") or {}).items() if e}
    reachable = [h for h in hosts if h not in errors]
    out = {**doc, "reachable_hosts": reachable,
           "unreachable_hosts": {h: docker_reason(e) for h, e in errors.items()}}
    if hosts and not reachable:
        out["advice"] = DOCKER_REMEDY
    return out


def docker_error_text(report: dict) -> str | None:
    """The one-line error for a docker view where no host answered at all."""
    if report.get("reachable_hosts") or not report.get("unreachable_hosts"):
        return None
    why = "; ".join(f"{h}: {r}" for h, r in report["unreachable_hosts"].items())
    return f"no Docker host is reachable from the console ({why}). {DOCKER_REMEDY}"


def max_chars() -> int:
    try:
        return max(2000, int(os.environ.get("HARNESS_MCP_MAX_CHARS", "60000")))
    except ValueError:
        return 60000


def clip(obj: Any, limit: int | None = None) -> Any:
    """Keep a tool result inside the client's context: oversized payloads become a marked, truncated string."""
    limit = limit or max_chars()
    text = json.dumps(obj, default=str)
    if len(text) <= limit:
        return obj
    return {"truncated": True, "total_chars": len(text), "json_prefix": text[:limit]}


# ------------------------------------------------------ scoped write access
# HARNESS_MCP_ALLOW_WRITES is all or nothing: run_op passes the console's own
# confirm, so one agent-set flag reaches every allowlisted op — secret pushes,
# key rotation, deploys, workflow dispatch, the observe reset. A remote agent
# that should only start a report or reorder the Work board gets a scope:
#   jobs   job_dispatch / job_cancel for DISPATCH_OPS only — local, $0 reports
#          and checks that write nothing to GitHub, read or write no secret and
#          start or destroy no container. The console is sent confirm=false, so
#          its own gate refuses anything remote even if this list were wrong.
#   work   work_apply — priority, pins, unpin and notes on the Work board: the
#          working tree's _data/work_queue.yml (and a roadmap entry's priority),
#          never a GitHub label move or a roadmap status change, never a commit.
# HARNESS_MCP_ALLOW_WRITES=1 implies every scope. Neither scope writes to
# GitHub, so neither is a § 11 write-back path.
SCOPES = ("jobs", "work")

# op -> the params a client may pass and the wall clock the layer allows it.
DISPATCH_OPS: dict[str, dict] = {
    "config-show": {"params": ("key",), "limit_s": 120},
    "status": {"params": (), "limit_s": 300},
    "audit": {"params": (), "limit_s": 600},
    "drift": {"params": (), "limit_s": 900},
    "schema-lint": {"params": (), "limit_s": 600},
    "workflows-lint": {"params": (), "limit_s": 600},
    "observe-status": {"params": (), "limit_s": 300},
    "observe-verify": {"params": (), "limit_s": 300},
    "lake-status": {"params": (), "limit_s": 300},
    "refine-surface": {"params": ("target",), "limit_s": 900},
}
DISPATCH_PARAM_RX = re.compile(r"^[A-Za-z0-9._/-]{0,64}$")
DISPATCH_WAIT_MAX_S = 120
DISPATCH_POLL_S = 2.0
DISPATCH_RUNNING_MAX = 2
DISPATCH_PER_HOUR = 20
DISPATCH_LOG_TAIL = 4000
JOB_ID_RX = re.compile(r"^[0-9a-f]{12}$")
JOB_DONE = ("succeeded", "failed", "cancelled", "interrupted")

# A plan is what the board's drag, pin and priority controls send (dash-gen
# work_board.PLAN_KEYS); the work scope takes the prioritising half of it.
WORK_PLAN_KEYS = ("priority", "pins", "unpin", "notes")
WORK_PLAN_OUTSIDE = {
    "stage": "moves an issue's labels on GitHub (or a roadmap entry's status)",
    "roadmap_status": "changes a roadmap entry's lifecycle status",
    "roadmap_reason": "rewrites a roadmap entry's recorded reason",
}
WORK_PRIORITIES = ("P0", "P1", "P2", "P3", "")
WORK_PLAN_MAX_KEYS = 25
WORK_NOTE_CHARS = 500
WORK_KEY_RX = re.compile(r"^(issue|pr|roadmap|spec|backlog):[A-Za-z0-9_.:/#-]{1,200}$")
WORK_LANE_RX = re.compile(r"^[a-z]{1,20}$")
WORK_APPLY_PER_HOUR = 30
WORK_DIFF_CHARS = 8000
WORK_SNAPSHOT = ("lane", "rank", "priority", "priority_source", "note")
PLAN_DOC = ("plan fields (any subset): priority {key: P0|P1|P2|P3, or \"\" to clear an override}; "
            "pins {lane: [keys in the order the loops should take them], [] clears the lane's order}; "
            "unpin [keys]; notes {key: text, or \"\" to clear}. Keys are board keys from work_board "
            "(issue:owner/repo#N, pr:owner/repo#N, roadmap:FF-NNNN, spec:…, backlog:…).")

# Token-shaped strings never reach an audit line, whatever an argument carried.
SECRETISH_RX = re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-ant-[A-Za-z0-9_-]{8,}"
                          r"|(?i:bearer)\s+\S+|[A-Za-z0-9_\-]{40,})")


def granted_scopes(value: str | None, writes: bool = False) -> tuple[frozenset[str], list[str]]:
    """(the scopes granted, the names asked for that are not scopes). Unknown names grant nothing."""
    asked = [s.strip().lower() for s in (value or "").split(",") if s.strip()]
    ignored = sorted({s for s in asked if s not in SCOPES})
    return (frozenset(SCOPES) if writes else frozenset(s for s in asked if s in SCOPES)), ignored


def scrub(obj: Any) -> Any:
    if isinstance(obj, str):
        return SECRETISH_RX.sub("<redacted>", obj)
    if isinstance(obj, dict):
        return {str(k): scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def audit_file() -> Path:
    p = os.environ.get("HARNESS_MCP_AUDIT")
    return Path(p).expanduser() if p else ROOT / ".fleet" / "mcp" / "audit.jsonl"


class Audit:
    """One append-only JSON line per scoped write call — done, refused or failed.

    It goes to HARNESS_MCP_AUDIT (default .fleet/mcp/audit.jsonl, gitignored)
    and always to stderr, which the sidecar's json-file log keeps and the log
    plane ships; where the file cannot be written (a read-only mount) stderr is
    the record. Values are scrubbed. `client` is the name the client gave in
    initialize — a label, never an identity: the bearer token is the gate.
    """

    def __init__(self, path: Path | None = None, stream=None):
        self.path = path or audit_file()
        self.stream = stream
        self._lock = threading.Lock()

    def record(self, **rec: Any) -> str:
        rec = scrub({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **rec})
        line = json.dumps(rec, default=str, sort_keys=True)
        with self._lock:
            print("harness-mcp audit " + line, file=self.stream or sys.stderr, flush=True)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                return str(self.path)
            except OSError:
                return "stderr"


class RateCap:
    """At most `n` takes per rolling `window` seconds."""

    def __init__(self, n: int, window: float = 3600.0, clock=time.monotonic):
        self.n, self.window, self.clock = n, window, clock
        self.stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self, what: str) -> None:
        now = self.clock()
        with self._lock:
            while self.stamps and now - self.stamps[0] > self.window:
                self.stamps.popleft()
            if len(self.stamps) >= self.n:
                raise ToolError(f"refused: {what} is capped at {self.n} per hour — try again later")
            self.stamps.append(now)


class Dispatcher:
    """Admission and the wall clock for the jobs this process started through job_dispatch.

    The console's job manager runs a job until it exits, so the layer keeps a
    limit per op: sweep() drops finished jobs and cancels any past its op's
    limit_s, and a daemon thread runs it every few seconds while one is live.
    At most DISPATCH_RUNNING_MAX run at once and DISPATCH_PER_HOUR start per
    hour. The state is this process's: a restart forgets the deadlines (each
    allowlisted op ends on its own), while the console's job index keeps the jobs.
    """

    def __init__(self, console: Console, audit: Audit, clock=time.monotonic, interval: float = 5.0,
                 watch: bool = True):
        self.c, self.audit, self.clock, self.interval, self.watch = console, audit, clock, interval, watch
        self.live: dict[str, tuple[str, float]] = {}     # job id -> (op, deadline on self.clock)
        self.hourly = RateCap(DISPATCH_PER_HOUR, clock=clock)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def admit(self) -> None:
        self.sweep()
        with self._lock:
            running = len(self.live)
        if running >= DISPATCH_RUNNING_MAX:
            raise ToolError(f"refused: {running} dispatched job(s) still running (at most {DISPATCH_RUNNING_MAX}) "
                            "— wait for one to finish (job_log) or stop it (job_cancel)")
        self.hourly.take("job_dispatch")

    def track(self, job_id: str, op: str, limit_s: int) -> None:
        with self._lock:
            self.live[job_id] = (op, self.clock() + limit_s)
            start = self.watch and (self._thread is None or not self._thread.is_alive())
            if start:
                self._thread = threading.Thread(target=self._loop, name="harness-mcp-dispatch-watch", daemon=True)
        if start:
            self._thread.start()

    def forget(self, job_id: str) -> None:
        with self._lock:
            self.live.pop(job_id, None)

    def sweep(self) -> list[str]:
        """Drop finished jobs and cancel overdue ones; returns the ids it cancelled."""
        with self._lock:
            items = list(self.live.items())
        if not items:
            return []
        try:
            status = {j.get("id"): j.get("status") for j in self.c.get("/api/jobs") or []}
        except ConsoleError:
            return []
        cancelled = []
        for jid, (op, deadline) in items:
            st = status.get(jid)
            if st is None or st in JOB_DONE:
                self.forget(jid)
            elif self.clock() > deadline:
                try:
                    self.c.post(f"/api/jobs/{jid}/cancel", {})
                    outcome = "cancelled: past its limit"
                except ConsoleError as e:
                    outcome = f"cancel failed: {e}"
                self.audit.record(tool="job_dispatch", scope="jobs", job_id=jid, op=op, outcome=outcome,
                                  limit_s=DISPATCH_OPS.get(op, {}).get("limit_s"))
                self.forget(jid)
                cancelled.append(jid)
        return cancelled

    def _loop(self) -> None:
        while True:
            time.sleep(self.interval)
            self.sweep()
            with self._lock:
                if not self.live:
                    self._thread = None
                    return


def check_dispatch(op: str, params: dict | None) -> tuple[str, dict, int]:
    """(op, params, limit_s) once the op is on DISPATCH_OPS and every param is one it declares."""
    spec = DISPATCH_OPS.get(op)
    if spec is None:
        raise ToolError(f"refused: {op!r} is not on the job_dispatch allowlist ({', '.join(sorted(DISPATCH_OPS))}); "
                        "anything else runs from the console, where a person starts it")
    params = params or {}
    if not isinstance(params, dict):
        raise ToolError("params must be an object")
    extra = sorted(set(params) - set(spec["params"]))
    if extra:
        allowed = ", ".join(spec["params"]) or "none"
        raise ToolError(f"refused: {op} takes no param(s) {extra} here (allowed: {allowed})")
    clean = {}
    for k, v in params.items():
        if not isinstance(v, (str, int)) or isinstance(v, bool) or not DISPATCH_PARAM_RX.match(str(v)):
            raise ToolError(f"refused: param {k!r} must be a short plain value ([A-Za-z0-9._/-], ≤ 64 chars)")
        clean[k] = str(v)
    return op, clean, int(spec["limit_s"])


def _keys(value: Any, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
        raise ToolError(f"{what} must be a list of board keys")
    bad = [k for k in value if not WORK_KEY_RX.match(k)]
    if bad:
        raise ToolError(f"{bad[0]!r} is not a board key — {PLAN_DOC}")
    return list(dict.fromkeys(value))


def check_plan(plan: Any) -> dict:
    """The plan in canonical form, once it is a prioritising plan of bounded size."""
    if not isinstance(plan, dict) or not plan:
        raise ToolError(f"plan must be a non-empty object — {PLAN_DOC}")
    for field, effect in WORK_PLAN_OUTSIDE.items():
        if field in plan:
            raise ToolError(f"refused: `{field}` {effect} — outside work-board prioritisation; make that change on "
                            "the console's Work board (/work), where a person confirms it")
    unknown = sorted(set(plan) - set(WORK_PLAN_KEYS))
    if unknown:
        raise ToolError(f"unknown plan field(s) {unknown} — {PLAN_DOC}")
    out: dict[str, Any] = {}
    if plan.get("priority"):
        pr = plan["priority"]
        if not isinstance(pr, dict):
            raise ToolError("priority must be an object {key: P0..P3 or \"\"}")
        _keys(list(pr), "priority")
        bad = [k for k, v in pr.items() if v not in WORK_PRIORITIES]
        if bad:
            raise ToolError(f"{bad[0]}: priority must be one of P0, P1, P2, P3 or \"\" (clear the override)")
        out["priority"] = {k: pr[k] for k in sorted(pr)}
    if plan.get("pins"):
        pins = plan["pins"]
        if not isinstance(pins, dict) or not all(isinstance(k, str) and WORK_LANE_RX.match(k) for k in pins):
            raise ToolError("pins must be an object {lane: [keys]} with lane ids from work_board")
        out["pins"] = {lane: _keys(pins[lane], f"pins.{lane}") for lane in sorted(pins)}
    if plan.get("unpin"):
        out["unpin"] = sorted(_keys(plan["unpin"], "unpin"))
    if plan.get("notes"):
        notes = plan["notes"]
        if not isinstance(notes, dict) or not all(isinstance(v, str) for v in notes.values()):
            raise ToolError("notes must be an object {key: text}")
        _keys(list(notes), "notes")
        long = [k for k, v in notes.items() if len(v) > WORK_NOTE_CHARS]
        if long:
            raise ToolError(f"{long[0]}: a note is at most {WORK_NOTE_CHARS} characters")
        out["notes"] = {k: notes[k].strip() for k in sorted(notes)}
    if not out:
        raise ToolError(f"the plan changes nothing — {PLAN_DOC}")
    named = plan_keys(out)
    if len(named) > WORK_PLAN_MAX_KEYS:
        raise ToolError(f"refused: the plan names {len(named)} items; at most {WORK_PLAN_MAX_KEYS} per plan")
    return out


def plan_keys(plan: dict) -> set[str]:
    keys = set(plan.get("priority") or {}) | set(plan.get("notes") or {}) | set(plan.get("unpin") or [])
    for lane_keys in (plan.get("pins") or {}).values():
        keys |= set(lane_keys)
    return keys


def board_index(board: dict) -> tuple[dict, dict, dict]:
    """(item by key, position within its lane, the lane's pinned keys in pin order)."""
    by_key, pos, pinned = {}, {}, {}
    seen: dict[str, int] = {}
    for it in board.get("items") or []:
        key, lane = it.get("key"), it.get("lane")
        by_key[key] = it
        pos[key] = seen.get(lane, 0)
        seen[lane] = pos[key] + 1
        if it.get("rank") is not None:
            pinned.setdefault(lane, []).append((it["rank"], key))
    return by_key, pos, {lane: [k for _, k in sorted(v)] for lane, v in pinned.items()}


def touched_lanes(plan: dict, by_key: dict) -> list[str]:
    lanes = set(plan.get("pins") or {})
    lanes |= {by_key[k].get("lane") for k in plan.get("unpin") or [] if k in by_key}
    return sorted(x for x in lanes if x)


def plan_state(plan: dict, board: dict) -> dict:
    """What the plan's targets look like now: the fields it would change, per key and per touched lane."""
    by_key, _, pinned = board_index(board)
    lanes = touched_lanes(plan, by_key)
    keys = plan_keys(plan) | {k for lane in lanes for k in pinned.get(lane, [])}
    return {"items": {k: ({f: by_key[k].get(f) for f in WORK_SNAPSHOT} if k in by_key else None) for k in sorted(keys)},
            "pins": {lane: pinned.get(lane, []) for lane in lanes}}


def plan_id_for(plan: dict, board: dict) -> str:
    """Deterministic over the plan and its targets' current state: a board that moved under a preview
    gives a different id, so an apply of that preview is refused."""
    doc = json.dumps({"plan": plan, "state": plan_state(plan, board)}, sort_keys=True, default=str)
    return hashlib.sha256(doc.encode()).hexdigest()[:16]


def undo_plan(plan: dict, board: dict) -> dict:
    """The plan that puts every target back the way `board` shows it."""
    by_key, _, pinned = board_index(board)
    undo: dict[str, Any] = {}
    if plan.get("priority"):
        pr = {}
        for k in plan["priority"]:
            it = by_key.get(k)
            if k.startswith("roadmap:"):
                if it and it.get("priority"):
                    pr[k] = it["priority"]          # a roadmap entry always has one
            else:
                pr[k] = it["priority"] if it and it.get("priority_source") == "override" else ""
        if pr:
            undo["priority"] = pr
    if plan.get("notes"):
        undo["notes"] = {k: ((by_key.get(k) or {}).get("note") or "") for k in plan["notes"]}
    lanes = touched_lanes(plan, by_key)
    if lanes:
        undo["pins"] = {lane: pinned.get(lane, []) for lane in lanes}
    return undo


def plan_rows(plan: dict, before: dict, after: dict) -> list[dict]:
    """Before → after for every item the plan names or reorders, unchanged ones left out."""
    b_by, b_pos, _ = board_index(before)
    a_by, a_pos, _ = board_index(after)
    keys = set(plan_state(plan, before)["items"]) | {k for lane in (plan.get("pins") or {})
                                                     for k in board_index(after)[2].get(lane, [])}
    rows = []
    for k in sorted(keys):
        b, a = b_by.get(k), a_by.get(k)
        snap_b = {**{f: b.get(f) for f in WORK_SNAPSHOT}, "position": b_pos.get(k)} if b else None
        snap_a = {**{f: a.get(f) for f in WORK_SNAPSHOT}, "position": a_pos.get(k)} if a else None
        if snap_b == snap_a:
            continue
        it = a or b or {}
        title = str(it.get("title") or "")
        rows.append({"key": k, "repo": it.get("repo"), "ref": it.get("ref"),
                     "title": title[: BOARD_TITLE_CHARS - 1] + "…" if len(title) > BOARD_TITLE_CHARS else title,
                     "before": snap_b, "after": snap_a})
    return rows


def plan_files(plan: dict) -> list[str]:
    files = {"_data/work_queue.yml"} if (plan.get("pins") or plan.get("unpin") or plan.get("notes") or any(
        not k.startswith("roadmap:") for k in plan.get("priority") or {})) else set()
    if any(k.startswith("roadmap:") for k in plan.get("priority") or {}):
        files.add("_data/roadmap.yml")
    return sorted(files)


def client_label(ctx: Context | None) -> dict:
    """The transport and the name/version the client gave in initialize — a label, not an identity."""
    out = {"transport": "http" if ctx is not None and _headers(ctx) is not None else "stdio"}
    try:
        info = ctx.session.client_params.client_info if ctx is not None else None
        if info is not None:
            out["client"] = f"{getattr(info, 'name', '?')}/{getattr(info, 'version', '?')}"[:80]
    except (AttributeError, ValueError, LookupError):
        pass
    return out


def _headers(ctx: Context):
    try:
        return ctx.headers
    except (AttributeError, ValueError, LookupError):
        return None


def build_server(console: Console | None = None, allow_writes: bool | None = None,
                 fleet_compat: bool | None = None, scopes: str | None = None,
                 audit: Audit | None = None, dispatcher: Dispatcher | None = None) -> MCPServer:
    c = console or Console()
    compat = truthy(os.environ.get("HARNESS_MCP_FLEET_COMPAT")) if fleet_compat is None else fleet_compat
    writes = truthy(os.environ.get("HARNESS_MCP_ALLOW_WRITES")) if allow_writes is None else allow_writes
    granted, ignored = granted_scopes(os.environ.get("HARNESS_MCP_SCOPES") if scopes is None else scopes, writes)
    if ignored:
        print(f"harness-mcp: ignoring unknown HARNESS_MCP_SCOPES entr{'y' if len(ignored) == 1 else 'ies'} "
              f"{ignored} (known: {', '.join(SCOPES)})", file=sys.stderr)
    log = audit or Audit()
    jobs = dispatcher or Dispatcher(c, log)
    applies = RateCap(WORK_APPLY_PER_HOUR)
    mcp = MCPServer(name="harness-console", title="bamr87 Harness Console", version=VERSION, instructions=INSTRUCTIONS)

    def call(fn, *a, **kw):
        try:
            out = fn(*a, **kw)
            # A bare list becomes one object, so every client sees one JSON document (and structured content).
            return clip({"count": len(out), "items": out} if isinstance(out, list) else out)
        except ConsoleError as e:
            # Surface as a tool error (isError) with the console's reason; never the token.
            raise ToolError(str(e)) from None

    def state() -> dict:
        return c.get("/api/state")

    # ------------------------------------------------------------ read tools
    @mcp.tool(annotations=READ)
    def console_overview() -> Any:
        """Console health, git head, signal freshness, KPIs and which MCP write tools are enabled
        (mcp_writes_enabled: the broad switch; mcp_scopes: the narrow jobs/work grants)."""
        def run():
            s = state()
            h = s.get("health", {})
            return {"console": c.get("/api/health"), "generated_at": s.get("generated_at"), "git": s.get("git"),
                    "sources": s.get("sources"), "tripped_wires": h.get("tripped_count"),
                    "harness_totals": s.get("harnesses", {}).get("totals"), "mcp_writes_enabled": writes,
                    "mcp_scopes": sorted(granted), "mcp_version": VERSION, "console_url": c.url}
        return call(run)

    @mcp.tool(annotations=READ)
    def fleet_status(q: str = "", sort: str = "featured", limit: int = 50) -> Any:
        """Every registry project with health, triage, CI and docker status. q filters by text; sort: featured|triage|name|health."""
        def run():
            v = c.get("/api/fleet", q=q, sort=sort)
            rows = v.get("rows", v if isinstance(v, list) else [])
            out = {k: v[k] for k in ("kpis", "sources") if isinstance(v, dict) and k in v}
            out["rows"] = [{k: r.get(k) for k in ROW_FIELDS if k in r} for r in rows[: max(1, min(limit, 200))]]
            out["total"] = len(rows)
            return out
        return call(run)

    @mcp.tool(annotations=READ)
    def fleet_docker() -> Any:
        """Containers on every Docker host the console knows about, with a diagnosis per host. Errors when no
        host answers — the console's container holds no Docker socket by design, so read containers from a host
        terminal (`tools/dash docker ps` / `tools/dash tui`) or set DASH_DOCKER_HOST."""
        def run():
            report = docker_report(c.get("/api/fleet/docker"))
            dead = docker_error_text(report)
            if dead:
                raise ConsoleError(dead)
            return report
        return call(run)

    @mcp.tool(annotations=READ)
    def project_detail(name: str) -> Any:
        """One registry project: its row, harness, health and links."""
        return call(c.get, f"/api/project/{name}")

    @mcp.tool(annotations=READ)
    def harness_health() -> Any:
        """The hub's six-layer harness health: scorecard, trip wires (tripped first) and notes."""
        def run():
            h = state().get("health", {})
            wires = sorted(h.get("trip_wires", []), key=lambda w: not w.get("tripped"))
            return {**{k: h.get(k) for k in ("generated_at", "scorecard", "tripped_count", "note", "sources")},
                    "trip_wires": wires}
        return call(run)

    @mcp.tool(annotations=READ)
    def harness_scorecard(repo: str = "") -> Any:
        """Per-repo AI harness inventory: totals, trends, attention list; pass repo to get one repo's entry."""
        def run():
            hs = state().get("harnesses", {})
            if repo:
                repos = hs.get("repos", {})
                hit = repos.get(repo) if isinstance(repos, dict) else next((r for r in repos if r.get("name") == repo), None)
                if hit is None:
                    raise ConsoleError(f"no harness entry for {repo!r}")
                return hit
            return {k: hs.get(k) for k in ("generated_at", "totals", "trends", "throughput", "attention", "note")}
        return call(run)

    @mcp.tool(annotations=READ)
    def live_snapshot() -> Any:
        """One-shot live view: sessions, Claude live usage, jobs, spend, health, deep dive, observability.
        Needs the console's /api/live route (bamr87/bamr87#432)."""
        def run():
            try:
                return c.get("/api/live")
            except ConsoleError as e:
                if e.status == 404:
                    raise ConsoleError("this console has no /api/live yet — it ships with bamr87/bamr87#432") from None
                raise
        return call(run)

    @mcp.tool(annotations=READ)
    def claude_telemetry(window: Literal["1h", "24h", "7d"] = "24h", session: str | None = None,
                         limit: int = 20) -> Any:
        """Claude Code's native OpenTelemetry from the fleet stack (read-only): claude_code_* series names;
        sessions, tokens by type/model, active time, lines of code, commits/PRs, edit-tool decisions over the
        window (Prometheus); event counts, per-session api_request rollups and the latest api_request/tool_result
        rows (Elasticsearch logs-fleet.claude-*). `session` filters events by session id prefix. Cost is
        Claude Code's API-equivalent (estimate), not the subscription bill — use spend_vs_budget for that."""
        def run():
            q = {"window": window, "limit": max(1, min(int(limit), 100))}
            if session:
                q["session"] = session
            try:
                return c.get("/api/claude-telemetry", **q)
            except ConsoleError as e:
                if e.status == 404:
                    raise ConsoleError("this console has no /api/claude-telemetry yet (feat/console-claude-telemetry)") from None
                raise
        return call(run)

    @mcp.tool(annotations=READ)
    def sessions() -> Any:
        """Active and idle local agent sessions (Claude Code / desktop) from the live collector (#432)."""
        def run():
            try:
                return c.get("/api/live").get("sessions")
            except ConsoleError as e:
                if e.status == 404:
                    raise ConsoleError("sessions come from /api/live (bamr87/bamr87#432); use agent_activity instead") from None
                raise
        return call(run)

    @mcp.tool(annotations=READ)
    def agent_activity(days: int = 7, repo: str = "", limit: int = 10) -> Any:
        """Local Claude Code sessions + CI agent runs, unified and analysed (the /activity page)."""
        return call(c.get, "/api/lake/review", days=days, repo=repo or None, limit=limit)

    @mcp.tool(annotations=READ)
    def ops_list() -> Any:
        """The console's allowlisted operations (what a job can run), with params and whether they write remotely."""
        return call(c.get, "/api/ops")

    @mcp.tool(annotations=READ)
    def jobs_list(status: str = "", limit: int = 25) -> Any:
        """Recent console jobs, newest first. status filters (running, finished, failed, ...)."""
        def run():
            jobs = c.get("/api/jobs")
            if status:
                jobs = [j for j in jobs if j.get("status") == status]
            return jobs[: max(1, min(limit, 200))]
        return call(run)

    @mcp.tool(annotations=READ)
    def job_log(job_id: str, offset: int = 0, tail_chars: int = 20000) -> Any:
        """A job's status and log from offset; the log is cut to its last tail_chars characters."""
        def run():
            d = c.get(f"/api/jobs/{job_id}", offset=offset)
            key = "text" if "text" in d else "log"   # the route's field is `text` (core.JobManager.tail)
            log = d.get(key, "")
            if isinstance(log, str) and len(log) > tail_chars:
                d = {**d, key: log[-tail_chars:], "log_truncated": True}
            return d
        return call(run)

    @mcp.tool(annotations=READ)
    def spend_vs_budget() -> Any:
        """Claude usage and GitHub Actions minutes against _data/fleet.yml budgets. Claude dollars are
        API-equivalent ESTIMATES (list prices, not billed); `subscription` sets them against the flat
        Claude subscription as an effective discount — the two are never summed. Metered API spend
        (api_key runs) is reported separately. Actions minutes are job-minutes when
        `minutes_basis` says so; each side's `parity` is its gap to a reference (the billing
        meter's account total; claude-cost's result lines) and `coverage` says whether the
        sweep was truncated or sampled."""
        def run():
            s = state()
            usage, contract = s.get("usage", {}), s.get("contract", {})
            budgets = {k: v for k, v in contract.items() if "budget" in k.lower()}
            for k, v in contract.items():
                if isinstance(v, dict):
                    budgets.update({f"{k}.{kk}": vv for kk, vv in v.items() if "budget" in kk.lower() or "cap" in kk.lower()})
            ai = usage.get("ai", {})
            sub = s.get("subscription")
            try:
                live = (c.get("/api/live") or {}).get("claude_live") or {}
                live_sub = live.get("subscription") if isinstance(live, dict) else None
            except ConsoleError:
                live_sub = None
            return {"ai": {k: v for k, v in ai.items() if k not in ("by_day", "runs")} if isinstance(ai, dict) else ai,
                    "ai_cost_kind": "API-equivalent (estimate, not billed)",
                    "actions": {k: v for k, v in usage.get("actions", {}).items() if k not in ("by_day", "by_workflow", "runs")},
                    "budgets": budgets,
                    "subscription": sub,
                    "subscription_live": live_sub}
        return call(run)

    @mcp.tool(annotations=READ)
    def lake_status() -> Any:
        """The data lake (traces plane): reachability, row counts, Phoenix link."""
        return call(c.get, "/api/lake")

    @mcp.tool(annotations=READ)
    def lake_runs(limit: int = 50) -> Any:
        """Recent agent/workflow runs (traces) from the data lake."""
        return call(c.get, "/api/lake/runs", limit=limit)

    @mcp.tool(annotations=READ)
    def workflow_lines(filter: Literal["all", "failing", "noswitch", "ai"] = "all", repo: str = "", limit: int = 100) -> Any:
        """Every workflow with provenance, kill switch and last verdict. filter=noswitch finds scheduled agents that cannot be stopped."""
        def run():
            rows = c.get("/api/lake/lines")
            if repo:
                rows = [r for r in rows if r.get("nwo") == repo or r.get("nwo", "").endswith("/" + repo)]
            if filter == "noswitch":
                rows = [r for r in rows if not r.get("switch")]
            elif filter == "ai":
                rows = [r for r in rows if r.get("ai")]
            elif filter == "failing":
                rows = [r for r in rows if str(r.get("last_conclusion") or r.get("verdict") or "").lower() in ("failure", "failed", "fail")]
            return {"total": len(rows), "rows": rows[: max(1, min(limit, 500))]}
        return call(run)

    @mcp.tool(annotations=READ)
    def observability() -> Any:
        """The log and metrics planes (Elasticsearch/Kibana, Prometheus/Grafana, Phoenix, index): status and links."""
        return call(c.get, "/api/observability")

    @mcp.tool(annotations=READ)
    def code_search(q: str, mode: Literal["search", "harmonize"] = "search") -> Any:
        """Semantic search over the fleet worktrees (Qdrant code index). mode=harmonize finds near-duplicate code."""
        return call(c.get, f"/api/index/{mode}", q=q)

    @mcp.tool(annotations=READ)
    def index_coverage() -> Any:
        """Which repos the semantic code index covers and how fresh it is."""
        return call(c.get, "/api/index/coverage")

    @mcp.tool(annotations=READ)
    def deep_dive() -> Any:
        """Daily deep-dive progress: cycle x/N, today's and next repo, per-repo status and scores."""
        return call(c.get, "/api/data/deep_dive")

    @mcp.tool(annotations=READ)
    def work_board(lane: str = "", repo: str = "", kind: str = "", stage: str = "", priority: str = "",
                   q: str = "", limit: int = 40, offset: int = 0, summary: bool = True) -> Any:
        """The Work board: every open item on the loops' lanes in the order they take them, paged.

        The whole board is ~390k characters, so this returns one page: summary=true (the default) drops each
        item's `detail` record and cuts long titles; summary=false returns full items and caps limit at 25.
        Filter with lane (triage|ready|building|review|blocked|done…), repo, kind (issue|pr|roadmap|spec|backlog),
        stage, priority (P0..P3) or q (substring over key/title/repo/labels). Page with offset until
        next_offset is null; matched_by_lane counts the whole filtered set. One item's record: work_item/fleet_work.
        """
        def run():
            return board_page(c.get("/api/work"), summary=summary, limit=limit, offset=offset, q=q,
                              lane=lane, repo=repo, kind=kind, stage=stage, priority=priority)
        return call(run)

    @mcp.tool(annotations=READ)
    def work_item(key: str) -> Any:
        """One Work-board item's drill-down: its board row plus its source record (the issue, the roadmap
        entry, the spec's tasks, the BACKLOG.md line). `key` is a board key from work_board."""
        if not WORK_KEY_RX.match(key or ""):
            raise ToolError(f"{key!r} is not a board key — keys look like issue:owner/repo#N or roadmap:FF-NNNN")
        return call(c.get, "/api/work/item", key=key)

    @mcp.tool(annotations=READ, description=(
        "What a Work-board plan WOULD change — writes nothing. Returns the console's change lines, each named item "
        "before → after (lane, position, pin rank, priority and its source, note), the files an apply would edit, "
        "`undo_plan` (the plan that restores today's state) and `plan_id`, which work_apply needs: show the user "
        "this diff and apply only that plan_id after they approve it. A plan takes priority, pins, unpin and notes; "
        "stage moves and roadmap status edits stay on the console's Work board. " + PLAN_DOC))
    def work_preview(plan: dict) -> Any:
        p = check_plan(plan)

        def run():
            before = c.get("/api/work")
            after = c.post("/api/work/preview", {"plan": p})
            return {"plan": p, "plan_id": plan_id_for(p, before), "writes_nothing": True,
                    "changes": after.get("changes") or [], "items": plan_rows(p, before, after),
                    "files": plan_files(p), "undo_plan": undo_plan(p, before),
                    "apply_enabled": "work" in granted,
                    "next": ("ask the user to approve this diff, then work_apply(plan, plan_id, confirm=true)"
                             if "work" in granted else
                             "work_apply is not enabled on this server (HARNESS_MCP_SCOPES lacks `work`); "
                             "the user can apply this on the console's Work board")}
        return call(run)

    @mcp.tool(annotations=READ)
    def loops() -> Any:
        """The control-plane loops (scheduled AI lanes) and their state."""
        return call(lambda: state().get("loops"))

    # ------------------------------------------------ harness refinement (ADR 0004 P2)
    @mcp.tool(annotations=READ)
    def refine_status(section: str = "") -> Any:
        """Harness refinement (docs/HARNESS-REFINEMENT.md): the hub's harness-surface check, the fleet sweep
        (every checked-out repo's context files, skills, agents, hooks, MCP), one Propose–Probe–Compose plan per
        loop with its ceiling against budget.loops, the experience library's lessons, the evidence trees built
        here and the review queue of unfiled loop-run previews. `section` narrows to one key (surface,
        fleet_surface, plans, library, evidence, reviews, config). Read it before refining a loop's harness.
        """
        def run():
            doc = c.get("/api/refine")
            if section:
                if section not in doc:
                    raise ToolError(f"no section {section!r}; one of {', '.join(sorted(doc))}")
                return {section: doc[section], "generated_at": doc.get("generated_at")}
            summary = {k: doc[k] for k in ("generated_at", "config", "missions", "stages", "modes", "cost_label") if k in doc}
            summary["surface"] = {k: v for k, v in (doc.get("surface") or {}).items() if k != "census"}
            summary["fleet_surface"] = (doc.get("fleet_surface") or {}).get("totals")
            summary["plans"] = [{k: p.get(k) for k in ("loop", "step", "k", "mode", "identity", "error")}
                                | {"ceiling_usd": (p.get("cost") or {}).get("ceiling_usd"),
                                   "budget": p.get("budget")} for p in doc.get("plans") or []]
            summary["library"] = {"count": (doc.get("library") or {}).get("count"),
                                  "uncommitted": (doc.get("library") or {}).get("uncommitted")}
            summary["evidence"] = len(doc.get("evidence") or [])
            summary["reviews"] = [{k: r.get(k) for k in ("run_id", "loop", "item", "would_file", "can_apply")}
                                  for r in doc.get("reviews") or []]
            return summary
        return call(run)

    @mcp.tool(annotations=READ)
    def refine_library(loop: str = "", domain: str = "", limit: int = 20) -> Any:
        """The harness experience library (_data/harness_library): each adopted refinement's cue, lesson,
        evidence, confidence and per-edit verdicts, newest first; filter by loop (repo-scout, …) and domain
        (the registry category). Data to re-verify, never a rule."""
        def run():
            lib = c.get("/api/refine").get("library") or {}
            rows = [e for e in lib.get("entries") or [] if (not loop or e.get("loop") == loop)
                    and (not domain or e.get("domain") == domain)]
            return {"root": lib.get("root"), "count": len(rows), "items": rows[: max(1, min(limit, 200))],
                    "uncommitted": lib.get("uncommitted")}
        return call(run)

    @mcp.tool(annotations=READ)
    def refine_reviews() -> Any:
        """The review queue: every local loop-run attempt whose dry-run preview has not been filed — what
        `loop-run` with run_id and apply would file after a person reads it (the console's confirm gate)."""
        return call(lambda: c.get("/api/refine").get("reviews") or [])

    # ------------------------------------------------------------- resources
    # ------------------------------------- the `fleet` server's tools (merged)
    # tools/fleetcore/mcp_server.py's read tools work from the committed signals, with no console running;
    # its console_* tools are aliases of the routes above. Same names, so `mcp__fleet__*` permissions keep working.
    def fleet_fn(name: str):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # tools/, for fleetcore
        from fleetcore import mcp_server as legacy
        return getattr(legacy, name)

    def local(fn_name: str, args: dict) -> Any:
        try:
            return clip(fleet_fn(fn_name)(args))
        except (ImportError, OSError, KeyError, ValueError, TypeError) as e:
            raise ToolError(f"{fn_name}: {e}") from None

    @mcp.tool(annotations=READ)
    def fleet_overview() -> Any:
        """Fleet KPIs, signal freshness, tripped harness wires and the red repos — from the committed signals."""
        return local("t_overview", {})

    @mcp.tool(annotations=READ)
    def fleet_apps(query: str = "", sort: str = "featured", health: str = "", limit: int = 50) -> Any:
        """Registry projects with health, CI, triage, open work and containers (the Apps view), from committed signals."""
        return local("t_apps", {"query": query, "sort": sort, "health": health or None, "limit": limit})

    @mcp.tool(annotations=READ)
    def fleet_inbox(repo: str = "", limit: int = 30) -> Any:
        """The fleet inbox (flagged issues, PRs, failing workflows, highest priority first), or one repo's open items."""
        return local("t_inbox", {"repo": repo, "limit": limit})

    @mcp.tool(annotations=READ)
    def fleet_work(lane: str = "", repo: str = "", kind: str = "", next_only: bool = False, limit: int = 25) -> Any:
        """The Work board in the order the loops take it, pins and overrides applied, next run's picks marked."""
        return local("t_work", {"lane": lane, "repo": repo, "kind": kind, "next_only": next_only, "limit": limit})

    @mcp.tool(annotations=READ)
    def fleet_workflows(workflow: str = "", health: bool = False, days: int = 30) -> Any:
        """The hub's GitHub Actions as one model (the workflow atlas): every workflow and composite action with
        its triggers, crons, inputs, jobs, Claude call sites and kill switch, and every finding against the
        standards. Pass `workflow` (a file stem such as fleet-pulse, or an action id) for one in full; `health`
        adds run health and failure causes from the local lake over `days`. Read it before changing a workflow."""
        return local("t_workflows", {"workflow": workflow, "health": health, "days": max(1, min(days, 365))})

    @mcp.tool(annotations=READ)
    def workflow_lint(text: str, id: str = "draft") -> Any:
        """Lint a draft workflow (its YAML text) against the hub's standards and _data/fleet.yml: permissions,
        timeouts, concurrency, crons, kill switch, Claude budget and usage-limit pairing, PR token, bare pushes.
        `id` is the file stem it will have. Nothing is written."""
        return local("t_workflow_lint", {"text": text, "id": id})

    @mcp.tool(annotations=READ)
    def console_ops() -> Any:
        """Alias of ops_list (the legacy `fleet` name)."""
        return ops_list()

    @mcp.tool(annotations=READ)
    def console_jobs(limit: int = 20) -> Any:
        """Alias of jobs_list (the legacy `fleet` name)."""
        return jobs_list(limit=limit)

    @mcp.tool(annotations=READ)
    def console_job_log(job_id: str, offset: int = 0) -> Any:
        """Alias of job_log (the legacy `fleet` name)."""
        return job_log(job_id, offset)

    @mcp.resource("harness://overview", mime_type="application/json", description="console_overview as a resource")
    def r_overview() -> str:
        return json.dumps(console_overview(), default=str)

    @mcp.resource("harness://health", mime_type="application/json", description="Harness health scorecard and trip wires")
    def r_health() -> str:
        return json.dumps(harness_health(), default=str)

    @mcp.resource("harness://ops", mime_type="application/json", description="Allowlisted operations")
    def r_ops() -> str:
        return json.dumps(ops_list(), default=str)

    @mcp.resource("harness://deep-dive", mime_type="application/json", description="Deep-dive ledger")
    def r_deep() -> str:
        return json.dumps(deep_dive(), default=str)

    @mcp.resource("harness://live", mime_type="application/json", description="Live snapshot (needs #432)")
    def r_live() -> str:
        return json.dumps(live_snapshot(), default=str)

    # ------------------------------------------------- guarded write tools
    if writes:
        def need(confirm: bool, what: str) -> None:
            if not confirm:
                raise ToolError(f"refused: {what} is destructive — ask the user, then call again with confirm=true")

        @mcp.tool(annotations=WRITE)
        def run_op(op: str, params: dict | None = None, confirm: bool = False) -> Any:
            """DESTRUCTIVE. Start an allowlisted console operation as a job (see ops_list). Needs confirm=true;
            the console additionally refuses remote-writing ops unless confirmed."""
            need(confirm, f"running op {op!r}")
            return call(c.post, "/api/jobs", {"op": op, "params": params or {}, "confirm": True})

        @mcp.tool(annotations=WRITE)
        def cancel_job(job_id: str, confirm: bool = False) -> Any:
            """DESTRUCTIVE. Cancel a running console job. Needs confirm=true."""
            need(confirm, f"cancelling job {job_id}")
            return call(c.post, f"/api/jobs/{job_id}/cancel", {})

        @mcp.tool(annotations=WRITE)
        def workflow_kill_switch(owner: str, repo: str, workflow_id: int, enabled: bool, confirm: bool = False) -> Any:
            """DESTRUCTIVE. Enable or disable a GitHub Actions workflow (the kill switch) through the console's
            GitHub link. Needs confirm=true and GitHub writes enabled in the console."""
            action = "workflow.enable" if enabled else "workflow.disable"
            need(confirm, f"{action} on {owner}/{repo} workflow {workflow_id}")
            return call(c.post, f"/api/github/repos/{owner}/{repo}/actions",
                        {"action": action, "params": {"workflow_id": workflow_id}, "confirm": True})

    if writes or compat:
        @mcp.tool(annotations=WRITE)
        def console_run(op: str, params: dict | None = None, confirm: bool = False) -> Any:
            """DESTRUCTIVE (legacy `fleet` name). Run one allowlisted operation as a console job. The console refuses
            a writing operation unless confirm=true — get the user's go-ahead first."""
            return call(c.post, "/api/jobs", {"op": op, "params": params or {}, "confirm": bool(confirm)})

        @mcp.tool(annotations=WRITE)
        def console_cancel(job_id: str) -> Any:
            """DESTRUCTIVE (legacy `fleet` name). Cancel a running console job."""
            return call(c.post, f"/api/jobs/{job_id}/cancel", {})

    # ------------------------------------------------- scoped write tools
    def refuse(tool: str, scope: str, ctx: Context | None, why: str, **rec: Any) -> NoReturn:
        log.record(tool=tool, scope=scope, outcome="refused", reason=why, **client_label(ctx), **rec)
        raise ToolError(why)

    if "jobs" in granted:
        @mcp.tool(annotations=SCOPED, description=(
            "Start ONE allowlisted report op as a console job, after the user approved it (confirm=true). The "
            f"allowlist: {', '.join(sorted(DISPATCH_OPS))} — local, $0 reports and checks that write nothing to "
            "GitHub, touch no secret and start no container; see ops_list for what each does. Each op has a wall "
            "clock (limit_s) after which the job is cancelled; at most "
            f"{DISPATCH_RUNNING_MAX} run at once and {DISPATCH_PER_HOUR} start per hour. wait_s (0–"
            f"{DISPATCH_WAIT_MAX_S}) waits for it and returns the end of its log; otherwise read it with job_log. "
            "Every call is audited."))
        def job_dispatch(op: str, params: dict | None = None, confirm: bool = False, wait_s: int = 0,
                         ctx: Context | None = None) -> Any:
            if not confirm:
                refuse("job_dispatch", "jobs", ctx, f"refused: starting {op!r} needs the user's go-ahead — ask, "
                       "then call again with confirm=true", op=op)
            try:
                op_id, clean, limit = check_dispatch(op, params)
            except ToolError as e:
                refuse("job_dispatch", "jobs", ctx, str(e), op=op, params=params)
            try:
                card = next((o for o in c.get("/api/ops") or [] if o.get("id") == op_id), None)
            except ConsoleError as e:
                raise ToolError(str(e)) from None
            # The console's own description of the op, checked again: a definition that changed to write
            # remotely, spend or need the confirm is refused here before the console is asked.
            if card is None or card.get("remote_write") or card.get("confirm") or card.get("unavailable"):
                why = ("not offered by this console" if card is None else card.get("unavailable")
                       or "the console marks it as writing remotely or spending")
                refuse("job_dispatch", "jobs", ctx, f"refused: {op_id} — {why}", op=op_id, params=clean)
            try:
                jobs.admit()
            except ToolError as e:
                refuse("job_dispatch", "jobs", ctx, str(e), op=op_id, params=clean)
            try:
                job = c.post("/api/jobs", {"op": op_id, "params": clean, "confirm": False})
            except ConsoleError as e:
                log.record(tool="job_dispatch", scope="jobs", op=op_id, params=clean, outcome="error",
                           reason=str(e), **client_label(ctx))
                raise ToolError(str(e)) from None
            jid = str(job.get("id") or "")
            jobs.track(jid, op_id, limit)
            where = log.record(tool="job_dispatch", scope="jobs", op=op_id, params=clean, outcome="started",
                               job_id=jid, limit_s=limit, **client_label(ctx))
            out: dict[str, Any] = {"job": job, "limit_s": limit, "audit": where,
                                   "next": "job_log(job_id) reads its log; job_cancel(job_id, confirm=true) stops it"}
            wait = max(0, min(int(wait_s or 0), DISPATCH_WAIT_MAX_S))
            if wait and jid:
                end = time.monotonic() + wait
                while True:
                    try:
                        d = c.get(f"/api/jobs/{jid}")
                    except ConsoleError as e:
                        out["wait_error"] = str(e)
                        break
                    if d.get("done") or time.monotonic() >= end:
                        text = d.get("text") or ""
                        out.update(job=d.get("job", job), done=bool(d.get("done")),
                                   log_tail=text[-DISPATCH_LOG_TAIL:], log_truncated=len(text) > DISPATCH_LOG_TAIL)
                        if d.get("done"):
                            jobs.forget(jid)
                        break
                    time.sleep(DISPATCH_POLL_S)
            return clip(out)

        @mcp.tool(annotations=SCOPED, description=(
            "Stop a running job that job_dispatch's allowlist could have started (confirm=true, after the user "
            "approved it). Jobs of any other op — a deploy, a secret push, a loop run — are refused: stop those "
            "from the console. Audited."))
        def job_cancel(job_id: str, confirm: bool = False, ctx: Context | None = None) -> Any:
            if not JOB_ID_RX.match(job_id or ""):
                refuse("job_cancel", "jobs", ctx, "job_id is the 12-hex-character id jobs_list shows", job_id=job_id)
            if not confirm:
                refuse("job_cancel", "jobs", ctx, f"refused: stopping job {job_id} needs the user's go-ahead — ask, "
                       "then call again with confirm=true", job_id=job_id)
            try:
                op = ((c.get(f"/api/jobs/{job_id}") or {}).get("job") or {}).get("op")
            except ConsoleError as e:
                raise ToolError(str(e)) from None
            if op not in DISPATCH_OPS:
                refuse("job_cancel", "jobs", ctx, f"refused: job {job_id} runs {op!r}, which job_dispatch cannot "
                       "start — stop it from the console", job_id=job_id, op=op)
            try:
                job = c.post(f"/api/jobs/{job_id}/cancel", {})
            except ConsoleError as e:
                raise ToolError(str(e)) from None
            jobs.forget(job_id)
            where = log.record(tool="job_cancel", scope="jobs", job_id=job_id, op=op, outcome="cancelled",
                               status=job.get("status"), **client_label(ctx))
            return {"job": job, "audit": where}

    if "work" in granted:
        @mcp.tool(annotations=SCOPED, description=(
            "Apply a Work-board plan the user approved: the exact plan and plan_id work_preview returned, with "
            "confirm=true. Writes the console's working tree only — _data/work_queue.yml (pins, priority overrides, "
            "notes) and, for a roadmap:FF key's priority, _data/roadmap.yml — and commits nothing: committing the "
            "file is the approval the loops read. Refused when the targets changed since the preview (preview "
            "again), for stage moves and roadmap status edits (the console's Work board does those), and past "
            f"{WORK_PLAN_MAX_KEYS} items per plan or {WORK_APPLY_PER_HOUR} applies per hour. Returns the per-change "
            "results, the git diff, each item after, and undo_plan to put it back. Audited. " + PLAN_DOC))
        def work_apply(plan: dict, plan_id: str, confirm: bool = False, ctx: Context | None = None) -> Any:
            try:
                p = check_plan(plan)
            except ToolError as e:
                refuse("work_apply", "work", ctx, str(e), plan=plan, plan_id=plan_id)
            if not confirm:
                refuse("work_apply", "work", ctx, "refused: applying a plan needs the user's approval of its "
                       "work_preview diff — ask, then call again with confirm=true", plan=p, plan_id=plan_id)
            try:
                before = c.get("/api/work")
            except ConsoleError as e:
                raise ToolError(str(e)) from None
            now_id = plan_id_for(p, before)
            if str(plan_id or "") != now_id:
                refuse("work_apply", "work", ctx, "refused: this plan_id does not match the plan and the board as "
                       "they are now (the plan differs, or its items moved since the preview) — run work_preview "
                       "again and show the user the new diff", plan=p, plan_id=plan_id)
            try:
                applies.take("work_apply")
            except ToolError as e:
                refuse("work_apply", "work", ctx, str(e), plan=p, plan_id=plan_id)
            try:
                # confirm=false: the console asks for it only for GitHub label moves, which this plan cannot hold
                res = c.post("/api/work/apply", {"plan": p, "confirm": False})
            except ConsoleError as e:
                log.record(tool="work_apply", scope="work", plan=p, plan_id=plan_id, outcome="error",
                           reason=str(e), **client_label(ctx))
                raise ToolError(str(e)) from None
            diff = str(res.get("diff") or "")
            results = res.get("results") or []
            where = log.record(tool="work_apply", scope="work", plan=p, plan_id=plan_id,
                               outcome="applied" if all(r.get("ok") for r in results) else "partial",
                               results=results, pruned=res.get("pruned"), files=plan_files(p),
                               diff=diff[:4000], **client_label(ctx))
            return clip({"plan_id": plan_id, "results": results, "pruned": res.get("pruned") or [],
                         "items": plan_rows(p, before, res.get("board") or {}), "files": plan_files(p),
                         "diff": diff[:WORK_DIFF_CHARS], "diff_truncated": len(diff) > WORK_DIFF_CHARS,
                         "undo_plan": undo_plan(p, before), "committed": False, "audit": where,
                         "note": "Working tree only, nothing committed: committing the file is the approval the "
                                 "loops read (docs/WORK-BOARD.md). To put it back, work_preview(undo_plan) then "
                                 "work_apply it, or restore the file from git."})

    return mcp


# ---------------------------------------------------------------- HTTP auth
class BearerAuth:
    """ASGI wrapper: every request needs `Authorization: Bearer <token>` (constant-time compare)."""

    def __init__(self, app, token: str):
        if not token:
            raise ValueError("refusing to serve MCP over HTTP without a token")
        self.app, self._token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope.get("headers") or []).get(b"authorization", b"")
            ok = got.startswith(b"Bearer ") and hmac.compare_digest(got[7:].strip(), self._token)
            if not ok:
                body = b'{"error":"unauthorized"}'
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def http_token() -> str:
    """HARNESS_MCP_TOKEN only — the HTTP face has its own secret, so the console token never leaves the machine."""
    return os.environ.get("HARNESS_MCP_TOKEN") or dotenv_value("HARNESS_MCP_TOKEN")


def http_app(server: MCPServer, host: str, port: int, token: str, extra_hosts: list[str] | None = None):
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"] + (extra_hosts or [])
    sec = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                    allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in extra_hosts or []])
    return BearerAuth(server.streamable_http_app(transport_security=sec, host=host), token)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Harness Console MCP server")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default=os.environ.get("HARNESS_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("HARNESS_MCP_PORT", "4002")))
    ap.add_argument("--allow-host", action="append", default=[], help="extra Host header to accept (e.g. a tunnel name)")
    ap.add_argument("--fleet-compat", action="store_true",
                    help="register the legacy fleet server's console_run/console_cancel too (stdio .mcp.json `fleet`)")
    ap.add_argument("--list-tools", action="store_true", help="print the tool catalog and exit")
    a = ap.parse_args(argv)
    server = build_server(fleet_compat=True if a.fleet_compat else None)
    if a.list_tools:
        import anyio
        for t in anyio.run(server.list_tools):
            a = t.annotations
            kind = "read" if a and a.read_only_hint else ("WRITE" if a and a.destructive_hint else "write")
            print(f"{kind:5}  {t.name}")
        return 0
    if not a.http:
        server.run("stdio")
        return 0
    token = http_token()
    if not token:
        print("harness-mcp: set HARNESS_MCP_TOKEN (env or .env) before serving HTTP — the console token is not reused", file=sys.stderr)
        return 2
    if a.host not in ("127.0.0.1", "localhost", "::1") and not Path("/.dockerenv").exists():
        print(f"harness-mcp: WARNING binding {a.host} — reachable beyond this machine; bearer auth still required", file=sys.stderr)
    import uvicorn
    granted, _ = granted_scopes(os.environ.get("HARNESS_MCP_SCOPES"), truthy(os.environ.get("HARNESS_MCP_ALLOW_WRITES")))
    print(f"harness-mcp: streamable HTTP on http://{a.host}:{a.port}/mcp (bearer auth; writes "
          f"{'ENABLED' if truthy(os.environ.get('HARNESS_MCP_ALLOW_WRITES')) else 'disabled'}; "
          f"scopes: {','.join(sorted(granted)) or 'none'})", file=sys.stderr)
    extra = a.allow_host + [h.strip() for h in os.environ.get("HARNESS_MCP_ALLOW_HOSTS", "").split(",") if h.strip()]
    uvicorn.run(http_app(server, a.host, a.port, token, extra), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

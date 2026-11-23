"""
core_jobs — the console's job manager: a section of core's logic, in its own
file.

  JOBS       asynchronous subprocess jobs with on-disk logs that the UI tails.
             Operations that WRITE TO GITHUB (fan-out --apply, secret rotation,
             workflow dispatch) require an explicit confirm flag and are
             serialized behind one lock — the console mirrors the fleet's
             rules: dry-run by default, one remote write at a time, never a
             merge. Every job reads back with a derived state, its ages and
             why it may be slow (JOB STATUS, docs/job-status.md).

What a job may run is not decided here: `submit` asks core.build_argv, which
resolves the operation against the OPS allowlist in core.py.

core.py loads this module at its end and re-exports every name in it, so callers
keep writing `core.<name>`. What core owns (its paths, constants and helpers, the
OPS table, and every name a test or tools/evals.py rebinds) is read here as
`core.<name>` at the moment of the call, never copied, so rebinding one on core
reaches this code as it did when this was a section of core.py. To replace a
name DEFINED here, patch it on this module: this file calls its own names directly.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

if "core" not in sys.modules:  # the order is a rule, not luck: core loads this module at its end
    raise ImportError("core_jobs is a section of core: import core, which loads it and re-exports its names")
import core  # noqa: E402


# --------------------------------------------------------------------------- #
# JOBS
# --------------------------------------------------------------------------- #
# A job in one of these states will never change again.
FINISHED_STATES = ("succeeded", "failed", "cancelled", "interrupted")


class JobUnavailable(RuntimeError):
    """An operation that cannot run in this process at all (see op_unavailable)."""


class JobConflict(RuntimeError):
    """A job that must run alone already is.

    Every op marked `exclusive="lake"` writes the one SQLite lake. Two of them
    at once used to mean the second died within seconds on "database is
    locked" — a double click on Extract, or an agent and a human both
    refreshing — so the console now says which job holds the lake instead.
    """
_JOB_ID_RX = re.compile(r"^[0-9a-f]{12}$")
ORPHAN_LOG_AGE_S = 86400


def _parse_ts(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


class Job:
    def __init__(self, op_id: str, argv: list[str], remote: bool, params: dict):
        self.id = uuid.uuid4().hex[:12]
        self.op = op_id
        self.title = core.OPS[op_id]["title"]
        self.argv = argv
        self.remote = remote
        self.params = params
        self.exclusive = core._exclusive_key(op_id, params)
        self.status = "queued"
        self.created = dt.datetime.now(dt.timezone.utc)
        self.started: dt.datetime | None = None
        self.finished: dt.datetime | None = None
        self.exit_code: int | None = None
        self.log_path = core.JOB_DIR / f"{self.id}.log"
        self.proc: subprocess.Popen | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "op": self.op, "title": self.title, "argv": self.argv,
            "remote_write": self.remote, "status": self.status,
            "created": self.created.isoformat(),
            "started": self.started.isoformat() if self.started else None,
            "finished": self.finished.isoformat() if self.finished else None,
            "exit_code": self.exit_code, "log_path": str(self.log_path),
            # Validated operation parameters (names, flags, numbers — never a
            # credential value: secrets-push takes a secret's NAME), so the page
            # can show what a job ran with and offer to run it again.
            "params": self.params,
            # The operation's group (observe, plan, verify, lake, content,
            # deploy) — what the Jobs page groups and filters by.
            "group": (core.OPS.get(self.op) or {}).get("group"),
            # what its confirm guarded (a GitHub write, or Claude spend) and the key it holds while live
            # an applied loop-run is a GitHub write, whatever the op's default gate wording
            "confirm": ("write" if core._flag(self.params or {}, "apply")
                        else (core.OPS.get(self.op) or {}).get("confirm", "write" if self.remote else None)),
            "exclusive": self.exclusive,
        }

    @classmethod
    def from_dict(cls, d: dict, job_dir: Path) -> "Job":
        """A job read back from the index — never re-run, only shown.

        Built without __init__ because an operation can have been renamed or
        removed since the job ran, and its history should still load.
        """
        job = cls.__new__(cls)
        job.id = str(d["id"])
        job.op = str(d.get("op") or "")
        job.title = str(d.get("title") or job.op)
        job.argv = list(d.get("argv") or [])
        job.remote = bool(d.get("remote_write"))
        job.params = dict(d.get("params") or {})
        job.status = str(d.get("status") or "interrupted")
        job.created = _parse_ts(d.get("created")) or dt.datetime.now(dt.timezone.utc)
        job.started = _parse_ts(d.get("started"))
        job.finished = _parse_ts(d.get("finished"))
        job.exit_code = d.get("exit_code")
        job.exclusive = d.get("exclusive")
        job.log_path = job_dir / f"{job.id}.log"
        job.proc = None
        return job


def job_env() -> dict:
    """The environment every job runs with.

    A job inherits this process's environment exactly as a terminal would —
    which is also how a credential handed to set_credential() reaches `gh` and
    the generators without ever touching an argv.

    PYTHON is what tools/dash-gen execs. Without it the generators ran on the
    system python3 while the console's own dependencies live in .venv-console,
    so `lake export` — whose OpenTelemetry SDK the console itself installs —
    died with ModuleNotFoundError on every real send. (The dry run returns
    before that import, which is why only the shipping path was broken, and why
    the UI looked fine until you unticked "dry run".) Handing jobs this
    interpreter makes what the console installs and what its jobs can import
    the same set.
    """
    return {**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0", "NO_COLOR": "1",
            "PYTHON": sys.executable}


def loop_job_fields(log_path: Path) -> dict:
    """The structured view of a `loop-run` job's log — the engine's `--json`
    run record when it printed one, else what its status lines say so far —
    from `tools/fleetcore/loopjob.py`, the one parser both surfaces use."""
    if str(core.TOOLS) not in sys.path:
        sys.path.insert(0, str(core.TOOLS))
    from fleetcore import loopjob
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return loopjob.parse_log(text)


# --------------------------------------------------------------------------- #
# JOB STATUS — what the bot holding a job's receipt can audit (HUB-064, FR60)
# --------------------------------------------------------------------------- #
# `status` says only what a job's process did. An agent that sent a job held a
# receipt and that raw status, so it could not tell a job still making progress
# from one that had gone quiet, or say why one was slow (the case that asked
# for this: a Claude Code session lookup that crawled while nobody could see
# why). These fields are derived each time a job is read, from what this
# runtime already holds — the job, its log's growth, the other live jobs, the
# live collector's file — so nothing new is stored and a job from an older
# index reads the same way. Design: docs/job-status.md.
JOB_STATES = ("queued", "running", "stalled", "done", "failed")
STALL_S = 120            # a running job whose log has not grown for this long is stalled; OPS[op]["stall_s"] overrides
LONG_STEP_MIN_RUNS = 3   # succeeded runs of an op before their p90 says what "typical" is
LONG_STEP_RUNS = 20      # ... read from its most recent succeeded runs
LONG_STEP_FLOOR_S = 30   # never call a run long before this, however quick its op usually is


def stall_threshold(op_id: str) -> int:
    """Seconds without log growth before a running job of this op reads as stalled."""
    value = (core.OPS.get(op_id) or {}).get("stall_s")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return int(value)
    return STALL_S


def _utc(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _since(now: dt.datetime, then: dt.datetime) -> float:
    return round(max(0.0, (_utc(now) - _utc(then)).total_seconds()), 1)


def _mtime(path: Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
    except OSError:
        return None


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def collector_lag(now: dt.datetime | None = None) -> dict | None:
    """The live collector's lag when its sessions.json is older than live.py
    calls stale, else None. A missing file is no collector on this host, not a
    lagging one, so it is None too."""
    import live  # noqa: PLC0415 — live imports core; by the time a job is read, core is loaded
    age = live.collector_age(now.timestamp() if now else None)
    if age is None or age <= live.STALE_S:
        return None
    return {"age_s": round(age, 1), "stale_s": live.STALE_S}


class JobManager:
    """Every job this runtime started, with history that survives a restart.

    The index (jobs.json beside the logs) is rewritten on every state change.
    Without it the list vanished with the process while the log files stayed
    in the job dir forever — including the logs of jobs evicted past
    max_jobs — so the directory only ever grew and the page only ever forgot.
    """

    def __init__(self, job_dir: Path = core.JOB_DIR, max_jobs: int = 200):
        self.job_dir = job_dir
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.job_dir / "jobs.json"
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.max_jobs = max_jobs
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._remote_lock = threading.Lock()   # one GitHub-writing job at a time
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        try:
            rows = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not _JOB_ID_RX.match(str(row.get("id", ""))):
                continue
            job = Job.from_dict(row, self.job_dir)
            # A job that was queued or running when the last process died has
            # no process to finish it. Say so rather than show it spinning.
            if job.status not in FINISHED_STATES:
                job.status = "interrupted"
            self.jobs[job.id] = job
            self.order.append(job.id)
        # Logs nobody indexes: written by a console that predates the index,
        # or by one that died between the log and the index write. Only files
        # named like a job id, and only once they are a day old — a fresh
        # unindexed log can belong to ANOTHER live process on the same dir
        # (a test run inside the console container deleted the running
        # console's logs exactly that way).
        cutoff = time.time() - ORPHAN_LOG_AGE_S
        for log in self.job_dir.glob("*.log"):
            if _JOB_ID_RX.match(log.stem) and log.stem not in self.jobs:
                try:
                    if log.stat().st_mtime < cutoff:
                        log.unlink(missing_ok=True)
                except OSError:
                    pass
        with self._lock:
            self._evict()
        self._save()

    def _save(self) -> None:
        with self._lock:
            rows = [self.jobs[i].to_dict() for i in self.order if i in self.jobs]
        with self._io_lock:
            tmp = self.index_path.with_suffix(".json.tmp")
            try:
                tmp.write_text(json.dumps(rows))
                tmp.replace(self.index_path)
            except OSError:
                pass   # history is a convenience; a full /tmp must not fail a job

    def _evict(self) -> None:
        """Drop the oldest jobs past max_jobs — and their logs. Caller holds _lock."""
        while len(self.order) > self.max_jobs:
            old = self.jobs.pop(self.order.pop(0), None)
            if old is not None:
                old.log_path.unlink(missing_ok=True)

    def clear(self, statuses: tuple[str, ...] = FINISHED_STATES) -> dict:
        """Forget finished jobs in `statuses`, logs included. Never a live one."""
        bad = set(statuses) - set(FINISHED_STATES)
        if bad:
            raise ValueError(f"only finished jobs can be cleared, not {sorted(bad)}")
        removed = 0
        with self._lock:
            for jid in list(self.order):
                job = self.jobs.get(jid)
                if job is not None and job.status in statuses:
                    self.order.remove(jid)
                    self.jobs.pop(jid, None)
                    job.log_path.unlink(missing_ok=True)
                    removed += 1
        self._save()
        return {"removed": removed, "remaining": len(self.order)}

    def submit(self, op_id: str, params: dict | None = None, confirm: bool = False) -> Job:
        params = params or {}
        argv, remote = core.build_argv(op_id, params)
        if remote and not confirm:
            raise PermissionError(
                f"'{op_id}' with these parameters writes to GitHub or destroys local data — "
                "resubmit with confirm=true")
        why = core.op_unavailable(op_id)
        if why:
            raise JobUnavailable(f"'{op_id}' cannot run here: {why}")
        job = Job(op_id, argv, remote, params)
        job.log_path = self.job_dir / f"{job.id}.log"
        exclusive = job.exclusive
        with self._lock:
            if exclusive:
                holder = next((j for j in self.jobs.values() if j.status in ("queued", "running")
                               and getattr(j, "exclusive", None) == exclusive), None)
                if holder is not None:
                    what = (f"is already writing the {exclusive}" if exclusive == "lake"
                            else f"already holds {exclusive}" + (" (one local run of a loop at a time)"
                                                                 if str(exclusive).startswith("loop:") else ""))
                    raise JobConflict(
                        f"'{holder.op}' (job {holder.id}) {what} — wait for it to finish, then run '{op_id}'")
            self.jobs[job.id] = job
            self.order.append(job.id)
            self._evict()
        self._save()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        env = job_env()
        lock = self._remote_lock if job.remote else None
        if lock:
            lock.acquire()
        try:
            job.started = dt.datetime.now(dt.timezone.utc)
            job.status = "running"
            self._save()
            with job.log_path.open("w") as log:
                log.write(f"$ {' '.join(job.argv)}\n")
                log.flush()
                try:
                    job.proc = subprocess.Popen(
                        job.argv, cwd=str(core.REPO_ROOT), stdout=log, stderr=subprocess.STDOUT,
                        env=env, start_new_session=True,
                    )
                    job.exit_code = job.proc.wait()
                except FileNotFoundError as exc:
                    log.write(f"\n[console] cannot start: {exc}\n")
                    job.exit_code = 127
            if job.status == "cancelled":
                pass
            elif job.exit_code == 0:
                job.status = "succeeded"
            else:
                job.status = "failed"
        finally:
            job.finished = dt.datetime.now(dt.timezone.utc)
            if lock:
                lock.release()
            self._save()

    # -- status (HUB-064) ----------------------------------------------------
    def _typical_s(self, op_id: str) -> tuple[float, int] | None:
        """(p90 seconds, runs read) over the op's most recent succeeded runs, or
        None below LONG_STEP_MIN_RUNS. Caller holds _lock."""
        took: list[float] = []
        for jid in reversed(self.order):
            j = self.jobs.get(jid)
            if j is not None and j.op == op_id and j.status == "succeeded" and j.started and j.finished:
                took.append(_since(j.finished, j.started))
                if len(took) == LONG_STEP_RUNS:
                    break
        return (_p90(took), len(took)) if len(took) >= LONG_STEP_MIN_RUNS else None

    def _waiting_on(self, job: Job) -> tuple[Job, str] | None:
        """The live job a queued one waits behind, and what it holds. Caller holds _lock."""
        for other in self.jobs.values():
            if other is job or other.status not in ("queued", "running"):
                continue
            if job.exclusive and getattr(other, "exclusive", None) == job.exclusive:
                return other, f"holds {job.exclusive}"
            if job.remote and other.remote and other.status == "running":
                return other, "holds the one GitHub-write slot (one remote write at a time)"
        return None

    def _progress(self, job: Job, now: dt.datetime, lag: dict | None) -> dict:
        """state, age_s, idle_s, stall_s and diagnostics for one job. Caller holds _lock."""
        stall_s = stall_threshold(job.op)
        age_s = _since(now, job.created)
        idle_s: float | None = None
        diagnostics: list[dict] = []
        if job.status in FINISHED_STATES:
            # the exact outcome stays in `status`; `state` says only whether it worked
            state = "done" if job.status == "succeeded" else "failed"
        elif job.status == "running" and job.started is not None:
            # a heartbeat is a log line, so log growth is the one sign of progress
            grew = _mtime(job.log_path)
            idle_s = _since(now, max(_utc(job.started), grew) if grew else job.started)
            state = "stalled" if idle_s > stall_s else "running"
            if state == "stalled":
                diagnostics.append({"code": "no_heartbeat",
                                    "detail": f"no log output for {idle_s:.0f} s (stalled past {stall_s} s)"})
            typical = self._typical_s(job.op)
            ran = _since(now, job.started)
            if typical and ran > max(typical[0], LONG_STEP_FLOOR_S):
                diagnostics.append({"code": "long_step",
                                    "detail": f"running {ran:.0f} s, past the {typical[0]:.0f} s p90 of its "
                                              f"last {typical[1]} successful runs"})
        else:
            state = "queued"
            idle_s = age_s
            waiting = self._waiting_on(job)
            if waiting:
                other, what = waiting
                diagnostics.append({"code": "queue_wait",
                                    "detail": f"queued behind '{other.op}' (job {other.id}), which {what}"})
        if lag and state in ("queued", "running", "stalled"):
            diagnostics.append({"code": "collector_lag",
                                "detail": f"the live collector last wrote .dash-live/sessions.json "
                                          f"{lag['age_s']:.0f} s ago (stale past {lag['stale_s']} s), so a "
                                          "Claude Code session lookup reads old data"})
        return {"state": state, "age_s": age_s, "idle_s": idle_s, "stall_s": stall_s, "diagnostics": diagnostics}

    def status(self, job_id: str, now: dt.datetime | None = None) -> dict:
        """What one job is doing now (GET /api/jobs/{id}/status, the MCP's
        job_status): who it is and its raw status, then the derived state, ages
        and diagnostics. KeyError for an unknown id."""
        now = now or dt.datetime.now(dt.timezone.utc)
        lag = collector_lag(now)
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            d = job.to_dict()
            keep = ("id", "op", "title", "group", "status", "exit_code", "created", "started", "finished",
                    "remote_write", "exclusive")
            return {**{k: d[k] for k in keep}, **self._progress(job, now, lag)}

    def list(self, now: dt.datetime | None = None) -> list[dict]:
        now = now or dt.datetime.now(dt.timezone.utc)
        lag = collector_lag(now)
        with self._lock:
            return [{**self.jobs[i].to_dict(), **self._progress(self.jobs[i], now, lag)}
                    for i in reversed(self.order) if i in self.jobs]

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def tail(self, job_id: str, offset: int = 0, limit: int = 200_000) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        text, new_offset = "", offset
        if job.log_path.exists():
            with job.log_path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(limit)
                new_offset = offset + len(chunk)
                text = chunk.decode("utf-8", "replace")
        now = dt.datetime.now(dt.timezone.utc)
        lag = collector_lag(now)
        with self._lock:
            progress = self._progress(job, now, lag)
        out = {"job": {**job.to_dict(), **progress}, "text": text, "offset": new_offset,
               "done": job.status in FINISHED_STATES}
        if job.op == "loop-run":
            # parsed ONCE, here (tools/fleetcore/loopjob.py): the page and the
            # TUI render these fields rather than reading the raw lines
            out["loop"] = loop_job_fields(job.log_path)
        if job.op == "assist":
            out["assist"] = core.assist_job_fields(job)
        return out

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.proc and job.status == "running":
            job.status = "cancelled"
            try:
                os.killpg(os.getpgid(job.proc.pid), 15)
            except (ProcessLookupError, PermissionError):
                pass
            self._save()
        return job


# --------------------------------------------------------------------------- #
# STARTUP HEALTH — per-project health on a fresh clone
# --------------------------------------------------------------------------- #
# _data/project_health.yml is ephemeral (gitignored, fleetcore/fleet.py SOURCES):
# only `dash-gen health` writes it, so a fresh clone or a console left off for a
# week showed every row's health as blank and the red/amber/green KPIs as 0/0/0
# while triage said 20 repos were red. On startup the console now runs the same
# allowlisted `health` operation itself when the file is missing or older than
# the harness's stale_data_days — as an ordinary job (visible in the Jobs tab,
# cancellable), off the request path, and cancelled after a timeout so a slow or
# unauthenticated GitHub can never hold anything up. CONSOLE_AUTO_HEALTH=0 turns
# it off; CONSOLE_AUTO_HEALTH_TIMEOUT sets the timeout in seconds.
AUTO_HEALTH_TIMEOUT = 300


def health_refresh_reason(root: Path = core.REPO_ROOT, now: dt.datetime | None = None) -> str | None:
    """Why the health snapshot needs regenerating, or None when it is fresh."""
    if str(core.TOOLS) not in sys.path:
        sys.path.insert(0, str(core.TOOLS))
    from fleetcore import fleet as _fleet

    src = next((s for s in _fleet.read_sources(root, now=now) if s.name == "health"), None)
    if src is None or not src.present:
        return "missing"
    if src.age_days is None:
        return "undated"
    if src.stale:
        return f"stale ({src.age_days:.1f}d old, limit {_fleet.stale_days(root):g}d)"
    return None


def auto_health(jobs: "JobManager", root: Path = core.REPO_ROOT, now: dt.datetime | None = None,
                timeout: float | None = None) -> Job | None:
    """Start the `health` job when the snapshot is missing or stale. Never blocks,
    never raises: a failure to start is reported and the console carries on."""
    if (os.environ.get("CONSOLE_AUTO_HEALTH") or "1").strip().lower() in ("0", "off", "false", "no"):
        return None
    try:
        reason = health_refresh_reason(root, now)
    except Exception as exc:  # a broken signal file must not stop the console starting
        sys.stderr.write(f"[console] health check skipped: {exc}\n")
        return None
    if reason is None:
        return None
    if timeout is None:
        try:
            timeout = float(os.environ.get("CONSOLE_AUTO_HEALTH_TIMEOUT") or AUTO_HEALTH_TIMEOUT)
        except ValueError:
            timeout = AUTO_HEALTH_TIMEOUT
    try:
        job = jobs.submit("health")
    except Exception as exc:
        sys.stderr.write(f"[console] could not start the health job: {exc}\n")
        return None
    sys.stderr.write(f"[console] project health {reason} — generating it (job {job.id}, "
                     f"timeout {timeout:g}s)\n")

    def _expire() -> None:
        if job.status in ("queued", "running"):
            sys.stderr.write(f"[console] health job {job.id} exceeded {timeout:g}s — cancelled\n")
            jobs.cancel(job.id)

    timer = threading.Timer(timeout, _expire)
    timer.daemon = True
    timer.start()
    return job

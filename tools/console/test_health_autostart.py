#!/usr/bin/env python3
"""
Fixture tests for the console's startup health refresh (core.auto_health).

_data/project_health.yml is ephemeral, so a fresh clone used to show blank
per-project health and red/amber/green 0/0/0. Guards that the console:

  * starts the allowlisted `health` job when the snapshot is missing, undated or
    older than the harness's stale_data_days, and leaves a fresh one alone;
  * never blocks or raises on startup (a broken signal file, a refused submit),
    and cancels the job after its timeout;
  * honours CONSOLE_AUTO_HEALTH=0; and
  * runs it from the FastAPI lifespan, i.e. on every console start (skipped
    unless FastAPI is installed).

No network, no pytest — the job manager is a stub, nothing runs dash-gen:

    python3 tools/console/test_health_autostart.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path

# Never the live console's job dir: importing `app` builds its JobManager,
# which loads (and re-saves) the history it finds. Run inside the console
# container — the console's own Tests job does — that was the RUNNING
# console's index. core reads this at import, so it is set before any import.
os.environ["DASH_CONSOLE_JOBS"] = tempfile.mkdtemp(prefix="console-test-jobs-")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402

NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)


class FakeJob:
    def __init__(self, op):
        self.id, self.op, self.status = "job" + op, op, "running"


class FakeJobs:
    def __init__(self, refuse=False):
        self.submitted, self.cancelled, self.refuse = [], [], refuse

    def submit(self, op_id, params=None, confirm=False):
        if self.refuse:
            raise PermissionError("nope")
        job = FakeJob(op_id)
        self.submitted.append(job)
        return job

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        for j in self.submitted:
            if j.id == job_id:
                j.status = "cancelled"


def make_root(health_stamp: str | None, *, with_health=True, fleet_days=3) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "_data").mkdir()
    (root / "_data" / "projects.yml").write_text("- name: a\n")
    (root / "_data" / "fleet.yml").write_text(f"harness:\n  trip_wires:\n    stale_data_days: {fleet_days}\n")
    if with_health:
        (root / "_data" / "project_health.yml").write_text("- name: a\n  status: green\n")
    if health_stamp is not None:
        (root / "_data" / "project_health_meta.yml").write_text(f"generated_at: '{health_stamp}'\n")
    return root


def _env(**kw):
    saved = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return saved


def test_reason_missing_undated_stale_fresh():
    assert core.health_refresh_reason(make_root(None, with_health=False), NOW) == "missing"
    assert core.health_refresh_reason(make_root(None), NOW) == "undated"
    stale = core.health_refresh_reason(make_root("2026-10-10 06:00 UTC"), NOW)
    assert stale and stale.startswith("stale (5.2d old, limit 3d)"), stale
    assert core.health_refresh_reason(make_root("2026-10-14 06:00 UTC"), NOW) is None
    # the limit is the harness's own stale_data_days
    assert core.health_refresh_reason(make_root("2026-10-10 06:00 UTC", fleet_days=7), NOW) is None


def test_missing_health_starts_one_job_and_fresh_does_not():
    saved = _env(CONSOLE_AUTO_HEALTH=None)
    try:
        jobs = FakeJobs()
        job = core.auto_health(jobs, make_root(None, with_health=False), NOW, timeout=60)
        assert job is not None and [j.op for j in jobs.submitted] == ["health"]
        jobs = FakeJobs()
        assert core.auto_health(jobs, make_root("2026-10-15 06:00 UTC"), NOW, timeout=60) is None
        assert jobs.submitted == []
    finally:
        _env(**saved)


def test_timeout_cancels_a_running_job_but_not_a_finished_one():
    saved = _env(CONSOLE_AUTO_HEALTH=None)
    try:
        jobs = FakeJobs()
        job = core.auto_health(jobs, make_root(None, with_health=False), NOW, timeout=0.05)
        for _ in range(100):
            if jobs.cancelled:
                break
            time.sleep(0.02)
        assert jobs.cancelled == [job.id] and job.status == "cancelled"
        jobs = FakeJobs()
        job = core.auto_health(jobs, make_root(None, with_health=False), NOW, timeout=0.05)
        job.status = "succeeded"
        time.sleep(0.2)
        assert jobs.cancelled == []
    finally:
        _env(**saved)


def test_switch_off_bad_timeout_and_failures_never_raise():
    saved = _env(CONSOLE_AUTO_HEALTH="0")
    try:
        jobs = FakeJobs()
        assert core.auto_health(jobs, make_root(None, with_health=False), NOW) is None and not jobs.submitted
        _env(CONSOLE_AUTO_HEALTH="1", CONSOLE_AUTO_HEALTH_TIMEOUT="soon")
        job = core.auto_health(jobs, make_root(None, with_health=False), NOW)
        assert job is not None  # unparsable timeout falls back to the default
        assert core.auto_health(FakeJobs(refuse=True), make_root(None, with_health=False), NOW) is None
        broken = make_root(None)
        (broken / "_data" / "project_health_meta.yml").write_text("generated_at: [unclosed\n")
        assert core.auto_health(FakeJobs(), broken, NOW) is None  # yaml error is reported, not raised
    finally:
        _env(CONSOLE_AUTO_HEALTH_TIMEOUT=None)
        _env(**saved)


def test_health_op_is_the_allowlisted_dash_gen_health():
    argv, remote = core.build_argv("health", {})
    assert argv[-1] == "health" and argv[0].endswith("dash-gen") and remote is False


def test_console_start_runs_auto_health():
    try:
        import fastapi  # noqa: F401
        from fastapi.testclient import TestClient
    except Exception:
        print("    (skipped: fastapi / TestClient not installed)")
        return
    import app as console_app
    calls = []
    real = core.auto_health
    core.auto_health = lambda jobs, *a, **k: calls.append(jobs)
    try:
        with TestClient(console_app.app, base_url="http://127.0.0.1:4001") as client:
            assert client.get("/api/health").status_code in (200, 401)
        assert calls == [console_app.jobs], calls
    finally:
        core.auto_health = real


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — console startup-health tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

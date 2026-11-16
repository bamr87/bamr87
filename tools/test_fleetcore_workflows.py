#!/usr/bin/env python3
"""
Fixture tests for the fleet workflow model (tools/fleetcore/workflows.py,
fleet-workflows/v1) and the sync that fills it (.github/scripts/dash-gen/
workflow_sync.py, `tools/dash workflows sync`) — ADR 0007 phase S1, #721.

A fake GitHub (three fleet repositories, the hub and one external upstream)
is read through the REAL sync into a temporary lake, and the model is built
from that lake. They pin:

  * every registry repository and the hub is a row; an external upstream is
    never fetched and says why; one that cannot be read says why too, and
    shows read: false — never a pass; a later failed attempt keeps the time
    of the last read that worked;
  * workflow counts are what the listing holds (.yml/.yaml only), a deleted
    file leaves the model though its row stays in the lake, an unchanged
    blob is not fetched again (the conditional read), and the per-repo file
    cap marks the repo truncated;
  * check states: a verify caller that ran no scenario is passed-empty, a
    green CI run is verified, an API-quota failure is quota, a failure with
    no job and a workflow with no run are never-ran, a cancelled run is
    cancelled, a real error is real-failure with classify_failure's evidence;
  * a failed AI check's log is stored with its Claude facts, so `lake sync`,
    which never downloads a stored log again, cannot lose its cost and
    `lake review` never calls it a real $0;
  * the sync refuses before reading anything when GITHUB_ACTIONS is set or
    the event is a pull request, and its token never comes from GITHUB_TOKEN
    (`gh auth token` runs with every token variable removed);
  * the wall-clock budget and --max-repos turn the rest into "not read";
  * the model opens the lake read-only and leaves it byte-identical; a lake
    older than the sync, or none at all, reads as "never read";
  * fleet-verify.yml still has the step names the model reads as "empty".

No network, no gh, no pytest; PyYAML only:

    python3 tools/test_fleetcore_workflows.py
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / ".github" / "scripts" / "dash-gen"))

import fleet_lake  # noqa: E402
import workflow_sync as ws  # noqa: E402
from fleetcore import workflows as fw  # noqa: E402

NOW = "2026-11-15T12:00:00Z"
LATER = "2026-11-16T12:00:00Z"

FLEET = {"hub": {"repo": "bamr87/bamr87", "owners": ["bamr87", "bash-365"]},
         "harnesses": {"inventory": {"max_workflow_files": 40}}}
REGISTRY = [
    {"name": "alpha", "repo_url": "https://github.com/bamr87/alpha"},
    {"name": "beta", "repo_url": "https://github.com/bash-365/beta"},
    {"name": "gamma", "repo_url": "https://github.com/bamr87/gamma"},
    {"name": "upstream", "repo_url": "https://github.com/someone-else/upstream"},
]

HEAD = "permissions:\n  contents: read\n"
GATE = "name: {name}\non:\n  {on}\n" + HEAD + "jobs:\n  a:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - run: echo\n"
VERIFY = ("name: Verify\non:\n  pull_request:\n  push:\n    branches: [main]\n" + HEAD
          + "jobs:\n  verify:\n    uses: bamr87/bamr87/.github/workflows/fleet-verify.yml@v2\n")
NIGHTLY = ("name: nightly\non:\n  schedule:\n    - cron: '7 3 * * *'\n" + HEAD
           + "jobs:\n  a:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - run: echo\n")
# An AI check: a pull-request gate that runs Claude.
REVIEW = ("name: Claude review\non:\n  pull_request:\n" + HEAD
          + "jobs:\n  review:\n    runs-on: ubuntu-latest\n    timeout-minutes: 15\n    steps:\n"
          + "      - uses: anthropics/claude-code-action@v1\n")


def gate(name: str, on: str = "push:") -> str:
    return GATE.format(name=name, on=on)


# --------------------------------------------------------------------------- #
# a fake GitHub: PyGithub's repository object for the files, a requests
# session for the runs, jobs and logs
# --------------------------------------------------------------------------- #
class NotFound(Exception):
    def __init__(self, status: int = 404):
        super().__init__(f"HTTP {status}")
        self.status = status


class Entry:
    def __init__(self, path: str, text: str):
        self.path, self.name, self.type = path, Path(path).name, "file"
        self.sha = hashlib.sha1(text.encode()).hexdigest()


class Blob:
    def __init__(self, text: str):
        self.decoded_content = text.encode()


class Repo:
    def __init__(self, files: dict[str, str], archived: bool = False):
        self.files, self.archived, self.default_branch, self.fetched = files, archived, "main", []

    def get_contents(self, path: str):
        if path == ".github/workflows":
            if self.files is None:
                raise NotFound()
            return [Entry(f".github/workflows/{n}", t) for n, t in sorted(self.files.items())]
        self.fetched.append(path)
        return Blob(self.files[Path(path).name])


class Github:
    def __init__(self, repos: dict[str, Repo]):
        self.repos, self.asked = repos, []

    def get_repo(self, nwo: str):
        self.asked.append(nwo)
        if nwo not in self.repos:
            raise NotFound(404)
        return self.repos[nwo]


class Resp:
    def __init__(self, status: int, body=None, content: bytes = b""):
        self.status_code, self.body, self.content = status, body, content

    def json(self):
        return self.body


def log_zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("0_build.txt", text)
    return buf.getvalue()


class Session:
    """routes: workflow file name -> list of run dicts; run id -> (jobs, log text)."""

    def __init__(self, runs: dict[str, list[dict]], jobs: dict[int, list[dict]], logs: dict[int, str]):
        self.runs, self.jobs, self.logs, self.urls = runs, jobs, logs, []

    def get(self, url: str, params=None, timeout=None):
        self.urls.append(url)
        if url.startswith("https://logs/"):
            return Resp(200, content=log_zip(self.logs[int(url.rsplit("/", 1)[1])]))
        if "/actions/workflows/" in url:
            name = url.split("/actions/workflows/", 1)[1].split("/", 1)[0]
            if name not in self.runs:
                return Resp(404)
            return Resp(200, {"total_count": len(self.runs[name]), "workflow_runs": self.runs[name]})
        if "/actions/runs/" in url and url.endswith("/jobs"):
            rid = int(url.split("/actions/runs/", 1)[1].split("/", 1)[0])
            js = self.jobs.get(rid, [])
            return Resp(200, {"total_count": len(js), "jobs": js})
        return Resp(404)


def run(rid: int, nwo: str, file: str, conclusion: str, status: str = "completed") -> dict:
    return {"id": rid, "path": f".github/workflows/{file}", "name": file, "event": "push", "status": status,
            "conclusion": conclusion, "head_branch": "main", "head_sha": "abc", "run_attempt": 1, "run_number": rid,
            "created_at": "2026-11-15T10:00:00Z", "run_started_at": "2026-11-15T10:00:00Z",
            "updated_at": "2026-11-15T10:05:00Z", "html_url": f"https://github.com/{nwo}/actions/runs/{rid}",
            "logs_url": f"https://logs/{rid}"}


def job(jid: int, name: str, conclusion: str, steps: list[tuple[str, str]]) -> dict:
    return {"id": jid, "name": name, "status": "completed", "conclusion": conclusion, "html_url": "u",
            "started_at": NOW, "completed_at": NOW, "runner_name": "r",
            "steps": [{"number": i + 1, "name": n, "status": "completed", "conclusion": c,
                       "started_at": NOW, "completed_at": NOW} for i, (n, c) in enumerate(steps)]}


def fake_fleet(alpha_files: dict | None = None):
    repos = {
        "bamr87/bamr87": Repo({"ci.yml": gate("ci", "pull_request:")}),
        "bamr87/alpha": Repo(alpha_files if alpha_files is not None else
                             {"verify.yml": VERIFY, "nightly.yml": NIGHTLY, "README.md": "# not a workflow"}),
        "bash-365/beta": Repo({"build.yml": gate("build"), "lint.yml": gate("lint", "pull_request:"),
                               "docs.yml": gate("docs"), "deploy.yml": gate("deploy"), "tests.yml": gate("tests")}),
        # bamr87/gamma is missing: get_repo raises, as an unreachable repository does
    }
    runs = {
        "ci.yml": [run(1, "bamr87/bamr87", "ci.yml", "success")],
        "verify.yml": [run(2, "bamr87/alpha", "verify.yml", None, "in_progress"),
                       run(3, "bamr87/alpha", "verify.yml", "success")],
        "build.yml": [run(4, "bash-365/beta", "build.yml", "failure")],
        "lint.yml": [run(5, "bash-365/beta", "lint.yml", "failure")],
        "docs.yml": [],
        "deploy.yml": [run(6, "bash-365/beta", "deploy.yml", "cancelled")],
        "tests.yml": [run(7, "bash-365/beta", "tests.yml", "failure")],
    }
    jobs = {
        1: [job(11, "test", "success", [("Run tests", "success")]), job(12, "lint", "success", [("Lint", "success")])],
        3: [job(31, "verify / verify", "success", [("Read verify config", "success"),
                                                   ("Report that nothing was verified", "success"),
                                                   ("Run the user scenarios", "skipped")])],
        4: [job(41, "build", "failure", [("Install", "failure")])],
        5: [],  # a failure with no job: held for approval
        6: [job(61, "deploy", "cancelled", [("Deploy", "cancelled")])],
        7: [job(71, "tests", "failure", [("pytest", "failure")])],
    }
    logs = {4: "2026-11-15T10:01:00Z ##[error]API rate limit exceeded for installation ID 123.\n",
            7: "2026-11-15T10:01:00Z FAILED tests/test_x.py::test_y - AssertionError: 1 != 2\n"
               "2026-11-15T10:01:01Z ##[error]Process completed with exit code 1.\n"}
    return Github(repos), Session(runs, jobs, logs)


def opts(**kw) -> argparse.Namespace:
    base = dict(ws.DEFAULTS, max_files=40, max_checks=6)
    return argparse.Namespace(**(base | kw))


class Fixture:
    """A data root (fleet.yml, projects.yml) and a lake directory, both temporary."""

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="fleet-wf-"))
        (self.dir / "_data").mkdir()
        (self.dir / "_data" / "fleet.yml").write_text(json.dumps(FLEET), encoding="utf-8")
        (self.dir / "_data" / "projects.yml").write_text(json.dumps(REGISTRY), encoding="utf-8")
        self.lake = self.dir / "lake"
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)

    def sync(self, gh, session, now: str = NOW, clock=None, **kw):
        conn = fleet_lake.connect(self.lake)
        try:
            plan = ws.targets(REGISTRY, FLEET)
            args = [conn, gh, ws.Api(session), plan, "bamr87/bamr87", opts(**kw), now]
            return ws.run_sync(*args, clock=clock, log=io.StringIO()) if clock else \
                ws.run_sync(*args, log=io.StringIO())
        finally:
            conn.close()

    def model(self) -> dict:
        return fw.build(self.dir, self.lake)


def repo(model: dict, nwo: str) -> dict:
    return next(r for r in model["repos"] if r["nwo"] == nwo)


def wf(model: dict, nwo: str, wid: str) -> dict:
    return next(w for w in repo(model, nwo)["workflows"] if w["id"] == wid)


# --------------------------------------------------------------------------- #
# the sync → the model
# --------------------------------------------------------------------------- #
def test_every_repo_is_a_row_and_a_missed_one_is_not_a_pass():
    with Fixture() as fx:
        gh, session = fake_fleet()
        results = fx.sync(gh, session)
        assert [r["nwo"] for r in results] == ["bamr87/bamr87", "bamr87/alpha", "bash-365/beta", "bamr87/gamma",
                                               "someone-else/upstream"]
        assert "someone-else/upstream" not in gh.asked, "an external upstream must never be fetched"
        m = fx.model()
        assert m["schema"] == "fleet-workflows/v1"
        s = m["summary"]
        assert (s["repos"], s["read"], s["not_read"], s["external"]) == (5, 3, 2, 1), s
        gamma = repo(m, "bamr87/gamma")
        assert gamma["read"] is False and gamma["workflows"] == [] and "unreachable" in gamma["reason"], gamma
        assert gamma["checks"]["verified"] == 0 and gamma["verify"] is None
        ext = repo(m, "someone-else/upstream")
        assert ext["read"] is False and ext["owned"] is False and "external upstream" in ext["reason"]
        for nwo in ("bamr87/bamr87", "bamr87/alpha", "bash-365/beta"):
            assert repo(m, nwo)["read"] and repo(m, nwo)["read_at"] == NOW, nwo


def test_workflow_counts_are_what_the_listing_holds():
    with Fixture() as fx:
        fx.sync(*fake_fleet())
        m = fx.model()
        alpha = repo(m, "bamr87/alpha")
        assert alpha["files"] == 2 and len(alpha["workflows"]) == 2, alpha  # README.md is not a workflow
        assert {w["id"] for w in alpha["workflows"]} == {"verify", "nightly"}
        assert len(repo(m, "bash-365/beta")["workflows"]) == 5
        assert m["summary"]["workflows"] == 1 + 2 + 5


def test_check_states_from_the_latest_runs():
    with Fixture() as fx:
        fx.sync(*fake_fleet())
        m = fx.model()
        hub_ci = wf(m, "bamr87/bamr87", "ci")["check"]
        assert hub_ci["state"] == "verified" and "2 job(s) ran" in hub_ci["evidence"], hub_ci
        v = wf(m, "bamr87/alpha", "verify")
        assert v["check_kind"] == "verify"
        assert v["check"]["state"] == "passed-empty", v["check"]
        assert v["check"]["run"]["id"] == 3, "the latest COMPLETED run, not the one still in progress"
        assert repo(m, "bamr87/alpha")["verify"] == "passed-empty"
        assert wf(m, "bamr87/alpha", "nightly")["check_kind"] is None, "a schedule is not a check"
        beta = {w["id"]: w["check"] for w in repo(m, "bash-365/beta")["workflows"]}
        assert beta["build"]["state"] == "quota" and beta["build"]["cause"] == "api-rate-limit", beta["build"]
        assert beta["lint"]["state"] == "never-ran" and "no job" in beta["lint"]["evidence"], beta["lint"]
        assert beta["docs"]["state"] == "never-ran" and "No run" in beta["docs"]["evidence"], beta["docs"]
        assert beta["deploy"]["state"] == "cancelled"
        assert beta["tests"]["state"] == "real-failure" and beta["tests"]["class"] == "defect", beta["tests"]
        assert "AssertionError" in beta["tests"]["evidence"] and beta["tests"]["failed_step"] == "tests › pytest"
        s = m["summary"]
        assert s["checks"]["verified"] == 1 and s["healthy_checks"] == 1, s["checks"]
        assert s["verify"]["passed-empty"] == 1


def test_a_green_check_that_verified_nothing_is_not_healthy():
    with Fixture() as fx:
        fx.sync(*fake_fleet())
        s = fx.model()["summary"]
        green = s["checks"]["verified"] + s["checks"]["passed-empty"]
        assert green == 2 and s["healthy_checks"] == 1, s


def test_logs_are_downloaded_only_for_failed_runs():
    with Fixture() as fx:
        gh, session = fake_fleet()
        fx.sync(gh, session)
        downloaded = sorted(int(u.rsplit("/", 1)[1]) for u in session.urls if u.startswith("https://logs/"))
        assert downloaded == [4, 7], downloaded  # not the green runs, not the zero-job or cancelled ones


def test_a_failed_ai_checks_claude_cost_is_recorded_from_the_log_it_stores():
    """`lake sync` takes a stored log as already parsed and never downloads it again, so the
    sync records Claude's facts from the failed AI check's log it stores, or that run's cost
    is lost and `lake review` calls it a real $0 ('no-claude-step')."""
    with Fixture() as fx:
        gh, session = fake_fleet()
        gh.repos["bamr87/alpha"].files["review.yml"] = REVIEW
        session.runs["review.yml"] = [run(8, "bamr87/alpha", "review.yml", "failure") | {"event": "pull_request"}]
        session.jobs[8] = [job(81, "review", "failure", [("Run Claude", "failure")])]
        session.logs[8] = ('2026-11-15T10:01:00Z {"type":"result","subtype":"error_max_turns","is_error":true,'
                           '"duration_ms":90000,"num_turns":12,"total_cost_usd":4.25}\n'
                           "2026-11-15T10:01:01Z ##[error]Process completed with exit code 1.\n")
        fx.sync(gh, session)
        assert "https://logs/8" in session.urls, "the failed AI check's log was not downloaded"
        with contextlib.closing(sqlite3.connect(fx.lake / "fleet.sqlite")) as conn:
            ai = conn.execute("SELECT ai FROM runs WHERE id=8").fetchone()
            agent = conn.execute("SELECT nwo, cost_usd, num_turns FROM agent_runs WHERE run_id=8").fetchone()
        assert ai == (1,), f"review.yml is an AI workflow: {ai}"
        assert agent == ("bamr87/alpha", 4.25, 12), f"Claude's facts were not recorded: {agent}"
        real = fleet_lake.utcnow
        fleet_lake.utcnow = lambda: dt.datetime(2026, 11, 16, 12, tzinfo=dt.timezone.utc)
        try:
            ci = fleet_lake.review(fx.lake, repo="bamr87/alpha")["ci"]
        finally:
            fleet_lake.utcnow = real
        review_wf = next(w for w in ci["workflows"] if w["workflow_path"] == ".github/workflows/review.yml")
        assert review_wf["cost_usd"] == 4.25 and review_wf["cost_unknown"] == 0, review_wf
        assert ci["cost_usd"] == 4.25 and ci["agent_runs"] == 1, ci


def test_a_later_sync_reads_only_changed_blobs_and_drops_deleted_files():
    with Fixture() as fx:
        gh, session = fake_fleet()
        fx.sync(gh, session)
        alpha = gh.repos["bamr87/alpha"]
        assert sorted(alpha.fetched) == [".github/workflows/nightly.yml", ".github/workflows/verify.yml"]
        alpha.fetched.clear()
        del alpha.files["nightly.yml"]
        fx.sync(gh, session, now=LATER)
        assert alpha.fetched == [], "an unchanged blob was fetched again"
        m = fx.model()
        assert [w["id"] for w in repo(m, "bamr87/alpha")["workflows"]] == ["verify"]
        assert repo(m, "bamr87/alpha")["read_at"] == LATER
        with contextlib.closing(sqlite3.connect(fx.lake / "fleet.sqlite")) as conn:
            kept = conn.execute("SELECT COUNT(*) FROM workflows WHERE nwo='bamr87/alpha'").fetchone()[0]
        assert kept == 2, "the lake keeps the deleted file's row; the model reads through `paths`"


def test_a_failed_later_attempt_keeps_the_last_good_read_time():
    with Fixture() as fx:
        gh, session = fake_fleet()
        fx.sync(gh, session)
        gh.repos.pop("bamr87/alpha")
        fx.sync(gh, session, now=LATER)
        alpha = repo(fx.model(), "bamr87/alpha")
        assert alpha["read"] is False and alpha["workflows"] == []
        assert alpha["read_at"] == NOW and f"last read {NOW}" in alpha["reason"], alpha


def test_a_repo_with_no_workflows_directory_is_read_with_zero():
    with Fixture() as fx:
        gh, session = fake_fleet()
        gh.repos["bamr87/alpha"].files = None  # the listing 404s
        fx.sync(gh, session)
        alpha = repo(fx.model(), "bamr87/alpha")
        assert alpha["read"] is True and alpha["files"] == 0 and alpha["workflows"] == [], alpha


def test_the_file_cap_marks_the_repo_truncated():
    with Fixture() as fx:
        fx.sync(*fake_fleet(), max_files=2)
        m = fx.model()
        beta = repo(m, "bash-365/beta")
        assert beta["truncated"] and beta["files"] == 5 and len(beta["workflows"]) == 2, beta
        assert "max_workflow_files" in beta["reason"]
        assert m["summary"]["truncated"] == ["bash-365/beta"]


def test_the_check_cap_leaves_the_rest_unknown_and_verify_goes_first():
    with Fixture() as fx:
        fx.sync(*fake_fleet(), max_checks=1)
        m = fx.model()
        assert wf(m, "bamr87/alpha", "verify")["check"]["state"] == "passed-empty"
        beta = {w["id"]: w["check"]["state"] for w in repo(m, "bash-365/beta")["workflows"]}
        assert sum(1 for s in beta.values() if s) == 1, beta
        assert beta["build"] == "quota", "a CI-named gate is read before the others"
        assert m["summary"]["checks"][fw.UNKNOWN] == 4


def test_the_budget_and_the_repo_cap_turn_the_rest_into_not_read():
    with Fixture() as fx:
        ticks = iter([0.0] + [0.0] * 3 + [10_000.0] * 50)
        results = fx.sync(*fake_fleet(), clock=lambda: next(ticks), budget_s=60)
        missed = {r["nwo"]: r["reason"] for r in results if not r["read"]}
        assert "time budget" in missed["bash-365/beta"] and "time budget" in missed["bamr87/gamma"], missed
    with Fixture() as fx:
        results = fx.sync(*fake_fleet(), max_repos=1)
        missed = {r["nwo"]: r["reason"] for r in results if not r["read"]}
        assert set(missed) == {"bamr87/alpha", "bash-365/beta", "bamr87/gamma", "someone-else/upstream"}
        assert "max-repos" in missed["bamr87/alpha"]


def test_archived_repos_are_read_but_their_runs_are_not():
    with Fixture() as fx:
        gh, session = fake_fleet()
        gh.repos["bamr87/alpha"].archived = True
        fx.sync(gh, session)
        assert not any("/verify.yml/" in u for u in session.urls)
        v = wf(fx.model(), "bamr87/alpha", "verify")
        assert v["check"]["state"] is None and "Archived" in v["check"]["evidence"]


def test_the_model_opens_the_lake_read_only():
    with Fixture() as fx:
        fx.sync(*fake_fleet())
        db = fx.lake / "fleet.sqlite"
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        fx.model()
        fw.view(fx.dir, lake_dir=fx.lake)
        assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_no_lake_and_an_old_lake_read_as_never_read():
    with Fixture() as fx:
        m = fx.model()
        assert m["lake"]["present"] is False and m["summary"]["read"] == 0
        assert "no lake" in repo(m, "bamr87/alpha")["reason"]
        fx.lake.mkdir()
        with contextlib.closing(sqlite3.connect(fx.lake / "fleet.sqlite")) as conn:
            conn.execute("CREATE TABLE workflows (nwo TEXT, path TEXT)")  # a lake from before the sync
        m = fx.model()
        assert m["lake"]["present"] is True and m["summary"]["read"] == 0
        assert repo(m, "bamr87/alpha")["reason"].startswith("never read")


def test_lint_uses_hub_rules_only_for_the_hub():
    with Fixture() as fx:
        gh, session = fake_fleet()
        sched = NIGHTLY.replace("7 3 * * *", "0 3 * * *")
        gh.repos["bamr87/bamr87"].files["nightly.yml"] = sched
        gh.repos["bamr87/alpha"].files["nightly.yml"] = sched
        fx.sync(gh, session)
        m = fx.model()
        hub_rules = {f["rule"] for f in wf(m, "bamr87/bamr87", "nightly")["findings"]}
        alpha_rules = {f["rule"] for f in wf(m, "bamr87/alpha", "nightly")["findings"]}
        assert {"cron-declared", "cron-on-hour"} <= hub_rules, hub_rules
        assert not ({"cron-declared", "cron-on-hour"} & alpha_rules), alpha_rules
        assert all(f["repo"] == "bamr87/alpha" for f in wf(m, "bamr87/alpha", "nightly")["findings"])


def test_view_serves_the_catalog_a_repo_and_one_workflow():
    with Fixture() as fx:
        fx.sync(*fake_fleet())
        cat = fw.view(fx.dir, lake_dir=fx.lake)
        assert cat["summary"]["repos"] == len(cat["repos"]) == 5
        assert {r["nwo"]: r["workflows"] for r in cat["repos"]}["bamr87/alpha"] == 2
        one = fw.view(fx.dir, repo="alpha", lake_dir=fx.lake)
        assert one["repo"]["nwo"] == "bamr87/alpha" and {w["id"] for w in one["workflows"]} == {"verify", "nightly"}
        assert next(w for w in one["workflows"] if w["id"] == "verify")["state"] == "passed-empty"
        full = fw.view(fx.dir, repo="bash-365/beta", workflow="build.yml", lake_dir=fx.lake)
        assert full["workflow"]["check"]["state"] == "quota" and full["workflow"]["jobs"]
        for bad in ({"repo": "no-such-repo"}, {"repo": "gamma", "workflow": "ci"}):
            try:
                fw.view(fx.dir, lake_dir=fx.lake, **bad)
            except KeyError:
                continue
            raise AssertionError(f"{bad} should be a KeyError")


def test_the_cli_lists_reads_and_misses():
    with Fixture() as fx:
        fx.sync(*fake_fleet())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fw.main(["--fleet", "--root", str(fx.dir), "list", "--lake", str(fx.lake)])
        text = out.getvalue()
        assert code == 0 and "3 of 5 repos read" in text and "not read (2)" in text, text
        assert "bamr87/gamma" in text and "unreachable" in text
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fw.main(["--root", str(fx.dir), "lint", "--lake", str(fx.lake), "--repo", "beta"])
        assert code == 0 and "0 error(s)" in out.getvalue(), out.getvalue()
        with contextlib.redirect_stderr(io.StringIO()):
            assert fw.main(["--root", str(fx.dir), "show", "nope", "--lake", str(fx.lake)]) == 1


# --------------------------------------------------------------------------- #
# guardrails
# --------------------------------------------------------------------------- #
def test_the_sync_refuses_in_ci_and_on_pull_requests_before_reading_anything():
    for env in ({"GITHUB_ACTIONS": "true"}, {"GITHUB_EVENT_NAME": "pull_request"},
                {"GITHUB_EVENT_NAME": "pull_request_target"}):
        assert ws.refusal(env), env
    assert ws.refusal({}) is None and ws.refusal({"GITHUB_ACTIONS": "false", "GITHUB_EVENT_NAME": "push"}) is None
    with Fixture() as fx:
        real = ws.operator_token

        def boom(*_a, **_k):
            raise AssertionError("a refused sync must not look for a token")

        saved = {k: os.environ.get(k) for k in ("GITHUB_ACTIONS", "GITHUB_EVENT_NAME")}
        ws.operator_token = boom
        try:
            for key, value in (("GITHUB_ACTIONS", "true"), ("GITHUB_EVENT_NAME", "pull_request")):
                os.environ.pop("GITHUB_ACTIONS", None)
                os.environ.pop("GITHUB_EVENT_NAME", None)
                os.environ[key] = value
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = ws.main(["--lake", str(fx.lake)])
                assert code != 0 and "refused" in err.getvalue() and "Nothing was read" in err.getvalue()
                assert not fx.lake.exists(), "a refused sync created the lake"
        finally:
            ws.operator_token = real
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_the_token_never_comes_from_github_token():
    seen = {}

    class Out:
        returncode, stdout = 0, "gho_operator\n"

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        return Out()

    token, source = ws.operator_token({"GITHUB_TOKEN": "ghs_job", "PATH": "/bin"}, run=fake_run)
    assert (token, source) == ("gho_operator", "gh auth token")
    assert seen["cmd"] == ["gh", "auth", "token"]
    assert "GITHUB_TOKEN" not in seen["env"] and "GH_TOKEN" not in seen["env"] and seen["env"]["PATH"] == "/bin"
    token, source = ws.operator_token({"GH_TOKEN": "gho_mine", "GITHUB_TOKEN": "ghs_job"},
                                      run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh was run")))
    assert (token, source) == ("gho_mine", "GH_TOKEN")

    class NotLoggedIn:
        returncode, stdout = 1, ""

    assert ws.operator_token({"GITHUB_TOKEN": "ghs_job"}, run=lambda *a, **k: NotLoggedIn())[0] is None

    def missing(*_a, **_k):
        raise FileNotFoundError("gh")

    assert ws.operator_token({"GITHUB_TOKEN": "ghs_job"}, run=missing)[0] is None


def test_targets_are_the_hub_and_the_registry_once_each():
    plan = ws.targets(REGISTRY + [{"name": "dup", "repo_url": "https://github.com/bamr87/alpha.git"}], FLEET)
    assert [t["nwo"] for t in plan] == ["bamr87/bamr87", "bamr87/alpha", "bash-365/beta", "bamr87/gamma",
                                        "someone-else/upstream"]
    assert plan[0]["hub"] and [t["owned"] for t in plan] == [True, True, True, True, False]
    assert [t["nwo"] for t in ws.targets(REGISTRY, FLEET, ["beta", "bamr87/gamma"])] == ["bash-365/beta", "bamr87/gamma"]


def test_check_state_pure_cases():
    ok = {"id": 1, "status": "completed", "conclusion": "success"}
    assert fw.check_state(None)["state"] == "never-ran"
    assert fw.check_state({**ok, "status": "action_required", "conclusion": None})["state"] == "never-ran"
    assert fw.check_state({**ok, "status": "in_progress", "conclusion": None})["state"] is None
    assert fw.check_state({**ok, "conclusion": "skipped"})["state"] == "passed-empty"
    assert fw.check_state({**ok, "conclusion": "stale"})["state"] == "never-ran"
    assert fw.check_state(ok, [{"conclusion": "skipped"}, {"conclusion": "skipped"}])["state"] == "passed-empty"
    assert fw.check_state(ok, [{"conclusion": "success"}])["state"] == "verified"
    warn = ["2026-11-15T10:00:00Z ##[warning]verify/verify.yml sets no app.start or app.static_dir, so no scenario ran."]
    assert fw.check_state(ok, None, [], warn)["state"] == "passed-empty"
    failed = {**ok, "conclusion": "failure"}
    usage = ["2026-11-15T10:00:00Z ##[error]Claude AI usage limit reached"]
    assert fw.check_state(failed, [{"conclusion": "failure"}], [], usage)["state"] == "quota"
    startup = fw.check_state({**ok, "conclusion": "startup_failure"}, [])
    assert startup["state"] == "real-failure" and startup["cause"] == "startup", startup
    assert fw.check_state(failed, None)["state"] == "real-failure", "unknown jobs are not a zero-job run"


def test_the_empty_step_names_are_fleet_verifys_own():
    text = (ROOT / ".github" / "workflows" / "fleet-verify.yml").read_text(encoding="utf-8")
    for name in fw.EMPTY_STEPS:
        assert f"- name: {name}\n" in text, f"fleet-verify.yml has no step {name!r}; update EMPTY_STEPS"
    assert "title=Not verified::" in text and fw.EMPTY_RX.search("Not verified")


def main() -> int:
    failed = 0
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as exc:  # noqa: BLE001 — a crash in one case is a failure of that case, reported
            failed += 1
            print(f"  ✗ {name}: {exc.__class__.__name__}: {exc}")
    print(f"{'FAIL' if failed else 'OK'} — {len(cases) - failed}/{len(cases)} fleet workflow model tests")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

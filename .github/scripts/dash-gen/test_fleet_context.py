#!/usr/bin/env python3
"""
Fixture tests for fleet_context.py — the read-only planes behind JEV's loop
context pack.

Guards the properties that let a HOST hand a sealed agent context without
handing it this machine:

  * the document keeps its contract (`fleet-context/v1`, five sections, each
    with status/source/as_of/age_hours/note/elapsed_ms/truncated/rows), and
    every section's rows and caps are what the engine half is built against;
  * lake_issues is CLOSED-only, newest first, capped, scout-flagged; lake_ci
    counts the tracked branch without pull-request runs, computes the failure
    streak over verdicts and names the failing job / step; lake_agents carries
    aggregates and command HEADS only — never a prompt, a cwd or a branch;
  * the code index keeps code from the hub and the target and withholds a
    sibling's (its visibility is unknown);
  * redaction masks $HOME, the host name, temp dirs and credential shapes
    across the whole document, whichever plane the text came from;
  * freshness: a sync older than 72 h is `stale` with its refresh command,
    rows still included;
  * a plane that refuses, a missing lake, a missing table and the overall
    deadline each cost one section, never the document, and exit 0; a bad
    request exits 2;
  * the lake is never written: a 0444 file in a 0555 directory, bytes and
    mtime unchanged, and the connection itself refuses a write; the HTTP side
    refuses any route that is not a read before a socket opens.

No network beyond in-process stubs on 127.0.0.1, no gh, no claude, no pytest.
Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_fleet_context.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_context as fc  # noqa: E402
import fleet_lake as fl  # noqa: E402

NOW = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.timezone.utc)
NWO = "bamr87/zer0-CMS"
NAME = "zer0-cms"
FAKE_HOME = "/Users/alice"
FAKE_HOST = "build-host-7.lan"
GH_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
ANT_KEY = "sk-ant-api03-" + "x" * 40
SENTINELS = ("SECRET-PROMPT-TEXT", "secret-cwd-dir", "secret-branch-name")


def ago(hours: float = 0, days: float = 0) -> str:
    return fl.iso(NOW - dt.timedelta(hours=hours, days=days))


def scrubber() -> fc.Scrubber:
    return fc.Scrubber(home=FAKE_HOME, hosts=[FAKE_HOST, "build-host-7"], paths=[])


@contextlib.contextmanager
def _env(**values):
    """Only the given plane/override variables set, whatever the shell has."""
    keys = ("QDRANT_URL", "OLLAMA_URL", "ES_URL", "QDRANT_COLLECTION", "HTTP_PROXY", "http_proxy")
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in values.items() if v})
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


@contextlib.contextmanager
def _tmp():
    d = Path(tempfile.mkdtemp(prefix="fleet-context-test-"))
    try:
        yield d
    finally:
        for p in [d, *d.rglob("*")]:
            with contextlib.suppress(OSError):
                p.chmod(0o755 if p.is_dir() else 0o644)
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# fixture lake
# --------------------------------------------------------------------------- #
def make_lake(root: Path, *, sync_age_h: float | None = 2, schema: bool = True) -> Path:
    d = root / "lake"
    d.mkdir()
    conn = sqlite3.connect(d / fl.DB_NAME)
    if schema:
        conn.executescript(fl.SCHEMA_SQL)
    else:
        conn.execute("CREATE TABLE syncs (id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT)")
    if sync_age_h is not None:
        conn.execute("INSERT INTO syncs (started_at, finished_at) VALUES (?, ?)",
                     (ago(hours=sync_age_h + 0.1), ago(hours=sync_age_h)))
    conn.commit()
    conn.close()
    return d


def _insert(lake: Path, table: str, rows: list[dict]) -> None:
    conn = sqlite3.connect(lake / fl.DB_NAME)
    for row in rows:
        cols = list(row)
        conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [row[c] for c in cols])
    conn.commit()
    conn.close()


def _issue(number, *, nwo=NWO, state="closed", closed_h=1.0, is_pr=0, labels=(), title=None):
    return {"nwo": nwo, "number": number, "title": title or f"Issue {number}", "state": state,
            "is_pr": is_pr, "labels": json.dumps(list(labels)), "author": "bamr87",
            "created_at": ago(days=35), "updated_at": ago(hours=closed_h),
            "closed_at": ago(hours=closed_h) if state == "closed" else None,
            "html_url": f"https://github.com/{nwo}/issues/{number}", "body": "body text"}


_RUN_ID = [1000]


def _run(path, conclusion, hours, *, nwo=NWO, branch="main", event="push", name=None):
    _RUN_ID[0] += 1
    return {"id": _RUN_ID[0], "nwo": nwo, "workflow_path": path, "workflow_name": name or Path(path).stem,
            "event": event, "status": "completed" if conclusion else "in_progress",
            "conclusion": conclusion, "head_branch": branch, "created_at": ago(hours=hours),
            "updated_at": ago(hours=hours), "html_url": "https://example.invalid", "ai": 0}


def _session(key, *, repo=NAME, hours=5, synced_h=1, calls=10, errors=2):
    return {"key": key, "session_id": key, "transcript": f"{FAKE_HOME}/.claude/projects/x/{key}.jsonl",
            "repo": repo, "cwd": f"{FAKE_HOME}/{SENTINELS[1]}", "git_branch": SENTINELS[2],
            "tool_calls": calls, "tool_errors": errors, "cost_usd": 1.5,
            "started_at": ago(hours=hours), "ended_at": ago(hours=hours - 0.5),
            "first_prompt": SENTINELS[0], "synced_at": ago(hours=synced_h)}


def _tool(key, seq, command, *, name="Bash", is_error=1, hours=4):
    return {"key": key, "idx": 0, "seq": seq, "name": name, "is_error": is_error,
            "input": json.dumps({"command": command, "description": "x"}), "started_at": ago(hours=hours)}


def rich_lake(root: Path, *, sync_age_h: float = 2, sessions_h: float = 1) -> Path:
    lake = make_lake(root, sync_age_h=sync_age_h)
    issues = [_issue(100 + i, closed_h=1 + i, is_pr=i % 2) for i in range(30)]
    issues[0]["labels"] = json.dumps(["ai-scout", "bug"])
    issues[1]["title"] = f"fix\x1b[31m the build \u202e{FAKE_HOME}/repo {GH_TOKEN}\x00 " + "x" * 200
    issues += [_issue(1, state="open"), _issue(2, closed_h=24 * 40),
               _issue(3, nwo="bamr87/law-ai")]
    _insert(lake, "issues", issues)

    ci = [_run(".github/workflows/ci.yml", c, h, name="CI")
          for c, h in (("failure", 1), ("failure", 2), ("skipped", 3), ("failure", 4), ("success", 5))]
    pages = [_run(".github/workflows/pages.yml", c, h) for c, h in (("success", 1), ("failure", 6))]
    lint = [_run(".github/workflows/lint.yml", "success", h) for h in (1, 2)]
    noise = [_run(".github/workflows/lint.yml", "failure", 1.5, branch="feat/x", event="pull_request"),
             _run(".github/workflows/lint.yml", "failure", 1.6, branch="main", event="pull_request"),
             _run(".github/workflows/lint.yml", "failure", 1.7, branch="feat/y", event="push"),
             _run(".github/workflows/lint.yml", "failure", 24 * 40),
             _run(".github/workflows/ci.yml", "failure", 1, nwo="bamr87/law-ai")]
    _insert(lake, "runs", ci + pages + lint + noise)
    failed = ci[0]["id"]
    _insert(lake, "jobs", [
        {"id": 1, "run_id": failed, "nwo": NWO, "name": "build", "status": "completed", "conclusion": "failure"},
        {"id": 2, "run_id": failed, "nwo": NWO, "name": "lint", "status": "completed", "conclusion": "success"},
        {"id": 3, "run_id": ci[1]["id"], "nwo": NWO, "name": "deploy", "status": "completed",
         "conclusion": "failure"},
    ])
    _insert(lake, "steps", [
        {"job_id": 1, "number": 1, "name": "Checkout", "status": "completed", "conclusion": "success"},
        {"job_id": 1, "number": 4, "name": "Run tests", "status": "completed", "conclusion": "failure"},
        {"job_id": 2, "number": 1, "name": "ruff", "status": "completed", "conclusion": "success"},
    ])
    _insert(lake, "agent_runs", [
        {"run_id": ci[0]["id"], "nwo": NWO, "model": "claude-opus-5-5", "num_turns": 12, "cost_usd": 0.5,
         "permission_denials": 2, "is_error": 1, "started_at": ago(hours=1)},
        {"run_id": ci[1]["id"], "nwo": NWO, "model": "claude-sonnet-5-5", "num_turns": 3, "cost_usd": 0.25,
         "permission_denials": 0, "is_error": 0, "started_at": "2026-10-31T09:00:00.1234567Z"},
        {"run_id": 99, "nwo": "bamr87/law-ai", "model": "x", "num_turns": 1, "cost_usd": 9.0,
         "permission_denials": 0, "is_error": 0, "started_at": ago(hours=1)},
    ])
    s1, s2 = _session("s1", synced_h=sessions_h), _session("s2", hours=3, synced_h=sessions_h)
    _insert(lake, "sessions", [s1, s2, _session("s3", repo="law-ai", synced_h=sessions_h)])
    _insert(lake, "session_tools", [
        _tool("s1", 1, f"cd {FAKE_HOME}/repo && bundle exec jekyll build --trace"),
        _tool("s1", 2, "cd /tmp/x && bundle exec jekyll serve"),
        _tool("s2", 1, f"cd {FAKE_HOME}/repo && bundle exec jekyll doctor", hours=2),
        _tool("s2", 2, f"GH_TOKEN={GH_TOKEN} gh api user"),
        _tool("s2", 3, "set -e; make test"),
        _tool("s2", 4, "set -euo pipefail\nmake test"),
        _tool("s2", 5, "make test", is_error=0),
        _tool("s2", 6, "cat x", name="Read"),
        _tool("s3", 1, "never this repo"),
    ])
    return lake


# --------------------------------------------------------------------------- #
# plane stubs
# --------------------------------------------------------------------------- #
class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def handle_error(self, request, client_address):
        # A client that gave up (the deadline test) closes its socket mid-reply;
        # that is the behaviour under test, so the stub records it, not a traceback.
        self.errors = getattr(self, "errors", 0) + 1


class Stub:
    """One loopback server answering for Qdrant, Ollama and Elasticsearch alike."""

    def __init__(self, routes: dict, delay: float = 0.0):
        self.routes, self.delay, self.requests = routes, delay, []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"null") if length else None
                stub.requests.append((self.command, self.path, body))
                if stub.delay:
                    time.sleep(stub.delay)
                fn = stub.routes.get((self.command, self.path))
                code, doc = fn(body) if fn else (404, {"error": "no route"})
                data = json.dumps(doc).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _answer

            def log_message(self, *_args):
                return None

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


CHUNK_40 = "\n".join(f"line {i:02d} " + "y" * 30 for i in range(40))


def _hit(path, score, chunk="code"):
    return {"id": path, "score": score,
            "payload": {"filePath": path, "startLine": "10", "endLine": "52", "codeChunk": chunk}}


def index_routes(collections=("ws-test",)):
    searches = {
        0: [_hit("tools/dash", 0.91, CHUNK_40), _hit(f"projects/{NAME}/site/_config.yml", 0.88),
            _hit("projects/law-ai/secret.py", 0.87, "PRIVATE SIBLING CODE"),
            _hit(f"projects/{NAME}/Gemfile", 0.80), _hit("docs/DASH.md", 0.79),
            _hit("projects/law-ai/b.py", 0.70, "PRIVATE SIBLING CODE"),
            _hit("projects/law-ai/low.py", 0.40, "PRIVATE SIBLING CODE")],
        1: [_hit("projects/bashos/x.sh", 0.77, "PRIVATE SIBLING CODE")],
    }
    return {
        ("GET", "/collections"): lambda _b: (200, {"result": {"collections": [{"name": n} for n in collections]}}),
        **{("GET", f"/collections/{n}"): (lambda _b, n=n: (200, {"result": {"points_count": len(n) * 10}}))
           for n in collections},
        ("POST", "/api/embed"): lambda b: (200, {"embeddings": [[float(i), 0.5, 0.25]
                                                                 for i, _ in enumerate(b["input"])]}),
        ("POST", "/collections/ws-test/points/search"): lambda b: (200, {"result": searches.get(int(b["vector"][0]), [])}),
        ("POST", "/collections/ws-test/points/count"): lambda b: (200, {"result": {"count": 302}}),
    }


def es_doc(tool, command=None, ts="2026-10-31T10:00:00.000Z", raw=None):
    claude = {"tool_name": tool, "event_name": "tool_result", "success": "false",
              "user_email": "someone@example.com", "session_id": "abc"}
    if raw is not None:
        claude["tool_input"] = raw
    elif command is not None:
        claude["tool_input"] = json.dumps({"command": command, "description": "d"})
    return {"_source": {"@timestamp": ts, "claude": claude}}


def es_routes(hits=None, newest="2026-10-31T11:30:00.000Z", api_errors=4, total=900):
    hits = hits if hits is not None else [
        es_doc("Bash", f"cd {FAKE_HOME}/x && bundle exec jekyll build", "2026-10-31T10:05:00.000Z"),
        es_doc("Bash", "bundle exec jekyll build --trace"),
        es_doc("Bash", f"cd /private/tmp/claude-501/s && bundle exec jekyll serve {ANT_KEY}"),
        es_doc("Bash", raw='{"command":"bash -c \'cd /private/tmp/x/theme\u2026[2207 chars]","timeout":1}'),
        es_doc("Edit"), es_doc("Edit"), es_doc("mcp_tool"),
    ]
    aggs = {"all": {"doc_count": 5000, "newest": {"value": 1.0 if newest else None, "value_as_string": newest},
                    "api_errors": {"doc_count": api_errors}}}
    return {("POST", "/logs-fleet.claude-*/_search"):
            lambda _b: (200, {"hits": {"total": {"value": total}, "hits": hits}, "aggregations": aggs})}


def contract_for(url: str) -> dict:
    return {"logs": {"elasticsearch": url, "datasets": {"claude": "fleet.claude"}}}


def cfg_for(url: str) -> dict:
    return {"qdrant": url, "embedder": url, "model": "nomic-embed-text", "min_score": 0.66, "limit": 40}


def build(lake_dir, url, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("scrubber", scrubber())
    kw.setdefault("contract", contract_for(url))
    kw.setdefault("index_cfg", cfg_for(url))
    kw.setdefault("registry_path", "/nonexistent/projects.yml")
    return fc.build(kw.pop("nwo", NWO), kw.pop("name", NAME), lake_dir=lake_dir, **kw)


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = fc.main(argv)
        except SystemExit as exc:   # argparse's own usage errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #
def test_the_document_keeps_its_contract():
    with _env(), _tmp() as tmp, Stub({**index_routes(), **es_routes()}) as stub:
        doc = build(rich_lake(tmp), stub.url, queries=["jekyll build"])
    assert list(doc) == ["schema", "generated_at", "nwo", "name", "window_days", "queries", "sections"], list(doc)
    assert doc["schema"] == "fleet-context/v1"
    assert doc["generated_at"] == "2026-10-31T12:00:00Z"
    assert (doc["nwo"], doc["name"], doc["window_days"], doc["queries"]) == (NWO, NAME, 30, ["jekyll build"])
    assert list(doc["sections"]) == list(fc.SECTIONS), list(doc["sections"])
    for key, sec in doc["sections"].items():
        assert list(sec) == ["status", "source", "as_of", "age_hours", "note", "elapsed_ms", "truncated", "rows"], \
            (key, list(sec))
        assert sec["status"] in fc.STATUSES and sec["source"] == fc.SOURCES[key], (key, sec["status"])
        assert isinstance(sec["elapsed_ms"], int) and isinstance(sec["truncated"], int), key
        assert isinstance(sec["rows"], list) and isinstance(sec["note"], str), key
        assert sec["status"] == "ok", (key, sec["status"], sec["note"])
    json.dumps(doc)


def test_sections_can_be_picked_and_keep_canonical_order():
    with _env(), _tmp() as tmp, Stub(es_routes()) as stub:
        doc = build(rich_lake(tmp), stub.url, sections=["telemetry_errors", "lake_issues"])
    assert list(doc["sections"]) == ["lake_issues", "telemetry_errors"]


# --------------------------------------------------------------------------- #
# lake sections
# --------------------------------------------------------------------------- #
def test_lake_issues_are_closed_only_newest_first_capped_and_scout_flagged():
    with _env(), _tmp() as tmp:
        sec = build(rich_lake(tmp), closed_port_url(), sections=["lake_issues"])["sections"]["lake_issues"]
    rows = sec["rows"]
    assert len(rows) == fc.CAP_ISSUES and sec["truncated"] == 30 - fc.CAP_ISSUES, (len(rows), sec["truncated"])
    numbers = [r["number"] for r in rows]
    assert numbers == list(range(100, 125)), numbers   # newest closed first
    assert not {1, 2, 3} & set(numbers), "open, out-of-window and other-repo issues stay out"
    assert rows[0]["scout"] is True and rows[0]["labels"] == ["ai-scout", "bug"]
    assert all(r["scout"] is False for r in rows[1:])
    assert {r["kind"] for r in rows} == {"issue", "pr"} and rows[1]["kind"] == "pr"
    assert set(rows[0]) == {"number", "kind", "title", "labels", "closed_at", "scout"}
    assert sec["as_of"] == ago(hours=2) and sec["age_hours"] == 2.0
    assert "the open ones are in the brief" in sec["note"]


def test_titles_are_untrusted_text_stripped_and_clipped():
    with _env(), _tmp() as tmp:
        rows = build(rich_lake(tmp), closed_port_url(), sections=["lake_issues"])["sections"]["lake_issues"]["rows"]
    title = rows[1]["title"]
    assert len(title) <= fc.TITLE_CHARS, len(title)
    assert not any(c in title for c in "\x1b\x00\u202e"), repr(title)
    assert FAKE_HOME not in title and GH_TOKEN not in title and "~/repo" in title, title


def test_a_token_cut_by_a_clip_is_masked_before_the_clip():
    # 130 characters, then a token: the 140-character clip leaves ten of its
    # characters, too few for its own pattern once it has been cut.
    title = fc.clean_line("x" * 125 + " " + GH_TOKEN, fc.TITLE_CHARS)
    assert GH_TOKEN[:10] not in title and len(title) <= fc.TITLE_CHARS, title
    snippet = fc.snippet_of("y" * 590 + f"\nkey = '{ANT_KEY}'")
    assert ANT_KEY[:14] not in snippet, snippet
    assert GH_TOKEN[:8] not in fc.command_head(f"curl -H 'Authorization: token {GH_TOKEN}' https://x")


def test_lake_ci_streak_counts_verdicts_and_names_the_failing_step():
    with _env(), _tmp() as tmp:
        sec = build(rich_lake(tmp), closed_port_url(), sections=["lake_ci"])["sections"]["lake_ci"]
    rows = {r["path"]: r for r in sec["rows"]}
    order = [r["path"] for r in sec["rows"]]
    assert order[0] == ".github/workflows/ci.yml", order   # failing first
    ci = rows[".github/workflows/ci.yml"]
    # failure, failure, (skipped: no verdict), failure, success -> a streak of three
    assert (ci["runs"], ci["failures"], ci["fail_streak"], ci["last_conclusion"]) == (5, 3, 3, "failure"), ci
    assert ci["workflow"] == "CI" and ci["last_at"] == ago(hours=1)
    assert ci["failing_steps"] == ["build / Run tests", "deploy"], ci["failing_steps"]
    pages = rows[".github/workflows/pages.yml"]
    assert (pages["failures"], pages["fail_streak"], pages["last_conclusion"]) == (1, 0, "success"), pages
    lint = rows[".github/workflows/lint.yml"]
    # PR runs (any branch), other branches and the out-of-window run are not the tracked branch's health
    assert (lint["runs"], lint["failures"]) == (2, 0), lint
    assert order.index(".github/workflows/pages.yml") < order.index(".github/workflows/lint.yml")
    assert "runs on main" in sec["note"] and "pull-request runs excluded" in sec["note"]


def test_lake_ci_caps_workflows_and_reads_the_registry_branch():
    with _env(), _tmp() as tmp:
        lake = make_lake(tmp)
        _insert(lake, "runs", [_run(f".github/workflows/w{i:02d}.yml", "success", 1, branch="dev")
                               for i in range(20)] + [_run(".github/workflows/main-only.yml", "failure", 1)])
        registry = tmp / "projects.yml"
        registry.write_text(f"- name: {NAME}\n  repo_url: https://github.com/{NWO}\n  branch: dev\n")
        sec = build(lake, closed_port_url(), sections=["lake_ci"], registry_path=registry)["sections"]["lake_ci"]
    assert len(sec["rows"]) == fc.CAP_WORKFLOWS and sec["truncated"] == 20 - fc.CAP_WORKFLOWS, sec["truncated"]
    assert all(r["path"] != ".github/workflows/main-only.yml" for r in sec["rows"]), "main is not the tracked branch"
    assert "runs on dev" in sec["note"]


def test_lake_agents_carries_aggregates_and_heads_never_the_session():
    with _env(), _tmp() as tmp:
        doc = build(rich_lake(tmp), closed_port_url(), sections=["lake_agents"])
    sec = doc["sections"]["lake_agents"]
    kinds = [r["kind"] for r in sec["rows"]]
    assert kinds[:2] == ["ci_agent_runs", "local_sessions"], kinds
    ci = sec["rows"][0]
    assert (ci["count"], ci["errors"], ci["permission_denials"], ci["turns"]) == (2, 1, 2, 15), ci
    assert ci["cost_usd"] == 0.75 and ci["models"] == {"claude-opus-5-5": 1, "claude-sonnet-5-5": 1}, ci
    assert ci["last_at"] == ago(hours=1) and ci["as_of"] == ago(hours=2)
    local = sec["rows"][1]
    assert (local["count"], local["tool_calls"], local["tool_errors"]) == (2, 20, 4), local
    heads = {r["head"]: r["count"] for r in sec["rows"] if r["kind"] == "failing_command"}
    # `set -euo pipefail` alone on the first line: the next line is the command
    assert heads == {"bundle exec jekyll": 3, "make test": 2, "gh api user": 1}, heads
    newest = next(r for r in sec["rows"] if r.get("head") == "bundle exec jekyll")
    assert newest["last_at"] == ago(hours=2), newest
    assert "API-equivalent (estimate)" in sec["note"]
    text = json.dumps(doc)
    for s in SENTINELS + (GH_TOKEN, FAKE_HOME, ".jsonl"):
        assert s not in text, f"{s} leaked into the pack"


def test_failing_commands_are_capped_by_head():
    with _env(), _tmp() as tmp:
        lake = make_lake(tmp)
        _insert(lake, "sessions", [_session("s1")])
        _insert(lake, "session_tools", [_tool("s1", i, f"tool{i:02d} --flag") for i in range(15)])
        sec = build(lake, closed_port_url(), sections=["lake_agents"])["sections"]["lake_agents"]
    commands = [r for r in sec["rows"] if r["kind"] == "failing_command"]
    assert len(commands) == fc.CAP_COMMANDS and sec["truncated"] == 15 - fc.CAP_COMMANDS, (len(commands), sec)


# --------------------------------------------------------------------------- #
# command heads + redaction
# --------------------------------------------------------------------------- #
def test_command_head_examples():
    cases = {
        "cd /Users/x/repo && bundle exec jekyll build --trace": "bundle exec jekyll",
        "FOO=1 BAR=2 python3 tools/x.py --flag": "python3 x.py --flag",
        "export X=1 && npm ci": "npm ci",
        "env -u PYTHONPATH python3 -m pytest -q": "python3 -m pytest",
        "set -e; make test": "make test",
        "set -euo pipefail\nmake test": "make test",   # a first line with no command reads on
        "cd /x\n\nnpm ci && npm test": "npm ci",
        "cd /x && python3 - <<'PY'\nimport os\nPY": "python3 -",   # a heredoc body is never a command
        "cd /x <<'EOF'\nrm -rf /\nEOF": "cd x",
        "cat file.txt | grep -n foo": "cat file.txt",
        "git status --short || true": "git status --short",
        "python3 - <<'PY'\nprint(1)\nPY": "python3 -",
        "cat >> tests/aieo/test_x.py <<'EOF'": "cat",
        'grep -rn "a/b c" src 2>/dev/null': "grep -rn b c",
        "bash -c 'cd /x/y && make -j4 all'": "make -j4 all",
        "bash -c 'S=/private/tmp/x/scratchpad; cd $S\u2026[597 chars]": "cd",
        "rm -f scratchp\u2026[878 chars]": "rm -f",   # the word the clip cut is not a word
        "DJANGO_SETTINGS_MODUL\u2026[300 chars]": "(clipped)",
        "for f in *.md; do wc -l \"$f\"; done": "wc -l $f",
        "if grep -q foo bar.txt; then echo y; fi": "grep -q foo",
        "(which ruff || pip install ruff)": "which ruff",
        "cd /tmp/x": "cd x",
        "bash <<'EOF'\ncd /x/y\nS=/private/tmp/z\npython3 - <<'PY'\nprint(1)\nPY\nEOF": "python3 -",
        'export PATH="/private/tmp/a/stubbin:$PATH"; cd \u2026[864 chars]': "export",
        'H=/private/tmp/x && E="-c user.email=1056\u2026[2742 chars]': "(clipped)",
        "": "",
    }
    for command, want in cases.items():
        got = fc.command_head(command)
        assert got == want, f"{command!r}: {got!r} != {want!r}"
    assert len(fc.command_head("x" * 200 + " a b")) == fc.HEAD_CHARS


def test_command_of_reads_dicts_json_and_clipped_json():
    assert fc.command_of({"command": "make"}) == "make"
    assert fc.command_of(json.dumps({"command": "make test"})) == "make test"
    assert fc.command_of('{"command":"cd /x && make \\"all\\"\u2026[99 chars]","timeout":1') \
        == 'cd /x && make "all"\u2026[99 chars]'
    assert fc.command_of('{"command":"half an escape \\') == "half an escape "
    assert fc.command_of("not json") == ""


def test_scrubber_masks_this_machine_and_credentials():
    s = scrubber()
    text = (f"cd {FAKE_HOME}/repo; ls /Users/bob/x; ssh {FAKE_HOST}; ping build-host-7 "
            f"/private/tmp/claude-501/sess/scratchpad/a.log /tmp/x.txt /var/folders/ab/T/y "
            f"{GH_TOKEN} gho_{'z' * 20} {ANT_KEY} github_pat_{'Q' * 30} Authorization: Bearer abc.def.ghijklmnop "
            f"GH_TOKEN=hunter2hunter2 -----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY----- "
            f"bell\x07 nul\x00 rtl\u202e git -c user.email=someone@example.com commit")
    out = s.text(text)
    for raw in (FAKE_HOME, "/Users/bob", FAKE_HOST, "build-host-7", "/private/tmp", "/tmp/x", "/var/folders",
                GH_TOKEN, ANT_KEY, "gho_zzzz", "github_pat_QQ", "abc.def.ghijklmnop", "hunter2", "MIIE",
                "\x07", "\x00", "\u202e", "someone@example.com"):
        assert raw not in out, f"{raw!r} survived: {out!r}"
    for mask in ("~/repo", "<host>", "<tmp>", "[REDACTED", "user.email=<email>"):
        assert mask in out, (mask, out)
    # a short host name is an ordinary word: the scout adapter's own floor
    assert fc.Scrubber(home="/h", hosts=["mac"], paths=[]).text("a mac mini") == "a mac mini"
    # the real HOME is masked by default
    home = os.path.expanduser("~")
    if len(home) > 1:
        assert home not in fc.Scrubber().text(f"x {home}/y")


def test_redaction_covers_every_plane_end_to_end():
    secret_chunk = f"ROOT = '{FAKE_HOME}/bamr87'  # on {FAKE_HOST}\nKEY = '{ANT_KEY}'\nTMP = '/var/folders/q/T/z'"
    routes = {**index_routes(), **es_routes()}
    routes[("POST", "/collections/ws-test/points/search")] = \
        lambda _b: (200, {"result": [_hit("tools/dash", 0.9, secret_chunk)]})
    with _env(), _tmp() as tmp, Stub(routes) as stub:
        doc = build(rich_lake(tmp), stub.url, queries=[f"where is {FAKE_HOME}"])
    text = json.dumps(doc, ensure_ascii=False)
    for raw in (FAKE_HOME, FAKE_HOST, ANT_KEY, GH_TOKEN, "/private/tmp", "/var/folders", "someone@example.com"):
        assert raw not in text, f"{raw!r} leaked"
    snippet = doc["sections"]["index_code"]["rows"][0]["snippet"]
    assert "~/bamr87" in snippet and "<host>" in snippet and "sk-ant-[REDACTED]" in snippet, snippet


# --------------------------------------------------------------------------- #
# freshness
# --------------------------------------------------------------------------- #
def test_an_old_sync_is_stale_with_its_refresh_command_and_keeps_its_rows():
    with _env(), _tmp() as tmp:
        doc = build(rich_lake(tmp, sync_age_h=100, sessions_h=100), closed_port_url(),
                    sections=["lake_issues", "lake_ci", "lake_agents"])
    for key in ("lake_issues", "lake_ci", "lake_agents"):
        sec = doc["sections"][key]
        assert sec["status"] == "stale" and sec["rows"], (key, sec["status"])
        assert sec["age_hours"] >= 100 and "100 h ago" in sec["note"], (key, sec["note"])
    assert "tools/dash lake sync" in doc["sections"]["lake_issues"]["note"]
    assert "tools/dash lake sessions" in doc["sections"]["lake_agents"]["note"]


def test_a_fresh_ci_sync_does_not_vouch_for_stale_sessions():
    with _env(), _tmp() as tmp:
        sec = build(rich_lake(tmp, sync_age_h=2, sessions_h=100), closed_port_url(),
                    sections=["lake_agents"])["sections"]["lake_agents"]
    assert sec["status"] == "stale" and "tools/dash lake sessions" in sec["note"], sec
    assert "lake sync" not in sec["note"], sec["note"]
    assert sec["as_of"] == ago(hours=100), "the older stamp speaks for the section"
    assert {r["kind"]: r.get("as_of") for r in sec["rows"][:2]} == \
        {"ci_agent_runs": ago(hours=2), "local_sessions": ago(hours=100)}


def test_a_lake_never_synced_is_stale_not_empty():
    with _env(), _tmp() as tmp:
        sec = build(make_lake(tmp, sync_age_h=None), closed_port_url(),
                    sections=["lake_issues"])["sections"]["lake_issues"]
    assert sec["status"] == "stale" and sec["as_of"] is None and "never been refreshed" in sec["note"], sec


# --------------------------------------------------------------------------- #
# unavailable, deadline, usage
# --------------------------------------------------------------------------- #
def test_a_missing_lake_is_unavailable_and_the_document_still_prints():
    with _env(QDRANT_URL=closed_port_url(), OLLAMA_URL=closed_port_url(), ES_URL=closed_port_url()), _tmp() as tmp:
        code, out, err = run_main(["--nwo", NWO, "--name", NAME, "--lake-dir", str(tmp / "nope"),
                                   "--query", "x", "--json"])
    assert code == 0, (code, err)
    assert err == "", "--json keeps stderr quiet"
    doc = json.loads(out)
    for key in ("lake_issues", "lake_ci", "lake_agents"):
        sec = doc["sections"][key]
        assert sec["status"] == "unavailable" and "no lake at" in sec["note"], sec
        assert "tools/dash lake sync" in sec["note"]
    assert str(tmp) not in out or not str(tmp).startswith(("/tmp", "/private", "/var")), "temp paths are masked"


def test_the_cli_reaches_the_planes_through_the_probe_env_and_summarises():
    with Stub({**index_routes(), **es_routes()}) as stub, \
            _env(QDRANT_URL=stub.url, OLLAMA_URL=stub.url, ES_URL=stub.url), _tmp() as tmp:
        code, out, err = run_main(["--nwo", NWO, "--name", NAME, "--lake-dir", str(rich_lake(tmp)),
                                   "--query", "jekyll build", "--sections", "index_code,telemetry_errors"])
    assert code == 0, err
    doc = json.loads(out)
    assert {k: v["status"] for k, v in doc["sections"].items()} == {"index_code": "ok", "telemetry_errors": "ok"}
    assert "index_code" in err and "telemetry_errors" in err and "lake_issues" not in err, err


def test_planes_that_refuse_are_unavailable_with_their_remedy():
    down = closed_port_url()
    with _env(), _tmp() as tmp:
        doc = build(rich_lake(tmp), down, queries=["x"])
    for key in ("index_code", "telemetry_errors"):
        sec = doc["sections"][key]
        assert sec["status"] == "unavailable" and sec["rows"] == [], (key, sec)
        assert "refused the connection" in sec["note"] and "tools/dash observe up" in sec["note"], sec["note"]
    assert doc["sections"]["lake_issues"]["status"] == "ok", "a down plane costs only its own section"


def test_a_missing_table_costs_only_that_section():
    with _env(), _tmp() as tmp:
        doc = build(make_lake(tmp, schema=False), closed_port_url(), sections=["lake_issues", "lake_agents"])
    assert doc["sections"]["lake_issues"]["status"] == "unavailable"
    assert "no issues table" in doc["sections"]["lake_issues"]["note"]
    assert "tools/dash lake sync" in doc["sections"]["lake_issues"]["note"]
    assert doc["sections"]["lake_agents"]["status"] == "unavailable"


def test_the_overall_deadline_bounds_the_whole_pass():
    with _env(), _tmp() as tmp, Stub({**index_routes(), **es_routes()}, delay=3.0) as stub:
        started = time.monotonic()
        doc = build(rich_lake(tmp), stub.url, queries=["x"], deadline_s=1.0)
        elapsed = time.monotonic() - started
    assert elapsed < 2.5, f"took {elapsed:.2f} s against a 1 s deadline"
    tele, index = doc["sections"]["telemetry_errors"], doc["sections"]["index_code"]
    assert tele["status"] == "unavailable" and "did not answer within" in tele["note"], tele["note"]
    assert index["status"] == "unavailable" and "--deadline-s" in index["note"], index["note"]
    assert doc["sections"]["lake_issues"]["status"] == "ok"


def test_the_deadline_reaches_inside_a_lake_query():
    with _tmp() as tmp:
        lake = rich_lake(tmp)
        conn, _tables = fc._open_lake(lake, fc.Deadline(0.05))
        time.sleep(0.1)
        try:
            conn.execute("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 10000000) "
                         "SELECT COUNT(*) FROM n").fetchone()
            raise AssertionError("the query ran past the deadline")
        except sqlite3.OperationalError as exc:
            assert "interrupt" in str(exc).lower(), exc
        finally:
            conn.close()


def test_usage_errors_exit_2():
    base = ["--nwo", NWO, "--name", NAME, "--lake-dir", "/nonexistent"]
    bad = [
        ["--nwo", "not-an-nwo", "--name", NAME],
        ["--nwo", "a/b/c", "--name", NAME],
        ["--nwo", NWO, "--name", "../x"],
        ["--nwo", NWO, "--name", "a/b"],
        base + ["--query", "a", "--query", "b", "--query", "c", "--query", "d"],
        base + ["--query", "x" * 301],
        base + ["--query", "bell\x07"],
        base + ["--query", "two\nlines"],
        base + ["--query", "  "],
        base + ["--sections", "lake_issues,nonsense"],
        base + ["--days", "0"],
        base + ["--deadline-s", "0"],
        base + ["--days", "many"],
        ["--name", NAME],
    ]
    with _env():
        for argv in bad:
            code, out, _err = run_main(argv)
            assert code == 2, (argv, code)
            assert out == "", (argv, "no document for a bad request")


def test_dash_gen_registers_the_subcommand():
    import dash_gen
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dash_gen.main(["context", "--nwo", "nope", "--name", NAME])
    assert code == 2 and "--nwo must be OWNER/REPO" in err.getvalue(), (code, err.getvalue())


# --------------------------------------------------------------------------- #
# index + telemetry
# --------------------------------------------------------------------------- #
def test_index_code_keeps_hub_and_target_code_and_withholds_siblings():
    with _env(), _tmp() as tmp, Stub(index_routes()) as stub:
        sec = build(tmp / "no-lake", stub.url, queries=["jekyll build", "shell"],
                    sections=["index_code"])["sections"]["index_code"]
    rows = sec["rows"]
    first = [r for r in rows if r["query"] == "jekyll build"]
    assert len(first) == fc.CAP_HITS and sec["truncated"] == 2, (len(first), sec["truncated"])
    assert [r["score"] for r in first] == [0.91, 0.88, 0.87, 0.8], [r["score"] for r in first]
    by_path = {r["path"]: r for r in rows}
    hub = by_path["tools/dash"]
    assert hub["project"] == "_hub" and hub["snippet"], hub
    assert hub["snippet"].count("\n") + 1 <= fc.SNIPPET_LINES and len(hub["snippet"]) <= fc.SNIPPET_CHARS
    assert hub["start_line"] == 10 and hub["end_line"] == 52 and "withheld" not in hub
    assert by_path[f"projects/{NAME}/site/_config.yml"]["snippet"] == "code"
    sibling = by_path["projects/law-ai/secret.py"]
    assert sibling["snippet"] is None and sibling["withheld"] == "sibling repo, visibility unknown", sibling
    assert "projects/law-ai/low.py" not in by_path, "below the floor stays out"
    assert by_path["projects/bashos/x.sh"]["snippet"] is None
    assert "PRIVATE SIBLING CODE" not in json.dumps(sec)
    assert "ws-test" in sec["note"] and "zer0-cms has ~302 chunks" in sec["note"], sec["note"]
    assert sec["as_of"] is None and sec["status"] == "ok"
    embeds = [r for r in stub.requests if r[1] == "/api/embed"]
    assert len(embeds) == 1 and embeds[0][2]["input"] == ["jekyll build", "shell"], "one embedding call"
    count = next(r for r in stub.requests if r[1].endswith("/points/count"))[2]
    assert count["filter"]["must"][1] == {"key": "pathSegments.1", "match": {"value": NAME}}, count


def test_index_code_for_the_hub_counts_the_hub_and_keeps_its_code():
    with _env(), _tmp() as tmp, Stub(index_routes()) as stub:
        sec = build(tmp / "no-lake", stub.url, nwo="bamr87/bamr87", name="bamr87", queries=["x"],
                    sections=["index_code"], fleet_path=fc.FLEET_DEFAULT)["sections"]["index_code"]
    assert next(r for r in sec["rows"] if r["project"] == "_hub")["snippet"]
    assert all(r["snippet"] is None for r in sec["rows"] if r["project"] not in ("_hub",)), sec["rows"]
    count = next(r for r in stub.requests if r[1].endswith("/points/count"))[2]
    assert "must_not" in count["filter"] and "the hub has" in sec["note"], (count, sec["note"])


def test_index_code_without_queries_is_empty_and_asks_nothing():
    with _env(), _tmp() as tmp, Stub(index_routes()) as stub:
        sec = build(tmp / "no-lake", stub.url, sections=["index_code"])["sections"]["index_code"]
    assert sec["status"] == "empty" and "no --query" in sec["note"] and stub.requests == [], sec


def test_index_code_picks_the_fullest_workspace_collection():
    routes = index_routes(collections=("other", "ws-a", "ws-test"))
    with _env(), _tmp() as tmp, Stub(routes) as stub:
        sec = build(tmp / "no-lake", stub.url, queries=["x"], sections=["index_code"])["sections"]["index_code"]
    assert "collection ws-test" in sec["note"], sec["note"]   # ws-test (70 points) over ws-a (40)


def test_telemetry_errors_aggregate_by_tool_and_head_in_one_request():
    with _env(), _tmp() as tmp, Stub(es_routes()) as stub:
        sec = build(tmp / "no-lake", stub.url, sections=["telemetry_errors"])["sections"]["telemetry_errors"]
    assert len(stub.requests) == 1, stub.requests
    method, path, body = stub.requests[0]
    assert (method, path) == ("POST", "/logs-fleet.claude-*/_search")
    filters = body["query"]["bool"]["filter"]
    assert {"term": {"fleet.repo": {"value": NWO, "case_insensitive": True}}} in filters
    assert {"term": {"claude.success": "false"}} in filters and body["size"] == fc.TELEMETRY_SAMPLE
    rows = sec["rows"]
    tools = {(r["tool"], r["head"]): r["count"] for r in rows if r["kind"] == "tool_error"}
    assert tools == {("Bash", "bundle exec jekyll"): 3, ("Bash", "cd"): 1, ("Edit", None): 2,
                     ("mcp_tool", None): 1}, tools
    assert rows[0]["last_at"] == "2026-10-31T10:05:00Z", rows[0]
    assert rows[-1] == {"kind": "api_errors", "count": 4}
    assert sec["as_of"] == "2026-10-31T11:30:00Z" and sec["status"] == "ok"
    assert "newest 7 of 900" in sec["note"], sec["note"]


def test_telemetry_caps_groups_and_says_when_the_stream_is_empty():
    many = [es_doc("Bash", f"tool{i:02d} run") for i in range(14)]
    with _env(), _tmp() as tmp, Stub(es_routes(hits=many, api_errors=0, total=14)) as stub:
        sec = build(tmp / "no-lake", stub.url, sections=["telemetry_errors"])["sections"]["telemetry_errors"]
    assert len(sec["rows"]) == fc.CAP_TELEMETRY and sec["truncated"] == 4, (len(sec["rows"]), sec["truncated"])
    with _env(), _tmp() as tmp, Stub(es_routes(hits=[], newest=None, api_errors=0, total=0)) as stub:
        sec = build(tmp / "no-lake", stub.url, sections=["telemetry_errors"])["sections"]["telemetry_errors"]
    assert sec["status"] == "empty" and "observe claude enable" in sec["note"], sec


# --------------------------------------------------------------------------- #
# read-only
# --------------------------------------------------------------------------- #
def test_the_lake_is_never_written():
    with _env(), _tmp() as tmp:
        lake = rich_lake(tmp)
        db = lake / fl.DB_NAME
        before = (db.read_bytes(), db.stat().st_mtime_ns)
        db.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)                     # 0444
        lake.chmod(0o555)
        saved = fl.connect
        fl.connect = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fleet_lake.connect migrates"))
        try:
            doc = build(lake, closed_port_url(), sections=["lake_issues", "lake_ci", "lake_agents"])
            conn = fc.open_ro(db)
            try:
                conn.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
                raise AssertionError("the read-only connection accepted a write")
            except sqlite3.OperationalError as exc:
                assert "readonly" in str(exc).lower() or "read-only" in str(exc).lower(), exc
            finally:
                conn.close()
        finally:
            fl.connect = saved
            lake.chmod(0o755)
            db.chmod(0o644)
        assert all(doc["sections"][k]["status"] == "ok" for k in ("lake_issues", "lake_ci", "lake_agents")), \
            {k: doc["sections"][k]["note"] for k in doc["sections"]}
        assert (db.read_bytes(), db.stat().st_mtime_ns) == before, "the lake file changed"
        assert sorted(p.name for p in lake.iterdir()) == [fl.DB_NAME], "no journal or sidecar was left"


def test_only_read_routes_reach_a_plane():
    with Stub({}) as stub:
        deadline = fc.Deadline(5)
        for plane, method, path in (("qdrant", "PUT", "/collections/x/points"),
                                    ("qdrant", "DELETE", "/collections/x"),
                                    ("qdrant", "POST", "/collections/x/points/delete"),
                                    ("elasticsearch", "POST", "/_bulk"),
                                    ("elasticsearch", "POST", "/logs-fleet.claude-default/_delete_by_query"),
                                    ("elasticsearch", "GET", "/_cat/indices"),
                                    ("ollama", "POST", "/api/pull"),
                                    ("github", "GET", "/repos/bamr87/bamr87")):
            try:
                fc.http_json(plane, stub.url, method, path, {}, deadline=deadline)
                raise AssertionError(f"{plane} {method} {path} was allowed")
            except fc.RouteRefused:
                pass
        assert stub.requests == [], "a refused route never opens a socket"


def test_a_proxy_in_the_environment_is_not_used():
    with _env(HTTP_PROXY=closed_port_url(), http_proxy=closed_port_url()), Stub(es_routes()) as stub:
        doc = fc.http_json("elasticsearch", stub.url, "POST", "/logs-fleet.claude-*/_search", {},
                           deadline=fc.Deadline(5))
    assert "hits" in doc and len(stub.requests) == 1


def test_shared_constants_match_their_owners():
    import fleet_triage
    import repo_scout
    assert fc.SCOUT_LABEL_DEFAULT == repo_scout.DEFAULTS["label"]
    assert set(fc.PR_EVENTS) == set(fleet_triage.PR_EVENTS)
    assert set(fc.ERROR_CONCLUSIONS) == set(fl.ERROR_CONCLUSIONS)


def main() -> int:
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as exc:   # an error in a test is a failure, reported with its type
            failures += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — fleet_context fixture tests ({len(tests) - failures}/{len(tests)})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

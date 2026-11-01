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
    mtime unchanged, and on a WRITABLE copy each of the connection's two
    read-only layers (`query_only`, `mode=ro`) refuses a write on its own; the
    HTTP side refuses any route that is not a read, and any plane URL that is
    not scheme://host:port, before a socket opens.

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
import platform
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
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
def make_lake(root: Path, *, sync_age_h: float | None = 2, schema: bool = True,
              repo_synced_h: float | None | bool = True) -> Path:
    """A lake whose last `lake sync` finished `sync_age_h` ago. Like a real
    sync it stamps the target's `repos` row with the pass's START (0.1 h
    earlier); `repo_synced_h` overrides that stamp, None leaves no row."""
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
    if repo_synced_h is True:
        repo_synced_h = None if sync_age_h is None else sync_age_h + 0.1
    if schema and repo_synced_h is not None:
        conn.execute("INSERT INTO repos (nwo, name, default_branch, synced_at) VALUES (?, ?, ?, ?)",
                     (NWO, NAME, "main", ago(hours=repo_synced_h)))
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


def rich_lake(root: Path, *, sync_age_h: float = 2, sessions_h: float = 1, repo_synced_h=True) -> Path:
    lake = make_lake(root, sync_age_h=sync_age_h, repo_synced_h=repo_synced_h)
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

    def __init__(self, routes: dict, delay: float = 0.0, trickle: float = 0.0, trickle_body: bool = False):
        """`trickle` sends the answer one byte at a time, that many seconds
        apart — from the status line on, or (`trickle_body`) after headers
        sent at once."""
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
                if trickle:
                    head = (f"HTTP/1.0 {code} OK\r\nContent-Type: application/json\r\n"
                            f"Content-Length: {len(data)}\r\n\r\n").encode()
                    try:
                        if trickle_body:
                            self.wfile.write(head)
                        for b in (data if trickle_body else head + data):
                            self.wfile.write(bytes([b]))
                            time.sleep(trickle)
                    except OSError:   # the client gave up: the behaviour under test
                        stub.gave_up = True
                    return
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
    kw.setdefault("home", FAKE_HOME)
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
    assert sec["as_of"] == ago(hours=2.1) and sec["age_hours"] == 2.1, "the repo's own stamp: the sync's start"
    assert "the open ones are in the brief" in sec["note"]


def test_titles_are_untrusted_text_stripped_and_clipped():
    with _env(), _tmp() as tmp:
        rows = build(rich_lake(tmp), closed_port_url(), sections=["lake_issues"])["sections"]["lake_issues"]["rows"]
    title = rows[1]["title"]
    assert len(title) <= fc.TITLE_CHARS, len(title)
    assert not any(c in title for c in "\x1b\x00\u202e"), repr(title)
    assert FAKE_HOME not in title and GH_TOKEN not in title and "~/repo" in title, title


def test_line_and_paragraph_separators_are_stripped_and_refused_in_a_query():
    ls, ps = chr(0x2028), chr(0x2029)   # a line end to str.splitlines, not to CommonMark
    out = fc.clean_line(f"line{ls}## heading{ps}para", fc.TITLE_CHARS)
    assert ls not in out and ps not in out, repr(out)
    assert ls not in fc.snippet_of(f"a{ls}## b")
    with _env():
        code, out, _err = run_main(["--nwo", NWO, "--name", NAME, "--lake-dir", "/nonexistent",
                                    "--query", f"a{ls}b"])
    assert code == 2 and out == "", (code, out)
    src = Path(fc.__file__).read_text(encoding="utf-8")
    hidden = sorted({f"U+{ord(c):04X}" for c in src if unicodedata.category(c) in ("Cf", "Zl", "Zp")})
    assert not hidden, f"fleet_context.py carries invisible characters {hidden}: write them as escapes"


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
    assert ci["last_at"] == ago(hours=1) and ci["as_of"] == ago(hours=2.1)
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


def test_sessions_run_in_the_home_directory_are_nobodys_repo():
    # ai_activity.repo_for names a session in $HOME after its basename, the user
    # name, which is also the hub checkout's name: those sessions are not the hub's
    with _env(), _tmp() as tmp:
        lake = rich_lake(tmp)
        home = {**_session("h1", calls=99, errors=50), "cwd": FAKE_HOME}
        slash = {**_session("h2", calls=99, errors=50), "cwd": FAKE_HOME + "/"}
        _insert(lake, "sessions", [home, slash])
        _insert(lake, "session_tools", [_tool("h1", 1, "rm -rf junk"), _tool("h2", 1, "rm -rf junk")])
        sec = build(lake, closed_port_url(), sections=["lake_agents"])["sections"]["lake_agents"]
    local = next(r for r in sec["rows"] if r["kind"] == "local_sessions")
    assert (local["count"], local["tool_calls"], local["tool_errors"]) == (2, 20, 4), local
    assert not any(r.get("head") == "rm -rf" for r in sec["rows"]), sec["rows"]


def test_a_locked_lake_says_retry_not_sync():
    with _env(), _tmp() as tmp:
        lake = rich_lake(tmp)
        holder = sqlite3.connect(lake / fl.DB_NAME)
        holder.execute("BEGIN EXCLUSIVE")
        try:
            started = time.monotonic()
            doc = build(lake, closed_port_url(), sections=["lake_issues", "lake_ci"], deadline_s=0.5)
            elapsed = time.monotonic() - started
        finally:
            holder.rollback()
            holder.close()
    assert elapsed < 2.0, elapsed
    for key in ("lake_issues", "lake_ci"):
        sec = doc["sections"][key]
        assert sec["status"] == "unavailable" and "locked" in sec["note"], (key, sec["note"])
        assert fc.REMEDY_LOCKED in sec["note"] and fc.REMEDY_LAKE not in sec["note"], (key, sec["note"])


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
        'grep -rn "a/b c" src 2>/dev/null': "grep -rn",   # a positional after a flag is a value
        "bash -c 'cd /x/y && make -j4 all'": "make -j4",
        "bash -c 'S=/private/tmp/x/scratchpad; cd $S\u2026[597 chars]": "cd",
        "rm -f scratchp\u2026[878 chars]": "rm -f",   # the word the clip cut is not a word
        "DJANGO_SETTINGS_MODUL\u2026[300 chars]": "(clipped)",
        "for f in *.md; do wc -l \"$f\"; done": "wc -l",
        "if grep -q foo bar.txt; then echo y; fi": "grep -q",
        "(which ruff || pip install ruff)": "which ruff",
        "cd /tmp/x": "cd x",
        "bash <<'EOF'\ncd /x/y\nS=/private/tmp/z\npython3 - <<'PY'\nprint(1)\nPY\nEOF": "python3 -",
        'export PATH="/private/tmp/a/stubbin:$PATH"; cd \u2026[864 chars]': "export",
        'H=/private/tmp/x && E="-c user.email=1056\u2026[2742 chars]': "(clipped)",
        "": "",
        # an option's value never stands in a head, attached or not (the
        # verifiers' probes): the option is kept and the head ends there
        "curl -u admin:hunter2pass https://example.invalid/x": "curl -u",
        "curl --user admin:Sup3rS3cret https://example.invalid/x": "curl --user",
        "curl --password=hunter2 https://example.invalid/x": "curl --password",
        "sshpass -p 'S3cretPass!' ssh host": "sshpass -p",
        "mysql -pMyDbPassw0rd -u root db": "mysql -p",
        "redis-cli -a myredispassword123 ping": "redis-cli -a",
        "curl -H 'X-Api-Key: 0123456789abcdef0123456789abcdef' https://x": "curl -H",
        "curl -H 'Authorization: Basic YWRtaW46aHVudGVyMg==' https://x": "curl -H",
        "curl --data-raw '{\"token\":\"abc\"}' https://x": "curl --data-raw",
        # positionals: lower-case subcommand words only, never an id or a password
        "echo npm_AbCdEf0123456789AbCdEf0123456789AbCd": "echo",
        # a data-only command's arguments are data: the head is the command word alone
        "echo hunter2 | docker login -u bamr87 --password-stdin": "echo",
        "printf 'hunter2hunter2' | gh auth login --with-token": "printf",
        "echo mysecretpassword > ~/.pgpass": "echo",
        "/bin/echo -n hunter2": "echo",
        "redis-cli auth myredispassword123": "redis-cli auth",
        "cat ~/.claude/projects/-Users-bamr87-bamr87/0b9a4a4e-1f0e-4a5e-9d55-1f2e3d4c5b6a.jsonl": "cat",
        "ls -la local_2bc336f8-1234-4abc-9def-0123456789ab": "ls -la",
        "git -c user.email=someone@example.com commit -m x": "git -c",
        "docker login -u bot --password-stdin": "docker login -u",
        "gh secret set FLEET_TOKEN --body x": "gh secret set",
        "python3 -c 'import os; print(os.environ)'": "python3 -c",
        "python3 test_fleet_context.py": "python3 test_fleet_context.py",
        "tok=$(grep '^DASH_CONSOLE_TOKEN=' .env | cut -d= -f2-)": "cut -d",   # a pattern is not a command
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


def test_every_name_of_this_machine_and_its_home_in_any_case_or_encoding_are_masked():
    real = fc.machine_names
    fc.machine_names = lambda: ("Fake-Bonjour-Name", "Fake-Bonjour-Name.local", "Fake\u2019s Computer Name")
    try:
        s = fc.Scrubber(home="/Users/alice", paths=["/srv/jev/work"])
    finally:
        fc.machine_names = real
    out = s.text("on Fake-Bonjour-Name.local and FAKE\u2019S COMPUTER NAME: /users/ALICE/a %2FUsers%2Falice%2Fb "
                 "\\/Users\\/alice\\/c %2FSRV%2Fjev%2Fwork%2Fd %2FUsers%2Fbob%2Fe \\/Users\\/bob\\/f GET /users/:id")
    for raw in ("Bonjour", "COMPUTER", "alice", "ALICE", "SRV", "bob"):
        assert raw not in out, (raw, out)
    assert out.count("<host>") == 2 and "~/a" in out and "~%2Fb" in out and "~\\/c" in out, out
    assert "<work>%2Fd" in out and "~%2Fe" in out and "~\\/f" in out and "GET /users/:id" in out, out
    names = fc.machine_names()
    assert platform.node() in names and socket.gethostname() in names, names
    if sys.platform == "darwin" and shutil.which("scutil"):
        bonjour = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
        if bonjour:
            assert bonjour in names and f"{bonjour}.local" in names, names


def test_token_masks_leave_english_alone_and_catch_header_and_url_shapes():
    for english in ("fix: token authentication for the console", "Rotate the token automatically every week",
                    "the bearer of bad news", "Authorization headers are documented"):
        assert fc.clean_line(english, fc.TITLE_CHARS) == english, fc.clean_line(english, fc.TITLE_CHARS)
    for text, value in (("token abc123def456ghi789", "abc123def456ghi789"),
                        ("Authorization: Basic YWRtaW46aHVudGVyMg==", "YWRtaW46aHVudGVyMg=="),
                        ("X-Api-Key: 0123456789abcdef0123", "0123456789abcdef0123"),
                        ('{"access_token": "abcdefgh12345678"}', "abcdefgh12345678"),
                        ("https://admin:hunter3hunter3@example.invalid/x", "hunter3hunter3"),
                        ("npm_AbCdEf0123456789AbCdEf0123456789AbCd", "AbCdEf0123456789"),
                        ("DB_PRIVATE_KEY=abcdefgh12345678", "abcdefgh12345678")):
        out = fc.mask_credentials(text)
        assert value not in out and "[REDACTED" in out, (text, out)


def test_file_urls_and_claudes_dashed_home_form_are_masked():
    sid = "0b9a4a4e-1f0e-4a5e-9d55-1f2e3d4c5b6a"
    text = (f"open file:///private/tmp/claude-501/-Users-alice-bamr87/{sid}/scratchpad/x "
            "file:///Users/bob/notes.md ls -Users-alice-bamr87/ and -Users-bob-proj cat file:///var/folders/q/T/z")
    out = scrubber().text(text)
    for raw in ("/private/tmp", "-Users-", "/Users/bob", "/var/folders", sid, "alice", "bob"):
        assert raw not in out, (raw, out)
    assert "file://<tmp>" in out and "file://~/notes.md" in out and "ls ~-bamr87/" in out, out
    assert fc.Scrubber(home="/home/runner", hosts=[], paths=[]).text("x -home-runner-proj") == "x ~-proj"
    assert fc.command_head("ls /Users/alice/.claude/projects/-Users-alice-bamr87/") == "ls", "a dashed dir is no flag"


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


def _words_of(o, *, data_keys: bool = False) -> set:
    """Every key (but a ci_agent_runs row's model names, which are data) and every row kind of a document."""
    if isinstance(o, list):
        return set().union(*(_words_of(x) for x in o))
    if not isinstance(o, dict):
        return set()
    words = set() if data_keys else set(o) | ({o["kind"]} if isinstance(o.get("kind"), str) else set())
    return words.union(*(_words_of(v, data_keys=k == "models") for k, v in o.items()))


def _shape(o):
    """A document with every string that is not one of its own words (DOC_WORDS) blanked."""
    if isinstance(o, dict):
        return {_shape(k): _shape(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_shape(x) for x in o]
    return ("<data>" if o not in fc.DOC_WORDS else o) if isinstance(o, str) else o


def test_a_host_named_like_a_word_of_the_document_keeps_it_whole():
    # Scrubber.obj masked the document's own keys and values as well as its data: a host called `stale`,
    # `rows`, `note`, `source`, `status`, `name` or `path` turned a status, a key or a field into `<host>`, and
    # the engine read every section as malformed, so mode require blocked an item whose planes all answered.
    routes = {**index_routes(), **es_routes()}
    routes[("POST", "/collections/ws-test/points/search")] = lambda _b: (200, {"result": [
        _hit("tools/dash", 0.91, "echo build"), _hit("projects/law-ai/secret.py", 0.87, "PRIVATE SIBLING CODE")]})
    with _env(), _tmp() as tmp, Stub(routes) as stub:
        doc = build(rich_lake(tmp), stub.url, queries=["jekyll build"], target_dir=str(tmp),
                    scrubber=fc.Scrubber(home=FAKE_HOME, hosts=[], paths=[]))
    words = _words_of(doc)
    assert words <= fc.DOC_WORDS, ("a field or row kind the planes write must be a DOC_WORDS word",
                                   sorted(words - fc.DOC_WORDS))
    assert {"issue", "ci_agent_runs", "local_sessions", "failing_command", "tool_error", "api_errors", "withheld",
            "failing_steps", "target_dir"} <= words, sorted(words)
    for host in sorted(w for w in fc.DOC_WORDS if len(w) > 3):
        scrubbed = fc.Scrubber(home=FAKE_HOME, hosts=[host], paths=[]).obj(doc)
        assert _shape(scrubbed) == _shape(doc), (host, "the planes rewrote the document's own words")
    tagged = {"title": "the stale cache", "note": "stale"}
    assert fc.Scrubber(home=FAKE_HOME, hosts=["stale"], paths=[]).obj(tagged) == \
        {"title": "the <host> cache", "note": "stale"}, "a word inside data is masked as ever"


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
        {"ci_agent_runs": ago(hours=2.1), "local_sessions": ago(hours=100)}


def test_a_lake_never_synced_is_stale_not_empty():
    with _env(), _tmp() as tmp:
        sec = build(make_lake(tmp, sync_age_h=None), closed_port_url(),
                    sections=["lake_issues"])["sections"]["lake_issues"]
    assert sec["status"] == "stale" and sec["as_of"] is None, sec
    assert f"the lake has never synced {NWO} — run `tools/dash lake sync --repo {NWO}`" in sec["note"], sec
    with _env(), _tmp() as tmp:   # a repos row from an interrupted pass, and no finished sync at all
        sec = build(make_lake(tmp, sync_age_h=None, repo_synced_h=1), closed_port_url(),
                    sections=["lake_issues"])["sections"]["lake_issues"]
    assert sec["status"] == "stale" and sec["as_of"] is None and "never been refreshed" in sec["note"], sec


def test_a_fresh_partial_sync_does_not_vouch_for_a_stale_repo():
    # the newest `lake sync` (2 h ago) was a `--repo OTHER` pass: this repo was
    # last reached twelve days ago, and its rows are that old
    with _env(), _tmp() as tmp:
        lake = rich_lake(tmp, sync_age_h=2, repo_synced_h=24 * 12)
        _insert(lake, "issues", [_issue(900, closed_h=24 * 11)])
        doc = build(lake, closed_port_url(), sections=["lake_issues", "lake_ci", "lake_agents"])
    for key in ("lake_issues", "lake_ci", "lake_agents"):
        sec = doc["sections"][key]
        assert sec["status"] == "stale" and sec["as_of"] == ago(hours=24 * 12), (key, sec["status"], sec["as_of"])
        assert f"tools/dash lake sync --repo {NWO}" in sec["note"], (key, sec["note"])
    assert doc["sections"]["lake_issues"]["age_hours"] == 288.0
    agents = {r["kind"]: r.get("as_of") for r in doc["sections"]["lake_agents"]["rows"][:2]}
    assert agents == {"ci_agent_runs": ago(hours=24 * 12), "local_sessions": ago(hours=1)}, agents


def test_a_registered_repo_the_lake_never_synced_is_stale_at_any_lake_age():
    with _env(), _tmp() as tmp:
        lake = make_lake(tmp, sync_age_h=2, repo_synced_h=None)
        _insert(lake, "repos", [{"nwo": "bamr87/law-ai", "name": "law-ai", "synced_at": ago(hours=2.1)}])
        doc = build(lake, closed_port_url(), sections=["lake_issues", "lake_ci", "lake_agents"])
    for key in ("lake_issues", "lake_ci"):
        sec = doc["sections"][key]
        assert sec["status"] == "stale" and sec["as_of"] is None and sec["rows"] == [], (key, sec)
        assert f"the lake has never synced {NWO}" in sec["note"], (key, sec["note"])
    assert doc["sections"]["lake_agents"]["status"] == "stale", doc["sections"]["lake_agents"]


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


def test_a_plane_that_trickles_is_cut_off_at_the_deadline():
    # One byte every 0.2 s: each recv returns within any per-recv timeout, so
    # only a wall-clock bound stops it. Headers trickled (the join bounds it)
    # and headers at once with the body trickled (the read loop bounds it).
    for trickle_body in (False, True):
        with _env(), _tmp() as tmp, Stub({**index_routes(), **es_routes()}, trickle=0.2,
                                         trickle_body=trickle_body) as stub:
            started = time.monotonic()
            doc = build(tmp / "no-lake", stub.url, queries=["x"], deadline_s=2.0,
                        sections=["telemetry_errors", "index_code"])
            elapsed = time.monotonic() - started
        assert elapsed < 3.0, f"took {elapsed:.2f} s against a 2 s deadline (trickle_body={trickle_body})"
        tele, index = doc["sections"]["telemetry_errors"], doc["sections"]["index_code"]
        assert tele["status"] == "unavailable" and "did not answer within" in tele["note"], tele["note"]
        assert index["status"] == "unavailable" and "--deadline-s" in index["note"], index["note"]


def test_a_plane_url_with_a_path_or_query_is_refused_before_a_socket_opens():
    with _env(), _tmp() as tmp, Stub({**index_routes(), **es_routes()}) as stub:
        es = stub.url + "/logs-fleet.claude-2026/_delete_by_query?conflicts=proceed&_="
        qd = stub.url + "/collections/ws-test/points/delete?wait=true&_="
        doc = build(tmp / "no-lake", stub.url, queries=["x"], sections=["telemetry_errors", "index_code"],
                    contract=contract_for(es), index_cfg=cfg_for(qd))
        for bad in (stub.url + "/x", stub.url + "?a=b", stub.url + "#f",
                    stub.url.replace("http://", "http://user:pw@")):
            try:
                fc.http_json("elasticsearch", bad, "POST", "/logs-fleet.claude-*/_search", {},
                             deadline=fc.Deadline(5))
                raise AssertionError(f"{bad} was used")
            except fc.Unavailable as exc:
                assert "pw" not in exc.note() and "only scheme://host:port" in exc.note(), exc.note()
        assert stub.requests == [], stub.requests
    for key in ("telemetry_errors", "index_code"):
        sec = doc["sections"][key]
        assert sec["status"] == "unavailable" and "carries a path" in sec["note"], (key, sec["note"])
    assert fc.plane_origin("qdrant", "http://127.0.0.1:6333/")[3] == "http://127.0.0.1:6333"


def test_untrusted_text_is_cut_before_the_masks_run():
    seen = []
    saved = fc.mask_credentials
    fc.mask_credentials = lambda text: seen.append(len(text)) or saved(text)
    try:
        huge = "fix the build " + "ab12 " * 800_000   # 4 MB: the masks would scan all of it
        assert fc.clean_line(huge, fc.TITLE_CHARS).startswith("fix the build ab12")
        assert fc.snippet_of(huge).startswith("fix the build")
        assert fc.command_head("make " + huge) == "make fix the"
        key = "-----BEGIN RSA PRIVATE KEY-----\n" + "K" * 10_000 + "\n-----END RSA PRIVATE KEY-----"
        out = fc.clean_line("x " + key, fc.TITLE_CHARS)   # the cut lands inside the block: masked to its end
    finally:
        fc.mask_credentials = saved
    assert max(seen) <= fc.HEAD_SCAN_CHARS, max(seen)
    assert "KKKK" not in out and "[REDACTED PRIVATE KEY]" in out, out


class _Ticking:
    """A clock that moves 0.3 s every time it is read: a Deadline(1) on it
    expires after a handful of rows, whatever the machine's speed."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.3
        return self.t


def test_the_deadline_reaches_the_python_work_on_each_row():
    with _tmp() as tmp:
        lake = rich_lake(tmp)
        conn, tables = fc._open_lake(lake, fc.Deadline(30))
        since = ago(days=30)
        try:
            calls = {
                "lake_issues": lambda d: fc.lake_issues(conn, tables, NWO, since, NOW, "ai-scout", d),
                "lake_ci": lambda d: fc.lake_ci(conn, tables, NWO, since, NOW, "main", d),
                "lake_agents": lambda d: fc.lake_agents(conn, tables, NWO, NAME, since, NOW, d),
                "failing_commands": lambda d: fc.failing_commands(conn, NAME, since, d),
            }
            for what, call in calls.items():
                try:
                    call(fc.Deadline(1.0, clock=_Ticking()))
                    raise AssertionError(f"{what} ran on past the deadline")
                except fc.Unavailable as exc:
                    assert "cut off" in exc.note() and "--deadline-s" in exc.note(), (what, exc.note())
                assert call(fc.Deadline(30)) is not None, what   # and an ample budget reads it all
        finally:
            conn.close()


def test_ci_agent_runs_models_are_capped():
    with _env(), _tmp() as tmp:
        lake = make_lake(tmp)
        _insert(lake, "agent_runs", [{"run_id": 7000 + i, "nwo": NWO, "model": f"model-{i:02d}",
                                      "num_turns": 1, "cost_usd": 0.01, "permission_denials": 0,
                                      "is_error": 0, "started_at": ago(hours=1)} for i in range(20)]
                + [{"run_id": 7100 + i, "nwo": NWO, "model": "claude-opus-5-5", "num_turns": 1, "cost_usd": 0.01,
                    "permission_denials": 0, "is_error": 0, "started_at": ago(hours=1)} for i in range(3)])
        sec = build(lake, closed_port_url(), sections=["lake_agents"])["sections"]["lake_agents"]
    models = sec["rows"][0]["models"]
    assert len(models) == fc.CAP_MODELS and list(models)[0] == "claude-opus-5-5", models
    assert models["(other)"] == 20 - (fc.CAP_MODELS - 2) and sum(models.values()) == 23, models
    assert sec["truncated"] >= 20 - (fc.CAP_MODELS - 2), sec["truncated"]


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


def test_target_dir_must_be_an_absolute_real_directory_with_no_link_in_it():
    with _env(), _tmp() as tmp:
        real = Path(os.path.realpath(tmp))
        (real / "clone").mkdir()
        (real / "under" / "deep").mkdir(parents=True)
        (real / "file").write_text("x", encoding="utf-8")
        (real / "link").symlink_to(real / "clone")
        (real / "via").symlink_to(real / "under")
        assert fc.target_dir_problem(str(real / "clone")) is None and fc.target_dir_problem(f"{real}/clone/") is None
        for bad, why in ((f"{real}/clone/../clone", "no '..'"), ("relative/clone", "absolute"),
                         (str(real / "nope"), "does not exist"), (str(real / "file"), "not a real directory"),
                         (str(real / "link"), "not a real directory"),
                         (str(real / "via" / "deep"), "symlink in its path"),
                         (f"{real}/clone\n", "control character"), ("", "non-empty")):
            assert why in (fc.target_dir_problem(bad) or ""), (bad, fc.target_dir_problem(bad))
        base = ["--nwo", NWO, "--name", NAME, "--lake-dir", str(real / "no-lake"), "--sections", "lake_issues",
                "--json"]
        code, out, err = run_main([*base, "--target-dir", "relative/clone"])
        assert code == 2 and out == "" and "--target-dir must be an absolute path" in err, (code, err)
        code, out, err = run_main([*base, f"--target-dir={real / 'via' / 'deep'}"])
        assert code == 2 and "symlink in its path" in err, (code, err)
        code, out, err = run_main([*base, f"--target-dir={real / 'clone'}"])
        doc = json.loads(out)
    assert code == 0 and doc["target_dir"] and str(real) not in out, (code, err, doc.get("target_dir"))


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


def test_index_code_counts_the_target_under_its_checkout_directory():
    # the registry names it zer0-CMS, the checkout (and so the index) projects/zer0-cms
    routes = index_routes()
    routes[("POST", "/collections/ws-test/points/count")] = lambda b: (200, {"result": {"count": (
        302 if b["filter"]["must"][1]["match"] == {"value": "zer0-cms"} else 0)}})
    with _env(), _tmp() as tmp, Stub(routes) as stub:
        registry = tmp / "projects.yml"
        registry.write_text("- name: zer0-CMS\n  submodule_path: projects/zer0-cms\n  branch: main\n"
                            "  repo_url: https://github.com/bamr87/zer0-CMS\n", encoding="utf-8")
        sec = build(tmp / "no-lake", stub.url, nwo="bamr87/zer0-CMS", name="zer0-CMS", queries=["jekyll build"],
                    sections=["index_code"], registry_path=registry)["sections"]["index_code"]
    assert "zer0-CMS has ~302 chunks" in sec["note"] and "holds no chunks" not in sec["note"], sec["note"]
    assert any(r["project"] == "zer0-cms" and r["snippet"] for r in sec["rows"]), "the target's code is its own"
    assert fc.checkout_dir("/nonexistent/projects.yml", "bamr87/x", "x") == "x", "no registry row: the name"


def test_index_code_leaves_out_the_registry_copies_and_shows_a_range_once():
    def hit(path, score, start="39", end="43"):
        return {"id": f"{path}{score}", "score": score,
                "payload": {"filePath": path, "startLine": start, "endLine": end, "codeChunk": "code"}}
    searches = {0: [hit("_data/cv_portfolio.json", 0.821), hit("_data/cv_portfolio.json", 0.801),
                    hit("_data/projects.yml", 0.80), hit("projects/SCHEMA.md", 0.79),
                    hit("specs/STACKS.md", 0.70, "23", "36"), hit("specs/STACKS.md", 0.69, "23", "36"),
                    hit("docs/STANDARDS.md", 0.68)],
                1: [hit("specs/STACKS.md", 0.75, "23", "36"), hit("pages/SCHEMA.md", 0.70)]}
    routes = index_routes()
    routes[("POST", "/collections/ws-test/points/search")] = \
        lambda b: (200, {"result": searches.get(int(b["vector"][0]), [])})
    with _env(), _tmp() as tmp, Stub(routes) as stub:
        sec = build(tmp / "no-lake", stub.url, queries=["docs project in jekyll, ruby", "schema"],
                    sections=["index_code"])["sections"]["index_code"]
    paths = [(r["query"], r["path"]) for r in sec["rows"]]
    assert paths == [("docs project in jekyll, ruby", "specs/STACKS.md"),
                     ("docs project in jekyll, ruby", "docs/STANDARDS.md"), ("schema", "pages/SCHEMA.md")], paths
    assert sec["truncated"] == 0 and sec["status"] == "ok", sec
    body = next(r for r in stub.requests if r[1].endswith("/points/search"))[2]
    assert body["filter"] == {"must_not": [{"key": "filePath", "match": {"any": list(fc.INDEX_EXCLUDED)}}]}, body
    assert "fileHash" in body["with_payload"], body


def test_index_code_withholds_code_the_checkout_no_longer_has():
    import hashlib

    def hit(path, score, chunk, file_hash=None):
        payload = {"filePath": path, "startLine": "1", "endLine": "16", "codeChunk": chunk}
        if file_hash is not None:
            payload["fileHash"] = file_hash
        return {"id": path, "score": score, "payload": payload}
    with _env(), _tmp() as tmp:
        root = tmp / "checkout"
        (root / "tools").mkdir(parents=True)
        (root / "projects" / NAME).mkdir(parents=True)
        (root / "tools" / "fresh.py").write_bytes(b"print('as indexed')\n")
        (root / "projects" / NAME / "README.md").write_bytes(b"# zer0-CMS: one Python platform\n")
        sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
        found = [hit("tools/fresh.py", 0.9, "print('as indexed')", sha(b"print('as indexed')\n")),
                 hit(f"projects/{NAME}/README.md", 0.88, "Fleet CMS: Rails 8.1 on Administrate",
                     sha(b"# zer0-CMS: Rails 8.1 on Administrate\n")),
                 hit(f"projects/{NAME}/gone.md", 0.87, "deleted since the scan", "0" * 64),
                 hit("tools/unhashed.py", 0.86, "no hash in the payload")]
        routes = index_routes()
        routes[("POST", "/collections/ws-test/points/search")] = lambda _b: (200, {"result": found})
        with Stub(routes) as stub:
            sec = build(tmp / "no-lake", stub.url, queries=["cms"], sections=["index_code"],
                        index_root=root)["sections"]["index_code"]
    rows = {r["path"]: r for r in sec["rows"]}
    assert rows["tools/fresh.py"]["snippet"] == "print('as indexed')" and "stale" not in rows["tools/fresh.py"]
    assert rows["tools/unhashed.py"]["snippet"], "no hash: the hit cannot be checked and is shown as before"
    readme, gone = rows[f"projects/{NAME}/README.md"], rows[f"projects/{NAME}/gone.md"]
    assert readme["snippet"] is None and readme["stale"] and "changed since the index scanned it" in readme["withheld"]
    assert gone["snippet"] is None and gone["stale"] and "not in this checkout" in gone["withheld"], gone
    assert "Rails 8.1" not in json.dumps(sec), "the outdated code never reaches the pack"
    assert sec["status"] == "stale" and "1 hit(s) from changed files, 1 from files not in" in sec["note"], sec
    assert fc.REMEDY_INDEX in sec["note"], sec["note"]
    assert fc.file_freshness("../escape", "0" * 64, root) is None and fc.file_freshness("/abs", "0" * 64, root) is None


def _hashed(path, score, chunk, data: bytes):
    """A hit Kilo cut from a file holding `data`: its fileHash is the sha256 of those bytes."""
    import hashlib
    return {"id": path, "score": score, "payload": {"filePath": path, "startLine": "1", "endLine": "16",
                                                     "codeChunk": chunk, "fileHash": hashlib.sha256(data).hexdigest()}}


def _index_with(found):
    routes = index_routes()
    routes[("POST", "/collections/ws-test/points/search")] = lambda _b: (200, {"result": found})
    return routes


def test_index_code_checks_the_targets_hits_against_the_agents_clone():
    # Every hit was compared with the hub checkout running the planes, but the agent reads its own clone of the
    # target at the branch head, which the hub's submodule pointer can lag: the target's hits are checked
    # against --target-dir (whose root is the repository's), the hub's still against the hub checkout.
    new, old = b"# zer0-CMS: one Python platform\n", b"# zer0-CMS: Rails 8.1 on Administrate\n"
    kept = b"still in the hub's checkout\n"
    found = [_hashed("tools/fresh.py", 0.9, "print('as indexed')", b"print('as indexed')\n"),
             _hashed(f"projects/{NAME}/README.md", 0.88, "one Python platform", new)]
    with _env(), _tmp() as tmp:
        root, clone = tmp / "hub", tmp / "clone"
        (root / "tools").mkdir(parents=True)
        (root / "projects" / NAME).mkdir(parents=True)
        clone.mkdir()
        (root / "tools" / "fresh.py").write_bytes(b"print('as indexed')\n")
        (root / "projects" / NAME / "README.md").write_bytes(old)   # the hub's pointer lags the branch head
        (root / "projects" / NAME / "kept.md").write_bytes(kept)
        (clone / "README.md").write_bytes(new)
        with Stub(_index_with(found)) as stub:
            lagging = build(tmp / "no-lake", stub.url, queries=["cms"], sections=["index_code"], index_root=root)
            cloned = build(tmp / "no-lake", stub.url, queries=["cms"], sections=["index_code"], index_root=root,
                           target_dir=clone)
        with Stub(_index_with([*found, _hashed(f"projects/{NAME}/kept.md", 0.87, "kept", kept)])) as stub:
            behind = build(tmp / "no-lake", stub.url, queries=["cms"], sections=["index_code"], index_root=root,
                           target_dir=clone)["sections"]["index_code"]
    sec = lagging["sections"]["index_code"]
    assert sec["status"] == "stale" and fc.REMEDY_INDEX in sec["note"], "against the hub's lagging checkout"
    sec = cloned["sections"]["index_code"]
    rows = {r["path"]: r for r in sec["rows"]}
    assert sec["status"] == "ok" and rows[f"projects/{NAME}/README.md"]["snippet"] == "one Python platform", sec
    assert rows["tools/fresh.py"]["snippet"], "the hub's hit is checked against the hub checkout, not the clone"
    assert "checked against its clone" in sec["note"] and "target_dir" not in lagging, sec["note"]
    assert cloned["target_dir"] and str(clone) not in json.dumps(cloned), ("recorded, redacted", cloned["target_dir"])
    rows = {r["path"]: r for r in behind["rows"]}
    assert behind["status"] == "stale" and rows[f"projects/{NAME}/kept.md"]["stale"], behind
    assert "index behind the agent's clone: 0 hit(s) from changed files, 1 from files not in" in behind["note"]
    assert f"`tools/update-submodules.sh --no-commit {NAME}`" in behind["note"], behind["note"]
    assert fc.REMEDY_INDEX not in behind["note"], "a re-scan alone cannot catch the hub's checkout up"


def test_index_code_without_the_targets_checkout_says_so_and_never_blames_the_index():
    # From a worktree or a fresh clone without submodules, every hashed hit from the target was 'missing', the
    # section 'stale' and the remedy a Kilo re-scan, which cannot help: the submodule is not checked out here.
    found = [_hashed(f"projects/{NAME}/README.md", 0.88, "one Python platform", b"# zer0-CMS\n"),
             _hit(f"projects/{NAME}/Gemfile", 0.80),                       # no fileHash: never checkable, shown
             _hashed("tools/fresh.py", 0.9, "print('as indexed')", b"print('as indexed')\n")]
    for layout in ("empty", "absent"):
        with _env(), _tmp() as tmp:
            root = tmp / "worktree"
            (root / "tools").mkdir(parents=True)
            (root / "tools" / "fresh.py").write_bytes(b"print('as indexed')\n")
            if layout == "empty":
                (root / "projects" / NAME).mkdir(parents=True)
            assert not fc.checked_out(root, NAME), layout
            with Stub(_index_with(found)) as stub:
                sec = build(tmp / "no-lake", stub.url, queries=["cms"], sections=["index_code"],
                            index_root=root)["sections"]["index_code"]
        rows = {r["path"]: r for r in sec["rows"]}
        readme = rows[f"projects/{NAME}/README.md"]
        assert sec["status"] == "ok" and readme["snippet"] is None and "stale" not in readme, (layout, sec)
        assert f"projects/{NAME} is not checked out here" in readme["withheld"], readme
        assert rows[f"projects/{NAME}/Gemfile"]["snippet"] and rows["tools/fresh.py"]["snippet"], rows
        assert f"`git submodule update --init projects/{NAME}`" in sec["note"] and "--target-dir" in sec["note"]
        assert fc.REMEDY_INDEX not in sec["note"] and "index behind" not in sec["note"], sec["note"]


def test_file_freshness_follows_no_link_in_the_tree():
    import hashlib
    with _tmp() as tmp:
        clone, outside = tmp / "clone", tmp / "outside"
        (outside / "docs").mkdir(parents=True)
        clone.mkdir()
        (outside / "docs" / "a.md").write_bytes(b"x\n")
        (clone / "docs").symlink_to(outside / "docs")
        (clone / "f.md").symlink_to(outside / "docs" / "a.md")
        (clone / "plain").write_bytes(b"a file, not a directory\n")
        h = hashlib.sha256(b"x\n").hexdigest()
        assert fc.file_freshness("docs/a.md", h, outside) == "fresh"
        assert fc.file_freshness("docs/a.md", h, clone) is None, "a linked directory is never followed"
        assert fc.file_freshness("f.md", h, clone) is None, "nor a linked file"
        assert fc.file_freshness("plain/a.md", h, clone) == "missing", "a file where the index saw a directory"
        assert fc.checked_out(clone.parent, "nope") is False


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


def test_telemetry_older_than_72_hours_is_stale_and_keeps_its_rows():
    with _env(), _tmp() as tmp, Stub(es_routes(newest="2026-10-27T11:00:00.000Z")) as stub:
        sec = build(tmp / "no-lake", stub.url, sections=["telemetry_errors"])["sections"]["telemetry_errors"]
    assert sec["status"] == "stale" and sec["rows"] and sec["age_hours"] == 97.0, (sec["status"], sec["age_hours"])
    assert "Claude Code telemetry last refreshed 97 h ago" in sec["note"] and "observe up" in sec["note"], sec["note"]


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


def test_each_read_only_layer_refuses_a_write_on_its_own():
    # A WRITABLE lake (0644 in a 0755 directory), so the filesystem refuses
    # nothing and only open_ro's own layers stand between it and a write.
    with _tmp() as tmp:
        db = rich_lake(tmp) / fl.DB_NAME
        before = db.read_bytes()
        conn = fc.open_ro(db)
        try:
            assert conn.execute("PRAGMA query_only").fetchone()[0] == 1, "query_only is on"
            for layer in ("query_only", "mode=ro"):
                try:
                    conn.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
                    raise AssertionError(f"a write got past {layer}")
                except sqlite3.OperationalError as exc:
                    assert "readonly" in str(exc).lower(), (layer, exc)
                conn.execute("PRAGMA query_only = OFF")   # peel the top layer: mode=ro must refuse alone
        finally:
            conn.close()
        assert db.read_bytes() == before, "the lake file changed"


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

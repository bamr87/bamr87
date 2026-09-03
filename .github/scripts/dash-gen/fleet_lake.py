#!/usr/bin/env python3
"""
fleet_lake — the LOCAL DATA LAKE and the TRACE EXPORTER of the local stack.

Everything the control plane knows about the fleet lives in GitHub: workflow
runs, their jobs and steps, the run logs (where claude-code-action reports
its model, turns, and cost), the open issues, the workflow files themselves,
and — for repos managed by GitFactory (bamr87/gitorio) — the `.factory/`
blueprints + prompts that those workflows were compiled from. The committed
`_data/*.yml` signals are AGGREGATES of that data, sized for a static page.
This module extracts the underlying records into a local SQLite database so
they can be queried, diffed, traced, and re-deployed from the bench without
another API call — the "download the data stored in GitHub for local
management and deployment" half of the local stack (docs/HARNESS-OPS.md,
"The local stack").

Three subcommands:

  sync     PyGithub over every OWNED registry repo (+ the hub): upserts
           repos, workflow files (classified with harness_registry — kind,
           auth, kill switch, GitFactory provenance), `.factory/**` and
           `fleet.manifest.yml`, workflow runs → jobs → steps, the run-log
           zip (per entry, capped), the claude-code-action facts scraped
           from those logs (model, session id, turns, cost, tool grants),
           and the window's issues/PRs. Idempotent: rerunning upserts.
  status   What the lake holds — tables, freshness, per-repo counts, the
           export ledger, and whether Phoenix is reachable. `--json` is the
           console's /api/lake document.
  export   Turn the lake's agent runs (workflow → jobs → steps → the Claude
           step with model/tokens/cost → tool calls when the log carries
           them) and this machine's Claude Code sessions (~/.claude/projects
           JSONL: every assistant turn and tool call, with real timestamps)
           into OpenInference spans and ship them to Arize Phoenix over
           OTLP/HTTP — the TRACEABILITY store of the local stack (compose
           service `phoenix`, UI on :6006). Trace and span ids are
           DETERMINISTIC (sha256 of the run / session key), so a re-export
           is idempotent at Phoenix rather than a duplicate; an `exports`
           ledger in the lake skips what was already shipped unless --force.

Design rules, same as every other dash-gen module: the network half degrades
(a repo that 404s yields no rows, not a crash); the analytics half is pure
and fixture-tested (test_fleet_lake.py) — log parsing, span building, and
id derivation need neither GitHub nor OpenTelemetry. The OTel SDK is an
OPTIONAL dependency imported only by `export` without --dry-run, and the
lake itself is gitignored (`.dash-lake/`): it holds logs, so it is never
committed and never published.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("fleet_lake requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import actions_analytics  # registry path + owner_repo + token resolution
import harness_registry   # workflow classification (kind/auth/switch/factory)

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
LAKE_DIR_DEFAULT = Path(os.environ.get("DASH_LAKE_DIR") or (REPO_ROOT / ".dash-lake"))
DB_NAME = "fleet.sqlite"
SCHEMA_VERSION = 2
PHOENIX_DEFAULT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or "http://127.0.0.1:6006"
PHOENIX_UI_DEFAULT = os.environ.get("PHOENIX_UI_URL") or PHOENIX_DEFAULT
CLAUDE_DIR_DEFAULT = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")) / "projects"
INSTRUMENTATION = "bamr87-dash-lake"
PROJECT_CI_DEFAULT = "fleet-harnesses"
PROJECT_LOCAL_DEFAULT = "claude-code-local"

CLAUDE_ACTION_MARKER = harness_registry.CLAUDE_ACTION_MARKER
FACTORY_DIR = ".factory"
MANIFEST_FILE = harness_registry.MANIFEST_FILE
MAX_FACTORY_FILES = 80
MAX_FILE_BYTES = 256_000
TERMINAL = ("success", "failure", "cancelled", "timed_out", "startup_failure", "skipped")
ERROR_CONCLUSIONS = ("failure", "timed_out", "startup_failure")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS syncs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, window_days INTEGER,
  repos INTEGER, runs INTEGER, jobs INTEGER, logs INTEGER, issues INTEGER, files INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS repos (
  nwo TEXT PRIMARY KEY, name TEXT, category TEXT, status TEXT, external INTEGER, archived INTEGER,
  default_branch TEXT, factory INTEGER, manifest INTEGER, synced_at TEXT);
CREATE TABLE IF NOT EXISTS workflows (
  nwo TEXT, path TEXT, name TEXT, sha TEXT, text TEXT, ai INTEGER, kind TEXT, triggers TEXT, crons TEXT,
  switch TEXT, factory_blueprint TEXT, factory_hash TEXT, model TEXT, max_turns INTEGER, auth TEXT,
  synced_at TEXT, PRIMARY KEY (nwo, path));
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, nwo TEXT, workflow_path TEXT, workflow_name TEXT, event TEXT, status TEXT,
  conclusion TEXT, head_branch TEXT, head_sha TEXT, run_attempt INTEGER, run_number INTEGER,
  created_at TEXT, run_started_at TEXT, updated_at TEXT, html_url TEXT, logs_url TEXT, ai INTEGER,
  synced_at TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, run_id INTEGER, nwo TEXT, name TEXT, status TEXT, conclusion TEXT,
  started_at TEXT, completed_at TEXT, runner_name TEXT, html_url TEXT);
CREATE TABLE IF NOT EXISTS steps (
  job_id INTEGER, number INTEGER, name TEXT, status TEXT, conclusion TEXT, started_at TEXT,
  completed_at TEXT, PRIMARY KEY (job_id, number));
CREATE TABLE IF NOT EXISTS logs (
  run_id INTEGER, entry TEXT, bytes INTEGER, truncated INTEGER, text TEXT, PRIMARY KEY (run_id, entry));
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id INTEGER PRIMARY KEY, nwo TEXT, model TEXT, session_id TEXT, num_turns INTEGER, cost_usd REAL,
  duration_ms INTEGER, permission_denials INTEGER, is_error INTEGER, max_turns INTEGER,
  allowed_tools TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
  cache_write_tokens INTEGER, started_at TEXT, ended_at TEXT, tool_calls TEXT, turns INTEGER);
CREATE TABLE IF NOT EXISTS issues (
  nwo TEXT, number INTEGER, title TEXT, state TEXT, is_pr INTEGER, labels TEXT, author TEXT,
  created_at TEXT, updated_at TEXT, closed_at TEXT, html_url TEXT, body TEXT, PRIMARY KEY (nwo, number));
CREATE TABLE IF NOT EXISTS factory_files (
  nwo TEXT, path TEXT, sha TEXT, text TEXT, synced_at TEXT, PRIMARY KEY (nwo, path));
CREATE TABLE IF NOT EXISTS sessions (
  key TEXT PRIMARY KEY, session_id TEXT, transcript TEXT, sidechain INTEGER, source TEXT,
  repo TEXT, cwd TEXT, git_branch TEXT, version TEXT, entrypoint TEXT, user_type TEXT,
  models TEXT, turns INTEGER, tool_calls INTEGER, tool_errors INTEGER, records INTEGER,
  input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
  cost_usd REAL, started_at TEXT, ended_at TEXT, duration_ms INTEGER,
  first_prompt TEXT, mtime TEXT, synced_at TEXT);
CREATE TABLE IF NOT EXISTS session_turns (
  key TEXT, idx INTEGER, message_id TEXT, model TEXT, cost_usd REAL, tool_calls INTEGER,
  input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
  text TEXT, started_at TEXT, ended_at TEXT, duration_ms INTEGER, PRIMARY KEY (key, idx));
CREATE TABLE IF NOT EXISTS session_tools (
  key TEXT, idx INTEGER, seq INTEGER, message_id TEXT, name TEXT, tool_use_id TEXT, input TEXT,
  started_at TEXT, ended_at TEXT, duration_ms INTEGER, is_error INTEGER,
  PRIMARY KEY (key, idx, seq));
CREATE TABLE IF NOT EXISTS exports (
  key TEXT PRIMARY KEY, kind TEXT, trace_id TEXT, spans INTEGER, endpoint TEXT, exported_at TEXT);
CREATE INDEX IF NOT EXISTS runs_nwo_created ON runs (nwo, created_at);
CREATE INDEX IF NOT EXISTS runs_ai_created ON runs (ai, created_at);
CREATE INDEX IF NOT EXISTS jobs_run ON jobs (run_id);
CREATE INDEX IF NOT EXISTS sessions_repo ON sessions (repo, started_at);
CREATE INDEX IF NOT EXISTS session_tools_name ON session_tools (name);
"""

TABLES = ["repos", "workflows", "factory_files", "runs", "jobs", "steps", "logs",
          "agent_runs", "issues", "sessions", "session_turns", "session_tools", "exports", "syncs"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value) -> str | None:
    """datetime -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC); strings pass through."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        ts = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def to_ns(value) -> int | None:
    ts = value if isinstance(value, dt.datetime) else parse_iso(value)
    if ts is None:
        return None
    return int(ts.timestamp() * 1_000_000_000)


def det_id(key: str, nbytes: int) -> int:
    """Deterministic OTel id: the first nbytes of sha256(key), never zero
    (0 is the invalid trace/span id in OTel)."""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:nbytes], "big") or 1


def trace_id_for(key: str) -> int:
    return det_id(f"trace:{key}", 16)


def span_id_for(trace_key: str, name: str) -> int:
    return det_id(f"span:{trace_key}:{name}", 8)


def hex_trace(trace_id: int) -> str:
    return f"{trace_id:032x}"


def lake_paths(lake_dir: Path | str | None = None) -> tuple[Path, Path]:
    d = Path(lake_dir) if lake_dir else LAKE_DIR_DEFAULT
    return d, d / DB_NAME


def connect(lake_dir: Path | str | None = None, create: bool = True) -> sqlite3.Connection:
    d, db = lake_paths(lake_dir)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    if create:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
        conn.commit()
    return conn


def upsert(conn: sqlite3.Connection, table: str, row: dict, keys: list[str]) -> None:
    cols = list(row)
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET {updates}")
    conn.execute(sql, [row[c] for c in cols])


# --------------------------------------------------------------------------- #
# log parsing (pure): claude-code-action facts out of a run log
# --------------------------------------------------------------------------- #
LOG_TS_RX = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) ?(.*)$")
_NUM = r"\s*:\s*([0-9.]+)"


def _split_log(text: str) -> tuple[str, list[tuple[int, str | None]]]:
    """Strip the Actions per-line timestamps. Returns (body, offsets) where
    offsets[i] = (start offset of line i in body, its timestamp or None)."""
    lines: list[str] = []
    stamps: list[str | None] = []
    for raw in text.splitlines():
        m = LOG_TS_RX.match(raw)
        if m:
            stamps.append(m.group(1))
            lines.append(m.group(2))
        else:
            stamps.append(None)
            lines.append(raw)
    body = "\n".join(lines)
    offsets: list[tuple[int, str | None]] = []
    pos = 0
    for line, stamp in zip(lines, stamps):
        offsets.append((pos, stamp))
        pos += len(line) + 1
    return body, offsets


def _stamp_at(offsets: list[tuple[int, str | None]], pos: int) -> str | None:
    """Timestamp of the log line containing body offset `pos` (nearest stamped
    line at or before it — continuation lines inherit)."""
    lo, hi = 0, len(offsets) - 1
    idx = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if offsets[mid][0] <= pos:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    for i in range(idx, -1, -1):
        if offsets[i][1]:
            return offsets[i][1]
    return None


def _first(rx: str, text: str, start: int = 0, end: int | None = None, flags=0):
    m = re.compile(rx, flags).search(text, start, end if end is not None else len(text))
    return m.group(1) if m else None


def parse_agent_log(text: str) -> dict:
    """Extract what claude-code-action prints even with its default
    `show_full_output: false`: the SDK options (model alias, maxTurns,
    allowedTools), the `system/init` block (resolved model), the `result`
    block (turns, cost, duration, denials, error flag) and the session id.
    With full output enabled the per-message JSON is there too, so assistant
    turns and tool calls are collected with the timestamp of their log line.
    Everything is optional; an unrelated log yields an empty dict."""
    body, offsets = _split_log(text)
    out: dict = {}
    init = re.search(r'"subtype"\s*:\s*"init"', body)
    if init:
        out["model"] = _first(r'"model"\s*:\s*"([^"]+)"', body, init.start(), init.start() + 600)
        out["started_at"] = _stamp_at(offsets, init.start())
    if "model" not in out or not out.get("model"):
        alias = _first(r'"model"\s*:\s*"([^"]+)"', body)
        if alias:
            out["model"] = alias
    sdk = body.find("SDK options:")
    if sdk >= 0:
        window = body[sdk:sdk + 4000]
        mt = _first(r'"maxTurns"' + _NUM, window)
        if mt:
            out["max_turns"] = int(float(mt))
        tools = re.search(r'"allowedTools"\s*:\s*\[([^\]]*)\]', window)
        if tools:
            out["allowed_tools"] = re.findall(r'"([^"]+)"', tools.group(1))
    result = None
    for m in re.finditer(r'"type"\s*:\s*"result"', body):
        result = m  # the last result block wins (retries print several)
    if result:
        seg_end = result.start() + 3000
        out["ended_at"] = _stamp_at(offsets, result.start())
        turns = _first(r'"num_turns"' + _NUM, body, result.start(), seg_end)
        cost = _first(r'"total_cost_usd"' + _NUM, body, result.start(), seg_end)
        dur = _first(r'"duration_ms"' + _NUM, body, result.start(), seg_end)
        denials = _first(r'"permission_denials_count"' + _NUM, body, result.start(), seg_end)
        is_err = _first(r'"is_error"\s*:\s*(true|false)', body, result.start(), seg_end)
        sub = _first(r'"subtype"\s*:\s*"([^"]+)"', body, result.start(), seg_end)
        if turns:
            out["num_turns"] = int(float(turns))
        if cost:
            out["cost_usd"] = float(cost)
        if dur:
            out["duration_ms"] = int(float(dur))
        if denials:
            out["permission_denials"] = int(float(denials))
        if is_err:
            out["is_error"] = is_err == "true"
        if sub:
            out["result_subtype"] = sub
        for key, rx in (("input_tokens", r'"input_tokens"' + _NUM),
                        ("output_tokens", r'"output_tokens"' + _NUM),
                        ("cache_read_tokens", r'"cache_read_input_tokens"' + _NUM),
                        ("cache_write_tokens", r'"cache_creation_input_tokens"' + _NUM)):
            v = _first(rx, body, result.start(), seg_end)
            if v is None:
                hits = re.findall(rx, body)
                v = max(hits, key=lambda h: float(h)) if hits else None
            if v is not None:
                out[key] = int(float(v))
    else:
        cost = _first(r'"total_cost_usd"' + _NUM, body)
        if cost:
            out["cost_usd"] = float(cost)
        turns = _first(r'"num_turns"' + _NUM, body)
        if turns:
            out["num_turns"] = int(float(turns))
    sid = _first(r"Set session_id:\s*([0-9a-fA-F-]{36})", body)
    if sid:
        out["session_id"] = sid
    turns_seen = [m.start() for m in re.finditer(r'"type"\s*:\s*"assistant"', body)]
    if turns_seen:
        out["turns"] = len(turns_seen)
    calls = []
    for m in re.finditer(r'"type"\s*:\s*"tool_use"', body):
        name = _first(r'"name"\s*:\s*"([^"]+)"', body, m.start(), m.start() + 600)
        if name:
            calls.append({"name": name, "at": _stamp_at(offsets, m.start())})
    if calls:
        out["tool_calls"] = calls
    return out


# --------------------------------------------------------------------------- #
# sync (the network half)
# --------------------------------------------------------------------------- #
def _content_text(blob) -> str:
    try:
        return blob.decoded_content.decode("utf-8", "replace")
    except Exception:
        return ""


def sync_workflows(conn, repo, nwo: str, now: str, max_files: int) -> dict[str, dict]:
    """Upsert every .github/workflows/*.yml; unchanged blobs (same sha) are
    reclassified from the stored text without a second content fetch.
    Returns {path: info} for the AI ones (the runs sync needs to know)."""
    try:
        listing = repo.get_contents(".github/workflows")
    except Exception:
        return {}
    if not isinstance(listing, list):
        listing = [listing]
    ai: dict[str, dict] = {}
    known = {r["path"]: r["sha"] for r in conn.execute(
        "SELECT path, sha FROM workflows WHERE nwo=?", (nwo,))}
    seen = 0
    for entry in listing:
        if not entry.name.endswith((".yml", ".yaml")):
            continue
        seen += 1
        if seen > max_files:
            break
        if known.get(entry.path) == entry.sha:
            row = conn.execute("SELECT text FROM workflows WHERE nwo=? AND path=?",
                               (nwo, entry.path)).fetchone()
            text = row["text"] if row else ""
        else:
            try:
                text = _content_text(repo.get_contents(entry.path))
            except Exception:
                continue
        info = harness_registry.classify_workflow(entry.path, text)
        factory = info.get("factory") or {}
        upsert(conn, "workflows", {
            "nwo": nwo, "path": entry.path, "name": info["name"], "sha": entry.sha, "text": text,
            "ai": int(bool(info["ai"])), "kind": info.get("kind"),
            "triggers": json.dumps(info["triggers"]), "crons": json.dumps(info["crons"]),
            "switch": info.get("switch"), "factory_blueprint": factory.get("blueprint"),
            "factory_hash": factory.get("hash"), "model": info.get("model"),
            "max_turns": info.get("max_turns"), "auth": info.get("auth"), "synced_at": now,
        }, ["nwo", "path"])
        if info["ai"]:
            ai[entry.path] = info
    return ai


def sync_factory(conn, repo, nwo: str, root_names: set[str], now: str) -> int:
    """Mirror `.factory/**` (blueprints, prompts, config, metrics ledgers) and
    the fleet/v1 manifest — the DESIGN side of a GitFactory-managed repo, so
    a compiled `factory--*.yml` in the lake can be diffed against the
    blueprint it claims (header hash) without the app."""
    count = 0
    targets: list = []
    if MANIFEST_FILE in root_names:
        try:
            targets.append(repo.get_contents(MANIFEST_FILE))
        except Exception:
            pass
    if FACTORY_DIR in root_names:
        stack = [FACTORY_DIR]
        while stack and len(targets) < MAX_FACTORY_FILES:
            path = stack.pop()
            try:
                listing = repo.get_contents(path)
            except Exception:
                continue
            if not isinstance(listing, list):
                listing = [listing]
            for c in listing:
                if c.type == "dir":
                    stack.append(c.path)
                elif len(targets) < MAX_FACTORY_FILES:
                    targets.append(c)
    known = {r["path"]: r["sha"] for r in conn.execute(
        "SELECT path, sha FROM factory_files WHERE nwo=?", (nwo,))}
    for c in targets:
        if known.get(c.path) == c.sha:
            conn.execute("UPDATE factory_files SET synced_at=? WHERE nwo=? AND path=?",
                         (now, nwo, c.path))
            count += 1
            continue
        if (c.size or 0) > MAX_FILE_BYTES:
            continue
        try:
            text = _content_text(repo.get_contents(c.path))
        except Exception:
            continue
        upsert(conn, "factory_files", {"nwo": nwo, "path": c.path, "sha": c.sha, "text": text,
                                       "synced_at": now}, ["nwo", "path"])
        count += 1
    return count


def store_logs(conn, session, run_id: int, logs_url: str, max_bytes: int) -> tuple[int, str]:
    """Download one run's log zip and store each entry (step files first, then
    the per-job full logs) until the per-run byte cap. Returns (entries,
    agent-relevant text) — the text the claude-code-action facts are parsed
    from."""
    try:
        resp = session.get(logs_url, timeout=90)
        if resp.status_code != 200:
            return 0, ""
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except Exception:
        return 0, ""
    names = [n for n in zf.namelist() if n.endswith(".txt")]
    names.sort(key=lambda n: (0 if "/" in n else 1, n))
    used, stored = 0, 0
    agent_text: list[str] = []
    for name in names:
        try:
            raw = zf.read(name)
        except Exception:
            continue
        text = raw.decode("utf-8", "replace")
        if CLAUDE_ACTION_MARKER in text or "total_cost_usd" in text or "SDK options:" in text:
            agent_text.append(text)
        truncated = 0
        if used + len(raw) > max_bytes:
            keep = max(0, max_bytes - used)
            text = text[:keep] + ("\n[dash-lake: truncated at per-run cap]\n" if keep < len(text) else "")
            truncated = 1
        upsert(conn, "logs", {"run_id": run_id, "entry": name, "bytes": len(raw),
                              "truncated": truncated, "text": text}, ["run_id", "entry"])
        stored += 1
        used += len(raw)
        if used >= max_bytes:
            break
    return stored, "\n".join(agent_text)


def sync_runs(conn, repo, nwo: str, session, window_start: dt.datetime, max_runs: int,
              ai_paths: set[str], jobs_mode: str, logs_mode: str, max_log_bytes: int,
              now: str) -> dict:
    counts = {"runs": 0, "jobs": 0, "logs": 0, "agent": 0}
    try:
        runs = repo.get_workflow_runs(created=f">={window_start.strftime('%Y-%m-%d')}")
    except Exception:
        return counts
    seen = 0
    for run in runs:
        if seen >= max_runs:
            break
        seen += 1
        created = run.created_at
        if created and created.replace(tzinfo=dt.timezone.utc) < window_start:
            break  # newest-first
        is_ai = run.path in ai_paths
        prior = conn.execute("SELECT status FROM runs WHERE id=?", (run.id,)).fetchone()
        upsert(conn, "runs", {
            "id": run.id, "nwo": nwo, "workflow_path": run.path, "workflow_name": run.name,
            "event": run.event, "status": run.status, "conclusion": run.conclusion,
            "head_branch": run.head_branch, "head_sha": run.head_sha,
            "run_attempt": run.run_attempt, "run_number": run.run_number,
            "created_at": iso(run.created_at), "run_started_at": iso(run.run_started_at),
            "updated_at": iso(run.updated_at), "html_url": run.html_url, "logs_url": run.logs_url,
            "ai": int(is_ai), "synced_at": now,
        }, ["id"])
        counts["runs"] += 1
        done = run.status == "completed"
        want_jobs = jobs_mode == "all" or (jobs_mode == "ai" and is_ai)
        # Jobs/steps are refreshed until the run completes; afterwards the
        # stored copy is final and costs no API call.
        if want_jobs and (not prior or prior["status"] != "completed" or not done):
            try:
                for job in run.jobs():
                    upsert(conn, "jobs", {
                        "id": job.id, "run_id": run.id, "nwo": nwo, "name": job.name,
                        "status": job.status, "conclusion": job.conclusion,
                        "started_at": iso(job.started_at), "completed_at": iso(job.completed_at),
                        "runner_name": job.runner_name, "html_url": job.html_url,
                    }, ["id"])
                    counts["jobs"] += 1
                    for step in job.steps or []:
                        upsert(conn, "steps", {
                            "job_id": job.id, "number": step.number, "name": step.name,
                            "status": step.status, "conclusion": step.conclusion,
                            "started_at": iso(step.started_at), "completed_at": iso(step.completed_at),
                        }, ["job_id", "number"])
            except Exception:
                pass
        want_logs = logs_mode == "all" or (logs_mode == "ai" and is_ai)
        if want_logs and done and run.conclusion in TERMINAL and run.conclusion != "skipped":
            have = conn.execute("SELECT 1 FROM logs WHERE run_id=? LIMIT 1", (run.id,)).fetchone()
            if not have:
                stored, agent_text = store_logs(conn, session, run.id, run.logs_url, max_log_bytes)
                counts["logs"] += stored
                if agent_text:
                    facts = parse_agent_log(agent_text)
                    if facts:
                        record_agent_run(conn, run.id, nwo, facts)
                        counts["agent"] += 1
        conn.commit()
    return counts


def record_agent_run(conn, run_id: int, nwo: str, facts: dict) -> None:
    upsert(conn, "agent_runs", {
        "run_id": run_id, "nwo": nwo, "model": facts.get("model"),
        "session_id": facts.get("session_id"), "num_turns": facts.get("num_turns"),
        "cost_usd": facts.get("cost_usd"), "duration_ms": facts.get("duration_ms"),
        "permission_denials": facts.get("permission_denials"),
        "is_error": None if facts.get("is_error") is None else int(bool(facts.get("is_error"))),
        "max_turns": facts.get("max_turns"),
        "allowed_tools": json.dumps(facts.get("allowed_tools")) if facts.get("allowed_tools") else None,
        "input_tokens": facts.get("input_tokens"), "output_tokens": facts.get("output_tokens"),
        "cache_read_tokens": facts.get("cache_read_tokens"),
        "cache_write_tokens": facts.get("cache_write_tokens"),
        "started_at": facts.get("started_at"), "ended_at": facts.get("ended_at"),
        "tool_calls": json.dumps(facts.get("tool_calls")) if facts.get("tool_calls") else None,
        "turns": facts.get("turns"),
    }, ["run_id"])


def sync_issues(conn, repo, nwo: str, window_start: dt.datetime, cap: int) -> int:
    n = 0
    try:
        issues = repo.get_issues(state="all", sort="updated", direction="desc", since=window_start)
        for issue in issues:
            if n >= cap:
                break
            n += 1
            upsert(conn, "issues", {
                "nwo": nwo, "number": issue.number, "title": (issue.title or "")[:300],
                "state": issue.state, "is_pr": int(issue.pull_request is not None),
                "labels": json.dumps([lb.name for lb in issue.labels]),
                "author": issue.user.login if issue.user else None,
                "created_at": iso(issue.created_at), "updated_at": iso(issue.updated_at),
                "closed_at": iso(issue.closed_at), "html_url": issue.html_url,
                "body": (issue.body or "")[:20000],
            }, ["nwo", "number"])
    except Exception:
        pass
    return n


def owned_projects(registry: list[dict], cfg: dict, only: list[str] | None) -> list[tuple[dict, str]]:
    owner = cfg["hub_nwo"].split("/", 1)[0]
    out = []
    for project in harness_registry.ensure_hub(registry, cfg):
        nwo = actions_analytics.owner_repo(project.get("repo_url", "") or "")
        if not nwo or not nwo.startswith(owner + "/"):
            continue  # external upstreams are consumed, never mirrored
        if only and project.get("name") not in only and nwo not in only \
                and nwo.split("/", 1)[1] not in only:
            continue
        out.append((project, nwo))
    return out


def cmd_sync(args: argparse.Namespace) -> int:
    token = actions_analytics.resolve_token()
    if not token:
        sys.stderr.write("lake sync: no GitHub token (GH_TOKEN/GITHUB_TOKEN or `gh auth login`) — "
                         "nothing extracted.\n")
        return 1
    try:
        from github import Auth, Github
        import requests
    except ImportError:
        sys.stderr.write("lake sync requires PyGithub + requests: pip install PyGithub requests\n")
        return 2
    gh = Github(auth=Auth.Token(token), per_page=100)
    session = requests.Session()
    session.headers["Authorization"] = f"token {token}"
    cfg = harness_registry.load_config(Path(args.fleet))
    with actions_analytics.REGISTRY.open() as fh:
        registry = yaml.safe_load(fh) or []
    targets = owned_projects(registry, cfg, args.repo)
    if not targets:
        sys.stderr.write("lake sync: no owned repos matched.\n")
        return 1
    conn = connect(args.lake)
    started = utcnow()
    now = iso(started)
    window_start = started - dt.timedelta(days=args.days)
    totals = {"repos": 0, "runs": 0, "jobs": 0, "logs": 0, "issues": 0, "files": 0, "agent": 0}
    for project, nwo in targets:
        sys.stderr.write(f"  lake · {nwo}\n")
        try:
            repo = gh.get_repo(nwo)
        except Exception as exc:
            sys.stderr.write(f"    unreachable ({exc.__class__.__name__}); skipped\n")
            continue
        try:
            root_names = {c.name for c in repo.get_contents("")}
        except Exception:
            root_names = set()
        upsert(conn, "repos", {
            "nwo": nwo, "name": project.get("name"), "category": project.get("category"),
            "status": project.get("status"), "external": 0, "archived": int(bool(repo.archived)),
            "default_branch": repo.default_branch, "factory": int(FACTORY_DIR in root_names),
            "manifest": int(MANIFEST_FILE in root_names), "synced_at": now,
        }, ["nwo"])
        totals["repos"] += 1
        ai = sync_workflows(conn, repo, nwo, now, cfg["inventory"]["max_workflow_files"])
        totals["files"] += len(ai)
        if not args.no_files:
            totals["files"] += sync_factory(conn, repo, nwo, root_names, now)
        conn.commit()
        if not repo.archived:
            c = sync_runs(conn, repo, nwo, session, window_start, args.max_runs, set(ai),
                          args.jobs, args.logs, args.max_log_bytes, now)
            for k in ("runs", "jobs", "logs", "agent"):
                totals[k] += c[k]
        if not args.no_issues:
            totals["issues"] += sync_issues(conn, repo, nwo, window_start, args.max_issues)
        conn.commit()
    finished = utcnow()
    conn.execute(
        "INSERT INTO syncs (started_at, finished_at, window_days, repos, runs, jobs, logs, issues, files, note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now, iso(finished), args.days, totals["repos"], totals["runs"], totals["jobs"],
         totals["logs"], totals["issues"], totals["files"],
         f"jobs={args.jobs} logs={args.logs} agent_runs={totals['agent']}"))
    conn.commit()
    _, db = lake_paths(args.lake)
    sys.stderr.write(
        f"lake: {db} — {totals['repos']} repos, {totals['runs']} runs, {totals['jobs']} jobs, "
        f"{totals['logs']} log entries, {totals['agent']} agent runs parsed, "
        f"{totals['issues']} issues/PRs, {totals['files']} files "
        f"in {(finished - started).total_seconds():.0f}s\n")
    return 0


# --------------------------------------------------------------------------- #
# status (offline)
# --------------------------------------------------------------------------- #
def phoenix_reachable(collector: str, timeout: float = 1.5) -> bool | None:
    """Best-effort probe of the Phoenix collector (GET /healthz, then /). None
    when the URL is malformed; never raises — the console renders the answer."""
    if not collector:
        return None
    for path in ("/healthz", "/"):
        try:
            req = urllib.request.Request(collector.rstrip("/") + path, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                if 200 <= resp.status < 400:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            return False
        except (urllib.error.URLError, ValueError, OSError):
            return False
    return False


def status_dict(lake_dir: Path | str | None = None, probe: bool = True,
                collector: str = PHOENIX_DEFAULT, ui: str = PHOENIX_UI_DEFAULT) -> dict:
    d, db = lake_paths(lake_dir)
    out: dict = {
        "present": db.exists(), "lake_dir": str(d), "db_path": str(db),
        "size_bytes": db.stat().st_size if db.exists() else 0,
        "schema_version": None, "tables": {}, "last_sync": None, "repos": [],
        "agent_runs": {"count": 0, "cost_usd": 0.0, "turns": 0, "models": {}},
        "sessions": {"count": 0, "cost_usd": 0.0, "turns": 0, "tool_calls": 0, "last": None},
        "exports": {"count": 0, "last": None, "spans": 0},
        "phoenix": {"collector": collector, "ui": ui,
                    "reachable": phoenix_reachable(collector) if probe else None},
    }
    if not db.exists():
        return out
    conn = connect(d, create=False)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        out["schema_version"] = int(row["value"]) if row else None
        for t in TABLES:
            try:
                out["tables"][t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            except sqlite3.Error:
                out["tables"][t] = None
        last = conn.execute("SELECT * FROM syncs ORDER BY id DESC LIMIT 1").fetchone()
        out["last_sync"] = dict(last) if last else None
        out["repos"] = [dict(r) for r in conn.execute(
            "SELECT r.nwo, r.factory, r.manifest, r.archived, r.synced_at, "
            "(SELECT COUNT(*) FROM runs WHERE runs.nwo=r.nwo) AS runs, "
            "(SELECT COUNT(*) FROM runs WHERE runs.nwo=r.nwo AND ai=1) AS ai_runs, "
            "(SELECT MAX(created_at) FROM runs WHERE runs.nwo=r.nwo) AS last_run, "
            "(SELECT COUNT(*) FROM workflows WHERE workflows.nwo=r.nwo) AS workflows, "
            "(SELECT COUNT(*) FROM issues WHERE issues.nwo=r.nwo AND state='open') AS open_issues "
            "FROM repos r ORDER BY runs DESC, r.nwo")]
        ag = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS cost, "
                          "COALESCE(SUM(num_turns),0) AS turns FROM agent_runs").fetchone()
        out["agent_runs"] = {"count": ag["n"], "cost_usd": round(ag["cost"] or 0, 4),
                             "turns": ag["turns"], "models": {
                                 r["model"] or "unknown": r["n"] for r in conn.execute(
                                     "SELECT model, COUNT(*) AS n FROM agent_runs GROUP BY model")}}
        try:
            se = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS cost, "
                              "COALESCE(SUM(turns),0) AS turns, COALESCE(SUM(tool_calls),0) AS tools, "
                              "MAX(ended_at) AS last FROM sessions").fetchone()
            out["sessions"] = {"count": se["n"], "cost_usd": round(se["cost"] or 0, 4),
                               "turns": se["turns"], "tool_calls": se["tools"], "last": se["last"]}
        except sqlite3.Error:  # pre-v2 lake, before `lake sessions` existed
            pass
        ex = conn.execute("SELECT COUNT(*) AS n, MAX(exported_at) AS last, COALESCE(SUM(spans),0) AS spans "
                          "FROM exports").fetchone()
        out["exports"] = {"count": ex["n"], "last": ex["last"], "spans": ex["spans"]}
    finally:
        conn.close()
    return out


def recent_runs(lake_dir: Path | str | None = None, limit: int = 50, ai_only: bool = True) -> list[dict]:
    d, db = lake_paths(lake_dir)
    if not db.exists():
        return []
    conn = connect(d, create=False)
    try:
        where = "WHERE r.ai=1" if ai_only else ""
        return [dict(r) for r in conn.execute(
            f"SELECT r.id, r.nwo, r.workflow_name, r.workflow_path, r.event, r.status, r.conclusion, "
            f"r.created_at, r.updated_at, r.html_url, r.ai, a.model, a.num_turns, a.cost_usd, "
            f"a.duration_ms, a.session_id, e.exported_at, e.trace_id "
            f"FROM runs r LEFT JOIN agent_runs a ON a.run_id=r.id "
            f"LEFT JOIN exports e ON e.key = 'run:' || r.nwo || ':' || r.id "
            f"{where} ORDER BY r.created_at DESC LIMIT ?", (max(1, min(int(limit), 500)),))]
    finally:
        conn.close()


def lines(lake_dir: Path | str | None = None) -> list[dict]:
    """The GitFactory-style 'lines' view: every workflow in the lake with its
    provenance (blueprint + hash), kill switch, kind, and latest conclusion."""
    d, db = lake_paths(lake_dir)
    if not db.exists():
        return []
    conn = connect(d, create=False)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT w.nwo, w.path, w.name, w.ai, w.kind, w.triggers, w.crons, w.switch, "
            "w.factory_blueprint, w.factory_hash, w.model, w.max_turns, w.auth, w.synced_at, "
            "(SELECT conclusion FROM runs WHERE runs.nwo=w.nwo AND runs.workflow_path=w.path "
            " AND status='completed' ORDER BY created_at DESC LIMIT 1) AS last_conclusion, "
            "(SELECT COUNT(*) FROM runs WHERE runs.nwo=w.nwo AND runs.workflow_path=w.path) AS runs, "
            "(SELECT 1 FROM factory_files f WHERE f.nwo=w.nwo AND f.path=w.factory_blueprint) AS blueprint_in_lake "
            "FROM workflows w ORDER BY w.ai DESC, w.nwo, w.path")]
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace) -> int:
    s = status_dict(args.lake, probe=not args.no_probe)
    if args.json:
        print(json.dumps(s, indent=2, default=str))
        return 0
    if not s["present"]:
        print(f"lake: nothing at {s['db_path']} — run `tools/dash lake sync` first.")
    else:
        t = s["tables"]
        ls = s["last_sync"] or {}
        print(f"lake: {s['db_path']} ({s['size_bytes'] / 1e6:.1f} MB, schema v{s['schema_version']})")
        print(f"  last sync: {ls.get('finished_at') or '—'} (window {ls.get('window_days')}d, "
              f"{ls.get('repos')} repos) {ls.get('note') or ''}")
        print("  tables:   " + ", ".join(f"{k}={v}" for k, v in t.items()))
        a = s["agent_runs"]
        print(f"  agent runs: {a['count']} · ${a['cost_usd']:.2f} · {a['turns']} turns · "
              + ", ".join(f"{m}×{n}" for m, n in a["models"].items()))
        ss = s["sessions"]
        print(f"  local sessions: {ss['count']} · ${ss['cost_usd']:.2f} · {ss['turns']} turns · "
              f"{ss['tool_calls']} tool calls (last {ss['last'] or '—'})")
        e = s["exports"]
        print(f"  exports:  {e['count']} traces / {e['spans']} spans (last {e['last'] or '—'})")
        for r in s["repos"][:60]:
            marks = ("⚙" if r.get("factory") else " ") + ("📜" if r.get("manifest") else " ")
            print(f"    {marks} {r['nwo']:<34} runs={r['runs']:<4} ai={r['ai_runs']:<3} "
                  f"wf={r['workflows']:<3} issues={r['open_issues']:<3} last={r.get('last_run') or '—'}")
    p = s["phoenix"]
    state = "reachable" if p["reachable"] else "not reachable" if p["reachable"] is False else "not probed"
    print(f"  phoenix:  {p['collector']} — {state} (UI {p['ui']})")
    return 0


# --------------------------------------------------------------------------- #
# span building (pure) — OpenInference over the lake / local sessions
# --------------------------------------------------------------------------- #
def _clean_attrs(attrs: dict) -> dict:
    out = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (dict,)):
            out[k] = json.dumps(v, default=str)[:8000]
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x) for x in v][:64]
        elif isinstance(v, (str, bool, int, float)):
            out[k] = v[:8000] if isinstance(v, str) else v
        else:
            out[k] = str(v)
    return out


def _span(trace_key: str, trace_id: int, name: str, kind: str, start_ns: int | None,
          end_ns: int | None, parent: int | None, attrs: dict, status: str = "UNSET",
          uid: str | None = None) -> dict:
    return {
        "trace_id": trace_id, "span_id": span_id_for(trace_key, uid or name), "parent_id": parent,
        "name": name[:200], "kind": kind, "start": start_ns, "end": end_ns, "status": status,
        "attributes": _clean_attrs({"openinference.span.kind": kind, **attrs}),
    }


def _agent_step(steps: list[dict], agent: dict | None) -> dict | None:
    """The step that ran claude-code-action: the one whose interval contains
    the agent's own start stamp; else the one named after Claude; else the
    longest — the SDK log only tells us WHEN, not WHICH step."""
    timed = [s for s in steps if s.get("started_at") and s.get("completed_at")]
    if agent and agent.get("started_at"):
        t = to_ns(agent["started_at"])
        for s in timed:
            if to_ns(s["started_at"]) <= t <= to_ns(s["completed_at"]):
                return s
    for s in steps:
        if "claude" in (s.get("name") or "").lower():
            return s
    if timed:
        return max(timed, key=lambda s: to_ns(s["completed_at"]) - to_ns(s["started_at"]))
    return None


def build_run_spans(run: dict, jobs: list[dict], steps_by_job: dict[int, list[dict]],
                    agent: dict | None) -> list[dict]:
    """One trace per workflow run: run (CHAIN) → job (CHAIN) → step (CHAIN;
    the Claude step is an AGENT carrying model/tokens/cost) → tool calls
    (TOOL, when the log had full output). Times come from GitHub's own
    stamps; where the log lacks an end for a tool call the next call's start
    (or the agent's end) closes it — an approximation, labelled as such."""
    key = f"run:{run['nwo']}:{run['id']}"
    tid = trace_id_for(key)
    start = to_ns(run.get("run_started_at") or run.get("created_at"))
    end = to_ns(run.get("updated_at")) or start
    ends = [to_ns(j.get("completed_at")) for j in jobs if j.get("completed_at")]
    if ends:
        end = max([end or 0] + ends)
    bad = (run.get("conclusion") in ERROR_CONCLUSIONS) or bool(agent and agent.get("is_error"))
    session_id = (agent or {}).get("session_id") or f"gh-run-{run['id']}"
    root = _span(key, tid, f"{run.get('workflow_name') or run.get('workflow_path')}", "CHAIN",
                 start, end, None, {
                     "session.id": session_id,
                     "github.repository": run["nwo"], "github.workflow": run.get("workflow_name"),
                     "github.workflow_path": run.get("workflow_path"), "github.run_id": run["id"],
                     "github.run_attempt": run.get("run_attempt"), "github.event": run.get("event"),
                     "github.conclusion": run.get("conclusion"), "github.head_branch": run.get("head_branch"),
                     "github.head_sha": run.get("head_sha"), "github.html_url": run.get("html_url"),
                     "input.value": f"{run.get('event')} → {run.get('workflow_name')}",
                     "output.value": run.get("conclusion") or run.get("status"),
                     "llm.cost.total": (agent or {}).get("cost_usd"),
                 }, "ERROR" if bad else "OK", uid="run")
    spans = [root]
    for job in jobs:
        js = to_ns(job.get("started_at")) or start
        je = to_ns(job.get("completed_at")) or end
        jspan = _span(key, tid, job.get("name") or f"job {job['id']}", "CHAIN", js, je, root["span_id"], {
            "github.job_id": job["id"], "github.job_conclusion": job.get("conclusion"),
            "github.runner": job.get("runner_name"), "github.html_url": job.get("html_url"),
        }, "ERROR" if job.get("conclusion") in ERROR_CONCLUSIONS else "OK", uid=f"job:{job['id']}")
        spans.append(jspan)
        steps = steps_by_job.get(job["id"], [])
        agent_step = _agent_step(steps, agent) if agent else None
        for step in steps:
            ss, se = to_ns(step.get("started_at")), to_ns(step.get("completed_at"))
            if ss is None or se is None:
                continue
            is_agent = agent_step is not None and step is agent_step
            attrs: dict = {"github.step": step.get("number"), "github.step_conclusion": step.get("conclusion")}
            if is_agent:
                attrs.update({
                    "llm.model_name": agent.get("model"), "llm.system": "anthropic",
                    "llm.token_count.prompt": agent.get("input_tokens"),
                    "llm.token_count.completion": agent.get("output_tokens"),
                    "llm.token_count.prompt_details.cache_read": agent.get("cache_read_tokens"),
                    "llm.token_count.prompt_details.cache_write": agent.get("cache_write_tokens"),
                    "llm.cost.total": agent.get("cost_usd"), "session.id": session_id,
                    "claude.num_turns": agent.get("num_turns"), "claude.max_turns": agent.get("max_turns"),
                    "claude.permission_denials": agent.get("permission_denials"),
                    "claude.duration_ms": agent.get("duration_ms"),
                    "claude.allowed_tools": agent.get("allowed_tools"),
                    "output.value": f"{agent.get('num_turns')} turns, ${agent.get('cost_usd')}",
                })
            sspan = _span(key, tid, step.get("name") or f"step {step.get('number')}",
                          "AGENT" if is_agent else "CHAIN", ss, se, jspan["span_id"], attrs,
                          "ERROR" if step.get("conclusion") in ERROR_CONCLUSIONS else
                          "UNSET" if step.get("conclusion") == "skipped" else "OK",
                          uid=f"step:{job['id']}:{step.get('number')}")
            spans.append(sspan)
            if is_agent:
                calls = agent.get("tool_calls") or []
                for i, call in enumerate(calls):
                    cs = to_ns(call.get("at")) or ss
                    nxt = calls[i + 1].get("at") if i + 1 < len(calls) else None
                    ce = to_ns(nxt) or to_ns(agent.get("ended_at")) or se
                    spans.append(_span(key, tid, call.get("name") or "tool", "TOOL", cs, max(cs, ce),
                                       sspan["span_id"], {"tool.name": call.get("name"),
                                                          "claude.tool_call_index": i,
                                                          "dash.end_time": "approximate"},
                                       "OK", uid=f"tool:{job['id']}:{i}"))
    return spans


def _local_cost(model: str | None, usage: dict) -> float | None:
    try:
        import ai_activity
        row = {"input": usage.get("input_tokens", 0) or 0, "output": usage.get("output_tokens", 0) or 0,
               "cache_5m": 0, "cache_1h": 0, "cache_read": usage.get("cache_read_input_tokens", 0) or 0}
        cc = usage.get("cache_creation") or {}
        row["cache_5m"] = cc.get("ephemeral_5m_input_tokens", usage.get("cache_creation_input_tokens", 0) or 0) or 0
        row["cache_1h"] = cc.get("ephemeral_1h_input_tokens", 0) or 0
        return round(float(ai_activity.cost_usd(ai_activity.normalize_model(model) or "", row)), 6)
    except Exception:
        return None


def read_session(path: Path) -> list[dict]:
    """Parse one ~/.claude/projects JSONL transcript into records (tolerant:
    bad lines are skipped, streamed duplicates keep the last)."""
    out = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def session_identity(records: list[dict], source: str = "") -> tuple[str, str, bool, str]:
    """(session_id, transcript stem, sidechain?, trace key) for one transcript.

    Sub-agent transcripts sit beside the main one and carry the PARENT's
    sessionId, so the file stem disambiguates them: same session id (Phoenix
    groups them), distinct trace key (otherwise two files collide on one
    trace). The key is the JOIN between a stored session and its trace.
    """
    stem = Path(source).stem if source else ""
    sid = next((r.get("sessionId") for r in records if r.get("sessionId")), None) or stem
    sidechain = bool(stem) and stem != sid
    return sid, stem, sidechain, f"session:{sid}" + (f"/{stem}" if sidechain else "")


def tool_results(records: list[dict]) -> dict[str, dict]:
    """tool_use_id -> {'ts': end time in ns, 'is_error': bool} from the user
    turns that carry tool_result blocks. A tool call is closed by its result,
    which is what gives a tool span its real duration."""
    out: dict[str, dict] = {}
    for r in records:
        if r.get("type") != "user":
            continue
        content = (r.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                out[block["tool_use_id"]] = {"ts": to_ns(r.get("timestamp")),
                                             "is_error": bool(block.get("is_error"))}
    return out


def fold_turns(records: list[dict]) -> tuple[list[str], dict[str, dict]]:
    """Fold assistant records into one entry per message id, in order.

    A streamed turn arrives as several records sharing a message id; the last
    usage wins and the content blocks accumulate, so one assistant turn is one
    unit of cost regardless of how it was streamed to disk.
    """
    turns: dict[str, dict] = {}
    order: list[str] = []
    for r in records:
        if r.get("type") != "assistant":
            continue
        msg = r.get("message") or {}
        mid = msg.get("id") or r.get("uuid")
        if not mid:
            continue
        if mid not in turns:
            order.append(mid)
            turns[mid] = {"first": r, "blocks": [], "usage": None, "ts": to_ns(r.get("timestamp"))}
        t = turns[mid]
        t["usage"] = msg.get("usage") or t["usage"]
        content = msg.get("content")
        if isinstance(content, list):
            t["blocks"].extend(b for b in content if isinstance(b, dict))
        elif isinstance(content, str):
            t["blocks"].append({"type": "text", "text": content})
        t["model"] = msg.get("model") or t.get("model")
    return order, turns


def first_prompt(records: list[dict]) -> str | None:
    """What the human asked to start the session — the queued prompt when the
    transcript records one, else the first plain-text user turn (a tool_result
    is the harness answering itself, never a prompt)."""
    for r in records:
        if r.get("type") == "queue-operation" and r.get("content"):
            return str(r["content"])[:2000]
    for r in records:
        if r.get("type") != "user":
            continue
        content = (r.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()[:2000]
        if isinstance(content, list):
            text = " ".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text").strip()
            if text:
                return text[:2000]
    return None


def _usage_tokens(usage: dict) -> dict:
    cc = usage.get("cache_creation") or {}
    write = usage.get("cache_creation_input_tokens")
    if write is None and cc:
        write = (cc.get("ephemeral_5m_input_tokens") or 0) + (cc.get("ephemeral_1h_input_tokens") or 0)
    return {"input_tokens": usage.get("input_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or 0,
            "cache_read_tokens": usage.get("cache_read_input_tokens") or 0,
            "cache_write_tokens": write or 0}


def session_facts(records: list[dict], source: str = "", mtime: str | None = None) -> dict | None:
    """One transcript -> the rows the lake stores: {'session', 'turns', 'tools'}.

    The denormalized twin of build_session_spans: same records, same trace
    key, same turn folding — shaped for SQL instead of OTLP. This is what
    makes a local session reviewable OFFLINE, without Phoenix and without
    re-reading ~/.claude, and joinable to its trace when Phoenix is up.
    """
    if not records:
        return None
    stamps = [t for t in (to_ns(r.get("timestamp")) for r in records if r.get("timestamp")) if t]
    if not stamps:
        return None
    sid, stem, sidechain, key = session_identity(records, source)
    results = tool_results(records)
    order, turns = fold_turns(records)
    first = next((r for r in records if r.get("cwd")), records[0])
    cwd = first.get("cwd")
    try:
        import ai_activity
        repo = ai_activity.repo_for(cwd) if cwd else None
    except Exception:
        repo = Path(cwd).name if cwd else None

    turn_rows, tool_rows, models = [], [], []
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    cost_total, tool_errors = 0.0, 0
    prev_end = min(stamps)
    for i, mid in enumerate(order):
        t = turns[mid]
        usage = t["usage"] or {}
        model = t.get("model")
        if model and model not in models:
            models.append(model)
        ts = t["ts"] or prev_end
        text = " ".join(b.get("text", "") for b in t["blocks"] if b.get("type") == "text").strip()
        blocks = [b for b in t["blocks"] if b.get("type") == "tool_use"]
        ends = [results.get(b.get("id"), {}).get("ts") for b in blocks]
        turn_end = max([ts] + [e for e in ends if e]) if blocks else ts
        cost = _local_cost(model, usage) if usage else None
        cost_total += cost or 0.0
        tok = _usage_tokens(usage)
        for k in totals:
            totals[k] += tok[k]
        turn_rows.append({"key": key, "idx": i, "message_id": mid, "model": model, "cost_usd": cost,
                          "tool_calls": len(blocks), "text": text[:4000] or None,
                          "started_at": iso(dt.datetime.fromtimestamp(ts / 1e9, dt.timezone.utc)),
                          "ended_at": iso(dt.datetime.fromtimestamp(max(ts, turn_end) / 1e9, dt.timezone.utc)),
                          "duration_ms": int(max(0, turn_end - ts) / 1e6), **tok})
        for j, b in enumerate(blocks):
            res = results.get(b.get("id")) or {}
            end = res.get("ts")
            if res.get("is_error"):
                tool_errors += 1
            tool_rows.append({
                "key": key, "idx": i, "seq": j, "message_id": mid, "name": b.get("name") or "tool",
                "tool_use_id": b.get("id"),
                "input": json.dumps(b.get("input"), default=str)[:4000] if b.get("input") is not None else None,
                "started_at": iso(dt.datetime.fromtimestamp(ts / 1e9, dt.timezone.utc)),
                "ended_at": iso(dt.datetime.fromtimestamp(end / 1e9, dt.timezone.utc)) if end else None,
                "duration_ms": int(max(0, end - ts) / 1e6) if end else None,
                "is_error": 1 if res.get("is_error") else 0})
        prev_end = max(prev_end, turn_end)

    start_ns, end_ns = min(stamps), max(max(stamps), prev_end)
    session = {
        "key": key, "session_id": sid, "transcript": stem or None, "sidechain": 1 if sidechain else 0,
        "source": source or None, "repo": repo, "cwd": cwd, "git_branch": first.get("gitBranch"),
        "version": first.get("version"), "entrypoint": first.get("entrypoint"),
        "user_type": first.get("userType"), "models": json.dumps(models), "turns": len(order),
        "tool_calls": len(tool_rows), "tool_errors": tool_errors, "records": len(records),
        "cost_usd": round(cost_total, 6) if cost_total else 0.0,
        "started_at": iso(dt.datetime.fromtimestamp(start_ns / 1e9, dt.timezone.utc)),
        "ended_at": iso(dt.datetime.fromtimestamp(end_ns / 1e9, dt.timezone.utc)),
        "duration_ms": int(max(0, end_ns - start_ns) / 1e6),
        "first_prompt": first_prompt(records), "mtime": mtime, "synced_at": iso(utcnow()), **totals}
    return {"session": session, "turns": turn_rows, "tools": tool_rows}


def build_session_spans(records: list[dict], source: str = "") -> list[dict]:
    """One trace per Claude Code session: session (AGENT) → assistant turn
    (LLM: model, tokens, cost, text) → tool call (TOOL: name, input; closed
    by the matching tool_result's timestamp). Real timestamps throughout."""
    if not records:
        return []
    sid, stem, sidechain, key = session_identity(records, source)
    tid = trace_id_for(key)
    stamps = [to_ns(r.get("timestamp")) for r in records if r.get("timestamp")]
    stamps = [s for s in stamps if s]
    if not stamps:
        return []
    first = next((r for r in records if r.get("cwd")), records[0])
    cwd = first.get("cwd")
    repo = None
    try:
        import ai_activity
        repo = ai_activity.repo_for(cwd) if cwd else None
    except Exception:
        repo = Path(cwd).name if cwd else None
    # tool results close tool spans
    results = {k: v["ts"] for k, v in tool_results(records).items() if v["ts"]}
    spans: list[dict] = []
    total_cost = 0.0
    order, turns = fold_turns(records)
    prev_end = min(stamps)
    for i, mid in enumerate(order):
        t = turns[mid]
        usage = t["usage"] or {}
        model = t.get("model")
        ts = t["ts"] or prev_end
        text = " ".join(b.get("text", "") for b in t["blocks"] if b.get("type") == "text").strip()
        tool_blocks = [b for b in t["blocks"] if b.get("type") == "tool_use"]
        tool_ends = [results.get(b.get("id")) for b in tool_blocks]
        turn_end = max([ts] + [e for e in tool_ends if e]) if tool_blocks else ts + 1_000_000
        cost = _local_cost(model, usage) if usage else None
        total_cost += cost or 0.0
        lspan = _span(key, tid, model or "assistant", "LLM", ts, max(ts, turn_end), None, {
            "llm.model_name": model, "llm.system": "anthropic", "llm.provider": "anthropic",
            "llm.token_count.prompt": usage.get("input_tokens"),
            "llm.token_count.completion": usage.get("output_tokens"),
            "llm.token_count.prompt_details.cache_read": usage.get("cache_read_input_tokens"),
            "llm.token_count.prompt_details.cache_write": usage.get("cache_creation_input_tokens"),
            "llm.cost.total": cost, "output.value": text[:4000] or None,
            "claude.turn_index": i, "claude.message_id": mid,
        }, "OK", uid=f"turn:{mid}")
        spans.append(lspan)
        for j, b in enumerate(tool_blocks):
            te = results.get(b.get("id")) or (ts + 1_000_000)
            spans.append(_span(key, tid, b.get("name") or "tool", "TOOL", ts, max(ts, te), lspan["span_id"], {
                "tool.name": b.get("name"), "tool_call.id": b.get("id"),
                "input.value": json.dumps(b.get("input"), default=str)[:4000] if b.get("input") is not None else None,
            }, "OK", uid=f"tool:{mid}:{j}"))
        prev_end = max(prev_end, turn_end)
    root = _span(key, tid, "claude-code session" + (" (sub-agent)" if sidechain else ""), "AGENT",
                 min(stamps), max(max(stamps), prev_end), None, {
        "session.id": sid, "dash.trace_key": key, "claude.transcript": stem or None,
        "claude.sidechain": sidechain,
        "user.id": first.get("userType"), "claude.cwd": cwd, "github.repository": repo,
        "claude.git_branch": first.get("gitBranch"), "claude.version": first.get("version"),
        "claude.entrypoint": first.get("entrypoint"), "claude.turns": len(order),
        "llm.cost.total": round(total_cost, 6) if total_cost else None,
        "input.value": next((str(r.get("content") or "")[:2000] for r in records
                             if r.get("type") == "queue-operation" and r.get("content")), None),
        "dash.source": source,
    }, "OK", uid="session")
    for s in spans:
        if s["parent_id"] is None:
            s["parent_id"] = root["span_id"]
    return [root] + spans


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def _run_bundle(conn, run_id: int) -> tuple[dict, list[dict], dict[int, list[dict]], dict | None]:
    run = dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE run_id=? ORDER BY started_at, id", (run_id,))]
    steps = {}
    for j in jobs:
        steps[j["id"]] = [dict(r) for r in conn.execute(
            "SELECT * FROM steps WHERE job_id=? ORDER BY number", (j["id"],))]
    a = conn.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    agent = dict(a) if a else None
    if agent:
        for k in ("allowed_tools", "tool_calls"):
            if agent.get(k):
                try:
                    agent[k] = json.loads(agent[k])
                except (TypeError, json.JSONDecodeError):
                    agent[k] = None
    return run, jobs, steps, agent


def select_runs(conn, days: int, limit: int, force: bool, ai_only: bool = True) -> list[int]:
    since = iso(utcnow() - dt.timedelta(days=days))
    where = ["status='completed'", "created_at>=?"]
    if ai_only:
        where.append("ai=1")
    sql = f"SELECT id, nwo FROM runs WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?"
    rows = conn.execute(sql, (since, limit)).fetchall()
    if force:
        return [r["id"] for r in rows]
    out = []
    for r in rows:
        if not conn.execute("SELECT 1 FROM exports WHERE key=?", (f"run:{r['nwo']}:{r['id']}",)).fetchone():
            out.append(r["id"])
    return out


def session_files(claude_dir: Path, days: int) -> list[Path]:
    if not claude_dir.exists():
        return []
    cutoff = (utcnow() - dt.timedelta(days=days)).timestamp()
    files = []
    for p in claude_dir.rglob("*.jsonl"):
        try:
            if p.stat().st_mtime >= cutoff and p.stat().st_size > 0:
                files.append(p)
        except OSError:
            continue
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def to_otel(spans: list[dict], project: str):
    """Plain span dicts -> OTel SDK ReadableSpans (imported lazily: the SDK is
    optional and only needed to ship)."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.util.instrumentation import InstrumentationScope
    from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

    resource = Resource.create({"openinference.project.name": project, "service.name": INSTRUMENTATION})
    scope = InstrumentationScope(INSTRUMENTATION, str(SCHEMA_VERSION))
    flags = TraceFlags(TraceFlags.SAMPLED)
    out = []
    for s in spans:
        ctx = SpanContext(trace_id=s["trace_id"], span_id=s["span_id"], is_remote=False, trace_flags=flags)
        parent = (SpanContext(trace_id=s["trace_id"], span_id=s["parent_id"], is_remote=False, trace_flags=flags)
                  if s.get("parent_id") else None)
        status = (Status(StatusCode.ERROR) if s["status"] == "ERROR"
                  else Status(StatusCode.OK) if s["status"] == "OK" else Status(StatusCode.UNSET))
        out.append(ReadableSpan(
            name=s["name"], context=ctx, parent=parent, resource=resource, attributes=s["attributes"],
            kind=SpanKind.INTERNAL, status=status, start_time=s["start"], end_time=s["end"],
            instrumentation_scope=scope))
    return out


def ship(spans: list[dict], project: str, endpoint: str, headers: dict | None = None,
         batch: int = 256) -> int:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import SpanExportResult

    exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", headers=headers or None,
                                timeout=30)
    otel = to_otel(spans, project)
    sent = 0
    for i in range(0, len(otel), batch):
        chunk = otel[i:i + batch]
        if exporter.export(chunk) != SpanExportResult.SUCCESS:
            raise RuntimeError(f"Phoenix refused a batch at {endpoint} (sent {sent} spans first)")
        sent += len(chunk)
    exporter.shutdown()
    return sent


def _otel_available() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(m) is not None
               for m in ("opentelemetry.sdk", "opentelemetry.exporter.otlp.proto.http"))


def cmd_export(args: argparse.Namespace) -> int:
    endpoint = args.endpoint or PHOENIX_DEFAULT
    headers = {}
    api_key = os.environ.get("PHOENIX_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"  # forwarded, never printed
    d, db = lake_paths(args.lake)
    bundles: list[tuple[str, str, str, list[dict]]] = []  # (key, kind, project, spans)
    if not args.no_ci:
        if not db.exists():
            sys.stderr.write(f"lake export: no lake at {db} — run `tools/dash lake sync` (or use --local only).\n")
            if not args.local:
                return 1
        else:
            conn = connect(d, create=False)
            try:
                for run_id in select_runs(conn, args.days, args.limit, args.force):
                    run, jobs, steps, agent = _run_bundle(conn, run_id)
                    spans = build_run_spans(run, jobs, steps, agent)
                    bundles.append((f"run:{run['nwo']}:{run_id}", "run", args.project, spans))
            finally:
                conn.close()
    if args.local:
        seen_keys = {}
        if db.exists():
            conn = connect(d, create=False)
            try:
                seen_keys = {r["key"]: r["spans"] for r in conn.execute(
                    "SELECT key, spans FROM exports WHERE kind='session'")}
            finally:
                conn.close()
        for path in session_files(Path(args.claude_dir), args.days)[: args.limit]:
            spans = build_session_spans(read_session(path), str(path))
            if not spans:
                continue
            key = spans[0]["attributes"]["dash.trace_key"]
            if not args.force and seen_keys.get(key) == len(spans):
                continue  # nothing new since the last export
            bundles.append((key, "session", args.local_project, spans))
    total = sum(len(b[3]) for b in bundles)
    if not bundles:
        sys.stderr.write("lake export: nothing new to export (use --force to resend).\n")
        return 0
    if args.dry_run:
        preview = {
            "endpoint": endpoint, "traces": len(bundles), "spans": total,
            "bundles": [{"key": k, "kind": kind, "project": proj, "spans": len(s),
                         "trace_id": hex_trace(s[0]["trace_id"]),
                         "root": s[0]["name"], "root_attributes": s[0]["attributes"]}
                        for k, kind, proj, s in bundles],
        }
        d.mkdir(parents=True, exist_ok=True)
        (d / "export-preview.json").write_text(json.dumps(preview, indent=2, default=str))
        sys.stderr.write(f"lake export (dry run): {len(bundles)} traces / {total} spans would go to "
                         f"{endpoint}/v1/traces — preview in {d / 'export-preview.json'}\n")
        for b in preview["bundles"][:12]:
            sys.stderr.write(f"  {b['kind']:<8} {b['key']:<60} {b['spans']:>4} spans  trace {b['trace_id']}\n")
        return 0
    if not _otel_available():
        sys.stderr.write("lake export needs the OpenTelemetry SDK + OTLP/HTTP exporter:\n"
                         "  pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http\n"
                         "(tools/console/requirements.txt carries both; --dry-run needs neither)\n")
        return 2
    if phoenix_reachable(endpoint) is False:
        sys.stderr.write(f"lake export: Phoenix not reachable at {endpoint} — "
                         "`docker compose up -d phoenix`, or pass --endpoint.\n")
        return 1
    conn = connect(d)
    shipped_traces, shipped_spans = 0, 0
    try:
        for key, kind, project, spans in bundles:
            n = ship(spans, project, endpoint, headers)
            upsert(conn, "exports", {"key": key, "kind": kind, "trace_id": hex_trace(spans[0]["trace_id"]),
                                     "spans": n, "endpoint": endpoint, "exported_at": iso(utcnow())}, ["key"])
            conn.commit()
            shipped_traces += 1
            shipped_spans += n
    except RuntimeError as exc:
        sys.stderr.write(f"lake export: {exc}\n")
        return 1
    finally:
        conn.close()
    sys.stderr.write(f"lake export: {shipped_traces} traces / {shipped_spans} spans → {endpoint}/v1/traces "
                     f"(projects: {args.project}{', ' + args.local_project if args.local else ''}); "
                     f"open {PHOENIX_UI_DEFAULT}/projects\n")
    return 0


# --------------------------------------------------------------------------- #
# sessions — extract this machine's Claude Code transcripts INTO the lake
# --------------------------------------------------------------------------- #
def store_session(conn: sqlite3.Connection, facts: dict) -> tuple[int, int]:
    """Persist one transcript's rows. Idempotent by trace key: a session that
    was resumed since the last extract has its turns/tools REPLACED rather
    than appended, so the lake mirrors the transcript instead of accumulating
    a longer and longer history of it."""
    key = facts["session"]["key"]
    upsert(conn, "sessions", facts["session"], ["key"])
    conn.execute("DELETE FROM session_turns WHERE key=?", (key,))
    conn.execute("DELETE FROM session_tools WHERE key=?", (key,))
    for row in facts["turns"]:
        upsert(conn, "session_turns", row, ["key", "idx"])
    for row in facts["tools"]:
        upsert(conn, "session_tools", row, ["key", "idx", "seq"])
    return len(facts["turns"]), len(facts["tools"])


def cmd_sessions(args: argparse.Namespace) -> int:
    claude_dir = Path(args.claude_dir)
    if not claude_dir.exists():
        sys.stderr.write(f"lake sessions: no transcripts at {claude_dir} "
                         "(set CLAUDE_CONFIG_DIR or pass --claude-dir).\n")
        return 0 if args.json else 1
    files = session_files(claude_dir, args.days)
    if args.limit:
        files = files[: args.limit]
    conn = connect(args.lake)
    sessions = turns = tools = skipped = 0
    try:
        for path in files:
            mtime = iso(dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc))
            if not args.force:
                row = conn.execute("SELECT mtime FROM sessions WHERE source=?", (str(path),)).fetchone()
                if row and row["mtime"] == mtime:
                    skipped += 1
                    continue  # transcript untouched since the last extract
            facts = session_facts(read_session(path), str(path), mtime)
            if not facts:
                continue
            if args.repo and facts["session"].get("repo") != args.repo:
                continue
            t, tl = store_session(conn, facts)
            sessions += 1
            turns += t
            tools += tl
        conn.commit()
    finally:
        conn.close()
    out = {"scanned": len(files), "sessions": sessions, "turns": turns,
           "tool_calls": tools, "skipped": skipped, "claude_dir": str(claude_dir)}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        sys.stderr.write(f"lake sessions: {sessions} transcripts → {turns} turns / {tools} tool calls "
                         f"({skipped} unchanged, {len(files)} scanned in {claude_dir})\n")
    return 0


# --------------------------------------------------------------------------- #
# review — the ANALYSIS layer over both planes, offline
# --------------------------------------------------------------------------- #
def review(lake_dir: Path | str | None = None, days: int = 30, repo: str | None = None,
           limit: int = 10) -> dict:
    """Unify the two planes — local Claude Code sessions and the CI agent runs
    claude-code-action produced — into one reviewable document.

    Pure SQL over the lake: no network, no Phoenix, no ~/.claude re-read. That
    is the point of extracting first — the review is reproducible from the
    lake alone, and answers the questions a trace viewer does not: what did
    the agents COST, where did the turns go, which tools fail, and what has
    not been traced yet.
    """
    d, db = lake_paths(lake_dir)
    cutoff = iso(utcnow() - dt.timedelta(days=days))
    out: dict = {"generated_at": iso(utcnow()), "window_days": days, "repo": repo,
                 "present": db.exists(), "db_path": str(db),
                 "local": {}, "ci": {}, "totals": {}, "findings": []}
    if not db.exists():
        return out
    # create=True, deliberately: SCHEMA_SQL is entirely CREATE ... IF NOT EXISTS,
    # so applying it to a lake that predates the session tables ADDS them (empty)
    # and is a no-op otherwise. That is what upgrades a v1 lake in place — without
    # it, `review` on a lake built before `sessions` existed dies on "no such
    # table: sessions" instead of reporting an empty local plane.
    conn = connect(d)
    try:
        rf = " AND repo=?" if repo else ""
        rp = [cutoff] + ([repo] if repo else [])
        s = conn.execute(
            "SELECT COUNT(*) AS sessions, COALESCE(SUM(turns),0) AS turns, "
            "COALESCE(SUM(tool_calls),0) AS tool_calls, COALESCE(SUM(tool_errors),0) AS tool_errors, "
            "COALESCE(SUM(cost_usd),0) AS cost, COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens, "
            "COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens, "
            "COALESCE(SUM(cache_write_tokens),0) AS cache_write_tokens, "
            "COALESCE(SUM(duration_ms),0) AS duration_ms "
            f"FROM sessions WHERE started_at >= ?{rf}", rp).fetchone()
        local = dict(s)
        local["cost_usd"] = round(local.pop("cost") or 0, 4)
        local["repos"] = [dict(r) for r in conn.execute(
            "SELECT repo, COUNT(*) AS sessions, COALESCE(SUM(turns),0) AS turns, "
            "ROUND(COALESCE(SUM(cost_usd),0),4) AS cost_usd "
            f"FROM sessions WHERE started_at >= ?{rf} GROUP BY repo ORDER BY cost_usd DESC", rp)]
        local["top_sessions"] = [dict(r) for r in conn.execute(
            "SELECT key, session_id, repo, git_branch, turns, tool_calls, tool_errors, "
            "ROUND(cost_usd,4) AS cost_usd, duration_ms, started_at, models, first_prompt "
            f"FROM sessions WHERE started_at >= ?{rf} ORDER BY cost_usd DESC LIMIT ?",
            rp + [limit])]
        local["tools"] = [dict(r) for r in conn.execute(
            "SELECT t.name, COUNT(*) AS calls, SUM(t.is_error) AS errors, "
            "ROUND(AVG(t.duration_ms),1) AS avg_ms "
            "FROM session_tools t JOIN sessions s ON s.key=t.key "
            f"WHERE s.started_at >= ?{(' AND s.repo=?' if repo else '')} "
            "GROUP BY t.name ORDER BY calls DESC", rp)]
        local["models"] = {r["model"] or "unknown": r["n"] for r in conn.execute(
            "SELECT u.model, COUNT(*) AS n FROM session_turns u JOIN sessions s ON s.key=u.key "
            f"WHERE s.started_at >= ?{(' AND s.repo=?' if repo else '')} GROUP BY u.model", rp)}
        local["untraced"] = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions s LEFT JOIN exports e ON e.key=s.key "
            f"WHERE s.started_at >= ?{rf} AND e.key IS NULL", rp).fetchone()["n"]
        out["local"] = local

        cf = " AND r.nwo=?" if repo else ""
        cp = [cutoff] + ([repo] if repo else [])
        c = conn.execute(
            "SELECT COUNT(*) AS agent_runs, COALESCE(SUM(a.cost_usd),0) AS cost, "
            "COALESCE(SUM(a.num_turns),0) AS turns, COALESCE(SUM(a.permission_denials),0) AS denials, "
            "COALESCE(SUM(a.is_error),0) AS errors, COALESCE(SUM(a.duration_ms),0) AS duration_ms, "
            "COALESCE(SUM(a.input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(a.output_tokens),0) AS output_tokens, "
            "COALESCE(SUM(a.cache_read_tokens),0) AS cache_read_tokens, "
            "COALESCE(SUM(a.cache_write_tokens),0) AS cache_write_tokens "
            "FROM agent_runs a JOIN runs r ON r.id=a.run_id "
            f"WHERE r.created_at >= ?{cf}", cp).fetchone()
        ci = dict(c)
        ci["cost_usd"] = round(ci.pop("cost") or 0, 4)
        ci["runs"] = conn.execute(
            f"SELECT COUNT(*) AS n FROM runs r WHERE r.created_at >= ?{cf} AND r.ai=1", cp).fetchone()["n"]
        ci["failed_runs"] = conn.execute(
            f"SELECT COUNT(*) AS n FROM runs r WHERE r.created_at >= ?{cf} AND r.ai=1 "
            "AND r.conclusion IN ('failure','timed_out','startup_failure')", cp).fetchone()["n"]
        ci["repos"] = [dict(r) for r in conn.execute(
            "SELECT r.nwo AS repo, COUNT(*) AS runs, COALESCE(SUM(a.num_turns),0) AS turns, "
            "ROUND(COALESCE(SUM(a.cost_usd),0),4) AS cost_usd "
            "FROM agent_runs a JOIN runs r ON r.id=a.run_id "
            f"WHERE r.created_at >= ?{cf} GROUP BY r.nwo ORDER BY cost_usd DESC", cp)]
        ci["workflows"] = [dict(r) for r in conn.execute(
            "SELECT r.nwo, r.workflow_name, r.workflow_path, COUNT(*) AS runs, "
            "ROUND(COALESCE(SUM(a.cost_usd),0),4) AS cost_usd, "
            "COALESCE(SUM(a.num_turns),0) AS turns, "
            "SUM(CASE WHEN r.conclusion IN ('failure','timed_out','startup_failure') THEN 1 ELSE 0 END) AS failures "
            "FROM runs r LEFT JOIN agent_runs a ON a.run_id=r.id "
            f"WHERE r.created_at >= ? AND r.ai=1{cf} "
            "GROUP BY r.nwo, r.workflow_path ORDER BY cost_usd DESC", cp)]
        ci["top_runs"] = [dict(r) for r in conn.execute(
            "SELECT r.id, r.nwo, r.workflow_name, r.conclusion, r.html_url, r.created_at, "
            "a.model, a.num_turns, ROUND(a.cost_usd,4) AS cost_usd, a.duration_ms, "
            "a.permission_denials, a.is_error, a.session_id "
            "FROM agent_runs a JOIN runs r ON r.id=a.run_id "
            f"WHERE r.created_at >= ?{cf} ORDER BY a.cost_usd DESC LIMIT ?", cp + [limit])]
        ci["models"] = {r["model"] or "unknown": r["n"] for r in conn.execute(
            "SELECT a.model, COUNT(*) AS n FROM agent_runs a JOIN runs r ON r.id=a.run_id "
            f"WHERE r.created_at >= ?{cf} GROUP BY a.model", cp)}
        ci["untraced"] = conn.execute(
            "SELECT COUNT(*) AS n FROM agent_runs a JOIN runs r ON r.id=a.run_id "
            "LEFT JOIN exports e ON e.key = 'run:' || r.nwo || ':' || r.id "
            f"WHERE r.created_at >= ?{cf} AND e.key IS NULL", cp).fetchone()["n"]
        out["ci"] = ci
    finally:
        conn.close()

    out["totals"] = {
        "cost_usd": round((local.get("cost_usd") or 0) + (ci.get("cost_usd") or 0), 4),
        "turns": (local.get("turns") or 0) + (ci.get("turns") or 0),
        "traces": (local.get("sessions") or 0) + (ci.get("agent_runs") or 0),
        "untraced": (local.get("untraced") or 0) + (ci.get("untraced") or 0),
    }
    out["findings"] = _findings(out)
    return out


def _findings(doc: dict) -> list[dict]:
    """Turn the numbers into the handful of statements worth acting on. Purely
    a function of the document, so the review is deterministic and testable."""
    f: list[dict] = []
    local, ci, tot = doc.get("local") or {}, doc.get("ci") or {}, doc.get("totals") or {}

    errs, calls = local.get("tool_errors") or 0, local.get("tool_calls") or 0
    if calls and errs / calls >= 0.10 and errs >= 5:
        worst = sorted([t for t in local.get("tools") or [] if (t.get("errors") or 0)],
                       key=lambda t: -(t["errors"] or 0))[:3]
        f.append({"severity": "warn", "plane": "local", "title": "local tool calls fail often",
                  "detail": f"{errs}/{calls} local tool calls ({errs / calls:.0%}) returned an error"
                            + (" — worst: " + ", ".join(f"{t['name']} ({t['errors']})" for t in worst) if worst else "")})

    if ci.get("errors"):
        f.append({"severity": "error", "plane": "ci", "title": "CI agent runs ended in error",
                  "detail": f"{ci['errors']} of {ci.get('agent_runs', 0)} claude-code-action runs reported "
                            "is_error — read their logs in the lake (`logs` table) before re-dispatching"})
    if ci.get("failed_runs"):
        f.append({"severity": "error", "plane": "ci", "title": "AI workflow runs failed",
                  "detail": f"{ci['failed_runs']} of {ci.get('runs', 0)} AI workflow runs concluded "
                            "failure/timed_out/startup_failure"})
    if ci.get("denials"):
        f.append({"severity": "warn", "plane": "ci", "title": "permission denials in CI",
                  "detail": f"{ci['denials']} tool-permission denials — the allowlist is narrower than the "
                            "prompt needs; widen `allowed_tools` or narrow the prompt"})

    for plane, doc_ in (("local", local), ("ci", ci)):
        read = doc_.get("cache_read_tokens") or 0
        billed = (doc_.get("input_tokens") or 0) + (doc_.get("cache_write_tokens") or 0)
        if read + billed > 1_000_000 and read / max(1, read + billed) < 0.5:
            f.append({"severity": "info", "plane": plane, "title": f"low cache reuse ({plane})",
                      "detail": f"only {read / max(1, read + billed):.0%} of prompt tokens came from cache "
                                "— long sessions re-send context that a stable prefix would cache"})

    top = (local.get("top_sessions") or [])[:1]
    if top and (local.get("cost_usd") or 0) > 0:
        share = (top[0].get("cost_usd") or 0) / local["cost_usd"]
        if share >= 0.4 and local.get("sessions", 0) > 2:
            f.append({"severity": "info", "plane": "local", "title": "cost concentrated in one session",
                      "detail": f"{share:.0%} of local spend is one session "
                                f"({top[0].get('repo') or '?'}, {top[0].get('turns')} turns, "
                                f"${top[0].get('cost_usd')})"})

    try:
        import ai_activity
        seen = set(local.get("models") or ()) | set(ci.get("models") or ())
        unpriced = sorted(m for m in seen
                          if m and m != "unknown" and ai_activity.normalize_model(m)
                          and ai_activity.normalize_model(m) not in ai_activity.PRICING)
        if unpriced:
            f.append({"severity": "warn", "plane": "both", "title": "models with no price row",
                      "detail": f"{', '.join(unpriced)} — counted but costed at $0, so every total "
                                "below understates spend; add a row to ai_activity.PRICING"})
    except Exception:
        pass

    if tot.get("untraced"):
        f.append({"severity": "info", "plane": "both", "title": "traces not shipped to Phoenix",
                  "detail": f"{tot['untraced']} sessions/runs in the lake have no export ledger entry — "
                            "`tools/dash lake export --local` to view them at :6006"})
    if not tot.get("traces"):
        f.append({"severity": "info", "plane": "both", "title": "lake holds no agent activity in this window",
                  "detail": "run `tools/dash lake sessions` (local) and `tools/dash lake sync` (CI) first"})
    return f


def cmd_review(args: argparse.Namespace) -> int:
    doc = review(args.lake, days=args.days, repo=args.repo, limit=args.limit)
    if args.json:
        print(json.dumps(doc, indent=2, default=str))
        return 0
    if not doc["present"]:
        print(f"lake review: nothing at {doc['db_path']} — run `tools/dash lake sessions` "
              "and/or `tools/dash lake sync` first.")
        return 1
    local, ci, tot = doc["local"], doc["ci"], doc["totals"]
    scope = f" · repo={doc['repo']}" if doc.get("repo") else ""
    print(f"Claude activity review — last {doc['window_days']}d{scope}")
    print(f"  total: ${tot['cost_usd']:.2f} · {tot['turns']} turns · {tot['traces']} traces "
          f"({tot['untraced']} not yet in Phoenix)")
    print(f"\n  LOCAL sessions (~/.claude transcripts)")
    print(f"    {local['sessions']} sessions · {local['turns']} turns · {local['tool_calls']} tool calls "
          f"({local['tool_errors']} errored) · ${local['cost_usd']:.2f}")
    print(f"    tokens: in {local['input_tokens']:,} · out {local['output_tokens']:,} · "
          f"cache r {local['cache_read_tokens']:,} / w {local['cache_write_tokens']:,}")
    for r in local["repos"][:8]:
        print(f"      {r['repo'] or '—':<28} {r['sessions']:>3} sessions  {r['turns']:>5} turns  ${r['cost_usd']:.2f}")
    if local["tools"]:
        print("    top tools: " + ", ".join(
            f"{t['name']}×{t['calls']}" + (f"({t['errors']}✗)" if t.get("errors") else "")
            for t in local["tools"][:8]))
    print(f"\n  CI agent runs (claude-code-action)")
    print(f"    {ci['agent_runs']} agent runs of {ci['runs']} AI workflow runs · {ci['turns']} turns · "
          f"${ci['cost_usd']:.2f} · {ci['failed_runs']} failed · {ci['denials']} denials")
    for r in ci["repos"][:8]:
        print(f"      {r['repo']:<28} {r['runs']:>3} runs      {r['turns']:>5} turns  ${r['cost_usd']:.2f}")
    for w in ci["workflows"][:8]:
        mark = "✗" if w.get("failures") else " "
        print(f"      {mark} {w['nwo']}/{w['workflow_path'].split('/')[-1]:<26} "
              f"{w['runs']:>3} runs ${w['cost_usd'] or 0:.2f}")
    if local["top_sessions"]:
        print("\n  most expensive local sessions")
        for r in local["top_sessions"][:5]:
            prompt = (r.get("first_prompt") or "").replace("\n", " ")[:58]
            print(f"    ${r['cost_usd'] or 0:>7.2f}  {r['turns']:>4}t {r['tool_calls']:>4}tc  "
                  f"{(r['repo'] or '—'):<16} {prompt}")
    if doc["findings"]:
        print("\n  findings")
        for x in doc["findings"]:
            icon = {"error": "✗", "warn": "!", "info": "·"}.get(x["severity"], "·")
            print(f"    {icon} [{x['plane']}] {x['title']} — {x['detail']}")
    return 0


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake", default=str(LAKE_DIR_DEFAULT),
                        help="lake directory (DASH_LAKE_DIR; default .dash-lake/ at the repo root)")
    sub = parser.add_subparsers(dest="lake_cmd", required=True)

    p_sync = sub.add_parser("sync", help="extract GitHub runs/jobs/steps/logs/issues/workflows/.factory into the lake")
    p_sync.add_argument("--fleet", default=str(FLEET_DEFAULT))
    p_sync.add_argument("--days", type=int, default=7, help="window for runs and issues (default 7)")
    p_sync.add_argument("--max-runs", type=int, default=60, help="runs per repo, newest first")
    p_sync.add_argument("--max-issues", type=int, default=200, help="issues/PRs per repo")
    p_sync.add_argument("--repo", action="append", help="only this registry name / nwo (repeatable)")
    p_sync.add_argument("--jobs", choices=["ai", "all", "none"], default="ai",
                        help="which runs get jobs+steps (default: AI workflow runs)")
    p_sync.add_argument("--logs", choices=["ai", "all", "none"], default="ai",
                        help="which completed runs get their log zip stored (default: AI runs)")
    p_sync.add_argument("--max-log-bytes", type=int, default=2_000_000, help="per-run log cap")
    p_sync.add_argument("--no-issues", action="store_true")
    p_sync.add_argument("--no-files", action="store_true", help="skip .factory/** + fleet.manifest.yml")
    p_sync.set_defaults(func=cmd_sync)

    p_status = sub.add_parser("status", help="what the lake holds + Phoenix reachability")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--no-probe", action="store_true", help="skip the Phoenix probe")
    p_status.set_defaults(func=cmd_status)

    p_sessions = sub.add_parser("sessions", help="extract this machine's Claude Code transcripts into the lake")
    p_sessions.add_argument("--claude-dir", default=str(CLAUDE_DIR_DEFAULT), help="~/.claude/projects")
    p_sessions.add_argument("--days", type=int, default=30, help="only transcripts touched in this window")
    p_sessions.add_argument("--limit", type=int, default=0, help="max transcripts (0 = no cap)")
    p_sessions.add_argument("--repo", default=None, help="only sessions attributed to this repo")
    p_sessions.add_argument("--force", action="store_true", help="re-read transcripts whose mtime is unchanged")
    p_sessions.add_argument("--json", action="store_true")
    p_sessions.set_defaults(func=cmd_sessions)

    p_review = sub.add_parser("review", help="analyze local sessions + CI agent runs from the lake (offline)")
    p_review.add_argument("--days", type=int, default=30)
    p_review.add_argument("--repo", default=None, help="restrict to one repo")
    p_review.add_argument("--limit", type=int, default=10, help="rows in each top-N table")
    p_review.add_argument("--json", action="store_true")
    p_review.set_defaults(func=cmd_review)

    p_export = sub.add_parser("export", help="ship OpenInference traces (agent runs, local sessions) to Phoenix")
    p_export.add_argument("--endpoint", default=None, help=f"Phoenix collector (PHOENIX_COLLECTOR_ENDPOINT; default {PHOENIX_DEFAULT})")
    p_export.add_argument("--project", default=PROJECT_CI_DEFAULT, help="Phoenix project for CI agent runs")
    p_export.add_argument("--local", action="store_true",
                          help="also export this machine's Claude Code sessions (from ~/.claude transcripts)")
    p_export.add_argument("--local-project", default=PROJECT_LOCAL_DEFAULT, help="Phoenix project for local sessions")
    p_export.add_argument("--claude-dir", default=str(CLAUDE_DIR_DEFAULT), help="~/.claude/projects")
    p_export.add_argument("--no-ci", action="store_true", help="skip the lake's CI runs")
    p_export.add_argument("--days", type=int, default=7)
    p_export.add_argument("--limit", type=int, default=200, help="max traces per kind")
    p_export.add_argument("--dry-run", action="store_true", help="build spans, write export-preview.json, send nothing")
    p_export.add_argument("--force", action="store_true", help="resend traces already in the export ledger")
    p_export.set_defaults(func=cmd_export)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

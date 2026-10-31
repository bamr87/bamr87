#!/usr/bin/env python3
"""
ai_activity — shadow-priced Claude Code usage across every repo (the dash's
AI-finance layer; see docs/DASH.md → "AI activity").

Claude Code writes one JSONL transcript per session to ~/.claude/projects/,
recording the model and full token breakdown (input / output / cache-write /
cache-read) for every assistant turn — regardless of billing mode. On a
subscription (OAuth) plan there is no invoice per interaction, so this module
answers the pilot question "what would this cost on standard API pricing?":

  scan    every */*.jsonl under the Claude projects dir, dedupe records by
          (message id, request id) — streamed responses repeat them — and
          attribute each turn to a repo via the record's cwd (worktrees and
          .git/modules paths normalized, then walk up to the nearest .git).
  ledger  merge daily aggregates into a persistent JSON ledger so history
          survives Claude Code's periodic transcript cleanup (~30 days).
          Token counts max-merge per (machine, day, repo, model); sessions
          union. Tokens only — prices are applied at report time. If repo
          attribution rules change, delete the ledger to rebuild it from the
          transcripts that still exist (stale keys are never dropped).
  report  write _data/ai_activity.yml (EPHEMERAL — gitignored, never
          committed; costs are estimates at API list prices, and publishing
          your own spend is an explicit opt-in, not a default).

It also owns the other half of local AI accounting, `dash ai run`:

  run     wrap `claude -p` with a dollar ceiling — `budget.local_usd`, or a
          call site's `budget.call_sites` cap with `--call-site` — then record
          the run's OWN reported cost — `total_cost_usd`, straight from the
          CLI, not an estimate — into a `runs` section of the same ledger,
          keyed by session id. A run that leaves no result is still recorded:
          charged at the cap as `estimated` when it may have spent, `no-spend`
          when the CLI provably never reached the model. Headless runs are
          reported as their own table and are NEVER added to the scan-derived
          estimates above: both halves see the same session, so summing them
          would double-count it.
          It is also the executor of JEV's local loop runner (docs/adr/0002,
          P1): `--stream`, `--timeout`, `--isolate` and the rest come from
          tools/jev/headless.py, imported lazily so `dash ai` never needs it.

Local-only by design: the data source is this machine's ~/.claude, so unlike
`health` this subcommand is NOT part of `dash-gen all` and never runs in CI.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import importlib
import json
import os
import platform
import re
import shutil
import signal
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("dash-gen requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "_data" / "projects.yml"
FLEET = REPO_ROOT / "_data" / "fleet.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "ai_activity.yml"
LEDGER_DEFAULT = Path(
    os.environ.get("DASH_AI_LEDGER", "~/.claude/ai-activity-ledger.json")
).expanduser()

# USD per MTok at Anthropic API list prices (source: claude-api skill model
# table, cached 2026-06-24; claude-opus-5 added 2026-08-31; 5.5 tier rows added
# 2026-10-17 from platform.claude.com/docs/en/about-claude/pricing). Cache writes:
# 1.25x input (5m TTL) / 2x (1h TTL); cache reads: 0.1x input. Unknown models
# are counted but priced at 0 and surfaced in `unpriced_models` — add a row
# here rather than guessing.
#
# This table is hand-maintained and therefore drifts: it lost `claude-opus-5`
# for two months, so every local Opus 5 session was counted at $0 (bamr87#130).
# `dash ai check` (ai_reconcile.py) now audits it against ccusage — run that
# after touching anything below.
PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5-1": {"in": 10.0, "out": 50.0},
    "claude-mythos-5-1": {"in": 10.0, "out": 50.0},
    "claude-fable-5":   {"in": 10.0, "out": 50.0},
    "claude-mythos-5":  {"in": 10.0, "out": 50.0},
    "claude-opus-5-5":  {"in": 4.0,  "out": 20.0},
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0},
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50},
    "claude-opus-5":    {"in": 5.0,  "out": 25.0},
    "claude-opus-4-8":  {"in": 5.0,  "out": 25.0},
    "claude-opus-4-7":  {"in": 5.0,  "out": 25.0},
    "claude-opus-4-6":  {"in": 5.0,  "out": 25.0},
    "claude-sonnet-5":  {"in": 3.0,  "out": 15.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5": {"in": 1.0,  "out": 5.0},
}
CACHE_5M_MULT, CACHE_1H_MULT, CACHE_READ_MULT = 1.25, 2.0, 0.1

# Rates this table deliberately does NOT apply, because list price keeps
# estimates comparable over time — but which ccusage (billing-accurate) does.
# model -> last date the intro rate was in effect, inclusive. `dash ai check`
# reads this to itemize the resulting cost delta as EXPLAINABLE rather than
# drift. claude-sonnet-5's intro rate was $2/$10 against the $3/$15 list.
INTRO_PRICING_UNTIL: dict[str, str] = {
    "claude-sonnet-5": "2026-08-31",
}

# Bare aliases occasionally recorded in place of a full id (resolved to the
# alias's current target) and dated snapshots (suffix stripped). A STALE alias
# is worse than a missing PRICING row: a missing row yields an obvious $0, a
# stale alias a plausible wrong number. Re-point these when a family's current
# model changes.
MODEL_ALIASES = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
    "fable": "claude-fable-5-1",
}
DATE_SUFFIX = re.compile(r"-20\d{6}$")

USAGE_FIELDS = ("input", "output", "cache_5m", "cache_1h", "cache_read", "turns")

# The ledger version is NOT bumped by the addition of the `runs` section, and
# that is deliberate. `merge_ledger` discards the WHOLE prior ledger when the
# version does not match, so a bump here would silently throw away every day of
# history the moment this landed — for a purely additive key. `runs` is read
# with a default instead: a v1 ledger written before this existed simply gains
# an empty section on its next merge. Bump only for a change that makes old
# data WRONG, and write a migration when you do.
LEDGER_VERSION = 1

# One record per headless `dash ai run`, keyed by session id in the ledger's
# `runs` section. Ordered as it is documented in dash-gen/README.md. The fields
# after `source` were added for the JEV loop runner (P1); like `runs` itself
# they are additive, so a row written before them simply lacks them.
RUN_FIELDS = (
    "timestamp", "machine", "repo", "session_id",
    "models", "usage", "total_cost_usd", "source",
    "call_site", "origin", "run_id", "attempt_id", "loop", "step", "item", "tier",
    "model", "outcome", "cost_source", "cap_usd", "auth_method", "cli_version", "duration_s",
)
# `--meta KEY=VALUE` may set only these, so a caller cannot overwrite a cost.
META_FIELDS = ("origin", "run_id", "attempt_id", "loop", "step", "item", "tier")
# A row is billed only when the CLI reported its cost; a row written before
# cost_source existed was always a reported one.
BILLED_SOURCES = (None, "", "reported")
# How long `dash ai run` waits for the ledger lock (`--ledger-wait`). It holds
# a cancel while it records a run, so a writer that is stopped (a `dash ai`
# suspended with Ctrl-Z) or hung must not keep it, and the Ctrl-C it ignores,
# waiting for ever.
LEDGER_WAIT_S = 30.0


class LedgerBusy(TimeoutError):
    """Another writer held the ledger lock for longer than the wait."""

# Fallback ceiling for `dash ai run` when _data/fleet.yml is unreadable (the
# wrapper must still be usable from a checkout that has no registry).
BUDGET_FALLBACK_USD = 5.0


# --------------------------------------------------------------------------- #
# model + repo attribution
# --------------------------------------------------------------------------- #
def normalize_model(model: str | None) -> str | None:
    """Canonical model id, or None for records that shouldn't be counted."""
    if not model or model == "<synthetic>":
        return None
    model = DATE_SUFFIX.sub("", model)
    return MODEL_ALIASES.get(model, model)


def _normalize_cwd(cwd: str) -> str:
    """Fold worktree / submodule-gitdir paths back onto the repo they belong to."""
    for marker in ("/.claude-worktrees/", "/.claude/worktrees/"):
        if marker in cwd:
            cwd = cwd.split(marker, 1)[0]
    if "/.git/modules/" in cwd:
        cwd = cwd.replace("/.git/modules/", "/")
    return cwd.rstrip("/") or "/"


@lru_cache(maxsize=None)
def _git_root(path: str) -> str | None:
    """Nearest ancestor (incl. path) containing a .git entry, if it exists on disk.

    A linked worktree resolves to its MAIN repo (via the .git file's
    ``gitdir: …/.git/worktrees/<name>`` pointer). A submodule's .git file
    points at ``…/.git/modules/…`` instead and is left alone — the submodule
    dir is the repo we want.
    """
    p = Path(path)
    while True:
        gitentry = p / ".git"
        if gitentry.exists():
            if gitentry.is_file():
                try:
                    content = gitentry.read_text().strip()
                except OSError:
                    content = ""
                if content.startswith("gitdir:"):
                    gd = Path(content.split(":", 1)[1].strip())
                    if not gd.is_absolute():
                        gd = (p / gd).resolve()
                    s = str(gd)
                    if "/.git/worktrees/" in s:
                        return s.split("/.git/worktrees/", 1)[0]
            return str(p)
        if p.parent == p:
            return None
        p = p.parent


@lru_cache(maxsize=None)
def repo_for(cwd: str) -> str:
    """Attribute a session cwd to a repo name.

    Prefers the on-disk git root (submodules included — their .git file wins
    over the monorepo root). Falls back to path heuristics for directories
    that no longer exist.
    """
    cwd = _normalize_cwd(cwd)
    root = _git_root(cwd)
    if root:
        return "bamr87" if root == str(REPO_ROOT) else (Path(root).name or "unknown")

    home = str(Path.home())
    mono = str(REPO_ROOT)
    if cwd == mono:
        return "bamr87"
    if cwd.startswith(mono + "/"):
        rel = cwd[len(mono) + 1:].split("/")
        return rel[1] if rel[0] == "projects" and len(rel) > 1 else "bamr87"
    for base in (home + "/github/", home + "/"):
        if cwd.startswith(base):
            return cwd[len(base):].split("/")[0]
    return Path(cwd).name or "unknown"


def load_registry_index() -> dict[str, dict]:
    """name/slug (lowercased) -> registry entry, for tagging repos as registered."""
    try:
        with REGISTRY.open() as fh:
            reg = yaml.safe_load(fh) or []
    except OSError:
        return {}
    index: dict[str, dict] = {}
    for p in reg:
        for key in (p.get("name"), p.get("slug")):
            if key:
                index[str(key).lower()] = p
    return index


# --------------------------------------------------------------------------- #
# scan: JSONL -> per-(machine, day, repo, model) aggregates
# --------------------------------------------------------------------------- #
def _local_date(ts: str) -> str | None:
    try:
        return (
            dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            .astimezone()
            .date()
            .isoformat()
        )
    except (ValueError, AttributeError):
        return None


def scan(projects_dir: Path, machine: str) -> tuple[dict, dict, set[str]]:
    """Stream every session file once.

    Returns (usage, sessions, models_seen):
      usage:    "machine|date|repo|model" -> {input, output, cache_5m, cache_1h,
                cache_read, turns}
      sessions: "machine|date|repo" -> set of session ids active that day
    """
    usage: dict[str, dict[str, int]] = {}
    sessions: dict[str, set[str]] = {}
    models_seen: set[str] = set()
    seen_msgs: set[str] = set()
    # rglob: subagent sidechains live nested under <session-id>/subagents/*.jsonl
    files = sorted(projects_dir.rglob("*.jsonl"))
    sys.stderr.write(f"  scanning {len(files)} session files in {projects_dir} …\n")

    for path in files:
        file_cwd: str | None = None
        try:
            fh = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                # cheap pre-filter; exact checks happen after parsing
                if '"assistant"' not in line or '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # truncated write mid-line; ignore
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message") or {}
                u = msg.get("usage")
                model = normalize_model(msg.get("model"))
                if not u or not model:
                    continue

                # streamed responses emit several records per API message
                key_id = msg.get("id") or rec.get("uuid")
                dedupe = f"{key_id}:{rec.get('requestId')}"
                if key_id and dedupe in seen_msgs:
                    continue
                seen_msgs.add(dedupe)

                date = _local_date(rec.get("timestamp", ""))
                if not date:
                    continue
                cwd = rec.get("cwd") or file_cwd
                if not cwd:
                    continue
                file_cwd = file_cwd or cwd
                repo = repo_for(cwd).replace("|", "-")
                models_seen.add(model)

                cache_total = u.get("cache_creation_input_tokens") or 0
                breakdown = u.get("cache_creation") or {}
                c5m = breakdown.get("ephemeral_5m_input_tokens")
                c1h = breakdown.get("ephemeral_1h_input_tokens")
                if c5m is None and c1h is None:
                    c5m, c1h = cache_total, 0  # old records: assume 5m TTL

                row = usage.setdefault(
                    f"{machine}|{date}|{repo}|{model}",
                    dict.fromkeys(USAGE_FIELDS, 0),
                )
                row["input"] += u.get("input_tokens") or 0
                row["output"] += u.get("output_tokens") or 0
                row["cache_5m"] += c5m or 0
                row["cache_1h"] += c1h or 0
                row["cache_read"] += u.get("cache_read_input_tokens") or 0
                row["turns"] += 1

                sid = rec.get("sessionId") or path.stem
                sessions.setdefault(f"{machine}|{date}|{repo}", set()).add(sid)

    return usage, sessions, models_seen


# --------------------------------------------------------------------------- #
# ledger: persistence across Claude Code's transcript cleanup
# --------------------------------------------------------------------------- #
def load_ledger(ledger_path: Path) -> dict:
    """Read the ledger, tolerating absence, corruption, and a missing `runs`.

    `runs` defaults rather than being required, so a v1 ledger written before
    the headless wrapper existed keeps all of its history — see LEDGER_VERSION.
    """
    ledger = {"version": LEDGER_VERSION, "usage": {}, "sessions": {}, "runs": {}}
    try:
        with ledger_path.open() as fh:
            prior = json.load(fh)
        if isinstance(prior, dict) and prior.get("version") == LEDGER_VERSION:
            ledger["usage"] = prior.get("usage", {})
            ledger["sessions"] = prior.get("sessions", {})
            ledger["runs"] = prior.get("runs", {})
    except (OSError, json.JSONDecodeError):
        pass
    return ledger


@contextlib.contextmanager
def ledger_lock(ledger_path: Path, wait_s: float | None = None) -> Iterator[None]:
    """An exclusive flock beside the ledger for one read-modify-write.

    Three writers rewrite the WHOLE file — `dash ai` (merge_ledger), the
    ai-usage collector (which calls merge_ledger) and every `dash ai run`
    (record_run) — and a loop runs several of the last at once. Without the
    lock, two of them loading the same version means one's rows are silently
    gone. One machine only: rows carry `machine` for the rest.

    With `wait_s`, LedgerBusy once the lock has been held elsewhere that long;
    without, it waits as long as it takes.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock = ledger_path.with_name(ledger_path.name + ".lock")
    with lock.open("a") as fh:
        if wait_s is None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + wait_s
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LedgerBusy(f"another writer held {lock} for {wait_s:g}s") from None
                    time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def save_ledger(ledger_path: Path, ledger: dict) -> None:
    """Stamp and write the ledger atomically."""
    ledger["updated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_name(f"{ledger_path.name}.{os.getpid()}.tmp")
    with tmp.open("w") as fh:
        json.dump(ledger, fh, separators=(",", ":"))
    tmp.replace(ledger_path)


def merge_ledger(ledger_path: Path, usage: dict, sessions: dict) -> dict:
    """Max-merge scan results into the ledger file; return the merged ledger.

    A day's tokens only grow while its transcripts exist and only shrink when
    Claude Code prunes them — so per-key max preserves the true daily total.
    """
    with ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)

        for key, row in usage.items():
            old = ledger["usage"].setdefault(key, dict.fromkeys(USAGE_FIELDS, 0))
            for f in USAGE_FIELDS:
                old[f] = max(old.get(f, 0), row[f])
        for key, ids in sessions.items():
            ledger["sessions"][key] = sorted(set(ledger["sessions"].get(key, [])) | ids)

        save_ledger(ledger_path, ledger)
    return ledger


def record_run(ledger_path: Path, record: dict, wait_s: float | None = None) -> dict:
    """Merge ONE headless run record into the ledger's `runs` section.

    Keyed by `session_id`, so re-running the wrapper against the same session
    (`--resume`) updates that record rather than appending a second one: the
    CLI's `total_cost_usd` is cumulative for the session, and two rows would be
    two charges for one conversation. A run the CLI gave no session id for
    falls back to a timestamp key — still one row, just not deduplicable.
    `wait_s` bounds the wait for the lock (ledger_lock).
    """
    key = record.get("session_id") or f"unknown-{record['timestamp']}"
    with ledger_lock(ledger_path, wait_s):
        ledger = load_ledger(ledger_path)
        ledger["runs"][key] = {f: record.get(f) for f in RUN_FIELDS}
        save_ledger(ledger_path, ledger)
    return ledger


# --------------------------------------------------------------------------- #
# report: ledger -> _data/ai_activity.yml
# --------------------------------------------------------------------------- #
def cost_usd(model: str, row: dict) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    return (
        row["input"] * p["in"]
        + row["output"] * p["out"]
        + row["cache_5m"] * p["in"] * CACHE_5M_MULT
        + row["cache_1h"] * p["in"] * CACHE_1H_MULT
        + row["cache_read"] * p["in"] * CACHE_READ_MULT
    ) / 1_000_000


def _headless_section(ledger: dict, window_start: str) -> dict:
    """The `dash ai run` table, kept SEPARATE from the scan-derived estimates.

    A row is BILLED only when the CLI reported its own `total_cost_usd` (a
    reported cost, not a shadow price off the PRICING table). A run that left
    no result is charged at its cap as `estimated`, and those dollars are
    reported apart — summed into `billed_cost_usd` an $8 guess would read as
    spend the CLI measured, which is HUB-032's failure again. The two accountings deliberately
    overlap: a headless run leaves a transcript that `scan()` also reads. That
    is precisely why they are never summed, and why each row carries
    `also_in_scan` so a reader can see which sessions are counted twice if they
    try. Acceptance criterion: "never blended into interactive-session
    estimates."
    """
    scanned: set[str] = set()
    for ids in (ledger.get("sessions") or {}).values():
        scanned.update(ids)

    rows = []
    for key, rec in (ledger.get("runs") or {}).items():
        sid = rec.get("session_id") or key
        ts = str(rec.get("timestamp") or "")
        usage = rec.get("usage") or {}
        cost = round(float(rec.get("total_cost_usd") or 0.0), 4)
        source = rec.get("cost_source")
        billed = source in BILLED_SOURCES
        rows.append({
            "session_id": sid,
            "timestamp": ts,
            "machine": rec.get("machine"),
            "repo": rec.get("repo"),
            "models": rec.get("models") or [],
            "billed_cost_usd": cost if billed else 0.0,
            "estimated_cost_usd": cost if source == "estimated" else 0.0,
            "cost_source": source or "reported",
            "outcome": rec.get("outcome"),
            "call_site": rec.get("call_site"),
            "origin": rec.get("origin"),
            "turns": usage.get("turns", 0),
            "tokens": {
                "input": usage.get("input", 0),
                "output": usage.get("output", 0),
                "cache_write": usage.get("cache_write", 0),
                "cache_read": usage.get("cache_read", 0),
            },
            "source": rec.get("source") or "dash ai run",
            "also_in_scan": sid in scanned,
        })
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    in_window = [r for r in rows if r["timestamp"][:10] >= window_start]

    return {
        "note": (
            "Billed cost as reported by `claude -p` itself, not a shadow price; "
            "runs that left no result are charged at their cap and shown as "
            "estimated_cost_usd, never as billed. Under subscription auth both "
            "are API-equivalent (estimate), not an invoice. Headless runs also "
            "leave a transcript the scan above reads, so these totals are NOT "
            "additive with the estimates — they are the same spend, measured two ways."
        ),
        "count": len(rows),
        "billed_cost_usd": round(sum(r["billed_cost_usd"] for r in rows), 2),
        "window_billed_cost_usd": round(sum(r["billed_cost_usd"] for r in in_window), 2),
        "estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in rows), 2),
        "window_estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in in_window), 2),
        "runs": rows[:50],
    }


def _bucket() -> dict:
    return {
        "cost": 0.0, "window_cost": 0.0, "input": 0, "output": 0,
        "cache_write": 0, "cache_read": 0, "turns": 0,
        "first": None, "last": None,
    }


def _cache_ratio_pct(b: dict) -> int:
    prompt = b["input"] + b["cache_write"] + b["cache_read"]
    return round(100 * b["cache_read"] / prompt) if prompt else 0


def build_report(ledger: dict, machine: str, window_days: int) -> dict:
    registry = load_registry_index()
    today = dt.date.today()
    window_start = (today - dt.timedelta(days=window_days - 1)).isoformat()

    totals = _bucket()
    repos: dict[str, dict] = {}
    models: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    unpriced: set[str] = set()
    active_days: set[str] = set()

    for key, row in ledger["usage"].items():
        _machine, date, repo, model = key.split("|", 3)
        c = cost_usd(model, row)
        if model not in PRICING:
            unpriced.add(model)
        in_window = date >= window_start
        active_days.add(date)

        for bucket in (
            totals,
            repos.setdefault(repo, _bucket()),
            models.setdefault(model, _bucket()),
        ):
            bucket["cost"] += c
            bucket["input"] += row["input"]
            bucket["output"] += row["output"]
            bucket["cache_write"] += row["cache_5m"] + row["cache_1h"]
            bucket["cache_read"] += row["cache_read"]
            bucket["turns"] += row["turns"]
            bucket["first"] = min(bucket["first"] or date, date)
            bucket["last"] = max(bucket["last"] or date, date)
            if in_window:
                bucket["window_cost"] += c

        repos[repo].setdefault("model_cost", {})
        repos[repo]["model_cost"][model] = repos[repo]["model_cost"].get(model, 0.0) + c
        if in_window:
            day = by_day.setdefault(date, {"cost": 0.0, "turns": 0, "output": 0})
            day["cost"] += c
            day["turns"] += row["turns"]
            day["output"] += row["output"]

    repo_sessions: dict[str, set[str]] = {}
    repo_window_sessions: dict[str, set[str]] = {}
    total_sessions: set[str] = set()
    for key, ids in ledger["sessions"].items():
        _machine, date, repo = key.split("|", 2)
        repo_sessions.setdefault(repo, set()).update(ids)
        total_sessions.update(ids)
        if date >= window_start:
            repo_window_sessions.setdefault(repo, set()).update(ids)

    def repo_entry(name: str, b: dict) -> dict:
        reg = registry.get(name.lower())
        top_model = max(b["model_cost"], key=b["model_cost"].get) if b.get("model_cost") else None
        return {
            "name": name,
            "registered": bool(reg) or name == "bamr87",
            "repo_url": (reg or {}).get("repo_url")
            or (f"https://github.com/bamr87/{name}" if name == "bamr87" else None),
            "est_cost_usd": round(b["cost"], 2),
            "window_est_cost_usd": round(b["window_cost"], 2),
            "sessions": len(repo_sessions.get(name, ())),
            "window_sessions": len(repo_window_sessions.get(name, ())),
            "turns": b["turns"],
            "tokens": {
                "input": b["input"], "output": b["output"],
                "cache_write": b["cache_write"], "cache_read": b["cache_read"],
            },
            "cache_read_ratio_pct": _cache_ratio_pct(b),
            "top_model": top_model,
            "last_activity": b["last"],
        }

    last14 = [(today - dt.timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    return {
        "generated_at": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "machine": machine,
        "window_days": window_days,
        "pricing_note": (
            "Estimated USD at Anthropic API list prices (cache writes 1.25x/2x input, "
            "cache reads 0.1x). Subscription usage bills nothing per token — this is "
            "shadow accounting, not an invoice."
        ),
        "unpriced_models": sorted(unpriced),
        "totals": {
            "est_cost_usd": round(totals["cost"], 2),
            "window_est_cost_usd": round(totals["window_cost"], 2),
            "tokens": {
                "input": totals["input"], "output": totals["output"],
                "cache_write": totals["cache_write"], "cache_read": totals["cache_read"],
            },
            "cache_read_ratio_pct": _cache_ratio_pct(totals),
            "turns": totals["turns"],
            "sessions": len(total_sessions),
            "repos": len(repos),
            "active_days": len(active_days),
            "first_activity": totals["first"],
            "last_activity": totals["last"],
        },
        "by_day": [
            {
                "date": d,
                "est_cost_usd": round(by_day.get(d, {}).get("cost", 0.0), 2),
                "turns": by_day.get(d, {}).get("turns", 0),
                "output_tokens": by_day.get(d, {}).get("output", 0),
            }
            for d in last14
        ],
        "headless": _headless_section(ledger, window_start),
        "repos": sorted(
            (repo_entry(n, b) for n, b in repos.items()),
            key=lambda r: (-r["window_est_cost_usd"], -r["est_cost_usd"]),
        ),
        "models": sorted(
            (
                {
                    "model": m,
                    "est_cost_usd": round(b["cost"], 2),
                    "window_est_cost_usd": round(b["window_cost"], 2),
                    "turns": b["turns"],
                    "tokens": {
                        "input": b["input"], "output": b["output"],
                        "cache_write": b["cache_write"], "cache_read": b["cache_read"],
                    },
                }
                for m, b in models.items()
            ),
            key=lambda r: -r["est_cost_usd"],
        ),
    }


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    claude_dir = Path(
        args.claude_dir or os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")
    ).expanduser()
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        sys.stderr.write(f"no Claude Code session data at {projects_dir}\n")
        return 1

    machine = platform.node().split(".")[0] or "local"
    usage, sessions, models_seen = scan(projects_dir, machine)
    ledger = merge_ledger(Path(args.ledger), usage, sessions)
    report = build_report(ledger, machine, args.window)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("# GENERATED by .github/scripts/dash-gen ai — do not edit or commit.\n")
        yaml.safe_dump(report, fh, sort_keys=False, allow_unicode=True)

    t = report["totals"]
    sys.stderr.write(
        f"Wrote {out}\n"
        f"  {t['repos']} repos · {t['sessions']} sessions · {t['turns']} turns "
        f"({', '.join(sorted(models_seen)) or 'no models'})\n"
        f"  est. API cost: ${t['est_cost_usd']:,.2f} all-time · "
        f"${t['window_est_cost_usd']:,.2f} last {args.window}d · "
        f"cache-read ratio {t['cache_read_ratio_pct']}%\n"
    )
    for r in report["repos"][:8]:
        sys.stderr.write(
            f"  {r['name']:<24} ${r['window_est_cost_usd']:>9,.2f} /{args.window}d   "
            f"${r['est_cost_usd']:>10,.2f} total   {r['window_sessions']:>3} sessions\n"
        )
    if report["unpriced_models"]:
        sys.stderr.write(
            f"  ! unpriced models (counted, $0): {', '.join(report['unpriced_models'])}\n"
        )
    return 0


# --------------------------------------------------------------------------- #
# `dash ai run` — the capped headless wrapper
# --------------------------------------------------------------------------- #
def load_local_budget() -> float:
    """The dollar ceiling for a local headless run, from _data/fleet.yml.

    `budget.local_usd`, falling back to `budget.default_usd`, falling back to
    BUDGET_FALLBACK_USD — the wrapper has to stay usable from a checkout with
    no registry, and a missing config must not mean "no cap at all".
    """
    try:
        with FLEET.open() as fh:
            fleet = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return BUDGET_FALLBACK_USD
    budget = fleet.get("budget") if isinstance(fleet, dict) else None
    if isinstance(budget, dict):
        for key in ("local_usd", "default_usd"):
            value = budget.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                return float(value)
    return BUDGET_FALLBACK_USD


# claude-code-action and the CLI have both spelled these fields more than one
# way. Read every spelling rather than guessing: a miss here is a silent zero
# in the ledger, which reads exactly like a free run.
_TOKEN_KEYS = {
    "input": ("inputTokens", "input_tokens", "input"),
    "output": ("outputTokens", "output_tokens", "output"),
    "cache_write": (
        "cacheCreationInputTokens", "cache_creation_input_tokens", "cacheWriteTokens",
    ),
    "cache_read": (
        "cacheReadInputTokens", "cache_read_input_tokens", "cacheReadTokens",
    ),
}


def usage_from_result(result: dict) -> dict:
    """Token totals across every model in the result's `modelUsage`."""
    usage = dict.fromkeys(_TOKEN_KEYS, 0)
    model_usage = result.get("modelUsage")
    if isinstance(model_usage, dict):
        for per_model in model_usage.values():
            if not isinstance(per_model, dict):
                continue
            for field, keys in _TOKEN_KEYS.items():
                for key in keys:
                    value = per_model.get(key)
                    if isinstance(value, int):
                        usage[field] += value
                        break
    usage["turns"] = result.get("num_turns") or 0
    return usage


def models_from_result(result: dict) -> list[str]:
    model_usage = result.get("modelUsage")
    if not isinstance(model_usage, dict):
        return []
    return sorted({normalize_model(m) or m for m in model_usage})


def headless():
    """tools.jev.headless — the isolation, streaming and classification layer.

    Imported lazily with the hub root APPENDED to sys.path (the way
    repo_scout.step_spec() reaches tools.jev.spec), so this directory's own
    modules keep precedence and `dash ai`, which never runs claude, never
    imports it. The dependency points one way: tools/jev never imports dash-gen.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    return importlib.import_module("tools.jev.headless")


def load_fleet_config() -> dict:
    try:
        with FLEET.open() as fh:
            fleet = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return fleet if isinstance(fleet, dict) else {}


def call_site_cap(fleet: dict, call_site: str) -> float | None:
    """`budget.call_sites[<workflow file>:<job id>]` — the CI cap, for a local run of the same step."""
    sites = ((fleet.get("budget") or {}).get("call_sites") or {})
    value = sites.get(call_site) if isinstance(sites, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def allowed_model_ids(fleet: dict) -> set[str]:
    allowed = (fleet.get("ai_models") or {}).get("allowed")
    lists = allowed.values() if isinstance(allowed, dict) else [allowed or []]
    return {str(m) for ids in lists for m in (ids or [])}


# Passed through to claude, these would undo what the wrapper is for: its cap,
# the output format its parser reads, or the permission system.
_OFF_MACHINE = ("a cloud session runs off this machine, outside the wrapper's isolation, and one it attaches "
                "to enforces no --max-budget-usd or --max-turns from this invocation")
REFUSED_PASSTHROUGH = {
    "--max-budget-usd": "the cap is this wrapper's job — set it with `dash ai run --max-budget-usd` "
                        "or `--call-site`",
    "--output-format": "the wrapper chooses the output format it parses (`--stream` for stream-json)",
    "-p": "the wrapper already runs claude in print mode",
    "--print": "the wrapper already runs claude in print mode",
    "--dangerously-skip-permissions": "a capped run never bypasses the permission system",
    "--allow-dangerously-skip-permissions": "a capped run never bypasses the permission system",
    "--cloud": _OFF_MACHINE,
    # the CLI's deprecated alias for --cloud
    "--remote": _OFF_MACHINE,
    "--teleport": _OFF_MACHINE,
}
#: Both name a permission mode: the second (hidden) one is used when nothing
#: else sets a mode, so it bypasses as surely as the first.
PERMISSION_MODE_FLAGS = ("--permission-mode", "--inherit-permission-mode")
SESSION_FLAGS = ("--session-id", "--resume", "-r", "--continue", "-c")
#: § 10.7: every AI dollar figure the wrapper prints carries this.
COST_LABEL = "API-equivalent (estimate)"


def _flag_values(args: list[str], names: tuple[str, ...]) -> list[str]:
    """Every value of a flag, in order (`--flag value` and `--flag=value`)."""
    out = []
    for i, a in enumerate(args):
        name, eq, value = a.partition("=")
        if name in names:
            out.append(value if eq else (args[i + 1] if i + 1 < len(args) else ""))
    return out


def _flag_value(args: list[str], names: tuple[str, ...]) -> str | None:
    """The value the CLI uses: the LAST occurrence, as its option parser keeps."""
    values = _flag_values(args, names)
    return values[-1] if values else None


def _json_value(value: str, cwd: Path) -> object:
    """A JSON flag value: inline, or a file — a relative path read from `cwd`,
    the directory claude resolves it in. ValueError when it is neither: the
    guard never vouches for a document it could not read."""
    text = value
    if not value.lstrip().startswith(("{", "[")):
        path = Path(value).expanduser()
        try:
            text = (path if path.is_absolute() else cwd / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read {value!r} from {cwd}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{value!r} is not JSON: {exc}") from exc


def _document_modes(flag: str, value: str, cwd: Path) -> list[str]:
    """The permission modes a `--settings` (`permissions.defaultMode`) or an
    `--agents` (each agent's `permissionMode`) value sets."""
    doc = _json_value(value, cwd)
    if flag == "--settings":
        perms = doc.get("permissions") if isinstance(doc, dict) else None
        found = [perms.get("defaultMode")] if isinstance(perms, dict) else []
    else:
        found = [a.get("permissionMode") for a in (doc.values() if isinstance(doc, dict) else [])
                 if isinstance(a, dict)]
    return [str(m) for m in found if m]


def refused_passthrough(passthrough: list[str], cwd: Path | None = None) -> str | None:
    """Why the passthrough may not run, or None.

    Flags only. Every run, `--isolate`d or not, still loads the user's and the
    project's settings files (`--isolate` builds the environment, not the
    settings sources; only a passthrough carrying `--restricted`, as JEV's
    headless.claude_flags does, ignores them), and those files — or an
    `--agent` defined in them — can set a permission mode this cannot see. A
    `--settings` or `--agents` value is read the way claude reads it, a
    relative path from `cwd`, and one that cannot be read is refused.
    """
    cwd = Path.cwd() if cwd is None else cwd
    for a in passthrough:
        name = a.partition("=")[0]
        if name in REFUSED_PASSTHROUGH:
            return f"{name} passed through to claude: {REFUSED_PASSTHROUGH[name]}"
    for flag in PERMISSION_MODE_FLAGS:
        if "bypassPermissions" in _flag_values(passthrough, (flag,)):
            return f"{flag} bypassPermissions passed through: a capped run never bypasses permissions"
    for flag in ("--settings", "--agents"):
        for value in _flag_values(passthrough, (flag,)):
            try:
                modes = _document_modes(flag, value, cwd)
            except ValueError as exc:
                return f"{flag}: {exc} — a document the wrapper cannot read could bypass permissions"
            if "bypassPermissions" in modes:
                return f"{flag} sets permission mode bypassPermissions: a capped run never bypasses permissions"
    return None


def parse_meta(items: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or key not in META_FIELDS or key in meta:
            raise ValueError(f"--meta {item!r}: KEY=VALUE once per key, KEY one of {', '.join(META_FIELDS)}")
        if key == "origin" and value != "local":
            # budget.loops counts `origin: local` rows: a row this wrapper
            # wrote is local whatever the caller says (P4 adds `ci` elsewhere)
            raise ValueError(f"--meta {item!r}: every row this wrapper writes is origin local")
        meta[key] = value
    return meta


def run_headless(args: argparse.Namespace) -> int:
    """Run `claude -p` under a dollar cap and record what it cost.

    The cap is the point: `--max-turns` bounds iterations, not spend, so a
    local script looping over repos has had no ceiling at all. Everything else
    here is bookkeeping around it — and, for JEV's local loop runner, the
    isolation, streaming and wall clock tools/jev/headless.py supplies.
    """
    # Whatever an earlier invocation left at these paths is never read as this
    # one's: every exit below either writes them afresh or leaves none.
    for stale in (args.result_file, args.outcome_file):
        if stale:
            Path(stale).unlink(missing_ok=True)
    fleet = load_fleet_config()
    if args.call_site:
        site_cap = call_site_cap(fleet, args.call_site)
        if site_cap is None:
            sys.stderr.write(f"_data/fleet.yml budget.call_sites has no positive cap for {args.call_site!r}\n")
            return 2
        if args.max_budget_usd is not None and args.max_budget_usd > site_cap:
            sys.stderr.write(
                f"refusing to run: --max-budget-usd {args.max_budget_usd:g} is above the "
                f"{args.call_site} cap ${site_cap:g} {COST_LABEL} — a call-site cap may only be lowered.\n")
            return 2
        budget = args.max_budget_usd if args.max_budget_usd is not None else site_cap
    else:
        budget = args.max_budget_usd if args.max_budget_usd is not None else load_local_budget()
    if budget <= 0:
        sys.stderr.write("--max-budget-usd must be greater than 0\n")
        return 2
    if args.ledger_wait <= 0:
        sys.stderr.write("--ledger-wait must be greater than 0\n")
        return 2
    if args.isolate_tmp and not args.isolate:
        sys.stderr.write("--isolate-tmp only means something with --isolate\n")
        return 2
    try:
        meta = parse_meta(args.meta)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    passthrough = list(args.claude_args or [])
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    # resolved first: a relative --settings or --agents path is claude's,
    # read from the directory claude runs in
    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd()
    if not cwd.is_dir():
        sys.stderr.write(f"--cwd {cwd} is not a directory\n")
        return 2
    refused = refused_passthrough(passthrough, cwd)
    if refused:
        sys.stderr.write(f"refusing to run: {refused}.\n")
        return 2

    hl = headless()
    claude = shutil.which(args.claude_bin)
    if not claude:
        sys.stderr.write(
            f"{args.claude_bin} not found on PATH — install Claude Code first "
            "(npm install -g @anthropic-ai/claude-code)\n"
        )
        missing = hl.Outcome("cli_missing", 0.0, "no-spend").as_dict()
        hl.write_json(args.outcome_file, {**missing, "cap_usd": budget, "exit_code": 127})
        return 127

    prompt = None
    if args.prompt_file:
        try:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write(f"--prompt-file: {exc}\n")
            return 2

    # A session id the wrapper chose is the row's key even when no result ever
    # arrives — which is exactly the run whose cost most needs a row.
    session_id = _flag_value(passthrough, ("--session-id",))
    added_session = []
    if _flag_value(passthrough, SESSION_FLAGS) is None:
        session_id = str(uuid.uuid4())
        added_session = ["--session-id", session_id]

    choice = None
    extra_secrets: dict[str, str] = {}
    env = None
    made_tmp = None
    if args.isolate or args.auth_order:
        try:
            order = (hl.auth_order({}, {"CLAUDE_AUTH_ORDER": args.auth_order}) if args.auth_order
                     else hl.auth_order(fleet, os.environ))
            dotenv = hl.hub_dotenv()
            choice = hl.choose_auth(order, os.environ, dotenv, lambda: hl.stored_login(claude, os.environ))
        except hl.NoCredential as exc:
            sys.stderr.write(f"refusing to run: {exc}\n")
            refused = hl.Outcome("credential_rejected", 0.0, "no-spend", detail=str(exc)).as_dict()
            hl.write_json(args.outcome_file, {**refused, "cap_usd": budget, "exit_code": 3})
            return 3
        except hl.JevError as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
        value = hl.credential_value(choice, os.environ, dotenv)
        if value:
            extra_secrets[hl.CREDENTIAL_ENV[choice.method]] = value
        if args.isolate:
            tmp = Path(args.isolate_tmp).expanduser() if args.isolate_tmp else None
            if tmp is None:
                tmp = made_tmp = Path(tempfile.mkdtemp(prefix="jev-ai-run-"))
            tmp.mkdir(parents=True, exist_ok=True)
            gh_none = tmp / "gh-none"
            gh_none.mkdir(exist_ok=True)
            env = hl.agent_env(os.environ, choice, credential_value=value, tmp=tmp, gh_config_dir=gh_none,
                               hub=REPO_ROOT)
        else:
            env = hl.with_one_credential(os.environ, choice, value)
    redactor = hl.Redactor(os.environ, extra_secrets)

    cmd = [claude, *hl.run_prefix(budget, stream=args.stream), *added_session, *passthrough]
    sys.stderr.write(f"  $ {redactor.text(' '.join(cmd))}\n  cap: ${budget:,.2f}"
                     f"{f' ({args.call_site})' if args.call_site else ''} {COST_LABEL}\n")
    if choice is not None:
        sys.stderr.write(f"  auth: {choice}{' · isolated environment' if args.isolate else ''}\n")
    if args.dry_run:
        if made_tmp is not None:
            shutil.rmtree(made_tmp, ignore_errors=True)
        return 0

    # Read BEFORE the run: once claude has reported its cost, nothing may start
    # another process ahead of the ledger row.
    cli_ver = hl.version_str(hl.cli_version(claude))
    signals: list[str] = []
    # Held from here until the row and the files are written: a signal before
    # claude starts cancels it, one while it runs starts stream's ladder, and
    # one after it exits waits for the bookkeeping.
    with hl.held_signals(signals):
        try:
            inv = hl.stream(cmd, prompt=prompt, cwd=cwd, env=env,
                            trace=hl.Trace(Path(args.trace) if args.trace else None, redactor),
                            timeout_s=args.timeout, redactor=redactor, cap_usd=budget,
                            echo=sys.stderr if args.stream else None,
                            fmt="stream-json" if args.stream else "json", received=signals)
        finally:
            if made_tmp is not None:
                shutil.rmtree(made_tmp, ignore_errors=True)
        # the ones claude was still running for; stream's own tidying and the
        # rmtree above happen after it exited, so a signal there is late
        during = inv.signals_seen
        code = _settle(args, hl, inv, budget=budget, redactor=redactor, choice=choice, cwd=cwd, meta=meta,
                       passthrough=passthrough, session_id=session_id, cli_ver=cli_ver, fleet=fleet)
    late = signals[during:]
    if late:
        sys.stderr.write(f"! {late[0]} arrived after claude exited, while the run was being recorded; its "
                         f"record is complete, and ai-run exits as {late[0]} would.\n")
        return 128 + signal.Signals[late[0]].value
    return code


def _settle(args: argparse.Namespace, hl, inv, *, budget: float, redactor, choice, cwd: Path, meta: dict,
            passthrough: list[str], session_id: str | None, cli_ver: str | None, fleet: dict) -> int:
    """Classify one finished invocation, persist it, then say so; the exit code.

    Persisting comes FIRST: after a hangup a write to the dead terminal can
    raise, and the ledger row, the result file and the outcome file must not
    depend on it."""
    outcome = hl.classify(inv, budget, redactor)
    outcome.detail = redactor.text(outcome.detail)
    if not inv.started and outcome.kind == "interrupted":
        # cancelled before claude was started: no process ran, so no row
        hl.write_json(args.outcome_file, {**outcome.as_dict(), "cap_usd": budget, "exit_code": 130,
                                          "interrupted": inv.interrupted})
        sys.stderr.write(f"! INTERRUPTED ({inv.interrupted}) before claude was started; nothing ran and "
                         "nothing is recorded.\n")
        return 130
    if not inv.started:
        # found on PATH but it could not be started (say, a broken shebang):
        # no process ran, so — as when it is not found at all — no row
        hl.write_json(args.outcome_file, {**outcome.as_dict(), "cap_usd": budget, "exit_code": 127})
        sys.stderr.write(f"{args.claude_bin} could not be started: {outcome.detail}\n")
        return 127
    # A signal-killed claude has a negative return code; the shell's 128+N is
    # what this process can exit with, and what the outcome file records.
    rc = 128 - inv.rc if inv.rc < 0 else inv.rc
    result = inv.result
    models = models_from_result(result) if result else []
    record = {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": platform.node().split(".")[0] or "local",
        "repo": args.repo or repo_for(str(cwd)),
        "session_id": (result or {}).get("session_id") or outcome.session_id or session_id,
        "models": models,
        "usage": usage_from_result(result) if result else {**dict.fromkeys(_TOKEN_KEYS, 0), "turns": 0},
        "total_cost_usd": round(outcome.cost_usd, 6),
        "source": args.source,
        "call_site": args.call_site or "local",
        "origin": "local",
        **meta,
        # never guessed from modelUsage: its first key is often a helper model
        "model": (normalize_model((inv.init or {}).get("model"))
                  or normalize_model(_flag_value(passthrough, ("--model",)))),
        "outcome": outcome.kind,
        "cost_source": outcome.cost_source,
        "cap_usd": budget,
        "auth_method": choice.method if choice else None,
        "cli_version": cli_ver,
        "duration_s": inv.duration_s,
    }
    cost = record["total_cost_usd"]
    allowed = allowed_model_ids(fleet)
    flagged = [m for m in models if allowed and m not in allowed]

    kind = outcome.kind
    if kind == "budget_hit":
        # A budget abort is LOUD. It stops the agent mid-task, so a silent exit
        # 0 would hand back partial work as if it were finished.
        warning = (
            f"! BUDGET CAP HIT — ${cost:,.4f} against a ${budget:,.2f} ceiling ({COST_LABEL}). "
            "The run was stopped MID-TASK and its output is probably partial. "
            "Raise `budget.local_usd` (or the call site's `budget.call_sites` entry) "
            "in _data/fleet.yml or pass --max-budget-usd.\n"
        )
        code = rc or 2
    elif kind == "timeout":
        warning = (f"! TIMED OUT after {args.timeout:g}s — {outcome.detail}; charged "
                   f"${cost:,.4f} {COST_LABEL} ({outcome.cost_source}).\n")
        code = 124
    elif kind == "interrupted":
        # A cancel or Ctrl-C, not a verdict on the credential or the agent.
        warning = (f"! INTERRUPTED ({inv.interrupted}) — {outcome.detail}; charged "
                   f"${cost:,.4f} {COST_LABEL} ({outcome.cost_source}).\n")
        code = 130
    elif kind == "usage_limit":
        # Capacity, not a defect (AGENTS.md): the credential WORKED.
        warning = (
            f"! USAGE LIMIT — {outcome.detail}. The credential is VALID — do NOT rotate it. "
            "The subscription's window is spent; run again after the reset. Nothing falls back "
            "to the other credential (#348).\n")
        code = 0 if args.usage_limit == "skip" else (rc or 1)
    elif kind == "credential_rejected":
        if choice is None:
            fix = "or rotate CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY, whichever this run used"
        elif choice.source == "login":
            fix = "or log in again (`claude login`)"
        else:
            fix = f"or rotate {hl.CREDENTIAL_ENV[choice.method]}"
        warning = (
            f"! CREDENTIAL REJECTED — Claude was never reached ($0, empty modelUsage): {outcome.detail}. "
            f"{'Auth: ' + str(choice) + '. ' if choice else ''}Run `claude auth status`, {fix} "
            "(docs/TOKEN-ROTATION.md).\n")
        code = rc or 1
    elif result is None:
        warning = (
            f"! no result record in the CLI's output ({kind}) — recorded as {outcome.cost_source}"
            f"{f', charged at the ${budget:g} cap {COST_LABEL}' if outcome.cost_source == 'estimated' else ''}. "
            "The run is still whatever claude's exit code says it is.\n"
        )
        code = rc or 1
    else:
        warning = ""
        code = rc

    ledger_path = Path(args.ledger)
    ledger_error = ""
    try:
        record_run(ledger_path, record, wait_s=args.ledger_wait)
    except LedgerBusy as exc:
        # the session happened: keep its outcome file, say so loudly, and fail
        ledger_error = str(exc)
        code = code or 1
        warning += (f"! THIS RUN IS NOT LEDGERED — {exc}. Its cost is in the outcome file; "
                    "find the stopped or hung writer (`fuser` / `lsof` on the lock file).\n")
    if result is not None:
        # redacted like the trace; the cost and token numbers claude-cost's
        # `log:` reads are not strings, so they come through unchanged
        hl.write_json(args.result_file, redactor.obj(result))
    hl.write_json(args.outcome_file, {
        **outcome.as_dict(), "cap_usd": budget, "exit_code": code, "rc": rc,
        "timed_out": inv.timed_out, "interrupted": inv.interrupted, "duration_s": inv.duration_s,
        "auth": {"method": choice.method, "source": choice.source} if choice else None,
        "cli_version": cli_ver, "tool_uses": inv.tool_uses,
        "permission_denials": inv.permission_denials, "models_flagged": flagged,
        "ledger": str(ledger_path), "ledger_error": ledger_error or None, "call_site": record["call_site"],
    })

    if inv.stderr_tail:
        sys.stderr.write(inv.stderr_tail if inv.stderr_tail.endswith("\n") else inv.stderr_tail + "\n")
    # with no result record, what the CLI printed (redacted) is the only
    # diagnosis there is
    echoed = (redactor.text(str(result.get("result") or "")) if result is not None
              else (inv.stdout_text or inv.stdout_noise))
    if result is not None or echoed:
        sys.stdout.write(echoed if echoed.endswith("\n") else echoed + "\n")
    sys.stderr.write(
        f"  {record['repo']} · {record['usage']['turns']} turn(s) · "
        f"${cost:,.4f} of ${budget:,.2f} {COST_LABEL} "
        f"({(cost / budget * 100) if budget else 0:.0f}%, {outcome.cost_source}) · {outcome.kind} · "
        f"session {record['session_id'] or 'unknown'}\n"
        f"  {'NOT recorded to' if ledger_error else 'recorded to'} {ledger_path}\n"
    )
    if flagged:
        sys.stderr.write(f"! model(s) outside _data/fleet.yml ai_models.allowed in modelUsage: "
                         f"{', '.join(flagged)}\n")
    if warning:
        sys.stderr.write(warning)
    return code


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-budget-usd", type=float, default=None, metavar="USD",
                        help="dollar ceiling (default: budget.local_usd in _data/fleet.yml; with "
                             "--call-site it may only LOWER that site's cap)")
    parser.add_argument("--call-site", default=None, metavar="FILE:JOB",
                        help="take the cap from budget.call_sites[FILE:JOB], the CI cap of that step")
    parser.add_argument("--ledger", default=str(LEDGER_DEFAULT), metavar="PATH",
                        help=f"persistent ledger (default: {LEDGER_DEFAULT})")
    parser.add_argument("--ledger-wait", type=float, default=LEDGER_WAIT_S, metavar="SECONDS",
                        help=f"wait at most SECONDS for another ledger writer's lock (default: {LEDGER_WAIT_S:g}); "
                             "a cancel waits that long too, and past it the run is not ledgered (exit non-zero)")
    parser.add_argument("--source", default="dash ai run", metavar="LABEL",
                        help="how this run was invoked, recorded on the ledger entry")
    parser.add_argument("--repo", default=None, metavar="NWO",
                        help="the repo the run is attributed to (default: from the working directory)")
    parser.add_argument("--cwd", default=None, metavar="DIR", help="run claude in DIR")
    parser.add_argument("--prompt-file", default=None, metavar="PATH",
                        help="send PATH's contents as the prompt, on stdin (never in argv)")
    parser.add_argument("--stream", action="store_true",
                        help="stream-json with a condensed live tee to stderr")
    parser.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                        help="wall clock: SIGINT (the turn ends, a result is still reported), "
                             "then SIGTERM, then SIGKILL; exit 124")
    parser.add_argument("--trace", default=None, metavar="PATH",
                        help="write a redacted, size-capped JSONL trace of the session")
    parser.add_argument("--result-file", default=None, metavar="PATH",
                        help="write the last result record as one JSON object (claude-cost `log:` reads it)")
    parser.add_argument("--outcome-file", default=None, metavar="PATH",
                        help="write the classified outcome (kind, cost, cost_source, exit code) as JSON")
    parser.add_argument("--isolate", action="store_true",
                        help="build claude's environment from scratch: no GitHub token, no SSH agent, "
                             "one Claude credential (tools/jev/headless.py agent_env)")
    parser.add_argument("--isolate-tmp", default=None, metavar="DIR",
                        help="TMPDIR for the isolated environment (default: a fresh temporary directory)")
    parser.add_argument("--auth-order", default=None, metavar="LIST",
                        help="credential order, e.g. oauth,api_key; the first PRESENT one is used, and the "
                             "other one and the CLI's other auth inputs (ANTHROPIC_AUTH_TOKEN, "
                             "ANTHROPIC_BASE_URL, CLAUDE_CONFIG_DIR, the provider switches) are unset "
                             "(default with --isolate: CLAUDE_AUTH_ORDER / ai_auth)")
    parser.add_argument("--usage-limit", choices=("fail", "skip"), default="fail",
                        help="skip = a spent usage window exits 0 with a warning (capacity, not a defect)")
    parser.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                        help=f"record KEY on the ledger row ({', '.join(META_FIELDS)}); repeatable")
    parser.add_argument("--claude-bin", default="claude", metavar="BIN",
                        help="Claude Code executable (default: claude)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the command and the cap, run nothing")
    parser.add_argument("claude_args", nargs=argparse.REMAINDER, metavar="-- ARGS",
                        help="everything after `--` is passed to `claude -p`")
    parser.set_defaults(func=run_headless)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--window", type=int, default=30, metavar="DAYS",
                        help="recent window for the report (default: 30)")
    parser.add_argument("--ledger", default=str(LEDGER_DEFAULT), metavar="PATH",
                        help=f"persistent ledger (default: {LEDGER_DEFAULT})")
    parser.add_argument("--claude-dir", default=None, metavar="PATH",
                        help="Claude config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    parser.add_argument("--out", default=str(OUT_DEFAULT), metavar="PATH",
                        help=f"report output (default: {OUT_DEFAULT})")
    parser.set_defaults(func=run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai_activity", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

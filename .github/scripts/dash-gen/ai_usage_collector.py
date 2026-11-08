#!/usr/bin/env python3
"""
ai_usage_collector — the COMMITTED Claude Code usage ledger across the fleet
(the dash's AI-transparency layer; see docs/AI-INTEGRATION.md → "Usage dashboard").

Where ai_activity.py shadow-prices LOCAL sessions and stays gitignored, this
module builds the publishable picture: every Claude Code touchpoint the fleet
leaves in public infrastructure, aggregated into _data/ai_usage.yml for the
/ai-usage/ dash page. Three sources, all harvested without touching any
submodule repo:

  ci      workflow runs of any fleet workflow that invokes Claude (detected by
          reading the workflow file content once per distinct path with runs in
          the window: `anthropics/claude-code-action`, the hub's `claude-run`
          composite, or a vendored `scripts/ai/run.sh`). The HUB ITSELF is
          collected alongside the registry — `_data/fleet.yml` `hub.repo` is
          not a registry entry, and leaving it out hid the fleet's single
          largest spender (fleet-pulse's doctor, the issue pipeline's three
          tiers, the fan-outs) from every number on this page.

          Each run is PRICED in this order (`cost_source` on every ledger row):
            reported   the run's own `total_cost_usd`, summed across every
                       Claude session in the run and de-duplicated per
                       `session_id` (the CLI's figure is cumulative per
                       session, and GitHub's log zip carries each job's text
                       twice, so "sum every match" would double-charge and
                       "take the last match" — the prior behaviour — charged a
                       three-session run for one session);
            tokens     no cost in the payload, but a model id and a token
                       breakdown are: priced from the same API list-price table
                       `ai_activity.py` uses, cache WRITES at 1.25x/2x input and
                       cache READS at 0.1x;
            no-spend   the run cannot have spent anything — it was `skipped`
                       wholesale, or its log shows no Claude step ran at all
                       (the fleet's loops open with an "is the loop on?" gate
                       job, which is why 146 of 277 runs looked "unpriced" in
                       the 2026-10-29 snapshot: they were $0, not unknown);
            estimated  a Claude step ran (or the log is gone) and left no
                       usage: `est_cost_usd` carries an explicit estimate from
                       the workflow's own priced median, else the run's turns
                       at `budget.usd_per_turn`, else the fleet median. These
                       are the only runs counted as `unpriced_runs`.

          Totals report the three figures separately — `ci_cost_usd` (measured),
          `ci_estimated_usd` (the gap), `ci_accounted_usd` (the sum) — and the
          budget check reads the ACCOUNTED figure, because a ceiling judged on
          the measured half alone reads a fleet over budget as comfortably
          inside it.
  vcs     Claude-attributed version control: commits whose message carries a
          "Co-Authored-By: Claude" trailer, and PRs whose body carries the
          "Generated with [Claude Code]" marker, counted per repo in-window
          with sample provenance links.
  local   an optional locally-published section: when the machine's
          ai-activity ledger exists (never in CI), its windowed aggregate is
          folded in under `local`; when absent, any previously committed
          `local` block is PRESERVED verbatim so the daily CI refresh never
          erases a deliberate local publish. Publishing local spend remains an
          explicit opt-in (run `tools/dash-gen ai-usage` on your machine and
          commit) — CI alone never adds it. Interactive local spend is a
          DIFFERENT population from CI and is never folded into the CI totals
          or the CI ceiling (the /live page reads it from Prometheus).

Output: _data/ai_usage.yml — committed, refreshed daily by
.github/workflows/fleet-pulse.yml, rendered at /ai-usage/. Auditability comes
from the per-run ledger entries (run URLs, PR/commit links) rather than
aggregate claims.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import io
import json
import re
import statistics
import sys
import time
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("dash-gen requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import actions_analytics  # registry loading + owner_repo + gh auth conventions
import ai_activity  # the API list-price table + model-id normalization

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DEFAULT = REPO_ROOT / "_data" / "ai_usage.yml"
FLEET = REPO_ROOT / "_data" / "fleet.yml"

# A workflow FILE that calls Claude by any of the fleet's three routes. The
# first two are actions; the third is the ai-runner kit's vendored shell runner
# (lifehacker.dev, it-journey, zer0-mistakes), whose runs were invisible here.
CLAUDE_WORKFLOW_MARKERS = (
    "anthropics/claude-code-action",
    "anthropics/claude-code-base-action",
    "actions/claude-run",
    "scripts/ai/run.sh",
)
# A run LOG that shows a Claude step actually executed. Deliberately excludes
# the credential names: a gate job that only tests `CLAUDE_CODE_OAUTH_TOKEN`
# echoes its own script and never reaches the model.
CLAUDE_LOG_MARKERS = (
    "claude-code-action",
    "claude-run-result",
    "total_cost_usd",
    "claude_args",
    "claude -p",
)
# Lines worth parsing for usage (cheap pre-filter before the JSON decode).
USAGE_MARKERS = ('"total_cost_usd"', '"output_tokens"', '"outputTokens"')

COMMIT_TRAILER = re.compile(r"co-authored-by:.*claude", re.IGNORECASE)
PR_MARKER = "Generated with [Claude Code]"

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
# Field names the same quantity travels under: the CLI's result payload
# (snake_case), its `modelUsage` map (camelCase), and the raw API usage block.
TOKEN_ALIASES = {
    "input_tokens": ("input_tokens", "inputTokens"),
    "output_tokens": ("output_tokens", "outputTokens"),
    "cache_read_tokens": ("cache_read_input_tokens", "cacheReadInputTokens"),
    "cache_write_tokens": ("cache_creation_input_tokens", "cacheCreationInputTokens"),
}
# The last-resort regexes, for a result line the JSON decoder cannot read
# (ANSI escapes, a truncated log). Cost only — a partial token set would price
# a run too low, which is worse than pricing it as an estimate.
COST_RX = re.compile(r'"total_cost_usd"\s*:\s*([0-9.]+)')
TURNS_RX = re.compile(r'"num_turns"\s*:\s*([0-9]+)')
SESSION_RX = re.compile(r'"session_id"\s*:\s*"([^"]+)"')


# --------------------------------------------------------------------------- #
# pricing — reported cost first, the token rate table second
# --------------------------------------------------------------------------- #
def _int(value) -> int:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def _tokens_from(obj: dict) -> tuple[dict[str, int], int]:
    """(token counts, cache-write tokens at the 1h TTL) from any usage shape."""
    out = dict.fromkeys(TOKEN_KEYS, 0)
    for key, names in TOKEN_ALIASES.items():
        for name in names:
            if name in obj:
                out[key] = _int(obj[name])
                break
    # Newer payloads split cache writes by TTL under `cache_creation`; they are
    # priced differently (1.25x vs 2x input), so the split is kept.
    cache_1h = 0
    creation = obj.get("cache_creation")
    if isinstance(creation, dict):
        five = _int(creation.get("ephemeral_5m_input_tokens"))
        cache_1h = _int(creation.get("ephemeral_1h_input_tokens"))
        if five or cache_1h:
            out["cache_write_tokens"] = five + cache_1h
    return out, cache_1h


def _record_from(obj: dict) -> dict | None:
    """One usage record from a result payload, a `modelUsage` map, or a bare
    usage block. None when the object carries no usage at all."""
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    model_usage = obj.get("modelUsage") if isinstance(obj.get("modelUsage"), dict) else {}
    cost = obj.get("total_cost_usd")
    cost = float(cost) if isinstance(cost, (int, float)) else None
    if not usage and not model_usage and any(n in obj for ns in TOKEN_ALIASES.values() for n in ns):
        usage = obj
    if cost is None and not usage and not model_usage:
        return None

    tokens, cache_1h = _tokens_from(usage) if usage else (dict.fromkeys(TOKEN_KEYS, 0), 0)
    models: dict[str, dict] = {}
    for raw_id, mu in model_usage.items():
        if not isinstance(mu, dict):
            continue
        mid = ai_activity.normalize_model(str(raw_id))
        if not mid:
            continue
        mt, m1h = _tokens_from(mu)
        models[mid] = {"tokens": mt, "cache_1h": m1h}
    if not models:
        mid = ai_activity.normalize_model(obj.get("model") if isinstance(obj.get("model"), str) else None)
        if mid and any(tokens.values()):
            models[mid] = {"tokens": tokens, "cache_1h": cache_1h}
    if model_usage and not any(tokens.values()):
        for m in models.values():
            for k in TOKEN_KEYS:
                tokens[k] += m["tokens"][k]
            cache_1h += m["cache_1h"]

    session = obj.get("session_id") or obj.get("sessionId")
    return {
        "session": str(session) if isinstance(session, str) else None,
        "cost_usd": cost,
        "turns": _int(obj.get("num_turns")),
        "duration_ms": _int(obj.get("duration_ms")) or None,
        "tokens": tokens,
        "cache_1h": cache_1h,
        "models": models,
        "echo": False,
    }


# The Actions log prefix: the zip's `<timestamp> `, or `gh run view --log`'s
# `<job>\t<step>\t<timestamp> `. Stripped to see a pretty-printed block's
# braces at column 0.
LOG_PREFIX_RX = re.compile(r"^(?:[^\t\n]*\t[^\t\n]*\t)?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")
# claude-code-action prints the session id on its own line after the block.
SESSION_LINE_RX = re.compile(r"Set session_id:\s*([0-9a-fA-F-]{36})")
# claude-cost's echo of the agent step's result record (the reference parity
# compares the ledger against).
ECHO_MARKER = "claude-run-result"
BLOCK_MAX_LINES = 4000
SESSION_LOOKAHEAD = 6


def _strip_prefix(line: str) -> str:
    return LOG_PREFIX_RX.sub("", line, count=1)


def _block_at(lines: list[str], i: int) -> tuple[dict | None, int]:
    """A pretty-printed JSON object opening at line i — a bare `{`, indented
    keys, a bare `}` at column 0, as claude-code-action prints its `result`
    record. Returns (object, index of the closing line), or (None, i)."""
    for j in range(i + 1, min(len(lines), i + BLOCK_MAX_LINES)):
        if _strip_prefix(lines[j]).rstrip() == "}":
            try:
                obj = json.loads("\n".join(_strip_prefix(x) for x in lines[i:j + 1]))
            except ValueError:
                return None, i
            return (obj if isinstance(obj, dict) else None), j
    return None, i


def iter_usage_records(text: str):
    """Every Claude usage payload in one log file.

    Two shapes reach a log, and one Claude call usually prints BOTH:

    * a single line — the CLI's result payload, which the hub's
      `claude-cost` step echoes behind `claude-run-result` (records from it
      carry `echo: True`), or a full-output stream line;
    * claude-code-action's PRETTY block: a bare `{`, one key per line, a bare
      `}`, then `Set session_id: <uuid>` on its own line. It is decoded as a
      whole and given that session id, so it folds into the echo of the same
      call (see dedupe_records). Read line by line instead, its
      `"total_cost_usd": 6.42,` line used to yield a second, session-less
      record and the run was charged twice (issue-pipeline run 42352285943:
      $25.64 for three tiers whose result lines sum to $12.82).

    A line the decoder refuses still yields its cost through `COST_RX`, so a
    truncated log degrades to a reported cost rather than to an estimate.
    """
    decoder = json.JSONDecoder()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _strip_prefix(line).rstrip() == "{":
            obj, end = _block_at(lines, i)
            if obj is not None:
                rec = _record_from(obj)
                if rec:
                    if not rec["session"]:
                        for nxt in lines[end + 1:end + 1 + SESSION_LOOKAHEAD]:
                            sid = SESSION_LINE_RX.search(nxt)
                            if sid:
                                rec["session"] = sid.group(1)
                                break
                    yield rec
                i = end + 1
                continue
        i += 1
        if not any(m in line for m in USAGE_MARKERS):
            continue
        echo = ECHO_MARKER in line
        found = False
        idx = line.find("{")
        while idx != -1:
            try:
                obj, end = decoder.raw_decode(line, idx)
            except ValueError:
                idx = line.find("{", idx + 1)
                continue
            if isinstance(obj, dict):
                rec = _record_from(obj)
                if rec:
                    found = True
                    rec["echo"] = echo
                    yield rec
            idx = line.find("{", max(end, idx + 1))
        if not found:
            cost = COST_RX.search(line)
            if cost:
                session = SESSION_RX.search(line)
                turns = TURNS_RX.search(line)
                yield {
                    "session": session.group(1) if session else None,
                    "cost_usd": float(cost.group(1)),
                    "turns": int(turns.group(1)) if turns else 0,
                    "duration_ms": None,
                    "tokens": dict.fromkeys(TOKEN_KEYS, 0),
                    "cache_1h": 0,
                    "models": {},
                    "echo": echo,
                }


def _same_call(a: dict, b: dict) -> bool:
    """Are two records prints of the same Claude call?

    The rules of the lake's parser (bamr87/bamr87#771, `fleet_lake._same_call`):
    the same session decides; two different sessions rule it out; otherwise the
    same duration and turn count (claude-code-action's reduced block and
    claude-cost's echo of it); otherwise the identical payload (GitHub's zip
    holds each job's text twice, as step files and as the per-job roll-up).
    """
    if a["session"] and b["session"]:
        return a["session"] == b["session"]
    if a.get("duration_ms") and (a.get("duration_ms"), a["turns"]) == (b.get("duration_ms"), b["turns"]):
        return True
    if a["session"] or b["session"]:
        return False
    return (a["cost_usd"], a["turns"], tuple(sorted(a["tokens"].items()))) == \
        (b["cost_usd"], b["turns"], tuple(sorted(b["tokens"].items())))


def _merge(a: dict, b: dict) -> dict:
    """One record from two prints of the same call: the richest wins (the
    CLI's `total_cost_usd` is cumulative within a session), and keeps the
    other's session id and echo mark if it lacks them."""
    win, other = (b, a) if _rank(b) > _rank(a) else (a, b)
    out = dict(win)
    out["session"] = win["session"] or other["session"]
    out["duration_ms"] = win.get("duration_ms") or other.get("duration_ms")
    out["echo"] = bool(win.get("echo") or other.get("echo"))
    return out


def dedupe_records(records: list[dict]) -> list[dict]:
    """One record per Claude call.

    Raw matches are unsummable: GitHub's log zip holds each job's text twice
    (`<job>.txt` and `<job>/<step>.txt`), the CLI's `total_cost_usd` is
    CUMULATIVE within a session (a resumed session emits a growing figure),
    and on the hub's loops every call is printed twice more — the action's
    reduced block and claude-cost's echo. Records that `_same_call` pairs are
    folded with `_merge`; the rest are distinct calls and are summed.
    """
    merged: list[dict] = []
    for rec in records:
        for i, prior in enumerate(merged):
            if _same_call(prior, rec):
                merged[i] = _merge(prior, rec)
                break
        else:
            merged.append(rec)
    return merged


def _rank(rec: dict) -> tuple:
    return (rec["cost_usd"] if rec["cost_usd"] is not None else -1.0,
            sum(rec["tokens"].values()), rec["turns"])


def price_tokens(model: str, tokens: dict[str, int], cache_1h: int = 0) -> float | None:
    """Token cost at API list prices, or None for a model with no rate row."""
    if model not in ai_activity.PRICING:
        return None
    cache_5m = max(0, tokens.get("cache_write_tokens", 0) - cache_1h)
    return ai_activity.cost_usd(model, {
        "input": tokens.get("input_tokens", 0),
        "output": tokens.get("output_tokens", 0),
        "cache_5m": cache_5m,
        "cache_1h": cache_1h,
        "cache_read": tokens.get("cache_read_tokens", 0),
    })


def price_records(records: list[dict]) -> dict:
    """Sum one run's sessions into a priced usage dict (see `cost_source`)."""
    totals = dict.fromkeys(TOKEN_KEYS, 0)
    cost = 0.0
    turns = 0
    reported = token_priced = False
    unpriced_models: set[str] = set()
    # The parity reference: claude-cost's own result lines, one per session
    # (the largest — cumulative — figure), summed independently of the merge.
    echoes: dict[str, float] = {}
    for rec in records:
        if rec.get("echo") and rec["cost_usd"] is not None:
            key = rec["session"] or f"payload:{rec['cost_usd']}:{rec['turns']}"
            echoes[key] = max(echoes.get(key, 0.0), rec["cost_usd"])
    for rec in dedupe_records(records):
        turns += rec["turns"]
        for key in TOKEN_KEYS:
            totals[key] += rec["tokens"][key]
        if rec["cost_usd"] is not None:
            cost += rec["cost_usd"]
            reported = True
            continue
        priced = 0.0
        ok = bool(rec["models"])
        for mid, mu in rec["models"].items():
            usd = price_tokens(mid, mu["tokens"], mu["cache_1h"])
            if usd is None:
                unpriced_models.add(mid)
                ok = False
            else:
                priced += usd
        if ok:
            cost += priced
            token_priced = True
    source = "reported" if reported else ("tokens" if token_priced else None)
    return {
        "cost_usd": round(cost, 6) if source else None,
        "cost_source": source,
        "cost_basis": "result-json" if reported else ("token-rates" if token_priced else None),
        "turns": turns or None,
        "result_line_usd": round(sum(echoes.values()), 6) if echoes else None,
        "unpriced_models": sorted(unpriced_models),
        **totals,
    }


# --------------------------------------------------------------------------- #
# CI runs
# --------------------------------------------------------------------------- #
def _workflow_uses_claude(api, nwo: str, path: str, cache: dict) -> bool:
    """Does the workflow file at `path` call Claude? One contents read per
    distinct path, cached for the sweep."""
    if path in cache:
        return cache[path]
    uses = False
    if path and not path.startswith("dynamic/"):
        try:
            blob = api.get(f"/repos/{nwo}/contents/{path}", kind="contents")
            text = base64.b64decode(blob.get("content") or "").decode("utf-8", "replace")
            uses = any(m in text for m in CLAUDE_WORKFLOW_MARKERS)
        except Exception:
            pass
    cache[path] = uses
    return uses


def _scan_log_for_usage(gh_session, url: str) -> dict:
    """Download a run's log zip and read every Claude usage payload in it."""
    out: dict = {"log": "unavailable", "claude_step": False, "records": []}
    try:
        resp = gh_session.get(url, timeout=60)
        if resp.status_code != 200:
            return out
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            out["log"] = "ok"
            for name in zf.namelist():
                if not name.endswith(".txt"):
                    continue
                text = zf.read(name).decode("utf-8", "replace")
                if any(m in text for m in CLAUDE_LOG_MARKERS):
                    out["claude_step"] = True
                if not any(m in text for m in USAGE_MARKERS):
                    continue
                out["records"].extend(iter_usage_records(text))
    except Exception:
        pass
    return out


def classify_run(conclusion: str | None, scan: dict | None) -> dict:
    """The usage fields for one run: priced, free, or left for the estimator."""
    if conclusion == "skipped":
        return {"cost_usd": 0.0, "cost_source": "no-spend", "cost_basis": "run-skipped",
                "turns": None, "result_line_usd": None, "unpriced_models": [],
                **dict.fromkeys(TOKEN_KEYS, 0)}
    scan = scan or {"log": "unavailable", "claude_step": False, "records": []}
    priced = price_records(scan["records"])
    if priced["cost_source"]:
        return priced
    if scan["log"] == "ok" and not scan["claude_step"]:
        # The run exists, its log is complete, and no Claude step is in it: the
        # gate job short-circuited the loop. $0 measured, not $0 assumed.
        priced.update({"cost_usd": 0.0, "cost_source": "no-spend", "cost_basis": "no-ai-step"})
        return priced
    priced["cost_basis"] = "log-unavailable" if scan["log"] != "ok" else None
    return priced


def collect_ci(api, gh_session, registry: list[dict], window_start: dt.datetime,
               max_runs: int, now: dt.datetime | None = None,
               coverage: list | None = None) -> list[dict]:
    """Every Claude-calling run created in the window, priced.

    The window is listed the way actions_analytics lists it — by `created`
    date range, split below GitHub's 1,000-result cap — so the hub's ~200
    runs a day no longer exhaust a 300-run budget before its Claude loops
    are reached (the 2026-11-07 ledger held 5 hub runs for 14 days). A repo
    whose listing still fell short is appended to `coverage` with
    `truncated: true` and `runs_missed`.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    entries: list[dict] = []
    for project in registry:
        nwo = actions_analytics.owner_repo(project.get("repo_url", ""))
        if not nwo:
            continue
        sys.stderr.write(f"  ci · {nwo}\n")
        listing = actions_analytics.list_window_runs(api, nwo, window_start, now, max_runs)
        claude_paths: dict[str, bool] = {}
        found = 0
        for run in listing["runs"]:
            if run.get("status") != "completed":
                continue
            if not _workflow_uses_claude(api, nwo, run.get("path") or "", claude_paths):
                continue
            found += 1
            created = actions_analytics.parse_ts(run.get("created_at"))
            updated = actions_analytics.parse_ts(run.get("updated_at"))
            # A skipped run cannot have spent anything, so its log is never
            # downloaded — that is 146 fewer zip downloads per refresh.
            scan = None if run.get("conclusion") == "skipped" else _scan_log_for_usage(
                gh_session, run.get("logs_url") or "")
            usage = classify_run(run.get("conclusion"), scan)
            entries.append({
                "repo": project["name"],
                "workflow": run.get("name"),
                "path": run.get("path"),
                "event": run.get("event"),
                "conclusion": run.get("conclusion"),
                "day": created.strftime("%Y-%m-%d") if created else None,
                "url": run.get("html_url"),
                "duration_min": round(max(0.0, (updated - created).total_seconds()) / 60, 1)
                if created and updated else 0.0,
                **{k: v for k, v in usage.items() if k != "unpriced_models"},
                "unpriced_models": usage["unpriced_models"] or None,
            })
        if coverage is not None:
            coverage.append({"repo": project["name"], "nwo": nwo,
                             "runs_in_window": listing["in_window"],
                             "runs_listed": len(listing["runs"]),
                             "claude_runs": found,
                             "truncated": bool(listing["truncated"]),
                             "runs_missed": listing["runs_missed"],
                             "error": listing["error"]})
    return entries


def ai_parity(entries: list[dict]) -> dict:
    """The ledger against claude-cost's own result lines, where a run has them.

    Every hub loop runs .github/actions/claude-cost after its agent, which
    echoes the CLI's result record behind `claude-run-result`; that line is the
    run's own statement of what it cost. Over the runs that carry one, the
    ledger's measured `cost_usd` should equal the sum of those lines — a
    positive gap is a double count (what this block caught: one issue-pipeline
    run ledgered at $25.64 against result lines of $12.82), a negative one a
    call the scraper missed. Runs without claude-cost (most submodule
    workflows) have no reference and are not compared.
    """
    rows = [r for r in entries if r.get("result_line_usd") is not None]
    ledger = round(sum(float(r.get("cost_usd") or 0.0) for r in rows), 4)
    lines = round(sum(float(r["result_line_usd"]) for r in rows), 4)
    off = [r for r in rows if abs(float(r.get("cost_usd") or 0.0) - float(r["result_line_usd"])) > 0.005]
    return {
        "measure": "Claude CI cost, API-equivalent (estimate)",
        "ours": "ledger cost_usd of runs that carry claude-cost result lines",
        "reference": "claude-cost `claude-run-result` lines (one per session)",
        "runs_compared": len(rows),
        "ledger_usd": ledger,
        "result_lines_usd": lines,
        "gap_pct": actions_analytics.gap_pct(ledger, lines),
        "runs_off": len(off),
        "runs_off_sample": [r.get("url") for r in off[:5]],
    }


# --------------------------------------------------------------------------- #
# commits + PRs
# --------------------------------------------------------------------------- #
def collect_vcs(gh, registry: list[dict], window_start: dt.datetime,
                commit_cap: int) -> tuple[list[dict], list[dict]]:
    commits: list[dict] = []
    prs: list[dict] = []
    since_date = window_start.strftime("%Y-%m-%d")
    for project in registry:
        nwo = actions_analytics.owner_repo(project.get("repo_url", ""))
        if not nwo:
            continue
        sys.stderr.write(f"  vcs · {nwo}\n")
        try:
            repo = gh.get_repo(nwo)
            n = 0
            for c in repo.get_commits(since=window_start):
                n += 1
                if n > commit_cap:
                    break
                msg = c.commit.message or ""
                if COMMIT_TRAILER.search(msg):
                    commits.append({
                        "repo": project["name"],
                        "sha": c.sha[:9],
                        "day": c.commit.author.date.strftime("%Y-%m-%d"),
                        "title": msg.splitlines()[0][:90],
                        "url": c.html_url,
                    })
        except Exception:
            pass
        try:
            q = f'repo:{nwo} is:pr created:>={since_date} "{PR_MARKER}" in:body'
            for issue in gh.search_issues(q):
                prs.append({
                    "repo": project["name"],
                    "number": issue.number,
                    "day": issue.created_at.strftime("%Y-%m-%d"),
                    "state": issue.state,
                    "title": issue.title[:90],
                    "url": issue.html_url,
                })
            time.sleep(2.2)  # search API: 30 req/min
        except Exception:
            pass
    return commits, prs


# --------------------------------------------------------------------------- #
# local section (opt-in publish, preserved across CI refreshes)
# --------------------------------------------------------------------------- #
def local_section(out_path: Path, window_days: int) -> dict | None:
    try:
        import ai_activity
        ledger_path = ai_activity.LEDGER_DEFAULT
        if ledger_path.exists():
            ledger = ai_activity.merge_ledger(ledger_path, {}, {})
            report = ai_activity.build_report(
                ledger, machine=ai_activity.platform.node(), window_days=window_days)
            return {
                "published": dt.date.today().isoformat(),
                "window_days": window_days,
                "totals": report.get("totals"),
                "by_repo": report.get("by_repo", [])[:20],
            }
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"  local ledger unavailable ({exc}); preserving prior section\n")
    if out_path.exists():
        try:
            prior = yaml.safe_load(out_path.read_text()) or {}
            return prior.get("local")
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# estimation — the runs that left no usage behind
# --------------------------------------------------------------------------- #
def load_usd_per_turn(fleet_path: Path = FLEET) -> float:
    """`budget.usd_per_turn` from _data/fleet.yml — the fleet's own declared
    rate, so the estimate and the caps that fund these runs agree."""
    try:
        cfg = yaml.safe_load(fleet_path.read_text()) or {}
        value = ((cfg.get("budget") or {}).get("usd_per_turn"))
        return float(value) if value is not None else 0.15
    except Exception:
        return 0.15


def estimate_unpriced(entries: list[dict], usd_per_turn: float) -> dict[str, int]:
    """Give every run with no usage data an explicit `est_cost_usd`.

    A run reaches here only if a Claude step ran (or its log is gone) and no
    payload survived — the honest answer is "we don't know", and the honest
    accounting is a stated estimate, not the zero the totals used to carry.
    The basis, cheapest assumption first:

      workflow-median  the median of this workflow's OWN priced runs in the
                       window — the same prompt at the same cap, so the best
                       evidence available;
      turns-rate       the run's own turn count at `budget.usd_per_turn`;
      fleet-median     the median priced run anywhere in the window;
      rate-floor       one turn at the declared rate, when nothing in the
                       window was priced at all.
    """
    by_workflow: dict[tuple[str, str], list[float]] = {}
    priced: list[float] = []
    for e in entries:
        if e.get("cost_source") in ("reported", "tokens"):
            by_workflow.setdefault((e["repo"], e["workflow"]), []).append(e["cost_usd"])
            priced.append(e["cost_usd"])
    bases: collections.Counter = collections.Counter()
    for e in entries:
        if e.get("cost_source"):
            continue
        same = by_workflow.get((e["repo"], e["workflow"]))
        if same:
            est, basis = statistics.median(same), "workflow-median"
        elif e.get("turns"):
            est, basis = e["turns"] * usd_per_turn, "turns-rate"
        elif priced:
            est, basis = statistics.median(priced), "fleet-median"
        else:
            est, basis = usd_per_turn, "rate-floor"
        e["cost_source"] = "estimated"
        e["est_cost_usd"] = round(est, 6)
        if e.get("cost_basis") != "log-unavailable":
            e["cost_basis"] = basis
        else:
            e["cost_basis"] = f"log-unavailable/{basis}"
        bases[basis] += 1
    return dict(bases)


def accounted(row: dict) -> float:
    """What a run cost the fleet, measured where possible and estimated where not."""
    return float(row.get("cost_usd") or 0.0) + float(row.get("est_cost_usd") or 0.0)


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def _empty_bucket() -> dict:
    return {
        "runs": 0, "cost_usd": 0.0, "est_cost_usd": 0.0, "accounted_usd": 0.0,
        "turns": 0, "minutes": 0.0,
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "priced_runs": 0, "unpriced_runs": 0, "no_spend_runs": 0,
    }


def _rollup(rows: list[dict], key) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for r in rows:
        b = agg.setdefault(key(r), _empty_bucket())
        b["runs"] += 1
        source = r.get("cost_source")
        if source == "estimated":
            b["unpriced_runs"] += 1
        elif source == "no-spend":
            b["no_spend_runs"] += 1
        else:
            b["priced_runs"] += 1
        b["cost_usd"] = round(b["cost_usd"] + float(r.get("cost_usd") or 0.0), 4)
        b["est_cost_usd"] = round(b["est_cost_usd"] + float(r.get("est_cost_usd") or 0.0), 4)
        b["accounted_usd"] = round(b["cost_usd"] + b["est_cost_usd"], 4)
        b["turns"] += r.get("turns") or 0
        b["minutes"] = round(b["minutes"] + (r.get("duration_min") or 0), 1)
        for t in TOKEN_KEYS:
            b[t] += r.get(t) or 0
    return agg


# The hub as a pseudo-registry row, and the registry with the hub first: one
# definition, shared with actions_analytics (which needs it for the same reason).
hub_entry = actions_analytics.hub_entry
with_hub = actions_analytics.with_hub


def build(gh, gh_session, registry: list[dict], window_days: int, max_runs: int,
          commit_cap: int, out_path: Path, api=None) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=window_days)
    cat_of = {p["name"]: p.get("category", "uncategorized") for p in registry}

    coverage: list[dict] = []
    ci = collect_ci(api, gh_session, registry, window_start, max_runs, now=now,
                    coverage=coverage)
    usd_per_turn = load_usd_per_turn()
    bases = estimate_unpriced(ci, usd_per_turn)
    commits, prs = collect_vcs(gh, registry, window_start, commit_cap)
    local = local_section(out_path, window_days)

    by_repo = _rollup(ci, lambda r: r["repo"])
    for c in commits:
        by_repo.setdefault(c["repo"], _empty_bucket())
        by_repo[c["repo"]]["commits"] = by_repo[c["repo"]].get("commits", 0) + 1
    for p in prs:
        by_repo.setdefault(p["repo"], _empty_bucket())
        by_repo[p["repo"]]["prs"] = by_repo[p["repo"]].get("prs", 0) + 1

    measured = round(sum(float(r.get("cost_usd") or 0.0) for r in ci), 2)
    estimated = round(sum(float(r.get("est_cost_usd") or 0.0) for r in ci), 2)
    unpriced = sum(1 for r in ci if r.get("cost_source") == "estimated")
    no_spend = sum(1 for r in ci if r.get("cost_source") == "no-spend")
    models = sorted({m for r in ci for m in (r.get("unpriced_models") or [])})
    report = {
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": window_days,
        "totals": {
            "ci_runs": len(ci),
            "ci_cost_usd": measured,
            "ci_estimated_usd": estimated,
            "ci_accounted_usd": round(measured + estimated, 2),
            "ci_priced_runs": sum(1 for r in ci if r.get("cost_source") in ("reported", "tokens")),
            "ci_unpriced_runs": unpriced,
            "ci_no_spend_runs": no_spend,
            "turns": sum(r.get("turns") or 0 for r in ci),
            "ci_minutes": round(sum(r.get("duration_min") or 0 for r in ci), 1),
            "commits": len(commits),
            "prs": len(prs),
            "repos_active": len(by_repo),
        },
        # How every dollar above was arrived at — the page states its own
        # confidence instead of implying the measured half is the whole.
        "pricing": {
            "measured_usd": measured,
            "estimated_usd": estimated,
            "estimated_share_pct": round(100.0 * estimated / (measured + estimated), 1)
            if (measured + estimated) else 0.0,
            "usd_per_turn": usd_per_turn,
            "rates": "API list prices (ai_activity.PRICING); cache writes 1.25x/2x in, reads 0.1x in",
            "estimate_bases": bases,
            "unpriced_models": models,
        },
        "by_repo": [
            {"repo": k, "category": cat_of.get(k, "uncategorized"), **v}
            for k, v in sorted(by_repo.items(),
                               key=lambda kv: (-kv[1]["accounted_usd"], -kv[1]["runs"]))
        ],
        "by_workflow": [
            {"workflow": k, **v}
            for k, v in sorted(_rollup(ci, lambda r: f'{r["repo"]}/{r["workflow"]}').items(),
                               key=lambda kv: (-kv[1]["accounted_usd"], -kv[1]["runs"]))
        ],
        "by_category": [
            {"category": k, **v}
            for k, v in sorted(_rollup(ci, lambda r: cat_of.get(r["repo"], "uncategorized")).items(),
                               key=lambda kv: -kv[1]["accounted_usd"])
        ],
        "by_day": [
            {"day": k, **v}
            for k, v in sorted(_rollup(ci, lambda r: r["day"]).items())
        ],
        "parity": {"ai_ci_cost": ai_parity(ci)},
        "coverage": {
            "truncated": any(r["truncated"] for r in coverage),
            "runs_missed": sum(int(r["runs_missed"] or 0) for r in coverage),
            "truncated_repos": [r["repo"] for r in coverage if r["truncated"]],
            "api_calls": dict(sorted(api.calls.items())) if api is not None else None,
            "repos": coverage,
        },
        "ci_ledger": sorted(ci, key=lambda r: (r["day"] or "", r["repo"]), reverse=True)[:200],
        "commit_ledger": sorted(commits, key=lambda c: c["day"], reverse=True)[:100],
        "pr_ledger": sorted(prs, key=lambda p: p["day"], reverse=True)[:100],
    }
    if local:
        report["local"] = local
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    try:
        from github import Github, Auth
        import requests
    except ImportError:
        sys.stderr.write("ai-usage requires PyGithub: pip install PyGithub\n")
        return 2

    token = actions_analytics.resolve_token()
    if not token:
        sys.stderr.write("No GitHub token (set GH_TOKEN/GITHUB_TOKEN or run `gh auth login`).\n")
        return 2
    gh = Github(auth=Auth.Token(token), per_page=100)
    api = actions_analytics.RestApi(actions_analytics.requester_of(gh))
    # a raw session for log-zip downloads, sharing the client's token
    gh_session = requests.Session()
    gh_session.headers["Authorization"] = f"token {token}"

    with actions_analytics.REGISTRY.open() as fh:
        registry = yaml.safe_load(fh) or []
    if not args.no_hub:
        registry = with_hub(registry)
    if args.repo:
        wanted = set(args.repo)
        registry = [p for p in registry if p.get("name") in wanted
                    or actions_analytics.owner_repo(p.get("repo_url", "")) in wanted]
    sys.stderr.write(f"Collecting Claude usage for {len(registry)} repos (last {args.days}d)…\n")
    out = Path(args.out)
    report = build(gh, gh_session, registry, args.days, args.max_runs,
                   args.commit_cap, out, api=api)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("# GENERATED by .github/scripts/dash-gen (ai_usage_collector) — "
                 "refreshed daily by fleet-pulse.yml. Edit the generator, not this file.\n")
        yaml.safe_dump(report, fh, sort_keys=False, allow_unicode=True)
    t = report["totals"]
    sys.stderr.write(
        f"ai-usage: {t['ci_runs']} CI runs · ${t['ci_cost_usd']} measured "
        f"+ ${t['ci_estimated_usd']} estimated ({t['ci_unpriced_runs']} runs) "
        f"= ${t['ci_accounted_usd']} accounted · {t['ci_no_spend_runs']} no-spend · "
        f"{t['commits']} commits · {t['prs']} PRs -> {out}\n")
    par = report["parity"]["ai_ci_cost"]
    if par["runs_compared"]:
        sys.stderr.write(
            f"  parity: ledger ${par['ledger_usd']} vs claude-cost result lines "
            f"${par['result_lines_usd']} over {par['runs_compared']} runs "
            f"(gap {par['gap_pct']}%)\n")
    if report["coverage"]["truncated"]:
        sys.stderr.write(f"  ! truncated: {report['coverage']['truncated_repos']} "
                         f"({report['coverage']['runs_missed']} runs missed)\n")
    if report["pricing"]["unpriced_models"]:
        sys.stderr.write(
            "  ! no rate row for: " + ", ".join(report["pricing"]["unpriced_models"])
            + " — add it to ai_activity.PRICING\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--days", type=int, default=14, help="analysis window (default 14)")
    parser.add_argument("--max-runs", type=int, default=0,
                        help="cap runs listed per repo; 0 = the whole window (default). "
                             "A cap that bites is published as coverage truncated + runs_missed")
    parser.add_argument("--repo", action="append", metavar="NAME",
                        help="only this registry name or owner/repo (repeatable; a local probe)")
    parser.add_argument("--commit-cap", type=int, default=150,
                        help="max commits scanned per repo (default 150)")
    parser.add_argument("--no-hub", action="store_true",
                        help="skip the hub itself (_data/fleet.yml hub.repo); registry only")
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.set_defaults(func=run)

#!/usr/bin/env python3
"""What the console's assistant did — one document from the records the fleet already keeps.

The assistant (agent `local:console-assist` in _data/agents.yml) leaves two records, and this module is the
one reader of both, so the console's Assist page, the MCP layer's `assist_activity` tool, the lake and a
terminal all say the same thing (AGENTS.md: shared surface code lives in tools/fleetcore/):

  the page audit   one JSON line per page command, pairing and operator's end, written by the console's
                   page bridge (tools/console/page_bridge.py) to `.fleet/assist/page-audit.jsonl`
                   (DASH_CONSOLE_PAGE_AUDIT overrides it; the file rotates once, to `.1`). It says what a
                   session did to a page: which session, the dock's or a paired one, the console's own
                   page or a fleet page and its origin, the action, its target, the mode, the outcome.
                   Typed text is never in it and neither is a session id, only its first eight characters.
  the AI ledger    one row per assistant message, written by `tools/dash-gen ai-run` (source
                   `console assist`) to ~/.claude/ai-activity-ledger.json (DASH_AI_LEDGER overrides it):
                   the session, its model, tokens, cost and the cost's source, the outcome and the cap.

`activity()` joins them into `assist-activity/v1`. Everything here is read-only and offline: no GitHub, no
model, no console. A cost is API-equivalent (estimate) (constitution § 10.7). A paired Claude Code session
is the person's own session: it has page-audit lines (client `paired`) and no ledger row, because it never
went through the capped runner; its cost is in its transcript, which the lake reads (`lake assist`).

Usage (from tools/, as `tools/dash apps assist activity` runs it):
    python3 -m fleetcore.assistlog [--days N] [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]
SCHEMA = "assist-activity/v1"
#: the assistant's id in the agent inventory (_data/fleet.yml harness.agents, _data/agents.yml)
AGENT = "local:console-assist"
#: the `--source` the console's assist operation gives ai-run: the ledger rows that are the assistant's
SOURCE = "console assist"
COST_LABEL = "API-equivalent (estimate)"
AUDIT_RELATIVE = Path(".fleet") / "assist" / "page-audit.jsonl"
#: the actions that are not a command on a page: a second session attaching, the operator ending a session
NOT_COMMANDS = ("attach", "end")
#: an outcome that is somebody's "no": the broker refused it (the mode, the ceiling), the page did not do it
#: (one of its own rules, or an element that is gone), the person declined, or nobody answered in time
NO_OUTCOMES = ("refused", "page", "declined", "timeout")
DAYS_DEFAULT = 7
RECENT_DEFAULT = 50
RECENT_MAX = 500
TEXT_MAX = 300


def audit_path(root: Path | str = HUB, env: dict | None = None) -> Path:
    """Where the page bridge's audit lives: DASH_CONSOLE_PAGE_AUDIT, else `.fleet/assist/page-audit.jsonl`
    in the hub checkout — beside the MCP layer's own audit, on disk a host tool can read and a restart keeps."""
    env = os.environ if env is None else env
    named = (env.get("DASH_CONSOLE_PAGE_AUDIT") or "").strip()
    return Path(named).expanduser() if named else Path(root) / AUDIT_RELATIVE


def ledger_path(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("DASH_AI_LEDGER") or "~/.claude/ai-activity-ledger.json").expanduser()


def parse_time(value) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


#: (which record, path) -> (the files' stamps, the rows read at those stamps): a console that polls the
#: activity document reads each file once per change, not once per request
_CACHE: dict[tuple[str, str], tuple[tuple, list[dict]]] = {}


def _stamp(*paths: Path) -> tuple:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _text(value, limit: int = TEXT_MAX) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def audit_row(line: str) -> dict | None:
    """One audit line as a row every reader agrees on, or None when it is not one. Lines written before a
    line carried `id`, `kind` and `origin` are read too: the id is then derived from the line itself, and a
    fleet page is recognized by its attach line's target (its origin)."""
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict) or not raw.get("action") or parse_time(raw.get("at")) is None:
        return None
    origin = _text(raw.get("origin")) or None
    if origin is None and raw.get("action") == "attach" and str(raw.get("target") or "").startswith("http"):
        origin = _text(raw.get("target"))
    kind = raw.get("kind") if raw.get("kind") in ("console", "fleet") else ("fleet" if origin else "console")
    try:
        ms = max(0, int(raw.get("ms") or 0))
    except (TypeError, ValueError):
        ms = 0
    rid = raw.get("id")
    if not (isinstance(rid, str) and rid):
        rid = hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]
    return {"id": _text(rid, 40), "at": parse_time(raw["at"]).astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
            "session": _text(raw.get("session"), 8), "client": _text(raw.get("client"), 20) or "dock",
            "kind": kind, "origin": origin, "repo": _text(raw.get("repo"), 120) or None,
            "action": _text(raw.get("action"), 20), "target": _text(raw.get("target")),
            "mode": _text(raw.get("mode"), 10), "outcome": _text(raw.get("outcome"), 20) or "ok", "ms": ms}


def read_audit(path: Path) -> list[dict]:
    """Every readable line of the audit, oldest first: the rotated file (`<name>.1`), then the live one. A
    missing file is an empty audit; a line that is not a record is skipped, never fatal."""
    parts = (path.with_suffix(path.suffix + ".1"), path)
    key, stamp = ("audit", str(path)), _stamp(*parts)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return list(hit[1])
    rows: list[dict] = []
    for part in parts:
        try:
            with part.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    row = audit_row(line)
                    if row is not None:
                        rows.append(row)
        except FileNotFoundError:
            continue
        except OSError:
            continue
    rows.sort(key=lambda r: r["at"])
    _CACHE[key] = (stamp, rows)
    return list(rows)


def since(rows: list[dict], days: int | None, now: dt.datetime | None = None, key: str = "at") -> list[dict]:
    """The rows of the last `days` days (None or 0: every row)."""
    if not days:
        return list(rows)
    cutoff = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=days)
    out = []
    for r in rows:
        when = parse_time(r.get(key))
        if when is not None and when >= cutoff:
            out.append(r)
    return out


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100.0 / whole, 1) if whole else None


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize_audit(rows: list[dict]) -> dict:
    """What the page audit holds, counted: commands (attach and end lines are counted apart), who asked, whose
    page, what came of it. `no_pct` is the share of commands that met a no — the broker's refusal, the page's
    own (a rule, or an element that is gone), the person's decline, or nobody answering — which is the rules
    working, not a fault."""
    commands = [r for r in rows if r["action"] not in NOT_COMMANDS]
    ok_ms = [r["ms"] for r in commands if r["outcome"] == "ok"]
    noes = sum(1 for r in commands if r["outcome"] in NO_OUTCOMES)
    origins = Counter(r["origin"] for r in rows if r["origin"])
    return {
        "lines": len(rows), "commands": len(commands),
        "attaches": sum(1 for r in rows if r["action"] == "attach"),
        "ended_by_operator": sum(1 for r in rows if r["action"] == "end"),
        "sessions": len({r["session"] for r in rows if r["session"]}),
        "by_outcome": dict(Counter(r["outcome"] for r in commands).most_common()),
        "by_action": dict(Counter(r["action"] for r in commands).most_common()),
        "by_client": dict(Counter(r["client"] for r in commands).most_common()),
        "by_kind": dict(Counter(r["kind"] for r in commands).most_common()),
        "by_mode": dict(Counter(r["mode"] for r in commands if r["mode"]).most_common()),
        "origins": dict(origins.most_common()),
        "no": noes, "no_pct": _pct(noes, len(commands)),
        "ok_ms_p50": _percentile(ok_ms, 0.5), "ok_ms_p95": _percentile(ok_ms, 0.95),
        "first": rows[0]["at"] if rows else None, "last": rows[-1]["at"] if rows else None,
    }


def read_runs(path: Path, source: str = SOURCE) -> list[dict]:
    """The assistant's rows of the AI ledger, oldest first, as the fields a reader needs. A missing or
    unreadable ledger is no rows: this is a reader, and ai-run is the only writer."""
    key, stamp = (f"runs:{source}", str(path)), _stamp(path)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return list(hit[1])
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs = doc.get("runs") if isinstance(doc, dict) else None
    if isinstance(runs, dict):
        items = list(runs.values())
    elif isinstance(runs, list):
        items = runs
    else:
        return []
    out = []
    for r in items:
        if not isinstance(r, dict) or r.get("source") != source:
            continue
        when = parse_time(r.get("timestamp"))
        if when is None:
            continue
        cost = r.get("total_cost_usd")
        usage = r.get("usage") if isinstance(r.get("usage"), dict) else {}
        out.append({
            "at": when.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
            "session_id": _text(r.get("session_id"), 64) or None,
            "model": _text(r.get("model"), 80) or None,
            "outcome": _text(r.get("outcome"), 40) or "unknown",
            "cost_usd": round(float(cost), 6) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
            "cost_source": _text(r.get("cost_source"), 20) or None,
            "cap_usd": r.get("cap_usd") if isinstance(r.get("cap_usd"), (int, float)) else None,
            "turns": usage.get("turns") if isinstance(usage.get("turns"), int) else None,
            "duration_s": r.get("duration_s") if isinstance(r.get("duration_s"), (int, float)) else None,
            "cli_version": _text(r.get("cli_version"), 20) or None,
        })
    out.sort(key=lambda r: r["at"])
    _CACHE[key] = (stamp, out)
    return list(out)


def summarize_runs(rows: list[dict]) -> dict:
    """The assistant's messages, counted. `cost_unreported` is a run whose cost the CLI never printed: it is
    charged at its cap as `estimated`, which is loud on purpose. `not_ok` is every message that did not end
    as an answer (a cap, the wall clock, a spent usage window, a rejected credential, a crash)."""
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    turns = [r["turns"] for r in rows if r["turns"] is not None]
    not_ok = sum(1 for r in rows if r["outcome"] != "ok")
    return {
        "messages": len(rows),
        "cost_usd": round(sum(costs), 4) if costs else (0.0 if rows else None),
        "cost_label": COST_LABEL,
        "by_outcome": dict(Counter(r["outcome"] for r in rows).most_common()),
        "by_model": dict(Counter(r["model"] or "unknown" for r in rows).most_common()),
        "by_cost_source": dict(Counter(r["cost_source"] or "unknown" for r in rows).most_common()),
        "cost_unreported": sum(1 for r in rows if r["cost_source"] not in ("reported", "no-spend")),
        "not_ok": not_ok, "not_ok_pct": _pct(not_ok, len(rows)),
        "budget_hits": sum(1 for r in rows if r["outcome"] == "budget_hit"),
        "turns": sum(turns) if turns else None,
        "max_cost_usd": round(max(costs), 4) if costs else None,
        "first": rows[0]["at"] if rows else None, "last": rows[-1]["at"] if rows else None,
    }


def activity(root: Path | str = HUB, *, days: int = DAYS_DEFAULT, limit: int = RECENT_DEFAULT,
             audit: Path | None = None, ledger: Path | None = None, now: dt.datetime | None = None,
             env: dict | None = None) -> dict:
    """The assistant's activity over the last `days` days: its page audit and its messages, each counted and
    with its newest `limit` rows (newest first). Paths are named so a reader can open the files."""
    days = max(0, int(days))
    limit = max(0, min(int(limit), RECENT_MAX))
    apath = audit if audit is not None else audit_path(root, env)
    lpath = ledger if ledger is not None else ledger_path(env)
    lines = since(read_audit(apath), days, now)
    runs = since(read_runs(lpath), days, now)
    return {
        "schema": SCHEMA, "agent": AGENT, "window_days": days, "cost_label": COST_LABEL,
        "generated_at": (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "page_audit": {"path": str(apath), "exists": apath.is_file(), "summary": summarize_audit(lines),
                       "recent": list(reversed(lines))[:limit]},
        "messages": {"ledger": str(lpath), "exists": lpath.is_file(), "source": SOURCE,
                     "summary": summarize_runs(runs),
                     "recent": [{**r, "session_id": (r["session_id"] or "")[:8] or None}
                                for r in list(reversed(runs))[:limit]]},
        "note": ("A paired Claude Code session has page-audit lines (client `paired`) and no ledger row: it is "
                 "the person's own session, never the capped runner's. Its cost is in its transcript "
                 "(`tools/dash lake assist` reads it from the lake)."),
    }


def blank(days: int = DAYS_DEFAULT) -> dict:
    """The document with nothing in it and no path named: what a published build carries, where there is no
    machine whose records these would be."""
    return {
        "schema": SCHEMA, "agent": AGENT, "window_days": max(0, int(days)), "cost_label": COST_LABEL,
        "generated_at": None,
        "page_audit": {"path": None, "exists": False, "summary": summarize_audit([]), "recent": []},
        "messages": {"ledger": None, "exists": False, "source": SOURCE, "summary": summarize_runs([]), "recent": []},
        "note": "The assistant runs on the operator's machine: its activity is recorded there, not here.",
    }


def _counts(counter: dict) -> str:
    return ", ".join(f"{n} {k}" for k, n in counter.items()) or "none"


def table(doc: dict) -> str:
    """The document as text for a terminal."""
    a, m = doc["page_audit"], doc["messages"]
    sa, sm = a["summary"], m["summary"]
    days = doc["window_days"]
    span = f"last {days} day(s)" if days else "all time"
    out = [f"The console's assistant ({doc['agent']}), {span}", ""]
    cost = "no messages" if not sm["messages"] else (
        f"{sm['messages']} message(s) · ${sm['cost_usd']:.4f} {COST_LABEL} · {_counts(sm['by_outcome'])}"
        f"{' · ' + str(sm['cost_unreported']) + ' with no reported cost (charged at the cap)' if sm['cost_unreported'] else ''}")
    out.append(f"Messages (AI ledger, source `{m['source']}`): {cost}")
    for r in m["recent"][:10]:
        money = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "$?"
        out.append(f"  {r['at']}  {r['outcome']:<12} {money:>9}  {r['turns'] if r['turns'] is not None else '?':>3} turn(s)  "
                   f"{r['model'] or '?'}  session {r['session_id'] or '?'}")
    out.append("")
    if not a["exists"]:
        out.append(f"Page audit: no file at {a['path']} (no page command has been recorded here)")
    else:
        out.append(f"Page audit ({a['path']}): {sa['commands']} command(s) on {sa['sessions']} session(s) · "
                   f"{_counts(sa['by_outcome'])} · asked by {_counts(sa['by_client'])} · pages: {_counts(sa['by_kind'])}"
                   f"{' · ' + str(sa['ended_by_operator']) + ' ended from the console' if sa['ended_by_operator'] else ''}")
        if sa["origins"]:
            out.append(f"  fleet pages by origin: {_counts(sa['origins'])}")
        for r in a["recent"][:15]:
            where = r["origin"] or "console"
            out.append(f"  {r['at']}  {r['session']:<8} {r['client']:<8} {r['action']:<9} {r['outcome']:<8} "
                       f"{r['mode']:<4} {where}  {r['target']}")
    out += ["", doc["note"]]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dash apps assist activity",
                                 description="What the console's assistant did: its messages (the AI ledger) "
                                             "and what its sessions did to pages (the page audit). Read-only.")
    ap.add_argument("--days", type=int, default=DAYS_DEFAULT, help=f"the window (default {DAYS_DEFAULT}; 0 is all time)")
    ap.add_argument("--limit", type=int, default=RECENT_DEFAULT, help="how many recent rows of each to carry")
    ap.add_argument("--json", action="store_true", help=f"the document ({SCHEMA})")
    a = ap.parse_args(argv)
    doc = activity(HUB, days=a.days, limit=a.limit)
    print(json.dumps(doc, indent=2) if a.json else table(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

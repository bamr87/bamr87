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

Local-only by design: the data source is this machine's ~/.claude, so unlike
`health` this subcommand is NOT part of `dash-gen all` and never runs in CI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import sys
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("dash-gen requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "_data" / "projects.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "ai_activity.yml"
LEDGER_DEFAULT = Path(
    os.environ.get("DASH_AI_LEDGER", "~/.claude/ai-activity-ledger.json")
).expanduser()

# USD per MTok at Anthropic API list prices (source: claude-api skill model
# table, cached 2026-06-24). Cache writes: 1.25x input (5m TTL) / 2x (1h TTL);
# cache reads: 0.1x input. Unknown models are counted but priced at 0 and
# surfaced in `unpriced_models` — add a row here rather than guessing.
# Note: claude-sonnet-5 has intro pricing ($2/$10) through 2026-08-31; the
# list price is used so estimates stay comparable over time.
PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5":   {"in": 10.0, "out": 50.0},
    "claude-mythos-5":  {"in": 10.0, "out": 50.0},
    "claude-opus-4-8":  {"in": 5.0,  "out": 25.0},
    "claude-opus-4-7":  {"in": 5.0,  "out": 25.0},
    "claude-opus-4-6":  {"in": 5.0,  "out": 25.0},
    "claude-sonnet-5":  {"in": 3.0,  "out": 15.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5": {"in": 1.0,  "out": 5.0},
}
CACHE_5M_MULT, CACHE_1H_MULT, CACHE_READ_MULT = 1.25, 2.0, 0.1

# Bare aliases occasionally recorded in place of a full id (resolved to the
# alias's current target) and dated snapshots (suffix stripped).
MODEL_ALIASES = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}
DATE_SUFFIX = re.compile(r"-20\d{6}$")

USAGE_FIELDS = ("input", "output", "cache_5m", "cache_1h", "cache_read", "turns")
LEDGER_VERSION = 1


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
def merge_ledger(ledger_path: Path, usage: dict, sessions: dict) -> dict:
    """Max-merge scan results into the ledger file; return the merged ledger.

    A day's tokens only grow while its transcripts exist and only shrink when
    Claude Code prunes them — so per-key max preserves the true daily total.
    """
    ledger = {"version": LEDGER_VERSION, "usage": {}, "sessions": {}}
    try:
        with ledger_path.open() as fh:
            prior = json.load(fh)
        if isinstance(prior, dict) and prior.get("version") == LEDGER_VERSION:
            ledger["usage"] = prior.get("usage", {})
            ledger["sessions"] = prior.get("sessions", {})
    except (OSError, json.JSONDecodeError):
        pass

    for key, row in usage.items():
        old = ledger["usage"].setdefault(key, dict.fromkeys(USAGE_FIELDS, 0))
        for f in USAGE_FIELDS:
            old[f] = max(old.get(f, 0), row[f])
    for key, ids in sessions.items():
        ledger["sessions"][key] = sorted(set(ledger["sessions"].get(key, [])) | ids)

    ledger["updated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(ledger, fh, separators=(",", ":"))
    tmp.replace(ledger_path)
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

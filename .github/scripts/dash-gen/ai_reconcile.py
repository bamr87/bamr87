#!/usr/bin/env python3
"""
ai_reconcile — independent audit of the ai-activity shadow-pricing layer
(`dash ai check`; see docs/DASH.md → "AI activity").

ai_activity.py prices local Claude Code usage from a hand-maintained PRICING
table, hand-written MODEL_ALIASES, and its own dedupe. Nothing audited any of
the three, so a new model id, a list-price change, or a dedupe regression
skewed every number on /ai-activity/ in silence — the table had already lost
`claude-opus-5` for two months before this check existed (bamr87/bamr87#130).

This reconciles the ledger against `ccusage`, a third-party reader of the SAME
~/.claude JSONL transcripts, per (day, model):

  tokens  input / output / cache-write / cache-read. Same source, so these
          must agree. This half is what makes a DEDUPE regression visible: a
          dedupe bug changes token counts while leaving the model set
          identical, so a cost-only comparison cannot see it at all.
  cost    ours at API list prices, ccusage's from its own price source. A
          divergence here means the PRICING table or an alias has drifted.

ccusage is a cross-check, never the source of truth — the ledger stays
authoritative and this command never writes to it, and never edits PRICING.

Deltas are split into EXPLAINABLE (a named, expected reason) and UNEXPLAINED.
Only unexplained drift past the tolerance in _data/fleet.yml `ai_reconcile:`
fails the command. Explainable classes:

  unpriced-model  the model has no PRICING row, so we price it at $0 while
                  ccusage reports its real cost. Cost only — a token delta on
                  an unpriced model is still drift.
  intro-pricing   ai_activity.INTRO_PRICING_UNTIL says we deliberately use
                  list price where ccusage billed the intro rate. Cost only.
  day-boundary    the delta is cancelled by an opposing delta on an adjacent
                  day for the same model and metric — a timezone/bucketing
                  difference, not a lost or double-counted record.

Offline-safe by construction: if ccusage is absent, offline, or fails, the
command prints a SKIP with the reason and exits ZERO. It never reports a
false "reconciled", and it is usable on a machine with no network.

Scope. Only the current machine's ledger rows are compared (ccusage reads this
machine's ~/.claude), aggregated over repos, over a short recent window of
COMPLETE days. Two clamps, both there to stop the check crying wolf:

  * today is excluded (`--include-today` opts back in). The ledger is a
    snapshot and ccusage is read seconds later, so while a session is live the
    two sides are sampling a moving day and can never agree — a partial period
    is not drift;
  * the window is clamped to the range ccusage actually observed, because
    Claude Code prunes transcripts after ~30 days while the ledger keeps that
    history. Past the pruning horizon the ledger legitimately exceeds ccusage.

Keep the window short; that is what keeps this audit sharp.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("dash-gen requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import ai_activity

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET = REPO_ROOT / "_data" / "fleet.yml"

# Every knob is overridable from _data/fleet.yml `ai_reconcile:`; these are the
# fallbacks so an absent block degrades to sane behaviour instead of zeroes.
DEFAULTS: dict[str, object] = {
    "ccusage_version": "20.0.20",
    "window_days": 7,
    "cost_tolerance_pct": 2.0,
    "cost_floor_usd": 0.01,
    "token_tolerance_pct": 1.0,
    "boundary_match_pct": 25.0,
    "timeout_seconds": 300,
}

METRICS = ("cost", "input", "output", "cache_write", "cache_read")
TOKEN_METRICS = ("input", "output", "cache_write", "cache_read")


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_config(fleet_path: Path) -> dict:
    try:
        with Path(fleet_path).open() as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    cfg = data.get("ai_reconcile") if isinstance(data, dict) else None
    return {**DEFAULTS, **(cfg or {})}


# --------------------------------------------------------------------------- #
# the two sides
# --------------------------------------------------------------------------- #
def _row() -> dict:
    return {m: 0.0 if m == "cost" else 0 for m in METRICS}


def load_ledger(path: Path) -> dict:
    try:
        with Path(path).open() as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def ledger_rows(ledger: dict, machine: str, since: str, until: str) -> dict:
    """(day, model) -> totals for one machine, summed over repos.

    Costs are recomputed here through ai_activity.cost_usd, so this side of
    the comparison is exactly what /ai-activity/ reports.
    """
    rows: dict[tuple[str, str], dict] = {}
    for key, raw in (ledger.get("usage") or {}).items():
        parts = key.split("|", 3)
        if len(parts) != 4 or not isinstance(raw, dict):
            continue
        machine_key, date, _repo, model = parts
        if machine_key != machine or not since <= date <= until:
            continue
        usage = {f: int(raw.get(f) or 0) for f in ai_activity.USAGE_FIELDS}
        agg = rows.setdefault((date, model), _row())
        agg["input"] += usage["input"]
        agg["output"] += usage["output"]
        agg["cache_write"] += usage["cache_5m"] + usage["cache_1h"]
        agg["cache_read"] += usage["cache_read"]
        agg["cost"] += ai_activity.cost_usd(model, usage)
    return rows


def ccusage_rows(payload: dict) -> dict:
    """(day, model) -> totals from `ccusage claude daily --json`.

    Model ids are put through ai_activity.normalize_model, the SAME folding the
    ledger applies (dated snapshots stripped, bare aliases resolved), so the two
    sides are keyed alike. That makes this a comparison of quantities rather
    than of id spelling — alias drift still shows up, as a COST delta.
    """
    rows: dict[tuple[str, str], dict] = {}
    for day in payload.get("daily") or []:
        if not isinstance(day, dict):
            continue
        # `ccusage claude daily` keys the day `date`; the multi-agent
        # `ccusage daily` calls it `period`. Accept either.
        date = day.get("date") or day.get("period")
        if not date:
            continue
        date = str(date)[:10]
        for mb in day.get("modelBreakdowns") or []:
            if not isinstance(mb, dict):
                continue
            model = ai_activity.normalize_model(mb.get("modelName"))
            if not model:
                continue
            agg = rows.setdefault((date, model), _row())
            agg["input"] += int(mb.get("inputTokens") or 0)
            agg["output"] += int(mb.get("outputTokens") or 0)
            agg["cache_write"] += int(mb.get("cacheCreationTokens") or 0)
            agg["cache_read"] += int(mb.get("cacheReadTokens") or 0)
            agg["cost"] += float(mb.get("cost") or 0.0)
    return rows


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #
def _shift(date: str, days: int) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()


def _material(ours: float, theirs: float, tol_pct: float, floor: float) -> bool:
    """Is the gap bigger than both the absolute floor and the relative tolerance?"""
    delta = abs(theirs - ours)
    if delta <= floor:
        return False
    scale = max(abs(ours), abs(theirs))
    return delta > scale * (tol_pct / 100.0)


def _boundary_explained(
    deltas: dict, date: str, model: str, metric: str, delta: float, match_pct: float
) -> bool:
    """True when an adjacent day carries an opposing delta that cancels this one.

    That is the signature of a day-boundary/timezone bucketing difference: the
    records were counted, just filed under the neighbouring date. A delta with
    no counterpart is a record gained or lost, which is real drift.
    """
    for adjacent in (_shift(date, -1), _shift(date, 1)):
        other = deltas.get((adjacent, model), {}).get(metric)
        if not other or (other > 0) == (delta > 0):
            continue
        if abs(other + delta) <= abs(delta) * (match_pct / 100.0):
            return True
    return False


def compare(ledger: dict, ccusage: dict, cfg: dict) -> list[dict]:
    """One finding per (day, model, metric) that differs materially."""
    cost_tol = float(cfg["cost_tolerance_pct"])
    cost_floor = float(cfg["cost_floor_usd"])
    token_tol = float(cfg["token_tolerance_pct"])
    match_pct = float(cfg["boundary_match_pct"])

    keys = sorted(set(ledger) | set(ccusage))
    deltas = {
        key: {
            m: ccusage.get(key, _row())[m] - ledger.get(key, _row())[m]
            for m in METRICS
        }
        for key in keys
    }

    findings: list[dict] = []
    for date, model in keys:
        ours = ledger.get((date, model), _row())
        theirs = ccusage.get((date, model), _row())
        presence = (
            "both" if (date, model) in ledger and (date, model) in ccusage
            else ("ledger-only" if (date, model) in ledger else "ccusage-only")
        )
        unpriced = model not in ai_activity.PRICING
        intro_until = ai_activity.INTRO_PRICING_UNTIL.get(model)
        intro = bool(intro_until) and date <= intro_until

        for metric in METRICS:
            is_cost = metric == "cost"
            tol, floor = (cost_tol, cost_floor) if is_cost else (token_tol, 0.0)
            if not _material(ours[metric], theirs[metric], tol, floor):
                continue

            delta = deltas[(date, model)][metric]
            # Cost reasons first: an unpriced model is $0 here by construction,
            # which no bucketing argument could account for.
            if is_cost and unpriced:
                reason = "unpriced-model"
            elif is_cost and intro:
                reason = "intro-pricing"
            elif _boundary_explained(deltas, date, model, metric, delta, match_pct):
                reason = "day-boundary"
            else:
                reason = None

            findings.append(
                {
                    "date": date,
                    "model": model,
                    "metric": metric,
                    "ledger": ours[metric],
                    "ccusage": theirs[metric],
                    "delta": delta,
                    "presence": presence,
                    "reason": reason,
                }
            )
    return findings


def build_report(ledger: dict, ccusage: dict, cfg: dict, window: dict) -> dict:
    findings = compare(ledger, ccusage, cfg)
    explained = [f for f in findings if f["reason"]]
    unexplained = [f for f in findings if not f["reason"]]
    by_reason: dict[str, int] = {}
    for f in explained:
        by_reason[f["reason"]] = by_reason.get(f["reason"], 0) + 1
    return {
        "window": window,
        "compared_keys": len(set(ledger) | set(ccusage)),
        "explainable": explained,
        "explainable_by_reason": dict(sorted(by_reason.items())),
        "unexplained": unexplained,
        "ok": not unexplained,
    }


# --------------------------------------------------------------------------- #
# ccusage invocation
# --------------------------------------------------------------------------- #
def run_ccusage(
    version: str, since: str, timeout: int, claude_dir: Path | None = None
) -> tuple[dict | None, str | None]:
    """Return (payload, skip_reason). Every failure is a SKIP, never an error.

    The version is PINNED so a ccusage schema change fails loudly here instead
    of silently skewing the comparison.
    """
    cmd = [
        "npx", "-y", f"ccusage@{version}",
        "claude", "daily", "--json", "--since", since,
    ]
    env = dict(os.environ)
    if claude_dir:
        env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except FileNotFoundError:
        return None, "npx is not installed — ccusage needs Node.js"
    except subprocess.TimeoutExpired:
        return None, f"ccusage@{version} timed out after {timeout}s (offline?)"
    if out.returncode != 0:
        tail = (out.stderr or out.stdout or "").strip().splitlines()
        detail = tail[-1][:200] if tail else "no output"
        return None, f"ccusage@{version} exited {out.returncode}: {detail}"
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None, (
            f"ccusage@{version} did not emit JSON — its schema may have changed; "
            "re-pin `ai_reconcile.ccusage_version` in _data/fleet.yml"
        )
    if not isinstance(payload, dict) or "daily" not in payload:
        return None, (
            f"ccusage@{version} JSON has no `daily` key — schema change; "
            "re-pin `ai_reconcile.ccusage_version` in _data/fleet.yml"
        )
    return payload, None


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _fmt(metric: str, value: float) -> str:
    return f"${value:,.4f}" if metric == "cost" else f"{int(value):,}"


def _fmt_delta(metric: str, value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{_fmt(metric, value)}" if metric != "cost" else f"{sign}${value:,.4f}"


def render(report: dict, cfg: dict) -> str:
    w = report["window"]
    lines = [
        f"ai check — ledger vs ccusage@{cfg['ccusage_version']}",
        f"  machine {w['machine']} · {w['since']} … {w['until']} "
        f"({w['days']}d) · {report['compared_keys']} (day, model) pair(s)",
        "",
    ]

    def table(title: str, rows: list[dict]) -> None:
        lines.append(f"{title} ({len(rows)})")
        if not rows:
            lines.append("  —")
            lines.append("")
            return
        lines.append(
            f"  {'day':<11}{'model':<20}{'metric':<12}"
            f"{'ledger':>14}{'ccusage':>14}{'delta':>14}  reason"
        )
        for f in sorted(rows, key=lambda r: (r["date"], r["model"], r["metric"])):
            note = f["reason"] or (
                f["presence"] if f["presence"] != "both" else "unexplained"
            )
            lines.append(
                f"  {f['date']:<11}{f['model']:<20}{f['metric']:<12}"
                f"{_fmt(f['metric'], f['ledger']):>14}"
                f"{_fmt(f['metric'], f['ccusage']):>14}"
                f"{_fmt_delta(f['metric'], f['delta']):>14}  {note}"
            )
        lines.append("")

    table("EXPLAINABLE", report["explainable"])
    if report["explainable_by_reason"]:
        lines.append(
            "  " + " · ".join(
                f"{k} {v}" for k, v in report["explainable_by_reason"].items()
            )
        )
        lines.append("")
    table("UNEXPLAINED", report["unexplained"])

    tol = (
        f"cost {cfg['cost_tolerance_pct']}% / ${cfg['cost_floor_usd']}, "
        f"tokens {cfg['token_tolerance_pct']}%"
    )
    lines.append(
        f"OK — reconciled within tolerance ({tol})."
        if report["ok"]
        else f"DRIFT — {len(report['unexplained'])} unexplained delta(s) past tolerance ({tol})."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def _skip(reason: str) -> int:
    """A skip is never a pass and never a failure — it is 'not measured'."""
    sys.stderr.write(
        f"SKIP — ai check did not run: {reason}\n"
        "  Nothing was reconciled; this is not a clean bill of health.\n"
    )
    return 0


def run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.fleet))
    if args.window:
        cfg["window_days"] = args.window
    if args.ccusage_version:
        cfg["ccusage_version"] = args.ccusage_version

    claude_dir = (
        Path(args.claude_dir).expanduser()
        if args.claude_dir
        else Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
    )
    ledger_path = Path(args.ledger).expanduser()
    ledger = load_ledger(ledger_path)
    if not ledger.get("usage"):
        return _skip(f"no ai-activity ledger at {ledger_path} — run `dash ai` first")

    today = dt.date.today()
    days = max(1, int(cfg["window_days"]))
    # Complete days only: the ledger is a snapshot and ccusage is read after
    # it, so a day still being written cannot reconcile and is not drift.
    last_day = today if args.include_today else today - dt.timedelta(days=1)
    since = (last_day - dt.timedelta(days=days - 1)).isoformat()

    if args.ccusage_json:
        # Offline path: a recorded payload. Used by the fixture tests and for
        # reproducing a delta without re-running the tool.
        try:
            with Path(args.ccusage_json).open() as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            return _skip(f"could not read {args.ccusage_json}: {exc}")
    else:
        payload, reason = run_ccusage(
            str(cfg["ccusage_version"]), since, int(cfg["timeout_seconds"]), claude_dir
        )
        if reason:
            return _skip(reason)

    cc = ccusage_rows(payload)
    if not cc:
        return _skip(
            f"ccusage reported no Claude usage since {since} — "
            "nothing to reconcile against"
        )

    # Clamp to what ccusage actually observed. Beyond its horizon the ledger's
    # retained history has no counterpart, and comparing there is noise.
    cc_dates = sorted({d for d, _m in cc})
    since = max(since, cc_dates[0])
    until = min(last_day.isoformat(), cc_dates[-1])
    cc = {k: v for k, v in cc.items() if since <= k[0] <= until}
    if not cc:
        return _skip(
            f"no COMPLETE day with usage in {since}…{last_day.isoformat()} — "
            "today is excluded because it is still being written "
            "(--include-today to compare it anyway)"
        )

    machine = args.machine or platform.node().split(".")[0] or "local"
    led = ledger_rows(ledger, machine, since, until)
    if not led and not args.machine:
        known = sorted({k.split("|", 1)[0] for k in ledger["usage"]})
        return _skip(
            f"ledger has no rows for machine {machine!r} in {since}…{until} "
            f"(known machines: {', '.join(known) or 'none'}; override with --machine)"
        )

    report = build_report(
        led, cc, cfg,
        {"machine": machine, "since": since, "until": until, "days": days},
    )
    sys.stdout.write(render(report, cfg) + "\n")
    return 0 if report["ok"] else 1


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--window", type=int, default=None, metavar="DAYS",
                        help="days to reconcile (default: fleet.yml ai_reconcile.window_days)")
    parser.add_argument("--ledger", default=str(ai_activity.LEDGER_DEFAULT), metavar="PATH",
                        help=f"ai-activity ledger (default: {ai_activity.LEDGER_DEFAULT})")
    parser.add_argument("--claude-dir", default=None, metavar="PATH",
                        help="Claude config dir passed to ccusage (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    parser.add_argument("--ccusage-version", default=None, metavar="VER",
                        help="override the pinned ccusage version (default: fleet.yml)")
    parser.add_argument("--ccusage-json", default=None, metavar="PATH",
                        help="reconcile against a recorded ccusage payload instead of running it (offline)")
    parser.add_argument("--machine", default=None, metavar="NAME",
                        help="ledger machine to compare (default: this host)")
    parser.add_argument("--include-today", action="store_true",
                        help="also compare today — a partial day both sides are still writing")
    parser.add_argument("--fleet", default=str(FLEET), metavar="PATH",
                        help=f"fleet config (default: {FLEET})")
    parser.set_defaults(func=run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai_reconcile", description=__doc__)
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

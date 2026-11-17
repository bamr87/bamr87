#!/usr/bin/env python3
"""Outcome learning — what happened to each loop's output, and where its next slots would pay.

Every loop that files work ranks it with a fixed rule: the scout rotates through
the repos by date, evolution takes every opted-in repo, the pipeline scores an
issue from its labels. None of them reads what happened to the last thing it
filed. This module does, and nothing else: it reads the issues and pull requests
the loops filed (the lake's `issues` table), sorts each into an outcome, and
keeps one estimate per loop and per arm (the repo a loop acted on) of how likely
the next output is to land.

  outcome   landed    a pull request merged, an issue closed as completed
            rejected  closed without merging, or closed as not planned / duplicate
            stale     still open after `horizon_days` with nobody working it
            working   open and carrying a label that says a later stage took it
            young     open and younger than the horizon — too early to count
            unread    closed, but the lake holds no reason for it yet

  estimate  Beta(prior + landed, prior + rejected + stale), each outcome weighted by
            its age (`half_life_days`); the prior is the loop's own rate, worth
            `prior_strength` observations, so an arm with no history starts at
            the loop's average and is still explored

  plan      Thompson sampling over the arms: the share of the next slots each arm
            would get is the probability that it is the best one. Seeded by the
            date, so one day's plan is one answer.

  replay    the test the estimate must pass before anything acts on it: walking
            the history in order, did the arm's estimate predict each outcome
            better than the loop's plain average did (Brier skill)?

It is a contextual bandit in the plainest form that fits a few hundred outcomes
a quarter, and it is SHADOW ONLY: it prints a plan, steers no loop and changes
no cap (ADR 0010, docs/LEARNING.md). Reads only; no network, no model, no write.

  python3 -m fleetcore.learn [status|plan|replay] [--loop L] [--json]      (tools/dash learn)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import sqlite3
import sys
from pathlib import Path

import yaml

from . import yamlio

SCHEMA = "learning/v1"
ROOT_DEFAULT = Path(__file__).resolve().parents[2]
COST_LABEL = "API-equivalent (estimate)"
MODES = ("shadow",)  # anything that steers a loop is a later, gated decision (ADR 0010 decision 6)
STATES = ("landed", "rejected", "stale", "working", "young", "unread")
RESOLVED = ("landed", "rejected", "stale")  # the states that count as evidence
DEFAULTS = {"mode": "shadow", "window_days": 90, "horizon_days": 14, "half_life_days": 30, "prior_strength": 4,
            "min_resolved": 8, "backlog_weeks": {"slow": 4, "hold": 12}, "working_labels": [], "loops": {}}
REJECT_REASONS = ("not_planned", "duplicate")
SIMULATIONS = 4000


class ConfigError(ValueError):
    """`_data/fleet.yml` `learning:` says something this module cannot act on."""


class LakeError(RuntimeError):
    """The lake cannot be read; the message says what to run."""


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_fleet(root: Path) -> dict:
    try:
        return yamlio.load(root / "_data" / "fleet.yml") or {}
    except (OSError, yaml.YAMLError):
        return {}


def load_config(fleet: dict) -> dict:
    raw = fleet.get("learning")
    if not isinstance(raw, dict):
        raise ConfigError("_data/fleet.yml has no `learning:` block")
    cfg = {**DEFAULTS, **raw}
    if cfg["mode"] not in MODES:
        raise ConfigError(f"learning.mode is {cfg['mode']!r}; only {', '.join(MODES)} exists (ADR 0010)")
    for key in ("window_days", "horizon_days", "half_life_days", "prior_strength", "min_resolved"):
        if not isinstance(cfg[key], (int, float)) or isinstance(cfg[key], bool) or cfg[key] <= 0:
            raise ConfigError(f"learning.{key} must be a positive number")
    weeks = cfg["backlog_weeks"]
    if not isinstance(weeks, dict) or not 0 < weeks.get("slow", 0) < weeks.get("hold", 0):
        raise ConfigError("learning.backlog_weeks needs 0 < slow < hold")
    loops = cfg["loops"]
    if not isinstance(loops, dict) or not loops:
        raise ConfigError("learning.loops names no loop")
    for name, rule in loops.items():
        if not isinstance(rule, dict) or rule.get("kind") not in ("issue", "pr"):
            raise ConfigError(f"learning.loops.{name}.kind must be issue or pr")
        if not (rule.get("labels") or rule.get("any_labels")):
            raise ConfigError(f"learning.loops.{name} needs `labels` (all of them) or `any_labels` (one of them)")
    cfg["working_labels"] = [str(x) for x in cfg["working_labels"] or []]
    return cfg


# --------------------------------------------------------------------------- #
# items: one issue or pull request, from the lake or from a search export
# --------------------------------------------------------------------------- #
def parse_ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def normalise(row: dict) -> dict:
    labels = row.get("labels") or []
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except ValueError:
            labels = []
    return {"nwo": str(row.get("nwo") or ""), "number": int(row.get("number") or 0),
            "is_pr": bool(row.get("is_pr")), "state": str(row.get("state") or ""),
            "state_reason": row.get("state_reason") or None, "merged_at": parse_ts(row.get("merged_at")),
            "created_at": parse_ts(row.get("created_at")), "closed_at": parse_ts(row.get("closed_at")),
            "labels": [str(x) for x in labels], "title": str(row.get("title") or "")[:200],
            "url": row.get("html_url") or row.get("url")}


def read_items_file(path: Path) -> list[dict]:
    """A search export: one JSON object per line with the lake's column names."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(normalise(json.loads(line)))
    return rows


def lake_path(root: Path) -> Path:
    """Where `tools/dash lake` keeps it: DASH_LAKE_DIR, else .dash-lake/ at the repo root."""
    return Path(os.environ.get("DASH_LAKE_DIR") or (root / ".dash-lake")) / "fleet.sqlite"


def read_lake(path: Path, since: dt.datetime) -> tuple[list[dict], dict]:
    """(items, facts) from the lake, opened read-only. `facts` says whether the
    outcome columns exist yet: a lake synced before they were added has none,
    and its closed rows read as `unread` until `lake sync` runs again."""
    if not path.is_file():
        raise LakeError(f"no lake at {path}: `tools/dash lake sync` builds one (or pass --lake FILE)")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        have = {r[1] for r in conn.execute("PRAGMA table_info(issues)")}
        if not have:
            raise LakeError(f"the lake at {path} has no `issues` table: run `tools/dash lake sync`")
        cols = [c for c in ("nwo", "number", "title", "state", "is_pr", "labels", "created_at", "closed_at",
                            "html_url", "state_reason", "merged_at") if c in have]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM issues WHERE created_at >= ?",
                            (since.strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchall()
        facts = {"path": str(path), "outcome_columns": {"state_reason", "merged_at"} <= have, "rows": len(rows)}
        return [normalise(dict(r)) for r in rows], facts
    finally:
        conn.close()


def read_costs(path: Path, since: dt.datetime, hub: str) -> dict[str, dict]:
    """workflow file name -> {usd, runs} for the hub's agent runs in the window."""
    if not path.is_file():
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT r.workflow_path, COALESCE(SUM(a.cost_usd), 0), COUNT(a.run_id), COUNT(*) "
            "FROM runs r LEFT JOIN agent_runs a ON a.run_id = r.id AND a.cost_usd IS NOT NULL "
            "WHERE r.nwo = ? AND r.created_at >= ? GROUP BY r.workflow_path",
            (hub, since.strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    # `runs_read` of `runs` carry a cost the lake has read: the total is a floor, not the bill
    return {Path(str(p)).name: {"usd": round(float(usd), 2), "runs_read": int(n), "runs": int(total)}
            for p, usd, n, total in rows if p and n}


# --------------------------------------------------------------------------- #
# outcomes
# --------------------------------------------------------------------------- #
def attribute(item: dict, cfg: dict) -> list[str]:
    """Every loop whose rule the item matches. One issue can be the scout's
    proposal and the pipeline's implementation: it is an outcome of both."""
    labels = set(item["labels"])
    out = []
    for name, rule in cfg["loops"].items():
        if (rule["kind"] == "pr") != item["is_pr"]:
            continue
        if rule.get("labels") and not set(rule["labels"]) <= labels:
            continue
        if rule.get("any_labels") and not set(rule["any_labels"]) & labels:
            continue
        out.append(name)
    return out


def classify(item: dict, cfg: dict, now: dt.datetime) -> str:
    if item["is_pr"] and item["merged_at"]:
        return "landed"
    if item["state"] == "closed":
        if item["is_pr"]:
            # a closed pull request with no merge time is rejected only when the lake stores merge times
            return "rejected" if item.get("_outcomes_known", True) else "unread"
        if item["state_reason"] == "completed":
            return "landed"
        if item["state_reason"] in REJECT_REASONS:
            return "rejected"
        return "unread"
    if set(cfg["working_labels"]) & set(item["labels"]):
        return "working"
    age = (now - item["created_at"]).total_seconds() / 86400 if item["created_at"] else 0
    return "stale" if age >= cfg["horizon_days"] else "young"


def decided_at(item: dict, state: str, cfg: dict) -> dt.datetime | None:
    """When the outcome became known: the merge or close, or — for a stale
    item — the day its horizon ran out."""
    if state == "landed":
        return item["merged_at"] or item["closed_at"]
    if state == "rejected":
        return item["closed_at"]
    if state == "stale" and item["created_at"]:
        return item["created_at"] + dt.timedelta(days=cfg["horizon_days"])
    return None


def outcomes(items: list[dict], cfg: dict, now: dt.datetime) -> list[dict]:
    out = []
    for item in items:
        loops = attribute(item, cfg)
        if not loops or not item["created_at"]:
            continue
        state = classify(item, cfg, now)
        row = {"key": f"{item['nwo']}#{item['number']}", "arm": item["nwo"], "state": state,
               "created_at": item["created_at"], "decided_at": decided_at(item, state, cfg),
               "title": item["title"], "url": item["url"]}
        out.extend({**row, "loop": loop} for loop in loops)
    return out


# --------------------------------------------------------------------------- #
# the estimate
# --------------------------------------------------------------------------- #
def decay(age_days: float, half_life: float) -> float:
    return 0.5 ** (max(age_days, 0.0) / half_life)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_quantile(q: float, a: float, b: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def weigh(rows: list[dict], at: dt.datetime, cfg: dict) -> tuple[float, float]:
    """(weighted landed, weighted not landed) among the rows whose outcome was known by `at`."""
    won = lost = 0.0
    for r in rows:
        if r["state"] not in RESOLVED or r["decided_at"] is None or r["decided_at"] > at:
            continue
        w = decay((at - r["decided_at"]).total_seconds() / 86400, cfg["half_life_days"])
        if r["state"] == "landed":
            won += w
        else:
            lost += w
    return won, lost


def prior(rows: list[dict], at: dt.datetime, cfg: dict) -> tuple[float, float]:
    """The loop's own rate, worth `prior_strength` observations (and 1/2 with no history at all)."""
    won, lost = weigh(rows, at, cfg)
    rate = (won + 1.0) / (won + lost + 2.0)
    k = float(cfg["prior_strength"])
    return k * rate, k * (1.0 - rate)


def estimate(arm_rows: list[dict], loop_rows: list[dict], at: dt.datetime, cfg: dict) -> dict:
    a0, b0 = prior(loop_rows, at, cfg)
    won, lost = weigh(arm_rows, at, cfg)
    a, b = a0 + won, b0 + lost
    return {"a": round(a, 4), "b": round(b, 4), "mean": round(a / (a + b), 4),
            "low": round(beta_quantile(0.05, a, b), 4), "high": round(beta_quantile(0.95, a, b), 4),
            "evidence": round(won + lost, 2)}


def counts(rows: list[dict]) -> dict:
    out = {s: 0 for s in STATES}
    for r in rows:
        out[r["state"]] += 1
    return out


def pressure(rows: list[dict], now: dt.datetime, cfg: dict) -> dict:
    """How much unresolved output a loop has against how fast its output lands.
    `weeks` is the backlog divided by the landing rate of the last four weeks."""
    c = counts(rows)
    open_now = c["stale"] + c["young"] + c["working"]
    since = now - dt.timedelta(days=28)
    recent = sum(1 for r in rows if r["state"] == "landed" and r["decided_at"] and r["decided_at"] >= since)
    per_week = recent / 4.0
    weeks = round(open_now / per_week, 1) if per_week else None
    limits = cfg["backlog_weeks"]
    if c["unread"]:
        advice = "unread"  # closed outputs whose outcome the lake has not stored: no rate to judge by
    elif open_now == 0:
        advice = "file"
    elif weeks is None or weeks >= limits["hold"]:
        advice = "hold"
    elif weeks >= limits["slow"]:
        advice = "slow"
    else:
        advice = "file"
    return {"open": open_now, "landed_per_week": round(per_week, 2), "weeks": weeks, "advice": advice}


def median_days(rows: list[dict]) -> float | None:
    spans = sorted((r["decided_at"] - r["created_at"]).total_seconds() / 86400 for r in rows
                   if r["state"] == "landed" and r["decided_at"])
    if not spans:
        return None
    mid = len(spans) // 2
    return round(spans[mid] if len(spans) % 2 else (spans[mid - 1] + spans[mid]) / 2, 1)


def loop_status(name: str, rows: list[dict], now: dt.datetime, cfg: dict, cost: dict | None = None) -> dict:
    c = counts(rows)
    resolved = sum(c[s] for s in RESOLVED)
    arms = []
    for arm in sorted({r["arm"] for r in rows}):
        arm_rows = [r for r in rows if r["arm"] == arm]
        arms.append({"arm": arm, "counts": counts(arm_rows), "estimate": estimate(arm_rows, rows, now, cfg)})
    arms.sort(key=lambda x: (-x["estimate"]["mean"], x["arm"]))
    doc = {"loop": name, "outputs": len(rows), "counts": c, "resolved": resolved,
           "landed_pct": round(100.0 * c["landed"] / resolved, 1) if resolved else None,
           "estimate": estimate(rows, rows, now, cfg), "median_days_to_land": median_days(rows),
           "pressure": pressure(rows, now, cfg), "enough": resolved >= cfg["min_resolved"], "arms": arms}
    if cost:
        per = round(cost["usd"] / c["landed"], 2) if c["landed"] and not c["unread"] else None
        doc["cost"] = {**cost, "usd_per_landed": per, "label": COST_LABEL}
    return doc


# --------------------------------------------------------------------------- #
# plan (Thompson sampling) and replay (the skill test)
# --------------------------------------------------------------------------- #
def plan(name: str, rows: list[dict], now: dt.datetime, cfg: dict, slots: int = 5,
         candidates: list[str] | None = None, seed: str | None = None) -> dict:
    """The share of the next `slots` each arm would get: the probability that
    its landing rate is the highest, from SIMULATIONS draws of every arm's
    estimate. An arm with no history draws from the loop's prior, so it keeps
    a share (exploration) until evidence says otherwise."""
    arms = sorted({r["arm"] for r in rows} | set(candidates or []))
    if not arms:
        return {"loop": name, "slots": slots, "arms": [], "seed": seed, "note": "no arm to choose between"}
    est = {arm: estimate([r for r in rows if r["arm"] == arm], rows, now, cfg) for arm in arms}
    seed = seed or f"{now.date().isoformat()}:{name}"
    rng = random.Random(seed)
    wins = {arm: 0 for arm in arms}
    for _ in range(SIMULATIONS):
        best = max(arms, key=lambda arm: rng.betavariate(est[arm]["a"], est[arm]["b"]))
        wins[best] += 1
    recent = now - dt.timedelta(days=cfg["horizon_days"])
    filed = {arm: sum(1 for r in rows if r["arm"] == arm and r["created_at"] >= recent) for arm in arms}
    total_filed = sum(filed.values())
    out = []
    for arm in arms:
        share = wins[arm] / SIMULATIONS
        out.append({"arm": arm, "share": round(share, 4), "slots": round(share * slots, 2),
                    "mean": est[arm]["mean"], "low": est[arm]["low"], "high": est[arm]["high"],
                    "evidence": est[arm]["evidence"],
                    "filed_recently": filed[arm],
                    "actual_share": round(filed[arm] / total_filed, 4) if total_filed else None})
    out.sort(key=lambda x: (-x["share"], -x["mean"], x["arm"]))
    resolved = sum(1 for r in rows if r["state"] in RESOLVED)
    return {"loop": name, "mode": cfg["mode"], "slots": slots, "seed": seed, "arms": out,
            "enough": resolved >= cfg["min_resolved"], "pressure": pressure(rows, now, cfg),
            "note": "shadow: this plan steers nothing; the loop still follows its own rule"}


def replay(name: str, rows: list[dict], cfg: dict) -> dict:
    """Prequential test: for each resolved output, in the order the outputs were
    filed, predict it from what was known the day it was filed — once with its
    arm's estimate, once with the loop's plain average — and score both (Brier).
    Skill above zero means knowing the arm helped."""
    done = sorted((r for r in rows if r["state"] in RESOLVED and r["decided_at"]),
                  key=lambda r: (r["created_at"], r["key"]))
    n, sq_arm, sq_base = 0, 0.0, 0.0
    for r in done:
        at = r["created_at"]
        a0, b0 = prior(rows, at, cfg)
        base = a0 / (a0 + b0)
        won, lost = weigh([x for x in rows if x["arm"] == r["arm"]], at, cfg)
        p = (a0 + won) / (a0 + b0 + won + lost)
        y = 1.0 if r["state"] == "landed" else 0.0
        sq_arm += (p - y) ** 2
        sq_base += (base - y) ** 2
        n += 1
    enough = n >= cfg["min_resolved"]
    arms = len({r["arm"] for r in rows})
    skill = round(1.0 - sq_arm / sq_base, 4) if n and sq_base > 0 and arms > 1 else None
    if arms < 2:
        verdict = "one arm: nothing to choose between"
    elif not enough:
        verdict = "not enough evidence"
    elif skill is not None and skill > 0:
        verdict = "the arm estimate predicts better than the loop average"
    else:
        verdict = "the arm estimate predicts no better than the loop average"
    return {"loop": name, "scored": n, "arms": arms, "brier_arm": round(sq_arm / n, 4) if n else None,
            "brier_loop": round(sq_base / n, 4) if n else None, "skill": skill, "enough": enough, "verdict": verdict}


# --------------------------------------------------------------------------- #
# the document every surface reads
# --------------------------------------------------------------------------- #
def registry_arms(root: Path, fleet: dict) -> list[str]:
    """The repos a loop could act on: the registry's own, active ones."""
    try:
        rows = yamlio.load(root / "_data" / "projects.yml") or []
    except (OSError, yaml.YAMLError):
        return []
    owners = {str(o).lower() for o in ((fleet.get("hub") or {}).get("owners") or [])}
    out = []
    for row in rows if isinstance(rows, list) else []:
        url = str((row or {}).get("repo_url") or "")
        nwo = url.split("github.com/", 1)[-1].removesuffix(".git").strip("/") if "github.com/" in url else ""
        if nwo and (not owners or nwo.split("/")[0].lower() in owners) and row.get("status") in (None, "active"):
            out.append(nwo)
    return sorted(set(out))


def backfill_command(cfg: dict) -> str:
    """The one-off sync that fills the outcome columns for the whole window: issues only, no job or log fetch."""
    return f"tools/dash lake sync --days {int(cfg['window_days'])} --jobs none --logs none --max-issues 2000"


def build(root: Path | str = ROOT_DEFAULT, *, items: list[dict] | None = None, lake: Path | None = None,
          now: dt.datetime | None = None, loop: str | None = None, slots: int = 5) -> dict:
    root = Path(root)
    now = now or dt.datetime.now(dt.timezone.utc)
    fleet = load_fleet(root)
    cfg = load_config(fleet)
    if loop and loop not in cfg["loops"]:
        raise ConfigError(f"no loop called {loop!r} in learning.loops (known: {', '.join(cfg['loops'])})")
    since = now - dt.timedelta(days=cfg["window_days"])
    hub = str((fleet.get("hub") or {}).get("repo") or "bamr87/bamr87")
    source: dict = {"kind": "items", "rows": len(items or [])}
    costs: dict = {}
    if items is None:
        path = lake or lake_path(root)
        items, source = read_lake(path, since)
        source["kind"] = "lake"
        costs = read_costs(path, since, hub)
    known = bool(source.get("outcome_columns", True))
    items = [dict(i, _outcomes_known=known) for i in items if i["created_at"] and i["created_at"] >= since]
    rows = outcomes(items, cfg, now)
    arms = registry_arms(root, fleet)
    loops = []
    for name, rule in cfg["loops"].items():
        if loop and name != loop:
            continue
        mine = [r for r in rows if r["loop"] == name]
        cost = costs.get(Path(str(rule.get("workflow") or "")).name) if rule.get("workflow") else None
        doc = loop_status(name, mine, now, cfg, cost)
        doc["rule"] = {k: rule[k] for k in ("kind", "labels", "any_labels", "workflow", "arms") if k in rule}
        doc["plan"] = plan(name, mine, now, cfg, slots, arms if rule.get("arms") == "registry" else None)
        doc["replay"] = replay(name, mine, cfg)
        loops.append(doc)
    unread = sum(d["counts"]["unread"] for d in loops)
    notes = []
    if not known:
        notes.append("this lake was synced before it stored why an issue closed or whether a pull request merged: "
                     f"closed outputs read as `unread` until `{backfill_command(cfg)}` runs")
    elif unread:
        notes.append(f"{unread} closed output(s) have no stored reason yet; `{backfill_command(cfg)}` reads them")
    return {"schema": SCHEMA, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": cfg["mode"],
            "config": {k: cfg[k] for k in ("window_days", "horizon_days", "half_life_days", "prior_strength",
                                           "min_resolved", "backlog_weeks", "working_labels")},
            "source": source, "loops": loops, "notes": notes, "cost_label": COST_LABEL}


def view(root: Path | str = ROOT_DEFAULT, loop: str = "", slots: int = 5, limit: int = 12,
         lake: Path | None = None, now: dt.datetime | None = None) -> dict:
    """The document /api/learn and the MCP's fleet_learning serve: `build`, with
    each loop's arm lists cut to `limit` (the counts stay whole). A lake that
    cannot be read is an answer, not an error: `available: false` and why."""
    limit = max(1, min(int(limit), 200))
    try:
        doc = build(root, lake=lake, now=now, loop=loop or None, slots=max(1, min(int(slots), 50)))
    except LakeError as exc:
        return {"schema": SCHEMA, "available": False, "reason": str(exc), "mode": "shadow", "loops": [],
                "cost_label": COST_LABEL}
    for lp in doc["loops"]:
        lp["arm_count"] = len(lp["arms"])
        lp["arms"] = lp["arms"][:limit]
        lp["plan"]["arm_count"] = len(lp["plan"]["arms"])
        lp["plan"]["arms"] = lp["plan"]["arms"][:limit]
    return doc | {"available": True}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _pct(x: float | None) -> str:
    return "  —  " if x is None else f"{100 * x:4.0f}%"


def print_status(doc: dict) -> None:
    cfg = doc["config"]
    print(f"outcome learning · {doc['mode']} · last {cfg['window_days']} days · an output is stale after "
          f"{cfg['horizon_days']} days · {doc['source']['kind']} ({doc['source'].get('rows', 0)} rows)")
    for note in doc["notes"]:
        print(f"  note: {note}")
    print(f"  {'loop':<16} {'out':>4} {'land':>5} {'rej':>4} {'stale':>5} {'work':>5} {'young':>5} {'unrd':>5}  "
          f"{'lands':>5}  {'90% range':<11} {'days':>5}  {'backlog':<22} advice")
    for lp in doc["loops"]:
        c, e, p = lp["counts"], lp["estimate"], lp["pressure"]
        if not p["open"]:
            backlog = "none open"
        elif p["advice"] == "unread":
            backlog = f"{p['open']} open"
        elif p["weeks"] is None:
            backlog = f"{p['open']} open, none landed"
        else:
            backlog = f"{p['open']} open, {p['weeks']} wk"
        days = "—" if lp["median_days_to_land"] is None else lp["median_days_to_land"]
        rng = f"{100 * e['low']:.0f}–{100 * e['high']:.0f}%" if lp["resolved"] else "—"
        few = "" if lp["enough"] else "  (too few resolved to trust)"
        print(f"  {lp['loop']:<16} {lp['outputs']:>4} {c['landed']:>5} {c['rejected']:>4} {c['stale']:>5} "
              f"{c['working']:>5} {c['young']:>5} {c['unread']:>5}  {_pct(e['mean'] if lp['resolved'] else None)}  "
              f"{rng:<11} {days!s:>5}  {backlog:<22} {p['advice']}{few}")
        if lp.get("cost"):
            cost = lp["cost"]
            per = "" if cost["usd_per_landed"] is None else f", ${cost['usd_per_landed']:.2f} per landed output"
            print(f"  {'':<16} ${cost['usd']:.2f} read from {cost['runs_read']} of {cost['runs']} run(s) in the lake"
                  f"{per} — {doc['cost_label']}, a floor")


def print_plan(doc: dict, top: int) -> None:
    for lp in doc["loops"]:
        pl, rp = lp["plan"], lp["replay"]
        print(f"{lp['loop']} — next {pl['slots']} slot(s), {pl.get('mode', doc['mode'])} (seed {pl['seed']})")
        if not pl["arms"]:
            print("  no arm to choose between")
            continue
        if not pl["enough"]:
            print(f"  not enough evidence yet ({lp['resolved']} resolved, {doc['config']['min_resolved']} needed): "
                  "every arm sits near the loop's average")
        print(f"  {'arm':<34} {'share':>6} {'slots':>6} {'lands':>6}  {'90% range':<10} {'evidence':>8}  filed lately")
        for a in pl["arms"][:top]:
            actual = "" if a["actual_share"] is None else f" ({100 * a['actual_share']:.0f}% of the loop's)"
            print(f"  {a['arm']:<34} {_pct(a['share'])} {a['slots']:>6.2f} {_pct(a['mean'])}  "
                  f"{100 * a['low']:.0f}–{100 * a['high']:.0f}%{'':<3} {a['evidence']:>8}  "
                  f"{a['filed_recently']}{actual}")
        if len(pl["arms"]) > top:
            print(f"  … {len(pl['arms']) - top} more arm(s) (--top N, or --json)")
        skill = "—" if rp["skill"] is None else f"{rp['skill']:+.2f}"
        print(f"  replay: {rp['verdict']} (skill {skill} over {rp['scored']} scored output(s))")
        print(f"  pressure: {lp['pressure']['advice']} — {lp['pressure']['open']} open, "
              f"{lp['pressure']['landed_per_week']} landing a week")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dash learn",
        description="Outcome learning (shadow): what happened to each loop's output, and where its next slots "
                    "would pay. Reads the local lake; writes nothing; steers nothing.")
    ap.add_argument("cmd", nargs="?", default="status", choices=("status", "plan", "replay"))
    ap.add_argument("--loop", help="one loop of learning.loops")
    ap.add_argument("--slots", type=int, default=5, help="how many next slots to share out (plan)")
    ap.add_argument("--top", type=int, default=12, help="arms to print per loop (plan)")
    ap.add_argument("--lake", help="the lake file (default .dash-lake/fleet.sqlite)")
    ap.add_argument("--items", help="read a search export (JSON lines) instead of the lake")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    ap.add_argument("--root", default=str(ROOT_DEFAULT), help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", help="print JSON")
    a = ap.parse_args(argv)
    try:
        items = read_items_file(Path(a.items)) if a.items else None
        doc = build(a.root, items=items, lake=Path(a.lake) if a.lake else None, now=parse_ts(a.now),
                    loop=a.loop, slots=max(1, a.slots))
    except (ConfigError, LakeError) as exc:
        print(f"dash learn: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"dash learn: cannot read {a.items or 'the lake'}: {exc}", file=sys.stderr)
        return 2
    if a.json:
        if a.cmd == "replay":
            doc = {"schema": doc["schema"], "generated_at": doc["generated_at"],
                   "loops": [lp["replay"] for lp in doc["loops"]]}
        print(json.dumps(doc, indent=1, default=str))
    elif a.cmd == "status":
        print_status(doc)
    elif a.cmd == "plan":
        print_plan(doc, max(1, a.top))
    else:
        for lp in doc["loops"]:
            rp = lp["replay"]
            skill = "—" if rp["skill"] is None else f"{rp['skill']:+.4f}"
            print(f"  {lp['loop']:<16} scored {rp['scored']:>4} over {rp['arms']:>2} arm(s)  "
                  f"brier: arm {rp['brier_arm']} loop {rp['brier_loop']}  skill {skill}  {rp['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

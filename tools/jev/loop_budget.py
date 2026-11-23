#!/usr/bin/env python3
"""
File: tools/jev/loop_budget.py
Description: The loop runner's monthly ceiling (tools/jev/loop.py; #486, ADR
             0002 P1): `_data/fleet.yml` `budget.loops` judged against the AI
             ledger `dash-gen ai-run` writes (DASH_AI_LEDGER). The ledger's
             local loop rows and the engine's own durable charges for an
             attempt that left no row (`<ledger>.loops-unledgered.jsonl`) make
             the month's position (`budget_position`, `local_spend`: an
             unreadable ledger, row or line refuses, it is never read as $0);
             `budget_lock` holds the month from the ceiling check until the
             attempt is ledgered; `charge` counts this run's own spend; and
             `_budget_dict` / `_sprint_budget` are the month and the active
             expedite sprint as the run record and `loop budget` show them.
             Moved here from loop.py unchanged; loop.py re-exports every name.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py (and loop_runs.py, loop_canary.py).
       Callers outside the engine import these names from tools.jev.loop
       (tools/jev/sprints.py reads `local_spend` that way, lazily).
Dependencies: Python 3.12 stdlib; tools/jev/ledger.py, tools/jev/sprints.py.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import math
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from . import sprints as sp
from .common import JevError, hub_repo
from .ledger import BudgetState, Ledger
from .loop_common import COST_LABEL, iso, now_utc
from .spec import StepSpecError

if TYPE_CHECKING:   # annotations only: the engine imports this module, never the reverse
    from .loop import RunContext


def ledger_path() -> Path:
    """The AI ledger ai-run writes one row per invocation to (DASH_AI_LEDGER)."""
    return Path(os.environ.get("DASH_AI_LEDGER") or "~/.claude/ai-activity-ledger.json").expanduser()


def loops_budget(fleet: dict) -> tuple[float, int]:
    """`_data/fleet.yml` `budget.loops`: (monthly_usd, scheduled_stop_pct)."""
    b = ((fleet.get("budget") or {}).get("loops") or {})
    usd, pct = b.get("monthly_usd"), b.get("scheduled_stop_pct")
    if (not isinstance(usd, (int, float)) or isinstance(usd, bool) or not math.isfinite(usd) or usd <= 0
            or not isinstance(pct, int) or isinstance(pct, bool) or not 0 < pct <= 100):
        raise StepSpecError("_data/fleet.yml budget.loops needs a finite monthly_usd > 0 and scheduled_stop_pct in "
                            "1..100 — the local loops' monthly ceiling")
    return float(usd), pct


def _utc_month(ts: str) -> str | None:
    try:
        t = dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=dt.UTC)).astimezone(dt.UTC).strftime("%Y-%m")


#: dash-gen ai_activity.LEDGER_VERSION (this package never imports dash-gen;
#: tools/test_jev_loop.py holds the two equal)
LEDGER_VERSION = 1


def unledgered_path(ledger: Path | None = None) -> Path:
    """Beside the AI ledger (never pruned with the runs): the engine's own
    charge for an attempt whose ai-run left no ledger row — it died, the
    backstop killed it, or its ledger write failed. budget_position counts
    each one whose attempt_id the ledger does not have, so a later run, and
    the canary, see that spend."""
    p = ledger or ledger_path()
    return p.with_name(p.name + ".loops-unledgered.jsonl")


def record_unledgered(ctx: RunContext, row: dict, attempt_id: str, cost: float, source: str) -> None:
    """Make an unledgered charge durable (under budget_lock, which the attempt
    holds); kept in this run's memory as well only if the file cannot take it."""
    # `repo` (the item's owner/repo, as ai-run's rows carry it) lets an expedite sprint count the charge
    line = {"timestamp": iso(), "origin": "local", "loop": ctx.spec.loop, "step": ctx.spec.step,
            "run_id": ctx.run.run_id, "attempt_id": attempt_id, "item": row.get("item"), "repo": row.get("nwo"),
            "cost_usd": round(cost, 6), "cost_source": source}
    try:
        fd = os.open(unledgered_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"jev loop: ! could not record the unledgered ${cost:g} charge in {unledgered_path()} ({exc}) — "
              "only this run counts it", file=sys.stderr)
        ctx.unledgered.append((cost, source))


def budget_position(fleet: dict, *, scheduled: bool, path: Path | None = None,
                    month: str | None = None) -> BudgetState:
    """Where this UTC month stands against `budget.loops`, from the AI ledger's
    rows with `origin: local` and a `loop` field (a plain `dash ai run` has
    none, so hand runs never count against the loops) — the same BudgetState
    arithmetic as the conflict engine. A ledger that exists but cannot be read
    (not JSON, not an object, another version) refuses: an unreadable ledger is
    not an empty month, and ai_activity's writers refuse to overwrite one."""
    cap, pct = loops_budget(fleet)
    m = month or now_utc().strftime("%Y-%m")
    spent, estimated = local_spend(lambda rec: _utc_month(str(rec.get("timestamp") or "")) == m, path)
    return BudgetState(month=m, spent_usd=round(spent, 4), estimated_usd=round(estimated, 4), cap_usd=cap,
                       stop_usd=round(cap * pct / 100.0, 4), scheduled=scheduled)


def local_spend(keep, path: Path | None = None) -> tuple[float, float]:
    """(spent, estimated) over the AI ledger's local loop rows (`origin:
    local` with a `loop` field) that `keep(row)` accepts, plus the engine's
    unledgered charges it accepts that the ledger has no row for. The monthly
    ceiling keeps one UTC month; an expedite sprint keeps its repositories
    inside its time box (tools/jev/sprints.py). A row's cost is read only once
    `keep` accepts it, and an unreadable ledger refuses."""
    p = path or ledger_path()
    rows: dict = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise JevError(f"the AI ledger {p} cannot be read ({exc}) — the monthly ceiling cannot be judged; repair "
                           "it in place (moved aside, the month would read as $0)") from exc
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            found = f"version {data.get('version')!r}" if isinstance(data, dict) else f"a JSON {type(data).__name__}"
            raise JevError(f"the AI ledger {p} is {found}, not version {LEDGER_VERSION} — the monthly ceiling cannot "
                           "be judged; migrate it in place (moved aside, the month would read as $0)")
        rows = data.get("runs") or {}
        if not isinstance(rows, dict):     # every row skipped would read as $0 spent
            raise JevError(f"the AI ledger {p} has a `runs` that is a JSON {type(rows).__name__}, not an object — "
                           "the monthly ceiling cannot be judged; repair it in place")
    spent = estimated = 0.0
    for rec in rows.values():
        if not isinstance(rec, dict) or rec.get("origin") != "local" or not rec.get("loop"):
            continue
        if not keep(rec):
            continue
        cost = _ledger_cost(rec, p)
        spent += cost
        if rec.get("cost_source") == "estimated":
            estimated += cost
    ledgered = {str(r.get("attempt_id")) for r in rows.values() if isinstance(r, dict) and r.get("attempt_id")}
    for rec in _unledgered_rows(unledgered_path(p)):
        if str(rec.get("attempt_id")) in ledgered or not keep(rec):
            continue
        spent += rec["cost_usd"]
        if rec.get("cost_source") == "estimated":
            estimated += rec["cost_usd"]
    return round(spent, 4), round(estimated, 4)


def _spend(value) -> float | None:
    """A spend figure the ceiling can add: finite and not negative. JSON reads
    `NaN` and `Infinity`, and one NaN would make every later comparison with
    the ceiling false, which reads as "fits"; a negative figure would give
    spend back."""
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if math.isfinite(cost) and cost >= 0 else None


def _ledger_cost(rec: dict, p: Path) -> float:
    """A ledger row's cost; an unreadable figure is charged at its cap, and one
    with no readable cap either refuses like an unreadable ledger. Only a
    finite cap above 0 stands in: a missing, null or $0 cap would charge the
    row $0, which is room, not a charge (ai-run writes the positive cap it
    handed claude on every row)."""
    cost = _spend(rec.get("total_cost_usd") or 0.0)
    if cost is None:
        cost = _spend(rec.get("cap_usd")) or None
    if cost is None:
        raise JevError(f"the AI ledger {p} has a row ({rec.get('session_id') or rec.get('attempt_id') or '?'}) whose "
                       "cost and cap are both unreadable — the monthly ceiling cannot be judged; repair it in place")
    return cost


def _unledgered_rows(p: Path) -> list[dict]:
    """The engine's durable unledgered charges; a line that cannot be read
    refuses like an unreadable ledger (it is spend, not noise)."""
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise JevError(f"{p} cannot be read ({exc}) — the monthly ceiling cannot be judged") from exc
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            cost = _spend(rec["cost_usd"])
            if cost is None:
                raise ValueError(f"cost_usd {rec['cost_usd']!r} is not a finite figure of 0 or more")
            rec["cost_usd"] = cost
        except (ValueError, TypeError, KeyError) as exc:
            raise JevError(f"{p} line {n} cannot be read ({exc}) — the monthly ceiling cannot be judged; repair "
                           "the line, never drop it (it is this month's spend)") from exc
        out.append(rec)
    return out


def charge(state: BudgetState, cost: float, source: str | None) -> None:
    """This run's own spend, counted as it happens (the ledger has it too)."""
    state.spent_usd = round(state.spent_usd + cost, 4)
    if source == "estimated":
        state.estimated_usd = round(state.estimated_usd + cost, 4)


@contextlib.contextmanager
def budget_lock() -> Iterator[bool]:
    """Held from the ceiling check until ai-run has ledgered the attempt (or the
    canary), so concurrent runs — of any step, from any checkout of the hub —
    cannot each pass `affords()` on the same month. It lives beside the shared
    AI ledger, not under this checkout's runs directory. Never waits: True when
    this process holds it, False when another attempt does."""
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.with_name(p.name + ".loops.lock").open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = False
        else:
            held = True
        try:
            yield held
        finally:
            if held:
                fcntl.flock(fh, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# the month and the sprint as the run record and `loop budget` show them
# --------------------------------------------------------------------------- #
def _budget_dict(state: BudgetState | None) -> dict:
    if state is None:
        return {}
    return {"month": state.month, "spent_usd": state.spent_usd, "estimated_usd": state.estimated_usd,
            "cap_usd": state.cap_usd, "ceiling_usd": state.ceiling_usd, "scheduled": state.scheduled,
            "label": COST_LABEL}


def _sprint_budget(fleet: dict) -> dict:
    """The active expedite sprint against its ceiling (tools/jev/sprints.py),
    for `loop budget`; `error` when budget.sprints or a ledger cannot be read."""
    try:
        sprints = sp.load_sprints(fleet)
        s = sp.active(sprints, now_utc())
        if s is None:
            return {"active": None, "declared": len(sprints),
                    "line": f"no active expedite sprint ({len(sprints)} declared)"}
        spent = sp.spend(s, ai_ledger=ledger_path(), jev=Ledger.load(), ci=sp.ci_rows(), pipeline=sp.pipeline_rows(),
                         hub=hub_repo(fleet))
        return {"active": s.as_dict(), "declared": len(sprints), **spent.as_dict(),
                "line": f"{s.slug}: {spent.summary(s)}; its time box ends {sp.iso(s.ends)}"}
    except JevError as exc:
        return {"error": str(exc), "line": f"cannot be judged: {exc}"}

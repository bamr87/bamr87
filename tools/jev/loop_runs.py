#!/usr/bin/env python3
"""
File: tools/jev/loop_runs.py
Description: The loop runner's run directory and its history (tools/jev/loop.py;
             #486, ADR 0002 P1): `.fleet/runs/<run_id>/` (0700: run.json,
             attempts.jsonl, summary.md, plan/, items/) as `RunDir`; earlier
             runs' attempts.jsonl as `History`, tier 0's memory and the
             record of what was already filed; `prune`, which keeps the
             newest KEEP_RUNS runs; `step_lock`, one run per loop step at a
             time; and how a run's record ends (`_finish`: the totals,
             summary.md, the LATEST pointer, the prune, the lines printed).
             Moved here from loop.py unchanged; loop.py re-exports every name.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py (and loop_publish.py, for `RunDir`).
       Callers outside the engine import these names from tools.jev.loop.
Dependencies: Python 3.12 stdlib.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from . import workspace as wsp
from .adapters import REUSE_DAYS
from .common import JevError
from .loop_budget import _budget_dict
from .loop_common import COST_LABEL, iso, now_utc, read_json, runs_dir, write_json
from .spec import StepSpec

if TYPE_CHECKING:   # annotations only: the engine imports this module, never the reverse
    from .loop import RunContext

RUN_SCHEMA = "jev-loop-run/v1"
ATTEMPT_SCHEMA = "jev-loop-attempt/v1"
KEEP_RUNS = 30


class RunDir:
    """`.fleet/runs/<run_id>/` — run.json, attempts.jsonl, summary.md, plan/, items/."""

    def __init__(self, path: Path):
        self.path = path
        self.run_id = path.name

    @classmethod
    def new(cls, loop: str, step: str, run_id: str | None = None) -> RunDir:
        rid = run_id or f"{now_utc():%Y%m%dT%H%M%SZ}-{loop}-{step}-{uuid.uuid4().hex[:6]}"
        base = runs_dir()
        base.mkdir(parents=True, exist_ok=True)
        base.chmod(0o700)   # run records hold repository content, private repos' included
        path = base / rid
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise JevError(f"run {rid} already exists") from exc
        return cls(path)

    @classmethod
    def load(cls, run_id: str) -> RunDir:
        if not wsp.RUN_ID_RX.fullmatch(run_id or ""):
            raise JevError(f"{run_id!r} is not a run id")
        path = runs_dir() / run_id
        if not (path / "run.json").is_file():
            raise JevError(f"no run {run_id} under {runs_dir()}")
        return cls(path)

    def write_json(self, rel: str, obj: object) -> Path:
        p = self.path / rel
        write_json(p, obj)
        return p

    def append_attempt(self, row: dict) -> None:
        with (self.path / "attempts.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"schema": ATTEMPT_SCHEMA, "ts": iso(), **row}, sort_keys=True, default=str) + "\n")


class History:
    """Earlier runs' attempts.jsonl — tier 0's memory."""

    def __init__(self, base: Path | None = None):
        self.base = base or runs_dir()

    def rows(self) -> Iterator[tuple[str, dict]]:
        for f in sorted(self.base.glob("*/attempts.jsonl")):
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield f.parent.name, row

    def completed(self, spec: StepSpec, item_key: str, reuse_key: str, *, within_days: int = REUSE_DAYS
                  ) -> dict | None:
        """The newest completed (`attempt`, outcome ok, validated) attempt of this
        item with this reuse key within `within_days`, and whether it was published.

        A publish is matched to the attempt by CONTENT, not by run: a later run
        that reused this attempt's outputs (tier 0) and filed them writes its
        `publish-apply` row in its own run directory. The row contract: every
        `publish-apply` row (`loop run --apply`, `loop publish --apply`) carries
        the `validated_sha256` of the file it published."""
        horizon = now_utc() - dt.timedelta(days=within_days)
        best: dict | None = None
        published: set[str] = set()
        for run_id, row in self.rows():
            if row.get("loop") != spec.loop or row.get("step") != spec.step or row.get("item") != item_key:
                continue
            if row.get("decision") == "publish-apply" and row.get("published") and row.get("validated_sha256"):
                published.add(str(row["validated_sha256"]))
            if (row.get("decision") != "attempt" or row.get("outcome") != "ok"
                    or row.get("reuse_key") != reuse_key or not row.get("validated_sha256")):
                continue
            try:
                ts = dt.datetime.strptime(str(row.get("ts")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
            except ValueError:
                continue
            if ts < horizon:
                continue
            item_dir = self.base / run_id / "items" / wsp.item_dirname(item_key)
            if best is None or ts >= best["_ts"]:
                best = {"_ts": ts, "run_id": run_id, "date": ts.date().isoformat(), "item_dir": str(item_dir),
                        "validated_sha256": row["validated_sha256"], "validated_rel": row.get("validated_rel")}
        if best is None:
            return None
        best["published"] = best["validated_sha256"] in published
        best.pop("_ts")
        return best

    def published_run(self, spec: StepSpec, item_key: str, validated_sha256: str) -> str | None:
        """The run that already filed these validated bytes for this item (a
        `publish-apply` row with `published`, whole or partial), or None — so
        two previews of one attempt (a tier-0 reuse) cannot both be filed."""
        for run_id, row in self.rows():
            if (row.get("loop") == spec.loop and row.get("step") == spec.step and row.get("item") == item_key
                    and row.get("decision") == "publish-apply" and row.get("published")
                    and row.get("validated_sha256") == validated_sha256):
                return run_id
        return None


def prune(keep: int = KEEP_RUNS, *, current: str | None = None) -> list[str]:
    """Remove the oldest run directories beyond `keep` (only ones this engine
    wrote) — every run ends with this, so the newest KEEP_RUNS runs are kept."""
    base = runs_dir()
    runs = []
    for d in base.iterdir() if base.is_dir() else []:
        meta = read_json(d / "run.json") if d.is_dir() else {}
        if meta.get("schema") == RUN_SCHEMA and d.name != current:
            runs.append((str(meta.get("started") or ""), d))
    runs.sort()
    gone = []
    for _, d in runs[: max(0, len(runs) - (keep - 1 if current else keep))]:
        shutil.rmtree(d, ignore_errors=False)
        gone.append(d.name)
    return gone


class LockHeld(JevError):
    """Another run of the same loop step holds its lock."""


@contextlib.contextmanager
def step_lock(spec: StepSpec) -> Iterator[None]:
    """One run per loop step at a time (a second one exits 2, it never waits)."""
    locks = runs_dir() / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    fh = (locks / f"{spec.loop}-{spec.step}.lock").open("w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockHeld(f"{spec.loop}/{spec.step} is already running (lock {fh.name})") from exc
        yield
    finally:
        fh.close()


# --------------------------------------------------------------------------- #
# how a run's record ends: the totals, summary.md, LATEST, the prune
# --------------------------------------------------------------------------- #
def _totals(record: dict) -> dict:
    items = record.get("items") or []
    spent = round(sum(float(i.get("cost_usd") or 0) for i in items), 4)
    estimated = round(sum(float(i.get("cost_usd") or 0) for i in items if i.get("cost_source") == "estimated"), 4)
    return {"spent_usd": spent, "estimated_usd": estimated, "label": COST_LABEL,
            "attempts": sum(1 for i in items if i.get("outcome")),
            "published": sum(int(i.get("published") or 0) for i in items)}


def _summary(record: dict) -> str:
    t = record.get("totals") or {}
    spend = (f"- spend: ${t.get('spent_usd', 0):.2f} ({COST_LABEL})"
             + (f", ${t['estimated_usd']:.2f} of it charged at the cap" if t.get("estimated_usd") else "")
             + (" — a rehearsal makes no model call" if record["mode"] == "rehearse" else ""))
    lines = [f"# jev loop {record['loop']}/{record['step']} — {record['run_id']}", "",
             f"- mode: {record['mode']} · status: {record['status']} · exit {record['exit_code']}",
             f"- posture: {record['posture']['name']} (network none) · model {record['tier']['model']} · "
             f"turns {record['tier']['max_turns']} · cap ${record['tier']['cap_usd']:g} ({COST_LABEL})", spend]
    b = record.get("budget") or {}
    if b.get("after"):
        a = b["after"]
        lines.append(f"- month {a['month']}: ${a['spent_usd']:.2f} of the ${a['cap_usd']:g} budget.loops ceiling "
                     f"({COST_LABEL}; this run stops at ${a['ceiling_usd']:g})")
    if record.get("usage_limited"):
        lines.append("- usage limit reached: the credential is valid (capacity, not a defect); the rest was skipped")
    lines.append("")
    if record.get("hub", {}).get("dirty_paths"):
        lines.append(f"- dirty at start: {', '.join(record['hub']['dirty_paths'])}")
    for n in record.get("notes") or []:
        lines.append(f"- {n}")
    lines += ["", "| Item | Status | Cost | Reason |", "| --- | --- | --- | --- |"]
    for i in record.get("items") or []:
        cost = f"${float(i['cost_usd']):.4f} ({i.get('cost_source')})" if i.get("outcome") else "$0"
        lines.append(f"| {i['key']} | {i['status']} | {cost} | {i.get('reason') or ''} |")
    for i in record.get("items") or []:
        if i.get("plan_id"):
            lines.append(f"\nPreview `{i['key']}`: `items/{i['dir']}/publish-plan.md` (plan {i['plan_id']})")
    for i in record.get("items") or []:
        line = (i.get("context") or {}).get("line")
        if line:
            lines.append(f"\nContext `{i['key']}`: {line}")
    return "\n".join(lines) + "\n"


def _finish(ctx: RunContext, record: dict, code: int, status: str) -> int:
    record.update(status=status, exit_code=code, finished=iso(), usage_limited=ctx.usage_limited,
                  totals=_totals(record))
    if ctx.budget is not None:
        record.setdefault("budget", {})["after"] = _budget_dict(ctx.budget)
    if ctx.events:
        # the circuit breaker's record (§ 27.3): what stopped, why, and the sprint's spend against its cap
        record["events"] = list(ctx.events)
        record["notes"] += [f"{e['event']} ({e['sprint']}): {e['reason']}" for e in ctx.events]
    ctx.run.write_json("run.json", record)
    (ctx.run.path / "summary.md").write_text(_summary(record), encoding="utf-8")
    (runs_dir() / "LATEST").write_text(ctx.run.run_id + "\n", encoding="utf-8")
    prune(current=ctx.run.run_id)
    for i in record["items"]:
        print(f"  {i['status']:<14} {i['key']}  {i.get('reason') or ''}", file=sys.stderr)
        for f in i.get("flags") or []:
            print(f"  {'':<14} ! {f}", file=sys.stderr)
        if (i.get("context") or {}).get("line"):
            print(f"  {'':<14} · {i['context']['line']}", file=sys.stderr)
    t = record["totals"]
    print(f"jev loop: {status} — ${t['spent_usd']:.2f} spent ({COST_LABEL}); exit {code}", file=sys.stderr)
    if ctx.opts.json:
        print(json.dumps(record, indent=2, sort_keys=True, default=str))
    else:
        print(f"run: {ctx.run.path}")
    return code

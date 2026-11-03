"""The `loop-run` job, read once for both surfaces.

A `loop-run` job is `tools/dash loop run <loop> [step] --target <name> --json`
(the JEV loop runner, docs/JEV.md) started by the Harness Console's job
manager. Its log is stdout and stderr merged: the engine's progress lines on
stderr (`jev loop: run <id>`, one line per item, the closing
`jev loop: <status> — $X spent (…); exit N`) and, last, the run record as one
pretty-printed JSON document on stdout. This module turns that text into the
fields the browser console's job page and the terminal dash's Jobs tab both
render — turns, outcome, status, and cost labelled as the estimate it is —
so neither surface parses raw lines itself.

Pure: no file, no network, no console import. The record is JEV's
`jev-loop-run/v1` (tools/jev/loop.py); what is read here is a subset chosen
for a job view, read defensively, because the log may hold a run that died
before the record (then only the status lines exist) or a record from a
newer engine (then unknown keys are ignored).
"""
from __future__ import annotations

import json
import re

SCHEMA = "loop-job/v1"
COST_LABEL = "API-equivalent (estimate)"

#: `jev loop: run 20261103T174230Z-repo-scout-scout-9c5c5b`
RUN_RX = re.compile(r"^jev loop: run (?P<run_id>\S+)\s*$")
#: `jev loop: rehearsed — $0.00 spent (API-equivalent (estimate)); exit 0`
END_RX = re.compile(r"^jev loop: (?P<status>[a-z-]+) — \$(?P<spent>[0-9.]+) spent \((?P<label>[^)]*\)?)\); exit (?P<exit>\d+)\s*$")
#: `  rehearsed      bamr87/SCHEMA  <reason>` — the per-item line the engine prints as it goes
ITEM_RX = re.compile(r"^ {2}(?P<status>[a-z-]+) {2,}(?P<key>\S+)(?: {2}(?P<reason>.*?))?\s*$")
#: `run: <path>` — printed instead of the record when the job ran without --json
RUNDIR_RX = re.compile(r"^run: (?P<path>\S+)\s*$")
#: the engine refusing or failing before a run existed: `jev loop: <why>`
NOTE_RX = re.compile(r"^jev loop: (?P<text>.+?)\s*$")


def empty() -> dict:
    return {
        "schema": SCHEMA, "record": False, "run_id": None, "status": None, "exit_code": None, "mode": None,
        "loop": None, "step": None, "target": None, "model": None, "max_turns": None, "cap_usd": None,
        "spent_usd": None, "estimated_usd": None, "cost_label": COST_LABEL, "attempts": None, "published": None,
        "usage_limited": None, "finished": None, "items": [], "run_dir": None, "notes": [],
    }


def _record(text: str) -> dict | None:
    """The one JSON document the engine prints last (indent=2: only its outer
    braces sit in column 0), or None when the log holds none that parses."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == "{"]
    ends = [i for i, line in enumerate(lines) if line == "}"]
    for start in reversed(starts):
        for end in reversed(ends):
            if end <= start:
                break
            try:
                doc = json.loads("\n".join(lines[start:end + 1]))
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("schema", "").startswith("jev-loop-run/"):
                return doc
    return None


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _item(row: dict) -> dict:
    """One item of the record, as the job view shows it."""
    out = {
        "key": str(row.get("key") or row.get("name") or ""), "status": str(row.get("status") or ""),
        "decision": row.get("decision"), "reason": str(row.get("reason") or ""),
        "outcome": row.get("outcome"), "cost_usd": _num(row.get("cost_usd")),
        "cost_source": row.get("cost_source"), "turns": row.get("turns"),
        "flags": [str(f) for f in (row.get("flags") or [])], "urls": [str(u) for u in (row.get("urls") or [])],
    }
    ctx = row.get("context") or {}
    if isinstance(ctx, dict) and ctx.get("line"):
        out["context"] = str(ctx["line"])
    return out


def parse_log(text: str) -> dict:
    """Structured fields from a `loop-run` job's log, whatever state it is in."""
    out = empty()
    for line in text.splitlines():
        m = RUN_RX.match(line)
        if m:
            out["run_id"] = m.group("run_id")
            continue
        m = END_RX.match(line)
        if m:
            out.update(status=m.group("status"), spent_usd=_num(m.group("spent")), exit_code=int(m.group("exit")))
            continue
        m = RUNDIR_RX.match(line)
        if m:
            out["run_dir"] = m.group("path")
            continue
        m = ITEM_RX.match(line)
        if m and m.group("key") != "!" and not line.startswith("  $"):
            out["items"].append({"key": m.group("key"), "status": m.group("status"),
                                 "reason": (m.group("reason") or "").strip(), "decision": None, "outcome": None,
                                 "cost_usd": None, "cost_source": None, "turns": None, "flags": [], "urls": []})
            continue
        m = NOTE_RX.match(line)
        if m and not line.startswith("jev loop: run "):
            out["notes"].append(m.group("text"))
    rec = _record(text)
    if rec is None:
        return out
    tier = rec.get("tier") if isinstance(rec.get("tier"), dict) else {}
    totals = rec.get("totals") if isinstance(rec.get("totals"), dict) else {}
    opts = rec.get("options") if isinstance(rec.get("options"), dict) else {}
    out.update({
        "record": True, "run_id": rec.get("run_id") or out["run_id"], "status": rec.get("status") or out["status"],
        "exit_code": rec.get("exit_code") if rec.get("exit_code") is not None else out["exit_code"],
        "mode": rec.get("mode"), "loop": rec.get("loop"), "step": rec.get("step"), "target": opts.get("target"),
        "model": tier.get("model"), "max_turns": tier.get("max_turns"), "cap_usd": _num(tier.get("cap_usd")),
        "spent_usd": _num(totals.get("spent_usd")), "estimated_usd": _num(totals.get("estimated_usd")),
        "cost_label": str(totals.get("label") or COST_LABEL),
        "attempts": totals.get("attempts"), "published": totals.get("published"),
        "usage_limited": rec.get("usage_limited"), "finished": rec.get("finished"),
        "items": [_item(r) for r in (rec.get("items") or []) if isinstance(r, dict)],
        "notes": [str(n) for n in (rec.get("notes") or [])] or out["notes"],
    })
    return out


def summary_lines(fields: dict) -> list[str]:
    """The same fields as text — what the terminal dash writes under a
    finished loop-run's log, and what a test can compare."""
    if not fields.get("run_id") and not fields.get("status"):
        return []
    head = [p for p in (
        f"loop {fields['loop']}/{fields['step']}" if fields.get("loop") else None,
        fields.get("mode"), fields.get("status"),
        f"${fields['spent_usd']:.2f} spent ({fields.get('cost_label') or COST_LABEL})"
        if fields.get("spent_usd") is not None else None,
        f"exit {fields['exit_code']}" if fields.get("exit_code") is not None else None,
    ) if p]
    lines = ["── loop-run · " + " · ".join(head)]
    if fields.get("model"):
        lines.append(f"   {fields['model']} · {fields.get('max_turns')} turns · ${fields.get('cap_usd') or 0:g} cap per attempt")
    for i in fields.get("items") or []:
        cost = f" · ${i['cost_usd']:.2f}" if i.get("cost_usd") is not None else ""
        turns = f" · {i['turns']} turns" if i.get("turns") is not None else ""
        reason = f" — {i['reason']}" if i.get("reason") else ""
        lines.append(f"   {i['status']:<12} {i['key']}{cost}{turns}{reason}")
    if fields.get("run_id"):
        lines.append(f"   run {fields['run_id']}" + (f" · {fields['run_dir']}" if fields.get("run_dir") else ""))
    return lines

#!/usr/bin/env python3
"""
File: tools/jev/loop_context.py
Description: The loop runner's side of the context pack (tools/jev/context.py,
             imported as `cpack`; #486): built on the host, read by the sealed
             agent. The spec's `local.context` and the mode a run uses
             (`--context`), the backstop on `dash-gen context`, the pack one
             item gets and how it is recorded (`item_pack`), the brief and the
             pack placed in the clone as new files (`place_inputs`), `loop
             plan`'s preview of a pack's sections, what `context.redact` reads
             to mask this machine (`host_ctx`), and `--refresh-context` (the
             lake's local session import). Moved here from loop.py unchanged;
             loop.py re-exports every name. `doctor_planes` stays in loop.py:
             it builds a RunContext, and tests replace it there.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py. Callers outside the engine import these
       names from tools.jev.loop.
Dependencies: Python 3.12 stdlib; the planes only through `ctx.dash_gen`.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import os
import platform
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from . import context as cpack
from . import headless
from . import workspace as wsp
from .adapters import Item
from .common import JevError
from .spec import ContextSpec, StepSpec

if TYPE_CHECKING:   # annotations only: the engine imports this module, never the reverse
    from .loop import RunContext

#: the engine's backstop beyond the planes' own --deadline-s (they bound themselves; a timeout is a plane problem)
CONTEXT_GRACE_S = 30
#: `--refresh-context`: the lake's LOCAL import of this machine's Claude Code
#: transcripts (claude_projects_dir() → the lake, nothing else written;
#: dash-gen fleet_lake cmd_sessions). Never `lake sync`, which reads GitHub.
REFRESH_ARGV = ("lake", "sessions")


def context_settings(spec: StepSpec) -> ContextSpec:
    """The spec's `local.context` (the loader always sets it; a LocalSpec made
    by hand without one gets the loader's defaults)."""
    if spec.local is not None and spec.local.context is not None:
        return spec.local.context
    return ContextSpec(mode=cpack.DEFAULT_MODE, file="context.md", providers=cpack.PROVIDERS,
                       max_chars=cpack.DEFAULT_MAX_CHARS, deadline_s=cpack.DEFAULT_DEADLINE_S, days=cpack.DEFAULT_DAYS)


def context_mode(ctx: RunContext) -> str:
    """`--context` when given, else the spec's mode — except for a step with
    no brief (`workspace.no_brief`), which is always `off`: the spec loader
    refuses any other mode there, and the CLI override would otherwise build
    and place a pack nothing points at (or block the item under `require`)."""
    if ctx.spec.workspace.no_brief:
        return "off"
    return ctx.opts.context or context_settings(ctx.spec).mode


def context_backstop(argv: list[str]) -> int:
    """`dash-gen context`'s subprocess timeout: its own --deadline-s plus CONTEXT_GRACE_S."""
    said = next((a.split("=", 1)[1] for a in argv if a.startswith("--deadline-s=")), "")
    try:
        secs = cpack.check_deadline(said)
    except ValueError:
        secs = cpack.MAX_DEADLINE_S
    return int(math.ceil(secs)) + CONTEXT_GRACE_S


def _finite(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def context_status(statuses: dict[str, str]) -> str:
    """The attempt row's compact form: `history:ok,lake_ci:stale,…`."""
    return ",".join(f"{k}:{v}" for k, v in statuses.items())


def context_request(ctx: RunContext, item: Item) -> cpack.ContextRequest | None:
    """The adapter's request with the spec's window; None when it asks for no pack."""
    req = ctx.adapter.context_request(ctx, item)
    return None if req is None else dataclasses.replace(req, days=context_settings(ctx.spec).days)


def item_pack(ctx: RunContext, item: Item, report: dict, row: dict, *,
              target_dir: Path | None = None) -> cpack.Pack | None:
    """Build this item's pack into its run directory (`context.build`) and
    record it: `report["context"]`, and on `row` (every later attempt row) the
    pack's sha256 and a compact status. Mode 'off' builds and places nothing,
    and the adapter is not asked; an adapter that asks for no pack (None) is
    'none'. `target_dir` is the item's clone (None offline): the planes check
    the target's code-index hits against its files, the ones the agent
    reads, passed as its realpath. A plane that is down is a status in the
    pack, never an exception here; an error that does raise (a bad request,
    an unwritable run directory) is the engine's own and is not caught."""
    cs = context_settings(ctx.spec)
    mode = context_mode(ctx)
    req = cpack.ContextRequest(item.nwo, item.name, days=cs.days) if mode == "off" else context_request(ctx, item)
    if req is not None and mode != "off" and target_dir is not None:
        req = dataclasses.replace(req, target_dir=os.path.realpath(target_dir))
    if req is None:
        report["context"] = {"mode": mode, "sha256": None, "bytes": 0, "file": cs.file, "statuses": {},
                             "missing": [], "ages": {}, "elapsed_ms": 0,
                             "notes": ["context: the adapter asks for no pack for this item"],
                             "line": "context none (the adapter asks for no pack for this item)"}
        row.update(context_sha256=None, context_status="none")
        return None
    pack = cpack.build(ctx, item, req, mode=mode, sections=cs.providers, max_chars=cs.max_chars, file=cs.file,
                       deadline_s=cs.deadline_s)
    report["context"] = {"mode": pack.mode, "sha256": pack.sha256, "bytes": pack.bytes, "file": cs.file,
                         "statuses": dict(pack.sections), "missing": list(pack.missing),
                         "ages": {k: _finite(v) for k, v in pack.ages.items()}, "elapsed_ms": pack.elapsed_ms,
                         "notes": list(pack.notes), "queries": len(req.queries), "line": cpack.status_line(pack)}
    row.update(context_sha256=pack.sha256, context_status="off" if pack.path is None else context_status(pack.sections))
    return pack


def place_inputs(ctx: RunContext, ws: wsp.Workspace, brief: Path | None, pack: cpack.Pack | None) -> None:
    """The brief and (when one was built) the pack into the clone's brief
    directory, each as a NEW file (workspace.place_bytes: O_EXCL, no link
    followed). With a pack, the clone's copy of the brief is the plan's
    bytes + "\n" + `context.pointer` — written once, never placed and then
    rewritten. The plan directory's brief is never touched, so the adapter's
    reuse key, computed from it, and with it tier 0, are the same with or
    without a pack. Without one (mode off) the clone gets the plan's brief
    byte for byte, as it always did."""
    bd = ctx.spec.workspace.brief_dir
    built = pack is not None and pack.path is not None
    file = context_settings(ctx.spec).file
    if built and brief is not None and brief.name.lower() == file.lower():
        raise JevError(f"the brief {brief.name} and the context pack {file} would be one file in {bd}/")
    if brief is not None:
        data = brief.read_bytes()
        if built:
            data += b"\n" + cpack.pointer(bd, file).encode("utf-8")
        # a step whose prompt reads the brief by a fixed name gets it in the clone root (workspace.brief_file)
        wsp.place_bytes(ws, data, ctx.spec.workspace.brief_file or f"{bd}/{brief.name}")
    if built:
        data = pack.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != pack.sha256:
            raise JevError(f"the context pack {pack.path} changed since it was built")
        wsp.place_bytes(ws, data, f"{bd}/{file}", mode=0o600)


def context_preview(ctx: RunContext, item: Item) -> dict | None:
    """`loop plan`'s look at what this item's pack would hold: each
    section's status and age (no rows, nothing written anywhere), or None
    under mode 'off'."""
    mode = context_mode(ctx)
    if mode == "off":
        return None
    req = context_request(ctx, item)
    if req is None:
        return {"mode": mode, "statuses": {}, "ages": {}, "missing": [], "queries": 0, "would_block": False,
                "note": "the adapter asks for no pack for this item"}
    cs = context_settings(ctx.spec)
    doc = cpack.gather(ctx, req, sections=cs.providers, deadline_s=cs.deadline_s, item_key=item.key)
    secs = doc["sections"]
    statuses = {k: str(secs[k].get("status")) for k in secs}
    missing = [k for k in cpack.PLANE_SECTIONS if statuses.get(k) == "unavailable"]
    return {"mode": mode, "statuses": statuses, "ages": {k: _finite(secs[k].get("age_hours")) for k in secs},
            "missing": missing, "queries": len(req.queries), "would_block": mode == "require" and bool(missing)}


def context_bits(statuses: dict[str, str], ages: dict[str, float | None]) -> str:
    out = []
    for k, v in statuses.items():
        age = ages.get(k)
        out.append(f"{k} {v}" + (f"({age:.0f}h)" if v == "stale" and age is not None else ""))
    return " · ".join(out)


def host_ctx() -> SimpleNamespace:
    """What `context.redact` reads to mask this machine, without a RunContext."""
    return SimpleNamespace(home=Path.home(), work_root=headless.work_root(), hostname=platform.node().split(".")[0])


# --------------------------------------------------------------------------- #
# `--refresh-context`
# --------------------------------------------------------------------------- #
def claude_projects_dir() -> Path:
    """This operator's Claude Code transcripts: `$CLAUDE_CONFIG_DIR/projects`,
    else `~/.claude/projects`. Read from the ENGINE's environment and passed
    as `--claude-dir`: the planes' environment (deterministic_env) drops
    CLAUDE_CONFIG_DIR with every other auth override, and the lake would
    fall back to ~/.claude."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def refresh_context(ctx: RunContext, record: dict) -> None:
    """`--refresh-context`, once per run, before the first pack: the lake's
    LOCAL session import (`tools/dash-gen lake sessions`: this machine's
    Claude Code transcripts, from `claude_projects_dir()`, into the lake,
    nothing else written), never `lake sync`. A failed import, or one that
    found no transcripts, is a note, never the run's failure — the pack then
    reads the lake as it is (stale is reported, never fatal)."""
    if context_mode(ctx) == "off":
        record["notes"].append("--refresh-context: nothing to refresh, the context pack is off for this step")
        return
    argv = [*REFRESH_ARGV, f"--claude-dir={claude_projects_dir()}", f"--days={context_settings(ctx.spec).days}",
            "--json"]
    res = ctx.dash_gen(argv)
    doc = cpack.parse_document(res.out) or {}
    counts = {k: doc[k] for k in ("scanned", "sessions", "turns", "tool_calls", "skipped")
              if isinstance(doc.get(k), int) and not isinstance(doc.get(k), bool)}
    shown = [cpack.redact(a, ctx) for a in argv]   # the transcript directory is under the home
    record["context_refresh"] = {"argv": shown, "exit": res.code, **counts}
    said = " ".join(cpack.redact((res.err or res.out or "").strip()[-400:], ctx).split())[-200:]
    if res.code != 0:
        record["notes"].append(f"--refresh-context: `tools/dash-gen {' '.join(shown)}` exited {res.code}"
                               + (f": {said}" if said else "") + " — the pack reads the lake as it is")
    elif not counts:   # `lake sessions --json` prints nothing when the directory is missing
        record["notes"].append(f"--refresh-context: the lake's local session import found no transcripts at "
                               f"{cpack.redact(str(claude_projects_dir()), ctx)}" + (f" ({said})" if said else "")
                               + " — the pack reads the lake as it is")
    else:
        record["notes"].append(f"--refresh-context: the lake's local session import read {counts.get('scanned', '?')}"
                               f" transcript(s), {counts.get('sessions', '?')} new or changed")

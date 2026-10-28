#!/usr/bin/env python3
"""
work_queue — the human's hand on the order the fleet's loops work in.

Every loop that ranks work ranks it by a formula: the issue pipeline by a
priority score, readiness and age; the spec-driven `/evolve` picker by severity,
kind and id. A formula cannot know that the maintainer wants issue #565 before
the three P1s above it, or that a computed P1 is really a P3. This file is
where that judgement lives, so the loops can read it instead of overruling it:

    _data/work_queue.yml   (schema work-queue/v1, committed, reviewed in git)

    order:     [key, …]     manual order — keys listed here come FIRST in
                            their lane, in this order; everything else follows
                            by the loop's own ranking
    priority:  {key: P0-3}  replaces the computed priority wherever a loop
                            ranks the item (and the label T1 applies)
    notes:     {key: text}  why — shown on the board, never read by a loop

A key names one work item across the fleet:

    issue:<owner>/<repo>#<n>     an open issue (the issue pipeline)
    pr:<owner>/<repo>#<n>        an open pull request
    roadmap:FF-NNNN              a _data/roadmap.yml spec
    spec:<project>/<NNN-slug>    a spec package in a spec-driven repo
    backlog:<project>/BL-…       a BACKLOG.md item in a spec-driven repo

A roadmap entry's own `priority:` and `status:` live in _data/roadmap.yml and
are edited there, not overridden here; an issue's stage lives in its labels.
This file holds only what has no other home: the order, and a priority the
formula would not have chosen.

The Harness Console's Work board writes it (tools/console, /work), always in
the working tree — the commit is the approval of record. The issue pipeline
reads it (issue_pipeline.py) and the board shows it. Stdlib + PyYAML only.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

SCHEMA = "work-queue/v1"
PRIORITIES = ("P0", "P1", "P2", "P3")
KINDS = ("issue", "pr", "roadmap", "spec", "backlog")
MAX_ORDER = 300          # pinned keys kept; a list longer than this is a sign of a bug
MAX_NOTE = 280

KEY_RX = re.compile(
    r"^(?:"
    r"(?:issue|pr):[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}#\d{1,9}"
    r"|roadmap:FF-\d{4,6}"
    r"|spec:[A-Za-z0-9._-]{1,64}/\d{3}-[a-z0-9][a-z0-9-]{0,80}"
    r"|backlog:[A-Za-z0-9._-]{1,64}/BL-\d{8}-\d{2,3}"
    r")$"
)

HEADER = """\
# =============================================================================
# _data/work_queue.yml — the human's order and priority overrides (work-queue/v1)
# =============================================================================
# Written by the Harness Console's Work board (/work) in the working tree;
# committing it is the approval. Read by the issue pipeline
# (.github/scripts/dash-gen/issue_pipeline.py) when it builds its queues, and
# by the board. Doc: docs/WORK-BOARD.md. Module: dash-gen/work_queue.py.
#
#   order:    keys that come FIRST in their lane, in this order
#   priority: replaces the computed priority wherever a loop ranks the item
#   notes:    why (shown on the board, never read by a loop)
#
# Keys: issue:<owner>/<repo>#<n> · pr:<owner>/<repo>#<n> · roadmap:FF-NNNN ·
#       spec:<project>/<NNN-slug> · backlog:<project>/BL-YYYYMMDD-NN
# A roadmap entry's priority/status are edited in _data/roadmap.yml itself;
# an issue's stage lives in its labels. Comments below this header are not kept.
# =============================================================================
"""


def empty() -> dict:
    return {"schema": SCHEMA, "updated_at": None, "order": [], "priority": {}, "notes": {}}


def kind_of(key: str) -> str:
    return key.split(":", 1)[0]


def valid_key(key) -> bool:
    return isinstance(key, str) and bool(KEY_RX.match(key))


def normalize(raw) -> tuple[dict, list[str]]:
    """Coerce a loaded document into the schema, dropping (and reporting) what
    does not fit. A loop must never crash on a hand-edited file: a bad entry
    costs that entry, not the run."""
    doc = empty()
    problems: list[str] = []
    if raw is None:
        return doc, problems
    if not isinstance(raw, dict):
        return doc, ["work_queue: top level is not a mapping — ignored"]
    if raw.get("schema") not in (None, SCHEMA):
        problems.append(f"work_queue: schema {raw.get('schema')!r} is not {SCHEMA} — read anyway")
    stamp = raw.get("updated_at")
    doc["updated_at"] = str(stamp) if stamp else None

    seen: set[str] = set()
    for key in raw.get("order") or []:
        if not valid_key(key):
            problems.append(f"work_queue: order entry {key!r} is not a work key — dropped")
        elif key in seen:
            problems.append(f"work_queue: {key} listed twice in order — first kept")
        else:
            seen.add(key)
            doc["order"].append(key)
    if len(doc["order"]) > MAX_ORDER:
        problems.append(f"work_queue: order has {len(doc['order'])} keys — only the first {MAX_ORDER} are read")
        doc["order"] = doc["order"][:MAX_ORDER]

    for key, value in (raw.get("priority") or {}).items():
        if not valid_key(key):
            problems.append(f"work_queue: priority key {key!r} is not a work key — dropped")
        elif kind_of(key) == "roadmap":
            problems.append(f"work_queue: {key} — a roadmap priority is edited in _data/roadmap.yml — dropped")
        elif str(value) not in PRIORITIES:
            problems.append(f"work_queue: {key} priority {value!r} is not one of {PRIORITIES} — dropped")
        else:
            doc["priority"][key] = str(value)

    for key, value in (raw.get("notes") or {}).items():
        if valid_key(key) and isinstance(value, str) and value.strip():
            doc["notes"][key] = value.strip()[:MAX_NOTE]
        else:
            problems.append(f"work_queue: note for {key!r} dropped")
    return doc, problems


def load(path: Path | str) -> tuple[dict, list[str]]:
    p = Path(path)
    if not p.exists():
        return empty(), []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        return empty(), [f"work_queue: unreadable ({exc.__class__.__name__}) — ignored"]
    return normalize(raw)


def dump(doc: dict) -> str:
    body = {
        "schema": SCHEMA,
        "updated_at": doc.get("updated_at"),
        "order": list(doc.get("order") or []),
        "priority": dict(sorted((doc.get("priority") or {}).items())),
        "notes": dict(sorted((doc.get("notes") or {}).items())),
    }
    return HEADER + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


def save(path: Path | str, doc: dict) -> None:
    Path(path).write_text(dump(doc), encoding="utf-8")


# --------------------------------------------------------------------------- #
# what the loops read
# --------------------------------------------------------------------------- #
def ranks(doc: dict) -> dict[str, int]:
    """key → 0-based position in the manual order."""
    return {k: i for i, k in enumerate(doc.get("order") or [])}


def priority_for(doc: dict, key: str, computed: str) -> tuple[str, str]:
    """(effective priority, source): the override when there is one."""
    over = (doc.get("priority") or {}).get(key)
    return (over, "override") if over else (computed, "computed")


# --------------------------------------------------------------------------- #
# what the board writes
# --------------------------------------------------------------------------- #
def apply_changes(doc: dict, *, pins: dict[str, list[str]] | None = None,
                  lane_members: dict[str, set[str]] | None = None,
                  unpin: list[str] | None = None,
                  priority: dict[str, str | None] | None = None,
                  notes: dict[str, str | None] | None = None,
                  today: str | None = None) -> dict:
    """A new document with the board's changes applied. Pure.

    `pins` maps a lane to the COMPLETE pinned list for that lane after a drag,
    in order; `lane_members` says which keys are in that lane now, so the lane's
    old pins are replaced rather than duplicated. Relative order is all a lane
    reads, so a lane's new pins go to the end of the global list.
    """
    out = {"schema": SCHEMA, "updated_at": doc.get("updated_at"),
           "order": list(doc.get("order") or []),
           "priority": dict(doc.get("priority") or {}),
           "notes": dict(doc.get("notes") or {})}
    for lane, keys in (pins or {}).items():
        bad = [k for k in keys if not valid_key(k)]
        if bad:
            raise ValueError(f"not a work key: {bad[0]!r}")
        members = set((lane_members or {}).get(lane) or ()) | set(keys)
        out["order"] = [k for k in out["order"] if k not in members] + list(dict.fromkeys(keys))
    drop = set(unpin or ())
    out["order"] = [k for k in out["order"] if k not in drop]
    for key, value in (priority or {}).items():
        if not valid_key(key):
            raise ValueError(f"not a work key: {key!r}")
        if kind_of(key) == "roadmap":
            raise ValueError(f"{key}: a roadmap priority is edited in _data/roadmap.yml")
        if value in (None, ""):
            out["priority"].pop(key, None)
        elif value not in PRIORITIES:
            raise ValueError(f"{key}: priority must be one of {PRIORITIES}")
        else:
            out["priority"][key] = value
    for key, value in (notes or {}).items():
        if not valid_key(key):
            raise ValueError(f"not a work key: {key!r}")
        if value in (None, ""):
            out["notes"].pop(key, None)
        else:
            out["notes"][key] = str(value).strip()[:MAX_NOTE]
    if len(out["order"]) > MAX_ORDER:
        raise ValueError(f"more than {MAX_ORDER} pinned keys — unpin some first")
    out["updated_at"] = today or dt.date.today().isoformat()
    return out


def prune(doc: dict, live: set[str]) -> tuple[dict, list[str]]:
    """Drop keys for items that no longer exist (closed, shipped, merged)."""
    gone = sorted({k for k in doc.get("order") or [] if k not in live}
                  | {k for k in doc.get("priority") or {} if k not in live}
                  | {k for k in doc.get("notes") or {} if k not in live})
    if not gone:
        return doc, []
    g = set(gone)
    return ({**doc,
             "order": [k for k in doc.get("order") or [] if k not in g],
             "priority": {k: v for k, v in (doc.get("priority") or {}).items() if k not in g},
             "notes": {k: v for k, v in (doc.get("notes") or {}).items() if k not in g}},
            gone)

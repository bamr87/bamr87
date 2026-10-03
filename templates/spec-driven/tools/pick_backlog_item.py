#!/usr/bin/env python3
"""Pick the top ``## Open`` BACKLOG item by the ``/evolve`` ordering.

The deterministic picker the autonomous evolve loop uses to choose the next
piece of work (the repo's evolve prompt or command, step 1):

1. ``severity: high`` before ``med`` before ``low``.
2. Within a severity, ``tech-debt``/``test-gap`` win over feature work (the
   standing nudge toward a refactor budget).
3. Otherwise the oldest ``BL-YYYYMMDD-NN`` first.

Stdlib only. Fleet copy: bamr87/bamr87 templates/spec-driven/tools/ (keep it
byte-identical, UPS-WORK-07).

    python3 tools/pick_backlog_item.py            # JSON {id,kind,severity,title}
    python3 tools/pick_backlog_item.py --id-only  # bare id (empty => Discovery Mode)
    python3 tools/pick_backlog_item.py --root <repo>
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

BACKLOG = pathlib.Path(__file__).resolve().parent.parent / "BACKLOG.md"

_BULLET = re.compile(
    r"^- \*\*(?P<id>BL-\d{8}-\d{2})\*\* — \*(?P<kind>[a-z-]+),\s*"
    r"(?P<sev>low|med|high)\* — (?P<text>.+)$"
)
_SEVERITY = {"high": 0, "med": 1, "low": 2}
_DEBT_KINDS = {"tech-debt", "test-gap"}
# Strip the trailing "_Surfaced in:_ …" / "_Shipped in:_ …" provenance tail.
_TAIL = re.compile(r"\s+_[A-Za-z][^_]*:_.*$")


def _root_arg(argv: list[str]) -> list[str]:
    """Strip ``--root <repo>`` from argv and point BACKLOG at that checkout."""
    global BACKLOG
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            BACKLOG = pathlib.Path(argv[i + 1]).resolve() / "BACKLOG.md"
        argv = argv[:i] + argv[i + 2 :]
    return argv


def open_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    in_open = False
    for line in text.splitlines():
        if line.startswith("## Open"):
            in_open = True
            continue
        if in_open and line.startswith("## "):
            break
        if in_open:
            m = _BULLET.match(line)
            if m:
                d = m.groupdict()
                # Skip items left in ## Open but already resolved (strikethrough
                # or an inline "(resolved …)" note) — they belong in ## Done.
                lowered = d["text"].lower()
                if "(resolved" in lowered or d["text"].lstrip().startswith("~~"):
                    continue
                title = _TAIL.sub("", d["text"]).strip()
                items.append(
                    {
                        "id": d["id"],
                        "kind": d["kind"],
                        "severity": d["sev"],
                        "title": title[:200],
                    }
                )
    return items


def _rank(item: dict[str, str]) -> tuple[int, int, str]:
    return (
        _SEVERITY.get(item["severity"], 3),
        0 if item["kind"] in _DEBT_KINDS else 1,
        item["id"],
    )


def pick(text: str) -> dict[str, str] | None:
    items = sorted(open_items(text), key=_rank)
    return items[0] if items else None


def main(argv: list[str]) -> int:
    argv = _root_arg(argv)
    text = BACKLOG.read_text(encoding="utf-8") if BACKLOG.exists() else ""
    top = pick(text)
    id_only = "--id-only" in argv
    if top is None:
        # Empty output signals the caller to switch to Discovery Mode.
        print("" if id_only else json.dumps({"id": None, "reason": "no open items"}))
        return 0
    print(top["id"] if id_only else json.dumps(top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

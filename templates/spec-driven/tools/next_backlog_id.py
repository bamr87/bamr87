#!/usr/bin/env python3
"""Print the next free ``BL-YYYYMMDD-NN`` backlog id.

Deterministic id minting so parallel/autonomous agents don't collide when
appending to ``BACKLOG.md``. Stdlib only, like the other spec-driven gates
(``spec_validator.py`` / ``backlog_lint.py``); it never imports the app. Fleet
copy: bamr87/bamr87 templates/spec-driven/tools/ (keep it byte-identical,
UPS-WORK-07).

    python3 tools/next_backlog_id.py            # next id for today (UTC)
    python3 tools/next_backlog_id.py --date 20260615
    python3 tools/next_backlog_id.py --root <repo>
"""

from __future__ import annotations

import datetime
import pathlib
import re
import sys

BACKLOG = pathlib.Path(__file__).resolve().parent.parent / "BACKLOG.md"


def _root_arg(argv: list[str]) -> list[str]:
    """Strip ``--root <repo>`` from argv and point BACKLOG at that checkout."""
    global BACKLOG
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            BACKLOG = pathlib.Path(argv[i + 1]).resolve() / "BACKLOG.md"
        argv = argv[:i] + argv[i + 2 :]
    return argv


def next_id(date: str, text: str) -> str:
    nums = [int(n) for n in re.findall(rf"BL-{re.escape(date)}-(\d{{2}})", text)]
    nxt = (max(nums) + 1) if nums else 1
    return f"BL-{date}-{nxt:02d}"


def main(argv: list[str]) -> int:
    argv = _root_arg(argv)
    date = None
    if "--date" in argv:
        try:
            date = argv[argv.index("--date") + 1]
        except IndexError:
            print("usage: next_backlog_id.py [--date YYYYMMDD]", file=sys.stderr)
            return 2
    if not date:
        date = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", date):
        print(f"bad --date {date!r} (want YYYYMMDD)", file=sys.stderr)
        return 2
    text = BACKLOG.read_text(encoding="utf-8") if BACKLOG.exists() else ""
    print(next_id(date, text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

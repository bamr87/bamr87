#!/usr/bin/env python3
"""Backlog lint — keeps [BACKLOG.md](../BACKLOG.md) machine-checkable.

Enforces:

* The file exists and contains the three canonical headings: ``## Open``,
  ``## Claimed``, ``## Done``.
* Every bullet under ``## Open`` / ``## Claimed`` / ``## Done`` matches
  ``- **BL-YYYYMMDD-NN** — *<kind>, <severity>* — <text>``.
* IDs are unique.
* Items are never silently *removed* against a baseline revision: the
  committed BACKLOG.md at ``$BACKLOG_LINT_BASE`` (default ``HEAD``) must
  be a strict subset of the current one. Locally (and via the edit hook)
  the ``HEAD`` default catches uncommitted deletions; in CI the checked-out
  worktree IS HEAD, so ci.yml sets ``BACKLOG_LINT_BASE: HEAD^1`` (with
  fetch-depth 2) to compare against the previous commit / PR base —
  otherwise the append-only check is a self-comparison no-op there
  (spec 038, backported from the gitorio port's adversarial review).

Exit code is non-zero on any violation. Used as a CI gate.

A second, non-gating mode reports *stale* ``## Open`` items — those whose
``BL-YYYYMMDD-NN`` date is older than a cutoff (default 60 days, the repo's own
triage rule)::

    python3 scripts/backlog_lint.py --stale-report [--stale-days 60]

It prints a markdown list to stdout and always exits 0, so it can never turn a
scheduled run red. ``.github/workflows/nightly-tests.yml`` feeds that output
into an idempotent ``backlog-triage`` issue (BL-20260503-14).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG = REPO_ROOT / "BACKLOG.md"

REQUIRED_HEADINGS = ("## Open", "## Claimed", "## Done")
BULLET_RE = re.compile(
    r"^- \*\*(?P<id>BL-\d{8}-\d{2})\*\* — \*(?P<kind>[a-z-]+),\s*(?P<sev>low|med|high)\* — .+$"
)
KINDS = {"feature", "refactor", "tech-debt", "test-gap", "doc-gap", "infra"}


def _ids(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("- **BL-"):
            m = BULLET_RE.match(line)
            if m:
                out.append(m.group("id"))
    return out


def _previous_backlog() -> str | None:
    base = os.environ.get("BACKLOG_LINT_BASE", "HEAD")
    try:
        result = subprocess.run(
            ["git", "show", f"{base}:BACKLOG.md"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


DEFAULT_STALE_DAYS = 60


def open_section(text: str) -> list[str]:
    """Return the bullet lines that live under ``## Open``.

    ``## Claimed`` items belong to their spec and ``## Done`` is history, so
    neither is triage material — only ``## Open`` goes stale.
    """
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == "## Open"
            continue
        if inside and line.startswith("- **BL-"):
            out.append(line)
    return out


def stale_open_items(
    text: str, *, days: int = DEFAULT_STALE_DAYS, today: _dt.date | None = None
) -> list[tuple[int, str, str]]:
    """``(age_in_days, id, bullet_text)`` for Open items older than ``days``.

    Sorted oldest first. Items whose id carries an unparseable date are
    skipped rather than reported — the format gate above is what polices ids.
    """
    now = today or _dt.datetime.now(_dt.timezone.utc).date()
    found: list[tuple[int, str, str]] = []
    for line in open_section(text):
        m = BULLET_RE.match(line)
        if not m:
            continue
        bl_id = m.group("id")
        stamp = bl_id[3:11]
        try:
            raised = _dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        except ValueError:
            continue
        age = (now - raised).days
        if age > days:
            found.append((age, bl_id, line[2:]))
    found.sort(key=lambda row: (-row[0], row[1]))
    return found


def _stale_report(days: int) -> int:
    """Print stale Open items as markdown. Never fails (always exit 0)."""
    if not BACKLOG.is_file():
        print("BACKLOG.md is missing; nothing to triage")
        return 0
    stale = stale_open_items(BACKLOG.read_text(encoding="utf-8"), days=days)
    if not stale:
        print(f"No ## Open items older than {days} days.")
        return 0
    print(f"{len(stale)} `## Open` item(s) unclaimed for more than {days} days:")
    print()
    for age, _bl_id, bullet in stale:
        print(f"- ({age}d) {bullet}")
    print()
    print(
        "Triage each per the rules at the top of BACKLOG.md: claim it into a "
        "spec, close it as done/obsolete/duplicate, or restate it."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stale-report",
        action="store_true",
        help="report ## Open items older than --stale-days instead of linting",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"staleness cutoff in days (default {DEFAULT_STALE_DAYS})",
    )
    args = parser.parse_args()
    if args.stale_report:
        return _stale_report(args.stale_days)

    if not BACKLOG.is_file():
        print("FAIL: BACKLOG.md is missing")
        return 1

    text = BACKLOG.read_text(encoding="utf-8")
    errors: list[str] = []

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing required heading: {heading!r}")

    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("- **BL-"):
            continue
        m = BULLET_RE.match(line)
        if not m:
            errors.append(f"line {lineno}: bullet does not match required format")
            continue
        bl_id, kind = m.group("id"), m.group("kind")
        if kind not in KINDS:
            errors.append(f"line {lineno}: unknown kind '{kind}' (allowed: {sorted(KINDS)})")
        if bl_id in seen:
            errors.append(f"line {lineno}: duplicate id {bl_id}")
        seen.add(bl_id)

    prev = _previous_backlog()
    if prev:
        prev_ids = set(_ids(prev))
        cur_ids = set(seen)
        removed = sorted(prev_ids - cur_ids)
        if removed:
            errors.append(
                "BACKLOG entries cannot be removed once committed (move to Done instead): "
                + ", ".join(removed)
            )

    if errors:
        print("FAIL BACKLOG.md")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"PASS BACKLOG.md ({len(seen)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

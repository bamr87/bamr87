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
  be a strict subset of the current one. Locally/via the edit hook the
  ``HEAD`` default catches uncommitted deletions; in CI the worktree IS
  HEAD, so ci.yml sets ``BACKLOG_LINT_BASE: HEAD^1`` (with fetch-depth 2)
  to compare against the previous commit / PR base instead — otherwise
  the append-only check would be a self-comparison no-op there.

Exit code is non-zero on any violation. Used as a CI gate (ci.yml
``spec-gate`` job) and by ``.claude/hooks/gate-check.sh``. Ported from
law-ai's ``scripts/backlog_lint.py`` (golden rule #11).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
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


def main() -> int:
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

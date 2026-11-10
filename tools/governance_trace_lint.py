#!/usr/bin/env python3
"""
File: tools/governance_trace_lint.py
Description: Warn-then-fail lint for constitution § 28 (grok-claude-governance):
             a PR body must carry a "Governed by:" line linking an amendment
             or PRD requirement (no orphan changes).
Author: bamr87
Created: 2026-11-05
Usage:
  python3 tools/governance_trace_lint.py check --body-file BODY.md [--gate] [--json]
  echo "$PR_BODY" | python3 tools/governance_trace_lint.py check [--gate]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GOVERNED_RE = re.compile(r"^\s*[*_]*governed by[*_]*\s*:(.*)$", re.I | re.M)
REF_RE = re.compile(
    r"(docs/amendments/(proposed/)?[\w.-]+\.md"
    r"|AMEND-(\d{4}|NEW:[\w-]+)"
    r"|\b(FR|NFR)\d+\b"
    r"|\b(FR|NFR)-NEW:[\w-]+"
    r"|amendment\s+#?\d{4}"
    r"|github\.com/bamr87/[\w.-]+/pull/\d+)",
    re.I,
)
EXEMPT_RE = re.compile(r"\btrace-exempt\b", re.I)


def check_body(body: str) -> dict:
    if EXEMPT_RE.search(body or ""):
        return {"ok": True, "exempt": True, "refs": []}
    refs: list[str] = []
    for m in GOVERNED_RE.finditer(body or ""):
        refs += [r.group(0) for r in REF_RE.finditer(m.group(1))]
    if refs:
        return {"ok": True, "exempt": False, "refs": refs}
    return {
        "ok": False,
        "exempt": False,
        "refs": [],
        "message": "PR body lacks a 'Governed by:' line naming an amendment or FR/NFR (§ 28.4)",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--body-file")
    c.add_argument("--gate", action="store_true", help="hard-fail on a missing trace")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else sys.stdin.read()
    res = check_body(body)
    if a.json:
        print(json.dumps(res))
    elif res["ok"]:
        print("governance-trace: ok" + (" (trace-exempt)" if res["exempt"] else f" — {', '.join(res['refs'])}"))
    else:
        print(f"governance-trace: {'FAIL' if a.gate else 'WARN'} — {res['message']}")
    return 1 if (a.gate and not res["ok"]) else 0


if __name__ == "__main__":
    sys.exit(main())

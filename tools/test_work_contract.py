#!/usr/bin/env python3
"""Consistency tests for specs/WORK.contract.yml against the generated _data/specs.yml.

    python3 tools/test_work_contract.py

Every rule in the contract states `applies` / `applies_notes` exactly as
tools/gen-specs-data.py writes them for the same row, so a checker reading
either file binds the same repos. Also checks that every rule marked
`rollout: warn` exists in specs.yml and that the WORK-02 lint keys are present.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    contract = yaml.safe_load((HUB / "specs" / "WORK.contract.yml").read_text(encoding="utf-8"))
    specs = {r["id"]: r for r in yaml.safe_load((HUB / "_data" / "specs.yml").read_text(encoding="utf-8"))["requirements"]}
    rules = {**contract["rules"], **contract["related"]}
    print("applies / applies_notes == _data/specs.yml")
    for rid, rule in rules.items():
        if "applies" not in rule:
            continue
        row = specs.get(rid)
        check(row is not None, f"{rid} is in _data/specs.yml")
        if row is None:
            continue
        check(rule["applies"] == row.get("applies"), f"{rid} applies {rule['applies']} == {row.get('applies')}")
        check(rule.get("applies_notes") == row.get("applies_notes"),
              f"{rid} applies_notes {rule.get('applies_notes')} == {row.get('applies_notes')}")
    print("rollout markers")
    for rid, rule in rules.items():
        if rule.get("rollout") is not None:
            check(rule["rollout"] == "warn", f"{rid} rollout is `warn`")
            check(specs.get(rid, {}).get("level") not in (None, "retired"), f"{rid} is a live row")
    print("UPS-WORK-02 lint keys")
    d = contract["definitions"]
    keys = (d.get("backlog_lint_keys") or {}).get("workflow") or []
    check(bool(keys) and all(k.startswith("jobs.<job>.") for k in keys), f"backlog_lint_keys.workflow are job paths {keys}")
    rx = re.compile(d.get("backlog_lint_value_re") or "(?!)", re.I)
    check(rx.search("python3 tools/backlog_lint.py") is not None, "backlog_lint_value_re matches backlog_lint.py")
    check(rx.search("ruby scripts/sync-backlog.rb") is None, "backlog_lint_value_re does not match a sync job")
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Consistency tests for specs/WORK.contract.yml against the generated _data/specs.yml.

    python3 tools/test_work_contract.py

Every rule in the contract states `applies` / `applies_notes` exactly as
tools/gen-specs-data.py writes them for the same row, so a checker reading
either file binds the same repos. Also checks that every rule marked
`rollout: warn` exists in specs.yml, that the WORK-02 lint keys are present,
and that every `hard_fail:` case is well-formed and stays a fail under
`rollout: warn` (UPS-REPO-21 `double_release`).
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


def hard_fail_cases(rule: dict, d: dict, uses: list[str]) -> list[str]:
    """Reference reading of a rule's `hard_fail:` cases: the names whose `all_of`
    callers all appear among the job-level `uses:` values (compared up to the '@',
    the ref fullmatching the named definitions regex, or anything for `any`)."""
    hits = []
    for name, case in (rule.get("hard_fail") or {}).items():
        def present(want: dict) -> bool:
            target = d[want["caller"]]
            rx = None if want["ref_re"] == "any" else re.compile(d[want["ref_re"]])
            return any(u.split("@", 1)[0] == target and (rx is None or rx.fullmatch(u.split("@", 1)[1] if "@" in u else ""))
                       for u in uses)
        if all(present(w) for w in case["all_of"]):
            hits.append(name)
    return hits


def reported(rule: dict, failed: bool, hard: list[str]) -> str:
    """The result vocabulary: `rollout: warn` turns a fail into warn, except a
    hard_fail case, which stays a fail."""
    if hard:
        return "fail"
    if failed:
        return "warn" if rule.get("rollout") == "warn" else "fail"
    return "pass"


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
    rx = re.compile(d.get("backlog_lint_value_re") or "(?!)", re.IGNORECASE)
    check(rx.search("python3 tools/backlog_lint.py") is not None, "backlog_lint_value_re matches backlog_lint.py")
    check(rx.search("ruby scripts/sync-backlog.rb") is None, "backlog_lint_value_re does not match a sync job")
    print("hard_fail cases (never softened by rollout: warn)")
    for rid, rule in rules.items():
        for name, case in (rule.get("hard_fail") or {}).items():
            check(case.get("result") == "fail", f"{rid} hard_fail.{name} result is `fail`")
            check(bool(case.get("all_of")), f"{rid} hard_fail.{name} has all_of")
            for w in case.get("all_of") or []:
                check(w.get("caller") in d, f"{rid} hard_fail.{name} caller `{w.get('caller')}` is a definition")
                check(w.get("ref_re") == "any" or w.get("ref_re") in d,
                      f"{rid} hard_fail.{name} ref_re `{w.get('ref_re')}` is `any` or a definition")
            check(all(k in d for k in case.get("reads") or []), f"{rid} hard_fail.{name} reads only definitions")
            check(bool(case.get("detail")), f"{rid} hard_fail.{name} has a detail")
    r21 = rules["UPS-REPO-21"]
    check(r21.get("rollout") == "warn", "UPS-REPO-21 still carries rollout: warn (so the hard fail is the exception)")
    check("double_release" in (r21.get("hard_fail") or {}), "UPS-REPO-21 has hard_fail.double_release")
    hub, legacy = d["release_workflow"], d["legacy_release_workflow"]
    cases = {
        "pinned hub + legacy @main": ([f"{hub}@v1", f"{legacy}@main"], True, "fail"),
        "pinned hub (SHA) + legacy @v1": ([f"{hub}@{'a' * 40}", f"{legacy}@v1"], True, "fail"),
        "legacy only": ([f"{legacy}@main"], True, "warn"),
        "pinned hub only": ([f"{hub}@v1"], False, "pass"),
        "unpinned hub + legacy": ([f"{hub}@main", f"{legacy}@main"], True, "warn"),
    }
    for label, (uses, failed, want) in cases.items():
        hard = hard_fail_cases(r21, d, uses)
        got = reported(r21, failed, hard)
        check(got == want, f"UPS-REPO-21 {label}: {got} == {want}")
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

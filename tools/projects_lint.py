#!/usr/bin/env python3
"""
File: tools/projects_lint.py
Description: Work-tracking gate (constitution § 9, amendment 0003, feature projects-coverage-gate).
  check            validate templates/projects/framework.yml offline (schema, lifecycle, label map)
  coverage [--json] live: open issues/PRs missing from the portfolio or required fields.
                   Needs the gh `read:project` scope; without it reports scope_missing (NFR-NEW:projects-scope-honest), exit 0.
Exit: 0 clean, 1 errors, 2 usage.  Skeleton: coverage is phase 2.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "templates/projects/framework.yml"


def validate(spec: dict) -> list[str]:
    errs = []
    if spec.get("schema") != "projects/v1":
        errs.append("schema must be projects/v1")
    fields = spec.get("fields") or {}
    for req in ("Status", "Priority", "Area", "Repo"):
        if not (fields.get(req) or {}).get("required"):
            errs.append(f"field {req} must exist and be required")
    status = (fields.get("Status") or {}).get("options", [])
    life = spec.get("lifecycle") or {}
    if set(life) != set(status):
        errs.append(f"lifecycle states {sorted(life)} != Status options {sorted(status)}")
    for s, d in life.items():
        for n in (d or {}).get("next", []):
            if n not in life:
                errs.append(f"lifecycle {s} -> unknown state {n}")
    keys = [p.get("key") for p in spec.get("projects", [])]
    if "portfolio" not in keys:
        errs.append("a 'portfolio' project is required")
    if len(keys) != len(set(keys)):
        errs.append("duplicate project keys")
    for lab, m in ((spec.get("labels") or {}).get("canonical") or {}).items():
        f = fields.get(m.get("field"))
        if not f:
            errs.append(f"label {lab} maps to unknown field {m.get('field')}")
        elif "options" in f and m.get("value") not in f["options"]:
            errs.append(f"label {lab} maps to unknown {m['field']} value {m.get('value')}")
    return errs


def has_project_scope() -> bool:
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        out = r.stdout + r.stderr
    except FileNotFoundError:
        return False
    return "project" in out


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("check", "coverage"):
        print(__doc__); return 2
    spec = yaml.safe_load(SPEC.read_text())
    errs = validate(spec)
    if argv[0] == "check":
        for e in errs:
            print(f"error: {e}")
        print(f"projects_lint: {len(errs)} error(s)")
        return 1 if errs else 0
    res = {"scope_missing": None if has_project_scope() else "project", "items": [], "phase": "skeleton"}
    print(json.dumps(res) if "--json" in argv else f"coverage: {res}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

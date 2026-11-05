#!/usr/bin/env python3
"""voices.py — validate the canonical fleet voice config (_data/voices/voices.yml, voices/v1).

  python3 tools/voices.py check [--file F] [--against COPY]   schema + reference checks; --against flags drift vs a consumer copy
  python3 tools/voices.py assign SITE ACTIVITY [--repo R] [--cadence daily|weekly]   which persona an entry gets

Stdlib + PyYAML only (jsonschema is not installed in CI): a structural check of
voices.schema.json's required keys, enums and references. Never reads secrets.
"""
import argparse, json, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "_data/voices/voices.yml"
SCHEMA = ROOT / "_data/voices/voices.schema.json"


def _check_profile(where, p, defs, errs):
    allowed = set(defs["profileFields"]["properties"]) | set(defs["persona"]["properties"])
    for k in p:
        if k not in allowed:
            errs.append(f"{where}: unknown key {k!r}")
    for k, v in (p.get("style") or {}).items():
        enum = defs["style"]["properties"].get(k, {}).get("enum")
        if enum is None:
            errs.append(f"{where}.style: unknown key {k!r}")
        elif v not in enum:
            errs.append(f"{where}.style.{k}: {v!r} not in {enum}")


def check(data):
    defs = json.loads(SCHEMA.read_text())["$defs"]
    errs = []
    if data.get("schema") != "voices/v1":
        errs.append("schema: must be voices/v1")
    _check_profile("defaults", data.get("defaults") or {}, defs, errs)
    for site, s in (data.get("sites") or {}).items():
        _check_profile(f"{site}.profile", s.get("profile") or {}, defs, errs)
        personas = s.get("personas") or {}
        for key, p in personas.items():
            for req in ("name", "role", "enabled"):
                if req not in p:
                    errs.append(f"{site}.personas.{key}: missing {req}")
            _check_profile(f"{site}.personas.{key}", p, defs, errs)
        for i, r in enumerate(s.get("assignment") or []):
            target = r.get("persona") or r.get("default")
            if target not in personas:
                errs.append(f"{site}.assignment[{i}]: unknown persona {target!r}")
    return errs


def assign(data, site, activity, repo=None, cadence=None):
    s = data["sites"][site]
    on = {k for k, p in s["personas"].items() if p.get("enabled")}
    for r in s.get("assignment", []):
        if "default" in r:
            return r["default"] if r["default"] in on else None
        if r["persona"] not in on:
            continue
        if "activity" in r and activity not in r["activity"]:
            continue
        if "repos" in r and repo not in r["repos"]:
            continue
        if "cadence" in r and cadence != r["cadence"]:
            continue
        return r["persona"]
    return None


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--file", default=str(FILE)); c.add_argument("--against")
    a = sub.add_parser("assign"); a.add_argument("site"); a.add_argument("activity")
    a.add_argument("--repo"); a.add_argument("--cadence"); a.add_argument("--file", default=str(FILE))
    ns = ap.parse_args()
    data = yaml.safe_load(Path(ns.file).read_text())
    if ns.cmd == "assign":
        print(assign(data, ns.site, ns.activity, ns.repo, ns.cadence)); return 0
    errs = check(data)
    if ns.against and yaml.safe_load(Path(ns.against).read_text()) != data:
        errs.append(f"drift: {ns.against} differs from {ns.file} (the hub file is canonical)")
    for e in errs:
        print("error:", e)
    print(f"{ns.file}: {'ok' if not errs else f'{len(errs)} error(s)'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

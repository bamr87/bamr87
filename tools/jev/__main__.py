#!/usr/bin/env python3
"""
File: tools/jev/__main__.py
Description: The JEV command line — `python3 -m tools.jev <group> <action>`.
             Three groups today: `number` (the assign-at-merge compiler, the
             conflict-free numbering scheme) and `conflicts` (the tiered
             conflict triage and resolution engine), `generated` (the
             main-only generated files guard). Doc: docs/JEV.md.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage:
  python3 -m tools.jev number    plan|apply|next|lint  [--repo .] [--base origin/main]
  python3 -m tools.jev conflicts scan|triage|resolve|budget [--pr owner/repo#n] [--dry-run]
  python3 -m tools.jev generated list|guard|regen [--base origin/main]
Exit: 0 clean, 1 a problem the caller must fix, 2 usage.
"""
from __future__ import annotations

import argparse
import sys

from . import VERSION, conflicts, generated, number
from .common import JevError


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m tools.jev", description=__doc__.split("Usage:")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"jev {VERSION}")
    sub = ap.add_subparsers(dest="group", required=True)
    number.add_arguments(sub.add_parser("number", help="the assign-at-merge numbering compiler"))
    conflicts.add_arguments(sub.add_parser("conflicts", help="tiered PR conflict triage"))
    generated.add_arguments(sub.add_parser("generated", help="main-only generated files: guard and regen"))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        mod = {"number": number, "conflicts": conflicts, "generated": generated}[args.group]
        return mod.main(args)
    except JevError as exc:
        print(f"jev: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

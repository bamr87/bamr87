#!/usr/bin/env python3
"""
File: tools/jev/__main__.py
Description: The JEV command line — `python3 -m tools.jev <group> <action>`.
             Two groups today: `number` (the assign-at-merge compiler, the
             conflict-free numbering scheme) and `conflicts` (the tiered
             conflict triage and resolution engine). Doc: docs/JEV.md.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage:
  python3 -m tools.jev number    plan|apply|next|lint  [--repo .] [--base origin/main]
  python3 -m tools.jev conflicts scan|triage|resolve|budget [--pr owner/repo#n] [--dry-run]
Exit: 0 clean, 1 a problem the caller must fix, 2 usage.
"""
from __future__ import annotations

import argparse
import sys

from . import VERSION, conflicts, number
from .common import JevError


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m tools.jev", description=__doc__.split("Usage:")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"jev {VERSION}")
    sub = ap.add_subparsers(dest="group", required=True)
    number.add_arguments(sub.add_parser("number", help="the assign-at-merge numbering compiler"))
    conflicts.add_arguments(sub.add_parser("conflicts", help="tiered PR conflict triage"))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return number.main(args) if args.group == "number" else conflicts.main(args)
    except JevError as exc:
        print(f"jev: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

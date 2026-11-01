#!/usr/bin/env python3
"""
File: tools/jev/__main__.py
Description: The JEV command line — `python3 -m tools.jev <group> <action>`.
             Six groups today: `number` (the assign-at-merge compiler, the
             conflict-free numbering scheme), `ratify` (the ratification and
             acceptance records a maintainer's merge decided), `conflicts`
             (the tiered conflict triage and resolution engine), `generated`
             (the main-only generated files guard), `steps` (the loop step
             specs: parity check and byte-exact prompt render) and `loop` (the
             local loop runner: a loop's agent step on this workstation,
             isolated and sandboxed). Doc: docs/JEV.md.
Author: bamr87
Created: 2026-10-29
Version: 0.3.0
Usage:
  python3 -m tools.jev number    plan|apply|next|lint  [--repo .] [--base origin/main]
  python3 -m tools.jev ratify    plan [--json] | apply [--plan F] | check-diff --base REV | pr-body [--title]
  python3 -m tools.jev conflicts scan|triage|resolve|budget [--pr owner/repo#n] [--dry-run]
  python3 -m tools.jev generated list|guard|regen [--base origin/main]
  python3 -m tools.jev steps     check | render <loop> <step> [--set TOKEN=value …]
  python3 -m tools.jev loop      list | doctor [--live] | plan <loop> | run <loop> [--rehearse|--apply]
                                 | publish <run_id> [--apply] | show <run_id>|--latest | budget
Exit: 0 clean, 1 a problem the caller must fix, 2 usage (`loop` adds 3 credential,
      4 host safety, 127 no claude CLI, 130 interrupted; docs/JEV.md).
"""
from __future__ import annotations

import argparse
import sys

from . import VERSION, conflicts, generated, loop, number, ratify, spec
from .common import JevError


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m tools.jev", description=__doc__.split("Usage:")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"jev {VERSION}")
    sub = ap.add_subparsers(dest="group", required=True)
    number.add_arguments(sub.add_parser("number", help="the assign-at-merge numbering compiler"))
    ratify.add_arguments(sub.add_parser(
        "ratify", help="record the ratification / acceptance / completion a maintainer's merge decided"))
    conflicts.add_arguments(sub.add_parser("conflicts", help="tiered PR conflict triage"))
    generated.add_arguments(sub.add_parser("generated", help="main-only generated files: guard and regen"))
    spec.add_arguments(sub.add_parser("steps", help="loop step specs: parity check and prompt render"))
    loop.add_arguments(sub.add_parser(
        "loop", help="run a loop's agent step locally with headless Claude Code: isolated, sandboxed; a run "
                     "previews, --apply files"))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        mod = {"number": number, "ratify": ratify, "conflicts": conflicts, "generated": generated,
               "steps": spec, "loop": loop}[args.group]
        return mod.main(args)
    except JevError as exc:
        print(f"jev: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

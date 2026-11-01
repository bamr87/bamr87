"""
File: tools/jev/__init__.py
Description: JEV — the harness-level agent logic engine. Its first capability is
             a tiered, mostly-deterministic PR CONFLICT triage and resolution
             engine, and the conflict-free NUMBERING scheme that removes the
             largest class of conflicts at the source (docs/JEV.md).
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage: python3 -m tools.jev --help
Dependencies: Python 3.12 stdlib + PyYAML; the `gh` CLI for anything that
              touches GitHub (every gh call JEV makes itself goes through common.gh).
"""
from __future__ import annotations

VERSION = "0.1.0"

__all__ = ["VERSION"]

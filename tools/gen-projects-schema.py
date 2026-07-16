#!/usr/bin/env python3
"""gen-projects-schema — regenerate projects/SCHEMA.md from the registry.

The structural contract for projects/ is derived, not hand-written: rows come
from .gitmodules (the authoritative submodule list), purposes from
_data/projects.yml descriptions. Every submodule is `terminal` — each project
is an independent repo carrying its own schema pyramid rooted at its own
SCHEMA.md; the hub never descends into them.

Usage:
    tools/gen-projects-schema.py            # rewrite projects/SCHEMA.md
    tools/gen-projects-schema.py --check    # exit 1 if the file is stale

Deps: PyYAML (same as the drift gate) + git.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "projects" / "SCHEMA.md"

HEADER = """\
---
schema: "0.1"
coverage: listed
---

# SCHEMA — projects

> One directory per project: each is an independent Git submodule with its
> own repo, branch, and release cycle — a separate schema pyramid rooted at
> its **own** SCHEMA.md, which the hub never descends into.

<!-- GENERATED from .gitmodules + _data/projects.yml by
     tools/gen-projects-schema.py — regenerate instead of hand-editing. -->

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | Projects index page | |
"""

FOOTER = """\

## Placement

- New project → register in `.gitmodules` **and** `_data/projects.yml` first
  (see `docs/SUBMODULE-CHECKLIST.md`), then regenerate this file.
- Seed a project's own pyramid with `tools/seed-schema.sh <name>`.

## Forbidden

- No project work committed via the hub: changes land in the submodule's own
  repo first; the hub only records pointer bumps (see CLAUDE.md).
- No non-submodule directories here — the drift gate flags strays.
"""


def submodule_paths() -> list[str]:
    out = subprocess.run(
        ["git", "config", "-f", str(ROOT / ".gitmodules"),
         "--get-regexp", r"^submodule\..*\.path$"],
        capture_output=True, text=True, check=True).stdout
    return sorted(line.split(None, 1)[1] for line in out.splitlines())


def descriptions() -> dict[str, str]:
    reg = yaml.safe_load((ROOT / "_data" / "projects.yml").read_text())
    by_path: dict[str, str] = {}
    for entry in reg or []:
        path = entry.get("submodule_path")
        if path:
            by_path[path] = entry.get("description") or ""
    return by_path


def clean(text: str, limit: int = 100) -> str:
    text = " ".join(text.replace("|", "/").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render() -> str:
    descs = descriptions()
    rows = []
    for path in submodule_paths():
        name = path.removeprefix("projects/")
        purpose = clean(descs.get(path, "")) or \
            "TODO: describe in _data/projects.yml, then regenerate"
        rows.append(f"| `{name}/` | dir | {purpose} | terminal |")
    return HEADER + "\n".join(rows) + "\n" + FOOTER


def main() -> int:
    text = render()
    if "--check" in sys.argv[1:]:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current != text:
            print("projects/SCHEMA.md is stale — regenerate with "
                  "tools/gen-projects-schema.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text)
    print(f"wrote {TARGET.relative_to(ROOT)} "
          f"({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

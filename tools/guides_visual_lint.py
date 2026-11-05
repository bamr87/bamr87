#!/usr/bin/env python3
"""
File: tools/guides_visual_lint.py
Description: Warn-then-fail lint for guide-like Markdown that lacks visual
             front-end evidence (constitution § 24 / docs/VISUAL-EVIDENCE.md).
             Default is warn-only (exit 0); --gate exits 1 when gaps remain.
Author: bamr87
Created: 2026-11-05
Usage: python3 tools/guides_visual_lint.py check [PATH] [--gate] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

IMG_RE = re.compile(
    r"!\[.*?\]\(|<img\s|test/evidence/|docs/assets/guides/|\.(?:png|gif|webp|jpe?g|mp4|webm)\b",
    re.I,
)
SKIP_RE = re.compile(r"(?m)^skip-visuals:\s*\S+")
# Prefer checklist / table rows: "- [ ] `path.md`" or "| `path.md` |"
BACKLOG_PATH_RE = re.compile(
    r"(?:^\s*-\s*\[[ xX]\]\s*|\|\s*)`([^`]+\.(?:md|MD))`",
    re.M,
)
BROKEN_LINK_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _repo(path: Path) -> Path:
    return path.resolve()


def _backlog_paths(repo: Path) -> list[str]:
    backlog = repo / "docs" / "visual-evidence-backlog.md"
    if not backlog.is_file():
        return []
    text = backlog.read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    for m in BACKLOG_PATH_RE.finditer(text):
        p = m.group(1)
        if p.endswith(".md") and not p.startswith("http"):
            out.append(p)
    # de-dupe, preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def _has_visual(text: str) -> bool:
    return bool(IMG_RE.search(text)) or bool(SKIP_RE.search(text))


def _broken_images(repo: Path, rel: str, text: str) -> list[str]:
    broken: list[str] = []
    base = (repo / rel).parent
    for m in BROKEN_LINK_RE.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "data:")):
            continue
        # strip optional title
        target = target.split()[0].strip("'\"")
        candidate = (base / target).resolve()
        try:
            candidate.relative_to(repo.resolve())
        except ValueError:
            broken.append(target)
            continue
        if not candidate.is_file():
            broken.append(target)
    return broken


def check(repo: Path, *, gate: bool = False) -> dict:
    paths = _backlog_paths(repo)
    gaps: list[dict] = []
    broken: list[dict] = []
    checked = 0
    for rel in paths:
        p = repo / rel
        if not p.is_file():
            gaps.append({"path": rel, "reason": "listed in backlog but file missing"})
            continue
        checked += 1
        text = p.read_text(encoding="utf-8", errors="replace")
        if not _has_visual(text):
            gaps.append({"path": rel, "reason": "no image, evidence ref, or skip-visuals reason"})
        for b in _broken_images(repo, rel, text):
            broken.append({"path": rel, "target": b})
    result = {
        "checker": "guides_visual_lint",
        "section": "constitution § 24",
        "checked": checked,
        "gaps": gaps,
        "broken_images": broken,
        "gate": gate,
        "ok": not gaps and not broken if gate else True,
        "warn_only": not gate,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="lint guide backlog paths for visual evidence")
    c.add_argument("path", nargs="?", default=".", help="repo root (default: .)")
    c.add_argument("--gate", action="store_true", help="exit 1 on gaps (default: warn-only)")
    c.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    if args.cmd != "check":
        ap.error("unknown command")
    repo = _repo(Path(args.path))
    result = check(repo, gate=args.gate)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"guides_visual_lint: checked {result['checked']} backlog paths "
              f"({('gate' if args.gate else 'warn-only')})")
        for g in result["gaps"]:
            print(f"  {'FAIL' if args.gate else 'WARN'}  {g['path']}: {g['reason']}")
        for b in result["broken_images"]:
            print(f"  {'FAIL' if args.gate else 'WARN'}  {b['path']}: broken image → {b['target']}")
        if not result["gaps"] and not result["broken_images"]:
            print("  ok")
        elif not args.gate:
            print("  (warn-only; pass --gate to fail)")
    if args.gate and (result["gaps"] or result["broken_images"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

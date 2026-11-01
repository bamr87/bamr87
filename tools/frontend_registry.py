#!/usr/bin/env python3
"""
File: tools/frontend_registry.py
Description: The fleet frontend registry (constitution § 18, docs/FRONTEND-PLATFORM.md).
             Lints the `frontend:` block on every _data/projects.yml entry and
             projects the shell launcher manifest from it, so the launcher is
             generated from the registry and never hand-kept. Static, offline,
             stdlib + PyYAML.
Usage: python3 tools/frontend_registry.py lint [--registry _data/projects.yml]
       python3 tools/frontend_registry.py launcher [--registry …]   # JSON on stdout
       python3 tools/frontend_registry.py table [--registry …]      # Markdown table
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
TYPES = ("app", "console", "site", "game", "ext", "none")
TIERS = ("shell", "tokens", "none")
SURFACES = ("browser", "desktop", "mobile", "vscode", "terminal")
SHELLS = ("fleet", "zer0", "own", "none", "TBD")
KEYS = ("type", "tier", "framework", "surfaces", "token_version", "entry_url", "shell", "enforce")
REQUIRED = ("type", "tier", "framework", "surfaces", "token_version", "entry_url", "shell")


def load(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def lint_entry(e: dict) -> list[str]:
    """Problems with one registry entry's `frontend:` block ([] when clean)."""
    name = e.get("name", "?")
    fe = e.get("frontend")
    if fe is None:
        return [f"{name}: no frontend: block (use tier: none for a repo without a frontend)"] if e.get("submodule_path") else []
    if not isinstance(fe, dict):
        return [f"{name}: frontend: must be a mapping"]
    p = [f"{name}: frontend.{k} missing" for k in REQUIRED if k not in fe]
    p += [f"{name}: frontend.{k} unknown key" for k in fe if k not in KEYS]
    if fe.get("type") not in TYPES:
        p.append(f"{name}: frontend.type {fe.get('type')!r} not in {TYPES}")
    tier = fe.get("tier")
    if tier not in TIERS:
        p.append(f"{name}: frontend.tier {tier!r} not in {TIERS}")
    surf = fe.get("surfaces")
    if not isinstance(surf, list) or any(s not in SURFACES for s in surf):
        p.append(f"{name}: frontend.surfaces must be a list from {SURFACES}")
    if fe.get("shell") not in SHELLS:
        p.append(f"{name}: frontend.shell {fe.get('shell')!r} not in {SHELLS}")
    tv = str(fe.get("token_version"))
    if tv not in ("none", "TBD") and not tv.lstrip("v").replace(".", "").isdigit():
        p.append(f"{name}: frontend.token_version {tv!r} is not vX.Y.Z, none or TBD")
    if "enforce" in fe and not isinstance(fe["enforce"], bool):
        p.append(f"{name}: frontend.enforce must be true/false")
    # tier coherence
    if fe.get("type") == "none" and tier != "none":
        p.append(f"{name}: type none requires tier none")
    if tier == "none" and fe.get("type") != "none":
        p.append(f"{name}: tier none requires type none")
    if fe.get("type") in ("site", "game", "ext") and tier == "shell":
        p.append(f"{name}: a {fe.get('type')} is tokens-tier (only app/console take the full shell)")
    if fe.get("type") in ("app", "console") and tier == "tokens":
        p.append(f"{name}: an {fe.get('type')} is shell-tier")
    if fe.get("enforce") and tier == "none":
        p.append(f"{name}: enforce: true on a tier-none entry is meaningless")
    return p


def lint(reg: list[dict]) -> list[str]:
    return [x for e in reg for x in lint_entry(e)]


def launcher(reg: list[dict]) -> dict:
    """The app shell launcher manifest: every frontend with an entry point."""
    apps = []
    for e in reg:
        fe = e.get("frontend") or {}
        if fe.get("tier") in (None, "none") or e.get("status") == "archived":
            continue
        apps.append({"id": e.get("slug") or e["name"], "name": e["name"], "type": fe["type"], "tier": fe["tier"],
                     "surfaces": fe.get("surfaces") or [], "url": fe.get("entry_url"),
                     "deep_link": f"fleet://{e.get('slug') or e['name']}/", "description": e.get("description", "")})
    return {"schema": "fleet-launcher/v1", "source": "_data/projects.yml frontend:", "apps": apps}


def table(reg: list[dict]) -> str:
    rows = ["| repo | type | tier | framework | surfaces | shell |", "| --- | --- | --- | --- | --- | --- |"]
    for e in reg:
        fe = e.get("frontend")
        if fe:
            rows.append(f"| {e['name']} | {fe['type']} | {fe['tier']} | {fe['framework']} | {', '.join(fe['surfaces']) or '—'} | {fe['shell']} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("cmd", choices=("lint", "launcher", "table"))
    ap.add_argument("--registry", default=str(HUB / "_data" / "projects.yml"))
    a = ap.parse_args(argv)
    reg = load(Path(a.registry))
    if a.cmd == "launcher":
        print(json.dumps(launcher(reg), indent=2))
        return 0
    if a.cmd == "table":
        print(table(reg))
        return 0
    probs = lint(reg)
    for x in probs:
        print(f"frontend: {x}")
    n = sum(1 for e in reg if e.get("frontend"))
    print(f"frontend registry: {n} entries, {len(probs)} problem(s)")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())

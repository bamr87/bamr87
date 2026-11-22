#!/usr/bin/env python3
"""ux_layout.py — the hub side of the ux-audit layout capture (`dash ux`).

The registry's `ux:` block (docs/UX-HARNESS.md) names each project's surfaces; this
tool is their reader. It projects them into capture targets and runs the kit's
Playwright scripts (templates/ux-audit/scripts/layout_capture.mjs and
layout_compare.mjs), which load each page at phone, tablet and desktop widths and
write a geometry snapshot, a wireframe SVG and a screenshot per page and width,
with the layout rules (L1–L6) it broke.

  dash ux targets      [--repo R]... [--role ROLE]            the targets the registry declares (JSON)
  dash ux capture      [--repo R]... [--role ROLE] [--out DIR] [--viewports phone,tablet,desktop]
                       [--color-scheme light|dark] [--inject-css FILE] [--no-png]
  dash ux compare      BASE HEAD [--out DIR] [--fail-on none|regression]
  dash ux consistency  RUN [--out DIR]

Scope (docs/UX-HARNESS.md): an entry is in scope when `ux.enabled` is true, or when
it has no `ux.enabled` but has a `live_url` and is not archived. An in-scope entry
without `ux.surfaces` contributes its `live_url` as `home`; a relative surface URL
is joined to the `live_url`.

Read-only: it loads public pages and writes only under --out (default
.fleet/ux/<UTC stamp>/). Warn-only: findings never fail; `capture` exits 2 only
when nothing was captured, which is a broken harness, not a clean audit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "_data" / "projects.yml"
KIT = Path(os.environ.get("UX_KIT_DIR", ROOT / "templates" / "ux-audit"))
OUT_ROOT = ROOT / ".fleet" / "ux"
INSTALL_HINT = "cd templates/ux-audit && npm install --no-package-lock && npx playwright install chromium"


def load_registry(path: Path = REGISTRY) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else data.get("projects", [])


def in_scope(entry: dict) -> bool:
    ux = entry.get("ux")
    if isinstance(ux, dict) and "enabled" in ux:
        return bool(ux["enabled"])
    return bool(entry.get("live_url")) and entry.get("status") != "archived"


def path_slug(url: str) -> str:
    """Same slug as layout_capture.mjs pathSlug, so ids match across the two."""
    parts = urlsplit(url)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    path = re.sub(r"\.html?$", "", path)
    return re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower() or "home"


def targets(registry: list[dict], repos: list[str] | None = None, role: str | None = None) -> list[dict]:
    wanted = {r.lower() for r in repos or []}
    if wanted:
        known = {str(e.get(k, "")).lower() for e in registry for k in ("name", "slug")}
        unknown = sorted(wanted - known)
        if unknown:
            raise SystemExit(f"dash ux: not in the registry: {', '.join(unknown)}")
    out: list[dict] = []
    for entry in registry:
        name = entry.get("slug") or entry.get("name")
        if wanted and not ({str(entry.get("name", "")).lower(), str(name).lower()} & wanted):
            continue
        if not in_scope(entry):
            continue
        live = entry.get("live_url")
        ux = entry.get("ux") if isinstance(entry.get("ux"), dict) else {}
        surfaces = ux.get("surfaces") or ([{"url": live, "role": "home"}] if live else [])
        for surface in surfaces:
            url = str(surface.get("url") or "")
            if not urlsplit(url).scheme:
                if not live:
                    print(f"dash ux: {name}: relative surface {url!r} and no live_url; skipped", file=sys.stderr)
                    continue
                url = urljoin(live.rstrip("/") + "/", url.lstrip("/"))
            surface_role = surface.get("role")
            if role and surface_role != role:
                continue
            out.append({"id": f"{name}--{path_slug(url)}", "site": name, "role": surface_role, "url": url})
    return out


def _node(script: str, args: list[str]) -> int:
    node = shutil.which("node")
    if not node:
        print("dash ux: node is not installed", file=sys.stderr)
        return 2
    if not (KIT / "node_modules" / "playwright").is_dir():
        print(f"dash ux: the kit's playwright is not installed: {INSTALL_HINT}", file=sys.stderr)
        return 2
    return subprocess.call([node, str(KIT / "scripts" / script), *args])


def _default_out() -> Path:
    return OUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cmd_targets(a: argparse.Namespace) -> int:
    print(json.dumps(targets(load_registry(), a.repo, a.role), indent=1))
    return 0


def cmd_capture(a: argparse.Namespace) -> int:
    found = targets(load_registry(), a.repo, a.role)
    if not found:
        print("dash ux: no in-scope surface matches", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else _default_out()
    out.mkdir(parents=True, exist_ok=True)
    (out / "targets.json").write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    args = ["--targets", str(out / "targets.json"), "--out", str(out), "--viewports", a.viewports, "--color-scheme", a.color_scheme]
    if a.inject_css:
        args += ["--inject-css", a.inject_css]
    if a.no_png:
        args.append("--no-png")
    status = _node("layout_capture.mjs", args)
    roles = [t["role"] for t in found if t["role"]]
    if status != 2 and any(roles.count(r) > 1 for r in set(roles)):
        _node("layout_compare.mjs", ["--consistency", str(out)])
    if status != 2:
        print(f"\nrun: {out}\nnext: dash ux compare {out} <later run>   ·   dash ux consistency {out}")
    return status


def cmd_compare(a: argparse.Namespace) -> int:
    args = ["--base", a.base, "--head", a.head, "--fail-on", a.fail_on]
    if a.out:
        args += ["--out", a.out]
    return _node("layout_compare.mjs", args)


def cmd_consistency(a: argparse.Namespace) -> int:
    args = ["--consistency", a.run]
    if a.out:
        args += ["--out", a.out]
    return _node("layout_compare.mjs", args)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dash ux", description="Layout capture over the registry's ux.surfaces (ux-audit kit, rules L1–L6).")
    sub = p.add_subparsers(dest="cmd")
    for name in ("targets", "capture"):
        s = sub.add_parser(name)
        s.add_argument("--repo", action="append", help="registry name or slug (repeatable)")
        s.add_argument("--role", help="only surfaces with this role (home, section, …)")
        if name == "capture":
            s.add_argument("--out", help="run directory (default .fleet/ux/<UTC stamp>/)")
            s.add_argument("--viewports", default="phone,tablet,desktop")
            s.add_argument("--color-scheme", default="light", choices=("light", "dark"))
            s.add_argument("--inject-css", help="CSS file applied to every page before measuring: preview a fix")
            s.add_argument("--no-png", action="store_true", help="skip screenshots")
    s = sub.add_parser("compare")
    s.add_argument("base")
    s.add_argument("head")
    s.add_argument("--out")
    s.add_argument("--fail-on", default="none", choices=("none", "regression"))
    s = sub.add_parser("consistency")
    s.add_argument("run")
    s.add_argument("--out")
    a = p.parse_args(argv)
    handlers = {"targets": cmd_targets, "capture": cmd_capture, "compare": cmd_compare, "consistency": cmd_consistency}
    if a.cmd not in handlers:
        p.print_help()
        return 0
    return handlers[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

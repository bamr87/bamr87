#!/usr/bin/env python3
"""The fleet's frontends as one launcher — what the app portal renders on every surface.

`launcher()` joins each registry `frontend:` block (constitution § 18,
docs/FRONTEND-PLATFORM.md) to the places that frontend can be reached:

  live   the deployed site: `frontend.entry_url`, else the entry's `live_url`
  local  the dev stack on this machine: the project's browser-facing services
         in `_data/ports.yml` (what `tools/dash dev up <project>` publishes on
         127.0.0.1), the most page-like one first

so the console's Apps page, `tools/dash apps` and every later surface (the
VS Code extension, the mobile shell) open the same app at the same address
(docs/adr/0005-console-as-fleet-portal.md). Pure over the two registries:
nothing here probes a port, starts a stack or opens a browser.

Usage (from tools/, as `tools/dash apps` runs it):
    python3 -m fleetcore.apps [list]                       # the table
    python3 -m fleetcore.apps url <app> [--target T] [--path /p]
    python3 -m fleetcore.apps json                         # the launcher document
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml

HUB = Path(__file__).resolve().parents[2]
SCHEMA = "fleet-launcher/v1"
# A frontend the portal can show in a frame: something a browser renders.
EMBED_TYPES = ("app", "console", "site", "game")
# The ports.yml bands a browser can open, most page-like first: that order
# picks a project's primary local target (law-ai's `frontend` before `backend`).
WEB_BANDS = ("frontend", "jekyll", "docs", "api")
LOCAL_HOST = "127.0.0.1"
# The verify kit's device matrix (verify/verify.yml `viewports:`) when the
# file is absent: the portal's presets and a scenario's viewports are one list.
DEFAULT_VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "tablet": {"width": 768, "height": 1024},
                     "mobile": {"width": 390, "height": 844}}


def _load(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def app_id(entry: dict) -> str:
    return str(entry.get("slug") or entry["name"])


def ports_entry(ports: dict | None, entry: dict) -> tuple[str | None, dict | None]:
    """This project's `_data/ports.yml` allocation, matched without regard to
    case on its slug, name or submodule directory (`zer0-CMS` ↔ `zer0-cms`)."""
    projects = (ports or {}).get("projects") or {}
    by_lower = {str(k).lower(): k for k in projects}
    sub = entry.get("submodule_path")
    for cand in (entry.get("slug"), entry.get("name"), Path(sub).name if sub else None):
        key = by_lower.get(str(cand or "").lower())
        if key and isinstance(projects[key], dict):
            return key, projects[key]
    return None, None


def local_targets(ports: dict | None, entry: dict) -> list[dict]:
    """The project's local dev services a browser can open, primary first.

    Only a compose-hosted project has an address here: its services publish
    the ports `_data/ports.yml` allocates, whoever starts them. A devenv-hosted
    project is served from the workspace container on a port picked at launch
    (.vscode/launch.json), so it has no fixed local address to offer."""
    key, proj = ports_entry(ports, entry)
    if not proj or proj.get("host") != "compose":
        return []
    ranked = []
    for order, (svc, spec) in enumerate((proj.get("services") or {}).items()):
        if not isinstance(spec, dict) or spec.get("band") not in WEB_BANDS:
            continue
        port = spec.get("port")
        if isinstance(port, bool) or not isinstance(port, int):
            continue
        ranked.append((WEB_BANDS.index(spec["band"]), order, str(svc), spec["band"], port))
    out = []
    for i, (_, _, svc, band, port) in enumerate(sorted(ranked)):
        out.append({
            "id": "local" if i == 0 else f"local-{svc}", "kind": "local",
            "label": "Local" if i == 0 else f"Local · {svc}",
            "url": f"http://{LOCAL_HOST}:{port}/", "service": svc, "port": port, "band": band,
            "start": f"tools/dash dev up {key}",
        })
    return out


def targets(entry: dict, ports: dict | None) -> list[dict]:
    fe = entry.get("frontend") or {}
    live = fe.get("entry_url") or entry.get("live_url")
    out = [{"id": "live", "kind": "live", "label": "Live", "url": str(live)}] if live else []
    return out + local_targets(ports, entry)


def launcher(registry: list[dict], ports: dict | None = None) -> dict:
    """The app shell launcher manifest: every frontend the registry declares,
    with where it runs. `url` and `deep_link` are the v1 keys; `targets` and the
    rest are additive, so a v1 reader keeps working."""
    apps = []
    for e in registry or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        fe = e.get("frontend") or {}
        if fe.get("tier") in (None, "none") or e.get("status") == "archived":
            continue
        tg = targets(e, ports)
        surfaces = list(fe.get("surfaces") or [])
        _, proj = ports_entry(ports, e)
        apps.append({
            "id": app_id(e), "name": e["name"], "type": fe.get("type"), "tier": fe.get("tier"),
            "surfaces": surfaces, "url": fe.get("entry_url"), "deep_link": f"fleet://{app_id(e)}/",
            "description": e.get("description", ""), "framework": fe.get("framework"), "shell": fe.get("shell"),
            "token_version": str(fe.get("token_version")), "enforce": bool(fe.get("enforce")),
            "status": e.get("status"), "category": e.get("category"), "featured": bool(e.get("featured")),
            "repo_url": e.get("repo_url"), "targets": tg,
            # frame = a browser surface with somewhere to point it; everything
            # else (an extension, a mobile app, a desktop build) is listed, not shown.
            "embed": "frame" if fe.get("type") in EMBED_TYPES and "browser" in surfaces and tg else "none",
            "local_host": (proj or {}).get("host"),
        })
    return {"schema": SCHEMA, "source": "_data/projects.yml frontend: ⨝ _data/ports.yml", "apps": apps}


def viewports(root: Path) -> list[dict]:
    """The device matrix, from the verify kit so the portal and a scenario agree."""
    doc = _load(root / "verify" / "verify.yml") or {}
    raw = doc.get("viewports") if isinstance(doc, dict) else None
    raw = raw if isinstance(raw, dict) and raw else DEFAULT_VIEWPORTS
    out = []
    for name, v in raw.items():
        if isinstance(v, dict) and isinstance(v.get("width"), int) and isinstance(v.get("height"), int):
            out.append({"id": str(name), "width": v["width"], "height": v["height"]})
    return out


def summary(apps: list[dict]) -> dict:
    def count(key: str) -> dict:
        out: dict[str, int] = {}
        for a in apps:
            out[str(a.get(key))] = out.get(str(a.get(key)), 0) + 1
        return out
    kinds = [{t["kind"] for t in a["targets"]} for a in apps]
    return {"apps": len(apps), "embeddable": sum(a["embed"] == "frame" for a in apps),
            "live": sum("live" in k for k in kinds), "local": sum("local" in k for k in kinds),
            "by_type": count("type"), "by_shell": count("shell"), "by_tier": count("tier")}


def apps_view(root: Path) -> dict:
    """The portal document (/api/apps): the launcher, the device matrix, the counts."""
    doc = launcher(_load(root / "_data" / "projects.yml") or [], _load(root / "_data" / "ports.yml") or {})
    doc["viewports"] = viewports(root)
    doc["summary"] = summary(doc["apps"])
    return doc


_PLAIN_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")
_origins_seen: dict[str, tuple[tuple[int, ...], list[str]]] = {}


def origin(url: str) -> str | None:
    """`scheme://host[:port]` of an http(s) address, else None. Only a plain
    host is accepted, so a registry value can never carry a space, a `;` or
    credentials into the policy that lists these origins."""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not _PLAIN_HOST.match(parts.netloc):
        return None
    return f"{parts.scheme}://{parts.netloc.lower()}"


def origins(apps: list[dict]) -> list[str]:
    """Every origin the portal frames: the targets of the apps it can show."""
    found = {origin(t["url"]) for a in apps if a.get("embed") == "frame" for t in a["targets"]}
    return sorted(o for o in found if o)


def target_origins(root: Path) -> list[str]:
    """`origins()` of this tree's launcher. The console asks on every response
    (its Content-Security-Policy names them), so the two registries are
    re-read only when one of them changed."""
    files = (root / "_data" / "projects.yml", root / "_data" / "ports.yml")
    stamp = tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in files)
    hit = _origins_seen.get(str(root))
    if hit and hit[0] == stamp:
        return hit[1]
    out = origins(launcher(_load(files[0]) or [], _load(files[1]) or {})["apps"])
    _origins_seen[str(root)] = (stamp, out)
    return out


def find(apps: list[dict], ref: str) -> dict | None:
    want = ref.lower()
    return next((a for a in apps if want in (a["id"].lower(), a["name"].lower())), None)


def resolve(apps: list[dict], ref: str, target: str | None = None, path: str = "") -> str:
    """The address of one app at one target. ValueError names what does exist."""
    app = find(apps, ref)
    if app is None:
        raise ValueError(f"no frontend named '{ref}' (known: {', '.join(a['id'] for a in apps)})")
    if not app["targets"]:
        raise ValueError(f"{app['id']} has no live or local address in the registry")
    tg = next((t for t in app["targets"] if t["id"] == target), None) if target else app["targets"][0]
    if tg is None:
        raise ValueError(f"{app['id']} has no target '{target}' (has: {', '.join(t['id'] for t in app['targets'])})")
    return urljoin(tg["url"], path.lstrip("/")) if path else tg["url"]


def _table(apps: list[dict]) -> str:
    rows = [("app", "type", "framework", "shell", "live", "local")]
    for a in apps:
        live = next((t["url"] for t in a["targets"] if t["kind"] == "live"), "—")
        local = next((t["url"] for t in a["targets"] if t["kind"] == "local"), "—")
        rows.append((a["id"], str(a["type"]), str(a["framework"]), str(a["shell"]), live, local))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dash apps", description="The fleet's frontends and where each one runs.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="every frontend with its live and local address (the default)")
    sub.add_parser("json", help="the launcher document (fleet-launcher/v1)")
    u = sub.add_parser("url", help="print the address of one app at one target")
    u.add_argument("app")
    u.add_argument("--target", help="live, local or local-<service> (default: the app's first target)")
    u.add_argument("--path", default="", help="a path inside the app")
    a = ap.parse_args(argv)
    doc = apps_view(HUB)
    if a.cmd == "json":
        print(json.dumps(doc, indent=2))
        return 0
    if a.cmd == "url":
        try:
            print(resolve(doc["apps"], a.app, a.target, a.path))
        except ValueError as exc:
            print(f"dash apps: {exc}", file=sys.stderr)
            return 2
        return 0
    s = doc["summary"]
    print(_table(doc["apps"]))
    print(f"\n{s['apps']} frontends · {s['embeddable']} open in the console · {s['live']} live · {s['local']} with a local stack")
    return 0


if __name__ == "__main__":
    sys.exit(main())

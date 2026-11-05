#!/usr/bin/env python3
"""
File: tools/frontend_registry.py
Description: The fleet frontend registry (constitution § 18, docs/FRONTEND-PLATFORM.md).
             Lints the `frontend:` block on every _data/projects.yml entry and
             projects the shell launcher manifest from it, so the launcher is
             generated from the registry and never hand-kept. Static, offline,
             stdlib + PyYAML — except `probe`, the one subcommand that reads the
             network: a GET of each registry address (never one typed on the
             command line), capped and time-limited, to say whether the app
             answers and whether it lets the fleet shell frame it (ADR 0005).
Usage: python3 tools/frontend_registry.py lint [--registry _data/projects.yml]
       python3 tools/frontend_registry.py launcher [--registry …]   # JSON on stdout
       python3 tools/frontend_registry.py table [--registry …]      # Markdown table
       python3 tools/frontend_registry.py probe [app …] [--target live|local|all] [--json] [--strict]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import apps as fapps  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
# The origins the fleet shell is served from: the public page and the local
# console. A frontend that names its framers must name one of these.
SHELL_ORIGINS = ("https://bamr87.github.io", "http://127.0.0.1:4001", "http://localhost:4001")
PROBE_TIMEOUT_S = 8
PROBE_CAP = 60
PROBE_AGENT = "fleet-frontend-probe (+https://github.com/bamr87/bamr87)"
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


def launcher(reg: list[dict], ports: dict | None = None) -> dict:
    """The app shell launcher manifest: every frontend with an entry point and
    its targets. One projection for every surface (fleetcore.apps)."""
    return fapps.launcher(reg, ports)


def frame_policy(headers: dict[str, str], shell_origins: tuple[str, ...] = SHELL_ORIGINS) -> tuple[str, bool]:
    """(policy, frameable) from a response's headers. `X-Frame-Options` of any
    value refuses a cross-origin shell; a CSP `frame-ancestors` list admits it
    only when it names `*` or one of the shell's origins."""
    h = {k.lower(): v for k, v in headers.items()}
    xfo = h.get("x-frame-options", "").strip().lower()
    m = re.search(r"frame-ancestors([^;]*)", h.get("content-security-policy", ""), flags=re.I)
    if m:
        sources = m.group(1).split()
        listed = "*" in sources or any(o in sources for o in shell_origins)
        return "frame-ancestors " + (" ".join(sources) or "'none'"), listed and not xfo
    if xfo:
        return f"x-frame-options {xfo}", False
    return "open", True


_META_REFRESH = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["'][^"'>]*url=([^"'>\s]+)""", re.I)
PROBE_BODY_BYTES = 8192


def moved_to(requested: str, final: str, body: str) -> str | None:
    """The origin an address hands the browser on to, when it is not its own:
    an HTTP redirect (the final URL) or a client-side one (`<meta refresh>`,
    how a static apex page forwards to www). A frame follows either, and the
    shell's policy then judges the origin it lands on, not the one asked for."""
    here = fapps.origin(requested)
    for candidate in (final, (m.group(1) if (m := _META_REFRESH.search(body)) else None)):
        there = fapps.origin(urllib.parse.urljoin(final, candidate)) if candidate else None
        if there and there != here:
            return there
    return None


def probe_one(app: dict, target: dict, known: frozenset[str] = frozenset(), timeout: float = PROBE_TIMEOUT_S) -> dict:
    row = {"app": app["id"], "target": target["id"], "url": target["url"], "status": None, "ok": False,
           "policy": None, "frameable": None, "moves_to": None, "error": None}
    req = urllib.request.Request(target["url"], headers={"User-Agent": PROBE_AGENT}, method="GET")
    final, body = target["url"], ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 — a registry URL, http(s) only
            row["status"] = res.status
            headers = dict(res.headers.items())
            final = res.geturl()
            body = res.read(PROBE_BODY_BYTES).decode("latin-1", "replace")
    except urllib.error.HTTPError as exc:
        row["status"] = exc.code
        headers = dict(exc.headers.items()) if exc.headers else {}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        row["error"] = str(getattr(exc, "reason", exc))[:120]
        return row
    row["ok"] = 200 <= (row["status"] or 0) < 400
    row["policy"], row["frameable"] = frame_policy(headers)
    row["moves_to"] = moved_to(target["url"], final, body)
    if row["moves_to"] and row["moves_to"] not in known:
        # The shell frames only origins the registry declares (its frame-src).
        row["policy"], row["frameable"] = f"moves to {row['moves_to']}, which no registry entry declares", False
    return row


def probe(apps: list[dict], which: str = "live", only: list[str] | None = None, cap: int = PROBE_CAP) -> list[dict]:
    """Ask each registry address whether it answers and whether it can be
    framed. Read-only; at most `cap` requests, each bounded by the timeout."""
    want = {x.lower() for x in only or []}
    known = frozenset(fapps.origins(apps))
    jobs = []
    for a in apps:
        if want and a["id"].lower() not in want and a["name"].lower() not in want:
            continue
        for t in a["targets"]:
            if which == "all" or t["kind"] == which:
                if not re.match(r"^https?://", t["url"]):
                    continue
                jobs.append((a, t))
    jobs = jobs[:cap]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda j: probe_one(j[0], j[1], known), jobs))


def probe_table(rows: list[dict]) -> str:
    out = [("app", "target", "status", "frame", "url")]
    for r in rows:
        status = str(r["status"]) if r["status"] is not None else f"down ({r['error']})"
        frame = "—" if r["frameable"] is None else ("yes" if r["frameable"] else f"no ({r['policy']})")
        out.append((r["app"], r["target"], status, frame, r["url"]))
    widths = [max(len(x[i]) for x in out) for i in range(len(out[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(x, widths)).rstrip() for x in out)


def table(reg: list[dict]) -> str:
    rows = ["| repo | type | tier | framework | surfaces | shell |", "| --- | --- | --- | --- | --- | --- |"]
    for e in reg:
        fe = e.get("frontend")
        if fe:
            rows.append(f"| {e['name']} | {fe['type']} | {fe['tier']} | {fe['framework']} | {', '.join(fe['surfaces']) or '—'} | {fe['shell']} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("cmd", choices=("lint", "launcher", "table", "probe"))
    ap.add_argument("apps", nargs="*", help="probe: only these apps (default: every frontend)")
    ap.add_argument("--registry", default=str(HUB / "_data" / "projects.yml"))
    ap.add_argument("--ports", default=str(HUB / "_data" / "ports.yml"))
    ap.add_argument("--target", choices=("live", "local", "all"), default="live", help="probe: which addresses")
    ap.add_argument("--json", action="store_true", help="probe: rows as JSON")
    ap.add_argument("--strict", action="store_true", help="probe: exit 1 when an address is down or refuses the shell")
    a = ap.parse_args(argv)
    reg = load(Path(a.registry))
    ports_path = Path(a.ports)
    ports = (yaml.safe_load(ports_path.read_text(encoding="utf-8")) or {}) if ports_path.is_file() else {}
    if a.cmd == "launcher":
        print(json.dumps(launcher(reg, ports), indent=2))
        return 0
    if a.cmd == "table":
        print(table(reg))
        return 0
    if a.cmd == "probe":
        rows = probe(launcher(reg, ports)["apps"], a.target, a.apps)
        if a.json:
            print(json.dumps(rows, indent=2))
        else:
            print(probe_table(rows) if rows else "frontend probe: no address matches")
            up = sum(r["ok"] for r in rows)
            print(f"\nfrontend probe: {up}/{len(rows)} answer · {sum(bool(r['frameable']) for r in rows)} can be framed by the shell")
        bad = [r for r in rows if not r["ok"] or not r["frameable"]]
        return 1 if a.strict and bad else 0
    probs = lint(reg)
    for x in probs:
        print(f"frontend: {x}")
    n = sum(1 for e in reg if e.get("frontend"))
    print(f"frontend registry: {n} entries, {len(probs)} problem(s)")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())

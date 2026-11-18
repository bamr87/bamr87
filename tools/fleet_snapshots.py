#!/usr/bin/env python3
"""
File: tools/fleet_snapshots.py
Description: The shrink guard of the weekly fleet-snapshots writer
             (.github/workflows/fleet-snapshots.yml, bamr87/bamr87#775).

             The workflow checks out every registry submodule its token can
             read, regenerates _data/conformance.yml (`dash spec fleet --write`)
             and _data/features_index.yml (`dash features fleet --write`) over
             them, and runs this guard before anything is published. Both
             generators succeed on an empty checkout: a dead or narrowed token
             clones nothing, and the week's snapshot would quietly become a
             hub-only one. fleet-pulse published exactly that features index,
             `repos_scanned: 1`, every day until this writer replaced its step.

             The guard compares each regenerated snapshot with a copy of the
             committed one (--before DIR) and refuses (exit 1, `::error::`) when

               * the scan lost more than --tolerance repos the committed
                 snapshot carried and the registry still lists, or
               * the scan read no registry submodule at all.

             A repo that left the registry, that the registry now marks
             archived, or that the conformance checker now skips by tier
             (`skipped: … reason: tier fork`), is excused: that shrink is the
             registry's, not the token's. Every registry submodule that is not
             checked out is listed in the report either way, so a tolerated
             loss is still visible. --summary appends the report as Markdown
             (the job summary).
Usage: python3 tools/fleet_snapshots.py --before DIR [--hub PATH] [--tolerance N] [--summary FILE]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
# Snapshot kind → its file under _data/ (and under --before).
SNAPSHOTS = {"conformance": "conformance.yml", "features_index": "features_index.yml"}
# The registry entry the hub would have if it had one: features_index.py adds the
# hub to its scan under this name. It is never excused.
HUB_NAME = "bamr87"
DEFAULT_TOLERANCE = 2


def load(path: Path) -> dict | None:
    """The snapshot at `path`, or None when the file does not exist."""
    if not path.is_file():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def repo_names(doc: dict | None) -> list[str]:
    """The repos a snapshot read: both generators list one `repos:` row per repo."""
    rows = (doc or {}).get("repos") or []
    return sorted({str(r["name"]) for r in rows if isinstance(r, dict) and r.get("name")})


def registry_submodules(hub: Path) -> dict[str, dict]:
    """Registry entries that are submodules, by name (the hub's own repo is not one)."""
    reg = yaml.safe_load((hub / "_data" / "projects.yml").read_text(encoding="utf-8")) or []
    return {str(e["name"]): e for e in reg if isinstance(e, dict) and e.get("name") and e.get("submodule_path")}


def unreadable(hub: Path, registry: dict[str, dict]) -> list[dict]:
    """Non-archived registry submodules with no checkout here (the clone failed or was never tried)."""
    out = []
    for name, e in sorted(registry.items()):
        if str(e.get("status")) == "archived":
            continue
        if not (hub / str(e["submodule_path"]) / ".git").exists():
            out.append({"name": name, "path": str(e["submodule_path"])})
    return out


def excused(kind: str, name: str, registry: dict[str, dict], after: dict) -> str | None:
    """Why losing `name` from a `kind` snapshot is not a read failure, or None when it is."""
    if name == HUB_NAME and kind == "features_index":
        return None
    e = registry.get(name)
    if e is None:
        return "no longer a registry submodule"
    if str(e.get("status")) == "archived":
        return "archived in the registry"
    if kind == "conformance":
        for s in after.get("skipped") or []:
            if isinstance(s, dict) and s.get("name") == name and str(s.get("reason", "")).startswith("tier "):
                return f"the checker skips it ({s['reason']})"
    return None


def compare(kind: str, before: dict | None, after: dict | None, registry: dict[str, dict],
            tolerance: int = DEFAULT_TOLERANCE) -> dict:
    """One snapshot's verdict: what the committed one read, what this scan read, what was lost."""
    file = SNAPSHOTS[kind]
    if after is None:
        return {"kind": kind, "file": file, "before": len(repo_names(before)), "after": 0, "lost": [],
                "excused": {}, "unread": [], "ok": False,
                "problems": [f"{file}: the generator wrote no file"]}
    had, has = set(repo_names(before)), set(repo_names(after))
    lost = sorted(had - has)
    why = {n: w for n in lost if (w := excused(kind, n, registry, after)) is not None}
    unread = [n for n in lost if n not in why]
    problems = []
    if registry and not has & set(registry):
        problems.append(f"{file}: the scan read no registry submodule at all "
                        f"({len(has)} repo(s), {len(registry)} in the registry)")
    if len(unread) > tolerance:
        problems.append(f"{file}: the scan lost {len(unread)} repo(s) the committed snapshot read "
                        f"({len(had)} → {len(has)}; tolerance {tolerance}): {', '.join(unread)}")
    return {"kind": kind, "file": file, "before": len(had), "after": len(has), "lost": lost,
            "excused": why, "unread": unread, "ok": not problems, "problems": problems}


def guard(hub: Path, before_dir: Path, tolerance: int = DEFAULT_TOLERANCE) -> tuple[bool, list[dict], list[dict]]:
    """(ok, one verdict per snapshot, the registry submodules not checked out)."""
    registry = registry_submodules(hub)
    results = [compare(kind, load(before_dir / file), load(hub / "_data" / file), registry, tolerance)
               for kind, file in SNAPSHOTS.items()]
    return all(r["ok"] for r in results), results, unreadable(hub, registry)


def render(ok: bool, results: list[dict], missing: list[dict], tolerance: int) -> str:
    lines = ["### Fleet snapshots: shrink guard", "",
             f"Verdict: **{'publish' if ok else 'refused, nothing published'}** (tolerance {tolerance} repo(s) per snapshot)", "",
             "| Snapshot | Committed | This scan | Lost (excused) | Verdict |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        lost = f"{len(r['lost'])} ({len(r['excused'])})"
        lines.append(f"| `{r['file']}` | {r['before']} | {r['after']} | {lost} | {'ok' if r['ok'] else 'refused'} |")
    lines.append("")
    for r in results:
        for p in r["problems"]:
            lines.append(f"- {p}")
        for name, why in sorted(r["excused"].items()):
            lines.append(f"- `{r['file']}`: `{name}` is no longer read and is excused: {why}")
    if missing:
        lines += ["", f"**Registry submodules with no checkout ({len(missing)}):** "
                  + ", ".join(f"`{m['name']}` (`{m['path']}`)" for m in missing)]
    else:
        lines += ["", "Every non-archived registry submodule was checked out."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet_snapshots.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True, metavar="DIR",
                    help="copies of the committed conformance.yml and features_index.yml, taken before regenerating")
    ap.add_argument("--hub", default=str(HUB), help="the hub checkout whose _data/ holds the regenerated snapshots")
    ap.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE,
                    help=f"repos a snapshot may lose before it is refused (default {DEFAULT_TOLERANCE})")
    ap.add_argument("--summary", metavar="FILE", help="append the report to FILE (the job summary)")
    a = ap.parse_args(argv)
    if a.tolerance < 0:
        ap.error("--tolerance is 0 or more")

    ok, results, missing = guard(Path(a.hub), Path(a.before), a.tolerance)
    report = render(ok, results, missing, a.tolerance)
    print(report, end="")
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    for m in missing:
        print(f"::warning::{m['name']} ({m['path']}) is a registry submodule this run could not check out")
    for r in results:
        for p in r["problems"]:
            print(f"::error::{p}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
File: .github/scripts/dash-gen/agent_fill.py
Description: `dash-gen agent-fill` — the planner of the fan-out agent fill on
             the JEV loop runner (bamr87/bamr87#488, ADR 0002 P3). CI's
             agent-fill job (fanout.yml) runs one claude-code-action step per
             kit on ONE named target's kit branch after the fan-out pushed it;
             this planner emits that same unit of work as JSON items, one per
             target repository: the registry's bamr87-owned, non-archived
             entries (the fan-out's own target list), each at the kit's branch
             (`chore/standardize-baseline`, `chore/schema-adoption`). Online it
             checks the branch exists and whether the agent pass already
             landed (a `(Claude agent pass)` commit on it: CI's dedupe), and
             skips what cannot or need not run; `--offline` emits every target
             with its branch state unknown. Read-only: GitHub GETs only.
             The prompt has no caller-filled part, so every row carries the
             spec's own bytes as `prompt`, as scout's and the doctor's plans do.
Author: bamr87
Created: 2026-11-03
Version: 0.1.0
Usage:
    dash-gen agent-fill --kit standardize --plan-dir <dir> [--target NAME|all] [--offline]
Output: one JSON object on stdout (the plan; written to <dir>/plan.json too);
        exit 1 when a named --target yields no item, 2 on a usage error.
Dependencies: Python 3.12 stdlib, PyYAML, `gh` on PATH unless --offline;
              tools/jev/spec.py for the prompt bytes (never imports the dash-gen entry point).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from evolution import step_spec

HUB = Path(__file__).resolve().parents[3]
REGISTRY_DEFAULT = HUB / "_data" / "projects.yml"
OWNER = "bamr87"
LOOP = "fanout"
#: The kits with an agent pass, as fanout.yml's plan job and push step name them.
KITS: dict[str, dict[str, str]] = {
    "standardize": {"branch": "chore/standardize-baseline",
                    "subject": "docs(agent-context): fill CLAUDE.md scaffold (Claude agent pass)"},
    "schema": {"branch": "chore/schema-adoption",
               "subject": "docs(schema): fill scaffold purposes (Claude agent pass)"},
}
#: CI's dedupe is the commit the push step makes: a branch carrying one is filled.
AGENT_PASS_MARK = "(Claude agent pass)"
NWO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
COMMIT_WINDOW = 30


def gh_json(args: list[str], *, timeout: int = 60) -> tuple[object | None, str]:
    """`gh api …` as parsed JSON, or (None, why). GET only."""
    try:
        proc = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"gh: {exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[-200:]
    try:
        return json.loads(proc.stdout or "null"), ""
    except ValueError as exc:
        return None, f"gh printed no JSON: {exc}"


def branch_state(nwo: str, branch: str) -> tuple[str, str]:
    """('present' | 'missing' | 'unknown', 'clear' | 'filled' | 'unavailable').
    Missing is a 404 on the branch; anything else that fails is unknown, and
    the dedupe is then unavailable (a filer never writes on that)."""
    data, why = gh_json([f"repos/{nwo}/branches/{branch}"])
    if data is None:
        if "404" in why or "Not Found" in why:
            return "missing", "clear"
        return "unknown", "unavailable"
    commits, why = gh_json([f"repos/{nwo}/commits?sha={branch}&per_page={COMMIT_WINDOW}"])
    if not isinstance(commits, list):
        return "present", "unavailable"
    for c in commits:
        msg = str(((c or {}).get("commit") or {}).get("message") or "")
        first = msg.splitlines()[0] if msg else ""
        if AGENT_PASS_MARK in first:
            return "present", "filled"
    return "present", "clear"


def nwo_of(entry: dict) -> str | None:
    url = str(entry.get("repo_url") or "")
    prefix = "https://github.com/"
    if not url.startswith(prefix):
        return None
    nwo = url[len(prefix):].removesuffix("/").removesuffix(".git")
    return nwo if NWO_RE.fullmatch(nwo) and nwo.split("/", 1)[0] == OWNER else None


def targets(registry: list[dict], want: str) -> tuple[list[dict], list[dict]]:
    """(rows to consider, dropped): bamr87-owned, non-archived registry
    entries — the fan-out's own target list — or the ONE `want` names by
    registry name, slug or owner/repo."""
    rows: list[dict] = []
    dropped: list[dict] = []
    for e in registry:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "")
        nwo = nwo_of(e)
        if nwo is None:
            dropped.append({"name": name, "reason": "not a bamr87-owned GitHub repository"})
            continue
        if e.get("status") == "archived":
            dropped.append({"name": name, "nwo": nwo, "reason": "archived"})
            continue
        rows.append({"name": name, "slug": str(e.get("slug") or ""), "nwo": nwo})
    if want and want != "all":
        rows = [r for r in rows if want in (r["name"], r["slug"], r["nwo"])]
    return rows, dropped


def build_plan(args: argparse.Namespace) -> dict:
    kit = KITS[args.kit]
    jev = step_spec()   # evolution's loader: the hub root APPENDED, so this directory's modules keep precedence
    spec = jev.load_spec(LOOP, f"agent-fill-{args.kit}")
    try:
        registry = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8")) or []
    except OSError as exc:
        raise SystemExit(f"agent-fill: cannot read {args.registry}: {exc}")
    rows, dropped = targets(registry, args.target)
    include: list[dict] = []
    skipped: list[dict] = []
    for r in rows:
        if args.offline:
            state, dedupe = "unknown", "offline"
        else:
            state, dedupe = branch_state(r["nwo"], kit["branch"])
        row = {"key": r["nwo"], "name": r["name"], "nwo": r["nwo"], "branch": kit["branch"], "kit": args.kit,
               "commit_subject": kit["subject"], "branch_status": state, "dedupe": dedupe}
        if state == "missing":
            skipped.append({**row, "reason": f"no {kit['branch']} on {r['nwo']}: run fanout.yml (kit {args.kit}, "
                                             f"target {r['name']}, dry_run=false) first"})
            continue
        if dedupe == "filled":
            skipped.append({**row, "reason": f"{kit['branch']} already carries a {AGENT_PASS_MARK} commit"})
            continue
        # last key: the rendered prompt (no caller-filled part: the spec's own bytes)
        row["prompt"] = jev.render_prompt(spec, jev.values_from(spec, row))
        include.append(row)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"generated_at": now, "count": len(include), "include": include, "skipped": skipped, "dropped": dropped,
            "kit": args.kit, "branch": kit["branch"], "commit_subject": kit["subject"],
            "model": spec.resolved.model, "max_turns": spec.resolved.max_turns,
            "target": args.target or "all", "offline": bool(args.offline)}


def run_plan(args: argparse.Namespace) -> int:
    try:
        plan = build_plan(args)
    except Exception as exc:  # noqa: BLE001 - a spec or registry problem fails the plan, never an agent run
        sys.stderr.write(f"✗ agent-fill: {type(exc).__name__}: {exc}\n")
        return 2
    if args.plan_dir:
        out = Path(args.plan_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
        sys.stderr.write(f"Wrote plan.json ({plan['count']} item(s)) to {out}/\n")
    for r in plan["include"]:
        sys.stderr.write(f"  ▶ {r['nwo']} @ {r['branch']}  [{r['branch_status']}, dedupe {r['dedupe']}]\n")
    for s_ in plan["skipped"]:
        sys.stderr.write(f"  ⏭ {s_['nwo']}: {s_['reason']}\n")
    sys.stderr.write(f"agent-fill plan (kit {plan['kit']}): {plan['count']} item(s), {len(plan['skipped'])} skipped, "
                     f"{len(plan['dropped'])} dropped\n")
    print(json.dumps(plan, separators=(",", ":")))
    if args.target not in (None, "", "all") and plan["count"] == 0:
        return 1
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kit", required=True, choices=sorted(KITS), help="the fan-out kit whose agent pass this is")
    parser.add_argument("--plan-dir", default=None, metavar="DIR", help="write plan.json here (the loop engine's plan)")
    parser.add_argument("--target", default="all", metavar="NAME|all",
                        help="one registry name, slug or owner/repo, or every eligible target (default)")
    parser.add_argument("--offline", action="store_true",
                        help="no GitHub reads: every target is emitted with its branch state unknown")
    parser.add_argument("--registry", default=str(REGISTRY_DEFAULT), metavar="PATH")
    parser.set_defaults(func=run_plan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dash-gen agent-fill", description=__doc__.split("\n\n")[0])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

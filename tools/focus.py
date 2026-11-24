#!/usr/bin/env python3
"""
focus.py — the checks a change owes, in one pass (ADR 0016).

A change to the hub is done when the drift gate is green and "the focused
tests for what you touched pass" (AGENTS.md). Which tests those are was a
table to read and a run of CI to learn from: each companion entry a change
forgot (a SCHEMA row, an F5 entry, a switch, a README line) came back as its
own red check. This reads the change, looks up _data/checks.yml, and names
every check that change owes, so they can be run here, together, first.

It adds no rule. Every check is an existing gate or test; this only chooses
which of them the change touched:

  from the registry   a check whose `paths:` match a changed file
  beside the module   test_<name>.py for a changed Python module: next to it,
                      or tools/test_<unit>_<name>.py for a module in a package
                      under tools/ (tools/jev/loop.py -> tools/test_jev_loop.py),
                      and any changed test file itself

The change is everything that differs from the merge base with --base
(default origin/main, then main): committed, staged, unstaged and untracked.

CLI (exit 0 nothing failed, 1 a check failed, 2 the registry or git is unusable):
  focus.py [--base REF] [--json]         list the checks this change owes, and why
  focus.py --run [--base REF] [--only ID ...] [--keep-going]
                                         run them from the hub root; stops at the
                                         first failure unless --keep-going. A check
                                         whose `needs:` is missing is reported as
                                         NOT RUN: it has proved nothing.
  focus.py --all [--run]                 every check in the registry, whatever changed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

SCHEMA = "checks/v1"
REGISTRY = "_data/checks.yml"
CODE_ROOTS = ("tools/", ".github/scripts/")
TIMEOUT_S = 1800


class RegistryError(ValueError):
    """The registry is missing or malformed, or git could not answer (one-line message)."""


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def load_registry(root: Path) -> list[dict]:
    path = Path(root) / REGISTRY
    if not path.is_file():
        raise RegistryError(f"{REGISTRY}: not found")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise RegistryError(f"{REGISTRY}: not readable YAML ({e})") from e
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("checks"), list):
        raise RegistryError(f"{REGISTRY}: expected `schema: {SCHEMA}` and a `checks:` list")
    seen: set[str] = set()
    for c in doc["checks"]:
        if not isinstance(c, dict):
            raise RegistryError(f"{REGISTRY}: every check is a map")
        cid = c.get("id")
        if not isinstance(cid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", cid) or cid in seen:
            raise RegistryError(f"{REGISTRY}: check id {cid!r} is missing, malformed or repeated")
        seen.add(cid)
        for key in ("title", "run"):
            if not isinstance(c.get(key), str) or not c[key].strip():
                raise RegistryError(f"{REGISTRY}: check `{cid}` needs a `{key}`")
        for key in ("paths", "files"):
            if key in c and (not isinstance(c[key], list) or not c[key] or not all(isinstance(p, str) and p for p in c[key])):
                raise RegistryError(f"{REGISTRY}: check `{cid}` `{key}` must be a non-empty list of patterns")
        if "paths" not in c:
            raise RegistryError(f"{REGISTRY}: check `{cid}` needs `paths`")
        if "needs" in c and not isinstance(c["needs"], str):
            raise RegistryError(f"{REGISTRY}: check `{cid}` `needs` must be one executable or path")
        if "{files}" in c["run"] and c["paths"] == ["**"] and "files" not in c:
            raise RegistryError(f"{REGISTRY}: check `{cid}` passes {{files}} but matches every path; give it `files:`")
    return doc["checks"]


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`**` crosses directories, `*` and `?` stay inside one path segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matching(files: list[str], patterns: list[str]) -> list[str]:
    regexes = [glob_to_regex(p) for p in patterns]
    return [f for f in files if any(r.match(f) for r in regexes)]


# --------------------------------------------------------------------------- #
# the change
# --------------------------------------------------------------------------- #
def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RegistryError(f"git {' '.join(args)}: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'failed'}")
    return proc.stdout


def resolve_base(root: Path, base: str | None) -> str:
    for ref in ([base] if base else ["origin/main", "main"]):
        if subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          capture_output=True).returncode == 0:
            return ref
    raise RegistryError(f"base ref {base or 'origin/main or main'} not found; pass --base")


def changed_files(root: Path, base: str) -> list[str]:
    """Paths that differ from the merge base with `base`, deleted ones included (a removal owes checks too)."""
    merge_base = _git(root, "merge-base", "HEAD", base).strip()
    tracked = _git(root, "diff", "--name-only", "--no-renames", merge_base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({f for f in (*tracked, *untracked) if f and not f.startswith("projects/")})


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #
def sibling_tests(root: Path, files: list[str]) -> dict[str, list[str]]:
    """test file -> the changed files that led to it. Only tests that exist."""
    root = Path(root)
    found: dict[str, list[str]] = {}
    for f in files:
        p = Path(f)
        if p.suffix != ".py" or not f.startswith(CODE_ROOTS):
            continue
        if p.name.startswith("test_"):
            candidates = [p]
        else:
            stem = p.stem.replace("-", "_")
            candidates = [p.with_name(f"test_{stem}.py")]
            if f.startswith("tools/") and len(p.parts) >= 3:  # tools/<unit>/.../<name>.py
                unit = p.parts[1]
                candidates += [Path("tools") / f"test_{unit}_{stem}.py", Path("tools") / f"test_{unit}.py"]
        for c in candidates:
            if (root / c).is_file():
                found.setdefault(c.as_posix(), []).append(f)
                break
    return dict(sorted(found.items()))


def plan(root: Path, files: list[str], base: str, every: bool = False) -> list[dict]:
    """The checks this set of files owes, registry order first, then the sibling tests."""
    root = Path(root)
    existing = [f for f in files if (root / f).exists()]
    steps: list[dict] = []
    for c in load_registry(root):
        because = matching(files, c["paths"])
        if not because and not every:
            continue
        argv = shlex.split(c["run"])
        if "{files}" in argv:
            targets = matching(existing, c.get("files") or c["paths"])
            if not targets:
                continue  # everything that matched was deleted: nothing to hand the command
            i = argv.index("{files}")
            argv[i:i + 1] = targets
        argv = [base if a == "{base}" else a for a in argv]
        steps.append({"id": c["id"], "title": c["title"], "argv": argv, "needs": c.get("needs"), "because": because[:5],
                      "matched": len(because)})
    owed = {tuple(s["argv"]) for s in steps}
    for test, sources in sibling_tests(root, files).items():
        if ("python3", test) in owed:
            continue  # the registry already names this test file: run it once
        steps.append({"id": f"test:{test}", "title": f"Tests beside {', '.join(sources[:2])}", "argv": ["python3", test],
                      "needs": None, "because": sources[:5], "matched": len(sources)})
    return steps


def missing_need(root: Path, need: str | None) -> str | None:
    if not need:
        return None
    if "/" in need:
        return None if (Path(root) / need).exists() else need
    return None if shutil.which(need) else need


FAILURE_LINE = re.compile(r"\b(FAIL(ED)?|ERROR|Error|Traceback|AssertionError|✗)")


def failure_excerpt(output: str, marked: int = 15, tail: int = 10) -> list[str]:
    """What a failed check said: the lines that name a failure, then the last lines. A test file that
    prints one line per case puts its failure in the middle, where the last lines alone would miss it."""
    lines = output.strip().splitlines()
    hits = [line for line in lines[:-tail] if FAILURE_LINE.search(line)][:marked]
    return [*hits, *(["…"] if hits else []), *lines[-tail:]]


def run(root: Path, steps: list[dict], keep_going: bool) -> list[dict]:
    """Run each step from the hub root; `python3` is this interpreter, the one that has PyYAML."""
    results: list[dict] = []
    for step in steps:
        need = missing_need(root, step["needs"])
        if need:
            results.append({**step, "status": "not-run", "detail": f"needs {need}"})
            print(f"  -  {step['id']:26s} NOT RUN (needs {need})", flush=True)
            continue
        argv = [sys.executable if a == "python3" and i == 0 else a for i, a in enumerate(step["argv"])]
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, timeout=TIMEOUT_S,
                                  env={**os.environ, "PYTHON": os.environ.get("PYTHON", sys.executable)})
            code, output = proc.returncode, (proc.stdout + proc.stderr)
        except subprocess.TimeoutExpired:
            code, output = 124, f"timed out after {TIMEOUT_S}s"
        except OSError as e:
            code, output = 127, str(e)
        took = time.monotonic() - started
        status = "passed" if code == 0 else "failed"
        results.append({**step, "status": status, "code": code, "seconds": round(took, 1)})
        # flushed, so a run piped to a file or a CI log shows each check as it finishes
        print(f"  {'✓' if code == 0 else '✗'}  {step['id']:26s} {took:6.1f}s  {shlex.join(step['argv'])[:110]}", flush=True)
        if code != 0:
            print("\n".join(f"       {line}" for line in failure_excerpt(output)), flush=True)
            if not keep_going:
                break
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="focus.py", description="The checks a change owes, in one pass (ADR 0016).")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="hub checkout (default: this one)")
    ap.add_argument("--base", help="ref the change is compared against (default: origin/main, then main)")
    ap.add_argument("--all", action="store_true", help="every check in the registry, whatever changed")
    ap.add_argument("--run", action="store_true", help="run the checks; without it they are only listed")
    ap.add_argument("--only", nargs="+", metavar="ID", help="keep only these check ids")
    ap.add_argument("--keep-going", action="store_true", help="with --run, do not stop at the first failure")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        base = resolve_base(root, args.base)
        files = changed_files(root, base)
        steps = plan(root, files, base, every=args.all)
    except RegistryError as e:
        print(f"focus: {e}", file=sys.stderr)
        return 2
    if args.only:
        unknown = set(args.only) - {s["id"] for s in steps}
        if unknown:
            print(f"focus: not in this change's plan: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        steps = [s for s in steps if s["id"] in args.only]
    if args.json:
        print(json.dumps({"schema": "focus-plan/v1", "base": base, "changed": files, "checks": steps}, indent=2))
        return 0
    print(f"focus: {len(files)} changed file(s) against {base}; {len(steps)} check(s) owed")
    if not args.run:
        for s in steps:
            need = missing_need(root, s["needs"])
            why = ", ".join(s["because"][:2]) + (f" +{s['matched'] - 2} more" if s["matched"] > 2 else "")
            print(f"  {s['id']:26s} {shlex.join(s['argv'])[:96]}")
            print(f"  {'':26s} {s['title']}" + (f"  [{why}]" if why else "") + (f"  (needs {need}: will not run here)" if need else ""))
        print("run them: python3 tools/focus.py --run")
        return 0
    results = run(root, steps, args.keep_going)
    failed = [r for r in results if r["status"] == "failed"]
    not_run = [r for r in results if r["status"] == "not-run"] + steps[len(results):]
    passed = [r for r in results if r["status"] == "passed"]
    print(f"focus: {len(passed)} passed, {len(failed)} failed, {len(not_run)} not run")
    for r in not_run:
        print(f"  not run: {r['id']}" + (f" ({r['detail']})" if r.get("detail") else " (stopped at the first failure)"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

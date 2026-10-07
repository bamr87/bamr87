#!/usr/bin/env python3
"""
sanctioned_lockfiles.py — the one reader of the hub-only lockfile exception of
UPS-QA-40, UPS-QA-41 and UPS-REPO-07, declared in specs/QUALITY.contract.yml
(`definitions.sanctioned_lockfiles`, `definitions.sanctioned_dependabot`).

Every enforcer goes through this file, so the parsing and the rules live once:
  tools/conformance.py       imports it (QA-40 / REPO-07 exemption, QA-41 detail)
  tools/check-drift.sh (j)   imports it (drift_problems(), declared_lockfiles())
  tools/unpin-deps.sh        runs `sanctioned_lockfiles.py paths <checkout>`

Who is the hub: a checkout whose `origin` remote is bamr87/bamr87 (or, with no
remote, $GITHUB_REPOSITORY when the checkout is the working directory), or the
hub checkout itself. The list is always read from the checked repo's own
contract, never from a separate hub checkout: fleet-conformance checks the PR
at `.` with the hub at `.fleet-hub`, and the two trees can differ. Carrying a
copy of the contract does not make a member repo the hub.

What counts: an entry whose paths are all under `.github/`, none under
`templates/`, and whose `sanctioned_dependabot` entry (directory "/" + dir) is
both declared and present in .github/dependabot.yml.

CLI (exit 0 ok, 1 problems found, 2 a file it must read is malformed):
  sanctioned_lockfiles.py check [ROOT]   drift check of the declaration vs the tree
  sanctioned_lockfiles.py paths [ROOT]   "<kind>\t<path>" (kind dir|lockfile|manifest|workflow)
                                         for the covered entries; nothing unless ROOT is the hub
  sanctioned_lockfiles.py covered [ROOT] the lockfiles the exception covers, one per line
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

HUB_NWO = "bamr87/bamr87"
CONTRACT = "specs/QUALITY.contract.yml"
DEPENDABOT = ".github/dependabot.yml"
GITIGNORE = ".gitignore"
BLOCK_BEGIN, BLOCK_END = "# BEGIN sanctioned_lockfiles", "# END sanctioned_lockfiles"
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "Gemfile.lock",
             "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock")
KINDS = ("dir", "lockfile", "manifest", "workflow")
EXACT = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")


class ContractError(ValueError):
    """A file the exception depends on is unreadable or malformed (one-line message)."""


def _load(root: Path, rel: str, kind: str):
    """Parse a YAML or JSON file under root; None when absent; ContractError when malformed."""
    p = Path(root) / rel
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text) if kind == "json" else yaml.safe_load(text)
    except UnicodeDecodeError as e:
        raise ContractError(f"{rel}: not UTF-8 ({e.reason})") from e
    except json.JSONDecodeError as e:
        raise ContractError(f"{rel}: not valid JSON (line {e.lineno} col {e.colno}: {e.msg})") from e
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1} col {mark.column + 1}: " if mark else ""
        raise ContractError(f"{rel}: not valid YAML ({where}{getattr(e, 'problem', None) or e})") from e
    except OSError as e:
        raise ContractError(f"{rel}: unreadable ({e.strerror})") from e


def origin_nwo(root: Path) -> str | None:
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        url = ""
    if not url and Path(root).resolve() == Path.cwd().resolve():
        url = os.environ.get("GITHUB_REPOSITORY", "")
    m = re.search(r"(?:github\.com[:/])?([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else None


def is_hub(root: Path, hub: Path | None = None) -> bool:
    """True when `root` is the hub: the hub checkout itself, or origin bamr87/bamr87."""
    if hub is not None and Path(root).resolve() == Path(hub).resolve():
        return True
    return origin_nwo(root) == HUB_NWO


def declared(root: Path) -> tuple[list[dict], list[dict]]:
    """(sanctioned_lockfiles, sanctioned_dependabot) from root's contract; ([], []) without one."""
    data = _load(root, CONTRACT, "yaml")
    if data is None:
        return [], []
    if not isinstance(data, dict):
        raise ContractError(f"{CONTRACT}: top level is not a mapping")
    qdefs = data.get("definitions") or {}
    if not isinstance(qdefs, dict):
        raise ContractError(f"{CONTRACT}: `definitions` is not a mapping")
    out = []
    for key, need in (("sanctioned_lockfiles", ("dir", "lockfile")), ("sanctioned_dependabot", ("package-ecosystem", "directory"))):
        items = qdefs.get(key) or []
        if not isinstance(items, list):
            raise ContractError(f"{CONTRACT}: `{key}` is not a list")
        for i, e in enumerate(items):
            if not isinstance(e, dict) or any(not isinstance(e.get(k), str) or not e.get(k) for k in need):
                raise ContractError(f"{CONTRACT}: {key}[{i}] needs string keys {', '.join(need)}")
        out.append(items)
    return out[0], out[1]


def location_problem(e: dict) -> str | None:
    """Why an entry can never qualify (outside .github/, under templates/), else None."""
    paths = [str(e[k]) for k in KINDS if e.get(k)]
    if any(not p.startswith(".github/") or "templates/" in p for p in paths):
        return f"sanctioned_lockfiles `{e.get('lockfile')}`: every path must live under .github/ and never under templates/"
    return None


def _dir_key(d) -> str:
    return "/" + str(d).strip("/")


def dependabot_present(root: Path) -> set[tuple[str, str]]:
    data = _load(root, DEPENDABOT, "yaml") or {}
    if not isinstance(data, dict):
        raise ContractError(f"{DEPENDABOT}: top level is not a mapping")
    present = set()
    for u in data.get("updates") or []:
        if isinstance(u, dict):
            dirs = u.get("directories") or [u.get("directory", "")]
            for d in dirs if isinstance(dirs, list) else [dirs]:
                present.add((str(u.get("package-ecosystem")), _dir_key(d)))
    return present


def evaluate(root: Path) -> tuple[dict[str, dict], list[str]]:
    """({lockfile: entry} that qualify, [why each other entry does not]); ignores identity."""
    locks, deps = declared(root)
    declared_dep = {(str(e["package-ecosystem"]), _dir_key(e["directory"])) for e in deps}
    present = dependabot_present(root)
    ok, why = {}, []
    for e in locks:
        bad = location_problem(e)
        if bad:
            why.append(bad)
            continue
        want = _dir_key(e["dir"])
        if not any(x[1] == want and x in present for x in declared_dep):
            why.append(f"sanctioned_lockfiles `{e['lockfile']}`: no sanctioned_dependabot entry for {want} "
                       f"present in {DEPENDABOT}")
            continue
        ok[e["lockfile"]] = e
    return ok, why


def covered(root: Path, hub: Path | None = None) -> dict[str, dict]:
    """The lockfiles the exception covers for `root`: {} unless root is the hub."""
    return evaluate(root)[0] if is_hub(root, hub) else {}


def declared_lockfiles(root: Path) -> set[str]:
    return {e["lockfile"] for e in declared(root)[0]}


def drift_problems(root: Path) -> list[str]:
    """Everything check-drift (j) enforces about the declaration, as messages."""
    try:
        locks, _ = declared(root)
    except ContractError as e:
        return [str(e)]  # without the list there is nothing else to check
    try:
        problems = evaluate(root)[1]
    except ContractError as e:  # e.g. a malformed dependabot.yml: report it, keep checking
        problems = [str(e)]
    for e in locks:
        man = e.get("manifest")
        if not man or location_problem(e):
            continue
        try:
            pkg = _load(root, man, "json")
        except ContractError as err:
            problems.append(str(err))
            continue
        if pkg is None:
            problems.append(f"{man}: declared in {CONTRACT} but missing")
            continue
        if not isinstance(pkg, dict):
            problems.append(f"{man}: top level is not an object")
            continue
        loose = [f"{k}@{v}" for sect in ("dependencies", "devDependencies", "optionalDependencies")
                 for k, v in (pkg.get(sect) or {}).items() if not EXACT.fullmatch(str(v))]
        if loose:
            problems.append(f"{man}: a sanctioned runtime pins exactly; loose: {', '.join(loose[:5])}")
    want = {e["lockfile"] for e in locks if not location_problem(e)}
    gi_path = Path(root) / GITIGNORE
    gi = gi_path.read_text(encoding="utf-8", errors="replace").splitlines() if gi_path.is_file() else []
    try:
        start = next(i for i, line in enumerate(gi) if line.startswith(BLOCK_BEGIN))
        end = gi.index(BLOCK_END, start)
    except (StopIteration, ValueError):
        if want:
            problems.append(f"{GITIGNORE}: no `{BLOCK_BEGIN}` … `{BLOCK_END}` block for the lockfiles in {CONTRACT}")
        return problems
    block = {line[1:] for line in gi[start:end] if line.startswith("!")}
    if block != want:
        problems.append(f"{GITIGNORE}: the sanctioned_lockfiles block {sorted(block)} != {CONTRACT} {sorted(want)}")
    last_pattern = max((i for i, line in enumerate(gi) if line.strip() in LOCKFILES), default=-1)
    if start < last_pattern:
        problems.append(f"{GITIGNORE}: the sanctioned_lockfiles block must come after every lockfile pattern "
                        "(a later pattern re-ignores it)")
    return problems


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("check", "paths", "covered"):
        print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
        return 2
    root = Path(argv[1] if len(argv) > 1 else ".")
    try:
        if argv[0] == "check":
            problems = drift_problems(root)
            for p in problems:
                print(p)
            return 1 if problems else 0
        entries = covered(root)
        for lock, e in sorted(entries.items()):
            if argv[0] == "covered":
                print(lock)
            else:
                for kind in KINDS:
                    if e.get(kind):
                        print(f"{kind}\t{e[kind]}")
        return 0
    except ContractError as e:
        print(f"sanctioned_lockfiles: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

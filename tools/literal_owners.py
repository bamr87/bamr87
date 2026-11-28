#!/usr/bin/env python3
"""
literal_owners.py — the literal owners the framework's code still carries, counted (ADR 0011 decision 2).

The stack is one framework and many instances. An instance's identity is its
settings, read once by tools/fleetcore/identity.py; a tool, kit, workflow or
standard that writes an owner out in full works for one instance only. This
file counts those and reports what is new. It reads one contract,
_data/literal_owners.yml, and the identity of the checkout it measures, so it
names no owner itself:

  what     an owner's name followed by a slash (`<owner>/`), for every owner
           the identity lists, where the text before it cannot be part of a
           name. Each occurrence is one of
             framework  the framework's own address, which stays fixed: it
                        matches an `allow:` rule (a reusable workflow or action
                        called at a ref, a link to the framework's tracker).
                        Counted, never held.
             hub        the hub's slug anywhere else
             owner      any other `<owner>/…`: a fleet repo, a URL, a path
  where    the contract's `roots:` (held) and `measured:` (counted only):
           every text file git tracks there or would add. A file git ignores
           is never counted, and node_modules, dist and vendor directories
           are skipped as tools/architecture.py skips them: another project's
           text.
  tests    a test file or anything under a tests or fixtures directory is
           counted apart and never held: a fixture is allowed to name an owner

What the tree carries is recorded per file in the contract's `baseline:`, and
the record only shrinks, the way ADR 0016's ledger does: `baseline --write`
lowers and drops entries, adds one only with --accept-new, and never raises a
number.

REPORT ONLY. While the contract says `enforce: false`, nothing here fails a
build: `check` prints what a gate would refuse and exits 0. Turning it on is a
later change the maintainer reviews.

CLI (exit 0 ok; 1 `enforce` is on and the tree differs from its baseline, or
`baseline` refused to record something; 2 the contract or the identity cannot
be read):
  literal_owners.py report   [--root R] [--files] [--json]   the counts by directory, and what differs from the baseline
  literal_owners.py check    [--root R]                      each file past its baseline, with its lines
  literal_owners.py baseline [--root R] [--write] [--accept-new]
                                                             what the baseline should hold now
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from fleetcore import identity

SCHEMA = "literal-owners/v1"
REPORT_SCHEMA = "literal-owners-report/v1"
CONTRACT = "_data/literal_owners.yml"
PLACEHOLDER = "{framework}"
HUB, OWNER = "hub", "owner"
SKIP_PARTS = frozenset({"node_modules", "dist", "dist-pages", "__pycache__", ".venv", "vendor"})
TEST_PARTS = frozenset({"tests", "test", "fixtures", "__tests__", "__fixtures__"})
# A name on GitHub is letters, digits, hyphens and (for a managed user) an underscore.
NAME_CHAR = "A-Za-z0-9_-"


class ContractError(ValueError):
    """The contract or the identity cannot be used (one-line message)."""


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #
def load_contract(root: Path) -> dict:
    """Parse and validate _data/literal_owners.yml. ContractError when it cannot be used."""
    path = Path(root) / CONTRACT
    if not path.is_file():
        raise ContractError(f"{CONTRACT}: not found")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise ContractError(f"{CONTRACT}: not readable YAML ({e})") from e
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ContractError(f"{CONTRACT}: expected `schema: {SCHEMA}`")
    if not isinstance(doc.get("enforce"), bool):
        raise ContractError(f"{CONTRACT}: `enforce:` must be true or false")
    for key, needed in (("roots", True), ("measured", False)):
        value = doc.get(key) or []
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value) or (needed and not value):
            raise ContractError(f"{CONTRACT}: `{key}:` must be a list of directories" + (", with at least one" if needed else ""))
    seen: set[str] = set()
    for rule in doc.get("allow") or []:
        if not isinstance(rule, dict) or not all(isinstance(rule.get(k), str) and rule[k].strip() for k in ("id", "pattern", "why")):
            raise ContractError(f"{CONTRACT}: each allow entry needs `id`, `pattern` and a `why`")
        if rule["id"] in (HUB, OWNER) or rule["id"] in seen:
            raise ContractError(f"{CONTRACT}: allow id {rule['id']!r} is reserved or listed twice")
        seen.add(rule["id"])
        if not rule["pattern"].startswith(PLACEHOLDER):
            raise ContractError(f"{CONTRACT}: allow.{rule['id']}.pattern must start with {PLACEHOLDER}: only the framework's address is allowed")
        try:
            re.compile(rule["pattern"].replace(PLACEHOLDER, "x/y"))
        except re.error as e:
            raise ContractError(f"{CONTRACT}: allow.{rule['id']}.pattern is not a regular expression ({e})") from e
    baseline = doc.get("baseline") or {}
    files = baseline.get("files") if isinstance(baseline, dict) else None
    files = {} if files is None else files
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0 for k, v in files.items()):
        raise ContractError(f"{CONTRACT}: baseline.files must map a path to a positive integer")
    return doc


def baseline_of(contract: dict) -> dict[str, int]:
    return dict((contract.get("baseline") or {}).get("files") or {})


# --------------------------------------------------------------------------- #
# whose literals, and what each one is
# --------------------------------------------------------------------------- #
def who_is(root: Path) -> tuple[identity.Identity, str]:
    """(the identity of the checkout, the framework's address). The settings alone:
    the count is a property of the tree, the same on every host."""
    fleet = identity.load_settings(root)
    who = identity.from_settings(fleet)
    if not who.owners:
        raise ContractError(f"{root / identity.SETTINGS} names no `hub.repo` and no `hub.owners`: there is no owner to look for")
    framework = fleet.get("framework") if isinstance(fleet.get("framework"), dict) else {}
    return who, str(framework.get("repo") or who.repo).strip()


class Matcher:
    """Finds every literal owner in a text and says which kind each one is."""

    def __init__(self, who: identity.Identity, framework: str, contract: dict) -> None:
        names = sorted({*who.owners, who.owner.lower()} - {""}, key=len, reverse=True)
        self.owner = re.compile(rf"(?<![{NAME_CHAR}])(?:{'|'.join(re.escape(n) for n in names)})/", re.I)
        # The slug, and nothing longer: `<hub>-archive` and `<hub>.github.io` are other names.
        self.hub = re.compile(re.escape(who.repo) + rf"(?:\.git)?(?![{NAME_CHAR}])(?!\.[{NAME_CHAR}])", re.I) if who.repo else None
        self.allow = [(rule["id"], re.compile(rule["pattern"].replace(PLACEHOLDER, re.escape(framework)), re.I))
                      for rule in contract.get("allow") or []] if framework else []

    def scan(self, text: str) -> list[tuple[str, int]]:
        """[(kind, offset)] in order. One occurrence is one thing: a reference the
        framework's address covers is not counted again for the owner inside it."""
        found: list[tuple[str, int]] = []
        pos = 0
        while True:
            hit = self.owner.search(text, pos)
            if hit is None:
                return found
            kind, end = OWNER, hit.end()
            for rule, pattern in self.allow:
                allowed = pattern.match(text, hit.start())
                if allowed:
                    kind, end = rule, allowed.end()
                    break
            else:
                slug = self.hub.match(text, hit.start()) if self.hub else None
                if slug:
                    kind, end = HUB, slug.end()
            found.append((kind, hit.start()))
            pos = max(end, hit.end())


# --------------------------------------------------------------------------- #
# what is measured
# --------------------------------------------------------------------------- #
def is_test(rel: Path) -> bool:
    name = rel.name
    return (name.startswith("test_") or name == "conftest.py" or ".test." in name or ".spec." in name
            or bool(TEST_PARTS.intersection(rel.parts[:-1])))


def _skipped(rel: Path) -> bool:
    return any(part in SKIP_PARTS for part in rel.parts)


def listed_files(root: Path, dirs: list[str]) -> list[Path]:
    """The files under `dirs`, relative to root: what git tracks plus what is new and
    not ignored, so a build's output is never counted. A plain directory is walked."""
    root = Path(root)
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *dirs],
                             capture_output=True, check=True).stdout.decode("utf-8", "replace")
        rels = [Path(p) for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        rels = []
        for d in dirs:
            for base, names, files in os.walk(root / d):
                names[:] = sorted(n for n in names if n not in SKIP_PARTS)
                rels.extend((Path(base) / f).relative_to(root) for f in files)
    keep = {rel for rel in rels if not _skipped(rel) and (root / rel).is_file() and not (root / rel).is_symlink()}
    return sorted(keep)


def _under(rel: Path, dirs: list[str]) -> str | None:
    """The directory of `dirs` a path is under: the longest that contains it."""
    text = rel.as_posix()
    hits = [d for d in dirs if text == d.strip("/") or text.startswith(d.strip("/") + "/")]
    return max(hits, key=len) if hits else None


def measure(root: Path, contract: dict, who: identity.Identity | None = None, framework: str | None = None) -> dict:
    """Every file under the contract's directories that names an owner:
    {path: {dir, held, test, counts: {kind: n}, lines: [line of each held occurrence]}}."""
    root = Path(root)
    if who is None or framework is None:
        who, framework = who_is(root)
    matcher = Matcher(who, framework, contract)
    roots = [str(d) for d in contract["roots"]]
    dirs = roots + [str(d) for d in contract.get("measured") or []]
    files: dict[str, dict] = {}
    unread = 0
    for rel in listed_files(root, dirs):
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            unread += 1  # not text: an image, an archive
            continue
        found = matcher.scan(text)
        if not found:
            continue
        counts: dict[str, int] = {}
        for kind, _ in found:
            counts[kind] = counts.get(kind, 0) + 1
        test = is_test(rel)
        where = _under(rel, dirs)
        files[rel.as_posix()] = {
            "dir": where, "held": where in roots and not test, "test": test, "counts": counts,
            "lines": [text.count("\n", 0, at) + 1 for kind, at in found if kind in (HUB, OWNER)]}
    return {"files": files, "dirs": dirs, "roots": roots, "unread": unread,
            "owners": list(who.owners), "hub": who.repo, "framework": framework,
            "rules": [rule["id"] for rule in contract.get("allow") or []]}


def held_count(row: dict) -> int:
    """The occurrences of a file that the framework's address does not cover."""
    return row["counts"].get(HUB, 0) + row["counts"].get(OWNER, 0)


def held(m: dict) -> dict[str, int]:
    """{path: occurrences} for what a baseline holds: non-test files under `roots:`."""
    return {path: held_count(row) for path, row in m["files"].items() if row["held"] and held_count(row)}


def by_directory(m: dict) -> list[dict]:
    rows = []
    for d in m["dirs"]:
        row = {"dir": d, "held": d in m["roots"], "files": 0, HUB: 0, OWNER: 0, "framework": {r: 0 for r in m["rules"]},
               "tests": {"files": 0, "occurrences": 0}}
        for item in m["files"].values():
            if item["dir"] != d:
                continue
            if item["test"]:
                row["tests"]["files"] += 1
                row["tests"]["occurrences"] += sum(item["counts"].values())
                continue
            row["files"] += 1
            for kind, n in item["counts"].items():
                if kind in (HUB, OWNER):
                    row[kind] += n
                else:
                    row["framework"][kind] += n
        rows.append(row)
    return rows


def compare(now: dict[str, int], baseline: dict[str, int]) -> dict:
    """What differs from the baseline. `new` and `over` are what a gate refuses;
    `under` and `gone` are reductions the baseline has not been lowered to yet."""
    return {
        "new": {p: n for p, n in sorted(now.items()) if p not in baseline},
        "over": {p: {"now": n, "baseline": baseline[p]} for p, n in sorted(now.items()) if p in baseline and n > baseline[p]},
        "under": {p: {"now": n, "baseline": baseline[p]} for p, n in sorted(now.items()) if p in baseline and n < baseline[p]},
        "gone": {p: n for p, n in sorted(baseline.items()) if p not in now},
    }


def planned_baseline(now: dict[str, int], baseline: dict[str, int], accept_new: bool) -> tuple[dict[str, int], list[str]]:
    """The baseline this tree should carry, and what was refused. Lowers and drops; adds only with accept_new; never raises."""
    out: dict[str, int] = {}
    refused: list[str] = []
    for path, n in sorted(now.items()):
        if path in baseline:
            if n > baseline[path]:
                refused.append(f"{path} has {n}, over its number {baseline[path]} (kept; a raise is a hand edit)")
            out[path] = min(baseline[path], n)
        elif accept_new:
            out[path] = n
        else:
            refused.append(f"{path} has {n} and is not in the baseline (pass --accept-new to record it)")
    return out, refused


def write_baseline(root: Path, files: dict[str, int]) -> None:
    """Replace the `baseline:` block, which must be the file's last top-level key, leaving every line above it as written."""
    path = Path(root) / CONTRACT
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("baseline:")]
    if len(starts) != 1:
        raise ContractError(f"{CONTRACT}: expected exactly one top-level `baseline:` key")
    tail = lines[starts[0] + 1:]
    if any(line and not line[0].isspace() and not line.startswith("#") for line in tail):
        raise ContractError(f"{CONTRACT}: `baseline:` must be the last top-level key so it can be rewritten in place")
    body = yaml.safe_dump({"baseline": {"files": files}}, sort_keys=True, default_flow_style=False, allow_unicode=True, width=200)
    path.write_text("\n".join(lines[:starts[0]]) + "\n" + body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def report_doc(root: Path, contract: dict) -> dict:
    m = measure(root, contract)
    now, baseline = held(m), baseline_of(contract)
    diff = compare(now, baseline)
    return {
        "schema": REPORT_SCHEMA, "enforce": contract["enforce"], "hub": m["hub"], "owners": m["owners"],
        "framework": m["framework"], "directories": by_directory(m),
        "held": {"files": len(now), "occurrences": sum(now.values())},
        "baseline": {"files": len(baseline), "occurrences": sum(baseline.values())},
        "diff": diff,
        "refused": sum(diff["new"].values()) + sum(v["now"] - v["baseline"] for v in diff["over"].values()),
        "files": {p: {"dir": r["dir"], "test": r["test"], "counts": r["counts"], "lines": r["lines"]} for p, r in sorted(m["files"].items())},
        "unread": m["unread"],
    }


def _table(rows: list[list[str]], head: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  ".join(str(c).ljust(w) if i == 0 else str(c).rjust(w) for i, (c, w) in enumerate(zip(r, widths))).rstrip()  # noqa: E731
    return "\n".join([line(head), line(["-" * w for w in widths])] + [line(r) for r in rows])


def _mode(doc: dict) -> str:
    return "enforced" if doc["enforce"] else f"report only (`enforce: false` in {CONTRACT}): nothing fails"


def _diff_lines(doc: dict, with_lines: bool) -> list[str]:
    diff, files, out = doc["diff"], doc["files"], []

    def at(path: str) -> str:
        return ("  lines " + ", ".join(str(n) for n in files[path]["lines"][:12])) if with_lines and path in files else ""

    for path, n in diff["new"].items():
        out.append(f"  new    {path}: {n}, not in the baseline{at(path)}")
    for path, v in diff["over"].items():
        out.append(f"  over   {path}: {v['now']}, the baseline holds it to {v['baseline']}{at(path)}")
    for path, v in diff["under"].items():
        out.append(f"  lower  {path}: {v['now']}, the baseline still allows {v['baseline']}")
    for path, n in diff["gone"].items():
        out.append(f"  gone   {path}: none now, the baseline still allows {n}")
    return out


def _print_report(doc: dict, show_files: bool) -> None:
    print(f"literal owners: {' '.join(doc['owners'])} · hub {doc['hub'] or '(none)'} · framework address {doc['framework'] or '(none)'}")
    print(_mode(doc))
    rules = list(doc["directories"][0]["framework"]) if doc["directories"] else []
    head = ["DIRECTORY", "FILES", "HELD", HUB, OWNER, *rules, "TEST FILES", "IN TESTS"]
    rows = []
    for d in doc["directories"]:
        name = d["dir"] if d["held"] else f"{d['dir']} (counted only)"
        rows.append([name, str(d["files"]), str(d[HUB] + d[OWNER]), str(d[HUB]), str(d[OWNER]),
                     *[str(d["framework"][r]) for r in rules], str(d["tests"]["files"]), str(d["tests"]["occurrences"])])
    print(_table(rows, head))
    h, b, diff = doc["held"], doc["baseline"], doc["diff"]
    print(f"\nheld: {h['occurrences']} in {h['files']} file(s) · baseline: {b['occurrences']} in {b['files']} file(s)")
    print(f"against the baseline: {len(diff['new'])} new file(s), {len(diff['over'])} over, "
          f"{len(diff['under'])} lower, {len(diff['gone'])} gone · {doc['refused']} occurrence(s) a gate would refuse")
    if show_files:
        for line in _diff_lines(doc, with_lines=False):
            print(line)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="literal_owners.py", description="The literal owners the framework's code carries (ADR 0011 decision 2). Report only.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("report", "check", "baseline"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="the framework checkout to measure (default: this one)")
        if name == "report":
            p.add_argument("--files", action="store_true", help="also list each file that differs from the baseline")
            p.add_argument("--json", action="store_true", help=f"the document ({REPORT_SCHEMA})")
        if name == "baseline":
            p.add_argument("--write", action="store_true", help="rewrite the baseline block in place")
            p.add_argument("--accept-new", action="store_true", help="also record files that are not in the baseline yet")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        contract = load_contract(root)
        if args.cmd == "baseline":
            files, refused = planned_baseline(held(measure(root, contract)), baseline_of(contract), args.accept_new)
            for line in refused:
                print(f"  ! {line}")
            if args.write:
                write_baseline(root, files)
                print(f"wrote {CONTRACT} baseline: {sum(files.values())} occurrence(s) in {len(files)} file(s)")
            else:
                print(yaml.safe_dump({"baseline": {"files": files}}, sort_keys=True, default_flow_style=False, width=200), end="")
            return 1 if refused else 0
        doc = report_doc(root, contract)
    except ContractError as e:
        print(f"literal owners: {e}", file=sys.stderr)
        return 2
    if args.cmd == "report":
        if args.json:
            print(json.dumps(doc, indent=2))
        else:
            _print_report(doc, args.files)
        return 0
    lines = _diff_lines(doc, with_lines=True)
    for line in lines:
        print(line)
    if not lines:
        print(f"literal owners: at the baseline · {_mode(doc)}")
        return 0
    stale = len(doc["diff"]["under"]) + len(doc["diff"]["gone"])
    print(f"literal owners: {doc['refused']} occurrence(s) past the baseline, {stale} baseline entr{'y' if stale == 1 else 'ies'} "
          f"to lower (`baseline --write`) · {_mode(doc)}")
    return 1 if doc["enforce"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

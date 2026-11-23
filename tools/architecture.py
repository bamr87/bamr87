#!/usr/bin/env python3
"""
architecture.py — the hub's own structure, measured and held (ADR 0016).

The hub's code is install-free on purpose: every script runs from a checkout on
a bare interpreter, so nothing enforces a package boundary for it. This file is
that boundary, written down and checked. It reads one contract,
_data/architecture.yml, and measures the hub's own source (never projects/):

  layers   which code unit imports which. Units are ordered low to high
           (generators, core, engines, surfaces); a unit may import from its
           own layer or a lower one, never a higher one.
  paths    which non-test Python modules change sys.path. A test file runs
           standalone by design and is not counted.
  sizes    source files past limits.module_lines. Tests are not counted.
  data     committed _data files past limits.data_file_kb.

What the tree already carries past a limit is recorded in the contract: a layer
exception names the file, the import and why it stays; the ledger holds the
number each oversized or path-changing file is held to. The ledger only
shrinks. A file is recorded with a little headroom, so a small fix fits; it
may not pass its number, a file that is not listed may not pass the limit,
and a file that has dropped well under its number must be recorded again at
the lower one in the same change, so a reduction cannot be spent later.

What it does not see: an import by file path (importlib, runpy) and a
subprocess call. Those are counted nowhere, so a new one needs a reviewer.

CLI (exit 0 ok, 1 the tree breaks the contract, 2 the contract is unreadable):
  architecture.py check  [--root R]                 the gate; prints each problem and its fix
  architecture.py report [--root R] [--json]        the measurements behind the check
  architecture.py ledger [--root R] [--write] [--accept-new]
                                                    what the ledger should hold now; --write
                                                    lowers and drops entries, and adds a new
                                                    one only with --accept-new. It never
                                                    raises a number: that is a hand edit a
                                                    reviewer sees.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from pathlib import Path

import yaml

SCHEMA = "architecture/v1"
CONTRACT = "_data/architecture.yml"
CODE_ROOTS = ("tools", ".github/scripts")
SKIP_PARTS = frozenset({"node_modules", "dist", "__pycache__", ".venv", "vendor"})
PATH_MUTATORS = frozenset({"insert", "append", "extend"})


class ContractError(ValueError):
    """The contract is missing or malformed (one-line message)."""


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #
def load_contract(root: Path) -> dict:
    """Parse and validate _data/architecture.yml. ContractError when it cannot be used."""
    path = Path(root) / CONTRACT
    if not path.is_file():
        raise ContractError(f"{CONTRACT}: not found")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise ContractError(f"{CONTRACT}: not readable YAML ({e})") from e
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ContractError(f"{CONTRACT}: expected `schema: {SCHEMA}`")
    limits = doc.get("limits")
    if not isinstance(limits, dict):
        raise ContractError(f"{CONTRACT}: `limits:` must be a map")
    for key in ("module_lines", "data_file_kb", "ledger_headroom_lines"):
        if not isinstance(limits.get(key), int) or isinstance(limits.get(key), bool) or limits[key] <= 0:
            raise ContractError(f"{CONTRACT}: limits.{key} must be a positive integer")
    layers = doc.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ContractError(f"{CONTRACT}: `layers:` must be a non-empty list, lowest first")
    seen: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("id"), str) or not isinstance(layer.get("paths"), list):
            raise ContractError(f"{CONTRACT}: each layer needs an `id` and a `paths` list")
        for p in layer["paths"]:
            if not isinstance(p, str) or p in seen:
                raise ContractError(f"{CONTRACT}: layer path {p!r} is not a string or is listed twice")
            seen.add(p)
    if not isinstance(doc.get("sources"), list) or not all(isinstance(s, str) for s in doc["sources"]):
        raise ContractError(f"{CONTRACT}: `sources:` must be a list of glob patterns")
    for item in doc.get("layer_exceptions") or []:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip() for k in ("file", "imports", "why")):
            raise ContractError(f"{CONTRACT}: each layer_exceptions entry needs `file`, `imports` and a `why`")
    ledger = doc.get("ledger") or {}
    if not isinstance(ledger, dict):
        raise ContractError(f"{CONTRACT}: `ledger:` must be a map")
    for section in ("sizes", "sys_path"):
        table = ledger.get(section) or {}
        if not isinstance(table, dict) or not all(isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0 for k, v in table.items()):
            raise ContractError(f"{CONTRACT}: ledger.{section} must map a path to a positive integer")
    return doc


# --------------------------------------------------------------------------- #
# what is measured
# --------------------------------------------------------------------------- #
def is_test(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or name == "conftest.py" or ".test." in name or ".spec." in name


def _skipped(rel: Path) -> bool:
    return any(part in SKIP_PARTS for part in rel.parts)


def python_modules(root: Path) -> list[Path]:
    """Every hub Python file under tools/ and .github/scripts/, as paths relative to root."""
    out: list[Path] = []
    for base in CODE_ROOTS:
        top = Path(root) / base
        if not top.is_dir():
            continue
        for p in top.rglob("*.py"):
            rel = p.relative_to(root)
            if not _skipped(rel) and p.is_file():
                out.append(rel)
    return sorted(out)


def source_files(root: Path, contract: dict) -> list[Path]:
    """The files limits.module_lines applies to: the contract's `sources` globs, tests left out."""
    out: set[Path] = set()
    for pattern in contract["sources"]:
        for p in Path(root).glob(pattern):
            rel = p.relative_to(root)
            if p.is_file() and not _skipped(rel) and not is_test(rel):
                out.add(rel)
    return sorted(out)


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def count_path_changes(tree: ast.AST) -> int:
    """How many statements change sys.path: sys.path.insert/append/extend(...) and any assignment to it."""

    def is_sys_path(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "path" and isinstance(node.value, ast.Name) and node.value.id == "sys"

    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in PATH_MUTATORS and is_sys_path(node.func.value):
            n += 1
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if is_sys_path(t) or (isinstance(t, ast.Subscript) and is_sys_path(t.value)):
                    n += 1
    return n


def _parse(root: Path, rel: Path) -> ast.AST | None:
    try:
        return ast.parse((Path(root) / rel).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None


# --------------------------------------------------------------------------- #
# layers
# --------------------------------------------------------------------------- #
def _layer_index(contract: dict) -> list[tuple[Path, int, str]]:
    """(unit path, layer rank, layer id), longest path first so the nearest unit wins."""
    units = [(Path(p), rank, layer["id"]) for rank, layer in enumerate(contract["layers"]) for p in layer["paths"]]
    return sorted(units, key=lambda u: -len(u[0].parts))


def unit_of(rel: Path, units: list[tuple[Path, int, str]]) -> tuple[Path, int, str] | None:
    for unit in units:
        if unit[0] in rel.parents:
            return unit
    return None


def _provided_names(root: Path, units: list[tuple[Path, int, str]]) -> dict[str, list[Path]]:
    """Top-level import name -> the unit paths that provide it.

    A unit that is a package (has __init__.py) is imported by its directory name.
    A unit that is a plain directory of scripts is imported by each module's stem
    and each sub-package's name, because the directory itself goes on sys.path.
    """
    names: dict[str, list[Path]] = {}
    for unit_path, _rank, _id in units:
        d = Path(root) / unit_path
        if not d.is_dir():
            continue
        if (d / "__init__.py").is_file():
            names.setdefault(unit_path.name, []).append(unit_path)
            continue
        for child in d.iterdir():
            if child.is_file() and child.suffix == ".py" and not is_test(child):
                names.setdefault(child.stem, []).append(unit_path)
            elif child.is_dir() and (child / "__init__.py").is_file():
                names.setdefault(child.name, []).append(unit_path)
    return names


def _imported_names(tree: ast.AST) -> list[str]:
    """Dotted names a module imports absolutely. `from a import b` yields `a` and `a.b`."""
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.append(node.module)
            out.extend(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
    return out


def layer_edges(root: Path, contract: dict) -> list[dict]:
    """Every import that crosses from one unit to another, with both layers' ranks."""
    units = _layer_index(contract)
    provided = _provided_names(root, units)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rel in python_modules(root):
        if is_test(rel):
            continue
        src = unit_of(rel, units)
        if src is None:
            continue
        tree = _parse(root, rel)
        if tree is None:
            continue
        for dotted in _imported_names(tree):
            parts = dotted.split(".")
            if parts[0] == "tools" and len(parts) > 1:
                parts = parts[1:]
            top = parts[0]
            owners = provided.get(top, [])
            if src[0] in owners or top in stdlib or len(owners) != 1:
                continue  # its own unit, the standard library, or a name two units share
            dst = next(u for u in units if u[0] == owners[0])
            key = (rel.as_posix(), top)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"file": rel.as_posix(), "imports": top, "from_unit": src[0].as_posix(), "from_layer": src[2],
                          "to_unit": dst[0].as_posix(), "to_layer": dst[2], "upward": src[1] < dst[1]})
    return sorted(edges, key=lambda e: (e["file"], e["imports"]))


# --------------------------------------------------------------------------- #
# the measurements, and the ledger they imply
# --------------------------------------------------------------------------- #
def measure(root: Path, contract: dict) -> dict:
    root = Path(root)
    limit = contract["limits"]["module_lines"]
    sizes = {rel.as_posix(): line_count(root / rel) for rel in source_files(root, contract)}
    path_changes: dict[str, int] = {}
    for rel in python_modules(root):
        if is_test(rel):
            continue
        tree = _parse(root, rel)
        n = count_path_changes(tree) if tree is not None else 0
        if n:
            path_changes[rel.as_posix()] = n
    data: dict[str, int] = {}
    data_dir = root / "_data"
    if data_dir.is_dir():
        data = {p.relative_to(root).as_posix(): p.stat().st_size for p in data_dir.rglob("*") if p.is_file()}
    return {"sizes": sizes, "oversized": {k: v for k, v in sizes.items() if v > limit}, "sys_path": path_changes,
            "edges": layer_edges(root, contract), "data": data}


def recorded_size(lines: int, headroom: int) -> int:
    """The number a file is held to when it is recorded: its length plus between half and all of the
    headroom, on a round number. A small fix fits under it, so a pull request that adds a few lines to
    a listed file does not have to edit the ledger, and the file still cannot grow by more than that."""
    step = max(1, headroom // 2)
    return int(math.ceil((lines + step) / step) * step)


def is_stale(lines: int, held: int, headroom: int) -> bool:
    """A listed file has dropped far enough under its number that the number must come down with it."""
    return lines <= held - 2 * headroom


def check(root: Path, contract: dict | None = None) -> list[str]:
    """Every way the tree breaks the contract, each with its fix. Empty means the gate passes."""
    root = Path(root)
    contract = contract or load_contract(root)
    limits = contract["limits"]
    m = measure(root, contract)
    ledger = contract.get("ledger") or {}
    led_sizes: dict[str, int] = dict(ledger.get("sizes") or {})
    led_paths: dict[str, int] = dict(ledger.get("sys_path") or {})
    problems: list[str] = []

    # layers
    exceptions = {(e["file"], e["imports"]) for e in contract.get("layer_exceptions") or []}
    upward = {(e["file"], e["imports"]): e for e in m["edges"] if e["upward"]}
    for key, e in sorted(upward.items()):
        if key not in exceptions:
            problems.append(f"layers: {e['file']} imports `{e['imports']}` from {e['to_unit']} ({e['to_layer']}), which sits above "
                            f"{e['from_unit']} ({e['from_layer']}). Move the shared code down a layer, or add a layer_exceptions "
                            f"entry with a `why` to {CONTRACT}.")
    for key in sorted(exceptions - set(upward)):
        problems.append(f"layers: the exception for {key[0]} importing `{key[1]}` no longer matches the tree. Remove it from {CONTRACT}.")

    # sizes
    cap, headroom = limits["module_lines"], limits["ledger_headroom_lines"]
    for path, lines in sorted(m["oversized"].items()):
        if path not in led_sizes:
            problems.append(f"sizes: {path} is {lines} lines, past the {cap}-line limit. Split it along a seam; if it must land "
                            f"whole, record it with `architecture.py ledger --write --accept-new`.")
        elif lines > led_sizes[path]:
            problems.append(f"sizes: {path} grew to {lines} lines; the ledger holds it to {led_sizes[path]}. Move code out of it, "
                            f"or raise the number in {CONTRACT} by hand and say why in the pull request.")
    for path, held in sorted(led_sizes.items()):
        lines = m["sizes"].get(path)
        if lines is None:
            problems.append(f"sizes: the ledger lists {path}, which is not a source file any more. Run `architecture.py ledger --write`.")
        elif lines <= cap:
            problems.append(f"sizes: {path} is down to {lines} lines, under the limit. Run `architecture.py ledger --write` to drop its entry.")
        elif is_stale(lines, held, headroom):
            problems.append(f"sizes: {path} is down to {lines} lines; the ledger still allows {held}. Run `architecture.py ledger --write` "
                            f"to hold the gain.")

    # sys.path
    for path, n in sorted(m["sys_path"].items()):
        if path not in led_paths:
            problems.append(f"paths: {path} changes sys.path ({n}x) and is not in the ledger. Import through a module already on the "
                            f"path; if this entry point needs it, record it with `architecture.py ledger --write --accept-new`.")
        elif n > led_paths[path]:
            problems.append(f"paths: {path} changes sys.path {n}x; the ledger holds it to {led_paths[path]}.")
    for path, held in sorted(led_paths.items()):
        n = m["sys_path"].get(path, 0)
        if n < held:
            problems.append(f"paths: {path} changes sys.path {n}x now; the ledger still allows {held}. Run `architecture.py ledger --write`.")

    # data
    max_bytes = limits["data_file_kb"] * 1024
    for path, size in sorted(m["data"].items()):
        if size > max_bytes:
            problems.append(f"data: {path} is {size // 1024} KB, past the {limits['data_file_kb']} KB limit for a committed _data file. "
                            f"Trim what the snapshot keeps, or split it by period.")
    return problems


def planned_ledger(root: Path, contract: dict, accept_new: bool) -> tuple[dict, list[str]]:
    """The ledger this tree should carry, and what was refused. Lowers and drops; adds only with accept_new; never raises."""
    m = measure(Path(root), contract)
    ledger = contract.get("ledger") or {}
    old_sizes: dict[str, int] = dict(ledger.get("sizes") or {})
    old_paths: dict[str, int] = dict(ledger.get("sys_path") or {})
    refused: list[str] = []
    sizes: dict[str, int] = {}
    headroom = contract["limits"]["ledger_headroom_lines"]
    for path, lines in sorted(m["oversized"].items()):
        want = recorded_size(lines, headroom)
        if path in old_sizes:
            if lines > old_sizes[path]:
                refused.append(f"sizes: {path} is {lines} lines, over its number {old_sizes[path]} (kept; a raise is a hand edit)")
            sizes[path] = min(old_sizes[path], want)
        elif accept_new:
            sizes[path] = want
        else:
            refused.append(f"sizes: {path} is {lines} lines and not in the ledger (pass --accept-new to record it)")
    paths: dict[str, int] = {}
    for path, n in sorted(m["sys_path"].items()):
        if path in old_paths:
            if n > old_paths[path]:
                refused.append(f"paths: {path} changes sys.path {n}x, over its number {old_paths[path]} (kept; a raise is a hand edit)")
            paths[path] = min(old_paths[path], n)
        elif accept_new:
            paths[path] = n
        else:
            refused.append(f"paths: {path} changes sys.path {n}x and is not in the ledger (pass --accept-new to record it)")
    return {"sizes": sizes, "sys_path": paths}, refused


def write_ledger(root: Path, new_ledger: dict) -> None:
    """Replace the `ledger:` block, which must be the file's last top-level key, leaving every line above it as written."""
    path = Path(root) / CONTRACT
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("ledger:")]
    if len(starts) != 1:
        raise ContractError(f"{CONTRACT}: expected exactly one top-level `ledger:` key")
    tail = lines[starts[0] + 1:]
    if any(line and not line[0].isspace() and not line.startswith("#") for line in tail):
        raise ContractError(f"{CONTRACT}: `ledger:` must be the last top-level key so it can be rewritten in place")
    body = yaml.safe_dump({"ledger": new_ledger}, sort_keys=True, default_flow_style=False, allow_unicode=True, width=200)
    path.write_text("\n".join(lines[:starts[0]]) + "\n" + body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _report(root: Path, contract: dict, as_json: bool) -> int:
    m = measure(root, contract)
    limits = contract["limits"]
    pairs: dict[tuple[str, str], int] = {}
    for e in m["edges"]:
        pairs[(e["from_unit"], e["to_unit"])] = pairs.get((e["from_unit"], e["to_unit"]), 0) + 1
    biggest = sorted(m["data"].items(), key=lambda kv: -kv[1])[:5]
    doc = {
        "schema": "architecture-report/v1",
        "limits": limits,
        "layers": [{"id": layer["id"], "paths": layer["paths"]} for layer in contract["layers"]],
        "unit_imports": [{"from": a, "to": b, "imports": n} for (a, b), n in sorted(pairs.items(), key=lambda kv: -kv[1])],
        "upward_imports": [e for e in m["edges"] if e["upward"]],
        "oversized": dict(sorted(m["oversized"].items(), key=lambda kv: -kv[1])),
        "sys_path": {"modules": len(m["sys_path"]), "changes": sum(m["sys_path"].values())},
        "largest_data_files_kb": {k: v // 1024 for k, v in biggest},
        "problems": check(root, contract),
    }
    if as_json:
        print(json.dumps(doc, indent=2))
        return 0
    print(f"layers (low to high): {' < '.join(layer['id'] for layer in contract['layers'])}")
    for row in doc["unit_imports"]:
        print(f"  {row['from']:28s} -> {row['to']:28s} {row['imports']:3d}")
    print(f"upward imports: {len(doc['upward_imports'])}")
    for e in doc["upward_imports"]:
        print(f"  {e['file']} imports `{e['imports']}` ({e['from_layer']} -> {e['to_layer']})")
    print(f"source files past {limits['module_lines']} lines: {len(doc['oversized'])}")
    for path, lines in doc["oversized"].items():
        print(f"  {lines:5d}  {path}")
    print(f"non-test modules that change sys.path: {doc['sys_path']['modules']} ({doc['sys_path']['changes']} statements)")
    print(f"largest _data files (limit {limits['data_file_kb']} KB):")
    for path, kb in doc["largest_data_files_kb"].items():
        print(f"  {kb:5d} KB  {path}")
    print(f"problems: {len(doc['problems'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="architecture.py", description="The hub's structure, measured and held (ADR 0016).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "report", "ledger"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="hub checkout (default: this one)")
        if name == "report":
            p.add_argument("--json", action="store_true")
        if name == "ledger":
            p.add_argument("--write", action="store_true", help="rewrite the ledger block in place")
            p.add_argument("--accept-new", action="store_true", help="also record files that are not in the ledger yet")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        contract = load_contract(root)
        if args.cmd == "report":
            return _report(root, contract, args.json)
        if args.cmd == "ledger":
            new_ledger, refused = planned_ledger(root, contract, args.accept_new)
            for line in refused:
                print(f"  ! {line}")
            if args.write:
                write_ledger(root, new_ledger)
                print(f"wrote {CONTRACT} ledger: {len(new_ledger['sizes'])} sizes, {len(new_ledger['sys_path'])} sys.path entries")
            else:
                print(yaml.safe_dump({"ledger": new_ledger}, sort_keys=True, default_flow_style=False, width=200), end="")
            return 1 if refused else 0
        problems = check(root, contract)
    except ContractError as e:
        print(f"architecture: {e}", file=sys.stderr)
        return 2
    for line in problems:
        print(f"  ✗ {line}")
    print(f"architecture: {len(problems)} problem(s)" if problems else "architecture: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""schema_lint — validate and scaffold Pyramid Schema (SCHEMA.md) trees.

Spec: Pyramid Schema v0.1. Stdlib only.

Usage:
    python schema_lint.py check <path> [--fix] [--werror] [--include-hidden]
    python schema_lint.py init  <path>

`check` walks the pyramid from <path>, verifying every traversed directory's
SCHEMA.md against reality. Exit 0 = clean (warnings allowed unless --werror),
exit 1 = errors. With --fix, mechanical drift is remediated first — strays are
registered with TODO purposes (newly registered dirs get scaffolded schemas),
stale rows are pruned — then the tree is re-checked; review the diff and fill
the TODOs. `init` scaffolds a SCHEMA.md (coverage: listed, purposes TODO)
into every directory that lacks one; it never overwrites.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from dataclasses import dataclass, field
from pathlib import Path

SPEC_VERSION = "0.1"
KINDS = {"file", "dir", "pattern"}
RULE_TOKENS = {"required", "generated", "terminal"}
COVERAGES = {"strict", "listed", "open"}
DEFAULT_COVERAGE = "listed"
IMPLICIT_ALLOWED = {"SCHEMA.md"}
ALWAYS_IGNORED = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store",
}


@dataclass
class Row:
    entry: str          # literal name (no trailing slash) or glob
    kind: str           # file | dir | pattern
    purpose: str
    rules: set[str]
    seen: bool = False

    @property
    def required(self) -> bool:
        return "required" in self.rules

    @property
    def terminal(self) -> bool:
        # generated dirs are implicitly terminal
        return "terminal" in self.rules or "generated" in self.rules


@dataclass
class SchemaDoc:
    path: Path
    coverage: str = DEFAULT_COVERAGE
    rows: list[Row] = field(default_factory=list)
    has_table: bool = False  # a Structure table exists (may be empty)


@dataclass
class FixPlan:
    """Mechanical remediations `check --fix` may apply to one SCHEMA.md."""
    add: list[tuple[str, str]] = field(default_factory=list)   # (display, kind)
    prune: list[str] = field(default_factory=list)             # entry names


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plans: dict[Path, FixPlan] = field(default_factory=dict)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def plan(self, schema_path: Path) -> FixPlan:
        return self.plans.setdefault(schema_path, FixPlan())


# ---------------------------------------------------------------- parsing

def _parse_frontmatter(lines: list[str]) -> tuple[dict, int]:
    """Return (fields, index of first line after frontmatter)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    fields: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fields, i + 1
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields, 0  # unterminated; treat as no frontmatter


def _clean_entry(cell: str) -> str:
    return cell.strip().strip("`").strip().rstrip("/")


def parse_schema(path: Path, report: Report) -> SchemaDoc:
    rel = path
    doc = SchemaDoc(path=path)
    lines = path.read_text(encoding="utf-8").splitlines()

    fm, body_start = _parse_frontmatter(lines)
    if not fm:
        report.warn(f"{rel}: missing or unterminated frontmatter; "
                    f"assuming coverage '{DEFAULT_COVERAGE}'")
    coverage = fm.get("coverage", DEFAULT_COVERAGE)
    if coverage not in COVERAGES:
        report.warn(f"{rel}: unknown coverage '{coverage}'; "
                    f"assuming '{DEFAULT_COVERAGE}'")
        coverage = DEFAULT_COVERAGE
    doc.coverage = coverage
    declared = fm.get("schema")
    if declared and declared != SPEC_VERSION:
        report.warn(f"{rel}: declares spec '{declared}', linter implements "
                    f"'{SPEC_VERSION}'")

    # Locate the Structure section.
    in_structure = False
    table_lines: list[str] = []
    for line in lines[body_start:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_structure = stripped.lower().startswith("## structure")
            continue
        if in_structure and stripped.startswith("|"):
            table_lines.append(stripped)

    if not table_lines:
        report.error(f"{rel}: no '## Structure' table found")
        return doc
    doc.has_table = True

    for raw in table_lines[1:]:  # skip header row
        cells = [c.strip() for c in raw.strip("|").split("|")]
        if cells and set(cells[0]) <= {"-", ":", " "}:
            continue  # separator row
        if len(cells) < 4:
            report.warn(f"{rel}: malformed Structure row skipped: {raw!r}")
            continue
        entry, kind = _clean_entry(cells[0]), cells[1].strip().lower()
        purpose = cells[2].strip()
        rules = {t for t in cells[3].replace(",", " ").split() if t}
        if not entry:
            continue
        if kind not in KINDS:
            report.error(f"{rel}: entry '{entry}' has unknown kind '{kind}'")
            continue
        for token in rules - RULE_TOKENS:
            if not token.startswith("x-"):
                report.warn(f"{rel}: entry '{entry}' has unknown rule "
                            f"'{token}' (prefix custom rules with 'x-')")
        doc.rows.append(Row(entry=entry, kind=kind, purpose=purpose,
                            rules=rules))
    return doc


# ---------------------------------------------------------------- checking

def _match_row(name: str, is_dir: bool, doc: SchemaDoc) -> Row | None:
    for row in doc.rows:
        if row.kind == "pattern":
            if not is_dir and fnmatch.fnmatch(name, row.entry):
                return row
        elif row.entry == name:
            return row
    return None


def check_dir(dirpath: Path, root: Path, report: Report,
              include_hidden: bool) -> None:
    rel = dirpath.relative_to(root) if dirpath != root else Path(".")
    schema_path = dirpath / "SCHEMA.md"
    if not schema_path.exists():
        report.error(f"{rel}: missing SCHEMA.md (run 'init' to scaffold)")
        return

    doc = parse_schema(schema_path, report)
    registered_names = {r.entry for r in doc.rows if r.kind != "pattern"}

    entries = sorted(dirpath.iterdir(), key=lambda p: p.name)
    for child in entries:
        name = child.name
        if name in IMPLICIT_ALLOWED:
            continue
        if name in ALWAYS_IGNORED:
            # Registering one of these documents it; contents are never
            # verified and it is never descended into.
            row = _match_row(name, child.is_dir(), doc)
            if row is not None:
                row.seen = True
            continue
        if name.startswith(".") and not include_hidden \
                and name not in registered_names:
            continue

        row = _match_row(name, child.is_dir(), doc)
        if row is None:
            if doc.coverage == "strict":
                report.error(f"{rel}: unregistered entry '{name}' "
                             f"(coverage: strict)")
            elif doc.coverage == "listed":
                report.warn(f"{rel}: unregistered entry '{name}'")
            if doc.coverage != "open" and doc.has_table:
                display = f"{name}/" if child.is_dir() else name
                kind = "dir" if child.is_dir() else "file"
                report.plan(schema_path).add.append((display, kind))
            continue

        row.seen = True
        if row.kind != "pattern":
            actual = "dir" if child.is_dir() else "file"
            if row.kind != actual:
                report.error(f"{rel}: '{name}' registered as {row.kind} "
                             f"but is a {actual}")
                continue
        # Symlinked dirs are entries, not subtrees: never descend (their
        # targets are checked wherever they really live, and cycles must
        # not hang the walk).
        if child.is_dir() and not row.terminal and not child.is_symlink():
            check_dir(child, root, report, include_hidden)

    for row in doc.rows:
        if row.seen:
            continue
        if row.required:
            what = "at least one match for pattern" \
                if row.kind == "pattern" else row.kind
            report.error(f"{rel}: missing required {what} '{row.entry}'")
        elif row.kind != "pattern" and "generated" not in row.rules:
            report.warn(f"{rel}: stale entry '{row.entry}' "
                        f"(registered but absent)")
            report.plan(schema_path).prune.append(row.entry)


# ---------------------------------------------------------------- fix

def apply_fixes(report: Report, root: Path) -> list[str]:
    """Apply the mechanical remediations a check pass planned.

    Surgical, byte-preserving edits: append `| entry | kind | TODO | |` rows
    for strays at the end of the Structure table, drop the table lines of
    stale literal rows, and leave every other byte of the file alone.
    Newly registered directories get their missing schemas scaffolded via
    ``init_tree`` so the re-check can descend. Pattern, ``required``, and
    ``generated`` rows are never planned, hence never touched.
    Returns human-readable summary lines.
    """
    summary: list[str] = []
    for schema_path in sorted(report.plans):
        plan = report.plans[schema_path]
        if not plan.add and not plan.prune:
            continue
        lines = schema_path.read_text(encoding="utf-8").splitlines(keepends=True)

        in_structure = False
        first = last = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_structure = stripped.lower().startswith("## structure")
                continue
            if in_structure and stripped.startswith("|"):
                if first is None:
                    first = i
                last = i
        if first is None or last is None:
            continue  # no table to edit (already reported as an error)

        prune = set(plan.prune)
        drop: set[int] = set()
        for i in range(first, last + 1):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if not cells or set(cells[0]) <= {"-", ":", " "}:
                continue  # header/separator
            if _clean_entry(cells[0]) in prune:
                drop.add(i)

        add_rows = [f"| `{display}` | {kind} | TODO | |\n"
                    for display, kind in plan.add]
        out: list[str] = []
        for i, line in enumerate(lines):
            keep = i not in drop
            if keep:
                out.append(line)
            if i == last and add_rows:
                if keep and not line.endswith("\n"):
                    out[-1] = line + "\n"
                out.extend(add_rows)
        schema_path.write_text("".join(out), encoding="utf-8")

        scaffolded = 0
        for display, kind in plan.add:
            if kind == "dir":
                target = schema_path.parent / display.rstrip("/")
                if target.is_dir() and not target.is_symlink():
                    scaffolded += len(init_tree(target))

        rel = schema_path.relative_to(root)
        parts = [f"+{len(add_rows)} registered"] if add_rows else []
        if drop:
            parts.append(f"-{len(drop)} stale pruned")
        if scaffolded:
            parts.append(f"{scaffolded} SCHEMA.md scaffolded")
        summary.append(f"fixed    {rel}: {', '.join(parts)}")
    return summary


# ---------------------------------------------------------------- init

INIT_TEMPLATE = """\
---
schema: "0.1"
coverage: listed
---

# SCHEMA — {name}

> TODO: one sentence — what this directory is for.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
{rows}
## Placement

- TODO: route common additions, or delete this section.
"""


def _terminal_marked(root: Path) -> set[Path]:
    """Dirs that existing schemas mark terminal/generated — init keeps out."""
    terminals: set[Path] = set()
    scratch = Report()
    for schema_path in root.rglob("SCHEMA.md"):
        parts = set(schema_path.relative_to(root).parts[:-1])
        if parts & ALWAYS_IGNORED or any(p.startswith(".") for p in parts):
            continue
        doc = parse_schema(schema_path, scratch)
        for row in doc.rows:
            if row.kind == "dir" and row.terminal:
                terminals.add((schema_path.parent / row.entry).resolve())
    return terminals


def init_tree(root: Path) -> list[Path]:
    created: list[Path] = []
    terminals = _terminal_marked(root)
    for dirpath in sorted([root, *root.rglob("*")]):
        if not dirpath.is_dir() or dirpath.is_symlink():
            continue
        parts = set(dirpath.relative_to(root).parts)
        if parts & ALWAYS_IGNORED or any(p.startswith(".") for p in parts):
            continue
        resolved = dirpath.resolve()
        if any(t == resolved or t in resolved.parents for t in terminals):
            continue
        schema_path = dirpath / "SCHEMA.md"
        if schema_path.exists():
            continue
        rows = []
        for child in sorted(dirpath.iterdir(),
                            key=lambda p: (p.is_file(), p.name)):
            name = child.name
            if name in ALWAYS_IGNORED or name in IMPLICIT_ALLOWED \
                    or name.startswith("."):
                continue
            kind = "dir" if child.is_dir() else "file"
            display = f"{name}/" if child.is_dir() else name
            rows.append(f"| `{display}` | {kind} | TODO | |")
        schema_path.write_text(
            INIT_TEMPLATE.format(name=dirpath.name or root.resolve().name,
                                 rows="\n".join(rows) + ("\n" if rows else "")),
            encoding="utf-8")
        created.append(schema_path)
    return created


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schema_lint",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="validate a schema pyramid")
    p_check.add_argument("path", nargs="?", default=".")
    p_check.add_argument("--fix", action="store_true",
                         help="auto-register strays (TODO purposes) and "
                              "prune stale rows, then re-check")
    p_check.add_argument("--werror", action="store_true",
                         help="treat warnings as errors")
    p_check.add_argument("--include-hidden", action="store_true",
                         help="also check dotfiles/dirs")

    p_init = sub.add_parser("init", help="scaffold missing SCHEMA.md files")
    p_init.add_argument("path", nargs="?", default=".")

    args = parser.parse_args(argv)
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    if args.command == "init":
        created = init_tree(root)
        if created:
            print(f"Scaffolded {len(created)} SCHEMA.md file(s):")
            for p in created:
                print(f"  + {p.relative_to(root)}")
            print("Next: replace the TODOs, then run "
                  "'schema_lint.py check' — the pyramid rises.")
        else:
            print("Nothing to scaffold; every directory already has a "
                  "SCHEMA.md.")
        return 0

    report = Report()
    check_dir(root, root, report, include_hidden=args.include_hidden)

    if args.fix and report.plans:
        fixed = apply_fixes(report, root)
        if fixed:
            for line in fixed:
                print(line)
            print("note: review the diff and fill in the TODO purposes "
                  "left by --fix.")
            report = Report()
            check_dir(root, root, report, include_hidden=args.include_hidden)

    for msg in report.errors:
        print(f"ERROR    {msg}")
    for msg in report.warnings:
        print(f"warning  {msg}")

    n_err, n_warn = len(report.errors), len(report.warnings)
    verdict = "FAIL" if n_err or (args.werror and n_warn) else "PASS"
    print(f"\n{verdict}: {n_err} error(s), {n_warn} warning(s)")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())

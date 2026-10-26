#!/usr/bin/env python3
"""Discovery audit for a spec-driven repo: the headless half of /evolve.

Fleet copy: bamr87/bamr87 templates/spec-driven/tools/evolve_audit.py. Consumed
by reference (the spec-driven plugin, or ``tools/fleet-kit.sh``); a vendored copy
is kept byte-identical like the other kit tools.

Scans the repo for follow-up candidates and appends them to ``BACKLOG.md`` under
``## Open``, in the bullet grammar ``backlog_lint.py`` checks::

    - **BL-YYYYMMDD-NN** — *kind, severity* — title. rationale _Surfaced in:_ …

Signals:

* ``TODO`` / ``FIXME`` / ``XXX`` / ``HACK`` comments in tracked source files
  (``git ls-files``; vendored and generated trees skipped) whose title is not
  already in the backlog.
* ``docs/<name>.md`` files referenced from ``AGENTS.md`` that do not exist
  (case-insensitive, so a case-mismatched link is never a false positive).
* A coverage shortfall against ``--coverage-floor`` (default 75), read from a
  Cobertura ``coverage.xml``: ``--coverage-xml``, else the first of
  ``coverage.xml``, ``backend/coverage.xml``, ``frontend/coverage/cobertura-coverage.xml``.

Repo-specific signals (a benchmark regression, an eval score) belong in the
repo's own harness, which fails the run on its own; this audit only files the
generic follow-ups. The script never deletes an entry and exits 0 even when it
adds nothing (idempotent). ``--dry-run`` prints the bullets without writing.

    python3 tools/evolve_audit.py [--root <repo>] [--dry-run] [--coverage-floor 75] [--coverage-xml <path>]
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s-]*(.{0,100})", re.IGNORECASE)
EXISTING_BL_RE = re.compile(r"\bBL-\d{8}-\d{2}\b")
SOURCE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rb", ".go", ".rs", ".sh",
    ".java", ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".cs", ".php", ".ex", ".exs",
}
SKIP_PARTS = {"node_modules", "vendor", "third_party", "dist", "build", ".next", "__pycache__", "specs", "archive"}
COVERAGE_CANDIDATES = ("coverage.xml", "backend/coverage.xml", "frontend/coverage/cobertura-coverage.xml")


@dataclass(frozen=True)
class Candidate:
    kind: str  # feature | refactor | tech-debt | test-gap | doc-gap | infra
    severity: str  # low | med | high
    title: str
    rationale: str
    surfaced: str = "evolve audit"

    def render(self, bl_id: str) -> str:
        return f"- **{bl_id}** — *{self.kind}, {self.severity}* — {self.title}. {self.rationale} _Surfaced in:_ {self.surfaced}."


def tracked_source_files(root: Path) -> Iterable[Path]:
    """Source files git tracks under ``root`` (respects .gitignore), minus vendored trees."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    files = []
    for rel in out.split("\0"):
        if not rel:
            continue
        p = Path(rel)
        if p.suffix.lower() not in SOURCE_SUFFIXES or SKIP_PARTS & set(p.parts) or ".min." in p.name:
            continue
        if (root / p).is_file():
            files.append(root / p)
    return files


def scan_todos(root: Path) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for path in tracked_source_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        for match in TODO_RE.finditer(text):
            tag, msg = match.group(1).upper(), match.group(2).strip()
            key = f"{rel}:{msg[:60]}"
            if key in seen or not msg:
                continue
            seen.add(key)
            sev = "high" if tag in {"FIXME", "XXX"} else "med"
            kind = "tech-debt" if tag == "HACK" else "test-gap" if "test" in msg.lower() else "refactor"
            out.append(Candidate(kind, sev, f"Resolve {tag} in {rel}", f'Comment: "{msg}"', "evolve audit (TODO scan)"))
    return out


def scan_missing_docs(root: Path) -> list[Candidate]:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return []
    referenced = sorted(set(re.findall(r"docs/[A-Za-z0-9_-]+\.md", agents.read_text(encoding="utf-8"))))
    docs_dir = root / "docs"
    existing_lower = {p.name.lower() for p in docs_dir.glob("*.md")} if docs_dir.is_dir() else set()
    return [
        Candidate("doc-gap", "low", f"Author missing doc {doc}", "Referenced by AGENTS.md but the file does not exist.", "evolve audit (missing-docs scan)")
        for doc in referenced
        if doc.split("/", 1)[1].lower() not in existing_lower
    ]


def coverage_report(xml_path: Path) -> tuple[float, list[tuple[str, float]]] | None:
    """(overall line coverage %, [(module, %)] lowest first) from a Cobertura file, or None."""
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return None
    cov = tree.getroot()
    try:
        total = float(cov.attrib.get("line-rate", "")) * 100.0
    except ValueError:
        return None
    modules = []
    for cls in cov.iter("class"):
        try:
            modules.append((cls.attrib.get("filename") or cls.attrib.get("name") or "?", float(cls.attrib.get("line-rate", "0")) * 100.0))
        except ValueError:
            continue
    modules.sort(key=lambda m: m[1])
    return round(total, 1), modules


def scan_coverage(root: Path, floor: float, xml: Path | None) -> list[Candidate]:
    candidates = [xml] if xml else [root / c for c in COVERAGE_CANDIDATES]
    path = next((p for p in candidates if p and p.is_file()), None)
    if path is None:
        return []
    report = coverage_report(path)
    if report is None:
        return []
    total, modules = report
    if total >= floor:
        return []
    worst = [m for m in modules if m[1] < floor][:5]
    details = ", ".join(f"{name}({pct:.0f}%)" for name, pct in worst) if worst else f"see {path.relative_to(root)}"
    return [
        Candidate(
            "test-gap",
            "high" if total < floor - 10 else "med",
            f"Coverage at {total:.0f}% (floor {floor:.0f}%)",
            f"Lowest-coverage modules: {details}. Add unit tests.",
            "evolve audit (coverage scan)",
        )
    ]


def existing_titles(backlog: Path) -> set[str]:
    if not backlog.exists():
        return set()
    titles: set[str] = set()
    for line in backlog.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **BL-"):
            # Split on '. ' (period + space), not a bare '.': titles embed file
            # paths whose extension dot would truncate the key and break dedup.
            parts = line.split(" — ", 2)
            if len(parts) == 3:
                titles.add(parts[2].split(". ", 1)[0].strip().lower())
    return titles


def next_id_seed(backlog: Path) -> tuple[str, int]:
    today = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    if not backlog.exists():
        return today, 1
    existing = EXISTING_BL_RE.findall(backlog.read_text(encoding="utf-8"))
    todays = [int(bl.split("-")[2]) for bl in existing if bl.startswith(f"BL-{today}-")]
    return today, (max(todays) + 1) if todays else 1


def insert_under_open(backlog: Path, bullets: list[str]) -> None:
    text = backlog.read_text(encoding="utf-8")
    # Anchor on the heading LINE, not a bare substring: a prose mention of
    # "## Open" earlier in the file must not become the insertion point.
    m = re.search(r"^## Open[ \t]*$", text, re.MULTILINE)
    if m is None:
        raise SystemExit("BACKLOG.md missing '## Open' section")
    eol = text.find("\n", m.end())
    insert_at = len(text) if eol == -1 else eol + 1
    prefix = text[:insert_at] if eol != -1 else text[:insert_at] + "\n"
    backlog.write_text(prefix + "\n" + "\n".join(bullets) + "\n" + text[insert_at:], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--root", type=Path, default=None, help="repo checkout to audit (default: the git root of the cwd)")
    ap.add_argument("--dry-run", action="store_true", help="print the bullets; do not write BACKLOG.md")
    ap.add_argument("--coverage-floor", type=float, default=75.0)
    ap.add_argument("--coverage-xml", type=Path, default=None)
    args = ap.parse_args(argv)

    root = args.root.resolve() if args.root else Path(
        subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False).stdout.strip() or "."
    ).resolve()
    backlog = root / "BACKLOG.md"
    if not backlog.is_file():
        print(f"evolve_audit: no BACKLOG.md under {root}; nothing to append to")
        return 0

    candidates = scan_todos(root) + scan_missing_docs(root) + scan_coverage(root, args.coverage_floor, args.coverage_xml)
    if not candidates:
        print("evolve_audit: no new candidates")
        return 0
    seen = existing_titles(backlog)
    fresh = [c for c in candidates if c.title.lower() not in seen]
    if not fresh:
        print("evolve_audit: all candidates already in BACKLOG")
        return 0

    today, seed = next_id_seed(backlog)
    bullets = [c.render(f"BL-{today}-{seed + i:02d}") for i, c in enumerate(fresh)]
    if args.dry_run:
        print(f"evolve_audit: would append {len(bullets)} item(s) to BACKLOG.md (--dry-run)")
    else:
        insert_under_open(backlog, bullets)
        print(f"evolve_audit: appended {len(bullets)} item(s) to BACKLOG.md")
    for line in bullets:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

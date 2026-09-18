#!/usr/bin/env python3
"""Fleet-portable UX audit (UPS-FE-60 R1–R13).

Stdlib only. Scans text sources under one or more roots and reports
machine-checkable UX/accessibility regressions. App-specific deeper rules
belong in the leaf (see bamr87/law-ai scripts/ux_audit.py as a reference).

Rules (aligned with specs/FRONTEND.md UPS-FE-60):
  R1  one scroller        — avoid ad-hoc overflow:auto/scroll on page chrome
  R2  viewport ownership  — avoid 100vh/100dvh grabs outside a declared shell
  R3  single <main>       — at most one <main> / role="main" per file
  R4  z-scale only        — raw z-index integers outside token files
  R5  focus indicator     — outline:none / outline-none without a replacement
  R6  landmark labels     — <nav>/<aside> without aria-label / aria-labelledby
  R7  page layout         — route files that skip a shared layout primitive
  R8  route states        — app-router groups missing loading/error/not-found
  R9  sticky offsets      — sticky/fixed top with magic pixels
  R10 composite names     — tablist/radiogroup/menu without an accessible name
  R11 control names       — input/textarea/select with placeholder-only naming
  R12 shared-CSS drift    — duplicate *.css basenames with divergent hashes
  R13 token literal leak  — hex/rgb colors outside token/theme files

Exempt a file:   ux-audit: exempt — <reason>
Exempt one rule: ux-audit: exempt-R5 — <reason>

Usage:
  python3 scripts/ux_audit.py --root .
  python3 scripts/ux_audit.py --root frontend --root lsat-static --list
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

RULES: list[tuple[str, str]] = [
    ("R1", "one scroller — avoid ad-hoc overflow scroll on page chrome"),
    ("R2", "viewport ownership — avoid 100vh/100dvh outside a shell"),
    ("R3", "single <main> — at most one main landmark per file"),
    ("R4", "z-scale only — no raw z-index integers outside tokens"),
    ("R5", "focus indicator — outline removed without a replacement"),
    ("R6", "landmark labels — nav/aside need an accessible name"),
    ("R7", "page layout — routes should use a shared layout primitive"),
    ("R8", "route states — loading/error/not-found siblings for app routes"),
    ("R9", "sticky offsets — sticky/fixed top uses tokens, not magic px"),
    ("R10", "composite names — tablist/radiogroup/menu need a name"),
    ("R11", "control names — controls need a label, not placeholder-only"),
    ("R12", "shared-CSS drift — duplicate CSS basenames must stay in sync"),
    ("R13", "token literal leak — hex/rgb colors belong in token files"),
]

TEXT_GLOBS = (
    "*.html", "*.htm", "*.md", "*.mdx",
    "*.css", "*.scss", "*.sass", "*.less",
    "*.js", "*.jsx", "*.ts", "*.tsx", "*.vue", "*.svelte",
    "*.erb", "*.hbs", "*.njk", "*.liquid",
)

SKIP_DIR_NAMES = {
    ".git", "node_modules", "vendor", "dist", "build", "_site",
    ".next", ".venv", "venv", "coverage", "__pycache__", ".turbo",
    "Pods", "target", "out",
}

TOKEN_PATH_HINTS = ("token", "theme", "design-system", "variables", "palette")
SHELL_PATH_HINTS = ("shell", "layout", "appshell", "page-layout", "base.css", "globals.css")
LAYOUT_HINTS = (
    "PageLayout", "AppShell", "SiteHeader", "BaseLayout", "DefaultLayout",
    "layout.tsx", "layout.jsx", "_layouts/", "root.html",
)

RE_OVERFLOW = re.compile(r"overflow(?:-y|-x)?\s*:\s*(auto|scroll)\b|overflow-(?:auto|scroll|y-auto|y-scroll)\b")
RE_VIEWPORT = re.compile(r"\b(?:min-|max-)?h-(?:screen|dvh|svh)|(?:min-|max-)?height\s*:\s*100(?:vh|dvh|svh)\b")
RE_MAIN = re.compile(r"<main\b|role=['\"]main['\"]", re.I)
RE_ZINDEX = re.compile(r"z-index\s*:\s*-?\d+|z-\[?\d{1,4}\]?")
RE_OUTLINE_NONE = re.compile(r"outline\s*:\s*none\b|outline-none\b|focus:outline-none\b")
RE_FOCUS_RING = re.compile(r"focus-visible|:focus-visible|focus:ring|focus-ring|outline\s*:\s*[^n]")
RE_NAV = re.compile(r"<(nav|aside)\b([^>]*)>", re.I)
RE_ARIA_NAME = re.compile(r"aria-(?:label|labelledby)\s*=", re.I)
RE_STICKY_TOP = re.compile(r"position\s*:\s*(sticky|fixed)[^;]{0,80}top\s*:\s*\d+px|sticky[^\"'\n]{0,40}top-\d+|top-\[[0-9]+px\]")
RE_COMPOSITE = re.compile(r"role=['\"](tablist|radiogroup|menu|menubar|listbox|tree)['\"]", re.I)
RE_PLACEHOLDER_ONLY = re.compile(
    r"<(input|textarea|select)\b(?=[^>]*placeholder=)(?![^>]*(?:aria-label|aria-labelledby|id=))[^>]*>",
    re.I,
)
RE_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RE_RGB = re.compile(r"\brgba?\([^)]+\)")
RE_EXEMPT_ALL = re.compile(r"ux-audit:\s*exempt\s*[—-]\s*\S+")
RE_EXEMPT_RULE = re.compile(r"ux-audit:\s*exempt-(R\d+)\s*[—-]\s*\S+")


@dataclass
class Finding:
    rule: str
    path: Path
    line: int
    message: str


@dataclass
class Audit:
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, path: Path, line: int, message: str) -> None:
        self.findings.append(Finding(rule, path, line, message))


def _is_token_file(path: Path) -> bool:
    p = str(path).lower()
    return any(h in p for h in TOKEN_PATH_HINTS)


def _is_shell_file(path: Path) -> bool:
    p = str(path).lower()
    return any(h in p for h in SHELL_PATH_HINTS)


def _iter_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix and any(path.match(g) for g in TEXT_GLOBS):
                out.append(path)
            elif path.name in {"ux.yml", "ux.yaml"}:
                out.append(path)
    return sorted(set(out))


def _exempt_rules(text: str) -> set[str]:
    if RE_EXEMPT_ALL.search(text):
        return {r for r, _ in RULES}
    return {m.group(1) for m in RE_EXEMPT_RULE.finditer(text)}


def audit_file(path: Path, text: str, audit: Audit) -> None:
    exempt = _exempt_rules(text)
    lines = text.splitlines()

    def hit(rule: str, idx: int, msg: str) -> None:
        if rule not in exempt:
            audit.add(rule, path, idx + 1, msg)

    # R3 — count mains
    if "R3" not in exempt:
        mains = list(RE_MAIN.finditer(text))
        if len(mains) > 1:
            line = text[: mains[1].start()].count("\n") + 1
            audit.add("R3", path, line, f"{len(mains)} <main> landmarks in one file")

    for idx, line in enumerate(lines):
        if "R1" not in exempt and RE_OVERFLOW.search(line) and not _is_shell_file(path):
            hit("R1", idx, "ad-hoc overflow scroll; prefer the shared shell scroller")
        if "R2" not in exempt and RE_VIEWPORT.search(line) and not _is_shell_file(path):
            hit("R2", idx, "viewport height grab outside a shell/layout file")
        if "R4" not in exempt and RE_ZINDEX.search(line) and not _is_token_file(path):
            # allow z-0/z-10 token-ish utilities commonly paired with scales — still flag raw z-index: N
            if re.search(r"z-index\s*:\s*-?\d+", line) or re.search(r"z-\[\d+\]", line):
                hit("R4", idx, "raw z-index; use the named z-scale/tokens")
        if "R5" not in exempt and RE_OUTLINE_NONE.search(line) and not RE_FOCUS_RING.search(line):
            # check nearby lines for a replacement
            window = "\n".join(lines[max(0, idx - 2): idx + 3])
            if not RE_FOCUS_RING.search(window):
                hit("R5", idx, "focus outline removed without a visible focus-visible replacement")
        if "R9" not in exempt and RE_STICKY_TOP.search(line) and not _is_token_file(path):
            hit("R9", idx, "sticky/fixed top uses a magic pixel value")
        if "R13" not in exempt and not _is_token_file(path):
            if RE_HEX.search(line) or RE_RGB.search(line):
                # ignore hex in hashes / issue ids loosely: require CSS-ish context
                if any(k in line for k in ("color", "background", "border", "fill", "stroke", "#", "rgb")):
                    if RE_HEX.search(line) or RE_RGB.search(line):
                        hit("R13", idx, "color literal outside a token/theme file")

    # Tag-level scans on joined text for multi-line tags
    for m in RE_NAV.finditer(text):
        if "R6" in exempt:
            break
        attrs = m.group(2) or ""
        if not RE_ARIA_NAME.search(attrs):
            line = text[: m.start()].count("\n") + 1
            audit.add("R6", path, line, f"<{m.group(1).lower()}> missing aria-label / aria-labelledby")

    for m in RE_COMPOSITE.finditer(text):
        if "R10" in exempt:
            break
        # look at a short window for a name
        window = text[m.start(): m.start() + 200]
        if not RE_ARIA_NAME.search(window):
            line = text[: m.start()].count("\n") + 1
            audit.add("R10", path, line, f"role={m.group(1)} missing an accessible name")

    for m in RE_PLACEHOLDER_ONLY.finditer(text):
        if "R11" in exempt:
            break
        line = text[: m.start()].count("\n") + 1
        audit.add("R11", path, line, "form control appears placeholder-only (no label/aria name on the tag)")

    # R7 — lightweight heuristic for route files
    if "R7" not in exempt:
        lower = str(path).lower()
        if any(seg in lower for seg in ("/pages/", "/app/", "/routes/", "/views/")) and path.suffix in {
            ".tsx", ".jsx", ".vue", ".svelte", ".html", ".erb", ".njk", ".liquid",
        }:
            if path.name.startswith("layout"):
                return
            if not any(h.lower() in text.lower() for h in LAYOUT_HINTS):
                # only flag "page-like" filenames
                if re.search(r"(page|index|view|screen)\.(tsx|jsx|vue|svelte|html)$", path.name, re.I):
                    audit.add("R7", path, 1, "page/route file does not reference a shared layout primitive")


def audit_route_states(roots: list[Path], audit: Audit) -> None:
    """R8: Next-style app-router groups should ship loading/error/not-found."""
    for root in roots:
        for layout in root.rglob("layout.tsx"):
            if any(part in SKIP_DIR_NAMES for part in layout.parts):
                continue
            parent = layout.parent
            needed = ["loading.tsx", "error.tsx", "not-found.tsx"]
            missing = [n for n in needed if not (parent / n).exists()]
            in_group = "(app)" in parent.parts or parent.name.startswith("(") or any(
                part.name.startswith("(") for part in parent.parents
            )
            if missing and in_group:
                audit.add("R8", layout, 1, f"route group missing {', '.join(missing)}")


def audit_css_drift(files: list[Path], audit: Audit) -> None:
    """R12: same basename CSS with different content."""
    by_name: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for path in files:
        if path.suffix.lower() not in {".css", ".scss"}:
            continue
        data = path.read_bytes()
        by_name[path.name].append((path, hashlib.sha256(data).hexdigest()))
    for name, entries in by_name.items():
        if len(entries) < 2:
            continue
        hashes = {h for _, h in entries}
        if len(hashes) > 1:
            paths = ", ".join(str(p) for p, _ in entries)
            audit.add("R12", entries[0][0], 1, f"divergent copies of {name}: {paths}")


def run(roots: list[Path]) -> Audit:
    audit = Audit()
    files = _iter_files(roots)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            audit.add("R0", path, 1, f"unreadable: {exc}")
            continue
        audit_file(path, text, audit)
    audit_route_states(roots, audit)
    audit_css_drift(files, audit)
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, default=None,
                        help="source root to scan (repeatable). Default: .")
    parser.add_argument("--list", action="store_true", help="print rules and exit")
    parser.add_argument("--max", type=int, default=0, help="optional max findings before abort (0 = no cap)")
    args = parser.parse_args(argv)

    if args.list:
        for rid, desc in RULES:
            print(f"{rid}\t{desc}")
        return 0

    roots = args.root or [Path(".")]
    audit = run(roots)
    for finding in audit.findings:
        print(f"{finding.rule}:{finding.path}:{finding.line}: {finding.message}")
        if args.max and len(audit.findings) >= args.max:
            break

    by_rule: dict[str, int] = defaultdict(int)
    for f in audit.findings:
        by_rule[f.rule] += 1
    print(f"ux_audit: {len(audit.findings)} finding(s) across {len(by_rule)} rule(s)", file=sys.stderr)
    return 1 if audit.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

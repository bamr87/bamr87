#!/usr/bin/env python3
"""Headless discovery half of /evolve.

Audits the repo for follow-up candidates and appends them to BACKLOG.md
under ``## Open``. Safe to run unattended (cron / launchd / GitHub Actions).

Signals collected:
- TODO / FIXME / XXX / HACK comments not already covered by an existing BL-* id.
- Missing docs referenced from AGENTS.md (e.g. ``docs/data-model.md``).
- Coverage shortfall vs. constitution gate (65%).
- Ruff / black violations that linger past auto-fix.

Each new candidate becomes a ``BL-YYYYMMDD-NN`` bullet in the format expected
by ``scripts/backlog_lint.py``. The script never deletes existing entries and
exits 0 even when it adds nothing (idempotent).
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "BACKLOG.md"
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s-]*(.{0,100})", re.IGNORECASE)
EXISTING_BL_RE = re.compile(r"\bBL-\d{8}-\d{2}\b")
SCAN_GLOBS = ("backend/law_ai/**/*.py", "frontend/app/**/*.ts", "frontend/components/**/*.tsx")
SKIP_DIRS = {".venv", "node_modules", ".next", "__pycache__", ".git"}


@dataclass(frozen=True)
class Candidate:
    kind: str  # feature | refactor | tech-debt | test-gap | doc-gap | infra
    severity: str  # low | med | high
    title: str
    rationale: str
    surfaced: str = "weekly evolve audit"  # provenance tail, per the house bullet format

    def render(self, bl_id: str) -> str:
        return (
            f"- **{bl_id}** — *{self.kind}, {self.severity}* — {self.title}. "
            f"{self.rationale} _Surfaced in:_ {self.surfaced}."
        )


def _iter_files() -> Iterable[Path]:
    for pattern in SCAN_GLOBS:
        for path in REPO.glob(pattern):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path


def _scan_todos() -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in TODO_RE.finditer(text):
            tag, msg = match.group(1).upper(), match.group(2).strip()
            key = f"{path.relative_to(REPO)}:{msg[:60]}"
            if key in seen or not msg:
                continue
            seen.add(key)
            sev = "high" if tag in {"FIXME", "XXX"} else "med"
            kind = "tech-debt" if tag == "HACK" else "test-gap" if "test" in msg.lower() else "refactor"
            out.append(
                Candidate(
                    kind=kind,
                    severity=sev,
                    title=f"Resolve {tag} in {path.relative_to(REPO)}",
                    rationale=f'Comment: "{msg}"',
                    surfaced="weekly evolve audit (TODO scan)",
                )
            )
    return out


def _scan_missing_docs() -> list[Candidate]:
    """Flag ``docs/*.md`` files referenced from AGENTS.md that do not exist.

    The reference list is parsed from AGENTS.md so it self-maintains, and the
    existence check is **case-insensitive** so a case-mismatched path (e.g.
    ``docs/AO-SDLC.md`` vs. the real ``docs/ao-sdlc.md``) is never mis-flagged as
    missing on case-sensitive filesystems — the recurring false positive that
    kept re-appearing in the weekly audit.
    """
    agents = REPO / "AGENTS.md"
    if not agents.exists():
        return []
    referenced = sorted(set(re.findall(r"docs/[A-Za-z0-9_-]+\.md", agents.read_text(encoding="utf-8"))))
    docs_dir = REPO / "docs"
    existing_lower = {p.name.lower() for p in docs_dir.glob("*.md")} if docs_dir.is_dir() else set()
    return [
        Candidate(
            kind="doc-gap",
            severity="low",
            title=f"Author missing doc {doc}",
            rationale="Referenced by AGENTS.md but file does not exist.",
            surfaced="weekly evolve audit (missing-docs scan)",
        )
        for doc in referenced
        if doc.split("/", 1)[1].lower() not in existing_lower
    ]


def _scan_coverage() -> list[Candidate]:
    """Delegate to law_ai.eval.coverage_audit (spec 018 T-003).

    Imports the Django-free ``coverage_audit`` module directly from the backend
    package directory so this script can still run stdlib-only on the host.

    When ``law_ai.eval.coverage_audit`` is already in ``sys.modules`` (e.g.
    during pytest runs that monkeypatch ``_DEFAULT_XML``), that existing module
    is reused rather than loading a fresh copy, so test patches take effect.
    """
    import importlib.util
    import sys

    # Prefer the already-imported version so test monkeypatches on
    # ``law_ai.eval.coverage_audit._DEFAULT_XML`` are respected.
    ca = sys.modules.get("law_ai.eval.coverage_audit")
    if ca is None:
        ca_path = REPO / "backend" / "law_ai" / "eval" / "coverage_audit.py"
        if not ca_path.exists():
            return []

        spec = importlib.util.spec_from_file_location("coverage_audit", ca_path)
        if spec is None or spec.loader is None:
            return []
        ca = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("coverage_audit", ca)
        spec.loader.exec_module(ca)  # type: ignore[union-attr]

    total = ca.overall_coverage()
    if total is None:
        return []
    if total >= 75.0:
        return []

    records = ca.load_coverage_report()
    worst = [r for r in records if r.pct < 75.0][:5]
    details = ", ".join(f"{r.module}({r.pct}%)" for r in worst) if worst else "see coverage.xml"
    return [
        Candidate(
            kind="test-gap",
            severity="high" if total < 65.0 else "med",
            title=f"Backend coverage at {total:.0f}% (gate 65%, target 75%)",
            rationale=f"Lowest-coverage modules: {details}. Add unit tests.",
            surfaced="weekly evolve audit (coverage scan)",
        )
    ]


def _scan_legalbench() -> list[Candidate]:
    """Return a candidate if the latest LegalBench report shows a regression.

    Reads the most-recent timestamped JSON from ``backend/var/legalbench/`` and
    checks whether any subset delta is negative (score dropped vs. baseline).
    Report files are named ``<UTC-timestamp>.json`` (e.g. ``20260501T060000Z.json``);
    ``baseline.json`` is excluded.
    """
    report_dir = REPO / "backend" / "var" / "legalbench"
    reports = sorted(
        (p for p in report_dir.glob("*.json") if p.name != "baseline.json"),
        reverse=True,
    )
    if not reports:
        return []

    import json as _json

    try:
        data = _json.loads(reports[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    delta_section = data.get("delta", {})
    regressions = [
        (subset, info["delta_pp"])
        for subset, info in delta_section.items()
        if isinstance(info, dict) and info.get("delta_pp", 0) < 0
    ]
    if not regressions:
        return []

    details = "; ".join(f"{s}: {d:+.1f}pp" for s, d in regressions)
    return [
        Candidate(
            kind="test-gap",
            severity="high",
            title=f"LegalBench regression detected in {len(regressions)} subset(s)",
            rationale=f"Deltas vs baseline: {details}. Review scoring and prompt changes.",
            surfaced="weekly evolve audit (LegalBench scan)",
        )
    ]


def _existing_titles() -> set[str]:
    if not BACKLOG.exists():
        return set()
    titles: set[str] = set()
    for line in BACKLOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **BL-"):
            # Title is between the second em-dash and the first sentence end.
            # Split on '. ' (period + space), NOT a bare '.': generated titles
            # embed file paths whose extension dot would otherwise truncate the
            # key and break dedup forever — the audit re-appended the same
            # items with fresh ids on every run (spec 038 backport).
            parts = line.split(" — ", 2)
            if len(parts) == 3:
                titles.add(parts[2].split(". ", 1)[0].strip().lower())
    return titles


def _next_id_seed() -> tuple[str, int]:
    today = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    if not BACKLOG.exists():
        return today, 1
    existing = EXISTING_BL_RE.findall(BACKLOG.read_text(encoding="utf-8"))
    todays = [int(bl.split("-")[2]) for bl in existing if bl.startswith(f"BL-{today}-")]
    return today, (max(todays) + 1) if todays else 1


def _insert_under_open(new_bullets: list[str]) -> None:
    text = BACKLOG.read_text(encoding="utf-8")
    # Anchor on the heading LINE, not a bare substring — a prose mention of
    # "## Open" earlier in the file must not become the insertion point.
    m = re.search(r"^## Open[ \t]*$", text, re.MULTILINE)
    if m is None:
        raise SystemExit("BACKLOG.md missing '## Open' section")
    eol = text.find("\n", m.end())
    # Heading at EOF without a trailing newline: normalize so the bullets
    # still land on their own lines instead of crashing (spec 038 backport).
    insert_at = len(text) if eol == -1 else eol + 1
    prefix = text[:insert_at] if eol != -1 else text[:insert_at] + "\n"
    insertion = "\n" + "\n".join(new_bullets) + "\n"
    BACKLOG.write_text(prefix + insertion + text[insert_at:], encoding="utf-8")


def main() -> int:
    candidates = _scan_todos() + _scan_missing_docs() + _scan_coverage() + _scan_legalbench()
    if not candidates:
        print("evolve_audit: no new candidates")
        return 0

    seen_titles = _existing_titles()
    fresh = [c for c in candidates if c.title.lower() not in seen_titles]
    if not fresh:
        print("evolve_audit: all candidates already in BACKLOG")
        return 0

    today, seed = _next_id_seed()
    bullets = [c.render(f"BL-{today}-{seed + i:02d}") for i, c in enumerate(fresh)]
    _insert_under_open(bullets)
    print(f"evolve_audit: appended {len(bullets)} item(s) to BACKLOG.md")
    for line in bullets:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

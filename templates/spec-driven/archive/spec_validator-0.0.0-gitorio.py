#!/usr/bin/env python3
"""Spec drift validator for GitFactory specs/ (AO-SDLC, ADR-022).

Enforces that every spec under ``specs/NNN-*`` is internally consistent:

* ``spec.md``, ``plan.md``, and ``tasks.md`` all exist.
* No unresolved ``OPEN QUESTION OQ-N`` blocks remain in ``spec.md``.
* Every ``FR-*``, ``NFR-*``, and ``AC-*`` ID defined in ``spec.md`` is
  referenced by at least one task in ``tasks.md``.
* ``tasks.md`` contains a ``## Follow-ups Discovered`` section so every
  implementation cycle is forced to record next-step work (the *content*
  of the section is reviewed by humans/PR, not validated here; an
  explicitly-empty list records ``_none — justified: <reason>_``).

Exit code is non-zero if any spec fails. Used as a CI gate (ci.yml
``spec-gate`` job) and by the ``.claude/hooks/gate-check.sh`` PostToolUse
hook. Ported from law-ai's ``scripts/spec_validator.py`` (golden rule #11).

Usage::

    python3 tools/spec_validator.py            # validate all specs/
    python3 tools/spec_validator.py specs/001-foo
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
SPEC_DIR_RE = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")
ID_RE = re.compile(r"\b((?:FR|NFR|AC)-[A-Z0-9-]+)\b")
OPEN_Q_RE = re.compile(r"OPEN QUESTION\s+OQ-\d+", re.IGNORECASE)
STATUS_RE = re.compile(r"^- \*\*Status\*\*:\s*([a-z\-]+)", re.IGNORECASE | re.MULTILINE)
# Task status markers — supports both the canonical `- **Status**: `[x]``
# block format and the compact `- [x] **T-NNN** — …` line format.
TASK_STATUS_BLOCK_RE = re.compile(
    r"^- \*\*Status\*\*:\s*`\[([ x~])\]`", re.MULTILINE
)
TASK_STATUS_INLINE_RE = re.compile(
    r"^- \[([ x~])\]\s+\*\*T-\d", re.MULTILINE
)
# Statuses that may legitimately still contain OPEN QUESTION blocks. The spec
# workflow expects `/clarify` to resolve OQs before the spec advances to
# `clarified`+.
PRE_CLARIFY_STATUSES = {"draft"}
# Statuses at which tasks.md is legitimately not yet filled (it is written by
# /tasks, which bumps the status to `in-progress`), so requirement-coverage
# cannot be demanded before then. Gitorio's commands bump the status at every
# stage (draft → clarified → planned → in-progress → shipped), which the
# law-ai original didn't model — without this set the validator could never
# pass between /clarify and /tasks.
PRE_TASKS_STATUSES = {"draft", "clarified", "planned"}
# Statuses that assert "all task work is complete". Validator rejects these
# when tasks.md still contains any `[ ]` or `[~]` task. Conversely, leaving
# unchecked tasks while declaring a not-shipped status is fine — that's the
# normal in-flight case.
SHIPPED_STATUSES = {"shipped"}

# Literal substrings that only ever appear in specs/_template/ files. If any of
# these survive into a real spec dir, the implementer copied the template and
# never replaced the placeholder. Keep this list narrow (high-signal,
# zero-false-positive) — generic strings like "TODO" or "…" are intentionally
# excluded because they appear in legitimate spec prose.
TEMPLATE_MARKERS = (
    "{Feature Name}",
    "{Short imperative title}",
    "# Plan: {",
    "# Tasks: {",
    "# Spec: {",
)


def _iter_spec_dirs(targets: list[str], bad_targets: list[str]) -> Iterable[Path]:
    if targets:
        for t in targets:
            p = (REPO_ROOT / t).resolve()
            if p.is_dir():
                yield p
            else:
                # A typo'd explicit target must fail loudly, not skip silently.
                bad_targets.append(t)
        return
    if not SPECS_DIR.is_dir():
        return
    for child in sorted(SPECS_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        if SPEC_DIR_RE.match(child.name):
            yield child
        else:
            # A misnamed spec dir would otherwise get zero validation.
            bad_targets.append(
                f"{_rel(child)} (directory name must match NNN-kebab-slug)"
            )


def _extract_ids(text: str) -> set[str]:
    return set(ID_RE.findall(text))


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def validate_spec(spec_dir: Path) -> list[str]:
    errors: list[str] = []
    spec = spec_dir / "spec.md"
    plan = spec_dir / "plan.md"
    tasks = spec_dir / "tasks.md"

    for required in (spec, plan, tasks):
        if not required.is_file():
            errors.append(f"missing {_rel(required)}")
    if errors:
        return errors

    spec_text = spec.read_text(encoding="utf-8")
    tasks_text = tasks.read_text(encoding="utf-8")

    status_match = STATUS_RE.search(spec_text)
    status = status_match.group(1).lower() if status_match else ""
    is_pre_clarify = status in PRE_CLARIFY_STATUSES

    open_qs = OPEN_Q_RE.findall(spec_text)
    if open_qs and not is_pre_clarify:
        errors.append(
            f"{_rel(spec)}: {len(open_qs)} unresolved OPEN QUESTION block(s) "
            f"(status='{status}'; resolve via /clarify or downgrade status to 'draft')"
        )

    spec_ids = _extract_ids(spec_text)
    task_ids = _extract_ids(tasks_text)

    missing = sorted(spec_ids - task_ids)
    if missing and status not in PRE_TASKS_STATUSES:
        errors.append(
            f"{_rel(tasks)}: requirement(s) not referenced by any task: "
            + ", ".join(missing)
        )

    if "## Follow-ups Discovered" not in tasks_text:
        errors.append(
            f"{_rel(tasks)}: missing required section '## Follow-ups Discovered' "
            "(use '_none_' if there are truly no follow-ups)"
        )

    # Status ↔ task-state consistency: a spec marked `shipped` must have every
    # task ticked off, and all-tasks-done must bump the status.
    task_marks = TASK_STATUS_BLOCK_RE.findall(tasks_text)
    task_marks += TASK_STATUS_INLINE_RE.findall(tasks_text)
    unfinished = [m for m in task_marks if m != "x"]
    if status in SHIPPED_STATUSES and unfinished:
        errors.append(
            f"{_rel(spec)}: status='shipped' but "
            f"{len(unfinished)} task(s) in tasks.md are not marked `[x]` — "
            "either finish the tasks or downgrade the status to 'in-progress'."
        )
    # Symmetric check: every task `[x]` but status still pre-shipped means
    # the bump was forgotten. Only enforced when at least one task exists so
    # an empty/skeleton tasks.md (e.g. fresh /tasks output) does not trip it.
    if (
        task_marks
        and not unfinished
        and status not in SHIPPED_STATUSES
        and status != ""
    ):
        errors.append(
            f"{_rel(spec)}: all {len(task_marks)} task(s) in tasks.md are "
            f"marked `[x]` but status='{status}' — bump status to 'shipped' "
            "or mark the open follow-up tasks accordingly."
        )

    # Leftover-template-placeholder check: catches the "I copied _template/
    # and forgot to fill it in" failure mode. A file that is still BYTE-
    # IDENTICAL to its _template/ counterpart is exempt — that is the
    # documented intermediate state of the /specify → /clarify → /plan chain
    # (plan.md and tasks.md are untouched copies until their stage runs), and
    # without the exemption the PostToolUse hook would block the very first
    # spec.md write. A file that was MODIFIED but still carries a placeholder
    # is always an error.
    template_dir = SPECS_DIR / "_template"
    for path in (spec, plan, tasks):
        text = path.read_text(encoding="utf-8")
        tpl = template_dir / path.name
        if tpl.is_file() and text == tpl.read_text(encoding="utf-8"):
            continue
        for marker in TEMPLATE_MARKERS:
            if marker in text:
                errors.append(
                    f"{_rel(path)}: leftover template placeholder "
                    f"{marker!r} — replace with concrete content from specs/_template/"
                )

    return errors


def main(argv: list[str]) -> int:
    bad_targets: list[str] = []
    spec_dirs = list(_iter_spec_dirs(argv[1:], bad_targets))
    for bad in bad_targets:
        print(f"FAIL {bad}: not a valid spec directory")
    if not spec_dirs:
        if bad_targets:
            return 1
        print("spec_validator: no specs to validate (this is fine)")
        return 0

    failed = len(bad_targets)
    for d in spec_dirs:
        errs = validate_spec(d)
        rel = _rel(d)
        if errs:
            failed += 1
            print(f"FAIL {rel}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"PASS {rel}")

    if failed:
        print(f"\n{failed} spec(s) failed validation")
        return 1
    print(f"\nAll {len(spec_dirs)} spec(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

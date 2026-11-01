#!/usr/bin/env python3
"""
File: tools/jev/classify.py
Description: JEV's DETERMINISTIC conflict classifier — the part that decides
             which tier a conflicted pull request belongs to, from the trial
             merge alone and with no model in the loop. Given the conflicted
             files, their hunk and line counts and what kind of file each one
             is, it returns exactly one tier and the reason for it, so the same
             pull request always triages the same way and a tier escalation is
             explainable without a transcript.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage: imported by tools/jev/conflicts.py; `python3 -m tools.jev conflicts triage`
       prints what it produces.
Dependencies: stdlib only.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# file kinds
#
# The kind is what decides a tier, so each one is a CLAIM about how the file
# may be resolved, not a description of where it lives:
#
#   generated  nobody hand-merges it: throw both sides away and regenerate.
#   fragment   one entry per file by construction, so a conflict in one means
#              the same slug was written twice — a numbering question, not a
#              content one.
#   union      an append-only list where order carries no meaning, so both
#              sides are the answer.
#   append     an ordered list of entries (a YAML list) that branches only ever
#              add to, at its end: resolvable ONLY when every conflict is two
#              pure insertions at the same place, nothing deleted or changed on
#              either side. Tier 0 checks that against the merge stages, and
#              that the result still parses with unique ids; anything else is
#              treated as source.
#   lockfile   the fleet commits none (docs/DEPENDENCIES.md); one in a conflict
#              is a policy problem a human owns.
#   workflow   a semantic conflict here changes what runs with which token.
#   secret     the same, one step worse.
#   migration  ordering is state, and the state has already been applied
#              somewhere.
#   binary     there are no hunks to reason about.
#   source     everything else.
# --------------------------------------------------------------------------- #
GENERATED = "generated"
FRAGMENT = "fragment"
UNION = "union"
APPEND = "append"
LOCKFILE = "lockfile"
WORKFLOW = "workflow"
SECRET = "secret"
MIGRATION = "migration"
BINARY = "binary"
SOURCE = "source"

#: Kinds tier 0 can finish on its own.
DETERMINISTIC_KINDS = frozenset({GENERATED, FRAGMENT, UNION, APPEND})
#: Kinds no model is allowed to touch, whatever the size of the diff.
HUMAN_ONLY_KINDS = frozenset({LOCKFILE, BINARY})
#: Kinds a cheap model is not allowed to touch (tier 1's exclusion list).
TIER1_FORBIDDEN_KINDS = frozenset({WORKFLOW, SECRET, MIGRATION, LOCKFILE, BINARY})

LOCKFILE_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "Gemfile.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "Cargo.lock",
    "composer.lock", "go.sum", "flake.lock",
})
SECRET_GLOBS = (
    ".env", ".env.*", "*/.env", "*/.env.*",
    "*secrets*", "*/secrets/*", "*credential*", "*token*",
    ".github/workflows/token-rotation.yml", ".github/workflows/api-keys.yml",
)
MIGRATION_GLOBS = ("*/migrations/*", "migrations/*", "db/migrate/*", "*/db/migrate/*",
                   "*/alembic/versions/*", "alembic/versions/*")
#: Paths whose generated nature is a hub fact rather than a `.gitattributes`
#: line, so a clone with no attributes file still classifies them correctly.
DEFAULT_GENERATED_GLOBS = (
    "CATALOG.md", "_data/specs.yml", "_data/cv_portfolio.json",
    "_data/features_index.yml", "_data/deep_dive.json", "projects/SCHEMA.md",
    "docs/README.md", "_site/*", "site/*",
)
DEFAULT_FRAGMENT_GLOBS = ("features/features.d/*", "changelog.d/*", "docs/amendments/proposed/*")
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".woff", ".woff2", ".ttf", ".otf", ".so", ".dylib", ".wasm", ".sqlite", ".db",
)

TIER0, TIER1, TIER2, TIER3 = "tier0", "tier1", "tier2", "tier3"


def _matches(path: str, globs) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def kind_of(path: str, *, generated: tuple | list = (), fragments: tuple | list = (),
            union: tuple | list = (), append: tuple | list = (), binary: bool = False) -> str:
    """The one kind a conflicted path has, most-restrictive rule first.

    Order matters: a lockfile under `.github/workflows/` is still a lockfile,
    and a generated file that is also a fragment directory entry would be a
    contradiction — so the dangerous kinds are tested before the easy ones and
    the easy ones never override them.
    """
    name = path.rsplit("/", 1)[-1]
    if binary or path.lower().endswith(BINARY_SUFFIXES):
        return BINARY
    if name in LOCKFILE_NAMES:
        return LOCKFILE
    if _matches(path, SECRET_GLOBS):
        return SECRET
    if path.startswith(".github/workflows/"):
        return WORKFLOW
    if _matches(path, MIGRATION_GLOBS):
        return MIGRATION
    if _matches(path, tuple(fragments) or DEFAULT_FRAGMENT_GLOBS):
        return FRAGMENT
    if _matches(path, tuple(union)):
        return UNION
    if _matches(path, tuple(append)):
        return APPEND
    if _matches(path, tuple(generated) + DEFAULT_GENERATED_GLOBS):
        return GENERATED
    return SOURCE


@dataclass
class ConflictFile:
    """One conflicted path and the shape of its conflict."""

    path: str
    hunks: int = 0
    lines: int = 0
    kind: str = SOURCE

    @property
    def deterministic(self) -> bool:
        return self.kind in DETERMINISTIC_KINDS


@dataclass
class Triage:
    """The classifier's verdict: one tier, the reason, and the counts behind it."""

    tier: str
    reason: str
    files: list[ConflictFile] = field(default_factory=list)
    attempts: int = 0
    id_collision: bool = False

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def line_count(self) -> int:
        return sum(f.lines for f in self.files)

    @property
    def hunk_count(self) -> int:
        return sum(f.hunks for f in self.files)

    @property
    def kinds(self) -> set[str]:
        return {f.kind for f in self.files}

    def report(self) -> str:
        """The triage report JEV posts on a pull request it hands to a human."""
        rows = "\n".join(
            f"| `{f.path}` | {f.kind} | {f.hunks} | {f.lines} |"
            for f in sorted(self.files, key=lambda x: x.path))
        return (
            f"**Tier:** `{self.tier}` — {self.reason}\n\n"
            f"**Totals:** {self.file_count} file(s), {self.hunk_count} hunk(s), "
            f"{self.line_count} conflicted line(s), {self.attempts} prior attempt(s)"
            f"{'; id collision' if self.id_collision else ''}\n\n"
            "| File | Kind | Hunks | Conflicted lines |\n| --- | --- | --- | --- |\n"
            f"{rows}\n")


# --------------------------------------------------------------------------- #
# parsing a trial merge
# --------------------------------------------------------------------------- #
CONFLICT_MARKER = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.M)
_START, _MID, _END = "<" * 7, "=" * 7, ">" * 7


def count_conflict_hunks(text: str) -> tuple[int, int]:
    """(hunks, conflicted lines) in a file git left conflict markers in.

    Conflicted lines are the lines BETWEEN the markers — both sides — because
    that is the quantity a resolver actually has to read, and it is the one a
    tier threshold should be expressed in. The markers themselves are not
    counted: three of them per hunk would make every one-line conflict look
    like a four-line one.
    """
    hunks = conflicted = 0
    inside = False
    for line in text.splitlines():
        if line.startswith(_START):
            hunks += 1
            inside = True
        elif line.startswith(_END):
            inside = False
        elif line.startswith(_MID):
            continue
        elif inside:
            conflicted += 1
    return hunks, conflicted


def has_conflict_markers(text: str) -> bool:
    return bool(CONFLICT_MARKER.search(text))


# --------------------------------------------------------------------------- #
# the tier ladder
# --------------------------------------------------------------------------- #
def classify(files: list[ConflictFile], *, attempts: int = 0, id_collision: bool = False,
             squash_only: bool = False, budget_exhausted: bool = False,
             max_attempts: int = 2, tier1_max_files: int = 3, tier1_max_lines: int = 40,
             tier2_max_files: int = 15, tier2_max_lines: int = 400,
             force_min_tier: str | None = None) -> Triage:
    """Pick the tier. Deterministic, total, and ordered cheapest-last.

    The blocking rules are evaluated FIRST and unconditionally: a lockfile,
    a binary, a repo that can only squash-merge, a second failed attempt or an
    exhausted monthly budget sends the pull request to a human no matter how
    small the diff looks. Only then does size decide between tier 0, 1 and 2 —
    otherwise a one-line conflict in `package-lock.json` would look like the
    cheapest work on the board.
    """
    def verdict(tier: str, reason: str) -> Triage:
        return Triage(tier=tier, reason=reason, files=files, attempts=attempts,
                      id_collision=id_collision)

    if not files:
        return verdict(TIER0, "no conflicted files in the trial merge")

    blocking = sorted({f.kind for f in files} & HUMAN_ONLY_KINDS)
    if blocking:
        return verdict(TIER3, f"a human owns this file kind: {', '.join(blocking)}")
    if squash_only:
        return verdict(TIER3, "the repository allows squash merges only, so a merge "
                              "commit from JEV would be discarded")
    if attempts >= max_attempts:
        return verdict(TIER3, f"{attempts} resolution attempt(s) already failed")
    if budget_exhausted:
        return verdict(TIER3, "the monthly JEV budget is exhausted")

    deterministic = all(f.deterministic for f in files) or (
        id_collision and all(f.deterministic or f.kind == FRAGMENT for f in files))
    order = [TIER0, TIER1, TIER2, TIER3]
    floor = order.index(force_min_tier) if force_min_tier in order else 0

    if deterministic and floor <= order.index(TIER0):
        what = ", ".join(sorted({f.kind for f in files}))
        return verdict(TIER0, f"every conflicted file is resolvable without a model ({what})")

    n, lines = len(files), sum(f.lines for f in files)
    forbidden = sorted({f.kind for f in files} & TIER1_FORBIDDEN_KINDS)
    if (floor <= order.index(TIER1) and not forbidden
            and n <= tier1_max_files and lines <= tier1_max_lines):
        return verdict(TIER1, f"{n} file(s) and {lines} conflicted line(s) are inside the "
                              f"cheap-model envelope ({tier1_max_files} files / "
                              f"{tier1_max_lines} lines)")
    if floor <= order.index(TIER2) and (n <= tier2_max_files or lines <= tier2_max_lines):
        why = "tier 1 was ruled out" if floor > order.index(TIER1) or forbidden else "too large for tier 1"
        detail = f" ({', '.join(forbidden)} present)" if forbidden else ""
        return verdict(TIER2, f"{why}{detail}; {n} file(s) / {lines} line(s) fit the strong-model "
                              f"envelope ({tier2_max_files} files or {tier2_max_lines} lines)")
    return verdict(TIER3, f"{n} file(s) and {lines} conflicted line(s) exceed every automated envelope")

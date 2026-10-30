#!/usr/bin/env python3
"""
Fixture tests for tools/jev/classify.py — JEV's deterministic conflict
classifier. No network, no gh, no model: the whole point of this module is
that the tier is a function of the trial merge, so the tests are too.

Run: python3 tools/test_jev_classify.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.jev import classify as c  # noqa: E402


def f(path: str, kind: str | None = None, hunks: int = 1, lines: int = 4) -> c.ConflictFile:
    return c.ConflictFile(path=path, hunks=hunks, lines=lines, kind=kind or c.kind_of(path))


# --------------------------------------------------------------------------- #
# file kinds
# --------------------------------------------------------------------------- #
def test_kind_of_puts_the_dangerous_rules_first():
    # a lockfile is a lockfile wherever it lives, and a workflow outranks the
    # generated/fragment globs that might otherwise match it
    assert c.kind_of("Gemfile.lock") == c.LOCKFILE
    assert c.kind_of("web/package-lock.json") == c.LOCKFILE
    assert c.kind_of(".github/workflows/drift-check.yml") == c.WORKFLOW
    assert c.kind_of(".github/workflows/token-rotation.yml") == c.SECRET
    assert c.kind_of(".env.example") == c.SECRET
    assert c.kind_of("db/migrate/20260101_add.rb") == c.MIGRATION
    assert c.kind_of("app/assets/logo.png") == c.BINARY
    assert c.kind_of("tools/dash") == c.SOURCE


def test_kind_of_reads_the_fragment_generated_and_union_globs():
    assert c.kind_of("features/features.d/thing.yml") == c.FRAGMENT
    assert c.kind_of("changelog.d/thing.md") == c.FRAGMENT
    assert c.kind_of("docs/amendments/proposed/thing.md") == c.FRAGMENT
    assert c.kind_of("CATALOG.md") == c.GENERATED
    assert c.kind_of("_data/x.yml", generated=["_data/x.yml"]) == c.GENERATED
    assert c.kind_of("_data/ledger.yml", union=["_data/ledger.yml"]) == c.UNION
    # an explicitly binary blob beats every path rule
    assert c.kind_of("tools/dash", binary=True) == c.BINARY


def test_conflict_hunks_count_both_sides_but_not_the_markers():
    text = (
        "intro\n"
        "<<<<<<< HEAD\n"
        "ours one\n"
        "ours two\n"
        "=======\n"
        "theirs one\n"
        ">>>>>>> origin/main\n"
        "tail\n"
        "<<<<<<< HEAD\n"
        "a\n"
        "=======\n"
        "b\n"
        ">>>>>>> origin/main\n")
    assert c.count_conflict_hunks(text) == (2, 5)
    assert c.has_conflict_markers(text)
    assert not c.has_conflict_markers("plain\nfile\n")
    assert c.count_conflict_hunks("plain\n") == (0, 0)


# --------------------------------------------------------------------------- #
# the tier ladder
# --------------------------------------------------------------------------- #
def test_tier0_takes_everything_a_generator_or_a_union_can_settle():
    t = c.classify([f("CATALOG.md"), f("features/features.d/x.yml"),
                    f("_data/ledger.yml", c.UNION)])
    assert t.tier == c.TIER0, t.reason
    assert "without a model" in t.reason


def test_tier1_is_the_small_source_conflict():
    t = c.classify([f("tools/a.py", lines=10), f("tools/b.py", lines=20)])
    assert t.tier == c.TIER1
    assert t.file_count == 2 and t.line_count == 30


def test_tier1_refuses_workflows_secrets_and_migrations_however_small():
    for path in (".github/workflows/ci.yml", ".env.production", "db/migrate/1_x.rb"):
        t = c.classify([f(path, lines=2)])
        assert t.tier == c.TIER2, f"{path} -> {t.tier}: {t.reason}"
        assert c.kind_of(path) in t.reason


def test_tier2_takes_what_is_too_big_for_tier1():
    many = [f(f"src/mod{i}.py", lines=20) for i in range(8)]
    t = c.classify(many)
    assert t.tier == c.TIER2 and t.line_count == 160


def test_tier3_is_everything_larger_than_every_envelope():
    huge = [f(f"src/mod{i}.py", lines=60) for i in range(20)]
    t = c.classify(huge)
    assert t.tier == c.TIER3 and "exceed every automated envelope" in t.reason


def test_blocking_rules_beat_a_tiny_diff():
    # a one-line lockfile conflict is still a human's: the fleet commits no
    # lockfiles, so one in a conflict is a policy problem, not a merge problem
    assert c.classify([f("Gemfile.lock", lines=1)]).tier == c.TIER3
    assert c.classify([f("docs/logo.png", lines=0)]).tier == c.TIER3
    assert c.classify([f("tools/a.py", lines=1)], squash_only=True).tier == c.TIER3
    assert c.classify([f("tools/a.py", lines=1)], attempts=2).tier == c.TIER3
    assert c.classify([f("tools/a.py", lines=1)], budget_exhausted=True).tier == c.TIER3
    # …and a generated file does not escape them either
    assert c.classify([f("CATALOG.md"), f("Gemfile.lock")]).tier == c.TIER3


def test_a_failed_tier_can_force_the_next_one_up():
    files = [f("tools/a.py", lines=5)]
    assert c.classify(files).tier == c.TIER1
    assert c.classify(files, force_min_tier=c.TIER2).tier == c.TIER2


def test_thresholds_come_from_the_caller_not_from_the_module():
    files = [f("a.py", lines=10), f("b.py", lines=10)]
    assert c.classify(files, tier1_max_files=1).tier == c.TIER2
    assert c.classify(files, tier1_max_lines=5).tier == c.TIER2
    assert c.classify(files, tier1_max_files=9, tier1_max_lines=99).tier == c.TIER1


def test_no_conflicted_files_is_tier0_not_a_crash():
    t = c.classify([])
    assert t.tier == c.TIER0 and t.file_count == 0 and t.line_count == 0


def test_report_names_every_file_and_the_totals():
    t = c.classify([f("tools/a.py", lines=7, hunks=2)])
    report = t.report()
    assert "`tools/a.py`" in report and "tier1" in report
    assert "1 file(s), 2 hunk(s), 7 conflicted line(s)" in report


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

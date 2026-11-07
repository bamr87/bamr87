#!/usr/bin/env python3
"""
Fixture tests for tools/jev/number.py — the assign-at-merge numbering compiler.

Every test builds a throwaway repository in a temp directory, so nothing here
reads or writes the hub's own catalog, PRD or changelog.

Run: python3 tools/test_jev_number.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.jev import number as n  # noqa: E402

FEATURES = """\
# the catalog
schema: features/v1
repo: o/r
features:
  - id: HUB-001
    title: First
    description: the first one
    status: shipped
    prd: [FR1]
"""
PRD = """\
# PRD

## 5. Requirements

**Functional**

- FR1: does the first thing
- FR2: does the second thing

**Non-functional**

- NFR1: is fast

## 6. Success metrics
"""
CHANGELOG = """\
# Changelog

Keep exactly one `## [Unreleased]` heading.

## [Unreleased]

### Added

- an earlier entry

## [1.0.0] - 2026-01-01

### Added

- the first release
"""
AMEND_INDEX = """\
# Amendments

| # | Title | Status | Affects |
| --- | --- | --- | --- |
| [0001](0001-ratify-constitution.md) | Ratify the constitution | ratified on merge | whole constitution |
"""
AMEND_0001 = "# 0001 — Ratify\n\n- **Status:** ratified\n- **Date:** 2026-10-21\n"


def mk(extra: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    files = {
        "features/features.yml": FEATURES,
        "PRD.md": PRD,
        "CHANGELOG.md": CHANGELOG,
        "docs/amendments/README.md": AMEND_INDEX,
        "docs/amendments/0000-template.md": "# NNNN — Title\n",
        "docs/amendments/0001-ratify-constitution.md": AMEND_0001,
    }
    files.update(extra or {})
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


def features_of(repo: Path) -> list[dict]:
    return (yaml.safe_load((repo / "features/features.yml").read_text()) or {})["features"]


# --------------------------------------------------------------------------- #
# reading the next free number
# --------------------------------------------------------------------------- #
def test_next_ids_reads_every_series():
    d = mk()
    assert n.next_ids(d) == {"HUB": "HUB-002", "FR": "FR3", "NFR": "NFR2", "amendment": "0002",
                             "FF": "FF-0001"}


def test_a_retired_id_is_never_reused():
    # HUB-007 is gone from the catalog but still named in the PRD, so the next
    # free number is 008 — an id that has been published is spent
    d = mk({"PRD.md": PRD + "\nHUB-007 was removed in 2026.\n"})
    assert n.next_ids(d)["HUB"] == "HUB-008"


def test_the_generated_prd_block_does_not_inflate_the_requirement_counter():
    d = mk({"PRD.md": PRD + "\n<!-- features:start v1 -->\n| FR99 | HUB-001 |\n<!-- features:end -->\n"})
    assert n.next_ids(d)["FR"] == "FR3"


# --------------------------------------------------------------------------- #
# compiling feature fragments
# --------------------------------------------------------------------------- #
def test_a_feature_fragment_is_numbered_compiled_and_consumed():
    frag = yaml.safe_dump({
        "id": "HUB-NEW", "slug": "thing", "title": "A thing",
        "description": "does a thing", "status": "shipped",
        "prd": ["FR-NEW:thing"],
        "prd_new": [{"key": "thing", "kind": "FR", "text": "The product must do a thing"}],
    })
    d = mk({"features/features.d/thing.yml": frag})
    plan = n.apply(d)
    assert not plan.errors, plan.errors
    assert plan.assignments == {"HUB-NEW:thing": "HUB-002", "FR-NEW:thing": "FR3"}

    entries = features_of(d)
    assert [e["id"] for e in entries] == ["HUB-001", "HUB-002"]
    assert entries[1]["prd"] == ["FR3"] and "prd_new" not in entries[1] and "slug" not in entries[1]
    assert "- FR3: The product must do a thing" in (d / "PRD.md").read_text()
    assert not (d / "features/features.d/thing.yml").exists()
    # the catalog's comment header survives: the compiler appends text, it does
    # not round-trip the YAML
    assert (d / "features/features.yml").read_text().startswith("# the catalog")


def test_a_scenario_takes_its_features_number():
    """A scenario lands with its feature and cites it by slug. Nothing else
    rewrites that line, so `HUB-NEW:<slug>` used to stay in verify/scenarios/
    for good and the feature index reported an unknown feature."""
    frag = yaml.safe_dump({"id": "HUB-NEW", "slug": "thing", "title": "A thing", "description": "does a thing",
                           "status": "shipped", "scenarios": ["verify/scenarios/thing.yml"]})
    other = "id: other\nfeature: HUB-001\n"
    d = mk({"features/features.d/thing.yml": frag,
            "verify/scenarios/thing.yml": "id: thing\nfeature: HUB-NEW:thing\n",
            "verify/scenarios/other.yml": other})
    plan = n.apply(d)
    assert not plan.errors, plan.errors
    assert (d / "verify/scenarios/thing.yml").read_text() == "id: thing\nfeature: HUB-002\n"
    assert (d / "verify/scenarios/other.yml").read_text() == other, "a scenario with no slug is left alone"
    assert features_of(d)[1]["scenarios"] == ["verify/scenarios/thing.yml"]


def test_two_fragments_get_two_different_numbers_in_filename_order():
    one = yaml.safe_dump({"id": "HUB-NEW", "title": "A", "description": "a"})
    two = yaml.safe_dump({"id": "HUB-NEW", "title": "B", "description": "b"})
    d = mk({"features/features.d/alpha.yml": one, "features/features.d/beta.yml": two})
    plan = n.apply(d)
    assert plan.assignments == {"HUB-NEW:alpha": "HUB-002", "HUB-NEW:beta": "HUB-003"}
    assert [e["id"] for e in features_of(d)] == ["HUB-001", "HUB-002", "HUB-003"]


def test_a_fragment_that_picked_its_own_number_is_an_error():
    d = mk({"features/features.d/thing.yml": yaml.safe_dump(
        {"id": "HUB-042", "title": "A", "description": "a"})})
    plan = n.apply(d)
    assert plan.errors and "numbers are assigned here" in plan.errors[0]
    assert (d / "features/features.d/thing.yml").exists(), "a rejected fragment is not consumed"


def test_a_plan_changes_nothing():
    d = mk({"features/features.d/thing.yml": yaml.safe_dump(
        {"id": "HUB-NEW", "title": "A", "description": "a"})})
    before = (d / "features/features.yml").read_text()
    plan = n.apply(d, write=False)
    assert plan.assignments == {"HUB-NEW:thing": "HUB-002"}
    assert (d / "features/features.yml").read_text() == before
    assert (d / "features/features.d/thing.yml").exists()


def test_an_empty_tree_is_a_no_op_so_the_compiler_is_safe_on_every_push():
    d = mk()
    before = {p: p.read_text() for p in d.rglob("*.md")}
    plan = n.apply(d)
    assert plan.empty and not plan.errors and not plan.assignments
    assert {p: p.read_text() for p in d.rglob("*.md")} == before


# --------------------------------------------------------------------------- #
# amendments
# --------------------------------------------------------------------------- #
def test_an_amendment_fragment_is_numbered_moved_and_indexed():
    body = ("# NEW — Conflict-free numbering\n\n"
            "- **Status:** proposed\n- **Number:** NEW\n- **Date:** 2026-10-29\n"
            "- **Affects:** constitution §8; HUB-NEW:thing\n")
    d = mk({"docs/amendments/proposed/conflict-free-numbering.md": body,
            "features/features.d/thing.yml": yaml.safe_dump(
                {"id": "HUB-NEW", "title": "A", "description": "a"})})
    plan = n.apply(d)
    assert not plan.errors, plan.errors
    out = d / "docs/amendments/0002-conflict-free-numbering.md"
    assert out.exists() and not (d / "docs/amendments/proposed/conflict-free-numbering.md").exists()
    text = out.read_text()
    assert text.startswith("# 0002 — Conflict-free numbering")
    assert "- **Number:** 0002" in text
    assert "HUB-002" in text and "HUB-NEW" not in text, "slug references are rewritten"
    index = (d / "docs/amendments/README.md").read_text()
    assert "| [0002](0002-conflict-free-numbering.md) | Conflict-free numbering | proposed |" in index


def test_an_unresolved_slug_reference_is_reported_not_silently_dropped():
    body = "# NEW — X\n\n- **Status:** proposed\n- **Number:** NEW\n- **Affects:** FR-NEW:nobody\n"
    d = mk({"docs/amendments/proposed/x.md": body})
    plan = n.apply(d)
    assert plan.errors and "FR-NEW:nobody" in plan.errors[0]
    assert (d / "docs/amendments/proposed/x.md").exists()


def test_a_reference_to_a_key_an_earlier_run_compiled_says_to_use_its_id():
    # 45ede64: #527 compiled FR-NEW:central-loop-switches to FR54, then #528's
    # amendment still said FR-NEW:central-loop-switches and wedged every run
    body = ("# NEW — Switches\n\n- **Status:** proposed\n- **Number:** NEW\n"
            "- **Affects:** requirement `FR-NEW:central-loop-switches`\n")
    d = mk({"docs/amendments/proposed/central-loop-switches.md": body})
    plan = n.plan(d)
    assert len(plan.errors) == 1, plan.errors
    err = plan.errors[0]
    assert err.startswith("docs/amendments/proposed/central-loop-switches.md: unresolved reference(s) "
                          "FR-NEW:central-loop-switches")
    assert "already have been compiled in an earlier run" in err and "assigned id" in err
    assert n.apply(d).errors == plan.errors, "apply refuses on the plan's error and consumes nothing"
    assert (d / "docs/amendments/proposed/central-loop-switches.md").exists()
    fixed = body.replace("`FR-NEW:central-loop-switches`", "`FR2`")
    (d / "docs/amendments/proposed/central-loop-switches.md").write_text(fixed)
    assert not n.plan(d).errors


# --------------------------------------------------------------------------- #
# changelog
# --------------------------------------------------------------------------- #
def test_changelog_fragments_merge_into_one_unreleased_section_in_kac_order():
    d = mk({"changelog.d/a.md": "### Fixed\n\n- fixed a thing\n",
            "changelog.d/b.md": "### Added\n\n- added a thing\n"})
    n.apply(d)
    text = (d / "CHANGELOG.md").read_text()
    unreleased = text.split("\n## [Unreleased]\n")[1].split("\n## [1.0.0]")[0]
    assert unreleased.index("### Added") < unreleased.index("### Fixed")
    assert "- an earlier entry" in unreleased and "- added a thing" in unreleased
    assert "- fixed a thing" in unreleased
    assert text.count("\n## [Unreleased]\n") == 1
    assert "## [1.0.0] - 2026-01-01" in text and "- the first release" in text
    assert not (d / "changelog.d/a.md").exists()


# --------------------------------------------------------------------------- #
# the lint
# --------------------------------------------------------------------------- #
def test_lint_rejects_a_hand_picked_number_in_a_compiled_file():
    diff = ("+++ b/features/features.yml\n"
            "+  - id: HUB-033\n"
            "+++ b/PRD.md\n"
            "+- FR28: the product must do a thing\n"
            "--- /dev/null\n"
            "+++ b/docs/amendments/0002-thing.md\n"
            "+# 0002 — Thing\n")
    problems = n.lint_diff(diff)
    assert len(problems) == 3, problems
    assert any("features/features.d/<slug>.yml" in p for p in problems)
    assert any("prd_new" in p for p in problems)
    assert any("docs/amendments/proposed/<slug>.md" in p for p in problems)


def test_lint_leaves_fragments_and_prose_alone():
    diff = ("+++ b/features/features.d/thing.yml\n"
            "+id: HUB-NEW\n"
            "+prd: [FR-NEW:thing]\n"
            "+++ b/docs/JEV.md\n"
            "+HUB-001 is the portfolio feature, and FR1 is its requirement.\n"
            "+++ b/docs/amendments/proposed/thing.md\n"
            "+# NEW — Thing\n")
    assert n.lint_diff(diff) == []


def test_lint_flags_only_an_added_numbered_amendment_not_a_modified_one():
    # A ratification-record PR (tools/jev/ratify.py) MODIFIES a numbered
    # record's Status line; only a new numbered file is a hand-picked number.
    modified = ("diff --git a/docs/amendments/0002-thing.md b/docs/amendments/0002-thing.md\n"
                "--- a/docs/amendments/0002-thing.md\n"
                "+++ b/docs/amendments/0002-thing.md\n"
                "@@ -4 +4 @@\n"
                "-- **Status:** proposed\n"
                "+- **Status:** ratified\n")
    assert n.lint_diff(modified) == []
    added = ("diff --git a/docs/amendments/0003-other.md b/docs/amendments/0003-other.md\n"
             "new file mode 100644\n"
             "--- /dev/null\n"
             "+++ b/docs/amendments/0003-other.md\n"
             "@@ -0,0 +1 @@\n"
             "+# 0003 — Other\n")
    problems = n.lint_diff(modified + added)
    assert problems == ["docs/amendments/0003-other.md: a new amendment is proposed as "
                        "docs/amendments/proposed/<slug>.md; the number is assigned at merge"], problems


def test_rewrite_refs_leaves_an_unknown_slug_legible():
    text = "see HUB-NEW:known and HUB-NEW:unknown"
    out = n.rewrite_refs(text, {"HUB-NEW:known": "HUB-050"})
    assert out == "see HUB-050 and HUB-NEW:unknown"
    assert n.unresolved_refs(out) == ["HUB-NEW:unknown"]


# --------------------------------------------------------------------------- #
# roadmap entries (FF-NNNN)
# --------------------------------------------------------------------------- #
ROADMAP = """\
# the roadmap header (schema lives here)

- id: FF-0001
  title: First
  status: shipped

- id: FF-0021
  title: Before the gap
  status: approved

- id: FF-0024
  title: After the gap
  status: proposed
"""


def ff_frag(title: str, **extra) -> str:
    return yaml.safe_dump({"id": "FF-NEW", "title": title, "project": "bamr87", "status": "proposed",
                           "priority": "P2", **extra}, sort_keys=False)


def test_next_ff_is_one_past_the_highest_and_gaps_are_never_back_filled():
    d = mk({"_data/roadmap.yml": ROADMAP})
    assert n.next_ids(d)["FF"] == "FF-0025", "FF-0022/0023 are a gap, never reused"


def test_a_retired_ff_named_elsewhere_is_spent():
    d = mk({"_data/roadmap.yml": ROADMAP,
            "docs/amendments/0002-x.md": "# 0002 — X\n\n- **Affects:** FF-0030\n"})
    assert n.next_ids(d)["FF"] == "FF-0031"


def test_a_roadmap_fragment_is_numbered_appended_and_consumed():
    d = mk({"_data/roadmap.yml": ROADMAP, "_data/roadmap.d/thing.yml": ff_frag("A thing")})
    plan = n.apply(d)
    assert not plan.errors, plan.errors
    assert plan.assignments == {"FF-NEW:thing": "FF-0025"}
    text = (d / "_data/roadmap.yml").read_text()
    assert text.startswith("# the roadmap header"), "the header survives: appended as text"
    rows = yaml.safe_load(text)
    assert [r["id"] for r in rows] == ["FF-0001", "FF-0021", "FF-0024", "FF-0025"]
    assert rows[-1]["title"] == "A thing" and "slug" not in rows[-1]
    assert list(rows[-1])[0] == "id"
    assert not (d / "_data/roadmap.d/thing.yml").exists()


def test_two_roadmap_fragments_number_in_filename_order():
    d = mk({"_data/roadmap.yml": ROADMAP, "_data/roadmap.d/beta.yml": ff_frag("B"),
            "_data/roadmap.d/alpha.yml": ff_frag("A")})
    plan = n.apply(d)
    assert plan.assignments == {"FF-NEW:alpha": "FF-0025", "FF-NEW:beta": "FF-0026"}


def test_a_roadmap_fragment_that_picked_its_own_number_is_an_error():
    d = mk({"_data/roadmap.yml": ROADMAP,
            "_data/roadmap.d/thing.yml": ff_frag("A").replace("FF-NEW", "FF-0040")})
    plan = n.apply(d)
    assert plan.errors and "FF-NEW" in plan.errors[0]
    assert (d / "_data/roadmap.d/thing.yml").exists()
    assert "FF-0040" not in (d / "_data/roadmap.yml").read_text()


def test_ff_slug_references_resolve_across_fragments():
    amend = ("# NEW — X\n\n- **Status:** proposed\n- **Number:** NEW\n"
             "- **Affects:** FF-NEW:thing; HUB-NEW:feat\n")
    feat = yaml.safe_dump({"id": "HUB-NEW", "title": "F", "description": "roadmap FF-NEW:thing"})
    d = mk({"_data/roadmap.yml": ROADMAP, "_data/roadmap.d/thing.yml": ff_frag("A"),
            "features/features.d/feat.yml": feat, "docs/amendments/proposed/x.md": amend})
    plan = n.apply(d)
    assert not plan.errors, plan.errors
    rec = (d / "docs/amendments/0002-x.md").read_text()
    assert "FF-0025" in rec and "FF-NEW" not in rec
    assert features_of(d)[-1]["description"] == "roadmap FF-0025"


def test_an_unresolved_ff_reference_is_an_error():
    amend = "# NEW — X\n\n- **Status:** proposed\n- **Number:** NEW\n- **Affects:** FF-NEW:nobody\n"
    d = mk({"docs/amendments/proposed/x.md": amend})
    plan = n.plan(d)
    assert plan.errors and "FF-NEW:nobody" in plan.errors[0]


def test_a_roadmap_plan_changes_nothing():
    d = mk({"_data/roadmap.yml": ROADMAP, "_data/roadmap.d/thing.yml": ff_frag("A")})
    plan = n.apply(d, write=False)
    assert plan.assignments == {"FF-NEW:thing": "FF-0025"} and not plan.empty
    assert (d / "_data/roadmap.yml").read_text() == ROADMAP


def test_lint_rejects_a_hand_picked_ff_in_the_roadmap():
    diff = ("--- a/_data/roadmap.yml\n+++ b/_data/roadmap.yml\n"
            "+- id: FF-0040\n"
            "+  title: hand-picked\n")
    problems = n.lint_diff(diff)
    assert len(problems) == 1 and "_data/roadmap.d/<slug>.yml" in problems[0], problems


def test_lint_leaves_roadmap_fragments_and_status_edits_alone():
    diff = ("--- /dev/null\n+++ b/_data/roadmap.d/thing.yml\n+id: FF-NEW\n"
            "--- a/_data/roadmap.yml\n+++ b/_data/roadmap.yml\n+  status: shipped\n"
            "+  issue_url: https://github.com/o/r/issues/1\n"
            "+++ b/docs/x.md\n+FF-0039 is cited in prose.\n")
    assert n.lint_diff(diff) == []


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

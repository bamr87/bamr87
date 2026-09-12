#!/usr/bin/env python3
"""
test_triage_engine.py — engine-level tests for the canonical Issue Autopilot.

Run: python3 scripts/issues/test_triage_engine.py   (no pytest needed; exits non-zero on failure)

Two things are under test, and the second is the one that matters:

  1. The verify-and-close feature flag. `features.verify_close` is the switch on
     the ONLY path by which the autopilot ever closes a HUMAN-authored issue, so
     it is tested for both directions and for typo-safety.

  2. BEHAVIOUR PARITY WITH THE FORKS THIS KIT REPLACES. The two pre-kit engines
     are archived verbatim beside this file (`archive/triage-0.0.0-*.py`). Each
     parity test runs the archived fork engine and the canonical engine over the
     SAME issue fixtures with that repo's real disposition rules and asserts the
     resulting plans are equal. That is what "adoption is a no-op" means, checked
     rather than asserted in a PR body:

       * lane OFF  -> canonical == the it-journey fork
       * lane ON   -> canonical == the zer0-mistakes fork

     Delete an archived engine and these tests stop being able to prove anything,
     so the archive is load-bearing for the tests as well as for `--upgrade`.

These tests are pure functions over fixtures: no network, no `gh`, no filesystem
beyond importing the engines.
"""
# kit: issue-autopilot v__KIT_VERSION__
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

PASSED = 0


def check(name: str, cond: bool) -> None:
    global PASSED
    if not cond:
        print(f"FAIL: {name}")
        raise SystemExit(1)
    PASSED += 1
    print(f"ok: {name}")


def load_engine(path: Path, name: str) -> Any:
    """Import a triage engine from an explicit path (archived copies have dashes)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - import guard
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


engine = load_engine(HERE / "triage.py", "kit_triage")

FORK_ITJ = HERE / "archive" / "triage-0.0.0-it-journey.py"
FORK_Z0 = HERE / "archive" / "triage-0.0.0-zer0-mistakes.py"


# --------------------------------------------------------------------------- #
# Fixtures — issues shaped like `gh issue list --json ...` output
# --------------------------------------------------------------------------- #
def issue(number: int, title: str, *, bot: bool = False, labels: list[str] | None = None,
          body: str = "") -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": n} for n in (labels or [])],
        "author": {"login": "app/github-actions" if bot else "someone", "is_bot": bot},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
    }


ISSUES = [
    issue(1, "🤖 AI Content Review: pages/x.md", bot=True, labels=["ai-review", "automated"]),
    issue(2, "Epic Quest: learn shell", labels=["enhancement", "epic"]),
    issue(3, "Typo in the docs", labels=["documentation"]),
    issue(4, "Buttons are the wrong colour", labels=["bug"]),
    issue(5, "Backlog task", labels=["agent-ready"], body="<!-- backlog-id: T-001 -->\nmirrored"),
    issue(6, "Something ambiguous"),
]

# The two repos' real disposition rules, trimmed to what the engine reads.
CONFIG_ITJ: dict[str, Any] = {
    "repo": "owner/repo",
    "limits": {"max_issues_per_run": 40},
    "dispositions": [
        {"id": "close-stale", "match": {"author_is_bot": True, "any_label": ["ai-review"],
                                        "title_regex": r"^(\s*🤖\s*)?AI Content Review"},
         "action": "recommend-close"},
        {"id": "epic", "match": {"any_label": ["enhancement", "epic"],
                                 "title_regex": r"(Epic Quest|⚔️|\bepic\b)"},
         "action": "decompose"},
        {"id": "content", "match": {"any_label": ["documentation"]}, "action": "resolve-content"},
        {"id": "bug", "match": {"any_label": ["bug"]}, "action": "resolve-code"},
    ],
    "default_disposition": {"id": "needs-human", "action": "route-human"},
    "areas": {"collections": ["quests", "docs", "notes"]},
    "labels": {"pr": "auto:issue", "triaged": "autopilot:triaged", "stale": "autopilot:stale",
               "epic": "autopilot:epic", "needs_human": "needs-human"},
}

CONFIG_Z0: dict[str, Any] = {
    "repo": "owner/repo",
    "limits": {"max_issues_per_run": 50},
    "dispositions": [
        {"id": "backlog-managed",
         "match": {"any_of": [{"body_regex": r"<!--\s*backlog-id:"},
                              {"any_label": ["agent-ready"]}]},
         "action": "skip"},
        {"id": "close-stale", "match": {"author_is_bot": True, "any_label": ["automated"],
                                        "title_regex": r"(AI Content Review|automated report|🤖)"},
         "action": "recommend-close"},
        {"id": "epic", "match": {"any_label": ["enhancement", "epic"],
                                 "title_regex": r"(Epic|⚔️|\bepic\b|tracking)"},
         "action": "decompose"},
        {"id": "content", "match": {"any_label": ["documentation", "area:docs"]},
         "action": "resolve-content"},
    ],
    "default_disposition": {"id": "needs-human", "action": "route-human"},
    "areas": {"collections": ["docs", "posts", "notes"]},
    "labels": {"pr": "auto:issue", "triaged": "autopilot:triaged", "stale": "autopilot:stale",
               "epic": "autopilot:epic", "needs_human": "autopilot:needs-human"},
}


FIXED_TIMESTAMP = "2026-01-03T00:00:00Z"


def plan_of(mod: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Build a plan, pinning the one non-deterministic field so plans compare."""
    plan = mod.build_plan(ISSUES, config, str(config.get("repo") or ""))
    plan["generated"] = FIXED_TIMESTAMP
    return plan


# --------------------------------------------------------------------------- #
# 1. The feature flag
# --------------------------------------------------------------------------- #
def test_flag_default_off() -> None:
    check("no features block -> lane off", engine.verify_close_enabled(CONFIG_ITJ) is False)
    check("empty features block -> lane off", engine.verify_close_enabled({"features": {}}) is False)
    check("features: null -> lane off", engine.verify_close_enabled({"features": None}) is False)


def test_flag_is_boolean_true_only() -> None:
    # A truthy string on an issue-CLOSING switch is a typo, not consent.
    for value in ("true", "yes", 1, "on"):
        check(f"features.verify_close={value!r} does NOT enable the lane",
              engine.verify_close_enabled({"features": {"verify_close": value}}) is False)
    check("features.verify_close=true enables the lane",
          engine.verify_close_enabled({"features": {"verify_close": True}}) is True)


def test_lane_off_emits_no_trace() -> None:
    plan = plan_of(engine, CONFIG_ITJ)
    check("lane off -> no verify_candidate key on any record",
          all("verify_candidate" not in r for r in plan["issues"]))
    check("lane off -> no verify_candidates count",
          "verify_candidates" not in plan["counts"])


def test_lane_on_flags_the_right_issues() -> None:
    cfg = {**CONFIG_Z0, "features": {"verify_close": True}}
    plan = plan_of(engine, cfg)
    by_num = {r["number"]: r for r in plan["issues"]}
    check("lane on -> every record carries the key",
          all("verify_candidate" in r for r in plan["issues"]))
    check("a plain human issue is a candidate", by_num[4]["verify_candidate"] is True)
    check("a bot issue is never a candidate", by_num[1]["verify_candidate"] is False)
    check("an epic (decompose) is never a candidate", by_num[2]["verify_candidate"] is False)
    check("a protected (skip) issue is never a candidate", by_num[5]["verify_candidate"] is False)
    check("the count matches the flags",
          plan["counts"]["verify_candidates"]
          == sum(1 for r in plan["issues"] if r["verify_candidate"]))


def test_skip_generalizes_the_hardcoded_disposition_id() -> None:
    """
    The fork excluded `disposition_id != "backlog-managed"` — one repo's id baked
    into the shared engine. The kit excludes `action != "skip"` instead. Renaming
    the disposition must therefore keep it protected.
    """
    cfg = {**CONFIG_Z0, "features": {"verify_close": True}}
    renamed = {**cfg, "dispositions": [
        {**d, "id": "mirrored-from-backlog"} if d["id"] == "backlog-managed" else d
        for d in cfg["dispositions"]
    ]}
    plan = plan_of(engine, renamed)
    rec = next(r for r in plan["issues"] if r["number"] == 5)
    check("a RENAMED skip disposition is still never a verify candidate",
          rec["disposition_id"] == "mirrored-from-backlog" and rec["verify_candidate"] is False)


# --------------------------------------------------------------------------- #
# 2. Behaviour parity with the forks this kit replaces
# --------------------------------------------------------------------------- #
def test_parity_with_it_journey_fork() -> None:
    fork = load_engine(FORK_ITJ, "fork_itj_triage")
    check("lane OFF: canonical plan == it-journey fork plan, byte for byte",
          plan_of(engine, CONFIG_ITJ) == plan_of(fork, CONFIG_ITJ))


def test_parity_with_zer0_mistakes_fork() -> None:
    fork = load_engine(FORK_Z0, "fork_z0_triage")
    canonical = plan_of(engine, {**CONFIG_Z0, "features": {"verify_close": True}})
    check("lane ON: canonical plan == zer0-mistakes fork plan, byte for byte",
          canonical == plan_of(fork, CONFIG_Z0))


def test_worklist_parity() -> None:
    """The rendered Markdown is what a human and an agent actually read."""
    fork_itj = load_engine(FORK_ITJ, "fork_itj_triage_wl")
    fork_z0 = load_engine(FORK_Z0, "fork_z0_triage_wl")

    off = plan_of(engine, CONFIG_ITJ)
    check("lane OFF: worklist markdown matches the it-journey fork",
          engine.render_worklist_md(off) == fork_itj.render_worklist_md(plan_of(fork_itj, CONFIG_ITJ)))

    on = plan_of(engine, {**CONFIG_Z0, "features": {"verify_close": True}})
    check("lane ON: worklist markdown matches the zer0-mistakes fork",
          engine.render_worklist_md(on) == fork_z0.render_worklist_md(plan_of(fork_z0, CONFIG_Z0)))


# --------------------------------------------------------------------------- #
# 3. The two converged features that are unconditional (inert without config)
# --------------------------------------------------------------------------- #
def test_any_of_is_inert_without_config() -> None:
    """`any_of` was zer0-only; it is unconditional in the kit because a config
    that never uses the key can never trigger it."""
    check("a match with no any_of is unaffected",
          engine.match_disposition(ISSUES[3], {"any_label": ["bug"]}) is True)
    check("any_of matches when one branch matches",
          engine.match_disposition(ISSUES[4],
                                   {"any_of": [{"body_regex": r"<!--\s*backlog-id:"},
                                               {"any_label": ["nope"]}]}) is True)
    check("any_of fails when no branch matches",
          engine.match_disposition(ISSUES[3],
                                   {"any_of": [{"any_label": ["nope"]}]}) is False)


def test_skip_batch_is_inert_without_config() -> None:
    """The `skipped` batch was zer0-only; a config with no `action: skip`
    disposition produces no such batch."""
    itj = plan_of(engine, CONFIG_ITJ)
    check("no skip disposition -> no 'skipped' batch",
          not any(b["id"] == "skipped" for b in itj["batches"]))
    z0 = plan_of(engine, CONFIG_Z0)
    check("a skip disposition -> exactly one 'skipped' batch holding it",
          [b["issue_numbers"] for b in z0["batches"] if b["id"] == "skipped"] == [[5]])


if __name__ == "__main__":
    test_flag_default_off()
    test_flag_is_boolean_true_only()
    test_lane_off_emits_no_trace()
    test_lane_on_flags_the_right_issues()
    test_skip_generalizes_the_hardcoded_disposition_id()
    test_parity_with_it_journey_fork()
    test_parity_with_zer0_mistakes_fork()
    test_worklist_parity()
    test_any_of_is_inert_without_config()
    test_skip_batch_is_inert_without_config()
    print(f"\nAll {PASSED} triage-engine assertions passed.")

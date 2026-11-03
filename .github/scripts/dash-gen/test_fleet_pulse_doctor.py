#!/usr/bin/env python3
"""
Contract tests for the `doctor` half of .github/workflows/fleet-pulse.yml — the
agent that consumes remediation.py's queue.

remediation.py has fixture tests for the queue it BUILDS; nothing guarded the
budget the consumer is given to work through it, and the two are coupled by
arithmetic that lives in two files. On 2026-08-25 that gap cost a full day's
remediation and $11.71: the prompt instructs the agent to read
`gh run view --log-failed` (thousands of lines, unusable without a pipe) while
the allowlist granted no `grep`, `head` or `tail` — so 36 of 121 turns were
spent on DENIED tool calls and the run died on `error_max_turns`. Neither half
of that is visible to actionlint, which validates syntax, not whether a prompt
can be carried out with the tools it was handed.

Guarded here:

  * every shell command the doctor prompt requires is actually permitted, so a
    prompt edit that adds a command cannot silently become a denial loop;
  * `--max-turns` is large enough for the queue cap it is paired with, so
    raising `max_candidates` cannot silently under-fund the agent;
  * the queue cap in the workflow and the one declared in `_data/fleet.yml`
    agree — the workflow passes an explicit `--limit`, which shadows the
    registry value, so a lone edit to either one is a lie;
  * the prompt is read from the STEP SPEC (tools/jev/steps/fleet-pulse/
    doctor.prompt.txt, ADR 0002 P3), the one source CI and the local loop
    runner render from, and the workflow's inline copy is byte-equal to it —
    so the allowlist checks guard the text both runners actually use, and the
    model and turn literals are `_data/fleet.yml` remediation.model /
    remediation.max_turns.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_fleet_pulse_doctor.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "fleet-pulse.yml"
FLEET = REPO_ROOT / "_data" / "fleet.yml"
SPEC_DIR = REPO_ROOT / "tools" / "jev" / "steps" / "fleet-pulse"

# Commands the `Diagnose & fix` prompt cannot be carried out without. `gh`/`git`
# are the work itself; the filters exist because the prompt tells the agent to
# read a `--log-failed` dump, and a piped command is matched per-segment — the
# `Bash(gh:*)` prefix rule does NOT cover the right-hand side of a pipe.
REQUIRED_COMMANDS = ["gh", "git", "grep", "head", "tail", "cat", "ls", "mkdir", "cd"]

# Turns one candidate costs before any iteration, from the prompt's own steps:
# Step 2 is 2 reads (run log + workflow definition); Step 3b is clone, branch,
# read, edit, commit, push, `gh pr create` — 7 more. That is an 11-turn floor
# with zero margin for a wrong guess, and the run that exhausted its budget
# averaged ~24 turns/candidate.
#
# 30 was still under-modelled: run 34742995303 finished its 4-candidate queue
# SUCCESSFULLY in 185 turns — 46 each — and the action failed the job for
# crossing the 160 ceiling, discarding a completed pass. Diagnosis is not the
# whole cost; the reads that rule a wrong hypothesis OUT are, and a cross-repo
# candidate adds a clone and a push. 55 is the observed 46 plus that margin.
MIN_TURNS_PER_CANDIDATE = 55

CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


def doctor_claude_args(workflow: dict) -> str:
    """The `claude_args` string handed to claude-code-action by `Diagnose & fix`."""
    for step in workflow["jobs"]["doctor"]["steps"]:
        if step.get("name") == "Diagnose & fix":
            return step["with"]["claude_args"]
    raise AssertionError("fleet-pulse.yml: doctor job has no 'Diagnose & fix' step")


def doctor_prompt(workflow: dict) -> str:
    """The workflow's inline copy of the prompt (held byte-equal to the spec below)."""
    for step in workflow["jobs"]["doctor"]["steps"]:
        if step.get("name") == "Diagnose & fix":
            return step["with"]["prompt"]
    raise AssertionError("fleet-pulse.yml: doctor job has no 'Diagnose & fix' step")


def spec_prompt() -> str:
    """The rendered step spec — the prompt CI and the local loop runner both run.
    Rendered through tools.jev.spec (hub root appended, so this directory's
    modules keep precedence), exactly as the planners do."""
    import importlib
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    jev = importlib.import_module("tools.jev.spec")
    spec = jev.load_spec("fleet-pulse", "doctor")
    return jev.render_prompt(spec, {})


def workflow_candidate_cap(workflow: dict) -> int:
    """The cap `pulse` passes to `dash-gen remediate --limit` on a scheduled run."""
    for step in workflow["jobs"]["pulse"]["steps"]:
        if step.get("id") == "remediate":
            m = re.search(r"--limit\s+\"\$\{\{\s*inputs\.max_candidates\s*\|\|\s*'(\d+)'\s*\}\}\"",
                          step["run"])
            if not m:
                raise AssertionError(
                    "fleet-pulse.yml: could not read the `--limit` fallback from the "
                    "'Build remediation queue' step")
            return int(m.group(1))
    raise AssertionError("fleet-pulse.yml: pulse job has no step with id 'remediate'")


def main() -> int:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))

    args = doctor_claude_args(workflow)
    prompt = spec_prompt()
    inline = doctor_prompt(workflow)

    # --- the spec is the prompt ---------------------------------------------- #
    check("the workflow's inline prompt is byte-equal to tools/jev/steps/fleet-pulse/doctor.prompt.txt "
          "(the spec CI and the local runner render)", inline == prompt)
    check("doctor.prompt.txt ends in exactly one newline and carries no {{TOKEN}}",
          prompt.endswith("\n") and not prompt.endswith("\n\n") and "{{" not in prompt)

    # --- allowlist covers the prompt ---------------------------------------- #
    m = re.search(r'--allowedTools\s+"([^"]+)"', args)
    check("doctor claude_args declares --allowedTools", bool(m))
    allowed = {t.strip() for t in m.group(1).split(",")} if m else set()

    for cmd in REQUIRED_COMMANDS:
        check(f"allowlist permits `{cmd}` (the prompt needs it)",
              f"Bash({cmd}:*)" in allowed)

    for tool in ("Read", "Grep", "Glob", "Edit", "Write"):
        check(f"allowlist permits the {tool} tool", tool in allowed)

    # The prompt is what makes the filters mandatory; if the log read is ever
    # dropped, this test's REQUIRED_COMMANDS should be revisited rather than
    # quietly over-granting.
    check("prompt still instructs a `--log-failed` read (the reason filters are required)",
          "--log-failed" in prompt)

    # --- turn budget matches the queue cap ---------------------------------- #
    m = re.search(r"--max-turns\s+(\d+)", args)
    check("doctor claude_args declares --max-turns", bool(m))
    max_turns = int(m.group(1)) if m else 0
    rem = fleet["remediation"]
    check(f"--max-turns ({max_turns}) is the literal of _data/fleet.yml remediation.max_turns ({rem.get('max_turns')})",
          max_turns == rem.get("max_turns"))
    m_model = re.search(r"--model\s+(\S+)", args)
    allowed_ids = {str(x) for ids in (fleet.get("ai_models", {}).get("allowed") or {}).values() for x in ids or []}
    check(f"--model is the literal of remediation.model ({rem.get('model')}), an exact id in ai_models.allowed",
          bool(m_model) and m_model.group(1) == rem.get("model") and rem.get("model") in allowed_ids)

    cap = workflow_candidate_cap(workflow)
    needed = cap * MIN_TURNS_PER_CANDIDATE
    check(f"--max-turns ({max_turns}) funds {cap} candidate(s) at "
          f"{MIN_TURNS_PER_CANDIDATE} turns each (needs >= {needed})",
          max_turns >= needed)

    # --- the cap is stated once, consistently -------------------------------- #
    declared = fleet["remediation"]["max_candidates"]
    check(f"workflow --limit fallback ({cap}) matches "
          f"_data/fleet.yml remediation.max_candidates ({declared})",
          cap == declared)

    check("cross-repo sub-cap does not exceed the candidate cap",
          fleet["remediation"]["max_cross_repo"] <= declared)

    # --- report -------------------------------------------------------------- #
    failed = [label for label, ok in CHECKS if not ok]
    print()
    for label, ok in CHECKS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print()
    if failed:
        print(f"FAILED ({len(failed)}/{len(CHECKS)})")
        return 1
    print(f"OK ({len(CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

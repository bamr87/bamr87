#!/usr/bin/env python3
"""
Contract tests for the fleet's AI SPEND guardrails — the `--max-budget-usd`
ceiling on every headless agent invocation, and the ledger's `runs` section.

WHY THIS EXISTS
---------------
`--max-turns` bounds ITERATIONS, not spend, and the two are not the same
quantity: one turn against a large context can outspend thirty small ones. Six
scheduled Claude loops ran for months with a turn cap and no dollar cap at all
(bamr87#128). The cap now lives in _data/fleet.yml `budget.call_sites` — but a
`claude_args` string cannot read YAML, so the number is necessarily written
twice and the two copies WILL drift. That drift is invisible: nothing fails, the
fleet just runs under a ceiling nobody declared.

Guarded here:

  * every `anthropics/claude-code-action` step in .github/workflows/ passes
    `--max-budget-usd` — so a NEW loop cannot be added uncapped;
  * each literal equals the `budget.call_sites` entry for its
    `<workflow file>:<job id>`, in both directions (no stale entry either);
  * each cap clears `usd_per_turn * --max-turns`, so raising a turn budget
    cannot silently under-fund its dollar budget and turn every long run into a
    mid-task abort;
  * the ledger's `runs` section is ADDITIVE — a v1 ledger written before it
    existed keeps its history (LEDGER_VERSION is deliberately not bumped);
  * run records dedupe by `session_id`, so re-running the wrapper against one
    session records one row rather than two charges for one conversation;
  * headless spend is reported separately and never folded into the
    scan-derived interactive estimates, which see the SAME sessions;
  * a budget abort is detected from either tell the CLI gives.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_ai_budget.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_activity  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
FLEET = REPO_ROOT / "_data" / "fleet.yml"
DASH = REPO_ROOT / "tools" / "dash"

CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


# --------------------------------------------------------------------------- #
# workflow call sites
# --------------------------------------------------------------------------- #
def call_sites() -> dict[str, str]:
    """`<workflow file>:<job id>` -> that step's claude_args string.

    Keyed by job rather than by step name because a step name is prose and gets
    reworded; a job id is referenced by `needs:` and cannot move quietly.
    """
    found: dict[str, str] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "claude-code-action" not in text:
            continue
        workflow = yaml.safe_load(text)
        for job_id, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if "claude-code-action" in str(step.get("uses", "")):
                    found[f"{path.name}:{job_id}"] = str(
                        (step.get("with") or {}).get("claude_args") or ""
                    )
    return found


def declared_max_turns(args: str, fleet: dict) -> int | None:
    """The step's turn cap, resolving the one site that reads it from fleet.yml.

    repo-evolution passes `--max-turns ${{ needs.plan.outputs.max_turns }}`,
    which the plan job reads from `evolution.max_turns` — so the arithmetic
    below still has a real number to work with. A site with no turn cap at all
    (the @claude mention handler) returns None and is skipped.
    """
    m = re.search(r"--max-turns\s+(\d+)", args)
    if m:
        return int(m.group(1))
    if re.search(r"--max-turns\s+\$\{\{[^}]*plan\.outputs\.max_turns", args):
        return int(fleet["evolution"]["max_turns"])
    return None


def check_workflows(fleet: dict) -> None:
    budget = fleet.get("budget") or {}
    declared = budget.get("call_sites") or {}
    per_turn = float(budget.get("usd_per_turn") or 0)

    check("_data/fleet.yml declares a `budget` block", bool(budget))
    check("budget.usd_per_turn is a positive number", per_turn > 0)
    for key in ("default_usd", "local_usd"):
        value = budget.get(key)
        check(f"budget.{key} is a positive number",
              isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0)

    sites = call_sites()
    check("at least one claude-code-action call site was found "
          "(a zero here means the scan broke, not that the fleet is clean)",
          len(sites) > 0)

    for site, args in sorted(sites.items()):
        m = re.search(r"--max-budget-usd\s+([0-9]+(?:\.[0-9]+)?)", args)
        check(f"{site}: claude_args passes --max-budget-usd", bool(m))
        if not m:
            continue
        literal = float(m.group(1))

        want = declared.get(site)
        check(f"{site}: declared in _data/fleet.yml budget.call_sites", want is not None)
        if want is None:
            continue
        check(f"{site}: workflow cap (${literal:g}) matches the declared cap (${want:g})",
              literal == float(want))

        max_turns = declared_max_turns(args, fleet)
        if max_turns is None:
            continue
        needed = per_turn * max_turns
        check(f"{site}: cap ${literal:g} funds {max_turns} turns at "
              f"${per_turn:g}/turn (needs >= ${needed:g})",
              literal >= needed)

    for site in sorted(declared):
        check(f"budget.call_sites entry `{site}` still names a real call site",
              site in sites)


# --------------------------------------------------------------------------- #
# what a cap DOES when it binds
# --------------------------------------------------------------------------- #
def cost_steps() -> dict[str, dict]:
    """`<workflow file>:<job id>` -> the `Report Claude run cost` step."""
    found: dict[str, dict] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "Report Claude run cost" not in text:
            continue
        workflow = yaml.safe_load(text)
        for job_id, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if str(step.get("name", "")) == "Report Claude run cost":
                    found[f"{path.name}:{job_id}"] = step
    return found


def check_abort_contract() -> None:
    """A cap that binds must CHANGE something, not just annotate.

    `::error::` writes an annotation; it does not fail a step, and a green job
    runs every `success()`-gated step after it. So an abort that exits 0 with
    truncated work published a pull request that read like a completed pass.
    Three properties close that, and each is asserted here because all three
    are invisible until the day a cap actually binds:

      * the cost step FAILS on a budget hit (`dash ai run` already exits 1 —
        the same event must not have two different verdicts);
      * it publishes `budget_hit` as a step OUTPUT, so a publishing step can
        gate on the cap rather than on the action's undocumented exit code;
      * it echoes the result record into the RUN LOG, because that log is what
        ai_usage_collector.py scrapes for `total_cost_usd` — if an abort's
        record never lands there, the runs that hit the cap are exactly the
        ones missing from the fleet's cost ledger.
    """
    steps = cost_steps()
    check("`Report Claude run cost` steps were found (a zero here means the "
          "scan broke, not that the fleet is clean)", len(steps) > 0)

    for site, step in sorted(steps.items()):
        body = str(step.get("run") or "")
        check(f"{site}: the cost step has `id: cost` so its verdict is readable",
              step.get("id") == "cost")
        check(f"{site}: publishes `budget_hit` to $GITHUB_OUTPUT",
              'budget_hit=${budget_hit}" >> "$GITHUB_OUTPUT"' in body)
        check(f"{site}: echoes the result record into the run log for the "
              f"cost collector", "claude-run-result" in body)

        # The budget branch must end in a non-zero exit. Match the branch
        # itself rather than the file, so an `exit 0` elsewhere cannot satisfy
        # this and a future edit that softens it fails here.
        branch = re.search(
            # YAML strips a block scalar's common indentation, so match the
            # branch's closing `fi` at whatever column it lands on.
            r'if \[ "\$budget_hit" = "true" \]; then(.*?)\n *fi\b',
            body, re.S)
        check(f"{site}: a budget hit FAILS the step (exit 1, not an annotation "
              f"alone)", bool(branch) and re.search(r"\bexit 1\b", branch.group(1)))

    # The two workflows that publish a PR from the agent's working tree must
    # gate on that output. Everywhere else the agent opens its own PR, so a
    # red job is the whole signal.
    for name, job_id in (("unified-evolution.yml", "evolve"),
                         ("repo-evolution.yml", "evolve")):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        check(f"{name}: the publishing step reads `steps.cost.outputs.budget_hit`",
              "steps.cost.outputs.budget_hit" in text)
        check(f"{name}: a budget-truncated PR says so in its body",
              "BUDGET_HIT" in text and "MID-TASK" in text)


# --------------------------------------------------------------------------- #
# the `runs` ledger section
# --------------------------------------------------------------------------- #
V1_FIXTURE = {
    "version": 1,
    "usage": {"box|2026-09-01|bamr87|claude-opus-5": {
        "input": 10, "output": 20, "cache_5m": 0, "cache_1h": 0,
        "cache_read": 5, "turns": 3}},
    "sessions": {"box|2026-09-01|bamr87": ["sess-scan"]},
}


def run_record(session_id: str, cost: float, ts: str = "2026-09-18T09:00:00+00:00") -> dict:
    return {
        "timestamp": ts,
        "machine": "box",
        "repo": "bamr87",
        "session_id": session_id,
        "models": ["claude-opus-5"],
        "usage": {"input": 1, "output": 2, "cache_write": 0, "cache_read": 0, "turns": 4},
        "total_cost_usd": cost,
        "source": "dash ai run",
    }


def check_ledger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ai-activity-ledger.json"
        path.write_text(json.dumps(V1_FIXTURE))

        # A v1 ledger with no `runs` key must SURVIVE. merge_ledger discards the
        # whole prior ledger on a version mismatch, so bumping LEDGER_VERSION
        # for this additive key would have silently deleted every day of
        # history the first time it ran.
        ledger = ai_activity.record_run(path, run_record("sess-a", 1.25))
        check("v1 ledger: prior `usage` survives the first run record",
              ledger["usage"] == V1_FIXTURE["usage"])
        check("v1 ledger: prior `sessions` survives the first run record",
              ledger["sessions"] == V1_FIXTURE["sessions"])
        check("v1 ledger: `runs` is created on demand", list(ledger["runs"]) == ["sess-a"])
        check("LEDGER_VERSION was not bumped for an additive key",
              ai_activity.LEDGER_VERSION == 1)

        on_disk = json.loads(path.read_text())
        check("the run record is persisted, not just returned",
              on_disk["runs"]["sess-a"]["total_cost_usd"] == 1.25)
        check("the record carries every documented field",
              set(on_disk["runs"]["sess-a"]) == set(ai_activity.RUN_FIELDS))

        # Dedupe: the CLI's total_cost_usd is CUMULATIVE for a session, so a
        # resumed session must update its row, not add a second charge.
        ledger = ai_activity.record_run(path, run_record("sess-a", 2.50))
        check("re-running the wrapper on one session records ONE row",
              list(ledger["runs"]) == ["sess-a"])
        check("the deduped row holds the latest cumulative cost",
              ledger["runs"]["sess-a"]["total_cost_usd"] == 2.50)

        ledger = ai_activity.record_run(path, run_record("sess-b", 0.75))
        check("a different session adds a second row",
              sorted(ledger["runs"]) == ["sess-a", "sess-b"])

        # A run with no session id still lands, keyed on its timestamp — one
        # row, just not deduplicable.
        anon = run_record("", 0.10)
        anon["session_id"] = None
        ledger = ai_activity.record_run(path, anon)
        check("a session-less run is still recorded", len(ledger["runs"]) == 3)

        # Separation: headless spend is its own accounting. Both halves see the
        # same session, so summing them would double-count it.
        report = ai_activity.build_report(ledger, "box", 30)
        headless = report["headless"]
        check("the report carries a distinct `headless` section", bool(headless))
        check("headless billed cost is not folded into the estimate totals",
              report["totals"]["est_cost_usd"] != headless["billed_cost_usd"]
              or headless["billed_cost_usd"] == 0)
        check("headless run count matches the ledger", headless["count"] == 3)
        check("headless billed cost sums the run records",
              abs(headless["billed_cost_usd"] - 3.35) < 1e-9)

        ledger["sessions"]["box|2026-09-18|bamr87"] = ["sess-a"]
        flagged = ai_activity._headless_section(ledger, "2026-01-01")
        by_id = {r["session_id"]: r for r in flagged["runs"]}
        check("a run whose transcript the scan also read is marked `also_in_scan`",
              by_id["sess-a"]["also_in_scan"] is True)
        check("a run with no scanned transcript is not marked",
              by_id["sess-b"]["also_in_scan"] is False)


# --------------------------------------------------------------------------- #
# wrapper behaviour
# --------------------------------------------------------------------------- #
def check_wrapper() -> None:
    # A budget abort has two tells and neither is a documented contract on its
    # own: the subtype naming the budget, or a FAILED run that reached the cap.
    check("budget abort detected from the result subtype",
          ai_activity.budget_was_hit(
              {"subtype": "error_max_budget", "total_cost_usd": 0.1, "is_error": True}, 5.0))
    check("budget abort detected from a failed run at the ceiling",
          ai_activity.budget_was_hit(
              {"subtype": "error", "total_cost_usd": 5.0, "is_error": True}, 5.0))
    check("an expensive SUCCESS is not misread as a budget abort",
          not ai_activity.budget_was_hit(
              {"subtype": "success", "total_cost_usd": 9.9, "is_error": False}, 5.0))
    check("an ordinary cheap failure is not misread as a budget abort",
          not ai_activity.budget_was_hit(
              {"subtype": "error", "total_cost_usd": 0.2, "is_error": True}, 5.0))

    result = {"type": "result", "subtype": "success", "session_id": "s1",
              "total_cost_usd": 1.5, "num_turns": 7}
    check("result_record reads a bare result object",
          ai_activity.result_record(json.dumps(result)) == result)
    check("result_record reads a stream array, taking the LAST result",
          ai_activity.result_record(
              json.dumps([{"type": "system"}, {"type": "result", "session_id": "old"}, result])
          ) == result)
    check("result_record reads JSONL",
          ai_activity.result_record(
              '{"type":"system"}\n' + json.dumps(result)) == result)
    check("result_record returns None when the CLI produced no result",
          ai_activity.result_record('{"type":"system"}') is None)
    check("result_record tolerates empty output", ai_activity.result_record("") is None)

    usage = ai_activity.usage_from_result({
        "num_turns": 9,
        "modelUsage": {
            "claude-opus-5": {"inputTokens": 100, "outputTokens": 20,
                              "cacheReadInputTokens": 7, "cacheCreationInputTokens": 3},
            "claude-haiku-4-5": {"input_tokens": 5, "output_tokens": 1},
        },
    })
    check("usage_from_result sums every model and both field spellings",
          usage == {"input": 105, "output": 21, "cache_write": 3,
                    "cache_read": 7, "turns": 9})

    check("the local cap comes from _data/fleet.yml, not a hardcoded default",
          ai_activity.load_local_budget()
          == float((yaml.safe_load(FLEET.read_text(encoding="utf-8"))
                    ["budget"]["local_usd"])))

    dash = DASH.read_text(encoding="utf-8")
    check("`dash ai run` dispatches to `dash-gen ai-run`",
          re.search(r'run\)\s*shift;\s*"\$\{TOOLS\}/dash-gen"\s+ai-run', dash) is not None)
    check("`dash ai` (bare) still reaches the scan, unchanged",
          re.search(r'\*\)\s*"\$\{TOOLS\}/dash-gen"\s+ai\s', dash) is not None)


def main() -> int:
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
    check_workflows(fleet)
    check_abort_contract()
    check_ledger()
    check_wrapper()

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

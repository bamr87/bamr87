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

  * every `anthropics/claude-code-action` step AND every `claude-run` action
    step (.github/actions/claude-run — local `./` or `bamr87/bamr87/…@main`)
    in .github/workflows/ passes `--max-budget-usd` / `max-budget-usd:` — so
    a NEW loop cannot be added uncapped by either route;
  * every claude-code-action site except the human-triggered @claude mention
    handler is followed by a `Report Claude run cost` step that USES the one
    shared `.github/actions/claude-cost` action with the SAME cap — six inline
    copies of that step had drifted (fleet-pulse reported against $25 while
    its claude_args said $40);
  * a reusable workflow's `${{ inputs.<name> }}` resolves to that input's
    `workflow_call` default, so its cap and turn floor are still checked;
  * the claude-run action itself forwards the cap to the CLI and defaults it
    to `budget.default_usd`, so a caller that forgets it is still capped;
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
  * a budget abort is detected from either tell the CLI gives;
  * the local loop runner's monthly ceiling (`budget.loops`, tools/jev/loop.py)
    covers at least one full-cap attempt of every step that runs locally, and
    `budget.loops` + `budget.jev` stay inside harnesses.budget.monthly_ai_usd.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_ai_budget.py
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_activity  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CLAUDE_RUN = REPO_ROOT / ".github" / "actions" / "claude-run"
CLAUDE_COST = REPO_ROOT / ".github" / "actions" / "claude-cost"

# The one claude-code-action call site with no cost step: a HUMAN-triggered
# mention handler whose seeded copy must stay byte-close to the kit template
# (templates/agent-context/claude.yml), which carries no hub-side step.
COST_EXEMPT = {"claude.yml:claude"}
FLEET = REPO_ROOT / "_data" / "fleet.yml"
DASH = REPO_ROOT / "tools" / "dash"
STEP_SPECS = REPO_ROOT / "tools" / "jev" / "steps"

CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


# --------------------------------------------------------------------------- #
# workflow call sites
# --------------------------------------------------------------------------- #
def is_claude_run(uses: str) -> bool:
    """A step that runs the fleet's composite `claude-run` action, by any ref."""
    return re.search(r"(^\./|^bamr87/bamr87/)\.github/actions/claude-run(@|$)", uses) is not None


def is_claude_cost(uses: str) -> bool:
    """A step that runs the shared `claude-cost` action — from this checkout, from
    the `.fleet-hub` sparse checkout a foreign-workspace job makes, or by ref."""
    return re.search(r"(^\./(\.fleet-hub/)?|^bamr87/bamr87/)\.github/actions/claude-cost(@|$)", uses) is not None


def call_inputs(workflow: dict) -> dict:
    """The `workflow_call` inputs of a reusable workflow (PyYAML reads `on:` as True)."""
    on = workflow.get("on", workflow.get(True)) or {}
    if not isinstance(on, dict):
        return {}
    return ((on.get("workflow_call") or {}).get("inputs")) or {}


def resolve_inputs(args: str, workflow: dict) -> str:
    """Substitute `${{ inputs.<name> }}` with that input's non-empty default.

    A reusable workflow's caller can override the input, but the DEFAULT is
    what the hub declares and what an unconfigured caller gets — that is the
    number to hold against `budget.call_sites` and the turn floor.
    """
    inputs = call_inputs(workflow)

    def sub(m: re.Match) -> str:
        default = (inputs.get(m.group(1)) or {}).get("default")
        return m.group(0) if default in (None, "") else str(default)

    return re.sub(r"\$\{\{\s*inputs\.([A-Za-z0-9_-]+)\s*\}\}", sub, args)


def call_sites() -> dict[str, str]:
    """`<workflow file>:<job id>` -> that step's agent arguments as one string.

    Keyed by job rather than by step name because a step name is prose and gets
    reworded; a job id is referenced by `needs:` and cannot move quietly.
    `claude-run` takes its caps as `with:` inputs rather than a `claude_args`
    string; they are rendered into the same `--flag value` shape so one set of
    checks covers both routes.
    """
    found: dict[str, str] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "claude-code-action" not in text and "claude-run" not in text:
            continue
        workflow = yaml.safe_load(text)
        for job_id, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                uses = str(step.get("uses", ""))
                with_ = step.get("with") or {}
                if "claude-code-action" in uses:
                    args = str(with_.get("claude_args") or "")
                    ACTION_SITES.add(f"{path.name}:{job_id}")
                elif is_claude_run(uses):
                    args = " ".join(
                        f"--{key} {with_[key]}" for key in ("max-turns", "max-budget-usd")
                        if str(with_.get(key, "")).strip())
                else:
                    continue
                found[f"{path.name}:{job_id}"] = resolve_inputs(args, workflow)
    return found


ACTION_SITES: set[str] = set()   # the claude-code-action sites, filled by call_sites()


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


def check_claude_run_action(budget: dict) -> None:
    """The composite action is a call site's last line of defence.

    A caller that omits `max-budget-usd` gets the action's default, so that
    default must be the fleet fallback, and the value must actually reach the
    CLI — an input that run.sh never forwards is a cap in name only.
    """
    action = yaml.safe_load((CLAUDE_RUN / "action.yml").read_text(encoding="utf-8"))
    spec = (action.get("inputs") or {}).get("max-budget-usd") or {}
    check("claude-run action declares a `max-budget-usd` input", bool(spec))
    default = str(spec.get("default", "")).strip()
    check(f"claude-run `max-budget-usd` defaults to budget.default_usd "
          f"(${budget.get('default_usd')}, got '{default}')",
          default != "" and float(default) == float(budget.get("default_usd") or -1))
    steps_text = yaml.safe_dump(action.get("runs") or {})
    check("claude-run action forwards the input to run.sh as --max-budget-usd",
          "inputs.max-budget-usd" in steps_text and "--max-budget-usd" in steps_text)
    run_sh = (CLAUDE_RUN / "run.sh").read_text(encoding="utf-8")
    check("run.sh passes --max-budget-usd to the claude CLI",
          re.search(r'args\+=\(--max-budget-usd "\$max_budget"\)', run_sh) is not None)
    check("run.sh treats a budget abort as final (no retry, no API fallback)",
          re.search(r"\*max_budget\*.*\) echo budget", run_sh) is not None
          and re.search(r"budget\)\n(?:.*\n){0,8}?\s*exit 1", run_sh) is not None)


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
    check("at least one claude-run call site was found (same reasoning)",
          any(f"{name}:" in site for site in sites
              for name in ("ai-lane.yml",)))
    check_claude_run_action(budget)

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


def check_abort_contract(sites: dict[str, str]) -> None:
    """A cap that binds must CHANGE something, not just annotate.

    `::error::` writes an annotation; it does not fail a step, and a green job
    runs every `success()`-gated step after it. So an abort that exits 0 with
    truncated work published a pull request that read like a completed pass.
    The script that closes that lives ONCE, in .github/actions/claude-cost;
    three properties are asserted on it because all three are invisible until
    the day a cap actually binds:

      * it FAILS on a budget hit (`dash ai run` already exits 1 — the same
        event must not have two different verdicts);
      * it publishes `budget_hit` as an OUTPUT, so a publishing step can gate
        on the cap rather than on the action's undocumented exit code;
      * it echoes the result record into the RUN LOG, because that log is what
        ai_usage_collector.py scrapes for `total_cost_usd` — if an abort's
        record never lands there, the runs that hit the cap are exactly the
        ones missing from the fleet's cost ledger.

    Then every call site: each claude-code-action job (bar the exempt mention
    handler) has a `Report Claude run cost` step, with `id: cost`, that USES
    the action (no inline copies — six of them drifted) on every non-cancelled
    outcome, with a `budget-usd` equal to the cap its claude_args carries.
    """
    action = yaml.safe_load((CLAUDE_COST / "action.yml").read_text(encoding="utf-8"))
    steps = (action.get("runs") or {}).get("steps") or []
    body = str(steps[0].get("run") or "") if steps else ""
    check("claude-cost: the action has a script to assert", bool(body))
    check("claude-cost: publishes `budget_hit` to $GITHUB_OUTPUT",
          'budget_hit=${budget_hit}" >> "$GITHUB_OUTPUT"' in body)
    check("claude-cost: declares `budget_hit` as an action output",
          "budget_hit" in (action.get("outputs") or {}))
    check("claude-cost: echoes the result record into the run log for the cost collector",
          "claude-run-result" in body)
    branch = re.search(r'if \[ "\$budget_hit" = "true" \]; then(.*?)\n *fi\b', body, re.S)
    check("claude-cost: a budget hit FAILS the step (exit 1, not an annotation alone)",
          bool(branch) and re.search(r"\bexit 1\b", branch.group(1)) is not None)
    check("claude-cost: the credential-rejected classifier is present", "modelUsage" in body)
    check("claude-cost: a 429 is classified apart from a refused credential", "429" in body)
    check("claude-cost: declares and publishes `usage_limit`",
          "usage_limit" in (action.get("outputs") or {}) and 'usage_limit=true" >> "$GITHUB_OUTPUT"' in body)
    check("claude-cost: `usage-limit` input defaults to `fail` (verdict stays with the agent step)",
          str(((action.get("inputs") or {}).get("usage-limit") or {}).get("default")) == "fail")
    check("claude-cost: in `skip` mode every failure but a usage limit still exits 1",
          'verdict=1' in body and 'exit "$verdict"' in body)

    steps = cost_steps()
    check("`Report Claude run cost` steps were found (a zero here means the "
          "scan broke, not that the fleet is clean)", len(steps) > 0)
    for site in sorted(ACTION_SITES - COST_EXEMPT):
        check(f"{site}: has a `Report Claude run cost` step", site in steps)
    for site, step in sorted(steps.items()):
        check(f"{site}: the cost step has `id: cost` so its verdict is readable",
              step.get("id") == "cost")
        check(f"{site}: the cost step USES the shared claude-cost action (no inline copy)",
              is_claude_cost(str(step.get("uses", ""))) and not step.get("run"))
        check(f"{site}: cost is reported on every non-cancelled outcome, not only on failure",
              "!cancelled()" in str(step.get("if")) and "failure()" not in str(step.get("if")))
        with_ = step.get("with") or {}
        m = re.search(r"--max-budget-usd\s+([0-9]+(?:\.[0-9]+)?)", sites.get(site, ""))
        cap = float(m.group(1)) if m else None
        got = str(with_.get("budget-usd", "")).strip()
        check(f"{site}: the readout's budget-usd ({got or '?'}) equals the job's "
              f"--max-budget-usd ({cap if cap is not None else '?'})",
              cap is not None and got != "" and float(got) == cap)
        check(f"{site}: `outcome` reads the agent step's outcome",
              re.search(r"steps\.[\w-]+\.outcome", str(with_.get("outcome", ""))) is not None)

    check_usage_limit_contract(steps)

    # The workflow that publishes a PR from the agent's working tree must gate
    # on that output. Everywhere else the agent opens its own PR, so a red job
    # is the whole signal.
    for name, job_id in (("repo-evolution.yml", "evolve"),):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        check(f"{name}: the publishing step reads `steps.cost.outputs.budget_hit`",
              "steps.cost.outputs.budget_hit" in text)
        check(f"{name}: a budget-truncated PR says so in its body",
              "BUDGET_HIT" in text and "MID-TASK" in text)


def check_usage_limit_contract(steps: dict[str, dict]) -> None:
    """A spent subscription window is capacity, not a defect — on a schedule.

    Every hub loop shares one Claude subscription. When its weekly window ran
    out (2026-10-23..25) fleet-pulse and issue-pipeline went red every morning
    until the reset, and the doctor filed issues about its own red runs (#335,
    #348). `usage-limit: skip` turns that into a warning — but only because the
    agent step is `continue-on-error` and claude-cost then owns the verdict.
    The two halves are useless apart: skip without continue-on-error is still
    red, and continue-on-error without skip would turn EVERY agent failure
    green. So: they come as a pair, and every scheduled loop uses them.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        on = workflow.get("on", workflow.get(True)) or {}
        scheduled = isinstance(on, dict) and "schedule" in on
        for job_id, job in (workflow.get("jobs") or {}).items():
            site = f"{path.name}:{job_id}"
            agents = [s for s in job.get("steps") or []
                      if "claude-code-action" in str(s.get("uses", ""))]
            if not agents or site in COST_EXEMPT:
                continue
            coe = all(s.get("continue-on-error") is True for s in agents)
            mode = str(((steps.get(site) or {}).get("with") or {}).get("usage-limit") or "fail")
            check(f"{site}: `usage-limit: skip` and a continue-on-error agent step come as a pair "
                  f"(skip={mode == 'skip'}, continue-on-error={coe})",
                  (mode == "skip") == coe)
            if scheduled:
                check(f"{site}: a scheduled loop reports a spent usage window as capacity "
                      "(`usage-limit: skip`), not as a red run", mode == "skip")


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

        # A v1 ledger with no `runs` key must SURVIVE. The writers refuse a
        # ledger of another version, so bumping LEDGER_VERSION for this additive
        # key would have stopped every writer the first time it ran.
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

        # An unreadable ledger is not an empty one: no writer replaces it with
        # only its own rows (the month's local-loop spend, budget.loops, is in it),
        # and a reader still sees it as empty rather than crashing.
        for bad in ("{truncated", json.dumps({"version": 2, "runs": {"r": {"total_cost_usd": 20}}}), "[]"):
            path.write_text(bad)
            for name, write in (("merge_ledger", lambda: ai_activity.merge_ledger(path, {}, {})),
                                ("record_run", lambda: ai_activity.record_run(path, run_record("sess-z", 1.0)))):
                try:
                    write()
                    refused, said = False, ""
                except ai_activity.LedgerUnreadable as exc:
                    refused, said = True, str(exc)
                check(f"{name} refuses to overwrite a ledger it cannot read ({bad[:12]}…)",
                      refused and path.read_text() == bad)
                # moved aside, the ledger would read as an empty month: budget.loops back at $0
                check(f"{name}'s refusal says to repair it in place, never to move it aside ({bad[:12]}…)",
                      "in place" in said and "budget.loops" in said and "move it aside" not in said)
            check(f"a reader sees an unreadable ledger ({bad[:12]}…) as empty",
                  ai_activity.load_ledger(path)["runs"] == {})
        path.unlink()
        check("an absent ledger is simply new to a writer",
              list(ai_activity.record_run(path, run_record("sess-n", 1.0))["runs"]) == ["sess-n"])


# --------------------------------------------------------------------------- #
# wrapper behaviour
# --------------------------------------------------------------------------- #
def check_wrapper() -> None:
    # `dash ai run` reads its result with headless.last_result and classifies it
    # with headless.classify (tools/jev/headless.py), so these hold THAT code.
    hl = ai_activity.headless()

    def budget_hit(result: dict, cap: float) -> bool:
        return hl.classify(hl.Invocation(rc=0, result=result), cap).kind == "budget_hit"

    # A budget abort has two tells and neither is a documented contract on its
    # own: the subtype naming the budget, or a FAILED run that reached the cap.
    check("budget abort detected from the result subtype",
          budget_hit({"subtype": "error_max_budget", "total_cost_usd": 0.1, "is_error": True}, 5.0))
    check("budget abort detected from a failed run at the ceiling",
          budget_hit({"subtype": "error", "total_cost_usd": 5.0, "is_error": True}, 5.0))
    check("an expensive SUCCESS is not misread as a budget abort",
          not budget_hit({"subtype": "success", "total_cost_usd": 9.9, "is_error": False}, 5.0))
    check("an ordinary cheap failure is not misread as a budget abort",
          not budget_hit({"subtype": "error", "total_cost_usd": 0.2, "is_error": True,
                          "modelUsage": {"claude-sonnet-5-5": {}}}, 5.0))

    result = {"type": "result", "subtype": "success", "session_id": "s1",
              "total_cost_usd": 1.5, "num_turns": 7}
    check("last_result reads a bare result object",
          hl.last_result(json.dumps(result)) == result)
    check("last_result reads a stream array, taking the LAST result",
          hl.last_result(
              json.dumps([{"type": "system"}, {"type": "result", "session_id": "old"}, result])
          ) == result)
    check("last_result reads JSONL",
          hl.last_result('{"type":"system"}\n' + json.dumps(result)) == result)
    check("last_result returns None when the CLI produced no result",
          hl.last_result('{"type":"system"}') is None)
    check("last_result tolerates empty output", hl.last_result("") is None)

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


# --------------------------------------------------------------------------- #
# the local loop runner's monthly ceiling
# --------------------------------------------------------------------------- #
def check_loops_budget(fleet: dict) -> None:
    """`budget.loops` is the local runner's monthly TOTAL (the `budget.jev`
    shape); each attempt is still held to its step's `call_sites` cap. Read
    from the spec files directly — a step runs locally iff its spec has a
    `local:` block — so this needs no tools.jev import."""
    budget = fleet.get("budget") or {}
    loops = budget.get("loops") or {}
    usd, pct = loops.get("monthly_usd"), loops.get("scheduled_stop_pct")
    check("budget.loops declares a finite monthly_usd above 0", _bounds(usd))
    check("budget.loops.scheduled_stop_pct is in 1..100",
          isinstance(pct, int) and not isinstance(pct, bool) and 0 < pct <= 100)
    if not _bounds(usd):
        return
    sites = budget.get("call_sites") or {}
    local = []
    for path in sorted(STEP_SPECS.glob("*/*.yml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(spec, dict) and spec.get("local"):
            local.append(str(spec.get("call_site")))
    check("at least one step spec runs locally (a local: block)", bool(local))
    for site in local:
        cap = sites.get(site)
        check(f"local step {site} has a budget.call_sites cap", _bounds(cap))
        check(f"budget.loops (${usd:g}) covers one full-cap attempt of {site} (${cap})",
              _bounds(cap) and usd >= cap)
    jev = (budget.get("jev") or {}).get("monthly_usd")
    ceiling = ((fleet.get("harnesses") or {}).get("budget") or {}).get("monthly_ai_usd")
    check("budget.jev declares a finite monthly_usd above 0", _bounds(jev))
    check("harnesses.budget.monthly_ai_usd is declared, a finite number above 0", _bounds(ceiling))
    if _bounds(jev) and _bounds(ceiling):
        check(f"budget.loops + budget.jev (${usd + jev:g}) stay inside harnesses.budget.monthly_ai_usd "
              f"(${ceiling:g})", usd + jev <= ceiling)


def _bounds(value) -> bool:
    """A cap or ceiling that bounds something: a finite number above 0. YAML's
    `.inf` passes `> 0`, and `x <= inf` is always true, so a bare `> 0` gate
    over an infinite ceiling holds nothing."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and value > 0)


def check_loops_budget_gate(fleet: dict) -> None:
    """The ceiling gate above is itself held: run on a copy of the fleet whose
    money bounds nothing, it must fail. The console's config form is one way
    such a value reaches `_data/fleet.yml`."""
    ceiling, loops, jev = ("harnesses", "budget", "monthly_ai_usd"), ("budget", "loops", "monthly_usd"), \
        ("budget", "jev", "monthly_usd")
    cases = (("harnesses.budget.monthly_ai_usd .inf", [(ceiling, math.inf)]),
             ("harnesses.budget.monthly_ai_usd .nan", [(ceiling, math.nan)]),
             ("budget.loops.monthly_usd and the ceiling .inf", [(loops, math.inf), (ceiling, math.inf)]),
             ("budget.jev.monthly_usd 'lots'", [(jev, "lots")]))
    for label, edits in cases:
        trial = copy.deepcopy(fleet)
        for path, value in edits:
            node = trial
            for key in path[:-1]:
                node = node.setdefault(key, {})
            node[path[-1]] = value
        mark = len(CHECKS)
        check_loops_budget(trial)
        verdicts = CHECKS[mark:]
        del CHECKS[mark:]
        check(f"the loops ceiling gate fails a fleet with {label}", any(not ok for _, ok in verdicts))


def main() -> int:
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
    check_workflows(fleet)
    check_loops_budget(fleet)
    check_loops_budget_gate(fleet)
    check_abort_contract(call_sites())
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

#!/usr/bin/env python3
"""
Fixture tests for the workflow atlas (workflow_atlas.py) — the hub's GitHub
Actions read as one model, linted against the standards, failures classified,
new workflows scaffolded inside the rules.

Each rule is exercised both ways on a small synthetic workflow (it fires on
the defect it names, and stays quiet on the fix), the failure classifier is
run on error lines copied from real failed runs, and the LIVE tree is held to
zero error-level findings — the gate for every rule that no other test owns
(kill-switch semantics, null dispatch inputs, PR token, timeouts …).

    python3 .github/scripts/dash-gen/test_workflow_atlas.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_atlas as wa  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET = {
    "hub": {"repo": "bamr87/bamr87"},
    "schedule": {"good_loop": "7 4 * * *", "agent": "37 11 * * *"},
    "budget": {"default_usd": 10, "call_sites": {"agent.yml:agent": 20}},
}

GOOD = """name: Good loop
on:
  schedule:
    - cron: '7 4 * * *'
  workflow_dispatch:
    inputs:
      apply:
        type: boolean
        default: true
permissions:
  contents: read
concurrency:
  group: good-loop
  cancel-in-progress: false
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v7
      - if: github.event_name != 'workflow_dispatch' || inputs.apply
        run: echo ok
      - uses: ./.github/actions/utilities/publish-data
        with:
          paths: "_data/x.yml _data/y.yml"
          message: "chore(data): x [skip ci]"
"""

AGENT = """name: Agent
on:
  schedule:
    - cron: '37 11 * * *'
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: agent
jobs:
  agent:
    if: ${{ github.event_name != 'schedule' || vars.AGENT_ENABLED == 'true' }}
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - id: agent
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_args: --model opus --max-turns 40 --max-budget-usd 20
      - id: cost
        if: ${{ !cancelled() }}
        uses: ./.github/actions/claude-cost
        with:
          budget-usd: "20"
          outcome: ${{ steps.agent.outcome }}
          usage-limit: skip
"""


def rules(text: str, fleet: dict | None = None, file: str = ".github/workflows/good-loop.yml") -> set[str]:
    return {f["rule"] for f in wa.lint_text(text, FLEET if fleet is None else fleet, file)["findings"]}


# --------------------------------------------------------------------------- #
# the model
# --------------------------------------------------------------------------- #
def test_parse_reads_triggers_inputs_jobs_and_uses():
    wf = wa.lint_text(GOOD, FLEET, ".github/workflows/good-loop.yml")["workflow"]
    assert wf["name"] == "Good loop" and wf["triggers"] == ["schedule", "workflow_dispatch"]
    assert wf["crons"][0]["human"] == "daily 04:07 UTC" and wf["crons"][0]["schedule_key"] == "good_loop"
    assert wf["dispatch_inputs"] == [{"name": "apply", "type": "boolean", "default": True, "required": False,
                                      "description": "", "options": []}]
    assert wf["jobs"][0]["timeout"] == 10 and wf["concurrency"]["group"] == "good-loop"
    kinds = {(r["kind"], r["target"]) for r in wf["uses"]}
    assert kinds == {("external", "actions/checkout"), ("action", "utilities/publish-data")}
    assert wf["publishes"] == ["_data/x.yml", "_data/y.yml"]


def test_refs_resolve_local_remote_and_hub_checkout_actions():
    for ref, kind, target in (
        ("./.github/actions/claude-cost", "action", "claude-cost"),
        ("./.fleet-hub/.github/actions/claude-cost", "action", "claude-cost"),
        ("bamr87/bamr87/.github/actions/claude-run@v2", "action", "claude-run"),
        ("./.github/workflows/fleet-conformance.yml", "workflow", "fleet-conformance"),
        ("bamr87/bamr87/.github/workflows/site-quality.yml@v1", "workflow", "site-quality"),
        ("actions/checkout@v7", "external", "actions/checkout"),
        ("github/codeql-action/init@v3", "external", "github/codeql-action/init"),
    ):
        r = wa._ref(ref)
        assert (r["kind"], r["target"]) == (kind, target), (ref, r)


def test_claude_sites_carry_budget_declared_cap_and_usage_limit_mode():
    wf = wa.lint_text(AGENT, FLEET, ".github/workflows/agent.yml")["workflow"]
    (s,) = wf["ai_sites"]
    assert s["site"] == "agent.yml:agent" and s["max_budget_usd"] == 20 and s["declared_usd"] == 20
    assert s["model"] == "opus" and s["max_turns"] == 40 and s["continue_on_error"] and s["usage_limit"] == "skip"
    assert wf["switch"] == "AGENT_ENABLED"


def test_readme_rows_group_and_retired_table():
    text = """# Workflows
## Daily and weekly loops
| Workflow | When | What it does |
| --- | --- | --- |
| `a.yml` | daily | **A** loop with [a link](x.md). |
## Something else
| `b.yml` | PR | B. |
## Retired
| Date | Removed | Why |
| --- | --- | --- |
| 2026-10-27 | `git-digs.yml` | never ran |
"""
    r = wa.parse_readme(text)
    assert r["rows"]["a.yml"]["group"] == "loop" and wa._plain(r["rows"]["a.yml"]["purpose"]) == "A loop with a link."
    assert r["rows"]["b.yml"]["group"] is None, "a row under an unknown heading still documents the file"
    assert r["retired"] == [{"date": "2026-10-27", "removed": "git-digs.yml", "why": "never ran", "files": ["git-digs.yml"]}]


# --------------------------------------------------------------------------- #
# the rules, both ways
# --------------------------------------------------------------------------- #
def test_good_fixtures_are_clean():
    assert rules(GOOD) == set()
    assert rules(AGENT, file=".github/workflows/agent.yml") == set()


def test_permissions_timeout_and_concurrency():
    bad = GOOD.replace("permissions:\n  contents: read\n", "").replace("    timeout-minutes: 10\n", "")
    bad = bad.replace("concurrency:\n  group: good-loop\n  cancel-in-progress: false\n", "")
    assert {"timeout", "concurrency"} <= rules(bad)
    assert "permissions" not in rules(bad), "every job declares its own permissions"
    assert "permissions" in rules(bad.replace("    permissions:\n      contents: write\n", ""))
    job_level = bad.replace("    timeout-minutes: 10\n", "") .replace("    runs-on: ubuntu-latest\n",
                            "    runs-on: ubuntu-latest\n    concurrency: writer\n")
    assert "concurrency" not in rules(job_level), "the one writing job is serialized"
    reusable = "on:\n  workflow_call:\njobs:\n  a:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - run: echo\n"
    assert "permissions" not in rules(reusable), "a called workflow inherits the caller's permissions"


def test_crons_declared_and_off_the_hour():
    assert "cron-declared" in rules(GOOD.replace("'7 4 * * *'", "'7 5 * * *'"))
    hits = rules(GOOD.replace("'7 4 * * *'", "'0 4 * * *'"))
    assert {"cron-on-hour", "cron-declared"} <= hits
    assert "cron-declared" not in rules(GOOD, fleet={}), "a draft with no fleet.yml skips the hub-only rules"


def test_sha_pins_are_errors():
    assert "sha-pin" in rules(GOOD.replace("actions/checkout@v7", "actions/checkout@" + "a" * 40))


def test_scheduled_agent_needs_a_kill_switch():
    assert "kill-switch" in rules(AGENT.replace(" || vars.AGENT_ENABLED == 'true'", ""), file=".github/workflows/agent.yml")


def test_budget_must_exist_and_match_fleet_yml():
    assert "ai-budget" in rules(AGENT.replace(" --max-budget-usd 20", ""), file=".github/workflows/agent.yml")
    assert "ai-budget" in rules(AGENT.replace("--max-budget-usd 20", "--max-budget-usd 30"), file=".github/workflows/agent.yml")
    assert "ai-budget" in rules(AGENT, file=".github/workflows/other.yml"), "an undeclared call site"


def test_usage_limit_halves_must_pair_on_scheduled_sites():
    agent = ".github/workflows/agent.yml"
    assert "usage-limit" in rules(AGENT.replace("        continue-on-error: true\n", ""), file=agent)
    assert "usage-limit" in rules(AGENT.replace("          usage-limit: skip\n", ""), file=agent)
    no_cost = AGENT[:AGENT.index("      - id: cost")]
    assert "usage-limit" in rules(no_cost, file=agent)
    dispatch_only = AGENT.replace("  schedule:\n    - cron: '37 11 * * *'\n", "").replace("        continue-on-error: true\n", "")
    assert "usage-limit" not in rules(dispatch_only.replace("          usage-limit: skip\n", ""), file=agent), \
        "a dispatch-only site may fail red"


def test_null_input_is_the_schema_vendor_defect():
    guard = "github.event_name != 'workflow_dispatch' || inputs.apply"
    bad = GOOD.replace(guard, "inputs.apply != false")
    assert "null-input" in rules(bad)
    assert "null-input" in rules(GOOD.replace(guard, "false == inputs.apply"))
    assert "null-input" in rules(GOOD.replace(guard, "${{ !inputs.apply }}"))
    assert "null-input" in rules(GOOD.replace(guard, "github.event_name != 'push' && inputs.apply != false")), \
        "a guard that does not name dispatch or schedule guards nothing"
    dispatch_only = bad.replace("  schedule:\n    - cron: '7 4 * * *'\n", "")
    assert "null-input" not in rules(dispatch_only), "dispatch-only: inputs are never null"
    assert "null-input" not in rules(GOOD.replace(guard, "inputs.apply != true"))
    assert "null-input" not in rules(bad.replace("default: true", "default: false")), \
        "with a false default, null and the default agree"


def test_usage_limit_skips_a_runtime_continue_on_error():
    agent = ".github/workflows/agent.yml"
    expr = AGENT.replace("continue-on-error: true", "continue-on-error: ${{ github.event_name == 'schedule' }}")
    assert "usage-limit" not in rules(expr, file=agent), "decided at run time: not checkable here"


def test_budget_from_an_input_with_no_default_is_not_missing():
    reusable = AGENT.replace("  schedule:\n    - cron: '37 11 * * *'\n  workflow_dispatch:\n",
                             "  workflow_call:\n    inputs:\n      cap:\n        type: string\n")
    reusable = reusable.replace("--max-budget-usd 20", "--max-budget-usd ${{ inputs.cap }}")
    assert "ai-budget" not in rules(reusable, file=".github/workflows/agent.yml")


def test_workflow_run_pr_token_and_bare_push():
    assert "workflow-run" in rules(GOOD.replace("  workflow_dispatch:\n", "  workflow_run:\n    workflows: [x]\n  workflow_dispatch:\n", 1))
    pr = GOOD.replace("        run: echo ok", "        env:\n          GH_TOKEN: ${{ github.token }}\n        run: gh pr create --fill")
    assert "pr-token" in rules(pr)
    assert "pr-token" not in rules(pr.replace("${{ github.token }}", "${{ secrets.FLEET_TOKEN }}"))
    assert "pr-token" not in rules(pr.replace("${{ github.token }}", "${{ steps.tok.outputs.token || github.token }}")), \
        "a probed token with the job token as a fallback"
    assert "pr-token" in rules(pr.replace("GH_TOKEN:", "GITHUB_TOKEN:"))
    assert "pr-token" in rules(GOOD.replace("        run: echo ok", "        uses: peter-evans/create-pull-request@v7"))
    assert "bare-push" in rules(GOOD.replace("run: echo ok", "run: git push origin HEAD:main"))
    assert "bare-push" in rules(GOOD.replace("run: echo ok", "run: git push"))
    assert "bare-push" not in rules(GOOD.replace("run: echo ok", 'run: git push origin "HEAD:refs/heads/$BRANCH"'))
    for ok in ("git push origin chore/main-data-refresh", "git push origin fix/master-list",
               'if ! git push -q "$REMOTE" "HEAD:refs/heads/${BR}"; then exit 1; fi'):
        assert "bare-push" not in rules(GOOD.replace("run: echo ok", f"run: {ok}")), ok
    for bad in ("git push origin", "git push origin HEAD", "git -C dir push --quiet", "git push -f origin main:main"):
        assert "bare-push" in rules(GOOD.replace("run: echo ok", f"run: {bad}")), bad


def test_actions_description_expression_and_unused():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "actions" / "used").mkdir(parents=True)
        (root / ".github" / "actions" / "lonely").mkdir(parents=True)
        (root / ".github" / "workflows" / "good-loop.yml").write_text(GOOD.replace(
            "utilities/publish-data", "used"))
        (root / ".github" / "actions" / "used" / "action.yml").write_text(
            "name: used\ndescription: defaults to ${{ github.token }}\nruns:\n  using: composite\n  steps: []\n")
        (root / ".github" / "actions" / "lonely" / "action.yml").write_text(
            "name: lonely\ndescription: nobody calls me\ninputs:\n  token:\n    description: normally ${{ github.token }}\n"
            "runs:\n  using: composite\n  steps: []\n")
        atlas = wa.scan(root, FLEET)
        got = {(f["rule"], f["target"]) for f in atlas["findings"]}
        assert ("action-description-expr", "used") in got and ("action-unused", "lonely") in got
        assert ("action-description-expr", "lonely") in got, "an input's description is a template too"
        assert ("undocumented", "good-loop") in got, "no README row"
        assert {a["id"]: a["used_by"] for a in atlas["actions"]} == {"lonely": [], "used": ["good-loop"]}


def test_malformed_yaml_is_a_finding_never_a_crash():
    for text in ("on: push\njobs: [a, b]\n",
                 "on:\n  workflow_dispatch:\n    inputs: [a, b]\njobs: {}\n",
                 "on: push\njobs:\n  a:\n    steps: {run: x}\n",
                 "a: &a [*a]\n"):
        got = wa.lint_text(text, FLEET)
        assert isinstance(got["findings"], list), text


def test_alias_bombs_are_refused_fast():
    import time
    lines, prev = ["      a: &a [x,x,x,x,x,x,x,x,x]"], "a"
    for name in "bcdefgh":
        lines.append(f"      {name}: &{name} [" + ",".join([f"*{prev}"] * 9) + "]")
        prev = name
    bomb = "on: push\npermissions: {}\njobs:\n  j:\n    runs-on: x\n    timeout-minutes: 1\n    steps:\n" \
           "    - run: echo\n      env:\n" + "\n".join("  " + x for x in lines) + "\n"
    t = time.time()
    got = wa.lint_text(bomb, FLEET)
    assert time.time() - t < 2 and got["findings"][0]["rule"] == "parse-error", got["findings"]


def test_yaml_12_booleans_keep_choice_options_strings():
    wf = wa.lint_text("on:\n  workflow_dispatch:\n    inputs:\n      x:\n        type: choice\n"
                      "        options: [yes, no, on]\njobs: {}\n", {})["workflow"]
    assert wf["triggers"] == ["workflow_dispatch"] and wf["dispatch_inputs"][0]["options"] == ["yes", "no", "on"]


# --------------------------------------------------------------------------- #
# health — error lines from real failed runs
# --------------------------------------------------------------------------- #
def _log(*errors: str, echo: str = "") -> str:
    lines = [f"2026-10-23T05:41:12.1234567Z {echo}"] if echo else []
    return "\n".join(lines + [f"2026-10-23T05:41:13.0000000Z ##[error]{e}" for e in errors])


def test_classifier_reads_capacity_before_the_agent_noise():
    log = _log("Claude result reported subtype success with is_error:true (run did not complete successfully)",
               "Action failed with error: Claude execution failed: result is_error:true",
               "Fleet doctor: Claude usage limit hit (HTTP 429): You've hit your weekly limit · resets 12am")
    c = wa.classify_failure(log, "failure")
    assert (c["cause"], c["class"]) == ("usage-limit", "capacity") and "429" in c["evidence"]


def test_classifier_reads_errors_before_warnings_and_skips_step_echo():
    log = "\n".join(["2026-10-23T05:41:12.0Z ##[warning]Failed to restore: Cache service responded with 503",
                     "2026-10-23T05:41:13.0Z ##[error]ModuleNotFoundError: No module named 'yaml'"])
    assert wa.classify_failure(log, "failure")["cause"] == "code"
    echo = "\n".join(["2026-10-23T05:41:12.0Z ##[group]Run anthropics/claude-code-action@v1",
                      "2026-10-23T05:41:12.0Z with:", '2026-10-23T05:41:12.0Z   prompt: skip runs that hit "usage limit hit"',
                      "2026-10-23T05:41:12.0Z ##[endgroup]", "2026-10-23T05:41:13.0Z ##[error]Process completed with exit code 1."])
    assert wa.classify_failure(echo, "failure")["class"] == "defect"
    rejected = _log("Action failed with error: Claude execution failed: result is_error:true",
                    "Tier 1: the Claude credential was REJECTED (expired or revoked). Rotate CLAUDE_CODE_OAUTH_TOKEN.")
    assert wa.classify_failure(rejected, "failure")["cause"] == "auth"


def test_classifier_reads_each_job_tail_and_picks_specific_evidence():
    failing = "2026-10-23T05:41:12.0Z npm error Cannot read properties of null (reading 'edgesOut')\n" \
              "2026-10-23T05:41:12.1Z npm error A complete log of this run can be found in: /x.log\n" \
              "2026-10-23T05:41:13.0Z ##[error]Process completed with exit code 1."
    later = "\n".join(f"2026-10-23T05:42:{i % 60:02d}.0Z step output {i}" for i in range(400))
    c = wa.classify_failure([failing, later], "failure")
    assert c["evidence"].startswith("npm error Cannot read properties"), c


def test_classifier_ignores_echoed_script_source():
    log = _log("Process completed with exit code 1.",
               echo='\x1b[36;1m  echo "::error::${TIER}: Claude usage limit hit (HTTP ${api_status:-429})"\x1b[0m')
    assert wa.classify_failure(log, "failure")["class"] == "defect"


def test_classifier_taxonomy():
    for line, cause, cls in (  # each as an error annotation, then as plain output
        ("release-please failed: GitHub Actions is not permitted to create or approve pull requests.", "actions-permission", "config"),
        ("Bad credentials - https://docs.github.com/rest", "auth", "config"),
        ("API rate limit exceeded for installation ID 123.", "api-rate-limit", "transient"),
        ("Unable to resolve action `actions/checkout@v99`, unable to find version `v99`", "missing-ref", "config"),
        ("Dependabot encountered an error performing the update", "dependabot", "dependency"),
        ("npm error code EUSAGE", "deps-install", "dependency"),
        ("The runner has received a shutdown signal.", "infra", "transient"),
        ("__tests__/a.test.tsx(125,44): error TS2339: Property 'x' does not exist", "code", "defect"),
        ("version.rb (1.31.1) != manifest (1.31.0) — run ./scripts/bin/manifest and commit", "gate", "defect"),
        ("! [remote rejected] main -> main (GH006: Protected branch update failed)", "push-rejected", "config"),
        ("error: failed to push some refs to 'https://github.com/x/y'", "push-rejected", "config"),
        ("refusing to allow a GitHub App to create or update workflow `.github/workflows/x.yml` without `workflows` permission",
         "actions-permission", "config"),
        ("gh: API rate limit exceeded for user ID 1. (HTTP 403)", "api-rate-limit", "transient"),
        ("IOException: No space left on device", "infra", "transient"),
        ("=== 3 failed, 401 passed in 2.1s ===", "test", "defect"),
        ("FAILED tests/test_api.py::test_unauthorized_returns_403", "test", "defect"),
    ):
        c = wa.classify_failure(_log(line, "Process completed with exit code 1."), "failure")
        assert (c["cause"], c["class"]) == (cause, cls), (line, c)
        c = wa.classify_failure(f"2026-10-23T05:41:12.0Z {line}\n" + _log("Process completed with exit code 1."), "failure")
        assert (c["cause"], c["class"]) == (cause, cls), ("tail", line, c)
    assert wa.classify_failure("", "timed_out")["cause"] == "timeout"
    assert wa.classify_failure("", "startup_failure")["class"] == "config"
    assert wa.classify_failure(_log("[simulate] 92 passed, 0 failed", "Process completed with exit code 1."),
                               "failure")["cause"] == "exit-code"
    c = wa.classify_failure(_log("Process completed with exit code 1."), "failure")
    assert (c["cause"], c["evidence"]) == ("exit-code", "Process completed with exit code 1.")


def test_run_health_rolls_up_verdicts_ghosts_and_capacity_skips():
    runs = [
        {"id": 1, "workflow_path": ".github/workflows/a.yml", "event": "schedule", "status": "completed",
         "conclusion": "failure", "created_at": "2026-10-20T05:00:00Z", "run_started_at": "2026-10-20T05:00:00Z",
         "updated_at": "2026-10-20T05:10:00Z", "html_url": "u1"},
        {"id": 2, "workflow_path": ".github/workflows/a.yml", "event": "schedule", "status": "completed",
         "conclusion": "success", "created_at": "2026-10-21T05:00:00Z", "run_started_at": "2026-10-21T05:00:00Z",
         "updated_at": "2026-10-21T05:04:00Z", "html_url": "u2"},
        {"id": 3, "workflow_path": ".github/workflows/gone.yml", "event": "schedule", "status": "completed",
         "conclusion": "skipped", "created_at": "2026-10-21T05:00:00Z", "html_url": "u3"},
    ]
    logs = {1: [_log("Claude usage limit hit (HTTP 429)")],
            2: ["2026-10-21T05:03:00.0Z ##[warning]Tier 1: Claude usage limit hit (HTTP 429) — skipped"]}
    doc = wa.run_health(runs, logs, {1: "agent › Run the agent"}, {".github/workflows/a.yml"})
    a, gone = doc["workflows"]
    assert (a["runs"], a["success_rate"], a["verdict"], a["capacity_skips"]) == (2, 50.0, "healthy", 1)
    assert a["last_failure"]["class"] == "capacity" and a["last_failure"]["failed_step"] == "agent › Run the agent"
    assert a["p50_min"] in (4.0, 10.0) and doc["classes"] == {"capacity": 1}
    assert gone["ghost"] and gone["verdict"] == "skipping" and doc["ghosts"] == [".github/workflows/gone.yml"]


# --------------------------------------------------------------------------- #
# scaffold
# --------------------------------------------------------------------------- #
def test_every_scaffold_kind_passes_every_rule():
    fleet = wa.load_fleet(REPO_ROOT)
    for kind in wa.KINDS:
        out = wa.scaffold(kind, f"test-{kind}", purpose="Test: a purpose with a colon.", root=REPO_ROOT, fleet=fleet)
        assert out["findings"] == [], (kind, out["findings"])
        assert not out["exists"] and out["file"] == f".github/workflows/test-{kind}.yml"
        if kind in wa.SCHEDULED_KINDS:
            assert out["cron"] and not out["cron"].startswith("0 ")
            assert any(c["file"] == "_data/fleet.yml" and f"test_{kind.replace('-', '_')}:" in c["snippet"] for c in out["companion"])
    agent = wa.scaffold("agent-loop", "nightly-audit", root=REPO_ROOT, fleet=fleet)
    assert agent["switch"] == "NIGHTLY_AUDIT_ENABLED" and "usage-limit: skip" in agent["text"]
    assert any("budget.call_sites" in c["where"] for c in agent["companion"])


def test_scaffold_quotes_names_and_refuses_taken_keys():
    for name in ("Audit: nightly", "[wip] audit", "@bot audit", "{x}", "Yes", "audit #2"):
        out = wa.scaffold("agent-loop", "name-check", name, root=REPO_ROOT, fleet={})
        assert out["findings"] == [] and out["text"].startswith(f'name: "{name}"'), (name, out["findings"])
    try:
        wa.scaffold("loop", "rotate-tokens", root=REPO_ROOT)
    except ValueError as exc:
        assert "schedule.rotate_tokens" in str(exc)
    else:
        raise AssertionError("an id whose schedule key is token-rotation's was accepted")


def test_write_creates_only_and_never_follows_a_link():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github" / "workflows").mkdir(parents=True)
        outside = root / "outside.yml"
        (root / ".github" / "workflows" / "doc-check.yml").symlink_to(outside)   # dangling
        rc = wa.main(["--root", tmp, "new", "--kind", "gate", "--id", "doc-check", "--write"])
        assert rc == 1 and not outside.exists()
        assert wa.main(["--root", tmp, "new", "--kind", "gate", "--id", "doc-other", "--write"]) == 0
        assert (root / ".github" / "workflows" / "doc-other.yml").read_text().startswith('name: "Doc Other"')


def test_scaffold_refuses_bad_ids_names_and_crons():
    for kind, wid, name, cron in (("nope", "x-y", None, None), ("gate", "Bad_Id", None, None),
                                  ("gate", "ok-id", 'quote"d', None), ("gate", "ok-id", "-beta", None),
                                  ("loop", "ok-id", None, "0 3 * * *"),
                                  ("loop", "ok-id", None, "every day")):
        try:
            wa.scaffold(kind, wid, name, cron, root=REPO_ROOT, fleet={})
        except ValueError:
            continue
        raise AssertionError(f"accepted {(kind, wid, name, cron)}")


def test_suggested_cron_skips_taken_hours():
    assert wa.suggest_cron("loop", ["7 1 * * *", "7 2 * * 1"]) == "7 3 * * *"
    assert wa.suggest_cron("agent-loop", ["37 11 * * *"]) == "37 12 * * *"


# --------------------------------------------------------------------------- #
# the live tree
# --------------------------------------------------------------------------- #
def test_live_tree_parses_and_carries_no_error():
    atlas = wa.scan(REPO_ROOT)
    assert atlas["workflows"] and not [w["id"] for w in atlas["workflows"] if w["parse_error"]]
    errors = [f"{f['rule']} {f['file']}:{f['line']} {f['message']}" for f in atlas["findings"] if f["severity"] == "error"]
    assert not errors, "workflow lint errors:\n  " + "\n  ".join(errors)
    assert atlas["summary"]["workflows"] == len(list((REPO_ROOT / ".github" / "workflows").glob("*.yml")))


def test_live_tree_every_workflow_and_action_is_documented():
    atlas = wa.scan(REPO_ROOT)
    missing = [f["message"] for f in atlas["findings"] if f["rule"] == "undocumented"]
    assert not missing, "\n  ".join(missing)
    assert not [a["id"] for a in atlas["actions"] if not a["used_by"]], "an action with no caller"


# --------------------------------------------------------------------------- #
def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print("OK — workflow atlas tests" if not failures else f"FAIL — {failures} workflow atlas test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

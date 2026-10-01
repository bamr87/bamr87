#!/usr/bin/env python3
"""
Fixture + workflow-contract tests for the weekly fleet steward
(steward.py, .github/workflows/fleet-steward.yml, docs/STEWARD.md).

Guarded here:
  * every open item reaches the brief tagged with the LANE that already owns
    it — the issue pipeline's `agent:*` work, held items, dependabot, PRs in
    flight — so the orchestrator acts only where nobody else does;
  * the brief's order is deterministic and puts critical/bug/CI-red work first;
  * cross-repo THEMES need three repos, so a word in two titles is not a theme;
  * a malformed decision (a repo outside the fleet, a thin plan, a non-GitHub
    ref, an unknown risk) becomes "report only" — the developer never runs on it;
  * the record step writes the LOG and appends ONE ledger row per run, capped;
  * the workflow runs the models _data/fleet.yml names, on the bamr87 API key
    alone (claude-auth pinned to api_key, no OAuth token), is default-OFF on its
    schedule, opens DRAFT PRs only, never lets the developer push, and checks
    the target out with no persisted credential.

Dependency-light — PyYAML only:
    python3 .github/scripts/dash-gen/test_steward.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import steward  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
WF = REPO_ROOT / ".github" / "workflows" / "fleet-steward.yml"
FLEET = REPO_ROOT / "_data" / "fleet.yml"
CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


def triage_fixture() -> dict:
    def repo(name, issues=(), prs=(), external=False):
        return {"name": name, "nwo": f"bamr87/{name}", "external": external, "archived": False,
                "issues": {"open": len(issues), "bugs": 0, "stale": 0, "items": list(issues)},
                "prs": {"open": len(prs), "ci_failing": 0, "dependabot": 0, "items": list(prs)},
                "workflows": {"failing": []}, "attention": {"score": 10, "level": "amber"}}

    def iss(n, title, labels=(), age=5):
        return {"number": n, "title": title, "labels": list(labels), "age_days": age, "idle_days": 1,
                "url": f"https://github.com/x/y/issues/{n}"}

    def pr(n, title, ci="", dependabot=False):
        return {"number": n, "title": title, "draft": False, "dependabot": dependabot, "ci": ci,
                "age_days": 3, "idle_days": 1, "url": f"https://github.com/x/y/pull/{n}"}

    return {"generated_at": "2026-09-30 05:00 UTC", "repos_scanned": 4, "repos_unreachable": [],
            "totals": {"open_issues": 5, "open_prs": 4},
            "by_repo": [
                repo("alpha", [iss(1, "Jekyll build breaks on ruby 3.4", ["bug"]),
                               iss(2, "agent picked this", ["agent:ready"]),
                               iss(3, "please wait", ["human-review"])],
                     [pr(10, "chore(deps): bump rack", dependabot=True)]),
                repo("beta", [iss(4, "fix(ci): jekyll build fails under ruby 3.4", ["security"])],
                     [pr(11, "feat: new widget", ci="failure")]),
                repo("gamma", [iss(5, "docs: jekyll theme ruby notes")],
                     [pr(12, "fix: unrelated thing")]),
                repo("mirror", [iss(6, "not ours")], external=True),
            ]}


def test_candidates_carry_their_lane_and_skip_external_repos():
    cands = steward.candidates(triage_fixture())
    lanes = {(c["repo"], c["number"]): c["lane"] for c in cands}
    check("an agent:* issue belongs to the issue pipeline", lanes[("alpha", 2)] == "issue-pipeline")
    check("a human-review issue is held", lanes[("alpha", 3)] == "held")
    check("a dependabot PR is dependabot's", lanes[("alpha", 10)] == "dependabot")
    check("someone's PR is in flight", lanes[("beta", 11)] == "in-flight")
    check("an unlabelled bug is open — nobody owns it", lanes[("alpha", 1)] == "open")
    check("an external mirror's items are not candidates", ("mirror", 6) not in lanes)


def test_order_puts_critical_work_first_and_is_deterministic():
    a = steward.candidates(triage_fixture())
    b = steward.candidates(triage_fixture())
    check("the order is deterministic", [c["url"] for c in a] == [c["url"] for c in b])
    check("the security issue leads", a[0]["repo"] == "beta" and a[0]["number"] == 4)
    pos = {(c["repo"], c["number"]): i for i, c in enumerate(a)}
    check("a CI-red PR outranks a dependabot bump", pos[("beta", 11)] < pos[("alpha", 10)])


def test_themes_need_three_repos():
    cands = steward.candidates(triage_fixture())
    th = {t["theme"]: t for t in steward.themes(cands)}
    check("'jekyll' recurs in three repos → a theme", "jekyll" in th and len(th["jekyll"]["repos"]) == 3)
    check("'widget' is in one repo → not a theme", "widget" not in th)
    check("conventional-commit prefixes are not themes", "fix" not in th and "docs" not in th)


def test_brief_names_lanes_themes_and_recent_runs():
    cfg = steward.load_config(FLEET)
    ledger = {"runs": [{"date": "2026-09-24", "act": True, "title": "harmonize jekyll",
                        "pr_url": "https://github.com/bamr87/bamr87/pull/1"}]}
    brief, cands, th, plan = steward.build_plan(triage_fixture(), ledger, cfg, "focus on ruby", "2026-10-01")
    check("the brief quotes the operator focus", "focus on ruby" in brief)
    check("the brief lists the themes", "**jekyll**" in brief)
    check("the brief shows each item's lane", "| issue-pipeline |" in brief and "| held |" in brief)
    check("the brief remembers recent picks", "harmonize jekyll" in brief)
    check("the plan carries the last PR for backpressure",
          plan["last_pr_url"] == "https://github.com/bamr87/bamr87/pull/1")
    check("the plan names the models from fleet.yml", plan["models"] == cfg["models"])
    check("the plan counts only unowned items as actionable", plan["actionable"] == 3)


def test_validate_refuses_a_malformed_decision():
    cfg = steward.load_config(FLEET)
    targets = {"bamr87/bamr87": "main", "bamr87/alpha": "main"}
    good = {"act": True, "kind": "theme", "target": "bamr87/alpha", "title": "Pin nothing, fix jekyll on ruby 3.4",
            "refs": ["https://github.com/bamr87/alpha/issues/1"], "risk": "medium",
            "plan": "1. Reproduce the build failure. 2. Fix the Gemfile constraint. 3. Run bundle exec jekyll build."}
    v = steward.validate(good, targets, cfg)
    check("a sound decision acts, on the registry's base branch",
          v["act"] == "true" and v["base"] == "main" and v["key"].startswith("bamr87/alpha:"))
    for label, patch in [("a repo outside the fleet", {"target": "someone/else"}),
                         ("a thin plan", {"plan": "fix it"}),
                         ("a non-GitHub ref", {"refs": ["http://evil.example/x"]}),
                         ("an unknown risk", {"risk": "yolo"})]:
        v = steward.validate({**good, **patch}, targets, cfg)
        check(f"{label} → report only", v["act"] == "false" and v["reason"])
    v = steward.validate({"act": False, "title": "quiet week", "why_not": "nothing unowned"}, targets, cfg)
    check("act:false is honoured with its reason", v["act"] == "false" and "nothing unowned" in v["reason"])
    check("a non-object decision is refused", steward.validate("missing", targets, cfg)["act"] == "false")


def test_record_logs_the_run_and_caps_the_ledger():
    cfg = {**steward.load_config(FLEET), "history": 3}
    ledger = {"runs": [{"date": f"2026-09-0{i}", "run_url": f"r{i}"} for i in range(1, 4)]}
    verdict = {"act": "true", "target": "bamr87/alpha", "title": "Fix it", "risk": "low", "reason": ""}
    text, new = steward.record("# Update\n\nAll quiet.", {"kind": "issue", "refs": ["https://github.com/a/b/issues/1"]},
                               verdict, {"pr_url": "https://github.com/bamr87/alpha/pull/9", "cost_orchestrate": "1.5",
                                         "cost_develop": "2.25", "run_url": "r4"}, ledger, cfg, "2026-10-01")
    check("the log carries the update and the run's outcome",
          "All quiet." in text and "pull/9" in text and "$1.5" in text)
    check("the ledger keeps `history` rows, newest last",
          len(new["runs"]) == 3 and new["runs"][-1]["pr_url"].endswith("/pull/9"))
    check("spend is recorded as numbers", new["runs"][-1]["cost_develop"] == 2.25)


def test_the_workflow_honours_the_contract():
    wf = yaml.safe_load(WF.read_text())
    text = WF.read_text()
    fleet = yaml.safe_load(FLEET.read_text())
    sc = fleet["steward"]
    jobs = wf["jobs"]
    on = wf.get(True) or wf.get("on")
    check("the schedule matches fleet.yml", on["schedule"][0]["cron"] == fleet["schedule"]["fleet_steward"])
    check("the scheduled run is default-OFF (FLEET_STEWARD_ENABLED == 'true')",
          "vars.FLEET_STEWARD_ENABLED == 'true'" in jobs["scan"]["if"] and "!= 'schedule'" in jobs["scan"]["if"])

    def agent_step(job):
        return next(s for s in jobs[job]["steps"] if "claude-code-action" in str(s.get("uses", "")))

    def auth_step(job):
        return next(s for s in jobs[job]["steps"] if s.get("id") == "claude-auth")

    for job, role in (("orchestrate", "orchestrator"), ("develop", "developer")):
        step = agent_step(job)
        args = step["with"]["claude_args"]
        check(f"{job} runs {sc['models'][role]} (fleet.yml steward.models.{role})",
              f"--model {sc['models'][role]}" in args)
        check(f"{job} bills the API key only — never the OAuth token",
              step["with"]["claude_code_oauth_token"] == ""
              and "secrets.ANTHROPIC_API_KEY" in step["with"]["anthropic_api_key"]
              and "CLAUDE_CODE_OAUTH_TOKEN" not in str(step["with"]))
        a = auth_step(job)
        check(f"{job}'s credential step is pinned to api_key",
              a["with"]["order"] == "api_key" and str(a["with"]["has-oauth"]) == "false")
        allowed = args.split('--allowedTools "')[1].split('"')[0].split(",")
        check(f"{job} cannot push, merge or write through gh",
              not any(t.startswith(("Bash(git push", "Bash(git commit", "Bash(git checkout", "Bash(gh api",
                                    "Bash(gh pr create", "Bash(gh pr merge", "Bash(gh issue comment",
                                    "Bash(gh issue close", "Bash(gh issue edit")) for t in allowed))
    co = next(s for s in jobs["develop"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    check("the developer's checkout persists no credential", co["with"].get("persist-credentials") is False)
    check("the target comes from the validated decision, not the agent",
          "needs.orchestrate.outputs.target" in co["with"]["repository"])
    check("the PR is always a draft", "gh pr create" in text and "--draft" in text and "gh pr merge" not in text)
    check("one steward PR at a time (backpressure gates the developer)",
          "needs.scan.outputs.develop_allowed == 'true'" in jobs["develop"]["if"])
    check("the developer waits for an accepted decision",
          "needs.orchestrate.outputs.act == 'true'" in jobs["develop"]["if"])
    check("the record job logs even when development was skipped",
          jobs["record"]["if"].startswith("${{ always()"))
    check("the log is published through publish-data, never a bare push",
          any("publish-data" in str(s.get("uses", "")) for s in jobs["record"]["steps"]))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
        except Exception as exc:  # a crash is a failure with its reason, not a traceback wall
            check(f"{t.__name__} raised {type(exc).__name__}: {exc}", False)
    failed = [label for label, ok in CHECKS if not ok]
    for label, ok in CHECKS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print(f"\n{'FAILED' if failed else 'OK'} ({len(CHECKS) - len(failed)}/{len(CHECKS)} checks)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

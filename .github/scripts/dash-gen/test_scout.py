#!/usr/bin/env python3
"""
test_scout.py — fixture tests for the daily repo-scout loop (repo_scout.py +
.github/workflows/repo-scout.yml), in the house style: plain python, no
network, no pytest. Run: python3 .github/scripts/dash-gen/test_scout.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import yaml  # noqa: E402

import repo_scout as rs  # noqa: E402

ROOT = HERE.parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "repo-scout.yml"
FLEET = ROOT / "_data" / "fleet.yml"

FAILS: list[str] = []


def check(label: str, ok) -> None:
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        FAILS.append(label)


def entry(name, *, owner="bamr87", status="active", scout=None, category="dev-tools", slug=None):
    e = {"name": name, "slug": slug or name.lower(), "repo_url": f"https://github.com/{owner}/{name}",
         "branch": "main", "category": category, "status": status, "stack": ["python"],
         "description": f"{name} does things"}
    if scout is not None:
        e["scout"] = scout
    return e


def cfg():
    c = rs.load_config(FLEET)
    c["sample"] = 2
    return c


# --------------------------------------------------------------------------- #
def test_selection() -> None:
    print("\nselection")
    reg = [entry("alpha"), entry("beta", status="archived"), entry("gamma", owner="microsoft"),
           entry("delta", scout=False), entry("eps", status="experiment"), entry("zeta", status="retired"),
           {"name": "nourl", "repo_url": "https://example.com/x", "status": "active"}]
    cands, dropped = rs.eligible(reg, cfg())
    names = [c["name"] for c in cands]
    check("owned, active/experiment repos qualify", names == ["alpha", "eps"])
    reasons = {d["name"]: d["reason"] for d in dropped}
    check("archived is dropped", "archived" in reasons.get("beta", ""))
    check("external upstream is dropped", "external" in reasons.get("gamma", ""))
    check("scout: false opts out", "opted out" in reasons.get("delta", ""))
    check("a status outside scout.statuses is dropped", "statuses" in reasons.get("zeta", ""))
    check("a non-GitHub repo_url is dropped", "GitHub" in reasons.get("nourl", ""))
    _, d2 = rs.eligible(reg, cfg(), target="nope")
    check("an unknown --target is reported", any("not in the registry" in d["reason"] for d in d2))
    c3, _ = rs.eligible(reg, cfg(), target="beta")
    check("an explicit archived target yields nothing", c3 == [])


def test_rotation() -> None:
    print("\nrotation")
    reg = [entry(f"r{i:02d}") for i in range(7)]
    cands, _ = rs.eligible(reg, cfg())
    day = dt.date(2026, 10, 21)
    a = [t["name"] for t in rs.rotation_order(cands, 2, day)]
    b = [t["name"] for t in rs.rotation_order(cands, 2, day)]
    check("the same day gives the same order", a == b)
    nxt = [t["name"] for t in rs.rotation_order(cands, 2, day + dt.timedelta(days=1))]
    check("the next day starts `sample` repos further on", nxt[0] == a[2 % 7])
    seen = set()
    for i in range(rs.cycle_days(7, 2)):
        seen |= set(t["name"] for t in rs.rotation_order(cands, 2, day + dt.timedelta(days=i))[:2])
    check("every repo is visited within cycle_days", seen == {c["name"] for c in cands})
    check("cycle_days is ceil(n / sample)", rs.cycle_days(7, 2) == 4 and rs.cycle_days(0, 2) == 0)
    check("an empty set rotates to nothing", rs.rotation_order([], 2, day) == [])


def fake_gh(issues_by_repo: dict, no_issues: set[str] = frozenset()):
    def gh(cmd):
        if cmd[:3] == ["gh", "repo", "view"]:
            return {"hasIssuesEnabled": cmd[3] not in no_issues}
        nwo = cmd[cmd.index("-R") + 1]
        return issues_by_repo.get(nwo)
    return gh


def test_plan_backpressure_and_brief() -> None:
    print("\nplan + brief")
    c = cfg()
    reg = [entry("alpha"), entry("beta"), entry("gamma", category="docs")]
    marker = rs.marker_line(c, "bamr87/alpha")
    gh = fake_gh({
        "bamr87/alpha": [{"number": n, "title": f"scout proposal {n}", "url": "u", "labels": ["ai-scout"], "body": marker}
                         for n in range(1, 4)],
        "bamr87/beta": [{"number": 9, "title": "Existing open issue about caching", "url": "u", "labels": ["bug"], "body": ""}],
        "bamr87/gamma": [],
    })
    day = dt.date(2026, 1, 1)
    with tempfile.TemporaryDirectory() as tmp:
        pdir = Path(tmp) / "scout"; pdir.mkdir()
        (pdir / "scout-prompt.md").write_text("## Goals\nScout {{REPO_NAME}} ({{NWO}}) — up to {{MAX_ISSUES}} of {{KINDS}}; types {{TYPES}}.\n")
        cdir = Path(tmp) / "cat"; cdir.mkdir()
        (cdir / "docs.md").write_text("## Category emphasis: docs\n")
        plan, briefs = rs.build_plan(reg, c, None, None, day=day, prompt_dir=pdir, category_dir=cdir, gh=gh, now="now")
        names = [t["name"] for t in plan["include"]]
        check("a repo at max_open_per_repo is skipped and the rotation moves on", "alpha" not in names)
        check("the skip is explained", any("still open" in s["reason"] for s in plan["skipped"]))
        check("the sample is filled from the rest", plan["count"] == 2 and set(names) == {"beta", "gamma"})
        gh2 = fake_gh({"bamr87/alpha": [], "bamr87/beta": [], "bamr87/gamma": []}, no_issues={"bamr87/alpha"})
        plan_ni, _ = rs.build_plan(reg, c, None, None, day=day, prompt_dir=pdir, category_dir=cdir, gh=gh2, now="now")
        check("a repo with Issues disabled is skipped with a reason",
              "alpha" not in [x["name"] for x in plan_ni["include"]]
              and any("disabled" in x["reason"] for x in plan_ni["skipped"]))
        check("plan.json carries the caps the workflow reads",
              plan["max_turns"] == c["max_turns"] and plan["model"] == c["model"]
              and plan["max_issues_per_repo"] == c["max_issues_per_repo"] and plan["label"] == c["label"])
        b = briefs["scout-workorder-beta.md"]
        check("brief starts with the hidden marker", b.splitlines()[0] == rs.marker_line(c, "bamr87/beta"))
        check("brief lists the open issues so they are not proposed again",
              "## Open issues — do NOT propose" in b and "#9 Existing open issue about caching" in b)
        check("brief renders the template placeholders", "Scout beta (bamr87/beta)" in b and "up to 3 of feature, fix, update" in b)
        check("brief carries the category emphasis", "Category emphasis: docs" in briefs["scout-workorder-gamma.md"])
        check("brief says when no earlier proposals are open", "first visit" in b)
        # offline: no gh → no backpressure, honest dedupe flag
        plan2, _ = rs.build_plan(reg, c, None, None, day=day, prompt_dir=pdir, category_dir=cdir, gh=None, now="now")
        check("offline plans mark dedupe unavailable", all(t["dedupe"] == "unavailable" for t in plan2["include"]))
        # explicit target bypasses the rotation and the sample
        plan3, _ = rs.build_plan(reg, c, None, None, day=day, target="gamma", prompt_dir=pdir, category_dir=cdir, gh=gh, now="now")
        check("--target picks exactly that repo", [t["name"] for t in plan3["include"]] == ["gamma"])


def test_proposals() -> None:
    print("\nproposals → issues")
    c = cfg()
    good = {"title": "Add --help to the CLI entrypoint", "kind": "feature", "type": "feature", "priority": "P2",
            "size": "size:s", "body": "## Problem\n" + "x" * 100}
    raw = [good,
           {"title": "short", "kind": "fix", "body": "x" * 100},
           {"title": "A fine title for a proposal", "kind": "wat", "body": "x" * 100},
           {"title": "Another fine title here", "kind": "update", "body": "too short"},
           {"title": "Weird labels get normalised", "kind": "fix", "type": "nope", "priority": "P9", "size": "huge", "body": "y" * 100},
           "not an object"]
    ok, rejected = rs.validate_proposals(raw, c)
    check("valid proposals pass, invalid ones are rejected with reasons", len(ok) == 2 and len(rejected) == 4)
    check("labels are drawn from the pipeline taxonomy plus the scout label",
          ok[0]["labels"] == [c["label"], "feature", "P2", "size:s"])
    check("an unknown type/priority/size falls back to kind→type, P3, size:s",
          ok[1]["labels"] == [c["label"], "bug", "P3", "size:s"])
    leaks = [dict(good, body=good["body"] + "\ntoken: ghp_" + "A" * 36),
             dict(good, body=good["body"] + "\ngithub_pat_" + "b" * 60),
             dict(good, title="Rotate sk-ant-oat01-" + "c" * 30),
             dict(good, body=good["body"] + "\n-----BEGIN OPENSSH PRIVATE KEY-----")]
    ok_l, rej_l = rs.validate_proposals(leaks, c)
    check("a proposal carrying a credential-shaped string is withheld", not ok_l and len(rej_l) == len(leaks))
    check("the rejection never echoes the credential",
          all("ghp_" not in str(r) and "sk-ant" not in str(r) and "github_pat_" not in str(r) for r in rej_l))
    check("duplicate detection: exact match after normalisation",
          rs.is_duplicate("Add --help to the CLI entrypoint!", ["add help to the cli entrypoint"], 0.6) is not None)
    check("duplicate detection: word overlap",
          rs.is_duplicate("Add a --help flag to the CLI entrypoint", ["Add --help flag for CLI entrypoint command"], 0.6) is not None)
    check("different proposals are not duplicates",
          rs.is_duplicate("Document the release process", ["Fix the broken Docker build"], 0.6) is None)

    calls: list[list[str]] = []

    def gh(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "create"]:
            return "https://github.com/bamr87/alpha/issues/42"
        return ""

    titles = ["Add --help output to the CLI entrypoint", "Document the release process in README",
              "Fix the Docker build on arm64 runners", "Drop the committed lockfile per fleet policy",
              "Cover the parser with a regression test"]
    many = [dict(good, title=t) for t in titles]
    ok, _ = rs.validate_proposals(many, c)
    res = rs.file_proposals("bamr87/alpha", ok, c, existing_titles=[titles[0]],
                            run_url="https://run", apply=True, gh=gh)
    check("an open issue with the same title is skipped", any("duplicates" in s["reason"] for s in res["skipped"]))
    check("the batch is capped at max_issues_per_repo", len(res["filed"]) == c["max_issues_per_repo"]
          and any("over max_issues_per_repo" in s["reason"] for s in res["skipped"]))
    check("every filed issue has a URL from gh issue create", all(f["url"] for f in res["filed"]))
    creates = [x for x in calls if x[:3] == ["gh", "issue", "create"]]
    labels_created = [x for x in calls if x[:3] == ["gh", "label", "create"]]
    check("labels are created (--force) before the first issue", labels_created and calls.index(labels_created[0]) < calls.index(creates[0])
          and all("--force" in x for x in labels_created))
    check("issues are filed in the target repo with the scout label",
          all("-R" in x and x[x.index("-R") + 1] == "bamr87/alpha" and c["label"] in x[x.index("--label") + 1] for x in creates))
    body = rs.issue_body(ok[0], c, "bamr87/alpha", "https://run")
    check("the marker is the FIRST line of the issue body", body.splitlines()[0] == rs.marker_line(c, "bamr87/alpha"))
    check("the body names the run and the hold label", "https://run" in body and "agent:hold" in body)
    dry = rs.file_proposals("bamr87/alpha", ok[:1], c, existing_titles=[], apply=False, gh=gh)
    check("a dry run files nothing and calls no writing verb",
          dry["filed"] and dry["filed"][0]["url"] is None and len(creates) == c["max_issues_per_repo"])
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "proposals.json"
        check("a missing proposals file is an empty, valid result", rs.load_proposals(p) == ([], ""))
        p.write_text("{not json")
        check("a corrupt proposals file files nothing", rs.load_proposals(p) == ([], ""))
        p.write_text(json.dumps({"proposals": [good], "notes": "fine"}))
        check("a proposals object carries notes", rs.load_proposals(p) == ([good], "fine"))


def step(job: dict, name: str) -> dict:
    for s in job["steps"]:
        if s.get("name") == name:
            return s
    raise AssertionError(f"repo-scout.yml: no step named {name!r}")


def test_workflow_contract() -> None:
    print("\nworkflow ↔ fleet.yml")
    raw = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(raw)
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    cron = (on.get("schedule") or [{}])[0].get("cron")
    check("cron matches _data/fleet.yml schedule.repo_scout", cron == fleet["schedule"]["repo_scout"])
    check("write-capable scheduled workflow has a concurrency group", bool((wf.get("concurrency") or {}).get("group")))
    plan, scout, file_ = wf["jobs"]["plan"], wf["jobs"]["scout"], wf["jobs"]["file"]
    check("every job sets timeout-minutes", all(j.get("timeout-minutes") for j in (plan, scout, file_)))
    check("a NEW loop starts OFF: the cron runs only when REPO_SCOUT_ENABLED == 'true', a dispatch always",
          "vars.REPO_SCOUT_ENABLED == 'true'" in str(plan.get("if")) and "github.event_name != 'schedule'" in str(plan.get("if")))
    check("scout needs plan, file needs both (needs:, not workflow_run)",
          scout.get("needs") == "plan" and set(file_.get("needs") or []) == {"plan", "scout"})
    check("plan probes the fleet token for real (gh api user)", "gh api user" in step(plan, "Probe fleet write token")["run"])
    check("plan fails loudly without Claude auth", "exit 1" in step(plan, "Require Claude auth")["run"])
    check("plan builds the matrix with dash-gen scout", "scout --target" in step(plan, "Build the plan")["run"])
    check("dispatch inputs reach the script via env, not inline expressions",
          "$TARGET" in step(plan, "Build the plan")["run"] and "$FOCUS" in step(plan, "Build the plan")["run"])
    strat = scout["strategy"]
    check("fail-fast is off", strat.get("fail-fast") is False)
    check("max-parallel and matrix are wired from the plan",
          "needs.plan.outputs.max_parallel" in str(strat.get("max-parallel")) and "needs.plan.outputs.matrix" in str(strat.get("matrix")))
    co = next(s for s in scout["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    check("target checkout keeps no credentials", co["with"].get("persist-credentials") is False)
    check("target checkout is the matrix repo on the matrix branch",
          "matrix.nwo" in str(co["with"].get("repository")) and "matrix.branch" in str(co["with"].get("ref")))
    check("the brief is hidden from git", ".git/info/exclude" in step(scout, "Hide the brief from git")["run"])
    auth = step(scout, "Choose the Claude credential (ai_auth order)")
    check("the credential is chosen by the repo's ai_auth order",
          auth["uses"].startswith("bamr87/bamr87/.github/actions/claude-auth@") and "vars.CLAUDE_AUTH_ORDER" in auth["with"]["order"])
    sc = step(scout, "Scout")
    args = sc["with"]["claude_args"]
    prompt = " ".join(sc["with"]["prompt"].split())
    check("each credential is gated on the chosen method",
          "steps.claude-auth.outputs.method == 'oauth'" in sc["with"]["claude_code_oauth_token"]
          and "steps.claude-auth.outputs.method == 'api_key'" in sc["with"]["anthropic_api_key"])
    m = re.search(r"--max-turns\s+(\d+)", args)
    check("--max-turns literal equals fleet.yml scout.max_turns", m and int(m.group(1)) == int(fleet["scout"]["max_turns"]))
    m = re.search(r"--max-budget-usd\s+(\d+)", args)
    check("--max-budget-usd literal equals budget.call_sites[repo-scout.yml:scout]",
          m and int(m.group(1)) == int(fleet["budget"]["call_sites"]["repo-scout.yml:scout"]))
    check("the model comes from the plan (fleet.yml scout.model)", "--model ${{ needs.plan.outputs.model }}" in args)
    m = re.search(r'--allowedTools\s+"([^"]+)"', args)
    allowed = {t.strip() for t in m.group(1).split(",")} if m else set()
    check("allowlist grants Read/Grep/Glob/Write (the one file it produces)", {"Read", "Grep", "Glob", "Write"} <= allowed)
    check("allowlist does NOT grant Edit", "Edit" not in allowed)
    for bad in ("Bash(git push:*)", "Bash(git checkout:*)", "Bash(git commit:*)", "Bash(gh issue create:*)",
                "Bash(gh issue edit:*)", "Bash(gh issue close:*)", "Bash(gh pr create:*)", "Bash(gh:*)", "Bash(git:*)", "Bash"):
        check(f"allowlist does NOT grant `{bad}`", bad not in allowed)
    # The allowlist runs interpreters that can read any env var, so the agent
    # step must hold no GitHub credential at all — not merely no writing verb.
    check("allowlist grants no `gh` verb", not any(t.startswith("Bash(gh ") for t in allowed))
    check("the agent step carries no GitHub token",
          not any(k in (sc.get("env") or {}) for k in ("GH_TOKEN", "GITHUB_TOKEN"))
          and "FLEET_TOKEN" not in yaml.safe_dump(sc))
    check("prompt tells the agent to read its brief", ".scout/${{ matrix.brief }}" in prompt)
    check("prompt names the proposals file and shape", ".scout/proposals.json" in prompt and '"proposals"' in prompt)
    check("prompt states the lanes", "fleet doctor" in prompt and "issue pipeline" in prompt and "open pr" in prompt.lower())
    check("prompt says the agent proposes and the workflow files", "never create an issue" in prompt and "the workflow FILES" in prompt)
    check("prompt carries the always-latest / no-lockfile rule", "lockfile" in prompt)
    cost = step(scout, "Report Claude run cost")
    check("cost is reported on success too", "!cancelled()" in str(cost.get("if")) and "failure()" not in str(cost.get("if")))
    check("a budget abort is called out as an error", "BUDGET CAP HIT" in cost["run"])
    check("the credential-rejected classifier is present", "modelUsage" in cost["run"])
    check("a scout that edited tracked files is discarded and reported",
          "git checkout -- ." in step(scout, "Verify the tree is untouched")["run"])
    up = step(scout, "Upload proposals")
    check("proposals travel as an artifact; none is a valid outcome", up["with"].get("if-no-files-found") == "ignore")
    fs = step(file_, "File the issues")
    check("the file job is the only GitHub writer and uses FLEET_TOKEN",
          "secrets.FLEET_TOKEN" in str(fs["env"].get("GH_TOKEN")) and "scout-file" in fs["run"])
    check("a dry run passes no --apply", "DRY_RUN" in fs["run"] and 'apply=()' in fs["run"])
    check("the workflow never merges, closes, or edits an issue",
          "gh pr merge" not in raw and "gh issue close" not in raw and "gh issue edit" not in raw and "--auto" not in raw)
    check("no scout job step pushes", "git push" not in yaml.safe_dump(scout))


def main() -> int:
    for fn in (test_selection, test_rotation, test_plan_backpressure_and_brief, test_proposals, test_workflow_contract):
        fn()
    print("\nOK — repo-scout fixture tests" if not FAILS else f"\nFAIL — {len(FAILS)} check(s):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

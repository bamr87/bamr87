#!/usr/bin/env python3
"""
Fixture tests for tools/branch_policy.py and the `branches:` block of _data/fleet.yml
(docs/BRANCHING.md, ADR 0015, UPS-QA-35/36): the policy honours constitution § 12.2, every
branch name the hub's own tools create is declared, the ruleset is planned before it is
written, and the audit finds the protection the old protect-branch.sh applied.

No network, no pytest: `gh api` is a fake. Needs only PyYAML:

    python3 tools/test_branch_policy.py
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

import branch_policy as bp  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
POLICY = bp.load_policy()


# --------------------------------------------------------------------------- #
# A fake `gh api`
# --------------------------------------------------------------------------- #
class FakeGh:
    """Answers `gh api -X METHOD PATH` from a table; records every call."""

    def __init__(self, table: dict):
        self.table = table
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, argv, stdin=None):
        method, path = argv[argv.index("-X") + 1], argv[argv.index("-X") + 2]
        body = json.loads(stdin) if stdin else None
        self.calls.append((method, path, body))
        key = (method, path.split("?")[0])
        hit = self.table.get(key, 404)
        if isinstance(hit, int):
            return subprocess.CompletedProcess(argv, 1, "", f"gh: Not Found (HTTP {hit})")
        return subprocess.CompletedProcess(argv, 0, json.dumps(hit), "")

    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def repo_table(slug="bamr87/app", *, merge_commit=True, rulesets=(), effective=(), classic=None,
               seen=("ci / ci", "ci / changes"), statuses=()):
    t = {
        ("GET", f"repos/{slug}"): {
            "default_branch": "main", "private": False, "allow_merge_commit": merge_commit,
            "allow_squash_merge": True, "allow_rebase_merge": True, "permissions": {"admin": True}},
        ("GET", f"repos/{slug}/rulesets"): [{"id": r["id"], "name": r["name"]} for r in rulesets],
        ("GET", f"repos/{slug}/rules/branches/main"): list(effective),
        ("GET", f"repos/{slug}/branches/main/protection"): classic if classic is not None else 404,
        ("GET", f"repos/{slug}/commits/main/check-runs"): {"check_runs": [{"name": n, "head_sha": "abc1234def"} for n in seen]},
        ("GET", f"repos/{slug}/commits/main/status"): {"sha": "abc1234def", "statuses": [{"context": c} for c in statuses]},
        ("POST", f"repos/{slug}/rulesets"): {"id": 77},
        ("DELETE", f"repos/{slug}/branches/main/protection"): {},
    }
    for r in rulesets:
        t[("GET", f"repos/{slug}/rulesets/{r['id']}")] = r
        t[("PUT", f"repos/{slug}/rulesets/{r['id']}")] = r
    return t


def run(argv, table):
    fake = FakeGh(table)
    rc = bp.main(argv, runner=fake)
    return rc, fake


# The classic protection the old tools/protect-branch.sh PUT on a repo.
OLD_SCRIPT = {"required_status_checks": {"strict": True, "contexts": ["CI / ci"]},
              "required_pull_request_reviews": {"required_approving_review_count": 1},
              "required_linear_history": {"enabled": True},
              "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False}}


# --------------------------------------------------------------------------- #
# The policy
# --------------------------------------------------------------------------- #
def test_policy_honours_section_12():
    assert POLICY.default == "main"
    assert POLICY.merge_method == "merge", "§ 12.2: a merge commit, never squash or rebase"
    assert POLICY.approvals == 0, "the review gate is the needs-amr label (§ 12.3-12.4)"
    assert POLICY.strict is False and POLICY.admin_bypass is True
    assert "claude/" in POLICY.sessions, "Claude Code cloud sessions name their own branch"
    doc = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
    assert doc["branches"]["protection"]["linear_history"] is False


def test_policy_refuses_what_contradicts_the_constitution():
    doc = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
    bad = copy.deepcopy(doc)
    bad["branches"]["protection"]["linear_history"] = True
    for broken, why in ((bad, "linear_history must be false"),):
        try:
            bp.policy_from(broken)
        except bp.PolicyError as e:
            assert why in str(e), e
        else:
            raise AssertionError(f"accepted {why}")
    dup = copy.deepcopy(doc)
    dup["branches"]["automation"].append({"prefix": "fix/", "owner": "x"})
    try:
        bp.policy_from(dup)
    except bp.PolicyError as e:
        assert "declared twice" in str(e), e
    else:
        raise AssertionError("accepted a prefix declared twice")
    squash = copy.deepcopy(doc)
    squash["branches"]["merge_method"] = "fast-forward"
    try:
        bp.policy_from(squash)
    except bp.PolicyError:
        pass
    else:
        raise AssertionError("accepted an unknown merge method")


def test_classify():
    cases = {"main": "default", "refs/heads/main": "default", "feature/x": "work", "feat/x": "work",
             "ci/pr-review": "work", "style/markdown-oneline": "work", "claude/eager-hawking-ow8ke1": "session",
             "chore/jev-ratify": "automation", "chore/jev-numbering": "automation", "chore/token-rotation": "work",
             "agent/issue-14": "automation", "ai-evolution/2026-11-21-1": "automation", "wip/mac/feature/x": "automation",
             "wtd/repo-map-docs": "automation", "dependabot/pip/pyyaml-6": "automation",
             "release-please--branches--main": "automation", "hotfix/x": "unknown", "fix/": "unknown", "": "unknown"}
    for name, kind in cases.items():
        assert bp.classify(name, POLICY)[0] == kind, (name, bp.classify(name, POLICY), kind)


def _created_branch_names() -> set[str]:
    """Every branch name the hub's own tools and workflows create, `${…}` filled with a sample."""
    names: set[str] = set()
    fill = lambda s: re.sub(r"\$\{[^}]*\}|\$[A-Z_]+", "1", s)  # noqa: E731
    for path in [HUB / "tools" / "fanout.sh", HUB / "tools" / "adopt-release.sh"]:
        for m in re.finditer(r'^\s*BRANCH="([^"$][^"]*)"', path.read_text(encoding="utf-8"), re.MULTILINE):
            names.add(fill(m.group(1)))
    for wf in (HUB / ".github" / "workflows").glob("*.yml"):
        for m in re.finditer(r"^\s+branch:\s*([A-Za-z0-9._/-]+)\s*$", wf.read_text(encoding="utf-8"), re.MULTILINE):
            names.add(m.group(1))
    for py in [HUB / ".github" / "scripts" / "dash-gen" / "agent_fill.py"]:
        names.update(re.findall(r'"branch":\s*"([^"]+)"', py.read_text(encoding="utf-8")))
    fleet = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
    names.add(f"{fleet['issue_pipeline']['branch_prefix']}-14")
    names.add(f"{fleet['evolution']['branch_prefix']}/2026-11-21-1")
    names.add("chore/jev-ratify")
    names.add("wip/mac/feature/x")
    return names


def test_every_branch_the_hub_creates_is_declared():
    names = _created_branch_names()
    assert len(names) >= 20, f"the scan found too few branch names to mean anything: {sorted(names)}"
    unknown = sorted(n for n in names if bp.classify(n, POLICY)[0] == "unknown")
    assert not unknown, f"declare these in _data/fleet.yml branches: (or rename them): {unknown}"


def test_pipeline_prefixes_are_automation():
    fleet = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
    for name in (f"{fleet['issue_pipeline']['branch_prefix']}-14", f"{fleet['evolution']['branch_prefix']}/x"):
        assert bp.classify(name, POLICY)[0] == "automation", name


def test_ratify_automation_prefixes_are_declared():
    from tools.jev import ratify
    for pre in ratify.AUTOMATION_PREFIXES:
        assert bp.classify(pre + "x", POLICY)[0] == "automation", f"jev ratify treats {pre} as automation; declare it"


# --------------------------------------------------------------------------- #
# The ruleset
# --------------------------------------------------------------------------- #
def test_desired_ruleset_is_merge_commit_only():
    rs = bp.desired_ruleset(POLICY, checks=["ci / ci"], approvals=0, strict=False, admin_bypass=True)
    types = [r["type"] for r in rs["rules"]]
    assert "required_linear_history" not in types
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(types)
    pr = next(r for r in rs["rules"] if r["type"] == "pull_request")["parameters"]
    assert pr["allowed_merge_methods"] == ["merge"] and pr["required_approving_review_count"] == 0
    sc = next(r for r in rs["rules"] if r["type"] == "required_status_checks")["parameters"]
    assert sc["required_status_checks"] == [{"context": "ci / ci"}] and sc["strict_required_status_checks_policy"] is False
    assert rs["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert rs["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    none = bp.desired_ruleset(POLICY, checks=[], approvals=2, strict=False, admin_bypass=False)
    assert "required_status_checks" not in [r["type"] for r in none["rules"]] and none["bypass_actors"] == []


def test_diff_ignores_live_defaults_and_names_real_changes():
    want = bp.desired_ruleset(POLICY, checks=["ci / ci"], approvals=0, strict=False, admin_bypass=True)
    live = copy.deepcopy(want)
    live["id"] = 9
    next(r for r in live["rules"] if r["type"] == "pull_request")["parameters"]["required_reviewers"] = []
    assert bp.diff_ruleset(live, want) == []
    next(r for r in live["rules"] if r["type"] == "pull_request")["parameters"]["allowed_merge_methods"] = ["squash"]
    live["rules"].append({"type": "required_linear_history"})
    changes = bp.diff_ruleset(live, want)
    assert any(c.startswith("change rule pull_request") for c in changes), changes
    assert "remove rule required_linear_history" in changes, changes


# --------------------------------------------------------------------------- #
# protect: plan first, write only with --apply
# --------------------------------------------------------------------------- #
def test_plan_is_a_dry_run():
    rc, fake = run(["protect", "bamr87/app", "--checks", "ci / ci"], repo_table())
    assert rc == 0
    assert fake.writes() == [], f"a plan wrote: {fake.writes()}"


def test_apply_creates_then_is_idempotent():
    rc, fake = run(["protect", "bamr87/app", "--checks", "ci / ci", "--apply"], repo_table())
    assert rc == 0 and fake.writes() == [("POST", "repos/bamr87/app/rulesets")], fake.writes()
    body = next(b for m, _, b in fake.calls if m == "POST")
    assert next(r for r in body["rules"] if r["type"] == "pull_request")["parameters"]["allowed_merge_methods"] == ["merge"]
    live = dict(body, id=77)
    rc, fake = run(["protect", "bamr87/app", "--apply"], repo_table(rulesets=[live]))
    assert rc == 0 and fake.writes() == [], f"a matching ruleset was rewritten: {fake.writes()}"


def test_update_keeps_the_live_checks_and_fixes_the_merge_method():
    live = bp.desired_ruleset(POLICY, checks=["ci / ci"], approvals=0, strict=False, admin_bypass=True)
    live["id"] = 5
    next(r for r in live["rules"] if r["type"] == "pull_request")["parameters"]["allowed_merge_methods"] = ["squash", "rebase"]
    rc, fake = run(["protect", "bamr87/app", "--apply"], repo_table(rulesets=[live]))
    assert rc == 0 and fake.writes() == [("PUT", "repos/bamr87/app/rulesets/5")], fake.writes()
    body = next(b for m, _, b in fake.calls if m == "PUT")
    checks = next(r for r in body["rules"] if r["type"] == "required_status_checks")["parameters"]["required_status_checks"]
    assert checks == [{"context": "ci / ci"}]


def test_refuses_a_check_that_never_reports():
    # The old default: "CI / ci" is the UI's "<workflow> / <job>", not the check run's name.
    rc, fake = run(["protect", "bamr87/app", "--checks", "CI / ci", "--apply"], repo_table())
    assert rc == 1 and fake.writes() == [], fake.writes()
    rc, fake = run(["protect", "bamr87/app", "--checks", "pr-only", "--allow-unseen", "--apply"], repo_table())
    assert rc == 0 and fake.writes() == [("POST", "repos/bamr87/app/rulesets")]


def test_refuses_when_the_repo_disallows_merge_commits():
    rc, fake = run(["protect", "bamr87/app", "--checks", "ci / ci", "--apply"], repo_table(merge_commit=False))
    assert rc == 1 and fake.writes() == []


def test_drop_classic_deletes_after_the_ruleset_lands():
    rc, fake = run(["protect", "bamr87/app", "--checks", "ci / ci", "--apply", "--drop-classic"],
                   repo_table(classic=OLD_SCRIPT))
    assert rc == 0
    assert fake.writes() == [("POST", "repos/bamr87/app/rulesets"), ("DELETE", "repos/bamr87/app/branches/main/protection")]
    rc, fake = run(["protect", "bamr87/app", "--checks", "ci / ci", "--drop-classic"], repo_table(classic=OLD_SCRIPT))
    assert rc == 0 and fake.writes() == [], "--drop-classic without --apply is still a plan"


def test_json_plan():
    fake = FakeGh(repo_table())
    out = _capture(lambda: bp.main(["protect", "bamr87/app", "--checks", "ci / ci", "--json"], runner=fake))
    doc = json.loads(out)
    assert doc["checks"] == ["ci / ci"] and doc["changes"] and doc["refusals"] == [] and doc["approvals"] == 0


# --------------------------------------------------------------------------- #
# check: the audit
# --------------------------------------------------------------------------- #
def _findings(table):
    st = bp.read_state(bp.Gh(FakeGh(table)), "bamr87/app", POLICY)
    return bp.findings(POLICY, st)


def test_check_finds_what_the_old_script_applied():
    fs = _findings(repo_table(classic=OLD_SCRIPT))
    errors = [f["text"] for f in fs if f["severity"] == "error"]
    warns = [f["text"] for f in fs if f["severity"] == "warn"]
    assert any("linear history" in e for e in errors), errors
    assert any("'CI / ci'" in e and "has not reported" in e for e in errors), errors
    assert any("1 approval" in w for w in warns), warns
    assert any("not applied" in w for w in warns), warns
    rc, fake = run(["check", "bamr87/app"], repo_table(classic=OLD_SCRIPT))
    assert rc == 1 and fake.writes() == []


def test_check_reads_every_ruleset_that_applies():
    effective = [{"type": "required_linear_history", "ruleset_id": 3, "ruleset_source": "bamr87/app"},
                 {"type": "pull_request", "ruleset_id": 3, "parameters": {"allowed_merge_methods": ["squash"]}}]
    errors = [f["text"] for f in _findings(repo_table(effective=effective)) if f["severity"] == "error"]
    assert any("linear history" in e for e in errors) and any("allows only squash" in e for e in errors), errors


def test_check_passes_a_repo_on_the_fleet_ruleset():
    want = bp.desired_ruleset(POLICY, checks=["ci / ci"], approvals=0, strict=False, admin_bypass=True)
    live = dict(want, id=7)
    effective = [dict(r, ruleset_id=7, ruleset_source="bamr87/app") for r in want["rules"]]
    fs = _findings(repo_table(rulesets=[live], effective=effective))
    assert fs == [], fs
    rc, _ = run(["check", "bamr87/app"], repo_table(rulesets=[live], effective=effective))
    assert rc == 0


def test_check_flags_merge_commits_turned_off():
    errors = [f for f in _findings(repo_table(merge_commit=False)) if f["severity"] == "error"]
    assert errors and "allow_merge_commit=true" in errors[0]["fix"], errors


# --------------------------------------------------------------------------- #
# Repo names and the wrapper
# --------------------------------------------------------------------------- #
def test_resolve_repo_uses_the_registry():
    with tempfile.TemporaryDirectory() as d:
        reg = Path(d) / "projects.yml"
        reg.write_text("- name: site\n  slug: site\n  repo_url: https://github.com/bash-365/site\n", encoding="utf-8")
        assert bp.resolve_repo("site", None, reg) == "bash-365/site"
        assert bp.resolve_repo("projects/site/", None, reg) == "bash-365/site"
        assert bp.resolve_repo("site", "other", reg) == "other/site"
        assert bp.resolve_repo("o/r", None, reg) == "o/r"
        assert bp.resolve_repo("unknown", None, reg) == "bamr87/unknown"


def test_wrapper_routes_to_the_tool():
    env = dict(os.environ, PYTHON="echo")
    sh = str(HUB / "tools" / "protect-branch.sh")
    out = subprocess.run(["bash", sh, "app", "--checks", "ci / ci"], capture_output=True, text=True, env=env, check=False)
    assert out.returncode == 0 and out.stdout.split()[1:3] == ["protect", "app"], out
    out = subprocess.run(["bash", sh, "a", "b", "--check"], capture_output=True, text=True, env=env, check=False)
    assert out.returncode == 0 and out.stdout.split()[1:] == ["check", "a", "b"], out
    out = subprocess.run(["bash", sh], capture_output=True, text=True, env=env, check=False)
    assert out.returncode == 2 and "--apply" in out.stderr, out


def _capture(fn) -> str:
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            out = _capture(t)
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

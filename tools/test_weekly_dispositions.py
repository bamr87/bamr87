#!/usr/bin/env python3
"""Offline tests for tools/weekly/closeout.py: the disposition rules and the live review gate. The
module reads and lists; these tests also hold it to never issuing a write. No network: `gh` is a
function the tests supply. Run: python3 tools/test_weekly_dispositions.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.weekly import closeout  # noqa: E402

NOW = datetime(2026, 11, 13, 5, 37, tzinfo=timezone.utc)
GATE = {"labels": {"gate": ["needs-amr"], "hold": ["agent:hold", "blocked"]}}
FLEET = {"jev": {"allowed_authors": ["bamr87", "github-actions[bot]", "app/github-actions", "claude[bot]"]},
         "weekly": {"closeout": {"never_merge": ["o/locked"], "repo_gate_paths": {"o/quests": [r"(^|/)pages/_quests/"]}}}}
CFG = closeout.config(FLEET)
WHO = closeout.trust(FLEET)
GREEN = {"mergeable": "MERGEABLE", "merge_state": "CLEAN", "checks": "SUCCESS", "review": None}
HEAD = "a" * 40
FACTS = {"allow_merge_commit": True, "default_branch": "main", "private": False}


def changed(*paths, kind="MODIFIED"):
    return [{"path": path, "changeType": kind} for path in paths]


def pr(number=1, repo="o/r", author="bamr87", labels=(), draft=False, updated="2026-11-12T00:00:00Z", enrich=GREEN, **more):
    return {"type": "pr", "repo": repo, "number": number, "title": f"pr {number}", "url": f"https://x/{number}", "author": author,
            "labels": list(labels), "draft": draft, "created_at": "2026-10-01T00:00:00Z", "updated_at": updated,
            "enrich": dict(enrich) if enrich else None, **more}


def dispose(rec, kinds=(), why=None):
    return closeout.dispose_pr(rec, kinds, why or {}, CFG, GATE, WHO, NOW)


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


def live(**over):
    """A `gh pr view` document for a pull request nothing holds."""
    doc = {"number": 1, "state": "OPEN", "isDraft": False, "title": "fix: a thing", "mergeable": "MERGEABLE",
           "mergeStateStatus": "CLEAN", "reviewDecision": None, "headRefOid": HEAD, "headRefName": "fix/a-thing",
           "baseRefName": "main", "labels": [], "files": [{"path": "src/app.py", "changeType": "MODIFIED"}],
           "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}],
           "author": {"login": "bamr87", "is_bot": False}, "updatedAt": "2026-11-12T00:00:00Z"}
    doc.update(over)
    return doc


class Gh:
    """Records every command; answers `gh pr view` from `prs` and `gh api repos/…` from `facts`."""

    def __init__(self, prs=None, facts=None, fail=()):
        self.calls, self.prs, self.fail = [], prs or {}, set(fail)
        self.facts = FACTS if facts is None else facts

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[:3] in (["gh", "pr", "view"], ["gh", "issue", "view"]):
            doc = self.prs.get((cmd[5], int(cmd[3])))
            return done(0, json.dumps(doc)) if doc is not None else done(1, "", "not found")
        if cmd[:2] == ["gh", "api"]:
            return done(0, json.dumps(self.facts)) if isinstance(self.facts, dict) else done(1, "", "forbidden")
        if cmd[2] in self.fail:
            return done(1, "", f"{cmd[2]} refused")
        return done(0, "ok\n")

    def did(self, verb):
        return [c for c in self.calls if len(c) > 2 and c[2] == verb]

    def writes(self):
        return [c for c in self.calls if c[:2] != ["gh", "api"] and c[2] != "view"]


class Rules(unittest.TestCase):
    def test_a_green_pull_request_from_a_trusted_author_is_ready(self):
        self.assertEqual(dispose(pr())["disposition"], "merge")

    def test_a_gate_or_hold_label_wins_over_green(self):
        for label in ("needs-amr", "agent:hold", "blocked", "Needs-AMR"):
            row = dispose(pr(labels=[label]))
            self.assertEqual(row["disposition"], "amr", label)
            self.assertTrue(row["why"].startswith("labelled "), label)

    def test_a_governing_document_is_for_ratification_even_when_green(self):
        row = dispose(pr(), ["ratification", "ready_to_merge"], {"ratification": "changes docs/constitution.md"})
        self.assertEqual((row["disposition"], row["why"]), ("ratify", "changes docs/constitution.md"))

    def test_a_label_gate_outranks_ratification(self):
        self.assertEqual(dispose(pr(labels=["needs-amr"]), ["ratification"])["disposition"], "amr")

    def test_a_release_pull_request_stays_with_the_maintainer(self):
        row = dispose(pr(author="github-actions", bot=True, head="release-please--branches--main"))
        self.assertEqual(row["disposition"], "amr")
        self.assertIn("release", row["why"])

    def test_a_private_repo_is_never_acted_on(self):
        row = dispose(pr(private=True))
        self.assertEqual((row["disposition"], row["private"]), ("amr", True))

    def test_a_draft_is_carried_until_it_goes_quiet(self):
        self.assertEqual(dispose(pr(draft=True))["disposition"], "carry")
        self.assertEqual(dispose(pr(draft=True, updated="2026-10-20T00:00:00Z"))["disposition"], "stale")

    def test_conflicts_and_failures_go_to_whoever_fixes_them(self):
        self.assertEqual(dispose(pr(enrich={**GREEN, "mergeable": "CONFLICTING"}))["disposition"], "resolve")
        self.assertEqual(dispose(pr(enrich={**GREEN, "checks": "FAILURE"}))["disposition"], "fix")
        self.assertEqual(dispose(pr(enrich={**GREEN, "review": "CHANGES_REQUESTED"}))["disposition"], "fix")

    def test_unsettled_state_waits_and_goes_stale_after_the_limit(self):
        self.assertEqual(dispose(pr(enrich={**GREEN, "checks": "PENDING"}))["disposition"], "wait")
        self.assertEqual(dispose(pr(enrich={**GREEN, "mergeable": "UNKNOWN"}))["disposition"], "wait")
        self.assertEqual(dispose(pr(enrich={**GREEN, "merge_state": "BLOCKED"}, updated="2026-10-01T00:00:00Z"))["disposition"], "stale")
        self.assertEqual(dispose(pr(enrich=None))["disposition"], "wait")

    def test_no_checks_is_not_proof_of_green(self):
        row = dispose(pr(enrich={**GREEN, "checks": None}))
        self.assertEqual(row["disposition"], "amr")
        self.assertIn("no check ran", row["why"])

    def test_an_untrusted_author_or_a_locked_repo_is_the_maintainers(self):
        self.assertEqual(dispose(pr(author="stranger"))["disposition"], "amr")
        self.assertEqual(dispose(pr(repo="o/locked"))["disposition"], "amr")
        self.assertEqual(dispose(pr(repo="O/Locked"))["disposition"], "amr")

    def test_a_dependabot_decision_is_the_maintainers(self):
        row = dispose(pr(author="dependabot", bot=True), ["dependabot"], {"dependabot": "major bump 1.0 → 2.0"})
        self.assertEqual((row["disposition"], row["why"]), ("amr", "major bump 1.0 → 2.0"))

    def test_a_dependabot_minor_bump_is_ready(self):
        self.assertEqual(dispose(pr(author="dependabot", bot=True, title="chore(deps): bump x from 1.2.3 to 1.2.4"))["disposition"], "merge")

    def test_a_dependabot_major_or_unstated_bump_is_held_even_without_the_index(self):
        major = dispose(pr(author="dependabot[bot]", title="chore(deps): bump x from 1.9.0 to 2.0.0"))
        grouped = dispose(pr(author="dependabot", bot=True, title="build(deps): bump the npm group with 4 updates"))
        zero = dispose(pr(author="dependabot", bot=True, title="bump y from 0.3.1 to 0.4.0"))
        self.assertEqual([r["disposition"] for r in (major, grouped, zero)], ["amr", "amr", "amr"])
        self.assertIn("states no versions", grouped["why"])

    def test_a_title_is_redacted_and_cut(self):
        token = "ghp_" + "a1B2" * 9
        row = dispose(pr(title=f"leak {token} " + "x" * 300))
        self.assertNotIn(token, row["title"])
        self.assertLessEqual(len(row["title"]), 140)

    def test_a_timestamp_without_a_zone_is_read_as_utc(self):
        self.assertEqual(dispose(pr(draft=True, updated="2026-10-20T00:00:00"))["disposition"], "stale")


class Trust(unittest.TestCase):
    def test_people_and_bots_are_kept_apart(self):
        self.assertEqual(WHO["people"], {"bamr87"})
        self.assertEqual(WHO["bots"], {"github-actions", "claude", "dependabot"})

    def test_a_person_is_matched_by_the_bare_login_only(self):
        ok = closeout.trusted_author
        self.assertTrue(ok("bamr87", False, WHO))
        self.assertTrue(ok("BAMR87", False, WHO))
        for login in ("bamr87x", "xbamr87", "", "bamr8"):
            self.assertFalse(ok(login, False, WHO), login)

    def test_a_person_cannot_borrow_a_bots_name(self):
        for login in ("claude", "github-actions", "dependabot"):
            self.assertFalse(closeout.trusted_author(login, False, WHO), login)

    def test_a_bot_cannot_borrow_a_persons_name(self):
        for login, is_bot in (("app/bamr87", True), ("bamr87[bot]", False), ("bamr87", True)):
            self.assertFalse(closeout.trusted_author(login, is_bot, WHO), login)

    def test_a_bot_is_matched_in_every_spelling_github_uses(self):
        for login, is_bot in (("app/dependabot", True), ("dependabot", True), ("dependabot[bot]", False), ("app/github-actions", True),
                              ("github-actions", True), ("claude[bot]", True)):
            self.assertTrue(closeout.trusted_author(login, is_bot, WHO), login)

    def test_the_index_spelling_of_a_bot_is_ready(self):
        self.assertEqual(dispose(pr(author="github-actions", bot=True))["disposition"], "merge")
        self.assertEqual(dispose(pr(author="github-actions", bot=False))["disposition"], "amr")

    def test_major_bump(self):
        self.assertIs(closeout.major_bump("bump x from 1.2.3 to 1.3.0"), False)
        self.assertIs(closeout.major_bump("bump x from 1.2.3 to 2.0.0"), True)
        self.assertIs(closeout.major_bump("bump x from 0.2.3 to 0.3.0"), True)
        self.assertIs(closeout.major_bump("update requirement from >=2.14.1 to >=2.15"), False)
        self.assertIsNone(closeout.major_bump("bump the npm group with 4 updates"))


class Issues(unittest.TestCase):
    def issue(self, number=1, labels=(), updated="2026-11-12T00:00:00Z"):
        return {"repo": "o/r", "number": number, "title": "t", "url": "u", "labels": list(labels), "kind": "issue",
                "created_at": "2026-09-01T00:00:00Z", "updated_at": updated}

    def go(self, item, in_pr=None):
        return closeout.dispose_issue(item, in_pr or {}, CFG, GATE, NOW)

    def test_an_epic_is_left_out(self):
        self.assertIsNone(self.go(self.issue(labels=["epic"])))

    def test_a_held_issue_waits_on_the_maintainer(self):
        for label in ("needs-amr", "agent:hold", "agent:blocked"):
            self.assertEqual(self.go(self.issue(labels=[label]))["disposition"], "amr")

    def test_an_issue_with_an_open_pull_request_is_carried_with_it(self):
        row = self.go(self.issue(number=7, updated="2026-08-01T00:00:00Z"), {"o/r#7": "o/r#9"})
        self.assertEqual((row["disposition"], row["why"]), ("carry", "o/r#9 is open for it"))

    def test_a_quiet_issue_is_stale_unless_its_priority_keeps_it(self):
        old = "2026-09-01T00:00:00Z"
        self.assertEqual(self.go(self.issue(updated=old))["disposition"], "stale")
        self.assertEqual(self.go(self.issue(updated=old, labels=["P1"]))["disposition"], "carry")
        self.assertEqual(self.go(self.issue(updated=old, labels=["roadmap"]))["disposition"], "carry")

    def test_a_recent_issue_is_carried(self):
        self.assertEqual(self.go(self.issue())["disposition"], "carry")


class Build(unittest.TestCase):
    ITEM = {"repo": "o/r", "number": 9, "kind": "pr", "title": "p", "author": "bamr87", "labels": [],
            "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-12T00:00:00Z"}
    STATE = {"closes": ["o/r#7"], "mergeable": "MERGEABLE", "merge_state": "CLEAN", "ci": "SUCCESS", "head": "fix/x"}
    MODEL = {"repos": [{"repo": "o/r", "private": False, "prs": {"9": STATE},
                        "items": [ITEM, {"repo": "o/r", "number": 7, "kind": "issue", "title": "i", "labels": [],
                                         "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-01T00:00:00Z"}]},
                       {"repo": "o/other", "private": False, "prs": {"3": {"closes": ["o/r#8"]}},
                        "items": [{"repo": "o/other", "number": 3, "kind": "pr", "title": "x", "author": "bamr87", "labels": []}]},
                       {"repo": "o/secret", "private": True, "prs": {}, "items": [{"repo": "o/secret", "number": 1, "kind": "issue", "title": "s", "labels": []}]},
                       {"repo": "o/old", "archived": True, "prs": {}, "items": [{"repo": "o/old", "number": 1, "kind": "issue", "title": "a", "labels": []}]}]}

    def test_the_index_is_the_only_source_of_pull_requests_when_it_answers(self):
        index = {"prs": {"a": pr(number=3)}}
        out = closeout.build(index, self.MODEL, FLEET, NOW, lambda rec, cfg: (["ready_to_merge"], ["ok"], {}), GATE)
        self.assertEqual([r["key"] for r in out["rows"] if r["type"] == "pr"], ["pr:o/r#3"])
        self.assertEqual(out["sources"], {"index": True, "model": True})

    def test_without_an_index_the_models_pull_requests_are_used(self):
        out = closeout.build(None, self.MODEL, FLEET, NOW)
        got = {r["key"]: r["disposition"] for r in out["rows"] if r["type"] == "pr"}
        self.assertEqual(got["pr:o/r#9"], "merge")
        self.assertFalse(out["sources"]["index"])

    def test_without_an_index_a_release_pull_request_is_still_held(self):
        model = {"repos": [{"repo": "o/r", "prs": {"9": {**self.STATE, "head": "release-please--branches--main"}},
                            "items": [{**self.ITEM, "author": "github-actions[bot]"}]}]}
        row = closeout.build(None, model, FLEET, NOW)["rows"][0]
        self.assertEqual(row["disposition"], "amr")
        self.assertIn("release", row["why"])

    def test_without_an_index_the_classifier_still_runs(self):
        seen = []
        closeout.build(None, self.MODEL, FLEET, NOW, lambda rec, cfg: seen.append(rec["number"]) or (["ratification"], ["x"], {}), GATE)
        self.assertEqual(sorted(seen), [3, 9])

    def test_without_an_index_a_private_repos_pull_request_is_still_private(self):
        model = {"repos": [{"repo": "o/secret", "private": True, "prs": {"9": self.STATE}, "items": [{**self.ITEM, "repo": "o/secret"}]}]}
        row = closeout.build(None, model, FLEET, NOW)["rows"][0]
        self.assertEqual((row["disposition"], row["private"]), ("amr", True))

    def test_private_and_archived_repos_contribute_no_issues(self):
        out = closeout.build(None, self.MODEL, FLEET, NOW)
        self.assertEqual([r["key"] for r in out["rows"] if r["type"] == "issue"], ["issue:o/r#7"])

    def test_an_issue_closed_by_an_open_pull_request_is_not_stale(self):
        out = closeout.build(None, self.MODEL, FLEET, NOW)
        self.assertEqual(next(r for r in out["rows"] if r["key"] == "issue:o/r#7")["disposition"], "carry")

    def test_a_pull_request_in_another_repo_can_close_it_too(self):
        model = json.loads(json.dumps(self.MODEL))
        model["repos"][0]["items"].append({"repo": "o/r", "number": 8, "kind": "issue", "title": "j", "labels": [],
                                           "updated_at": "2026-08-01T00:00:00Z"})
        row = next(r for r in closeout.build(None, model, FLEET, NOW)["rows"] if r["key"] == "issue:o/r#8")
        self.assertEqual((row["disposition"], row["why"]), ("carry", "o/other#3 is open for it"))

    def test_counts_cover_every_row_once(self):
        out = closeout.build(None, self.MODEL, FLEET, NOW)
        self.assertEqual(sum(c["pr"] + c["issue"] for c in out["counts"].values()), len(out["rows"]))

    def test_nothing_readable_is_an_empty_result_not_a_crash(self):
        out = closeout.build(None, None, {}, NOW)
        self.assertEqual((out["rows"], out["sources"]), ([], {"index": False, "model": False}))


class Gate(unittest.TestCase):
    def verdict(self, repo="o/r", facts=FACTS, **over):
        return closeout.gate_verdict(live(**over), CFG, GATE, WHO, repo, facts)

    def test_nothing_holds_a_plain_green_change(self):
        self.assertIsNone(self.verdict())

    def test_every_gated_path_holds_it(self):
        for path in (".github/workflows/ci.yml", ".github/actions/x/action.yml", ".github/scripts/dash-gen/x.py", ".github/dependabot.yml",
                     ".github/CODEOWNERS", "CODEOWNERS", "_data/fleet.yml", "_data/agents.yml", "docs/constitution.md",
                     "docs/amendments/proposed/x.md", "docs/adr/0001-x.md", "AGENTS.md", "CLAUDE.md", "SECURITY.md",
                     ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/stop.sh", ".mcp.json", ".gitmodules",
                     "infra/main.tf", "compose/x.yml", "docker-compose.yml", "Dockerfile", "Dockerfile.dev", ".env", ".env.example",
                     "tools/install-weekly.sh", "tools/update-submodules.sh", "tools/dash", "tools/dash-gen", "tools/jev/loop.py",
                     "tools/weekly/core.py", "tools/weekly/closeout.py", "tools/pm_review.py", "tools/console/gh_projects_write.py",
                     "tools/console/core.py", "tools/console/subscription.py", "tools/console/gh_projects.py", "tools/fleetcore/graph.py",
                     "compose.yml", "compose.yaml", "projects/fleet-observe/compose.yml", "yaml.py", "setup.py", ".vscode/launch.json",
                     ".devcontainer/devcontainer.json", ".pre-commit-config.yaml",
                     "templates/ci/x.yml", "specs/DOCS.md", "projects/x/.github/workflows/y.yml"):
            got = self.verdict(files=changed("README.md", path))
            self.assertEqual((got[0], path in got[1]), ("amr", True), path)

    def test_a_gated_path_is_matched_whatever_its_case(self):
        for path in ("claude.md", "Agents.md", "_data/Fleet.yml", ".GitHub/workflows/x.yml", "DOCS/Constitution.md"):
            self.assertEqual(self.verdict(files=changed(path))[0], "amr", path)

    def test_ordinary_paths_do_not(self):
        for path in ("README.md", "src/x.py", "docs/guide.md", "pages/posts/a.md", "data/fleet.yml.md", "tools/console/web/src/App.tsx",
                     "tools/weekly_notes.md", "tools/dashboard.py", "site/package.json", "_data/projects.yml", "docs/compose.md"):
            self.assertIsNone(self.verdict(files=changed(path)), path)

    def test_config_can_add_a_gated_path_and_never_remove_one(self):
        cfg = closeout.config({"weekly": {"closeout": {"gate_paths": [r"^extra/"]}}})
        self.assertEqual(len(cfg["gate_paths"]), len(closeout.DEFAULTS["gate_paths"]) + 1)
        gated = lambda path: closeout.gate_verdict(live(files=changed(path)), cfg, GATE, WHO, "o/r", FACTS)  # noqa: E731
        self.assertEqual(gated("extra/x")[0], "amr")
        self.assertEqual(gated("_data/fleet.yml")[0], "amr")

    def test_a_bare_string_in_config_is_one_name_not_its_letters(self):
        fleet = {"jev": {"allowed_authors": "bamr87"}, "weekly": {"closeout": {"never_merge": "o/locked", "release_heads": "rel--",
                                                                             "repo_gate_paths": {"o/r": "^docs/"}}}}
        cfg, who = closeout.config(fleet), closeout.trust(fleet)
        self.assertEqual((who["people"], cfg["never_merge"], cfg["release_heads"]), ({"bamr87"}, ["o/locked"], ["rel--"]))
        self.assertFalse(closeout.trusted_author("b", False, who))
        self.assertEqual(closeout.gate_verdict(live(), cfg, GATE, who, "o/locked", FACTS)[0], "amr")
        self.assertEqual(closeout.gate_verdict(live(files=changed("docs/a.md")), cfg, GATE, who, "o/r", FACTS)[0], "amr")
        self.assertIsNone(closeout.gate_verdict(live(), cfg, GATE, who, "o/r", FACTS))

    def test_config_of_the_wrong_shape_keeps_the_rules(self):
        for bad in ({"never_merge": 7, "release_heads": None, "repo_gate_paths": ["x"]}, {"release_heads": []}, "nonsense", None):
            cfg = closeout.config({"weekly": {"closeout": bad}})
            self.assertEqual(cfg["release_heads"], ["release-please--"], bad)
            self.assertEqual((cfg["repo_gate_paths"], len(cfg["gate_paths"])), ({}, len(closeout.DEFAULTS["gate_paths"])), bad)
            self.assertIn("release", closeout.gate_verdict(live(headRefName="release-please--x"), cfg, GATE, WHO, "o/r", FACTS)[1])
        self.assertEqual(closeout.trust({"jev": {"allowed_authors": 7}})["people"], set())

    def test_a_pattern_that_does_not_compile_holds_everything(self):
        cfg = closeout.config({"weekly": {"closeout": {"repo_gate_paths": {"o/r": ["("]}}}})
        got = closeout.gate_verdict(live(), cfg, GATE, WHO, "o/r", FACTS)
        self.assertEqual(got[0], "amr")
        self.assertIn("does not compile", got[1])

    def test_a_repos_own_content_gate_applies_only_there(self):
        files = changed("pages/_quests/1/a.md")
        self.assertEqual(self.verdict(repo="o/quests", files=files)[0], "amr")
        self.assertIn("own content gate", self.verdict(repo="O/Quests", files=files)[1])
        self.assertIn("own content gate", self.verdict(repo="o/quests", files=changed("Pages/_Quests/1/a.md"))[1])
        self.assertIsNone(self.verdict(repo="o/r", files=files))

    def test_unreadable_oversized_or_renamed_files_hold_it(self):
        self.assertEqual(self.verdict(files=[])[0], "amr")
        self.assertEqual(self.verdict(files=None)[0], "amr")
        self.assertEqual(self.verdict(files=[*changed("a"), None])[0], "amr")
        self.assertEqual(self.verdict(files=changed(""))[0], "amr")
        self.assertEqual(self.verdict(files=changed(*[f"f{n}" for n in range(100)]))[0], "amr")
        self.assertIsNone(self.verdict(files=changed(*[f"f{n}" for n in range(99)])))
        for kind in ("RENAMED", "COPIED", "renamed"):
            got = self.verdict(files=changed("docs/new.md", kind=kind))
            self.assertEqual(got[0], "amr", kind)
            self.assertIn("came from", got[1])
        for missing in ([{"path": "docs/a.md"}], [{"path": "docs/a.md", "changeType": None}], [{"path": "docs/a.md", "changeType": ""}]):
            self.assertIn("rename cannot be ruled out", self.verdict(files=missing)[1])

    def test_labels_and_state(self):
        for label in ("Needs-AMR", "agent:hold", "blocked"):
            self.assertEqual(self.verdict(labels=[{"name": label}])[0], "amr", label)
        for state in ("MERGED", "CLOSED"):
            self.assertEqual(self.verdict(state=state)[0], "gone", state)
        for state in (None, "", "LOCKED", 7):
            self.assertEqual(self.verdict(state=state)[0], "wait", state)       # not open, and not known to be gone
        self.assertEqual(self.verdict(isDraft=True)[0], "carry")
        self.assertEqual(self.verdict(mergeable="CONFLICTING")[0], "resolve")
        for merge_state in ("BEHIND", "BLOCKED", "UNSTABLE", "DIRTY", "UNKNOWN", None):
            self.assertEqual(self.verdict(mergeStateStatus=merge_state)[0], "wait", merge_state)
        self.assertIsNone(self.verdict(mergeStateStatus="HAS_HOOKS"))
        self.assertEqual(self.verdict(mergeable="UNKNOWN")[0], "wait")          # a CLEAN left over from before
        self.assertEqual(self.verdict(reviewDecision="CHANGES_REQUESTED")[0], "fix")

    def test_a_field_that_cannot_be_read_holds_it(self):
        """Unreadable is never read as "no": no labels, not a draft, not a release branch."""
        for over in ({"labels": None}, {"labels": "needs-amr"}, {"labels": [None]}, {"labels": [{"name": None}]}, {"labels": [{}]},
                     {"isDraft": None}, {"isDraft": "false"}, {"headRefName": None}, {"headRefName": ""}, {"headRefName": 7}):
            got = self.verdict(**over)
            self.assertEqual(got[0], "amr", over)
            self.assertIn("could not be read", got[1], over)
        for key in ("labels", "isDraft", "headRefName"):
            doc = live()
            del doc[key]
            self.assertEqual(closeout.gate_verdict(doc, CFG, GATE, WHO, "o/r", FACTS)[0], "amr", key)

    def test_the_built_in_gate_labels_cannot_be_switched_off(self):
        for emptied in ({"labels": {"gate": [], "hold": []}}, {"labels": {}}, {"labels": None}, {}, None, {"labels": {"gate": "x", "hold": None}}):
            for label in ("needs-amr", "agent:hold", "blocked"):
                got = closeout.gate_verdict(live(labels=[{"name": label}]), CFG, emptied, WHO, "o/r", FACTS)
                self.assertEqual(got, ("amr", f"labelled {label}"), (emptied, label))
            row = closeout.dispose_pr(pr(labels=["needs-amr"]), [], {}, CFG, emptied, WHO, NOW)
            self.assertEqual(row["disposition"], "amr", emptied)
        extra = {"labels": {"gate": ["human-review"], "hold": []}}
        self.assertEqual(closeout.gate_verdict(live(labels=[{"name": "human-review"}]), CFG, extra, WHO, "o/r", FACTS)[0], "amr")

    def test_authors_are_read_with_their_kind(self):
        self.assertEqual(self.verdict(author={"login": "stranger", "is_bot": False})[0], "amr")
        self.assertEqual(self.verdict(author={"login": "claude", "is_bot": False})[0], "amr")
        self.assertEqual(self.verdict(author={"login": "app/bamr87", "is_bot": True})[0], "amr")
        self.assertEqual(self.verdict(author={"login": "bamr87", "is_bot": True})[0], "amr")       # GitHub says bot: not the person
        self.assertEqual(self.verdict(author=None)[0], "amr")
        self.assertEqual(self.verdict(author={"login": "", "is_bot": True})[0], "amr")
        self.assertIsNone(self.verdict(author={"login": "app/github-actions", "is_bot": True}))
        self.assertIsNone(self.verdict(author={"login": "github-actions", "is_bot": True}))        # the bare login, marked by GitHub

    def test_the_live_gate_holds_what_fridays_rules_held(self):
        """Days pass between the close-out and the confirm: the gate trusts nothing it was told."""
        self.assertIn("release", self.verdict(headRefName="release-please--branches--main")[1])
        self.assertEqual(self.verdict(repo="o/locked")[0], "amr")
        self.assertEqual(self.verdict(repo="O/Locked")[0], "amr")
        dep = {"login": "app/dependabot", "is_bot": True}
        self.assertEqual(self.verdict(author=dep, title="bump x from 1.0.0 to 2.0.0")[0], "amr")
        self.assertEqual(self.verdict(author=dep, title="bump the npm group with 4 updates")[0], "amr")
        self.assertIsNone(self.verdict(author=dep, title="bump x from 1.0.0 to 1.0.1"))

    def test_the_repo_must_take_a_merge_commit_and_the_base_must_be_the_default(self):
        self.assertIn("merge commits", self.verdict(facts={**FACTS, "allow_merge_commit": False})[1])
        self.assertEqual(self.verdict(facts={**FACTS, "allow_merge_commit": None})[0], "amr")
        self.assertIn("not the repo's default branch", self.verdict(baseRefName="release/1.x")[1])
        self.assertEqual(self.verdict(facts={**FACTS, "default_branch": None})[0], "amr")

    def test_a_private_repo_is_held_by_what_github_says_now(self):
        for private in (True, None, "false"):
            got = self.verdict(facts={**FACTS, "private": private})
            self.assertEqual(got[0], "amr", private)
            self.assertIn("private", got[1])
        self.assertEqual(self.verdict(facts={"allow_merge_commit": True, "default_branch": "main"})[0], "amr")   # not said at all

    def test_a_gated_path_is_reported_before_a_failing_check(self):
        got = self.verdict(files=changed("_data/fleet.yml"), statusCheckRollup=[{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}])
        self.assertEqual(got[0], "amr")

    def test_checks(self):
        ok = closeout.checks_green
        self.assertEqual(ok([])[0], False)
        self.assertEqual(ok(None)[0], False)
        self.assertTrue(ok([{"name": "a", "status": "COMPLETED", "conclusion": "SUCCESS"}, {"name": "b", "status": "COMPLETED", "conclusion": "SKIPPED"},
                            {"name": "c", "status": "COMPLETED", "conclusion": "NEUTRAL"}])[0])
        for bad in ({"status": "IN_PROGRESS", "conclusion": None}, {"status": "COMPLETED", "conclusion": "FAILURE"},
                    {"status": "COMPLETED", "conclusion": "CANCELLED"}, {"status": "QUEUED"}):
            self.assertFalse(ok([{"name": "x", **bad}])[0], bad)
        good = {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}
        for bad in ({"status": "COMPLETED", "conclusion": "CANCELLED"}, {"status": "COMPLETED", "conclusion": "TIMED_OUT"},
                    {"status": "COMPLETED", "conclusion": "ACTION_REQUIRED"}, {"status": "IN_PROGRESS"}):
            self.assertFalse(ok([good, {"name": "x", **bad}])[0], bad)       # one green check does not excuse another
        self.assertTrue(ok([{"__typename": "StatusContext", "context": "s", "state": "SUCCESS"}])[0])
        for state in ("PENDING", "FAILURE", "ERROR", "EXPECTED", "", None):
            self.assertFalse(ok([good, {"__typename": "StatusContext", "context": "s", "state": state}])[0], state)
        for conclusion in ("STALE", "STARTUP_FAILURE", "", None, "success-ish"):
            self.assertFalse(ok([good, {"name": "x", "status": "COMPLETED", "conclusion": conclusion}])[0], conclusion)
        self.assertEqual(self.verdict(statusCheckRollup=[])[0], "amr")
        self.assertEqual(self.verdict(statusCheckRollup=[{"name": "x", "status": "COMPLETED", "conclusion": "FAILURE"}])[0], "fix")
        self.assertEqual(self.verdict(statusCheckRollup=[{"name": "x", "status": "IN_PROGRESS"}])[0], "wait")

    def test_checks_that_were_all_skipped_prove_nothing(self):
        skipped = [{"name": "a", "status": "COMPLETED", "conclusion": "SKIPPED"}, {"name": "b", "status": "COMPLETED", "conclusion": "NEUTRAL"}]
        self.assertFalse(closeout.checks_green(skipped)[0])
        self.assertEqual(self.verdict(statusCheckRollup=skipped)[0], "amr")


def result(*rows):
    return closeout.tally({"rows": list(rows), "sources": {"index": True, "model": False}, "scanned": False})


def ready(number=1, repo="o/r", disposition="merge", kind="pr", updated="2026-11-12T00:00:00Z"):
    return {"key": f"{kind}:{repo}#{number}", "type": kind, "repo": repo, "number": number, "title": "t", "url": "u",
            "disposition": disposition, "why": "w", "updated_at": updated}


class Scan(unittest.TestCase):
    def test_a_held_candidate_moves_and_a_closed_one_leaves(self):
        gh = Gh({("o/r", 1): live(), ("o/r", 2): live(files=changed(".github/workflows/x.yml")),
                 ("o/r", 3): live(state="MERGED"), ("o/r", 4): live(mergeStateStatus="BEHIND")})
        out = closeout.gate_scan(result(ready(1), ready(2), ready(3), ready(4), ready(5)), FLEET, GATE, runner=gh, workers=1)
        self.assertEqual({r["number"]: r["disposition"] for r in out["rows"]}, {1: "merge", 2: "amr", 4: "wait", 5: "wait"})
        self.assertTrue(out["scanned"])
        self.assertEqual(out["counts"]["merge"]["pr"], 1)

    def test_a_squash_only_repo_keeps_its_merges_with_the_maintainer(self):
        gh = Gh({("o/r", 1): live()}, facts={**FACTS, "allow_merge_commit": False})
        out = closeout.gate_scan(result(ready(1)), FLEET, GATE, runner=gh, workers=1)
        self.assertEqual(out["rows"][0]["disposition"], "amr")
        self.assertIn("merge commits", out["rows"][0]["why"])

    def test_a_repo_github_now_says_is_private_is_held(self):
        gh = Gh({("o/r", 1): live()}, facts={**FACTS, "private": True})
        out = closeout.gate_scan(result(ready(1)), FLEET, GATE, runner=gh, workers=1)
        self.assertEqual(out["rows"][0]["disposition"], "amr")

    def test_unreadable_repo_settings_hold_it(self):
        for facts in ("forbidden", {}, {**FACTS, "allow_merge_commit": "yes"}, {**FACTS, "private": None}):
            gh = Gh({("o/r", 1): live()}, facts=facts)
            self.assertEqual(closeout.gate_scan(result(ready(1)), FLEET, GATE, runner=gh, workers=1)["rows"][0]["disposition"], "amr", facts)

    def test_the_scan_only_reads(self):
        gh = Gh({("o/r", 1): live()})
        closeout.gate_scan(result(ready(1), ready(2, disposition="carry")), FLEET, GATE, runner=gh, workers=1)
        self.assertEqual(gh.writes(), [])
        self.assertEqual(len(gh.did("view")), 1)


class ReadOnly(unittest.TestCase):
    """The module lists. Nothing in it can merge, close, comment or label."""

    def test_it_has_no_function_that_writes(self):
        for name in ("merge_ready", "close_proposed", "safe_reason"):
            self.assertFalse(hasattr(closeout, name), name)

    def test_every_gh_call_in_it_is_a_read(self):
        import re
        source = Path(closeout.__file__).read_text()
        calls = set(re.findall(r'\["gh",\s*"(\w+)",\s*(?:"(\w+)")?', source))
        self.assertEqual(calls, {("pr", "view"), ("api", "")})
        for flag in ("--admin", "--squash", "--rebase", "--auto", "--delete-branch", "--comment"):
            self.assertNotIn(flag, source, flag)


class Output(unittest.TestCase):
    def test_lists_are_one_repo_and_number_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = closeout.list_files(result(ready(1), ready(2, disposition="amr"), ready(3, disposition="carry"), ready(4, kind="issue", disposition="stale")), Path(tmp))
            self.assertEqual(sorted(written), ["amr", "merge"])
            self.assertEqual(Path(written["merge"]).read_text(), "o/r 1\n")

    def test_the_report_says_whether_ready_was_read_live(self):
        doc = result(ready(1))
        self.assertIn("only mechanical", "\n".join(closeout.render(doc, {})))
        doc["scanned"] = True
        self.assertIn("read from live GitHub", "\n".join(closeout.render(doc, {})))

    def test_a_missing_index_is_said_at_the_top(self):
        doc = result()
        doc["sources"]["index"] = False
        self.assertIn("could not be read", "\n".join(closeout.render(doc, {})))

    def test_how_fresh_the_index_was_is_shown(self):
        doc = result(ready(1))
        doc["note"] = "partial, live+cache; merge state is not current for 4 of 120 pull request(s)"
        self.assertIn("The decision index: partial, live+cache", "\n".join(closeout.render(doc, {})))


if __name__ == "__main__":
    unittest.main()

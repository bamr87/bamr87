#!/usr/bin/env python3
"""
Fixture tests for tools/jev/conflicts.py — the conflict engine's safety rules,
its reading of a real conflicted working tree, and its validation gate.

Everything here runs against LOCAL git repositories built in a temp directory:
no network, no `gh`, no model. The parts that would call GitHub are exercised
through the one wrapper they all go through (`common.gh`), whose job is to
refuse the two things JEV must never do.

Run: python3 tools/test_jev_conflicts.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.jev import classify as cls  # noqa: E402
from tools.jev import conflicts as cf  # noqa: E402
from tools.jev.common import JevConfig, JevError, git  # noqa: E402

CFG = JevConfig(allowed_authors=["bamr87", "bamr87-bot"], needs_human_label="jev:needs-human")


def pr(**kw) -> cf.PullRequest:
    base = dict(repo="o/r", number=1, author="bamr87", base="main", head="feature")
    base.update(kw)
    return cf.PullRequest(**base)


def conflicted_repo(attributes: str = "") -> Path:
    """A real repository mid-merge, with `file.txt` conflicted.

    Built rather than mocked: the hunk counting, `git check-attr` reading and
    `--ours` / `--theirs` resolution are all git behaviour, and a fake git
    would only test the fake.
    """
    d = Path(tempfile.mkdtemp()) / "repo"
    d.mkdir(parents=True)
    git(["init", "-q", "-b", "main"], cwd=d)
    git(["config", "user.name", "t"], cwd=d)
    git(["config", "user.email", "t@example.com"], cwd=d)
    if attributes:
        (d / ".gitattributes").write_text(attributes)
    (d / "file.txt").write_text("base\n")
    git(["add", "-A"], cwd=d)
    git(["commit", "-qm", "base"], cwd=d)
    git(["checkout", "-qb", "feature"], cwd=d)
    (d / "file.txt").write_text("ours\n")
    git(["commit", "-qam", "ours"], cwd=d)
    git(["checkout", "-q", "main"], cwd=d)
    (d / "file.txt").write_text("theirs\n")
    git(["commit", "-qam", "theirs"], cwd=d)
    git(["checkout", "-q", "feature"], cwd=d)
    git(["merge", "--no-ff", "main", "-m", "merge"], cwd=d)
    return d


# --------------------------------------------------------------------------- #
# refusals — the rules JEV is not allowed to break
# --------------------------------------------------------------------------- #
def test_the_gh_wrapper_refuses_to_merge_a_pull_request():
    for argv in (["pr", "merge", "1", "--repo", "o/r"],
                 ["pr", "merge", "1", "--squash"]):
        try:
            cf.gh(argv)
        except JevError as exc:
            assert "never merges" in str(exc)
        else:
            raise AssertionError(f"{argv} was not refused")


def test_the_gh_wrapper_refuses_an_admin_override_anywhere_in_the_arguments():
    try:
        cf.gh(["pr", "comment", "1", "--repo", "o/r", "--admin"])
    except JevError as exc:
        assert "never uses --admin" in str(exc)
    else:
        raise AssertionError("--admin was not refused")


def test_the_guard_refuses_destructive_and_settings_verbs_and_allows_what_jev_uses():
    from tools.jev.common import assert_no_admin, assert_safe_git
    refused = [["issue", "close", "1", "-R", "o/r"], ["issue", "delete", "1"], ["issue", "transfer", "1", "o/x"],
               ["issue", "lock", "1"], ["repo", "delete", "o/r", "--yes"], ["repo", "archive", "o/r"],
               ["repo", "edit", "o/r", "--visibility", "public"], ["repo", "rename", "x"], ["repo", "transfer"],
               ["api", "-X", "DELETE", "repos/o/r"], ["api", "--method", "PATCH", "repos/o/r"],
               ["api", "--method=PUT", "repos/o/r/topics"], ["api", "-XDELETE", "repos/o/r/git/refs/heads/x"],
               ["secret", "set", "FLEET_TOKEN"], ["variable", "set", "REPO_SCOUT_ENABLED"],
               ["variable", "delete", "X"], ["repo", "sync", "o/r", "--force"], ["pr", "merge", "1"],
               ["api", "graphql", "-f", "query=mutation { deleteRepository(input: {}) { clientMutationId } }"],
               # gh POSTs implicitly once a parameter is added: a REST write without -X
               ["api", "repos/o/r/merges", "-f", "base=main", "-f", "head=feature"],
               ["api", "-X", "POST", "repos/o/r/transfer", "-f", "new_owner=x"],
               ["api", "repos/o/r/git/refs", "-f", "ref=refs/heads/x", "-f", "sha=abc"],
               ["api", "repos/o/r/issues", "-ftitle=x"], ["api", "repos/o/r/issues", "--raw-field=title=x"],
               ["api", "repos/o/r/labels", "--input", "label.json"],
               # GraphQL whose text the guard cannot read
               ["api", "graphql", "--input", "body.json"], ["api", "graphql", "-F", "query=@q.graphql"],
               ["api", "graphql", "-f", "query=  # c\nsubscription { x }"]]
    for argv in refused:
        try:
            assert_no_admin(argv)
        except JevError as exc:
            assert "refusing" in str(exc)
        else:
            raise AssertionError(f"{argv} was not refused")
    for argv in (["label", "create", "jev:needs-human", "--repo", "o/r", "--force"],
                 ["pr", "edit", "1", "--repo", "o/r", "--add-label", "x"], ["pr", "comment", "1", "--body", "b"],
                 ["issue", "create", "-R", "o/r", "--title", "t"], ["repo", "clone", "o/r", "/tmp/x"],
                 ["variable", "get", "REPO_SCOUT_ENABLED", "-R", "o/r"], ["api", "repos/o/r/commits/main"],
                 ["api", "-X", "GET", "repos/o/r"], ["api", "graphql", "-f", "query={ viewer { login } }"],
                 ["api", "repos/o/r/commits/main", "--jq", ".sha"], ["api", "--paginate", "repos/o/r/pulls"]):
        assert_no_admin(argv)
    from tools.jev.common import _api_method
    assert _api_method(["api", "repos/o/r/merges", "-f", "base=main"]) == "POST"
    assert _api_method(["api", "repos/o/r", "--jq", ".x"]) == "GET"
    for argv in (["push", "--force", "origin", "x"], ["push", "-f"], ["push", "--force-with-lease"],
                 ["push", "origin", "+HEAD:refs/heads/x"], ["push", "origin", ":x"], ["push", "--mirror"],
                 ["push", "--delete", "origin", "x"], ["-c", "a=b", "push", "-f"],
                 ["push", "-fu", "origin", "x"], ["push", "--forc", "origin", "x"], ["push", "--mirr"],
                 ["--git-dir", "/r/.git", "push", "-f", "origin", "x"], ["--work-tree", "/w", "push", "--force"],
                 ["-c", "remote.origin.push=+refs/heads/*:refs/heads/*", "push", "origin"],
                 ["-c", "remote.origin.mirror=true", "push", "origin"]):
        try:
            assert_safe_git(argv)
        except JevError as exc:
            assert "force-push" in str(exc)
        else:
            raise AssertionError(f"git {argv} was not refused")
    assert_safe_git(["push", "origin", "HEAD:refs/heads/fix/x"])   # what commit_and_push sends
    assert_safe_git(["push", "-u", "--dry-run", "origin", "x"])
    assert_safe_git(["--git-dir=/r/.git", "--work-tree=/w", "status"])
    assert_safe_git(["log", "--grep", "push", "-f"])
    try:
        git(["push", "--force", "origin", "x"], cwd=Path("/nonexistent"))
    except JevError as exc:
        assert "force-push" in str(exc)
    else:
        raise AssertionError("common.git did not apply the guard")


def test_a_fork_branch_is_never_eligible_however_trusted_the_author():
    ok, why = cf.eligible(CFG, pr(head_repo="someone/r"))
    assert not ok and "fork" in why


def test_an_unlisted_author_is_never_eligible():
    ok, why = cf.eligible(CFG, pr(author="a-stranger"))
    assert not ok and "allowed_authors" in why


def test_a_hold_label_keeps_the_pull_request():
    for label in ("jev:needs-human", "agent:hold", "human-review"):
        ok, why = cf.eligible(CFG, pr(labels=[label]))
        assert not ok and label in why, label


def test_a_same_repo_branch_from_a_listed_author_is_eligible():
    ok, why = cf.eligible(CFG, pr(head_repo="o/r"))
    assert ok and why == "eligible"
    assert cf.eligible(CFG, pr(head_repo=""))[0], "an unknown head repo is the PR's own repo"


def test_a_pull_request_reference_must_be_owner_repo_number():
    assert cf.parse_ref("bamr87/bamr87#437") == ("bamr87/bamr87", 437)
    for bad in ("bamr87#437", "bamr87/bamr87", "437", "bamr87/bamr87/437"):
        try:
            cf.parse_ref(bad)
        except JevError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


# --------------------------------------------------------------------------- #
# reading a real conflicted tree
# --------------------------------------------------------------------------- #
def test_gitattributes_decide_a_files_kind_before_any_built_in_glob():
    d = conflicted_repo("file.txt merge=jev-regen\n")
    assert cf._attribute_kinds(d, ["file.txt"]) == {"file.txt": cls.GENERATED}
    d2 = conflicted_repo("file.txt merge=union\n")
    assert cf._attribute_kinds(d2, ["file.txt"]) == {"file.txt": cls.UNION}
    d3 = conflicted_repo("file.txt linguist-generated=true\n")
    assert cf._attribute_kinds(d3, ["file.txt"]) == {"file.txt": cls.GENERATED}
    assert cf._attribute_kinds(conflicted_repo(), ["file.txt"]) == {}
    assert cf._attribute_kinds(d, []) == {}


def test_validation_catches_a_conflict_marker_left_behind():
    d = conflicted_repo()
    good, problems = cf.validate(d)
    assert not good and any("conflict markers remain" in p for p in problems)


def test_validation_passes_on_a_cleanly_resolved_tree():
    d = conflicted_repo()
    (d / "file.txt").write_text("ours and theirs\n")
    git(["add", "-A"], cwd=d)
    good, problems = cf.validate(d)
    assert good, problems


def test_validation_catches_an_unmerged_path_with_no_markers():
    # a binary conflict leaves no markers at all, so the marker sweep alone
    # would call the tree clean
    d = conflicted_repo()
    (d / "file.txt").write_text("resolved\n")
    good, problems = cf.validate(d)
    assert not good and any("unmerged paths remain" in p for p in problems)


def test_tier0_takes_ours_and_stages_it():
    d = conflicted_repo("file.txt merge=jev-regen\n")
    ws = cf.Workspace(path=d, pr=pr(), merge_failed=True,
                      conflicted=[cls.ConflictFile("file.txt", 1, 2, cls.GENERATED)])
    done, detail = cf.resolve_tier0(ws)
    assert done and "ours + regenerate" in detail
    assert (d / "file.txt").read_text() == "ours\n"
    good, problems = cf.validate(d)
    assert good, problems


def test_a_declared_union_file_never_reaches_jev_because_git_merges_it():
    # the point of `merge=union` in .gitattributes: git resolves it itself, so
    # the file is not in the conflicted list at all
    d = conflicted_repo("file.txt merge=union\n")
    unmerged = git(["diff", "--name-only", "--diff-filter=U"], cwd=d)
    assert unmerged.out.strip() == "", unmerged.out
    assert set((d / "file.txt").read_text().split()) == {"ours", "theirs"}


def test_tier0_keeps_both_sides_of_a_union_file_rather_than_dropping_ours():
    # the same file WITHOUT the attribute: a real conflict, classified union by
    # `jev.union_paths`. Taking --theirs would silently delete this branch's rows.
    d = conflicted_repo()
    ws = cf.Workspace(path=d, pr=pr(), merge_failed=True,
                      conflicted=[cls.ConflictFile("file.txt", 1, 2, cls.UNION)])
    done, detail = cf.resolve_tier0(ws)
    assert done and "union (both sides)" in detail, detail
    assert set((d / "file.txt").read_text().split()) == {"ours", "theirs"}
    good, problems = cf.validate(d)
    assert good, problems


def test_an_id_collision_is_recognised_on_the_compiled_files_and_the_fragments():
    assert cf.id_collision([cls.ConflictFile("features/features.d/x.yml", 1, 2, cls.FRAGMENT)])
    assert cf.id_collision([cls.ConflictFile("features/features.yml", 1, 2, cls.GENERATED)])
    assert cf.id_collision([cls.ConflictFile("CHANGELOG.md", 1, 2, cls.GENERATED)])
    assert not cf.id_collision([cls.ConflictFile("tools/a.py", 1, 2, cls.SOURCE)])


# --------------------------------------------------------------------------- #
# spend
# --------------------------------------------------------------------------- #
def test_every_model_call_carries_its_dollar_cap_and_a_turn_cap():
    argv = cf.claude_argv("claude-haiku-4-5-20251001", "resolve it", 0.25, 8)
    assert argv[0] == "claude" and "-p" in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "0.25"
    assert argv[argv.index("--max-turns") + 1] == "8"
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert "json" in argv, "the cost is read from the CLI's JSON output"


def test_an_unreadable_cli_payload_is_charged_at_the_tier_cap_not_at_zero():
    cfg = JevConfig(tiers={"tier1": __import__("tools.jev.common", fromlist=["TierPolicy"])
                           .TierPolicy(name="tier1", model="m", max_usd=0.25, max_turns=8)})
    ws = cf.Workspace(path=Path("."), pr=pr(), conflicted=[])
    triage = cls.classify([cls.ConflictFile("a.py", 1, 2, cls.SOURCE)])

    def fake(argv, cwd=None, env=None, timeout=900, stdin=None):
        return __import__("tools.jev.common", fromlist=["Run"]).Run(0, "not json at all", "")

    ok, usd, model, detail = cf.resolve_with_model(cfg, ws, triage, "tier1", runner=fake)
    assert ok and usd == 0.25 and model == "m" and "tier cap" in detail


def test_a_reported_cost_is_taken_verbatim():
    cfg = JevConfig(tiers={"tier1": __import__("tools.jev.common", fromlist=["TierPolicy"])
                           .TierPolicy(name="tier1", model="m", max_usd=0.25, max_turns=8)})
    ws = cf.Workspace(path=Path("."), pr=pr(), conflicted=[])
    triage = cls.classify([cls.ConflictFile("a.py", 1, 2, cls.SOURCE)])

    def fake(argv, cwd=None, env=None, timeout=900, stdin=None):
        return __import__("tools.jev.common", fromlist=["Run"]).Run(
            0, '{"total_cost_usd": 0.0731, "subtype": "success"}', "")

    ok, usd, _model, detail = cf.resolve_with_model(cfg, ws, triage, "tier1", runner=fake)
    assert ok and usd == 0.0731 and detail == "success"


def test_a_tier_with_no_model_configured_does_not_pretend_to_run():
    ws = cf.Workspace(path=Path("."), pr=pr(), conflicted=[])
    triage = cls.classify([cls.ConflictFile("a.py", 1, 2, cls.SOURCE)])
    ok, usd, model, detail = cf.resolve_with_model(JevConfig(), ws, triage, "tier1")
    assert not ok and usd == 0.0 and not model and "no model configured" in detail


def test_the_resolution_prompt_forbids_committing_pushing_and_merging():
    ws = cf.Workspace(path=Path("/tmp/x"), pr=pr(title="A title"),
                      conflicted=[cls.ConflictFile("a.py", 1, 2, cls.SOURCE)])
    text = cf._prompt(ws, cls.classify(ws.conflicted))
    for rule in ("do not push", "do not merge the pull request",
                 "Never delete another branch's work", "regenerate it with its generator",
                 "Leave no conflict marker"):
        assert rule in text, rule


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

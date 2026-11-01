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

import os
import subprocess
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
                 ["push", "--delete", "origin", "x"], ["-c", "core.symlinks=false", "push", "-f"],
                 ["push", "-fu", "origin", "x"], ["push", "--forc", "origin", "x"], ["push", "--mirr"],
                 ["--git-dir", "/r/.git", "push", "-f", "origin", "x"], ["--work-tree", "/w", "push", "--force"]):
        try:
            assert_safe_git(argv)
        except JevError as exc:
            assert "force-push" in str(exc)
        else:
            raise AssertionError(f"git {argv} was not refused")
    assert_safe_git(["push", "origin", "HEAD:refs/heads/fix/x"])   # what commit_and_push sends
    assert_safe_git(["-c", "user.name=t", "-cuser.email=t@x", "commit", "-q", "-m", "m"])
    assert_safe_git(["config", "--local", "remote.origin.pushurl", "no-push://disabled"])   # what harden sets
    assert_safe_git(["push", "-u", "--dry-run", "origin", "HEAD:refs/heads/x"])
    assert_safe_git(["--git-dir=/r/.git", "--work-tree=/w", "status"])
    assert_safe_git(["log", "--grep", "push", "-f"])
    try:
        git(["push", "--force", "origin", "x"], cwd=Path("/nonexistent"))
    except JevError as exc:
        assert "force-push" in str(exc)
    else:
        raise AssertionError("common.git did not apply the guard")


def test_the_gh_guard_fails_closed_on_every_spelling_gh_would_still_run():
    """gh finds the verb past a flag and takes aliases, and pflag splits a
    shorthand bundle (`-iXPUT` is `-i -X PUT`): each spelling a post-fix review
    showed gh sending as a merge, a delete or a POST is refused."""
    from tools.jev.common import assert_no_admin
    for argv in (["pr", "-R", "o/r", "merge", "1", "--squash"], ["pr", "--repo=o/r", "merge", "1"],
                 ["issue", "-R", "o/r", "close", "1"], ["secret", "-R", "o/r", "delete", "FLEET_TOKEN"],
                 ["-R", "o/r", "pr", "merge", "1"], ["secret", "remove", "FLEET_TOKEN"], ["variable", "remove", "X"],
                 ["repo", "sync", "o/r", "--force=true"], ["pr", "close", "1"], ["label", "delete", "x"],
                 ["release", "delete", "v1"], ["run", "delete", "1"], ["cache", "delete", "1"], ["co", "1"],
                 ["pr", "comment", "1", "--delete-last"], ["pr", "comment", "1", "--edit-last", "--body", "x"],
                 ["api", "-iXPUT", "repos/o/r/pulls/1/merge"], ["api", "-iX", "PUT", "repos/o/r/pulls/1/merge"],
                 ["api", "-iXDELETE", "repos/o/r/git/refs/heads/main"], ["api", "-if", "title=x", "repos/o/r/issues"],
                 ["api", "-iftitle=x", "repos/o/r/issues"],
                 ["api", "repos/o/r/pulls/1/merge", "-ifmerge_method=squash"],
                 ["api", "-iZPUT", "repos/o/r"], ["api", "graphql", "-if", "query=mutation { x }"], [],
                 # no JEV caller runs `gh auth status`, and -t prints the token
                 ["auth", "status", "--show-token"], ["auth", "status", "-t"],
                 # gh hands everything after `--` to git clone
                 ["repo", "clone", "o/r", "d", "--", "-c", "remote.origin.push=:refs/heads/main"],
                 ["repo", "clone", "o/r", "d", "--", "--upload-pack=touch /tmp/x"],
                 ["repo", "clone", "o/r", "d", "--", "--mirror"]):
        try:
            assert_no_admin(argv)
        except JevError as exc:
            assert "refusing" in str(exc), (argv, exc)
        else:
            raise AssertionError(f"gh {argv} was not refused")
    from tools.jev.common import _api_method
    assert _api_method(["api", "-iXPUT", "x"]) == "PUT" and _api_method(["api", "-if", "a=b", "x"]) == "POST"
    assert _api_method(["api", "-i", "repos/o/r"]) == "GET"
    assert_no_admin(["api", "-i", "repos/o/r/commits/main"])
    assert_no_admin(["api", "-iXGET", "repos/o/r"])
    from tools.jev.workspace import CLONE_OPTS
    assert_no_admin(["repo", "clone", "o/r", "d", "--no-upstream", "--", "--branch", "main", *CLONE_OPTS])
    assert_no_admin(["repo", "clone", "o/r", "d", "--", "--no-tags", "--quiet"])   # what jev conflicts sends


def test_the_git_guard_fails_closed_on_aliases_config_and_plumbing():
    """An alias, an autocorrected typo, plumbing, `--config-env`, a `:ref`
    refspec set through -c, a push key written with `git config` and config
    injected through the environment each forced or deleted a remote ref past
    the old guard (a post-fix review ran them against a bare remote)."""
    from tools.jev.common import assert_safe_git
    for argv in (["-c", "alias.fp=push --force", "fp", "origin", "main"],
                 ["-c", "help.autocorrect=immediate", "psuh", "--force", "origin", "main"],
                 ["-c", "remote.origin.push=:refs/heads/keep", "push", "origin"],
                 ["-cremote.origin.push=:refs/heads/main", "push", "origin"],
                 ["-c", "remote.origin.push=+refs/heads/*:refs/heads/*", "push", "origin"],
                 ["-c", "remote.origin.mirror=true", "push", "origin"],
                 ["--config-env", "remote.origin.mirror=MIRROR", "push", "origin"],
                 ["--config-env=remote.origin.push=PUSHSPEC", "push", "origin"],
                 ["send-pack", "--force", "../remote.git", "main"], ["http-push", "--force", "u", "main"],
                 ["--exec-path=/tmp/x", "push", "origin"], ["push", "--receive-pack=sh -c x", "origin"],
                 ["config", "remote.origin.push", ":refs/heads/main"], ["config", "--local", "alias.st", "push -f"],
                 ["config", "remote.origin.mirror", "true"], ["-c"], []):
        try:
            assert_safe_git(argv)
        except JevError as exc:
            assert "refusing" in str(exc), (argv, exc)
        else:
            raise AssertionError(f"git {argv} was not refused")
    for env in ({"GIT_CONFIG_PARAMETERS": "'remote.origin.push'=':x'"},
                {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "alias.p", "GIT_CONFIG_VALUE_0": "push -f"}):
        try:
            assert_safe_git(["push", "origin"], env)
        except JevError as exc:
            assert "environment" in str(exc)
        else:
            raise AssertionError(f"{env} was not refused")
    # end to end: the delete refspec through -c is refused and the remote branch survives
    with tempfile.TemporaryDirectory() as tmp:
        remote, work = Path(tmp) / "remote.git", Path(tmp) / "work"
        assert git(["init", "-q", "--bare", "-b", "main", str(remote)], cwd=Path(tmp)).ok
        assert git(["clone", "-q", str(remote), str(work)], cwd=Path(tmp)).ok
        (work / "f").write_text("x\n")
        assert git(["add", "f"], cwd=work).ok
        assert git(["-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "m"],
                   cwd=work).ok
        assert git(["push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/keep"], cwd=work).ok
        try:
            git(["-c", "remote.origin.push=:refs/heads/keep", "push", "origin"], cwd=work)
        except JevError:
            pass
        else:
            raise AssertionError("the -c delete refspec ran")
        branches = git(["--git-dir", str(remote), "rev-parse", "--verify", "-q", "refs/heads/keep"], cwd=Path(tmp))
        assert branches.ok, "the remote branch was deleted"


def test_the_git_guard_refuses_config_that_a_later_plain_push_would_follow():
    """A second post-fix review planted a delete refspec or a mirror flag with
    a call that is not a push — a clone's own -c, `remote add --mirror`, a
    `git config include.path`, a global config file in env — or turned hooks
    back on with a later -c, then deleted a remote branch with a plain push.
    Each route is refused, and a push names an explicit <src>:<dst> refspec,
    so config planted past the guard is never followed either."""
    from tools.jev.common import assert_safe_git
    from tools.jev.workspace import CLONE_OPTS
    for argv in (["clone", "-q", "-c", "remote.origin.push=:refs/heads/keep", "r", "w"],
                 ["clone", "-cremote.origin.push=:x", "r", "w"], ["clone", "--config=remote.origin.mirror=true", "r"],
                 ["clone", "--config", "include.path=/tmp/x", "r"], ["clone", "-c", "core.hooksPath=/tmp/h", "r"],
                 ["clone", "--mirror", "r", "w"], ["clone", "--mirr", "r"], ["clone", "--upload-pack=touch /tmp/x", "r"],
                 ["clone", "-u", "touch /tmp/x", "r"], ["clone", "--template=/tmp/t", "r"], ["clone", "-qc", "x=y", "r"],
                 ["remote", "add", "--mirror=push", "m", "r"], ["remote", "add", "m", "r"],
                 ["remote", "set-url", "origin", "r"], ["remote", "set-url", "--push", "origin", "r"],
                 ["config", "include.path", "evil.cfg"], ["config", "includeIf.gitdir:/x/.path", "evil.cfg"],
                 ["config", "url./tmp/r.pushInsteadOf", "https://github.com/"], ["config", "core.sshCommand", "sh"],
                 ["config", "remote.origin.uploadpack", "sh"], ["config", "core.hooksPath", "/tmp/h"],
                 ["config", "core.fsmonitor", "/tmp/x"], ["config", "credential.helper", "!sh -c x"],
                 ["config", "--file", "f", "remote.origin.push", ":x"], ["config", "--global", "include.path", "x"],
                 ["config", "set", "include.path", "x"], ["config", "--add", "remote.origin.push", ":x"],
                 ["-c", "core.hooksPath=/tmp/h", "push", "origin", "HEAD:refs/heads/x"],
                 ["-c", "core.fsmonitor=/tmp/x", "status"], ["-c", "core.pager=sh -c x", "log"],
                 ["fetch", "--upload-pack=touch /tmp/x", "origin"], ["fetch", "--prune", "origin"],
                 ["push", "origin"], ["push", "m"], ["push", "origin", "main"], ["push", "origin", "HEAD:"],
                 ["push", "--all", "origin"], ["push", "--repo=m", "HEAD:refs/heads/x"]):
        try:
            assert_safe_git(argv)
        except JevError as exc:
            assert "refusing" in str(exc), (argv, exc)
        else:
            raise AssertionError(f"git {argv} was not refused")
    for env in ({"GIT_CONFIG_GLOBAL": "/tmp/evil.cfg"}, {"GIT_CONFIG_SYSTEM": "/tmp/evil.cfg"},
                {"GIT_DIR": "/tmp/r.git"}, {"GIT_CONFIG": "/tmp/evil.cfg"}):
        try:
            assert_safe_git(["push", "origin", "HEAD:refs/heads/x"], env)
        except JevError as exc:
            assert "environment" in str(exc)
        else:
            raise AssertionError(f"{env} was not refused")
    # what JEV itself sends still passes
    assert_safe_git(["push", "origin", "HEAD:refs/heads/x"], {"GIT_CONFIG_GLOBAL": "/dev/null",
                                                              "GIT_CONFIG_NOSYSTEM": "1"})
    for argv in (["clone", "--branch", "main", *CLONE_OPTS, "/src", "/dest"], ["remote"], ["remote", "remove", "up"],
                 ["config", "--local", "remote.origin.pushurl", "no-push://disabled"],
                 ["config", "--local", "credential.helper", ""], ["config", "--local", "core.hooksPath", "/dev/null"],
                 ["config", "--local", "core.fsmonitor", "false"], ["config", "user.name", "bamr87-bot"],
                 ["config", "--local", "--get", "core.hooksPath"], ["config", "--get-regexp", r"^remote\..*\.pushurl$"],
                 ["fetch", "--quiet", "origin", "main"]):
        assert_safe_git(argv)
    # end to end against a bare remote: every route is refused, and config
    # planted behind the guard's back (plain git) does not steer JEV's push
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        remote, work = t / "remote.git", t / "work"
        assert git(["init", "-q", "--bare", "-b", "main", str(remote)], cwd=t).ok
        assert git(["clone", "-q", str(remote), str(work)], cwd=t).ok
        (work / "f").write_text("x\n")
        assert git(["add", "f"], cwd=work).ok
        assert git(["-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "m"],
                   cwd=work).ok
        assert git(["push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/keep"], cwd=work).ok
        evil = t / "evil.cfg"
        evil.write_text('[remote "origin"]\n\tpush = :refs/heads/keep\n')
        hooks = t / "hooks"
        hooks.mkdir()
        (hooks / "pre-push").write_text(f"#!/bin/sh\ngit push -q {remote} :refs/heads/keep </dev/null\n")
        (hooks / "pre-push").chmod(0o755)

        def alive() -> bool:
            return git(["--git-dir", str(remote), "rev-parse", "--verify", "-q", "refs/heads/keep"], cwd=t).ok
        # each route: the call that plants the config, then the push that would follow it
        routes = [([("clone", "-q", "-c", "remote.origin.push=:refs/heads/keep", str(remote), str(t / "w1"))],
                   ["push", "origin"], t / "w1", None),
                  ([("remote", "add", "--mirror=push", "m", str(remote))], ["push", "m"], work, None),
                  ([("config", "include.path", str(evil))], ["push", "origin"], work, None),
                  ([], ["-c", f"core.hooksPath={hooks}", "push", "origin", "HEAD:refs/heads/x"], work, None),
                  ([], ["push", "origin"], work, {"GIT_CONFIG_GLOBAL": str(evil)})]
        for plants, push, cwd, env in routes:
            try:
                for args in plants:
                    git(list(args), cwd=t if args[0] == "clone" else cwd)
                git(push, cwd=cwd, env=env)
            except JevError:
                pass
            else:
                raise AssertionError(f"{plants} then {push} ran")
            assert alive(), f"{plants} then {push} deleted the remote branch"
        # planted with plain git: JEV's explicit refspec wins over a push
        # refspec in config, and git refuses a mirror remote beside one
        def plant(*kv: str) -> None:
            subprocess.run(["git", "config", *kv], cwd=work, check=True, stdin=subprocess.DEVNULL)
        plant("remote.origin.push", ":refs/heads/keep")
        assert git(["push", "-q", "origin", "HEAD:refs/heads/x"], cwd=work).ok and alive()
        plant("remote.origin.mirror", "true")
        assert not git(["push", "-q", "origin", "HEAD:refs/heads/y"], cwd=work).ok and alive()


def test_the_git_guard_holds_init_and_the_environment_and_pins_the_pack_programs():
    """A third review planted `remote.origin.receivepack` — a program git runs
    on a push to a local or ssh remote, explicit refspec or not — through
    `init --template`, a clone's GIT_TEMPLATE_DIR and a push's GIT_COMMON_DIR,
    and deleted a remote branch. Each route is refused; HOME and
    XDG_CONFIG_HOME cannot move the global config; and a receivepack or
    uploadpack planted past the guard never runs, because git() names the
    pack program itself."""
    from tools.jev.common import assert_safe_git
    from tools.jev.workspace import CLONE_ENV, CLONE_OPTS
    for argv in (["init", "--template=/tmp/t", "w"], ["init", "-q", "--template", "/tmp/t", "w"],
                 ["init", "--templ=/tmp/t", "w"], ["init", "--separate-git-dir=/tmp/g", "w"],
                 ["init", "--shared=all", "w"], ["init", "-q", "a", "b"], ["fetch", "--upload-pack", "sh", "origin"]):
        try:
            assert_safe_git(argv)
        except JevError as exc:
            assert "refusing" in str(exc), (argv, exc)
        else:
            raise AssertionError(f"git {argv} was not refused")
    for env in ({"GIT_TEMPLATE_DIR": "/tmp/t"}, {"GIT_COMMON_DIR": "/tmp/r.git"}, {"GIT_SSH_COMMAND": "sh -c x"},
                {"GIT_SSH": "/tmp/x"}, {"GIT_PROXY_COMMAND": "/tmp/x"}, {"GIT_ASKPASS": "/tmp/x"},
                {"GIT_EXTERNAL_DIFF": "/tmp/x"}, {"GIT_NAMESPACE": "x"}, {"GIT_OBJECT_DIRECTORY": "/tmp/o"},
                {"GIT_WORK_TREE": "/tmp/w"}, {"GIT_INDEX_FILE": "/tmp/i"}, {"GIT_CONFIG_SYSTEM": "/tmp/s"},
                {"HOME": "/tmp/evil-home"}, {"XDG_CONFIG_HOME": "/tmp/evil-xdg"},
                {"HOME": "/tmp/evil-home", "GIT_CONFIG_GLOBAL": "/tmp/evil.cfg"}):
        try:
            assert_safe_git(["push", "origin", "HEAD:refs/heads/x"], env)
        except JevError as exc:
            assert "environment" in str(exc), (env, exc)
        else:
            raise AssertionError(f"{env} was not refused")
    # what JEV itself hands git still passes: the clone's env, engine_git's env
    # (the caller's own HOME), and a moved HOME once the global config is /dev/null
    assert_safe_git(["clone", "--branch", "main", *CLONE_OPTS, "/src", "/dest"], CLONE_ENV)
    engine_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    engine_env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    assert_safe_git(["status"], engine_env)
    assert_safe_git(["status"], {"HOME": "/tmp/h", "GIT_CONFIG_GLOBAL": "/dev/null"})
    assert assert_safe_git(["init", "-q", "-b", "main"]) == 0
    assert_safe_git(["init", "-q", "--bare", "-b", "main", "r"])
    assert assert_safe_git(["-C", "/w", "push", "origin", "HEAD:refs/heads/x"]) == 2
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        remote, work = t / "remote.git", t / "work"
        assert git(["init", "-q", "--bare", "-b", "main", str(remote)], cwd=t).ok
        assert git(["clone", "-q", str(remote), str(work)], cwd=t).ok
        commit = ["-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "m"]
        (work / "f").write_text("x\n")
        assert git(["add", "f"], cwd=work).ok and git(commit, cwd=work).ok
        assert git(["push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/keep"], cwd=work).ok
        marker = t / "pack-program-ran"
        rp = t / "rp.sh"   # deletes keep, then does a real receive-pack so the push still "works"
        rp.write_text(f'#!/bin/sh\ntouch {marker}\ngit --git-dir="$1" update-ref -d refs/heads/keep\n'
                      'exec git-receive-pack "$@"\n')
        up = t / "up.sh"
        up.write_text(f'#!/bin/sh\ntouch {marker}\nexec git-upload-pack "$@"\n')
        for p in (rp, up):
            p.chmod(0o755)
        tpl = t / "tpl"
        tpl.mkdir()
        (tpl / "config").write_text(f'[remote "origin"]\n\treceivepack = {rp}\n')
        other = t / "other.git"
        assert subprocess.run(["git", "init", "-q", "--bare", str(other)], stdin=subprocess.DEVNULL).returncode == 0
        subprocess.run(["git", "--git-dir", str(other), "config", "remote.origin.receivepack", str(rp)], check=True)
        home = t / "home"
        home.mkdir()
        (home / ".gitconfig").write_text(f'[remote "origin"]\n\treceivepack = {rp}\n')

        def alive() -> bool:
            return git(["--git-dir", str(remote), "rev-parse", "--verify", "-q", "refs/heads/keep"], cwd=t).ok
        # the review's routes, each with the push that would follow it
        routes = [(["init", "-q", "-b", "main", f"--template={tpl}", str(t / "w1")], None, t / "w1"),
                  (["clone", "-q", "--branch", "main", *CLONE_OPTS, str(remote), str(t / "w2")],
                   {"GIT_TEMPLATE_DIR": str(tpl)}, t / "w2"),
                  (None, {"GIT_COMMON_DIR": str(other)}, work),
                  (None, {"HOME": str(home)}, work)]
        for plant, env, cwd in routes:
            try:
                if plant:
                    git(plant, cwd=t, env=env if plant[0] == "clone" else None)
                git(["push", "-q", "origin", "HEAD:refs/heads/x"], cwd=cwd, env=None if plant else env)
            except JevError:
                pass
            else:
                raise AssertionError(f"{plant} / {env} then a push ran")
            assert alive() and not marker.exists(), f"{plant} / {env} ran the planted receive-pack"
        # planted behind the guard's back with plain git: git() names the pack
        # program itself, so neither the receivepack nor the uploadpack runs
        for key, value in (("remote.origin.receivepack", rp), ("remote.origin.uploadpack", up)):
            subprocess.run(["git", "config", key, str(value)], cwd=work, check=True, stdin=subprocess.DEVNULL)
        assert git(["push", "-q", "origin", "HEAD:refs/heads/x"], cwd=work).ok
        assert git(["fetch", "--quiet", "origin", "main"], cwd=work).ok
        assert alive() and not marker.exists(), "a planted pack program ran"
        # the control: plain git with the planted config does run it (so the probe is real)
        plain = ["git", "-c", "core.hooksPath=/dev/null", "push", "-q", "origin", "HEAD:refs/heads/y"]
        assert subprocess.run(plain, cwd=work, stdin=subprocess.DEVNULL, capture_output=True).returncode == 0
        assert marker.exists() and not alive(), "the probe's receive-pack never ran under plain git"


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


ROADMAP = "_data/roadmap.yml"


def entry(fid: str, title: str) -> str:
    return f"\n- id: {fid}\n  title: \"{title}\"\n  status: proposed\n"


def roadmap_conflict(base: str, ours: str, theirs: str, extra: dict | None = None) -> Path:
    """A real repository mid-merge of main INTO a feature branch, with the
    roadmap conflicted: `ours` is the branch's file, `theirs` main's."""
    d = Path(tempfile.mkdtemp()) / "repo"
    (d / "_data").mkdir(parents=True)
    git(["init", "-q", "-b", "main"], cwd=d)
    git(["config", "user.name", "t"], cwd=d)
    git(["config", "user.email", "t@example.com"], cwd=d)
    for rel, text in (extra or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    (d / ROADMAP).write_text(base)
    git(["add", "-A"], cwd=d)
    git(["commit", "-qm", "base"], cwd=d)
    git(["checkout", "-qb", "feature"], cwd=d)
    (d / ROADMAP).write_text(ours)
    git(["commit", "-qam", "ours"], cwd=d)
    git(["checkout", "-q", "main"], cwd=d)
    (d / ROADMAP).write_text(theirs)
    git(["commit", "-qam", "theirs"], cwd=d)
    git(["checkout", "-q", "feature"], cwd=d)
    git(["merge", "--no-ff", "main", "-m", "merge"], cwd=d)
    assert git(["diff", "--name-only", "--diff-filter=U"], cwd=d).out.strip() == ROADMAP
    return d


BASE = entry("FF-0001", "one")


def test_an_append_path_is_its_own_kind_and_the_dangerous_kinds_still_win():
    assert cls.kind_of(ROADMAP, append=[ROADMAP]) == cls.APPEND
    assert cls.kind_of(ROADMAP) == cls.SOURCE
    assert cls.kind_of(".github/workflows/x.yml", append=[".github/workflows/*"]) == cls.WORKFLOW
    assert cls.APPEND in cls.DETERMINISTIC_KINDS


def test_two_branches_appending_to_the_roadmap_resolve_main_first_then_the_branch():
    # the conflict #555 and #563 (and #553) kept having: each appends one entry at the end
    d = roadmap_conflict(BASE, BASE + entry("FF-0003", "branch"), BASE + entry("FF-0002", "main"))
    assert cf.append_kind(d, ROADMAP) == cls.APPEND
    ws = cf.Workspace(path=d, pr=pr(), merge_failed=True,
                      conflicted=[cls.ConflictFile(ROADMAP, 1, 8, cls.APPEND)])
    done, detail = cf.resolve_tier0(ws)
    assert done and "append (main's entries, then this branch's)" in detail, detail
    import yaml
    data = yaml.safe_load((d / ROADMAP).read_text())
    assert [e["id"] for e in data] == ["FF-0001", "FF-0002", "FF-0003"], data
    good, problems = cf.validate(d)
    assert good, problems


def test_an_edit_to_an_existing_entry_is_not_an_append_and_escalates():
    # union would keep both titles under one key and YAML would silently keep the last
    edited = lambda title: entry("FF-0001", title)  # noqa: E731
    d = roadmap_conflict(BASE, edited("branch's title"), edited("main's title"))
    text, why = cf.append_resolution(d, ROADMAP)
    assert text is None and "changes or deletes" in why, why
    assert cf.append_kind(d, ROADMAP) == cls.SOURCE


def test_two_branches_claiming_one_id_escalate_to_a_person():
    # what #555 and #563 did with FF-0033: a numbering question, not a merge
    d = roadmap_conflict(BASE, BASE + entry("FF-0002", "branch"), BASE + entry("FF-0002", "main"))
    text, why = cf.append_resolution(d, ROADMAP)
    assert text is None and "both sides claim id FF-0002" in why, why
    assert cf.append_kind(d, ROADMAP) == cls.SOURCE


def test_an_append_that_breaks_the_yaml_escalates():
    d = roadmap_conflict(BASE, BASE + "\n- id: FF-0003\n  title: [unclosed\n",
                         BASE + entry("FF-0002", "main"))
    text, why = cf.append_resolution(d, ROADMAP)
    assert text is None and "not valid YAML" in why, why


def test_a_duplicate_key_in_the_result_is_refused_rather_than_silently_kept():
    import yaml
    try:
        yaml.load("- id: a\n  title: x\n  title: y\n", Loader=cf._UniqueKeyLoader)
    except yaml.YAMLError as exc:
        assert "duplicate key" in str(exc)
    else:
        raise AssertionError("a duplicate key was accepted")


def test_tier0_never_numbers_on_a_pull_request_branch():
    # ids are assigned on main (amendment 0002); `number apply` on the branch
    # would consume its fragments and pick numbers another branch may pick too
    d = conflicted_repo("file.txt merge=jev-regen\n")
    (d / "tools" / "jev").mkdir(parents=True)
    (d / "tools" / "jev" / "number.py").write_text("# stand-in\n")
    calls: list[list[str]] = []
    real = cf.run
    cf.run = lambda argv, **kw: calls.append(list(argv))  # noqa: E731
    try:
        ws = cf.Workspace(path=d, pr=pr(), merge_failed=True,
                          conflicted=[cls.ConflictFile("file.txt", 1, 2, cls.GENERATED)])
        done, detail = cf.resolve_tier0(ws)
    finally:
        cf.run = real
    assert done, detail
    assert not any("number" in a and "apply" in a for a in calls), calls


def test_a_compiled_catalog_takes_mains_copy_only_where_the_repo_compiles_it():
    # features.yml compiled from features.d is never edited by a pull request
    # (constitution § 5): keeping the branch's copy would drop what main compiled
    for compiled in (True, False):
        d = Path(tempfile.mkdtemp()) / "repo"
        (d / "features").mkdir(parents=True)
        git(["init", "-q", "-b", "main"], cwd=d)
        git(["config", "user.name", "t"], cwd=d)
        git(["config", "user.email", "t@example.com"], cwd=d)
        if compiled:
            (d / "features" / "features.d").mkdir()
            (d / "features" / "features.d" / "README.md").write_text("fragments\n")
        (d / "features" / "features.yml").write_text("base\n")
        git(["add", "-A"], cwd=d)
        git(["commit", "-qm", "base"], cwd=d)
        git(["checkout", "-qb", "feature"], cwd=d)
        (d / "features" / "features.yml").write_text("branch\n")
        git(["commit", "-qam", "ours"], cwd=d)
        git(["checkout", "-q", "main"], cwd=d)
        (d / "features" / "features.yml").write_text("main compiled HUB-064\n")
        git(["commit", "-qam", "theirs"], cwd=d)
        git(["checkout", "-q", "feature"], cwd=d)
        git(["merge", "--no-ff", "main", "-m", "merge"], cwd=d)
        ws = cf.Workspace(path=d, pr=pr(), merge_failed=True,
                          conflicted=[cls.ConflictFile("features/features.yml", 1, 2, cls.GENERATED)])
        done, detail = cf.resolve_tier0(ws)
        assert done, detail
        got = (d / "features" / "features.yml").read_text()
        assert got == ("main compiled HUB-064\n" if compiled else "branch\n"), (compiled, got, detail)


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

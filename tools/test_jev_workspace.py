#!/usr/bin/env python3
"""
Fixture tests for tools/jev/workspace.py — the local loop engine's throwaway
workspaces (#486, ADR 0002 P1). A workspace holds a repository the engine does
not trust, so what is tested is what keeps it from reaching back: a committed
symlink checks out as a plain file, the clone runs no hook and no fsmonitor
and holds no push URL, upstream remote or credential helper, a target that
commits the brief directory is refused, a change anywhere in `.git` (or a
nested `.git`) is caught, the engine's own git never runs a filter, fsmonitor
or submodule the agent planted — even with the tamper check bypassed — an
output is harvested only as a regular, singly linked file inside the clone,
and `destroy` never chmods through a symlink or chokes on an unreadable
directory.

No network: `clone` runs against a stub `gh` whose `repo clone` is a `git
clone` of a local fixture. Run: python3 tools/test_jev_workspace.py
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))

from tools.jev import workspace as W  # noqa: E402
from tools.jev.common import JevError, git  # noqa: E402

OUTSIDE = Path(tempfile.mkdtemp(prefix="jev-ws-outside-"))
SECRET = OUTSIDE / "secret.txt"
SECRET.write_text("not-for-the-clone\n", encoding="utf-8")
WORK = Path(tempfile.mkdtemp(prefix="jev-ws-work-"))
os.environ["JEV_WORK_ROOT"] = str(WORK)

STUB_GH = r'''#!__PY__
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["STUB_GH_LOG"], "a") as fh:
    fh.write(json.dumps(argv) + "\n")
if argv[:2] == ["repo", "clone"]:
    nwo, dest = argv[2], argv[3]
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    src = json.loads(os.environ["STUB_GH_FIXTURES"])[nwo]
    code = subprocess.run(["git", "clone", "--quiet", *rest, src, dest]).returncode
    if code == 0 and nwo in os.environ.get("STUB_GH_FORKS", ""):
        # what gh does for a fork (even, here, with --no-upstream: harden must cope)
        subprocess.run(["git", "-C", dest, "remote", "add", "upstream", "https://github.com/parent/repo.git"])
        subprocess.run(["git", "-C", dest, "config", "remote.upstream.gh-resolved", "base"])
    sys.exit(code)
sys.stderr.write("stub gh: unexpected " + " ".join(argv) + "\n")
sys.exit(3)
'''


def fixture_repo() -> Path:
    """A repository with a README and a committed symlink to a file outside it."""
    repo = Path(tempfile.mkdtemp(prefix="jev-ws-fixture-"))
    cfg = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    assert git(["init", "-q", "-b", "main"], cwd=repo).ok
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    os.symlink(SECRET, repo / "link")
    assert git(["add", "README.md", "link"], cwd=repo).ok
    assert git([*cfg, "commit", "-q", "-m", "fixture"], cwd=repo).ok, "fixture commit"
    return repo


FIXTURE = fixture_repo()
CFG = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def fixture_with(files: dict[str, str], gitlink: str | None = None) -> Path:
    """A repository committing `files` (and optionally a gitlink at `gitlink`)."""
    repo = Path(tempfile.mkdtemp(prefix="jev-ws-fixture-"))
    assert git(["init", "-q", "-b", "main"], cwd=repo).ok
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body, encoding="utf-8")
    assert git(["add", "-A"], cwd=repo).ok
    if gitlink:
        sha = git(["rev-parse", "HEAD"], cwd=FIXTURE).out.strip()
        assert git(["update-index", "--add", "--cacheinfo", f"160000,{sha},{gitlink}"], cwd=repo).ok
    assert git([*CFG, "commit", "-q", "-m", "fixture"], cwd=repo).ok
    return repo


def marker_filter(config: Path, marker: Path) -> None:
    """Plant a clean filter that drops `marker` when anything runs it."""
    with config.open("a", encoding="utf-8") as fh:
        fh.write(f'[filter "x"]\n\tclean = touch {marker}; cat\n')


def make(nwo: str = "bamr87/alpha", run_id: str | None = None) -> W.Workspace:
    run_id = run_id or f"t-{os.urandom(3).hex()}"
    return W.clone_local(FIXTURE, nwo, "main", run_id=run_id, brief_dir=".scout")


def cfg(ws: W.Workspace, key: str) -> str:
    return git(["config", "--local", "--get", key], cwd=ws.path).out.strip()


@contextlib.contextmanager
def env(**kv: str):
    saved = {k: os.environ.get(k) for k in kv}
    os.environ.update(kv)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --------------------------------------------------------------------------- #
# the clone
# --------------------------------------------------------------------------- #
def test_a_committed_symlink_checks_out_as_a_plain_file():
    ws = make()
    link = ws.path / "link"
    assert link.is_file() and not link.is_symlink(), "core.symlinks=false: the link is a text file"
    assert link.read_text(encoding="utf-8") == str(SECRET), "it holds the target path, never the target"
    W.destroy(ws)


def test_the_clone_is_hardened():
    ws = make()
    assert cfg(ws, "remote.origin.url") == "https://github.com/bamr87/alpha.git"
    assert cfg(ws, "remote.origin.pushurl") == "no-push://disabled"
    assert cfg(ws, "credential.helper") == ""
    assert cfg(ws, "core.fsmonitor") == "false"
    assert cfg(ws, "core.hooksPath") == "/dev/null"
    assert cfg(ws, "core.symlinks") == "false"
    assert "/.scout/" in (ws.path / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ws.tmp.is_dir() and ws.tmp == ws.path / ".scout" / ".tmp"
    assert ws.head_sha and len(ws.head_sha) == 40
    assert oct(ws.root.stat().st_mode & 0o777) == "0o700" and oct((WORK / ws.root.parent.name).stat().st_mode
                                                                  & 0o777) == "0o700"
    W.destroy(ws)


def test_clone_goes_through_gh_with_the_hardening_options():
    bindir = Path(tempfile.mkdtemp(prefix="jev-ws-bin-"))
    stub = bindir / "gh"
    stub.write_text(STUB_GH.replace("__PY__", sys.executable), encoding="utf-8")
    stub.chmod(0o755)
    log = bindir / "gh.log"
    with env(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", STUB_GH_LOG=str(log),
             STUB_GH_FIXTURES=json.dumps({"bamr87/alpha": str(FIXTURE)})):
        ws = W.clone("bamr87/alpha", "main", run_id="t-gh", brief_dir=".scout")
    [call] = [json.loads(x) for x in log.read_text().splitlines()]
    assert call[:4] == ["repo", "clone", "bamr87/alpha", str(ws.path)]
    assert "--no-upstream" in call[:call.index("--")], "a fork's parent is never added as a remote"
    tail = call[call.index("--") + 1:]
    for opt in ("--no-recurse-submodules", "core.symlinks=false", "core.hooksPath=/dev/null", "--branch"):
        assert opt in tail, opt
    assert cfg(ws, "remote.origin.pushurl") == "no-push://disabled"
    W.destroy(ws)


def test_a_forks_upstream_remote_is_removed_whatever_cloned_it():
    bindir = Path(tempfile.mkdtemp(prefix="jev-ws-bin-"))
    stub = bindir / "gh"
    stub.write_text(STUB_GH.replace("__PY__", sys.executable), encoding="utf-8")
    stub.chmod(0o755)
    with env(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", STUB_GH_LOG=str(bindir / "gh.log"),
             STUB_GH_FIXTURES=json.dumps({"bamr87/fork": str(FIXTURE)}), STUB_GH_FORKS="bamr87/fork"):
        ws = W.clone("bamr87/fork", "main", run_id="t-fork", brief_dir=".scout")
    assert git(["remote"], cwd=ws.path).out.split() == ["origin"]
    pushes = git(["config", "--get-regexp", r"^remote\..*\.pushurl$"], cwd=ws.path).out.split()
    assert pushes == ["remote.origin.pushurl", "no-push://disabled"], pushes
    assert not git(["config", "--get", "remote.upstream.gh-resolved"], cwd=ws.path).ok
    W.destroy(ws)


def test_a_target_that_commits_the_brief_directory_is_refused_and_leaves_nothing():
    for files in ({".scout/proposals.json": '{"proposals": [{"title": "planted"}]}'}, {".scout": "a file\n"},
                  {".scout/.tmp": "a file\n"}):
        src = fixture_with(files)
        rid = f"t-brief-{os.urandom(3).hex()}"
        try:
            W.clone_local(src, "bamr87/alpha", "main", run_id=rid, brief_dir=".scout")
        except JevError as exc:
            assert "commits .scout/" in str(exc), exc
        else:
            raise AssertionError(f"a target committing {list(files)} was accepted")
        assert not (WORK / rid).exists(), "the refused clone is removed with its run directory"


def test_a_ctrl_c_during_the_clone_or_the_hardening_leaves_no_clone_behind():
    """KeyboardInterrupt is no Exception: the clone (a private repository's
    content, perhaps) must still go, whichever step it lands in."""
    real = (W.git, W.harden, W._pristine_gitdir)

    def git_then_interrupt(args, cwd, **kw):
        res = real[0](args, cwd, **kw)
        if args[:1] == ["clone"]:
            raise KeyboardInterrupt
        return res

    def interrupt(*_a, **_kw):
        raise KeyboardInterrupt
    for name, patch in (("git", git_then_interrupt), ("harden", interrupt), ("_pristine_gitdir", interrupt)):
        rid = f"t-int-{name.strip('_')}-{os.urandom(3).hex()}"
        setattr(W, name, patch)
        try:
            W.clone_local(FIXTURE, "bamr87/alpha", "main", run_id=rid, brief_dir=".scout")
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError(f"{name}: the interrupt was swallowed")
        finally:
            W.git, W.harden, W._pristine_gitdir = real
        assert not (WORK / rid).exists(), f"Ctrl-C in {name}: the clone and its run directory are removed"


def test_a_brief_dir_that_leaves_the_clone_is_refused():
    for bad in ("../escape", str(OUTSIDE / "abs"), ".", "a/../../b", ".git", "x/.git", ""):
        rid = f"t-bd-{os.urandom(3).hex()}"
        try:
            W.clone_local(FIXTURE, "bamr87/alpha", "main", run_id=rid, brief_dir=bad)
        except JevError as exc:
            assert "brief_dir" in str(exc), exc
        else:
            raise AssertionError(f"brief_dir {bad!r} was accepted")
        assert not (WORK / rid).exists() and not (OUTSIDE / "abs").exists()


def test_a_work_root_inside_the_hub_is_refused():
    with env(JEV_WORK_ROOT=str(HUB / ".fleet" / "work")):
        try:
            make(run_id="t-hub")
        except JevError as exc:
            assert "inside the hub" in str(exc)
        else:
            raise AssertionError("a work root under the hub was accepted")
    assert not (HUB / ".fleet" / "work").exists()


def test_a_bad_nwo_or_run_id_is_refused():
    for nwo, rid in (("not a slug", "t-1"), ("o/r", "../escape"), ("o/r", "")):
        try:
            W.clone_local(FIXTURE, nwo, "main", run_id=rid, brief_dir=".scout")
        except JevError:
            continue
        raise AssertionError(f"accepted {nwo!r} / {rid!r}")


# --------------------------------------------------------------------------- #
# tamper baseline and the tree
# --------------------------------------------------------------------------- #
def test_tampering_with_git_config_or_hooks_is_caught():
    ws = make()
    assert W.tampered(ws) == []
    with (ws.path / ".git" / "config").open("a") as fh:
        fh.write("[core]\n\tfsmonitor = /tmp/evil\n")
    assert W.tampered(ws) == ["config"]
    ws2 = make()
    (ws2.path / ".git" / "hooks" / "post-checkout").write_text("#!/bin/sh\n")
    assert W.tampered(ws2) == ["hooks/post-checkout"]
    W.destroy(ws)
    W.destroy(ws2)


def test_every_git_entry_that_redirects_config_or_objects_is_in_the_baseline():
    cases = {"HEAD": lambda g: (g / "HEAD").write_text("ref: refs/heads/other\n"),
             "info/exclude": lambda g: (g / "info" / "exclude").open("a").write("x\n"),
             "commondir": lambda g: (g / "commondir").write_text("../elsewhere\n"),
             "config.worktree": lambda g: (g / "config.worktree").write_text("[core]\n"),
             "info/attributes": lambda g: (g / "info" / "attributes").write_text("* filter=x\n"),
             "objects/info/alternates": lambda g: (g / "objects" / "info" / "alternates").write_text("/x\n"),
             "worktrees/": lambda g: (g / "worktrees").mkdir(),
             "modules/": lambda g: (g / "modules").mkdir()}
    for key, plant in cases.items():
        ws = make()
        plant(ws.path / ".git")
        assert key in W.tampered(ws), (key, W.tampered(ws))
        W.destroy(ws)
    ws = make()
    (ws.path / "sub").mkdir()
    (ws.path / "sub" / ".git").write_text("gitdir: /elsewhere\n")
    assert W.tampered(ws) == ["nested .git"]
    (ws.path / "sub" / ".git").unlink()
    (ws.path / ".scout" / ".tmp" / "scratch").mkdir()
    (ws.path / ".scout" / ".tmp" / "scratch" / ".git").mkdir()   # a test suite's repo under TMPDIR
    (ws.path / ".git" / "index").write_bytes(b"rewritten by the agent's own git status")
    assert W.tampered(ws) == [], "the brief directory and the index are not configuration"
    W.destroy(ws)


def test_the_pristine_git_dir_sits_beside_the_clone_not_in_it():
    ws = make()
    assert ws.gitdir == ws.root / W.PRISTINE and ws.gitdir.is_dir()
    assert not ws.gitdir.is_relative_to(ws.path), "outside the agent's write root"
    assert oct(ws.gitdir.stat().st_mode & 0o777) == "0o700"
    W.destroy(ws)


@contextlib.contextmanager
def _bypass_tamper_check():
    """The engine's git, with the tamper refusal switched off: what the
    pristine GIT_DIR alone still guarantees."""
    saved = W.tampered
    W.tampered = lambda ws: []
    try:
        yield
    finally:
        W.tampered = saved


def test_a_filter_planted_in_git_config_never_runs_in_the_engines_git():
    ws = make()
    marker = OUTSIDE / f"PWNED-config-{os.urandom(3).hex()}"
    marker_filter(ws.path / ".git" / "config", marker)
    (ws.path / ".gitattributes").write_text("* filter=x\n")
    (ws.path / "README.md").write_text("# fixturX\n")   # same size: git must hash it
    for call in (W.tree_report, W.discard_tracked):
        try:
            call(ws)
        except JevError as exc:
            assert "changed (config)" in str(exc), exc
        else:
            raise AssertionError(f"{call.__name__} ran git in a tampered clone")
    with _bypass_tamper_check():
        rep = W.tree_report(ws)
        W.discard_tracked(ws)
    assert "README.md" in rep.tracked and not marker.exists(), "the pristine GIT_DIR defines no filter"
    assert (ws.path / "README.md").read_text() == "# fixture\n", "checkout ran through the pristine index"
    git(["status", "--porcelain"], cwd=ws.path)   # control: the clone's own git does run it
    assert marker.exists(), "control: the planted filter is real"
    W.destroy(ws)


def test_a_commondir_redirect_is_caught_and_never_read():
    ws = make()
    marker = OUTSIDE / f"PWNED-commondir-{os.urandom(3).hex()}"
    planted = ws.path / ".scout" / "c"
    shutil.copytree(ws.path / ".git", planted)
    marker_filter(planted / "config", marker)
    (ws.path / ".git" / "commondir").write_text(f"{planted}\n")
    (ws.path / ".gitattributes").write_text("* filter=x\n")
    (ws.path / "README.md").write_text("# fixturX\n")
    assert "commondir" in W.tampered(ws)
    with _bypass_tamper_check():
        W.tree_report(ws)
        W.discard_tracked(ws)
    assert not marker.exists(), "the engine's git never reads the clone's config or commondir"
    git(["status", "--porcelain"], cwd=ws.path)   # control: the clone's own git follows commondir
    assert marker.exists(), "control: the planted commondir is real"
    W.destroy(ws)


def test_a_gitfile_planted_in_a_submodule_directory_is_caught_and_never_followed():
    src = fixture_with({}, gitlink="sub")
    ws = W.clone_local(src, "bamr87/alpha", "main", run_id=f"t-sub-{os.urandom(3).hex()}", brief_dir=".scout")
    assert (ws.path / "sub").is_dir() and not any((ws.path / "sub").iterdir()), "--no-recurse-submodules: empty"
    marker = OUTSIDE / f"PWNED-sub-{os.urandom(3).hex()}"
    planted = ws.path / ".scout" / "c"
    shutil.copytree(ws.path / ".git", planted)
    marker_filter(planted / "config", marker)
    (ws.path / "sub" / ".git").write_text(f"gitdir: {planted}\n")
    (ws.path / "sub" / ".gitattributes").write_text("* filter=x\n")
    (ws.path / "sub" / "README.md").write_text("# fixturX\n")
    assert W.tampered(ws) == ["nested .git"], W.tampered(ws)
    with _bypass_tamper_check():
        W.tree_report(ws)
    assert not marker.exists(), "--ignore-submodules=all: no submodule is entered"
    git(["status", "--porcelain"], cwd=ws.path / "sub")   # control: plain git follows the planted gitfile
    assert marker.exists(), "control: the planted gitfile is real"
    W.destroy(ws)


def test_the_git_wrapper_never_runs_a_repositorys_fsmonitor():
    repo = fixture_with({})
    marker = OUTSIDE / f"PWNED-fsmonitor-{os.urandom(3).hex()}"
    script = OUTSIDE / f"fsmonitor-{os.urandom(3).hex()}.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    assert git(["config", "--local", "core.fsmonitor", str(script)], cwd=repo).ok
    assert git(["status", "--porcelain"], cwd=repo).ok
    assert not marker.exists(), "common.git passes core.fsmonitor=false"
    subprocess.run(["git", "status", "--porcelain"], cwd=repo, stdin=subprocess.DEVNULL, capture_output=True,
                   check=False)   # control: git without the wrapper runs it
    assert marker.exists(), "control: the planted fsmonitor is real"


def test_a_filter_in_the_users_global_or_system_config_never_runs_in_the_engines_git():
    """The tamper check sees nothing here: `.gitattributes` is the agent's to
    write, and the filter lives in the user's own config, outside `.git`. Only
    engine_git's GIT_CONFIG_GLOBAL=/dev/null (and GIT_CONFIG_NOSYSTEM, for the
    machine's own system file, which a test cannot write) keep it from running
    on the host."""
    ws = make()
    home = Path(tempfile.mkdtemp(prefix="jev-ws-home-"))
    marker = OUTSIDE / f"PWNED-global-{os.urandom(3).hex()}"
    marker_filter(home / ".gitconfig", marker)
    (ws.path / ".gitattributes").write_text("* filter=x\n")
    (ws.path / "README.md").write_text("# fixturX\n")   # same size: git must hash it
    seen: list[dict] = []
    real_git = W.git

    def spy(args, cwd, **kw):
        seen.append(dict(kw.get("env") or {}))
        return real_git(args, cwd, **kw)
    W.git = spy
    try:
        with env(HOME=str(home), XDG_CONFIG_HOME=str(home / "xdg"), GIT_CONFIG_SYSTEM=str(home / ".gitconfig")):
            assert W.tampered(ws) == [], "nothing under .git changed"
            rep = W.tree_report(ws)
            W.discard_tracked(ws)
            assert "README.md" in rep.tracked and not marker.exists(), "the engine's git reads no global config"
            (ws.path / "README.md").write_text("# fixturX\n")
            subprocess.run(["git", "status", "--porcelain"], cwd=ws.path, stdin=subprocess.DEVNULL,
                           capture_output=True, check=False)   # control: plain git with this HOME runs it
    finally:
        W.git = real_git
    assert marker.exists(), "control: the global filter is real"
    assert seen and all(e.get("GIT_CONFIG_GLOBAL") == "/dev/null" and e.get("GIT_CONFIG_NOSYSTEM") == "1"
                        and "GIT_CONFIG_SYSTEM" not in e for e in seen), "no global or system config, ever"
    W.destroy(ws)


def test_the_tree_report_ignores_the_brief_and_discard_restores_tracked_files():
    ws = make()
    (ws.path / ".scout" / "brief.md").write_text("brief\n")
    (ws.path / ".scout" / "proposals.json").write_text("[]\n")
    assert W.tree_report(ws) == W.TreeReport([], [])
    (ws.path / "README.md").write_text("edited\n")
    (ws.path / "stray.txt").write_text("x\n")
    rep = W.tree_report(ws)
    assert rep.tracked == ["README.md"] and rep.untracked == ["stray.txt"], rep
    W.discard_tracked(ws)
    assert (ws.path / "README.md").read_text() == "# fixture\n"
    assert W.tree_report(ws).tracked == []
    W.destroy(ws)


def test_place_copies_a_file_inside_and_refuses_an_escape():
    ws = make()
    src = OUTSIDE / "brief.md"
    src.write_text("b\n")
    assert W.place(ws, src, ".scout/brief.md").read_text() == "b\n"
    for bad in ("../x", "/etc/x", ""):
        try:
            W.place(ws, src, bad)
        except JevError:
            continue
        raise AssertionError(bad)
    W.destroy(ws)


# --------------------------------------------------------------------------- #
# harvest
# --------------------------------------------------------------------------- #
def test_harvest_copies_a_regular_file_with_its_digest():
    ws = make()
    body = b'{"proposals": []}\n'
    (ws.path / ".scout" / "proposals.json").write_bytes(body)
    dest = Path(tempfile.mkdtemp())
    h = W.harvest(ws, ".scout/proposals.json", dest)
    assert h.reason == "ok" and h.dest == dest / ".scout" / "proposals.json" and h.dest.read_bytes() == body
    assert h.sha256 == hashlib.sha256(body).hexdigest() and h.size == len(body)
    assert W.harvest(ws, ".scout/absent.json", dest).reason == "absent"
    W.destroy(ws)


def test_harvest_refuses_a_symlink_fifo_hardlink_oversize_or_escape():
    ws = make()
    dest = Path(tempfile.mkdtemp())
    scout = ws.path / ".scout"
    os.symlink(SECRET, scout / "proposals.json")
    assert W.harvest(ws, ".scout/proposals.json", dest).reason == "symlink"
    (scout / "proposals.json").unlink()
    os.mkfifo(scout / "proposals.json")   # a FIFO must not hang the engine
    assert W.harvest(ws, ".scout/proposals.json", dest).reason == "not-regular"
    (scout / "proposals.json").unlink()
    inside_copy = ws.path / "hl-source"
    inside_copy.write_text("x")
    os.link(inside_copy, scout / "proposals.json")
    assert W.harvest(ws, ".scout/proposals.json", dest).reason == "hardlink"
    (scout / "proposals.json").unlink()
    (scout / "proposals.json").write_bytes(b"x" * (W.HARVEST_MAX + 1))
    assert W.harvest(ws, ".scout/proposals.json", dest).reason == "too-large"
    (scout / "proposals.json").unlink()
    os.rmdir(ws.tmp)
    os.rmdir(scout)
    os.symlink(OUTSIDE, scout)          # a symlinked directory on the way out
    (OUTSIDE / "proposals.json").write_text("[]")
    assert W.harvest(ws, ".scout/proposals.json", dest).reason == "symlink"
    assert W.harvest(ws, "../x.json", dest).reason == "bad-path"
    assert not any(dest.rglob("*.json")), "nothing refused was copied"
    secret_mode, outside_mode = SECRET.stat().st_mode, OUTSIDE.stat().st_mode
    W.destroy(ws)
    assert SECRET.is_file() and OUTSIDE.is_dir(), "destroy never follows a symlink out"
    assert (SECRET.stat().st_mode, OUTSIDE.stat().st_mode) == (secret_mode, outside_mode), "nor chmods one"


# --------------------------------------------------------------------------- #
# destroy
# --------------------------------------------------------------------------- #
def test_destroy_removes_the_item_and_the_empty_run_directory():
    ws = make(run_id="t-destroy")
    ro = ws.path / "ro"
    ro.mkdir()
    (ro / "f").write_text("x")
    ro.chmod(0o500)                     # an agent may leave a read-only directory
    W.destroy(ws)
    assert not ws.root.exists() and not (WORK / "t-destroy").exists()


def test_destroy_copes_with_unreadable_directories():
    for mode in (0o000, 0o100, 0o200, 0o300):
        rid = f"t-unreadable-{mode:o}"
        ws = make(run_id=rid)
        full, empty = ws.path / "full", ws.path / "empty"
        full.mkdir()
        (full / "f").write_text("x")
        empty.mkdir()
        full.chmod(mode)
        empty.chmod(mode)
        W.destroy(ws)
        assert not ws.root.exists() and not (WORK / rid).exists(), oct(mode)


def test_destroy_never_chmods_through_a_symlink():
    victim_file = OUTSIDE / f"victim-{os.urandom(3).hex()}.txt"
    victim_file.write_text("keep my mode\n")
    victim_file.chmod(0o400)
    victim_dir = OUTSIDE / f"victim-dir-{os.urandom(3).hex()}"
    victim_dir.mkdir()
    victim_dir.chmod(0o555)
    ws = make(run_id="t-symlink-chmod")
    for n, target in enumerate((victim_file, victim_dir)):
        d = ws.path / f"ro{n}"
        d.mkdir()
        os.symlink(target, d / "ln")
        d.chmod(0o500)
    W.destroy(ws)
    assert not ws.root.exists()
    assert victim_file.stat().st_mode & 0o777 == 0o400, oct(victim_file.stat().st_mode)
    assert victim_dir.stat().st_mode & 0o777 == 0o555, oct(victim_dir.stat().st_mode)
    victim_dir.chmod(0o755)


def test_destroy_keeps_a_run_directory_that_still_has_items():
    a = make(nwo="bamr87/alpha", run_id="t-two")
    b = make(nwo="bamr87/beta", run_id="t-two")
    W.destroy(a)
    assert (WORK / "t-two").is_dir() and b.path.is_dir()
    W.destroy(b)
    assert not (WORK / "t-two").exists()


def test_importing_the_module_has_no_side_effects():
    out = subprocess.run([sys.executable, "-c", "import tools.jev.workspace"], cwd=HUB, capture_output=True,
                         text=True, check=False)
    assert out.returncode == 0 and out.stdout == "" and out.stderr == "", out.stderr


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

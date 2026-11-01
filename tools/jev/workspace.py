#!/usr/bin/env python3
"""
File: tools/jev/workspace.py
Description: The local loop engine's throwaway workspaces (#486, ADR 0002 P1).
             Each item gets a fresh clone of its target OUTSIDE the hub tree —
             under `~/.cache/jev/work/<run_id>/` (0700; JEV_WORK_ROOT
             overrides), inside the sandbox's home fence, so a session there
             walks up to no hub CLAUDE.md, no hub scanner meets a nested clone,
             and the fence hides every other run. The clone is hardened (a
             committed symlink is a plain file, no hooks, no fsmonitor, no
             credential helper, no push URL on any remote, no upstream remote,
             no submodules, no LFS smudge), refused when the target commits the
             brief directory, and carries a tamper baseline over all of `.git`
             but its objects and index plus any nested `.git`. Once an agent
             could have touched the clone the engine's git reads none of its
             `.git` configuration: status and checkout run against an
             engine-held copy of the fresh GIT_DIR beside the clone (sharing
             only the object store; no global or system config, no attributes
             file, no submodule), and refuse a tampered clone. A clone is
             removed on any failure before it is handed back, Ctrl-C included. The
             harvest follows no symlink: only a regular file inside the clone,
             read from the descriptor that was checked, ever leaves it, and
             `destroy` never chmods or follows a link out of it; `place`
             writes only a new file, under directories lstat-ed as real ones
             (O_EXCL | O_NOFOLLOW), so no link in a clone redirects an
             engine write.
Author: bamr87
Created: 2026-10-31
Version: 0.1.0
Usage: imported by tools/jev/loop.py.
Dependencies: Python 3.12 stdlib, git, and gh for `clone` (via common.gh).
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .common import JevError, gh, git, is_clone_relpath, is_nwo
from .headless import work_root, work_root_problem

RUN_ID_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
#: `git clone` options every workspace is made with (after gh's `--`)
CLONE_OPTS = ("--no-recurse-submodules", "-c", "core.symlinks=false", "-c", "core.hooksPath=/dev/null",
              "-c", "core.fsmonitor=false")
CLONE_ENV = {"GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
HARVEST_MAX = 256 * 1024
TMP_NAME = ".tmp"
#: the engine-held copy of the fresh GIT_DIR, beside the clone (outside the agent's write root)
PRISTINE = ".gitdir-pristine"
#: `.git` entries the tamper baseline does not hash: content, not configuration,
#: never read by the engine's git (it runs on the pristine copy), and the index
#: is rewritten by the agent's own allowed `git status`
BASELINE_SKIP = ("objects", "index")
#: …except these, which redirect where objects are read from
BASELINE_ALSO = ("objects/info/alternates", "objects/info/http-alternates")
#: every engine git call on an agent-touched clone (with the pristine GIT_DIR)
ENGINE_GIT_OPTS = ("-c", "core.attributesFile=/dev/null", "-c", "submodule.recurse=false",
                   "-c", "diff.ignoreSubmodules=all", "-c", "core.symlinks=false")
DIRNAME_RX = re.compile(r"[A-Za-z0-9_.-]{1,160}")


@dataclass
class Workspace:
    root: Path        # <work root>/<run_id>/<owner>__<repo> — destroyed with the item
    path: Path        # the clone itself: <root>/<repo>
    nwo: str
    branch: str
    head_sha: str
    brief_dir: str
    baseline: dict[str, str] = field(default_factory=dict)
    gitdir: Path | None = None   # <root>/.gitdir-pristine — the engine's git reads only this

    @property
    def tmp(self) -> Path:
        """The agent's TMPDIR: inside the clone (the sandbox writes only there) and git-excluded."""
        return self.path / self.brief_dir / TMP_NAME


@dataclass
class TreeReport:
    tracked: list[str]
    untracked: list[str]


@dataclass
class Harvest:
    rel: str
    dest: Path | None
    sha256: str | None
    size: int
    reason: str   # ok | absent | symlink | not-regular | hardlink | too-large | escapes-workspace | bad-path


def slug(nwo: str) -> str:
    if not is_nwo(nwo):
        raise JevError(f"{nwo!r} is not an owner/repo slug")
    return nwo.replace("/", "__")


def item_dirname(key: str) -> str:
    """The directory an item's run record and workspace live in.

    A repo-keyed item (scout: the nwo) is `<owner>__<repo>`, as before; any
    other key (a doctor marker `owner/repo:path`, an issue `owner/repo#12`) is
    its safe characters plus 8 hex of its sha256, so two keys never share one.
    """
    if is_nwo(key):
        return slug(key)
    if not isinstance(key, str) or not key:
        raise JevError(f"{key!r} is not an item key")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("._-")[:60] or "item"
    return f"{safe}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:8]}"


def _private_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    p.chmod(0o700)


def _item_root(nwo: str, run_id: str, dirname: str | None = None) -> Path:
    if not RUN_ID_RX.fullmatch(run_id or ""):
        raise JevError(f"run id {run_id!r} must match {RUN_ID_RX.pattern}")
    name = slug(nwo) if dirname is None else dirname
    if not DIRNAME_RX.fullmatch(name or "") or name in (".", ".."):
        raise JevError(f"item directory {name!r} is not a plain name")
    base = work_root()
    problem = work_root_problem(base)
    if problem:
        raise JevError(f"{problem} — no workspace is made there")
    _private_dir(base)
    _private_dir(base / run_id)
    root = base / run_id / name
    if root.exists():
        raise JevError(f"workspace {root} already exists")
    _private_dir(root)
    return root


def check_brief_dir(brief_dir: object) -> str:
    """The brief directory, refused (JevError) unless it stays inside the clone
    (`common.is_clone_relpath`): the agent's TMPDIR and the git-exclude line
    are built from it, and destroy removes only what is under the item root."""
    if not is_clone_relpath(brief_dir):
        raise JevError(f"brief_dir {brief_dir!r} must be a relative path inside the clone (no '..', '.' or '.git')")
    return brief_dir


def _finish(root: Path, nwo: str, branch: str, brief_dir: str) -> Workspace:
    """Harden the fresh clone and take its baseline; an OSError is the item's
    JevError. The caller (`_made`) removes the root on any failure."""
    path = root / nwo.split("/", 1)[1]
    try:
        # the clone is fresh: git wrote its .git, nothing has run in it yet
        committed = git(["ls-tree", "-r", "--name-only", "HEAD", "--", brief_dir], cwd=path)
        if committed.out.strip() or os.path.lexists(path / brief_dir):
            raise JevError(f"{nwo} commits {brief_dir}/ — the brief directory must be the engine's alone "
                           "(a committed output would be harvested as the agent's)")
        head = git(["rev-parse", "HEAD"], cwd=path)
        ws = Workspace(root=root, path=path, nwo=nwo, branch=branch,
                       head_sha=head.out.strip() if head.ok else "", brief_dir=brief_dir)
        harden(ws)
        ws.gitdir = _pristine_gitdir(ws)
        ws.baseline = baseline(ws)
    except OSError as exc:
        raise JevError(f"could not prepare the workspace for {nwo}: {exc}") from exc
    return ws


def _made(root: Path, make) -> Workspace:
    """Run `make()` (the clone, then `_finish`) and hand back its Workspace — or
    remove `root` on ANY exit without one (a failure, a JevError, a Ctrl-C),
    so a private repository's content never stays behind in the work root."""
    try:
        return make()
    except BaseException:
        destroy_root(root)
        raise


def clone(nwo: str, branch: str, *, run_id: str, brief_dir: str, dirname: str | None = None) -> Workspace:
    """A fresh, hardened clone of `nwo` at `branch`, full history (CI's fetch-depth 0).
    `--no-upstream`: for a fork, gh would otherwise add and fetch the parent as
    a second remote with a live push URL."""
    check_brief_dir(brief_dir)
    root = _item_root(nwo, run_id, dirname)
    dest = root / nwo.split("/", 1)[1]

    def make() -> Workspace:
        res = gh(["repo", "clone", nwo, str(dest), "--no-upstream", "--", "--branch", branch, *CLONE_OPTS],
                 env=CLONE_ENV, timeout=900)
        if not res.ok:
            raise JevError(f"gh repo clone {nwo} ({branch}) failed: {(res.err or res.out).strip()[-300:]}")
        return _finish(root, nwo, branch, brief_dir)
    return _made(root, make)


def clone_local(src: Path, nwo: str, branch: str, *, run_id: str, brief_dir: str,
                dirname: str | None = None) -> Workspace:
    """The same workspace from a local repository (the tests and the canary)."""
    check_brief_dir(brief_dir)
    root = _item_root(nwo, run_id, dirname)
    dest = root / nwo.split("/", 1)[1]

    def make() -> Workspace:
        res = git(["clone", "--branch", branch, *CLONE_OPTS, str(src), str(dest)], cwd=root, env=CLONE_ENV)
        if not res.ok:
            raise JevError(f"git clone {src} failed: {res.err.strip()[-300:]}")
        return _finish(root, nwo, branch, brief_dir)
    return _made(root, make)


def harden(ws: Workspace) -> None:
    """Close every route by which the checkout's own config could run code or
    reach a credential, and hide the brief directory from git. Every remote but
    origin is removed, whatever cloned the repository."""
    remotes = git(["remote"], cwd=ws.path)
    if not remotes.ok:
        raise JevError(f"could not list the remotes of {ws.path}: {remotes.err.strip()}")
    for name in remotes.out.split():
        if name != "origin" and not git(["remote", "remove", name], cwd=ws.path).ok:
            raise JevError(f"could not remove the remote {name!r} from {ws.path}")
    for key, value in (("remote.origin.url", f"https://github.com/{ws.nwo}.git"),
                       ("remote.origin.pushurl", "no-push://disabled"),
                       ("credential.helper", ""),
                       ("core.fsmonitor", "false"),
                       ("core.hooksPath", "/dev/null"),
                       ("core.symlinks", "false")):
        res = git(["config", "--local", key, value], cwd=ws.path)
        if not res.ok:
            raise JevError(f"could not set {key} in {ws.path}: {res.err.strip()}")
    info = ws.path / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    with (info / "exclude").open("a", encoding="utf-8") as fh:
        fh.write(f"\n/{ws.brief_dir}/\n")
    ws.tmp.mkdir(parents=True, exist_ok=True)


def place(ws: Workspace, src: Path, rel: str) -> Path:
    """Copy `src` (a file the engine wrote) to `rel` inside the clone, as `place_bytes`."""
    return place_bytes(ws, Path(src).read_bytes(), rel)


def place_bytes(ws: Workspace, data: bytes, rel: str, *, mode: int = 0o666) -> Path:
    """Write `data` as a NEW file at `rel` inside the clone — never through a
    symlink, never over a file. Every directory on the way, the clone root
    included, is lstat-ed and must be a real directory (a missing one is made
    0700 and checked again), and the file is opened O_CREAT | O_EXCL |
    O_NOFOLLOW: an existing name, a dangling link included, refuses. So nothing
    a target commits or plants (a symlinked brief directory, a file already
    at the name) can redirect an engine write out of the clone or replace a
    file in it. `mode` is before the umask (0o666 is what shutil.copyfile
    gives, so a placed brief is the file it always was). The agent has not
    run yet when the engine places a file, so the walk-then-open window is
    not one it can race."""
    dest = _inside(ws, rel)
    node = ws.path
    for part in (None, *Path(rel).parts[:-1]):
        node = node if part is None else node / part
        try:
            st = os.lstat(node)
        except FileNotFoundError:
            try:
                os.mkdir(node, 0o700)
            except FileExistsError:   # made between the lstat and the mkdir: checked below like any other
                pass
            except OSError as exc:
                raise JevError(f"could not make {node} in the clone: {exc}") from exc
            st = os.lstat(node)
        if stat.S_ISLNK(st.st_mode):
            raise JevError(f"refusing to place {rel}: {node} is a symlink in the clone")
        if not stat.S_ISDIR(st.st_mode):
            raise JevError(f"refusing to place {rel}: {node} is not a directory")
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    except FileExistsError as exc:
        raise JevError(f"refusing to place {rel}: something is already at {dest} (the engine never overwrites "
                       "a file in the clone, nor writes through a link)") from exc
    except OSError as exc:
        raise JevError(f"could not place {rel} in the clone: {exc}") from exc
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return dest


def _inside(ws: Workspace, rel: str) -> Path:
    parts = Path(rel).parts
    if not rel or Path(rel).is_absolute() or ".." in parts:
        raise JevError(f"{rel!r} is not a path inside the workspace")
    return ws.path.joinpath(*parts)


def _sha_file(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "absent"


def _pristine_gitdir(ws: Workspace) -> Path:
    """Copy the fresh, hardened GIT_DIR to `<root>/.gitdir-pristine` (0700),
    sharing the clone's objects through `objects/info/alternates` — objects are
    content, read only. It sits beside the clone, outside the agent's write
    root, so nothing an agent writes under the clone's `.git` (config,
    commondir, info/attributes, a hook) is ever read by the engine's git."""
    src = ws.path / ".git"
    dest = ws.root / PRISTINE
    shutil.copytree(src, dest, symlinks=True, ignore=lambda d, names: ["objects"] if Path(d) == src else [])
    (dest / "objects" / "info").mkdir(parents=True)
    (dest / "objects" / "pack").mkdir()
    (dest / "objects" / "info" / "alternates").write_text(f"{(src / 'objects').resolve()}\n", encoding="utf-8")
    dest.chmod(0o700)
    return dest


def _git_inventory(g: Path) -> dict[str, str]:
    """Every entry under `.git` but BASELINE_SKIP: a regular file's sha256, a
    symlink's target (never followed), "dir", or "special" (a FIFO is never read)."""
    try:
        st = os.lstat(g)
    except FileNotFoundError:
        return {".git": "absent"}
    if not stat.S_ISDIR(st.st_mode):
        return {".git": "not-a-directory"}
    out: dict[str, str] = {}
    stack = [g]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            out[f"{d.relative_to(g).as_posix()}/"] = "unreadable"
            continue
        for e in entries:
            rel = Path(e.path).relative_to(g).as_posix()
            if rel in BASELINE_SKIP:
                continue
            if e.is_symlink():
                out[rel] = f"symlink:{os.readlink(e.path)}"
            elif e.is_dir(follow_symlinks=False):
                out[f"{rel}/"] = "dir"
                stack.append(Path(e.path))
            elif e.is_file(follow_symlinks=False):
                out[rel] = _sha_file(Path(e.path))
            else:
                out[rel] = "special"
    for rel in BASELINE_ALSO:
        p = g / rel
        out[rel] = (f"symlink:{os.readlink(p)}" if p.is_symlink() else _sha_file(p) if p.is_file()
                    else "special" if os.path.lexists(p) else "absent")
    return out


def _nested_git(ws: Workspace) -> list[str]:
    """Every `.git` below the worktree root (a gitfile planted in a submodule
    directory would point git at a config of the agent's choosing), outside
    the brief directory, which git never walks."""
    found: list[str] = []
    brief = Path(ws.brief_dir)
    for dirpath, dirnames, filenames in os.walk(ws.path, followlinks=False):
        rel = Path(dirpath).relative_to(ws.path)
        if rel != Path(".") and (".git" in dirnames or ".git" in filenames):
            found.append((rel / ".git").as_posix())
        dirnames[:] = [d for d in dirnames if d != ".git" and rel / d != brief]
    return sorted(found)


def baseline(ws: Workspace) -> dict[str, str]:
    """The tamper baseline: all of `.git` but its objects and index, the
    object redirects, and the list of nested `.git` entries."""
    out = _git_inventory(ws.path / ".git")
    out["nested .git"] = ",".join(_nested_git(ws))
    return out


def tampered(ws: Workspace) -> list[str]:
    """What changed in the baseline since the workspace was made ([] = nothing)."""
    now = baseline(ws)
    return sorted(k for k in set(now) | set(ws.baseline) if now.get(k) != ws.baseline.get(k))


def engine_git(ws: Workspace, args: list[str], *, timeout: int = 900):
    """git on an agent-touched clone, the only way the engine runs it there.

    Refused outright when the clone is tampered with. Otherwise it runs against
    the engine-held pristine GIT_DIR (`--git-dir`/`--work-tree`), with no global
    or system config, no attributes file, no submodule recursion and every
    inherited GIT_* variable dropped: a `.gitattributes` in the tree can then
    name only a filter that nothing defines, and no `.git` the agent wrote is read.
    """
    changed = tampered(ws)
    if changed:
        raise JevError(f"refusing to run git in {ws.path}: its .git changed ({', '.join(changed)})")
    if ws.gitdir is None or not ws.gitdir.is_dir():
        raise JevError(f"no engine-held GIT_DIR for {ws.path}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return git([f"--git-dir={ws.gitdir}", f"--work-tree={ws.path}", *ENGINE_GIT_OPTS, *args], cwd=ws.path,
               timeout=timeout, env=env, inherit_env=False)


def tree_report(ws: Workspace) -> TreeReport:
    """`git status` through `engine_git` (refused on a tampered clone), minus the brief directory."""
    res = engine_git(ws, ["status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=all"])
    if not res.ok:
        raise JevError(f"git status failed in {ws.path}: {res.err.strip()}")
    tracked, untracked = [], []
    for line in res.out.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if path == ws.brief_dir or path.startswith(ws.brief_dir.rstrip("/") + "/"):
            continue
        (untracked if code == "??" else tracked).append(path)
    return TreeReport(tracked=tracked, untracked=untracked)


def discard_tracked(ws: Workspace) -> None:
    """CI's "Verify the tree is untouched": tracked edits are thrown away
    (through `engine_git`: refused on a tampered clone)."""
    res = engine_git(ws, ["checkout", "--", "."])
    if not res.ok:
        raise JevError(f"git checkout failed in {ws.path}: {res.err.strip()}")


def harvest(ws: Workspace, rel: str, dest_dir: Path, *, max_bytes: int = HARVEST_MAX) -> Harvest:
    """Copy one declared output out of the clone without trusting the clone.

    Every component is checked with lstat (no symlinked directory on the way),
    the file is opened O_NOFOLLOW | O_NONBLOCK (a FIFO cannot hang the engine),
    the open descriptor must be a regular file with one link, no larger than
    `max_bytes`, and the bytes are copied from that descriptor — so the file
    read is the file checked. O_NOFOLLOW guards only the last component; the
    realpath check below is an untested belt against a parent directory
    swapped for a symlink between the lstat walk and the open (a race no
    deterministic test reaches; the agent has exited by harvest time).
    """
    try:
        target = _inside(ws, rel)
    except JevError:
        return Harvest(rel, None, None, 0, "bad-path")
    node = ws.path
    for part in Path(rel).parts[:-1]:
        node = node / part
        try:
            st = node.lstat()
        except FileNotFoundError:
            return Harvest(rel, None, None, 0, "absent")
        if stat.S_ISLNK(st.st_mode):
            return Harvest(rel, None, None, 0, "symlink")
        if not stat.S_ISDIR(st.st_mode):
            return Harvest(rel, None, None, 0, "not-regular")
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return Harvest(rel, None, None, 0, "absent")
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            return Harvest(rel, None, None, 0, "symlink")
        return Harvest(rel, None, None, 0, "not-regular")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return Harvest(rel, None, None, 0, "not-regular")
        if st.st_nlink > 1:
            # a hard link to a file outside the clone passes every path check
            return Harvest(rel, None, None, st.st_size, "hardlink")
        if st.st_size > max_bytes:
            return Harvest(rel, None, None, st.st_size, "too-large")
        if not Path(os.path.realpath(target)).is_relative_to(ws.path.resolve()):
            return Harvest(rel, None, None, st.st_size, "escapes-workspace")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                return Harvest(rel, None, None, total, "too-large")
            chunks.append(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    dest = Path(dest_dir).joinpath(*Path(rel).parts)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return Harvest(rel, dest, hashlib.sha256(data).hexdigest(), len(data), "ok")


def _make_writable(root: Path) -> None:
    """Give every real directory under `root` back u+rwx — an agent may leave
    one read-only or unreadable. A symlink is never chmod-ed (chmod follows
    links: the target could be any file of the user's outside the clone) and
    never walked; files need no mode, unlinking needs only the directory's."""
    def own(p: str) -> None:
        st = os.lstat(p)
        if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            os.chmod(p, 0o700)

    own(str(root))
    for dirpath, dirnames, _files in os.walk(root, topdown=True, followlinks=False):
        for d in dirnames:
            own(os.path.join(dirpath, d))   # before os.walk lists it


def destroy_root(root: Path) -> None:
    if root.is_symlink():
        raise JevError(f"refusing to destroy {root}: it is a symlink")
    if root.exists():
        try:
            shutil.rmtree(root)
        except OSError:
            _make_writable(root)
            shutil.rmtree(root)
    run_dir = root.parent
    try:
        run_dir.rmdir()   # the run's directory, once its last item is gone
    except OSError as exc:
        if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT):
            raise


def destroy(ws: Workspace) -> None:
    destroy_root(ws.root)

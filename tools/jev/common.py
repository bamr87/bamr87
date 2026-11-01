#!/usr/bin/env python3
"""
File: tools/jev/common.py
Description: The shared bottom layer of JEV — locating the hub, reading
             `_data/fleet.yml` `jev:` / `budget:`, the one `gh` wrapper every
             gh call JEV makes itself goes through (and the allowlist guard it
             applies), the `git` wrapper (no hooks, no fsmonitor, no
             force-push; an allowlist of subcommands and options), the small
             subprocess helper, and a `.env` reader that returns named keys
             only. Nothing here talks to a model or writes a file.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Dependencies: PyYAML, and the `gh` CLI for gh().
"""
from __future__ import annotations

import functools
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[2]
FLEET_YML = HUB / "_data" / "fleet.yml"
REGISTRY_YML = HUB / "_data" / "projects.yml"
#: `owner/repo` — the one definition spec.py, workspace.py and the engine share
NWO_RX = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def is_nwo(value: object) -> bool:
    """An `owner/repo` slug whose parts are names, never `.` or `..`."""
    return (isinstance(value, str) and NWO_RX.fullmatch(value) is not None
            and not {".", ".."} & set(value.split("/")))


def is_bare_name(value: object) -> bool:
    """A plain file name: no directory part, not absolute, not `.`/`..`, no NUL
    or backslash. What a plan row's `brief` must be — the engine resolves it
    beside the plan, and anything else would copy a host file into a clone."""
    return (isinstance(value, str) and bool(value) and value not in (".", "..")
            and Path(value).name == value and not any(c in value for c in "/\\\0"))


def is_clone_relpath(value: object) -> bool:
    """A relative POSIX path that stays inside a clone: not absolute, no
    backslash or NUL, and no `.`, `..` or `.git` part. What a step's
    `workspace.brief_dir` must be — the agent's TMPDIR is built from it."""
    if not isinstance(value, str) or not value or value.startswith("/") or any(c in value for c in "\\\0"):
        return False
    parts = [p for p in value.split("/") if p]
    return bool(parts) and not any(p in (".", "..", ".git") for p in parts)


class JevError(RuntimeError):
    """A condition JEV refuses to guess its way past (bad config, no gh, …)."""


# --------------------------------------------------------------------------- #
# process helpers
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    """The complete result of a subprocess — never raises on a non-zero exit.

    JEV runs commands that are EXPECTED to fail (a trial merge that conflicts,
    a validation command a repo does not have), so a failure is data, not an
    exception. Callers decide which code means what.
    """

    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run(argv: list[str], cwd: Path | None = None, env: dict | None = None,
        timeout: int = 900, stdin: str | None = None, *, inherit_env: bool = True) -> Run:
    """Run `argv`, capture everything, never raise on a non-zero exit.

    `env` is merged over `os.environ` by default. With `inherit_env=False` it
    is the child's WHOLE environment: a merge can add a variable but never
    remove one, and an environment built to keep credentials out has to be
    able to say "not this one".

    With no `stdin` the child reads /dev/null, never the caller's stdin: an
    inherited pipe nobody writes to blocks a child that reads it forever, and
    an inherited terminal hands the operator's keystrokes to a tool JEV runs.
    """
    merged = {**os.environ, **(env or {})} if inherit_env else dict(env or {})
    feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        proc = subprocess.run(  # noqa: S603 - argv is a list, never a shell string
            argv, cwd=str(cwd) if cwd else None, env=merged, **feed,
            capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        return Run(127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return Run(124, exc.stdout or "", f"timed out after {timeout}s")
    return Run(proc.returncode, proc.stdout or "", proc.stderr or "")


#: macOS's other names for this machine (`scutil --get`): the Bonjour name, which
#: is also reachable as `<name>.local`, and the "Computer Name" people see
MAC_NAME_KEYS = ("LocalHostName", "ComputerName")


@functools.lru_cache(maxsize=1)
def machine_names() -> tuple[str, ...]:
    """Every name this machine answers to that a log, a transcript or a title
    can carry: `platform.node()`, `socket.gethostname()`, and on macOS the
    LocalHostName (bare and with `.local`) and the ComputerName. Read once
    per process (`scutil` is a local configd read, never the network); a
    name that cannot be read is left out."""
    names = {platform.node(), socket.gethostname()}
    if sys.platform == "darwin" and shutil.which("scutil"):
        for key in MAC_NAME_KEYS:
            res = run(["scutil", "--get", key], timeout=5)
            value = res.out.strip() if res.code == 0 else ""
            if value and "\n" not in value:
                names |= {value, f"{value}.local"} if key == "LocalHostName" else {value}
    return tuple(sorted(n for n in names if n))


def git(args: list[str], cwd: Path, timeout: int = 900, env: dict | None = None, *,
        inherit_env: bool = True) -> Run:
    """git, with the repository's own hooks, fsmonitor and pagers out of the way.

    A checkout JEV did not write can name a hook directory or an fsmonitor
    program in its config; either would run on the next `git status`. Every
    call also passes `assert_safe_git`, so no history is ever rewritten remotely,
    and a push or fetch names git's own pack program, so one in config never runs.
    `inherit_env=False` makes `env` the whole environment (see `run`).
    """
    i = assert_safe_git(args, env)
    pin = _GIT_PACK_PINS.get(args[i])
    if pin:
        args = [*args[:i + 1], pin, *args[i + 1:]]
    return run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
                *args], cwd=cwd, timeout=timeout, env=env, inherit_env=inherit_env)


def git_bytes(args: list[str], cwd: Path, timeout: int = 900) -> bytes | None:
    """git's stdout as BYTES, or None on a non-zero exit — for a blob whose
    exact bytes matter. `run` decodes in text mode, which turns CRLF and a bare
    CR into LF, so a check that compares files through it cannot see a
    line-ending change. Same guard and the same `-c` settings as `git`; no
    push or fetch (nothing to pin)."""
    i = assert_safe_git(args)
    if args[i] in _GIT_PACK_PINS:
        raise JevError(f"refusing: git_bytes reads; `git {args[i]}` goes through git()")
    try:
        proc = subprocess.run(  # noqa: S603 - argv is a list, never a shell string
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", *args],
            cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def gh(args: list[str], cwd: Path | None = None, timeout: int = 180, env: dict | None = None) -> Run:
    """The ONE place JEV shells out to GitHub.

    Centralised so a dry run can be reasoned about in one place and so a
    missing CLI produces one legible error instead of a stack trace per call
    site. JEV never passes `--admin` to anything, and `assert_no_admin` below
    is the belt to that braces. `env` is merged over the caller's environment.
    """
    if shutil.which("gh") is None:
        raise JevError("the `gh` CLI is required for this command (brew install gh; gh auth login)")
    assert_no_admin(args)
    return run(["gh", *args], cwd=cwd, timeout=timeout, env=env)


def gh_json(args: list[str], cwd: Path | None = None, timeout: int = 180):
    """gh … --json …, decoded. An empty body reads as an empty list."""
    res = gh(args, cwd=cwd, timeout=timeout)
    if not res.ok:
        raise JevError(f"gh {' '.join(args)} failed: {res.err.strip() or res.out.strip()}")
    body = res.out.strip()
    return json.loads(body) if body else []


def assert_no_admin(args: list[str]) -> None:
    """JEV never merges and never uses an admin override — asserted, not assumed.

    `gh pr merge --admin` bypasses branch protection, and `gh api -X PATCH
    /repos/...` can change settings. Both are outside JEV's mandate (the
    constitution's agent row: an agent never merges its own work and never
    changes settings), so they are refused here rather than trusted not to be
    written. The guard fails closed: only the `gh <noun> <verb>` commands JEV
    issues pass (`_GH_ALLOWED`), named by the argv's first two words — gh
    finds the verb past a flag (`gh pr -R o/r merge`) and takes aliases
    (`gh secret remove`), so a flag there, or any other command, is refused.
    What `gh repo clone` hands git after `--` is held to the options of a
    `git clone` (`assert_safe_clone`).
    """
    if "--admin" in args or any(a.startswith("--admin=") for a in args):
        raise JevError("refusing: JEV never uses --admin")
    noun = args[0] if args else ""
    verb = (args[1] if len(args) > 1 else "") if noun != "api" else None
    if not noun or noun.startswith("-") or (verb is not None and (not verb or verb.startswith("-"))):
        raise JevError(f"refusing: `gh {' '.join(args[:3])}` — JEV's gh argv starts with its command "
                       "(`gh <noun> <verb>`, no flag before the verb)")
    if (noun, verb) == ("pr", "merge"):
        raise JevError("refusing: JEV never merges a pull request")
    if (noun, verb) not in _GH_ALLOWED:
        why = _GH_REFUSED_WHY.get(noun, "not one of the gh commands JEV issues")
        raise JevError(f"refusing: JEV never runs `gh {noun} {verb}` ({why})")
    if verb == "comment" and any(a.split("=", 1)[0] in ("--delete-last", "--edit-last") for a in args):
        raise JevError("refusing: JEV only adds comments (never --edit-last or --delete-last)")
    if (noun, verb) == ("repo", "clone") and "--" in args:
        # gh hands everything after `--` to `git clone`, past assert_safe_git
        assert_safe_clone(args[args.index("--") + 1:], "gh repo clone … --")
    if noun == "api":
        _assert_api_read(args)


#: The `gh` commands JEV issues — an allowlist, so a destructive verb, an alias
#: of one (`secret remove`, `variable remove`) or a command nobody listed fails
#: closed. Adding one is a reviewed change here plus a case in
#: tools/test_jev_conflicts.py. `api` is checked on its own (`_assert_api_read`).
_GH_ALLOWED = frozenset({
    ("api", None), ("issue", "create"), ("issue", "list"), ("issue", "view"),
    ("label", "create"), ("pr", "comment"), ("pr", "edit"), ("pr", "list"), ("pr", "view"),
    ("repo", "clone"), ("repo", "list"), ("repo", "view"), ("variable", "get"),
})
#: why a command outside _GH_ALLOWED is refused, by noun (for the message)
_GH_REFUSED_WHY = {
    "issue": "an agent loop files and comments; it never closes, deletes, moves or locks an issue",
    "pr": "JEV comments on and labels a pull request; it never merges, closes or reopens one",
    "repo": "repository settings and lifecycle belong to a person",
    "secret": "secrets and variables are written hub-first by the token loops, never by JEV",
    "variable": "secrets and variables are written hub-first by the token loops, never by JEV",
}


#: `gh api` flags that take a value (the value is never the endpoint)
_API_VALUE_FLAGS = frozenset({"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "--input",
                              "-q", "--jq", "-t", "--template", "--cache", "--hostname", "-p", "--preview"})
#: `gh api`'s boolean shorthands (`-i`/--include), which pflag lets lead a bundle such as `-iXPUT`
_API_BOOL_SHORT = frozenset({"i"})
#: `gh api` flags that add a request parameter — and with it gh's implicit POST
_API_PARAM_FLAGS = ("-f", "--raw-field", "-F", "--field", "--input")


def _api_fields(args: list[str]) -> tuple[str | None, list[tuple[str, str]]]:
    """(endpoint, [(flag, value)]) of a `gh api …` argv, every spelling of a
    flag's value included (`-f k=v`, `-fk=v`, `--field=k=v`), and a shorthand
    bundle read the way gh's flag parser (pflag) reads it: `-iXPUT` is `-i`
    then `-X PUT`, `-if k=v` is `-i` then `-f k=v`. A shorthand this guard does
    not know is refused (JevError) rather than guessed."""
    endpoint, fields, i = None, [], 1
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            name, eq, attached = a.partition("=")
            if name in _API_VALUE_FLAGS:
                fields.append((name, attached if eq else (args[i + 1] if i + 1 < len(args) else "")))
                i += 1 if eq else 2
            else:
                i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            j, took_next = 1, False
            while j < len(a):
                c = a[j]
                if f"-{c}" in _API_VALUE_FLAGS:
                    rest = a[j + 1:]
                    took_next = not rest
                    fields.append((f"-{c}", rest or (args[i + 1] if i + 1 < len(args) else "")))
                    break
                if c not in _API_BOOL_SHORT:
                    raise JevError(f"refusing: `gh api {a}` — a shorthand flag this guard cannot read (-{c})")
                j += 1
            i += 2 if took_next else 1
            continue
        if endpoint is None:
            endpoint = a
        i += 1
    return endpoint, fields


def _api_method(args: list[str]) -> str:
    """The HTTP method a `gh api …` call would send: what -X/--method says, else
    gh's own default — GET, and POST as soon as any parameter is added."""
    _endpoint, fields = _api_fields(args)
    explicit = [v for f, v in fields if f in ("-X", "--method")]
    if explicit:
        return explicit[-1].upper()
    return "POST" if any(f in _API_PARAM_FLAGS for f, _v in fields) else "GET"


#: a GraphQL document that writes (after leading whitespace and # comments)
_GRAPHQL_WRITE_RX = re.compile(r"\A(?:\s|#[^\n]*\n?)*(mutation|subscription)\b", re.I)


def _assert_api_read(args: list[str]) -> None:
    """`gh api` fails closed: a GET, or an inline GraphQL query — nothing else.

    No JEV caller writes through `gh api` (every write is a reviewed `gh <noun>
    <verb>`), and a REST POST can do what a refused verb does (`/merges`,
    `/transfer`, `/git/refs`), so every method but GET is refused. GraphQL
    always POSTs; it is let through only as an inline `query=` that is not a
    mutation or subscription — never `--input` or an `@file` body, whose text
    this guard cannot see.
    """
    endpoint, fields = _api_fields(args)
    if endpoint == "graphql":
        if any(f == "--input" for f, _v in fields) or any(f in ("-F", "--field") and v.partition("=")[2][:1] == "@"
                                                          for f, v in fields):
            raise JevError("refusing: JEV never sends a GraphQL body it cannot read (--input or an @file field)")
        queries = [v.partition("=")[2] for f, v in fields if f in _API_PARAM_FLAGS and v.startswith("query=")]
        if (not queries or any(_GRAPHQL_WRITE_RX.match(q) for q in queries)
                or any("mutation" in a.lower() for a in args)):
            raise JevError("refusing: JEV never sends a GraphQL mutation (it bypasses every verb above)")
        explicit = [v.upper() for f, v in fields if f in ("-X", "--method")]
        if explicit and explicit[-1] != "POST":
            raise JevError(f"refusing: JEV sends GraphQL queries as gh does (POST), not -X {explicit[-1]}")
        return
    method = _api_method(args)
    if method != "GET":
        raise JevError(f"refusing: JEV never sends `gh api` {method} (only GETs; every write is a reviewed "
                       "`gh <noun> <verb>`)")


#: The git subcommands JEV runs — an allowlist, so an alias (`-c alias.p='push
#: -f'` then `p`), an autocorrected typo (`psuh`) or plumbing that pushes
#: (`send-pack`, `http-push`) fails closed. git itself refuses an alias that
#: shadows one of these.
_GIT_ALLOWED = frozenset({"add", "blame", "check-attr", "check-ignore", "checkout", "clone", "commit", "config", "diff",
                          "fetch", "grep", "init", "log", "ls-files", "ls-tree", "merge", "merge-file", "push",
                          "remote", "rev-parse", "show", "status", "update-index"})
#: git global options JEV passes, and whether each takes a value (`--opt=v` or
#: `--opt v`; `-c k=v` or `-ck=v`). Every other one (`--config-env`,
#: `--exec-path`, …) is refused.
_GIT_GLOBAL_OPTS = {"-c": True, "-C": True, "--git-dir": True, "--work-tree": True, "--no-pager": False}
#: the only keys JEV sets with `-c` — not alias.*, help.autocorrect or any
#: remote.*/push.* key, through which a plain push forces, mirrors or deletes,
#: and not core.hooksPath, core.fsmonitor or core.pager: `git` sets those
#: itself, and a later `-c` would win over it
_GIT_CONFIG_KEYS = frozenset({"core.attributesfile", "core.symlinks", "diff.ignoresubmodules", "submodule.recurse",
                              "user.email", "user.name", "commit.gpgsign"})
#: the keys a `git config` write may set, each with the one value it may take
#: (None: any). Every other key — include.*, url.*, remote.*.push or .mirror,
#: alias.*, core.sshCommand — redirects a later push or runs a command.
_GIT_CONFIG_WRITES = {"user.name": None, "user.email": None, "commit.gpgsign": None, "core.symlinks": None,
                      "remote.origin.url": None, "remote.origin.pushurl": None, "credential.helper": "",
                      "core.fsmonitor": "false", "core.hookspath": "/dev/null"}
#: `git config` options JEV passes (True = takes a value); a read option makes the call a read
_GIT_CONFIG_OPTS = {"--local": False, "--get": False, "--get-all": False, "--get-regexp": False, "--list": False,
                    "-l": False}
_GIT_CONFIG_READS = frozenset({"--get", "--get-all", "--get-regexp", "--list", "-l"})
#: `git clone` options JEV passes (workspace.CLONE_OPTS, `jev conflicts`' gh
#: passthrough), and the only `clone -c` settings, each pinned: they harden
#: the new clone's own config. `--mirror`, `--upload-pack`, `--template` and
#: any other `-c` are refused.
_GIT_CLONE_OPTS = {"--branch": True, "-b": True, "-c": True, "--config": True, "--no-recurse-submodules": False,
                   "--no-tags": False, "--quiet": False, "-q": False}
_GIT_CLONE_CONFIG = frozenset({"core.symlinks=false", "core.hookspath=/dev/null", "core.fsmonitor=false"})
#: `git fetch` and `git push` options JEV passes (no `--upload-pack`, `--repo`, `--all`, …)
_GIT_FETCH_OPTS = {"--quiet": False, "-q": False, "--no-tags": False}
_GIT_PUSH_OPTS = {"--quiet": False, "-q": False, "--set-upstream": False, "-u": False, "--dry-run": False,
                  "-n": False, "--porcelain": False, "--no-verify": False, "--atomic": False, "--verbose": False,
                  "-v": False}
#: a push refspec JEV sends: an explicit `<src>:<dst>`, never `+` (force) or an empty source (delete)
_PUSH_REFSPEC_RX = re.compile(r"[^+:\s][^:\s]*:[^:\s]+")
#: push options that rewrite or remove a remote ref, or run a program
#: (`--receive-pack`/`--exec`); git accepts any unambiguous prefix of a long
#: option, so a prefix counts
_PUSH_DANGEROUS = ("force", "force-with-lease", "force-if-includes", "mirror", "delete", "prune", "receive-pack",
                   "exec")
#: `git init` options JEV passes (no `--template`, whose `config` file is
#: copied into the new repository, and no `--separate-git-dir`)
_GIT_INIT_OPTS = {"--quiet": False, "-q": False, "--initial-branch": True, "-b": True, "--bare": False}
#: the GIT_* environment variables JEV hands git: an ALLOWLIST, because the
#: names that inject config, a repository, a template or a program are many
#: (GIT_CONFIG_*, GIT_DIR, GIT_COMMON_DIR, GIT_TEMPLATE_DIR, GIT_SSH_COMMAND,
#: GIT_EXEC_PATH, …). A global or system config file only as /dev/null, which
#: is what engine_git sets.
_GIT_ENV_ALLOWED = frozenset({"GIT_LFS_SKIP_SMUDGE", "GIT_TERMINAL_PROMPT", "GIT_CONFIG_NOSYSTEM", "GIT_OPTIONAL_LOCKS",
                              "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME",
                              "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"})
_GIT_ENV_DEVNULL = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"})
#: where git finds its global config when GIT_CONFIG_GLOBAL does not say
_GIT_ENV_HOMES = ("HOME", "XDG_CONFIG_HOME")
#: the pack programs every push and fetch names itself, so a `receivepack` or
#: `uploadpack` planted in config past the guard never runs (the command line wins)
_GIT_PACK_PINS = {"push": "--receive-pack=git-receive-pack", "fetch": "--upload-pack=git-upload-pack"}


def _git_env_problems(env: dict | None) -> list[str]:
    env = env or {}
    bad = [k for k, v in env.items() if k.startswith("GIT_") and k not in _GIT_ENV_ALLOWED
           and not (k in _GIT_ENV_DEVNULL and v == "/dev/null")]
    if env.get("GIT_CONFIG_GLOBAL") != "/dev/null":
        bad += [k for k in _GIT_ENV_HOMES if k in env and env[k] != os.environ.get(k)]
    return sorted(bad)


def _git_options(what: str, args: list[str], allowed: dict[str, bool]) -> tuple[list[tuple[str, str]], list[str]]:
    """([(option, value)], positionals) of a git argv, every option one in
    `allowed` (True = takes a value: `--opt=v`, `--opt v`, `-ov`, `-o v`).
    Anything else — a prefix git would expand, a bundle of short flags, a
    value on a flag that takes none — is refused (JevError)."""
    opts, positionals, i, ended = [], [], 0, False
    while i < len(args):
        a = args[i]
        if ended or a == "-" or not a.startswith("-"):
            positionals.append(a)
            i += 1
            continue
        if a == "--":
            ended, i = True, i + 1
            continue
        name, eq, value = a.partition("=") if a.startswith("--") else (a[:2], "", a[2:])
        takes = allowed.get(name)
        if takes is None or (not takes and (eq or value)):
            raise JevError(f"refusing: JEV never passes `{a.split('=', 1)[0]}` to {what}")
        if not takes:
            opts.append((name, ""))
            i += 1
            continue
        attached = eq or value
        if not attached and i + 1 >= len(args):
            raise JevError(f"refusing: {what} {name} needs a value")
        opts.append((name, value if attached else args[i + 1]))
        i += 1 if attached else 2
    return opts, positionals


def assert_safe_clone(args: list[str], what: str = "git clone") -> None:
    """A `git clone` tail (or `gh repo clone`'s passthrough after `--`) passes
    only the options JEV uses, and `-c` only the pinned hardening settings — a
    clone's own `-c remote.origin.push=:ref` or `--mirror` would turn a later
    plain push into a delete."""
    opts, _positionals = _git_options(what, args, _GIT_CLONE_OPTS)
    for name, value in opts:
        key, _eq, val = value.partition("=")
        if name in ("-c", "--config") and f"{key.lower()}={val}" not in _GIT_CLONE_CONFIG:
            raise JevError(f"refusing: JEV never clones with `{name} {value}` (only "
                           f"{', '.join(sorted(_GIT_CLONE_CONFIG))})")


def assert_safe_git(args: list[str], env: dict | None = None) -> int:
    """No force-push, mirror or remote delete, whatever the caller meant; the
    index of the subcommand in `args` when the call is allowed.

    A push that rewrites or removes a remote ref discards somebody's commits
    and detaches review comments from them; JEV only ever adds a merge commit.
    The guard fails closed: the subcommand must be one JEV runs
    (`_GIT_ALLOWED`), a global option one JEV passes (`_GIT_GLOBAL_OPTS`; no
    `--config-env`), a `-c` key one JEV sets (`_GIT_CONFIG_KEYS`), and `env`
    may set only the GIT_* names in `_GIT_ENV_ALLOWED` (a global or system
    config file only as /dev/null) and may move HOME or XDG_CONFIG_HOME, where
    git finds its global config, only when that config is /dev/null. The
    subcommands that could plant config a later push follows are held to the
    options JEV uses: `clone` (its `-c` pinned, no `--mirror` or
    `--template`), `init` (`-q`, `-b`, `--bare`), `fetch`, `remote` (list and
    remove only) and `config` (a write only of the keys in
    `_GIT_CONFIG_WRITES`). A push is refused for a force, mirror, delete or
    prune flag in any spelling (bundled short flags, long-option prefixes), any
    option JEV does not pass, and any refspec but an explicit `<src>:<dst>` —
    so a push refspec or mirror flag in config, wherever it came from, never
    applies (git ignores the first and refuses the second beside a refspec) —
    and `git()` pins every push's and fetch's pack program (`_GIT_PACK_PINS`),
    so a `receivepack` or `uploadpack` in config never runs either.
    """
    bad_env = _git_env_problems(env)
    if bad_env:
        raise JevError(f"refusing: JEV never hands git config, a repository or a program through the environment "
                       f"({', '.join(bad_env)})")
    i, config = 0, []
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        name, eq, value = a.partition("=") if a.startswith("--") else (a[:2], "", a[2:])
        if name not in _GIT_GLOBAL_OPTS:
            raise JevError(f"refusing: JEV never passes the git option {a.split('=', 1)[0]}")
        if not _GIT_GLOBAL_OPTS[name]:
            i += 1
            continue
        attached = value if (eq or not a.startswith("--")) else ""
        if not attached and i + 1 >= len(args):
            raise JevError(f"refusing: git {name} needs a value")
        if name == "-c":
            config.append(attached or args[i + 1])
        i += 1 if attached else 2
    for c in config:
        if c.partition("=")[0].lower() not in _GIT_CONFIG_KEYS:
            raise JevError(f"refusing: JEV never sets `-c {c.partition('=')[0]}` on git (only "
                           f"{', '.join(sorted(_GIT_CONFIG_KEYS))})")
    sub = args[i] if i < len(args) else ""
    if sub not in _GIT_ALLOWED:
        raise JevError(f"refusing: JEV never runs `git {sub}` (not one of the git commands it issues)")
    tail = args[i + 1:]
    if sub == "clone":
        assert_safe_clone(tail)
    elif sub == "fetch":
        _git_options("git fetch", tail, _GIT_FETCH_OPTS)
    elif sub == "init":
        _opts, positionals = _git_options("git init", tail, _GIT_INIT_OPTS)
        if len(positionals) > 1:
            raise JevError(f"refusing: git init takes one directory, not {' '.join(positionals)}")
    elif sub == "remote":
        if tail not in ([], ["-v"]) and not (len(tail) == 2 and tail[0] in ("remove", "rm", "get-url")):
            raise JevError(f"refusing: JEV only lists and removes remotes, never `git remote {' '.join(tail[:2])}`")
    elif sub == "config":
        opts, positionals = _git_options("git config", tail, _GIT_CONFIG_OPTS)
        if not any(name in _GIT_CONFIG_READS for name, _v in opts) and len(positionals) > 1:
            key, value = positionals[0].lower(), positionals[1]
            pinned = _GIT_CONFIG_WRITES.get(key, ())
            if len(positionals) != 2 or pinned == () or (pinned is not None and value != pinned):
                raise JevError(f"refusing: JEV never sets git config {positionals[0]}={value} (it would redirect a "
                               "push or run a command)")
    elif sub == "push":
        _assert_safe_push(tail)
    return i


def _assert_safe_push(tail: list[str]) -> None:
    def dangerous(a: str) -> bool:
        if a.startswith("--"):
            name = a[2:].split("=", 1)[0]
            return len(name) >= 2 and any(d.startswith(name) for d in _PUSH_DANGEROUS)
        if a.startswith("-") and len(a) > 1 and a[1:].isalpha():
            return bool(set(a[1:]) & {"f", "d"})
        return (a.startswith("+") and len(a) > 1) or (a.startswith(":") and len(a) > 1)

    bad = [a for a in tail if dangerous(a)]
    if bad:
        raise JevError(f"refusing: JEV never force-pushes or deletes a remote ref ({' '.join(bad)})")
    _opts, positionals = _git_options("git push", tail, _GIT_PUSH_OPTS)
    refspecs = positionals[1:]
    if not refspecs or not all(_PUSH_REFSPEC_RX.fullmatch(r) for r in refspecs):
        raise JevError(f"refusing: JEV pushes only an explicit <src>:<dst> refspec (`git push {' '.join(tail)}`), "
                       "so no push refspec or mirror flag in config ever applies")


def dotenv_values(names: list[str] | tuple[str, ...], path: Path | None = None) -> dict[str, str]:
    """The named keys of a `.env` file, PARSED, never sourced.

    Sourcing would run whatever the file holds, and reading every key would put
    secrets this caller has no use for into its memory. So: `KEY=value` lines
    only (an optional `export ` prefix; a quoted value ends at its closing
    quote, so a trailing ` # comment` is dropped; an unquoted value ends at
    ` #`), only the keys asked for, the last assignment winning as it would in
    a shell — an empty `KEY=` included, which leaves the key absent. A missing
    or unreadable file is an empty answer, not an error.
    """
    p = path or (HUB / ".env")
    wanted = set(names)
    out: dict[str, str] = {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in wanted:
            continue
        value = value.strip()
        if value[:1] in ("\"", "'"):
            end = value.find(value[0], 1)
            if end > 0:
                value = value[1:end]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return {k: v for k, v in out.items() if v}


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
@dataclass
class TierPolicy:
    """One triage tier's envelope. Everything here comes from fleet.yml."""

    name: str
    model: str = ""
    max_files: int = 0
    max_lines: int = 0
    max_usd: float = 0.0
    max_turns: int = 0


@dataclass
class JevConfig:
    """`_data/fleet.yml` `jev:` plus the slice of `budget:` JEV is held to."""

    enabled: bool = False
    orgs: list[str] = field(default_factory=list)
    allowed_authors: list[str] = field(default_factory=list)
    scan_limit: int = 50
    max_attempts: int = 2
    monthly_usd: float = 10.0
    scheduled_stop_pct: int = 80
    needs_human_label: str = "jev:needs-human"
    enforce_numbering: bool = False
    tiers: dict[str, TierPolicy] = field(default_factory=dict)
    generated_paths: list[str] = field(default_factory=list)
    fragment_paths: list[str] = field(default_factory=list)
    union_paths: list[str] = field(default_factory=list)
    #: The tiers the engine may run on its own. tier0 is free and
    #: deterministic; tier1/tier2 spend money and stay off until listed here.
    auto_tiers: list[str] = field(default_factory=lambda: ["tier0", "tier1", "tier2"])

    def tier(self, name: str) -> TierPolicy:
        return self.tiers.get(name, TierPolicy(name))

    @property
    def monthly_stop_usd(self) -> float:
        """Where a SCHEDULED run stops — below the hard cap, deliberately.

        A cron that spends up to the last cent leaves nothing for the manual
        run a human makes when something is actually on fire, so the schedule
        yields at 80% and says so.
        """
        return self.monthly_usd * self.scheduled_stop_pct / 100.0


def load_fleet(path: Path | None = None) -> dict:
    p = path or FLEET_YML
    if not p.is_file():
        raise JevError(f"no fleet configuration at {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def finite_usd(value, what: str) -> float:
    """A dollar cap or ceiling that bounds something: a finite number above 0.
    YAML reads `.inf` and `.nan`; an infinite ceiling affords every attempt,
    and one NaN makes every comparison with it false, which reads as "fits"."""
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value <= 0):
        raise JevError(f"{what} must be a finite number above 0, not {value!r}")
    return float(value)


def load_config(fleet: dict | None = None) -> JevConfig:
    """Read `jev:` and `budget.jev:` into one object with the defaults applied.
    Money that is set but bounds nothing is refused, never defaulted:
    `monthly_usd` and every tier cap must be a finite number above 0,
    `scheduled_stop_pct` an integer in 1..100, and a tier that names a model
    must have a cap."""
    data = fleet if fleet is not None else load_fleet()
    jev = (data.get("jev") or {})
    budget = ((data.get("budget") or {}).get("jev") or {})
    tiers: dict[str, TierPolicy] = {}
    for name, spec in (jev.get("tiers") or {}).items():
        spec = spec or {}
        model = str(spec.get("model") or "")
        cap = budget.get(f"{name}_usd", spec.get("max_usd"))
        if cap is None and not model:
            max_usd = 0.0      # a tier that buys no model spends nothing
        else:
            max_usd = finite_usd(cap, f"_data/fleet.yml budget.jev.{name}_usd (the {name} attempt cap)")
        tiers[str(name)] = TierPolicy(
            name=str(name),
            model=model,
            max_files=int(spec.get("max_files") or 0),
            max_lines=int(spec.get("max_lines") or 0),
            max_usd=max_usd,
            max_turns=int(spec.get("max_turns") or 0),
        )
    pct = budget.get("scheduled_stop_pct", 80)
    if isinstance(pct, bool) or not isinstance(pct, int) or not 0 < pct <= 100:
        raise JevError(f"_data/fleet.yml budget.jev.scheduled_stop_pct must be an integer in 1..100, not {pct!r} "
                       "— a scheduled run stops there, below the monthly cap")
    return JevConfig(
        enabled=bool(jev.get("enabled", False)),
        orgs=[str(o) for o in (jev.get("orgs") or [])],
        allowed_authors=[str(a) for a in (jev.get("allowed_authors") or [])],
        scan_limit=int(jev.get("scan_limit") or 50),
        max_attempts=int(jev.get("max_attempts") or 2),
        monthly_usd=finite_usd(budget.get("monthly_usd", 10),
                               "_data/fleet.yml budget.jev.monthly_usd (the engine's monthly ceiling)"),
        scheduled_stop_pct=pct,
        needs_human_label=str(jev.get("needs_human_label") or "jev:needs-human"),
        enforce_numbering=bool((jev.get("numbering") or {}).get("enforce", False)),
        tiers=tiers,
        generated_paths=[str(p) for p in (jev.get("generated_paths") or [])],
        fragment_paths=[str(p) for p in (jev.get("fragment_paths") or [])],
        union_paths=[str(p) for p in (jev.get("union_paths") or [])],
        auto_tiers=[str(t) for t in (jev.get("auto_tiers") or ["tier0", "tier1", "tier2"])],
    )


def registry_repos(path: Path | None = None) -> list[str]:
    """`owner/repo` for every registry project that has a GitHub URL."""
    p = path or REGISTRY_YML
    if not p.is_file():
        return []
    out: list[str] = []
    for entry in yaml.safe_load(p.read_text(encoding="utf-8")) or []:
        url = str((entry or {}).get("repo_url") or "")
        slug = url.rstrip("/").removesuffix(".git").split("github.com/")[-1]
        if slug.count("/") == 1:
            out.append(slug)
    return sorted(dict.fromkeys(out))


def hub_repo(fleet: dict | None = None) -> str:
    data = fleet if fleet is not None else load_fleet()
    return str((data.get("hub") or {}).get("repo") or "bamr87/bamr87")

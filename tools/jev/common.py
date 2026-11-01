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

import json
import os
import re
import shutil
import subprocess
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


def git(args: list[str], cwd: Path, timeout: int = 900, env: dict | None = None, *,
        inherit_env: bool = True) -> Run:
    """git, with the repository's own hooks, fsmonitor and pagers out of the way.

    A checkout JEV did not write can name a hook directory or an fsmonitor
    program in its config; either would run on the next `git status`. Every
    call also passes `assert_safe_git`, so no history is ever rewritten remotely.
    `inherit_env=False` makes `env` the whole environment (see `run`).
    """
    assert_safe_git(args, env)
    return run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
                *args], cwd=cwd, timeout=timeout, env=env, inherit_env=inherit_env)


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
    if noun == "api":
        _assert_api_read(args)


#: The `gh` commands JEV issues — an allowlist, so a destructive verb, an alias
#: of one (`secret remove`, `variable remove`) or a command nobody listed fails
#: closed. Adding one is a reviewed change here plus a case in
#: tools/test_jev_conflicts.py. `api` is checked on its own (`_assert_api_read`).
_GH_ALLOWED = frozenset({
    ("api", None), ("auth", "status"), ("issue", "create"), ("issue", "list"), ("issue", "view"),
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
_GIT_ALLOWED = frozenset({"add", "check-attr", "check-ignore", "checkout", "clone", "commit", "config", "diff",
                          "fetch", "grep", "init", "log", "ls-files", "ls-tree", "merge", "merge-file", "push",
                          "remote", "rev-parse", "show", "status", "update-index"})
#: git global options JEV passes, and whether each takes a value (`--opt=v` or
#: `--opt v`; `-c k=v` or `-ck=v`). Every other one (`--config-env`,
#: `--exec-path`, …) is refused.
_GIT_GLOBAL_OPTS = {"-c": True, "-C": True, "--git-dir": True, "--work-tree": True, "--no-pager": False}
#: the only keys JEV sets with `-c` — not alias.*, help.autocorrect or any
#: remote.*/push.* key, through which a plain push forces, mirrors or deletes
_GIT_CONFIG_KEYS = frozenset({"core.attributesfile", "core.fsmonitor", "core.hookspath", "core.pager",
                              "core.symlinks", "diff.ignoresubmodules", "submodule.recurse", "user.email",
                              "user.name", "commit.gpgsign"})
#: config a `git config` write may never set (they redirect a later push or run a command)
_GIT_CONFIG_WRITE_RX = re.compile(r"(?i)^(alias\..|help\.autocorrect$|remote\..+\.(push|mirror|receivepack)$|push\.)")
#: push options that rewrite or remove a remote ref, or run a program
#: (`--receive-pack`/`--exec`); git accepts any unambiguous prefix of a long
#: option, so a prefix counts
_PUSH_DANGEROUS = ("force", "force-with-lease", "force-if-includes", "mirror", "delete", "prune", "receive-pack",
                   "exec")
#: environment variables that inject git config or a git binary directory
_GIT_ENV_REFUSED_RX = re.compile(r"^(GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_\d+|GIT_CONFIG_VALUE_\d+"
                                 r"|GIT_EXEC_PATH)$")


def assert_safe_git(args: list[str], env: dict | None = None) -> None:
    """No force-push, mirror or remote delete, whatever the caller meant.

    A push that rewrites or removes a remote ref discards somebody's commits
    and detaches review comments from them; JEV only ever adds a merge commit.
    The guard fails closed: the subcommand must be one JEV runs
    (`_GIT_ALLOWED`), a global option one JEV passes (`_GIT_GLOBAL_OPTS`; no
    `--config-env`), a `-c` key one JEV sets (`_GIT_CONFIG_KEYS`), and `env`
    may inject no config. A push is then refused for bundled short flags
    (`-fu`), a long-option prefix (`--forc`) and a `+` or `:` refspec, and a
    `git config` write for a key that would redirect a later push.
    """
    bad_env = sorted(k for k in (env or {}) if _GIT_ENV_REFUSED_RX.match(k))
    if bad_env:
        raise JevError(f"refusing: JEV never hands git config through the environment ({', '.join(bad_env)})")
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
    if sub == "config":
        keys = [a for a in tail if _GIT_CONFIG_WRITE_RX.match(a)]
        if keys:
            raise JevError(f"refusing: JEV never sets git config that redirects a push or runs a command ({keys[0]})")
        return
    if sub != "push":
        return

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


def load_config(fleet: dict | None = None) -> JevConfig:
    """Read `jev:` and `budget.jev:` into one object with the defaults applied."""
    data = fleet if fleet is not None else load_fleet()
    jev = (data.get("jev") or {})
    budget = ((data.get("budget") or {}).get("jev") or {})
    tiers: dict[str, TierPolicy] = {}
    for name, spec in (jev.get("tiers") or {}).items():
        spec = spec or {}
        tiers[str(name)] = TierPolicy(
            name=str(name),
            model=str(spec.get("model") or ""),
            max_files=int(spec.get("max_files") or 0),
            max_lines=int(spec.get("max_lines") or 0),
            max_usd=float(budget.get(f"{name}_usd", spec.get("max_usd") or 0.0)),
            max_turns=int(spec.get("max_turns") or 0),
        )
    return JevConfig(
        enabled=bool(jev.get("enabled", False)),
        orgs=[str(o) for o in (jev.get("orgs") or [])],
        allowed_authors=[str(a) for a in (jev.get("allowed_authors") or [])],
        scan_limit=int(jev.get("scan_limit") or 50),
        max_attempts=int(jev.get("max_attempts") or 2),
        monthly_usd=float(budget.get("monthly_usd", 10)),
        scheduled_stop_pct=int(budget.get("scheduled_stop_pct", 80)),
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

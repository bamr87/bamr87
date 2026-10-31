#!/usr/bin/env python3
"""
File: tools/jev/common.py
Description: The shared bottom layer of JEV — locating the hub, reading
             `_data/fleet.yml` `jev:` / `budget:`, the one `gh` wrapper every
             GitHub call goes through (and the guard it applies), the `git`
             wrapper (no hooks, no fsmonitor, no force-push), the small
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
    """
    merged = {**os.environ, **(env or {})} if inherit_env else dict(env or {})
    try:
        proc = subprocess.run(  # noqa: S603 - argv is a list, never a shell string
            argv, cwd=str(cwd) if cwd else None, env=merged, input=stdin,
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
    assert_safe_git(args)
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
    changes settings), so they are refused at the one choke point rather than
    trusted not to be written.
    """
    if "--admin" in args:
        raise JevError("refusing: JEV never uses --admin")
    verb = tuple(args[:2])
    if verb == ("pr", "merge"):
        raise JevError("refusing: JEV never merges a pull request")
    if verb in _REFUSED_VERBS:
        raise JevError(f"refusing: JEV never runs `gh {' '.join(verb)}` ({_REFUSED_VERBS[verb]})")
    if verb == ("repo", "sync") and any(a in ("--force", "-f") for a in args):
        raise JevError("refusing: JEV never force-syncs a repository (it rewrites the branch)")
    if args[:1] == ["api"]:
        _assert_api_read(args)


#: `gh <noun> <verb>` pairs no JEV caller may run, with why. Allowed and in use:
#: `label create --force`, `pr edit --add-label`, `pr comment`, `issue create`,
#: `repo clone`, `variable get` and `api` GETs.
_REFUSED_VERBS = {
    **{("issue", v): "an agent loop files and comments; it never closes, deletes, moves or locks an issue"
       for v in ("close", "delete", "transfer", "lock")},
    **{("repo", v): "repository settings and lifecycle belong to a person"
       for v in ("delete", "archive", "edit", "rename", "transfer")},
    **{(n, v): "secrets and variables are written hub-first by the token loops, never by JEV"
       for n in ("secret", "variable") for v in ("set", "delete")},
}


#: `gh api` flags that take a value (the value is never the endpoint)
_API_VALUE_FLAGS = frozenset({"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "--input",
                              "-q", "--jq", "-t", "--template", "--cache", "--hostname", "-p", "--preview"})
#: `gh api` flags that add a request parameter — and with it gh's implicit POST
_API_PARAM_FLAGS = ("-f", "--raw-field", "-F", "--field", "--input")


def _api_fields(args: list[str]) -> tuple[str | None, list[tuple[str, str]]]:
    """(endpoint, [(flag, value)]) of a `gh api …` argv, every spelling of a
    flag's value included (`-f k=v`, `-fk=v`, `--field=k=v`)."""
    endpoint, fields, i = None, [], 1
    while i < len(args):
        a = args[i]
        name, eq, attached = a.partition("=") if a.startswith("--") else (a[:2], "", a[2:])
        if a.startswith("--") and name in _API_VALUE_FLAGS:
            value = attached if eq else (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if eq else 2
        elif a.startswith("-") and not a.startswith("--") and name in _API_VALUE_FLAGS:
            value = attached or (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if attached else 2
        else:
            if endpoint is None and not a.startswith("-"):
                endpoint = a
            i += 1
            continue
        fields.append((name, value))
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


#: git global options whose value may follow as the next argument
_GIT_VALUE_OPTS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                             "--config-env", "--list-cmds", "--attr-source"})
#: push options that rewrite or remove a remote ref (git accepts any
#: unambiguous prefix of a long option, so a prefix counts)
_PUSH_DANGEROUS = ("force", "force-with-lease", "force-if-includes", "mirror", "delete", "prune")
#: a `-c` value that makes a plain push rewrite or mirror
_PUSH_CONFIG_RX = re.compile(r"(?i)^remote\..+\.(push\s*=\s*\+|mirror\s*=)|^push\..*=\s*\+")


def assert_safe_git(args: list[str]) -> None:
    """No force-push, mirror or remote delete, whatever the caller meant.

    A push that rewrites or removes a remote ref discards somebody's commits
    and detaches review comments from them; JEV only ever adds a merge commit.
    Every spelling counts: bundled short flags (`-fu`), a long-option prefix
    (`--forc`), a global option with a separate value (`--git-dir DIR push`)
    and a forced refspec or mirror set through `-c`.
    """
    i, config = 0, []
    while i < len(args) and args[i].startswith("-"):
        if args[i] in _GIT_VALUE_OPTS:
            if args[i] == "-c" and i + 1 < len(args):
                config.append(args[i + 1])
            i += 2
        else:
            if args[i].startswith("-c") and len(args[i]) > 2:
                config.append(args[i][2:])
            i += 1
    if args[i:i + 1] != ["push"]:
        return
    tail = args[i + 1:]

    def dangerous(a: str) -> bool:
        if a.startswith("--"):
            name = a[2:].split("=", 1)[0]
            return len(name) >= 2 and any(d.startswith(name) for d in _PUSH_DANGEROUS)
        if a.startswith("-") and len(a) > 1 and a[1:].isalpha():
            return bool(set(a[1:]) & {"f", "d"})
        return (a.startswith("+") and len(a) > 1) or (a.startswith(":") and len(a) > 1)

    bad = [a for a in tail if dangerous(a)] + [c for c in config if _PUSH_CONFIG_RX.search(c)]
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

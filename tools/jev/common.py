#!/usr/bin/env python3
"""
File: tools/jev/common.py
Description: The shared bottom layer of JEV — locating the hub, reading
             `_data/fleet.yml` `jev:` / `budget:`, the one `gh` wrapper every
             GitHub call goes through, and the small subprocess helper the
             git work uses. Nothing here talks to a model or writes a file.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Dependencies: PyYAML, and the `gh` CLI for gh().
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[2]
FLEET_YML = HUB / "_data" / "fleet.yml"
REGISTRY_YML = HUB / "_data" / "projects.yml"


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
        timeout: int = 900, stdin: str | None = None) -> Run:
    """Run `argv`, capture everything, never raise on a non-zero exit."""
    merged = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(  # noqa: S603 - argv is a list, never a shell string
            argv, cwd=str(cwd) if cwd else None, env=merged, input=stdin,
            capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        return Run(127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return Run(124, exc.stdout or "", f"timed out after {timeout}s")
    return Run(proc.returncode, proc.stdout or "", proc.stderr or "")


def git(args: list[str], cwd: Path, timeout: int = 900) -> Run:
    """git, with the repository's own hooks and pagers out of the way."""
    return run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat", *args],
               cwd=cwd, timeout=timeout)


def gh(args: list[str], cwd: Path | None = None, timeout: int = 180) -> Run:
    """The ONE place JEV shells out to GitHub.

    Centralised so a dry run can be reasoned about in one place and so a
    missing CLI produces one legible error instead of a stack trace per call
    site. JEV never passes `--admin` to anything, and `assert_no_admin` below
    is the belt to that braces.
    """
    if shutil.which("gh") is None:
        raise JevError("the `gh` CLI is required for this command (brew install gh; gh auth login)")
    assert_no_admin(args)
    return run(["gh", *args], cwd=cwd, timeout=timeout)


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
    if args[:1] == ["pr"] and len(args) > 1 and args[1] == "merge":
        raise JevError("refusing: JEV never merges a pull request")


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

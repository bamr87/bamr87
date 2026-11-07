#!/usr/bin/env python3
# ============================================================================
# File:          tools/weekly.py
# Description:   The weekly routine (docs/WEEKLY.md): regroup, recap and save the state of the
#                whole workspace. A Friday run is local only: it takes inventory of the hub and
#                every submodule (branches, worktrees, stashes, uncommitted work, live sessions),
#                proves what is merged, saves everything else to the local archive, refreshes to
#                main and removes what is proven safe (after the report-only runs), runs the PM
#                review, ranks next week's work and drafts the week's chronicles and retro. Every
#                external write waits for `confirm --apply`, the maintainer's yes: `wip/` pushes,
#                Fleet project ops through the § 11 service, and one weekly pull request.
# Usage:         python3 tools/weekly.py run [--scheduled | --apply] [--offline] [--no-plan]
#                python3 tools/weekly.py inventory [--json] [--offline]
#                python3 tools/weekly.py confirm [--apply] [--keep-drafts] [--publish SLUG]…
#                python3 tools/weekly.py status
#                (or tools/dash weekly <run|inventory|confirm|status> …)
# Exit:          0 clean · 1 failed · 2 usage · 3 switched off
# Never:         merges, deletes a remote ref, or pushes outside `wip/` and the weekly PR branch.
#                A Friday run makes no GitHub write at all. Nothing unmerged, uncommitted or in
#                use is ever removed, and uncommitted work is never pushed (constitution § 10.5,
#                § 10.6, § 11, § 13.6, § 23).
# ============================================================================
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".github" / "scripts" / "dash-gen"))

from tools.jev.headless import SECRET_RE  # noqa: E402  (the one secret pattern; never a copy)

RUN_SCHEMA = "weekly-run/v1"
PLAN_SCHEMA = "weekly-plan/v1"
SWITCH_KEY = "hub/weekly"
SNAPSHOT = "_data/weekly_plan.yml"
QUEUE = "_data/work_queue.yml"
ROADMAP = "_data/roadmap.yml"
LANES = ("decide", "finish", "unblock", "do")
LANE_TITLES = {"decide": "Decide", "finish": "Finish", "unblock": "Unblock", "do": "Do"}
SECRET_FILE_RX = re.compile(r"(^|/)(\.env(\.(?!example$|sample$)[^/]+)?|id_[rd]sa|[^/]+\.(pem|p12|pfx|key))$")
#: Shapes SECRET_RE does not cover; only this tool's publish gate needs them.
EXTRA_SECRET_RX = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAIza[0-9A-Za-z_-]{35}\b")
PR_NUMBER_RX = re.compile(r"(?:\(#(\d+)\)$|^Merge pull request #(\d+))")
NWO_RX = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")

DEFAULTS: dict = {
    "wip_prefix": "wip/mac",
    "archive_dir": "~/bamr87-archive/weekly",
    "report_only_runs": 2,
    "worktree_idle_hours": 24,
    "snapshot_max_mb": 50,
    "foreign_roots": ["~/.local/share/kilo"],
    "regenerable": [
        "node_modules", "__pycache__", ".venv", ".venv-*", "_site", "dist", ".pytest_cache", ".DS_Store",
        ".ruff_cache", ".mypy_cache", ".jekyll-cache", "*.tsbuildinfo", "project_health*.yml", "report.json",
        ".vscode-test", "out", ".test-media",
    ],
    "commit": {"name": "bamr87", "email": "10567847+bamr87@users.noreply.github.com"},
    "confirm": {"max_age_days": 8, "board_batches": 4},
    "plan": {
        "capacity": {"decide": 5, "finish": 5, "unblock": 3, "do": 5},
        "priority_score": {"P0": 1000, "P1": 500, "P2": 200, "P3": 50, "none": 100},
        "lane_score": {"decide": 300, "finish": 250, "unblock": 150, "do": 0},
        "pin_score": 5000,
        "age_cap_days": 60,
        "skip_labels": ["epic"],
    },
    "chronicle": {
        "max_per_repo": 8,
        "noise": r"^(chore\((data|jev|submodules?|deps)\)|Merge (branch|remote)|.*\[skip ci\])",
    },
    "history_weeks": 12,
}


# ---- plumbing --------------------------------------------------------------------------------

#: GIT_OPTIONAL_LOCKS=0: a status from this tool never takes the index lock from a live session.
ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


def run(cmd: list[str], cwd: Path | str | None = None, timeout: int = 120,
        env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace",
                              timeout=timeout, env=env or ENV)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return subprocess.CompletedProcess(cmd, 124, "", str(exc))


def git(repo: Path | str, *args: str, timeout: int = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    # submodule.recurse=false: the hub sets it true, and a recursing checkout moves every submodule.
    return run(["git", "-C", str(repo), "-c", "submodule.recurse=false", *args], timeout=timeout, env=env)


def out(repo: Path | str, *args: str, timeout: int = 120) -> str:
    r = git(repo, *args, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""


def yes(repo: Path | str, *args: str) -> bool:
    return git(repo, *args).returncode == 0


def count(repo: Path | str, *args: str) -> int:
    try:
        return int(out(repo, "rev-list", "--count", *args) or 0)
    except ValueError:
        return 0


class GitError(RuntimeError):
    """A git call a safety check depends on failed. `out()` and `count()` turn failure into "" and 0,
    which a guard would read as clean, so every guard uses `strict()` and fails closed."""


def strict(repo: Path | str, *args: str, timeout: int = 120, ok: tuple = (0,)) -> str:
    r = git(repo, *args, timeout=timeout)
    if r.returncode not in ok:
        raise GitError(f"git {args[0]}: {(r.stderr or 'failed').strip()[:160]}")
    return r.stdout.strip("\n")


def strict_count(repo: Path | str, *args: str) -> int:
    try:
        return int(strict(repo, "rev-list", "--count", *args) or 0)
    except ValueError as exc:
        raise GitError(f"git rev-list: {exc}") from exc


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def expand(path: str | Path) -> Path:
    return Path(os.path.expanduser(str(path)))


def real(path: str | Path) -> str:
    return os.path.realpath(str(path))


def merged(base: dict, over: dict | None) -> dict:
    result = dict(base)
    for key, value in (over or {}).items():
        result[key] = merged(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def load_fleet(root: Path) -> dict:
    return yaml.safe_load((root / "_data" / "fleet.yml").read_text()) or {}


def load_config(fleet: dict) -> dict:
    return merged(DEFAULTS, fleet.get("weekly"))


def plan_week(now: datetime) -> str:
    """The ISO week a run plans for: a Friday, Saturday or Sunday run plans the coming week."""
    year, week, _ = (now + timedelta(days=3)).isocalendar()
    return f"{year}-W{week:02d}"


def switched_off(fleet: dict) -> str | None:
    """Why the switch stops a scheduled run, or None: the most restrictive level wins (§ 17.2)."""
    if (fleet.get("weekly") or {}).get("enabled") is False:
        return "weekly.enabled is false"
    sw = fleet.get("switches") or {}
    entry = (sw.get("loops") or {}).get(SWITCH_KEY) or {}
    levels = (("global", sw.get("global") or {}), (f"group {entry.get('group')}",
              (sw.get("groups") or {}).get(entry.get("group")) or {}), (SWITCH_KEY, entry))
    for name, level in levels:
        if level.get("state") == "off":
            return f"{name} is off" + (f": {level['reason']}" if level.get("reason") else "")
    return None


# ---- what is in use --------------------------------------------------------------------------

def live_state(sessions_dir: Path | None = None) -> dict:
    """Everything that says a path is in use: live agent sessions, process working directories,
    and what running containers mount or were composed from."""
    sessions, paths, ids = [], set(), set()
    for file in sorted((sessions_dir or expand("~/.claude/sessions")).glob("*.json")):
        try:
            row = json.loads(file.read_text())
            os.kill(int(row.get("pid")), 0)
        except (OSError, ValueError, TypeError):
            continue
        sessions.append({"name": row.get("name") or "", "cwd": row.get("cwd") or ""})
        ids.add(str(row.get("sessionId") or ""))
        if row.get("cwd"):
            paths.add(real(row["cwd"]))
    degraded = []
    lsof = run(["lsof", "-a", "-d", "cwd", "-u", str(os.getuid()), "-Fn"], timeout=30)
    if lsof.returncode != 0 and not lsof.stdout:
        degraded.append("lsof")
    paths |= {real(line[1:]) for line in lsof.stdout.splitlines() if line.startswith("n/")}
    ps = run(["docker", "ps", "-q"], timeout=15)
    if ps.returncode != 0:
        degraded.append("docker")
    ids_out = ps.stdout.split()
    if ids_out:
        inspect = run(["docker", "inspect", *ids_out], timeout=30)
        try:
            containers = json.loads(inspect.stdout)
        except json.JSONDecodeError:
            containers = []
            degraded.append("docker inspect")
        for c in containers:
            for m in c.get("Mounts") or []:
                if m.get("Type") == "bind":
                    paths.add(real(re.sub(r"^/host_mnt", "", m.get("Source") or "")))
            wd = ((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.project.working_dir")
            if wd:
                paths.add(real(wd))
    return {"sessions": sessions, "paths": sorted(p for p in paths if p != "/"),
            "session_ids": sorted(i for i in ids if i), "degraded": degraded}


def is_live(path: str, live: dict) -> str | None:
    """Why `path` is in use, or None. A process or mount inside it counts; one at a parent does not."""
    target = real(path)
    for p in live.get("paths") or []:
        if p == target or p.startswith(target + os.sep):
            return f"in use at {p}"
    for sid in live.get("session_ids") or []:
        if f"/{sid}/" in target + "/":
            return "in a live session's scratchpad"
    return None


# ---- classification --------------------------------------------------------------------------

def registry(root: Path) -> list[dict]:
    """The hub and every submodule in .gitmodules, each with the branch it declares."""
    rows = [{"name": "hub", "path": root, "branch": "main"}]
    listing = out(root, "config", "-f", ".gitmodules", "--get-regexp", r"\.path$")
    for line in listing.splitlines():
        key, _, rel = line.partition(" ")
        name = key[len("submodule."):-len(".path")]
        branch = out(root, "config", "-f", ".gitmodules", f"submodule.{name}.branch") or "main"
        rows.append({"name": Path(rel).name, "path": root / rel, "branch": branch})
    return rows


def nwo_of(repo: Path) -> str | None:
    match = NWO_RX.search(out(repo, "remote", "get-url", "origin"))
    return match.group(1) if match else None


def gh_prs(nwo: str | None) -> list[dict]:
    if not nwo:
        return []
    r = run(["gh", "pr", "list", "--repo", nwo, "--state", "all", "--limit", "1000", "--json",
             "number,headRefName,headRefOid,baseRefName,state"], timeout=60)
    try:
        return json.loads(r.stdout) if r.returncode == 0 else []
    except json.JSONDecodeError:
        return []


def unique_patches(repo: Path, upstream: str, tip: str) -> int:
    """Commits on `tip` with no patch-equivalent on `upstream`; -1 when git cannot say."""
    r = git(repo, "cherry", upstream, tip)
    return sum(line.startswith("+") for line in r.stdout.splitlines()) if r.returncode == 0 else -1


def holds_everything(repo: Path, onto: str, tip: str) -> bool:
    """True when `onto` provably has all of `tip`. Both tests must agree: patch-ids ignore whitespace and
    see nothing in a merge, and the tree test alone calls a commit-then-remove branch merged. A
    multi-commit squash fails this on purpose; its merged PR is the proof."""
    merged_tree = git(repo, "merge-tree", "--write-tree", onto, tip)
    tree = out(repo, "rev-parse", f"{onto}^{{tree}}")
    same = merged_tree.returncode == 0 and bool(tree) and merged_tree.stdout.split("\n")[0].strip() == tree
    return same and unique_patches(repo, onto, tip) == 0


def merge_proof(repo: Path, name: str, tip: str, base: str, prs: list[dict], offline: bool = False) -> str | None:
    """Evidence that `name` is merged, or None. A branch's `[gone]` upstream proves nothing, and a merged
    PR with the same head name proves nothing either: its tip must be the PR's or be covered by it, and
    the PR must have merged into the branch this repo declares."""
    if yes(repo, "merge-base", "--is-ancestor", tip, base):
        return "ancestor of main"
    if holds_everything(repo, base, tip):
        return "main already holds all of it"
    declared = base.split("/", 1)[1]
    for pr in prs:
        if pr.get("headRefName") != name or pr.get("state") != "MERGED" or pr.get("baseRefName") != declared:
            continue
        oid, number = pr.get("headRefOid") or "", pr.get("number")
        if tip == oid:
            return f"tip is the head of merged PR #{number}"
        if yes(repo, "cat-file", "-e", oid):
            if yes(repo, "merge-base", "--is-ancestor", tip, oid):
                return f"behind the head of merged PR #{number}"
            continue
        if not offline and yes(repo, "fetch", "-q", "origin", f"pull/{number}/head"):
            head = out(repo, "rev-parse", "FETCH_HEAD")
            if head and holds_everything(repo, head, tip):
                return f"merged PR #{number} already holds all of it"
    return None


def classify_branch(repo: Path, name: str, tip: str, base: str, prs: list[dict], offline: bool = False) -> dict:
    row = {"name": name, "tip": tip, "ahead": strict_count(repo, f"{base}..{tip}"),
           "unsaved": strict_count(repo, tip, "--not", "--remotes"), "proof": None}
    mine = [p for p in prs if p.get("headRefName") == name]
    open_pr = next((p for p in mine if p.get("state") == "OPEN"), None)
    if open_pr:
        return {**row, "state": "open-pr", "pr": open_pr.get("number")}
    row["proof"] = merge_proof(repo, name, tip, base, prs, offline)
    if row["proof"]:
        return {**row, "state": "merged"}
    return {**row, "state": "local-only" if row["unsaved"] else "remote-held"}


def worktrees(repo: Path) -> list[dict]:
    rows, cur = [], {}
    for line in strict(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if cur:
                rows.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(" ")
        cur[key] = value or True
    return rows


def initialized_submodules(path: Path) -> list[str]:
    """Initialized submodules inside a worktree. Removing it deletes their gitdirs, with any stash,
    ignored file or local branch in them, so such a worktree is never removed automatically."""
    if not (path / ".gitmodules").exists():
        return []
    listing = strict(path, "config", "-f", ".gitmodules", "--get-regexp", r"\.path$", ok=(0, 1))
    rels = [line.partition(" ")[2] for line in listing.splitlines()]
    return [rel for rel in rels if (path / rel / ".git").exists()]


def ignored_keepers(path: Path, patterns: Iterable[str]) -> list[str]:
    """Ignored files a removal would lose, minus what is regenerable: `git status` never shows them."""
    from fnmatch import fnmatch
    keep = []
    for line in strict(path, "status", "--ignored", "--porcelain", "--ignore-submodules=all").splitlines():
        if not line.startswith("!! "):
            continue
        rel = line[3:].rstrip("/")
        if not any(fnmatch(part, pat) for part in rel.split("/") for pat in patterns):
            keep.append(rel)
    return keep


def idle_hours(path: Path, now: datetime) -> float:
    gitdir = Path(strict(path, "rev-parse", "--absolute-git-dir"))
    marks = [p.stat().st_mtime for p in (gitdir / "logs" / "HEAD", path) if p.exists()]
    return (now.timestamp() - max(marks)) / 3600 if marks else 0.0


def classify_worktree(w: dict, cfg: dict, live: dict, now: datetime) -> dict:
    path = Path(w["worktree"])
    branch = str(w.get("branch") or "").replace("refs/heads/", "") or None
    row = {"path": str(path), "branch": branch, "head": w.get("HEAD"), "files": 0}
    if not path.exists():
        return {**row, "state": "missing", "why": "the directory is gone; check it before `git worktree prune`"}
    if any(real(path).startswith(real(expand(r)) + os.sep) for r in cfg["foreign_roots"]):
        return {**row, "state": "foreign", "why": "owned by another tool"}
    if w.get("locked"):
        return {**row, "state": "locked", "why": "locked"}
    try:
        dirty = [l for l in strict(path, "status", "--porcelain", "--ignore-submodules=all").splitlines() if l]
        row["files"] = len(dirty)
        why = is_live(str(path), live)
        if why:
            return {**row, "state": "live", "why": why}
        if dirty:
            return {**row, "state": "dirty", "why": f"{len(dirty)} uncommitted file(s)"}
        inited = initialized_submodules(path)
        if inited:
            return {**row, "state": "has-submodules", "why": f"{len(inited)} initialized submodule(s), never removed automatically"}
        if strict_count(path, "HEAD", "--not", "--remotes", "--branches"):
            return {**row, "state": "unique-commits", "why": "detached with commits no ref holds"}
        held = ignored_keepers(path, cfg["regenerable"])
        if held:
            return {**row, "state": "holds-ignored", "why": "ignored files: " + ", ".join(held[:4])}
        idle = idle_hours(path, now)
    except (GitError, OSError) as exc:
        return {**row, "state": "unknown", "why": f"could not be read: {exc}"}
    if idle < float(cfg["worktree_idle_hours"]):
        return {**row, "state": "recent", "why": f"touched {idle:.0f}h ago"}
    return {**row, "state": "dead", "why": "clean, idle and unused"}


def inventory_repo(row: dict, cfg: dict, live: dict, prs_for: Callable[[str | None], list[dict]],
                   offline: bool, now: datetime) -> dict:
    path, declared = row["path"], row["branch"]
    base = f"origin/{declared}"
    rec: dict = {"name": row["name"], "path": str(path), "branch": declared, "nwo": None, "fetch_failed": False}
    if not (path / ".git").exists():
        return {**rec, "state": "uninitialized"}
    if not offline and git(path, "fetch", "origin", "--prune", "--quiet", timeout=180).returncode != 0:
        rec["fetch_failed"] = True
    if not yes(path, "rev-parse", "-q", "--verify", base):
        return {**rec, "state": "no-base"}
    rec["nwo"] = nwo_of(path)
    try:
        # lstrip=2, not :short: a tag with a branch's name makes :short ambiguous (`heads/x`)
        heads = [l.split(" ", 1) for l in strict(path, "for-each-ref", "--format=%(refname:lstrip=2) %(objectname)",
                                                 "refs/heads").splitlines()]
        others = [(n, t) for n, t in heads if n != declared]
        prs = prs_for(rec["nwo"]) if others and not offline else []
        trees = worktrees(path)
        checked_out = {str(w.get("branch")).replace("refs/heads/", ""): w["worktree"] for w in trees[1:] if w.get("branch")}
        branches = []
        for name, tip in others:
            b = classify_branch(path, name, tip, base, prs, offline)
            b["worktree"] = checked_out.get(name)
            branches.append(b)
        rows = [classify_worktree(w, cfg, live, now) for w in trees[1:]]
        for w in rows:
            nested = any(real(t["worktree"]).startswith(real(w["path"]) + os.sep) for t in trees)
            if w["state"] == "dead" and nested:
                w.update(state="holds-worktree", why="another worktree lives inside it")
        local_main = dict(heads).get(declared)
        head = strict(path, "rev-parse", "HEAD")
        head_branch = out(path, "symbolic-ref", "--short", "-q", "HEAD") or None
        dirty = [l for l in strict(path, "status", "--porcelain", "--ignore-submodules=all").splitlines() if l]
        return {
            **rec, "state": "ok", "head": head, "head_branch": head_branch,
            "behind": strict_count(path, f"HEAD..{base}"), "ahead": strict_count(path, f"{base}..HEAD"),
            "detached_unique": 0 if head_branch else strict_count(path, "HEAD", "--not", "--remotes", "--branches"),
            "main_tip": local_main, "main_ahead": strict_count(path, f"{base}..{local_main}") if local_main else 0,
            "dirty": dirty[:200], "dirty_count": len(dirty), "branches": branches, "worktrees": rows,
            "stashes": [l for l in strict(path, "stash", "list", "--format=%H %cs %s").splitlines() if l],
        }
    except GitError as exc:
        return {**rec, "state": "unreadable", "why": str(exc)}


def inventory(root: Path, cfg: dict, live: dict, offline: bool = False, now: datetime | None = None,
              prs_for: Callable[[str | None], list[dict]] = gh_prs, workers: int = 6) -> list[dict]:
    moment = now or now_utc()
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda r: inventory_repo(r, cfg, live, prs_for, offline, moment), registry(root)))


def wip_candidates(inv: list[dict]) -> list[dict]:
    rows = []
    for repo in inv:
        for b in repo.get("branches") or []:
            if b["state"] == "local-only" or (b["state"] == "open-pr" and b["unsaved"]):
                rows.append({"repo": repo["name"], "path": repo["path"], "branch": b["name"], "tip": b["tip"],
                             "commits": b["unsaved"]})
        if repo.get("main_ahead"):
            tip = repo["main_tip"]
            if count(repo["path"], tip, "--not", "--remotes"):
                rows.append({"repo": repo["name"], "path": repo["path"], "branch": repo["branch"], "tip": tip,
                             "commits": repo["main_ahead"]})
    return rows


def removals(inv: list[dict]) -> dict:
    """What a tidy may remove: dead worktrees, and merged branches no worktree still holds."""
    trees, branches = [], []
    for repo in inv:
        dead = {w["path"] for w in repo.get("worktrees") or [] if w["state"] == "dead"}
        trees += [{"repo": repo["name"], "path": repo["path"], "worktree": w} for w in sorted(dead)]
        for b in repo.get("branches") or []:
            held = b.get("worktree")
            if b["state"] == "merged" and (not held or held in dead):
                branches.append({"repo": repo["name"], "path": repo["path"], "branch": b["name"], "tip": b["tip"],
                                 "proof": b["proof"]})
    return {"worktrees": trees, "branches": branches}


# ---- save ------------------------------------------------------------------------------------

def snapshot_dirty(path: Path, label: str, dest: Path, max_mb: int) -> dict:
    """Copy uncommitted work to the archive without touching the working tree."""
    result: dict = {"label": label, "path": str(path), "patch": None, "untracked": 0, "skipped": []}
    diff = git(path, "diff", "HEAD", "--binary", timeout=180)
    if diff.returncode != 0:
        raise GitError(f"git diff in {path}: {diff.stderr.strip()[:120]}")
    if diff.stdout:
        target = dest / f"{label}.patch"
        target.write_text(diff.stdout)
        result["patch"] = str(target)
    names = [n for n in strict(path, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if n]
    keep = []
    for name in names:
        file = path / name
        try:
            if file.is_file() and file.stat().st_size <= max_mb * 1024 * 1024 and os.access(file, os.R_OK):
                keep.append(name)
            elif file.is_file():
                result["skipped"].append(name)
        except OSError:
            result["skipped"].append(name)
    if keep:
        with tarfile.open(dest / f"{label}.untracked.tgz", "w:gz") as tar:
            for name in keep:
                try:
                    tar.add(path / name, arcname=name)
                    result["untracked"] += 1
                except OSError:
                    result["skipped"].append(name)
    return result


def snapshot_label(repo: str, path: str) -> str:
    """Two worktrees can share a basename; the path's hash keeps their snapshots apart."""
    return f"{repo}--{Path(path).name}-{hashlib.sha1(path.encode()).hexdigest()[:6]}"


def save_repo(repo: dict, dest: Path, cfg: dict) -> dict:
    """Bundle everything `main` does not contain: branches, stashes, and commits only a detached HEAD
    or a vanished worktree still points at. Then verify the bundle, and snapshot uncommitted work."""
    path, base = Path(repo["path"]), f"origin/{repo['branch']}"
    result: dict = {"repo": repo["name"], "ok": True, "bundle": None, "refs": 0, "snapshots": []}
    temp: list[str] = []
    try:
        max_mb = int(cfg["snapshot_max_mb"])
        if repo.get("dirty_count"):
            result["snapshots"].append(snapshot_dirty(path, snapshot_label(repo["name"], "checkout"), dest, max_mb))
        for w in repo.get("worktrees") or []:
            if w.get("files"):
                result["snapshots"].append(snapshot_dirty(Path(w["path"]), snapshot_label(repo["name"], w["path"]), dest, max_mb))
        (dest / "refs").mkdir(exist_ok=True)
        (dest / "refs" / f"{repo['name']}.txt").write_text(
            strict(path, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads") + "\n")
        refs = [f"refs/heads/{b['name']}" for b in repo.get("branches") or [] if b["ahead"]]
        if repo.get("main_ahead"):
            refs.append(f"refs/heads/{repo['branch']}")
        loose = [line.split(" ", 1)[0] for line in repo.get("stashes") or []]
        if repo.get("detached_unique"):
            loose.append(repo["head"])
        for w in repo.get("worktrees") or []:
            if not w.get("branch") and w.get("head") and strict_count(path, w["head"], "--not", "--remotes", "--branches"):
                loose.append(w["head"])
        for n, sha in enumerate(dict.fromkeys(loose)):
            ref = f"refs/weekly/keep-{n}"
            strict(path, "update-ref", ref, sha)
            temp.append(ref)
        if refs or temp:
            bundle = dest / f"{repo['name']}.bundle"
            strict(path, "bundle", "create", "-q", str(bundle), f"^{base}", *refs, *temp, timeout=300)
            strict(path, "bundle", "verify", "-q", str(bundle))
            result.update(bundle=str(bundle), refs=len(refs) + len(temp))
    except (GitError, OSError) as exc:
        return {**result, "ok": False, "error": str(exc)[:200]}
    finally:
        for ref in temp:
            git(path, "update-ref", "-d", ref)
    return result


def save(inv: list[dict], dest: Path, cfg: dict) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    dest.chmod(0o700)
    return [save_repo(r, dest, cfg) for r in inv if r.get("state") == "ok"]


def looks_secret(text: str) -> bool:
    return bool(SECRET_RE.search(text) or EXTRA_SECRET_RX.search(text))


def scan_commits(repo: Path, tip: str, max_commits: int = 500) -> list[str]:
    """Where commits about to go public look like they hold a secret. Names the file, never the value.
    Reads every commit's message and every blob it adds, merges included, because a diff shows neither
    binaries nor what only a merge brought in. Anything it cannot read counts as a hit."""
    listed = git(repo, "rev-list", tip, "--not", "--remotes", timeout=60)
    shas = listed.stdout.split()
    if listed.returncode != 0:
        return ["(the commits could not be read)"]
    if len(shas) > max_commits:
        return [f"({len(shas)} commits is too many to scan)"]
    hits: set[str] = set()
    seen: set[str] = set()
    for sha in shas:
        message = git(repo, "log", "-1", "--format=%B", sha)
        if message.returncode != 0:
            return ["(the commits could not be read)"]
        if looks_secret(message.stdout):
            hits.add(f"commit {sha[:8]} message")
        raw = git(repo, "diff-tree", "--root", "-r", "-m", "--no-commit-id", "--no-renames", "-z", sha, timeout=60)
        if raw.returncode != 0:
            return ["(the commits could not be read)"]
        fields = raw.stdout.split("\0")
        for meta, name in zip(fields[0::2], fields[1::2]):
            parts = meta.split()
            if len(parts) < 5 or parts[4] == "D" or parts[1] == "160000":
                continue
            if SECRET_FILE_RX.search(name):
                hits.add(f"{name} (secret-shaped file name)")
            if parts[3] in seen:
                continue
            seen.add(parts[3])
            blob = git(repo, "cat-file", "blob", parts[3], timeout=60)
            if blob.returncode != 0:
                hits.add(f"{name} (could not be read)")
            elif looks_secret(blob.stdout):
                hits.add(name)
    return sorted(hits)


# ---- refresh and tidy ------------------------------------------------------------------------

def checkout_in_use(path: str, repo: dict, live: dict) -> bool:
    """A session or a process in the repo's own checkout, not in one of its linked worktrees."""
    linked = [real(w["path"]) for w in repo.get("worktrees") or []]
    target = real(path)
    places = [real(row.get("cwd") or "/") for row in live.get("sessions") or []] + list(live.get("paths") or [])
    for place in places:
        inside = place == target or place.startswith(target + os.sep)
        if inside and not any(place == w or place.startswith(w + os.sep) for w in linked):
            return True
    return False


def refresh(root: Path, inv: list[dict], live: dict) -> dict:
    """Fast-forward the hub and move each submodule to its declared branch, one at a time, leaving out
    any that a session is in or that is on a feature branch. Pointers stay with the daily
    update-submodules PR, so local main never diverges from the protected branch."""
    if (root / ".git" / "index.lock").exists():
        return {"ok": False, "error": "the hub's index is locked", "notes": []}
    if out(root, "diff", "--cached", "--name-only"):
        return {"ok": False, "error": "the hub has staged changes, so its index is left alone", "notes": []}
    fresh = live_now(live)
    if fresh.get("degraded"):
        return {"ok": False, "error": "could not read what is in use, so nothing moved", "notes": []}
    notes = []
    if out(root, "symbolic-ref", "--short", "-q", "HEAD") == "main":
        git(root, "fetch", "-q", "origin")
        if not yes(root, "merge", "--ff-only", "-q", "origin/main"):
            notes.append("hub main did not fast-forward")
    else:
        notes.append("hub is not on main")
    failed = 0
    for repo in inv[1:]:
        if repo.get("state") != "ok":
            continue
        name, path = repo["name"], repo["path"]
        if checkout_in_use(path, repo, fresh):
            notes.append(f"{name}: in use, so it stays put")
            continue
        try:  # read now, not at inventory: a commit may have landed during the save
            branch = out(path, "symbolic-ref", "--short", "-q", "HEAD") or None
            if branch not in (None, repo["branch"]):
                notes.append(f"{name}: left on {branch}")
                continue
            head = strict(path, "rev-parse", "HEAD")
            if branch is None and strict_count(path, head, "--not", "--remotes", "--branches"):
                strict(path, "branch", f"weekly/detached-{head[:8]}", head)
        except GitError as exc:
            notes.append(f"{name}: stays put, its detached commits could not be anchored ({exc})")
            continue
        rel = os.path.relpath(path, root)
        script = run(["bash", "tools/update-submodules.sh", "--no-commit", "--no-push", rel], cwd=root, timeout=300)
        git(root, "reset", "-q", "--", rel)  # only what this call staged: the index was empty before the run
        failed += script.returncode != 0
        notes += [re.sub(r"\x1b\[[0-9;]*m", "", l).strip() for l in script.stdout.splitlines() if "WARN" in l]
    return {"ok": not failed, "error": f"{failed} submodule(s) failed to refresh" if failed else None, "notes": notes[:40]}


def tidy(plan: dict, saved: list[dict], cfg: dict, live: dict, now: datetime) -> dict:
    """Remove what `removals` listed, re-checking each at the moment of removal, in repos whose save
    verified. No `--force`: git itself refuses a dirty worktree. A dead worktree goes first so the
    merged branch it held can follow. Nothing is removed if what is in use cannot be read."""
    safe = {s["repo"] for s in saved if s.get("ok")}
    done: dict = {"worktrees": [], "branches": [], "skipped": []}
    fresh = live_now(live)
    if fresh.get("degraded") or live.get("degraded"):
        which = ", ".join(fresh.get("degraded") or live.get("degraded") or [])
        done["skipped"].append(f"nothing removed: could not read what is in use ({which})")
        return done
    for t in plan["worktrees"]:
        if t["repo"] not in safe:
            done["skipped"].append(f"{t['worktree']}: its repo's save failed")
            continue
        try:
            row = next((w for w in worktrees(Path(t["path"])) if w.get("worktree") == t["worktree"]), None)
        except GitError as exc:
            done["skipped"].append(f"{t['worktree']}: {exc}")
            continue
        check = classify_worktree(row, cfg, fresh, now) if row else {"state": "gone"}
        if check["state"] != "dead":
            done["skipped"].append(f"{t['worktree']}: now {check['state']}")
            continue
        r = git(t["path"], "worktree", "remove", t["worktree"], timeout=300)
        (done["worktrees"].append(t["worktree"]) if r.returncode == 0 else
         done["skipped"].append(f"{t['worktree']}: {r.stderr.strip()[:120]}"))
    for b in plan["branches"]:
        label = f"{b['repo']}:{b['branch']}"
        if b["repo"] not in safe:
            done["skipped"].append(f"{label}: its repo's save failed")
        elif out(b["path"], "rev-parse", "-q", "--verify", f"refs/heads/{b['branch']}") != b["tip"]:
            done["skipped"].append(f"{label}: moved since the inventory")
        else:
            r = git(b["path"], "branch", "-D", b["branch"])
            done["branches"].append(label) if r.returncode == 0 else done["skipped"].append(f"{label}: in use")
    return done


def live_now(live: dict) -> dict:
    """A fresh read when the inventory used the real machine; a test's fixed state otherwise."""
    return live if live.get("fixed") else live_state()


# ---- plan ------------------------------------------------------------------------------------

def run_pm(root: Path) -> dict:
    r = run([sys.executable, str(root / "tools" / "pm_review.py"), "review"], cwd=root, timeout=600)
    return {"ok": r.returncode == 0, "error": (r.stderr or r.stdout).strip()[-300:] if r.returncode else None}


def pm_files(root: Path) -> tuple[dict | None, dict | None]:
    pm = root / ".fleet" / "pm"
    try:
        return json.loads((pm / "model.json").read_text()), json.loads((pm / "review.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None, None


def lane_of(item: dict, pr: dict | None, status: str, labels: set[str]) -> str:
    if "needs-amr" in labels or status == "Needs Amr":
        return "decide"
    if pr is None or pr.get("draft"):
        return "do"
    if pr.get("mergeable") == "CONFLICTING" or pr.get("ci") in ("FAILURE", "ERROR"):
        return "unblock"
    return "finish"


def rank(model: dict, queue: dict, cfg: dict, held: Iterable[str], now: datetime) -> dict:
    """Every open item ranked by rules alone. Deterministic: the same input gives the same plan."""
    p = cfg["plan"]
    board = {(i.get("repo"), i.get("number")): i.get("fields") or {} for i in (model.get("board") or {}).get("items") or []}
    pins = {k: n for n, k in enumerate(queue.get("order") or [])}
    overrides = queue.get("priority") or {}
    held = set(held) - {"Needs Amr"}
    skip = set(p["skip_labels"])
    rows, held_count = [], 0
    for repo in model.get("repos") or []:
        if repo.get("private") or repo.get("archived"):
            continue
        prs = repo.get("prs") or {}
        for item in repo.get("items") or []:
            number, labels = item.get("number"), set(item.get("labels") or [])
            is_pr = str(item.get("kind", "")).startswith("p")
            pr = (prs.get(str(number)) or prs.get(number)) if is_pr else None
            fields = board.get((item.get("repo"), number)) or {}
            status = fields.get("Status") or ""
            if status in held or labels & skip:
                held_count += status in held
                continue
            key = f"{'pr' if is_pr else 'issue'}:{item.get('repo')}#{number}"
            lane = lane_of(item, pr if is_pr else None, status, labels)
            priority = overrides.get(key) or fields.get("Priority") or next(
                (x for x in ("P0", "P1", "P2", "P3") if x in labels), "none")
            created = item.get("created_at") or ""
            age = max(0, (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days) if created else 0
            score = p["priority_score"].get(priority, p["priority_score"]["none"]) + p["lane_score"][lane] + min(age, p["age_cap_days"])
            reasons = [priority if priority != "none" else "no priority set", f"{age}d old"]
            if key in pins:
                score += p["pin_score"] - pins[key]
                reasons.insert(0, "pinned")
            if lane == "finish":
                reasons.append("ready for your review")
            elif lane == "unblock":
                reasons.append("conflicting" if (pr or {}).get("mergeable") == "CONFLICTING" else "CI failing")
            rows.append({"key": key, "ref": f"{item.get('repo')}#{number}", "title": item.get("title") or "",
                         "url": item.get("url") or "", "lane": lane, "priority": priority, "score": score,
                         "reasons": reasons})
    rows.sort(key=lambda r: (-r["score"], r["ref"]))
    lanes = {lane: [r for r in rows if r["lane"] == lane][: p["capacity"][lane]] for lane in LANES}
    return {"lanes": lanes, "ranked": len(rows), "held": held_count,
            "by_lane": {lane: sum(r["lane"] == lane for r in rows) for lane in LANES}}


def proposed_queue(doc: dict, plan: dict, open_keys: set[str], pinned: set[str], week: str, today: str) -> dict:
    """The human's pins stay first and in order; this week's plan follows them. A key leaves only if it
    was pinned when the run read the fleet and was closed then, so a pin added since is never dropped."""
    import work_queue as wq
    stale = {k for k in pinned if wq.kind_of(k) in ("issue", "pr")} - open_keys
    keys = set(doc.get("order") or []) | set(doc.get("priority") or {}) | set(doc.get("notes") or {})
    pruned, _ = wq.prune(doc, keys - stale)
    order = list(pruned.get("order") or [])
    wanted = [r["key"] for lane in LANES for r in plan["lanes"][lane]]
    fresh = [k for k in wanted if k not in order][: max(0, wq.MAX_ORDER - len(order))]
    notes = {k: f"Weekly plan {week}" for k in fresh}
    return wq.apply_changes({**pruned, "order": order + fresh}, notes=notes, today=today)


# ---- recap: chronicles and the retro (constitution § 23) --------------------------------------

def activity(inv: list[dict], since: datetime, until: datetime, noise: str, hidden: Iterable[str] = ()) -> dict:
    """Commits that reached each repo's main in the window, by day and repo. Git alone, so $0."""
    rx = re.compile(noise)
    skip = set(hidden)
    days: dict = {}
    for repo in inv:
        if repo.get("state") != "ok" or not repo.get("nwo") or repo["nwo"] in skip:
            continue
        log = out(repo["path"], "log", f"origin/{repo['branch']}", f"--since={since.isoformat()}",
                  f"--until={until.isoformat()}", "--format=%cs%x09%s", timeout=60)
        for line in log.splitlines():
            day, _, subject = line.partition("\t")
            if subject and not rx.search(subject):
                days.setdefault(day, {}).setdefault(repo["nwo"], []).append(subject)
    return days


def totals(days: dict) -> dict:
    subjects = [(repo, s) for day in days.values() for repo, rows in day.items() for s in rows]
    prs = {(repo, next(g for g in m.groups() if g)) for repo, s in subjects for m in [PR_NUMBER_RX.search(s)] if m}
    return {"commits": sum(not s.startswith("Merge pull request") for _, s in subjects), "prs_merged": len(prs),
            "repos": len({repo for repo, _ in subjects}), "days": len(days)}


def redact(text: str) -> str:
    return SECRET_RE.sub("[REDACTED]", text)


def front_matter(title: str, date: str, description: str, categories: list[str]) -> str:
    head = {"title": title, "date": date, "description": description, "categories": categories,
            "tags": ["chronicle"], "draft": True}
    return "---\n" + yaml.safe_dump(head, sort_keys=False, allow_unicode=True) + "---\n\n"


def weight(subject: str) -> int:
    """Lead with what shipped: a feature before a fix before everything else. The sort is stable."""
    match = re.match(r"([a-z]+)[(!:]", subject)
    return {"feat": 0, "fix": 1, "perf": 2}.get(match.group(1) if match else "", 3)


def repo_lines(rows: list[str], limit: int) -> list[str]:
    shown = sorted((r for r in rows if not r.startswith("Merge pull request")), key=weight) or rows
    lines = [f"- {s}" for s in shown[:limit]]
    if len(shown) > limit:
        lines.append(f"- and {len(shown) - limit} more")
    return lines


def render_chronicle(day: str, repos: dict, limit: int) -> str:
    t = totals({day: repos})
    body = [front_matter(f"Fleet chronicle: {day}", day, f"{t['commits']} commits across {t['repos']} repos.", ["chronicle"]).rstrip("\n"), ""]
    body.append(f"{t['commits']} commits and {t['prs_merged']} merged pull requests across {t['repos']} repos.")
    for nwo in sorted(repos):
        body += ["", f"## {nwo}", "", *repo_lines(repos[nwo], limit)]
    return redact("\n".join(body) + "\n")


def render_retro(week: str, date: str, days: dict, state: dict, backlog: dict, plan: dict | None, limit: int) -> str:
    t = totals(days)
    by_repo: dict = {}
    for day in days.values():
        for nwo, rows in day.items():
            by_repo.setdefault(nwo, []).extend(rows)
    top = sorted(by_repo.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:6]
    body = [front_matter(f"Weekly retro: going into {week}", date,
                         f"{t['commits']} commits across {t['repos']} repos, and the plan for {week}.",
                         ["chronicle", "retrospective"]).rstrip("\n"), ""]
    body.append(f"{t['commits']} commits and {t['prs_merged']} merged pull requests across {t['repos']} repos, on {t['days']} active days.")
    body += ["", "## What shipped", ""]
    for nwo, rows in top:
        body += [f"### {nwo}", "", *repo_lines(rows, limit), ""]
    body += ["## Where things stand", "",
             f"- {state.get('on_main', 0)} of {state.get('repos', 0)} repos on their declared branch.",
             f"- {state.get('local_only', 0)} branches with work on no remote, {state.get('uncommitted', 0)} places with uncommitted work.",
             f"- {backlog.get('open_items', 0)} open items, {backlog.get('on_board', 0)} on the Fleet project, {backlog.get('findings', 0)} PM findings.", ""]
    if plan:
        body += [f"## The plan for {week}", ""]
        for lane in LANES:
            rows = plan["lanes"][lane]
            if rows:
                body += [f"### {LANE_TITLES[lane]}", "", *[f"- [{r['ref']}]({r['url']}): {r['title']}" for r in rows], ""]
    body += ["## In my own words", "", "<!-- weekly: your notes go here; an empty section is removed on publish -->", ""]
    return redact("\n".join(body))


def finalize_post(text: str, keep_draft: bool) -> str:
    """Publish a reviewed post: drop `draft: true` (§ 23.4) and any section left unwritten."""
    text = re.sub(r"\n## In my own words\n\n<!-- weekly:[^\n]*-->\n*", "\n", text).rstrip() + "\n"
    return text if keep_draft else re.sub(r"(?m)^draft: true\n", "", text, count=1)


def draft_posts(root: Path) -> list[str]:
    folder = root / "pages" / "posts"
    return sorted(p.name for p in folder.glob("*.md") if re.search(r"(?m)^draft: true$", p.read_text(errors="replace")))


# ---- the run ---------------------------------------------------------------------------------

def run_dirs(state_dir: Path) -> list[Path]:
    return sorted((p for p in state_dir.glob("*-W*") if (p / "run.json").exists()), key=lambda p: p.name)


def read_run(path: Path) -> dict:
    return json.loads((path / "run.json").read_text())


def scheduled_count(state_dir: Path) -> int:
    runs = [read_run(p) for p in run_dirs(state_dir)]
    return sum(1 for r in runs if r.get("scheduled") and r.get("finished") and not r.get("errors"))


def decide_mode(args: argparse.Namespace, state_dir: Path, cfg: dict) -> str:
    """`preview` changes no repo. `report-only` is the same, on the schedule. `active` refreshes and tidies."""
    if getattr(args, "apply", False):
        return "active"
    if not getattr(args, "scheduled", False):
        return "preview"
    return "active" if scheduled_count(state_dir) >= int(cfg["report_only_runs"]) else "report-only"


@contextlib.contextmanager
def lock(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    file = state_dir / ".lock"
    with contextlib.suppress(OSError, ValueError):
        os.kill(int(file.read_text()), 0)
        raise SystemExit(f"weekly: another run holds {file}")
    file.write_text(str(os.getpid()))
    try:
        yield
    finally:
        file.unlink(missing_ok=True)


def state_summary(inv: list[dict], live: dict) -> dict:
    ok = [r for r in inv if r.get("state") == "ok"]
    tree_rows = [w for r in ok for w in r["worktrees"]]
    return {
        "repos": len(ok), "on_main": sum(r["head_branch"] == r["branch"] and not r["behind"] for r in ok),
        "branches": sum(len(r["branches"]) for r in ok), "worktrees": len(tree_rows),
        "local_only": sum(b["state"] == "local-only" for r in ok for b in r["branches"]),
        "uncommitted": sum(bool(r["dirty_count"]) for r in ok) + sum(bool(w.get("files")) for w in tree_rows),
        "stashes": sum(len(r["stashes"]) for r in ok), "live_sessions": len(live.get("sessions") or []),
    }


def backlog_summary(review: dict | None, model: dict | None) -> dict:
    if not review:
        return {}
    cov = review.get("coverage") or {}
    road: dict = {}
    for entry in (model or {}).get("roadmap") or []:
        road[entry.get("status") or "unknown"] = road.get(entry.get("status") or "unknown", 0) + 1
    return {"open_items": cov.get("open_items", 0), "on_board": cov.get("on_board", 0),
            "findings": len(review.get("findings") or []), "board_ops": len(review.get("ops") or []),
            "roadmap_edits": len(review.get("roadmap_edits") or []), "roadmap": road}


def console_stale(root: Path) -> bool:
    stamp = root / "tools" / "console" / "web" / "dist" / "index.html"
    src = root / "tools" / "console" / "web" / "src"
    if not stamp.exists() or not src.exists():
        return False
    newest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0)
    return newest > stamp.stat().st_mtime


def cmd_run(args: argparse.Namespace, root: Path, state_dir: Path, archive: Path, live: dict | None = None,
            prs_for: Callable = gh_prs, now: datetime | None = None) -> int:
    fleet = load_fleet(root)
    cfg = load_config(fleet)
    moment = now or now_utc()
    if args.scheduled:
        why = switched_off(fleet)
        if why:
            print(f"weekly: skipped, {why}")
            return 3
    with lock(state_dir):
        mode = decide_mode(args, state_dir, cfg)
        week = plan_week(moment)
        run_id = f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{week}"
        folder = state_dir / run_id
        folder.mkdir(parents=True)
        folder.chmod(0o700)
        record: dict = {"schema": RUN_SCHEMA, "id": run_id, "week": week, "mode": mode, "scheduled": bool(args.scheduled),
                        "started": moment.isoformat(), "finished": None, "errors": [],
                        "scheduled_number": scheduled_count(state_dir) + 1}
        in_use = live if live is not None else live_state()
        if in_use.get("degraded"):
            record["errors"].append("could not read what is in use (" + ", ".join(in_use["degraded"]) + "): nothing will be removed")
        print(f"weekly: {run_id} ({mode}), taking inventory")
        inv = inventory(root, cfg, in_use, offline=args.offline, now=moment, prs_for=prs_for)
        (folder / "inventory.json").write_text(json.dumps(inv, indent=1, default=str) + "\n")
        record["errors"] += [f"{r['name']}: fetch failed, using the last known refs" for r in inv if r.get("fetch_failed")]
        record["errors"] += [f"{r['name']}: {r.get('why')}" for r in inv if r.get("state") == "unreadable"]
        print("weekly: saving to the local archive")
        saved = save(inv, archive / run_id, cfg)
        record["errors"] += [f"{s['repo']}: {s.get('error')}" for s in saved if not s["ok"]]
        wip = wip_candidates(inv)
        for row in wip:
            row["blocked"] = scan_commits(Path(row["path"]), row["tip"])
        plan_removal = removals(inv)
        done = None
        if mode == "active":
            print("weekly: refreshing to main and tidying")
            fresh = refresh(root, inv, in_use)
            record["refresh"] = fresh
            if not fresh["ok"]:
                record["errors"].append(f"refresh: {fresh.get('error') or 'update-submodules failed'}")
            done = tidy(plan_removal, saved, cfg, in_use, moment)
        plan, backlog, model, review = None, {}, None, None
        if not (args.no_plan or args.offline):
            print("weekly: PM review and ranking")
            pm = run_pm(root)
            if not pm["ok"]:
                record["errors"].append(f"pm review: {pm['error']}")
            model, review = pm_files(root) if pm["ok"] else (None, None)
            if model:
                import work_queue as wq
                doc, _ = wq.load(root / QUEUE)
                held = ((fleet.get("pm") or {}).get("board") or {}).get("held") or ("Needs Amr", "Hold", "Blocked", "Won't do")
                plan = rank(model, doc, cfg, held, moment)
                record["pinned"] = list(doc.get("order") or [])
                backlog = backlog_summary(review, model)
        print("weekly: drafting the chronicles and the retro")
        hidden = [r.get("repo") for r in (model or {}).get("repos") or [] if r.get("private")]
        days = activity(inv, moment - timedelta(days=7), moment, cfg["chronicle"]["noise"], hidden)
        posts = folder / "posts"
        posts.mkdir()
        limit = int(cfg["chronicle"]["max_per_repo"])
        written = []
        for day, repos in sorted(days.items()):
            name = f"{day}-chronicle.md"
            if on_main(root, f"pages/posts/{name}") is None:
                (posts / name).write_text(render_chronicle(day, repos, limit))
                written.append(name)
        state = state_summary(inv, in_use)
        date = moment.astimezone().date().isoformat()
        retro = f"{date}-weekly-retro.md"
        (posts / retro).write_text(render_retro(week, date, days, state, backlog, plan, limit))
        written.append(retro)
        record.update(state=state, backlog=backlog, plan=plan, wip=wip, saved=saved, removal=plan_removal, done=done,
                      recap=totals(days), posts=written, drafts=draft_posts(root), console_stale=console_stale(root),
                      archive=str(archive / run_id), sessions=in_use.get("sessions"),
                      open_keys=sorted(r["key"] for r in all_open(model)) if model else [],
                      finished=now_utc().isoformat())
        (folder / "run.json").write_text(json.dumps(record, indent=1, default=str) + "\n")
        report = render_report(record, inv, cfg)
        (folder / "report.md").write_text(report)
        print(report)
        print(f"\nfiles: {folder}")
        if args.scheduled:
            notify(f"Weekly review ready: {week}", f"{state['local_only']} branches to save. tools/dash weekly confirm")
        return 1 if record["errors"] else 0


def all_open(model: dict | None) -> list[dict]:
    rows = []
    for repo in (model or {}).get("repos") or []:
        for item in repo.get("items") or []:
            kind = "pr" if str(item.get("kind", "")).startswith("p") else "issue"
            rows.append({"key": f"{kind}:{item.get('repo')}#{item.get('number')}"})
    return rows


def notify(title: str, text: str) -> None:
    script = f'display notification {json.dumps(text)} with title {json.dumps(title)}'
    run(["osascript", "-e", script], timeout=10)


# ---- the report ------------------------------------------------------------------------------

def render_report(rec: dict, inv: list[dict], cfg: dict) -> str:
    s, b, wip = rec["state"], rec.get("backlog") or {}, rec.get("wip") or []
    plan, removal, done = rec.get("plan"), rec["removal"], rec.get("done")
    blocked = [w for w in wip if w.get("blocked")]
    mode_line = {"preview": "Preview: no repo was changed.",
                 "report-only": f"Report-only run, number {rec.get('scheduled_number', 1)} of {cfg['report_only_runs']}: no repo was changed.",
                 "active": "Active run: refreshed to main and tidied."}[rec["mode"]]
    lines = [f"# Weekly review: going into {rec['week']}", "", f"> {mode_line} Everything below was also saved to `{rec['archive']}`.", ""]
    if rec["errors"]:
        lines += ["## Problems", "", *[f"- {e}" for e in rec["errors"]], ""]
    lines += ["## Waiting for you", "", "`tools/dash weekly confirm` shows the detail; `--apply` is your yes.", "",
              f"- Push {len(wip) - len(blocked)} branches to `{cfg['wip_prefix']}/` ({sum(w['commits'] for w in wip if not w.get('blocked'))} commits).",
              f"- Apply {b.get('board_ops', 0)} Fleet project ops, {cfg['confirm']['board_batches']} batches at a time.",
              f"- Open the weekly PR: {len(rec.get('posts') or [])} posts, the plan and the state snapshot."]
    if blocked:
        lines += ["", "Held back because they look like they hold a secret:", ""]
        lines += [f"- {w['repo']} `{w['branch']}`: {'; '.join(w['blocked'][:3])}" for w in blocked]
    verb = "Removed" if done else "Would remove"
    trees = done["worktrees"] if done else [t["worktree"] for t in removal["worktrees"]]
    branches = done["branches"] if done else [f"{b_['repo']}:{b_['branch']}" for b_ in removal["branches"]]
    lines += ["", f"## {verb}", "", f"{len(branches)} merged branches and {len(trees)} dead worktrees. A removed worktree keeps its branch.", ""]
    lines += [f"- `{x}`" for x in [*branches[:30], *trees[:30]]]
    if len(branches) > 30:
        lines.append(f"- and {len(branches) - 30} more branches")
    if done and done["skipped"]:
        lines += ["", "Skipped on the final check:", "", *[f"- {x}" for x in done["skipped"][:20]]]
    lines += ["", "## Open loops", ""]
    lines += [f"- {w['repo']} `{w['branch']}`: {w['commits']} commit(s) on no remote" for w in wip]
    for r in inv:
        if r.get("state") != "ok":
            lines.append(f"- {r['name']}: {r.get('state')}")
            continue
        if r["dirty_count"]:
            lines.append(f"- {r['name']}: {r['dirty_count']} uncommitted file(s) in the checkout (archived, never pushed)")
        if r["head_branch"] != r["branch"] or r["behind"]:
            lines.append(f"- {r['name']}: on {r['head_branch'] or 'a detached HEAD'}, {r['behind']} behind {r['branch']}")
        if r["stashes"]:
            lines.append(f"- {r['name']}: {len(r['stashes'])} stash(es)")
        for w in r["worktrees"]:
            if w["state"] in ("dirty", "unique-commits", "holds-ignored", "holds-worktree", "has-submodules", "locked", "missing", "unknown"):
                lines.append(f"- {r['name']} worktree `{Path(w['path']).name}`: {w['state']} ({w['why']})")
            elif w["state"] == "live" and w.get("files"):
                lines.append(f"- {r['name']} worktree `{Path(w['path']).name}`: {w['files']} uncommitted file(s), in use (archived)")
    if rec.get("console_stale"):
        lines.append("- The console's page is older than its source: `docker restart fleet-console-1`.")
    for snap in (x for s_ in rec.get("saved") or [] for x in s_.get("snapshots") or []):
        if snap["skipped"]:
            lines.append(f"- `{snap['label']}`: {len(snap['skipped'])} file(s) too big or unreadable, not archived")
    in_use = sum(w["state"] == "live" for r in inv for w in r.get("worktrees") or [])
    names = ", ".join(sorted(row["name"] or Path(row["cwd"]).name for row in rec.get("sessions") or []))
    lines.append(f"- {in_use} worktrees in use, left alone. Live sessions: {names or 'none'}.")
    lines += ["", "## Writing", "",
              f"{rec['recap']['commits']} commits and {rec['recap']['prs_merged']} merged PRs this week. "
              f"Drafted {len(rec.get('posts') or [])} posts to review under `posts/` in this run's folder."]
    if rec.get("drafts"):
        lines += ["", "Older drafts still unpublished in `pages/posts/`:", "", *[f"- `{d}`" for d in rec["drafts"]]]
    if b:
        lines += ["", "## Backlog", "", f"{b['open_items']} open items, {b['on_board']} on the Fleet project, {b['findings']} PM findings.",
                  "", "Roadmap: " + ", ".join(f"{v} {k}" for k, v in sorted(b["roadmap"].items()))]
    if plan:
        lines += ["", f"## The plan for {rec['week']}", "", f"Ranked {plan['ranked']} open items; {plan['held']} are held.", ""]
        for lane in LANES:
            rows = plan["lanes"][lane]
            if rows:
                lines += [f"### {LANE_TITLES[lane]} ({plan['by_lane'][lane]} in the lane)", ""]
                lines += [f"- [{r['ref']}]({r['url']}): {r['title']} ({', '.join(r['reasons'])})" for r in rows]
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---- confirm: the only external writes -------------------------------------------------------

def push_wip(row: dict, cfg: dict) -> str:
    """Mirror one local branch at `wip/…`. The tip gets an empty [skip ci] commit so the push wakes no
    workflow; the local branch is untouched. Refuses anything outside the prefix."""
    repo, prefix = Path(row["path"]), cfg["wip_prefix"].rstrip("/")
    ref = f"refs/heads/{prefix}/{row['branch']}"
    if not ref.startswith("refs/heads/wip/"):
        return f"refused: {ref} is outside wip/"
    if row.get("blocked"):
        return "held: looks like it holds a secret"
    if out(repo, "rev-parse", "-q", "--verify", f"refs/heads/{row['branch']}") != row["tip"]:
        return "skipped: the branch moved since the review"
    remote = (out(repo, "ls-remote", "origin", ref).split() or [""])[0]
    if remote and yes(repo, "fetch", "-q", "origin", ref) and out(repo, "rev-parse", "-q", "--verify", f"{remote}^") == row["tip"]:
        return "already saved"
    who = cfg["commit"]
    env = {**ENV, "GIT_AUTHOR_NAME": who["name"], "GIT_AUTHOR_EMAIL": who["email"],
           "GIT_COMMITTER_NAME": who["name"], "GIT_COMMITTER_EMAIL": who["email"]}
    tree = out(repo, "rev-parse", f"{row['tip']}^{{tree}}")
    made = git(repo, "commit-tree", tree, "-p", row["tip"], "-m",
               f"chore(wip): weekly save of {row['branch']} [skip ci]", env=env)
    if made.returncode != 0:
        return f"failed: {made.stderr.strip()[:160]}"
    pushed = git(repo, "push", "-q", f"--force-with-lease={ref}:{remote}", "origin", f"{made.stdout.strip()}:{ref}", timeout=300)
    return "pushed" if pushed.returncode == 0 else f"failed: {pushed.stderr.strip()[:200]}"


def next_batches(plan_file: Path, done: list[int], limit: int) -> list[int]:
    try:
        indexes = [b["index"] for b in json.loads(plan_file.read_text()).get("batches") or []]
    except (OSError, json.JSONDecodeError):
        return []
    return [i for i in indexes if i not in done][:limit]


def apply_board(root: Path, batches: list[int]) -> list[dict]:
    """The § 11 service does the writing: same flag, confirm, stale-plan refusal, caps and audit.
    Only a batch that exited 0 counts as done; the first failure stops the rest."""
    env = {**ENV, "HARNESS_PROJECTS_WRITES": "1"}
    plan = str(root / ".fleet" / "pm" / "board-plan.json")
    results = []
    for index in batches:
        r = run([sys.executable, str(root / "tools" / "projects_backfill.py"), "apply", plan, "--confirm",
                 "--batch", str(index)], cwd=root, timeout=600, env=env)
        text = (r.stdout or r.stderr).strip()
        results.append({"index": index, "ok": r.returncode == 0, "note": text.splitlines()[-1][:200] if text else f"batch {index}: no output"})
        if r.returncode != 0:
            break
    return results


def snapshot_doc(rec: dict, previous: dict | None, cfg: dict) -> dict:
    b, s, recap = rec.get("backlog") or {}, rec["state"], rec["recap"]
    entry = {"week": rec["week"], "commits": recap["commits"], "prs_merged": recap["prs_merged"],
             "open_items": b.get("open_items", 0), "on_board": b.get("on_board", 0), "local_only": s["local_only"]}
    history = [h for h in (previous or {}).get("history") or [] if h.get("week") != rec["week"]]
    plan = rec.get("plan") or {"lanes": {}}
    return {
        "schema": PLAN_SCHEMA, "week": rec["week"], "generated_at": rec["finished"], "recap": recap, "state": s,
        "backlog": b,
        "plan": {lane: [{k: r[k] for k in ("ref", "title", "url", "priority", "reasons")} for r in plan["lanes"].get(lane) or []]
                 for lane in LANES},
        "history": (history + [entry])[-int(cfg["history_weeks"]):],
    }


def on_main(root: Path, rel: str) -> str | None:
    """A file as `origin/main` holds it, or None if it holds no such file. The PR must never carry the
    checkout's uncommitted edits, and a stale checkout must never revert what has landed since."""
    if not strict(root, "ls-tree", "origin/main", "--", rel):
        return None
    r = git(root, "show", f"origin/main:{rel}")
    if r.returncode != 0:
        raise GitError(f"git show: {r.stderr.strip()[:160]}")
    return r.stdout


def weekly_pr_files(root: Path, rec: dict, folder: Path, cfg: dict, keep_drafts: bool, publish: list[str]) -> dict[str, str]:
    """Every file the weekly PR writes, by path, built on `origin/main`. Writes nothing."""
    import work_queue as wq
    files: dict[str, str] = {}
    for name in rec.get("posts") or []:
        if on_main(root, f"pages/posts/{name}") is None:  # never overwrite a post that has landed
            files[f"pages/posts/{name}"] = finalize_post((folder / "posts" / name).read_text(), keep_drafts)
    for name in publish:
        text = on_main(root, f"pages/posts/{name}")
        if text is None:
            raise SystemExit(f"weekly: {name} is not in pages/posts/ on origin/main")
        files[f"pages/posts/{name}"] = finalize_post(text, False)
    text = on_main(root, SNAPSHOT)
    previous = yaml.safe_load(text) if text else None
    head = "# GENERATED by tools/weekly.py (docs/WEEKLY.md). Edit the generator, not this file.\n"
    files[SNAPSHOT] = head + yaml.safe_dump(snapshot_doc(rec, previous, cfg), sort_keys=False, allow_unicode=True)
    text = on_main(root, QUEUE)
    if rec.get("plan") and text is not None:
        doc, _ = wq.normalize(yaml.safe_load(text))
        today = rec["started"][:10]
        files[QUEUE] = wq.dump(proposed_queue(doc, rec["plan"], set(rec.get("open_keys") or []), set(rec.get("pinned") or []),
                                              rec["week"], today))
    _, review = pm_files(root)
    edits = (review or {}).get("roadmap_edits") or []
    text = on_main(root, ROADMAP)
    if edits and text is not None:
        import pm_review
        result = text
        for edit in edits:  # an edit for an entry main no longer has is stale, not fatal
            with contextlib.suppress(ValueError):
                result = pm_review.apply_roadmap_edits(result, [edit])
        if result != text:
            files[ROADMAP] = result
    return files


def open_weekly_pr(root: Path, rec: dict, files: dict[str, str], cfg: dict) -> str:
    """Commit on a detached throwaway worktree and push a branch unique to this run, without force. No
    local branch is made or deleted, so nothing of the maintainer's can be overwritten."""
    stamp = rec["id"].split("-", 1)[0].lower()
    branch = f"chore/weekly-{rec['week'].lower()}-{stamp}"
    ref = f"refs/heads/{branch}"
    who = cfg["commit"]
    title = f"chore(weekly): recap and plan going into {rec['week']}"
    nwo = nwo_of(root)
    mine = out(root, "ls-remote", "origin", ref)
    other = run(["gh", "pr", "list", "--repo", nwo or "", "--state", "open", "--search", f'"{title}" in:title',
                 "--json", "url", "--jq", ".[0].url // empty"], timeout=30).stdout.strip()
    if other and not mine:
        return f"skipped: {other} is already open for {rec['week']}; merge or close it first"
    if not mine:
        with tempfile.TemporaryDirectory(prefix="weekly-pr-") as tmp:
            tree = Path(tmp) / "hub"
            added = git(root, "worktree", "add", "-q", "--detach", str(tree), "origin/main", timeout=180)
            if added.returncode != 0:
                return f"failed: {added.stderr.strip()[:200]}"
            try:
                for rel, text in files.items():
                    (tree / rel).parent.mkdir(parents=True, exist_ok=True)
                    (tree / rel).write_text(text)
                git(tree, "add", "--", *files)
                made = git(tree, "-c", f"user.name={who['name']}", "-c", f"user.email={who['email']}", "commit", "-q", "-m", title)
                if made.returncode != 0:
                    return f"failed: {(made.stderr or made.stdout).strip()[:200]}"
                pushed = git(tree, "push", "-q", "origin", f"HEAD:{ref}", timeout=180)
                if pushed.returncode != 0:
                    return f"failed: {pushed.stderr.strip()[:200]}"
            finally:
                git(root, "worktree", "remove", "--force", str(tree))
    body = ("The week's record: the retro, the chronicles, the plan and the state snapshot "
            "(docs/WEEKLY.md). Merging this publishes the posts (constitution § 23.4) and "
            f"makes the plan the order the loops read.\n\nRun `{rec['id']}`.")
    pr = run(["gh", "pr", "create", "--repo", nwo or "", "--base", "main", "--head", branch, "--title", title, "--body", body], timeout=60)
    if pr.returncode == 0:
        return pr.stdout.strip()
    existing = run(["gh", "pr", "view", branch, "--repo", nwo or "", "--json", "url", "--jq", ".url"], timeout=30)
    return existing.stdout.strip() or f"failed: {pr.stderr.strip()[:200]}"


def cmd_confirm(args: argparse.Namespace, root: Path, state_dir: Path, now: datetime | None = None) -> int:
    cfg = load_config(load_fleet(root))
    rows = run_dirs(state_dir)
    if not rows:
        print("weekly: no run to confirm yet", file=sys.stderr)
        return 1
    folder = rows[-1]
    rec = read_run(folder)
    age = ((now or now_utc()) - datetime.fromisoformat(rec["started"])).days
    if age > int(cfg["confirm"]["max_age_days"]):
        print(f"weekly: refused, run {rec['id']} is {age} days old; run it again", file=sys.stderr)
        return 1
    for w in rec.get("wip") or []:
        unscanned = any(hit.startswith("(") or hit.endswith("(could not be read)") for hit in w.get("blocked") or [])
        if f"{w['repo']}:{w['branch']}" in args.allow and not unscanned:
            w["blocked"] = []  # the maintainer read the hit and typed exactly this repo and branch
    wip = [w for w in rec.get("wip") or [] if not w.get("blocked")]
    held = [w for w in rec.get("wip") or [] if w.get("blocked")]
    state_file = folder / "confirm.json"
    progress = json.loads(state_file.read_text()) if state_file.exists() else {"batches": [], "wip": {}, "pr": None}
    plan_file = root / ".fleet" / "pm" / "board-plan.json"
    git(root, "fetch", "-q", "origin", "main")
    batches = next_batches(plan_file, progress["batches"], int(cfg["confirm"]["board_batches"]))
    try:
        files = weekly_pr_files(root, rec, folder, cfg, args.keep_drafts, args.publish)
    except GitError as exc:
        print(f"weekly: refused, origin/main could not be read: {exc}", file=sys.stderr)
        return 1
    print(f"Run {rec['id']} ({rec['mode']}).\n\nPush to {cfg['wip_prefix']}/: {len(wip)} branches")
    for w in wip:
        print(f"  {w['repo']} {w['branch']} ({w['commits']} commits)")
    for w in held:
        unscanned = any(hit.startswith("(") or hit.endswith("(could not be read)") for hit in w["blocked"])
        how = "it could not be scanned, so it stays local" if unscanned else f"read it, then --allow {w['repo']}:{w['branch']}"
        print(f"  HELD {w['repo']} {w['branch']}: {'; '.join(w['blocked'][:3])} ({how})")
    print(f"\nFleet project: batches {batches or 'none left'} of {plan_file}\n\nWeekly PR: {len(files)} files")
    for rel in sorted(files):
        print(f"  {rel}")
    print(f"\nRead first: {folder / 'report.md'} and {folder / 'posts'}/")
    if not args.apply:
        print("\nDry run: nothing was pushed, applied or opened. `--apply` is your yes.")
        return 0
    failed = 0
    for w in wip:
        key = f"{w['repo']}:{w['branch']}"
        if str(progress["wip"].get(key, "")).startswith(("pushed", "already")):
            continue
        result = push_wip(w, cfg)
        progress["wip"][key] = result
        failed += result.startswith(("failed", "refused"))
        print(f"{key}: {result}")
    for row in apply_board(root, batches):
        print(row["note"])
        if row["ok"]:
            progress["batches"].append(row["index"])
        else:
            failed += 1
    if not progress["pr"]:
        result = open_weekly_pr(root, rec, files, cfg)
        print(f"Weekly PR: {result}")
        if result.startswith("failed"):
            failed += 1
        else:
            progress["pr"] = result
    state_file.write_text(json.dumps(progress, indent=1) + "\n")
    left = next_batches(plan_file, progress["batches"], 10 ** 6)
    if left:
        print(f"{len(left)} board batches left (200 ops an hour): run confirm --apply again after the hour.")
    return 1 if failed else 0


def cmd_status(state_dir: Path) -> int:
    rows = run_dirs(state_dir)
    if not rows:
        print("weekly: no runs yet")
        return 0
    rec = read_run(rows[-1])
    s = rec.get("state") or {}
    print(f"{rec['id']}: {rec['mode']}, {s.get('on_main', 0)}/{s.get('repos', 0)} repos on main, "
          f"{s.get('local_only', 0)} local-only branches, {s.get('uncommitted', 0)} with uncommitted work")
    print(f"report: {rows[-1] / 'report.md'}")
    return 0


def cmd_inventory(args: argparse.Namespace, root: Path) -> int:
    cfg = load_config(load_fleet(root))
    live = live_state()
    inv = inventory(root, cfg, live, offline=args.offline)
    if args.json:
        print(json.dumps(inv, indent=1, default=str))
        return 0
    s, plan = state_summary(inv, live), removals(inv)
    print(json.dumps(s, indent=1))
    print(f"removable: {len(plan['branches'])} merged branches, {len(plan['worktrees'])} dead worktrees")
    for w in wip_candidates(inv):
        print(f"local-only: {w['repo']} {w['branch']} ({w['commits']} commits)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "the weekly routine (docs/WEEKLY.md)")
    parser.add_argument("--root", default=str(ROOT), help="the hub checkout to work on")
    parser.add_argument("--state-dir", default=None, help="run folders (default: <root>/.fleet/weekly)")
    parser.add_argument("--archive", default=None, help="the archive (default: fleet.yml weekly.archive_dir)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="the routine; bare it is a preview that changes no repo")
    how = r.add_mutually_exclusive_group()
    how.add_argument("--scheduled", action="store_true", help="the LaunchAgent's mode: honours the switch and report-only runs")
    how.add_argument("--apply", action="store_true", help="refresh and tidy now, typed by the maintainer")
    r.add_argument("--offline", action="store_true", help="no fetch and no GitHub reads")
    r.add_argument("--no-plan", action="store_true", help="skip the PM review and the ranking")
    i = sub.add_parser("inventory", help="read-only: what the routine sees")
    i.add_argument("--json", action="store_true")
    i.add_argument("--offline", action="store_true")
    c = sub.add_parser("confirm", help="show the external writes; --apply is the maintainer's yes")
    c.add_argument("--apply", action="store_true")
    c.add_argument("--keep-drafts", action="store_true", help="land the week's posts as drafts")
    c.add_argument("--publish", action="append", default=[], metavar="FILE", help="also publish an older draft in pages/posts/")
    c.add_argument("--allow", action="append", default=[], metavar="REPO:BRANCH", help="push one held branch, after reading what the scan found")
    sub.add_parser("status", help="the latest run's headline")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    state_dir = Path(args.state_dir).resolve() if args.state_dir else root / ".fleet" / "weekly"
    if args.cmd == "status":
        return cmd_status(state_dir)
    if args.cmd == "inventory":
        return cmd_inventory(args, root)
    if args.cmd == "confirm":
        return cmd_confirm(args, root, state_dir)
    # absolute: every git call runs with -C in a repo, so a relative path would land inside each one
    archive = expand(args.archive or load_config(load_fleet(root))["archive_dir"]).resolve()
    return cmd_run(args, root, state_dir, archive)


if __name__ == "__main__":
    sys.exit(main())

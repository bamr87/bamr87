#!/usr/bin/env python3
"""
File: tools/uplift.py
Purpose: FLEET UPLIFT — the hub's inbound arc (docs/UPLIFT.md).

The hub already pushes OUT (kits through tools/fanout.sh, the backlog fan-out)
and works INSIDE one repo (the scout, the evolution loop). Nothing carried an
improvement one repo made back UP to the hub so the others could get it. This
reads what every fleet repo did on its default branch and answers one question
from file contents, with no model and no GitHub call:

    a repo changed a file. Which other repos still hold a version of that
    file the repo held before its change?

A byte-identical earlier version means the same change applies there without
adaptation. From that one comparison every change in the window is one of:

  candidate  one or two repos hold the new content and others hold an earlier
             version: one repo's own improvement, not yet anywhere else
  rollout    the new content is the hub's own source, came in on a fan-out
             branch, or is already held by `rollout_min` repos: a deployment
             in flight, listed with who is still behind
  fork       `fork_min` repos took the same earlier version to different
             contents: a seed each repo fills in, not one fix
  local      nobody else holds an earlier version: the repo's own business

A candidate carries its ROUTE. `kit`: the earlier version is a hub source or
carries a kit stamp, so the change is made once in the kit and fanned out.
`patch`: the hub owns no source for it, so the same patch goes to each repo.

A second lane reads each repo's feature index (features/features.yml) at the
start of the window and now, and lists what was declared or shipped.

`file` turns a candidate into a hub issue for the issue pipeline: a preview
first, and `--apply`, typed by a person, files exactly the previewed bytes.
A repo less visible than the hub is never filed from, and a body that holds a
credential-shaped string is withheld.

Reads: local git only (each submodule checkout's origin/<branch>, as of its
last fetch). Writes: .fleet/uplift/ (ephemeral). `file --apply` is the one
GitHub write, on the hub, capped.

Usage:
  python3 tools/uplift.py scan [--days N] [--repo NAME ...] [--json]
  python3 tools/uplift.py show KEY
  python3 tools/uplift.py brief [KEY ...] [--top N] [--out FILE]
  python3 tools/uplift.py file KEY [KEY ...] [--apply]
  python3 tools/uplift.py status
  (also `tools/dash uplift …`)
Dependencies: Python 3.12 stdlib + PyYAML; git; gh only for `file`.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
SCHEMA = "fleet-uplift/v1"
KEY_PREFIX = "u-"
#: git's hash of an empty file: every repo's empty `__init__.py` shares it, so it proves nothing
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
DELETED = "deleted"
REGULAR_MODES = ("100644", "100755")
LOG_FORMAT = "%x1e%H%x1f%an%x1f%cI%x1f%s%x1f%b%x1d"
MERGE_RX = re.compile(r"^Merge pull request #(\d+) from ([^/\s]+)/(\S+)")
SQUASH_RX = re.compile(r"\(#(\d+)\)\s*$")
KIT_RX = re.compile(r"(?:#|//|<!--)\s*kit:\s*([a-z][a-z0-9-]*)\s+v([0-9][0-9A-Za-z.]*)")
FANOUT_BRANCH_RX = re.compile(r'^\s+BRANCH="([^"$]+)"', re.M)
#: a body holding one of these is withheld, never filed (the scout's filer uses the same shapes)
CREDENTIAL_RX = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")
LABEL_COLOR, LABEL_TEXT = "0E8A16", "Captured by the fleet uplift scan: one repo's improvement others still lack"

DEFAULTS: dict = {
    "days": 14,
    "rollout_min": 3,
    "fork_min": 3,
    "stale_days": 3,
    "max_rows": 40,
    "diff_lines": 120,
    "hub_sources": ["templates/", ".editorconfig", "tools/unwrap-prose.py", "tools/schema_lint.py",
                    "tools/docs_index.py"],
    "ignore_paths": ["CHANGELOG.md", "*/CHANGELOG.md", ".release-please-manifest.json",
                     "*/.release-please-manifest.json", "*.lock", "*package-lock.json", "*pnpm-lock.yaml"],
    "ignore_authors": ["dependabot[bot]", "github-actions[bot]", "github-actions", "GitHub Action",
                       "renovate[bot]", "release-please[bot]"],
    "ignore_subjects": [r"^chore\(main\): release", r"^chore: release", r"release-please--branches--",
                        r"^chore\(submodule\)", r"^chore\(jev\)"],
    "rollout_branches": ["chore/governance-baseline", "chore/root-tidy", "backlog/", "ci/verify-kit-",
                         "chore/kit-"],
    "rollout_subjects": [r"\badopt(s|ed)? the .+ kit\b", r"\(kit v\d", r"\bkit v\d+\.\d+",
                         r"\badopt standardization baseline\b", r"\badopt Pyramid Schema\b"],
    "features": {"files": ["features/features.yml"], "max_rows": 40},
    "file": {"label": "uplift", "marker": "fleet-uplift", "max_per_run": 3, "max_open": 10, "hold": False},
}


class UpliftError(Exception):
    """A refusal the caller prints: a bad key, a config that does not load, a git read that failed."""


# ----------------------------------------------------------------------- config
def merged(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merged(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_config(hub: Path) -> tuple[dict, dict]:
    """→ (the `uplift:` settings over the defaults, the whole fleet.yml)."""
    fleet = load_yaml(hub / "_data" / "fleet.yml") or {}
    if not isinstance(fleet, dict):
        raise UpliftError("_data/fleet.yml is not a mapping")
    block = fleet.get("uplift")
    if block is not None and not isinstance(block, dict):
        raise UpliftError("_data/fleet.yml `uplift:` is not a mapping")
    cfg = merged(DEFAULTS, block)
    unknown = sorted(set(block or {}) - set(DEFAULTS))
    if unknown:
        raise UpliftError(f"_data/fleet.yml `uplift:` has unknown keys: {', '.join(unknown)}")
    for key in ("days", "rollout_min", "fork_min", "stale_days", "max_rows", "diff_lines"):
        if not isinstance(cfg[key], int) or isinstance(cfg[key], bool) or cfg[key] < 1:
            raise UpliftError(f"_data/fleet.yml `uplift.{key}` must be a whole number of 1 or more")
    return cfg, fleet


# -------------------------------------------------------------------------- git
def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(repo), *args],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        if check:
            last = (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1]
            raise UpliftError(f"git {args[0]} failed in {repo.name}: {last}")
        return ""
    return proc.stdout


def blob_bytes(repo: Path, sha: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", sha], capture_output=True)
    if proc.returncode != 0:
        raise UpliftError(f"git cat-file failed in {repo.name} for {sha[:10]}")
    return proc.stdout


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def main_checkout(hub: Path) -> Path:
    """The checkout that owns the submodules: a linked worktree's own `projects/` is empty."""
    common = git(hub, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).strip()
    return Path(common).parent if common else hub


def default_projects_dir(hub: Path) -> Path:
    env = os.environ.get("UPLIFT_PROJECTS")
    if env:
        return Path(env).expanduser()
    here = hub / "projects"
    if here.is_dir() and any((p / ".git").exists() for p in here.iterdir()):
        return here
    return main_checkout(hub) / "projects"


# ------------------------------------------------------------------------ model
@dataclass
class Commit:
    sha: str
    author: str
    date: str
    subject: str
    title: str                      # the pull request's title for a merge commit, else the subject
    pr: int | None
    branch: str | None              # the head branch a merge commit names
    changes: list[tuple[str, str, str | None, str | None]]   # (status, path, pre blob, post blob)
    ignored: bool = False
    fanout: bool = False


@dataclass
class Repo:
    target: str                     # the name under projects/ and what tools/fanout.sh --target takes
    nwo: str
    path: Path
    branch: str
    is_hub: bool = False
    read: bool = False
    reason: str = ""
    head: str = ""
    fetched_at: str | None = None
    tree: dict[str, str] = field(default_factory=dict)
    commits: list[Commit] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"origin/{self.branch}"


@dataclass
class Move:
    """One repo took one path from earlier versions to what it holds now."""
    repo: Repo
    path: str
    ancestors: list[str]            # oldest first
    post: str | None                # None: the repo deleted the file
    commits: list[Commit]


def nwo_of(url: str) -> str | None:
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def load_fleet(hub: Path, projects: Path, fleet: dict) -> tuple[list[Repo], list[dict]]:
    """The repos uplift compares: the hub itself and every registry submodule a
    fleet owner owns that is not archived. → (members, the rows left out and why)."""
    hub_cfg = fleet.get("hub") or {}
    owners = set(hub_cfg.get("owners") or ["bamr87"])
    registry = load_yaml(hub / "_data" / "projects.yml") or []
    rows = registry.get("projects", []) if isinstance(registry, dict) else registry
    members: list[Repo] = []
    skipped: list[dict] = []
    hub_nwo = hub_cfg.get("repo")
    if hub_nwo:
        # The registry lists submodules only; a tool that walks it alone would leave the hub out.
        members.append(Repo(target=hub_nwo.split("/", 1)[1], nwo=hub_nwo, path=hub,
                            branch=hub_cfg.get("default_branch") or "main", is_hub=True))
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("submodule_path"):
            continue
        target = Path(row["submodule_path"]).name
        nwo = nwo_of(row.get("repo_url") or "")
        if not nwo:
            skipped.append({"repo": target, "why": "no GitHub URL in the registry"})
        elif nwo.split("/", 1)[0] not in owners:
            skipped.append({"repo": target, "why": f"external upstream ({nwo})"})
        elif row.get("status") == "archived":
            skipped.append({"repo": target, "why": "archived"})
        else:
            members.append(Repo(target=target, nwo=nwo, path=projects / target, branch=row.get("branch") or "main"))
    return members, skipped


def matches(patterns: list[str], text: str) -> bool:
    return any(fnmatch.fnmatchcase(text, p) for p in patterns)


def parse_log(out: str) -> list[Commit]:
    commits: list[Commit] = []
    for chunk in out.split("\x1e")[1:]:
        head, _, raw = chunk.partition("\x1d")
        parts = head.split("\x1f", 4)
        if len(parts) < 5:
            continue
        sha, author, date, subject, body = parts
        changes: list[tuple[str, str, str | None, str | None]] = []
        for line in raw.splitlines():
            if not line.startswith(":"):
                continue
            meta, _, path = line.partition("\t")
            f = meta.split()
            if len(f) < 5 or not path or "\t" in path:
                continue                                   # a rename (two paths) moved the file; it is neither an edit nor a deletion
            old_mode, new_mode, pre, post, status = f[0][1:], f[1], f[2], f[3], f[4][0]
            if status == "A" and new_mode in REGULAR_MODES:
                changes.append(("A", path, None, post))
            elif status == "D" and old_mode in REGULAR_MODES:
                changes.append(("D", path, pre, None))
            elif status == "M" and old_mode in REGULAR_MODES and new_mode in REGULAR_MODES:
                changes.append(("M", path, pre, post))
        merge = MERGE_RX.match(subject)
        squash = SQUASH_RX.search(subject)
        title = subject
        if merge:
            title = next((ln.strip() for ln in body.splitlines() if ln.strip()), subject)
        commits.append(Commit(sha=sha, author=author, date=date, subject=subject, title=title,
                              pr=int(merge.group(1)) if merge else int(squash.group(1)) if squash else None,
                              branch=merge.group(3) if merge else None, changes=changes))
    return commits


def fanout_branches(hub: Path, cfg: dict) -> tuple[set[str], list[str]]:
    """→ (the exact branches tools/fanout.sh pushes its kits on, the configured prefixes)."""
    script = hub / "tools" / "fanout.sh"
    exact = set(FANOUT_BRANCH_RX.findall(script.read_text(encoding="utf-8"))) if script.is_file() else set()
    return exact, list(cfg["rollout_branches"])


def read_repo(repo: Repo, since: str, cfg: dict, branches: tuple[set[str], list[str]]) -> None:
    """Fill `repo` from its checkout: the tree it holds now and the window's commits.
    A repo that cannot be read is marked so; it is never reported as quiet."""
    if not (repo.path / ".git").exists():
        repo.reason = "no checkout"
        return
    head = git(repo.path, "rev-parse", "-q", "--verify", f"{repo.ref}^{{commit}}", check=False).strip()
    if not head:
        repo.reason = f"no {repo.ref}"
        return
    repo.head = head
    gitdir = git(repo.path, "rev-parse", "--absolute-git-dir", check=False).strip()
    fetch_head = Path(gitdir) / "FETCH_HEAD" if gitdir else None
    if fetch_head and fetch_head.is_file():
        repo.fetched_at = dt.datetime.fromtimestamp(fetch_head.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
    try:
        for line in git(repo.path, "ls-tree", "-r", repo.ref).splitlines():
            meta, _, path = line.partition("\t")
            f = meta.split()
            if len(f) == 3 and f[1] == "blob" and f[0] in REGULAR_MODES:
                repo.tree[path] = f[2]
        out = git(repo.path, "log", "--first-parent", "--diff-merges=first-parent", f"--since={since}",
                  "--raw", "--no-abbrev", "-M", f"--format={LOG_FORMAT}", repo.ref)
    except UpliftError as exc:
        repo.reason = str(exc)
        repo.tree.clear()
        return
    exact, prefixes = branches
    subjects = [re.compile(p) for p in cfg["ignore_subjects"]]
    bots = {a.lower() for a in cfg["ignore_authors"]}
    rollouts = [re.compile(p, re.I) for p in cfg["rollout_subjects"]]
    for c in parse_log(out):
        texts = (c.subject, c.title)
        # an author is matched whole: `dependabot[bot]` as a glob would be a character class, and match nothing
        c.ignored = c.author.lower() in bots or any(rx.search(t) for rx in subjects for t in texts)
        c.fanout = (bool(c.branch) and (c.branch in exact or any(c.branch.startswith(p) for p in prefixes))) \
            or any(rx.search(t) for rx in rollouts for t in texts)
        repo.commits.append(c)
    repo.read = True


def moves_of(repo: Repo, cfg: dict) -> list[Move]:
    """Every path the repo changed in the window, as one net move per path: the
    versions it held (oldest first) and what it holds now. A path that came
    back to where it started, or that only ignored commits touched, is no move."""
    chains: dict[str, list[str | None]] = {}
    touched: dict[str, list[Commit]] = {}
    for c in reversed(repo.commits):                       # oldest first
        for status, path, pre, post in c.changes:
            if matches(cfg["ignore_paths"], path):
                continue
            if status == "A" and path not in chains:
                continue                                   # a new file has no earlier version to be behind on
            chain = chains.setdefault(path, [pre])
            chain.append(post)
            if not c.ignored:
                touched.setdefault(path, []).append(c)
    out: list[Move] = []
    for path, chain in chains.items():
        if path not in touched:
            continue
        now = repo.tree.get(path)
        if chain[0] == now:
            continue                                       # back where it started: nothing changed for this repo
        seen: list[str] = []
        for sha in chain[:-1]:
            if sha and sha != now and sha != EMPTY_BLOB and sha not in seen:
                seen.append(sha)
        if seen:
            out.append(Move(repo=repo, path=path, ancestors=seen, post=now, commits=touched[path]))
    return out


def hub_source_blobs(hub_repo: Repo | None, cfg: dict) -> dict[str, str]:
    """blob → the hub path that holds it, for the paths the hub fans out from."""
    if not hub_repo or not hub_repo.read:
        return {}
    out: dict[str, str] = {}
    for path, sha in sorted(hub_repo.tree.items()):
        if sha != EMPTY_BLOB and any(path == p or (p.endswith("/") and path.startswith(p)) for p in cfg["hub_sources"]):
            out.setdefault(sha, path)
    return out


def change_key(path: str, post: str | None) -> str:
    return KEY_PREFIX + hashlib.sha256(f"{path}\0{post or DELETED}".encode()).hexdigest()[:10]


def commit_url(nwo: str, c: Commit) -> str:
    return f"https://github.com/{nwo}/pull/{c.pr}" if c.pr else f"https://github.com/{nwo}/commit/{c.sha}"


def kit_stamp(repo: Repo, sha: str) -> tuple[str, str] | None:
    try:
        data = blob_bytes(repo.path, sha)[:4096]
    except UpliftError:
        return None
    m = None if is_binary(data) else KIT_RX.search(data.decode("utf-8", "replace"))
    return (m.group(1), m.group(2)) if m else None


def analyze(members: list[Repo], cfg: dict) -> dict:
    """Classify every move of the window against what every repo holds now."""
    read = [r for r in members if r.read]
    hub_repo = next((r for r in read if r.is_hub), None)
    hub_blobs = hub_source_blobs(hub_repo, cfg)
    groups: dict[tuple[str, str | None], list[Move]] = {}
    for repo in read:
        for move in moves_of(repo, cfg):
            groups.setdefault((move.path, move.post), []).append(move)
    stats: dict[tuple[str, str | None], dict] = {}
    for (path, post), moves in groups.items():
        origins = sorted({m.repo.target for m in moves})
        ancestors: list[str] = []
        for move in moves:
            ancestors += [a for a in move.ancestors if a not in ancestors]
        holders = sorted(r.target for r in read if r.tree.get(path) == post) if post else list(origins)
        behind = {r.target: r.tree[path] for r in read if r.target not in origins and r.tree.get(path) in ancestors}
        primary = max(moves, key=lambda m: (m.commits[-1].date, m.repo.target))
        rollout = (bool(post and post in hub_blobs) or all(c.fanout for m in moves for c in m.commits)
                   or len(holders) >= cfg["rollout_min"])
        was = now = None
        # the diff is taken from the earlier version most repos behind hold (the newest of them on a tie): after a
        # kit upgrade and an edit on top, that is the upgrade, so the diff is the edit alone
        held = list(behind.values())
        base = max(reversed(primary.ancestors), key=held.count)
        if behind:                               # only what will be reported is opened
            # the stamp of the version just before this one: a stamp that is new or newer since then is the hub's
            # kit arriving (the repo took an upgrade, it wrote nothing); the same stamp is the repo's own edit
            was = kit_stamp(primary.repo, primary.ancestors[-1])
            now = kit_stamp(primary.repo, post) if post else None
            rollout = rollout or bool(now and now != was)
        stats[(path, post)] = {
            "origins": origins, "ancestors": ancestors, "holders": holders, "behind": behind, "primary": primary,
            "base": base,
            "diverged": sum(1 for r in read if path in r.tree and r.tree[path] != post and r.tree[path] not in ancestors),
            "rollout": rollout, "kit": now if rollout else was,
        }
    # the distinct contents each earlier version was taken to by a repo on its own (a rollout's content is not a
    # competing variant): `fork_min` of them is a seed each repo fills in
    posts_of: dict[tuple[str, str], set[str | None]] = {}
    for (path, post), st in stats.items():
        if not st["rollout"]:
            for sha in st["ancestors"]:
                posts_of.setdefault((path, sha), set()).add(post)
    changes: list[dict] = []
    for (path, post), moves in groups.items():
        st = stats[(path, post)]
        ancestors, holders, behind, diverged = (st[k] for k in ("ancestors", "holders", "behind", "diverged"))
        variants = max((len(posts_of.get((path, a), ())) for a in ancestors), default=0)
        if st["rollout"]:
            kind = "rollout" if behind else "landed"
        elif not behind:
            kind = "local"
        elif variants >= cfg["fork_min"]:
            kind = "fork"
        else:
            kind = "candidate"
        primary, stamp = st["primary"], st["kit"]
        last = primary.commits[-1]
        entry = {
            "key": change_key(path, post), "path": path, "action": "edit" if post else "delete", "class": kind,
            "origins": [{"repo": m.repo.target, "nwo": m.repo.nwo, "commit": m.commits[-1].sha,
                         "date": m.commits[-1].date, "title": m.commits[-1].title, "pr": m.commits[-1].pr,
                         "url": commit_url(m.repo.nwo, m.commits[-1]), "author": m.commits[-1].author,
                         "commits": len(m.commits)}
                        for m in sorted(moves, key=lambda m: m.repo.target)],
            "behind": sorted(behind), "behind_holds": behind, "holders": holders, "diverged": diverged,
            "variants": variants, "post": post, "ancestors": ancestors,
            "from": {"repo": primary.repo.target, "nwo": primary.repo.nwo, "base": st["base"],
                     "date": last.date, "title": last.title, "url": commit_url(primary.repo.nwo, last)},
            "route": None, "kit": {"name": stamp[0], "version": stamp[1]} if stamp else None, "hub_source": None,
        }
        if kind in ("candidate", "rollout"):
            entry["hub_source"] = next((hub_blobs[a] for a in ancestors if a in hub_blobs), None)
        if kind == "candidate":
            entry["route"] = "kit" if entry["hub_source"] or stamp else "patch"
        changes.append(entry)
    order = lambda e: (-len(e["behind"]), e["path"], e["key"])  # noqa: E731
    by = {k: sorted((e for e in changes if e["class"] == k), key=order)
          for k in ("candidate", "rollout", "fork", "landed", "local")}
    forks: dict[str, dict] = {}
    for e in by["fork"]:
        row = forks.setdefault(e["path"], {"path": e["path"], "repos": [], "behind": set()})
        row["repos"] += [o["repo"] for o in e["origins"]]
        row["behind"] |= set(e["behind"])
    return {
        "candidates": by["candidate"], "rollouts": by["rollout"],
        "forks": sorted(({"path": f["path"], "variants": len(f["repos"]), "repos": sorted(f["repos"]),
                          "behind": sorted(f["behind"])} for f in forks.values()),
                        key=lambda f: (-len(f["behind"]), f["path"])),
        "counts": {"candidates": len(by["candidate"]), "rollouts": len(by["rollout"]), "forks": len(forks),
                   "landed": len(by["landed"]), "local": len(by["local"]), "moves": len(changes)},
    }


# --------------------------------------------------------------- feature lane
def feature_map(repo: Repo, sha: str) -> dict[str, dict] | None:
    try:
        data = yaml.safe_load(blob_bytes(repo.path, sha).decode("utf-8", "replace"))
    except (yaml.YAMLError, UpliftError):
        return None
    rows = data.get("features") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    return {str(f["id"]): f for f in rows if isinstance(f, dict) and f.get("id")}


def read_features(repo: Repo, since: str, cfg: dict) -> tuple[list[dict], list[dict]]:
    """→ (features declared or shipped in the window, indexes created or unreadable in it)."""
    rows: list[dict] = []
    notes: list[dict] = []
    base = git(repo.path, "rev-list", "-1", "--first-parent", f"--before={since}", repo.ref, check=False).strip()
    for rel in cfg["features"]["files"]:
        now_sha = repo.tree.get(rel)
        if not now_sha:
            continue
        was_sha = git(repo.path, "rev-parse", "-q", "--verify", f"{base}:{rel}", check=False).strip() if base else ""
        if was_sha == now_sha:
            continue
        now = feature_map(repo, now_sha)
        if now is None:
            notes.append({"repo": repo.target, "file": rel, "note": "unreadable"})
            continue
        was = feature_map(repo, was_sha) if was_sha else None
        if was is None:
            notes.append({"repo": repo.target, "file": rel, "note": "created", "features": len(now)})
            continue
        for fid, feat in now.items():
            status = str(feat.get("status") or "")
            if fid not in was:
                change = "new"
            elif status == "shipped" and str(was[fid].get("status") or "") != "shipped":
                change = "shipped"
            else:
                continue
            rows.append({"repo": repo.target, "nwo": repo.nwo, "id": fid, "change": change, "status": status,
                         "title": " ".join(str(feat.get("title") or "").split())[:160], "file": rel})
    return rows, notes


def split_fleet_wide(rows: list[dict], rollout_min: int) -> tuple[list[dict], list[dict]]:
    """A feature title that is new in `rollout_min` repos at once came from the hub (a kit added the entry to each):
    it is listed once, with its repos, and never as one repo's own feature."""
    by_title: dict[str, list[dict]] = {}
    for row in rows:
        by_title.setdefault(" ".join(row["title"].lower().split()), []).append(row)
    own: list[dict] = []
    wide: list[dict] = []
    for group in by_title.values():
        repos = sorted({r["repo"] for r in group})
        if len(repos) >= rollout_min:
            wide.append({"title": group[0]["title"], "repos": repos})
        else:
            own += group
    return own, sorted(wide, key=lambda w: (-len(w["repos"]), w["title"]))


# ------------------------------------------------------------------------- scan
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def scan(hub: Path, projects: Path, *, days: int | None = None, only: list[str] | None = None,
         now: dt.datetime | None = None) -> tuple[dict, list[Repo]]:
    cfg, fleet = load_config(hub)
    now = now or utcnow()
    days = days or cfg["days"]
    since = (now - dt.timedelta(days=days)).isoformat(timespec="seconds")
    members, skipped = load_fleet(hub, projects, fleet)
    known = {r.target for r in members}
    unknown = sorted(set(only or []) - known)
    if unknown:
        raise UpliftError(f"not a fleet repo: {', '.join(unknown)} (names are the folders under projects/)")
    branches = fanout_branches(hub, cfg)
    for repo in members:
        read_repo(repo, since, cfg, branches)
        if only and repo.target not in only:
            repo.commits = []                    # still compared against, never an origin
    result = analyze(members, cfg)
    features: list[dict] = []
    notes: list[dict] = []
    for repo in members:
        if repo.read and not repo.is_hub and (not only or repo.target in only):
            rows, extra = read_features(repo, since, cfg)
            features += rows
            notes += extra
    features, fleet_wide = split_fleet_wide(features, cfg["rollout_min"])
    stale_before = now - dt.timedelta(days=cfg["stale_days"])
    repos = []
    for r in members:
        stale = bool(r.read and not r.is_hub and r.fetched_at and dt.datetime.fromisoformat(r.fetched_at) < stale_before)
        repos.append({"repo": r.target, "nwo": r.nwo, "read": r.read, "reason": r.reason, "head": r.head,
                      "fetched_at": r.fetched_at, "stale": stale, "commits": len(r.commits)})
    doc = {
        "schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "since": since, "days": days,
        "hub": (fleet.get("hub") or {}).get("repo"), "projects": str(projects), "only": sorted(only or []),
        "repos": repos, "skipped": skipped,
        "counts": {**result["counts"], "repos": len(members), "read": sum(1 for r in members if r.read),
                   "commits": sum(len(r.commits) for r in members), "features": len(features)},
        "candidates": result["candidates"], "rollouts": result["rollouts"], "forks": result["forks"],
        "features": sorted(features, key=lambda f: (f["repo"], f["id"])), "feature_rollouts": fleet_wide,
        "feature_notes": notes,
    }
    return doc, members


def state_dir(hub: Path) -> Path:
    env = os.environ.get("UPLIFT_STATE")
    return Path(env).expanduser() if env else hub / ".fleet" / "uplift"


def save(doc: dict, hub: Path) -> Path:
    out = state_dir(hub)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "scan.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------- rendering
def day(iso: str) -> str:
    return iso[:10]


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def names(items: list[str], limit: int = 6) -> str:
    return ", ".join(items[:limit]) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def headline(doc: dict) -> str:
    c = doc["counts"]
    return (f"{c['candidates']} candidate(s) · {c['rollouts']} rollout(s) in flight · {c['forks']} forked file(s) · "
            f"{c['features']} feature(s) declared or shipped")


def render(doc: dict, cfg: dict) -> str:
    c = doc["counts"]
    scope = f" · origins limited to {', '.join(doc['only'])}" if doc["only"] else ""
    lines = [f"Fleet uplift — {doc['days']} days to {day(doc['generated_at'])} · {c['read']} of {c['repos']} repos read · "
             f"{c['commits']} commits{scope}", "  " + headline(doc), ""]
    limit = cfg["max_rows"]
    lines.append("CANDIDATES — one repo changed a file that other repos still hold in an earlier version")
    if not doc["candidates"]:
        lines.append("  none in this window")
    for e in doc["candidates"][:limit]:
        src = e["from"]
        other = f" · {e['variants']} repos changed it differently" if e["variants"] > 1 else ""
        lines.append(f"  {e['key']}  {len(e['behind']):>3} behind  {e['route']:<5}  {e['path']}"
                     + (" (deleted)" if e["action"] == "delete" else ""))
        lines.append(f"      from {src['repo']} {day(src['date'])}: {clip(src['title'], 88)}{other}")
        lines.append(f"      behind: {names(e['behind'])}")
    if len(doc["candidates"]) > limit:
        lines.append(f"  … {len(doc['candidates']) - limit} more (--json has them all)")
    lines += ["", "ROLLOUTS IN FLIGHT — content that is the hub's, or that several repos already hold; these are still behind"]
    if not doc["rollouts"]:
        lines.append("  none in this window")
    for e in doc["rollouts"][:limit]:
        src = f" · kit {e['kit']['name']} v{e['kit']['version']}" if e["kit"] else ""
        lines.append(f"  {e['key']}  {len(e['holders']):>3} hold it · {len(e['behind']):>3} behind  {e['path']}{src}")
        lines.append(f"      latest in {e['from']['repo']} {day(e['from']['date'])}: {clip(e['from']['title'], 84)}")
        lines.append(f"      behind: {names(e['behind'])}")
    if len(doc["rollouts"]) > limit:
        lines.append(f"  … {len(doc['rollouts']) - limit} more")
    if doc["forks"]:
        lines += ["", "FORKED — several repos took the same file to different contents (a seed each fills in, or competing fixes)"]
        for f in doc["forks"][:limit]:
            lines.append(f"  {f['variants']} variants · {len(f['behind'])} still hold the original  {f['path']}  ({names(f['repos'], 4)})")
    lines += ["", "FEATURES — declared or shipped in a repo's feature index"]
    if not doc["features"] and not doc["feature_notes"] and not doc["feature_rollouts"]:
        lines.append("  none in this window")
    by_repo: dict[str, list[dict]] = {}
    for f in doc["features"]:
        by_repo.setdefault(f["repo"], []).append(f)
    for repo, rows in list(by_repo.items())[: cfg["features"]["max_rows"]]:
        shipped = sum(1 for f in rows if f["change"] == "shipped")
        what = f"{len(rows) - shipped} new" + (f", {shipped} shipped" if shipped else "")
        shown = "; ".join(f"{f['id']} {clip(f['title'], 48)}" for f in rows[:3])
        lines.append(f"  {repo:<24} {what:<18} {shown}" + (f"; and {len(rows) - 3} more" if len(rows) > 3 else ""))
    if len(by_repo) > cfg["features"]["max_rows"]:
        lines.append(f"  … {len(by_repo) - cfg['features']['max_rows']} more repos")
    for w in doc["feature_rollouts"]:
        lines.append(f"  fleet-wide ({len(w['repos'])} repos, so the hub's doing, not one repo's): {clip(w['title'], 80)}")
    created = [n for n in doc["feature_notes"] if n["note"] == "created"]
    if created:
        lines.append("  index created in the window (not listed feature by feature): "
                     + names([f"{n['repo']} ({n['features']})" for n in created], 8))
    unread = [r for r in doc["repos"] if not r["read"]]
    stale = [r for r in doc["repos"] if r["stale"]]
    if unread or stale:
        lines.append("")
    if unread:
        lines.append("NOT READ (their activity is unknown, not absent): "
                     + ", ".join(f"{r['repo']} ({r['reason']})" for r in unread))
    if stale:
        lines.append(f"STALE (last fetched over {cfg['stale_days']} days ago, newer commits are not seen): "
                     + names([r["repo"] for r in stale], 10))
    lines += ["", "Next: tools/dash uplift show <key>  ·  tools/dash uplift brief --top 5  ·  "
                  "tools/dash uplift file <key> (a preview; --apply files it)"]
    return "\n".join(lines)


def find(doc: dict, key: str) -> dict:
    want = key if key.startswith(KEY_PREFIX) else KEY_PREFIX + key
    rows = [e for e in doc["candidates"] + doc["rollouts"] if e["key"].startswith(want)]
    if not rows:
        raise UpliftError(f"no candidate or rollout has the key {key} in this window (tools/dash uplift scan lists them)")
    if len(rows) > 1:
        raise UpliftError(f"{key} matches {len(rows)} entries: {', '.join(e['key'] for e in rows)}")
    return rows[0]


def change_diff(entry: dict, members: list[Repo], max_lines: int) -> str:
    """The change as a unified diff, from the earlier version most repos behind hold to what the origin holds now."""
    repo = next(r for r in members if r.target == entry["from"]["repo"])
    old = blob_bytes(repo.path, entry["from"]["base"])
    new = blob_bytes(repo.path, entry["post"]) if entry["post"] else b""
    if is_binary(old) or is_binary(new):
        return f"(binary file: {len(old)} bytes before, {len(new)} bytes after)"
    path = entry["path"]
    rows = list(difflib.unified_diff(old.decode("utf-8", "replace").splitlines(), new.decode("utf-8", "replace").splitlines(),
                                     fromfile=f"a/{path}", tofile=f"b/{path}" if entry["post"] else "/dev/null", lineterm=""))
    if len(rows) > max_lines:
        rows = rows[:max_lines] + [f"… {len(rows) - max_lines} more lines: {entry['from']['url']}"]
    return "\n".join(rows)


def route_text(entry: dict) -> str:
    if entry["class"] != "candidate":
        kit = entry["kit"]
        what = (f"kit `{kit['name']}` v{kit['version']} arriving" if kit else
                "the content is the hub's own, came in on a fan-out branch, or several repos already hold it")
        return (f"This is a rollout, not one repo's improvement: {what}. The repos listed as behind have not taken it yet"
                + (f"; the kit's fan-out with `--upgrade` carries it to them." if kit else "."))
    if entry["route"] == "kit":
        if entry["hub_source"]:
            where = f"the earlier version is byte-identical to the hub's `{entry['hub_source']}`"
        else:
            kit = entry["kit"]
            where = (f"the earlier version carries the stamp `kit: {kit['name']} v{kit['version']}`, "
                     f"so the hub's `{kit['name']}` kit seeded it")
        return (f"Route `kit`: {where}. Make the change once in the kit, bump the kit's version, and deploy it with the kit's "
                "fan-out and `--upgrade`. Do not patch the copies: an edited copy is skipped by every later upgrade.")
    more = (" That many identical copies suggest the file belongs in a kit; adopting it is the alternative to patching each."
            if len(entry["behind"]) >= 3 else "")
    return ("Route `patch`: the hub owns no source for this file, so the same patch goes to each repo that still holds "
            f"an earlier version.{more}")


def render_entry(entry: dict, members: list[Repo], cfg: dict) -> str:
    src = entry["from"]
    lines = [f"{entry['key']}  {entry['class']}  {entry['path']}" + (" (deleted)" if entry["action"] == "delete" else ""), ""]
    for o in entry["origins"]:
        lines.append(f"  changed in {o['nwo']} on {day(o['date'])} by {o['author']}: {o['title']}")
        lines.append(f"    {o['url']}" + (f" ({o['commits']} commits touched the file)" if o["commits"] > 1 else ""))
    lines += ["", f"  {len(entry['behind'])} repo(s) hold a version the origin held before, byte for byte:",
              f"    {', '.join(entry['behind']) or '(none)'}"]
    if entry["post"]:
        lines.append(f"  {len(entry['holders'])} repo(s) hold the new content: {', '.join(entry['holders'])}")
    if entry["diverged"]:
        lines.append(f"  {entry['diverged']} repo(s) hold the file with other contents (not comparable)")
    if entry["variants"] > 1:
        lines.append(f"  {entry['variants']} different contents were made from the same earlier version across the fleet")
    lines += ["", "  " + route_text(entry), "", change_diff(entry, members, cfg["diff_lines"]),
              "", f"  (the diff is from the earlier version most repos behind hold to what {src['repo']} holds now; "
                  "a repo on another earlier version takes the same end state)"]
    return "\n".join(lines)


def render_brief(entries: list[dict], members: list[Repo], doc: dict, cfg: dict) -> str:
    """The work order a session or a harness reads: evidence first, then the questions only judgment answers."""
    out = ["# Fleet uplift work order", "",
           f"From `tools/dash uplift` on {day(doc['generated_at'])}: {doc['days']} days of default-branch history in "
           f"{doc['counts']['read']} repos, read from local git. Every count below is a byte comparison of file contents, "
           "not an estimate.", "",
           "For each candidate decide, in this order:", "",
           "1. **Is it general?** State the improvement without naming the repo it came from. If you cannot, it is specific "
           "to that repo: say so and stop.",
           "2. **Where does it belong?** A kit or standard in the hub (`templates/`, `specs/`), or the same patch in each repo.",
           "3. **Who gets it?** Start from the repos listed as behind; add or drop one only with a reason.",
           "4. **What proves it landed?** Acceptance criteria a later `tools/dash uplift scan` or a test can check.", "",
           "Propose only. Filing is `tools/dash uplift file <key>` (a preview) and `--apply`, typed by the maintainer.", ""]
    for e in entries:
        src = e["from"]
        out += [f"## {e['key']}: `{e['path']}`" + (" (deleted)" if e["action"] == "delete" else ""), "",
                f"- **Changed in:** {src['nwo']} on {day(src['date'])}: {src['title']} ({src['url']})",
                f"- **Behind ({len(e['behind'])}):** {', '.join(e['behind'])}",
                f"- **Already hold it:** {', '.join(e['holders']) or 'nobody else'}",
                f"- **Route found:** {route_text(e)}"]
        if e["variants"] > 1:
            out.append(f"- **Competing changes:** {e['variants']} different contents were made from the same earlier version.")
        out += ["", "```diff", change_diff(e, members, cfg["diff_lines"]), "```", ""]
    if doc["features"]:
        out += ["## Features declared or shipped in the window", "",
                "Ask of each: would a sibling repo of the same kind want it? If so it is a roadmap entry "
                "(`/future-features`), not a patch.", ""]
        out += [f"- {f['repo']} `{f['id']}` ({f['change']}): {f['title']}" for f in doc["features"][: cfg["features"]["max_rows"]]]
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------------ filing
class Gh:
    """Every GitHub call `file` makes, in one place so tests stub it."""

    def run(self, *args: str) -> str:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout

    def visibility(self, nwo: str) -> str | None:
        try:
            return self.run("api", f"repos/{nwo}", "--jq", ".visibility").strip() or None
        except (subprocess.CalledProcessError, OSError):
            return None

    def issues(self, repo: str, label: str) -> list[dict]:
        out = self.run("issue", "list", "--repo", repo, "--label", label, "--state", "all", "--limit", "500",
                       "--json", "number,state,url,body")
        return json.loads(out or "[]")

    def ensure_label(self, repo: str, label: str) -> None:
        self.run("label", "create", label, "--repo", repo, "--color", LABEL_COLOR, "--description", LABEL_TEXT, "--force")

    def create_issue(self, repo: str, title: str, body_file: Path, labels: list[str]) -> str:
        args = ["issue", "create", "--repo", repo, "--title", title, "--body-file", str(body_file)]
        for label in labels:
            args += ["--label", label]
        return self.run(*args).strip()


def marker(cfg: dict, key: str) -> str:
    return f'<!-- {cfg["file"]["marker"]} key="{key}" -->'


def issue_title(entry: dict) -> str:
    verb = "deleted" if entry["action"] == "delete" else "changed"
    return clip(f"Uplift: {entry['path']} {verb} in {entry['from']['repo']}, {len(entry['behind'])} repo(s) hold the earlier version", 200)


def issue_body(entry: dict, members: list[Repo], cfg: dict, hub_target: str | None) -> str:
    src = entry["from"]
    behind = [b for b in entry["behind"] if b != hub_target]
    lines = [marker(cfg, entry["key"]), "", "## What changed, and where", "",
             f"`{src['nwo']}` {'deleted' if entry['action'] == 'delete' else 'changed'} `{entry['path']}` on {day(src['date'])}: "
             f"{src['title']} ({src['url']}).", "", "## Who still holds the earlier version", "",
             f"{len(entry['behind'])} fleet repo(s) hold a version of this file that `{src['repo']}` held before its change, "
             "byte for byte, so the same change applies to each without adaptation."
             + (" The hub's own copy is one of them." if hub_target in entry["behind"] else ""), ""]
    if entry["route"] == "patch" and behind:
        lines += [f"applies_to: {', '.join(behind)}", ""]
    else:
        lines += [f"Repos behind: {', '.join(behind) or 'the hub only'}", ""]
    lines += ["## The change", "", "```diff", change_diff(entry, members, cfg["diff_lines"]), "```", "",
              "## Route", "", route_text(entry), ""]
    if entry["variants"] > 1:
        lines += [f"{entry['variants']} different contents were made from the same earlier version across the fleet. "
                  "Reconcile them before generalizing one.", ""]
    lines += ["## Acceptance criteria", "",
              "- [ ] The improvement is stated without naming the repo it came from, or this issue is closed as specific to that repo.",
              "- [ ] It is made at the route above: once in the kit, or as the same patch in each repo listed.",
              f"- [ ] `tools/dash uplift scan` no longer lists `{entry['key']}` as a candidate.", "", "---",
              f"_Captured by the fleet's uplift scan (`tools/dash uplift`, bamr87/bamr87 docs/UPLIFT.md) from local git history, "
              f"as `{entry['key']}`. Close it if the change is specific to its repo; label `agent:hold` to keep automation off it._"]
    return "\n".join(lines) + "\n"


def preview_paths(hub: Path, key: str) -> tuple[Path, Path]:
    base = state_dir(hub) / "previews"
    return base / f"{key}.md", base / f"{key}.json"


def digest(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()


def file_candidates(keys: list[str], *, hub: Path, doc: dict, members: list[Repo], cfg: dict, apply: bool,
                    gh: Gh | None = None) -> tuple[list[dict], int]:
    """Preview, or with `apply` file, one hub issue per candidate. → (one result per key, exit code)."""
    gh = gh or Gh()
    fcfg = cfg["file"]
    hub_nwo = doc["hub"]
    if not hub_nwo:
        raise UpliftError("_data/fleet.yml `hub.repo` is not set: there is no hub to file on")
    hub_target = hub_nwo.split("/", 1)[1]
    results: list[dict] = []
    if len(keys) > fcfg["max_per_run"]:
        raise UpliftError(f"{len(keys)} keys given; one run files at most {fcfg['max_per_run']} (uplift.file.max_per_run)")
    entries = [find(doc, k) for k in keys]
    existing: dict[str, dict] = {}
    open_count = 0
    if apply:
        for issue in gh.issues(hub_nwo, fcfg["label"]):
            open_count += issue.get("state", "").upper() == "OPEN"
            for m in re.finditer(r'<!-- %s key="([^"]+)" -->' % re.escape(fcfg["marker"]), issue.get("body") or ""):
                existing.setdefault(m.group(1), issue)
    hub_visibility = gh.visibility(hub_nwo) if apply else None
    labelled = False
    for entry in entries:
        key = entry["key"]
        res = {"key": key, "path": entry["path"], "outcome": "", "detail": ""}
        results.append(res)
        if entry["class"] != "candidate":
            res.update(outcome="refused", detail="a rollout, not one repo's improvement: there is nothing to capture")
            continue
        title, body = issue_title(entry), issue_body(entry, members, cfg, hub_target)
        if CREDENTIAL_RX.search(body):
            res.update(outcome="withheld", detail="the change holds a credential-shaped string; nothing was written")
            continue
        md, meta = preview_paths(hub, key)
        if not apply:
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(body, encoding="utf-8")
            meta.write_text(json.dumps({"key": key, "title": title, "sha256": digest(title, body),
                                        "labels": [fcfg["label"]] + (["agent:hold"] if fcfg["hold"] else [])}, indent=2) + "\n",
                            encoding="utf-8")
            res.update(outcome="preview", detail=str(md), title=title)
            continue
        if key in existing:
            res.update(outcome="skipped", detail=f"already filed: {existing[key].get('url')}")
            continue
        if open_count >= fcfg["max_open"]:
            res.update(outcome="refused", detail=f"{open_count} uplift issues are open; close or land some first "
                                                 f"(uplift.file.max_open is {fcfg['max_open']})")
            continue
        seen = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else None
        if not seen or not md.is_file():
            res.update(outcome="refused", detail=f"no preview yet: run `tools/dash uplift file {key}` and read it first")
            continue
        if seen.get("sha256") != digest(title, body) or md.read_text(encoding="utf-8") != body:
            res.update(outcome="refused", detail="the candidate changed since its preview: preview it again and read the new one")
            continue
        origin_visibility = gh.visibility(entry["from"]["nwo"])
        if hub_visibility == "public" and origin_visibility != "public":
            res.update(outcome="withheld", detail=f"{entry['from']['nwo']} is {origin_visibility or 'of unknown visibility'} "
                                                  f"and the hub is public: its change is never filed there")
            continue
        if not labelled:
            gh.ensure_label(hub_nwo, fcfg["label"])
            labelled = True
        url = gh.create_issue(hub_nwo, title, md, seen["labels"])
        open_count += 1
        res.update(outcome="filed", detail=url)
    bad = any(r["outcome"] in ("refused", "withheld") for r in results)
    return results, 1 if bad else 0


# -------------------------------------------------------------------------- CLI
def parse_now(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    when = dt.datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def run_scan(args: argparse.Namespace) -> tuple[dict, list[Repo], dict, Path]:
    hub = Path(args.hub).resolve() if args.hub else HUB
    projects = Path(args.projects).expanduser().resolve() if args.projects else default_projects_dir(hub)
    cfg, _ = load_config(hub)
    doc, members = scan(hub, projects, days=args.days, only=getattr(args, "repo", None) or None, now=parse_now(args.now))
    return doc, members, cfg, hub


def cmd_scan(args: argparse.Namespace) -> int:
    doc, _, cfg, hub = run_scan(args)
    saved = save(doc, hub)
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print(render(doc, cfg))
        print(f"\nSaved: {saved}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    doc, members, cfg, _ = run_scan(args)
    print(render_entry(find(doc, args.key), members, cfg))
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    doc, members, cfg, _ = run_scan(args)
    entries = [find(doc, k) for k in args.keys] if args.keys else doc["candidates"][: args.top]
    text = render_brief(entries, members, doc, cfg)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}: {len(entries)} candidate(s)")
    else:
        print(text)
    return 0


def cmd_file(args: argparse.Namespace) -> int:
    doc, members, cfg, hub = run_scan(args)
    results, code = file_candidates(args.keys, hub=hub, doc=doc, members=members, cfg=cfg, apply=args.apply)
    for r in results:
        print(f"{r['outcome']:<9} {r['key']}  {r['path']}\n          {r['detail']}")
    if not args.apply and any(r["outcome"] == "preview" for r in results):
        print("\nNothing was filed. Read the preview(s), then add --apply to file exactly those bytes as hub issues.")
    return code


def cmd_status(args: argparse.Namespace) -> int:
    hub = Path(args.hub).resolve() if args.hub else HUB
    path = state_dir(hub) / "scan.json"
    if not path.is_file():
        print("No scan yet: tools/dash uplift scan")
        return 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    age = (parse_now(args.now) or utcnow()) - dt.datetime.fromisoformat(doc["generated_at"])
    print(f"Last scan {day(doc['generated_at'])} ({age.days} day(s) ago), {doc['days']} days, "
          f"{doc['counts']['read']} of {doc['counts']['repos']} repos read")
    print("  " + headline(doc))
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--days", type=int, help="the window of default-branch history (default: uplift.days)")
    common.add_argument("--projects", help="the folder holding the submodule checkouts (default: the hub's projects/)")
    common.add_argument("--hub", help=argparse.SUPPRESS)
    common.add_argument("--now", help=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog="uplift", description="What one fleet repo improved that the others still lack "
                                                           "(docs/UPLIFT.md). Reads local git; calls no model.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("scan", parents=[common], help="read the window and list candidates, rollouts and features")
    p.add_argument("--repo", action="append", metavar="NAME", help="only changes made in this repo (repeatable)")
    p.add_argument("--json", action="store_true", help="print the whole document as JSON")
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("show", parents=[common], help="one candidate or rollout in full, with its diff")
    p.add_argument("key")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("brief", parents=[common], help="the work order a session or harness reads (Markdown)")
    p.add_argument("keys", nargs="*", metavar="KEY")
    p.add_argument("--top", type=int, default=5, help="without keys: this many candidates, most repos behind first")
    p.add_argument("--out", help="write the work order to this file")
    p.set_defaults(fn=cmd_brief)
    p = sub.add_parser("file", parents=[common], help="preview a candidate as a hub issue; --apply files the preview")
    p.add_argument("keys", nargs="+", metavar="KEY")
    p.add_argument("--apply", action="store_true", help="file exactly the previewed bytes (typed by a person)")
    p.set_defaults(fn=cmd_file)
    p = sub.add_parser("status", parents=[common], help="the last scan's headline, without reading git")
    p.set_defaults(fn=cmd_status)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["scan", *argv]                   # bare `dash uplift`, or flags alone, is the scan
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    try:
        return args.fn(args)
    except UpliftError as exc:
        sys.stderr.write(f"uplift: {exc}\n")
        return 2
    except subprocess.CalledProcessError as exc:
        last = ((exc.stderr or "").strip().splitlines() or [f"exit {exc.returncode}"])[-1]
        sys.stderr.write(f"uplift: {exc.cmd[0]} {exc.cmd[1] if len(exc.cmd) > 1 else ''} failed: {last}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

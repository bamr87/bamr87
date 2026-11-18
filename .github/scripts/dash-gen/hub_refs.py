#!/usr/bin/env python3
"""
hub_refs — does every pin of a hub reusable workflow or action resolve?

A caller that pins `bamr87/bamr87/.github/workflows/<file>@<ref>` (or
`.github/actions/<name>@<ref>`) at a ref that lacks the file fails at startup:
the run has no jobs and its log names nothing. law-ai's CI on main was red that
way from 2026-10-30, calling `spec-gate.yml@v2` while `v2` predated the file,
and the hub's own spec-driven kit carried the same pin (FF-0037,
bamr87/bamr87#610). This module is the one reading of those pins the hub's
three callers share:

  extract    every hub `uses:` in a workflow or action file, at job and step
             level, quoted or not, with a trailing comment or not. Local
             `./` refs, other owners, comment lines and block scalars
             (`run: |`) are ignored. Matches workflow_atlas's `_ref` shapes.
  resolve    each distinct target@ref ONCE per run, to one of four states:
               ok                   the ref exists and carries the target
               ref-missing          the hub has no such ref
               file-missing-at-ref  the ref exists, the target is not in it
               unverified           anything else: no network, a 401/403/5xx,
                                    a tag the local clone does not hold
             Two backends: `GitBackend` reads a local hub clone (offline; a
             tag missing locally is unverified, never ref-missing, because CI
             checks out without tags) and `ApiBackend` asks GitHub
             (`commits/<ref>`, then `contents/<target>?ref=<ref>`; the hub is
             public, so a 404 there is authoritative).
  fix        a broken pin carries its computed fix: the target is on main →
             cut the next `vX.Y.0` and move `vX` (docs/WORKFLOW-VERSIONING.md,
             Cutting a release); the ref was never cut → cut it or repin; the
             target is gone from main too → repin to its replacement.

Callers: tools/check-drift.sh check (q) (`check templates`, offline, warns;
`fleet` under --remote/--ci lists the broken fleet callers the daily scan
recorded), tools/fanout.sh's pre-flight (`check --online` on the kit's caller
templates; --apply is refused until they resolve) and harness_registry.py's
fleet scan (`hub_refs` on every repo row, a `hub-ref-broken` attention item).

Stdlib only. Fixture tests: python3 test_hub_refs.py
Doc: docs/WORKFLOW-VERSIONING.md "Pins resolve before they ship".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

HUB_DEFAULT = "bamr87/bamr87"
DEFAULT_BRANCH = "main"
STATES = ("ok", "ref-missing", "file-missing-at-ref", "unverified")
BROKEN = ("ref-missing", "file-missing-at-ref")
ACTION_FILES = ("action.yml", "action.yaml")
# Kit history and test data: an archived shape is never seeded again (only
# compared byte for byte), and a fixture is somebody's input, not a pin.
SKIP_DIRS = {"archive", "fixtures", "node_modules", ".git"}
TAG_FETCH = "git fetch --no-tags --depth=1 origin '+refs/tags/v*:refs/tags/v*'"

# `uses:` as a key, optionally the first key of a sequence entry, the value
# optionally quoted (matching quotes), optionally followed by a comment.
USES_RX = re.compile(
    r"""^[ \t]*(?:-[ \t]+)?uses:[ \t]*(?P<q>['"]?)(?P<value>[^'"\s#]+)(?P=q)[ \t]*(?:\#.*)?$""")
# The same shapes workflow_atlas.WORKFLOW_REF_RX / LOCAL_ACTION_RX accept,
# restricted to a remote owner/repo and a ref.
REMOTE_RX = re.compile(
    r"^(?P<nwo>[\w.-]+/[\w.-]+)/(?P<target>\.github/(?:workflows/[\w.-]+?\.ya?ml"
    r"|actions/[\w./-]+?))/?@(?P<ref>\S+)$")
# A key whose value is a block scalar (`run: |`, `script: >-`): its body is
# text, so a `uses:` line inside it is not a pin.
BLOCK_RX = re.compile(r"^(?P<lead>[ \t]*(?:-[ \t]+)?)[^\s#'\"][^:#]*:[ \t]*[|>][-+0-9]*[ \t]*(?:#.*)?$")
SHA_RX = re.compile(r"^[0-9a-f]{40}$")
MAJOR_RX = re.compile(r"^v(\d+)$")
RELEASE_RX = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #
def kind_of(target: str) -> str:
    return "workflow" if target.startswith(".github/workflows/") else "action"


def extract(text: str, path: str, hub: str = HUB_DEFAULT) -> list[dict]:
    """Every pin of a `hub` workflow or action in one YAML file, in line order."""
    out: list[dict] = []
    block_min: int | None = None  # body of an open block scalar is indented >= this
    for n, line in enumerate(text.splitlines(), 1):
        body = line.lstrip(" \t")
        indent = len(line) - len(body)
        if block_min is not None:
            if not body or indent >= block_min:
                continue
            block_min = None
        if not body or body.startswith("#"):
            continue
        b = BLOCK_RX.match(line)
        if b:
            block_min = len(b.group("lead")) + 1
            continue
        m = USES_RX.match(line)
        if not m:
            continue
        r = REMOTE_RX.match(m.group("value"))
        if not r or r.group("nwo").lower() != hub.lower():
            continue
        target = r.group("target").rstrip("/")
        out.append({"path": path, "line": n, "kind": kind_of(target), "target": target,
                    "ref": r.group("ref"), "uses": m.group("value")})
    return out


def iter_yaml_files(root: Path, paths: Iterable[str]) -> list[Path]:
    """The .yml/.yaml files under each path (a file is taken as given), sorted,
    skipping SKIP_DIRS."""
    files: list[Path] = []
    for p in paths:
        full = (root / p) if not Path(p).is_absolute() else Path(p)
        if full.is_file():
            files.append(full)
            continue
        if not full.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith((".yml", ".yaml")):
                    files.append(Path(dirpath) / name)
    return files


def scan_paths(root: Path, paths: Iterable[str], hub: str = HUB_DEFAULT) -> list[dict]:
    refs: list[dict] = []
    for f in iter_yaml_files(root, paths):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = f.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = f.as_posix()
        refs.extend(extract(text, rel, hub))
    return refs


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #
def result(status: str, detail: str = "", via: str = "") -> dict:
    return {"status": status, "detail": detail, "via": via}


def _git_env() -> dict:
    """Git that reads only the clone it is pointed at: no inherited GIT_*
    redirection (a hook's GIT_DIR), no prompt, no lazy fetch of a missing
    object in a partial clone (offline means offline)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
    return env


class GitBackend:
    """Offline: the hub clone at `root`. `default_branch` is resolved against
    the working tree under check (what that branch holds once the tree lands),
    every other ref against the clone's tags, then its branches. A ref the
    clone does not hold is unverified: CI checks out shallow and tagless, and a
    missing tag says nothing about GitHub."""

    via = "git"

    def __init__(self, root: Path | str, default_branch: str = DEFAULT_BRANCH,
                 worktree_is_default: bool = True):
        self.root = Path(root)
        self.default_branch = default_branch
        self.worktree_is_default = worktree_is_default

    def _git(self, *args: str) -> tuple[int, str]:
        try:
            r = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                               text=True, env=_git_env(), timeout=30)
        except (OSError, subprocess.SubprocessError):
            return 1, ""
        return r.returncode, r.stdout

    def commit(self, ref: str) -> str | None:
        if SHA_RX.match(ref):
            cands = [f"{ref}^{{commit}}"]
        else:
            cands = [f"refs/tags/{ref}^{{commit}}", f"refs/remotes/origin/{ref}^{{commit}}",
                     f"refs/heads/{ref}^{{commit}}"]
        for cand in cands:
            rc, out = self._git("rev-parse", "--verify", "--quiet", cand)
            if rc == 0 and out.strip():
                return out.strip()
        return None

    def has(self, commit: str, kind: str, target: str) -> bool:
        paths = [target] if kind == "workflow" else [f"{target}/{f}" for f in ACTION_FILES]
        # ls-tree reads trees only, so a blobless clone answers without a fetch.
        rc, out = self._git("ls-tree", "--name-only", commit, "--", *paths)
        return rc == 0 and bool(out.strip())

    def resolve(self, kind: str, target: str, ref: str) -> dict:
        if ref == self.default_branch and self.worktree_is_default:
            present = present_in_tree(self.root, kind, target)
            return (result("ok", f"{ref} is the tree under check", self.via) if present
                    else result("file-missing-at-ref", f"{ref} has no {_what(kind, target)}", self.via))
        sha = self.commit(ref)
        if sha is None:
            return result("unverified", f"{ref} is not in the local clone ({TAG_FETCH})", self.via)
        if self.has(sha, kind, target):
            return result("ok", "", self.via)
        return result("file-missing-at-ref", f"{ref} has no {_what(kind, target)} (local tag)", self.via)

    def tags(self) -> list[str] | None:
        rc, out = self._git("tag", "--list", "v*")
        return out.split() if rc == 0 else None


Getter = Callable[..., tuple]  # get(path, accept=None) -> (status code | None, data)


class ApiBackend:
    """GitHub, through `get(path, accept=None) -> (code, data)`: the ref first
    (commits/<ref>, asking for the bare SHA), then the target at it. A 404 (422
    for a ref GitHub cannot parse as one) is authoritative because the hub is
    public; any other answer, or none, is unverified."""

    via = "api"

    def __init__(self, get: Getter, hub: str = HUB_DEFAULT):
        self.get = get
        self.hub = hub

    def resolve(self, kind: str, target: str, ref: str) -> dict:
        q = urllib.parse.quote
        code, _ = self.get(f"repos/{self.hub}/commits/{q(ref, safe='')}",
                           accept="application/vnd.github.sha")
        if code in (404, 422):
            return result("ref-missing", f"{self.hub} has no ref {ref}", self.via)
        if code != 200:
            return result("unverified", f"commits/{ref} answered {code or 'nothing'}", self.via)
        code, data = self.get(f"repos/{self.hub}/contents/{q(target)}?ref={q(ref, safe='')}")
        if code == 404:
            return result("file-missing-at-ref", f"{ref} has no {_what(kind, target)}", self.via)
        if code != 200:
            return result("unverified", f"contents/{target}@{ref} answered {code or 'nothing'}", self.via)
        if kind == "action":
            names = {e.get("name") for e in data if isinstance(e, dict)} if isinstance(data, list) else set()
            if not names & set(ACTION_FILES):
                return result("file-missing-at-ref", f"{ref} has no {_what(kind, target)}", self.via)
        return result("ok", "", self.via)

    def tags(self) -> list[str] | None:
        code, data = self.get(f"repos/{self.hub}/git/matching-refs/tags/v")
        if code != 200 or not isinstance(data, list):
            return None
        return [str(r.get("ref", "")).removeprefix("refs/tags/") for r in data if isinstance(r, dict)]


class Resolver:
    """Each distinct target@ref is looked up once per run (`lookups` counts
    them); a backend's `unverified` falls through to the next backend."""

    def __init__(self, *backends):
        self.backends = list(backends)
        self.cache: dict[tuple[str, str], dict] = {}
        self.lookups = 0

    def resolve(self, kind: str, target: str, ref: str) -> dict:
        key = (target, ref)
        if key not in self.cache:
            self.lookups += 1
            res = result("unverified", "no backend", "")
            for backend in self.backends:
                res = backend.resolve(kind, target, ref)
                if res["status"] != "unverified":
                    break
            self.cache[key] = res
        return self.cache[key]

    def tags(self) -> list[str] | None:
        for backend in self.backends:
            tags = backend.tags()
            if tags is not None:
                return tags
        return None


# --------------------------------------------------------------------------- #
# getters (the network edge; tests pass a dict-backed function instead)
# --------------------------------------------------------------------------- #
def http_getter(token: str | None = None, timeout: float = 20.0) -> Getter:
    """api.github.com over urllib. Never prints the token."""
    def get(path: str, accept: str | None = None) -> tuple:
        req = urllib.request.Request(f"https://api.github.com/{path}")
        req.add_header("Accept", accept or "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "hub-refs")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, _decode(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (urllib.error.URLError, OSError, ValueError):
            return None, None
    return get


def gh_getter(gh: str = "gh") -> Getter:
    """`gh api`, so a local run and fanout.sh use the same auth gh already has."""
    code_rx = re.compile(r"HTTP (\d{3})")

    def get(path: str, accept: str | None = None) -> tuple:
        cmd = [gh, "api", path]
        if accept:
            cmd[2:2] = ["-H", f"Accept: {accept}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None, None
        if r.returncode == 0:
            return 200, _decode(r.stdout.encode())
        m = code_rx.search(r.stderr or "")
        return (int(m.group(1)) if m else None), None
    return get


def default_getter() -> Getter:
    gh = shutil.which("gh")
    if gh:
        return gh_getter(gh)
    return http_getter(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))


def _decode(raw: bytes):
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except ValueError:
        return text.strip()


# --------------------------------------------------------------------------- #
# facts about main, and the computed fix
# --------------------------------------------------------------------------- #
def _what(kind: str, target: str) -> str:
    return target if kind == "workflow" else f"{target}/action.yml"


def present_in_tree(root: Path, kind: str, target: str) -> bool:
    if kind == "workflow":
        return (root / target).is_file()
    return any((root / target / f).is_file() for f in ACTION_FILES)


class TreeFacts:
    """What a checkout of the hub's default branch says about a target: is it
    there, and does the changelog's `[Unreleased]` (or a changelog.d fragment
    waiting to be compiled into it) name it."""

    def __init__(self, root: Path | str, tags: list[str] | None = None,
                 tags_fn: Callable[[], list[str] | None] | None = None):
        self.root = Path(root)
        self._tags = tags
        self._tags_fn = tags_fn  # read once, and only when a fix needs a version
        self._unreleased: str | None = None

    @property
    def tags(self) -> list[str] | None:
        if self._tags is None and self._tags_fn is not None:
            self._tags, self._tags_fn = self._tags_fn(), None
        return self._tags

    def on_main(self, kind: str, target: str) -> bool:
        return present_in_tree(self.root, kind, target)

    def unreleased_text(self) -> str:
        if self._unreleased is None:
            parts = []
            try:
                text = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
                m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
                parts.append(m.group(1) if m else "")
            except OSError:
                pass
            frag_dir = self.root / "changelog.d"
            if frag_dir.is_dir():
                for f in sorted(frag_dir.glob("*.md")):
                    if f.name not in ("README.md", "SCHEMA.md"):
                        parts.append(f.read_text(encoding="utf-8", errors="replace"))
            self._unreleased = "\n".join(parts)
        return self._unreleased

    def unreleased(self, target: str) -> bool:
        return target.rsplit("/", 1)[-1] in self.unreleased_text()


def next_release(major: int, tags: list[str] | None) -> str | None:
    """The next minor of `vN` from the tags: v2.0.0 → v2.1.0. None when the
    tags are unknown; vN.0.0 when no release of that major exists yet."""
    if tags is None:
        return None
    minors = [int(m.group(2)) for m in (RELEASE_RX.match(t) for t in tags)
              if m and int(m.group(1)) == major]
    return f"v{major}.{max(minors) + 1}.0" if minors else f"v{major}.0.0"


def compute_fix(kind: str, target: str, ref: str, status: str, facts: TreeFacts | None) -> list[str]:
    """The fix for one broken pin, most direct first. Empty for a pin that is
    not broken."""
    if status not in BROKEN:
        return []
    name = target.rsplit("/", 1)[-1]
    on_main = facts.on_main(kind, target) if facts else None
    tags = facts.tags if facts else None
    stopgap = ("or, as a stopgap, repin the caller to a ref that has it "
               "(a SHA bends the always-latest policy, check (k); @main bends UPS-WORK-10)")
    if on_main is False:
        return [f"repin to the replacement of {name}: it is gone from {DEFAULT_BRANCH} too "
                "(CHANGELOG.md and the Retired table in .github/workflows/README.md name it)"]
    major = MAJOR_RX.match(ref)
    release = RELEASE_RX.match(ref)
    if status == "file-missing-at-ref" and major:
        nxt = next_release(int(major.group(1)), tags) or f"the next v{major.group(1)}.Y.0"
        why = (f"{name} is on {DEFAULT_BRANCH} under [Unreleased], so that release carries it"
               if facts and facts.unreleased(target) else
               f"{name} is on {DEFAULT_BRANCH} but not under [Unreleased]: add its changelog.d "
               "entry in the release PR")
        return [f"cut {nxt} and move {ref}", why, stopgap]
    if status == "file-missing-at-ref" and release:
        nxt = next_release(int(release.group(1)), tags) or f"the next v{release.group(1)}.Y.0"
        return [f"repin to v{release.group(1)} once {nxt} carries {name} ({ref} is immutable "
                "and never gains it); cut it first if no release has it", stopgap]
    if status == "file-missing-at-ref":
        return [f"repin to a release tag that carries {name}", stopgap]
    # ref-missing: the ref was never cut
    if major:
        return [f"cut v{major.group(1)}.0.0 and create {ref} (a new major: "
                "docs/WORKFLOW-VERSIONING.md), or repin to an existing major"]
    if release:
        return [f"cut {ref}, or repin to an existing tag"]
    return [f"repin to an existing release tag: the hub has no ref {ref}"]


def annotate(refs: list[dict], resolver: Resolver, facts: TreeFacts | None) -> list[dict]:
    """Resolve each extracted pin in place: `status`, `detail`, and on a broken
    one its `fix` (a list, the most direct first)."""
    for r in refs:
        res = resolver.resolve(r["kind"], r["target"], r["ref"])
        r["status"] = res["status"]
        if res.get("detail"):
            r["detail"] = res["detail"]
        else:
            r.pop("detail", None)
        fix = compute_fix(r["kind"], r["target"], r["ref"], res["status"], facts)
        if fix:
            r["fix"] = fix
        else:
            r.pop("fix", None)
    return refs


def summarize(refs: list[dict]) -> dict:
    counts = {s: 0 for s in STATES}
    for r in refs:
        counts[r.get("status", "unverified")] = counts.get(r.get("status", "unverified"), 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def line_for(r: dict) -> str:
    text = f"{r['path']}:{r['line']} {r['uses']}: {r['status']}"
    if r.get("detail"):
        text += f" — {r['detail']}"
    if r.get("fix"):
        text += f"; fix: {r['fix'][0]}"
    return text


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    refs = scan_paths(root, args.paths or ["templates"], args.hub)
    git = GitBackend(root, args.default_branch)
    backends = ([ApiBackend(default_getter(), args.hub)] if args.online else []) + [git]
    resolver = Resolver(*backends)
    facts = TreeFacts(root, tags_fn=resolver.tags)
    annotate(refs, resolver, facts)
    counts = summarize(refs)
    broken = [r for r in refs if r["status"] in BROKEN]
    unverified = [r for r in refs if r["status"] == "unverified"]
    if args.json:
        print(json.dumps({"refs": refs, "counts": counts, "lookups": resolver.lookups,
                          "via": [b.via for b in backends]}, indent=2))
    else:
        where = " ".join(args.paths or ["templates"])
        via = "GitHub, then the local tags" if args.online else "the local tags, offline"
        if counts["ok"] and not args.quiet:
            print(f"  ✓ {counts['ok']} of {len(refs)} hub pin(s) in {where} resolve "
                  f"({resolver.lookups} distinct target@ref, via {via})")
        if not refs and not args.quiet:
            print(f"  ✓ no hub pins in {where}")
        for r in broken:
            print(f"  ✗ {line_for(r)}")
        for r in unverified:
            print(f"  ! {line_for(r)}")
    if broken:
        return 1
    return 3 if unverified else 0


def cmd_fleet(args: argparse.Namespace) -> int:
    """The broken fleet callers the committed daily scan recorded. Offline: it
    reads _data/harness_registry.yml, never GitHub."""
    path = Path(args.registry)
    try:
        import yaml  # the committed file is YAML; PyYAML is the hub's one dependency
    except ImportError:
        print("  ! skipped (PyYAML unavailable)")
        return 0
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"  ! could not read {path}: {exc}")
        return 0
    repos = [r for r in data.get("repos") or [] if isinstance(r, dict)]
    scanned_at = (data.get("scan") or {}).get("scanned_at") or data.get("generated_at") or "unknown"
    if not any("hub_refs" in r for r in repos):
        print(f"  ! the committed scan ({scanned_at}) predates hub_refs: "
              "fleet-pulse.yml's next harness scan records them")
        return 0
    refs = [dict(x, repo=r.get("repo")) for r in repos if not r.get("archived")
            for x in r.get("hub_refs") or []]
    unread_repos = sorted(str(r.get("repo")) for r in repos
                          if not r.get("external") and not r.get("scanned"))
    unread_files = sum(int(r.get("hub_refs_unread_files") or 0) for r in repos)
    counts = summarize(refs)
    readable = sum(1 for r in repos if r.get("scanned"))
    print(f"  ✓ {counts['ok']} of {len(refs)} hub pin(s) in {readable} scanned fleet repo(s) "
          f"resolve (scan {scanned_at})")
    for r in refs:
        if r.get("status") in BROKEN:
            print(f"  ✗ {r['repo']}: {line_for(r)}")
    if counts["unverified"]:
        print(f"  ! {counts['unverified']} fleet pin(s) unverified when scanned — NOT verified clean")
    if unread_repos or unread_files:
        shown = " ".join(unread_repos[:6]) + (" …" if len(unread_repos) > 6 else "")
        print(f"  ! {len(unread_repos)} repo(s) unread{(' (' + shown + ')') if shown else ''} and "
              f"{unread_files} workflow file(s) unread (past the cap or unreadable) — NOT verified clean")
    return 1 if any(r.get("status") in BROKEN for r in refs) else 0


def main(argv: list[str] | None = None) -> int:
    root_default = str(Path(__file__).resolve().parents[3])
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="resolve every hub pin under PATHS (default: templates)")
    c.add_argument("paths", nargs="*", help="files or directories, relative to --root")
    c.add_argument("--root", default=root_default, help="the hub checkout (default: this one)")
    c.add_argument("--hub", default=HUB_DEFAULT, help="owner/repo of the hub")
    c.add_argument("--default-branch", default=DEFAULT_BRANCH)
    c.add_argument("--online", action="store_true",
                   help="ask GitHub first (gh, else GH_TOKEN), then the local tags")
    c.add_argument("--json", action="store_true")
    c.add_argument("--quiet", action="store_true", help="print only what does not resolve")
    c.set_defaults(func=cmd_check)
    f = sub.add_parser("fleet", help="broken fleet callers from the committed harness scan")
    f.add_argument("--registry", default=str(Path(root_default) / "_data" / "harness_registry.yml"))
    f.set_defaults(func=cmd_fleet)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

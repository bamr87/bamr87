#!/usr/bin/env python3
"""
Every hub workflow or action that a fleet caller pins at a tag or a SHA exists
at that ref (bamr87/bamr87#457).

UPS-WORK-10 makes a caller pin `bamr87/bamr87` and `bamr87/.github` workflows
and actions at `@vN`, `@vX.Y.Z` or a full SHA, but nothing checked that the pin
resolves. From 2026-10-26 until v2.1.0 (2026-11-15) the spec-driven kit's
caller pinned `spec-gate.yml@v2` while the hub's `v2` tag predated the file,
and law-ai's CI on main, pinned the same way, failed at startup for two weeks.
This test reads the same `uses:` values as UPS-WORK-10 (conformance.py's
yaml_values at the contract's uses_keys, filtered by fleet_uses_value_re and
pinned_ref_re from specs/WORK.contract.yml) in:

- the callers the kits seed: templates/**/*.yml and *.yaml, minus each kit's
  archive/ of retired versions and any fixtures/;
- the hub's own pin_scope (.github/workflows, .github/actions), whose reusable
  workflows call hub actions by tag because `./` resolves in the caller.

Each pinned path is checked at its ref in the repo it names. A reusable
workflow is the file itself; an action is a directory holding action.yml or
action.yaml. A ref that is not a pin (`@main`) is UPS-WORK-10's to fail.

Refs are read as GitHub serves them, never from this checkout: CI checks out
at depth 1 with no tags, and a local clone can still hold a floating tag from
before it moved (`v2` moved on 2026-11-15). Each repo's v* tags, and any pinned
SHA, are fetched at depth 1 without blobs (about 250 KB for the hub) into a
scratch repository that is deleted afterwards. A repo that cannot be fetched
(offline) makes the test `skip` with git's reason, never pass.

The fixture tests build throwaway repositories and need no network. Needs
PyYAML and git:

    python3 tools/test_template_pins.py
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
#: Directories under templates/ that are never seeded into a repo.
NOT_SEEDED = {"archive", "fixtures"}
SHA = re.compile(r"[0-9a-f]{40}")
FETCH_TIMEOUT = 120
#: Git runs on scratch repositories alone: no inherited GIT_DIR (a hook's) can
#: aim it at this checkout, no prompt can hang it, no read goes to the network.
GIT_ENV = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
           "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}


class Skip(Exception):
    pass


class Pin(NamedTuple):
    file: str   # the caller, relative to the scanned root
    uses: str   # the parsed `uses:` value
    repo: str   # bamr87/bamr87 or bamr87/.github
    path: str   # a workflow file or an action directory in that repo
    ref: str    # vN, vX.Y.Z or a 40-character SHA


def caller_files(root: Path, hub: Path = HUB) -> list[Path]:
    """The seeded templates under root/templates, then root's UPS-WORK-10 pin_scope."""
    root = root.resolve()
    t = root / "templates"
    seeded = [p for p in sorted(t.rglob("*")) if p.suffix in (".yml", ".yaml") and p.is_file()
              and not NOT_SEEDED & set(p.relative_to(t).parts[:-1])]
    return seeded + c._pin_files(c.Repo(root, hub))


def pins_in(files: list[Path], root: Path, hub: Path = HUB) -> tuple[list[Pin], list[str]]:
    """(pins, files that are not valid YAML). A pin is a parsed `uses:` value
    that matches fleet_uses_value_re with a ref that fullmatches pinned_ref_re."""
    d = c._defs(c.Repo(hub, hub))
    keys = [k for kind in ("workflow", "action") for k in (d.get("uses_keys") or {}).get(kind) or []]
    fleet, pinned = re.compile(d["fleet_uses_value_re"]), re.compile(d["pinned_ref_re"])
    pins: list[Pin] = []
    broken: list[str] = []
    for p in files:
        rel = str(p.resolve().relative_to(root.resolve()))
        vals = c.yaml_values(p, keys)
        if vals is None:
            broken.append(rel)
        for v in vals or []:
            m = fleet.match(v)
            if m and pinned.fullmatch(m.group(2)):
                owner, name, path = m.group(1).split("/", 2)
                pins.append(Pin(rel, v, f"{owner}/{name}", path, m.group(2)))
    return pins, broken


class Store:
    """A scratch bare repository holding one remote's v* tags, and any SHA asked
    for, as commits and trees at depth 1 without blobs. A path is looked up in
    the trees, so nothing after the fetch reads from the network."""

    def __init__(self, path: Path, repo: str, url: str):
        self.path, self.repo = path, repo
        path.mkdir(parents=True)
        self.git("init", "-q", "--bare", check=True)
        self.git("remote", "add", "origin", url, check=True)

    def git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, text=True,
                              env=GIT_ENV, timeout=FETCH_TIMEOUT, check=check)

    def fetch(self, *refspecs: str) -> str | None:
        """None once fetched, else why not (git's last line)."""
        try:
            r = self.git("fetch", "-q", "--depth=1", "--filter=blob:none", "--no-tags", "origin", *refspecs)
        except subprocess.TimeoutExpired:
            return f"no answer in {FETCH_TIMEOUT}s"
        return None if r.returncode == 0 else (r.stderr.strip().splitlines() or [f"git exited {r.returncode}"])[-1]

    def commit(self, rev: str) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").returncode == 0

    def blob(self, rev: str, path: str) -> bool:
        # ls-tree takes the type from the parent tree, so the blob itself is never
        # needed (`git cat-file -e` would want it, and this repository has none).
        entry = self.git("ls-tree", rev, "--", path).stdout.split(None, 2)
        return len(entry) > 1 and entry[1] == "blob"

    def missing(self, ref: str, path: str) -> str | None:
        """Why `path` is not at `ref`, or None when it is."""
        if SHA.fullmatch(ref):
            err = None if self.commit(ref) else self.fetch(ref)
            if not self.commit(ref):
                return f"{self.repo} has no commit {ref}" + (f" ({err})" if err else "")
            rev = ref
        else:
            rev = f"refs/tags/{ref}"
            if not self.commit(rev):
                return f"{self.repo} has no tag {ref}"
        want = [path] if path.endswith((".yml", ".yaml")) else [f"{path}/action.yml", f"{path}/action.yaml"]
        if any(self.blob(rev, f) for f in want):
            return None
        return f"{ref} has no {want[0]}" + (" (nor action.yaml)" if len(want) > 1 else "")


def check(pins: list[Pin], remotes: dict[str, str]) -> tuple[list[str], list[str]]:
    """(problems, unverified): one line per pin whose ref lacks its path, and one
    per repo that could not be fetched, whose pins are then not checked. A repo
    missing from `remotes` is fetched from GitHub."""
    problems: list[str] = []
    unverified: list[str] = []
    with tempfile.TemporaryDirectory(prefix="template-pins-") as tmp:
        for repo in sorted({p.repo for p in pins}):
            url = remotes.get(repo, f"https://github.com/{repo}.git")
            store = Store(Path(tmp) / repo.replace("/", "_"), repo, url)
            theirs = [p for p in pins if p.repo == repo]
            err = store.fetch("+refs/tags/v*:refs/tags/v*")
            if err:
                unverified.append(f"{len(theirs)} pin(s) into {repo} not checked: {url} could not be fetched ({err})")
                continue
            problems += [f"{p.file}: {p.uses}: {why}" for p in theirs if (why := store.missing(p.ref, p.path))]
    return problems, unverified


# --- the hub as it is ------------------------------------------------------- #
def test_hub_callers_resolve_at_their_pins():
    pins, broken = pins_in(caller_files(HUB), HUB)
    assert not broken, f"not valid YAML, so its pins cannot be read: {', '.join(broken)}"
    assert pins, "no pinned bamr87/bamr87 or bamr87/.github `uses:` found; did the contract's regexes move?"
    problems, unverified = check(pins, {})
    assert not problems, "pinned at a ref that does not carry it:\n  " + "\n  ".join(problems)
    if unverified:
        raise Skip("; ".join(unverified))
    print(f"     {len(pins)} pin(s) in {len({p.file for p in pins})} caller(s) resolve on GitHub")


# --- fixtures --------------------------------------------------------------- #
GIT_CFG = ("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
           "-c", "tag.gpgsign=false", "-c", "core.hooksPath=/dev/null")
WF = "on: workflow_call\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: 'true'\n"
ACTION = "runs:\n  using: composite\n  steps: []\n"
HUB_WF = "bamr87/bamr87/.github/workflows"
HUB_ACTION = "bamr87/bamr87/.github/actions"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *GIT_CFG, *args], capture_output=True, text=True,
                          env=GIT_ENV, check=True).stdout.strip()


def make_repo(path: Path, commits: list[dict[str, str]]) -> list[str]:
    """A throwaway repository with one commit per {path: text} map, each on top
    of the last; returns the commit SHAs in order."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    shas = []
    for i, files in enumerate(commits):
        for rel, text in files.items():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            (path / rel).write_text(text, encoding="utf-8")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", f"commit {i}")
        shas.append(git(path, "rev-parse", "HEAD"))
    return shas


def tag(repo: Path, name: str, sha: str) -> None:
    """An annotated tag, as the hub cuts them; -f moves a floating one."""
    git(repo, "tag", "-f", "-a", name, "-m", name, sha)


class Fleet(NamedTuple):
    root: Path
    hub: Path
    shas: list[str]
    remotes: dict[str, str]


@contextlib.contextmanager
def fleet():
    """A throwaway hub whose v9 (and v9.0.0) predates new.yml and the `new`
    action, and a bamr87/.github whose v1 carries release-please.yml only."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        shas = make_repo(root / "hub", [
            {".github/workflows/old.yml": WF, ".github/actions/old/action.yml": ACTION,
             ".github/actions/yaml-only/action.yaml": ACTION, ".github/actions/bare/README.md": "# no metadata\n"},
            {".github/workflows/new.yml": WF, ".github/actions/new/action.yml": ACTION},
        ])
        tag(root / "hub", "v9", shas[0])
        tag(root / "hub", "v9.0.0", shas[0])
        dot = make_repo(root / "dotgithub", [{".github/workflows/release-please.yml": WF}])
        tag(root / "dotgithub", "v1", dot[0])
        yield Fleet(root, root / "hub", shas,
                    {"bamr87/bamr87": str(root / "hub"), "bamr87/.github": str(root / "dotgithub")})


def verdict(fx: Fleet, files: dict[str, str]) -> tuple[list[str], list[str]]:
    caller = fx.root / "caller"
    for rel, text in files.items():
        (caller / rel).parent.mkdir(parents=True, exist_ok=True)
        (caller / rel).write_text(text, encoding="utf-8")
    pins, broken = pins_in([caller / rel for rel in files], caller)
    assert not broken, broken
    return check(pins, fx.remotes)


def job(uses: str) -> str:
    return f"on: push\njobs:\n  gate:\n    uses: {uses}\n    secrets: inherit\n"


def steps(*uses: str) -> str:
    head = "on: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n"
    return head + "".join(f"      - uses: {u}\n" for u in uses)


def test_tag_lacking_the_workflow_fails_naming_the_file_and_the_tag():
    # The #457 shape: the template pins @v9, and the workflow landed after v9 was cut.
    with fleet() as fx:
        problems, unverified = verdict(fx, {"templates/kit/ci.yml": job(f"{HUB_WF}/new.yml@v9")})
    assert unverified == [], unverified
    assert problems == [f"templates/kit/ci.yml: {HUB_WF}/new.yml@v9: v9 has no .github/workflows/new.yml"], problems


def test_moving_the_floating_tag_onto_the_file_fixes_the_pin():
    with fleet() as fx:
        tag(fx.hub, "v9", fx.shas[1])
        problems, unverified = verdict(fx, {"templates/kit/ci.yml": job(f"{HUB_WF}/new.yml@v9")})
        assert (problems, unverified) == ([], []), (problems, unverified)
        problems, _ = verdict(fx, {"templates/kit/ci.yml": job(f"{HUB_WF}/new.yml@v9.0.0")})
    # The immutable tag stays where it was cut.
    want = f"templates/kit/ci.yml: {HUB_WF}/new.yml@v9.0.0: v9.0.0 has no .github/workflows/new.yml"
    assert problems == [want], problems


def test_workflows_and_actions_present_at_the_tag_pass():
    with fleet() as fx:
        problems, unverified = verdict(fx, {
            "templates/kit/ci.yml": job(f"{HUB_WF}/old.yml@v9"),
            "templates/kit/steps.yml": steps(f"{HUB_ACTION}/old@v9", f"{HUB_ACTION}/yaml-only@v9.0.0"),
            ".github/actions/setup/action.yml": ACTION.replace("steps: []", f"steps:\n    - uses: {HUB_ACTION}/old@v9"),
        })
    assert (problems, unverified) == ([], []), (problems, unverified)


def test_action_needs_its_metadata_file_at_the_tag():
    with fleet() as fx:
        problems, _ = verdict(fx, {"templates/kit/steps.yml": steps(f"{HUB_ACTION}/bare@v9", f"{HUB_ACTION}/new@v9")})
    assert problems == [
        f"templates/kit/steps.yml: {HUB_ACTION}/bare@v9: v9 has no .github/actions/bare/action.yml (nor action.yaml)",
        f"templates/kit/steps.yml: {HUB_ACTION}/new@v9: v9 has no .github/actions/new/action.yml (nor action.yaml)",
    ], problems


def test_a_tag_the_repo_does_not_have_fails():
    with fleet() as fx:
        problems, _ = verdict(fx, {"templates/kit/ci.yml": job(f"{HUB_WF}/old.yml@v8")})
    assert problems == [f"templates/kit/ci.yml: {HUB_WF}/old.yml@v8: bamr87/bamr87 has no tag v8"], problems


def test_full_sha_passes_only_when_that_commit_carries_the_path():
    with fleet() as fx:
        old, new = fx.shas
        absent = "0123456789abcdef" * 2 + "01234567"
        caller = steps(f"{HUB_ACTION}/new@{new}", f"{HUB_ACTION}/new@{old}", f"{HUB_ACTION}/old@{absent}")
        problems, _ = verdict(fx, {"templates/kit/ci.yml": caller})
    assert len(problems) == 2, problems
    assert problems[0] == (f"templates/kit/ci.yml: {HUB_ACTION}/new@{old}: "
                           f"{old} has no .github/actions/new/action.yml (nor action.yaml)"), problems
    assert problems[1].startswith(f"templates/kit/ci.yml: {HUB_ACTION}/old@{absent}: "
                                  f"bamr87/bamr87 has no commit {absent}"), problems


def test_dot_github_pins_resolve_in_their_own_repo():
    dot = "bamr87/.github/.github/workflows"
    with fleet() as fx:
        problems, unverified = verdict(fx, {"templates/kit/release.yml": job(f"{dot}/release-please.yml@v1")
                                            + f"  publish:\n    uses: {dot}/old.yml@v1\n"})
    assert unverified == [], unverified
    assert problems == [f"templates/kit/release.yml: {dot}/old.yml@v1: v1 has no .github/workflows/old.yml"], problems


def test_refs_that_are_not_pins_and_text_outside_uses_keys_are_not_read():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = root / "templates/kit/ci.yml"
        f.parent.mkdir(parents=True)
        f.write_text(
            f"# uses: {HUB_WF}/new.yml@v9\n"
            "on: push\njobs:\n"
            f"  gate:\n    uses: {HUB_WF}/new.yml@main\n"
            "  gen:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - run: |\n          echo 'uses: {HUB_WF}/new.yml@v9'\n"
            f"      - uses: actions/checkout@v7\n        with:\n          note: {HUB_WF}/new.yml@v9\n"
            f"      - uses: ./.github/actions/local\n", encoding="utf-8")
        pins, broken = pins_in([f], root)
    assert (pins, broken) == ([], []), (pins, broken)


def test_unreachable_repo_is_unverified_never_passed():
    with fleet() as fx:
        caller = fx.root / "caller.yml"
        caller.write_text(job(f"{HUB_WF}/new.yml@v9"), encoding="utf-8")
        pins, _ = pins_in([caller], fx.root)
        problems, unverified = check(pins, {"bamr87/bamr87": str(fx.root / "no-such-repo")})
    assert problems == [], problems
    assert len(unverified) == 1 and unverified[0].startswith("1 pin(s) into bamr87/bamr87 not checked:"), unverified


def test_scope_is_the_seeded_templates_and_the_hub_pin_scope():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()
        for rel in ("templates/kit/ci.yml", "templates/kit/sub/release.yaml", "templates/kit/archive/ci-0.1.0.yml",
                    "templates/site/fixtures/configs/x.yml", "templates/kit/README.md", ".github/workflows/w.yml",
                    ".github/actions/setup/action.yml", ".github/dependabot.yml"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("on: push\n", encoding="utf-8")
        got = [str(p.relative_to(root)) for p in caller_files(root)]
    assert got == ["templates/kit/ci.yml", "templates/kit/sub/release.yaml", ".github/actions/setup/action.yml",
                   ".github/workflows/w.yml"], got


def test_a_caller_that_is_not_yaml_is_reported():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = root / "templates/kit/ci.yml"
        f.parent.mkdir(parents=True)
        f.write_text(f"jobs: [\n  - uses: {HUB_WF}/new.yml@v9\n", encoding="utf-8")
        assert pins_in([f], root) == ([], ["templates/kit/ci.yml"])


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = skipped = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Skip as e:
            skipped += 1
            print(f"skip {t.__name__}: {e}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    raise SystemExit(1 if failed else 0)

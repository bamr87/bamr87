#!/usr/bin/env python3
"""
Fixture tests for reconcile.py.

Guards the invariant the whole design rests on: `--apply` must write the
authoritative fixes and must NEVER touch the ambiguous ones. A 404 that
auto-deregistered a submodule would eventually delete a live project, because a
repo-scoped token 404s on a *private* repo exactly as it does on a deleted one.

Deliberately dependency-light — the GitHub client is stubbed, so this needs only
PyYAML and runs on a bare interpreter:

    python3 .github/scripts/dash-gen/test_reconcile.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reconcile  # noqa: E402

REGISTRY_FIXTURE = """\
- name: alive
  slug: alive
  submodule_path: projects/alive
  branch: main
  repo_url: https://github.com/bamr87/it-journey
  description: fine   # this comment must survive a surgical rewrite
- name: gone
  slug: gone
  submodule_path: projects/gone
  branch: main
  repo_url: https://github.com/bamr87/THIS-REPO-DOES-NOT-EXIST-xyz
- name: mismatch
  slug: mismatch
  submodule_path: projects/mismatch
  branch: main
  repo_url: https://github.com/bamr87/scripts
- name: moved
  slug: moved
  submodule_path: projects/moved
  branch: main
  repo_url: https://github.com/bamr87/oldname
"""

GITMODULES_FIXTURE = """\
[submodule "projects/alive"]
\tpath = projects/alive
\turl = https://github.com/bamr87/it-journey.git
\tbranch = main
[submodule "projects/gone"]
\tpath = projects/gone
\turl = https://github.com/bamr87/THIS-REPO-DOES-NOT-EXIST-xyz.git
\tbranch = main
[submodule "projects/mismatch"]
\tpath = projects/mismatch
\turl = https://github.com/bamr87/WRONG-URL.git
\tbranch = main
[submodule "projects/moved"]
\tpath = projects/moved
\turl = https://github.com/bamr87/oldname.git
\tbranch = main
"""


class _Repo:
    def __init__(self, full_name: str, default_branch: str):
        self.full_name, self.default_branch = full_name, default_branch


class _NotFound(Exception):
    status = 404


class _FakeGitHub:
    """Deterministic stand-in for PyGithub: one repo per drift class."""

    def get_repo(self, nwo: str):
        if "DOES-NOT-EXIST" in nwo:
            raise _NotFound()
        if nwo.endswith("/oldname"):
            return _Repo("bamr87/newname", "main")   # renamed
        if nwo.endswith("/scripts"):
            return _Repo(nwo, "master")              # branch drift
        return _Repo(nwo, "main")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    reg_path, gm_path = tmp / "projects.yml", tmp / ".gitmodules"
    reg_path.write_text(REGISTRY_FIXTURE, encoding="utf-8")
    gm_path.write_text(GITMODULES_FIXTURE, encoding="utf-8")

    failures: list[str] = []

    def check(label: str, cond: bool) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    mods = reconcile.parse_gitmodules(gm_path)
    registry = reconcile.load_registry(reg_path)
    findings = reconcile.collect(_FakeGitHub(), registry, mods)
    seen = {(f.kind, f.name) for f in findings}

    print("detection:")
    for kind, name in (("missing", "gone"), ("url-mismatch", "mismatch"),
                       ("renamed", "moved"), ("branch-drift", "mismatch")):
        check(f"detects {kind} on '{name}'", (kind, name) in seen)

    before = reg_path.read_text(encoding="utf-8")
    reconcile.apply_fixes(findings, mods, registry_path=reg_path, gitmodules_path=gm_path)
    after = reg_path.read_text(encoding="utf-8")

    print("apply safety:")
    check("404 entry is NOT rewritten",
          "https://github.com/bamr87/THIS-REPO-DOES-NOT-EXIST-xyz" in after)
    check("renamed entry IS rewritten", "https://github.com/bamr87/newname" in after)
    check("branch value is NOT auto-changed", "branch: main" in after)
    check("inline comment survives", "# this comment must survive" in after)
    check("edit is surgical (line count stable)",
          len(before.splitlines()) == len(after.splitlines()))

    shutil.rmtree(tmp)
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'OK'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

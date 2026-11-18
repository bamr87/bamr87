#!/usr/bin/env python3
"""
The two roots of tools/conformance.py (docs/adr/0011): the FRAMEWORK checkout
(`--hub`: the spec, the contracts, the kits, the tools) and the INSTANCE
(`--instance` / $FLEET_HOME: the control plane whose registry lists the repos).

An instance here is a throwaway directory holding only its own registry and one
tiny repository, owned by a made-up `acme` account. The framework is this
checkout. The tests hold four things: an instance needs nothing of the
framework's inside it, the registry read is the instance's alone, an instance's
own standards win over the framework's, and with no instance named the checker
behaves as it always did (one root).

No network, no pytest. Needs PyYAML and git:

    python3 tools/test_conformance_instance.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
CHECKER = HUB / "tools" / "conformance.py"

REGISTRY = [{
    "name": "demo", "slug": "demo", "submodule_path": "projects/demo", "branch": "main",
    "repo_url": "https://github.com/acme/demo", "description": "A demo repository.",
    "stack": ["python"], "category": "dev-tools", "status": "active",
    "frontend": {"type": "none", "tier": "none", "framework": "none", "surfaces": [],
                 "token_version": "none", "entry_url": None, "shell": "none"},
}]


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True)


def instance(tmp: Path, standards: dict | None = None) -> Path:
    """An instance that owns one repo and carries none of the framework's files."""
    inst = tmp / "acme-hub"
    (inst / "_data").mkdir(parents=True)
    (inst / "_data" / "projects.yml").write_text(yaml.safe_dump(REGISTRY, sort_keys=False), encoding="utf-8")
    if standards is not None:
        (inst / "_data" / "standards.yml").write_text(yaml.safe_dump(standards), encoding="utf-8")
    repo = inst / "projects" / "demo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("# demo\n\n> A demo repository.\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://github.com/acme/demo.git")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c")
    return inst


def fleet_json(inst: Path | None) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = c.fleet(HUB, None, True, inst)
    assert rc == 0
    return json.loads(buf.getvalue())


class TwoRoots(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_no_instance_named_is_the_single_root(self):
        self.assertEqual(c.Repo(self.tmp, HUB).instance, HUB.resolve())
        self.assertEqual(c.Repo(self.tmp, HUB, None).hub, HUB.resolve())

    def test_fleet_checks_the_instances_registry_and_nothing_else(self):
        out = fleet_json(instance(self.tmp))
        self.assertEqual([r["name"] for r in out["repos"]], ["demo"])
        self.assertEqual(out["repos"][0]["nwo"], "acme/demo")
        self.assertEqual(out["repos"][0]["path"], "projects/demo")

    def test_an_instance_needs_none_of_the_frameworks_files(self):
        inst = instance(self.tmp)
        self.assertEqual(sorted(p.name for p in (inst / "_data").iterdir()), ["projects.yml"])
        row = fleet_json(inst)["repos"][0]
        self.assertGreater(row["checked"], 20, "the framework's spec was not applied")
        # The framework's own tools back the checks: nothing reports a hub file as missing.
        missing = [u["detail"] for u in row.get("unverified", []) if "not found" in u["detail"]]
        self.assertEqual(missing, [])

    def test_tier_comes_from_the_frameworks_standards_by_default(self):
        self.assertEqual(fleet_json(instance(self.tmp))["repos"][0]["tier"], "active")

    def test_an_instances_own_standards_win(self):
        inst = instance(self.tmp, standards={"status_tier": {"active": "experiment"}})
        self.assertEqual(fleet_json(inst)["repos"][0]["tier"], "experiment")

    def test_registry_entry_is_read_from_the_instance(self):
        inst = instance(self.tmp)
        repo = inst / "projects" / "demo"
        self.assertEqual(c.registry_entry(c.Repo(repo, HUB, inst))["name"], "demo")
        # One root: the framework checkout's registry has no acme/demo.
        self.assertIsNone(c.registry_entry(c.Repo(repo, HUB)))

    def test_fleet_home_selects_the_instance_from_the_command_line(self):
        inst = instance(self.tmp)
        env = dict(os.environ, FLEET_HOME=str(inst))
        p = subprocess.run([sys.executable, str(CHECKER), "fleet", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        self.assertEqual([r["name"] for r in json.loads(p.stdout)["repos"]], ["demo"])

    def test_write_lands_in_the_instance_never_in_the_framework(self):
        inst = instance(self.tmp)
        snapshot = HUB / "_data" / "conformance.yml"
        before = hashlib.sha256(snapshot.read_bytes()).hexdigest() if snapshot.is_file() else None
        env = {k: v for k, v in os.environ.items() if k != "FLEET_HOME"}
        p = subprocess.run([sys.executable, str(CHECKER), "fleet", "--instance", str(inst), "--write"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        written = yaml.safe_load((inst / "_data" / "conformance.yml").read_text(encoding="utf-8"))
        self.assertEqual([r["name"] for r in written["repos"]], ["demo"])
        after = hashlib.sha256(snapshot.read_bytes()).hexdigest() if snapshot.is_file() else None
        self.assertEqual(before, after, "the framework checkout's snapshot was rewritten")


if __name__ == "__main__":
    unittest.main(verbosity=1)

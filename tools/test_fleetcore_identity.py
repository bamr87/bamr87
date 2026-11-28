#!/usr/bin/env python3
"""Tests for tools/fleetcore/identity.py — who an instance is, read once from its
settings (ADR 0011 decision 2), and the modules that ask it.
Offline, no pytest:  python3 tools/test_fleetcore_identity.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import clouds, graph, identity, learn, stars  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
REPO, HOME = identity.ENV_REPO, identity.ENV_HOME


def environment(**extra) -> dict:
    """This process's environment without the two variables the resolver reads (CI sets one), plus `extra`."""
    return {k: v for k, v in os.environ.items() if k not in (REPO, HOME)} | extra

# A made-up instance: nothing here may depend on who owns this checkout.
SETTINGS = {"hub": {"repo": "Acme/control", "shared": "acme/.shared", "default_branch": "trunk", "bot_name": "acme-bot",
                    "bot_email": "bot@acme.test", "site": "https://acme.test/control/", "owners": ["Acme", "acme-labs"]}}


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def instance(root: Path, settings: dict | None) -> Path:
    """A control plane that holds only its settings (none when `settings` is None)."""
    root.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        write(root, "_data/fleet.yml", yaml.safe_dump(settings))
    return root


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.inst = instance(self.tmp / "instance", SETTINGS)
        self.bare = instance(self.tmp / "bare", None)


class SettingsTests(Fixture):
    def test_the_committed_settings_resolve(self):
        hub = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))["hub"]
        who = identity.resolve(HUB, env={})
        self.assertEqual((who.repo, who.source), (hub["repo"], "settings"))
        self.assertEqual(f"{who.owner}/{who.name}", hub["repo"])
        self.assertEqual(list(who.owners), [str(o).lower() for o in hub["owners"]])
        self.assertIn(who.owner.lower(), who.owners, "the hub's own owner is one of the fleet's owners")
        self.assertEqual((who.shared, who.default_branch, who.bot_name, who.bot_email),
                         (hub["shared"], hub["default_branch"], hub["bot_name"], hub["bot_email"]))
        self.assertEqual(who.site, str(hub.get("site") or ""), "a site only when the settings give one")
        self.assertTrue(who.owned(hub["repo"]) and who.owned(hub["shared"]))

    def test_every_key_is_read_from_the_hub_block(self):
        who = identity.from_settings(SETTINGS)
        self.assertEqual(who.as_dict(), {
            "repo": "Acme/control", "owner": "Acme", "name": "control", "owners": ["acme", "acme-labs"],
            "shared": "acme/.shared", "default_branch": "trunk", "bot_name": "acme-bot", "bot_email": "bot@acme.test",
            "site": "https://acme.test/control/", "source": "settings"})
        self.assertEqual(set(who.as_dict()), set(identity.KEYS), "the CLI answers every key the record has")

    def test_owners_are_lower_cased_once_each_and_kept_as_written(self):
        who = identity.from_settings({"hub": {"repo": "a/hub", "owners": ["Org", "a", "ORG", " ", None]}})
        self.assertEqual(who.owners, ("org", "a"))
        self.assertEqual(who.declared_owners, ("Org", "a", "ORG"), "what the settings wrote, for a caller that shows it")

    def test_with_no_owners_declared_the_owner_of_the_repo_is_the_fleet(self):
        for hub in ({"repo": "Solo/hub"}, {"repo": "Solo/hub", "owners": []}, {"repo": "Solo/hub", "owners": None}):
            who = identity.from_settings({"hub": hub})
            self.assertEqual((who.owners, who.declared_owners), (("solo",), ()), hub)

    def test_one_owner_written_as_a_scalar_is_one_owner(self):
        self.assertEqual(identity.from_settings({"hub": {"repo": "a/hub", "owners": "Org"}}).owners, ("org",))

    def test_the_default_branch_is_main_and_the_rest_is_empty_until_set(self):
        who = identity.from_settings({"hub": {"repo": "a/hub"}})
        self.assertEqual((who.default_branch, who.shared, who.bot_name, who.bot_email, who.site), ("main", "", "", "", ""))

    def test_settings_that_are_not_a_mapping_declare_nothing(self):
        for fleet in (None, [], "text", {}, {"hub": None}, {"hub": "a/hub"}, {"hub": ["a/hub"]}, {"hub": {"repo": {"x": 1}}}):
            who = identity.from_settings(fleet)
            self.assertEqual((who.repo, who.owners, who.source), ("", (), "none"), fleet)

    def test_from_settings_never_reads_the_environment(self):
        with mock.patch.dict(os.environ, {REPO: "env/hub", HOME: str(self.inst)}):
            self.assertEqual(identity.from_settings({}).source, "none")
            self.assertEqual(identity.from_settings({"hub": {"owners": ["a"]}}).repo, "")


class FallbackTests(Fixture):
    def test_no_repository_in_the_settings_falls_back_to_the_environment(self):
        who = identity.resolve(self.bare, env={REPO: "Env-Org/control-plane"})
        self.assertEqual((who.repo, who.owner, who.name, who.owners, who.source),
                         ("Env-Org/control-plane", "Env-Org", "control-plane", ("env-org",), "environment"))
        self.assertTrue(who.owned("env-org/anything"))

    def test_the_settings_win_over_the_environment(self):
        who = identity.resolve(self.inst, env={REPO: "env/hub"})
        self.assertEqual((who.repo, who.source), ("Acme/control", "settings"))

    def test_owners_the_settings_declare_survive_the_fallback(self):
        inst = instance(self.tmp / "owners-only", {"hub": {"owners": ["one", "two"], "bot_name": "b"}})
        who = identity.resolve(inst, env={REPO: "env/hub"})
        self.assertEqual((who.repo, who.owners, who.bot_name, who.source), ("env/hub", ("one", "two"), "b", "environment"))

    def test_with_neither_it_says_so_and_invents_no_owner(self):
        for root in (self.bare, instance(self.tmp / "other-keys", {"images": {"python": "3.12"}})):
            who = identity.resolve(root, env={})
            self.assertEqual((who.repo, who.owner, who.name, who.owners, who.source), ("", "", "", (), "none"))
            self.assertFalse(who.owned("anyone/anything"), "nothing is the fleet's when no owner is known")

    def test_settings_that_do_not_parse_are_read_as_absent(self):
        broken = self.tmp / "broken"
        write(broken, "_data/fleet.yml", "hub: [unclosed\n")
        self.assertEqual(identity.resolve(broken, env={}).source, "none")
        self.assertEqual(identity.resolve(broken, env={REPO: "env/hub"}).source, "environment")

    def test_the_process_environment_is_the_default_and_an_empty_one_switches_it_off(self):
        with mock.patch.dict(os.environ, {REPO: "proc/hub"}):
            self.assertEqual(identity.resolve(self.bare).repo, "proc/hub")
            self.assertEqual(identity.resolve(self.bare, env={}).repo, "")
        with mock.patch.dict(os.environ, environment(), clear=True):
            self.assertEqual(identity.resolve(self.bare).source, "none")


class OwnedTests(unittest.TestCase):
    WHO = identity.from_settings(SETTINGS)

    def test_a_slug_or_a_github_address_of_an_owner_is_owned(self):
        for repo in ("acme/site", "Acme/Site", "ACME-LABS/x", "acme/site.git", "acme/control/.github/workflows/ci.yml@v2",
                     "https://github.com/acme/site", "https://github.com/Acme/site.git", "https://github.com/acme/site/",
                     "http://www.github.com/acme-labs/x", "https://github.com/acme/site/issues/3", "github.com/acme/site",
                     "git@github.com:acme/site.git", "ssh://git@github.com/acme-labs/x.git", "  acme/site  "):
            self.assertTrue(self.WHO.owned(repo), repo)

    def test_another_owner_is_not(self):
        for repo in ("someone/site", "https://github.com/someone/site.git", "git@github.com:someone/site.git",
                     "acme-labs-fork/x", "notacme/site", "acmee/site"):
            self.assertFalse(self.WHO.owned(repo), repo)

    def test_an_address_on_another_host_is_not_the_fleets(self):
        for repo in ("https://gitlab.com/acme/site", "git@gitlab.com:acme/site.git", "https://github.com.evil.test/acme/site",
                     "https://evil.test/github.com/acme/site", "https://github.com@evil.test/acme/site",
                     "https://api.github.com/repos/acme/site", "evil.test/acme/site"):
            self.assertFalse(self.WHO.owned(repo), repo)

    def test_what_names_no_repository_is_not_owned(self):
        for repo in ("", None, "acme", "acme/", "/", "https://github.com/acme", "https://github.com/", 7, ["acme/site"]):
            self.assertFalse(self.WHO.owned(repo), repo)
            self.assertEqual(identity.owner_of(repo), "", repo)

    def test_owner_of_reads_the_owner_and_lower_cases_it(self):
        self.assertEqual(identity.owner_of("https://github.com/Some-Org/Repo.git"), "some-org")
        self.assertEqual(identity.owner_of("Some-Org/Repo"), "some-org")

    def test_the_module_function_resolves_then_asks(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = instance(Path(tmp), SETTINGS)
            self.assertTrue(identity.owned("acme-labs/x", inst, env={}))
            self.assertFalse(identity.owned("someone/x", inst, env={}))


class InstanceTests(Fixture):
    """ADR 0011 decision 1: FLEET_HOME names the instance root, a tool that takes a path takes --instance."""

    def test_the_root_is_an_argument_so_the_same_code_answers_for_another_instance(self):
        here, there = identity.resolve(HUB, env={}), identity.resolve(self.inst, env={})
        self.assertEqual(there.repo, "Acme/control")
        self.assertNotEqual(here.repo, there.repo)
        self.assertEqual(identity.resolve(str(self.inst), env={}), there, "a path as text is the same root")

    def test_fleet_home_names_the_instance_when_no_root_is_given(self):
        self.assertEqual(identity.home({HOME: str(self.inst)}), self.inst)
        self.assertEqual(identity.home({}), identity.HUB, "with neither, the instance root is this checkout")
        self.assertEqual(identity.home({HOME: "  "}), identity.HUB)
        self.assertEqual(identity.resolve(env={HOME: str(self.inst)}).repo, "Acme/control")
        self.assertEqual(identity.resolve(env={}), identity.resolve(HUB, env={}))
        with mock.patch.dict(os.environ, {HOME: str(self.inst)}):
            self.assertEqual(identity.resolve().repo, "Acme/control")

    def test_a_named_root_wins_over_fleet_home(self):
        other = instance(self.tmp / "other", {"hub": {"repo": "other/hub"}})
        self.assertEqual(identity.resolve(other, env={HOME: str(self.inst)}).repo, "other/hub")


class CliTests(Fixture):
    def run_cli(self, *argv, env: dict | None = None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environment(**(env or {})), clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = identity.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_show_prints_every_key(self):
        code, out, err = self.run_cli("--instance", str(self.inst))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "repo=Acme/control", "owner=Acme", "name=control", "owners=acme acme-labs", "shared=acme/.shared",
            "default_branch=trunk", "bot_name=acme-bot", "bot_email=bot@acme.test", "site=https://acme.test/control/",
            "source=settings"])
        self.assertEqual([line.split("=", 1)[0] for line in out.splitlines()], list(identity.KEYS))
        self.assertEqual(self.run_cli("show", "--instance", str(self.inst))[1], out, "show is the default")

    def test_get_prints_one_value_for_a_script(self):
        for key, value in (("repo", "Acme/control"), ("owner", "Acme"), ("name", "control"), ("owners", "acme acme-labs"),
                           ("shared", "acme/.shared"), ("default_branch", "trunk"), ("bot_name", "acme-bot"),
                           ("bot_email", "bot@acme.test"), ("site", "https://acme.test/control/"), ("source", "settings")):
            self.assertEqual(self.run_cli("get", key, "--instance", str(self.inst)), (0, value + "\n", ""), key)

    def test_get_of_a_key_with_no_value_fails_and_says_why(self):
        inst = instance(self.tmp / "thin", {"hub": {"repo": "thin/hub"}})
        code, out, err = self.run_cli("get", "bot_email", "--instance", str(inst))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no bot_email", err)
        self.assertIn("hub.bot_email", err)
        code, out, err = self.run_cli("get", "repo", "--instance", str(self.bare))
        self.assertEqual((code, out), (1, ""))
        self.assertIn(f"names no `hub.repo` and {REPO} is not set", err)
        self.assertEqual(self.run_cli("get", "nothing", "--instance", str(self.inst))[0], 2)
        self.assertEqual(self.run_cli("get", "--instance", str(self.inst))[0], 2)

    def test_owned_answers_with_its_exit_code(self):
        code, out, _ = self.run_cli("owned", "https://github.com/acme-labs/x.git", "--instance", str(self.inst))
        self.assertEqual((code, out), (0, "owned: acme-labs is one of the fleet's owners\n"))
        code, out, _ = self.run_cli("owned", "someone/x", "--instance", str(self.inst))
        self.assertEqual((code, out), (1, "not owned: someone is not one of acme, acme-labs\n"))
        code, out, _ = self.run_cli("owned", "someone", "--instance", str(self.inst))
        self.assertEqual(code, 1)
        self.assertIn("names no GitHub owner", out)
        code, out, _ = self.run_cli("owned", "acme/x", "--instance", str(self.bare))
        self.assertEqual(code, 1)
        self.assertIn("no owner is known", out)
        self.assertEqual(self.run_cli("owned", "--instance", str(self.inst))[0], 2)

    def test_json_is_the_document(self):
        code, out, _ = self.run_cli("json", "--instance", str(self.inst))
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((doc["schema"], doc["instance"]), ("fleet-identity/v1", str(self.inst)))
        self.assertEqual({k: doc[k] for k in identity.KEYS}, identity.from_settings(SETTINGS).as_dict())

    def test_no_identity_is_an_error_that_still_prints_the_keys(self):
        code, out, err = self.run_cli("--instance", str(self.bare))
        self.assertEqual(code, 1)
        self.assertIn("repo=\n", out)
        self.assertIn("source=none\n", out)
        self.assertIn("no identity", err)
        self.assertEqual(self.run_cli("json", "--instance", str(self.bare))[0], 1)

    def test_the_environment_answers_when_the_settings_do_not(self):
        code, out, _ = self.run_cli("--instance", str(self.bare), env={REPO: "env/hub"})
        self.assertEqual(code, 0)
        self.assertIn("repo=env/hub\n", out)
        self.assertIn("owners=env\n", out)
        self.assertIn("source=environment\n", out)

    def test_fleet_home_is_the_default_instance(self):
        self.assertEqual(self.run_cli("get", "repo", env={HOME: str(self.inst)}), (0, "Acme/control\n", ""))
        other = instance(self.tmp / "other", {"hub": {"repo": "other/hub"}})
        self.assertEqual(self.run_cli("get", "repo", "--instance", str(other), env={HOME: str(self.inst)})[1], "other/hub\n")

    @unittest.skipUnless(shutil.which("bash"), "tools/dash is a bash script")
    def test_the_shell_twin_is_the_same_implementation(self):
        dash = (HUB / "tools" / "dash").read_text(encoding="utf-8")
        self.assertIn("identity) cmd_identity", dash)
        self.assertIn('-m fleetcore.identity "$@"', dash)
        env = environment(PYTHON=sys.executable)

        def sh(*argv, cwd=HUB, extra=None):
            return subprocess.run([str(HUB / "tools" / "dash"), "identity", *argv], capture_output=True, text=True,
                                  cwd=cwd, env=env | (extra or {}), check=False)

        got = sh("get", "owners", "--instance", str(self.inst))
        self.assertEqual((got.returncode, got.stdout), (0, "acme acme-labs\n"), got.stderr)
        self.assertEqual(sh("get", "repo").stdout.strip(), identity.resolve(HUB, env={}).repo)
        # A path is relative to where the caller stands, not to tools/.
        self.assertEqual(sh("get", "repo", "--instance", "instance", cwd=self.tmp).stdout, "Acme/control\n")
        self.assertEqual(sh("get", "repo", extra={HOME: str(self.inst)}).stdout, "Acme/control\n")
        self.assertEqual(sh("owned", "someone/x", "--instance", str(self.inst)).returncode, 1)
        self.assertEqual(sh("get", "repo", "--instance", str(self.bare)).returncode, 1)


class NeutralityTests(unittest.TestCase):
    def test_the_resolver_names_no_owner(self):
        source = (HUB / "tools" / "fleetcore" / "identity.py").read_text(encoding="utf-8").lower()
        for owner in identity.resolve(HUB, env={}).owners:
            self.assertNotIn(owner, source, f"tools/fleetcore/identity.py names the owner '{owner}': it reads owners, it holds none")

    def test_it_loads_and_answers_without_pyyaml(self):
        # stars.py asks from_settings(), and the SessionStart hook loads stars.py on a bare interpreter.
        code = ("import sys; sys.modules['yaml'] = None; sys.path.insert(0, sys.argv[1]); "
                "from fleetcore import identity, stars; "
                "print(identity.from_settings({'hub': {'repo': 'a/hub'}}).owners[0], stars.config({'hub': {'owners': ['Z']}})['account'])")
        got = subprocess.run([sys.executable, "-c", code, str(HUB / "tools")], capture_output=True, text=True, check=False)
        self.assertEqual((got.returncode, got.stdout.split()), (0, ["a", "Z"]), got.stderr)


class AdoptionTests(Fixture):
    """The core modules that used to work the identity out by hand ask the resolver for what the
    settings declare. Each keeps its own default where it had one, and none reads the environment:
    a module's answer is the same on every host."""

    REGISTRY = [
        {"name": "site", "repo_url": "https://github.com/acme/site", "status": "active", "submodule_path": "projects/site"},
        {"name": "lab", "repo_url": "https://github.com/Acme-Labs/lab.git", "status": "active", "submodule_path": "projects/lab"},
        {"name": "mirror", "repo_url": "https://github.com/someone/mirror", "status": "active", "submodule_path": "projects/mirror"},
    ]

    def root(self, name: str, settings: dict | None) -> Path:
        root = instance(self.tmp / name, settings)
        write(root, "_data/projects.yml", yaml.safe_dump(self.REGISTRY))
        for row in self.REGISTRY:
            write(root, f"{row['submodule_path']}/.git", "gitdir: x\n")
        return root

    def observe(self, root: Path) -> dict:
        fleet = identity.load_settings(root)
        g = graph.build(root, parts=("registry",))
        cfg = stars.config(fleet)
        read, _, external, slug = clouds.targets(root)
        return {"graph": (g.hub, sorted(n["id"] for n in g.nodes.values() if n["attrs"].get("external"))),
                "learn": learn.registry_arms(root, fleet), "stars": (cfg["account"], cfg["owners"]),
                "clouds": (slug, [r["repo"] for r in read], external)}

    def test_declared_owners_decide_what_is_the_fleets_in_every_module(self):
        got = self.observe(self.root("declared", SETTINGS))
        self.assertEqual(got, {
            "graph": ("Acme/control", ["repo:someone/mirror"]),
            "learn": ["Acme-Labs/lab", "acme/site"],
            "stars": ("Acme", ["acme", "acme-labs"]),
            "clouds": ("Acme/control", ["Acme/control", "acme/site", "Acme-Labs/lab"], 1)})

    def test_each_module_keeps_its_own_default_and_none_reads_the_environment(self):
        root = self.root("no-hub", {"images": {"python": "3.12"}})
        with mock.patch.dict(os.environ, {REPO: "env/hub", HOME: str(self.inst)}):
            got = self.observe(root)
        with mock.patch.dict(os.environ, environment(), clear=True):
            self.assertEqual(got, self.observe(root), "the same answer with and without GITHUB_REPOSITORY and FLEET_HOME")
        self.assertEqual(got["graph"][0], graph.HUB_DEFAULT, "the graph's default hub is its own constant")
        self.assertEqual(got["learn"], ["Acme-Labs/lab", "acme/site", "someone/mirror"], "no owners declared: nothing is filtered")
        self.assertEqual(got["clouds"], ("", ["acme/site", "Acme-Labs/lab", "someone/mirror"], 0), "no hub named: no hub row, no filter")
        self.assertNotIn("env/hub", json.dumps(got))

    def test_a_repo_with_no_owners_declared_is_the_owner_of_the_hub(self):
        got = self.observe(self.root("repo-only", {"hub": {"repo": "acme/control"}}))
        self.assertEqual(got["graph"], ("acme/control", ["repo:acme-labs/lab", "repo:someone/mirror"]))
        self.assertEqual(got["clouds"], ("acme/control", ["acme/control", "acme/site"], 2))
        self.assertEqual(got["learn"], ["Acme-Labs/lab", "acme/site", "someone/mirror"], "learning filters on declared owners only")


if __name__ == "__main__":
    unittest.main()

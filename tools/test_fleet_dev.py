#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_fleet_dev.py
# Description:   Tests for the fleet dev stack's launcher (tools/fleet-dev.sh)
#                and its smoke test (tools/fleet_smoke.py): every compose-hosted
#                project selects a service, compose profiles reach compose as
#                global flags, the hub is found under the compose project that
#                is running, and `check` holds what is deployed.
#                Bare interpreter + PyYAML; no network, no Docker (a stub
#                `docker` records what the launcher would have run).
# Author:        bamr87
# Created:       2026-11-17
# Last Modified: 2026-11-17
# Version:       1.0.0
# Usage:         python3 tools/test_fleet_dev.py
#                run by tools/run-all-tests.sh
# ============================================================================
#
# Each test is something a local deploy of the workspace found on 2026-11-17:
# `dash dev up zer0-cms` answered "no service selected", the smoke test called
# a healthy console absent, and a check with only part of the fleet up reported
# every project nobody had started as a regression.

import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fleet_smoke as fs  # noqa: E402

with open(os.path.join(ROOT, "_data", "ports.yml"), encoding="utf-8") as fh:
    PORTS = yaml.safe_load(fh)
PROJECTS = PORTS["projects"]


def compose_projects():
    """Compose-hosted projects whose submodule is checked out here."""
    for name, spec in PROJECTS.items():
        if (spec or {}).get("host") != "compose":
            continue
        path = os.path.join(ROOT, spec["compose"])
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                yield name, spec, yaml.safe_load(fh) or {}


def service_profile_list(svc):
    prof = (svc or {}).get("profiles") or []
    return [str(p) for p in prof] if isinstance(prof, list) else [str(prof)]


class RegistryProfiles(unittest.TestCase):
    """`profiles:` in _data/ports.yml — what `dash dev up <project>` activates."""

    def test_every_compose_project_starts_something(self):
        # zer0-cms puts every service behind a profile; a bare `up` selected none.
        seen = 0
        for name, spec, doc in compose_projects():
            seen += 1
            active = {str(p) for p in spec.get("profiles") or []}
            started = [s for s, body in (doc.get("services") or {}).items()
                       if not service_profile_list(body) or active & set(service_profile_list(body))]
            self.assertTrue(started, f"`dash dev up {name}` would select no service: "
                                     f"every one is behind a profile and ports.yml activates {sorted(active) or 'none'}")
        if not seen:
            self.skipTest("no compose-hosted submodule is checked out")

    def test_a_registry_profile_exists_in_the_compose_file(self):
        # A typo here is silent: compose accepts an unknown profile and starts nothing for it.
        for name, spec, doc in compose_projects():
            declared = {p for body in (doc.get("services") or {}).values() for p in service_profile_list(body)}
            for prof in spec.get("profiles") or []:
                self.assertIn(str(prof), declared, f"{name}: ports.yml activates profile {prof!r}, "
                                                   f"which no service in {spec['compose']} declares")


class Launcher(unittest.TestCase):
    """tools/fleet-dev.sh, with a stub `docker` that writes down its arguments."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fleet-dev-")
        self.log = os.path.join(self.tmp, "argv.log")
        stub = os.path.join(self.tmp, "docker")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FLEET_DEV_TEST_LOG"\nexit 0\n')
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def run_dev(self, *args):
        if not os.path.isfile(os.path.join(ROOT, PROJECTS["zer0-cms"]["compose"])):
            self.skipTest("projects/zer0-cms is not checked out")
        env = dict(os.environ, PATH=self.tmp + os.pathsep + os.environ["PATH"],
                   FLEET_DEV_TEST_LOG=self.log, PYTHON=sys.executable)
        proc = subprocess.run(["bash", os.path.join(HERE, "fleet-dev.sh"), *args],
                              capture_output=True, text=True, env=env, timeout=120)
        calls = []
        if os.path.exists(self.log):
            with open(self.log, encoding="utf-8") as fh:
                calls = [line.split() for line in fh.read().splitlines() if line.startswith("compose ")]
        return proc, calls

    def test_the_registry_profile_reaches_compose_before_the_subcommand(self):
        # `--profile` is a global compose flag: after `up` it is an error, and
        # only before it do ps, logs and down see the same services as up.
        proc, calls = self.run_dev("config", "zer0-cms")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(calls), 1, calls)
        argv = calls[0]
        self.assertIn("--profile", argv)
        self.assertEqual(argv[argv.index("--profile") + 1], "content")
        self.assertLess(argv.index("--profile"), argv.index("config"))

    def test_a_command_line_profile_is_added_to_the_registry_ones(self):
        for form in (("--profile", "imagegen"), ("--profile=imagegen",)):
            with self.subTest(form=form):
                if os.path.exists(self.log):
                    os.remove(self.log)
                proc, calls = self.run_dev("config", "zer0-cms", *form)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                argv = calls[0]
                given = [argv[i + 1] for i, a in enumerate(argv) if a == "--profile"]
                self.assertEqual(given, ["content", "imagegen"])
                self.assertEqual(argv[-1], "config", "the profile name leaked into the subcommand's arguments")

    def test_a_project_without_profiles_gets_none(self):
        proc, calls = self.run_dev("config", "gitorio")
        if not calls:
            self.skipTest("projects/gitorio is not checked out")
        self.assertNotIn("--profile", calls[0])

    def test_profile_without_a_name_is_refused(self):
        proc, calls = self.run_dev("config", "zer0-cms", "--profile")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(calls, "compose ran although --profile had no name")


def fact(name, state="running", health=None):
    return {"container": name, "state": state, "health": health, "image": "img", "status": ""}


class SmokeTopology(unittest.TestCase):
    """Where fleet_smoke.py looks for a project's containers."""

    def test_the_hub_is_found_under_the_core_project(self):
        # `tools/dash up` runs the hub as compose project `fleet`; only `dash dev
        # up hub` makes it `fleet-hub`. Reading `fleet-hub` alone called a
        # healthy console absent.
        live = {"fleet": {"console": fact("fleet-console-1", health="healthy")}}
        self.assertEqual(fs.project_label("bamr87", live), "fleet")
        self.assertEqual(fs.projects_up(PORTS, live), {"bamr87"})

    def test_a_running_fleet_hub_wins_and_a_stopped_one_does_not(self):
        core = {"console": fact("fleet-console-1")}
        self.assertEqual(fs.project_label("bamr87", {"fleet": core, "fleet-hub": {"console": fact("fleet-hub-console-1")}}), "fleet-hub")
        self.assertEqual(fs.project_label("bamr87", {"fleet": core, "fleet-hub": {"console": fact("fleet-hub-console-1", "exited")}}), "fleet")

    def test_other_projects_keep_their_own_name(self):
        self.assertEqual(fs.project_label("law-ai", {"fleet": {"console": fact("fleet-console-1")}}), "law-ai")

    def test_only_a_running_container_makes_a_project_up(self):
        live = {"zer0-cms": {"content": fact("zer0-cms-content-1", "exited")},
                "gitorio": {"dev": fact("gitorio-dev-1")}}
        self.assertEqual(fs.projects_up(PORTS, live), {"gitorio"})

    def test_a_docker_run_copy_does_not_replace_the_compose_container(self):
        # A review console started with `docker run` from the compose image
        # carried the same project/service labels and no healthcheck.
        real, copy = fact("fleet-console-1", health="healthy"), fact("console-review")
        self.assertGreater(fs._rank("fleet", "console", real), fs._rank("fleet", "console", copy))
        self.assertGreater(fs._rank("fleet", "console", copy), fs._rank("fleet", "console", fact("fleet-console-1", "exited")))

    def test_profiles_the_registry_activates_are_not_optional(self):
        if not os.path.isfile(os.path.join(ROOT, PROJECTS["zer0-cms"]["compose"])):
            self.skipTest("projects/zer0-cms is not checked out")
        self.assertEqual(fs.service_profiles(PORTS, "zer0-cms", "content"), [])
        self.assertEqual(fs.service_profiles(PORTS, "zer0-cms", "imagegen"), ["imagegen"])

    def test_the_hubs_own_profiles_are_read_from_the_root_compose_file(self):
        self.assertEqual(fs.service_profiles(PORTS, "bamr87", "mkdocs"), ["docs"])
        self.assertEqual(fs.service_profiles(PORTS, "bamr87", "console"), [])


class SmokeCheck(unittest.TestCase):
    """`check` holds what is deployed; `--all` holds everything recorded."""

    REG = {"projects": {
        "bamr87": {"host": "hub", "services": {
            "console": {"port": 4001, "band": "hub"},
            "mkdocs": {"port": 8001, "band": "docs"}}},
        "law-ai": {"host": "compose", "services": {"backend": {"port": 8110, "band": "api"}}},
        "cv-pro": {"host": "devenv", "services": {"vite": {"port": 5000, "band": "frontend"}}},
    }}
    OK = {"state": "running", "ok": True, "verdict": "ok", "http": "2xx", "exec_user": "vscode"}
    BASE = {"expectations": {"bamr87/console": dict(OK, health="healthy"),
                             "bamr87/mkdocs": dict(OK, http="3xx", exec_user="root"),
                             "law-ai/backend": dict(OK, exec_user="root")}}

    def check(self, live, http_ok=True, all_=False, project=None):
        saved = {n: getattr(fs, n) for n in ("containers", "inspect_all", "probe_http", "probe_exec", "load_baseline")}
        fs.containers = lambda: live
        fs.inspect_all = lambda names: {}
        fs.probe_http = lambda port, path="/": ({"kind": "http", "ok": True, "status": 200, "status_class": "2xx"} if http_ok
                                                else {"kind": "http", "ok": False, "error": "URLError"})
        fs.probe_exec = lambda container: {"kind": "exec", "ok": True, "user": "vscode"}
        fs.load_baseline = lambda: self.BASE
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = fs.cmd_check(self.REG, types.SimpleNamespace(project=project, all=all_))
        finally:
            for name, fn in saved.items():
                setattr(fs, name, fn)
        return rc, out.getvalue()

    CORE = {"fleet": {"console": fact("fleet-console-1", health="healthy")}}

    def test_a_project_nobody_started_is_not_a_regression(self):
        rc, out = self.check(self.CORE)
        self.assertEqual(rc, 0, out)
        self.assertIn("not up, not checked (1): law-ai", out)
        self.assertNotIn("cv-pro", out, "a devenv-hosted project has no container to be up")
        self.assertIn("1 services match", out)

    def test_a_profile_nobody_started_is_reported_not_failed(self):
        rc, out = self.check(self.CORE)
        self.assertIn("optional, profile not started (1): bamr87/mkdocs[docs]", out)

    def test_all_holds_the_projects_that_are_not_up(self):
        rc, out = self.check(self.CORE, all_=True)
        self.assertEqual(rc, 1, out)
        self.assertIn("✗ law-ai/backend", out)
        self.assertIn("✗ bamr87/mkdocs", out)

    def test_naming_a_project_is_strict_too(self):
        rc, out = self.check(self.CORE, project="law-ai")
        self.assertEqual(rc, 1, out)

    def test_a_running_service_that_stops_answering_still_fails(self):
        rc, out = self.check(self.CORE, http_ok=False)
        self.assertEqual(rc, 1, out)
        self.assertIn("✗ bamr87/console", out)

    def test_nothing_deployed_is_not_a_failure(self):
        rc, out = self.check({"someone-elses": {"web": fact("web-1")}})
        self.assertEqual(rc, 0, out)
        self.assertIn("nothing from the registry is running", out)


if __name__ == "__main__":
    unittest.main()

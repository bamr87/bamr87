#!/usr/bin/env python3
# ============================================================================
# File:          tools/console/test_web_deps.py
# Description:   Tests for tools/console/web-deps.sh: the page's dependencies
#                are installed when absent and upgraded when present, the
#                caller learns when to rebuild, and an offline start still
#                builds. A stub `npm` stands in for the registry.
#                Bare interpreter; no network, no Node.
# Author:        bamr87
# Created:       2026-11-17
# Last Modified: 2026-11-17
# Version:       1.0.0
# Usage:         python3 tools/console/test_web_deps.py
#                run by tools/run-all-tests.sh
# ============================================================================
#
# "Always latest" was true of a fresh install only. `npm install` leaves an
# existing node_modules alone while it satisfies the ranges, and the page's
# ranges are `*`, so the compose service's volume sat on Mantine 9.7.2 while CI
# built with 9.8.1 and a scenario failed locally on a page nobody had changed.

import os
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "web-deps.sh")

# $1 is install or update. NPM_STUB_MOVES=1 rewrites the hidden lockfile, which
# is what npm does when a package changed; NPM_STUB_FAILS=1 is the registry
# being unreachable.
NPM = """#!/bin/sh
printf '%s\\n' "$*" >> "$NPM_STUB_LOG"
[ "${NPM_STUB_FAILS:-0}" = 1 ] && exit 1
mkdir -p node_modules
if [ "$1" = install ] || [ "${NPM_STUB_MOVES:-0}" = 1 ]; then
  printf 'moved %s\\n' "$(wc -l < "$NPM_STUB_LOG")" > node_modules/.package-lock.json
fi
exit 0
"""


class WebDeps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="web-deps-")
        self.web = os.path.join(self.tmp, "web")
        os.makedirs(self.web)
        with open(os.path.join(self.web, "package.json"), "w", encoding="utf-8") as fh:
            fh.write('{"dependencies": {"@mantine/core": "*"}}\n')
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        stub = os.path.join(self.bin, "npm")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write(NPM)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.log = os.path.join(self.tmp, "npm.log")

    def installed(self):
        """An install from some earlier day, newer than package.json."""
        mods = os.path.join(self.web, "node_modules")
        os.makedirs(mods)
        with open(os.path.join(mods, ".package-lock.json"), "w", encoding="utf-8") as fh:
            fh.write("as first installed\n")
        old = os.path.getmtime(mods) - 3600
        os.utime(os.path.join(self.web, "package.json"), (old, old))

    def run_deps(self, **env):
        base = {k: v for k, v in os.environ.items() if k != "CONSOLE_SKIP_INSTALL"}
        full = dict(base, PATH=self.bin + os.pathsep + os.environ["PATH"], NPM_STUB_LOG=self.log, **env)
        proc = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", 'source "$1"; web_deps "$2"; echo "changed=$WEB_DEPS_CHANGED"', "_", SCRIPT, self.web],
            capture_output=True, text=True, env=full, timeout=60)
        calls = []
        if os.path.exists(self.log):
            with open(self.log, encoding="utf-8") as fh:
                calls = [line.split()[0] for line in fh.read().splitlines()]
        return proc, calls

    def test_a_fresh_checkout_is_installed(self):
        proc, calls = self.run_deps()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, ["install"])
        self.assertIn("changed=1", proc.stdout)

    def test_an_existing_install_is_upgraded_and_the_caller_told_to_rebuild(self):
        self.installed()
        proc, calls = self.run_deps(NPM_STUB_MOVES="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, ["update"], "an install that exists was left on the releases of the day it was made")
        self.assertIn("changed=1", proc.stdout)

    def test_nothing_newer_means_no_rebuild(self):
        self.installed()
        proc, calls = self.run_deps()
        self.assertEqual(calls, ["update"])
        self.assertIn("changed=0", proc.stdout)

    def test_skip_install_never_reaches_the_registry(self):
        self.installed()
        proc, calls = self.run_deps(CONSOLE_SKIP_INSTALL="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, [])
        self.assertIn("changed=0", proc.stdout)

    def test_an_unreachable_registry_does_not_stop_the_build(self):
        self.installed()
        proc, calls = self.run_deps(NPM_STUB_FAILS="1")
        self.assertEqual(proc.returncode, 0, "an offline start must still serve the page it has")
        self.assertIn("changed=0", proc.stdout)
        self.assertIn("building with the ones installed", proc.stderr)

    def test_a_changed_package_json_reinstalls(self):
        self.installed()
        os.utime(os.path.join(self.web, "package.json"), None)
        future = os.path.getmtime(os.path.join(self.web, "node_modules")) + 60
        os.utime(os.path.join(self.web, "package.json"), (future, future))
        proc, calls = self.run_deps()
        self.assertEqual(calls, ["install"])

    def test_both_builders_use_it(self):
        for name in ("run.sh", "build-pages.sh"):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn('source "$HERE/web-deps.sh"', text, f"{name} installs the page's dependencies its own way")
            self.assertNotIn("npm install --no-package-lock --no-audit", text.split("web-deps.sh", 1)[0],
                             f"{name} still installs before it asks web-deps.sh")


if __name__ == "__main__":
    unittest.main()

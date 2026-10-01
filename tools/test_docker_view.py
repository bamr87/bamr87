#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_docker_view.py
# Description:   Tests for tools/docker_view.py — the version comparison, the
#                image census, the pin/ceiling classification, and the rule
#                that absence is never conformance.
#                Bare interpreter + PyYAML; no network, no Docker.
# Author:        bamr87
# Created:       2026-09-22
# Last Modified: 2026-09-22
# Version:       1.0.0
# Usage:         python3 tools/test_docker_view.py
# ============================================================================
#
# Every test here is a mistake this generator actually made before it shipped.
# It reads five registries and renders a page a human will trust; the failure
# mode is not a crash, it is a confident wrong number — a fleet reported as
# conforming, a deliberate decision reported as drift, a stage name reported as
# an image. Those are the cases below.

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docker_view as dv  # noqa: E402


def write(files):
    d = tempfile.mkdtemp(prefix="dv-")
    for rel, text in files.items():
        path = os.path.join(d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    return d


class Compare(unittest.TestCase):
    """Comparison happens at the CONTRACT's precision, not at the major."""

    def test_python_311_is_behind_314_although_the_major_matches(self):
        # The bug: comparing majors only. `ver_tuple("3.11")[0] == 3` equals
        # `ver_tuple("3.14")[0]`, so five repos on 3.11/3.12 were reported as
        # conforming to a 3.14 contract.
        label, behind = dv.compare("3.11-slim", "3.14")
        self.assertEqual(label, "3.11")
        self.assertTrue(behind)

    def test_postgres_15_is_behind_18_at_major_precision(self):
        label, behind = dv.compare("15-alpine", "18")
        self.assertEqual(label, "15")
        self.assertTrue(behind)

    def test_equal_at_the_contract_precision_is_not_behind(self):
        self.assertEqual(dv.compare("3.14-slim", "3.14"), ("3.14", False))
        self.assertEqual(dv.compare("1.27-alpine", "1"), ("1", False))

    def test_ahead_is_not_behind(self):
        # zer0-cms runs Rails on Ruby 4.0 against a 3.4 contract capped by the
        # github-pages gem. Ahead is a decision, never a violation.
        _, behind = dv.compare("4.0.5", "3.4")
        self.assertFalse(behind)

    def test_a_less_precise_tag_counts_as_behind(self):
        # `python:3` is not pinned to 3.14 — treating it as conforming would
        # let a floating major masquerade as the contract.
        self.assertEqual(dv.compare("3", "3.14"), ("3.0", True))

    def test_a_tag_with_no_version_is_floating_not_behind(self):
        self.assertEqual(dv.compare("alpine", "1"), (None, None))
        self.assertEqual(dv.compare("latest", "18"), (None, None))


class Census(unittest.TestCase):
    """What is and is not an image reference."""

    def test_a_multistage_stage_name_is_not_an_image(self):
        # `FROM base` refers to a stage declared in the same file. The first
        # run put `base`, `build` and `lawmode` in the fleet's image census.
        d = write({"Dockerfile": "FROM python:3.14-slim AS base\n"
                                 "FROM base AS build\n"
                                 "FROM build\n"})
        got = dv.file_images(os.path.join(d, "Dockerfile"))
        self.assertEqual(got, [("python", "3.14-slim")])

    def test_stage_names_are_matched_case_insensitively(self):
        d = write({"Dockerfile": "FROM node:24-alpine as Builder\nFROM builder\n"})
        self.assertEqual(dv.file_images(os.path.join(d, "Dockerfile")),
                         [("node", "24-alpine")])

    def test_parameterized_references_are_skipped_not_guessed(self):
        # All three forms appeared in the fleet: ${VAR}, $VAR, and a kit's
        # {{VAR}} placeholder. Recording the literal puts `$RUBY_VERSION` in
        # the census as though it were a tag.
        d = write({"Dockerfile": "ARG RUBY_VERSION=3.4\n"
                                 "FROM ruby:${RUBY_VERSION}-slim\n"
                                 "FROM ruby:$RUBY_VERSION-slim\n",
                   "Dockerfile.template": "FROM ruby:{{RUBY_VERSION}}-slim\n"})
        self.assertEqual(dv.file_images(os.path.join(d, "Dockerfile")), [])
        self.assertEqual(dv.file_images(os.path.join(d, "Dockerfile.template")), [])

    def test_scratch_is_not_an_image(self):
        d = write({"Dockerfile": "FROM scratch\n"})
        self.assertEqual(dv.file_images(os.path.join(d, "Dockerfile")), [])

    def test_a_registry_prefix_is_normalized_away(self):
        d = write({"docker-compose.yml": "services:\n  db:\n    image: docker.io/library/postgres:18-alpine\n"})
        self.assertEqual(dv.file_images(os.path.join(d, "docker-compose.yml")),
                         [("postgres", "18-alpine")])


class Classification(unittest.TestCase):
    """Below the contract is not automatically drift."""

    def setUp(self):
        self._images, self._overrides = dv.dh.load_images, dv.dh.load_overrides

    def tearDown(self):
        dv.dh.load_images, dv.dh.load_overrides = self._images, self._overrides

    def _rows(self, census, conf, overrides=None):
        dv.dh.load_images = lambda: {"postgres": "18", "python": "3.14"}
        dv.dh.load_overrides = lambda: overrides or {}
        rows, _over, _un = dv.image_contract([], census, {}, conf)
        return {r["family"]: r for r in rows}

    def test_a_deliberate_pin_is_not_drift(self):
        # The hub's Postgres is 15 because Wiki.js content lives in a volume
        # that major wrote. Reporting it as drift every day trains people to
        # ignore the panel.
        rows = self._rows({"postgres": {"15-alpine": ["bamr87"]}},
                          {"bamr87": {"pinned": ["postgres"]}})
        self.assertEqual(rows["postgres"]["behind"], {})
        self.assertEqual(rows["postgres"]["pinned"][0]["project"], "bamr87")
        self.assertTrue(rows["postgres"]["conforming"])

    def test_an_image_override_ceiling_is_its_own_contract(self):
        rows = self._rows({"python": {"3.13-slim": ["law-ai"]}},
                          {"law-ai": {"pinned": []}},
                          overrides={"law-ai": {"python": ("3.13", "crewai has no 3.14 wheel")}})
        self.assertEqual(rows["python"]["behind"], {})
        self.assertTrue(rows["python"]["conforming"])

    def test_below_even_its_own_ceiling_is_reported(self):
        rows = self._rows({"python": {"3.12-slim": ["law-ai"]}},
                          {"law-ai": {"pinned": []}},
                          overrides={"law-ai": {"python": ("3.13", "reason")}})
        self.assertEqual(rows["python"]["ceilings"][0]["project"], "law-ai")
        self.assertEqual(rows["python"]["ceilings"][0]["ceiling"], "3.13")

    def test_an_unpinned_repo_below_the_contract_is_drift(self):
        rows = self._rows({"postgres": {"15-alpine": ["ai-seed"]}}, {"ai-seed": {"pinned": []}})
        self.assertEqual(rows["postgres"]["behind"], {"15": ["ai-seed"]})
        self.assertFalse(rows["postgres"]["conforming"])

    def test_a_pin_in_one_repo_does_not_excuse_another(self):
        rows = self._rows({"postgres": {"15-alpine": ["bamr87", "ai-seed"]}},
                          {"bamr87": {"pinned": ["postgres"]}, "ai-seed": {"pinned": []}})
        self.assertEqual(rows["postgres"]["behind"], {"15": ["ai-seed"]})
        self.assertEqual([p["project"] for p in rows["postgres"]["pinned"]], ["bamr87"])

    def test_a_floating_tag_is_listed_and_never_counted_as_drift(self):
        rows = self._rows({"postgres": {"alpine": ["someone"]}}, {"someone": {"pinned": []}})
        self.assertEqual(rows["postgres"]["floating"], ["alpine"])
        self.assertTrue(rows["postgres"]["conforming"])


class AbsenceIsNotConformance(unittest.TestCase):
    """A repo with no checkout has no findings — which is not the same as none."""

    def test_a_missing_checkout_carries_the_previous_audit_forward(self):
        projects = [{"name": "ghost", "host": "compose"}]
        previous = {"projects": [{"name": "ghost", "conformance": {"changes": 7, "pinned": []}}]}
        got = dv.conformance(projects, previous, scan=True)
        self.assertEqual(got["ghost"]["changes"], 7)
        self.assertTrue(got["ghost"]["stale"])

    def test_it_is_never_silently_reported_as_clean(self):
        projects = [{"name": "ghost", "host": "compose"}]
        got = dv.conformance(projects, None, scan=True)
        self.assertIsNone(got["ghost"])


class Publications(unittest.TestCase):
    """Reading the hub's own compose: the parameterized form is the normal one."""

    def test_a_parameterized_publication_yields_its_default_and_variable(self):
        d = write({"docker-compose.yml":
                   "services:\n  wiki:\n    ports:\n"
                   '      - "127.0.0.1:${WIKI_PORT:-3000}:3000"   # Wiki.js\n'})
        got = dv.published_ports(os.path.join(d, "docker-compose.yml"))
        self.assertEqual(got[0]["port"], 3000)
        self.assertEqual(got[0]["var"], "WIKI_PORT")
        self.assertEqual(got[0]["target"], "3000")
        self.assertEqual(got[0]["comment"], "Wiki.js")

    def test_a_range_stays_a_range(self):
        # devenv publishes one range so the eleven Jekyll sites it hosts are
        # reachable. Expanding it would claim eleven services that do not exist.
        d = write({"docker-compose.yml":
                   "services:\n  devenv:\n    ports:\n"
                   '      - "127.0.0.1:4010-4020:4010-4020"\n'})
        got = dv.published_ports(os.path.join(d, "docker-compose.yml"))
        self.assertEqual(got[0]["range"], [4010, 4020])
        self.assertNotIn("port", got[0])

    def test_a_commented_out_port_is_not_published(self):
        d = write({"docker-compose.yml":
                   "services:\n  web:\n    ports:\n"
                   '      # - "127.0.0.1:9999:9999"\n'
                   '      - "127.0.0.1:8080:80"\n'})
        got = dv.published_ports(os.path.join(d, "docker-compose.yml"))
        self.assertEqual([g["port"] for g in got], [8080])


class Rendering(unittest.TestCase):
    """The row a human reads."""

    def test_a_devenv_served_allocation_is_on_demand_not_unknown(self):
        # Eleven working sites have no container of their own, so the smoke
        # harness skips them by design. Recording that as "unknown" reads as a
        # hole in the data rather than as "not started yet".
        row = dv.service_row("wargames", "jekyll", {"port": 4015, "band": "jekyll"},
                             None, {}, on_demand=True)
        self.assertEqual(row["verdict"], "on-demand")
        self.assertEqual(row["url"], "http://127.0.0.1:4015/")

    def test_a_missing_recording_with_no_excuse_stays_unknown(self):
        row = dv.service_row("p", "api", {"port": 8100, "band": "api"}, None, {})
        self.assertEqual(row["verdict"], "unknown")

    def test_a_database_gets_a_connect_command_and_no_link(self):
        live = {"verdict": "ok", "container": "p-db-1", "state": "running"}
        row = dv.service_row("p", "db", {"port": 5442, "band": "database"}, live, {})
        self.assertNotIn("url", row)
        self.assertIn("psql", row["connect"])
        # The credential comes from the container's own env: POSTGRES_USER
        # differs per repo, and a guessed -U is wrong somewhere in the fleet.
        self.assertIn("$POSTGRES_USER", row["connect"])

    def test_a_debug_allocation_carries_its_attach_configuration(self):
        launch = {5713: {"attach": "Attach: law-ai/backend (debugpy :5713)"}}
        row = dv.service_row("law-ai", "backend",
                             {"port": 5713, "band": "debug", "kind": "debugpy",
                              "local": "projects/law-ai/backend", "remote": "/app"},
                             None, launch, kind="debug")
        self.assertIn("debugpy :5713", row["attach"])
        self.assertEqual(row["path_mapping"], "projects/law-ai/backend -> /app")

    def test_an_allocation_with_no_attach_configuration_says_so(self):
        row = dv.service_row("p", "worker", {"port": 5799, "band": "debug"}, None, {}, kind="debug")
        self.assertIn("no launch.json", row["attach"])


class Launch(unittest.TestCase):
    """Both ways a launch configuration names a port."""

    def test_attach_comes_from_the_structure_and_start_from_the_label(self):
        cfg = {"configurations": [
            {"name": "Attach: law-ai/backend (debugpy :5713)", "connect": {"port": 5713}},
            {"name": "Jekyll: wargames (:4015, devenv)"},
            {"name": "no port here"},
        ]}
        d = write({".vscode/launch.json": "// a comment VS Code tolerates\n" + json.dumps(cfg)})
        old, dv.HUB = dv.HUB, d
        try:
            got = dv.load_launch()
        finally:
            dv.HUB = old
        self.assertEqual(got[5713]["attach"], "Attach: law-ai/backend (debugpy :5713)")
        self.assertEqual(got[5713]["start"], "Attach: law-ai/backend (debugpy :5713)")
        self.assertEqual(got[4015]["start"], "Jekyll: wargames (:4015, devenv)")
        self.assertNotIn("attach", got[4015])


class Probes(unittest.TestCase):
    """Flattening the smoke recording."""

    def test_every_probe_kind_lands_on_the_row(self):
        smoke = {"services": [{
            "project": "p", "service": "db", "verdict": "ok", "state": "running",
            "probes": [
                {"kind": "tcp", "ok": True},
                {"kind": "postgres", "ok": True, "server_version": "15.19", "major": "15",
                 "databases": ["app"]},
                {"kind": "exec", "ok": True, "user": "root"},
            ]}]}
        flat = dv.smoke_index(smoke)[("p", "db")]
        self.assertEqual(flat["version"], "15.19")
        self.assertEqual(flat["major"], "15")
        self.assertEqual(flat["user"], "root")
        self.assertEqual(flat["databases"], ["app"])
        self.assertTrue(flat["tcp"])

    def test_an_http_failure_keeps_its_error_rather_than_vanishing(self):
        smoke = {"services": [{
            "project": "p", "service": "web", "verdict": "absent",
            "probes": [{"kind": "http", "ok": False, "error": "URLError", "ms": 0}]}]}
        flat = dv.smoke_index(smoke)[("p", "web")]
        self.assertEqual(flat["http"]["error"], "URLError")
        self.assertNotIn("status", flat["http"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

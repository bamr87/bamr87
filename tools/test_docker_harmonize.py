#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_docker_harmonize.py
# Description:   Fixture tests for tools/docker_harmonize.py — every rule, the
#                deliberate-pin logic, idempotency, and comment preservation.
#                Bare interpreter + PyYAML; no network, no Docker.
# Author:        bamr87
# Created:       2026-09-21
# Last Modified: 2026-09-21
# Version:       1.0.0
# Usage:         python3 tools/test_docker_harmonize.py
# ============================================================================
#
# This tool edits other people's repositories unattended, so the tests are
# written around the ways that goes wrong: downgrading a version, clobbering a
# deliberate pin, destroying a comment, "fixing" a test fixture, and — worst —
# not being idempotent, which turns a second fan-out run into a second PR.

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docker_harmonize as dh  # noqa: E402

REGISTRY = {"postgres": "18", "redis": "8", "node": "24", "python": "3.14",
            "ruby": "3.4", "nginx": "1"}


OVERRIDES = {}


def slurp(path):
    with open(path) as fh:
        return fh.read()


def make_repo(files, project="demo"):
    d = tempfile.mkdtemp(prefix="dh-")
    for rel, text in files.items():
        path = os.path.join(d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    return d


def apply(files, project="demo"):
    """Apply to a temp repo; return (result, {relpath: new text})."""
    root = make_repo(files, project)
    dh.load_images = lambda: dict(REGISTRY)
    dh.load_ports = lambda: {}
    dh.load_overrides = lambda: dict(OVERRIDES)
    res, pins = dh.run(root, project, write=True)
    out = {rel: slurp(os.path.join(root, rel)) for rel in files}
    return res, out, root


def rules(res):
    return sorted(c.rule for c in res.changes)


class ImageBumps(unittest.TestCase):
    def test_variant_is_preserved_and_bookworm_becomes_trixie(self):
        _, out, _ = apply({"Dockerfile": "FROM python:3.12-slim-bookworm AS base\nFROM node:22-alpine\n"})
        self.assertIn("FROM python:3.14-slim-trixie AS base", out["Dockerfile"])
        self.assertIn("FROM node:24-alpine", out["Dockerfile"])

    def test_never_downgrades(self):
        # Rails apps already on Ruby 4.0 must not be pulled back to the
        # Jekyll-capped registry value.
        _, out, _ = apply({"web/Dockerfile": "ARG RUBY_VERSION=4.0.5\nFROM ruby:$RUBY_VERSION-slim\n"})
        self.assertIn("ARG RUBY_VERSION=4.0.5", out["web/Dockerfile"])

    def test_arg_feeding_a_from_line_is_bumped(self):
        _, out, _ = apply({"Dockerfile": "ARG RUBY_VERSION=3.2.3\nFROM ruby:$RUBY_VERSION-slim\n"})
        self.assertIn("ARG RUBY_VERSION=3.4", out["Dockerfile"])

    def test_floating_and_unmanaged_tags_are_left_alone(self):
        src = "FROM nginx:alpine\nFROM node:latest\nFROM neo4j:5-community\nFROM scratch\n"
        res, out, _ = apply({"Dockerfile": src})
        self.assertEqual(out["Dockerfile"], src)
        self.assertNotIn("I1", rules(res))

    def test_stage_alias_is_not_an_image(self):
        src = "FROM python:3.14-slim AS base\nFROM base AS dev\n"
        res, out, _ = apply({"Dockerfile": src})
        self.assertEqual(out["Dockerfile"], src)

    def test_compose_image_keeps_quoting_and_trailing_comment(self):
        _, out, _ = apply({"docker-compose.yml":
                           "services:\n  cache:\n    image: 'redis:7-alpine'  # the cache\n"})
        self.assertIn("image: 'redis:8-alpine'  # the cache", out["docker-compose.yml"])


class Overrides(unittest.TestCase):
    def tearDown(self):
        OVERRIDES.clear()

    def test_a_repo_ceiling_replaces_the_fleet_target_and_is_reported(self):
        OVERRIDES["demo"] = {"python": ("3.13", "crewai has no 3.14 release")}
        res, out, _ = apply({"Dockerfile": "FROM python:3.12-slim\n"})
        self.assertIn("FROM python:3.13-slim", out["Dockerfile"])
        held = [f for f in res.findings if f.kind == "held-back"]
        self.assertEqual(len(held), 1)
        self.assertIn("crewai", held[0].msg)

    def test_an_override_for_another_project_is_ignored(self):
        OVERRIDES["someone-else"] = {"python": ("3.13", "x")}
        _, out, _ = apply({"Dockerfile": "FROM python:3.12-slim\n"})
        self.assertIn("FROM python:3.14-slim", out["Dockerfile"])


class PinnedDeps(unittest.TestCase):
    def test_a_runtime_bump_over_an_exact_pin_is_flagged(self):
        files = {"Dockerfile": "FROM python:3.11-slim\n", "requirements.txt": "psycopg2-binary==2.9.10\nrequests\n"}
        res, _, _ = apply(files)
        hit = [f for f in res.findings if f.kind == "pinned-deps"]
        self.assertEqual(len(hit), 1)
        self.assertIn("psycopg2-binary==2.9.10", hit[0].msg)
        self.assertIn("deps-latest", hit[0].msg)

    def test_no_pin_no_warning(self):
        res, _, _ = apply({"Dockerfile": "FROM python:3.11-slim\n", "requirements.txt": "requests\nflask>=3\n"})
        self.assertFalse([f for f in res.findings if f.kind == "pinned-deps"])

    def test_a_non_runtime_bump_does_not_warn(self):
        files = {"docker-compose.yml": "services:\n  c:\n    image: redis:7-alpine\n", "requirements.txt": "x==1.0\n"}
        res, _, _ = apply(files)
        self.assertFalse([f for f in res.findings if f.kind == "pinned-deps"])


class DeliberatePins(unittest.TestCase):
    PINNED = (
        "services:\n"
        "  db:\n"
        "    # MAJOR VERSION IS PINNED ON PURPOSE. Bumping needs dump/restore.\n"
        "    image: postgres:16-alpine\n"
        "    volumes:\n      - pg:/var/lib/postgresql/data\n"
        "  init:\n"
        "    image: postgres:16-alpine\n"
        "  cache:\n"
        "    image: redis:7-alpine\n"
    )

    def test_pinned_image_and_its_whole_family_are_frozen(self):
        res, out, _ = apply({"docker-compose.yml": self.PINNED})
        text = out["docker-compose.yml"]
        self.assertEqual(text.count("postgres:16-alpine"), 2)        # incl. the sidecar
        self.assertIn("/var/lib/postgresql/data", text)              # P1 must not fire
        self.assertNotIn("P1", rules(res))
        self.assertIn("redis:8-alpine", text)                        # other families still move

    def test_a_pin_does_not_leak_into_another_file(self):
        # The hub pins its Wiki.js database (real data in an existing volume);
        # that must not hold back an unrelated, empty postgres in another file.
        files = {"docker-compose.yml": "services:\n  wiki-db:\n    # fleet-pin: real data\n    image: postgres:15-alpine\n",
                 "compose/shared.yml": "services:\n  fleet-db:\n    image: postgres:17-alpine\n"}
        _, out, _ = apply(files)
        self.assertIn("postgres:15-alpine", out["docker-compose.yml"])
        self.assertIn("postgres:18-alpine", out["compose/shared.yml"])

    def test_a_pin_still_covers_a_sidecar_in_the_same_file(self):
        src = ("services:\n  db:\n    # pinned: dump/restore needed\n    image: postgres:16-alpine\n"
               "  db-init:\n    image: postgres:16-alpine\n")
        _, out, _ = apply({"docker-compose.yml": src})
        self.assertEqual(out["docker-compose.yml"].count("postgres:16-alpine"), 2)

    def test_pins_are_reported(self):
        root = make_repo({"docker-compose.yml": self.PINNED})
        dh.load_images = lambda: dict(REGISTRY)
        _, pins = dh.run(root, "demo", write=False)
        self.assertEqual(pins, ["postgres"])


class Postgres18(unittest.TestCase):
    def test_data_mount_moves_with_the_major(self):
        src = ("services:\n  db:\n    image: postgres:16-alpine\n"
               "    volumes:\n      - pg:/var/lib/postgresql/data\n      - ./init:/docker-entrypoint-initdb.d\n")
        res, out, _ = apply({"docker-compose.yml": src})
        text = out["docker-compose.yml"]
        self.assertIn("- pg:/var/lib/postgresql\n", text)
        self.assertNotIn("/var/lib/postgresql/data", text)
        self.assertIn("./init:/docker-entrypoint-initdb.d", text)    # untouched
        self.assertIn("P1", rules(res))

    def test_timescale_tracks_the_postgres_major(self):
        src = ("services:\n  ts:\n    image: timescale/timescaledb:latest-pg16\n"
               "    volumes:\n      - d:/var/lib/postgresql/data\n")
        _, out, _ = apply({"docker-compose.yml": src})
        self.assertIn("timescale/timescaledb:latest-pg18", out["docker-compose.yml"])
        self.assertIn("- d:/var/lib/postgresql\n", out["docker-compose.yml"])


class Ports(unittest.TestCase):
    def test_loopback_env_overridable_same_default(self):
        _, out, _ = apply({"docker-compose.yml":
                           'services:\n  web:\n    image: x\n    ports:\n      - "8000:8000"\n      - 9000:9000/udp\n'})
        t = out["docker-compose.yml"]
        self.assertIn('"127.0.0.1:${DEMO_WEB_PORT:-8000}:8000"', t)
        self.assertIn("127.0.0.1:${DEMO_WEB_9000_PORT:-9000}:9000/udp", t)

    def test_already_parameterized_is_left_alone(self):
        src = ('services:\n  web:\n    image: x\n    ports:\n'
               '      - "${BIND_HOST:-127.0.0.1}:${DJANGO_PORT:-8000}:8000"\n')
        res, out, _ = apply({"docker-compose.yml": src})
        self.assertEqual(out["docker-compose.yml"], src)
        self.assertNotIn("T1", rules(res))

    def test_env_values_hardcoding_a_host_port_follow_the_variable(self):
        src = ("services:\n  api:\n    image: x\n    ports:\n      - \"3001:3001\"\n"
               "  web:\n    image: y\n    environment:\n"
               "      - VITE_API_URL=http://localhost:3001\n"
               "      - CORS=${CORS:-http://localhost:3001}\n")
        _, out, _ = apply({"docker-compose.yml": src})
        t = out["docker-compose.yml"]
        self.assertIn("VITE_API_URL=http://localhost:${DEMO_API_PORT:-3001}", t)
        # a port at the END of a ${…:-…} default must be rewritten too
        self.assertIn("CORS=${CORS:-http://localhost:${DEMO_API_PORT:-3001}}", t)

    def test_unpublished_ports_are_not_touched(self):
        src = 'services:\n  web:\n    image: x\n    ports:\n      - "8000"\n    environment:\n      - U=http://localhost:9999\n'
        _, out, _ = apply({"docker-compose.yml": src})
        self.assertEqual(out["docker-compose.yml"], src)


class ContainerNames(unittest.TestCase):
    def test_removed_when_nothing_references_it(self):
        res, out, _ = apply({"docker-compose.yml": "services:\n  a:\n    image: x\n    container_name: my-a\n"})
        self.assertNotIn("container_name", out["docker-compose.yml"])
        self.assertIn("N1", rules(res))

    def test_kept_when_a_script_references_it(self):
        files = {"docker-compose.yml": "services:\n  a:\n    image: x\n    container_name: my-a\n",
                 "scripts/run.sh": "docker exec my-a ls\n"}
        res, out, _ = apply(files)
        self.assertIn("container_name: my-a", out["docker-compose.yml"])
        self.assertTrue(any(f.kind == "container_name" for f in res.findings))

    def test_a_comment_in_a_script_does_not_block(self):
        files = {"docker-compose.yml": "services:\n  a:\n    image: x\n    container_name: my-a\n",
                 "tools/x.py": "# the old name was my-a, now namespaced\n"}
        res, out, _ = apply(files)
        self.assertNotIn("container_name", out["docker-compose.yml"])

    def test_a_docs_mention_does_not_block_but_is_reported(self):
        files = {"docker-compose.yml": "services:\n  a:\n    image: x\n    container_name: my-a\n",
                 "README.md": "Run `docker logs my-a`.\n"}
        res, out, _ = apply(files)
        self.assertNotIn("container_name", out["docker-compose.yml"])
        self.assertTrue(any(f.kind == "docs" for f in res.findings))


class Healthchecks(unittest.TestCase):
    def test_localhost_becomes_loopback_only_inside_healthchecks(self):
        src = ("services:\n  a:\n    image: x\n    environment:\n      - U=http://localhost:80\n"
               "    healthcheck:\n      test: [\"CMD\", \"wget\", \"http://localhost/\"]\n")
        _, out, _ = apply({"docker-compose.yml": src})
        t = out["docker-compose.yml"]
        self.assertIn("http://127.0.0.1/", t)
        self.assertIn("U=http://localhost:80", t)                    # env value untouched

    def test_qdrant_has_no_curl(self):
        src = ("services:\n  q:\n    image: qdrant/qdrant:latest\n    healthcheck:\n"
               "      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:6333/health\"]\n")
        _, out, _ = apply({"docker-compose.yml": src})
        self.assertIn("/dev/tcp/127.0.0.1/6333", out["docker-compose.yml"])
        self.assertNotIn("curl", out["docker-compose.yml"])

    def test_celery_ping_gets_a_timeout_once(self):
        src = ("services:\n  w:\n    image: x\n    healthcheck:\n"
               "      test: [\"CMD-SHELL\", \"celery -A app inspect ping || exit 1\"]\n")
        _, out, _ = apply({"docker-compose.yml": src})
        self.assertIn("inspect ping --timeout 8", out["docker-compose.yml"])
        res2, _, _ = apply({"docker-compose.yml": out["docker-compose.yml"]})
        self.assertNotIn("H2", rules(res2))


class EnvFiles(unittest.TestCase):
    def test_missing_scalar_env_file_becomes_optional(self):
        _, out, _ = apply({"docker-compose.yml": "services:\n  a:\n    image: x\n    env_file: .env\n"})
        self.assertIn("- path: .env\n        required: false", out["docker-compose.yml"])

    def test_missing_list_env_file_becomes_optional(self):
        _, out, _ = apply({"docker-compose.yml": "services:\n  a:\n    image: x\n    env_file:\n      - .env\n"})
        self.assertIn("- path: .env\n", out["docker-compose.yml"])
        self.assertIn("required: false", out["docker-compose.yml"])

    def test_an_insertion_does_not_strand_later_services(self):
        # E1 inserts lines; the main loop used to keep iterating a span list built
        # BEFORE the insertion, so every service after it silently kept its
        # hardcoded ports. Only 1 of 3 T1 rewrites fired.
        src = ("services:\n"
               "  a:\n    image: x\n    env_file: .env\n    ports:\n      - \"7001:7001\"\n"
               "  b:\n    image: y\n    ports:\n      - \"7002:7002\"\n"
               "  c:\n    image: z\n    ports:\n      - \"7003:7003\"\n")
        res, out, _ = apply({"docker-compose.yml": src})
        t = out["docker-compose.yml"]
        self.assertEqual(sum(1 for c in res.changes if c.rule == "T1"), 3)
        for svc, port in (("A", 7001), ("B", 7002), ("C", 7003)):
            self.assertIn("${DEMO_%s_PORT:-%d}:%d" % (svc, port, port), t)

    def test_two_missing_env_files_both_convert(self):
        src = ("services:\n  a:\n    image: x\n    env_file: .env\n"
               "  b:\n    image: y\n    env_file:\n      - .env.local\n")
        _, out, _ = apply({"docker-compose.yml": src})
        self.assertEqual(out["docker-compose.yml"].count("required: false"), 2)

    def test_present_env_file_is_left_required(self):
        files = {"docker-compose.yml": "services:\n  a:\n    image: x\n    env_file: .env.defaults\n",
                 ".env.defaults": "A=1\n"}
        _, out, _ = apply(files)
        self.assertNotIn("required: false", out["docker-compose.yml"])


class Lockfiles(unittest.TestCase):
    def test_copy_of_a_forbidden_lockfile_is_trimmed(self):
        _, out, _ = apply({"Dockerfile": "FROM ruby:3.4\nCOPY Gemfile Gemfile.lock ./\nRUN bundle install\n"})
        self.assertIn("COPY Gemfile ./", out["Dockerfile"])
        self.assertNotIn("Gemfile.lock", out["Dockerfile"])

    def test_copy_keeps_the_lockfile_when_the_repo_has_one(self):
        src = "FROM ruby:3.4\nCOPY Gemfile Gemfile.lock ./\n"
        _, out, _ = apply({"Dockerfile": src, "Gemfile.lock": "x\n"})
        self.assertEqual(out["Dockerfile"], src)

    def test_npm_ci_needs_a_lockfile(self):
        _, out, _ = apply({"Dockerfile": "FROM node:24\nRUN npm ci --omit=dev\n"})
        self.assertIn("npm install --omit=dev", out["Dockerfile"])


class Preservation(unittest.TestCase):
    SRC = ("# top comment — why this stack exists\n"
           "version: '3.8'\n\n"
           "services:\n"
           "  # the cache: keep it small\n"
           "  cache:\n"
           "    image: redis:7-alpine   # trailing note\n"
           "    ports:\n"
           "      - \"6379:6379\"   # exposed for the debugger\n")

    def test_comments_survive_and_version_is_dropped(self):
        _, out, _ = apply({"docker-compose.yml": self.SRC})
        t = out["docker-compose.yml"]
        for keep in ("# top comment — why this stack exists", "# the cache: keep it small",
                     "# trailing note", "# exposed for the debugger"):
            self.assertIn(keep, t)
        self.assertNotIn("version:", t)

    def test_second_apply_is_a_noop(self):
        _, first, root = apply({"docker-compose.yml": self.SRC})
        res2, out2 = dh.run(root, "demo", write=True)[0], slurp(os.path.join(root, "docker-compose.yml"))
        self.assertEqual(res2.changes, [])
        self.assertEqual(out2, first["docker-compose.yml"])

    def test_fixtures_are_never_rewritten(self):
        src = 'services:\n  w:\n    image: postgres:12\n    ports:\n      - "3000:3000"\n'
        _, out, _ = apply({"src/test/fixtures/site/docker-compose.yml": src})
        self.assertEqual(out["src/test/fixtures/site/docker-compose.yml"], src)


class Failures(unittest.TestCase):
    def test_a_file_the_transformer_cannot_process_is_an_error_not_silence(self):
        # run() catches per-file exceptions so one bad file cannot abort a fleet
        # sweep — but `check` must then FAIL, or a crash reads as conformance.
        import docker_harmonize as m
        orig = m.transform_compose
        m.transform_compose = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            res, _, _ = apply({"docker-compose.yml": "services:\n  a:\n    image: x\n"})
        finally:
            m.transform_compose = orig
        self.assertTrue([f for f in res.findings if f.kind == "error"])


class DockerIgnore(unittest.TestCase):
    def test_seeded_beside_the_build_context_not_the_dockerfile(self):
        files = {"docker-compose.yml": "services:\n  api:\n    build:\n      context: .\n      dockerfile: backend/Dockerfile\n",
                 "backend/Dockerfile": "FROM python:3.14-slim\n"}
        res, _, root = apply(files)
        self.assertTrue(os.path.exists(os.path.join(root, ".dockerignore")))
        self.assertFalse(os.path.exists(os.path.join(root, "backend/.dockerignore")))
        self.assertIn("D1", rules(res))

    def test_never_overwrites_an_existing_one(self):
        files = {"Dockerfile": "FROM python:3.14-slim\n", ".dockerignore": "mine\n"}
        res, out, _ = apply(files)
        self.assertEqual(out[".dockerignore"], "mine\n")
        self.assertNotIn("D1", rules(res))

    def test_excludes_secrets_and_vcs_but_not_build_output(self):
        _, out, root = apply({"Dockerfile": "FROM node:24-alpine\n"})
        body = slurp(os.path.join(root, ".dockerignore"))
        for must in (".git", ".env", "node_modules", "__pycache__"):
            self.assertIn(must, body)
        self.assertIn("!.env.example", body)
        # several repos COPY a pre-built frontend from dist/
        self.assertNotIn("\ndist\n", body)
        self.assertNotIn("\nbuild\n", body)

    def test_a_template_dockerfile_is_version_bumped_but_gets_no_dockerignore(self):
        res, out, root = apply({"templates/Dockerfile.consumer.template": "FROM ruby:3.3-slim\n"})
        self.assertIn("FROM ruby:3.4-slim", out["templates/Dockerfile.consumer.template"])
        self.assertFalse(os.path.exists(os.path.join(root, "templates/.dockerignore")))

    def test_a_standalone_dockerfile_gets_one_in_its_own_directory(self):
        res, _, root = apply({"web/Dockerfile": "FROM ruby:3.4-slim\n"})
        self.assertTrue(os.path.exists(os.path.join(root, "web/.dockerignore")))


class Advisory(unittest.TestCase):
    def test_reports_but_does_not_fix_root_and_missing_healthcheck(self):
        res, out, _ = apply({"Dockerfile": "FROM python:3.14-slim\nRUN pip install x\n"})
        kinds = {f.kind for f in res.findings}
        self.assertTrue({"root-user", "single-stage", "no-healthcheck"} <= kinds)
        self.assertEqual(out["Dockerfile"], "FROM python:3.14-slim\nRUN pip install x\n")

    def test_a_non_root_user_silences_the_finding(self):
        res, _, _ = apply({"Dockerfile": "FROM python:3.14-slim\nUSER app\n"})
        self.assertNotIn("root-user", {f.kind for f in res.findings})


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
"""Fixture tests for the UPS-BE-10/11 rows in tools/conformance.py (/healthz and
/version): they bind to `api, app (server-rendered)`, so a repo with no server
side is N/A, and any server signal (kind api, manage.py, a Dockerfile, a server
framework dependency, a stdlib or net/http server) keeps both rows checked.
Offline, no pytest:

    python3 tools/test_conformance_backend.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
ROWS = ("UPS-BE-10", "UPS-BE-11")
SPA = {
    "package.json": '{"dependencies":{"react":"*","react-dom":"*","next-themes":"*"},'
                    '"devDependencies":{"vite":"*","@vitejs/plugin-react":"*"}}',
    "index.html": "<div id=root></div>",
    "src/main.tsx": "import React from 'react'\n",
}
ROUTES = {"src/routes.py": '@app.get("/healthz")\ndef healthz(): ...\n@app.get("/version")\ndef version(): ...\n'}
SERVERS = {
    "django": {"manage.py": "import django\n"},
    "fastapi": {"requirements.txt": "fastapi>=0.110\nuvicorn\n"},
    "pyproject flask": {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["flask>=3"]\n'},
    "next": {"package.json": '{"dependencies":{"next":"*","react":"*"}}'},
    "express": {"package.json": '{"dependencies":{"express":"*"}}'},
    "frontend/ fastify": {**SPA, "frontend/package.json": '{"devDependencies":{"fastify":"*"}}'},
    "packages/* hono": {**SPA, "packages/edge/package.json": '{"dependencies":{"hono":"*"}}'},
    "Dockerfile": {**SPA, "Dockerfile": "FROM nginx\n"},
    "app/Dockerfile": {**SPA, "app/Dockerfile.prod": "FROM node\n"},
    "wrangler": {**SPA, "wrangler.toml": 'name = "x"\n'},
    "rails": {"Gemfile": "source 'https://rubygems.org'\ngem 'rails'\n"},
    "stdlib server": {"pyproject.toml": '[project]\nname = "lab"\n',
                      "src/lab/app.py": "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
                                        "class Handler(BaseHTTPRequestHandler):\n    def do_GET(self): ...\n"},
    "asyncio server": {"pyproject.toml": '[project]\nname = "gui"\n',
                       "src/gui/http.py": "import asyncio\nasync def run(h): await asyncio.start_server(h, '127.0.0.1', 0)\n"},
    "go net/http": {"go.mod": "module x\n", "main.go": 'import "net/http"\nfunc main() { http.ListenAndServe(":8080", nil) }\n'},
}


def repo(files: dict[str, str], tmp: Path) -> c.Repo:
    for rel, body in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    r = c.Repo(tmp, HUB)
    r.registry_entry = {"name": "x"}
    return r


class BackendConformance(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def fresh(self, name: str) -> Path:
        d = self.tmp / name.replace("/", "_").replace(" ", "_").replace("*", "x")
        d.mkdir()
        return d

    def verdicts(self, files, kinds=("app",), name="r"):
        r = repo(files, self.fresh(name))
        return {rid: c.CHECKS[rid](r, list(kinds)) for rid in ROWS}

    def assert_na(self, files, kinds=("app",), name="r"):
        for rid, (ok, detail) in self.verdicts(files, kinds, name).items():
            self.assertIs(ok, True, rid)
            self.assertIn("n/a", detail, rid)

    def test_browser_only_spa_is_na(self):
        self.assert_na(SPA)

    def test_static_preview_tooling_is_not_a_server_side(self):
        """A static-file preview and a Node playtest server ship with static apps."""
        self.assert_na({**SPA,
                        "tools/serve.py": "import http.server\n"
                                          "http.server.ThreadingHTTPServer(('', 8000), http.server.SimpleHTTPRequestHandler)\n",
                        "tools/play.mjs": "import { createServer } from 'node:http'\ncreateServer().listen(0)\n"})

    def test_comment_test_helper_and_nested_repo_are_not_signals(self):
        self.assert_na({**SPA,
                        "requirements.txt": "# gunicorn is not used here\npyyaml\n",
                        "tests/helpers.py": "from http.server import BaseHTTPRequestHandler\n"
                                            "class H(BaseHTTPRequestHandler): ...\n",
                        "vendored/.git/HEAD": "ref: refs/heads/main\n",
                        "vendored/package.json": '{"dependencies":{"express":"*"}}'})

    def test_server_side_is_checked_fails_without_routes_and_passes_with_them(self):
        for name, files in SERVERS.items():
            with self.subTest(name):
                for rid, (ok, detail) in self.verdicts(files, name=f"{name}-bare").items():
                    self.assertIs(ok, False, f"{name} {rid}: {detail}")
                for rid, (ok, detail) in self.verdicts({**files, **ROUTES}, name=f"{name}-routed").items():
                    self.assertIs(ok, True, f"{name} {rid}")
                    self.assertNotIn("n/a", detail, f"{name} {rid}")

    def test_kind_api_is_always_checked(self):
        for rid, (ok, _) in self.verdicts({}, kinds=("api",), name="api-bare").items():
            self.assertIs(ok, False, rid)
        for rid, (ok, _) in self.verdicts(dict(ROUTES), kinds=("api",), name="api-routed").items():
            self.assertIs(ok, True, rid)

    def test_server_side_names_its_evidence(self):
        r = repo(SERVERS["frontend/ fastify"], self.fresh("evidence"))
        self.assertEqual(c._server_side(r, ["app"]), "frontend/package.json depends on fastify")
        self.assertIsNone(c._server_side(repo(SPA, self.fresh("spa")), ["app"]))

    def test_run_checks_no_longer_fails_a_browser_only_app(self):
        specs = c.load_specs(HUB)
        spa = c.run_checks(repo(SPA, self.fresh("run-spa")), ["app"], "active", specs)
        self.assertFalse({f["id"] for f in spa["failing"]} & set(ROWS))
        srv = c.run_checks(repo(SERVERS["django"], self.fresh("run-srv")), ["app"], "active", specs)
        self.assertTrue(set(ROWS) <= {f["id"] for f in srv["failing"]})

    def test_rows_still_bind_to_server_rendered_apps(self):
        """The N/A rests on the spec's qualifier: if specs/BACKEND.md drops it, revisit _server_side."""
        import yaml
        reqs = {q["id"]: q for q in yaml.safe_load((HUB / "_data" / "specs.yml").read_text())["requirements"]}
        for rid in ROWS:
            self.assertEqual(set(reqs[rid]["applies"]), {"api", "app"}, rid)
            self.assertIn("server-rendered", " ".join(reqs[rid].get("applies_notes") or []), rid)


if __name__ == "__main__":
    unittest.main()

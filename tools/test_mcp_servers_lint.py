#!/usr/bin/env python3
"""Fixture tests for tools/mcp_servers_lint.py (constitution § 25, and § 16.4's server.json)."""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from mcp_servers_lint import (
    HUB_MANIFEST,
    HUB_VERSION_SOURCE,
    PUBLISHER_META,
    VERSION_LITERAL_RE,
    check,
    find_server_manifests,
)

REPO = Path(__file__).resolve().parents[1]
SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

GOOD_MANIFEST = {
    "$schema": SCHEMA_URL,
    "name": "io.github.example/fleet",
    "description": "A test server",
    "version": "1.2.3",
    "repository": {"url": "https://github.com/example/example", "source": "github"},
    "_meta": {
        PUBLISHER_META: {
            "transport": {"type": "stdio"},
            "launch": {"command": "tools/console/mcp.sh", "args": []},
            "environmentVariables": [
                {"name": "DASH_CONSOLE_TOKEN", "description": "bearer", "isSecret": True},
            ],
        }
    },
}


def _write_registry(root: Path, ids: list[str], extra: dict[str, dict] | None = None) -> None:
    data = {
        "schema": "mcp-servers/v1",
        "servers": [
            {
                "id": i,
                "role": "client-config",
                "status": "canonical",
                "owner": "test",
                "path": ".mcp.json",
                "transports": ["stdio"],
                "entrypoint": "npx",
                "secret_env": [],
                **((extra or {}).get(i) or {}),
            }
            for i in ids
        ],
    }
    (root / "_data").mkdir(parents=True, exist_ok=True)
    # minimal YAML without depending on dump formatting for ids we control
    import yaml

    (root / "_data" / "mcp_servers.yml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


def _write_json(root: Path, rel: str, doc: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _manifest_repo(root: Path, manifest: dict | None = None, *, version_literal: str | None = "1.2.3",
                   server_json: str | None = HUB_MANIFEST) -> None:
    """A minimal hub: registry row `fleet` (with server_json), .mcp.json, the console
    manifest and, unless version_literal is None, mcp_layer/server.py's VERSION."""
    _write_registry(root, ["fleet"], {"fleet": {"server_json": server_json} if server_json else {}})
    _write_json(root, ".mcp.json", {"mcpServers": {"fleet": {"command": "tools/console/mcp.sh"}}})
    if manifest is not None:
        _write_json(root, HUB_MANIFEST, manifest)
    if version_literal is not None:
        src = root / HUB_VERSION_SOURCE
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(f'import sys\n\nVERSION = "{version_literal}"\n', encoding="utf-8")


def _reasons(result: dict) -> list[str]:
    return [f["reason"] for f in result["findings"]]


class McpServersLintTest(unittest.TestCase):
    def test_clean_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_registry(root, ["github", "fleet"])
            (root / ".mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "github": {
                                "command": "npx",
                                "args": ["-y", "@modelcontextprotocol/server-github"],
                                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"},
                            },
                            "fleet": {"command": "tools/console/mcp.sh", "args": []},
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = check(root, gate=True)
            self.assertTrue(result["ok"], result["findings"])

    def test_inline_token_fails_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_registry(root, ["github"])
            (root / ".mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "github": {
                                "command": "npx",
                                "args": ["-y", "@modelcontextprotocol/server-github"],
                                "env": {
                                    "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_AAAAAAAAAAAAAAAAAAAAAAAA"
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            warn = check(root, gate=False)
            self.assertTrue(warn["ok"])
            self.assertTrue(warn["findings"])
            hard = check(root, gate=True)
            self.assertFalse(hard["ok"])

    def test_missing_mcp_servers_object(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_registry(root, [])
            (root / ".mcp.json").write_text(json.dumps({"servers": {}}), encoding="utf-8")
            result = check(root, gate=True)
            self.assertFalse(result["ok"])
            self.assertTrue(any("mcpServers" in f["reason"] for f in result["findings"]))


class ServerManifestLintTest(unittest.TestCase):
    """MCP Registry server.json (constitution § 16.4): shape, name, version, transport,
    no secret and no machine-local endpoint; the console's version follows mcp_layer."""

    def _check(self, manifest: dict, **kw) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            kw.setdefault("version_literal", manifest.get("version"))
            _manifest_repo(root, manifest, **kw)
            return check(root, gate=True)

    def _assert_reason(self, result: dict, needle: str) -> None:
        self.assertFalse(result["ok"], f"expected a finding containing {needle!r}")
        self.assertTrue(any(needle in r for r in _reasons(result)), (needle, _reasons(result)))

    def _bad(self, mutate, needle: str) -> None:
        doc = copy.deepcopy(GOOD_MANIFEST)
        mutate(doc)
        self._assert_reason(self._check(doc), needle)

    def _publisher_env(self, entry: dict):
        return lambda d: d["_meta"][PUBLISHER_META]["environmentVariables"].append(entry)

    def test_clean_manifest(self):
        result = self._check(copy.deepcopy(GOOD_MANIFEST))
        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(result["server_manifests"], [HUB_MANIFEST])

    def test_package_and_remote_shapes_pass(self):
        doc = copy.deepcopy(GOOD_MANIFEST)
        del doc["_meta"]
        doc["packages"] = [
            {
                "registryType": "npm",
                "identifier": "@example/server",
                "version": "1.2.3",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {"name": "API_TOKEN", "isSecret": True, "value": "{api_token}"},
                    {"name": "LOG_LEVEL", "value": "info"},
                ],
            }
        ]
        doc["remotes"] = [{"type": "streamable-http", "url": "https://mcp.example.com/mcp"}]
        result = self._check(doc)
        self.assertTrue(result["ok"], result["findings"])

    def test_schema_url_required(self):
        self._bad(lambda d: d.update({"$schema": "https://example.com/server.schema.json"}), "$schema")

    def test_name_must_be_github_namespace(self):
        self._bad(lambda d: d.update({"name": "fleet"}), "io.github.<owner>/<server>")
        self._bad(lambda d: d.update({"name": "com.example/fleet"}), "io.github.<owner>/<server>")

    def test_description_bounds(self):
        self._bad(lambda d: d.update({"description": ""}), "description")
        self._bad(lambda d: d.update({"description": "x" * 101}), "description")

    def test_version_is_specific(self):
        for bad in ("", "latest", "^1.2.3", "~1.2.3", ">=1.2.3", "1.x", "1.*"):
            with self.subTest(version=bad):
                doc = copy.deepcopy(GOOD_MANIFEST)
                doc["version"] = bad
                self._assert_reason(self._check(doc, version_literal=None), "specific version")

    def test_needs_a_transport(self):
        self._bad(lambda d: d.pop("_meta"), "declares no transport")
        self._bad(lambda d: d["_meta"][PUBLISHER_META].update({"transport": {"type": "ws"}}), "transport.type")
        self._bad(lambda d: d.update({"packages": [{"registryType": "npm", "identifier": "x"}]}),
                  "packages[0] transport")
        self._bad(lambda d: d.update({"remotes": [{"type": "stdio"}]}), "remotes[0]")

    def test_secret_literal_fails(self):
        def leak(d):
            d["packages"] = [
                {
                    "registryType": "npm",
                    "identifier": "@example/server",
                    "transport": {"type": "stdio"},
                    "environmentVariables": [{"name": "GITHUB_TOKEN", "value": "ghp_" + "A" * 24}],
                }
            ]
        self._bad(leak, "inline credential")
        self._bad(leak, "must be a {placeholder}")

    def test_publisher_env_is_names_only(self):
        self._bad(self._publisher_env({"name": "MODE", "default": "fast"}), "names only")
        self._bad(self._publisher_env({"name": "lower-case"}), "not an env var name")

    def test_machine_local_endpoints_fail(self):
        for url in ("http://127.0.0.1:4002/mcp", "http://localhost:4002/mcp",
                    "https://quiet-river-1234.trycloudflare.com/mcp", "http://host.docker.internal:4002/mcp"):
            with self.subTest(url=url):
                self._bad(lambda d, u=url: d.update({"remotes": [{"type": "streamable-http", "url": u}]}),
                          "machine-local endpoint")

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _manifest_repo(root, None)
            (root / HUB_MANIFEST).write_text("{not json", encoding="utf-8")
            self._assert_reason(check(root, gate=True), "invalid JSON")

    def test_version_drift_from_mcp_layer_fails(self):
        result = self._check(copy.deepcopy(GOOD_MANIFEST), version_literal="9.9.9")
        self._assert_reason(result, "bump both together")

    def test_console_without_manifest_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _manifest_repo(root, None, server_json=None)
            self._assert_reason(check(root, gate=True), "no MCP Registry server.json")

    def test_registry_server_json_must_exist_and_match_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _manifest_repo(root, copy.deepcopy(GOOD_MANIFEST), server_json="tools/console/missing.json")
            self._assert_reason(check(root, gate=True), "does not exist")
        self._bad(lambda d: d.update({"name": "io.github.example/example"}), "must end in /fleet")

    def test_walk_skips_submodules_dependencies_and_venvs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel in ("projects/spoke/server.json", "tools/console/web/node_modules/x/server.json",
                        ".venv-mcp/lib/server.json", "_site/server.json", "mcp/server.json"):
                _write_json(root, rel, {})
            self.assertEqual(find_server_manifests(root), ["mcp/server.json"])


class HubConsoleManifestTest(unittest.TestCase):
    """The committed tools/console/server.json itself (issue #541)."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads((REPO / HUB_MANIFEST).read_text(encoding="utf-8"))
        cls.meta = cls.doc["_meta"][PUBLISHER_META]

    def test_lint_is_clean_for_the_manifest(self):
        result = check(REPO, gate=True)
        self.assertIn(HUB_MANIFEST, result["server_manifests"])
        mine = [f for f in result["findings"]
                if f["path"] in (HUB_MANIFEST, HUB_VERSION_SOURCE) or "server_json" in f["reason"]]
        self.assertEqual(mine, [])

    def test_version_equals_mcp_layer_version(self):
        # Read by regex: the MCP SDK is not installed on plain python3, so server.py cannot be imported.
        match = VERSION_LITERAL_RE.search((REPO / HUB_VERSION_SOURCE).read_text(encoding="utf-8"))
        self.assertIsNotNone(match)
        self.assertEqual(self.doc["version"], match.group(1),
                         "bump tools/console/server.json with mcp_layer VERSION")

    def test_name_is_the_stable_registry_id(self):
        self.assertEqual(self.doc["name"], "io.github.bamr87/fleet")
        self.assertEqual(self.meta["registryId"], "fleet")

    def test_transport_is_stdio_launched_by_mcp_sh(self):
        import yaml

        self.assertEqual(self.meta["transport"], {"type": "stdio"})
        registry = yaml.safe_load((REPO / "_data" / "mcp_servers.yml").read_text(encoding="utf-8"))
        row = next(r for r in registry["servers"] if r["id"] == "fleet")
        self.assertEqual(self.meta["launch"]["command"], row["entrypoint"])
        self.assertIn("stdio", row["transports"])
        self.assertEqual(row["server_json"], HUB_MANIFEST)
        mcp = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["fleet"]
        self.assertEqual(self.meta["launch"]["command"], mcp["command"])
        self.assertEqual(self.meta["launch"]["args"], mcp.get("args", []))

    def test_unpublished_and_carries_no_endpoint_or_value(self):
        self.assertNotIn("packages", self.doc)
        self.assertNotIn("remotes", self.doc)
        self.assertIs(self.meta["published"], False)
        urls = re.findall(r"[a-z][a-z0-9+.-]*://[^\s\"]+", json.dumps(self.doc))
        self.assertEqual(sorted(urls), sorted([SCHEMA_URL, self.doc["repository"]["url"]]))
        for env in self.meta["environmentVariables"]:
            self.assertFalse({"value", "default"} & set(env), env)


if __name__ == "__main__":
    unittest.main()

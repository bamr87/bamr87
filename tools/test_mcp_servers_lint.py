#!/usr/bin/env python3
"""Fixture tests for tools/mcp_servers_lint.py (constitution § 25)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcp_servers_lint import check


def _write_registry(root: Path, ids: list[str]) -> None:
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


if __name__ == "__main__":
    unittest.main()

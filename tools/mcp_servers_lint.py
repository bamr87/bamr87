#!/usr/bin/env python3
"""
File: tools/mcp_servers_lint.py
Description: Warn-then-fail lint for MCP client configs and the hub MCP
             registry (constitution § 25 / docs/MCP-SERVERS.md).
             Default is warn-only (exit 0); --gate exits 1 on findings.
Author: bamr87
Created: 2026-11-05
Usage: python3 tools/mcp_servers_lint.py check [PATH] [--gate] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|bearer|credential|pat)",
    re.I,
)
INLINE_SECRET_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)
ENV_REF_RE = re.compile(r"^\$\{(?:env:)?[A-Z][A-Z0-9_]*\}$")

DEFAULT_CONFIG_PATHS = (
    ".mcp.json",
    "verify/mcp.json",
    "templates/verify/mcp.json",
)


def _repo(path: Path) -> Path:
    return path.resolve()


def _load_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)
    if not isinstance(data, dict):
        return None, "root must be a JSON object"
    return data, None


def _load_registry(repo: Path) -> tuple[dict | None, str | None]:
    path = repo / "_data" / "mcp_servers.yml"
    if not path.is_file():
        return None, "missing _data/mcp_servers.yml"
    if yaml is None:
        return None, "PyYAML required to read mcp_servers.yml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    if not isinstance(data, dict):
        return None, "registry root must be a mapping"
    return data, None


def _env_ok(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return bool(ENV_REF_RE.match(value.strip()))


def _check_server_entry(rel: str, sid: str, entry: object) -> list[dict]:
    findings: list[dict] = []
    if not isinstance(entry, dict):
        findings.append({"path": rel, "server": sid, "reason": "server entry must be an object"})
        return findings
    has_cmd = "command" in entry
    has_url = "url" in entry
    if not has_cmd and not has_url:
        findings.append(
            {"path": rel, "server": sid, "reason": "server needs command (stdio) or url (http)"}
        )
    env = entry.get("env") or {}
    if env and not isinstance(env, dict):
        findings.append({"path": rel, "server": sid, "reason": "env must be an object"})
        env = {}
    for k, v in env.items():
        if SECRET_KEY_RE.search(str(k)) and not _env_ok(v):
            findings.append(
                {
                    "path": rel,
                    "server": sid,
                    "reason": f"secret-looking env {k!r} must be an ${'{ENV}'} ref, not a literal",
                }
            )
        if isinstance(v, str) and INLINE_SECRET_RE.search(v):
            findings.append(
                {"path": rel, "server": sid, "reason": "inline credential pattern in env value"}
            )
    # scan the serialized entry for inline secrets outside env refs
    blob = json.dumps(entry)
    if INLINE_SECRET_RE.search(blob):
        # allow if the only matches are inside ${...}? still flag — literals should not appear
        findings.append(
            {"path": rel, "server": sid, "reason": "inline credential pattern in server config"}
        )
    return findings


def _check_config(repo: Path, rel: str) -> list[dict]:
    path = repo / rel
    if not path.is_file():
        return [{"path": rel, "server": "", "reason": "config file missing"}]
    data, err = _load_json(path)
    if err:
        return [{"path": rel, "server": "", "reason": f"invalid JSON: {err}"}]
    assert data is not None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return [{"path": rel, "server": "", "reason": "missing mcpServers object"}]
    findings: list[dict] = []
    for sid, entry in servers.items():
        findings.extend(_check_server_entry(rel, str(sid), entry))
    return findings


def check(repo: Path, *, gate: bool = False) -> dict:
    findings: list[dict] = []
    checked_configs: list[str] = []
    for rel in DEFAULT_CONFIG_PATHS:
        if (repo / rel).is_file() or rel == ".mcp.json":
            checked_configs.append(rel)
            findings.extend(_check_config(repo, rel))

    registry, reg_err = _load_registry(repo)
    registry_ids: set[str] = set()
    if reg_err:
        findings.append({"path": "_data/mcp_servers.yml", "server": "", "reason": reg_err})
    else:
        assert registry is not None
        if registry.get("schema") != "mcp-servers/v1":
            findings.append(
                {
                    "path": "_data/mcp_servers.yml",
                    "server": "",
                    "reason": "schema must be mcp-servers/v1",
                }
            )
        rows = registry.get("servers") or []
        if not isinstance(rows, list):
            findings.append(
                {"path": "_data/mcp_servers.yml", "server": "", "reason": "servers must be a list"}
            )
            rows = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                findings.append(
                    {
                        "path": "_data/mcp_servers.yml",
                        "server": "",
                        "reason": "each registry row needs an id",
                    }
                )
                continue
            sid = str(row["id"])
            registry_ids.add(sid)
            for key in ("secret_env",):
                vals = row.get(key) or []
                if vals and not isinstance(vals, list):
                    findings.append(
                        {
                            "path": "_data/mcp_servers.yml",
                            "server": sid,
                            "reason": f"{key} must be a list of names",
                        }
                    )
                for item in vals if isinstance(vals, list) else []:
                    if not isinstance(item, str) or INLINE_SECRET_RE.search(item):
                        findings.append(
                            {
                                "path": "_data/mcp_servers.yml",
                                "server": sid,
                                "reason": "secret_env must be env names only, never values",
                            }
                        )

        # unknown ids in hub .mcp.json
        mcp_path = repo / ".mcp.json"
        if mcp_path.is_file() and registry_ids:
            data, err = _load_json(mcp_path)
            if not err and data:
                for sid in (data.get("mcpServers") or {}):
                    if sid not in registry_ids and sid != "playwright":
                        # playwright may appear as verify-playwright in registry
                        if sid not in registry_ids:
                            findings.append(
                                {
                                    "path": ".mcp.json",
                                    "server": str(sid),
                                    "reason": "server id not listed in _data/mcp_servers.yml",
                                }
                            )

    # de-dupe findings
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for f in findings:
        key = (f.get("path"), f.get("server"), f.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)

    result = {
        "checker": "mcp_servers_lint",
        "section": "constitution § 25",
        "checked_configs": checked_configs,
        "registry_ids": sorted(registry_ids),
        "findings": uniq,
        "gate": gate,
        "ok": not uniq if gate else True,
        "warn_only": not gate,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="lint MCP configs and registry")
    c.add_argument("path", nargs="?", default=".", help="repo root (default: .)")
    c.add_argument("--gate", action="store_true", help="exit 1 on findings (default: warn-only)")
    c.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    if args.cmd != "check":
        ap.error("unknown command")
    repo = _repo(Path(args.path))
    result = check(repo, gate=args.gate)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        n = len(result["findings"])
        mode = "gate" if args.gate else "warn-only"
        print(
            f"mcp_servers_lint: checked {len(result['checked_configs'])} configs, "
            f"{len(result['registry_ids'])} registry ids ({mode})"
        )
        for f in result["findings"]:
            loc = f["path"]
            if f.get("server"):
                loc = f"{loc} [{f['server']}]"
            print(f"  WARN  {loc}: {f['reason']}")
        if result["findings"] and not args.gate:
            print("  (warn-only; pass --gate to fail)")
        if args.gate and result["findings"]:
            print(f"mcp_servers_lint: {n} finding(s)", file=sys.stderr)
            return 1
    if args.gate and result["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

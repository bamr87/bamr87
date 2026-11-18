#!/usr/bin/env python3
"""
File: tools/mcp_servers_lint.py
Description: Warn-then-fail lint for MCP client configs, the hub MCP
             registry (constitution § 25 / docs/MCP-SERVERS.md) and every
             committed MCP Registry server.json manifest (constitution § 16.4):
             its shape, its name in the io.github.<owner>/<server> namespace,
             a specific version, no secret literal and no machine-local
             endpoint, and the console manifest's version equal to the
             mcp_layer VERSION. Default is warn-only (exit 0); --gate exits 1
             on findings.
Author: bamr87
Created: 2026-11-05
Usage: python3 tools/mcp_servers_lint.py check [PATH] [--gate] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
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

# MCP Registry server.json (schema 2025-12-11, constitution § 16.4). The fleet names
# servers in the registry's GitHub namespace; the schema itself allows any reverse-DNS
# namespace, so this is the stricter fleet rule.
SERVER_MANIFEST = "server.json"
SERVER_SCHEMA_RE = re.compile(
    r"^https://static\.modelcontextprotocol\.io/schemas/\d{4}-\d{2}-\d{2}/server\.schema\.json$"
)
SERVER_NAME_RE = re.compile(r"^io\.github\.[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
VERSION_RANGE_RE = re.compile(r"[\^~<>=*\s]|(?:^|\.)[xX](?:$|\.)")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"^\{[A-Za-z0-9_.-]+\}$")
# One machine's endpoint never belongs in a manifest: loopback, the Docker host alias,
# and quick-tunnel hostnames, which change on every restart (constitution § 25.6).
LOCAL_ENDPOINT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9.-])(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[::1\]|"
    r"host\.docker\.internal|[a-z0-9-]+\.trycloudflare\.com)(?![A-Za-z0-9-])"
)
LOCAL_TRANSPORTS = ("stdio", "streamable-http", "sse")
REMOTE_TRANSPORTS = ("streamable-http", "sse")
PUBLISHER_META = "io.modelcontextprotocol.registry/publisher-provided"
# Directories the manifest walk never enters: submodules are their own pyramids, the
# rest are build output, dependencies and local state.
SKIP_DIRS = frozenset(
    {".git", "node_modules", "projects", "_site", "dist", "build", "__pycache__", ".fleet", ".dash-live"}
)
# The hub's own console server: its manifest's version follows mcp_layer's VERSION.
HUB_MANIFEST = "tools/console/server.json"
HUB_VERSION_SOURCE = "tools/console/mcp_layer/server.py"
VERSION_LITERAL_RE = re.compile(r"""^VERSION\s*=\s*["']([^"']+)["']""", re.M)


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


def find_server_manifests(repo: Path) -> list[str]:
    """Every committed-style server.json under repo, as sorted posix paths.

    Submodules (projects/), dependencies, build output, virtualenvs and local
    state are skipped: a spoke's manifest is linted in its own repo.
    """
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".venv"))
        if SERVER_MANIFEST in filenames:
            found.append((Path(dirpath) / SERVER_MANIFEST).relative_to(repo).as_posix())
    return sorted(found)


def _version_ok(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        return False
    return value.strip().lower() != "latest" and not VERSION_RANGE_RE.search(value)


def _check_env_inputs(rel: str, sid: str, where: str, items: object, *, names_only: bool) -> list[dict]:
    """environmentVariables entries: an env name each, and never a secret's value.

    names_only (the publisher-provided launch block) forbids any value or default;
    a package entry may carry a value, but a secret one only as a {placeholder}.
    """
    if items is None:
        return []
    if not isinstance(items, list):
        return [{"path": rel, "server": sid, "reason": f"{where} must be a list"}]
    findings: list[dict] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            findings.append({"path": rel, "server": sid, "reason": f"{where}[{i}] needs a name"})
            continue
        name = item["name"]
        if not ENV_NAME_RE.match(name):
            findings.append(
                {"path": rel, "server": sid, "reason": f"{where}[{i}] name {name!r} is not an env var name"}
            )
        secret = item.get("isSecret") is True or bool(SECRET_KEY_RE.search(name))
        for key in ("value", "default"):
            if key not in item:
                continue
            val = item[key]
            if names_only:
                findings.append(
                    {"path": rel, "server": sid, "reason": f"{where}[{i}] {name}: names only, no {key}"}
                )
            elif secret and not (isinstance(val, str) and PLACEHOLDER_RE.match(val)):
                findings.append(
                    {
                        "path": rel,
                        "server": sid,
                        "reason": f"{where}[{i}] {name}: a secret's {key} must be a {{placeholder}}, "
                        "never a literal",
                    }
                )
    return findings


def _check_server_manifest(repo: Path, rel: str) -> list[dict]:
    """Shape of one MCP Registry server.json: the schema's required fields, the
    fleet's name rule, a transport, and nothing secret or machine-local."""
    data, err = _load_json(repo / rel)
    if err:
        return [{"path": rel, "server": "", "reason": f"invalid JSON: {err}"}]
    assert data is not None
    name = data.get("name")
    sid = name if isinstance(name, str) else ""
    findings: list[dict] = []

    def add(reason: str) -> None:
        findings.append({"path": rel, "server": sid, "reason": reason})

    schema = data.get("$schema")
    if not isinstance(schema, str) or not SERVER_SCHEMA_RE.match(schema):
        add(
            "$schema must be the MCP Registry schema URL "
            "(static.modelcontextprotocol.io/schemas/<date>/server.schema.json)"
        )
    if not isinstance(name, str) or not SERVER_NAME_RE.match(name) or len(name) > 200:
        add("name must be io.github.<owner>/<server> (the MCP Registry GitHub namespace)")
    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 100:
        add("description must be 1-100 characters")
    if not _version_ok(data.get("version")):
        add("version must be one specific version: no range, not 'latest'")
    repository = data.get("repository")
    if repository is not None and (
        not isinstance(repository, dict) or not repository.get("url") or not repository.get("source")
    ):
        add("repository needs url and source")

    transports: list[str] = []
    packages = data.get("packages") or []
    if not isinstance(packages, list):
        add("packages must be a list")
        packages = []
    for i, pkg in enumerate(packages):
        if not isinstance(pkg, dict) or not pkg.get("registryType") or not pkg.get("identifier"):
            add(f"packages[{i}] needs registryType and identifier")
            continue
        if "version" in pkg and not _version_ok(pkg["version"]):
            add(f"packages[{i}] version must be one specific version: no range, not 'latest'")
        t = pkg.get("transport")
        ttype = t.get("type") if isinstance(t, dict) else None
        if ttype not in LOCAL_TRANSPORTS:
            add(f"packages[{i}] transport.type must be one of {', '.join(LOCAL_TRANSPORTS)}")
        else:
            transports.append(ttype)
        findings.extend(
            _check_env_inputs(
                rel, sid, f"packages[{i}].environmentVariables",
                pkg.get("environmentVariables"), names_only=False,
            )
        )
    remotes = data.get("remotes") or []
    if not isinstance(remotes, list):
        add("remotes must be a list")
        remotes = []
    for i, remote in enumerate(remotes):
        rtype = remote.get("type") if isinstance(remote, dict) else None
        if rtype not in REMOTE_TRANSPORTS or not remote.get("url"):
            add(f"remotes[{i}] needs type ({', '.join(REMOTE_TRANSPORTS)}) and url")
        else:
            transports.append(rtype)

    meta = data.get("_meta")
    publisher = meta.get(PUBLISHER_META) if isinstance(meta, dict) else None
    if isinstance(publisher, dict):
        t = publisher.get("transport")
        if t is not None:
            ttype = t.get("type") if isinstance(t, dict) else None
            if ttype not in LOCAL_TRANSPORTS:
                add(f"_meta publisher-provided transport.type must be one of {', '.join(LOCAL_TRANSPORTS)}")
            else:
                transports.append(ttype)
        findings.extend(
            _check_env_inputs(
                rel, sid, "_meta publisher-provided environmentVariables",
                publisher.get("environmentVariables"), names_only=True,
            )
        )
    if not transports:
        add("declares no transport: packages[].transport, remotes[] or _meta publisher-provided transport")

    blob = json.dumps(data)
    if INLINE_SECRET_RE.search(blob):
        add("inline credential pattern in server.json")
    if LOCAL_ENDPOINT_RE.search(blob):
        add("a machine-local endpoint (loopback, Docker host or quick tunnel) never belongs in server.json")
    return findings


def _hub_manifest_findings(repo: Path) -> list[dict]:
    """The console MCP server ships a server.json whose version is mcp_layer's VERSION."""
    source = repo / HUB_VERSION_SOURCE
    if not source.is_file():
        return []
    manifest = repo / HUB_MANIFEST
    if not manifest.is_file():
        return [
            {
                "path": HUB_MANIFEST,
                "server": "fleet",
                "reason": "the console MCP server has no MCP Registry server.json (constitution § 16.4)",
            }
        ]
    match = VERSION_LITERAL_RE.search(source.read_text(encoding="utf-8"))
    if not match:
        return [
            {"path": HUB_VERSION_SOURCE, "server": "fleet", "reason": 'no VERSION = "…" literal to compare'}
        ]
    data, err = _load_json(manifest)
    if err or data is None:
        return []  # reported by _check_server_manifest
    if data.get("version") != match.group(1):
        return [
            {
                "path": HUB_MANIFEST,
                "server": "fleet",
                "reason": f"version {data.get('version')!r} differs from {HUB_VERSION_SOURCE} VERSION "
                f"{match.group(1)!r}: bump both together",
            }
        ]
    return []


def _registry_manifest_findings(repo: Path, sid: str, row: dict) -> list[dict]:
    """A registry row's server_json: the file exists and is named for the row's id (§ 25.4)."""
    rel = row.get("server_json")
    if not rel or row.get("status") == "spoke":
        return []  # a spoke's manifest lives in its own repo
    where = "_data/mcp_servers.yml"
    if not isinstance(rel, str) or not (repo / rel).is_file():
        return [{"path": where, "server": sid, "reason": f"server_json {rel!r} does not exist"}]
    data, err = _load_json(repo / rel)
    if err or data is None:
        return []  # reported by _check_server_manifest
    name = data.get("name")
    if not isinstance(name, str) or name.rsplit("/", 1)[-1] != sid:
        return [
            {
                "path": rel,
                "server": sid,
                "reason": f"name {name!r} must end in /{sid}, the registry id (constitution § 25.4)",
            }
        ]
    return []


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
            findings.extend(_registry_manifest_findings(repo, sid, row))

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

    server_manifests = find_server_manifests(repo)
    for rel in server_manifests:
        findings.extend(_check_server_manifest(repo, rel))
    findings.extend(_hub_manifest_findings(repo))

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
        "server_manifests": server_manifests,
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
    c = sub.add_parser("check", help="lint MCP configs, the registry and server.json manifests")
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
            f"{len(result['server_manifests'])} server.json, "
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

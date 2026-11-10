#!/usr/bin/env python3
"""
File: tools/claude_code_executes_lint.py
Description: Warn-then-fail lint for constitution § 26 (Claude Code executes;
             Grok bots set direction only). Locally validates agent_roles.yml
             and, with --files, whether a path set is direction-setting.
             Optional --pr uses `gh` to warn on known Grok authors.
Author: bamr87
Created: 2026-11-05
Usage:
  python3 tools/claude_code_executes_lint.py check [PATH] [--gate] [--json]
  python3 tools/claude_code_executes_lint.py check [PATH] --files a b [--gate]
  python3 tools/claude_code_executes_lint.py check [PATH] --pr N [--gate]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def _repo(path: Path) -> Path:
    return path.resolve()


def _load_roles(repo: Path) -> tuple[dict | None, str | None]:
    path = repo / "_data" / "agent_roles.yml"
    if not path.is_file():
        return None, "missing _data/agent_roles.yml"
    if yaml is None:
        return None, "PyYAML required"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    if not isinstance(data, dict):
        return None, "agent_roles.yml root must be a mapping"
    return data, None


def _is_direction_setting(rel: str, prefixes: list[str]) -> bool:
    rel = rel.lstrip("./")
    for p in prefixes:
        p = p.lstrip("./")
        if rel == p or rel.startswith(p.rstrip("/") + "/") or rel.startswith(p):
            return True
    return False


def check(
    repo: Path,
    *,
    gate: bool = False,
    files: list[str] | None = None,
    pr: int | None = None,
) -> dict:
    findings: list[dict] = []
    roles, err = _load_roles(repo)
    prefixes: list[str] = []
    warn_logins: list[str] = []
    if err:
        findings.append({"reason": err, "path": "_data/agent_roles.yml"})
    else:
        assert roles is not None
        if roles.get("schema") != "agent-roles/v1":
            findings.append(
                {
                    "reason": "schema must be agent-roles/v1",
                    "path": "_data/agent_roles.yml",
                }
            )
        prefixes = [str(x) for x in (roles.get("direction_setting_path_prefixes") or [])]
        warn_logins = [str(x) for x in (roles.get("github_logins_warn") or [])]
        if not roles.get("executors"):
            findings.append({"reason": "executors list missing", "path": "_data/agent_roles.yml"})
        if not roles.get("directors"):
            findings.append({"reason": "directors list missing", "path": "_data/agent_roles.yml"})
        if not prefixes:
            findings.append(
                {
                    "reason": "direction_setting_path_prefixes empty",
                    "path": "_data/agent_roles.yml",
                }
            )

    # constitution section present?
    constitution = repo / "docs" / "constitution.md"
    if constitution.is_file():
        text = constitution.read_text(encoding="utf-8", errors="replace")
        if "Claude Code executes" not in text:
            findings.append(
                {
                    "reason": "constitution missing Claude Code executes section",
                    "path": "docs/constitution.md",
                }
            )
    else:
        findings.append({"reason": "docs/constitution.md missing", "path": "docs/constitution.md"})

    non_direction: list[str] = []
    if files:
        for f in files:
            if not _is_direction_setting(f, prefixes):
                non_direction.append(f)
                findings.append(
                    {
                        "reason": "path is not direction-setting under § 26",
                        "path": f,
                    }
                )

    pr_author = None
    if pr is not None:
        try:
            out = subprocess.check_output(
                [
                    "gh",
                    "pr",
                    "view",
                    str(pr),
                    "--json",
                    "author,files,labels,title",
                    "-q",
                    ".",
                ],
                cwd=str(repo),
                text=True,
            )
            payload = json.loads(out)
            pr_author = (payload.get("author") or {}).get("login")
            labels = {l.get("name") for l in payload.get("labels") or []}
            if "direction-setting" in labels or "pre-§26" in labels or "pre-s26" in labels:
                pass  # labelled exception / grandfather
            elif pr_author and warn_logins and pr_author in warn_logins:
                changed = [f.get("path") for f in payload.get("files") or [] if f.get("path")]
                bad = [p for p in changed if not _is_direction_setting(p, prefixes)]
                for p in bad:
                    findings.append(
                        {
                            "reason": f"Grok-warn author {pr_author!r} changed non-direction path",
                            "path": p,
                        }
                    )
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            findings.append({"reason": f"could not inspect PR: {e}", "path": f"pr:{pr}"})

    result = {
        "checker": "claude_code_executes_lint",
        "section": "constitution § 26",
        "findings": findings,
        "non_direction_files": non_direction,
        "pr_author": pr_author,
        "gate": gate,
        "ok": not findings if gate else True,
        "warn_only": not gate,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="lint agent_roles + optional paths/PR")
    c.add_argument("path", nargs="?", default=".", help="repo root")
    c.add_argument("--gate", action="store_true")
    c.add_argument("--json", action="store_true")
    c.add_argument("--files", nargs="*", default=None, help="changed paths to classify")
    c.add_argument("--pr", type=int, default=None, help="PR number to inspect via gh")
    args = ap.parse_args(argv)
    repo = _repo(Path(args.path))
    result = check(repo, gate=args.gate, files=args.files, pr=args.pr)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        mode = "gate" if args.gate else "warn-only"
        print(f"claude_code_executes_lint: {len(result['findings'])} finding(s) ({mode})")
        for f in result["findings"]:
            print(f"  WARN  {f.get('path', '')}: {f['reason']}")
        if result["findings"] and not args.gate:
            print("  (warn-only; pass --gate to fail)")
    if args.gate and result["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

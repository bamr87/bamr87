#!/usr/bin/env python3
"""
reconcile.py — keep the project registry in sync with GitHub reality.

Closes the loop that `check-drift.sh` check (g) only *opens*: (g) detects that
the registry disagrees with GitHub and warns, but nothing ever acts on it. This
module classifies the same drift and can write the fixes it is actually safe to
write.

Three sources are compared:

  1. `_data/projects.yml`  — the registry (repo_url, branch, submodule_path)
  2. `.gitmodules`         — the submodule declarations (url, branch, path)
  3. GitHub                — existence, canonical full_name, default_branch

Findings are routed by how trustworthy the signal is, which is the whole point
of the split:

  AUTHORITATIVE — GitHub states these unambiguously, so `--apply` writes them:
    renamed        repo moved; GitHub resolves the old slug to a new full_name
    url-mismatch   registry repo_url != .gitmodules url (internal inconsistency)

  ADVISORY — reported, never auto-applied:
    branch-drift   declared branch != GitHub default. Often DELIBERATE — this
                   fleet intentionally tracks `master` on scripts and `dev` on
                   sonic-pi — so "fixing" it automatically would be wrong.
    missing        404. A repo-scoped token 404s on a *private* repo exactly as
                   it does on a deleted one, so auto-deregistering here would
                   eventually delete a live project. Humans decide.
    unverifiable   API error that is neither of the above.

Writes are surgical: the registry keeps its comments and formatting (only the
one offending `repo_url:` line is rewritten) and `.gitmodules` is edited via
`git config -f`, never regenerated.

Auth: a token from GH_TOKEN / GITHUB_TOKEN, else `gh auth token`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import yaml

import actions_analytics  # owner_repo, resolve_token

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "_data" / "projects.yml"
GITMODULES = REPO_ROOT / ".gitmodules"

# Kinds that `--apply` is allowed to write. Everything else is report-only.
AUTHORITATIVE = ("renamed", "url-mismatch")
ADVISORY = ("branch-drift", "missing", "token-scope", "unverifiable")

# If more than this share of probed repos 404, the token almost certainly cannot
# see private repos — it is not that the fleet was mass-deleted overnight. CI's
# default GITHUB_TOKEN is repo-scoped and 404s on every private repo in the
# fleet, which would otherwise flood the nightly issue with false "missing"
# findings and train everyone to ignore it.
BLIND_TOKEN_RATIO = 0.25


@dataclass
class Finding:
    kind: str
    name: str
    detail: str
    submodule_path: str | None = None
    current: str | None = None
    proposed: str | None = None

    @property
    def authoritative(self) -> bool:
        return self.kind in AUTHORITATIVE


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_gitmodules(path: Path | None = None) -> dict[str, dict[str, str]]:
    """.gitmodules -> {submodule name: {path, url, branch}}.

    Parsed by hand rather than via `git config` so this stays usable when the
    file is inspected outside a work tree.
    """
    path = path or GITMODULES
    mods: dict[str, dict[str, str]] = {}
    cur: str | None = None
    if not path.exists():
        return mods
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        m = re.match(r'\[submodule "(.+)"\]', line)
        if m:
            cur = m.group(1)
            mods[cur] = {"path": "", "url": "", "branch": "main"}
            continue
        if cur and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k in ("path", "url", "branch"):
                mods[cur][k] = v
    return mods


def load_registry(path: Path | None = None) -> list[dict]:
    return yaml.safe_load((path or REGISTRY).read_text(encoding="utf-8")) or []


def norm_url(url: str | None) -> str:
    """Compare URLs without being tripped by .git / trailing slash / case."""
    if not url:
        return ""
    return url.strip().rstrip("/").removesuffix(".git").lower()


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------

def probe(gh, nwo: str) -> tuple[str, str | None, str | None]:
    """(status, full_name, default_branch) for one owner/repo.

    status is 'ok' | 'missing' | 'error'.
    """
    try:
        repo = gh.get_repo(nwo)
        return "ok", repo.full_name, repo.default_branch
    except Exception as exc:  # PyGithub raises UnknownObjectException on 404
        status = getattr(exc, "status", None)
        if status == 404:
            return "missing", None, None
        return "error", None, None


def collect(gh, registry: list[dict], mods: dict[str, dict[str, str]]) -> list[Finding]:
    """Compare all three sources and classify every disagreement."""
    findings: list[Finding] = []
    probed = 0

    # .gitmodules url indexed by submodule path, for the internal-consistency check
    gm_by_path = {m["path"]: m for m in mods.values() if m.get("path")}

    for entry in registry:
        name = entry.get("name", "?")
        repo_url = entry.get("repo_url") or ""
        sub_path = entry.get("submodule_path")
        nwo = actions_analytics.owner_repo(repo_url)
        if not nwo:
            continue

        # (1) internal: registry repo_url vs .gitmodules url
        gm = gm_by_path.get(sub_path) if sub_path else None
        if gm and norm_url(gm["url"]) != norm_url(repo_url):
            findings.append(Finding(
                kind="url-mismatch", name=name, submodule_path=sub_path,
                detail=f"registry repo_url and .gitmodules url disagree",
                current=gm["url"], proposed=repo_url,
            ))

        # (2) external: what does GitHub actually say?
        probed += 1
        status, full, default_branch = probe(gh, nwo)
        if status == "missing":
            findings.append(Finding(
                kind="missing", name=name, submodule_path=sub_path,
                detail=f"{nwo} returns 404 (deleted, renamed without redirect, or private to this token)",
                current=repo_url,
            ))
            continue
        if status == "error":
            findings.append(Finding(
                kind="unverifiable", name=name, submodule_path=sub_path,
                detail=f"could not verify {nwo}", current=repo_url,
            ))
            continue

        if full and full.lower() != nwo.lower():
            findings.append(Finding(
                kind="renamed", name=name, submodule_path=sub_path,
                detail=f"renamed on GitHub: {nwo} -> {full}",
                current=repo_url, proposed=f"https://github.com/{full}",
            ))

        declared = entry.get("branch")
        if sub_path and declared and default_branch and declared != default_branch:
            findings.append(Finding(
                kind="branch-drift", name=name, submodule_path=sub_path,
                detail=(f"declared branch '{declared}' but GitHub default is "
                        f"'{default_branch}' (may be intentional)"),
                current=declared, proposed=default_branch,
            ))

    return collapse_blind_token(findings, probed)


def collapse_blind_token(findings: list[Finding], probed: int) -> list[Finding]:
    """Replace a pile of 404s with one 'your token is blind' finding.

    A repo-scoped token (CI's default GITHUB_TOKEN) 404s on every private repo
    in the fleet. Reported verbatim that is a dozen false "deleted" alarms per
    night; collapsed, it is one actionable line telling you to grant the token
    private-repo visibility.
    """
    missing = [f for f in findings if f.kind == "missing"]
    if not probed or len(missing) <= 1 or len(missing) / probed < BLIND_TOKEN_RATIO:
        return findings

    names = ", ".join(sorted(f.name for f in missing))
    collapsed = [f for f in findings if f.kind != "missing"]
    collapsed.append(Finding(
        kind="token-scope",
        name="(token)",
        detail=(f"{len(missing)}/{probed} repos returned 404 — the token almost "
                f"certainly cannot see private repos rather than the fleet having "
                f"been deleted. Grant private-repo read (e.g. set "
                f"FLEET_TOKEN) and re-run before believing any of "
                f"these: {names}"),
    ))
    return collapsed


# --------------------------------------------------------------------------
# surgical writes
# --------------------------------------------------------------------------

def rewrite_registry_url(name: str, new_url: str, path: Path | None = None) -> bool:
    """Replace repo_url for one entry, leaving every other byte untouched."""
    path = path or REGISTRY
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out, in_entry, changed = [], False, False
    for line in lines:
        if re.match(r"^- name:\s*", line):
            in_entry = re.match(r"^- name:\s*'?\"?" + re.escape(name) + r"'?\"?\s*$", line) is not None
        if in_entry and re.match(r"^\s+repo_url:\s*", line) and not changed:
            indent = re.match(r"^(\s+)", line).group(1)
            out.append(f"{indent}repo_url: {new_url}\n")
            changed = True
            continue
        out.append(line)
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def rewrite_gitmodules_url(sub_name: str, new_url: str, path: Path | None = None) -> bool:
    r = subprocess.run(
        ["git", "config", "-f", str(path or GITMODULES), f"submodule.{sub_name}.url", new_url],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return r.returncode == 0


def apply_fixes(
    findings: list[Finding],
    mods: dict[str, dict[str, str]],
    registry_path: Path | None = None,
    gitmodules_path: Path | None = None,
) -> list[str]:
    """Write only the authoritative fixes. Returns human-readable change lines."""
    applied: list[str] = []
    name_by_path = {m["path"]: n for n, m in mods.items() if m.get("path")}

    for f in findings:
        if not f.authoritative or not f.proposed:
            continue
        if f.kind == "renamed":
            if rewrite_registry_url(f.name, f.proposed, registry_path):
                applied.append(f"{f.name}: registry repo_url -> {f.proposed}")
            sub = name_by_path.get(f.submodule_path or "")
            if sub and rewrite_gitmodules_url(sub, f.proposed + ".git", gitmodules_path):
                applied.append(f"{f.name}: .gitmodules url -> {f.proposed}.git")
        elif f.kind == "url-mismatch":
            # Converge .gitmodules onto the registry, which is the declared
            # source of truth per docs/DASH.md.
            sub = name_by_path.get(f.submodule_path or "")
            if sub and rewrite_gitmodules_url(sub, f.proposed, gitmodules_path):
                applied.append(f"{f.name}: .gitmodules url -> {f.proposed} (matched registry)")
    return applied


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def render(findings: list[Finding]) -> str:
    if not findings:
        return "  ✓ registry matches GitHub (names, urls, branches)\n"
    buckets: dict[str, list[Finding]] = {}
    for f in findings:
        buckets.setdefault(f.kind, []).append(f)
    order = list(AUTHORITATIVE) + list(ADVISORY)
    out = []
    for kind in order:
        if kind not in buckets:
            continue
        tag = "auto-fixable" if kind in AUTHORITATIVE else "needs a human"
        out.append(f"  [{kind}] ({tag})")
        for f in buckets[kind]:
            out.append(f"    - {f.name}: {f.detail}")
    return "\n".join(out) + "\n"


def issue_body(findings: list[Finding]) -> str:
    """Markdown for the tracking issue covering the advisory findings."""
    advisory = [f for f in findings if not f.authoritative]
    lines = [
        "The nightly registry reconciliation found drift that needs a human decision.",
        "",
        "These are **not** auto-fixed on purpose: a repo-scoped token 404s on a private",
        "repo exactly as it does on a deleted one, and a non-default branch is often a",
        "deliberate choice in this fleet.",
        "",
    ]
    for kind in ADVISORY:
        rows = [f for f in advisory if f.kind == kind]
        if not rows:
            continue
        lines.append(f"### {kind}")
        lines.append("")
        for f in rows:
            path = f" (`{f.submodule_path}`)" if f.submodule_path else ""
            lines.append(f"- **{f.name}**{path} — {f.detail}")
        lines.append("")
    lines.append("---")
    lines.append("Generated by `dash-gen reconcile`. Re-run locally: `tools/dash-gen reconcile`.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------

def run(args) -> int:
    try:
        from github import Auth, Github
    except ImportError:
        sys.stderr.write("PyGithub not installed (pip install -r requirements.txt)\n")
        return 2

    token = actions_analytics.resolve_token()
    if not token:
        sys.stderr.write("No GitHub token (set GH_TOKEN/GITHUB_TOKEN or run `gh auth login`).\n")
        return 2

    gh = Github(auth=Auth.Token(token), per_page=100)
    registry = load_registry()
    mods = parse_gitmodules()
    findings = collect(gh, registry, mods)

    applied: list[str] = []
    if args.apply:
        applied = apply_fixes(findings, mods)

    if args.json:
        print(json.dumps({
            "findings": [asdict(f) for f in findings],
            "authoritative": sum(1 for f in findings if f.authoritative),
            "advisory": sum(1 for f in findings if not f.authoritative),
            "applied": applied,
            "issue_body": issue_body(findings) if any(not f.authoritative for f in findings) else "",
        }, indent=2))
    else:
        sys.stdout.write(render(findings))
        for line in applied:
            sys.stdout.write(f"  applied: {line}\n")

    if args.fail_on_drift and findings:
        return 1
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true",
                        help="write the authoritative fixes (renames, url mismatches); "
                             "404s and branch drift are never auto-applied")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output (used by reconcile-registry.yml)")
    parser.add_argument("--fail-on-drift", action="store_true",
                        help="exit 1 if any drift was found (for use as a gate)")
    parser.set_defaults(func=run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reconcile", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

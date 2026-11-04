#!/usr/bin/env python3
"""
File: .github/scripts/dash-gen/agent_fill_file.py
Description: `dash-gen agent-fill-file` — the fan-out agent fill's local filer
             (JEV loop runner, bamr87/bamr87#488, ADR 0002 P3). A loop runner
             attempt leaves the adapter's validated document: the kit, the
             target, the kit branch, the commit subject CI's push step uses
             and the patch the engine harvested from the clone. This filer is
             a complete dry run of what CI's "Push the agent pass" step does —
             the exact patch and commit message, the structural rules (the
             kit's branch and subject, only the files the brief allows, no
             credential shape), and online the dedupe CI relies on (the branch
             exists and carries no `(Claude agent pass)` commit yet) — behind
             `--apply`, which the engine adds only after the § 13.6 yes;
             `--apply` is refused with exit 2, naming #488, until its publish
             step (the commit pushed to the kit's PR branch with FLEET_TOKEN
             probed by `gh api user`) lands. Nothing here writes to GitHub.

The validated item document (`--item`):

    {"kit": "standardize", "repo": "bamr87/alpha", "key": "bamr87/alpha", "branch":
     "chore/standardize-baseline", "commit_subject": "docs(agent-context): fill CLAUDE.md
     scaffold (Claude agent pass)", "patch": "agent-fill.patch", "files": ["CLAUDE.md"]}

Usage:
    dash-gen agent-fill-file --item items/<dir>/outputs/agent-fill.validated.json \\
        --run-url "local run …" --bodies-dir items/<dir>/bodies [--offline]
    …  --apply --reviewed-bodies items/<dir>/bodies      # refused: #488

Output: one JSON object on stdout — {"apply": false, "filed": [...], "skipped": [...],
"rejected": [...]}. `filed` rows carry `title` (the commit subject), `kind` ("push"),
`repo`, `branch`, `files`, `body_file`, `patch_file` and `url` (null in a dry run).
Author: bamr87
Created: 2026-11-03
Version: 0.1.0
Dependencies: Python 3.12 stdlib; `gh` on PATH unless --offline. Never imports the dash-gen entry point.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from agent_fill import AGENT_PASS_MARK, KITS, NWO_RE, branch_state

PATCH_MAX = 1024 * 1024
DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.M)
#: the same credential shapes repo_scout.SECRET_RE refuses in a proposal
SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
#: the two messages the adapter and CI read off this filer's stderr
NO_DEDUPE = "filing without the duplicate check"
APPLY_REFUSED = ("agent-fill-file --apply is not implemented in this release: the publish step (the validated "
                 "patch committed as the `(Claude agent pass)` commit and pushed to the kit's PR branch with "
                 "FLEET_TOKEN probed by `gh api user`) lands with bamr87/bamr87#488's next pull request; "
                 "nothing was pushed")


def patch_files(patch: str) -> list[str]:
    """The paths a unified diff touches, from its `diff --git` headers, in order."""
    seen: list[str] = []
    for a, b in DIFF_HEADER_RE.findall(patch):
        path = b if b != "/dev/null" else a
        if path not in seen:
            seen.append(path)
    return seen


def allowed_file(kit: str, path: str) -> bool:
    """What the kit's brief lets the agent touch: standardize edits CLAUDE.md
    alone; schema edits SCHEMA.md files (any directory, deletions included)."""
    if kit == "standardize":
        return path == "CLAUDE.md"
    if kit == "schema":
        return path.rsplit("/", 1)[-1] == "SCHEMA.md" and ".." not in path.split("/")
    return False


def load_item(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def problems(item: dict, item_dir: Path) -> list[str]:
    """Why the document cannot be filed (the structural rules)."""
    out: list[str] = []
    kit = item.get("kit")
    if kit not in KITS:
        return [f"kit must be one of {sorted(KITS)}, not {kit!r}"]
    repo = str(item.get("repo") or "")
    if not NWO_RE.fullmatch(repo):
        out.append(f"repo {repo!r} is not owner/repo")
    if item.get("key") != repo:
        out.append(f"key {item.get('key')!r} != repo {repo!r}")
    if item.get("branch") != KITS[kit]["branch"]:
        out.append(f"branch {item.get('branch')!r} is not the {kit} kit's {KITS[kit]['branch']}")
    if item.get("commit_subject") != KITS[kit]["subject"]:
        out.append(f"commit_subject is not the {kit} kit's push-step message")
    name = item.get("patch")
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        return [*out, "patch must name a file beside the document"]
    patch_path = item_dir / name
    if not patch_path.is_file() or patch_path.is_symlink():
        return [*out, f"patch {name} is missing or not a regular file"]
    if patch_path.stat().st_size > PATCH_MAX:
        return [*out, f"patch {name} is over {PATCH_MAX} bytes"]
    text = patch_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        out.append("the patch is empty: the agent changed nothing")
    touched = patch_files(text)
    declared = item.get("files")
    if not isinstance(declared, list) or declared != touched:
        out.append(f"files {declared!r} do not match the patch's own headers {touched!r}")
    for path in touched:
        if not allowed_file(kit, path):
            out.append(f"the {kit} brief allows no edit to {path!r}")
    if SECRET_RE.search(text):
        out.append("the patch carries a credential shape")
    return out


def run_file(args: argparse.Namespace) -> int:
    item_path = Path(args.item)
    try:
        item = load_item(item_path)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"agent-fill-file: --item {item_path}: {exc}\n")
        return 2
    if args.apply:
        sys.stderr.write(f"agent-fill-file: {APPLY_REFUSED}\n")
        return 2
    if args.reviewed_bodies:
        sys.stderr.write("agent-fill-file: --reviewed-bodies only means something with --apply\n")
        return 2
    bodies = Path(args.bodies_dir)
    bodies.mkdir(parents=True, exist_ok=True)
    title = str(item.get("commit_subject") or "?")[:120]
    rejected = [{"title": title, "reason": why} for why in problems(item, item_path.parent)]
    result: dict = {"apply": False, "run_url": args.run_url, "filed": [], "skipped": [], "rejected": rejected}
    if rejected:
        print(json.dumps(result, separators=(",", ":")))
        return 0
    repo, branch = str(item["repo"]), str(item["branch"])
    if not args.offline:
        state, dedupe = branch_state(repo, branch)
        if state == "missing":
            result["rejected"].append({"title": title, "reason": f"no {branch} on {repo}: the fan-out has not pushed "
                                                                 "the kit branch (or it was merged and deleted)"})
            print(json.dumps(result, separators=(",", ":")))
            return 0
        if dedupe == "filled":
            result["skipped"].append({"title": title, "reason": f"{branch} already carries a {AGENT_PASS_MARK} commit"})
            print(json.dumps(result, separators=(",", ":")))
            return 0
        if dedupe == "unavailable":
            sys.stderr.write(f"agent-fill-file: could not read {repo}@{branch} — {NO_DEDUPE}\n")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repo).strip("-.")[:80] or "item"
    patch_file = bodies / f"{slug}.patch"
    patch_file.write_bytes((item_path.parent / str(item["patch"])).read_bytes())
    body_file = bodies / f"{slug}.md"
    files = list(item["files"])
    body_file.write_text(f"{item['commit_subject']}\n\nFiled from {args.run_url or 'a local run'} onto {repo}@{branch}: "
                         f"{', '.join(files)}.\n", encoding="utf-8")
    result["filed"].append({"title": item["commit_subject"], "kind": "push", "repo": repo, "branch": branch,
                            "files": files, "body_file": str(body_file), "patch_file": str(patch_file), "url": None})
    sys.stderr.write(f"agent-fill-file: dry run — would push the agent pass to {repo}@{branch}: {title}\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", required=True, metavar="PATH", help="the adapter's validated item document")
    parser.add_argument("--run-url", default="", metavar="TEXT", help="the run this filing comes from")
    parser.add_argument("--bodies-dir", required=True, metavar="DIR", help="where the exact patch and message are written")
    parser.add_argument("--offline", action="store_true", help="no GitHub reads: no branch or agent-pass dedupe")
    parser.add_argument("--apply", action="store_true", help="push it (refused in this release: #488)")
    parser.add_argument("--reviewed-bodies", default=None, metavar="DIR",
                        help="with --apply: push only a patch byte-identical to this reviewed preview")
    parser.set_defaults(func=run_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dash-gen agent-fill-file", description=__doc__.split("\n\n")[0])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

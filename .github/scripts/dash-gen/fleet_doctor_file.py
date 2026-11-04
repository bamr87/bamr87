#!/usr/bin/env python3
"""
fleet_doctor_file — the fleet doctor's local FILER (`dash-gen doctor-file`).

In CI the doctor agent files its own work: it pushes a `fix/fleet-doctor-*`
branch and opens a draft PR (Step 3a / 3b of its prompt), or files one hub
issue (Step 3c), holding FLEET_TOKEN while it does. A LOCAL attempt (the JEV
loop runner, tools/jev/steps/fleet-pulse/doctor.yml) hands the agent no
credential and no network, so the agent's edits come out as a patch and the
filing it attempted (its `gh pr create` / `gh issue create` call, refused by
the permission layer) comes out as a title and a body. The adapter
(tools/jev/adapters/fleet_pulse_doctor.py) writes both into ONE validated
item document; this filer turns it into what the maintainer reviews, and —
behind `--apply`, which the engine adds only after the § 13.6 yes — into the
PR or the issue CI would have opened.

THIS RELEASE FILES NOTHING. The dry run is complete (the exact body bytes,
the patch, the dedupe against the hub's and the target's open markers, the
structural rules); `--apply` is refused with exit 2, naming bamr87/bamr87#488,
until the publish step (push with FLEET_TOKEN probed by `gh api user`, a
draft PR carrying the MARKER line CI dedupes on, or the hub issue) lands in
that issue's next pull request. Nothing here can write to GitHub.

The validated item document (`--item`):

    {"kind": "pr" | "issue", "repo": "owner/repo", "where": "hub" | "submodule",
     "key": "owner/repo:.github/workflows/x.yml", "marker": "<!-- fleet-doctor key=\"…\" -->",
     "title": "…", "body": "<marker line>\\n…", "branch": "fix/fleet-doctor-<slug>" | null,
     "patch": "changes.patch" | null (beside the document), "source": "gh-call" | "result-text"}

Usage:
    dash-gen doctor-file --item items/<dir>/outputs/doctor.validated.json \\
        --run-url "local run …" --bodies-dir items/<dir>/bodies [--offline]
    …  --apply --reviewed-bodies items/<dir>/bodies      # refused: #488

Output: one JSON object on stdout — {"apply": false, "filed": [...], "skipped": [...],
"rejected": [...]}. `filed` rows carry `title`, `kind`, `repo`, `labels`, `body_file`,
`patch_file`, `branch` and `url` (null until an apply exists).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import remediation

HUB_DEFAULT = "bamr87/bamr87"
LABELS = ["fleet-doctor", "automation"]
TITLE_MAX = 200
BODY_MAX = 60_000
PATCH_MAX = 512 * 1024
BRANCH_RE = re.compile(r"fix/fleet-doctor-[a-z0-9][a-z0-9._-]{0,80}")
NWO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
#: the same credential shapes repo_scout.SECRET_RE refuses in a proposal
SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
#: the two messages the adapter and CI read off this filer's stderr
NO_DEDUPE = "filing without the duplicate check"
APPLY_REFUSED = ("doctor-file --apply is not implemented in this release: the publish step (a fix branch pushed with "
                 "FLEET_TOKEN probed by `gh api user` and a draft PR, or the hub issue, each carrying the MARKER line) "
                 "lands with bamr87/bamr87#488's next pull request; nothing was filed")


def load_item(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the item document is not a JSON object")
    return data


def problems(item: dict, item_dir: Path) -> list[str]:
    """Why the document cannot be filed (the structural rules)."""
    out: list[str] = []
    kind = item.get("kind")
    if kind not in ("pr", "issue"):
        out.append(f"kind must be pr or issue, not {kind!r}")
    repo = str(item.get("repo") or "")
    if not NWO_RE.fullmatch(repo):
        out.append(f"repo {repo!r} is not owner/repo")
    marker = str(item.get("marker") or "")
    key = remediation.MARKER_RE.fullmatch(marker)
    if not key:
        out.append("marker is not a fleet-doctor marker line")
    elif key.group(1) != item.get("key"):
        out.append(f"marker key {key.group(1)!r} != item key {item.get('key')!r}")
    title = str(item.get("title") or "").strip()
    if not title or len(title) > TITLE_MAX or "\n" in title:
        out.append(f"title is empty, multi-line or over {TITLE_MAX} characters")
    body = str(item.get("body") or "")
    if not body.strip():
        out.append("body is empty")
    elif body.splitlines()[0].strip() != marker:
        out.append("the body's first line is not the MARKER line (tomorrow's run would re-file it)")
    if len(body.encode("utf-8")) > BODY_MAX:
        out.append(f"body over {BODY_MAX} bytes")
    if SECRET_RE.search(title) or SECRET_RE.search(body):
        out.append("the title or body carries a credential shape")
    patch = item.get("patch")
    if kind == "pr":
        branch = str(item.get("branch") or "")
        if not BRANCH_RE.fullmatch(branch):
            out.append(f"branch {branch!r} is not fix/fleet-doctor-<slug>")
        if not patch:
            out.append("a pr needs a patch")
    if patch:
        p = item_dir / str(patch)
        if not isinstance(patch, str) or "/" in patch or not p.is_file() or p.is_symlink():
            out.append(f"patch {patch!r} is not a regular file beside the item document")
        else:
            data = p.read_bytes()
            if not data.strip():
                out.append("the patch is empty")
            elif len(data) > PATCH_MAX:
                out.append(f"the patch is over {PATCH_MAX} bytes")
            elif SECRET_RE.search(data.decode("utf-8", errors="replace")):
                out.append("the patch carries a credential shape")
    return out


def open_keys(hub: str, repo: str, *, offline: bool) -> tuple[set[str] | None, str]:
    """The marker keys with an open issue or PR in the hub and in the target
    repo; None (with why) when the read failed — the caller then skips the
    filing rather than risking a duplicate."""
    if offline:
        return None, "offline"
    try:
        seen = remediation.open_markers(hub)
        if repo != hub:
            seen |= remediation.cross_repo_open_markers([repo])
    except Exception as exc:  # noqa: BLE001 - gh's failure modes are many; the answer is the same: do not dedupe
        return None, f"{type(exc).__name__}: {exc}"
    return seen, ""


def run_file(args: argparse.Namespace) -> int:
    item_path = Path(args.item)
    try:
        item = load_item(item_path)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"doctor-file: --item {item_path}: {exc}\n")
        return 2
    if args.apply:
        sys.stderr.write(f"doctor-file: {APPLY_REFUSED}\n")
        return 2
    if args.reviewed_bodies:
        sys.stderr.write("doctor-file: --reviewed-bodies only means something with --apply\n")
        return 2
    bodies = Path(args.bodies_dir)
    bodies.mkdir(parents=True, exist_ok=True)
    rejected = [{"title": str(item.get("title") or "?")[:80], "reason": why}
                for why in problems(item, item_path.parent)]
    result: dict = {"apply": False, "run_url": args.run_url, "filed": [], "skipped": [], "rejected": rejected}
    if rejected:
        print(json.dumps(result, separators=(",", ":")))
        return 0
    seen, why = open_keys(args.hub, str(item["repo"]), offline=args.offline)
    if seen is None and not args.offline:
        sys.stderr.write(f"doctor-file: could not list the open issues and PRs ({why}) — {NO_DEDUPE}\n")
    if seen is not None and item["key"] in seen:
        result["skipped"].append({"title": item["title"], "reason": "already tracked by an open issue or fix PR"})
        print(json.dumps(result, separators=(",", ":")))
        return 0
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item["key"])).strip("-.")[:80] or "item"
    body_file = bodies / f"{slug}.md"
    body_file.write_text(str(item["body"]), encoding="utf-8")
    patch_file = None
    if item.get("patch"):
        patch_file = bodies / f"{slug}.patch"
        patch_file.write_bytes((item_path.parent / str(item["patch"])).read_bytes())
    result["filed"].append({
        "title": item["title"], "kind": item["kind"], "repo": item["repo"], "where": item.get("where"),
        "labels": list(LABELS), "body_file": str(body_file), "patch_file": str(patch_file) if patch_file else None,
        "branch": item.get("branch"), "url": None,
    })
    sys.stderr.write(f"doctor-file: dry run — would open a {item['kind']} in {item['repo']}: {item['title']}\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", required=True, metavar="PATH", help="the adapter's validated item document")
    parser.add_argument("--run-url", default="", metavar="TEXT", help="the run this filing comes from")
    parser.add_argument("--bodies-dir", required=True, metavar="DIR", help="where the exact body bytes are written")
    parser.add_argument("--hub", default=HUB_DEFAULT, metavar="OWNER/REPO")
    parser.add_argument("--offline", action="store_true", help="no GitHub reads: no open-marker dedupe")
    parser.add_argument("--apply", action="store_true", help="file it (refused in this release: #488)")
    parser.add_argument("--reviewed-bodies", default=None, metavar="DIR",
                        help="with --apply: file only bodies byte-identical to this reviewed preview")
    parser.set_defaults(func=run_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doctor-file", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

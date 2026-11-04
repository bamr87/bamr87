#!/usr/bin/env python3
"""
fleet_evolve_file — the evolution agent's local FILER (`dash-gen evolve-file`).

In CI the repo-evolution workflow publishes the agent's pass itself: its
`Open draft PR` step commits the checkout as bamr87-bot, pushes an
`ai-evolution/<date>-<run>` branch to the TARGET repository (an explicit URL
derived from the matrix `nwo`, never the inherited `origin` — bamr87/bamr87#220)
and opens a draft PR there whose body starts with the brief's marker line,
holding FLEET_TOKEN while it does. A LOCAL attempt (the JEV loop runner,
tools/jev/steps/repo-evolution/evolve.yml) hands the agent no credential and
no network, so its edits come out as a patch and its final message as the PR
body. The adapter (tools/jev/adapters/repo_evolution_evolve.py) writes both
into ONE validated item document; this filer turns it into what the
maintainer reviews, and — behind `--apply`, which the engine adds only after
the § 13.6 yes — into the branch and the draft PR CI would have opened.

THIS RELEASE FILES NOTHING. The dry run is complete (the exact body bytes,
the patch, the open-pass dedupe in the target repository, the structural
rules, the #220 remote guard); `--apply` is refused with exit 2, naming
bamr87/bamr87#488, until the publish step (push with FLEET_TOKEN probed by
`gh api user`, a draft PR carrying the marker line) lands in that issue's
next pull request. Nothing here can write to GitHub.

The validated item document (`--item`):

    {"kind": "pr" | "none", "repo": "owner/repo", "key": "owner/repo", "name": "<registry name>",
     "base": "main", "marker": "<!-- repo-evolution key=\\"owner/repo\\" -->", "title": "…",
     "body": "<marker line>\\n…", "branch": "ai-evolution/<yyyymmdd>-local-<run>" | null,
     "remote": "https://github.com/owner/repo", "patch": "evolve.patch" | null (beside the document),
     "flagged": false | true (a budget hit: the body carries CI's PARTIAL warning), "source": "result-text"}

`kind: none` is CI's "No changes — no pull request opened": a valid pass that files nothing.

Usage:
    dash-gen evolve-file --item items/<dir>/outputs/evolve.validated.json \\
        --run-url "local run …" --bodies-dir items/<dir>/bodies [--offline]
    …  --apply --reviewed-bodies items/<dir>/bodies      # refused: #488

Output: one JSON object on stdout — {"apply": false, "filed": [...], "skipped": [...],
"rejected": [...]}. `filed` rows carry `title`, `kind`, `repo`, `base`, `branch`, `remote`,
`labels`, `flagged`, `body_file`, `patch_file` and `url` (null until an apply exists).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import evolution

TITLE_MAX = 200
BODY_MAX = 60_000
PATCH_MAX = 512 * 1024
NWO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,120}")
#: the same credential shapes repo_scout.SECRET_RE and fleet_doctor_file refuse
SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
#: `diff --git a/<path> b/<path>`: a path with a space is printed unquoted, an
#: unusual one in git's quoted form (`"a/\303\274.txt" "b/…"`); both are read
DIFF_HEADER = "diff --git "
_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def lockfile_re(cfg: dict) -> re.Pattern:
    """The fleet's lockfile policy (`_data/fleet.yml` `dependencies.lockfile_patterns`,
    carried on `cfg["lockfile_patterns"]` by evolution.load_config): the same
    list CI's publish step greps, so the preview and CI drop the same files."""
    pats = [str(x) for x in (cfg.get("lockfile_patterns") or evolution.DEFAULT_LOCKFILE_PATTERNS)]
    return re.compile(r"(^|/)(?:" + "|".join(re.escape(x) for x in pats) + r")$")


def _unquote(s: str) -> str:
    out = bytearray()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            octal = s[i + 1:i + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out += bytes([int(octal, 8)])
                i += 4
                continue
            if s[i + 1] in _C_ESCAPES:
                out += _C_ESCAPES[s[i + 1]].encode("utf-8")
                i += 2
                continue
        out += ch.encode("utf-8", errors="surrogateescape")
        i += 1
    return out.decode("utf-8", errors="surrogateescape")


def diff_header_path(line: str) -> str | None:
    """The new path of a `diff --git` header line, or None for any other line."""
    if not line.startswith(DIFF_HEADER):
        return None
    rest = line[len(DIFF_HEADER):].rstrip("\r\n")
    if rest.startswith('"'):
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)" "((?:[^"\\]|\\.)*)"', rest)
        if not m:
            return None
        b = _unquote(m.group(2))
        return b[2:] if b.startswith("b/") else None
    parts = rest.split(" b/")
    for k in range(1, len(parts)):   # equal halves: the engine harvests no rename
        left, right = " b/".join(parts[:k]), " b/".join(parts[k:])
        if left.startswith("a/") and left[2:] == right:
            return right
    return parts[1] if len(parts) == 2 and parts[0].startswith("a/") else None


def diff_files(text: str) -> list[tuple[str, bool]]:
    """(path, is_new) per file section of a unified diff; `is_new` reads the
    section's header (`new file mode` / `--- /dev/null`): an untracked file."""
    out: list[tuple[str, bool]] = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        path = diff_header_path(ln)
        if path is None:
            continue
        head = lines[i + 1:i + 6]
        out.append((path, any(h.startswith("new file mode") or h.startswith("--- /dev/null") for h in head)))
    return out
#: the two messages the adapter reads off this filer's stderr
NO_DEDUPE = "filing without the duplicate check"
APPLY_REFUSED = ("evolve-file --apply is not implemented in this release: the publish step (the ai-evolution branch "
                 "pushed to the target with FLEET_TOKEN probed by `gh api user`, and a draft PR carrying the marker "
                 "line) lands with bamr87/bamr87#488's next pull request; nothing was filed")
NO_CHANGES = "the agent made no changes — nothing to open"


def load_item(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the item document is not a JSON object")
    return data


def branch_re(cfg: dict) -> re.Pattern:
    prefix = re.escape(str(cfg.get("branch_prefix") or evolution.DEFAULTS["branch_prefix"]).rstrip("/"))
    return re.compile(prefix + r"/[0-9]{8}-[A-Za-z0-9._-]{1,60}")


def problems(item: dict, item_dir: Path, cfg: dict) -> list[str]:
    """Why the document cannot be filed (the structural rules, and #220's remote guard)."""
    out: list[str] = []
    kind = item.get("kind")
    if kind not in ("pr", "none"):
        out.append(f"kind must be pr or none, not {kind!r}")
    repo = str(item.get("repo") or "")
    if not NWO_RE.fullmatch(repo):
        out.append(f"repo {repo!r} is not owner/repo")
    if item.get("key") != repo:
        out.append(f"key {item.get('key')!r} != repo {repo!r} (an evolution pass is keyed by its repository)")
    marker = str(item.get("marker") or "")
    if repo and marker != evolution.marker_line(cfg, repo):
        out.append("marker is not this repository's repo-evolution marker line")
    base = str(item.get("base") or "")
    if not BRANCH_NAME_RE.fullmatch(base):
        out.append(f"base {base!r} is not a branch name")
    remote = str(item.get("remote") or "")
    if repo and remote != f"https://github.com/{repo}":
        # bamr87/bamr87#220: the publish remote is derived from the item's nwo and nothing else
        out.append(f"remote {remote!r} is not https://github.com/{repo} — refusing a push anywhere else")
    title = str(item.get("title") or "").strip()
    if not title or len(title) > TITLE_MAX or "\n" in title:
        out.append(f"title is empty, multi-line or over {TITLE_MAX} characters")
    body = str(item.get("body") or "")
    if not body.strip():
        out.append("body is empty")
    elif body.splitlines()[0].strip() != marker:
        out.append("the body's first line is not the marker line (the next run would re-file it)")
    if len(body.encode("utf-8")) > BODY_MAX:
        out.append(f"body over {BODY_MAX} bytes")
    if SECRET_RE.search(title) or SECRET_RE.search(body):
        out.append("the title or body carries a credential shape")
    if not isinstance(item.get("flagged"), bool):
        out.append("flagged must be a boolean")
    patch = item.get("patch")
    if kind == "pr":
        branch = str(item.get("branch") or "")
        if not branch_re(cfg).fullmatch(branch):
            out.append(f"branch {branch!r} is not {cfg.get('branch_prefix', 'ai-evolution')}/<yyyymmdd>-<slug>")
        if not patch:
            out.append("a pr needs a patch")
    elif patch:
        out.append("a pass with no changes carries no patch")
    if patch:
        p = item_dir / str(patch)
        if not isinstance(patch, str) or "/" in patch or not p.is_file() or p.is_symlink():
            out.append(f"patch {patch!r} is not a regular file beside the item document")
        else:
            data = p.read_bytes()
            text = data.decode("utf-8", errors="replace")
            if not data.strip():
                out.append("the patch is empty")
            elif len(data) > PATCH_MAX:
                out.append(f"the patch is over {PATCH_MAX} bytes")
            elif SECRET_RE.search(text):
                out.append("the patch carries a credential shape")
            rx = lockfile_re(cfg)
            locks = sorted({path for path, is_new in diff_files(text) if is_new and rx.search(path)})
            if locks:
                out.append(f"the patch creates a lockfile ({', '.join(locks)}): CI drops an untracked lockfile, "
                           "never commits it (a tracked one the agent modified is committed, and stays)")
    return out


def open_pass(repo: str, cfg: dict, *, offline: bool) -> tuple[list[dict] | None, str]:
    """The target's open evolution PRs (branch prefix or marker); None with
    why when gh could not answer — the caller then skips rather than risking
    a second open pass."""
    if offline:
        return None, "offline"
    try:
        found = evolution.open_evolution_prs(repo, cfg)
    except Exception as exc:  # noqa: BLE001 - gh's failure modes are many; the answer is the same: do not dedupe
        return None, f"{type(exc).__name__}: {exc}"
    return (found, "") if found is not None else (None, "gh could not list the open pull requests")


def run_file(args: argparse.Namespace) -> int:
    item_path = Path(args.item)
    try:
        item = load_item(item_path)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"evolve-file: --item {item_path}: {exc}\n")
        return 2
    if args.apply:
        sys.stderr.write(f"evolve-file: {APPLY_REFUSED}\n")
        return 2
    if args.reviewed_bodies:
        sys.stderr.write("evolve-file: --reviewed-bodies only means something with --apply\n")
        return 2
    cfg = evolution.load_config(Path(args.config))
    bodies = Path(args.bodies_dir)
    bodies.mkdir(parents=True, exist_ok=True)
    rejected = [{"title": str(item.get("title") or "?")[:80], "reason": why}
                for why in problems(item, item_path.parent, cfg)]
    result: dict = {"apply": False, "run_url": args.run_url, "filed": [], "skipped": [], "rejected": rejected}
    if rejected:
        print(json.dumps(result, separators=(",", ":")))
        return 0
    if item["kind"] == "none":
        result["skipped"].append({"title": item["title"], "repo": item["repo"], "reason": NO_CHANGES})
        sys.stderr.write(f"evolve-file: {item['repo']}: {NO_CHANGES}\n")
        print(json.dumps(result, separators=(",", ":")))
        return 0
    found, why = open_pass(str(item["repo"]), cfg, offline=args.offline)
    if found is None and not args.offline:
        sys.stderr.write(f"evolve-file: could not list the open pull requests ({why}) — {NO_DEDUPE}\n")
    if found:
        ref = found[0].get("url") or f"#{found[0].get('number')}"
        result["skipped"].append({"title": item["title"], "repo": item["repo"],
                                  "reason": f"previous evolution PR is still open: {ref}"})
        print(json.dumps(result, separators=(",", ":")))
        return 0
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item["key"])).strip("-.")[:80] or "item"
    body_file = bodies / f"{slug}.md"
    body_file.write_text(str(item["body"]), encoding="utf-8")
    patch_file = bodies / f"{slug}.patch"
    patch_file.write_bytes((item_path.parent / str(item["patch"])).read_bytes())
    result["filed"].append({
        "title": item["title"], "kind": "pr", "repo": item["repo"], "base": item["base"], "branch": item["branch"],
        "remote": item["remote"], "labels": [str(cfg.get("label") or "ai-evolution"), "automation"],
        "flagged": bool(item["flagged"]), "body_file": str(body_file), "patch_file": str(patch_file), "url": None,
    })
    sys.stderr.write(f"evolve-file: dry run — would push {item['branch']} to {item['remote']} and open a draft PR "
                     f"against {item['base']}: {item['title']}{' [PARTIAL: budget hit]' if item['flagged'] else ''}\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", required=True, metavar="PATH", help="the adapter's validated item document")
    parser.add_argument("--run-url", default="", metavar="TEXT", help="the run this filing comes from")
    parser.add_argument("--bodies-dir", required=True, metavar="DIR", help="where the exact body bytes are written")
    parser.add_argument("--config", default=str(evolution.FLEET_DEFAULT), metavar="PATH",
                        help="_data/fleet.yml (evolution: branch_prefix, marker, label)")
    parser.add_argument("--offline", action="store_true", help="no GitHub reads: no open-pass dedupe")
    parser.add_argument("--apply", action="store_true", help="file it (refused in this release: #488)")
    parser.add_argument("--reviewed-bodies", default=None, metavar="DIR",
                        help="with --apply: file only bodies byte-identical to this reviewed preview")
    parser.set_defaults(func=run_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evolve-file", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

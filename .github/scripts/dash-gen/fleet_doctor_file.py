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

The dry run is complete (the exact body bytes, the patch, the dedupe against
the hub's and the target's open markers, the structural rules) and writes
nothing. `--apply --reviewed-bodies <dir>` — the flags the engine adds only
after the § 13.6 yes (the OPS remote-write path, amendment
`ops-remote-write-path`) — files exactly what CI's doctor would have: the
publish token (`GH_TOKEN`, the engine's probed FLEET_TOKEN, else the ambient
gh login) is probed again with `gh api user`; the open-marker dedupe must be
readable (exit 3 and nothing filed otherwise); the body and the patch must be
byte-identical to the reviewed preview's (`<slug>.md` / `<slug>.patch` in the
reviewed directory) or the item is withheld; then, for a `pr`, a scratch clone
of the target (`gh repo clone`, never the hub checkout), the branch, the patch
applied and committed, ONE push of `HEAD:refs/heads/<branch>` with git's own
pack program pinned and the credential read from gh (`gh auth git-credential`,
never in argv), and `gh pr create --draft` with the labels CI uses; for an
`issue`, `gh label create --force` for the same labels and `gh issue create`.
Nothing else is written: no merge, no force, no delete, no settings.

The validated item document (`--item`):

    {"kind": "pr" | "issue", "repo": "owner/repo", "where": "hub" | "submodule",
     "key": "owner/repo:.github/workflows/x.yml", "marker": "<!-- fleet-doctor key=\"…\" -->",
     "title": "…", "body": "<marker line>\\n…", "branch": "fix/fleet-doctor-<slug>" | null,
     "patch": "changes.patch" | null (beside the document), "source": "gh-call" | "result-text"}

Usage:
    dash-gen doctor-file --item items/<dir>/outputs/doctor.validated.json \\
        --run-url "local run …" --bodies-dir items/<dir>/bodies [--offline]
    …  --bodies-dir items/<dir>/filed --apply --reviewed-bodies items/<dir>/bodies

Output: one JSON object on stdout — {"apply": bool, "filed": [...], "skipped": [...],
"rejected": [...]}. `filed` rows carry `title`, `kind`, `repo`, `labels`, `body_file`,
`patch_file`, `branch` and `url` (null on a dry run). Exit 2: a usage or structural
refusal; 3: the dedupe list or the publish token could not be read under --apply
(nothing filed); 0 otherwise — a failed push or create is a `skipped` row whose
reason says `failed`, which the adapter reads as a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import remediation

HUB_DEFAULT = "bamr87/bamr87"
LABELS = ["fleet-doctor", "automation"]
TITLE_MAX = 200
BODY_MAX = 60_000
PATCH_MAX = 512 * 1024
BRANCH_RE = re.compile(r"fix/fleet-doctor-[a-z0-9][a-z0-9._-]{0,80}")
#: the branch a PR is based on and opened against: the target's registry
#: branch (the hub's, for a hub fix), written by the adapter — never assumed
BASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}")
LABELS_REFUSED = "the labels could not be created before the push"
BRANCH_TAKEN = "the fix branch already exists in the target with a commit that is not this run's"
NWO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
#: the same credential shapes repo_scout.SECRET_RE refuses in a proposal
SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
#: the messages the adapter and CI read off this filer's stderr and result
NO_DEDUPE = "filing without the duplicate check"
#: why --reviewed-bodies withheld the item (tools/jev/adapters/fleet_pulse_doctor.py reads it)
NOT_REVIEWED = "not in the reviewed preview (its body or patch is not byte-identical to a reviewed one)"
TOKEN_REFUSED = "the publish token was refused by `gh api user`"
#: the commit identity of an applied fix: a noreply address, never this account's private email
COMMIT_NAME, COMMIT_EMAIL = "fleet-doctor", "fleet-doctor@users.noreply.github.com"
#: git's own pack program, pinned on the one push so no config can steer it (tools/jev/common.py does the same)
RECEIVE_PACK = "--receive-pack=git-receive-pack"
#: the credential comes from gh (GH_TOKEN in this process, else its stored login), never from argv or a URL
CREDENTIAL_HELPER = "credential.helper=!gh auth git-credential"


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
        base = item.get("base")
        if not isinstance(base, str) or not BASE_RE.fullmatch(base) or ".." in base.split("/"):
            out.append(f"base {base!r} is not the target's branch (the adapter writes the registry branch; a pr "
                       "is never based on an assumed default)")
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


def markers_unreadable(hub: str, repo: str) -> str:
    """Why the open-marker lists cannot be trusted: the one `gh issue list` and
    `gh pr list` per repository must each answer (a read, `--limit 1`); '' when
    they do. `remediation.open_markers` treats a failed list as empty, which a
    dry run may show but an apply must never file on."""
    for nwo in dict.fromkeys((hub, repo)):
        for noun in ("issue", "pr"):
            ok, _out, err = _run(["gh", noun, "list", "-R", nwo, "--state", "open", "--limit", "1", "--json", "number"],
                                 timeout=90)
            if not ok:
                return f"gh {noun} list -R {nwo}: {_why(err)}"
    return ""


def run_file(args: argparse.Namespace) -> int:
    item_path = Path(args.item)
    try:
        item = load_item(item_path)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"doctor-file: --item {item_path}: {exc}\n")
        return 2
    if args.apply and not args.reviewed_bodies:
        sys.stderr.write("doctor-file: --apply needs --reviewed-bodies (the engine adds both after the § 13.6 yes)\n")
        return 2
    if args.apply and args.offline:
        sys.stderr.write("doctor-file: --apply with --offline is refused: filing needs the live dedupe\n")
        return 2
    if not args.apply and args.reviewed_bodies:
        sys.stderr.write("doctor-file: --reviewed-bodies only means something with --apply\n")
        return 2
    bodies = Path(args.bodies_dir)
    bodies.mkdir(parents=True, exist_ok=True)
    rejected = [{"title": str(item.get("title") or "?")[:80], "reason": why}
                for why in problems(item, item_path.parent)]
    result: dict = {"apply": bool(args.apply), "run_url": args.run_url, "filed": [], "skipped": [],
                    "rejected": rejected}
    if rejected:
        print(json.dumps(result, separators=(",", ":")))
        return 0
    seen, why = open_keys(args.hub, str(item["repo"]), offline=args.offline)
    if args.apply and seen is not None:
        # remediation.open_markers reads a failed `gh … list` as nothing open; an apply must know the difference
        unreadable = markers_unreadable(args.hub, str(item["repo"]))
        if unreadable:
            seen, why = None, unreadable
    if seen is None and not args.offline:
        if args.apply:
            # the reviewed preview was deduped: filing without the list could re-file what it dropped
            sys.stderr.write(f"doctor-file: could not list the open issues and PRs ({why}) — --apply files nothing "
                             "without the duplicate check\n")
            result["skipped"].append({"title": item["title"], "reason": f"dedupe unavailable ({why}): nothing filed"})
            print(json.dumps(result, separators=(",", ":")))
            return 3
        sys.stderr.write(f"doctor-file: could not list the open issues and PRs ({why}) — {NO_DEDUPE}\n")
    if seen is not None and item["key"] in seen:
        result["skipped"].append({"title": item["title"], "reason": "already tracked by an open issue or fix PR"})
        print(json.dumps(result, separators=(",", ":")))
        return 0
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item["key"])).strip("-.")[:80] or "item"
    body = str(item["body"])
    patch_bytes = (item_path.parent / str(item["patch"])).read_bytes() if item.get("patch") else None
    if args.apply:
        if not reviewed_matches(Path(args.reviewed_bodies), slug, body, patch_bytes):
            sys.stderr.write(f"doctor-file: {item['title']}: {NOT_REVIEWED}\n")
            result["skipped"].append({"title": item["title"], "reason": NOT_REVIEWED})
            print(json.dumps(result, separators=(",", ":")))
            return 0
        login, why = probe_token()
        if login is None:
            sys.stderr.write(f"doctor-file: {TOKEN_REFUSED}: {why} — nothing filed\n")
            result["skipped"].append({"title": item["title"], "reason": f"{TOKEN_REFUSED}: {why}"})
            print(json.dumps(result, separators=(",", ":")))
            return 3
        sys.stderr.write(f"doctor-file: publishing as {login}\n")
    body_file = bodies / f"{slug}.md"
    body_file.write_text(body, encoding="utf-8")
    patch_file = None
    if patch_bytes is not None:
        patch_file = bodies / f"{slug}.patch"
        patch_file.write_bytes(patch_bytes)
    row = {
        "title": item["title"], "kind": item["kind"], "repo": item["repo"], "where": item.get("where"),
        "labels": list(LABELS), "body_file": str(body_file), "patch_file": str(patch_file) if patch_file else None,
        "branch": item.get("branch"), "url": None,
    }
    if not args.apply:
        result["filed"].append(row)
        sys.stderr.write(f"doctor-file: dry run — would open a {item['kind']} in {item['repo']}: {item['title']}\n")
        print(json.dumps(result, separators=(",", ":")))
        return 0
    why = ensure_labels(str(item["repo"]))
    if why:
        # nothing pushed, nothing created: a PR or issue without CI's labels would escape the dedupe's readers
        result["skipped"].append({"title": item["title"], "reason": f"{LABELS_REFUSED}: {why}"})
        sys.stderr.write(f"doctor-file: {LABELS_REFUSED} ({why}) — nothing filed\n")
        print(json.dumps(result, separators=(",", ":")))
        return 3
    if item["kind"] == "issue":
        url, why = create_issue(item, body_file)
    else:
        url, why = open_pr(item, patch_file, body_file, args.run_url)
    if url is None:
        result["skipped"].append({"title": item["title"], "reason": why})
        sys.stderr.write(f"  ✗ {item['title']}: {why}\n")
    else:
        row["url"] = url
        result["filed"].append(row)
        sys.stderr.write(f"  ✓ filed: {item['title']}  [{' '.join(LABELS)}]  {url}\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


# --------------------------------------------------------------------------- #
# the apply: what CI's doctor would have written, and nothing else
# --------------------------------------------------------------------------- #
def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 600, env: dict | None = None):
    """A subprocess with its stdin closed; (ok, stdout, stderr-or-why)."""
    try:
        out = subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL, env=env)
    except FileNotFoundError:
        return False, "", f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, "", f"{argv[0]} timed out after {timeout}s"
    return out.returncode == 0, out.stdout, (out.stderr or out.stdout).strip()


def _why(err: str, n: int = 240) -> str:
    """The last line of a failure, with any credential shape removed."""
    last = (err.strip().splitlines() or [""])[-1]
    return SECRET_RE.sub("[REDACTED]", last)[-n:]


def reviewed_matches(reviewed: Path, slug: str, body: str, patch: bytes | None) -> bool:
    """The body (and the patch, when there is one) are byte-identical to the
    reviewed preview's `<slug>.md` / `<slug>.patch`."""
    body_file, patch_file = reviewed / f"{slug}.md", reviewed / f"{slug}.patch"
    if not body_file.is_file() or body_file.is_symlink():
        return False
    if hashlib.sha256(body_file.read_bytes()).hexdigest() != hashlib.sha256(body.encode("utf-8")).hexdigest():
        return False
    if patch is None:
        return not patch_file.exists()
    return patch_file.is_file() and not patch_file.is_symlink() and \
        hashlib.sha256(patch_file.read_bytes()).hexdigest() == hashlib.sha256(patch).hexdigest()


def probe_token() -> tuple[str | None, str]:
    """`gh api user` with the credential gh holds (GH_TOKEN in this process —
    the engine's probed FLEET_TOKEN — else its stored login): the login, or
    None and why. A token's presence proves nothing (AGENTS.md)."""
    ok, out, err = _run(["gh", "api", "user", "--jq", ".login"], timeout=60)
    login = out.strip()
    if not ok or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?", login):
        return None, _why(err) or "no login"
    return login, ""


def ensure_labels(repo: str) -> str:
    """The labels CI's doctor passes to `gh pr create` / `gh issue create` must
    exist in the target (`--force` only refreshes an existing one) BEFORE
    anything is pushed or created: '' when they do, else why — the caller
    files nothing then, since a `gh pr create --label` that fails after the
    push would strand the branch."""
    for name in LABELS:
        ok, _out, err = _run(["gh", "label", "create", name, "-R", repo, "--force"], timeout=60)
        if not ok:
            return f"gh label create {name} -R {repo}: {_why(err)}"
    return ""


def create_issue(item: dict, body_file: Path) -> tuple[str | None, str]:
    """Step 3c: ONE tracking issue, MARKER line first (the body file's bytes)."""
    argv = ["gh", "issue", "create", "-R", str(item["repo"]), "--title", str(item["title"]),
            "--body-file", str(body_file), "--label", ",".join(LABELS)]
    ok, out, err = _run(argv, timeout=120)
    if not ok:
        return None, f"gh issue create failed: {_why(err)}"
    url = (out.strip().splitlines() or [""])[-1]
    return (url, "") if url.startswith("https://") else (None, f"gh issue create failed: no URL ({_why(out)})")


def open_pr(item: dict, patch_file: Path | None, body_file: Path, run_url: str) -> tuple[str | None, str]:
    """Steps 3a / 3b: a scratch clone of the target (never the hub checkout or
    a submodule working tree), the fix branch, the reviewed patch applied and
    committed, ONE push of `HEAD:refs/heads/<branch>` (git's receive-pack
    pinned, the credential from gh, nothing in argv) and a draft PR with the
    labels CI uses. The clone is removed whatever happens."""
    repo, branch = str(item["repo"]), str(item["branch"])
    base = str(item.get("base") or "")
    if patch_file is None:
        return None, "a pr needs a patch"
    if not base:
        return None, "the validated document names no base branch (the target's registry branch): nothing filed"
    subject = str(item["title"])
    trailer = (f"Fleet doctor, run locally ({run_url}); the pull request body carries the MARKER line."
               if run_url else "Fleet doctor, run locally; the pull request body carries the MARKER line.")
    with tempfile.TemporaryDirectory(prefix="jev-doctor-apply-") as tmp:
        dest = Path(tmp) / "repo"
        ok, _out, err = _run(["gh", "repo", "clone", repo, str(dest), "--", "--quiet", "--no-tags"], timeout=900)
        if not ok:
            return None, f"clone failed: {_why(err)}"
        git = ["git", "-C", str(dest), "-c", "core.hooksPath=/dev/null", "-c", "credential.helper="]
        # the target's branch, never the clone's default: the registry says what the PR is based on
        ok, _out, err = _run([*git, "checkout", "-q", base])
        if not ok:
            return None, f"base branch {base} is not in {repo}: {_why(err)} — registry branch drift?"
        # the fix branch must not already exist on the remote: a push is never a force, so a leftover from an
        # earlier filing (a PR create that failed after its push) would be rejected forever; this run's own
        # commit on it is reused, anything else is a human's call
        ok, out, err = _run([*git, "ls-remote", "--heads", "origin", branch], timeout=120)
        if not ok:
            return None, f"could not read the remote's branches: {_why(err)}"
        existing = out.strip() != ""
        if existing:
            ok, _out, err = _run([*git, "fetch", "-q", "--no-tags", "origin", branch], timeout=600)
            if not ok:
                return None, f"could not fetch the existing {branch}: {_why(err)}"
            ok, out, _err = _run([*git, "log", "-1", "--format=%s%n%b", "FETCH_HEAD"])
            lines = out.splitlines() if ok else []
            ours = bool(lines) and lines[0] == subject and (not run_url or any(run_url in ln for ln in lines[1:]))
            if not ours:
                return None, f"{BRANCH_TAKEN} ({branch} in {repo}): delete or rename it before filing"
            sys.stderr.write(f"doctor-file: {branch} already carries this run's commit in {repo}: reusing it, "
                             "no push\n")
        else:
            ok, _out, err = _run([*git, "checkout", "-q", "-b", branch])
            if not ok:
                return None, f"branch {branch} failed: {_why(err)}"
            ok, _out, err = _run([*git, "apply", "--index", str(patch_file)])
            if not ok:
                return None, f"the reviewed patch does not apply on {base} any more: {_why(err)}"
            ok, _out, err = _run([*git, "-c", f"user.name={COMMIT_NAME}", "-c", f"user.email={COMMIT_EMAIL}",
                                  "-c", "commit.gpgsign=false", "commit", "-q", "-m", subject, "-m", trailer])
            if not ok:
                return None, f"commit failed: {_why(err)}"
            ok, _out, err = _run([*git, "-c", CREDENTIAL_HELPER, "push", "-q", RECEIVE_PACK, "origin",
                                  f"HEAD:refs/heads/{branch}"], timeout=600)
            if not ok:
                return None, f"push failed ({branch} in {repo}): {_why(err)}"
        argv = ["gh", "pr", "create", "-R", repo, "--draft", "--base", base, "--head", branch,
                "--title", subject, "--body-file", str(body_file)]
        for name in LABELS:
            argv += ["--label", name]
        ok, out, err = _run(argv, timeout=120)
        if not ok:
            return None, f"gh pr create failed after the push of {branch}: {_why(err)}"
        url = (out.strip().splitlines() or [""])[-1]
        return (url, "") if url.startswith("https://") else (None, f"gh pr create failed: no URL ({_why(out)})")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", required=True, metavar="PATH", help="the adapter's validated item document")
    parser.add_argument("--run-url", default="", metavar="TEXT", help="the run this filing comes from")
    parser.add_argument("--bodies-dir", required=True, metavar="DIR", help="where the exact body bytes are written")
    parser.add_argument("--hub", default=HUB_DEFAULT, metavar="OWNER/REPO")
    parser.add_argument("--offline", action="store_true", help="no GitHub reads: no open-marker dedupe")
    parser.add_argument("--apply", action="store_true",
                        help="file it: the push + draft PR, or the issue, CI would have opened (the engine adds "
                             "this only after the § 13.6 yes; needs --reviewed-bodies)")
    parser.add_argument("--reviewed-bodies", default=None, metavar="DIR",
                        help="with --apply: file only a body and patch byte-identical to this reviewed preview's")
    parser.set_defaults(func=run_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doctor-file", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

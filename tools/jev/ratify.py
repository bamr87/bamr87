#!/usr/bin/env python3
"""
File: tools/jev/ratify.py
Description: RECORD WHAT A MERGE DECIDED. Constitution § 8.3 says merging an
             amendment's pull request ratifies it, and that the record then
             says `Status: ratified` and `Ratified by:` the PR; the maintainer
             ruled on 2026-11-01 that merging the PR that adds an ADR (or a
             phase of one) accepts it. Nothing wrote either fact down, so
             merged records kept saying `proposed`. This module derives, from
             repository STATE, which records a maintainer's merge has already
             decided, and plans the exact line edits that record it:

               ratify   — docs/amendments/NNNN-*.md `**Status:** proposed`
                          → ratified, `**Ratified by:**` the PR, and the
                          index row's status cell
               accept   — docs/adr/NNNN-*.md `- **Status**: proposed` (the
                          header and any phase line) → accepted, plus
                          `- **Accepted in**:` the PR, and the index cell
               complete — an ADR whose `- **Tracking**: #N` issue the
                          maintainer closed as completed, with every
                          sub-issue closed, gets `- **Completed**: <date>`

             It reads GitHub (GETs only, through `common.gh`) and writes only
             the working tree. It never pushes, opens or merges anything: the
             `ratify` job in .github/workflows/jev-number.yml does that, and
             merges only when `guard` says go — the PR is the job's own, its
             head is one commit on main's tip, every check on that SHA passed,
             and the diff is exactly the plan it was built from, each of whose
             triggers still holds (amendment `ratification-records`).
Author: bamr87
Created: 2026-11-01
Version: 0.2.0
Usage:
  python3 -m tools.jev ratify plan       [--json] [--out FILE] [--ref HEAD] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify apply      [--plan FILE] [--ref HEAD] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify check-diff --base REV [--head HEAD] [--plan FILE] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify pr-body    [--plan FILE] [--title] [--ref HEAD] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify select     --plan FILE [--manual] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify guard      --pr N --sha SHA [--base-ref main] [--plan FILE] [--repo OWNER/NAME]
Exit: 0 clean (guard: go), 1 a problem the caller must fix (a mismatch, a
      diff that is not the plan), 2 usage; check-diff and guard: 3 not yet
      (GitHub could not be read, a check is still running — retry later);
      guard: 4 refuse (hand the PR to the maintainer), 5 re-cut (main moved
      or a trigger changed: plan again from main's tip), 6 stop (the PR was
      merged, closed or held by a person: leave it).
Dependencies: PyYAML; `git` (full history: blame and log); `gh` for the GETs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .common import JevError, git, git_bytes, gh_json, hub_repo

AMEND_DIR = "docs/amendments"
AMEND_INDEX = "docs/amendments/README.md"
AMEND_PROPOSED = "docs/amendments/proposed"
ADR_DIR = "docs/adr"
ADR_INDEX = "docs/adr/README.md"
FLEET = "_data/fleet.yml"
BRANCH = "chore/jev-ratify"
SCHEMA = "jev-ratify/v1"
#: the mode every record file has; check-diff refuses any other
RECORD_MODE = "100644"

#: guard (and check-diff) verdicts — the exit codes the workflow branches on
GO, WAIT, REFUSE, RECUT, STOP = 0, 3, 4, 5, 6
VERDICT = {GO: "go", WAIT: "not yet", REFUSE: "refuse", RECUT: "re-cut", STOP: "stop"}

#: a numbered record, never the 0000 template
RECORD_NAME = re.compile(r"^(?!0000-)(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
#: the only files a ratification-record change may touch (amendment `ratification-records`)
ALLOWED_PATH = re.compile(r"^(?:docs/amendments/(?!0000-)\d{4}-[a-z0-9][a-z0-9-]*\.md|docs/amendments/README\.md"
                          r"|docs/adr/(?!0000-)\d{4}-[a-z0-9][a-z0-9-]*\.md|docs/adr/README\.md)$")
INDEX_PATHS = (AMEND_INDEX, ADR_INDEX)

# Amendments put the colon INSIDE the bold (`**Status:**`); ADRs put it outside
# (`**Status**:`). Each pattern keeps the lead (indent, bullet, field name) so
# a rewritten line differs from the original only in its value. `.` matches a
# CR, so a CRLF record's line end survives in `rest` / `value`.
AMEND_STATUS = re.compile(r"^(?P<lead>(?P<bullet>\s*[-*]\s+)\*\*Status:\*\*\s*)(?P<value>\S+?)(?P<rest>\r?|\s.*)$")
AMEND_RATIFIED_BY = re.compile(r"^(?P<lead>\s*[-*]\s+\*\*Ratified by:\*\*)(?P<value>.*?)(?P<eol>\r?)$")
ADR_STATUS = re.compile(r"^(?P<lead>(?P<bullet>\s*[-*]\s+)\*\*Status\*\*:\s*)(?P<value>[A-Za-z]+)(?P<rest>.*)$")
ADR_FIELD = r"^\s*[-*]\s+\*\*{name}\*\*:\s*(?P<value>.*?)\r?$"
ADR_TRACKING = re.compile(r"^\s*[-*]\s+\*\*Tracking\*\*:\s*#(?P<n>\d+)\b")
#: a Markdown code fence; a Status line inside one is an example, never a record
FENCE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
#: an index row's cells: split on `|` but not on an escaped `\|`
CELL_SPLIT = re.compile(r"(?<!\\)\|")
#: the line shapes a planned edit may write into a record (check-diff re-asserts them)
RECORD_LINE = re.compile(r"^\s*[-*]\s+\*\*(?:Status:\*\*|Ratified by:\*\*|Status\*\*:|Accepted in\*\*:|Completed\*\*:)")
#: a closing keyword in a PR body, the fallback when GraphQL is unavailable
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.I)
#: GitHub's closing keywords followed by a reference. The record PR's body must
#: never carry one: GitHub parses it again when the record PR merges, and
#: would close (again) an issue the maintainer reopened.
CLOSING_REF = re.compile(r"\b(?P<kw>close[sd]?|fix(?:e[sd])?|resolve[sd]?)(?P<sep>\s*:?\s*)"
                         r"(?P<ref>(?:[\w.-]+/[\w.-]+)?#\d+|GH-\d+"
                         r"|https?://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+)", re.I)
#: head-branch prefixes whose merge is automation, never the maintainer's
#: decision; the hub's own publish branches are added from its workflows
#: (`_automation_branches`). A bare `chore/jev-` prefix would be wrong: agent
#: feature branches use it too (#442, amendment 0004, is one).
AUTOMATION_PREFIXES = ("wtd/", "dependabot/")
#: a literal `branch:` input in a workflow (publish-data's stable PR branch)
WORKFLOW_BRANCH = re.compile(r"^\s*branch:\s*['\"]?(?P<b>[\w./-]+)['\"]?\s*(?:#.*)?$", re.M)
WORKFLOWS = ".github/workflows"

HOLD_LABELS = ("needs-amr", "agent:hold", "blocked")
#: a check run's conclusions that let the record merge
CHECK_OK = ("success", "skipped", "neutral")
#: the comment in the PR body that names the plan the head was built from
PLAN_MARK = re.compile(r"<!-- jev-ratify plan: (?P<json>\{.*?\}) -->")


class RatifyError(JevError):
    """A plan that cannot be applied or a diff that is not the plan."""


# --------------------------------------------------------------------------- #
# GitHub: GETs only, through common.gh (the guard refuses anything else)
# --------------------------------------------------------------------------- #
def _gh_json(args: list[str]):
    """The one seam to GitHub; the tests replace it with a fake."""
    return gh_json(args)


def _why(exc: Exception) -> str:
    return str(exc).rsplit("failed: ", 1)[-1].strip()[:160] or type(exc).__name__


def _unknown_commit(exc: Exception) -> bool:
    """GitHub's 422 for a commit it has never seen (never pushed, or rewritten)."""
    text = str(exc)
    return "HTTP 422" in text or "No commit found" in text


class GitHub:
    """The handful of reads a plan and the guard need, cached per run."""

    def __init__(self, repo: str):
        self.repo = repo
        self._pulls: dict[int, dict] = {}
        self._by_commit: dict[str, list] = {}
        self._issues: dict[int, dict] = {}

    def default_branch(self) -> str:
        data = _gh_json(["api", f"repos/{self.repo}"]) or {}
        return str(data.get("default_branch") or "main")

    def pulls_for_commit(self, sha: str) -> list[dict]:
        if sha not in self._by_commit:
            self._by_commit[sha] = list(_gh_json(["api", f"repos/{self.repo}/commits/{sha}/pulls"]) or [])
        return self._by_commit[sha]

    def pull(self, number: int, *, fresh: bool = False) -> dict:
        if fresh or number not in self._pulls:
            self._pulls[number] = _gh_json(["api", f"repos/{self.repo}/pulls/{number}"]) or {}
        return self._pulls[number]

    def closing_issues(self, number: int, body: str) -> list[int]:
        """The issues the PR closes: GraphQL's closingIssuesReferences, else the
        closing keywords in its body (a token without GraphQL still plans)."""
        owner, name = self.repo.split("/", 1)
        query = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n)"
                 "{closingIssuesReferences(first:50){nodes{number}}}}}")
        try:
            data = _gh_json(["api", "graphql", "-f", f"query={query}", "-F", f"o={owner}", "-F", f"r={name}",
                             "-F", f"n={number}"]) or {}
            nodes = (((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {})
            nodes = (nodes.get("closingIssuesReferences") or {}).get("nodes") or []
            return sorted({int(n["number"]) for n in nodes if isinstance(n, dict) and n.get("number")})
        except (JevError, ValueError, TypeError):
            return sorted({int(n) for n in CLOSES.findall(body or "")})

    def issue(self, number: int) -> dict:
        if number not in self._issues:
            self._issues[number] = _gh_json(["api", f"repos/{self.repo}/issues/{number}"]) or {}
        return self._issues[number]

    def _pages(self, endpoint: str) -> list:
        pages = _gh_json(["api", "--paginate", "--slurp", endpoint]) or []
        return pages if isinstance(pages, list) else [pages]

    def sub_issues(self, number: int) -> list[dict]:
        out: list[dict] = []
        for page in self._pages(f"repos/{self.repo}/issues/{number}/sub_issues?per_page=100"):
            out.extend(page if isinstance(page, list) else [page])
        return [i for i in out if isinstance(i, dict)]

    def branch_tip(self, branch: str) -> str:
        data = _gh_json(["api", f"repos/{self.repo}/branches/{branch}"]) or {}
        return str((data.get("commit") or {}).get("sha") or "")

    def check_runs(self, sha: str) -> list[dict]:
        """Every check run on `sha` itself (the latest attempt of each) — by
        SHA, never by PR, so a force-push cannot lend the old head's checks."""
        out: list[dict] = []
        for page in self._pages(f"repos/{self.repo}/commits/{sha}/check-runs?filter=latest&per_page=100"):
            out.extend((page or {}).get("check_runs") or [] if isinstance(page, dict) else [])
        return [r for r in out if isinstance(r, dict)]

    def statuses(self, sha: str) -> list[dict]:
        """The latest commit status per context on `sha`."""
        data = _gh_json(["api", f"repos/{self.repo}/commits/{sha}/status"]) or {}
        return [s for s in data.get("statuses") or [] if isinstance(s, dict)]

    def record_pulls(self, base: str) -> list[dict]:
        """The PRs, newest first, opened from this repository's own record branch."""
        owner = self.repo.split("/", 1)[0]
        out: list[dict] = []
        for page in self._pages(f"repos/{self.repo}/pulls?state=all&head={owner}:{BRANCH}&base={base}"
                                "&sort=created&direction=desc&per_page=100"):
            out.extend(page if isinstance(page, list) else [page])
        return [p for p in out if isinstance(p, dict)]


# --------------------------------------------------------------------------- #
# the repository as of one commit
# --------------------------------------------------------------------------- #
def _decode(data: bytes) -> str:
    """Bytes to text with NO newline translation, reversibly (`_encode`)."""
    return data.decode("utf-8", errors="surrogateescape")


def _encode(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogateescape")


class Tree:
    """Files and history at one commit — never the working tree, so a plan is
    a function of a commit and two runs over it agree."""

    def __init__(self, root: Path, ref: str):
        self.root = root
        res = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=root)
        if not res.ok or not res.out.strip():
            raise RatifyError(f"{ref!r} is not a commit in {root}")
        self.sha = res.out.strip()
        self._first_parent: list[str] | None = None

    def read(self, rel: str) -> str | None:
        """The file's exact text: read as bytes, so a CR survives."""
        data = git_bytes(["show", f"{self.sha}:{rel}"], cwd=self.root)
        return None if data is None else _decode(data)

    def ls(self, rel_dir: str) -> list[str]:
        res = git(["ls-tree", "--name-only", self.sha, f"{rel_dir}/"], cwd=self.root)
        return sorted(line.strip() for line in res.out.splitlines() if line.strip()) if res.ok else []

    def added_by(self, rel: str, *, upto: str | None = None) -> str | None:
        """The newest commit reachable from `upto` (default: this one) that
        ADDED the path `rel` — renames off, so a move into `rel` counts."""
        args = ["log", upto or self.sha, "--no-renames", "--diff-filter=A", "--format=%H", "--", rel]
        res = git(args, cwd=self.root)
        shas = res.out.split() if res.ok else []
        return shas[0] if shas else None

    def blame(self, rel: str, lineno: int) -> str | None:
        """The commit that introduced line `lineno` of `rel` as it stands here."""
        res = git(["blame", "--porcelain", "-L", f"{lineno},{lineno}", self.sha, "--", rel], cwd=self.root)
        first = res.out.split("\n", 1)[0].split() if res.ok else []
        return first[0] if first and re.fullmatch(r"[0-9a-f]{40}", first[0]) else None

    def mainline(self, sha: str) -> str | None:
        """The first-parent commit of this one that brought `sha` in — the merge
        (or the squash, or the direct push) a branch commit reached main by."""
        if self._first_parent is None:
            res = git(["log", "--first-parent", "--format=%H", self.sha], cwd=self.root)
            self._first_parent = res.out.split() if res.ok else []
        if sha in self._first_parent:
            return sha
        res = git(["log", "--ancestry-path", "--format=%H", f"{sha}..{self.sha}"], cwd=self.root)
        descendants = set(res.out.split()) if res.ok else set()
        hits = [c for c in self._first_parent if c in descendants]
        return hits[-1] if hits else None


def _live(lines: list[str]) -> list[bool]:
    """Per line: is it outside every fenced code block? A Status line quoted in
    a ```markdown example is not a record and is never edited."""
    out: list[bool] = []
    fence = ""
    for ln in lines:
        m = FENCE.match(ln)
        if not fence:
            if m:
                fence = m.group("fence")
                out.append(False)
            else:
                out.append(True)
            continue
        out.append(False)
        if m and m.group("fence")[0] == fence[0] and len(m.group("fence")) >= len(fence) \
                and ln.strip() == m.group("fence"):
            fence = ""
    return out


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #
@dataclass
class Edit:
    """One line operation. `replace` swaps line `line` (which must read `old`);
    `insert` adds `new` right after line `line` (which must read `old`).
    `key` names the decision it records (`ratify:<path>`,
    `accept:<path>:<status line>`, `complete:<path>`): the guard holds a PR to
    the keys it was built for."""

    path: str
    line: int
    op: str            # replace | insert
    old: str
    new: str
    kind: str          # ratify | accept | complete
    record: str
    trigger: dict
    key: str = ""


@dataclass
class Plan:
    repo: str
    ref: str
    maintainer: str
    default_branch: str = "main"
    edits: list[Edit] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)   # tracked ADRs whose issue is not done yet
    notes: list[str] = field(default_factory=list)
    #: the hub's automation branches as of `ref` (not serialized: derived)
    automation: frozenset = field(default=frozenset(), repr=False)

    @property
    def empty(self) -> bool:
        return not self.edits

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "repo": self.repo, "ref": self.ref, "maintainer": self.maintainer,
                "default_branch": self.default_branch, "edits": [asdict(e) for e in self.edits],
                "skipped": self.skipped, "pending": self.pending, "notes": self.notes,
                "keys": self.keys(), "digest": self.digest()}

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise RatifyError(f"not a {SCHEMA} plan")
        return cls(repo=str(data.get("repo") or ""), ref=str(data.get("ref") or ""),
                   maintainer=str(data.get("maintainer") or ""),
                   default_branch=str(data.get("default_branch") or "main"),
                   edits=[Edit(**e) for e in data.get("edits") or []],
                   skipped=list(data.get("skipped") or []), pending=list(data.get("pending") or []),
                   notes=list(data.get("notes") or []))

    def records(self, kind: str) -> list[str]:
        return list(dict.fromkeys(e.record for e in self.edits if e.kind == kind))

    def keys(self) -> list[str]:
        return sorted({e.key for e in self.edits})

    def by_key(self, key: str) -> list[tuple]:
        return sorted((e.path, e.line, e.op, e.old, e.new) for e in self.edits if e.key == key)

    def digest(self) -> str:
        """What the plan WRITES, independent of the commit it is cut from: two
        plans with one digest produce the same record PR."""
        rows = sorted((e.key, e.path, e.op, e.old, e.new) for e in self.edits)
        return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8", "surrogateescape")).hexdigest()

    def restricted(self, keys: list[str]) -> "Plan":
        wanted = set(keys)
        return Plan(repo=self.repo, ref=self.ref, maintainer=self.maintainer, default_branch=self.default_branch,
                    edits=[e for e in self.edits if e.key in wanted])

    def why_not(self, key: str) -> dict | None:
        """The skip or pending entry that keeps `key` out of this plan."""
        return next((s for s in [*self.skipped, *self.pending] if s.get("key") == key), None)


def _date(stamp: str | None) -> str:
    return str(stamp or "")[:10]


def _skip(plan: Plan, key: str, record: str, kind: str, reason: str, *, line: int | None = None,
          read_error: bool = False) -> None:
    entry = {"record": record, "kind": kind, "reason": reason, "key": key, "read_error": read_error}
    if line is not None:
        entry["line"] = line
    plan.skipped.append(entry)


def _pr_trigger(github: GitHub, number: int, commit: str) -> dict:
    pr = github.pull(number)
    login = str(((pr.get("merged_by") or {}).get("login")) or "")
    return {
        "type": "pr", "number": number, "title": str(pr.get("title") or ""),
        "url": str(pr.get("html_url") or f"https://github.com/{github.repo}/pull/{number}"),
        "merged": bool(pr.get("merged_at")), "merged_at": str(pr.get("merged_at") or ""),
        "merged_by": login, "merge_commit_sha": str(pr.get("merge_commit_sha") or ""),
        "base": str((pr.get("base") or {}).get("ref") or ""),
        "head_ref": str((pr.get("head") or {}).get("ref") or ""),
        "author": str((pr.get("user") or {}).get("login") or ""),
        "labels": sorted(str(lb.get("name")) for lb in pr.get("labels") or [] if isinstance(lb, dict)),
        "closing_issues": github.closing_issues(number, str(pr.get("body") or "")) if pr.get("merged_at") else [],
        "commit": commit,
    }


def _resolve_pr(tree: Tree, github: GitHub, sha: str, default: str) -> tuple[dict | None, str, bool]:
    """(trigger, "", False) for the merged PR that brought `sha` onto the
    default branch, else (None, why not, whether the why is a read failure
    that may pass). The commit's own PRs first (GitHub associates a squash or
    merge with them); when it has none merged into the default branch — a
    stacked PR merged into its parent's branch — the PR of the first-parent
    commit that brought it in."""
    tried: list[dict] = []
    for step in (0, 1):
        candidate = sha if step == 0 else tree.mainline(sha)
        if not candidate or (step == 1 and candidate == sha):
            continue
        try:
            pulls = github.pulls_for_commit(candidate)
        except JevError as exc:
            if _unknown_commit(exc):
                return None, (f"GitHub does not know commit {candidate[:7]} (HTTP 422: never pushed, or its history "
                              "was rewritten), so no pull request can be named for it"), False
            return None, f"GitHub could not list the pull requests of commit {candidate[:7]} ({_why(exc)})", True
        tried += pulls
        merged = sorted((p for p in pulls if p.get("merged_at") and (p.get("base") or {}).get("ref") == default),
                        key=lambda p: str(p.get("merged_at")))
        if merged:
            number = int(merged[0]["number"])
            try:
                return _pr_trigger(github, number, sha), "", False
            except JevError as exc:
                return None, f"GitHub could not read PR #{number} ({_why(exc)})", True
    if tried:
        nums = ", ".join(f"#{p.get('number')}" for p in tried)
        return None, f"commit {sha[:7]}'s pull request ({nums}) is not merged into {default}", False
    return None, f"commit {sha[:7]} reached {default} without a pull request (a direct push decides nothing)", False


def _automation_branches(tree: Tree) -> frozenset:
    """The branches the hub's own jobs open PRs from, as of this commit: every
    literal `branch:` input in .github/workflows/*.yml (publish-data's stable
    branches: chore/jev-numbering, chore/fleet-pulse, …) and the record branch."""
    out = {BRANCH}
    for path in tree.ls(WORKFLOWS):
        if path.endswith((".yml", ".yaml")):
            out |= {m.group("b") for m in WORKFLOW_BRANCH.finditer(tree.read(path) or "")}
    return frozenset(out)


def _is_automation(head_ref: str, automation: frozenset) -> bool:
    return head_ref in automation or head_ref.startswith(AUTOMATION_PREFIXES)


def _maintainer_check(trigger: dict, maintainer: str, automation: frozenset = frozenset()) -> str:
    """Why the trigger PR's merge is not the maintainer's decision, or "".
    `merged_by` reads the maintainer for a FLEET_TOKEN merge too, so a PR
    from an automation branch or by a bot counts for nothing whoever merged
    it; that every gated PR is merged by the maintainer is § 12.3 and § 12.5."""
    if not trigger.get("merged"):
        return f"PR #{trigger['number']} is not merged"
    if trigger.get("merged_by") != maintainer:
        who = f"@{trigger['merged_by']}" if trigger.get("merged_by") else "an unknown account"
        return f"PR #{trigger['number']} was merged by {who}, not the maintainer @{maintainer}"
    if _is_automation(str(trigger.get("head_ref") or ""), automation):
        return (f"PR #{trigger['number']} came from the automation branch {trigger['head_ref']}; an automation "
                "merge decides nothing")
    if str(trigger.get("author") or "").endswith("[bot]"):
        return f"PR #{trigger['number']} was opened by the bot @{trigger['author']}; a bot's PR decides nothing"
    return ""


def _stamp(trigger: dict, repo: str) -> str:
    return (f"https://github.com/{repo}/pull/{trigger['number']} "
            f"(merged {_date(trigger['merged_at'])} by @{trigger['merged_by']})")


def _filled(value: str, repo: str) -> int | None:
    """The PR number a Ratified by / Accepted in value names, when — and only
    when — it is already a stamp (`https://github.com/<repo>/pull/N (merged
    YYYY-MM-DD…`). A placeholder, prose or any other URL is not filled."""
    m = re.match(rf"^\s*https://github\.com/{re.escape(repo)}/pull/(\d+) \(merged \d{{4}}-\d{{2}}-\d{{2}}\b", value)
    return int(m.group(1)) if m else None


def _index_edit(text: str | None, path: str, number: str, link_rx: str, old_status: str, new_status: str,
                kind: str, record: str, trigger: dict, key: str) -> tuple[Edit | None, str]:
    """The index row for `number` with only its status cell changed."""
    if text is None:
        return None, f"{path}: missing, so {record}'s row could not be updated"
    for i, line in enumerate(text.split("\n"), start=1):
        cells = CELL_SPLIT.split(line)
        if len(cells) < 5 or not re.match(link_rx.format(n=re.escape(number)), cells[1].strip()):
            continue
        if cells[3].strip() != old_status:
            return None, f"{path}:{i}: {record}'s status cell reads {cells[3].strip()!r}, left as it is"
        cells[3] = cells[3].replace(old_status, new_status, 1)
        return Edit(path, i, "replace", line, "|".join(cells), kind, record, trigger, key), ""
    return None, f"{path}: no index row for {number}"


def _header_end(lines: list[str], live: list[bool]) -> int:
    """Index of the first `## ` heading: the header block is everything above it."""
    return next((i for i, ln in enumerate(lines) if live[i] and ln.startswith("## ")), len(lines))


def _amendment_commit(tree: Tree, path: str, slug: str) -> tuple[str | None, str]:
    """The commit whose PR proposed THIS record: the newest add of
    proposed/<slug>.md that the commit creating the numbered file descends
    from (a later re-proposal of the slug never names an older record), else
    the commit that created the numbered file itself (a record numbered by
    hand, before amendment 0002)."""
    created = tree.added_by(path)
    if not created:
        return None, f"no commit on {tree.sha[:7]} adds {path}"
    return tree.added_by(f"{AMEND_PROPOSED}/{slug}.md", upto=created) or created, ""


def _plan_amendments(tree: Tree, github: GitHub, plan: Plan) -> None:
    index = tree.read(AMEND_INDEX)
    for path in tree.ls(AMEND_DIR):
        name = path.rsplit("/", 1)[-1]
        m = RECORD_NAME.match(name)
        if not m:
            continue
        lines = (tree.read(path) or "").split("\n")
        live = _live(lines)
        status_i = next((i for i, ln in enumerate(lines) if live[i] and AMEND_STATUS.match(ln)), None)
        if status_i is None:
            continue
        sm = AMEND_STATUS.match(lines[status_i])
        if sm.group("value").lower() != "proposed":
            continue
        key = f"ratify:{path}"
        sha, why = _amendment_commit(tree, path, name[5:-3])
        if not sha:
            _skip(plan, key, path, "ratify", why)
            continue
        trigger, why, read_error = _resolve_pr(tree, github, sha, plan.default_branch)
        why = why or _maintainer_check(trigger, plan.maintainer, plan.automation)
        if why:
            _skip(plan, key, path, "ratify", why, read_error=read_error)
            continue
        by_i = next((i for i, ln in enumerate(lines) if live[i] and AMEND_RATIFIED_BY.match(ln)), None)
        by = AMEND_RATIFIED_BY.match(lines[by_i]) if by_i is not None else None
        named = _filled(by.group("value"), plan.repo) if by else None
        if named is not None and named != trigger["number"]:
            _skip(plan, key, path, "ratify", f"its Ratified by names #{named}, but the PR that proposed it is "
                                             f"#{trigger['number']}; left for the maintainer")
            continue
        stamp = _stamp(trigger, plan.repo)
        edits = [Edit(path, status_i + 1, "replace", lines[status_i], f"{sm.group('lead')}ratified{sm.group('rest')}",
                      "ratify", path, trigger, key)]
        if by is None:
            eol = "\r" if lines[status_i].endswith("\r") else ""
            edits.append(Edit(path, status_i + 1, "insert", lines[status_i],
                              f"{sm.group('bullet')}**Ratified by:** {stamp}{eol}", "ratify", path, trigger, key))
        elif named is None:
            edits.append(Edit(path, by_i + 1, "replace", lines[by_i], f"{by.group('lead')} {stamp}{by.group('eol')}",
                              "ratify", path, trigger, key))
        plan.edits += edits
        edit, note = _index_edit(index, AMEND_INDEX, m.group(1), r"^\[{n}\]\(", "proposed", "ratified",
                                 "ratify", path, trigger, key)
        if edit:
            plan.edits.append(edit)
        if note:
            plan.notes.append(note)


def _plan_adrs(tree: Tree, github: GitHub, plan: Plan) -> None:
    index = tree.read(ADR_INDEX)
    accepted_rx = re.compile(ADR_FIELD.format(name="Accepted in"))
    completed_rx = re.compile(ADR_FIELD.format(name="Completed"))
    for path in tree.ls(ADR_DIR):
        name = path.rsplit("/", 1)[-1]
        m = RECORD_NAME.match(name)
        if not m:
            continue
        lines = (tree.read(path) or "").split("\n")
        live = _live(lines)
        head_end = _header_end(lines, live)
        header_i: int | None = None          # the header's Status line
        header_status: str | None = None     # the header's status once this plan is applied
        header_anchor: int | None = None     # the header line a Completed line goes after
        for i, line in enumerate(lines):
            sm = ADR_STATUS.match(line) if live[i] else None
            if not sm:
                continue
            value = sm.group("value").lower()
            nxt = accepted_rx.match(lines[i + 1]) if i + 1 < len(lines) and live[i + 1] else None
            if i < head_end and header_i is None:
                header_i, header_status, header_anchor = i, value, (i + 1 if nxt else i)
            if value != "proposed":
                continue
            key = f"accept:{path}:{i + 1}"
            sha = tree.blame(path, i + 1)
            trigger, why, read_error = (_resolve_pr(tree, github, sha, plan.default_branch) if sha
                                        else (None, f"git blame found no commit for {path}:{i + 1}", False))
            why = why or _maintainer_check(trigger, plan.maintainer, plan.automation)
            named = _filled(nxt.group("value"), plan.repo) if nxt else None
            if not why and named is not None and named != trigger["number"]:
                why = (f"the Accepted in under it names #{named}, but the PR that introduced the line is "
                       f"#{trigger['number']}; left for the maintainer")
            if why:
                _skip(plan, key, path, "accept", why, line=i + 1, read_error=read_error)
                continue
            eol = "\r" if line.endswith("\r") else ""
            plan.edits.append(Edit(path, i + 1, "replace", line, f"{sm.group('lead')}accepted{sm.group('rest')}",
                                   "accept", path, trigger, key))
            indent = re.match(r"\s*", line).group(0)
            accepted = f"{indent}- **Accepted in**: {_stamp(trigger, plan.repo)}{eol}"
            if nxt and named is None:
                plan.edits.append(Edit(path, i + 2, "replace", lines[i + 1], accepted, "accept", path, trigger, key))
            elif not nxt:
                plan.edits.append(Edit(path, i + 1, "insert", line, accepted, "accept", path, trigger, key))
            if i == header_i:
                header_status = "accepted"
                edit, note = _index_edit(index, ADR_INDEX, m.group(1), r"^{n}$", "proposed", "accepted",
                                         "accept", path, trigger, key)
                if edit:
                    plan.edits.append(edit)
                if note:
                    plan.notes.append(note)
        _plan_completion(github, plan, path, lines, live, head_end, header_status, header_anchor, completed_rx)


def _plan_completion(github: GitHub, plan: Plan, path: str, lines: list[str], live: list[bool], head_end: int,
                     header_status: str | None, anchor: int | None, completed_rx: re.Pattern) -> None:
    tracking = next((ADR_TRACKING.match(ln) for i, ln in enumerate(lines[:head_end])
                     if live[i] and ADR_TRACKING.match(ln)), None)
    if not tracking or anchor is None:
        return
    number = int(tracking.group("n"))
    key = f"complete:{path}"
    url = f"https://github.com/{github.repo}/issues/{number}"
    try:
        issue = github.issue(number)
        subs = github.sub_issues(number)
    except JevError as exc:
        # One bad Tracking line (a typo, a transferred issue) must not stop every other record.
        missing = "HTTP 404" in str(exc) or "Not Found" in str(exc)
        plan.pending.append({"record": path, "issue": number, "key": key, "url": url, "open_sub_issues": [],
                             "read_error": not missing,
                             "reason": (f"tracking issue #{number} does not exist in {github.repo} (HTTP 404)"
                                        if missing else f"GitHub could not read tracking issue #{number} "
                                                        f"({_why(exc)})")})
        return
    open_subs = sorted(int(s.get("number") or 0) for s in subs if str(s.get("state")) != "closed")
    closer = str(((issue.get("closed_by") or {}).get("login")) or "")
    trigger = {"type": "issue", "number": number, "title": str(issue.get("title") or ""),
               "url": str(issue.get("html_url") or url),
               "state": str(issue.get("state") or ""), "state_reason": str(issue.get("state_reason") or ""),
               "closed_at": str(issue.get("closed_at") or ""), "closed_by": closer,
               "sub_issues": {"total": len(subs), "closed": len(subs) - len(open_subs), "open": open_subs}}
    reason = ""
    if trigger["state"] != "closed":
        reason = f"tracking issue #{number} is open"
    elif trigger["state_reason"] != "completed":
        reason = f"tracking issue #{number} closed as {trigger['state_reason'] or 'unspecified'}, not completed"
    elif closer != plan.maintainer:
        reason = (f"tracking issue #{number} was closed by {'@' + closer if closer else 'an unknown account'}, "
                  f"not the maintainer @{plan.maintainer}")
    elif open_subs:
        reason = f"tracking issue #{number} is closed but sub-issue(s) {', '.join(f'#{n}' for n in open_subs)} are open"
    elif header_status != "accepted":
        reason = f"tracking issue #{number} is complete but the ADR is {header_status}, not accepted"
    if reason:
        plan.pending.append({"record": path, "issue": number, "reason": reason, "key": key, "read_error": False,
                             "open_sub_issues": open_subs, "url": trigger["url"]})
        return
    eol = "\r" if lines[anchor].endswith("\r") else ""
    indent = re.match(r"\s*", lines[anchor]).group(0)
    completed = f"{indent}- **Completed**: {_date(trigger['closed_at'])} (#{number} closed){eol}"
    existing = next((i for i in range(head_end) if live[i] and completed_rx.match(lines[i])), None)
    if existing is not None:
        if lines[existing] != completed:
            plan.edits.append(Edit(path, existing + 1, "replace", lines[existing], completed, "complete", path,
                                   trigger, key))
        return
    plan.edits.append(Edit(path, anchor + 1, "insert", lines[anchor], completed, "complete", path, trigger, key))


def plan(root: Path, *, ref: str = "HEAD", repo: str | None = None) -> Plan:
    """Every record a maintainer's merge (or a completed tracking issue) has
    decided but that still says otherwise, as of `ref`. Idempotent: once its
    edits are on `ref`, the plan for `ref` is empty. A GitHub read that fails
    for one record skips that record (`read_error`); only a repository that
    cannot be read at all raises."""
    tree = Tree(root, ref)
    fleet_text = tree.read(FLEET)
    fleet = (yaml.safe_load(fleet_text) or {}) if fleet_text else None
    hub = hub_repo(fleet)
    p = Plan(repo=repo or hub, ref=tree.sha, maintainer=hub.split("/", 1)[0], automation=_automation_branches(tree))
    github = GitHub(p.repo)
    p.default_branch = github.default_branch()
    _plan_amendments(tree, github, p)
    _plan_adrs(tree, github, p)
    return p


# --------------------------------------------------------------------------- #
# applying a plan, and proving a diff is one
# --------------------------------------------------------------------------- #
def _shape_problem(e: Edit) -> str:
    """Why an edit is not a ratification-record edit, or "" when it is."""
    if not ALLOWED_PATH.match(e.path):
        return f"{e.path}: not a ratification-record file"
    if e.op not in ("replace", "insert") or e.kind not in ("ratify", "accept", "complete"):
        return f"{e.path}:{e.line}: unknown edit {e.op}/{e.kind}"
    if e.path in INDEX_PATHS:
        old, new = CELL_SPLIT.split(e.old), CELL_SPLIT.split(e.new)
        if (e.op != "replace" or len(old) != len(new) or len(old) < 5
                or [c for j, c in enumerate(old) if j != 3] != [c for j, c in enumerate(new) if j != 3]
                or new[3].strip() not in ("ratified", "accepted")):
            return f"{e.path}:{e.line}: an index edit changes only the status cell to ratified or accepted"
        return ""
    if not RECORD_LINE.match(e.new) or "\n" in e.new:
        return f"{e.path}:{e.line}: {e.new[:60]!r} is not a Status, Ratified by, Accepted in or Completed line"
    if e.op == "replace" and not (RECORD_LINE.match(e.old) or e.old.strip() == ""):
        return f"{e.path}:{e.line}: replaces {e.old[:60]!r}, which is not a status line"
    return ""


def apply_text(text: str, edits: list[Edit]) -> str:
    """`text` with `edits` applied; every edit's `old` is verified first."""
    lines = text.split("\n")
    live = _live(lines)
    replace: dict[int, str] = {}
    after: dict[int, list[str]] = {}
    for e in edits:
        problem = _shape_problem(e)
        if problem:
            raise RatifyError(problem)
        if not 1 <= e.line <= len(lines) or lines[e.line - 1] != e.old:
            got = lines[e.line - 1] if 1 <= e.line <= len(lines) else "<past the end>"
            raise RatifyError(f"{e.path}:{e.line}: expected {e.old!r}, found {got!r} — the plan is stale")
        if e.path not in INDEX_PATHS and not live[e.line - 1]:
            raise RatifyError(f"{e.path}:{e.line}: inside a fenced code block — an example, never a record")
        if e.op == "replace":
            if e.line in replace:
                raise RatifyError(f"{e.path}:{e.line}: two replacements of one line")
            replace[e.line] = e.new
        else:
            after.setdefault(e.line, []).append(e.new)
    out: list[str] = []
    for n, line in enumerate(lines, start=1):
        out.append(replace.get(n, line))
        out.extend(after.get(n, []))
    return "\n".join(out)


def _by_path(edits: list[Edit]) -> dict[str, list[Edit]]:
    grouped: dict[str, list[Edit]] = {}
    for e in edits:
        grouped.setdefault(e.path, []).append(e)
    return grouped


def apply(root: Path, p: Plan) -> list[str]:
    """Write `p` into the working tree. Every file is checked before any is
    written, so a mismatch anywhere changes nothing. Bytes in, bytes out: a
    CRLF record stays CRLF."""
    out: dict[Path, bytes] = {}
    for rel, edits in _by_path(p.edits).items():
        f = root / rel
        if not f.is_file():
            raise RatifyError(f"{rel}: not in the working tree")
        out[f] = _encode(apply_text(_decode(f.read_bytes()), edits))
    for f, data in out.items():
        f.write_bytes(data)
    return sorted(p_.relative_to(root).as_posix() for p_ in out)


def diff_problems(root: Path, base: str, head: str, p: Plan) -> list[str]:
    """Why `git diff base head` is not exactly plan `p`: every changed path one
    of the four record files, modified in place at mode 100644, each
    byte-identical to `p` applied to `base`, and every planned file changed."""
    base_tree, head_tree = Tree(root, base), Tree(root, head)
    problems = [msg for e in p.edits for msg in [_shape_problem(e)] if msg]
    res = git(["diff", "--raw", "--no-renames", "--no-abbrev", base_tree.sha, head_tree.sha], cwd=root)
    if not res.ok:
        return [f"could not diff {base}..{head}: {res.err.strip() or 'unknown error'}"]
    changed: dict[str, tuple[str, str, str]] = {}
    for row in res.out.splitlines():
        meta, _tab, rel = row.partition("\t")
        parts = meta.lstrip(":").split()
        if rel and len(parts) >= 5:
            changed[rel] = (parts[0], parts[1], parts[4])
    planned = _by_path(p.edits)
    for rel, (old_mode, new_mode, status) in sorted(changed.items()):
        if not ALLOWED_PATH.match(rel):
            problems.append(f"{rel}: not a ratification-record file (only docs/amendments/NNNN-*.md, "
                            "docs/amendments/README.md, docs/adr/NNNN-*.md and docs/adr/README.md)")
        elif status != "M":
            problems.append(f"{rel}: {({'A': 'added', 'D': 'deleted', 'T': 'retyped'}).get(status[:1], status)} — "
                            "a ratification-record change only modifies existing records")
        elif old_mode != new_mode or new_mode != RECORD_MODE:
            problems.append(f"{rel}: mode {old_mode} → {new_mode} — a record file stays {RECORD_MODE}")
        elif rel not in planned:
            problems.append(f"{rel}: changed, but the plan as of {base_tree.sha[:7]} has no edit for it")
        else:
            try:
                want = _encode(apply_text(base_tree.read(rel) or "", planned[rel]))
            except RatifyError as exc:
                problems.append(str(exc))
                continue
            got = git_bytes(["show", f"{head_tree.sha}:{rel}"], cwd=root) or b""
            if got != want:
                problems.append(_first_difference(rel, _decode(want), _decode(got)))
    for rel in sorted(planned):
        if rel not in changed:
            problems.append(f"{rel}: the plan edits it, but the diff does not")
    return problems


def check_diff(root: Path, base: str, head: str = "HEAD", repo: str | None = None,
               held: Plan | None = None) -> tuple[Plan, list[str]]:
    """(the plan as of `base`, problems). No problem means `git diff base head`
    is exactly that plan: the same files, each byte-identical to the plan
    applied to `base`, and nothing else. With `held` (the plan the head was
    built from) see `verify` for the codes; this keeps the plain answer."""
    if held is not None:
        _code, problems, _notes = verify(root, base, head, held, repo=repo)
        return held, problems
    p = plan(root, ref=base, repo=repo)
    return p, diff_problems(root, base, head, p)


def verify(root: Path, base: str, head: str, held: Plan, *,
           repo: str | None = None) -> tuple[int, list[str], list[str]]:
    """(verdict, problems, notes) for a head built from plan `held`:
    REFUSE when the diff is not exactly `held` (or `held` is not a plan of
    `base`), or a record in it no longer holds; WAIT when GitHub could not be
    read; RECUT when a record's edits changed since `held` was made. A record
    that became eligible after `held` is a note, never a failure — the next
    run records it."""
    base_sha = Tree(root, base).sha
    if held.ref != base_sha:
        return REFUSE, [f"the plan is as of {held.ref[:7]}, but the change is cut from {base_sha[:7]}"], []
    problems = diff_problems(root, base, head, held)
    if problems:
        return REFUSE, problems, []
    try:
        fresh = plan(root, ref=base, repo=repo or held.repo)
    except JevError as exc:
        return WAIT, [f"GitHub could not be read to re-check the triggers ({_why(exc)})"], []
    code, out = GO, []
    for key in held.keys():
        if fresh.by_key(key) == held.by_key(key):
            continue
        if fresh.by_key(key):
            code = max(code, RECUT) if code != REFUSE else code
            out.append(f"{key}: its edits changed since the plan was made; re-plan")
            continue
        why = fresh.why_not(key)
        if why and why.get("read_error"):
            code = WAIT if code == GO else code
            out.append(f"{key}: {why['reason']}")
        else:
            code = REFUSE
            out.append(f"{key}: no longer holds — {why['reason'] if why else 'it is no longer in the plan'}")
    notes = [f"{k}: became eligible after the plan; the next run records it" for k in fresh.keys()
             if k not in set(held.keys())]
    return code, out, notes


def _first_difference(rel: str, want: str, got: str) -> str:
    w, g = want.split("\n"), got.split("\n")
    for i in range(max(len(w), len(g))):
        a = w[i] if i < len(w) else "<end of file>"
        b = g[i] if i < len(g) else "<end of file>"
        if a != b:
            return (f"{rel}:{i + 1}: {b[:100]!r} is not the plan's {a[:100]!r} — an edit outside the Status, "
                    "Ratified by, Accepted in and Completed lines and index status cells")
    return f"{rel}: differs from the plan"


# --------------------------------------------------------------------------- #
# the record PR: which one is the job's, and may it merge
# --------------------------------------------------------------------------- #
def _own(pr: dict, repo: str, maintainer: str) -> bool:
    """A PR the post-merge job opened: from this repository's own record
    branch (never a fork's branch of the same name), by the maintainer's
    token, into the default branch."""
    head = pr.get("head") or {}
    return (str((head.get("repo") or {}).get("full_name") or "") == repo and str(head.get("ref") or "") == BRANCH
            and str((pr.get("user") or {}).get("login") or "") == maintainer)


def _plan_mark(body: str) -> dict:
    m = PLAN_MARK.search(body or "")
    try:
        return json.loads(m.group("json")) if m else {}
    except ValueError:
        return {}


def select(p: Plan, *, manual: bool = False) -> dict:
    """What the job does with plan `p`: {"action": create | update | hold,
    "number": N or None, "reason": …}. Only the job's own PRs count (`_own`).
    An open one carrying a hold label is the maintainer's. A record PR the
    maintainer closed unmerged for this same plan holds it until a manual
    dispatch: closing is a brake, not an invitation to reopen."""
    github = GitHub(p.repo)
    pulls = [pr for pr in github.record_pulls(p.default_branch) if _own(pr, p.repo, p.maintainer)]
    opened = [pr for pr in pulls if pr.get("state") == "open"]
    if opened:
        pr = opened[0]
        held = [str(lb.get("name")) for lb in pr.get("labels") or [] if str(lb.get("name")) in HOLD_LABELS]
        if held:
            return {"action": "hold", "number": pr["number"],
                    "reason": f"#{pr['number']} carries {', '.join(held)}: it is the maintainer's (constitution "
                              "§ 12.4); not updated, not merged"}
        return {"action": "update", "number": pr["number"], "reason": f"updating the open record PR #{pr['number']}"}
    closed = next((pr for pr in pulls if pr.get("state") == "closed"), None)
    if closed and not closed.get("merged_at") and not manual:
        if _plan_mark(str(closed.get("body") or "")).get("digest") == p.digest():
            closer = str((github.issue(int(closed["number"])).get("closed_by") or {}).get("login") or "")
            if not closer.endswith("[bot]"):
                return {"action": "hold", "number": closed["number"],
                        "reason": f"#{closed['number']}, the record PR for this same plan, was closed unmerged"
                                  f"{' by @' + closer if closer else ''} on {_date(closed.get('closed_at'))}; "
                                  "held until a manual dispatch or a change to the plan"}
    return {"action": "create", "number": None, "reason": "no open record PR; opening one"}


def _check_verdict(github: GitHub, sha: str) -> tuple[int, str]:
    runs, statuses = github.check_runs(sha), github.statuses(sha)
    bad = [f"{r.get('name')} ({r.get('conclusion')})" for r in runs
           if r.get("status") == "completed" and r.get("conclusion") not in CHECK_OK]
    bad += [f"{s.get('context')} ({s.get('state')})" for s in statuses if s.get("state") in ("failure", "error")]
    if bad:
        return REFUSE, f"check(s) on {sha[:7]} did not pass: {', '.join(bad)}"
    waiting = [str(r.get("name")) for r in runs if r.get("status") != "completed"]
    waiting += [str(s.get("context")) for s in statuses if s.get("state") not in ("success", "failure", "error")]
    if waiting:
        return WAIT, f"{len(waiting)} check(s) on {sha[:7]} still running: {', '.join(waiting[:8])}"
    if not runs and not statuses:
        return WAIT, f"no check has reported on {sha[:7]} yet"
    return GO, f"{len(runs)} check run(s) and {len(statuses)} status(es) on {sha[:7]} passed"


def guard(root: Path, number: int, sha: str, *, base_ref: str = "main", held: Plan | None = None,
          repo: str | None = None) -> tuple[int, list[str]]:
    """May the job merge record PR #`number` at `sha` now? (verdict, reasons).
    Read-only: GETs and local git. In order — the first answer that is not
    go decides: the PR is open and the job's own; its head is `sha`; no hold
    label; `sha` is one commit whose only parent is the live tip of
    `base_ref`; every check run and status on `sha` completed as success,
    skipped or neutral (at least one); GitHub reports it mergeable; and the
    diff is exactly the plan it was built from (`held`, else the keys its
    body names), each of whose triggers still holds (`verify`)."""
    tree = Tree(root, "HEAD")
    fleet_text = tree.read(FLEET)
    hub = hub_repo((yaml.safe_load(fleet_text) or {}) if fleet_text else None)
    repo = repo or (held.repo if held else "") or hub
    maintainer = hub.split("/", 1)[0]
    github = GitHub(repo)
    try:
        pr = github.pull(number, fresh=True)
    except JevError as exc:
        return WAIT, [f"GitHub could not read PR #{number} ({_why(exc)})"]
    if pr.get("merged_at"):
        return STOP, [f"#{number} is already merged"]
    if pr.get("state") != "open":
        return STOP, [f"#{number} is closed; closing a record PR is the maintainer's brake"]
    if not _own(pr, repo, maintainer):
        head = pr.get("head") or {}
        return REFUSE, [f"#{number} is not the job's own record PR (head {(head.get('repo') or {}).get('full_name')}:"
                        f"{head.get('ref')}, author @{(pr.get('user') or {}).get('login')})"]
    if str((pr.get("base") or {}).get("ref") or "") != base_ref:
        return REFUSE, [f"#{number}'s base is {(pr.get('base') or {}).get('ref')}, not {base_ref}"]
    if pr.get("draft"):
        return REFUSE, [f"#{number} was turned into a draft"]
    head_sha = str((pr.get("head") or {}).get("sha") or "")
    if head_sha != sha:
        return REFUSE, [f"#{number}'s head moved from {sha[:7]} to {head_sha[:7]}: something other than the job "
                        "pushed to its branch"]
    held_labels = [str(lb.get("name")) for lb in pr.get("labels") or [] if str(lb.get("name")) in HOLD_LABELS]
    if held_labels:
        return STOP, [f"#{number} carries {', '.join(held_labels)}: left to the maintainer"]
    parents = git(["log", "-1", "--format=%P", sha], cwd=root)
    if not parents.ok:
        return WAIT, [f"commit {sha[:7]} is not in this checkout (fetch the record branch)"]
    if len(parents.out.split()) != 1:
        return REFUSE, [f"{sha[:7]} has {len(parents.out.split())} parents; a record PR is ONE commit on {base_ref}"]
    parent = parents.out.split()[0]
    try:
        tip = github.branch_tip(base_ref)
    except JevError as exc:
        return WAIT, [f"GitHub could not read {base_ref}'s tip ({_why(exc)})"]
    if parent != tip:
        return RECUT, [f"{base_ref} moved to {tip[:7]} after the branch was cut from {parent[:7]}; re-cut"]
    try:
        code, why = _check_verdict(github, sha)
    except JevError as exc:
        return WAIT, [f"GitHub could not read the checks on {sha[:7]} ({_why(exc)})"]
    if code != GO:
        return code, [why]
    mergeable, state = pr.get("mergeable"), str(pr.get("mergeable_state") or "unknown")
    if mergeable is None or state == "unknown":
        return WAIT, [f"GitHub has not computed #{number}'s mergeability yet"]
    if state == "behind":
        return RECUT, [f"#{number} is behind {base_ref}; re-cut"]
    if mergeable is not True or state not in ("clean", "has_hooks", "unstable"):
        return REFUSE, [f"#{number} is not mergeable (mergeable={mergeable}, state={state})"]
    if held is None:
        mark = _plan_mark(str(pr.get("body") or ""))
        if not mark.get("keys"):
            return REFUSE, [f"#{number}'s body names no plan (<!-- jev-ratify plan: … -->)"]
        try:
            fresh = plan(root, ref=parent, repo=repo)
        except JevError as exc:
            return WAIT, [f"GitHub could not be read to re-plan ({_why(exc)})"]
        held = fresh.restricted(list(mark["keys"]))
        missing = [k for k in mark["keys"] if not held.by_key(k)]
        if missing:
            why = [fresh.why_not(k) for k in missing]
            if any(w and w.get("read_error") for w in why):
                return WAIT, [f"{k}: {w['reason']}" for k, w in zip(missing, why) if w]
            return REFUSE, [f"{k}: no longer holds — {w['reason'] if w else 'not in the plan'}"
                            for k, w in zip(missing, why)]
    code, problems, _notes = verify(root, parent, sha, held, repo=repo)
    if code != GO:
        return code, problems
    return GO, [why, f"#{number} at {sha[:7]} is exactly the plan as of {parent[:7]} ({len(held.edits)} edit(s))"]


# --------------------------------------------------------------------------- #
# the pull request body
# --------------------------------------------------------------------------- #
def _counts(p: Plan) -> dict[str, int]:
    return {"ratified": len(p.records("ratify")),
            "accepted": len({(e.path, e.line) for e in p.edits if e.kind == "accept" and e.op == "replace"
                             and e.path not in INDEX_PATHS and ADR_STATUS.match(e.new)}),
            "completed": len(p.records("complete"))}


def pr_title(p: Plan) -> str:
    parts = [f"{n} {k}" for k, n in _counts(p).items() if n]
    return defuse("chore(jev): record ratification and acceptance" + (f" ({', '.join(parts)})" if parts else ""))


def _title_of(root: Path, ref: str, rel: str) -> str:
    text = Tree(root, ref).read(rel) or ""
    m = re.search(r"^#\s+(?:ADR\s+)?\d{4}\s+—\s+(.+?)\r?$", text, re.M)
    return m.group(1).strip() if m else rel.rsplit("/", 1)[-1]


def defuse(text: str) -> str:
    """`text` with every GitHub closing keyword parted from its reference
    (`Fixes #5` → `Fixes (ref #5)`), so merging the record PR closes nothing."""
    return CLOSING_REF.sub(lambda m: f"{m['kw']}{m['sep'] or ' '}(ref {m['ref']})", text)


def _cell(text: str) -> str:
    return defuse(str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " "))


def pr_body(p: Plan, root: Path | None = None) -> str:
    def title(rel: str) -> str:
        return _cell(_title_of(root, p.ref, rel)) if root else ""

    def pr_cells(t: dict) -> str:
        return (f"[#{t['number']}]({t['url']}) {_cell(t['title'])} | {_date(t['merged_at'])} | @{t['merged_by']} | "
                f"`{t['merge_commit_sha'][:7]}`")

    out = [
        "## Ratification and acceptance records", "",
        "The maintainer's merge of each trigger pull request below **is** the ratification (an amendment, "
        "constitution § 8.3) or the acceptance (an ADR, [docs/adr/README.md](docs/adr/README.md)); this pull "
        "request only records it (amendment `ratification-records`). It changes Status, Ratified by, Accepted "
        "in and Completed lines and index status cells, and nothing else.", "",
    ]
    rat = [e for e in p.edits if e.kind == "ratify" and e.op == "replace" and AMEND_STATUS.match(e.new)]
    if rat:
        out += ["### Amendments ratified", "",
                "| Record | Change | Trigger PR | Merged | Merged by | Merge commit |",
                "| --- | --- | --- | --- | --- | --- |"]
        for e in rat:
            num = e.path.rsplit("/", 1)[-1][:4]
            out.append(f"| [{num}]({e.path}) {title(e.path)} | proposed → ratified | {pr_cells(e.trigger)} |")
        out.append("")
    acc = [e for e in p.edits if e.kind == "accept" and e.op == "replace" and ADR_STATUS.match(e.new)]
    if acc:
        out += ["### ADRs accepted", "",
                "| Record | Status line | Change | Trigger PR | Merged | Merged by | Merge commit |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for e in acc:
            num = e.path.rsplit("/", 1)[-1][:4]
            out.append(f"| [ADR {num}]({e.path}) {title(e.path)} | L{e.line} | proposed → accepted | "
                       f"{pr_cells(e.trigger)} |")
        out.append("")
    com = [e for e in p.edits if e.kind == "complete"]
    if com:
        out += ["### ADRs completed", "", "| Record | Tracking issue | Closed | Closed by | Sub-issues closed |",
                "| --- | --- | --- | --- | --- |"]
        for e in com:
            t, num = e.trigger, e.path.rsplit("/", 1)[-1][:4]
            out.append(f"| [ADR {num}]({e.path}) {title(e.path)} | [#{t['number']}]({t['url']}) {_cell(t['title'])} | "
                       f"{_date(t['closed_at'])} ({t['state_reason']}) | @{t.get('closed_by', '')} | "
                       f"{t['sub_issues']['closed']} of {t['sub_issues']['total']} |")
        out.append("")
    triggers = {e.trigger["number"]: e.trigger for e in p.edits if e.trigger.get("type") == "pr"}
    # "#N closed #M" is a closing keyword: GitHub would close #M again on this
    # PR's merge. Name the link without one.
    follow = [f"- [#{n}]({t['url']}) linked issue(s) {', '.join(f'#{i}' for i in t['closing_issues'])} "
              "(GitHub resolved them when that pull request merged)"
              for n, t in sorted(triggers.items()) if t.get("closing_issues")]
    follow += [f"- {x['record']}: completes when the maintainer finishes [issue {x['issue']}]({x['url']}) as "
               f"completed with every sub-issue done — now: {x['reason']}"
               + (f" (open sub-issues: {', '.join(f'#{n}' for n in x['open_sub_issues'])})"
                  if x.get("open_sub_issues") else "") for x in p.pending]
    if follow:
        out += ["### Linked issues and follow-ups", "", *follow, ""]
    if p.skipped:
        out += ["### Skipped", "", "| Record | Kind | Reason |", "| --- | --- | --- |"]
        out += [f"| {s['record']}{(':' + str(s['line'])) if s.get('line') else ''} | {s['kind']} | "
                f"{_cell(s['reason'])}{' (a read failure; the next run retries)' if s.get('read_error') else ''} |"
                for s in p.skipped]
        out.append("")
    if p.notes:
        out += ["### Notes", "", *[f"- {n}" for n in p.notes], ""]
    out += [
        "### The guard that merges this pull request", "",
        f"The `ratify` job in `.github/workflows/jev-number.yml` merges this pull request itself, and only when "
        f"`python3 -m tools.jev ratify guard --pr <n> --sha <head sha>` says go: the PR is the job's own (this "
        f"repository's `{BRANCH}`, opened by the maintainer's token) and open; its head is unchanged and is ONE "
        f"commit whose only parent is the current tip of `{p.default_branch}`; it carries none of "
        f"{', '.join(f'`{h}`' for h in HOLD_LABELS)}; every check run and status on that SHA completed as success, "
        f"skipped or neutral (at least one); GitHub reports it mergeable; and the diff is exactly the plan below, "
        f"each of whose triggers still holds. Then: `gh pr merge <n> --merge --match-head-commit <head sha> "
        f"--delete-branch` — a merge commit, never squash, `--admin` or `--auto`. A refused guard labels it "
        f"`needs-amr`, says why, and leaves it to the maintainer; a check still running or a GitHub read that "
        f"failed only waits.", "",
        "<!-- jev-ratify plan: "
        f"{json.dumps({'repo': p.repo, 'ref': p.ref, 'digest': p.digest(), 'keys': p.keys()})} -->",
    ]
    return defuse("\n".join(out)) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("action", choices=("plan", "apply", "check-diff", "pr-body", "select", "guard"))
    ap.add_argument("--root", default=".", help="the repository checkout (default: .)")
    ap.add_argument("--ref", default="HEAD", help="plan as of this commit (default: HEAD)")
    ap.add_argument("--repo", default=None, help="the GitHub OWNER/NAME (default: _data/fleet.yml hub.repo)")
    ap.add_argument("--plan", dest="plan_file", default=None,
                    help="apply / pr-body / select / check-diff / guard: a plan written by `plan --out` "
                         "(default: plan now; check-diff and guard: the plan the head was built from)")
    ap.add_argument("--out", default=None, help="plan: also write the JSON plan to this file")
    ap.add_argument("--base", default=None, help="check-diff: the commit the change is cut from")
    ap.add_argument("--head", default="HEAD", help="check-diff: the commit to check (default: HEAD)")
    ap.add_argument("--title", action="store_true", help="pr-body: print the pull request title instead")
    ap.add_argument("--manual", action="store_true", help="select: a manual dispatch (lifts a closed-PR hold)")
    ap.add_argument("--pr", type=int, default=None, help="guard: the record PR's number")
    ap.add_argument("--sha", default=None, help="guard: the head SHA the job pushed")
    ap.add_argument("--base-ref", default="main", help="guard: the branch the record merges into (default: main)")
    ap.add_argument("--json", action="store_true")


def _read_plan(path: str) -> Plan:
    try:
        return Plan.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise RatifyError(f"cannot read the plan {path}: {exc}") from exc


def _load_or_plan(args: argparse.Namespace, root: Path) -> Plan:
    return _read_plan(args.plan_file) if args.plan_file else plan(root, ref=args.ref, repo=args.repo)


def _print_plan(p: Plan) -> None:
    print(f"ratify plan @ {p.ref[:7]} ({p.repo}; maintainer @{p.maintainer})")
    for e in p.edits:
        t = e.trigger
        tag = (f"#{t['number']} merged {_date(t.get('merged_at'))} by @{t.get('merged_by')}"
               if t.get("type") == "pr" else f"#{t['number']} closed {_date(t.get('closed_at'))}")
        print(f"  {e.kind:<8} {e.path}:{e.line} {e.op}  ← {tag}")
        if e.op == "replace":
            print(f"           - {e.old.strip()[:110]}")
        print(f"           + {e.new.strip()[:110]}")
    for s in p.skipped:
        print(f"  skip     {s['record']}{(':' + str(s['line'])) if s.get('line') else ''} ({s['kind']}): {s['reason']}")
    for x in p.pending:
        print(f"  pending  {x['record']}: {x['reason']}")
    for n in p.notes:
        print(f"  note     {n}")
    print(f"{len(p.edits)} edit(s) in {len(_by_path(p.edits))} file(s); {len(p.skipped)} skipped"
          if p.edits else f"nothing to record; {len(p.skipped)} skipped")


def _verdict_out(args: argparse.Namespace, what: str, code: int, reasons: list[str], extra: dict) -> None:
    if args.json:
        print(json.dumps({"verdict": VERDICT.get(code, str(code)), "code": code, "reasons": reasons, **extra},
                         indent=2))
        return
    for r in reasons:
        print(f"  {r}")
    print(f"{what}: {VERDICT.get(code, str(code))}")


def main(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.action == "check-diff":
        if not args.base:
            print("jev ratify check-diff: --base is required", file=sys.stderr)
            return 2
        if args.plan_file:
            held = _read_plan(args.plan_file)
            code, problems, notes = verify(root, args.base, args.head, held, repo=args.repo)
            _verdict_out(args, "check-diff", code, problems + notes, {"base": held.ref, "edits": len(held.edits)})
            return 0 if code == GO else (1 if code == REFUSE else WAIT)
        try:
            p = plan(root, ref=args.base, repo=args.repo)
        except JevError as exc:
            print(f"check-diff: GitHub could not be read ({_why(exc)}); retry", file=sys.stderr)
            return WAIT
        problems = diff_problems(root, args.base, args.head, p)
        if args.json:
            print(json.dumps({"base": p.ref, "edits": len(p.edits), "problems": problems}, indent=2))
        else:
            for pr in problems:
                print(f"  error: {pr}")
            print(f"check-diff: the diff is exactly the plan ({len(p.edits)} edit(s)) as of {p.ref[:7]}"
                  if not problems else f"check-diff: {len(problems)} problem(s) — not a ratification-record change")
        if problems and any(s.get("read_error") for s in [*p.skipped, *p.pending]):
            print("check-diff: the plan skipped a record GitHub could not be read for; retry before refusing",
                  file=sys.stderr)
            return WAIT
        return 1 if problems else 0
    if args.action == "guard":
        if args.pr is None or not args.sha:
            print("jev ratify guard: --pr and --sha are required", file=sys.stderr)
            return 2
        held = _read_plan(args.plan_file) if args.plan_file else None
        code, reasons = guard(root, args.pr, args.sha, base_ref=args.base_ref, held=held, repo=args.repo)
        _verdict_out(args, f"guard #{args.pr} @ {args.sha[:7]}", code, reasons, {"pr": args.pr, "sha": args.sha})
        return code
    if args.action == "select":
        if not args.plan_file:
            print("jev ratify select: --plan is required", file=sys.stderr)
            return 2
        print(json.dumps(select(_read_plan(args.plan_file), manual=args.manual)))
        return 0
    p = _load_or_plan(args, root)
    if args.action == "plan":
        if args.out:
            Path(args.out).write_text(json.dumps(p.to_dict(), indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(p.to_dict(), indent=2))
        else:
            _print_plan(p)
        return 0
    if args.action == "apply":
        try:
            changed = apply(root, p)
        except RatifyError as exc:
            print(f"jev ratify apply: refused: {exc}", file=sys.stderr)
            return 1
        print(f"applied {len(p.edits)} edit(s) to {len(changed)} file(s)" if changed else "nothing to record")
        for rel in changed:
            print(f"  {rel}")
        return 0
    print(pr_title(p) if args.title else pr_body(p, root), end="\n" if args.title else "")
    return 0

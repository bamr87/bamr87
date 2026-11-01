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
               complete — an ADR whose `- **Tracking**: #N` issue closed as
                          completed with every sub-issue closed gets
                          `- **Completed**: <date> (#N closed)`

             It reads GitHub (GETs only, through `common.gh`) and writes only
             the working tree. It never pushes, opens or merges anything: the
             `ratify` job in .github/workflows/jev-number.yml does that, and
             merges only when `check-diff` proves the pull request holds
             exactly this plan (amendment `ratification-records`).
Author: bamr87
Created: 2026-11-01
Version: 0.1.0
Usage:
  python3 -m tools.jev ratify plan       [--json] [--out FILE] [--ref HEAD] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify apply      [--plan FILE] [--ref HEAD] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify check-diff --base REV [--head HEAD] [--repo OWNER/NAME] [--root .]
  python3 -m tools.jev ratify pr-body    [--plan FILE] [--title] [--ref HEAD] [--repo OWNER/NAME] [--root .]
Exit: 0 clean, 1 a problem the caller must fix (a mismatch, a diff that is
      not the plan), 2 usage.
Dependencies: PyYAML; `git` (full history: blame and log); `gh` for the GETs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .common import JevError, git, gh_json, hub_repo

AMEND_DIR = "docs/amendments"
AMEND_INDEX = "docs/amendments/README.md"
AMEND_PROPOSED = "docs/amendments/proposed"
ADR_DIR = "docs/adr"
ADR_INDEX = "docs/adr/README.md"
FLEET = "_data/fleet.yml"
BRANCH = "chore/jev-ratify"
SCHEMA = "jev-ratify/v1"

#: a numbered record, never the 0000 template
RECORD_NAME = re.compile(r"^(?!0000-)(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
#: the only files a ratification-record change may touch (amendment `ratification-records`)
ALLOWED_PATH = re.compile(r"^(?:docs/amendments/(?!0000-)\d{4}-[a-z0-9][a-z0-9-]*\.md|docs/amendments/README\.md"
                          r"|docs/adr/(?!0000-)\d{4}-[a-z0-9][a-z0-9-]*\.md|docs/adr/README\.md)$")
INDEX_PATHS = (AMEND_INDEX, ADR_INDEX)

# Amendments put the colon INSIDE the bold (`**Status:**`); ADRs put it outside
# (`**Status**:`). Each pattern keeps the lead (indent, bullet, field name) so
# a rewritten line differs from the original only in its value.
AMEND_STATUS = re.compile(r"^(?P<lead>(?P<bullet>\s*[-*]\s+)\*\*Status:\*\*\s*)(?P<value>\S+)(?P<rest>.*)$")
AMEND_RATIFIED_BY = re.compile(r"^(?P<lead>\s*[-*]\s+\*\*Ratified by:\*\*)(?P<value>.*)$")
ADR_STATUS = re.compile(r"^(?P<lead>(?P<bullet>\s*[-*]\s+)\*\*Status\*\*:\s*)(?P<value>[A-Za-z]+)(?P<rest>.*)$")
ADR_FIELD = r"^\s*[-*]\s+\*\*{name}\*\*:\s*(?P<value>.*)$"
ADR_TRACKING = re.compile(r"^\s*[-*]\s+\*\*Tracking\*\*:\s*#(?P<n>\d+)\b")
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
#: the line shapes a planned edit may write into a record (check-diff re-asserts them)
RECORD_LINE = re.compile(r"^\s*[-*]\s+\*\*(?:Status:\*\*|Ratified by:\*\*|Status\*\*:|Accepted in\*\*:|Completed\*\*:)")
#: a closing keyword in a PR body, the fallback when GraphQL is unavailable
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.I)

HOLD_LABELS = ("needs-amr", "agent:hold", "blocked")


class RatifyError(JevError):
    """A plan that cannot be applied or a diff that is not the plan."""


# --------------------------------------------------------------------------- #
# GitHub: GETs only, through common.gh (the guard refuses anything else)
# --------------------------------------------------------------------------- #
def _gh_json(args: list[str]):
    """The one seam to GitHub; the tests replace it with a fake."""
    return gh_json(args)


class GitHub:
    """The handful of reads a plan needs, cached per run."""

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

    def pull(self, number: int) -> dict:
        if number not in self._pulls:
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

    def sub_issues(self, number: int) -> list[dict]:
        pages = _gh_json(["api", "--paginate", "--slurp",
                          f"repos/{self.repo}/issues/{number}/sub_issues?per_page=100"]) or []
        out: list[dict] = []
        for page in pages:
            out.extend(page if isinstance(page, list) else [page])
        return [i for i in out if isinstance(i, dict)]


# --------------------------------------------------------------------------- #
# the repository as of one commit
# --------------------------------------------------------------------------- #
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
        res = git(["show", f"{self.sha}:{rel}"], cwd=self.root)
        return res.out if res.ok else None

    def ls(self, rel_dir: str) -> list[str]:
        res = git(["ls-tree", "--name-only", self.sha, f"{rel_dir}/"], cwd=self.root)
        return sorted(line.strip() for line in res.out.splitlines() if line.strip()) if res.ok else []

    def added_by(self, rel: str, *, follow: bool = False) -> str | None:
        """The newest commit reachable from this one that ADDED `rel`."""
        args = ["log", self.sha, "--diff-filter=A", "--format=%H", *(["--follow"] if follow else []), "--", rel]
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


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #
@dataclass
class Edit:
    """One line operation. `replace` swaps line `line` (which must read `old`);
    `insert` adds `new` right after line `line` (which must read `old`)."""

    path: str
    line: int
    op: str            # replace | insert
    old: str
    new: str
    kind: str          # ratify | accept | complete
    record: str
    trigger: dict


@dataclass
class Plan:
    repo: str
    ref: str
    maintainer: str
    default_branch: str = "main"
    edits: list[Edit] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)   # tracked ADRs whose issue is still open
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.edits

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "repo": self.repo, "ref": self.ref, "maintainer": self.maintainer,
                "default_branch": self.default_branch, "edits": [asdict(e) for e in self.edits],
                "skipped": self.skipped, "pending": self.pending, "notes": self.notes}

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


def _date(stamp: str | None) -> str:
    return str(stamp or "")[:10]


def _pr_trigger(github: GitHub, number: int, commit: str) -> dict:
    pr = github.pull(number)
    login = str(((pr.get("merged_by") or {}).get("login")) or "")
    return {
        "type": "pr", "number": number, "title": str(pr.get("title") or ""),
        "url": str(pr.get("html_url") or f"https://github.com/{github.repo}/pull/{number}"),
        "merged": bool(pr.get("merged_at")), "merged_at": str(pr.get("merged_at") or ""),
        "merged_by": login, "merge_commit_sha": str(pr.get("merge_commit_sha") or ""),
        "base": str((pr.get("base") or {}).get("ref") or ""),
        "labels": sorted(str(lb.get("name")) for lb in pr.get("labels") or [] if isinstance(lb, dict)),
        "closing_issues": github.closing_issues(number, str(pr.get("body") or "")) if pr.get("merged_at") else [],
        "commit": commit,
    }


def _resolve_pr(tree: Tree, github: GitHub, sha: str, default: str) -> tuple[dict | None, str]:
    """(trigger, "") for the merged PR that brought `sha` onto the default
    branch, or (None, why not). The commit's own PRs first (GitHub associates a
    squash or merge with them); when it has none merged into the default
    branch — a stacked PR merged into its parent's branch — the PR of the
    first-parent commit that brought it in."""
    tried: list[dict] = []
    for step in (0, 1):
        candidate = sha if step == 0 else tree.mainline(sha)
        if not candidate or (step == 1 and candidate == sha):
            continue
        pulls = github.pulls_for_commit(candidate)
        tried += pulls
        merged = sorted((p for p in pulls if p.get("merged_at") and (p.get("base") or {}).get("ref") == default),
                        key=lambda p: str(p.get("merged_at")))
        if merged:
            return _pr_trigger(github, int(merged[0]["number"]), sha), ""
    if tried:
        nums = ", ".join(f"#{p.get('number')}" for p in tried)
        return None, f"commit {sha[:7]}'s pull request ({nums}) is not merged into {default}"
    return None, f"commit {sha[:7]} reached {default} without a pull request (a direct push decides nothing)"


def _maintainer_check(trigger: dict, maintainer: str) -> str:
    if not trigger.get("merged"):
        return f"PR #{trigger['number']} is not merged"
    if trigger.get("merged_by") != maintainer:
        who = f"@{trigger['merged_by']}" if trigger.get("merged_by") else "an unknown account"
        return f"PR #{trigger['number']} was merged by {who}, not the maintainer @{maintainer}"
    return ""


def _stamp(trigger: dict, repo: str) -> str:
    return (f"https://github.com/{repo}/pull/{trigger['number']} "
            f"(merged {_date(trigger['merged_at'])} by @{trigger['merged_by']})")


def _index_edit(text: str | None, path: str, number: str, link_rx: str, old_status: str, new_status: str,
                kind: str, record: str, trigger: dict) -> tuple[Edit | None, str]:
    """The index row for `number` with only its status cell changed."""
    if text is None:
        return None, f"{path}: missing, so {record}'s row could not be updated"
    for i, line in enumerate(text.split("\n"), start=1):
        cells = line.split("|")
        if len(cells) < 5 or not re.match(link_rx.format(n=re.escape(number)), cells[1].strip()):
            continue
        if cells[3].strip() != old_status:
            return None, f"{path}:{i}: {record}'s status cell reads {cells[3].strip()!r}, left as it is"
        cells[3] = cells[3].replace(old_status, new_status, 1)
        return Edit(path, i, "replace", line, "|".join(cells), kind, record, trigger), ""
    return None, f"{path}: no index row for {number}"


def _header_end(lines: list[str]) -> int:
    """Index of the first `## ` heading: the header block is everything above it."""
    return next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))


def _plan_amendments(tree: Tree, github: GitHub, plan: Plan) -> None:
    index = tree.read(AMEND_INDEX)
    for path in tree.ls(AMEND_DIR):
        name = path.rsplit("/", 1)[-1]
        m = RECORD_NAME.match(name)
        if not m:
            continue
        text = tree.read(path) or ""
        lines = text.split("\n")
        status_i = next((i for i, ln in enumerate(lines) if AMEND_STATUS.match(ln)), None)
        if status_i is None:
            continue
        sm = AMEND_STATUS.match(lines[status_i])
        if sm.group("value").lower() != "proposed":
            continue
        slug = name[5:-3]
        sha = (tree.added_by(f"{AMEND_PROPOSED}/{slug}.md") or tree.added_by(path, follow=True))
        if not sha:
            plan.skipped.append({"record": path, "kind": "ratify", "reason": f"no commit on {tree.sha[:7]} adds it"})
            continue
        trigger, why = _resolve_pr(tree, github, sha, plan.default_branch)
        why = why or _maintainer_check(trigger, plan.maintainer)
        if why:
            plan.skipped.append({"record": path, "kind": "ratify", "reason": why})
            continue
        new_status = f"{sm.group('lead')}ratified{sm.group('rest')}"
        plan.edits.append(Edit(path, status_i + 1, "replace", lines[status_i], new_status, "ratify", path, trigger))
        stamp = _stamp(trigger, plan.repo)
        by_i = next((i for i, ln in enumerate(lines) if AMEND_RATIFIED_BY.match(ln)), None)
        if by_i is None:
            plan.edits.append(Edit(path, status_i + 1, "insert", lines[status_i],
                                   f"{sm.group('bullet')}**Ratified by:** {stamp}", "ratify", path, trigger))
        elif not PR_URL.search(AMEND_RATIFIED_BY.match(lines[by_i]).group("value")):
            lead = AMEND_RATIFIED_BY.match(lines[by_i]).group("lead")
            plan.edits.append(Edit(path, by_i + 1, "replace", lines[by_i], f"{lead} {stamp}", "ratify", path,
                                   trigger))
        edit, note = _index_edit(index, AMEND_INDEX, m.group(1), r"^\[{n}\]\(", "proposed", "ratified",
                                 "ratify", path, trigger)
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
        head_end = _header_end(lines)
        header_i: int | None = None          # the header's Status line
        header_status: str | None = None     # the header's status once this plan is applied
        header_anchor: int | None = None     # the header line a Completed line goes after
        for i, line in enumerate(lines):
            sm = ADR_STATUS.match(line)
            if not sm:
                continue
            value = sm.group("value").lower()
            if i < head_end and header_i is None:
                header_i, header_status, header_anchor = i, value, i
                if i + 1 < len(lines) and accepted_rx.match(lines[i + 1]):
                    header_anchor = i + 1
            if value != "proposed":
                continue
            sha = tree.blame(path, i + 1)
            trigger, why = (_resolve_pr(tree, github, sha, plan.default_branch) if sha
                            else (None, f"git blame found no commit for {path}:{i + 1}"))
            why = why or _maintainer_check(trigger, plan.maintainer)
            if why:
                plan.skipped.append({"record": path, "kind": "accept", "line": i + 1, "reason": why})
                continue
            plan.edits.append(Edit(path, i + 1, "replace", line, f"{sm.group('lead')}accepted{sm.group('rest')}",
                                   "accept", path, trigger))
            indent = re.match(r"\s*", line).group(0)
            accepted = f"{indent}- **Accepted in**: {_stamp(trigger, plan.repo)}"
            if i + 1 < len(lines) and accepted_rx.match(lines[i + 1]):
                plan.edits.append(Edit(path, i + 2, "replace", lines[i + 1], accepted, "accept", path, trigger))
            else:
                plan.edits.append(Edit(path, i + 1, "insert", line, accepted, "accept", path, trigger))
            if i == header_i:
                header_status = "accepted"
                edit, note = _index_edit(index, ADR_INDEX, m.group(1), r"^{n}$", "proposed", "accepted",
                                         "accept", path, trigger)
                if edit:
                    plan.edits.append(edit)
                if note:
                    plan.notes.append(note)
        _plan_completion(github, plan, path, lines, head_end, header_status, header_anchor, completed_rx)


def _plan_completion(github: GitHub, plan: Plan, path: str, lines: list[str], head_end: int,
                     header_status: str | None, anchor: int | None, completed_rx: re.Pattern) -> None:
    tracking = next((ADR_TRACKING.match(ln) for ln in lines[:head_end] if ADR_TRACKING.match(ln)), None)
    if not tracking or anchor is None:
        return
    number = int(tracking.group("n"))
    issue = github.issue(number)
    subs = github.sub_issues(number)
    open_subs = sorted(int(s.get("number") or 0) for s in subs if str(s.get("state")) != "closed")
    trigger = {"type": "issue", "number": number, "title": str(issue.get("title") or ""),
               "url": str(issue.get("html_url") or f"https://github.com/{github.repo}/issues/{number}"),
               "state": str(issue.get("state") or ""), "state_reason": str(issue.get("state_reason") or ""),
               "closed_at": str(issue.get("closed_at") or ""),
               "sub_issues": {"total": len(subs), "closed": len(subs) - len(open_subs), "open": open_subs}}
    reason = ""
    if trigger["state"] != "closed":
        reason = f"tracking issue #{number} is open"
    elif trigger["state_reason"] != "completed":
        reason = f"tracking issue #{number} closed as {trigger['state_reason'] or 'unspecified'}, not completed"
    elif open_subs:
        reason = f"tracking issue #{number} is closed but sub-issue(s) {', '.join(f'#{n}' for n in open_subs)} are open"
    elif header_status != "accepted":
        reason = f"tracking issue #{number} is complete but the ADR is {header_status}, not accepted"
    if reason:
        plan.pending.append({"record": path, "issue": number, "reason": reason,
                             "open_sub_issues": open_subs, "url": trigger["url"]})
        return
    indent = re.match(r"\s*", lines[anchor]).group(0)
    completed = f"{indent}- **Completed**: {_date(trigger['closed_at'])} (#{number} closed)"
    existing = next((i for i in range(head_end) if completed_rx.match(lines[i])), None)
    if existing is not None:
        if lines[existing] != completed:
            plan.edits.append(Edit(path, existing + 1, "replace", lines[existing], completed, "complete", path,
                                   trigger))
        return
    plan.edits.append(Edit(path, anchor + 1, "insert", lines[anchor], completed, "complete", path, trigger))


def plan(root: Path, *, ref: str = "HEAD", repo: str | None = None) -> Plan:
    """Every record a maintainer's merge (or a completed tracking issue) has
    decided but that still says otherwise, as of `ref`. Idempotent: once its
    edits are on `ref`, the plan for `ref` is empty."""
    tree = Tree(root, ref)
    fleet_text = tree.read(FLEET)
    fleet = (yaml.safe_load(fleet_text) or {}) if fleet_text else None
    hub = hub_repo(fleet)
    p = Plan(repo=repo or hub, ref=tree.sha, maintainer=hub.split("/", 1)[0])
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
        old, new = e.old.split("|"), e.new.split("|")
        if (e.op != "replace" or len(old) != len(new) or len(old) < 5
                or [c for j, c in enumerate(old) if j != 3] != [c for j, c in enumerate(new) if j != 3]
                or new[3].strip() not in ("ratified", "accepted")):
            return f"{e.path}:{e.line}: an index edit changes only the status cell to ratified or accepted"
        return ""
    if not RECORD_LINE.match(e.new):
        return f"{e.path}:{e.line}: {e.new[:60]!r} is not a Status, Ratified by, Accepted in or Completed line"
    if e.op == "replace" and not (RECORD_LINE.match(e.old) or e.old.strip() == ""):
        return f"{e.path}:{e.line}: replaces {e.old[:60]!r}, which is not a status line"
    return ""


def apply_text(text: str, edits: list[Edit]) -> str:
    """`text` with `edits` applied; every edit's `old` is verified first."""
    lines = text.split("\n")
    replace: dict[int, str] = {}
    after: dict[int, list[str]] = {}
    for e in edits:
        problem = _shape_problem(e)
        if problem:
            raise RatifyError(problem)
        if not 1 <= e.line <= len(lines) or lines[e.line - 1] != e.old:
            got = lines[e.line - 1] if 1 <= e.line <= len(lines) else "<past the end>"
            raise RatifyError(f"{e.path}:{e.line}: expected {e.old!r}, found {got!r} — the plan is stale")
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
    written, so a mismatch anywhere changes nothing."""
    out: dict[Path, str] = {}
    for rel, edits in _by_path(p.edits).items():
        f = root / rel
        if not f.is_file():
            raise RatifyError(f"{rel}: not in the working tree")
        out[f] = apply_text(f.read_text(encoding="utf-8"), edits)
    for f, text in out.items():
        f.write_text(text, encoding="utf-8")
    return sorted(p_.relative_to(root).as_posix() for p_ in out)


def check_diff(root: Path, base: str, head: str = "HEAD", repo: str | None = None) -> tuple[Plan, list[str]]:
    """(the plan as of `base`, problems). No problem means `git diff base head`
    is exactly that plan: the same files, each byte-identical to the plan
    applied to `base`, and nothing else."""
    p = plan(root, ref=base, repo=repo)
    base_tree, head_tree = Tree(root, base), Tree(root, head)
    problems = [msg for e in p.edits for msg in [_shape_problem(e)] if msg]
    res = git(["diff", "--name-status", "--no-renames", base_tree.sha, head_tree.sha], cwd=root)
    if not res.ok:
        return p, [f"could not diff {base}..{head}: {res.err.strip() or 'unknown error'}"]
    changed: dict[str, str] = {}
    for row in res.out.splitlines():
        parts = row.split("\t")
        if len(parts) >= 2:
            changed[parts[-1]] = parts[0]
    planned = _by_path(p.edits)
    for rel, status in sorted(changed.items()):
        if not ALLOWED_PATH.match(rel):
            problems.append(f"{rel}: not a ratification-record file (only docs/amendments/NNNN-*.md, "
                            "docs/amendments/README.md, docs/adr/NNNN-*.md and docs/adr/README.md)")
        elif status != "M":
            problems.append(f"{rel}: {({'A': 'added', 'D': 'deleted'}).get(status[:1], status)} — a "
                            "ratification-record change only modifies existing records")
        elif rel not in planned:
            problems.append(f"{rel}: changed, but the plan as of {base_tree.sha[:7]} has no edit for it")
        else:
            try:
                want = apply_text(base_tree.read(rel) or "", planned[rel])
            except RatifyError as exc:
                problems.append(str(exc))
                continue
            got = head_tree.read(rel) or ""
            if got != want:
                problems.append(_first_difference(rel, want, got))
    for rel in sorted(planned):
        if rel not in changed:
            problems.append(f"{rel}: the plan edits it, but the diff does not")
    return p, problems


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
# the pull request body
# --------------------------------------------------------------------------- #
def _counts(p: Plan) -> dict[str, int]:
    return {"ratified": len(p.records("ratify")),
            "accepted": len({(e.path, e.line) for e in p.edits if e.kind == "accept" and e.op == "replace"
                             and e.path not in INDEX_PATHS and ADR_STATUS.match(e.new)}),
            "completed": len(p.records("complete"))}


def pr_title(p: Plan) -> str:
    parts = [f"{n} {k}" for k, n in _counts(p).items() if n]
    return "chore(jev): record ratification and acceptance" + (f" ({', '.join(parts)})" if parts else "")


def _title_of(root: Path, ref: str, rel: str) -> str:
    text = Tree(root, ref).read(rel) or ""
    m = re.search(r"^#\s+(?:ADR\s+)?\d{4}\s+—\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else rel.rsplit("/", 1)[-1]


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


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
        out += ["### ADRs completed", "", "| Record | Tracking issue | Closed | Sub-issues closed |",
                "| --- | --- | --- | --- |"]
        for e in com:
            t, num = e.trigger, e.path.rsplit("/", 1)[-1][:4]
            out.append(f"| [ADR {num}]({e.path}) {title(e.path)} | [#{t['number']}]({t['url']}) {_cell(t['title'])} | "
                       f"{_date(t['closed_at'])} ({t['state_reason']}) | "
                       f"{t['sub_issues']['closed']} of {t['sub_issues']['total']} |")
        out.append("")
    triggers = {e.trigger["number"]: e.trigger for e in p.edits if e.trigger.get("type") == "pr"}
    follow = [f"- #{n} closed {', '.join(f'#{i}' for i in t['closing_issues'])}"
              for n, t in sorted(triggers.items()) if t.get("closing_issues")]
    follow += [f"- {x['record']}: completes when [#{x['issue']}]({x['url']}) closes as completed with every "
               f"sub-issue closed — {x['reason']}" for x in p.pending]
    if follow:
        out += ["### Closing issues and follow-ups", "", *follow, ""]
    if p.skipped:
        out += ["### Skipped", "", "| Record | Kind | Reason |", "| --- | --- | --- |"]
        out += [f"| {s['record']}{(':' + str(s['line'])) if s.get('line') else ''} | {s['kind']} | "
                f"{_cell(s['reason'])} |" for s in p.skipped]
        out.append("")
    if p.notes:
        out += ["### Notes", "", *[f"- {n}" for n in p.notes], ""]
    out += [
        "### The guard that merges this pull request", "",
        f"The `ratify` job in `.github/workflows/jev-number.yml` merges this pull request itself, and only when "
        f"every check on its head completed as success, skipped or neutral (at least one check); the head is "
        f"unchanged and was cut from the current tip of `{p.default_branch}`; GitHub reports it mergeable; it "
        f"carries none of {', '.join(f'`{h}`' for h in HOLD_LABELS)}; and `python3 -m tools.jev ratify "
        f"check-diff --base origin/{p.default_branch}` passes on the head. Then: `gh pr merge <n> --merge "
        f"--match-head-commit <head sha> --delete-branch` — a merge commit, never squash, `--admin` or "
        f"`--auto`. A failed guard labels it `needs-amr`, says why, and leaves it to the maintainer.", "",
        f"<!-- jev-ratify plan: {p.repo}@{p.ref} -->",
    ]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("action", choices=("plan", "apply", "check-diff", "pr-body"))
    ap.add_argument("--root", default=".", help="the repository checkout (default: .)")
    ap.add_argument("--ref", default="HEAD", help="plan as of this commit (default: HEAD)")
    ap.add_argument("--repo", default=None, help="the GitHub OWNER/NAME (default: _data/fleet.yml hub.repo)")
    ap.add_argument("--plan", dest="plan_file", default=None,
                    help="apply / pr-body: a plan written by `plan --json` (default: plan now)")
    ap.add_argument("--out", default=None, help="plan: also write the JSON plan to this file")
    ap.add_argument("--base", default=None, help="check-diff: the commit the change is cut from")
    ap.add_argument("--head", default="HEAD", help="check-diff: the commit to check (default: HEAD)")
    ap.add_argument("--title", action="store_true", help="pr-body: print the pull request title instead")
    ap.add_argument("--json", action="store_true")


def _load_or_plan(args: argparse.Namespace, root: Path) -> Plan:
    if args.plan_file:
        try:
            return Plan.from_dict(json.loads(Path(args.plan_file).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise RatifyError(f"cannot read the plan {args.plan_file}: {exc}") from exc
    return plan(root, ref=args.ref, repo=args.repo)


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


def main(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.action == "check-diff":
        if not args.base:
            print("jev ratify check-diff: --base is required", file=sys.stderr)
            return 2
        p, problems = check_diff(root, args.base, args.head, args.repo)
        if args.json:
            print(json.dumps({"base": p.ref, "edits": len(p.edits), "problems": problems}, indent=2))
        else:
            for pr in problems:
                print(f"  error: {pr}")
            print(f"check-diff: the diff is exactly the plan ({len(p.edits)} edit(s)) as of {p.ref[:7]}"
                  if not problems else f"check-diff: {len(problems)} problem(s) — not a ratification-record change")
        return 1 if problems else 0
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

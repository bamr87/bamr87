#!/usr/bin/env python3
"""
File: tools/jev/conflicts.py
Description: JEV's first capability — an automated, TIERED pull-request conflict
             triage and resolution engine for the whole fleet. It lists open
             pull requests GitHub reports as CONFLICTING, reproduces each
             conflict with a trial merge in a throwaway clone, classifies it
             deterministically (tools/jev/classify.py), and then spends the
             cheapest thing that can finish the job: nothing at all for
             generated / fragment / union / id-collision conflicts, a cheap
             model for small ones, a strong model for large ones, and a human
             for everything else.
             Every tier resolves by MERGING THE BASE INTO THE HEAD with a merge
             commit — never a rebase, never a force-push — validates the result
             by running the repository's own checks, and discards the attempt if
             anything is left dirty. It never merges a pull request, never uses
             `--admin` and never touches settings. Full doc: docs/JEV.md.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage:
  python3 -m tools.jev conflicts scan    [--repo owner/name] [--json]
  python3 -m tools.jev conflicts triage  --pr owner/repo#123 [--json]
  python3 -m tools.jev conflicts resolve --pr owner/repo#123 [--dry-run]
  python3 -m tools.jev conflicts budget  [--scheduled]
Dependencies: PyYAML, `git`, the `gh` CLI, and the `claude` CLI for tiers 1–2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import classify as cls
from .common import JevConfig, JevError, git, gh, gh_json, hub_repo, load_config, load_fleet, \
    registry_repos, run
from .ledger import Ledger, Resolution, budget_state

PR_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")

#: Validation commands, tried in this order and skipped when the repository
#: does not carry the file each one needs. Discovered rather than configured:
#: a repo that gains a gate gets it enforced here on the next run, and a repo
#: that has none still gets the two universal checks below.
VALIDATORS: tuple[tuple[str, list[str]], ...] = (
    ("tools/check-drift.sh", ["bash", "tools/check-drift.sh"]),
    ("tools/schema_lint.py", ["python3", "tools/schema_lint.py", "check", "."]),
    ("tools/governance_lint.py", ["python3", "tools/governance_lint.py", "check", "."]),
    ("tools/docs_index.py", ["python3", "tools/docs_index.py", "--check"]),
    ("tools/run-all-tests.sh", ["bash", "tools/run-all-tests.sh"]),
)
#: Generators re-run when a tier-0 resolution takes "ours" on a generated file.
#: Each entry is (the file that must exist, the command). A repo without the
#: generator simply does not get that regeneration.
REGENERATORS: tuple[tuple[str, list[str]], ...] = (
    ("tools/gen-specs-data.py", ["python3", "tools/gen-specs-data.py"]),
    ("tools/gen-projects-schema.py", ["python3", "tools/gen-projects-schema.py"]),
    ("tools/gen-catalog.py", ["python3", "tools/gen-catalog.py"]),
    ("tools/governance_lint.py", ["python3", "tools/governance_lint.py", "prd-sync", ".", "--write"]),
    ("tools/docs_index.py", ["python3", "tools/docs_index.py", "--write"]),
)


@dataclass
class PullRequest:
    """The slice of a pull request JEV reasons about."""

    repo: str
    number: int
    title: str = ""
    author: str = ""
    base: str = "main"
    head: str = ""
    head_repo: str = ""
    mergeable: str = "UNKNOWN"
    labels: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def ref(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def same_repo(self) -> bool:
        """A fork's branch is not JEV's to push to, whoever opened the PR."""
        return not self.head_repo or self.head_repo == self.repo


def parse_ref(text: str) -> tuple[str, int]:
    m = PR_REF.match(text.strip())
    if not m:
        raise JevError(f"a pull request is named owner/repo#number, not {text!r}")
    return f"{m.group('owner')}/{m.group('repo')}", int(m.group("number"))


# --------------------------------------------------------------------------- #
# detect
# --------------------------------------------------------------------------- #
def fleet_repos(cfg: JevConfig, fleet: dict | None = None) -> list[str]:
    """Every repo JEV watches: the hub, the registry, and the configured orgs.

    The orgs are listed because the registry is a list of SUBMODULES and the
    fleet is wider than that — a repo in `year-of-ai` or `EissaLab` has the
    same conflicts and the same bots opening them.
    """
    data = fleet if fleet is not None else load_fleet()
    repos = [hub_repo(data), *registry_repos()]
    for org in cfg.orgs:
        try:
            listed = gh_json(["repo", "list", org, "--no-archived", "--limit", "200",
                              "--json", "nameWithOwner"])
        except JevError:
            continue                      # an org we cannot read is not an error here
        repos += [str(r.get("nameWithOwner")) for r in listed if r.get("nameWithOwner")]
    return sorted(dict.fromkeys(r for r in repos if r.count("/") == 1))


def open_prs(repo: str, limit: int = 50) -> list[PullRequest]:
    fields = ("number,title,author,baseRefName,headRefName,headRepositoryOwner,"
              "headRepository,mergeable,labels,url")
    try:
        rows = gh_json(["pr", "list", "--repo", repo, "--state", "open",
                        "--limit", str(limit), "--json", fields])
    except JevError:
        return []                          # private / unreadable repo: not a failure
    out = []
    for row in rows:
        owner = (row.get("headRepositoryOwner") or {}).get("login") or ""
        name = (row.get("headRepository") or {}).get("name") or ""
        out.append(PullRequest(
            repo=repo, number=int(row["number"]), title=str(row.get("title") or ""),
            author=str((row.get("author") or {}).get("login") or ""),
            base=str(row.get("baseRefName") or "main"),
            head=str(row.get("headRefName") or ""),
            head_repo=f"{owner}/{name}" if owner and name else "",
            mergeable=str(row.get("mergeable") or "UNKNOWN"),
            labels=[str(l.get("name")) for l in (row.get("labels") or [])],
            url=str(row.get("url") or "")))
    return out


def scan(cfg: JevConfig, repos: list[str] | None = None) -> list[PullRequest]:
    """Every open pull request GitHub currently reports as CONFLICTING.

    `UNKNOWN` is deliberately NOT included: GitHub computes mergeability lazily,
    so an unknown is a question GitHub has not answered yet, and treating it as
    a conflict would have JEV clone a repository to discover nothing.
    """
    targets = repos if repos is not None else fleet_repos(cfg)
    found: list[PullRequest] = []
    for repo in targets:
        found += [pr for pr in open_prs(repo, cfg.scan_limit) if pr.mergeable == "CONFLICTING"]
    return found


def eligible(cfg: JevConfig, pr: PullRequest) -> tuple[bool, str]:
    """Whether JEV may act on this pull request at all. Refusals are the point.

    JEV pushes a commit to somebody else's branch, so the gate is narrow: the
    branch must live in the same repository (never a fork), the author must be
    the operator or a fleet bot, and a human who has said `jev:needs-human` or
    `agent:hold` keeps it.
    """
    if not pr.same_repo:
        return False, f"the head branch lives in {pr.head_repo}, not {pr.repo} (fork)"
    if cfg.allowed_authors and pr.author not in cfg.allowed_authors:
        return False, f"author {pr.author!r} is not in jev.allowed_authors"
    held = {cfg.needs_human_label, "agent:hold", "human-review"} & set(pr.labels)
    if held:
        return False, f"held by label(s): {', '.join(sorted(held))}"
    return True, "eligible"


# --------------------------------------------------------------------------- #
# the trial merge
# --------------------------------------------------------------------------- #
@dataclass
class Workspace:
    """A throwaway clone with the base merged into the head, conflicts and all."""

    path: Path
    pr: PullRequest
    conflicted: list[cls.ConflictFile] = field(default_factory=list)
    merge_failed: bool = False

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _attribute_kinds(repo_path: Path, paths: list[str]) -> dict[str, str]:
    """Ask git what `.gitattributes` says about each conflicted path.

    The repository's own attributes are authoritative: a file marked
    `merge=jev-regen` is generated BY THAT REPO'S declaration, so JEV does not
    have to carry a list of every generated file in the fleet.
    """
    if not paths:
        return {}
    res = git(["check-attr", "merge", "linguist-generated", "--", *paths], cwd=repo_path)
    out: dict[str, str] = {}
    for line in res.out.splitlines():
        parts = line.rsplit(": ", 2)
        if len(parts) != 3:
            continue
        path, attr, value = parts[0], parts[1], parts[2]
        if attr == "merge" and value == "jev-regen":
            out[path] = cls.GENERATED
        elif attr == "merge" and value == "union":
            out.setdefault(path, cls.UNION)
        elif attr == "linguist-generated" and value in ("true", "set"):
            out.setdefault(path, cls.GENERATED)
    return out


def trial_merge(cfg: JevConfig, pr: PullRequest, workdir: Path | None = None) -> Workspace:
    """Clone, check out the head, merge the base into it, and read the wreckage.

    `--no-commit` is not used: git has to actually write the conflict markers
    for the classifier to count hunks and conflicted lines, and for a model (at
    tier 1 or 2) to have something to resolve in the working tree.
    """
    root = workdir or Path(tempfile.mkdtemp(prefix="jev-"))
    path = root / pr.repo.split("/")[-1]
    clone = gh(["repo", "clone", pr.repo, str(path), "--", "--no-tags", "--quiet"])
    if not clone.ok:
        raise JevError(f"could not clone {pr.repo}: {clone.err.strip()}")
    git(["config", "user.name", "bamr87-bot"], cwd=path)
    git(["config", "user.email", "10567847+bamr87@users.noreply.github.com"], cwd=path)
    for ref in (pr.head, pr.base):
        fetched = git(["fetch", "--quiet", "origin", ref], cwd=path)
        if not fetched.ok:
            raise JevError(f"could not fetch {ref} of {pr.repo}: {fetched.err.strip()}")
    checkout = git(["checkout", "-B", pr.head, f"origin/{pr.head}"], cwd=path)
    if not checkout.ok:
        raise JevError(f"could not check out {pr.head}: {checkout.err.strip()}")

    merged = git(["merge", "--no-ff", f"origin/{pr.base}",
                  "-m", f"Merge branch '{pr.base}' into {pr.head}"], cwd=path)
    ws = Workspace(path=path, pr=pr)
    if merged.ok:
        return ws                           # GitHub was stale; there is nothing to resolve

    status = git(["diff", "--name-only", "--diff-filter=U"], cwd=path)
    paths = [p for p in status.out.splitlines() if p.strip()]
    declared = _attribute_kinds(path, paths)
    for rel in paths:
        f = path / rel
        try:
            text = f.read_text(encoding="utf-8")
            binary = False
        except (UnicodeDecodeError, OSError):
            text, binary = "", True
        hunks, lines = cls.count_conflict_hunks(text)
        kind = declared.get(rel) or cls.kind_of(
            rel, generated=cfg.generated_paths, fragments=cfg.fragment_paths,
            union=cfg.union_paths, binary=binary)
        ws.conflicted.append(cls.ConflictFile(path=rel, hunks=hunks, lines=lines, kind=kind))
    ws.merge_failed = True
    return ws


def id_collision(files: list[cls.ConflictFile]) -> bool:
    """Whether the conflict is two branches claiming the same sequential id.

    This is the class the numbering amendment removes at the source; until
    every repo has adopted fragments it is also the single most common
    deterministic conflict, so tier 0 still has to recognise it.
    """
    return any(f.kind == cls.FRAGMENT for f in files) or any(
        f.path.endswith(("features/features.yml", "CHANGELOG.md")) for f in files)


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def union_resolve(repo_path: Path, rel: str) -> bool:
    """Take BOTH sides of an append-only file, in order, the way `merge=union` does.

    `git checkout --theirs` would be the one-liner and it is wrong: it keeps the
    incoming side and silently drops ours, which on an append-only list means
    losing every row this branch added. The three merge stages are written out
    and handed to `git merge-file --union`, which is the same algorithm git's
    own union driver uses — so a repo that declared the attribute and one that
    only matches `jev.union_paths` get identical results.
    """
    stages = {}
    for stage, name in ((1, "base"), (2, "ours"), (3, "theirs")):
        blob = git(["show", f":{stage}:{rel}"], cwd=repo_path)
        stages[name] = blob.out if blob.ok else ""
    tmp = repo_path / ".git" / "jev-union"
    tmp.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, text in stages.items():
        paths[name] = tmp / name
        paths[name].write_text(text, encoding="utf-8")
    merged = git(["merge-file", "--union", "-p", str(paths["ours"]), str(paths["base"]),
                  str(paths["theirs"])], cwd=repo_path)
    if not merged.ok and not merged.out:
        return False
    (repo_path / rel).write_text(merged.out, encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    return True


def resolve_tier0(ws: Workspace, repo_path: Path | None = None) -> tuple[bool, str]:
    """Deterministic resolution: ours + regenerate, union, or renumber.

    "Ours" is the head branch, because the merge direction is base-INTO-head:
    for a generated file whatever the generator produces next is the real
    answer either way, so taking a side is only about reaching a tree the
    generator can run in. An append-only file is different — both sides are
    the answer — so it goes through `union_resolve` instead.
    """
    path = repo_path or ws.path
    notes: list[str] = []
    for f in ws.conflicted:
        if f.kind == cls.UNION:
            if not union_resolve(path, f.path):
                return False, f"union merge failed for {f.path}"
            notes.append(f"{f.path}: union (both sides)")
        else:
            res = git(["checkout", "--ours", "--", f.path], cwd=path)
            if not res.ok:
                return False, f"ours checkout failed for {f.path}"
            notes.append(f"{f.path}: ours + regenerate")
        git(["add", "--", f.path], cwd=path)

    for marker, argv in REGENERATORS:
        if (path / marker).is_file():
            run(argv, cwd=path, timeout=600)
    if (path / "tools" / "jev" / "number.py").is_file():
        run(["python3", "-m", "tools.jev", "number", "apply"], cwd=path, timeout=600)
    git(["add", "-A"], cwd=path)
    return True, "; ".join(notes)


def claude_argv(model: str, prompt: str, max_usd: float, max_turns: int) -> list[str]:
    """The headless Claude invocation, capped exactly as the fleet requires.

    Every headless call carries `--max-budget-usd` (AGENTS.md; the caps come
    from `_data/fleet.yml` `budget.jev`), and `--output-format json` is what
    makes `total_cost_usd` readable afterwards — a run whose cost cannot be
    read is a run charged to nobody.
    """
    return ["claude", "-p", "--output-format", "json", "--model", model,
            "--max-turns", str(max_turns), "--max-budget-usd", f"{max_usd:g}", prompt]


def _prompt(ws: Workspace, triage: cls.Triage) -> str:
    files = "\n".join(f"- {f.path} ({f.kind}, {f.hunks} hunk(s), {f.lines} conflicted line(s))"
                      for f in ws.conflicted)
    return (
        f"You are resolving a git merge conflict in {ws.pr.repo} pull request "
        f"#{ws.pr.number} ({ws.pr.title!r}).\n"
        f"The working tree at {ws.path} is mid-merge: branch '{ws.pr.base}' has been merged "
        f"into '{ws.pr.head}' and git has left conflict markers.\n\n"
        f"Conflicted files:\n{files}\n\n"
        "Resolve every conflict so that BOTH sides' intent is preserved. Rules:\n"
        "1. Never delete another branch's work to make the conflict go away.\n"
        "2. Never edit a generated file by hand — regenerate it with its generator.\n"
        "3. Do not change anything outside the conflicted files.\n"
        "4. Leave no conflict marker and no stray whitespace error behind.\n"
        "5. Do not commit, do not push, do not merge the pull request. Stage your work "
        "with `git add` and stop.\n\n"
        f"Triage: {triage.reason}")


def resolve_with_model(cfg: JevConfig, ws: Workspace, triage: cls.Triage, tier: str,
                       runner=run) -> tuple[bool, float, str, str]:
    """Hand the conflicted tree to a model. Returns (ok, usd, model, detail).

    The cost is read from the CLI's own JSON (`total_cost_usd`), which is the
    figure the fleet ledger calls `reported`. When the payload cannot be parsed
    the attempt is still charged — at the tier's cap, flagged `estimated` by
    the caller — because an unreadable run is the one most likely to have been
    expensive.
    """
    policy = cfg.tier(tier)
    if not policy.model:
        return False, 0.0, "", f"no model configured for {tier}"
    argv = claude_argv(policy.model, _prompt(ws, triage), policy.max_usd, policy.max_turns)
    res = runner(argv, cwd=ws.path, timeout=1800)
    usd, detail = 0.0, ""
    try:
        payload = json.loads(res.out or "{}")
        usd = float(payload.get("total_cost_usd") or 0.0)
        detail = str(payload.get("subtype") or payload.get("result") or "")[:200]
    except (ValueError, TypeError):
        usd, detail = policy.max_usd, "unparseable CLI output; charged at the tier cap"
    if res.code == 127:
        return False, 0.0, policy.model, "the `claude` CLI is not installed"
    return res.ok, usd, policy.model, detail or ("ok" if res.ok else res.err.strip()[:200])


def validate(repo_path: Path) -> tuple[bool, list[str]]:
    """Prove the resolution before it is pushed. Two universal checks, then the repo's own.

    `git diff --check` and a conflict-marker sweep are not optional extras:
    a model that "resolved" a conflict by leaving `<<<<<<<` in place produces
    a tree that builds in some languages and is wrong in all of them.
    """
    problems: list[str] = []
    tracked = git(["grep", "-l", "-E", r"^(<{7}|={7}|>{7})( |$)", "--", "."], cwd=repo_path)
    if tracked.ok and tracked.out.strip():
        problems.append("conflict markers remain in: " + ", ".join(tracked.out.split()[:10]))
    whitespace = git(["diff", "--check", "HEAD"], cwd=repo_path)
    if whitespace.out.strip():
        problems.append("git diff --check reports whitespace errors")
    staged = git(["diff", "--check", "--cached"], cwd=repo_path)
    if staged.out.strip():
        problems.append("git diff --check --cached reports whitespace errors")
    unresolved = git(["diff", "--name-only", "--diff-filter=U"], cwd=repo_path)
    if unresolved.out.strip():
        problems.append("unmerged paths remain: " + ", ".join(unresolved.out.split()[:10]))
    for marker, argv in VALIDATORS:
        if not (repo_path / marker).is_file():
            continue
        res = run(argv, cwd=repo_path, timeout=1800)
        if not res.ok:
            problems.append(f"{marker} failed: {(res.err or res.out).strip().splitlines()[-1][:160]}"
                            if (res.err or res.out).strip() else f"{marker} failed")
    return not problems, problems


def commit_and_push(ws: Workspace, message: str) -> tuple[bool, str]:
    """Record the merge and push it to the pull request's own branch.

    A merge commit, never a rebase and never `--force`: the pull request's
    history belongs to whoever opened it, and a force-push would discard review
    comments anchored to the commits it replaces.
    """
    git(["add", "-A"], cwd=ws.path)
    committed = git(["commit", "--no-verify", "-m", message], cwd=ws.path)
    if not committed.ok and "nothing to commit" not in (committed.out + committed.err):
        return False, committed.err.strip() or committed.out.strip()
    pushed = git(["push", "origin", f"HEAD:refs/heads/{ws.pr.head}"], cwd=ws.path)
    return pushed.ok, (pushed.err.strip() or "pushed")


def escalate(cfg: JevConfig, pr: PullRequest, triage: cls.Triage, extra: str = "",
             dry_run: bool = False) -> None:
    """Label the pull request for a human and leave the triage report behind."""
    body = (f"### JEV conflict triage\n\n{triage.report()}\n"
            f"{extra}\n\nJEV does not resolve this one. It never merges, never force-pushes and "
            f"never uses `--admin`; a human owns it from here. Remove the "
            f"`{cfg.needs_human_label}` label to let JEV look again.\n")
    if dry_run:
        print(body)
        return
    gh(["pr", "comment", str(pr.number), "--repo", pr.repo, "--body", body])
    gh(["label", "create", cfg.needs_human_label, "--repo", pr.repo, "--color", "B60205",
        "--description", "JEV could not resolve this conflict", "--force"])
    gh(["pr", "edit", str(pr.number), "--repo", pr.repo, "--add-label", cfg.needs_human_label])


# --------------------------------------------------------------------------- #
# the ladder
# --------------------------------------------------------------------------- #
def resolve(cfg: JevConfig, pr: PullRequest, *, dry_run: bool = False, scheduled: bool = False,
            ledger: Ledger | None = None, workdir: Path | None = None) -> Resolution:
    """Triage one pull request and climb the tier ladder until something sticks.

    A tier that fails validation is DISCARDED (`git merge --abort`) rather than
    pushed and fixed later: a half-resolved merge commit on somebody's branch is
    worse than the conflict it replaced, because the conflict is at least
    honest about needing attention.
    """
    led = ledger if ledger is not None else Ledger.load()
    budget = budget_state(cfg, led, scheduled=scheduled)
    ok, why = eligible(cfg, pr)
    if not ok:
        return Resolution(repo=pr.repo, pr=pr.number, tier="none", outcome="skipped",
                          cost_source="no-spend", reason=why)

    ws = trial_merge(cfg, pr, workdir)
    try:
        if not ws.merge_failed:
            return Resolution(repo=pr.repo, pr=pr.number, tier=cls.TIER0, outcome="resolved",
                              cost_source="no-spend",
                              reason="the trial merge was clean — GitHub's mergeable state was stale")
        t1, t2 = cfg.tier(cls.TIER1), cfg.tier(cls.TIER2)
        triage = cls.classify(
            ws.conflicted, attempts=led.attempts(pr.repo, pr.number),
            id_collision=id_collision(ws.conflicted),
            squash_only=False, budget_exhausted=budget.exhausted,
            max_attempts=cfg.max_attempts,
            tier1_max_files=t1.max_files or 3, tier1_max_lines=t1.max_lines or 40,
            tier2_max_files=t2.max_files or 15, tier2_max_lines=t2.max_lines or 400)

        if triage.tier == cls.TIER3:
            escalate(cfg, pr, triage, dry_run=dry_run)
            return Resolution(repo=pr.repo, pr=pr.number, tier=cls.TIER3, outcome="escalated",
                              cost_source="no-spend", files=triage.file_count,
                              lines=triage.line_count, reason=triage.reason)

        ladder = [t for t in (cls.TIER0, cls.TIER1, cls.TIER2)
                  if (cls.TIER0, cls.TIER1, cls.TIER2).index(t)
                  >= (cls.TIER0, cls.TIER1, cls.TIER2).index(triage.tier)]
        spent, model, notes = 0.0, "", []
        for tier in ladder:
            if tier == cls.TIER0:
                done, detail = resolve_tier0(ws)
                cost, used_model = 0.0, ""
            else:
                if not budget.affords(cfg.tier(tier).max_usd):
                    notes.append(f"{tier}: skipped, ${cfg.tier(tier).max_usd:g} would cross the "
                                 f"${budget.ceiling_usd:.2f} ceiling")
                    break
                if dry_run:
                    notes.append(f"{tier}: would run {cfg.tier(tier).model} at "
                                 f"${cfg.tier(tier).max_usd:g}")
                    break
                done, cost, used_model, detail = resolve_with_model(cfg, ws, triage, tier)
                spent += cost
                model = used_model or model
            notes.append(f"{tier}: {detail}")
            if not done:
                git(["checkout", "--", "."], cwd=ws.path)
                continue
            good, problems = validate(ws.path)
            if not good:
                notes.append(f"{tier}: validation failed — {'; '.join(problems)[:300]}")
                git(["merge", "--abort"], cwd=ws.path)
                git(["checkout", "-B", pr.head, f"origin/{pr.head}"], cwd=ws.path)
                git(["merge", "--no-ff", f"origin/{pr.base}",
                     "-m", f"Merge branch '{pr.base}' into {pr.head}"], cwd=ws.path)
                continue
            if dry_run:
                return Resolution(repo=pr.repo, pr=pr.number, tier=tier, outcome="dry-run",
                                  model=model, cost_usd=round(spent, 4),
                                  cost_source="reported" if spent else "no-spend",
                                  files=triage.file_count, lines=triage.line_count,
                                  reason="; ".join(notes)[:400])
            message = (f"merge: resolve conflicts with {pr.base} ({tier})\n\n"
                       f"Resolved by JEV ({tier}) and validated by the repository's own checks.\n"
                       f"{triage.reason}\n")
            pushed, detail = commit_and_push(ws, message)
            outcome = "resolved" if pushed else "failed"
            notes.append(f"push: {detail}")
            res = Resolution(repo=pr.repo, pr=pr.number, tier=tier, outcome=outcome, model=model,
                             cost_usd=round(spent, 4),
                             cost_source="reported" if spent else "no-spend",
                             files=triage.file_count, lines=triage.line_count,
                             reason="; ".join(notes)[:400])
            led.append(res)
            return res

        triage.reason = f"every automated tier failed or was unaffordable: {'; '.join(notes)[:300]}"
        escalate(cfg, pr, triage, dry_run=dry_run)
        res = Resolution(repo=pr.repo, pr=pr.number, tier=cls.TIER3, outcome="escalated",
                         model=model, cost_usd=round(spent, 4),
                         cost_source="reported" if spent else "no-spend",
                         files=triage.file_count, lines=triage.line_count, reason=triage.reason)
        if not dry_run:
            led.append(res)
        return res
    finally:
        if workdir is None:
            ws.cleanup()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("action", choices=("scan", "triage", "resolve", "budget"))
    ap.add_argument("--pr", default="", help="owner/repo#number")
    ap.add_argument("--repo", default="", help="limit a scan to one owner/repo")
    ap.add_argument("--dry-run", action="store_true", help="decide and report, change nothing")
    ap.add_argument("--scheduled", action="store_true",
                    help="this is a cron run: stop at the scheduled share of the monthly cap")
    ap.add_argument("--json", action="store_true")


def _one(cfg: JevConfig, ref: str) -> PullRequest:
    repo, number = parse_ref(ref)
    for pr in open_prs(repo, cfg.scan_limit):
        if pr.number == number:
            return pr
    raise JevError(f"{ref} is not an open pull request")


def main(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.action == "budget":
        print(budget_state(cfg, Ledger.load(), scheduled=args.scheduled).summary())
        return 0
    if not cfg.enabled and args.action == "resolve" and not args.dry_run:
        print("jev.enabled is false in _data/fleet.yml — refusing to write. "
              "Use --dry-run, or switch it on.")
        return 1
    if args.action == "scan":
        prs = scan(cfg, [args.repo] if args.repo else None)
        if args.json:
            print(json.dumps([{"ref": p.ref, "title": p.title, "author": p.author,
                               "url": p.url, "eligible": eligible(cfg, p)[0],
                               "why": eligible(cfg, p)[1]} for p in prs], indent=2))
        else:
            for p in prs:
                ok, why = eligible(cfg, p)
                print(f"{'✓' if ok else '·'} {p.ref:<40} {p.title[:50]:<52} {why}")
            print(f"{len(prs)} conflicting pull request(s)")
        return 0
    if not args.pr:
        print("--pr owner/repo#number is required", flush=True)
        return 2
    pr = _one(cfg, args.pr)
    if args.action == "triage":
        ws = trial_merge(cfg, pr)
        try:
            led = Ledger.load()
            t1, t2 = cfg.tier(cls.TIER1), cfg.tier(cls.TIER2)
            triage = cls.classify(
                ws.conflicted, attempts=led.attempts(pr.repo, pr.number),
                id_collision=id_collision(ws.conflicted),
                budget_exhausted=budget_state(cfg, led, scheduled=args.scheduled).exhausted,
                max_attempts=cfg.max_attempts,
                tier1_max_files=t1.max_files or 3, tier1_max_lines=t1.max_lines or 40,
                tier2_max_files=t2.max_files or 15, tier2_max_lines=t2.max_lines or 400)
            print(json.dumps({"ref": pr.ref, "tier": triage.tier, "reason": triage.reason,
                              "files": [f.__dict__ for f in triage.files]}, indent=2)
                  if args.json else triage.report())
        finally:
            ws.cleanup()
        return 0

    led = Ledger.load()
    res = resolve(cfg, pr, dry_run=args.dry_run, scheduled=args.scheduled, ledger=led)
    if not args.dry_run and os.environ.get("JEV_WRITE_LEDGER", "1") != "0":
        led.save()
    print(json.dumps(res.__dict__, indent=2) if args.json
          else f"{res.repo}#{res.pr}: {res.outcome} at {res.tier} (${res.cost_usd:.2f}) — {res.reason}")
    return 0 if res.outcome in ("resolved", "dry-run", "escalated", "skipped") else 1

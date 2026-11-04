#!/usr/bin/env python3
"""
File: tools/jev/adapters/repo_evolution_evolve.py
Description: The evolution agent's step (repo-evolution.yml, job `evolve`) on
             the JEV loop engine — P3 of #484, step 2 (bamr87/bamr87#488,
             ADR 0002 P3). The deterministic halves stay where CI runs them:
             the planner is `tools/dash-gen targets` (CI's plan job: the
             opted-in submodules, the open-pass dedupe, the cap, one brief per
             target, every row carrying the spec's rendered prompt) and the
             filer is `tools/dash-gen evolve-file` (a complete dry run; its
             --apply is refused until #488's publish step lands). This module
             maps their JSON and holds the loop's local-only decisions: tier-0
             reuse (same HEAD, same brief), the dedupe block on --apply, and
             what a valid dry-run output is — the patch the engine harvested
             from the target clone (`local.harvest: patch`), with the
             lockfiles CI's publish step drops removed, and the agent's final
             message as the draft PR body behind the brief's marker line (CI's
             publish step, step for step: its PARTIAL warning on a budget hit,
             its footer, its branch name and its #220 remote derived from the
             item's nwo). An empty pass is a valid result that files nothing,
             as in CI. It imports nothing from dash-gen (ADR 0002) and has no
             GitHub write path of its own: the engine runs the spec-declared
             publish argv.
Author: bamr87
Created: 2026-11-03
Version: 0.1.0
Usage: registered as `repo_evolution_evolve` in tools/jev/adapters/__init__.py
       REGISTRY; named by tools/jev/steps/repo-evolution/evolve.yml `local.adapter`.
Dependencies: Python 3.12 stdlib, tools/jev/headless.py (the trace reader).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from ..common import JevError, is_bare_name, is_nwo
from ..context import MAX_QUERY_CHARS, ContextRequest
from ..headless import read_events, tool_calls
from . import Adapter, Item, PlanResult, PublishPlan, Tier0, Triage, Verdict
from .common import (DEFAULT_LOCKFILE_PATTERNS, LOCAL_ARTEFACT_RX, diff_sections, last_json as _last_json, leaks_private, lockfile_patterns, lockfile_regex, publishing_commands, result_text as _result_text)

#: the engine's harvest for a `local.harvest: patch` step (spec.PATCH_OUTPUT)
PATCH = "changes.patch"
VALIDATED = "evolve.validated.json"
PATCH_COPY = "evolve.patch"
#: the brief's one per-run line (evolution.render_brief: 'Prepared {now} by `dash-gen targets` …')
PREPARED_RX = re.compile(r"Prepared \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")
#: a repo-evolution marker line (evolution.marker_line; the planner writes it)
MARKER_RX = re.compile(r'<!-- repo-evolution key="([^"]+)" -->')
#: the filer's stderr messages (fleet_evolve_file.NO_DEDUPE / APPLY_REFUSED / NO_CHANGES)
NO_DEDUPE = "filing without the duplicate check"
APPLY_REFUSED = "evolve-file --apply is not implemented"
NO_CHANGES = "the agent made no changes"
DEFAULT_PREFIX = "ai-evolution"
NO_FOCUS = "_No operator focus was given"
FOCUS_SECTION = "## Focus for this run"
NO_SUMMARY = "_The agent left no summary — review the diff._"
BRIEF_MAX_BYTES = 1024 * 1024
#: CI's publish step, verbatim but for the run reference: the warning a budget hit's body carries
PARTIAL_BLOCK = ("> **⛔ This pass hit its `--max-budget-usd` ceiling and was stopped MID-TASK.**\n"
                 "> The diff is PARTIAL by construction and the agent's own verification never ran.\n"
                 "> See the run ({run_ref}) for the spend and `budget.call_sites` in the hub's `_data/fleet.yml` "
                 "for the cap.\n")
FOOTER = ("---\n"
          "Draft opened by the [bamr87/bamr87 repo-evolution loop](https://github.com/bamr87/bamr87/blob/main/docs/"
          "EVOLUTION.md) — {run_ref}; the brief the agent worked from is `{brief}`. Machine-authored: review it as "
          "you would any contribution. Nothing here merges automatically, and no new pass is opened for this "
          "repository while this one is open.\n")


def publish_attempts(events: list[dict]) -> list[str]:
    """Every publishing command the session attempted (the allowlist refuses
    them; CI's publish step owns them): shown to the reviewer, never filed. The
    verb is seen wherever a command segment starts (after `cd pkg &&`, in
    `git -C . commit`, behind an `env GIT_DIR=.git` prefix, after a `|`)."""
    out = []
    for call in tool_calls(events):
        if call["name"] != "Bash":
            continue
        command = str(call["input"].get("command") or "").strip()
        if publishing_commands(command):
            out.append(command[:120])
    return out


def drop_lockfiles(patch: bytes, patterns: Iterable[str] = DEFAULT_LOCKFILE_PATTERNS) -> tuple[bytes, list[str]]:
    """The patch without the file sections CI's publish step would have
    dropped, and the paths dropped. CI drops only UNTRACKED lockfiles (`git
    ls-files --others`, a verify step's leftovers): a tracked lockfile the
    agent modified is committed there, so it stays here too. A section is
    untracked when its header creates the file (`new file mode`, `---
    /dev/null`, as the engine's `git diff --no-index /dev/null …` harvest
    writes). Headers are read by `common.diff_header_paths` (a path with a
    space, or git's quoted form); everything before the first header is kept."""
    text = patch.decode("utf-8", errors="surrogateescape")
    pre, sections = diff_sections(text)
    if not sections:
        return patch, []
    rx = lockfile_regex(patterns)
    kept, dropped = [pre], []
    for path, section, is_new in sections:
        if is_new and rx.search(path):
            dropped.append(path)
        else:
            kept.append(section)
    out = "".join(kept)
    return (out.encode("utf-8", errors="surrogateescape") if dropped else patch), dropped


def focus_query(text: str) -> str:
    """The brief's operator focus, as one code-index query; '' when none was given."""
    if FOCUS_SECTION not in text:
        return ""
    body = text.split(FOCUS_SECTION, 1)[1].split("\n## ", 1)[0]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines or lines[0].startswith(NO_FOCUS):
        return ""
    return " ".join(" ".join(lines).split())[:MAX_QUERY_CHARS].rstrip()


class RepoEvolutionEvolve(Adapter):
    name = "repo_evolution_evolve"
    sources = (".github/scripts/dash-gen/evolution.py", ".github/evolution/",
               ".github/scripts/dash-gen/fleet_evolve_file.py")

    def items(self, ctx, plan: dict) -> PlanResult:
        """One item per planned repository (the clone is the target, as CI's
        checkout is). A row is refused (JevError) unless it names a registry
        name, an owner/repo nwo, a branch, its marker and a brief that is a
        bare file name in the plan directory."""
        items = []
        for r in plan.get("include") or []:
            missing = [k for k in ("name", "nwo", "branch", "marker") if not isinstance(r.get(k), str) or not r.get(k)]
            if missing or not is_nwo(r["nwo"]):
                raise JevError(f"plan row {r.get('name')!r}: needs a name, an owner/repo nwo, a branch and a marker "
                               f"(missing {missing})")
            if not is_bare_name(r.get("brief")):
                raise JevError(f"plan row {r['name']!r}: the brief {r.get('brief')!r} is not a bare file name "
                               "in the plan directory")
            m = MARKER_RX.fullmatch(r["marker"])
            if not m or m.group(1) != r["nwo"]:
                raise JevError(f"plan row {r['name']!r}: the marker {r['marker']!r} is not this repository's "
                               "repo-evolution marker line")
            items.append(Item(key=r["nwo"], name=r["name"], nwo=r["nwo"], branch=r["branch"], row=r,
                              brief=ctx.plan_dir / r["brief"]))
        # a planner-skipped row names the repo (open pass) or the registry entry (dropped): one identity each
        skipped = [{**s, "key": s["nwo"] if is_nwo(s.get("nwo")) else str(s.get("name") or "?")}
                   for s in plan.get("skipped") or []]
        return PlanResult(items=items, skipped=skipped, dropped=list(plan.get("dropped") or []),
                          meta={k: plan.get(k) for k in ("max_parallel", "max_turns", "model", "branch_prefix",
                                                         "label", "marker", "focus", "generated_at")})

    def reuse_key(self, ctx, item: Item, head_sha: str | None) -> str | None:
        if not head_sha or item.brief is None or not item.brief.is_file():
            return None
        brief = PREPARED_RX.sub("Prepared", item.brief.read_text(encoding="utf-8"))
        digest = hashlib.sha256()
        for part in (ctx.spec.template_sha256, head_sha, brief):
            digest.update(part.encode("utf-8") + b"\0")
        return digest.hexdigest()

    def tier0(self, ctx, item: Item, head_sha: str | None) -> Tier0:
        if head_sha == "":   # loop.head_sha: GitHub's 409, an empty repository
            return Tier0("skip", "the repository is empty, nothing to improve")
        return super().tier0(ctx, item, head_sha)

    def classify(self, ctx, item: Item) -> Triage:
        if ctx.opts.apply and item.row.get("dedupe") != "clear":
            return Triage(True, "the plan could not check for an open evolution PR (dedupe "
                                f"{item.row.get('dedupe')!r}): --apply needs a live dedupe — one open pass per repo")
        return Triage(False, "one tier: evolution.model")

    def _branch(self, ctx) -> str:
        """CI: `<prefix>/<yyyymmdd>-<run id>`; locally the run id is the engine's."""
        fleet = getattr(ctx, "fleet", None) or {}
        prefix = str(((fleet.get("evolution") or {}).get("branch_prefix")) or DEFAULT_PREFIX).rstrip("/")
        run = getattr(getattr(ctx, "run", None), "run_id", None) or "local"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"local-{run}").strip("-.")[:60]
        return f"{prefix}/{dt.datetime.now(dt.timezone.utc):%Y%m%d}-{slug}"

    def validate(self, ctx, item: Item, harvested: dict, outcome) -> Verdict:
        """The dry run's output: the engine's patch of the target clone, with
        CI's lockfile drop applied, and the agent's final message as the PR
        body behind the marker line — one validated document the filer reads.
        A budget hit (`on_budget_hit: publish-flagged`) carries CI's PARTIAL
        warning; an empty pass is `kind: none`, valid and filing nothing."""
        h = harvested.get(PATCH)
        if h is None:
            return Verdict(False, [f"the engine harvested no {PATCH} (the spec's local.harvest is not patch?)"])
        if h.dest is None and h.reason != "absent":
            return Verdict(False, [f"{PATCH} refused: {h.reason}"])
        patch = h.dest.read_bytes() if h.dest is not None else b""
        patch, dropped = drop_lockfiles(patch, lockfile_patterns(getattr(ctx, "fleet", None)))
        out_dir = ctx.item_dir(item) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        events = read_events(ctx.item_dir(item) / "trace.jsonl")
        row = item.row
        marker = str(row["marker"])
        flags: list[str] = []
        if dropped:
            flags.append(f"untracked lockfile(s) dropped from the patch, as CI's publish step does: {', '.join(dropped)}")
        attempts = publish_attempts(events)
        if attempts:
            flags.append(f"the agent attempted {len(attempts)} publishing command(s) the allowlist refuses "
                         f"(publishing is the filer's job): {attempts[0]}")
        flagged = str(outcome.get("kind") or "") == "budget_hit"
        run_ref = ctx.run_ref()
        summary = _result_text(events).strip() or NO_SUMMARY
        brief = row.get("brief") or "(the brief)"
        body = marker + "\n\n"
        if flagged:
            body += PARTIAL_BLOCK.format(run_ref=run_ref) + "\n"
            flags.append("budget hit: the body carries CI's PARTIAL warning (on_budget_hit publish-flagged)")
        body += summary + "\n\n" + FOOTER.format(run_ref=run_ref, brief=brief)
        title = f"chore(evolve): AI improvement pass — {dt.datetime.now(dt.timezone.utc):%Y-%m-%d}"
        text = title + "\n" + body + "\n" + patch.decode("utf-8", errors="replace")
        if leaks_private(text, ctx):   # never put this machine's paths in a public tracker
            return Verdict(False, ["the body or the patch carries a local path or the host name — withheld"])
        if LOCAL_ARTEFACT_RX.search(summary):
            flags.append("the body cites a local-runner denial; check the report rests on the repository, not on it")
        changed = bool(patch.strip())
        if not changed:
            flags.append(NO_CHANGES + " — a valid pass, nothing to open (CI: 'No changes — no pull request opened')")
        patch_name = None
        if changed:
            (out_dir / PATCH_COPY).write_bytes(patch)
            patch_name = PATCH_COPY
        doc = {"kind": "pr" if changed else "none", "repo": item.nwo, "key": item.key, "name": item.name,
               "base": item.branch, "marker": marker, "title": title, "body": body,
               "branch": self._branch(ctx) if changed else None, "remote": f"https://github.com/{item.nwo}",
               "patch": patch_name, "flagged": flagged, "source": "result-text", "dropped_lockfiles": dropped}
        validated = out_dir / VALIDATED
        validated.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        # $0: the filer's own structural rules on the copy, offline (no gh call)
        with tempfile.TemporaryDirectory(prefix="jev-evolve-dry-") as tmp:
            dry = ctx.dash_gen(["evolve-file", "--item", str(validated), "--bodies-dir", tmp, "--offline"])
        if not dry.ok:
            return Verdict(False, [f"evolve-file --offline exited {dry.code}: {dry.err.strip()[-300:]}"])
        try:
            res = _last_json(dry.out)
        except ValueError as exc:
            return Verdict(False, [f"evolve-file --offline printed no result: {exc}"])
        if res.get("rejected"):
            return Verdict(False, [f"evolve-file: {r.get('reason')}" for r in res["rejected"]])
        return Verdict(True, flags=flags, publish_file=validated,
                       facts={"kind": doc["kind"], "repo": item.nwo, "base": item.branch, "patch_bytes": len(patch),
                              "flagged": flagged, "dropped_lockfiles": dropped, "publish_attempts": len(attempts),
                              "title": title})

    def publish(self, ctx, item: Item, verdict: Verdict, execute, *, apply: bool = False) -> PublishPlan:
        res = execute()   # the spec's publish argv; with --apply only after the gate (refused by the filer today)
        if not res.ok:
            why = res.err.strip()[-300:]
            blocker = (f"evolve-file --apply is refused in this release (bamr87/bamr87#488): {why}"
                       if APPLY_REFUSED in res.err else f"evolve-file exited {res.code}: {why}")
            return PublishPlan(False, [blocker], [], None)
        try:
            out = _last_json(res.out)
        except ValueError as exc:
            return PublishPlan(False, [f"evolve-file printed no result: {exc}"], [], None)
        blockers = ["dedupe_unavailable"] if NO_DEDUPE in res.err else []
        blockers += [f"rejected: {r.get('reason')}" for r in out.get("rejected") or []]
        blockers += [f"skipped: {s.get('reason')}" for s in out.get("skipped") or []
                     if NO_CHANGES not in str(s.get("reason") or "")]
        rows = [{"title": f.get("title"), "kind": f.get("kind"), "repo": f.get("repo"), "base": f.get("base"),
                 "branch": f.get("branch"), "remote": f.get("remote"), "labels": f.get("labels"),
                 "flagged": f.get("flagged"), "url": f.get("url"), "body_file": f.get("body_file"),
                 "patch_file": f.get("patch_file")} for f in out.get("filed") or []]
        # no `failures`: evolve-file skips only for "no changes" and an open pass, never a failed filing
        return PublishPlan(publishable=bool(rows) and not blockers, blockers=blockers, rows=rows,
                           bodies_dir=ctx.bodies_dir(item, apply=apply))

    def apply_steps(self, ctx, item: Item, plan: PublishPlan) -> list[str] | None:
        """What `--apply` would write for an evolution pass: never an issue —
        a branch pushed to the target and one draft PR (the filer refuses
        `--apply` in this release, so the steps say what the yes would mean)."""
        rows = [r for r in plan.rows if r.get("kind") == "pr"]
        if not rows:
            return ["Nothing: the pass made no changes, so no branch is pushed and no pull request is opened."]
        r = rows[0]
        labels = ", ".join(str(lab) for lab in (r.get("labels") or [])) or "none"
        return [f"Push the validated patch, committed as bamr87-bot, as branch `{r.get('branch')}` to "
                f"`{r.get('remote')}` (the remote derived from the item's nwo, bamr87/bamr87#220; the only push), "
                "after a live recheck (one open evolution PR per repository, the token probe).",
                f"`gh pr create --draft -R {item.nwo}` against `{r.get('base')}` with the body below (marker line "
                f"first) and the labels {labels}; nothing else is written. (`evolve-file --apply` is refused in this "
                "release: bamr87/bamr87#488.)"]

    def context_request(self, ctx, item: Item) -> ContextRequest:
        """The repository and its registry name, plus the operator's focus and
        the category as code-index queries (the brief's own words)."""
        text = ""
        b = item.brief
        try:
            if b is not None and not b.is_symlink() and b.is_file() and b.stat().st_size <= BRIEF_MAX_BYTES:
                text = b.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        queries = [focus_query(text),
                   " ".join(f"{item.name} {item.row.get('category') or ''} README documentation".split())
                   [:MAX_QUERY_CHARS].rstrip()]
        return ContextRequest(item.nwo, item.name, tuple(q for q in queries if q))

    def recheck(self, ctx, item: Item) -> str | None:
        plan = ctx.planner(target=item.name, no_files=True)   # live: one open pass per repo, the cap, the registry
        if any(r.get("nwo") == item.nwo for r in plan.get("include") or []):
            return None
        return next((s.get("reason") for s in (plan.get("skipped") or []) + (plan.get("dropped") or [])
                     if s.get("name") == item.name), "no longer in the plan")


ADAPTER = RepoEvolutionEvolve()

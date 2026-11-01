#!/usr/bin/env python3
"""
File: tools/jev/adapters/repo_scout.py
Description: repo-scout's agent step on the JEV loop engine (#486). The two
             deterministic halves stay where CI runs them — the planner is
             `tools/dash-gen scout`, the filer `tools/dash-gen scout-file` —
             and this module maps their JSON, adding the local-only checks:
             tier-0 reuse (same HEAD, same brief), the dedupe block on
             --apply, the privacy filter (no local path or host name reaches a
             public tracker), the local-runner artefact flags and the context
             pack's code-index queries, read from the brief. It imports
             nothing from dash-gen (ADR 0002) and has no GitHub write path of
             its own: the engine runs the spec-declared publish argv.
Author: bamr87
Created: 2026-10-31
Version: 0.1.0
Usage: registered as `repo_scout` in tools/jev/adapters/__init__.py REGISTRY;
       named by tools/jev/steps/repo-scout/scout.yml `local.adapter`.
Dependencies: Python 3.12 stdlib.
"""
from __future__ import annotations

import hashlib
import json
import re

from ..common import JevError, is_bare_name, is_nwo
from ..context import MAX_QUERIES, MAX_QUERY_CHARS, ContextRequest
from . import Adapter, Item, PlanResult, PublishPlan, Tier0, Triage, Verdict

OUTPUT = ".scout/proposals.json"
#: the brief's one per-run line (repo_scout.render_brief: 'Prepared {now} by `dash-gen scout` …')
PREPARED_RX = re.compile(r"Prepared \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")
#: what a sandboxed, offline shell says when it is refused — flagged for the
#: reviewer, not rejected: a repo about sandboxes may legitimately say it
LOCAL_ARTEFACT_RX = re.compile(r"EAI_AGAIN|ENOTFOUND|Could not resolve host|getaddrinfo|"
                               r"Operation not permitted|sandbox-exec|Network is unreachable")
#: scout-file's per-issue failure (CI's file job greps it to fail the job)
FILE_FAILED = "gh issue create failed"
#: scout-file's stderr when the open issues cannot be listed
NO_DEDUPE = "filing without the duplicate check"
#: scout-file's skip reason for a body --reviewed-bodies withheld (its NOT_REVIEWED)
NOT_REVIEWED = "not in the reviewed preview"
#: The brief lines the context pack's code-index queries come from
#: (dash-gen repo_scout.render_brief and evolution.render_conformance; the
#: adapter tests hold them to the real planner's brief). Each is read only
#: inside its own `## ` section, so no line elsewhere in the brief (an issue
#: title, the goals) can stand in for one.
BRIEF_SECTION_RX = re.compile(r"## (.+?)\s*")
REPOSITORY_SECTION = "Repository (from the registry)"
CONFORMANCE_SECTION = "Conformance gaps (Universal Project Standard)"
FOCUS_SECTION = "Focus for this run"
DESCRIPTION_RX = re.compile(r"- \*\*Description:\*\* (.+)")
CATEGORY_RX = re.compile(r"- \*\*Category:\*\* (.+?) · \*\*Status:\*\* .*? · \*\*Stack:\*\* (.+)")
GAP_RX = re.compile(r"\s*- `([^`]+)` \(([A-Z]+)\) — (.+?)(?: → `[^`]*`)?\s*")
NO_DESCRIPTION = "(no description in the registry)"
NO_FOCUS = "_No operator focus was given"
BRIEF_MAX_BYTES = 1024 * 1024


def _brief_sections(text: str) -> dict[str, list[str]]:
    """`## heading` → its lines, up to the next heading; the first section of a name wins."""
    out: dict[str, list[str]] = {}
    lines: list[str] | None = None
    for line in text.splitlines():
        m = BRIEF_SECTION_RX.fullmatch(line)
        if m:
            lines = None if m.group(1) in out else out.setdefault(m.group(1), [])
        elif lines is not None:
            lines.append(line)
    return out


def _query(text: str) -> str:
    """One line, whitespace folded, clipped to the planes' query bound."""
    return " ".join(text.split())[:MAX_QUERY_CHARS].rstrip()


def brief_queries(text: str) -> list[str]:
    """Up to MAX_QUERIES code-index queries from a scout brief, in order: the
    registry description, the category and stack, then the operator focus —
    or, with no focus, the first conformance gap the brief lists. Each is one
    line of at most MAX_QUERY_CHARS; an empty or missing one is dropped. The
    brief is the engine's own planner file, but its text is still data: it
    only ever becomes a query string."""
    sections = _brief_sections(text)
    repo = sections.get(REPOSITORY_SECTION, [])
    out: list[str] = []
    desc = next((m.group(1) for m in map(DESCRIPTION_RX.fullmatch, repo) if m), "").strip()
    if desc and desc != NO_DESCRIPTION:
        out.append(_query(desc))
    cat = next((m for m in map(CATEGORY_RX.fullmatch, repo) if m), None)
    if cat:
        category, stack = cat.group(1).strip(), cat.group(2).strip()
        out.append(_query(f"{category} project in {stack}" if stack and stack != "unknown" else category))
    focus = " ".join(ln.strip() for ln in sections.get(FOCUS_SECTION, []) if ln.strip())
    if focus and not focus.startswith(NO_FOCUS):
        out.append(_query(focus))
    else:
        gap = next((m for m in map(GAP_RX.fullmatch, sections.get(CONFORMANCE_SECTION, [])) if m), None)
        if gap:
            out.append(_query(f"{gap.group(1)} {gap.group(3)}"))
    kept = []
    for q in out:
        if q and q not in kept:
            kept.append(q)
    return kept[:MAX_QUERIES]


def _last_json(text: str) -> dict:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("no output")
    out = json.loads(lines[-1])
    if not isinstance(out, dict):
        raise ValueError("not a JSON object")
    return out


class RepoScout(Adapter):
    name = "repo_scout"
    sources = (".github/scripts/dash-gen/repo_scout.py", ".github/scout/")

    def items(self, ctx, plan: dict) -> PlanResult:
        """One item per planned repo. A row is refused (JevError) unless it
        names a repo, a branch and a brief that is a bare file name in the plan
        directory — saved plans (`--plan-file`) included — so no row can make
        the engine copy a host file into a clone."""
        items = []
        for r in plan.get("include") or []:
            missing = [k for k in ("nwo", "name", "branch") if not isinstance(r.get(k), str) or not r.get(k)]
            if missing or not is_nwo(r["nwo"]):
                raise JevError(f"plan row {r.get('name')!r}: needs a name, an owner/repo nwo and a branch")
            if not is_bare_name(r.get("brief")):
                raise JevError(f"plan row {r['name']!r}: the brief {r.get('brief')!r} is not a bare file name "
                               "in the plan directory")
            items.append(Item(key=r["nwo"], name=r["name"], nwo=r["nwo"], branch=r["branch"], row=r,
                              brief=ctx.plan_dir / r["brief"]))
        # a planner-skipped row carries its nwo: the attempts log keys it like every other row
        skipped = [{**s, "key": s["nwo"]} if is_nwo(s.get("nwo")) else dict(s) for s in plan.get("skipped") or []]
        return PlanResult(items=items, skipped=skipped,
                          dropped=list(plan.get("dropped") or []),
                          meta={k: plan.get(k) for k in ("day", "eligible", "sample", "cycle_days", "focus")})

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
            return Tier0("skip", "the repository is empty, nothing to read")
        return super().tier0(ctx, item, head_sha)

    def classify(self, ctx, item: Item) -> Triage:
        if ctx.opts.apply and item.row.get("dedupe") != "clear":
            return Triage(True, "the plan could not list open issues (dedupe unavailable): --apply needs a live dedupe")
        return Triage(False, "one tier: scout.model")

    def validate(self, ctx, item: Item, harvested: dict, outcome) -> Verdict:
        h = harvested[OUTPUT]
        validated = ctx.item_dir(item) / "outputs" / "proposals.validated.json"
        validated.parent.mkdir(parents=True, exist_ok=True)
        if h.reason == "absent":   # an agent that found nothing is a valid outcome
            validated.write_text(json.dumps({"proposals": [], "notes": ""}) + "\n", encoding="utf-8")
            return Verdict(True, publish_file=validated, facts={"proposals": 0})
        if h.dest is None:
            return Verdict(False, [f"{OUTPUT} refused: {h.reason}"])
        try:
            data = json.loads(h.dest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Verdict(False, [f"{OUTPUT} is not JSON: {exc}"])
        if isinstance(data, list):
            raw, notes = data, ""
        elif isinstance(data, dict):
            raw, notes = list(data.get("proposals") or []), str(data.get("notes") or "")
        else:
            return Verdict(False, [f"{OUTPUT} is neither a list nor an object"])
        private = [s for s in (str(ctx.home), ctx.hostname, str(ctx.work_root)) if s and len(s) > 3]
        kept, withheld, flags = [], [], []
        for p in raw:
            text = json.dumps(p, ensure_ascii=False)
            if any(s in text for s in private):   # never put this machine's paths in a public tracker
                withheld.append({"title": "proposal withheld", "reason": "carries a local path or the host name"})
                continue
            if LOCAL_ARTEFACT_RX.search(text):
                title = p.get("title", "?") if isinstance(p, dict) else "?"
                flags.append(f"cites a local-runner denial; check it is a repo defect: {str(title)[:80]}")
            kept.append(p)
        validated.write_text(json.dumps({"proposals": kept, "notes": notes}, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        # $0: --offline and no --apply make no gh call — the filer's own
        # structural rules (length, kind, credential shapes), run on the copy
        dry = ctx.dash_gen(["scout-file", "--nwo", item.nwo, "--proposals", str(validated), "--offline"])
        if not dry.ok:
            return Verdict(False, [f"scout-file --offline exited {dry.code}: {dry.err.strip()[-300:]}"])
        try:
            res = _last_json(dry.out)
        except ValueError as exc:
            return Verdict(False, [f"scout-file --offline printed no result: {exc}"])
        return Verdict(True, flags=flags, publish_file=validated,
                       facts={"proposals": len(raw), "would_file": len(res.get("filed") or []),
                              "rejected": list(res.get("rejected") or []) + withheld,
                              "capped_or_duplicate": list(res.get("skipped") or []), "notes": notes[:500]})

    def publish(self, ctx, item: Item, verdict: Verdict, execute, *, apply: bool = False) -> PublishPlan:
        res = execute()   # the spec's publish argv; with --apply only after the gate
        if not res.ok:
            return PublishPlan(False, [f"scout-file exited {res.code}: {res.err.strip()[-300:]}"], [], None)
        try:
            out = _last_json(res.out)
        except ValueError as exc:
            return PublishPlan(False, [f"scout-file printed no result: {exc}"], [], None)
        blockers = ["dedupe_unavailable"] if NO_DEDUPE in res.err else []
        failures = [s.get("title", "?") for s in out.get("skipped") or [] if s.get("reason") == FILE_FAILED]
        withheld = [s for s in out.get("skipped") or [] if str(s.get("reason") or "").startswith(NOT_REVIEWED)]
        if withheld:
            blockers.append(f"withheld {len(withheld)} body(ies) not in the reviewed preview")
        rows = [{"title": f.get("title"), "labels": f.get("labels"), "url": f.get("url"),
                 "body_file": f.get("body_file")} for f in out.get("filed") or []]
        return PublishPlan(publishable=bool(rows) and not blockers, blockers=blockers, rows=rows,
                           bodies_dir=ctx.bodies_dir(item, apply=apply), failures=failures)

    def context_request(self, ctx, item: Item) -> ContextRequest:
        """The repo, its registry name (the lake's and the index's name for it)
        and `brief_queries` from the item's brief in the plan directory — a
        regular file of at most BRIEF_MAX_BYTES, or no queries at all."""
        text = ""
        b = item.brief
        try:
            if b is not None and not b.is_symlink() and b.is_file() and b.stat().st_size <= BRIEF_MAX_BYTES:
                text = b.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        return ContextRequest(item.nwo, item.name, tuple(brief_queries(text)))

    def recheck(self, ctx, item: Item) -> str | None:
        plan = ctx.planner(target=item.name, no_files=True)   # live: issues enabled + backpressure
        if any(r.get("nwo") == item.nwo for r in plan.get("include") or []):
            return None
        return next((s.get("reason") for s in (plan.get("skipped") or []) + (plan.get("dropped") or [])
                     if s.get("name") == item.name), "no longer in the plan")


ADAPTER = RepoScout()

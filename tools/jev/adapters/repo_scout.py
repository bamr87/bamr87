#!/usr/bin/env python3
"""
File: tools/jev/adapters/repo_scout.py
Description: repo-scout's agent step on the JEV loop engine (#486). The two
             deterministic halves stay where CI runs them — the planner is
             `tools/dash-gen scout`, the filer `tools/dash-gen scout-file` —
             and this module maps their JSON, adding the local-only checks:
             tier-0 reuse (same HEAD, same brief), the dedupe block on
             --apply, the privacy filter (no local path or host name reaches a
             public tracker) and the local-runner artefact flags. It imports
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

    def recheck(self, ctx, item: Item) -> str | None:
        plan = ctx.planner(target=item.name, no_files=True)   # live: issues enabled + backpressure
        if any(r.get("nwo") == item.nwo for r in plan.get("include") or []):
            return None
        return next((s.get("reason") for s in (plan.get("skipped") or []) + (plan.get("dropped") or [])
                     if s.get("name") == item.name), "no longer in the plan")


ADAPTER = RepoScout()

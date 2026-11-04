#!/usr/bin/env python3
"""
File: tools/jev/adapters/fleet_pulse_doctor.py
Description: The fleet doctor's agent step (fleet-pulse.yml, job `doctor`) on
             the JEV loop engine — P3 of #484, the first step after scout
             (bamr87/bamr87#488, ADR 0002 P3). The deterministic halves stay
             where CI runs them: the planner is `tools/dash-gen remediate
             --plan-dir` (CI's remediation queue, split into one item per
             candidate with the evidence Step 2 of the prompt reads fetched
             into the brief, because a local attempt's shell has no network)
             and the filer is `tools/dash-gen doctor-file` (a complete dry
             run; its --apply is refused until #488's publish step lands).
             This module maps their JSON and holds the doctor's local-only
             decisions: tier-0 reuse (same HEAD, same brief), the dedupe block
             on --apply, and what a valid dry-run output is — the patch the
             engine harvested from the clone (`local.harvest: patch`) plus the
             filing the agent ATTEMPTED: its `gh pr create` / `gh issue create`
             call, refused by the permission layer and read back from the
             trace, is the title and body CI would have filed, with the MARKER
             line held first (tomorrow's CI run dedupes on it). It imports
             nothing from dash-gen (ADR 0002) and has no GitHub write path of
             its own: the engine runs the spec-declared publish argv.
Author: bamr87
Created: 2026-11-03
Version: 0.1.0
Usage: registered as `fleet_pulse_doctor` in tools/jev/adapters/__init__.py
       REGISTRY; named by tools/jev/steps/fleet-pulse/doctor.yml `local.adapter`.
Dependencies: Python 3.12 stdlib, tools/jev/headless.py (the trace reader).
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import tempfile
from pathlib import Path

from ..common import JevError, is_bare_name, is_nwo
from ..context import MAX_QUERY_CHARS, ContextRequest
from ..headless import read_events, tool_calls
from . import Adapter, Item, PlanResult, PublishPlan, Tier0, Triage, Verdict

#: the engine's harvest for a `local.harvest: patch` step (spec.PATCH_OUTPUT)
PATCH = "changes.patch"
VALIDATED = "doctor.validated.json"
PATCH_COPY = "doctor.patch"
#: the brief's per-run lines: the signal stamps and the evidence capture time
VOLATILE_RX = re.compile(r"^(?:Signals: .*|.*What they printed when the planner ran them .*)\n?", re.M)
#: a doctor marker line (remediation.MARKER_RE's fleet-doctor form; the planner writes it)
MARKER_RX = re.compile(r'<!-- fleet-doctor key="([^"]+)" -->')
#: the prompt's own branch name for a hub fix
BRANCH_RX = re.compile(r"fix/fleet-doctor-[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
#: what a sandboxed, offline shell says when it is refused — flagged for the
#: reviewer, never a reason to reject: the doctor must not diagnose from it
LOCAL_ARTEFACT_RX = re.compile(r"EAI_AGAIN|ENOTFOUND|Could not resolve host|getaddrinfo|"
                               r"Operation not permitted|sandbox-exec|Network is unreachable|"
                               r"has been denied because Claude Code is running in don't ask mode")
#: the filer's stderr messages (fleet_doctor_file.NO_DEDUPE; CI's doctor has no filer)
NO_DEDUPE = "filing without the duplicate check"
APPLY_REFUSED = "doctor-file --apply is not implemented"
BRIEF_MAX_BYTES = 1024 * 1024
RESULT_MAX_CHARS = 20_000


def _last_json(text: str) -> dict:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("no output")
    out = json.loads(lines[-1])
    if not isinstance(out, dict):
        raise ValueError("not a JSON object")
    return out


def _gh_create(command: str) -> dict | None:
    """A `gh pr create …` or `gh issue create …` command line → its intent
    (kind, repo, title, body, draft), or None. The agent's own argv, read as
    gh reads it: `shlex` splits it, `-R`/`--repo` names the repository,
    `--title`/`-t` and `--body`/`-b` carry the text (`--body-file` is not
    followed: a file the agent wrote is not in the harvest)."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    while argv and argv[0] == "env":   # `env GH_TOKEN=… gh …`
        argv = argv[1:]
    while argv and "=" in argv[0] and not argv[0].startswith("-"):   # `GH_TOKEN=… gh …`: the assignments
        argv = argv[1:]
    if len(argv) < 3 or argv[0] != "gh" or argv[1] not in ("pr", "issue") or argv[2] != "create":
        return None
    intent = {"kind": argv[1], "repo": None, "title": "", "body": "", "draft": False}
    i = 3
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if a in ("-R", "--repo"):
            intent["repo"], i = nxt, i + 2
        elif a.startswith("--repo="):
            intent["repo"], i = a.split("=", 1)[1], i + 1
        elif a in ("-t", "--title"):
            intent["title"], i = nxt, i + 2
        elif a.startswith("--title="):
            intent["title"], i = a.split("=", 1)[1], i + 1
        elif a in ("-b", "--body"):
            intent["body"], i = nxt, i + 2
        elif a.startswith("--body="):
            intent["body"], i = a.split("=", 1)[1], i + 1
        elif a in ("-d", "--draft"):
            intent["draft"], i = True, i + 1
        elif a in ("-l", "--label", "-B", "--base", "-H", "--head", "-a", "--assignee", "-F", "--body-file"):
            i += 2
        else:
            i += 1
    return intent


def filing_intents(events: list[dict]) -> tuple[list[dict], str | None]:
    """Every `gh … create` the session attempted (in order) and the branch it
    checked out, read from the trace. A refused call still names what the
    agent meant to file — that is the dry run's body."""
    intents: list[dict] = []
    branch: str | None = None
    for call in tool_calls(events):
        if call["name"] != "Bash":
            continue
        command = str(call["input"].get("command") or "")
        m = BRANCH_RX.search(command) if "checkout" in command and " -b " in command else None
        if m:
            branch = m.group(0)
        intent = _gh_create(command)
        if intent and (intent["title"] or intent["body"]):
            intents.append(intent)
    return intents, branch


def _result_text(events: list[dict]) -> str:
    """The session's final `result` text (ai-run's trace is redacted), clipped."""
    for e in reversed(events):
        if e.get("type") == "result":
            return str(e.get("result") or "")[:RESULT_MAX_CHARS]
    return ""


class FleetPulseDoctor(Adapter):
    name = "fleet_pulse_doctor"
    sources = (".github/scripts/dash-gen/remediation.py", ".github/scripts/dash-gen/fleet_doctor_file.py")

    def items(self, ctx, plan: dict) -> PlanResult:
        """One item per candidate. The clone is the HUB for every item (the
        row's `nwo`, as CI's doctor works in the hub checkout); the candidate's
        own repository is the row's `repo`. A row is refused (JevError) unless
        it names its key, the hub, a branch, the candidate repo and a brief
        that is a bare file name in the plan directory."""
        items = []
        for r in plan.get("include") or []:
            missing = [k for k in ("key", "name", "nwo", "branch", "repo", "path", "marker", "where")
                       if not isinstance(r.get(k), str) or not r.get(k)]
            if missing or not is_nwo(r["nwo"]) or not is_nwo(r["repo"]):
                raise JevError(f"plan row {r.get('name')!r}: needs key, name, an owner/repo nwo (the hub), a branch, "
                               f"the candidate repo, path, marker and where (missing {missing})")
            if not is_bare_name(r.get("brief")):
                raise JevError(f"plan row {r['name']!r}: the brief {r.get('brief')!r} is not a bare file name "
                               "in the plan directory")
            if r["where"] not in ("hub", "submodule"):
                raise JevError(f"plan row {r['name']!r}: where is hub or submodule, not {r['where']!r}")
            items.append(Item(key=r["key"], name=r["name"], nwo=r["nwo"], branch=r["branch"], row=r,
                              brief=ctx.plan_dir / r["brief"]))
        skipped = [dict(s) for s in plan.get("skipped") or []]   # the planner's rows carry `key` already
        return PlanResult(items=items, skipped=skipped, dropped=list(plan.get("dropped") or []),
                          meta={k: plan.get(k) for k in ("total", "max_candidates", "max_cross_repo", "target",
                                                         "offline")})

    def reuse_key(self, ctx, item: Item, head_sha: str | None) -> str | None:
        if not head_sha or item.brief is None or not item.brief.is_file():
            return None
        brief = VOLATILE_RX.sub("", item.brief.read_text(encoding="utf-8"))
        digest = hashlib.sha256()
        for part in (ctx.spec.template_sha256, head_sha, brief):
            digest.update(part.encode("utf-8") + b"\0")
        return digest.hexdigest()

    def tier0(self, ctx, item: Item, head_sha: str | None) -> Tier0:
        if head_sha == "":
            return Tier0("skip", "the hub repository read as empty, nothing to clone")
        return super().tier0(ctx, item, head_sha)

    def classify(self, ctx, item: Item) -> Triage:
        if ctx.opts.apply and item.row.get("dedupe") != "clear":
            return Triage(True, "the plan could not list open issues and PRs (dedupe unavailable): --apply needs "
                                "a live dedupe")
        return Triage(False, "one tier: remediation.model")

    def validate(self, ctx, item: Item, harvested: dict, outcome) -> Verdict:
        """The dry run's output: the engine's patch of the clone and the filing
        the agent attempted, as one validated document the filer reads."""
        h = harvested.get(PATCH)
        if h is None:
            return Verdict(False, [f"the engine harvested no {PATCH} (the spec's local.harvest is not patch?)"])
        if h.dest is None and h.reason != "absent":
            return Verdict(False, [f"{PATCH} refused: {h.reason}"])
        patch = h.dest.read_bytes() if h.dest is not None else b""
        out_dir = ctx.item_dir(item) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        events = read_events(ctx.item_dir(item) / "trace.jsonl")
        intents, branch = filing_intents(events)
        row = item.row
        marker = str(row["marker"])
        private = [s for s in (str(ctx.home), ctx.hostname, str(ctx.work_root)) if s and len(s) > 3]
        flags: list[str] = []
        # the filing: what the agent asked gh for, else what a hub fix with no call becomes
        intent = next((i for i in intents if i["kind"] == "pr"), None) or next(iter(intents), None)
        source = "gh-call"
        if intent is None:
            if not patch.strip():
                return Verdict(False, ["the agent left neither a fix (an empty patch) nor a filing (no `gh pr create` "
                                       "or `gh issue create` in the session)"])
            if row["where"] != "hub":
                return Verdict(False, ["the agent edited the hub checkout for a submodule candidate and filed nothing "
                                       "— a submodule fix belongs in its own repository (Step 3b), or an issue (3c)"])
            source = "result-text"
            intent = {"kind": "pr", "repo": item.nwo, "title": f"fix(ci): fleet doctor — {row['repo']}/{row['workflow']}",
                      "body": marker + "\n\n" + (_result_text(events) or "(the session left no summary)")}
            flags.append("no `gh pr create` in the session: the title and body are synthesised from the result text")
        kind = intent["kind"]
        repo = intent.get("repo") or (item.nwo if kind == "pr" or row["where"] == "hub" else item.nwo)
        if kind == "pr" and not patch.strip():
            return Verdict(False, ["the agent asked for a PR but the clone carries no edits (an empty patch)"])
        if kind == "pr" and row["where"] == "submodule" and repo == item.nwo:
            # Step 3b would have cloned the submodule; offline it could not, and a hub PR for a submodule file is wrong
            return Verdict(False, [f"a PR for the submodule candidate {row['repo']} was aimed at the hub"])
        body = str(intent.get("body") or "")
        if body.splitlines()[:1] != [marker]:
            flags.append("the MARKER line was not the body's first line: prepended (CI dedupes on it)")
            body = marker + "\n\n" + body.lstrip("\n")
        title = " ".join(str(intent.get("title") or "").split())[:200] or f"fleet doctor — {row['repo']}/{row['workflow']}"
        text = title + "\n" + body + "\n" + patch.decode("utf-8", errors="replace")
        if any(s in text for s in private):   # never put this machine's paths in a public tracker
            return Verdict(False, ["the filing or the patch carries a local path or the host name — withheld"])
        if LOCAL_ARTEFACT_RX.search(body):
            flags.append("the body cites a local-runner denial; check the diagnosis rests on the brief's evidence")
        if any(i["kind"] != kind for i in intents):
            flags.append(f"the session attempted {len(intents)} filings; the first {kind} is kept")
        patch_name = None
        if patch.strip():
            (out_dir / PATCH_COPY).write_bytes(patch)
            patch_name = PATCH_COPY
        elif kind == "pr":
            return Verdict(False, ["a pr needs a patch"])
        doc = {"kind": kind, "repo": repo, "where": row["where"], "key": item.key, "marker": marker,
               "workflow": row["workflow"], "path": row["path"], "title": title, "body": body,
               "branch": branch if kind == "pr" else None, "patch": patch_name, "source": source,
               "signals": list(row.get("signals") or [])}
        if kind == "pr" and not doc["branch"]:
            doc["branch"] = "fix/fleet-doctor-" + re.sub(r"[^a-z0-9]+", "-", row["name"].lower()).strip("-")[:60]
            flags.append("no `git checkout -b` in the session: the branch name is derived from the item")
        validated = out_dir / VALIDATED
        validated.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        # $0: the filer's own structural rules on the copy, offline (no gh call)
        with tempfile.TemporaryDirectory(prefix="jev-doctor-dry-") as tmp:
            dry = ctx.dash_gen(["doctor-file", "--item", str(validated), "--bodies-dir", tmp, "--offline"])
        if not dry.ok:
            return Verdict(False, [f"doctor-file --offline exited {dry.code}: {dry.err.strip()[-300:]}"])
        try:
            res = _last_json(dry.out)
        except ValueError as exc:
            return Verdict(False, [f"doctor-file --offline printed no result: {exc}"])
        if res.get("rejected"):
            return Verdict(False, [f"doctor-file: {r.get('reason')}" for r in res["rejected"]])
        return Verdict(True, flags=flags, publish_file=validated,
                       facts={"kind": kind, "repo": repo, "where": row["where"], "patch_bytes": len(patch),
                              "filings_attempted": len(intents), "source": source, "title": title})

    def publish(self, ctx, item: Item, verdict: Verdict, execute, *, apply: bool = False) -> PublishPlan:
        res = execute()   # the spec's publish argv; with --apply only after the gate (refused by the filer today)
        if not res.ok:
            why = res.err.strip()[-300:]
            blocker = (f"doctor-file --apply is refused in this release (bamr87/bamr87#488): {why}"
                       if APPLY_REFUSED in res.err else f"doctor-file exited {res.code}: {why}")
            return PublishPlan(False, [blocker], [], None)
        try:
            out = _last_json(res.out)
        except ValueError as exc:
            return PublishPlan(False, [f"doctor-file printed no result: {exc}"], [], None)
        blockers = ["dedupe_unavailable"] if NO_DEDUPE in res.err else []
        blockers += [f"rejected: {r.get('reason')}" for r in out.get("rejected") or []]
        rows = [{"title": f.get("title"), "kind": f.get("kind"), "repo": f.get("repo"), "labels": f.get("labels"),
                 "url": f.get("url"), "body_file": f.get("body_file"), "patch_file": f.get("patch_file"),
                 "branch": f.get("branch")} for f in out.get("filed") or []]
        return PublishPlan(publishable=bool(rows) and not blockers, blockers=blockers, rows=rows,
                           bodies_dir=ctx.bodies_dir(item, apply=apply),
                           failures=[s.get("title", "?") for s in out.get("skipped") or []
                                     if "failed" in str(s.get("reason") or "")])

    def context_request(self, ctx, item: Item) -> ContextRequest:
        """The hub and its checkout name, plus the candidate as code-index
        queries: the workflow path with its signals, then the workflow name."""
        row = item.row
        signals = " ".join(str(s) for s in row.get("signals") or [])
        queries = [" ".join(f"{row.get('path')} {signals}".split())[:MAX_QUERY_CHARS].rstrip(),
                   " ".join(f"{row.get('repo')} {row.get('workflow')} workflow".split())[:MAX_QUERY_CHARS].rstrip()]
        return ContextRequest(item.nwo, item.nwo.split("/", 1)[1], tuple(q for q in queries if q))

    def recheck(self, ctx, item: Item) -> str | None:
        plan = ctx.planner(target=item.key, no_files=True)   # live: dedupe against today's open markers
        if any(r.get("key") == item.key for r in plan.get("include") or []):
            return None
        return next((s.get("reason") for s in plan.get("skipped") or [] if s.get("key") == item.key),
                    "no longer in the queue")


ADAPTER = FleetPulseDoctor()

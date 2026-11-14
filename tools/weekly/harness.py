#!/usr/bin/env python3
# ============================================================================
# File:          tools/weekly/harness.py
# Description:   The two halves of the weekend (docs/WEEKLY.md, constitution § 26, § 28).
#                Claude Code executes: `review` runs ONE capped, sandboxed, read-only session over
#                the close-out's stale set and returns validated proposals, through the reflector's
#                session runner (tools/jev/reflect.py: `dash-gen ai-run --isolate`, the budget lock,
#                budget.loops, the AI ledger). Grok bots direct: `grok_brief` renders the standing
#                brief a Grok bot runs for a stage, and `direction` reads back the week's direction
#                issue, which is the only thing the two halves pass to each other.
# Usage:         imported by tools/weekly/cli.py
# Never:         acts on a proposal (nothing in the routine does: a proposal is a line in a report),
#                reads a session's output after a posture breach, spends past weekly.agent.usd or
#                budget.loops, or writes to GitHub.
# ============================================================================
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from tools.weekly import core

BRIEFS = Path(__file__).resolve().parent / "briefs"
PROPOSALS_SCHEMA = "weekly-agent/v1"
ACTIONS = ("close", "carry", "decide")
LOOP, STEP, SOURCE = "weekly", "close-out", "tools/dash weekly close"
TOOLS = ("Read", "Glob", "Grep")
STAGES = ("close", "prepare", "plan")
COST_LABEL = "API-equivalent (estimate)"

DEFAULTS: dict = {
    "enabled": True,
    # Kept equal to harness_refinement.model / max_turns on purpose: the session's posture (model,
    # turns, tool grant) is then the reflector's, so `tools/dash refine reflect doctor --live --yes`
    # arms both. A different value needs its own probe and canary, and the host check refuses until
    # it has one.
    "model": "claude-sonnet-5-5",
    "max_turns": 40,
    "usd": 2,
    "timeout_minutes": 15,
    "max_items": 60,
    "context_items": 400,
    "reason_chars": 240,
}
GROK_DEFAULTS: dict = {
    "issue_repo": "bamr87/bamr87",
    # The week's one issue. The same title the console's weekly lanes comment on (PR #841),
    # so the local routine, the CI lanes and the Grok bots meet in one place, each under its own heading.
    "issue_title": "Week {week} — close-out and plan",
    "issue_label": "weekly-closeout",
    "handoff_label": "executor:claude-code",
    # Whose words on the issue count as direction. The issue is public, so anyone can comment on it:
    # only the repo's owner, a login listed here (a Grok bot's account), or a comment GitHub marks as
    # written by an owner, member or collaborator is read.
    "authors": [],
}
TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
#: What a reason may not contain: a mention, markup, or a character that is not printable text. A
#: reason can end up in a comment under the maintainer's name, where `@claude` starts an agent run.
UNSAFE_REASON = re.compile(r"[@<>`\x00-\x1f\x7f\u2028\u2029\ud800-\udfff]|!\[")
#: What no text from the model may carry into a report, a file or a terminal: control characters
#: (an escape sequence repaints a terminal) and lone surrogates (they cannot be written as UTF-8).
UNPRINTABLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029\ud800-\udfff]")
SECTIONS = (("friday", "## Friday: direction close-out"), ("saturday", "## Saturday: direction for the week"),
            ("sunday", "## Sunday: plan sign-off"))


def agent_config(fleet: dict) -> dict:
    return core.merged(DEFAULTS, (fleet.get("weekly") or {}).get("agent"))


def grok_config(fleet: dict) -> dict:
    return core.merged(GROK_DEFAULTS, (fleet.get("weekly") or {}).get("grok"))


def fill(template: str, values: dict[str, Any]) -> str:
    """One pass over `{{TOKEN}}`s. An unknown token is an error, so a reworded brief cannot ship a hole."""
    def sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"the brief names {{{{{key}}}}}, which nothing fills")
        return str(values[key])
    return re.sub(r"\{\{([A-Z][A-Z0-9_]*)\}\}", sub, template)


# ---- the Grok half ------------------------------------------------------------------------------

def grok_brief(stage: str, week: str, fleet: dict) -> str:
    """The standing brief a Grok bot runs for one stage, with the week and the handoff label filled in."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    cfg = grok_config(fleet)
    return fill((BRIEFS / f"grok-{stage}.md").read_text(encoding="utf-8"),
                {"WEEK": week, "HANDOFF_LABEL": cfg["handoff_label"], "ISSUE_TITLE": cfg["issue_title"].format(week=week),
                 "ISSUE_LABEL": cfg["issue_label"], "ISSUE_REPO": cfg["issue_repo"]})


def direction(week: str, fleet: dict, runner: Callable = core.run) -> dict:
    """What the Grok half has written for the week: the direction issue, which sections it carries and
    the handoff issues it links. Reads only; a missing issue is an answer, not an error."""
    cfg = grok_config(fleet)
    title = cfg["issue_title"].format(week=week)
    out: dict = {"title": title, "found": False, "url": None, "sections": [], "handoffs": [], "error": None}
    listed = runner(["gh", "issue", "list", "--repo", cfg["issue_repo"], "--state", "open", "--search",
                     f'"{title}" in:title', "--json", "number,title,url,author", "--limit", "20"], timeout=60)
    if listed.returncode != 0:
        return {**out, "error": (listed.stderr or "gh issue list failed").strip()[:160]}
    try:
        rows = [i for i in json.loads(listed.stdout or "[]") if isinstance(i, dict) and i.get("title") == title]
    except json.JSONDecodeError:
        return {**out, "error": "the issue list could not be parsed"}
    allowed = {str(cfg["issue_repo"]).split("/")[0].lower(), *[str(a).lower() for a in cfg["authors"] or []]}
    # Anyone can open an issue with this title. One a trusted login opened wins; otherwise the oldest,
    # whose body is then not read (only trusted comments on it are).
    rows.sort(key=lambda i: (str((i.get("author") or {}).get("login") or "").lower() not in allowed, i.get("number") or 0))
    match = rows[0] if rows else None
    if not match:
        return out
    view = runner(["gh", "issue", "view", str(match["number"]), "--repo", cfg["issue_repo"], "--json", "author,body,comments"], timeout=60)
    try:
        doc = json.loads(view.stdout) if view.returncode == 0 else {}
    except json.JSONDecodeError:
        doc = {}
    doc = doc if isinstance(doc, dict) else {}

    def trusted(author: Any, association: Any = None) -> bool:
        login = str((author or {}).get("login") or "").lower() if isinstance(author, dict) else ""
        return bool(login) and (login in allowed or str(association or "").upper() in TRUSTED_ASSOCIATIONS)

    blocks, ignored = [], 0

    def text_of(body: Any) -> str:
        return str(body or "").replace("\r\n", "\n").replace("\r", "\n")  # the web editor stores CRLF

    if trusted(doc.get("author")):
        blocks.append(text_of(doc.get("body")))
    for c in doc.get("comments") or []:
        if isinstance(c, dict) and trusted(c.get("author"), c.get("authorAssociation")):
            blocks.append(text_of(c.get("body")))
        else:
            ignored += 1
    sections = [name for name, heading in SECTIONS if any(_section(b, heading) is not None for b in blocks)]
    # Handoffs are what Saturday's section links, and nothing else on the issue: the console's own
    # lanes comment here too, and a pull request they mention is not a handoff.
    refs = set()
    for block in blocks:
        part = _section(block, SECTIONS[1][1])
        if part is None:
            continue
        for owner_repo, number in re.findall(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(\d+)", part):
            refs.add(f"{owner_repo}#{number}")
        for owner_repo, number in re.findall(r"(?<![\w/])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)", part):
            refs.add(f"{owner_repo}#{number}")
    refs.discard(f"{cfg['issue_repo']}#{match['number']}")
    return {**out, "found": True, "url": match.get("url"), "number": match["number"], "sections": sections,
            "handoffs": sorted(refs), "ignored_comments": ignored}


def _section(text: str, heading: str) -> str | None:
    """The part of a comment under one `## ` heading, up to the next one; None when it is not there."""
    found = re.search(r"(?mi)^" + re.escape(heading) + r"[ \t]*$", text)
    if not found:
        return None
    rest = text[found.end():]
    nxt = re.search(r"(?m)^## ", rest)
    return rest[: nxt.start()] if nxt else rest


# ---- the Claude half: one capped session over the stale set -------------------------------------

def build_brief(result: dict, week: str, cfg: dict) -> dict:
    """The session's whole evidence: the stale rows to rule on, and every other open item as context."""
    public = [r for r in result["rows"] if not r.get("private")]  # a private title must not come back in a public reason
    stale = [r for r in public if r["disposition"] == "stale"][: int(cfg["max_items"])]
    keys = {r["key"] for r in stale}
    keep = ("key", "type", "repo", "number", "title", "author", "labels", "age_days", "idle_days", "why",
            "draft", "checks", "merge_state")
    context = [{"key": r["key"], "title": r["title"], "disposition": r["disposition"]}
               for r in public if r["key"] not in keys][: int(cfg["context_items"])]
    return {"week": week, "stale": [{k: r[k] for k in keep if k in r} for r in stale], "open": context,
            "limits": {"max_items": int(cfg["max_items"]), "reason_chars": int(cfg["reason_chars"])}}


def parse_final(text: str) -> tuple[dict | None, str]:
    """The session's final message → its proposals document, or None and why."""
    s = (text or "").strip()
    if not s:
        return None, "the final message is empty"
    if len(s) > 200_000:
        return None, "the final message is too long"
    fenced = re.findall(r"```(?:json)?[ \t]*\n(.*?)\n[ \t]*```", s, re.S)
    if fenced:
        s = fenced[-1]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        return None, "no JSON object in the final message"
    try:
        doc = json.loads(s[start:end + 1])
    except ValueError as exc:
        return None, f"the final message's JSON does not parse ({exc})"
    if not isinstance(doc, dict) or not isinstance(doc.get("proposals"), list):
        return None, "the document has no `proposals` list"
    return doc, ""


def validate(doc: dict, brief: dict, cfg: dict) -> dict:
    """The engine's check on every proposal. The session read titles written by anyone, so nothing it
    says is trusted: a key outside the stale set, an unknown action or a reason that is not one short
    line is dropped, and the count of what was dropped is reported."""
    stale = {r["key"] for r in brief["stale"]}
    known = stale | {r["key"] for r in brief["open"]}
    limit, accepted, dropped, seen = int(cfg["reason_chars"]), [], [], set()
    for raw in doc.get("proposals") or []:
        if not isinstance(raw, dict):
            dropped.append({"key": None, "why": "not an object"})
            continue
        key, action, reason = raw.get("key"), raw.get("action"), raw.get("reason")
        if not isinstance(key, str) or key not in stale:
            dropped.append({"key": UNPRINTABLE.sub("?", str(key))[:80], "why": "not a key in the stale set"})
        elif key in seen:
            dropped.append({"key": key, "why": "a second proposal for the same item"})
        elif not isinstance(action, str) or action not in ACTIONS:
            dropped.append({"key": key, "why": f"action {ascii(str(action)[:20])} is not one of {', '.join(ACTIONS)}"})
        elif not isinstance(reason, str) or not reason.strip() or "\n" in reason.strip():
            dropped.append({"key": key, "why": "the reason is not one line"})
        elif UNSAFE_REASON.search(reason):
            dropped.append({"key": key, "why": "the reason holds a mention, markup or a control character"})
        elif len(accepted) >= int(cfg["max_items"]):
            dropped.append({"key": key, "why": "past the cap"})
        else:
            seen.add(key)
            row = {"key": key, "action": action, "reason": core.redact(reason.strip())[:limit]}
            by = raw.get("superseded_by")
            if isinstance(by, str) and by in known and by != key:
                row["superseded_by"] = by
            accepted.append(row)
    notes = doc.get("notes")
    notes = core.redact(" ".join(UNPRINTABLE.sub(" ", notes).split()))[:1000] if isinstance(notes, str) else ""
    return {"schema": PROPOSALS_SCHEMA, "accepted": accepted, "dropped": dropped,
            "notes": "" if UNSAFE_REASON.search(notes) else notes}


def review(folder: Path, result: dict, week: str, run_id: str, fleet: dict, *, scheduled: bool,
           claude_bin: str = "claude", session: Callable | None = None) -> dict:
    """Run the close-out agent, or say why it did not run. Every refusal is a status, never an error:
    the rules' dispositions stand on their own, and a week without the agent is a longer stale list.
    `session` replaces the real one in tests."""
    cfg = agent_config(fleet)
    status: dict = {"status": "skipped", "why": "", "cap_usd": float(cfg["usd"]), "model": cfg["model"],
                    "label": COST_LABEL, "accepted": [], "dropped": [], "notes": ""}
    if not cfg["enabled"]:
        return {**status, "why": "weekly.agent.enabled is false"}
    brief = build_brief(result, week, cfg)
    if not brief["stale"]:
        return {**status, "why": "nothing is stale"}
    # A scheduled close can run again in the same weekend (a later slot makes up a run that failed).
    # The session it already paid for is not bought twice: its answer is kept beside the run folders
    # and checked again against today's stale set.
    spent = folder.parent / f".agent-{week}.json"
    if scheduled and spent.exists():
        try:
            earlier = json.loads(spent.read_text())
            verdict = validate(earlier["document"], brief, cfg)
            return {**status, **{k: verdict[k] for k in ("accepted", "dropped", "notes")}, "status": "ok",
                    "cost_usd": 0.0, "why": f"kept from {earlier.get('run_id')}, which already spent this week's session: "
                                            f"{len(verdict['accepted'])} proposal(s) still apply"}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {**status, "why": f"this week's session already ran and its answer could not be read ({spent.name})"}
    record = folder / "agent"
    evidence = record / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    record.chmod(0o700)
    (evidence / "brief.json").write_text(json.dumps(brief, indent=1) + "\n", encoding="utf-8")
    template = (BRIEFS / "claude-close.prompt.txt").read_text(encoding="utf-8")
    (evidence / "MISSION.md").write_text(fill(template, {"STALE": len(brief["stale"]), "MAX_ITEMS": brief["limits"]["max_items"],
                                                         "REASON_CHARS": brief["limits"]["reason_chars"]}), encoding="utf-8")
    ran = (session or _session)(record, evidence, cfg, fleet, run_id=run_id, item=f"week-{week}",
                                scheduled=scheduled, claude_bin=claude_bin)
    status.update({k: ran[k] for k in ("status", "why", "cost_usd", "cost_source", "turns") if k in ran})
    doc, why = parse_final(ran.get("final") or "") if ran.get("status") == "ok" else (None, "")
    if scheduled and (ran.get("status") == "ok" or float(ran.get("cost_usd") or 0) > 0):
        spent.write_text(json.dumps({"run_id": run_id, "document": doc or {"proposals": []}}) + "\n", encoding="utf-8")
    if ran.get("status") != "ok":
        return status
    if doc is None:
        return {**status, "status": "rejected", "why": why}
    verdict = validate(doc, brief, cfg)
    (record / "proposals.json").write_text(json.dumps(verdict, indent=1) + "\n", encoding="utf-8")
    return {**status, **{k: verdict[k] for k in ("accepted", "dropped", "notes")},
            "why": f"{len(verdict['accepted'])} proposal(s) accepted, {len(verdict['dropped'])} dropped"}


def _session(record: Path, evidence: Path, cfg: dict, fleet: dict, *, run_id: str, item: str, scheduled: bool,
             claude_bin: str) -> dict:
    """ONE model call, the way the incident reflector makes one: the host check (CLI, sandbox, a cached
    probe and canary for this posture, one credential), the budget lock, budget.loops' ceiling, then
    `dash-gen ai-run --isolate` in a throwaway copy of the evidence, and the posture checks before any
    output is read."""
    from tools.jev import headless, loop as engine, reflect, spec as S
    from tools.jev.common import JevError
    if cfg["model"] not in S.allowed_models(fleet):
        return {"status": "refused", "why": f"weekly.agent.model {cfg['model']!r} is not in ai_models.allowed (§ 13.3)"}
    spec = reflect.ReflectSpec(loop=LOOP, step=STEP, call_site="local", allowed_tools=TOOLS,
                               resolved=S.Resolved(model=cfg["model"], max_turns=int(cfg["max_turns"]),
                                                   max_budget_usd=float(cfg["usd"])),
                               timeout_minutes=int(cfg["timeout_minutes"]))
    posture = headless.Posture("sandbox")
    try:
        host = engine.host_check(spec, posture, fleet, claude_bin, None, live=True, preflight=True)
    except (JevError, S.StepSpecError, OSError) as exc:
        return {"status": "host-refused", "why": f"the host check could not run: {exc}"}
    refusal = host.refusal()
    if refusal:
        # the engine names the loop runner's doctor; the posture is the reflector's, so its doctor arms it
        return {"status": "host-refused", "why": reflect.retarget(refusal[1]) + " (the close-out agent shares the reflector's posture: "
                "`tools/dash refine reflect doctor`, then `tools/dash refine reflect doctor --live --yes`, arms both)"}
    with engine.budget_lock() as held:
        if not held:
            return {"status": "budget-locked", "why": "another local loop attempt holds the budget lock"}
        try:
            state = engine.budget_position(fleet, scheduled=scheduled)
        except (JevError, S.StepSpecError) as exc:
            return {"status": "budget-unreadable", "why": f"monthly ceiling: {exc}"}
        if not state.affords(float(cfg["usd"])):
            return {"status": "budget-stop", "why": f"monthly ceiling: {state.summary()}"}
        ran = reflect.run_session(record, evidence, spec=spec, posture=posture, host=host, fleet=fleet,
                                  run_id=run_id, item=item, source=SOURCE)
    outcome = ran["outcome"]
    base = {"cost_usd": outcome.get("cost_usd"), "cost_source": outcome.get("cost_source"), "turns": outcome.get("turns")}
    if ran["breach"]:
        return {**base, "status": "unsafe", "why": f"{ran['breach']}: the output is left unread"}
    kind = str(outcome.get("kind"))
    if kind == "usage_limit":
        return {**base, "status": "usage-limited", "why": "Claude usage limit: capacity, not a defect"}
    if kind != "ok":
        return {**base, "status": "failed", "why": f"{kind}: {str(outcome.get('detail') or '')[:160]}"}
    return {**base, "status": "ok", "why": "", "final": ran["final"]}


def render(agent: dict, rows: list[dict], cap: int = 20) -> list[str]:
    """The report's section on what the close-out agent proposed."""
    lines = ["### The close-out agent", ""]
    cost = agent.get("cost_usd")
    spent = f" It spent ${float(cost):.2f} of a ${agent['cap_usd']:g} cap, {agent['label']}." if cost is not None else ""
    if agent["status"] != "ok":
        return lines + [f"Did not run ({agent['status']}): {agent['why']}.{spent} The stale list above stands as the rules left it.", ""]
    by_key = {r["key"]: r for r in rows}
    lines += [f"One read-only session ({agent['model']}) ruled on the stale items: {agent['why']}.{spent} "
              "Nothing below is applied until you say so.", ""]
    for action, title in (("close", "Close"), ("decide", "Decide"), ("carry", "Carry")):
        picked = [p for p in agent["accepted"] if p["action"] == action]
        if not picked:
            continue
        lines += [f"**{title}** ({len(picked)})", ""]
        for p in picked[:cap]:
            row = by_key.get(p["key"]) or {}
            via = f", superseded by {p['superseded_by'].split(':', 1)[1]}" if p.get("superseded_by") else ""
            lines.append(f"- [{row.get('repo')}#{row.get('number')}]({row.get('url')}): {p['reason']}{via}")
        if len(picked) > cap:
            lines.append(f"- and {len(picked) - cap} more")
        lines.append("")
    if agent.get("notes"):
        lines += [f"Its notes: {agent['notes']}", ""]
    return lines

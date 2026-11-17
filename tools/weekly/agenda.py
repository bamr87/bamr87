#!/usr/bin/env python3
# ============================================================================
# File:          tools/weekly/agenda.py
# Description:   Sunday's plan (docs/WEEKLY.md): the week's ranked plan with what the Grok half
#                handed off lifted into it, the week day by day (each day's focus lane beside the
#                loops scheduled on the hub), what Saturday found at risk, and the Monday brief
#                that puts all of it on one page. Pure builders and renderers: the stage that
#                gathers their inputs is tools/weekly/cli.py `cmd_plan`.
# Usage:         imported by tools/weekly/cli.py; `tools/dash weekly plan` runs it
# Never:         writes anywhere but the run folder. The plan reaches `_data/work_queue.yml` only
#                through the weekly pull request the maintainer's confirm opens.
# ============================================================================
from __future__ import annotations

from typing import Any

from tools.weekly import core, prepare

DEFAULTS: dict = {
    "handoff_score": 2000,   # above every priority, below a maintainer's pin (plan.pin_score)
    # Each weekday's focus lane; Friday closes the week. A day with no focus shows only its schedule.
    "focus": {"Monday": "decide", "Tuesday": "finish", "Wednesday": "unblock", "Thursday": "do", "Friday": "close"},
    "fix_first": 5,
}


def config(fleet: dict) -> dict:
    return core.merged(DEFAULTS, (fleet.get("weekly") or {}).get("agenda"))


def handoff_boost(model: dict | None, direction: dict | None, label: str, points: int) -> dict[str, tuple[int, str]]:
    """What the week's direction issue links, and anything carrying the handoff label: each gets the
    same lift, so a handoff outranks the backlog without outranking a pin."""
    boost: dict[str, tuple[int, str]] = {}
    for ref in (direction or {}).get("handoffs") or []:
        boost[ref] = (points, "handed off for this week")
    for repo in (model or {}).get("repos") or []:
        for item in repo.get("items") or []:
            if label in (item.get("labels") or []):
                boost.setdefault(f"{item.get('repo')}#{item.get('number')}", (points, f"labelled {label}"))
    return boost


def handoff_status(model: dict | None, direction: dict | None, plan: dict | None) -> dict:
    """Which handed-off issues the plan carries, which are open but past the lane's slots, and which
    the fleet no longer has open (closed, or in a repo the review cannot read)."""
    refs = list((direction or {}).get("handoffs") or [])
    open_refs = {f"{i.get('repo')}#{i.get('number')}" for r in (model or {}).get("repos") or [] for i in r.get("items") or []}
    planned = {row["ref"] for lane in core.LANES for row in ((plan or {}).get("lanes") or {}).get(lane) or []}
    return {"planned": [r for r in refs if r in planned], "unplanned": [r for r in refs if r in open_refs and r not in planned],
            "not_open": [r for r in refs if r not in open_refs]}


def readiness(prep: dict | None, limit: int) -> dict:
    """Saturday's findings, shortened for the brief."""
    if not prep:
        return {"ran": False, "fix": [], "counts": {}}
    fix = [f"{k['name']}: {k['why']}" + (f" (`{k['fix']}`)" if k.get("fix") else "") for k in prep.get("checks") or [] if k["state"] != prepare.READY]
    fix += [f"{r['id']}: " + ("; ".join(r["notes"]) or ((r.get("switch") or {}).get("why") or r["state"]))
            for r in prep.get("activities") or [] if r["state"] in (prepare.RISK, prepare.UNKNOWN)]
    fix += [f"{j['label']} is not loaded on this Mac (`{j['installer']}`)" for j in prep.get("local_jobs") or [] if not j.get("loaded")]
    return {"ran": True, "fix": fix[:limit], "more": max(0, len(fix) - limit), "counts": prep.get("counts") or {},
            "generated_at": prep.get("generated_at")}


def days(calendar: list[dict], plan: dict | None, cfg: dict) -> list[dict]:
    """The week day by day: the focus lane's items and the hub's loops."""
    out = []
    for day in calendar:
        focus = (cfg["focus"] or {}).get(day["name"])
        items = ((plan or {}).get("lanes") or {}).get(focus) or [] if focus in core.LANES else []
        loops: dict[str, list[str]] = {}
        for slot in day.get("hub") or []:
            loops.setdefault(slot["id"], []).append(slot["local"].split(" ", 1)[1])
        out.append({"date": day["date"], "name": day["name"], "focus": focus, "items": [{k: r[k] for k in ("ref", "title", "url")} for r in items],
                    "loops": [{"id": k, "times": v} for k, v in loops.items()], "fleet": day.get("fleet") or 0})
    return out


def headline(record: dict) -> str:
    plan, ready = record.get("plan") or {}, record.get("readiness") or {}
    lanes = plan.get("by_lane") or {}
    risk = (ready.get("counts") or {}).get(prepare.RISK, 0)
    return (f"{plan.get('ranked', 0)} open items ranked, {lanes.get('decide', 0)} wait on a decision, "
            f"{risk} scheduled activit{'y is' if risk == 1 else 'ies are'} at risk")


def render(record: dict) -> str:
    """The Monday brief: the one page to read before the week starts."""
    week, plan = record["week"], record.get("plan")
    ready, direction, hand = record.get("readiness") or {}, record.get("direction") or {}, record.get("handoffs") or {}
    lines = [f"# The week ahead: {week}", "", f"> {record.get('headline', '')}. Nothing here was written anywhere but this folder: "
             "`tools/dash weekly confirm` shows what your yes would do.", ""]
    if record.get("errors"):
        lines += ["## Problems", "", *[f"- {e}" for e in record["errors"]], ""]
    lines += ["## First thing Monday", ""]
    step = 1
    if not record.get("confirmed"):
        lines.append(f"{step}. Confirm the weekend: `tools/dash weekly confirm`, then `--apply`. It carries this plan into the weekly pull request.")
        step += 1
    if ready.get("fix"):
        lines.append(f"{step}. Fix what Saturday found before the loops run:")
        lines += [f"   - {x}" for x in ready["fix"]]
        if ready.get("more"):
            lines.append(f"   - and {ready['more']} more in Saturday's report")
        step += 1
    elif not ready.get("ran"):
        lines.append(f"{step}. Saturday's preflight did not run, so nothing has checked that the week's loops can run: `tools/dash weekly prepare`.")
        step += 1
    decide = ((plan or {}).get("lanes") or {}).get("decide") or []
    if decide:
        lines.append(f"{step}. Decide, in this order, because each one unblocks work:")
        lines += [f"   - [{r['ref']}]({r['url']}): {r['title']}" for r in decide]
    if step == 1 and not decide:
        lines.append("Nothing is waiting: the weekend is confirmed, the week's loops can run and no decision is queued.")
    lines += ["", "## Direction", ""]
    if direction.get("error"):
        lines.append(f"The direction issue could not be read ({direction['error']}).")
    elif not direction.get("found"):
        lines.append(f"No issue titled `{direction.get('title', '')}` is open, so the Grok half has not set direction for this week. "
                     "Its briefs: `tools/dash weekly brief close`, `prepare` and `plan`.")
    else:
        done = direction.get("sections") or []
        marks = ", ".join(f"{name} {'done' if name in done else 'missing'}" for name in ("friday", "saturday", "sunday"))
        lines.append(f"[{direction['title']}]({direction['url']}): {marks}.")
        if hand.get("planned"):
            lines.append(f"- In the plan: {', '.join(hand['planned'])}.")
        if hand.get("unplanned"):
            lines.append(f"- Handed off but past the lane's slots: {', '.join(hand['unplanned'])}. Pin one in `_data/work_queue.yml` to force it in.")
        if hand.get("not_open"):
            lines.append(f"- Linked but not open in a repo the review reads: {', '.join(hand['not_open'])}.")
    if plan:
        lines += ["", "## The plan", "", f"Ranked {plan['ranked']} open items; {plan['held']} are held.", ""]
        for lane in core.LANES:
            rows = plan["lanes"][lane]
            if rows:
                lines += [f"### {core.LANE_TITLES[lane]} ({plan['by_lane'][lane]} in the lane)", ""]
                lines += [f"- [{r['ref']}]({r['url']}): {r['title']} ({', '.join(r['reasons'])})" for r in rows]
                lines.append("")
    else:
        lines += ["", "## The plan", "", "No plan: the PM review did not run, so nothing was ranked.", ""]
    lines += ["## The week, day by day", "", "Local time, by local day. Loops are the hub's; the rest of the fleet is counted.", ""]
    for day in record.get("days") or []:
        title = f"### {day['name']} {day['date']}"
        if day.get("focus"):
            title += f": {core.LANE_TITLES.get(day['focus'], 'Close the week')}"
        lines += [title, ""]
        for item in day["items"]:
            lines.append(f"- [{item['ref']}]({item['url']}): {item['title']}")
        if day.get("focus") == "close":
            lines.append("- The close-out runs tonight: `tools/dash weekly close`.")
        for loop in day["loops"]:
            lines.append(f"- scheduled: {loop['id']} at {', '.join(loop['times'][:6])}" + (f" and {len(loop['times']) - 6} more" if len(loop["times"]) > 6 else ""))
        if day["fleet"]:
            lines.append(f"- and {day['fleet']} scheduled runs across the rest of the fleet")
        if not (day["items"] or day["loops"] or day["fleet"] or day.get("focus") == "close"):
            lines.append("- nothing scheduled")
        lines.append("")
    co: Any = record.get("closeout")
    if co:
        c = co["counts"]
        lines += ["## Where Friday's close-out stands now", "",
                  f"{co['open']['pr']} open pull requests: {c['merge']['pr']} "
                  + ("ready to merge" if co.get("scanned") else "mechanically ready (their changed files were not read)")
                  + f", {c['ratify']['pr'] + c['amr']['pr']} waiting on you, "
                  f"{c['resolve']['pr']} conflicting, {c['fix']['pr']} failing checks, {c['stale']['pr']} stale. "
                  f"{co['open']['issue']} open issues, {c['stale']['issue']} of them stale.", ""]
    return "\n".join(lines).rstrip() + "\n"

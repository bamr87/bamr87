#!/usr/bin/env python3
# ============================================================================
# File:          tools/weekly/cli.py
# Description:   The weekly routine's command line (docs/WEEKLY.md). Three stages, one per day:
#                `close` (Friday: save, tidy, close out; core.py, closeout.py), `prepare` (Saturday:
#                can next week's schedule run; prepare.py) and `plan` (Sunday: the plan, the agenda
#                and the Monday brief; agenda.py). `auto` is what the LaunchAgent calls: it runs
#                every stage that is due this weekend and has not run, in order, so a Mac that was
#                asleep on Friday night still closes the week before it prepares the next.
#                `confirm` is the maintainer's yes for every external write of all three.
# Usage:         python3 -m tools.weekly close [--scheduled | --apply] [--agent] [--offline] [--no-plan]
#                python3 -m tools.weekly prepare [--scheduled] [--offline]
#                python3 -m tools.weekly plan [--scheduled] [--offline]
#                python3 -m tools.weekly auto --scheduled
#                python3 -m tools.weekly confirm [--apply] [--keep-drafts] [--publish FILE]… [--allow REPO:BRANCH]…
#                python3 -m tools.weekly status | inventory [--json] | brief <close|prepare|plan>
#                (or tools/dash weekly …)
# Exit:          0 clean · 1 failed · 2 usage · 3 switched off
# Never:         a scheduled stage writes to GitHub or changes a repo before the report-only runs
#                are done; see core.py for what confirm may write.
# ============================================================================
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from tools.weekly import agenda, closeout, core, harness, prepare


def _start(args: argparse.Namespace, root: Path, stage: str, now: datetime | None) -> tuple[dict, dict, datetime, str | None]:
    fleet = core.load_fleet(root)
    moment = now or core.now_utc()
    why = core.switched_off(fleet) if args.scheduled else None
    if why:
        print(f"weekly {stage}: skipped, {why}")
    return fleet, core.load_config(fleet), moment, why


def _folder(state_dir: Path, moment: datetime, week: str, stage: str) -> tuple[str, Path]:
    run_id = f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{week}-{stage}"
    folder = state_dir / run_id
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    return run_id, folder


def _finish(folder: Path, record: dict, report: str) -> None:
    record["finished"] = core.now_utc().isoformat()
    (folder / "run.json").write_text(json.dumps(record, indent=1, default=str) + "\n")
    (folder / "report.md").write_text(report)
    print(report)
    print(f"\nfiles: {folder}")


def cmd_prepare(args: argparse.Namespace, root: Path, state_dir: Path, now: datetime | None = None,
                runner: Callable = core.run, position: Callable | None = None) -> int:
    """Saturday's stage: can next week's schedule run. Reads and reports; the fixes are the maintainer's."""
    fleet, _, moment, off = _start(args, root, "prepare", now)
    if off:
        return 3
    with core.lock(state_dir):
        week = core.plan_week(moment)
        run_id, folder = _folder(state_dir, moment, week, "prepare")
        print(f"weekly: {run_id}, checking that {week}'s schedule can run")
        doc = prepare.build(root, fleet, week, moment, offline=args.offline, runner=runner, position=position)
        (folder / "prepare.json").write_text(json.dumps(doc, indent=1, default=str) + "\n")
        brief = folder / "grok-brief.md"
        brief.write_text(harness.grok_brief("prepare", week, fleet))
        c = doc["counts"]
        bad = sum(k["state"] != prepare.READY for k in doc["checks"])
        errors = [f"refresh: `{r['command']}` failed ({r['note']})" for r in doc["refreshed"] if not r["ok"]]
        record = {"schema": core.RUN_SCHEMA, "id": run_id, "stage": "prepare", "week": week,
                  "mode": "scheduled" if args.scheduled else "manual", "scheduled": bool(args.scheduled),
                  "started": moment.isoformat(), "errors": errors, "counts": c, "checks_failing": bad,
                  "headline": f"{c[prepare.READY]} activities ready, {c[prepare.RISK]} at risk, {bad} checks need a fix"}
        lines = prepare.render(doc) + ["## The Grok half", "", f"Direction for the week is a Grok bot's: its brief is `{brief}` "
                                       "(`tools/dash weekly brief prepare`). Sunday's plan reads what it hands off.", ""]
        _finish(folder, record, "\n".join(lines).rstrip() + "\n")
        if args.scheduled:
            core.notify(f"Ready for {week}?", f"{c[prepare.RISK]} scheduled activities at risk, {bad} checks to fix. tools/dash weekly status")
        return 1 if errors else 0


def cmd_plan(args: argparse.Namespace, root: Path, state_dir: Path, now: datetime | None = None,
             direction: Callable | None = None, read_index: Callable | None = None, runner: Callable | None = None) -> int:
    """Sunday's stage: the week's plan, its agenda and the Monday brief. Writes only its run folder."""
    fleet, cfg, moment, off = _start(args, root, "plan", now)
    if off:
        return 3
    with core.lock(state_dir):
        week = core.plan_week(moment)
        run_id, folder = _folder(state_dir, moment, week, "plan")
        acfg, gcfg = agenda.config(fleet), harness.grok_config(fleet)
        record: dict = {"schema": core.RUN_SCHEMA, "id": run_id, "stage": "plan", "week": week,
                        "mode": "scheduled" if args.scheduled else "manual", "scheduled": bool(args.scheduled),
                        "started": moment.isoformat(), "errors": []}
        model = None
        if args.offline:
            model, _ = core.pm_files(root)
            if model:
                record["errors"].append(f"offline: ranked from the PM review of {str(model.get('generated_at'))[:16]}, not a fresh one")
        else:
            print(f"weekly: {run_id}, PM review and ranking")
            pm = core.run_pm(root)
            if pm["ok"]:
                model, _ = core.pm_files(root)
            else:
                record["errors"].append(f"pm review: {pm['error']}")
        title = gcfg["issue_title"].format(week=week)
        told = {"title": title, "found": False, "url": None, "sections": [], "handoffs": [], "error": "offline" if args.offline else None}
        if not args.offline:
            told = (direction or harness.direction)(week, fleet)
        plan = None
        if model:
            import work_queue as wq
            doc, _ = wq.load(root / core.QUEUE)
            held = ((fleet.get("pm") or {}).get("board") or {}).get("held") or ("Needs Amr", "Hold", "Blocked", "Won't do")
            boost = agenda.handoff_boost(model, told, gcfg["handoff_label"], int(acfg["handoff_score"]))
            plan = core.rank(model, doc, cfg, held, moment, boost)
            record["pinned"] = list(doc.get("order") or [])
            record["open_keys"] = sorted(r["key"] for r in core.all_open(model))
        index, classify, gate_cfg, note = (read_index or closeout.read_index)(root, args.offline)
        closed = closeout.build(index, model, fleet, moment, classify, gate_cfg)
        if not args.offline:  # the same live read Friday made, so "ready" means the same thing on both days
            labels = (gate_cfg or {}).get("labels") or {"gate": ["needs-amr"], "hold": ["agent:hold", "blocked"]}
            closeout.gate_scan(closed, fleet, {"labels": labels}, **({"runner": runner} if runner else {}))
        saturday = core.latest(state_dir, "prepare")
        prep = None
        if saturday and saturday[1].get("week") == week and (saturday[0] / "prepare.json").exists():
            prep = json.loads((saturday[0] / "prepare.json").read_text())
        calendar = prep["calendar"] if prep else prepare.calendar(
            prepare.activities(fleet, prepare._load(root / "_data" / "harness_registry.yml"),
                               prepare._load(root / "_data" / "actions_usage.yml"), week, prepare.config(fleet)),
            week, str((fleet.get("hub") or {}).get("repo") or "bamr87/bamr87"))
        friday = core.latest(state_dir, "close")
        confirmed = bool(friday and friday[1].get("week") == week and (friday[0] / "confirm.json").exists())
        record.update(plan=plan, direction=told, handoffs=agenda.handoff_status(model, told, plan),
                      readiness=agenda.readiness(prep, int(acfg["fix_first"])), days=agenda.days(calendar, plan, acfg),
                      closeout={"counts": closed["counts"], "open": closed["open"], "sources": closed["sources"], "note": note,
                                "scanned": closed["scanned"]},
                      confirmed=confirmed)
        record["headline"] = agenda.headline(record)
        (folder / "grok-brief.md").write_text(harness.grok_brief("plan", week, fleet))
        _finish(folder, record, agenda.render(record))
        if args.scheduled:
            core.notify(f"The week ahead: {week}", f"{record['headline']}. tools/dash weekly confirm")
        return 1 if not plan else 0


# ---- auto: what the LaunchAgent calls -----------------------------------------------------------

def _py_weekday(launchd: int) -> int:
    return (int(launchd) - 1) % 7  # launchd: 0 and 7 are Sunday; Python: Monday is 0


def slot_before(now: datetime, spec: dict) -> datetime:
    """The most recent time, at or before `now`, that matches a slot's weekday, hour and minute."""
    at = now.replace(hour=int(spec["hour"]), minute=int(spec["minute"]), second=0, microsecond=0)
    at -= timedelta(days=(at.weekday() - _py_weekday(spec["weekday"])) % 7)
    return at if at <= now else at - timedelta(days=7)


def slot_after(after: datetime, spec: dict) -> datetime:
    """The first time after `after` that matches a slot."""
    return slot_before(after + timedelta(days=7), spec)


#: How early a firing may be and still count as its slot.
EARLY = timedelta(minutes=2)


def schedule_problem(schedule: dict) -> str | None:
    """Why a schedule cannot work, or None. Each slot is whole numbers, off the hour, and the three
    fall in order inside one weekend: close, then prepare, then plan, within three days."""
    for stage in core.STAGES:
        slot = schedule.get(stage)
        if not isinstance(slot, dict):
            return f"weekly.schedule.{stage} is missing"
        for key, low, high in (("weekday", 0, 7), ("hour", 0, 23), ("minute", 1, 59)):
            value = slot.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                return f"weekly.schedule.{stage}.{key} must be a whole number from {low} to {high}" + (" (never on the hour)" if key == "minute" else "")
    start = datetime(2026, 1, 2, 12, 0)  # any moment: the check is about the order of the three, not a date
    first = slot_before(start, schedule["close"])
    second = slot_after(first, schedule["prepare"])
    third = slot_after(second, schedule["plan"])
    if not first < second < third <= first + timedelta(days=3):
        return "weekly.schedule: close, prepare and plan must fall in that order within three days"
    hours = schedule.get("catch_up_hours")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0 <= hours <= 72:
        return "weekly.schedule.catch_up_hours must be a number from 0 to 72"
    return None


def wall(moment: datetime) -> datetime:
    """A moment as this machine's wall clock reads it, without a zone. The slots are wall-clock times
    (launchd's), so the arithmetic is done on wall time: a fixed UTC offset would put Friday's slot an
    hour off on the weekend the clocks change, and the close would run twice."""
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def due_stages(now: datetime, schedule: dict, done: Callable[[str, datetime], bool]) -> list[str]:
    """The stages that are due this weekend and have not run, in order. `now` and the `since` handed
    to `done` are wall-clock times (`wall`). The weekend starts at Friday's slot; a stage missed while
    the Mac slept is still due until `catch_up_hours` after Sunday's slot, and after that the weekend
    is over and nothing runs late into the week it was meant to prepare."""
    now = wall(now)
    early = now + EARLY  # launchd is not promised to the second: a firing just before a slot is that slot
    start = slot_before(early, schedule["close"])
    second = slot_after(start, schedule["prepare"])
    third = slot_after(second, schedule["plan"])
    if now > third + timedelta(hours=float(schedule["catch_up_hours"])):
        return []
    slots = {"close": start, "prepare": second, "plan": third}
    return [stage for stage in core.STAGES if slots[stage] <= early and not done(stage, start - EARLY)]


def cmd_auto(args: argparse.Namespace, root: Path, state_dir: Path, archive: Path, now: datetime | None = None,
             stages: dict[str, Callable[[], int]] | None = None) -> int:
    fleet = core.load_fleet(root)
    why = core.switched_off(fleet)
    if why:
        print(f"weekly: skipped, {why}")
        return 3
    cfg = core.load_config(fleet)
    problem = schedule_problem(cfg["schedule"])
    if problem:
        print(f"weekly: {problem}; nothing runs until it is fixed", file=sys.stderr)
        return 2
    local = wall(now or core.now_utc())

    def done(stage: str, since: datetime) -> bool:
        for path in core.run_dirs(state_dir):
            rec = core.read_run(path)
            try:
                started = wall(datetime.fromisoformat(str(rec.get("started"))))
            except ValueError:
                continue
            if core.stage_of(rec) == stage and rec.get("scheduled") and rec.get("finished") and started >= since:
                return True
        return False

    due = due_stages(local, cfg["schedule"], done)
    if not due:
        print("weekly: nothing is due")
        return 0
    one = argparse.Namespace(scheduled=True, apply=False, offline=False, no_plan=False, agent=False)
    table = stages or {"close": lambda: core.cmd_run(one, root, state_dir, archive),
                       "prepare": lambda: cmd_prepare(one, root, state_dir),
                       "plan": lambda: cmd_plan(one, root, state_dir)}
    worst = 0
    for stage in due:
        print(f"weekly: {stage} is due")
        try:
            code = table[stage]()
        except Exception as exc:  # noqa: BLE001  (one stage's crash is reported and does not cost the weekend its other stages)
            print(f"weekly: {stage} failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
            code = 1
        except SystemExit as exc:  # the lock held by another run, or a refusal: the same, by its own message
            print(f"weekly: {stage} stopped: {exc}", file=sys.stderr)
            code = 1
        worst = max(worst, code)
        if code == 3:
            break
    return worst


def cmd_brief(args: argparse.Namespace, root: Path) -> int:
    fleet = core.load_fleet(root)
    print(harness.grok_brief(args.stage, args.week or core.plan_week(core.now_utc()), fleet), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/dash weekly", description="the weekly routine (docs/WEEKLY.md)")
    parser.add_argument("--root", default=str(core.ROOT), help="the hub checkout to work on")
    parser.add_argument("--state-dir", default=None, help="run folders (default: <root>/.fleet/weekly)")
    parser.add_argument("--archive", default=None, help="the archive (default: fleet.yml weekly.archive_dir)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("close", help="Friday: save, tidy and close out the week; bare it is a preview that changes no repo")
    how = r.add_mutually_exclusive_group()
    how.add_argument("--scheduled", action="store_true", help="the LaunchAgent's mode: honours the switch and the report-only runs")
    how.add_argument("--apply", action="store_true", help="refresh and tidy now, typed by the maintainer")
    r.add_argument("--agent", action="store_true", help="also run the close-out agent on the stale items (one capped session)")
    r.add_argument("--offline", action="store_true", help="no fetch and no GitHub reads")
    r.add_argument("--no-plan", action="store_true", help="skip the PM review, the ranking and the close-out")
    for name, text in (("prepare", "Saturday: can next week's scheduled activities run"),
                       ("plan", "Sunday: the week's plan, its agenda and the Monday brief")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--scheduled", action="store_true", help="the LaunchAgent's mode: honours the switch")
        s.add_argument("--offline", action="store_true", help="no GitHub reads")
    a = sub.add_parser("auto", help="run every stage that is due this weekend and has not run (the LaunchAgent's entry)")
    a.add_argument("--scheduled", action="store_true", required=True, help="auto only runs scheduled stages")
    i = sub.add_parser("inventory", help="read-only: what the close-out sees on this machine")
    i.add_argument("--json", action="store_true")
    i.add_argument("--offline", action="store_true")
    c = sub.add_parser("confirm", help="show the weekend's external writes (wip/ pushes, board ops, the weekly PR); --apply is the maintainer's yes")
    c.add_argument("--apply", action="store_true")
    c.add_argument("--keep-drafts", action="store_true", help="land the week's posts as drafts")
    c.add_argument("--publish", action="append", default=[], metavar="FILE", help="also publish an older draft in pages/posts/")
    c.add_argument("--allow", action="append", default=[], metavar="REPO:BRANCH", help="push one held branch, after reading what the scan found")
    sub.add_parser("status", help="the latest run of each stage")
    b = sub.add_parser("brief", help="print the Grok bot's brief for a stage")
    b.add_argument("stage", choices=harness.STAGES)
    b.add_argument("--week", default=None, help="the ISO week, e.g. 2026-W47 (default: the week being planned)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    state_dir = Path(args.state_dir).resolve() if args.state_dir else root / ".fleet" / "weekly"
    if args.cmd == "status":
        return core.cmd_status(state_dir)
    if args.cmd == "inventory":
        return core.cmd_inventory(args, root)
    if args.cmd == "confirm":
        return core.cmd_confirm(args, root, state_dir)
    if args.cmd == "brief":
        return cmd_brief(args, root)
    if args.cmd == "prepare":
        return cmd_prepare(args, root, state_dir)
    if args.cmd == "plan":
        return cmd_plan(args, root, state_dir)
    # absolute: every git call runs with -C in a repo, so a relative path would land inside each one
    archive = core.expand(args.archive or core.load_config(core.load_fleet(root))["archive_dir"]).resolve()
    if args.cmd == "auto":
        return cmd_auto(args, root, state_dir, archive)
    return core.cmd_run(args, root, state_dir, archive)


if __name__ == "__main__":
    sys.exit(main())

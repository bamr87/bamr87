#!/usr/bin/env python3
# ============================================================================
# File:          tools/weekly/prepare.py
# Description:   Saturday's preflight (docs/WEEKLY.md): every activity scheduled for the coming week,
#                when it fires, and whether it can run. Reads the central switch map and the fleet's
#                schedule, each workflow's last result, the credential ledgers, the month's AI spend
#                against its ceilings, the freshness of the data the agents read, and this Mac's own
#                scheduled jobs. Reports; changes nothing but the local caches its refresh list names.
# Usage:         imported by tools/weekly/cli.py; `tools/dash weekly prepare` runs it
# Never:         flips a switch, rotates a credential, loads or unloads a LaunchAgent, or reads a
#                secret's value: it names the fix and the person runs it (constitution § 10.5, § 17.3).
# ============================================================================
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

from tools.weekly import core

SCHEMA = "weekly-prepare/v1"
READY, RISK, OFF, UNKNOWN = "ready", "at-risk", "off", "unknown"
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: The only commands the refresh list may name: local, idempotent, $0, and writing nothing but
#: gitignored local data. Config chooses among these; it cannot add one, because Saturday's run is
#: unattended and a `tools/dash` subcommand can do anything, including this routine's own confirm.
REFRESHABLE = ("tools/dash decisions refresh", "tools/dash lake status --no-probe")

DEFAULTS: dict = {
    # Refreshes run before the checks, each one of REFRESHABLE.
    "refresh": ["tools/dash decisions refresh"],
    "refresh_timeout_s": 300,
    "min_disk_gb": 10,
    "fires_shown": 4,
    "failing_rate_pct": 50,
}


def config(fleet: dict) -> dict:
    return core.merged(DEFAULTS, (fleet.get("weekly") or {}).get("prepare"))


# ---- the week and when a cron fires in it -----------------------------------------------------

def week_window(week: str) -> tuple[datetime, datetime]:
    """Monday 00:00 UTC to the next Monday, for an ISO week such as 2026-W47. Hub crons are UTC."""
    year, number = week.split("-W")
    start = datetime.fromisocalendar(int(year), int(number), 1).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def parse_cron(cron: str) -> dict | None:
    import harness_registry  # .github/scripts/dash-gen, on sys.path through core
    return harness_registry.parse_cron(str(cron or ""))


def fires(cron: str, start: datetime, end: datetime, parsed: dict | None = None) -> list[datetime] | None:
    """Every time a 5-field cron fires in [start, end), in UTC; None for a cron that does not parse.
    Vixie's rule holds: when both the day of month and the day of week are restricted, either matches."""
    p = parsed or parse_cron(cron)
    if not p:
        return None
    out = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        dow = (day.weekday() + 1) % 7  # cron: Sunday is 0
        dom_ok, dow_ok = day.day in p["doms"], dow in p["dows"]
        if p["dom_restricted"] and p["dow_restricted"]:
            day_ok = dom_ok or dow_ok
        else:
            day_ok = dom_ok and dow_ok
        if day_ok and day.month in p["months"]:
            for hour in sorted(p["hours"]):
                for minute in sorted(p["minutes"]):
                    at = day.replace(hour=hour, minute=minute)
                    if start <= at < end:
                        out.append(at)
        day += timedelta(days=1)
    return out


# ---- switches ---------------------------------------------------------------------------------

def variable_value(repo: str, name: str, runner: Callable = core.run) -> tuple[str | None, str | None]:
    """(value, error). An unset variable is ('', None): GitHub answers 404 and that is a fact, not a
    failure. Reads one repository variable; never a secret (§ 17.8)."""
    r = runner(["gh", "variable", "get", name, "-R", repo], timeout=30)
    if r.returncode == 0:
        return r.stdout.strip(), None
    text = (r.stderr or r.stdout or "").lower()
    if "not found" in text or "404" in text:
        return "", None
    return None, (r.stderr or "gh variable get failed").strip()[:120]


def switch_state(entry: dict, switches: dict, fleet: dict, live: Callable[[str, str], tuple[str | None, str | None]] | None) -> dict:
    """One loop's switch, read the way the loop reads it: the most restrictive of the global, the
    group and the loop itself (§ 17.2), then the gate. `live` reads a repository variable; without it
    an `unverified` loop stays unverified and says so."""
    gate = entry.get("gate") or {}
    for name, level in (("global", switches.get("global") or {}),
                        (f"group {entry.get('group')}", (switches.get("groups") or {}).get(entry.get("group")) or {})):
        if level.get("state") == "off":
            return {"on": False, "verified": True, "why": f"{name} is off" + (f": {level['reason']}" if level.get("reason") else "")}
    declared, default = str(entry.get("state") or "unverified"), str(entry.get("default") or "on")
    kind = gate.get("kind")
    if kind == "fleet_config" and gate.get("name"):
        node: Any = fleet
        for part in str(gate["name"]).split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, bool):
            return {"on": node, "verified": True, "why": f"{gate['name']} is {str(node).lower()}"}
        return {"on": None, "verified": False, "why": f"{gate['name']} is not a true/false value in _data/fleet.yml"}
    if kind == "repo_variable" and gate.get("name") and live and entry.get("repo"):
        value, error = live(str(entry["repo"]), str(gate["name"]))
        if error:
            return {"on": None, "verified": False, "why": f"{gate['name']} could not be read ({error})"}
        opt_in = gate.get("semantics") == "opt_in"
        on = (value == "true") if opt_in else (value != "false")
        shown = repr(value) if value else "unset"
        drift = "" if on == (default == "on") else f"; the map's default is {default}"
        return {"on": on, "verified": True, "why": f"{gate['name']} is {shown}{drift}", "drift": bool(drift)}
    if declared in ("on", "off"):
        return {"on": declared == "on", "verified": bool(entry.get("verified")), "why": f"the map says {declared}"}
    return {"on": default == "on", "verified": False, "why": f"unverified; the map's default is {default}"}


# ---- the week's activities ----------------------------------------------------------------------

def nwo_of(url: Any) -> str | None:
    """owner/repo of a github.com URL, or None for any other host (the host is parsed, not searched for)."""
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    path = parts.path.removesuffix("/").removesuffix(".git").strip("/")
    return path or None


def last_runs(usage: dict | None) -> dict[tuple[str, str], dict]:
    """Each workflow's last result, by (owner/repo, path). The usage snapshot names a repo by its
    registry name and carries the URL, so the URL is what identifies it."""
    rows = {}
    for w in (usage or {}).get("workflows") or []:
        repo = nwo_of(w.get("repo_url")) or w.get("repo")
        if repo and w.get("path"):
            rows[(str(repo).lower(), str(w["path"]))] = w
    return rows


def activities(fleet: dict, registry: dict | None, usage: dict | None, week: str, cfg: dict,
               live: Callable | None = None) -> list[dict]:
    """Every scheduled workflow in the fleet for the week: the hub's loops from the central switch map,
    then the rest of the fleet from the harness registry's schedule. Each carries when it fires, its
    switch as far as it can be read, its last result and one verdict."""
    start, end = week_window(week)
    switches = fleet.get("switches") or {}
    runs = last_runs(usage)
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(ident: str, repo: str, path: str, cron: str, ai: bool, entry: dict | None) -> None:
        key = (repo.lower(), path)
        if key in seen:
            return
        seen.add(key)
        times = fires(cron, start, end)
        last = runs.get(key) or {}
        row: dict = {"id": ident, "repo": repo, "workflow": path, "cron": cron, "ai": ai,
                     "fires": None if times is None else len(times),
                     "first": [t.isoformat() for t in (times or [])[: int(cfg["fires_shown"])]],
                     "times": [t.isoformat() for t in (times or [])] if times is not None and len(times) <= 28 else [],
                     "last_conclusion": last.get("last_conclusion"), "last_run_at": last.get("last_run_at"),
                     "success_rate_pct": last.get("success_rate_pct"), "switch": None, "notes": []}
        state = READY
        if entry is not None:
            sw = switch_state(entry, switches, fleet, live)
            row["switch"] = sw
            if sw["on"] is False:
                state = OFF
            elif sw["on"] is None:
                state = UNKNOWN
            if sw.get("drift"):
                row["notes"].append("its variable disagrees with the switch map: record the flip in _data/fleet.yml")
                state = RISK if state == READY else state
            if entry.get("flip") and sw["on"] is False:
                row["notes"].append(f"to turn it on: {entry['flip']}")
        if times is None:
            row["notes"].append(f"its cron `{cron}` could not be parsed")
            state = UNKNOWN if state == READY else state
        if state == READY and str(last.get("last_conclusion") or "").lower() in ("failure", "timed_out", "startup_failure"):
            row["notes"].append(f"its last run ended {last['last_conclusion']}" + (f" on {str(last.get('last_run_at'))[:10]}" if last.get("last_run_at") else ""))
            state = RISK
        rate = last.get("success_rate_pct")
        if state == READY and isinstance(rate, (int, float)) and rate < float(cfg["failing_rate_pct"]) and (last.get("runs") or 0) >= 3:
            row["notes"].append(f"{rate:g}% of its recent runs succeeded")
            state = RISK
        row["state"] = state
        rows.append(row)

    for ident, entry in (switches.get("loops") or {}).items():
        if isinstance(entry, dict) and entry.get("cron") and entry.get("repo") and str(entry.get("workflow") or "").startswith(".github/"):
            add(ident, str(entry["repo"]), str(entry["workflow"]), str(entry["cron"]),
                (entry.get("group") or "").endswith("agents") or "agent" in ident, entry)
    names = {str(r.get("repo")): str(r.get("nwo")) for r in (registry or {}).get("repos") or [] if r.get("repo") and r.get("nwo")}
    hub = str((fleet.get("hub") or {}).get("repo") or "")
    names.setdefault(hub.split("/")[-1], hub)
    for s in (registry or {}).get("schedule") or []:
        if s.get("repo") and s.get("path") and s.get("cron"):
            repo = names.get(str(s["repo"])) or str(s["repo"])  # the registry's schedule names a repo, not owner/repo
            add(f"{s['repo']}:{Path(str(s['path'])).stem}", repo, str(s["path"]), str(s["cron"]), bool(s.get("ai")), None)
    order = {RISK: 0, UNKNOWN: 1, READY: 2, OFF: 3}
    rows.sort(key=lambda r: (order[r["state"]], r["repo"].lower(), r["workflow"]))
    return rows


def calendar(rows: list[dict], week: str, hub: str, tz: tzinfo | None = None) -> list[dict]:
    """The hub's loops by day, for the agenda; the rest of the fleet is counted per day. Days are the
    reader's own (`tz`, the machine's zone by default), because the times shown are: the week's crons
    are UTC, so west of Greenwich the week starts on Sunday evening and the first day listed is that
    Sunday."""
    start, end = week_window(week)
    days: dict[str, dict] = {}

    def day_of(at: datetime) -> dict:
        key = at.date().isoformat()
        return days.setdefault(key, {"date": key, "name": DAY_NAMES[at.weekday()], "hub": [], "fleet": 0})

    cursor = start.astimezone(tz)
    last = (end - timedelta(seconds=1)).astimezone(tz)
    while cursor.date() <= last.date():
        day_of(cursor)
        cursor += timedelta(days=1)
    for row in rows:
        if row["state"] == OFF:
            continue
        for stamp in row["times"] or row["first"]:
            at = datetime.fromisoformat(stamp).astimezone(tz)
            slot = day_of(at)
            if row["repo"].lower() == hub.lower():
                slot["hub"].append({"at": at.isoformat(), "local": at.strftime("%a %H:%M"), "id": row["id"],
                                    "state": row["state"], "ai": row["ai"]})
            else:
                slot["fleet"] += 1
    out = [days[key] for key in sorted(days)]
    for d in out:
        d["hub"].sort(key=lambda x: x["at"])
    return out


# ---- the week's gates: credentials, money, data, this machine -----------------------------------

def _load(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _stamp(doc: Any) -> datetime | None:
    if not isinstance(doc, dict):
        return None
    for key in ("generated_at", "updated_at", "generated", "updated"):
        raw = doc.get(key)
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        if not raw:
            continue
        text = str(raw).replace(" UTC", "+00:00").replace("Z", "+00:00")
        for candidate in (text, text.replace(" ", "T", 1)):
            try:
                at = datetime.fromisoformat(candidate)
                return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def check(name: str, state: str, why: str, fix: str = "") -> dict:
    return {"name": name, "state": state, "why": why, "fix": fix}


def credential_checks(root: Path, week: str, now: datetime) -> list[dict]:
    """From the committed ledgers, which hold names, ages and expiry dates and never a value."""
    _, end = week_window(week)
    out = []
    rotation = _load(root / "_data" / "token_rotation.yml") or {}
    read_at = _stamp(rotation)
    since = max(0, (now - read_at).days) if read_at else 0  # the ledger's ages are as of the day it was written
    for tok in rotation.get("tokens") or []:
        name, age, limit = tok.get("name"), tok.get("oldest_age_days"), tok.get("max_age_days")
        counts = tok.get("counts") or {}
        notes = [str(a) for a in tok.get("attention") or []]
        if counts.get("missing"):
            notes.append(f"missing in {counts['missing']} repo(s)")
        if isinstance(age, (int, float)) and isinstance(limit, (int, float)):
            age = age + since
            if age > limit:
                notes.append(f"{age:g} days old, past its {limit:g}-day limit")
            elif age + max(0, (end - now).days) > limit:
                notes.append(f"{age:g} days old: it passes its {limit:g}-day limit before the week ends")
        if notes:
            out.append(check(f"token {name}", RISK, "; ".join(notes[:3]), "tools/dash secrets plan, then tools/dash secrets rotate --apply"))
        else:
            out.append(check(f"token {name}", READY, f"{age if age is not None else '?'} days old across {counts.get('repos', '?')} repo(s)"))
    keys = _load(root / "_data" / "api_keys.yml") or {}
    for slot, row in (keys.get("slots") or {}).items():
        raw = (row or {}).get("expires_at")
        try:
            expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
        except ValueError:
            expires = None
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires is None:
            out.append(check(f"API key {slot}", UNKNOWN, "no expiry recorded", "tools/dash keys status"))
        elif expires < now:
            out.append(check(f"API key {slot}", RISK, f"expired {str(raw)[:10]}, by the ledger: if it is still in use, the ledger is stale",
                             "tools/dash keys status, then tools/dash keys rotate --apply"))
        elif expires < end:
            out.append(check(f"API key {slot}", RISK, f"expires {str(raw)[:10]}, inside the week", "tools/dash keys status, then tools/dash keys rotate --apply"))
        else:
            out.append(check(f"API key {slot}", READY, f"expires {str(raw)[:10]}"))
    return out


def budget_checks(fleet: dict, registry: dict | None, position: Callable | None = None) -> list[dict]:
    """The month so far against each ceiling. Every figure is API-equivalent (estimate) (§ 10.7)."""
    out = []
    if position is None:
        def position(scheduled: bool):
            from tools.jev import loop as engine
            return engine.budget_position(fleet, scheduled=scheduled)
    try:
        state = position(True)
        left = state.ceiling_usd - state.spent_usd
        agent = float((((fleet.get("weekly") or {}).get("agent") or {}).get("usd")) or 2)
        refine = float(((fleet.get("harness_refinement") or {}).get("stage_usd")) or 0)
        need = max(agent, refine)
        why = f"${state.spent_usd:.2f} of the ${state.ceiling_usd:g} scheduled ceiling spent in {state.month} (API-equivalent, estimate)"
        out.append(check("local loop budget", READY if left >= need else RISK, why,
                         "" if left >= need else "scheduled local sessions stop until the month turns; run one by hand, or raise budget.loops by a gated PR"))
    except Exception as exc:  # the ledger is this machine's: unreadable is a finding, not a crash
        out.append(check("local loop budget", UNKNOWN, f"the AI ledger could not be read ({type(exc).__name__})", "tools/dash loop budget"))
    trends = (registry or {}).get("trends") or {}
    for key, label in (("ai_cost_usd", "fleet AI spend"), ("actions_minutes", "Actions minutes")):
        t = trends.get(key) or {}
        if not t:
            continue
        status = str(t.get("status") or "unknown")
        figure = t.get("projected_monthly", t.get("billed_this_month"))
        why = f"{figure} against a monthly budget of {t.get('budget_monthly')} ({status})"
        out.append(check(label, READY if status in ("ok", "under", "within") else RISK if status in ("breach", "over", "warn", "warning") else UNKNOWN,
                         why, "" if status in ("ok", "under", "within") else "tools/dash harnesses; a paused loop is a flip in _data/fleet.yml switches:"))
    return out


def source_checks(root: Path, fleet: dict, now: datetime) -> list[dict]:
    """The data the agents read, against the freshness each source promises (§ 29.4)."""
    out = []
    for ident, src in (((fleet.get("harness") or {}).get("sources")) or {}).items():
        if not isinstance(src, dict) or not src.get("slo_days") or not src.get("path"):
            continue
        path = root / str(src["path"])
        if path.suffix not in (".yml", ".yaml", ".json") or not path.exists():
            continue
        doc = _load(path) if path.suffix != ".json" else _json(path)
        at = _stamp(doc)
        if at is None:
            continue
        age = (now - at).days
        if age > int(src["slo_days"]):
            out.append(check(f"source {ident}", RISK, f"{age} days old, promised within {src['slo_days']}", f"its writer: {src.get('writer') or 'none declared'}"))
        else:
            out.append(check(f"source {ident}", READY, f"{age} day(s) old"))
    return out


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def local_jobs(root: Path, runner: Callable = core.run) -> list[dict]:
    """This Mac's scheduled jobs from the agent inventory, and whether launchd has each one loaded."""
    inventory = _load(root / "_data" / "agents.yml") or {}
    uid = os.getuid()
    out = []
    for agent in inventory.get("agents") or []:
        if agent.get("kind") != "local-job":
            continue
        label = "com.bamr87." + str(agent.get("id") or "").split(":", 1)[-1]
        r = runner(["launchctl", "print", f"gui/{uid}/{label}"], timeout=15)
        loaded = r.returncode == 0
        out.append({"id": agent.get("id"), "label": label, "trigger": agent.get("trigger"), "loaded": loaded,
                    "installer": agent.get("where"), "state": READY if loaded else OFF})
    return out


def machine_checks(root: Path, cfg: dict, runner: Callable = core.run, offline: bool = False) -> list[dict]:
    out = []
    free = shutil.disk_usage(root).free / 1024 ** 3
    out.append(check("disk", READY if free >= float(cfg["min_disk_gb"]) else RISK, f"{free:.0f} GB free",
                     "" if free >= float(cfg["min_disk_gb"]) else "tools/dash docker fleet; docker system df"))
    out.append(check("claude CLI", READY, "on PATH") if shutil.which("claude") else
               check("claude CLI", RISK, "not on PATH: no local session can run", "install Claude Code"))
    docker = runner(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    out.append(check("docker", READY, f"daemon {docker.stdout.strip()}") if docker.returncode == 0 else
               check("docker", RISK, "the daemon did not answer: the console and the dev stacks are down", "tools/dash up"))
    if not offline:
        who = runner(["gh", "api", "user", "--jq", ".login"], timeout=30)
        out.append(check("GitHub login", READY, f"signed in as {who.stdout.strip()}") if who.returncode == 0 else
                   check("GitHub login", RISK, "gh could not read its own user: every GitHub read this week fails", "gh auth status"))
    return out


def refresh(root: Path, cfg: dict, runner: Callable = core.run) -> list[dict]:
    """Run the refresh list. Only a command in REFRESHABLE runs, with no shell, from the hub root, under
    a time limit; anything else in the config is refused and reported."""
    out = []
    listed = cfg.get("refresh")
    for command in ([listed] if isinstance(listed, str) else listed or []):
        parts = str(command).split()
        if " ".join(parts) not in REFRESHABLE:
            out.append({"command": command, "ok": False, "note": "refused: not one of " + ", ".join(f"`{c}`" for c in REFRESHABLE)})
            continue
        r = runner(parts, cwd=root, timeout=int(cfg["refresh_timeout_s"]))
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        out.append({"command": command, "ok": r.returncode == 0, "note": tail[-1][:160] if tail else ""})
    return out


def build(root: Path, fleet: dict, week: str, now: datetime, *, offline: bool = False, runner: Callable = core.run,
          position: Callable | None = None) -> dict:
    cfg = config(fleet)
    hub = str((fleet.get("hub") or {}).get("repo") or "bamr87/bamr87")
    refreshed = [] if offline else refresh(root, cfg, runner)
    registry = _load(root / "_data" / "harness_registry.yml")
    usage = _load(root / "_data" / "actions_usage.yml")
    live = None if offline else (lambda repo, name: variable_value(repo, name, runner))
    rows = activities(fleet, registry, usage, week, cfg, live)
    checks = (credential_checks(root, week, now) + budget_checks(fleet, registry, position)
              + source_checks(root, fleet, now) + machine_checks(root, cfg, runner, offline))
    jobs = local_jobs(root, runner)
    start, end = week_window(week)
    counts = {s: sum(r["state"] == s for r in rows) for s in (READY, RISK, UNKNOWN, OFF)}
    return {"schema": SCHEMA, "week": week, "window": {"start": start.isoformat(), "end": end.isoformat()},
            "generated_at": now.isoformat(), "refreshed": refreshed, "activities": rows, "counts": counts,
            "calendar": calendar(rows, week, hub), "checks": checks, "local_jobs": jobs,
            "usage_as_of": str((usage or {}).get("generated_at") or "") or None}


def render(doc: dict, cap: int = 25) -> list[str]:
    c = doc["counts"]
    lines = [f"# Ready for {doc['week']}?", "",
             f"> {c[READY]} scheduled activities are ready, {c[RISK]} are at risk, {c[UNKNOWN]} could not be read and {c[OFF]} are switched off. "
             "Nothing was changed: each fix below is yours to run.", ""]
    risky = [r for r in doc["activities"] if r["state"] in (RISK, UNKNOWN)]
    bad = [k for k in doc["checks"] if k["state"] != READY]
    down = [j for j in doc["local_jobs"] if not j["loaded"]]
    lines += ["## Fix before Monday", ""]
    if not (risky or bad or down):
        lines += ["Nothing. Every scheduled activity, credential, budget and source the week needs is in order.", ""]
    for k in bad:
        lines.append(f"- **{k['name']}** ({k['state']}): {k['why']}." + (f" Fix: `{k['fix']}`" if k["fix"] else ""))
    for r in risky[:cap]:
        lines.append(f"- **{r['id']}** ({r['state']}): " + ("; ".join(r["notes"]) or (r["switch"] or {}).get("why") or "no detail") + ".")
    if len(risky) > cap:
        lines.append(f"- and {len(risky) - cap} more in `prepare.json`")
    for j in down:
        lines.append(f"- **{j['label']}** is not loaded on this Mac. It is yours to install: `{j['installer']}`")
    lines += ["", "## The week on the hub", "", "Local time, by local day: the crons are UTC, so west of Greenwich the week's first runs "
              "are on Sunday evening. An activity that is switched off is left out.", ""]
    for day in doc["calendar"]:
        lines.append(f"### {day['name']} {day['date']}")
        lines.append("")
        if not day["hub"]:
            lines.append("- nothing scheduled on the hub")
        seen: dict[str, list[str]] = {}
        for slot in day["hub"]:
            seen.setdefault(slot["id"], []).append(slot["local"].split(" ", 1)[1] + ("" if slot["state"] == READY else f" ({slot['state']})"))
        for ident, times in seen.items():
            lines.append(f"- {ident}: {', '.join(times[:6])}" + (f" and {len(times) - 6} more" if len(times) > 6 else ""))
        if day["fleet"]:
            lines.append(f"- and {day['fleet']} runs across the rest of the fleet")
        lines.append("")
    lines += ["## Checks", "", "| Check | State | Detail |", "| --- | --- | --- |"]
    lines += [f"| {k['name']} | {k['state']} | {k['why']} |" for k in doc["checks"]]
    lines += ["", "## On this Mac", "", "| Job | When | Loaded |", "| --- | --- | --- |"]
    lines += [f"| `{j['label']}` | {str(j['trigger'] or '').split(': ', 1)[-1]} | {'yes' if j['loaded'] else 'no'} |" for j in doc["local_jobs"]]
    if doc["refreshed"]:
        lines += ["", "## Refreshed first", ""]
        lines += [f"- `{r['command']}`: {'ok' if r['ok'] else 'failed'}" + (f" ({r['note']})" if r["note"] else "") for r in doc["refreshed"]]
    if doc.get("usage_as_of"):
        lines += ["", f"Last results are from `_data/actions_usage.yml` as of {str(doc['usage_as_of'])[:16]}."]
    return lines + [""]

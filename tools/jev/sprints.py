#!/usr/bin/env python3
"""
File: tools/jev/sprints.py
Description: The expedite sprint's ceiling and circuit breaker (constitution
             § 27.3, § 27.4 and § 27.6; docs/EXPEDITE-SPRINTS.md; #689).
             `_data/fleet.yml` `budget.sprints` holds each sprint Amr declared
             (Gate A): the work-queue item, the repositories its loops work
             in, an API-equivalent (estimate) dollar ceiling and an appetite in
             hours. This module loads that block and refuses what bounds
             nothing (a cap that is `.inf`, `.nan`, 0 or negative, a ceiling
             above the fleet's monthly one) and a second sprint whose time box
             overlaps another (WIP 1). It sums a sprint's spend from the
             ledgers that already exist, and from the issue pipeline's record
             of the tier caps each of its runs reserved for sprint items
             (`_data/issue_pipeline.yml` `sprint.reservations`), and answers
             the one question every
             loop asks before it spends on a sprint item: `gate()` gives
             nothing, `budget-skip` (the ceiling cannot absorb this attempt's
             full cap, or the time box of the sprint that declared this item
             has closed) or `sprint-off` (the sprint-scope kill switch,
             `vars.EXPEDITE_SPRINT_ENABLED`, is 'false'). A sprint never
             raises a cap: each loop checks its own ceilings as before, and a
             sprint item must fit its sprint's as well.
Author: bamr87
Created: 2026-11-15
Version: 0.1.0
Usage: imported by tools/jev/loop.py (the loop runner), tools/jev/conflicts.py
       (tiers 1 and 2) and, lazily, dash-gen's issue_pipeline.py (the tier
       queues); `tools/dash loop budget` prints the active sprint.
Dependencies: PyYAML; the `gh` CLI only to read the switch on a scheduled
              local run that was not handed its value.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .common import HUB, JevError, finite_usd, gh, is_nwo

#: the sprint-scope kill switch (opt-out: unset arms it, 'false' stops every sprint loop)
SWITCH = "EXPEDITE_SPRINT_ENABLED"
#: § 10.7: every dollar figure here carries this
COST_LABEL = "API-equivalent (estimate)"
BUDGET_SKIP = "budget-skip"
SPRINT_OFF = "sprint-off"
#: the run-record event a tripped breaker leaves behind
STOP_EVENT = "sprint-stop"
#: the committed CI ledger (dash-gen ai_usage_collector); JEV_CI_USAGE points a test elsewhere
CI_USAGE = HUB / "_data" / "ai_usage.yml"
#: the issue pipeline's committed snapshot: `sprint.reservations` holds one row
#: per run that reserved a tier job's cap for a sprint item (dash-gen
#: issue_pipeline.py); JEV_ISSUE_PIPELINE points a test elsewhere
ISSUE_PIPELINE = HUB / "_data" / "issue_pipeline.yml"
KEYS =frozenset({"item", "repos", "usd", "hours", "declared", "ends", "note"})
SLUG_RX = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
#: dash-gen work_queue.KEY_RX, copied because nothing under tools/jev imports
#: dash-gen (tools/test_jev_sprints.py holds the two equal)
WORK_KEY_RX = re.compile(
    r"^(?:"
    r"(?:issue|pr):[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}#\d{1,9}"
    r"|roadmap:FF-\d{4,6}"
    r"|spec:[A-Za-z0-9._-]{1,64}/\d{3}-[a-z0-9][a-z0-9-]{0,80}"
    r"|backlog:[A-Za-z0-9._-]{1,64}/BL-\d{8}-\d{2,3}"
    r")$"
)
REPO_KEY_RX = re.compile(r"(?:issue|pr):(?P<nwo>[^#\s]+)#\d+")
#: a cost_source whose figure is an estimate (ledger.ESTIMATED_SOURCES)
ESTIMATED = frozenset({"estimated", "tokens"})


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(value: object, what: str) -> dt.datetime:
    """A declared instant as an aware UTC time. YAML reads `2026-11-20` as a
    date (midnight UTC here) and an ISO timestamp as a datetime; a time with no
    zone is UTC. Anything else refuses."""
    if isinstance(value, dt.datetime):
        t = value
    elif isinstance(value, dt.date):
        t = dt.datetime(value.year, value.month, value.day)
    elif isinstance(value, str) and value.strip():
        try:
            t = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise JevError(f"{what} must be a date or an ISO time, not {value!r}") from exc
    else:
        raise JevError(f"{what} must be a date or an ISO time, not {value!r}")
    return (t if t.tzinfo else t.replace(tzinfo=dt.UTC)).astimezone(dt.UTC)


def _instant(value: object) -> dt.datetime | None:
    """A ledger row's timestamp, or None when it has none that parses (the
    monthly ceiling skips such a row too)."""
    try:
        return _when(value, "timestamp")
    except JevError:
        return None


def _day(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Sprint:
    """One declared expedite sprint. `ends` is already the earlier of the
    declared end and `declared + hours`: neither field extends the other."""

    slug: str
    item: str
    repos: tuple[str, ...]
    usd: float
    hours: float
    declared: dt.datetime
    ends: dt.datetime

    def active(self, now: dt.datetime) -> bool:
        return self.declared <= now < self.ends

    def closed(self, now: dt.datetime) -> bool:
        return now >= self.ends

    def covers(self, repo: object) -> bool:
        return isinstance(repo, str) and repo.lower() in {r.lower() for r in self.repos}

    def names(self) -> set[str]:
        return {r.split("/", 1)[1].lower() for r in self.repos}

    def within(self, when: object) -> bool:
        t = _instant(when)
        return t is not None and self.declared <= t < self.ends

    def within_day(self, day: object) -> bool:
        """A ledger that records only a day counts every row of a day the time
        box touches: a little early spend is charged, never a little missed."""
        d = _day(day)
        return d is not None and self.declared.date() <= d <= self.ends.date()

    def as_dict(self) -> dict:
        return {"slug": self.slug, "item": self.item, "repos": list(self.repos), "usd": self.usd,
                "hours": self.hours, "declared": iso(self.declared), "ends": iso(self.ends), "label": COST_LABEL}


def monthly_ceiling(fleet: dict) -> float | None:
    """harnesses.budget.monthly_ai_usd when it bounds something, else None
    (test_ai_budget.py fails a fleet whose ceiling does not)."""
    v = (((fleet.get("harnesses") or {}).get("budget") or {}).get("monthly_ai_usd"))
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
    return float(v) if ok else None


def load_sprints(fleet: dict) -> list[Sprint]:
    """`budget.sprints`, validated, oldest first. Refuses (JevError) rather than
    guess: an entry that is not the documented shape, a ceiling or appetite
    that is not a finite number above 0, a ceiling above the fleet's monthly
    one (§ 27.4: a sprint sits inside the caps), an end that is not after the
    declaration, an item that names no repository and lists none, and two
    sprints whose time boxes overlap (WIP 1, § 27.1)."""
    budget = fleet.get("budget") if isinstance(fleet.get("budget"), dict) else {}
    raw = budget.get("sprints")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise JevError(f"_data/fleet.yml budget.sprints must be a mapping of <slug>: {{item, usd, hours, declared}}, "
                       f"not a {type(raw).__name__}")
    ceiling = monthly_ceiling(fleet)
    out: list[Sprint] = []
    for slug, spec in raw.items():
        where = f"_data/fleet.yml budget.sprints.{slug}"
        if not isinstance(slug, str) or not SLUG_RX.fullmatch(slug):
            raise JevError(f"_data/fleet.yml budget.sprints has a key {slug!r} that is not a sprint slug "
                           "(lowercase letters, digits and hyphens)")
        if not isinstance(spec, dict):
            raise JevError(f"{where} must be a mapping, not {spec!r}")
        unknown = sorted(str(k) for k in spec if k not in KEYS)
        if unknown:
            raise JevError(f"{where} has unknown key(s) {', '.join(unknown)}; the shape is item, repos, usd, hours, "
                           "declared, ends, note")
        item = spec.get("item")
        if not isinstance(item, str) or not WORK_KEY_RX.fullmatch(item):
            raise JevError(f"{where}.item must be the _data/work_queue.yml key Amr pinned (issue:<owner>/<repo>#<n>, "
                           f"pr:…, roadmap:FF-NNNN, spec:…, backlog:…), not {item!r}")
        usd = finite_usd(spec.get("usd"), f"{where}.usd (the sprint's {COST_LABEL} ceiling)")
        if ceiling is not None and usd > ceiling:
            raise JevError(f"{where}.usd ${usd:g} is above harnesses.budget.monthly_ai_usd ${ceiling:g}: a sprint "
                           "ceiling sits inside the fleet's caps and never raises them (constitution § 27.4)")
        hours = finite_usd(spec.get("hours"), f"{where}.hours (the sprint's appetite, in hours)")
        declared = _when(spec.get("declared"), f"{where}.declared")
        try:
            box = declared + dt.timedelta(hours=hours)
        except OverflowError as exc:
            raise JevError(f"{where}.hours {hours:g} runs past any calendar") from exc
        ends = box if spec.get("ends") is None else _when(spec["ends"], f"{where}.ends")
        if ends <= declared:
            raise JevError(f"{where}.ends ({iso(ends)}) is not after its declaration ({iso(declared)})")
        repos = spec.get("repos")
        if repos is None:
            m = REPO_KEY_RX.fullmatch(item)
            if not m or not is_nwo(m.group("nwo")):
                raise JevError(f"{where}.item {item!r} names no repository: list the repos its loops work in "
                               "(repos: [owner/repo, …])")
            names: tuple[str, ...] = (m.group("nwo"),)
        elif isinstance(repos, list) and repos and all(is_nwo(r) for r in repos):
            names = tuple(dict.fromkeys(str(r) for r in repos))
        else:
            raise JevError(f"{where}.repos must be a non-empty list of owner/repo, not {repos!r}")
        out.append(Sprint(slug=slug, item=item, repos=names, usd=usd, hours=hours, declared=declared,
                          ends=min(ends, box)))
    out.sort(key=lambda s: s.declared)
    for a, b in zip(out, out[1:]):
        if b.declared < a.ends:
            raise JevError(f"_data/fleet.yml budget.sprints: {a.slug} ({iso(a.declared)} to {iso(a.ends)}) and "
                           f"{b.slug} ({iso(b.declared)} to {iso(b.ends)}) overlap; at most one expedite sprint is "
                           "active fleet-wide (WIP 1, constitution § 27.1): end the first before the next begins")
    return out


def active(sprints: Iterable[Sprint], now: dt.datetime) -> Sprint | None:
    return next((s for s in sprints if s.active(now)), None)


def for_repo(sprints: Iterable[Sprint], repo: object, now: dt.datetime) -> Sprint | None:
    """The active sprint whose loops work in `repo`: every loop attempt there,
    inside its time box, is sprint work."""
    s = active(sprints, now)
    return s if s is not None and s.covers(repo) else None


def holding(sprints: Iterable[Sprint], key: str | None, now: dt.datetime) -> Sprint | None:
    """The latest closed sprint that declared `key`: its circuit breaker keeps
    that item stopped until a new declaration (§ 27.3, never extended)."""
    if not key:
        return None
    for s in reversed(list(sprints)):
        if s.closed(now) and s.item.lower() == key.lower():
            return s
    return None


# --------------------------------------------------------------------------- #
# spend, from the ledgers that already exist
# --------------------------------------------------------------------------- #
@dataclass
class Spend:
    spent_usd: float = 0.0
    estimated_usd: float = 0.0
    by_source: dict[str, float] = field(default_factory=dict)

    def add(self, source: str, cost: float, estimated: bool) -> None:
        self.spent_usd = round(self.spent_usd + cost, 4)
        if estimated:
            self.estimated_usd = round(self.estimated_usd + cost, 4)
        self.by_source[source] = round(self.by_source.get(source, 0.0) + cost, 4)

    def summary(self, sprint: Sprint) -> str:
        share = f" ({self.estimated_usd:.2f} estimated)" if self.estimated_usd else ""
        return f"${self.spent_usd:.2f}{share} of ${sprint.usd:.2f} spent ({COST_LABEL})"

    def as_dict(self) -> dict:
        return {"spent_usd": self.spent_usd, "estimated_usd": self.estimated_usd, "by_source": dict(self.by_source),
                "label": COST_LABEL}


def ai_ledger_path() -> Path:
    """The AI ledger ai-run writes (loop.ledger_path; tools/test_jev_sprints.py holds them equal)."""
    return Path(os.environ.get("DASH_AI_LEDGER") or "~/.claude/ai-activity-ledger.json").expanduser()


def ci_rows(path: Path | None = None) -> list[dict]:
    """`_data/ai_usage.yml` `ci_ledger`: one row per CI run, by repository name
    and day. A missing file is no rows; one that cannot be read refuses."""
    p = path or Path(os.environ.get("JEV_CI_USAGE") or CI_USAGE)
    if not p.is_file():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise JevError(f"{p} cannot be read ({exc}); the sprint ceiling cannot be judged") from exc
    rows = data.get("ci_ledger") if isinstance(data, dict) else None
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise JevError(f"{p} has a `ci_ledger` that is not a list; the sprint ceiling cannot be judged")
    return [r for r in rows if isinstance(r, dict)]


def _ci_cost(row: dict, p: str) -> float:
    raw = row.get("cost_usd")
    if raw is None:
        return 0.0
    try:
        cost = float(raw)
    except (TypeError, ValueError):
        cost = math.nan
    if isinstance(raw, bool) or not math.isfinite(cost) or cost < 0:
        raise JevError(f"{p} has a run ({row.get('url') or row.get('repo')}) whose cost_usd {raw!r} is not a finite "
                       "figure of 0 or more; the sprint ceiling cannot be judged")
    return cost


def pipeline_rows(path: Path | None = None, *, text: str | None = None, where: str | None = None) -> list[dict]:
    """The issue pipeline's record of its runs' sprint reservations: the
    `sprint.reservations` rows of its snapshot, read from `path` (default
    `_data/issue_pipeline.yml`, or JEV_ISSUE_PIPELINE) or from `text` (the same
    file as another branch holds it). A missing file or block is no rows; one
    that cannot be read refuses, as an unreadable ledger does."""
    if text is None:
        p = path or Path(os.environ.get("JEV_ISSUE_PIPELINE") or ISSUE_PIPELINE)
        where = where or str(p)
        if not p.is_file():
            return []
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise JevError(f"{where} cannot be read ({exc}); the sprint ceiling cannot be judged") from exc
    where = where or "the issue pipeline snapshot"
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise JevError(f"{where} cannot be read ({exc}); the sprint ceiling cannot be judged") from exc
    block = data.get("sprint") if isinstance(data, dict) else None
    if block is None:
        return []
    if not isinstance(block, dict):
        raise JevError(f"{where} has a `sprint` block that is not a mapping; the sprint ceiling cannot be judged")
    rows = block.get("reservations")
    if rows is None:
        return []
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise JevError(f"{where} has a `sprint.reservations` that is not a list of runs; the sprint ceiling cannot "
                       "be judged")
    return rows


def reservation(sprint: Sprint, *, run: str, at: dt.datetime, tiers: Mapping[str, float]) -> dict:
    """One issue-pipeline run's row in `sprint.reservations`: the full cap of
    each tier job it let run a sprint item, which every later attempt on the
    sprint counts as estimated spend (`pipeline_spend`)."""
    return {"run": str(run), "at": iso(at), "sprint": sprint.slug, "declared": iso(sprint.declared),
            "usd": round(sum(float(v) for v in tiers.values()), 4),
            "tiers": {k: float(v) for k, v in tiers.items()}, "label": COST_LABEL}


def of_sprint(row: Mapping, sprint: Sprint) -> bool:
    """A reservation row made under this declaration (its slug and declared
    time): a re-declared slug starts from nothing."""
    return row.get("sprint") == sprint.slug and _instant(row.get("declared")) == sprint.declared


def pipeline_spend(sprint: Sprint, rows: Iterable[dict]) -> float:
    """What the issue pipeline's runs reserved for `sprint` inside its time box
    (rows of this declaration only, one per run). A tier job batches several
    issues in one hub session, so no ledger attributes its cost to one item:
    the full cap it was allowed is the estimate, and it errs high. A row of
    this sprint that cannot be read refuses."""
    total, seen = 0.0, set()
    for r in rows:
        if not of_sprint(r, sprint):
            continue
        run = str(r.get("run") or "")
        at = _instant(r.get("at"))
        raw = r.get("usd")
        try:
            usd = float(raw)
        except (TypeError, ValueError):
            usd = math.nan
        if not run or at is None or isinstance(raw, bool) or not math.isfinite(usd) or usd < 0:
            raise JevError(f"the issue pipeline's sprint.reservations has a row ({r!r}) without a run, a time and a "
                           "finite figure of 0 or more; the sprint ceiling cannot be judged")
        if run in seen or not sprint.within(at):
            continue
        seen.add(run)
        total += usd
    return round(total, 4)


def spend(sprint: Sprint, *, ai_ledger: Path | None = None, jev=None, ci: Iterable[dict] | None = None,
          pipeline: Iterable[dict] | None = None, hub: str = "bamr87/bamr87",
          extra: Iterable[tuple[float, str | None]] = ()) -> Spend:
    """What `sprint` has spent inside its time box, from every ledger it is
    handed: the local loop runner's attempts in the AI ledger (and the
    engine's unledgered charges) on a sprint repository; JEV's conflict
    attempts (`jev`, a ledger.Ledger) on one; the CI runs of a sprint
    repository's own workflows (`ci`, ai_usage.yml rows); and the tier caps the
    issue pipeline's runs reserved for sprint items (`pipeline`, its
    `sprint.reservations` rows, an estimate). The hub's CI rows are never
    attributed: its workflows run fleet-wide loops, and the issue pipeline's
    share of them is its reservations. `extra` is a run's own charges no
    ledger holds yet, counted whole. An unreadable figure refuses, as the
    monthly ceilings do."""
    total = Spend()
    if ai_ledger is not None:
        from . import loop as engine   # lazily: loop imports this module
        spent, estimated = engine.local_spend(
            lambda r: sprint.covers(r.get("repo")) and sprint.within(r.get("timestamp")), ai_ledger)
        if spent:
            total.add("loops", round(spent - estimated, 4), False)
            if estimated:
                total.add("loops", estimated, True)
    if jev is not None:
        for r in jev.resolutions:
            if sprint.covers(r.get("repo")) and sprint.within_day(r.get("date")):
                total.add("jev", jev._cost(r), str(r.get("cost_source")) in ESTIMATED)
    if ci is not None:
        hub_name = hub.split("/")[-1].lower()
        names = sprint.names() - {hub_name}
        where = str(os.environ.get("JEV_CI_USAGE") or CI_USAGE)
        for r in ci:
            if str(r.get("repo") or "").lower() in names and sprint.within_day(r.get("day")):
                total.add("ci", _ci_cost(r, where), str(r.get("cost_source")) in ESTIMATED)
    if pipeline is not None:
        reserved = pipeline_spend(sprint, pipeline)
        if reserved:
            total.add("issue-pipeline", reserved, True)
    for cost, source in extra:
        total.add("unledgered", float(cost), source == "estimated")
    return total


# --------------------------------------------------------------------------- #
# the switch and the gate
# --------------------------------------------------------------------------- #
def read_switch(*, scheduled: bool, reader: Callable[[], str | None] | None = None,
                env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """(armed, why) for the sprint-scope switch, read the way CI reads a § 17
    switch: opt-out (unset arms it), a case-blind 'false' trips it, and a
    manual run bypasses it as a workflow_dispatch does. A workflow hands the
    value in `EXPEDITE_SPRINT_ENABLED` (empty is unset); otherwise `reader`
    (`gh variable get`) reads it, and one that fails refuses rather than
    guesses."""
    if not scheduled:
        return True, f"a manual run bypasses vars.{SWITCH}, as a workflow_dispatch does"
    env = os.environ if env is None else env
    if SWITCH in env:
        value = env[SWITCH] or None
    elif reader is not None:
        try:
            value = reader()
        except JevError as exc:
            return False, (f"vars.{SWITCH} cannot be read ({exc}); a scheduled sprint attempt refuses rather than "
                           "guess its switch")
    else:
        value = None
    if value is not None and value.strip().lower() == "false":
        return False, f"switched off: vars.{SWITCH} is {value!r}, which stops every sprint loop (constitution § 27.6)"
    return True, f"vars.{SWITCH} is {value!r} (opt-out: armed unless 'false')"


def gh_reader(hub: str) -> Callable[[], str | None]:
    """`gh variable get` for the switch: the value, None when it is unset (and
    the hub is readable), JevError when it cannot be told."""
    def read() -> str | None:
        res = gh(["variable", "get", SWITCH, "-R", hub])
        if res.ok:
            return res.out.strip()
        if "not found" in (res.err or "").lower():
            # gh says "not found" for any 404, a repository this auth cannot see too
            if not gh(["api", f"repos/{hub}", "--jq", ".full_name"]).ok:
                raise JevError(f"it reads as not found, but {hub} is not readable with this gh auth")
            return None
        raise JevError((res.err or res.out).strip()[-200:] or f"gh exited {res.code}")
    return read


def once(fn: Callable[[], tuple[bool, str]]) -> Callable[[], tuple[bool, str]]:
    """The switch, read once per run however many sprint items ask."""
    memo: list[tuple[bool, str]] = []

    def call() -> tuple[bool, str]:
        if not memo:
            memo.append(fn())
        return memo[0]
    return call


@dataclass(frozen=True)
class Verdict:
    decision: str            # budget-skip | sprint-off
    reason: str
    sprint: Sprint
    spend: Spend | None = None

    def event(self, now: dt.datetime) -> dict:
        """The stop event a loop appends to its run record (and #691's record will carry)."""
        return {"event": STOP_EVENT if self.decision == BUDGET_SKIP else SPRINT_OFF, "sprint": self.sprint.slug,
                "item": self.sprint.item, "decision": self.decision, "reason": self.reason, "at": iso(now),
                "cap_usd": self.sprint.usd, "spent_usd": self.spend.spent_usd if self.spend else None,
                "estimated_usd": self.spend.estimated_usd if self.spend else None, "label": COST_LABEL}


def switched_off(sprints: list[Sprint], *, repo: object, now: dt.datetime,
                 switch: Callable[[], tuple[bool, str]]) -> Verdict | None:
    """`sprint-off` for an item of the active sprint while its switch is off,
    else None. Read before anything a loop does on the item, its $0 tier 0
    included: a kill switch stops the loop, not only its spend."""
    s = for_repo(sprints, repo, now)
    if s is None:
        return None
    armed, why = switch()
    return None if armed else Verdict(SPRINT_OFF, f"sprint {s.slug}: {why}", s)


def gate(sprints: list[Sprint], *, repo: object, now: dt.datetime, cost_usd: float | None,
         spend_of: Callable[[Sprint], Spend], switch: Callable[[], tuple[bool, str]] | None = None,
         key: str | None = None) -> Verdict | None:
    """The question a loop asks before it spends on an item: None when no
    sprint holds it. On an item of the active sprint: `sprint-off` while the
    switch is off, then `budget-skip` when the sprint's spend plus this
    attempt's full cap (`cost_usd`; None asks only the switch) would cross its
    ceiling. On the item a closed sprint declared (`key`, a work-queue key):
    `budget-skip`, until a new declaration."""
    s = for_repo(sprints, repo, now)
    if s is None:
        held = holding(sprints, key, now)
        if held is None:
            return None
        return Verdict(BUDGET_SKIP, f"sprint {held.slug}: its time box closed at {iso(held.ends)}; the circuit "
                                    "breaker stopped it and nothing extends it but a new declaration in "
                                    "budget.sprints (constitution § 27.3)", held)
    if switch is not None:
        armed, why = switch()
        if not armed:
            return Verdict(SPRINT_OFF, f"sprint {s.slug}: {why}", s)
    if cost_usd is None:
        return None
    spent = spend_of(s)
    if spent.spent_usd + cost_usd > s.usd:
        return Verdict(BUDGET_SKIP, f"sprint {s.slug} ceiling: {spent.summary(s)}; this attempt may cost up to "
                                    f"${cost_usd:g}, so the circuit breaker stops the sprint (constitution § 27.3)",
                       s, spent)
    return None

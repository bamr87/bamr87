#!/usr/bin/env python3
"""
File: tools/jev/ledger.py
Description: JEV's spend ledger — `_data/jev_resolutions.yml`. One append-only
             record per resolution attempt (repo, pull request, tier, model,
             outcome, cost, and whether that cost was reported or estimated),
             plus the month-to-date arithmetic the monthly cap and the
             scheduled-run stop are judged on.
             The fleet's wider Claude accounting (docs/AI-INTEGRATION.md) reads
             the same records under the call site `jev-conflicts`.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage: imported by tools/jev/conflicts.py; `python3 -m tools.jev conflicts budget`
       prints the month-to-date position.
Dependencies: PyYAML.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .common import HUB, JevConfig

LEDGER_PATH = HUB / "_data" / "jev_resolutions.yml"
SCHEMA = "jev-resolutions/v1"
CALL_SITE = "jev-conflicts"

#: Costs JEV did not measure are still spend. A record whose `cost_source` is
#: one of these carries an estimate, and every aggregate reports the estimated
#: share separately — the lesson of the fleet ledger reading 87% of its runs as
#: free (HUB-032, NFR10).
ESTIMATED_SOURCES = frozenset({"estimated", "tokens"})


@dataclass
class Resolution:
    """One attempt. Written whether it succeeded, failed or was only triaged."""

    repo: str
    pr: int
    tier: str
    outcome: str                      # resolved | failed | escalated | triaged | dry-run
    date: str = ""
    model: str = ""
    cost_usd: float = 0.0
    cost_source: str = "reported"     # reported | estimated | tokens | no-spend
    files: int = 0
    lines: int = 0
    reason: str = ""
    call_site: str = CALL_SITE

    def __post_init__(self) -> None:
        if not self.date:
            self.date = _dt.date.today().isoformat()

    @property
    def month(self) -> str:
        return self.date[:7]


@dataclass
class Ledger:
    """The committed file, loaded. Append-only: nothing here ever edits a row."""

    path: Path = LEDGER_PATH
    schema: str = SCHEMA
    resolutions: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Ledger:
        p = path or LEDGER_PATH
        if not p.is_file():
            return cls(path=p)
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(path=p, schema=str(data.get("schema") or SCHEMA),
                   resolutions=[r for r in (data.get("resolutions") or []) if isinstance(r, dict)])

    def append(self, record: Resolution) -> None:
        self.resolutions.append({k: v for k, v in asdict(record).items() if v != ""})

    def month_total(self, month: str | None = None) -> float:
        m = month or _dt.date.today().strftime("%Y-%m")
        return round(sum(float(r.get("cost_usd") or 0)
                         for r in self.resolutions if str(r.get("date", ""))[:7] == m), 4)

    def month_estimated(self, month: str | None = None) -> float:
        m = month or _dt.date.today().strftime("%Y-%m")
        return round(sum(float(r.get("cost_usd") or 0) for r in self.resolutions
                         if str(r.get("date", ""))[:7] == m
                         and str(r.get("cost_source")) in ESTIMATED_SOURCES), 4)

    def attempts(self, repo: str, pr: int) -> int:
        """How many times JEV has already TRIED to resolve this pull request.

        A triage-only row is not an attempt — otherwise simply looking at a
        pull request twice would exhaust its retry budget and hand it to a
        human who has nothing new to look at.
        """
        return sum(1 for r in self.resolutions
                   if r.get("repo") == repo and int(r.get("pr") or 0) == pr
                   and str(r.get("outcome")) in ("resolved", "failed"))

    def save(self) -> None:
        body = {
            "schema": self.schema,
            "call_site": CALL_SITE,
            "generated": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resolutions": self.resolutions,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "# _data/jev_resolutions.yml — JEV's conflict-resolution ledger (schema "
            f"{SCHEMA}).\n"
            "# Append-only, one row per attempt; written by tools/jev/conflicts.py and\n"
            "# published by .github/workflows/jev-conflicts.yml. Holds no secret and no\n"
            "# diff — only what was attempted, at which tier, and what it cost.\n"
            "# The monthly cap lives in _data/fleet.yml budget.jev (docs/JEV.md).\n"
            + yaml.safe_dump(body, sort_keys=False, width=100, allow_unicode=True),
            encoding="utf-8")


@dataclass
class BudgetState:
    """Where the month stands against the cap — the one thing a run asks first."""

    month: str
    spent_usd: float
    estimated_usd: float
    cap_usd: float
    stop_usd: float
    scheduled: bool

    @property
    def remaining_usd(self) -> float:
        return round(max(0.0, self.cap_usd - self.spent_usd), 4)

    @property
    def ceiling_usd(self) -> float:
        """The ceiling THIS run is held to: the stop line on a schedule, the cap by hand."""
        return self.stop_usd if self.scheduled else self.cap_usd

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.ceiling_usd

    def affords(self, usd: float) -> bool:
        return self.spent_usd + usd <= self.ceiling_usd

    def summary(self) -> str:
        share = f" ({self.estimated_usd:.2f} estimated)" if self.estimated_usd else ""
        return (f"{self.month}: ${self.spent_usd:.2f}{share} of ${self.cap_usd:.2f} spent; "
                f"this run stops at ${self.ceiling_usd:.2f}"
                f"{' — EXHAUSTED' if self.exhausted else ''}")


def budget_state(cfg: JevConfig, ledger: Ledger, *, scheduled: bool,
                 month: str | None = None) -> BudgetState:
    m = month or _dt.date.today().strftime("%Y-%m")
    return BudgetState(month=m, spent_usd=ledger.month_total(m),
                       estimated_usd=ledger.month_estimated(m),
                       cap_usd=cfg.monthly_usd, stop_usd=cfg.monthly_stop_usd,
                       scheduled=scheduled)

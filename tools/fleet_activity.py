#!/usr/bin/env python3
"""
File: tools/fleet_activity.py
Purpose: thin, fire-and-forget emit wrapper for the FLEET ACTIVITY LOG.

The event schema and write path are the ones proposed in the fleet activity
log PRD (bamr87/bamr87#409, docs/prd/FLEET-ACTIVITY-LOG.md, FR7-FR14,
NFR4-NFR6). Until that log store exists, this module is the producer half:

  * emit() appends one JSON line to a local, bounded spool (the queue file)
    and returns immediately. It NEVER raises into the caller (NFR4): any
    error is swallowed and counted in ``Activity.errors``.
  * flush() is best-effort: when FLEET_ACTIVITY_ENDPOINT is set (and not in
    dry-run) it POSTs the spool as one JSON batch with a short timeout; on any
    failure the spool is kept for the next run. ``event_id`` makes ingestion
    idempotent (at-least-once).
  * free text is redacted against known token patterns before spooling (NFR6).
  * the spool is bounded; on overflow the oldest events are dropped and a
    ``dropped`` counter event records the loss (NFR5).

Event fields: event_id, ts (UTC), bot_id, repo, task_ref, run_id, event_type
(start|finish|declined|blocked_handoff|retry), standard_version,
standard_source, decision, outcome (success|failure|skipped|pending|unknown),
detail (JSON), amendments ([{amendment, repo, relation}] — the
fleet_event_amendment rows, FR9).

Stdlib only. Used by tools/backlog_fanout.py; reusable by any lane.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = {"start", "finish", "declined", "blocked_handoff", "retry"}
OUTCOMES = {"success", "failure", "skipped", "pending", "unknown"}
DEFAULT_MAX_EVENTS = 5000

_SECRET_RX = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{16,})"
)
_KIT_RX = re.compile(r"<!--\s*kit:\s*([a-z0-9-]+)\s+v([0-9][0-9A-Za-z.\-]*)")


def redact(value):
    """Recursively replace token-shaped substrings with [REDACTED]."""
    if isinstance(value, str):
        return _SECRET_RX.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def standard_version(agents_md_text: str | None) -> str:
    """The standard a repo declares in its AGENTS.md kit stamp (FR8).

    ``<!-- kit: sdlc v0.1.0 ...`` → ``sdlc v0.1.0``; absent → ``unknown``
    (which is itself a drift row in the PRD's drift query).
    """
    if not agents_md_text:
        return "unknown"
    m = _KIT_RX.search(agents_md_text)
    return f"{m.group(1)} v{m.group(2)}" if m else "unknown"


def default_queue() -> Path:
    if os.environ.get("FLEET_ACTIVITY_QUEUE"):
        return Path(os.environ["FLEET_ACTIVITY_QUEUE"])
    base = os.environ.get("RUNNER_TEMP") or "/tmp"
    return Path(base) / "fleet-activity" / "queue.jsonl"


class Activity:
    """One run's emitter. All public methods are no-throw."""

    def __init__(self, bot_id: str, *, queue: Path | str | None = None,
                 run_id: str | None = None, dry_run: bool = True,
                 endpoint: str | None = None,
                 max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self.bot_id = bot_id
        self.queue = Path(queue) if queue else default_queue()
        self.run_id = run_id or os.environ.get("GITHUB_RUN_ID") or uuid.uuid4().hex[:12]
        self.dry_run = dry_run
        self.endpoint = endpoint if endpoint is not None else os.environ.get("FLEET_ACTIVITY_ENDPOINT", "")
        self.max_events = max_events
        self.emitted = 0
        self.errors = 0

    # ------------------------------------------------------------------ emit
    def emit(self, event_type: str, *, repo: str, task_ref: str, decision: str,
             outcome: str = "unknown", standard: str = "unknown",
             standard_source: str = "", detail: dict | None = None,
             amendments: list[dict] | None = None) -> dict | None:
        try:
            ev = {
                "event_id": str(uuid.uuid4()),
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "bot_id": self.bot_id,
                "repo": repo,
                "task_ref": task_ref,
                "run_id": self.run_id,
                "event_type": event_type if event_type in EVENT_TYPES else "finish",
                "standard_version": standard or "unknown",
                "standard_source": standard_source,
                "decision": decision,
                "outcome": outcome if outcome in OUTCOMES else "unknown",
                "detail": detail or {},
                "amendments": amendments or [],
                "dry_run": self.dry_run,
            }
            ev = redact(ev)
            self._append(ev)
            self.emitted += 1
            return ev
        except Exception:  # NFR4: logging never fails the work
            self.errors += 1
            return None

    def _append(self, ev: dict) -> None:
        self.queue.parent.mkdir(parents=True, exist_ok=True)
        with self.queue.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")
        self._bound()

    def _bound(self) -> None:
        lines = self.queue.read_text(encoding="utf-8").splitlines()
        if len(lines) <= self.max_events:
            return
        dropped = len(lines) - (self.max_events - 1)
        keep = lines[dropped:]
        marker = {
            "event_id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bot_id": self.bot_id, "repo": "", "task_ref": "", "run_id": self.run_id,
            "event_type": "finish", "standard_version": "unknown", "standard_source": "",
            "decision": "spool overflow", "outcome": "unknown",
            "detail": {"dropped": dropped}, "amendments": [], "dry_run": self.dry_run,
        }
        self.queue.write_text("\n".join(keep + [json.dumps(marker, sort_keys=True)]) + "\n",
                              encoding="utf-8")

    # ----------------------------------------------------------------- flush
    def flush(self, timeout: float = 3.0) -> str:
        """Best-effort ship of the spool. Returns a status word; never raises.

        ``kept-dry-run``  dry run: events stay in the local queue only
        ``kept-no-endpoint``  no FLEET_ACTIVITY_ENDPOINT configured (today's default)
        ``flushed``  the store accepted the batch; the spool was truncated
        ``kept-unavailable``  the store was down/slow/refused; spool kept
        """
        try:
            if self.dry_run:
                return "kept-dry-run"
            if not self.endpoint:
                return "kept-no-endpoint"
            if not self.queue.exists():
                return "flushed"
            import urllib.request
            body = "[" + ",".join(l for l in self.queue.read_text(encoding="utf-8").splitlines() if l.strip()) + "]"
            req = urllib.request.Request(self.endpoint, data=body.encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (operator-set URL)
                if 200 <= resp.status < 300:
                    self.queue.write_text("", encoding="utf-8")
                    return "flushed"
            return "kept-unavailable"
        except Exception:
            self.errors += 1
            return "kept-unavailable"

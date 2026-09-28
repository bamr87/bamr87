"""
Fleet JSON logging for __PROJECT_NAME__ — kit: elk v__KIT_VERSION__

UPS-OPS-10 emission plus the UPS-OPS-12 redaction filter, in one stdlib-only
module. No dependency: a logging adapter that needs a package is an adapter
half the fleet will not install.

    from fleet_logging import configure
    configure()                     # LOG_LEVEL / LOG_FORMAT from the environment
    log = logging.getLogger(__name__)
    log.info("served", extra={"request_id": rid, "path": path, "status": 200})

Emits one JSON object per line with the fields the spec names — ts, level, msg,
logger, request_id, app, version — which is exactly what the fleet log plane
routes to the `fleet.app` dataset. A line missing `level` or `msg` still ships,
but as raw container chatter with two weeks of retention instead of a month.

The redaction filter is attached here rather than left to the ingest pipeline
on purpose: it has to hold when this repo is run standalone, where the hub's
central Logstash filter is not in the path at all.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time

# The fleet's credential shapes (_data/fleet.yml `observability.logs.redact`).
# Redacting at emission means the secret never reaches a file, a terminal
# scrollback or a container log — not merely never reaches the index.
REDACTIONS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]+"), "github_pat_[REDACTED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh?_[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{20,}"), "AIza[REDACTED]"),
    (re.compile(r"(?i)\b(authorization|api[-_]?key|password|secret|token)\b\s*[:=]\s*\S+",),
     r"\1: [REDACTED]"),
]

# Everything LogRecord carries that is not ours to emit.
_STD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


def scrub(text: str) -> str:
    for rx, repl in REDACTIONS:
        text = rx.sub(repl, text)
    return text


class FleetJsonFormatter(logging.Formatter):
    """One JSON object per line, ISO-8601 UTC, with `extra=` merged in."""

    def __init__(self, app: str, version: str) -> None:
        super().__init__()
        self.app, self.version = app, version

    def format(self, record: logging.LogRecord) -> str:
        doc = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "msg": scrub(record.getMessage()),
            "logger": record.name,
            "app": self.app,
            "version": self.version,
        }
        if record.exc_info:
            doc["error"] = scrub(self.formatException(record.exc_info))
        for key, value in vars(record).items():
            if key not in _STD and not key.startswith("_"):
                doc[key] = scrub(value) if isinstance(value, str) else value
        return json.dumps(doc, default=str)


class FleetTextFormatter(logging.Formatter):
    """Human format for a terminal. Redacted too — a secret in a dev log is
    still a secret in a scrollback, a screenshot and a bug report."""

    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


def configure(app: str | None = None, version: str | None = None,
              stream=None) -> logging.Logger:
    """Install the fleet handler on the root logger.

    JSON unless LOG_FORMAT says otherwise, and JSON by default whenever
    APP_ENV is production — a container whose logs are not machine-readable is
    a container the log plane can only store, not answer questions about.
    """
    app = app or os.environ.get("APP_NAME") or "__PROJECT_NAME__"
    version = version or os.environ.get("GIT_SHA") or os.environ.get("APP_VERSION") or "dev"
    fmt = (os.environ.get("LOG_FORMAT") or
           ("json" if os.environ.get("APP_ENV") == "production" else "text")).lower()
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        FleetJsonFormatter(app, version) if fmt == "json"
        else FleetTextFormatter("%(asctime)s %(levelname)-5s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    return root

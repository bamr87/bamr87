"""
backend.views — the health endpoints (UPS-BE-10, UPS-BE-11) under /api/v1/.

  /api/v1/healthz   liveness: 200 {"status": "ok"}, touches nothing
  /api/v1/readyz    readiness: the database answers and every migration is
                    applied → 200 {"status": "ok", "checks": {...}}, else 503
                    {"status": "degraded", ...}
  /api/v1/version   {"name", "version", "commit", "built_at"}

All three are unauthenticated and uncached: the dispatcher exempts exactly
these paths from DASH_CONSOLE_TOKEN (never from the Host check), so a
healthcheck needs no secret. A failure is reported as a word, not as the
driver's message, and the message goes to the log only.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

log = logging.getLogger("console.backend")

NAME = "bamr87-harness-console"


@never_cache
@require_safe
def healthz(request):
    return JsonResponse({"status": "ok"})


@never_cache
@require_safe
def readyz(request):
    checks = {"db": "ok", "migrations": "unknown"}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except (DatabaseError, ImproperlyConfigured) as exc:
        log.warning("readyz: the database did not answer: %s: %s", type(exc).__name__, exc)
        checks["db"] = "unreachable"
    if checks["db"] == "ok":
        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except DatabaseError as exc:
            log.warning("readyz: could not read the migration state: %s: %s", type(exc).__name__, exc)
        else:
            checks["migrations"] = "pending" if pending else "ok"
    ok = all(v == "ok" for v in checks.values())
    return JsonResponse({"status": "ok" if ok else "degraded", "checks": checks}, status=200 if ok else 503)


@lru_cache(maxsize=1)
def _release() -> str | None:
    """The newest released version in the hub's CHANGELOG.md (`## [2.1.0] - …`)."""
    try:
        text = (settings.REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
    return m.group(1) if m else None


@lru_cache(maxsize=1)
def _commit() -> str | None:
    """GIT_SHA (the fleet's build variable), else the checkout's HEAD — read once, at the first call."""
    sha = (os.environ.get("GIT_SHA") or "").strip()
    if sha:
        return sha
    try:
        out = subprocess.run(["git", "-C", str(settings.REPO_ROOT), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("version: git rev-parse failed: %s", exc)
        return None
    return out.stdout.strip() or None


@never_cache
@require_safe
def version(request):
    return JsonResponse({"name": NAME, "version": _release(), "commit": _commit(),
                         "built_at": (os.environ.get("BUILT_AT") or "").strip() or None})

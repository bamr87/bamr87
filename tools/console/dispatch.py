#!/usr/bin/env python3
"""
dispatch — the Harness Console's ASGI entry point: one process, one port, two
frameworks while the backend moves to Django (ADR 0006 decision 4, phase B1).

    /admin/, /accounts/, /api/v1/   the Django project in backend/
    everything else                 the FastAPI app in app.py, untouched: its
                                    middleware, every route, the page
                                    fallback, the Terminal WebSocket and the
                                    startup lifespan

run.sh and serve.py serve `dispatch:app`; `uvicorn app:app` still serves the
FastAPI half alone, and the public snapshot (snapshot.py) never imports this
module, so the site builds with Django absent.

The Django side gets the console's own guards before Django sees a request,
with the very functions app.py's routes use: the Host allowlist
(app.host_refusal → 421, the DNS-rebinding guard) on every path, and the
DASH_CONSOLE_TOKEN bearer check (app.token_ok → 401) on every path except the
three health endpoints, so a healthcheck needs no secret. Every response it
sends carries the console's Content-Security-Policy (app.content_policy); the
admin is built from external scripts and stylesheets, so `script-src 'self'`
holds there too. Referrer-Policy stays Django's `same-origin`, not the page's
`no-referrer`: under `no-referrer` a browser sends `Origin: null` with a form
POST and Django's CSRF check refuses the admin's own login.

The admin's static files are served here, from the installed Django package,
at /admin/static/ (settings.STATIC_URL), behind the same guards. A WebSocket
to a Django path is closed: none is routed there.

When Django is not installed or its settings refuse to load (no
DJANGO_SECRET_KEY off loopback, an unsupported DATABASE_URL), the console
starts anyway: the FastAPI half serves as before and the Django paths answer
503 with the reason, which is printed once at startup too. Never a secret: the
reasons name a variable or a scheme, never a value.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketClose

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as console  # noqa: E402

PREFIXES = ("/admin/", "/accounts/", "/api/v1/")
# Exempt from the bearer token, never from the Host check. Exact paths only.
HEALTH = frozenset({"/api/v1/healthz", "/api/v1/readyz", "/api/v1/version"})
STATIC_PREFIX = "/admin/static"


def is_django(path: str) -> bool:
    """True for a path the Django side answers: under a prefix, or the prefix without its slash
    (Django then redirects /admin to /admin/)."""
    return any(path.startswith(p) or path == p[:-1] for p in PREFIXES)


def load_django() -> tuple[ASGIApp | None, ASGIApp | None, str | None]:
    """(Django's ASGI handler, the admin's static files, None), or (None, None, why not)."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    try:
        from django.core.asgi import get_asgi_application
        from django.core.exceptions import ImproperlyConfigured
    except ImportError as exc:
        return None, None, (f"Django is not installed ({exc.name}): tools/console/run.sh installs "
                            "tools/console/requirements.txt")
    try:
        handler = get_asgi_application()
    except ImproperlyConfigured as exc:
        return None, None, f"the Django backend is not configured: {exc}"
    # A Starlette app, not a bare Mount: its exception middleware turns a missing file into a 404.
    static = Starlette(routes=[Mount(STATIC_PREFIX, app=StaticFiles(packages=[("django.contrib.admin", "static")]))])
    return handler, static, None


DJANGO, STATIC, UNAVAILABLE = load_django()
if UNAVAILABLE:
    print(f"console: /admin/, /accounts/ and /api/v1/ are off: {UNAVAILABLE}", file=sys.stderr, flush=True)
else:
    from django.conf import settings as _settings

    from backend.settings import describe_database

    print(f"console: Django backend on {describe_database(_settings.DATABASES['default'])}", flush=True)


def _secured(send: Send, path: str, host: str) -> Send:
    """`send`, with the console's security headers added to the response start."""
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            # Django sends header names as written ("Referrer-Policy"); Starlette
            # matches lowercase ones, so lower them first or a header is doubled.
            message["headers"] = [(k.lower(), v) for k, v in message.get("headers") or []]
            headers = MutableHeaders(scope=message)
            headers["Content-Security-Policy"] = console.content_policy(path, host)
            headers.setdefault("X-Content-Type-Options", "nosniff")
            headers.setdefault("Referrer-Policy", "same-origin")
        await send(message)
    return wrapped


async def django_side(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "websocket":
        await WebSocketClose(code=1008)(scope, receive, send)
        return
    path = scope["path"]
    headers = Headers(scope=scope)
    send = _secured(send, path, (headers.get("host") or "").strip())
    reason = console.host_refusal(headers.get("host"))
    if reason:
        await JSONResponse({"detail": reason}, status_code=421)(scope, receive, send)
        return
    if path not in HEALTH and not console.token_ok(headers.get("authorization")):
        await JSONResponse({"detail": "console token required"}, status_code=401)(scope, receive, send)
        return
    if DJANGO is None or STATIC is None:
        await JSONResponse({"detail": UNAVAILABLE}, status_code=503)(scope, receive, send)
        return
    target = STATIC if path.startswith(STATIC_PREFIX + "/") else DJANGO
    await target(scope, receive, send)


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] in ("http", "websocket") and is_django(scope["path"]):
        await django_side(scope, receive, send)
    else:
        await console.app(scope, receive, send)

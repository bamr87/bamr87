"""
Fleet logging settings for __PROJECT_NAME__ (Django) — kit: elk v__KIT_VERSION__

Paste into settings.py, or `from .fleet_logging_settings import LOGGING`.
Depends on adapters/python-logging.py being importable as `fleet_logging` —
this file is only the Django wiring; the formatter and the UPS-OPS-12 redaction
live there, so a Django repo and a plain Python repo emit the same line.

UPS-OPS-11 asks for one line per request at completion. Django's own
`django.server` logger only speaks under runserver, so production request lines
come from middleware — `fleet_logging`'s `configure()` plus a small middleware,
or django-structlog if the project already uses it.
"""
import os

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("LOG_FORMAT", "json" if os.environ.get("APP_ENV") == "production" else "text")

LOGGING = {
    "version": 1,
    # False, deliberately: Django configures loggers before this runs, and
    # leaving them in place means half the application logs in one format and
    # half in another — which reaches the log plane as two datasets.
    "disable_existing_loggers": False,
    "formatters": {
        "fleet_json": {
            "()": "fleet_logging.FleetJsonFormatter",
            "app": os.environ.get("APP_NAME", "__PROJECT_NAME__"),
            "version": os.environ.get("GIT_SHA", "dev"),
        },
        "fleet_text": {
            "()": "fleet_logging.FleetTextFormatter",
            "format": "%(asctime)s %(levelname)-5s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            # stdout, not stderr: the shipper reads the container's stdout, and
            # a log stream split across both fds interleaves unpredictably.
            "stream": "ext://sys.stdout",
            "formatter": "fleet_json" if LOG_FORMAT == "json" else "fleet_text",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Django's request logger emits 4xx/5xx; keep it, it is the error half
        # of UPS-OPS-11.
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # SQL at DEBUG is one line per query. On a busy page that is hundreds
        # of documents nobody reads, against a shared retention budget.
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

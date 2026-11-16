"""
backend.settings — the Harness Console's Django project (ADR 0006, phase B1).

Every value comes from the environment, so one settings module serves a laptop
console, the compose service and, later, a cloud host:

  DJANGO_SECRET_KEY   signs sessions and CSRF tokens. Required whenever the
                      console answers on a non-loopback host (a name in
                      DASH_CONSOLE_ALLOWED_HOSTS). On loopback it may be
                      unset: one is generated once into the state directory
                      (mode 600, gitignored) and reused. Never logged or printed.
  DATABASE_URL        `postgres://user:pass@host:5432/name` or
                      `sqlite:////absolute/path.sqlite3`. Unset, the database
                      is SQLite in the state directory (ADR 0006 decision 7).
  DASH_CONSOLE_STATE  the state directory (default <repo>/.fleet/console).
  DASH_CONSOLE_ALLOWED_HOSTS  the hosts beyond loopback the console answers
                      to — the same list the FastAPI app's DNS-rebinding guard
                      reads, so ALLOWED_HOSTS here equals app.ALLOWED_HOSTS.

DEBUG is always off. The functions below are plain Python so test_backend.py
can hold each rule without re-importing Django.
"""
from __future__ import annotations

import os
import secrets
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

CONSOLE_DIR = Path(__file__).resolve().parents[1]          # tools/console
REPO_ROOT = CONSOLE_DIR.parents[1]

# The console's loopback names (app.ALLOWED_HOSTS without the extra hosts).
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0")


def state_dir(environ: Mapping[str, str] = os.environ) -> Path:
    return Path(environ.get("DASH_CONSOLE_STATE") or (REPO_ROOT / ".fleet" / "console"))


def extra_hosts(environ: Mapping[str, str] = os.environ) -> list[str]:
    """DASH_CONSOLE_ALLOWED_HOSTS, parsed exactly as app.py parses it."""
    return [h.strip().lower() for h in (environ.get("DASH_CONSOLE_ALLOWED_HOSTS") or "").split(",") if h.strip()]


def allowed_hosts(environ: Mapping[str, str] = os.environ) -> list[str]:
    return list(dict.fromkeys([*LOOPBACK_HOSTS, *extra_hosts(environ)]))


def secret_key(environ: Mapping[str, str] = os.environ, state: Path | None = None) -> str:
    """DJANGO_SECRET_KEY, else (on loopback only) the key generated once into the state directory."""
    key = (environ.get("DJANGO_SECRET_KEY") or "").strip()
    if key:
        return key
    remote = [h for h in extra_hosts(environ) if h not in LOOPBACK_HOSTS]
    if remote:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is required when the console answers on a non-loopback host "
            f"(DASH_CONSOLE_ALLOWED_HOSTS names {', '.join(remote)}): set it in .env or the environment")
    return _local_key((state or state_dir(environ)) / "secret_key")


def _local_key(path: Path) -> str:
    """Read the generated key, creating it first if absent. The file appears
    whole or not at all (written to a private temp file, then hard-linked into
    place), so a second process starting at the same moment reads the winner's
    key rather than an empty file."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secret_key-")    # mode 600
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(secrets.token_urlsafe(50) + "\n")
            try:
                os.link(tmp, path)
            except OSError as exc:
                # FileExistsError: another process won the race, and its key is read below.
                # Anything else is a filesystem without hard links: move the file into place instead.
                if not isinstance(exc, FileExistsError) and not path.exists():
                    os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise ImproperlyConfigured(f"{path} is empty: delete it and start the console again to generate a new key")
    return key


_POSTGRES = {"postgres", "postgresql", "pgsql"}


def database(url: str | None, state: Path) -> dict:
    """Django's DATABASES['default'] from DATABASE_URL; SQLite in the state directory when unset.

    Errors name the scheme only, never the URL: it can carry a password."""
    url = (url or "").strip()
    if not url:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)     # SQLite creates the file, not its directory
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(state / "db.sqlite3")}
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme == "sqlite":
        path = unquote(parts.path)
        if parts.netloc == ":memory:" or path in ("", "/", "/:memory:"):
            return {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        # dj-database-url's convention: sqlite:////abs/path is absolute, sqlite:///rel is relative.
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": path[1:]}
    if scheme in _POSTGRES:
        name = unquote(parts.path.lstrip("/"))
        if not name:
            raise ImproperlyConfigured("DATABASE_URL names no database (postgres://user:pass@host:5432/<name>)")
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": unquote(parts.username or ""),
            "PASSWORD": unquote(parts.password or ""),
            "HOST": unquote(parts.hostname or ""),
            "PORT": str(parts.port or ""),
            "OPTIONS": dict(parse_qsl(parts.query)),
        }
    raise ImproperlyConfigured(f"DATABASE_URL scheme '{scheme}' is not supported: use postgres:// or sqlite://")


def describe_database(db: Mapping[str, str]) -> str:
    """One line naming the database for a log, with no user or password."""
    if db["ENGINE"].endswith("sqlite3"):
        return f"sqlite {db['NAME']}"
    where = f"{db.get('HOST') or 'localhost'}:{db.get('PORT') or '5432'}"
    return f"postgresql {where}/{db['NAME']}"


STATE_DIR = state_dir()
SECRET_KEY = secret_key(os.environ, STATE_DIR)
DEBUG = False
ALLOWED_HOSTS = allowed_hosts()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": database(os.environ.get("DATABASE_URL"), STATE_DIR)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "/admin/login/"

# Cookies are scoped to a host, not a port: a Django app on 127.0.0.1:8000
# would share `sessionid` and `csrftoken` with this console, so the names are
# the console's own.
SESSION_COOKIE_NAME = "console_sessionid"
CSRF_COOKIE_NAME = "console_csrftoken"
# The console's frame-ancestors is 'self': the Desktop may open the admin in a window, no other origin may.
X_FRAME_OPTIONS = "SAMEORIGIN"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# The admin's CSS, JS and icons, served by the dispatcher straight from the
# installed Django package (no collectstatic step, nothing written).
STATIC_URL = "/admin/static/"

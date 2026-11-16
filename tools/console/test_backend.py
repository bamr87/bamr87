#!/usr/bin/env python3
"""
Tests for the console's Django backend and the dispatcher in front of it
(backend/, dispatch.py — ADR 0006, phase B1).

Guards what makes a second framework safe to put on the request path of a
write-capable console:

  * routing: /admin/, /accounts/ and /api/v1/ reach Django, and every other
    path answers exactly as the FastAPI app alone answers it;
  * the guards: a foreign Host is refused on every Django path, and without
    the bearer token (when DASH_CONSOLE_TOKEN is set) on every Django path but
    the three health endpoints — the same checks, from the same functions, as
    the FastAPI routes;
  * the health endpoints: liveness, readiness that follows the database and
    its migrations, the version document;
  * migrations run on SQLite in the state directory, and the admin signs in
    end to end under the console's Content-Security-Policy and Django's CSRF
    check;
  * settings from the environment: the generated secret key (mode 600, reused,
    never printed), DJANGO_SECRET_KEY required off loopback, DATABASE_URL
    parsing that never echoes a password, ALLOWED_HOSTS equal to the console's
    DNS-rebinding allowlist;
  * degradation: without Django, or with settings that refuse to load, the
    FastAPI half still serves and the Django paths answer 503 with the reason;
  * the public snapshot imports nothing from Django.

Needs the console's requirements (Django, FastAPI and starlette's TestClient):

    .venv-console/bin/python tools/console/test_backend.py

With plain python3 only the snapshot test runs; the rest report themselves
skipped, as test_console.py does without FastAPI.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TMP = Path(tempfile.mkdtemp(prefix="console-test-backend-"))

# Never the live console's job dir or database: both are read at import.
os.environ["DASH_CONSOLE_JOBS"] = str(TMP / "jobs")
os.environ["DASH_CONSOLE_STATE"] = str(TMP / "state")
os.environ["CONSOLE_AUTO_HEALTH"] = "0"
for _k in ("DATABASE_URL", "DJANGO_SECRET_KEY", "DASH_CONSOLE_TOKEN", "DASH_CONSOLE_ALLOWED_HOSTS",
           "DJANGO_SETTINGS_MODULE"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(HERE))

HAVE_DJANGO = importlib.util.find_spec("django") is not None
HAVE_FASTAPI = importlib.util.find_spec("fastapi") is not None
try:
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
except (ImportError, RuntimeError):     # starlette absent, or its TestClient's HTTP library
    TestClient = None
NEED_ALL = unittest.skipUnless(HAVE_DJANGO and HAVE_FASTAPI and TestClient,
                               "skipped: needs django, fastapi and starlette's TestClient (the console venv)")
NEED_DJANGO = unittest.skipUnless(HAVE_DJANGO, "skipped: django not installed")
BASE = "http://127.0.0.1:4001"


def _python(code: str, **env: str) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter with the test's environment plus `env`."""
    full = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env}
    return subprocess.run([sys.executable, "-c", code], cwd=HERE, env=full, capture_output=True, text=True, timeout=180)


class Snapshot(unittest.TestCase):
    """The public site builds with Django absent (ADR 0006: the service layer never needs it)."""

    def test_snapshot_and_app_import_with_django_blocked(self):
        mods = "snapshot, site_docs" + (", app" if HAVE_FASTAPI else "")
        r = _python(f"import sys; sys.modules['django'] = None; sys.path.insert(0, '.'); import {mods}; print('ok')")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("ok", r.stdout)

    def test_build_pages_never_starts_the_dispatcher(self):
        for name in ("build-pages.sh", "snapshot.py", "site_docs.py"):
            text = (HERE / name).read_text(encoding="utf-8")
            hit = re.search(r"\bimport dispatch\b|dispatch:app|\b(?:import|from) django\b|backend/manage\.py", text)
            self.assertIsNone(hit, f"{name}: {hit and hit.group(0)}")


class Wiring(unittest.TestCase):
    """run.sh, serve.py and requirements.txt start the dispatcher, after migrate."""

    def test_run_sh_migrates_then_serves_the_dispatcher(self):
        run = (HERE / "run.sh").read_text(encoding="utf-8")
        migrate = run.index("backend/manage.py migrate --noinput")
        self.assertLess(migrate, run.index("uvicorn dispatch:app"))
        self.assertNotIn("uvicorn app:app", run)
        self.assertIn('"dispatch:app"', (HERE / "serve.py").read_text(encoding="utf-8"))

    def test_django_is_an_unpinned_requirement(self):
        lines = (HERE / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("django", [ln.strip() for ln in lines])
        self.assertFalse([ln for ln in lines if re.match(r"^django\s*[=<>~!]", ln, flags=re.I)], "no pins (fleet policy)")


@NEED_DJANGO
class Settings(unittest.TestCase):
    """backend/settings.py: every value from the environment, nothing secret in a message."""

    @classmethod
    def setUpClass(cls):
        from django.core.exceptions import ImproperlyConfigured

        from backend import settings
        cls.s = settings
        cls.Improper = ImproperlyConfigured

    def test_allowed_hosts_are_loopback_plus_the_console_list(self):
        self.assertEqual(self.s.allowed_hosts({}), list(self.s.LOOPBACK_HOSTS))
        hosts = self.s.allowed_hosts({"DASH_CONSOLE_ALLOWED_HOSTS": " Console.Example , localhost,,x.test "})
        self.assertEqual(hosts, [*self.s.LOOPBACK_HOSTS, "console.example", "x.test"])

    @unittest.skipUnless(HAVE_FASTAPI, "skipped: fastapi not installed")
    def test_allowed_hosts_equal_the_fastapi_guard(self):
        import app as console_app
        self.assertEqual(set(self.s.ALLOWED_HOSTS), console_app.ALLOWED_HOSTS)
        env = {"DASH_CONSOLE_ALLOWED_HOSTS": "Console.Example, x.test"}
        r = _python("import app, json; print(json.dumps(sorted(app.ALLOWED_HOSTS)))", **env)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), sorted(self.s.allowed_hosts(env)))

    def test_secret_key_is_generated_once_private_and_silent(self):
        state = Path(tempfile.mkdtemp(dir=TMP)) / "s"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            first = self.s.secret_key({}, state)
            second = self.s.secret_key({}, state)
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 50)
        self.assertEqual(stat.S_IMODE((state / "secret_key").stat().st_mode), 0o600)
        self.assertEqual(out.getvalue() + err.getvalue(), "", "nothing printed")
        self.assertEqual([p.name for p in state.iterdir()], ["secret_key"], "no temp file left behind")

    def test_secret_key_from_the_environment_wins_and_writes_nothing(self):
        state = Path(tempfile.mkdtemp(dir=TMP)) / "s"
        self.assertEqual(self.s.secret_key({"DJANGO_SECRET_KEY": " from-env "}, state), "from-env")
        self.assertFalse(state.exists())

    def test_secret_key_is_required_off_loopback(self):
        state = Path(tempfile.mkdtemp(dir=TMP)) / "s"
        with self.assertRaises(self.Improper) as caught:
            self.s.secret_key({"DASH_CONSOLE_ALLOWED_HOSTS": "console.example"}, state)
        self.assertIn("DJANGO_SECRET_KEY", str(caught.exception))
        self.assertFalse(state.exists(), "no key generated for a non-loopback console")
        # a loopback name in the list is still loopback
        self.assertTrue(self.s.secret_key({"DASH_CONSOLE_ALLOWED_HOSTS": "localhost"}, state))
        self.assertEqual(self.s.secret_key({"DASH_CONSOLE_ALLOWED_HOSTS": "console.example",
                                            "DJANGO_SECRET_KEY": "k"}, state), "k")

    def test_an_empty_key_file_is_refused(self):
        state = Path(tempfile.mkdtemp(dir=TMP))
        (state / "secret_key").write_text("\n")
        with self.assertRaises(self.Improper):
            self.s.secret_key({}, state)

    def test_database_url(self):
        state = Path(tempfile.mkdtemp(dir=TMP)) / "s"
        db = self.s.database(None, state)
        self.assertEqual(db, {"ENGINE": "django.db.backends.sqlite3", "NAME": str(state / "db.sqlite3")})
        self.assertTrue(state.is_dir(), "the SQLite directory exists before Django opens the file")
        pg = self.s.database("postgres://fleet:p%40ss%2Fw@db:5433/console?sslmode=prefer", state)
        self.assertEqual((pg["ENGINE"], pg["NAME"], pg["USER"], pg["PASSWORD"], pg["HOST"], pg["PORT"], pg["OPTIONS"]),
                         ("django.db.backends.postgresql", "console", "fleet", "p@ss/w", "db", "5433", {"sslmode": "prefer"}))
        self.assertEqual(self.s.database("postgresql://u@localhost/x", state)["PORT"], "")
        self.assertEqual(self.s.database("sqlite:////var/x.sqlite3", state)["NAME"], "/var/x.sqlite3")
        self.assertEqual(self.s.database("sqlite:///rel.sqlite3", state)["NAME"], "rel.sqlite3")
        self.assertEqual(self.s.database("sqlite://:memory:", state)["NAME"], ":memory:")
        for bad in ("mysql://u:s3cret@h/db", "postgres://u:s3cret@h/"):
            with self.assertRaises(self.Improper) as caught:
                self.s.database(bad, state)
            self.assertNotIn("s3cret", str(caught.exception))

    def test_describe_database_never_names_the_user_or_password(self):
        state = Path(tempfile.mkdtemp(dir=TMP))
        line = self.s.describe_database(self.s.database("postgres://fleet:s3cret@db:5433/console", state))
        self.assertEqual(line, "postgresql db:5433/console")
        self.assertTrue(self.s.describe_database(self.s.database("", state)).startswith("sqlite "))

    def test_debug_is_off_and_cookies_are_the_consoles_own(self):
        self.assertFalse(self.s.DEBUG)
        self.assertEqual((self.s.SESSION_COOKIE_NAME, self.s.CSRF_COOKIE_NAME), ("console_sessionid", "console_csrftoken"))
        self.assertEqual(self.s.STATIC_URL, "/admin/static/")


@NEED_ALL
class Dispatcher(unittest.TestCase):
    """dispatch.py over HTTP, against a SQLite database migrated in setUpClass."""

    @classmethod
    def setUpClass(cls):
        import dispatch
        from django.core.management import call_command
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        cls.d = dispatch
        cls.client = TestClient(dispatch.app, base_url=BASE)
        cls.fastapi = TestClient(dispatch.console.app, base_url=BASE)
        cls.ready_before = cls.client.get("/api/v1/readyz")
        call_command("migrate", interactive=False, verbosity=0)
        cls.ready_after = cls.client.get("/api/v1/readyz")
        executor = MigrationExecutor(connection)
        cls.pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        cls.db_name = connection.settings_dict["NAME"]

    # ---- the backend ---------------------------------------------------------
    def test_migrations_run_on_sqlite_in_the_state_dir_and_readyz_follows_them(self):
        self.assertEqual(Path(self.db_name), TMP / "state" / "db.sqlite3")
        self.assertEqual(self.ready_before.status_code, 503)
        self.assertEqual(self.ready_before.json(), {"status": "degraded", "checks": {"db": "ok", "migrations": "pending"}})
        self.assertEqual(self.pending, [])
        self.assertEqual(self.ready_after.status_code, 200)
        self.assertEqual(self.ready_after.json(), {"status": "ok", "checks": {"db": "ok", "migrations": "ok"}})

    def test_readyz_reports_an_unreachable_database_as_a_word(self):
        from django.db import DatabaseError
        with mock.patch("django.db.backends.base.base.BaseDatabaseWrapper.cursor",
                        side_effect=DatabaseError("connection to server at db failed")), \
                self.assertLogs("console.backend", level="WARNING"):
            r = self.client.get("/api/v1/readyz")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"status": "degraded", "checks": {"db": "unreachable", "migrations": "unknown"}})

    def test_healthz_and_version(self):
        r = self.client.get("/api/v1/healthz")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        self.assertIn("no-cache", r.headers["cache-control"])
        v = self.client.get("/api/v1/version").json()
        self.assertEqual(set(v), {"name", "version", "commit", "built_at"})
        self.assertEqual(v["name"], "bamr87-harness-console")
        self.assertRegex(v["version"] or "", r"^\d+\.\d+\.\d+$")
        self.assertIn(self.client.post("/api/v1/healthz").status_code, (403, 405))   # CSRF, then GET/HEAD only

    # ---- routing ---------------------------------------------------------------
    def test_is_django(self):
        for path in ("/admin/", "/admin", "/admin/login/", "/accounts/", "/accounts", "/api/v1/", "/api/v1", "/api/v1/healthz"):
            self.assertTrue(self.d.is_django(path), path)
        for path in ("/", "/administrator", "/api/health", "/api/v10/x", "/api", "/accountsx", "/projects/admin/"):
            self.assertFalse(self.d.is_django(path), path)

    def test_django_answers_its_prefixes(self):
        r = self.client.get("/admin/login/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Harness Console admin", r.text)
        r = self.client.get("/admin", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (301, "/admin/"))
        self.assertEqual(self.client.get("/admin/", follow_redirects=False).status_code, 302)   # to the login page
        self.assertEqual(self.client.get("/accounts/").status_code, 404)                        # reserved for B3
        self.assertEqual(self.client.get("/api/v1/nope").status_code, 404)
        r = self.client.get("/admin/static/admin/css/base.css")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/css"))
        self.assertEqual(self.client.get("/admin/static/admin/css/nope.css").status_code, 404)

    def test_every_other_path_answers_exactly_as_fastapi_alone(self):
        for path in ("/", "/projects/zer0-mistakes", "/api/health", "/api/keys", "/api/theme", "/theme.css",
                     "/api/v10/x", "/api", "/administrator", "/assets/none.js"):
            via, alone = self.client.get(path), self.fastapi.get(path)
            self.assertEqual((via.status_code, via.content), (alone.status_code, alone.content), path)
            self.assertEqual(via.headers.get("content-security-policy"), alone.headers.get("content-security-policy"), path)
        self.assertEqual(self.client.get("/", headers={"Host": "evil.example"}).status_code, 421)

    def test_lifespan_reaches_the_fastapi_app(self):
        with mock.patch.object(self.d.console.core, "auto_health") as started:
            with TestClient(self.d.app, base_url=BASE) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
        started.assert_called_once()

    def test_a_websocket_to_a_django_path_is_closed(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/v1/healthz"):
                pass

    # ---- the guards -------------------------------------------------------------
    def test_a_foreign_host_is_refused_on_every_django_path(self):
        expected = self.fastapi.get("/api/health", headers={"Host": "evil.example"})
        self.assertEqual(expected.status_code, 421)
        for path in ("/admin/", "/admin/login/", "/accounts/", "/api/v1/healthz", "/api/v1/readyz", "/admin/static/admin/css/base.css"):
            r = self.client.get(path, headers={"Host": "evil.example:4001"})
            self.assertEqual((r.status_code, r.json()), (421, expected.json()), path)
        self.assertEqual(self.client.get("/api/v1/healthz", headers={"Host": "localhost:4001"}).status_code, 200)

    def test_the_bearer_token_guards_every_django_path_but_health(self):
        with mock.patch.dict(os.environ, {"DASH_CONSOLE_TOKEN": "t0k-for-tests"}):
            self.assertEqual(self.fastapi.get("/api/state").status_code, 401)     # FastAPI's own, for parity
            for path in ("/admin/", "/admin/login/", "/accounts/", "/api/v1/", "/api/v1/nope", "/admin/static/admin/css/base.css"):
                self.assertEqual(self.client.get(path).status_code, 401, path)
                self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer wrong"}).status_code, 401, path)
                self.assertEqual(self.client.get(path, headers={"Authorization": "Basic t0k-for-tests"}).status_code, 401, path)
            # the scheme is case-insensitive and stray spaces are forgiven, as on the FastAPI routes
            r = self.client.get("/admin/login/", headers={"Authorization": "bearer  t0k-for-tests "})
            self.assertEqual(r.status_code, 200)
            for path in sorted(self.d.HEALTH):
                self.assertEqual(self.client.get(path).status_code, 200, path)
            self.assertEqual(self.client.get("/api/v1/healthz/").status_code, 401, "the exemption is exact")
        self.assertEqual(self.client.get("/admin/login/").status_code, 200, "no token configured, none needed")

    def test_django_responses_carry_the_consoles_policy(self):
        r = self.client.get("/admin/login/")
        self.assertEqual(r.headers["content-security-policy"], self.d.console.content_policy("/admin/login/", "127.0.0.1:4001"))
        self.assertIn("script-src 'self'", r.headers["content-security-policy"])
        self.assertIn("frame-ancestors 'self'", r.headers["content-security-policy"])
        self.assertEqual(r.headers.get_list("referrer-policy"), ["same-origin"])
        self.assertEqual(r.headers.get_list("x-content-type-options"), ["nosniff"])
        self.assertEqual(r.headers["x-frame-options"], "SAMEORIGIN")
        self.assertNotRegex(r.text, r"<script(?![^>]*\bsrc=)(?![^>]*type=\"application/json\")[^>]*>",
                            "an inline script would be blocked by script-src 'self'")
        refused = self.client.get("/admin/", headers={"Host": "evil.example"})
        self.assertIn("content-security-policy", refused.headers)

    def test_the_admin_signs_in_under_the_csrf_check(self):
        from django.contrib.auth import get_user_model
        password = secrets.token_urlsafe(24)
        get_user_model().objects.create_superuser("console-test-admin", "", password)
        client = TestClient(self.d.app, base_url=BASE)
        page = client.get("/admin/login/?next=/admin/")
        self.assertIn("console_csrftoken", client.cookies)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text).group(1)
        form = {"csrfmiddlewaretoken": token, "username": "console-test-admin", "password": password, "next": "/admin/"}
        # What a browser sends under Referrer-Policy: no-referrer — refused, which is why the admin keeps same-origin.
        self.assertEqual(client.post("/admin/login/?next=/admin/", data=form, headers={"Origin": "null"},
                                     follow_redirects=False).status_code, 403)
        r = client.post("/admin/login/?next=/admin/", data=form, headers={"Origin": BASE}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/admin/"))
        self.assertIn("console_sessionid", client.cookies)
        home = client.get("/admin/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Harness Console administration", home.text)
        self.assertNotIn(password, home.text)

    # ---- degradation ------------------------------------------------------------
    def test_without_django_the_django_paths_answer_503_and_fastapi_serves(self):
        with mock.patch.multiple(self.d, DJANGO=None, STATIC=None, UNAVAILABLE="Django is not installed (django)"):
            for path in ("/admin/", "/api/v1/healthz"):
                r = self.client.get(path)
                self.assertEqual((r.status_code, r.json()), (503, {"detail": "Django is not installed (django)"}), path)
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_a_missing_django_degrades_at_import(self):
        r = _python("import sys; sys.modules['django'] = None\n"
                    "from starlette.testclient import TestClient\nimport dispatch\n"
                    f"c = TestClient(dispatch.app, base_url='{BASE}')\n"
                    "print(c.get('/admin/').status_code, c.get('/api/health').status_code)")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertEqual(r.stdout.strip().splitlines()[-1], "503 200")
        self.assertIn("Django is not installed", r.stderr)

    def test_settings_that_refuse_to_load_degrade_and_say_why(self):
        state = Path(tempfile.mkdtemp(dir=TMP)) / "remote"
        r = _python("from starlette.testclient import TestClient\nimport dispatch\n"
                    f"c = TestClient(dispatch.app, base_url='{BASE}')\n"
                    "a = c.get('/admin/')\nprint(a.status_code, c.get('/api/health').status_code)\nprint(a.json()['detail'])",
                    DASH_CONSOLE_ALLOWED_HOSTS="console.example", DASH_CONSOLE_STATE=str(state))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        status, detail = r.stdout.strip().splitlines()[-2:]
        self.assertEqual(status, "503 200")
        self.assertIn("DJANGO_SECRET_KEY is required", detail)
        self.assertIn("DJANGO_SECRET_KEY is required", r.stderr)
        self.assertFalse((state / "secret_key").exists())


@NEED_DJANGO
class ManagePy(unittest.TestCase):
    """backend/manage.py works from any directory, with the console's environment."""

    def test_migrate_and_check_from_the_repo_root(self):
        state = Path(tempfile.mkdtemp(dir=TMP)) / "manage"
        env = {**os.environ, "DASH_CONSOLE_STATE": str(state), "PYTHONDONTWRITEBYTECODE": "1"}
        for args in (["migrate", "--noinput"], ["check"], ["showmigrations", "--plan"]):
            r = subprocess.run([sys.executable, str(HERE / "backend" / "manage.py"), *args], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, f"{args}: {r.stderr[-2000:]}")
        self.assertTrue((state / "db.sqlite3").is_file())
        self.assertNotIn("[ ]", r.stdout, "every migration applied")
        self.assertNotIn((state / "secret_key").read_text().strip(), r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

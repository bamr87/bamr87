#!/usr/bin/env python3
"""
test_pages — the console's PUBLIC face: the static snapshot published to
GitHub Pages (snapshot.py), the site documents both faces serve (site_docs.py),
and the door a public page uses to reach a running console (app.py,
remote_page).

What these hold, in order of how badly breaking them would hurt:

  * the snapshot never publishes the lake, a local path, a credential's
    presence, a local service's probe, or a draft;
  * a page on the Pages origin reaches a console only while the console
    requires its token;
  * every route the app declares gets a page of its own in the build (a deep
    link answers 200), and every retired Jekyll URL still lands somewhere.

Dependency-light like test_console.py: no pytest; run `python3
tools/console/test_pages.py`. The FastAPI checks skip without fastapi.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Never the live console's job dir: importing `app` builds its JobManager,
# which loads (and re-saves) the history it finds. Run inside the console
# container — the console's own Tests job does — that was the RUNNING
# console's index. core reads this at import, so it is set before any import.
os.environ["DASH_CONSOLE_JOBS"] = tempfile.mkdtemp(prefix="console-test-jobs-")

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import snapshot  # noqa: E402  (first: it points core at an empty lake)
import site_docs  # noqa: E402

WEB = HERE / "web" / "src"
_DOCS: dict | None = None


def docs() -> dict:
    global _DOCS
    if _DOCS is None:
        _DOCS = snapshot.documents()
    return _DOCS


def test_the_snapshot_publishes_nothing_local():
    blob = json.dumps(docs(), default=str)
    root = str(snapshot.core.REPO_ROOT)
    assert root not in blob, "an absolute path of the build machine is in the snapshot"
    assert str(Path.home()) not in blob, "the build machine's home directory is in the snapshot"
    assert not re.search(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9\-_]{20,})", blob), \
        "something token-shaped is in the snapshot"
    # Credentials are a console's business: not even their presence is written.
    assert "auth" not in docs(), "the auth document must not be published"
    assert docs()["capabilities"]["env_tokens"] == {} and docs()["capabilities"]["mode"] == "snapshot"


def test_the_lake_and_local_planes_are_absent_whatever_this_machine_holds():
    d = docs()
    assert d["lake"]["present"] is False and d["lake/runs"] == [] and d["lake/lines"] == []
    assert d["lake/review"]["present"] is False
    assert d["observability"]["present"] is False and d["observability"]["planes"] == {}
    assert d["fleet/docker"]["containers"] == [] and d["index/coverage"]["projects"] == []
    assert d["tui/status"]["available"] is False
    for key, doc in d.items():
        if key.startswith("project/"):
            assert doc["lake_runs"] == [] and doc["lake_lines"] == [], f"{key} carries lake rows"


def test_drafts_stay_out_of_the_public_build():
    every = site_docs.posts(include_drafts=True)
    public = {p["slug"] for p in docs()["site"]["posts"]}
    for p in every:
        if p["draft"]:
            assert p["slug"] not in public and f"site/post/{p['slug']}" not in docs(), p["slug"]
        else:
            assert p["slug"] in public, p["slug"]


def test_one_fleet_view_per_sort_each_row_searchable():
    from fleetcore import fleet as fl
    for sort in fl.SORTS:
        view = docs()[f"fleet/{sort}"]
        assert view["rows"], sort
        assert all(isinstance(r.get("haystack"), str) and r["haystack"] for r in view["rows"]), \
            f"fleet/{sort}: the page filters on `haystack` (fleetcore's own predicate) — it must be on every row"


def test_every_app_route_has_a_page_in_the_build():
    """main.tsx's <Route path> table ↔ STATIC_ROUTES: a route the build does
    not know about is a deep link that answers 404 on Pages."""
    main = (WEB / "main.tsx").read_text()
    nav = (WEB / "nav.ts").read_text()
    paths = set(re.findall(r'<Route path="([^"*:]+)"', main))
    paths |= set(re.findall(r"'([a-z-]+)'", re.search(r"PROFILE_PAGES = \[([^\]]*)\]", nav).group(1)))
    missing = sorted(p for p in paths if p not in snapshot.STATIC_ROUTES and p != "auth")
    assert not missing, f"routes with no page in the static build: {missing} — add them to snapshot.STATIC_ROUTES"
    legacy_ts = (WEB / "lib" / "legacy.ts").read_text()
    legacy = set(re.findall(r"^\s+'?([a-z-]+)'?: '/", legacy_ts, re.M))
    assert legacy == set(snapshot.LEGACY_ROUTES), \
        f"legacy.ts and snapshot.LEGACY_ROUTES disagree: {sorted(legacy ^ set(snapshot.LEGACY_ROUTES))}"


def test_build_writes_a_page_per_route_and_the_feeds():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "index.html").write_text("<!doctype html><html><head><title>x</title></head><body></body></html>")
        manifest = snapshot.build(out, "/bamr87/", "https://example.test/bamr87")
        assert manifest["schema"] == "console-snapshot/v1" and manifest["documents"] >= 40
        for path in ("about/index.html", "portfolio/index.html", "harnesses/health/index.html", "triage/index.html",
                     "404.html", "sitemap.xml", "feed.xml", "robots.txt", "theme.css", ".nojekyll",
                     "snapshot/state.json", "snapshot/manifest.json", "snapshot/github/fleet.json"):
            assert (out / path).exists(), path
        name = next(p["name"] for p in snapshot.core.load_yaml(snapshot.core.DATA / "projects.yml"))
        page = (out / "projects" / name / "index.html").read_text()
        assert f"<title>{name} · " in page and 'rel="canonical" href="https://example.test/bamr87/projects/' in page
        sitemap = (out / "sitemap.xml").read_text()
        assert "https://example.test/bamr87/portfolio" in sitemap and "/bamr87/triage<" not in sitemap
        assert not (out / "snapshot" / "auth.json").exists()


def test_site_documents_are_json_and_refuse_what_is_not_listed():
    idx = site_docs.site_index(include_drafts=True)
    json.dumps(idx)
    assert idx["profile"].get("name"), "_data/profile.yml carries the site's identity"
    assert [p["slug"] for p in idx["pages"]][:4] == ["about", "experience", "services", "contact"]
    for bad in ("../fleet", "UPPER", ""):
        try:
            site_docs.page(bad)
        except ValueError:
            continue
        raise AssertionError(f"page({bad!r}) was not refused")
    try:
        site_docs.data("api_keys")
    except KeyError:
        pass
    else:
        raise AssertionError("a registry not in PUBLIC_DATA was served")


def test_a_remote_page_reaches_a_console_only_with_its_token():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("    (skipped: fastapi not installed)")
        return
    import app as console_app

    origin = "https://bamr87.github.io"
    assert origin in console_app.REMOTE_ORIGINS
    client = TestClient(console_app.app, base_url="http://127.0.0.1:4001")
    saved = os.environ.pop("DASH_CONSOLE_TOKEN", None)
    try:
        # The preflight is answered (Chrome's Private Network Access included),
        # so the refusal that follows can be read by the page.
        pre = client.options("/api/state", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                     "Access-Control-Request-Private-Network": "true"})
        assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == origin
        assert pre.headers.get("access-control-allow-private-network") == "true"
        # No token configured: refused, with a reason, before any route runs.
        r = client.get("/api/state", headers={"Origin": origin})
        assert r.status_code == 403 and "DASH_CONSOLE_TOKEN" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == origin
        assert client.post("/api/jobs", json={"op": "status"}, headers={"Origin": origin}).status_code == 403
        # The console's own page (no Origin, or its own) is untouched.
        assert client.get("/api/state").status_code == 200
        # An origin nobody listed gets no CORS at all.
        other = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in other.headers

        os.environ["DASH_CONSOLE_TOKEN"] = "remote-test-token"
        assert client.get("/api/state", headers={"Origin": origin}).status_code == 401
        ok = client.get("/api/site", headers={"Origin": origin, "Authorization": "Bearer remote-test-token"})
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == origin
        assert ok.json()["profile"]["name"]
        # The terminal's WebSocket admits the same origin under the same rule.
        assert console_app.tui.refusal({"host": "127.0.0.1:4001", "origin": origin}) is None
        os.environ.pop("DASH_CONSOLE_TOKEN")
        assert console_app.tui.refusal({"host": "127.0.0.1:4001", "origin": origin}) is not None
    finally:
        if saved is None:
            os.environ.pop("DASH_CONSOLE_TOKEN", None)
        else:
            os.environ["DASH_CONSOLE_TOKEN"] = saved


def test_the_console_serves_the_site_documents_with_drafts():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("    (skipped: fastapi not installed)")
        return
    import app as console_app

    client = TestClient(console_app.app, base_url="http://127.0.0.1:4001")
    saved = os.environ.pop("DASH_CONSOLE_TOKEN", None)
    try:
        assert client.get("/api/site/page/about").json()["markdown"]
        assert client.get("/api/site/page/nope").status_code == 404
        assert client.get("/api/data/projects").status_code == 200
        assert client.get("/api/data/api_keys").status_code == 404
        drafts = [p for p in site_docs.posts(include_drafts=True) if p["draft"]]
        if drafts:
            assert client.get(f"/api/site/post/{drafts[0]['slug']}").status_code == 200, "drafts show on a console"
        fleet = client.get("/api/github/fleet").json()
        assert set(fleet["dispatchable"]) == set(console_app.core.DISPATCHABLE)
        assert client.get("/api/capabilities").json()["mode"] == "console"
    finally:
        if saved is not None:
            os.environ["DASH_CONSOLE_TOKEN"] = saved


def test_every_embedded_diagram_exists_and_is_served_sandboxed():
    page = (WEB / "pages" / "HealthPage.tsx").read_text()
    names = re.findall(r"\['([a-z0-9-]+\.[a-z]+)', '", page)
    assert names, "HealthPage.tsx lists no diagrams"
    for n in names:
        assert (snapshot.core.REPO_ROOT / "diagrams" / f"{n}.html").is_file(), f"diagrams/{n}.html is missing"
    sandbox = re.findall(r'sandbox="([^"]*)"', page)
    assert sandbox == ["allow-scripts allow-popups allow-downloads"], f"the diagram frame must stay sandboxed without same-origin: {sandbox}"
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return
    import app as console_app
    client = TestClient(console_app.app, base_url="http://127.0.0.1:4001")
    r = client.get(f"/diagrams/{names[0]}.html")
    assert r.status_code == 200 and r.headers["content-security-policy"].startswith("sandbox allow-scripts")
    assert client.get("/diagrams/README.md").status_code == 404  # only <name>.<type>.html
    assert client.get("/diagrams/nope.architecture.html").status_code == 404


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — public site tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

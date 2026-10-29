#!/usr/bin/env python3
"""
snapshot — build the Harness Console's PUBLIC face: the static site published
at https://bamr87.github.io/bamr87/ (build-dash.yml).

The page is the console's own React app (web/), built with a base path and
VITE_STATIC=1. What it would ask the console's API for, this script writes as
files: every GET document the page reads, rendered by the SAME functions
app.py routes to (core.py, fleetcore, site_docs.py, github_link.py), under
<out>/snapshot/ at the path the API would serve it from — /api/state becomes
snapshot/state.json, /api/project/zer0-mistakes becomes
snapshot/project/zer0-mistakes.json. The page's client maps one onto the other
(web/src/api/static.ts), so the two cannot drift by construction.

What is deliberately NOT published, whatever the machine running this holds:

  * the local data lake (.dash-lake/ — it holds run logs; the console README's
    "Publish the lake" refusal). core is pointed at an empty lake directory
    before it is imported, so every lake-backed document is its "absent" shape.
  * the probes of local services (Phoenix, Kibana, Grafana, Qdrant, Docker):
    what one laptop's ports answered is not a fact about the fleet.
  * credentials of any kind, their presence included: the auth document is not
    written at all. The token-rotation ledger the state document carries is
    already committed public data (names and ages, never values).
  * absolute paths of the build machine.
  * draft posts.

Beside the documents it writes one index.html per known route (so a deep link
returns 200 with its own title and description, not a 404 that happens to boot
the app), a 404.html for every other path, sitemap.xml, feed.xml (Atom),
robots.txt, theme.css and .nojekyll.

Usage (after `CONSOLE_BASE=/bamr87/ VITE_STATIC=1 npm run build` in web/):
    python3 tools/console/snapshot.py --out tools/console/web/dist \\
        --base /bamr87/ --site-url https://bamr87.github.io/bamr87
tools/console/build-pages.sh does both.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

HERE = Path(__file__).resolve().parent
# Before core is imported: an empty lake, so nothing local is published.
_EMPTY_LAKE = tempfile.mkdtemp(prefix="snapshot-lake-")
os.environ["DASH_LAKE_DIR"] = _EMPTY_LAKE
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402
import github_link as ghl  # noqa: E402
import site_docs  # noqa: E402
from fleetcore import fleet as fl  # noqa: E402
from fleetcore import keys as fkeys  # noqa: E402
from fleetcore import theme as ftheme  # noqa: E402
from fleetcore import views as fviews  # noqa: E402

HUB = "bamr87/bamr87"
LOCAL_ONLY = ("runs on the operator's machine and is never published — "
              "connect a console (the Connect page) to see it live")

# Every page the app routes to that is not a drill-down, with what a search
# engine or a link preview should say about it. test_snapshot.py holds this
# list equal to the <Route path> table in web/src/main.tsx.
STATIC_ROUTES: dict[str, tuple[str, str]] = {
    "": ("Home", "Portfolio and agentic harness control plane for the bamr87 fleet."),
    "overview": ("Overview", "Fleet attention queue, KPIs and signal freshness."),
    "about": ("About", ""),
    "experience": ("Experience", ""),
    "services": ("Services", ""),
    "contact": ("Contact", ""),
    "portfolio": ("Portfolio", "Every project in the fleet, featured first, with its live health."),
    "blog": ("Writing", "Notes on enterprise architecture, DevOps, cloud and practical AI workflows."),
    "projects": ("Projects", "Every registry project with health, triage and CI state."),
    "inbox": ("Inbox", "Flagged issues, pull requests and failing workflows across the fleet."),
    "roadmap": ("Roadmap", "Planned features across the fleet, by status and priority."),
    "work": ("Work board", "Every open issue, PR, roadmap spec and backlog item, in the order the loops take them."),
    "deep-dive": ("Deep dive", "One repo a day, every repo once per cycle: progress, calendar, scores and deep-dive issues/PRs."),
    "features": ("Features", "What each repo does and what proves it — the fleet feature index."),
    "engagements": ("Engagements", "Every project as a client: estimates, actuals and leverage."),
    "github": ("GitHub", "Manage fleet repos' issues, runs and workflows."),
    "containers": ("Containers", "The fleet dev stack: ports, images and services."),
    "harnesses": ("Harness inventory", "Per-repo AI harness deployment matrix."),
    "harnesses/health": ("Harness health", "Trip wires and the six-layer harness scorecard."),
    "schedules": ("Schedules", "Crons, caps and collisions across the fleet."),
    "loops": ("Loops", "The control-plane loops and their outputs."),
    "costs": ("Costs", "Claude spend and Actions minutes against budget."),
    "activity": ("Agent activity", "Local sessions and CI agent runs."),
    "observe/traces": ("Traces", "The data lake and Phoenix traces."),
    "observe/lines": ("Lines", "Every workflow with provenance and kill switch."),
    "observe/logs": ("Logs", "Kibana over the log plane."),
    "observe/metrics": ("Metrics", "Grafana."),
    "observe/index": ("Code index", "Semantic search over the worktree."),
    "content": ("Content sites", "The content atlas and editorial plan."),
    "jobs": ("Jobs", "Every job, with live logs."),
    "ops": ("Operations", "The allowlisted operations."),
    "toolbox": ("Toolbox", "Scripts, skills and template kits the hub provides."),
    "terminal": ("Terminal", "The terminal dash, in the page."),
    "config": ("Config", "_data/fleet.yml, block by block."),
    "auth": ("Credentials", "Tokens, gh login and rotation."),
    "connect": ("Connect", "Connect this page to GitHub or to a running console."),
}

# The retired Jekyll site's URLs, kept alive: the app redirects each to the
# page that replaced it (web/src/lib/legacy.ts), and a stub here makes the old
# link return 200 rather than 404 first.
LEGACY_ROUTES = ["dashboard", "monitor", "cockpit", "actions", "ai-usage", "ai-activity", "triage", "harness",
                 "issue-pipeline", "docker", "resume", "docs", "sitemap"]


def _json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, default=str, separators=(",", ":")), encoding="utf-8")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=core.REPO_ROOT, capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# --------------------------------------------------------------------------- #
# The documents
# --------------------------------------------------------------------------- #
def capabilities() -> dict:
    return {"mode": "snapshot", "tools": {}, "gh_authenticated": None, "env_tokens": {},
            "contract_editing": False, "config_editing": False, "auth_writes": False,
            "console_token_required": False, "python": "", "job_dir": "", "lake_dir": "",
            "lake_present": False, "otel_exporter": False, "phoenix": {"collector": "", "ui": ""},
            "observability": {}}


def state() -> dict:
    doc = core.load_state()
    doc["repo_root"] = HUB
    git = doc.get("git") or {}
    doc["git"] = {"branch": os.environ.get("GITHUB_REF_NAME") or git.get("branch"), "head": git.get("head"),
                  "dirty_count": 0}
    return doc


def fleet_views() -> dict[str, dict]:
    """One document per sort key. Filtering (q, health) is applied by the page
    on the sorted rows with fleetcore's own predicate — a substring of each
    row's `haystack`, which is written here from the AppRow itself."""
    snap = fl.load_snapshot(core.REPO_ROOT)
    hay = {r.name: r.haystack for r in snap.rows}
    out = {}
    for sort in fl.SORTS:
        view = fviews.dash_view(core.REPO_ROOT, sort=sort)
        for row in view["rows"]:
            row["haystack"] = hay.get(row["name"], row["name"].lower())
        out[sort] = view
    return out


def project(name: str) -> dict:
    detail = core.project_detail(name)
    view = fviews.dash_view(core.REPO_ROOT, repo=name)
    detail["row"] = next((r for r in view["rows"] if r["name"] == name), None)
    detail["inbox"] = view["inbox"]
    return detail


def lake() -> dict:
    return {"present": False, "snapshot": True, "error": f"The data lake {LOCAL_ONLY}.", "tables": {},
            "repos": [], "agent_runs": {"count": 0}, "exports": {"count": 0},
            "phoenix": {"collector": "", "ui": "", "reachable": None}}


def lake_review() -> dict:
    doc = core.lake_review(30, None, 15)
    doc.pop("db_path", None)
    return doc | {"snapshot": True}


def observability() -> dict:
    return {"present": False, "snapshot": True, "error": f"The observability stack {LOCAL_ONLY}.",
            "planes": {}, "datasets": [], "embeds": {}, "shipments": {"count": 0, "last": None}}


def documents() -> dict[str, object]:
    """path under snapshot/ (no .json) → document."""
    registry = [p for p in core.load_yaml(core.DATA / "projects.yml") or [] if isinstance(p, dict) and p.get("name")]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    docs: dict[str, object] = {
        "health": {"ok": True, "snapshot": True, "repo_root": HUB, "jobs": 0},
        "state": state(),
        "capabilities": capabilities(),
        "ops": core.list_ops(),
        "keys": fkeys.as_json("web"),
        "theme": {"tokens": ftheme.TOKENS, "levels": ftheme.LEVEL_ROLE},
        "jobs": [],
        "config": core.read_config(),
        "contract": core.read_contract(),
        "content": core.content_report(),
        "work": core.work_board(local=False),
        "lake": lake(),
        "lake/runs": [],
        "lake/lines": [],
        "lake/review": lake_review(),
        "observability": observability(),
        "index/coverage": {"projects": [], "snapshot": True, "error": f"The code index {LOCAL_ONLY}."},
        "tui/status": {"available": False, "active": 0, "max": 0, "app": "tools/tui/app.py"},
        "fleet/docker": {"hosts": [], "containers": [], "errors": {"snapshot": f"Docker {LOCAL_ONLY}."},
                         "polled_at": now},
        "github/status": {"connected": False, "source": None, "kind": None, "login": None, "name": None,
                          "avatar_url": None, "scopes": [], "rate": None, "error": None, "session_set": False,
                          "writes_enabled": False, "auth_writes": False, "fleet_owner": ghl._hub_owner(),
                          "oauth": {"client_id_set": False, "client_secret_set": False, "device_flow": False,
                                    "web_flow": False, "default_scopes": "", "callback_url": "",
                                    "new_app_url": "", "authorized_apps_url": ""}},
        "github/fleet": {"owner": ghl._hub_owner(), "hub": ghl._hub(), "repos": ghl.fleet_repos(),
                         "dispatchable": {wf: sorted(i) for wf, i in core.DISPATCHABLE.items()}},
        "github/log": [],
        "site": site_docs.site_index(include_drafts=False),
    }
    for sort, view in fleet_views().items():
        docs[f"fleet/{sort}"] = view
    for p in registry:
        docs[f"project/{p['name']}"] = project(p["name"])
    for meta in site_docs.pages():
        docs[f"site/page/{meta['slug']}"] = site_docs.page(meta["slug"])
    for meta in site_docs.posts():
        docs[f"site/post/{meta['slug']}"] = site_docs.post(meta["slug"])
    for name in site_docs.PUBLIC_DATA:
        value = site_docs.data(name)
        if value is not None:
            docs[f"data/{name}"] = value
    return docs


# --------------------------------------------------------------------------- #
# The pages around the documents
# --------------------------------------------------------------------------- #
def routes(docs: dict) -> dict[str, tuple[str, str]]:
    """Every path a crawler or a pasted link can land on → (title, description)."""
    out = dict(STATIC_ROUTES)
    for meta in docs["site"]["pages"]:
        out[meta["slug"]] = (meta["title"], meta["description"])
    for meta in docs["site"]["posts"]:
        out[f"blog/{meta['slug']}"] = (meta["title"], meta["excerpt"])
    for key, doc in docs.items():
        if key.startswith("project/"):
            reg = doc["registry"]
            out[f"projects/{reg['name']}"] = (reg["name"], str(reg.get("description") or ""))
    # In the registry's own casing: links carry GitHub's full_name, and Pages
    # paths are case-sensitive (fleet_repos() keys are lowercased for lookup).
    owned = docs["github/fleet"]["repos"]
    for key, doc in docs.items():
        m = re.match(r"^https?://github\.com/([^/]+/[^/#?]+?)(?:\.git)?/?$", str(doc["registry"].get("repo_url") or "")) \
            if key.startswith("project/") else None
        if m and m.group(1).lower() in owned:
            out[f"github/{m.group(1)}"] = (m.group(1), f"Issues, pull requests, runs and workflows of {m.group(1)}.")
    hub = str(docs["github/fleet"]["hub"].get("repo") or HUB)
    out.setdefault(f"github/{hub}", (hub, f"Issues, pull requests, runs and workflows of {hub}."))
    for loop in docs["state"].get("loops") or []:
        out[f"loops/{loop['id']}"] = (str(loop.get("title") or loop["id"]), str(loop.get("summary") or ""))
    for site in docs["content"].get("declared") or []:
        out[f"content/{site['name']}"] = (site["name"], f"Content atlas for {site['name']}.")
    for section in docs["config"].get("sections") or []:
        out[f"config/{section['key']}"] = (f"Config · {section['title']}", str(section.get("blurb") or ""))
    for op in docs["ops"]:
        out[f"ops/{op['id']}"] = (op["title"], str(op.get("desc") or ""))
    for legacy in LEGACY_ROUTES:
        out.setdefault(legacy, ("Redirecting", ""))
    return out


def _page(template: str, title: str, description: str, url: str, site: dict) -> str:
    full = f"{title} · {site['title']}" if title and title != "Home" else f"{site['title']} — {site.get('name', '')}".strip(" —")
    description = re.sub(r"\s+", " ", description or site.get("description") or "").strip()[:300]
    head = "\n".join([
        f'<meta name="description" content="{html.escape(description)}">',
        f'<link rel="canonical" href="{html.escape(url)}">',
        f'<meta property="og:title" content="{html.escape(full)}">',
        f'<meta property="og:description" content="{html.escape(description)}">',
        f'<meta property="og:url" content="{html.escape(url)}">',
        f'<meta property="og:image" content="{html.escape(site["image"])}">',
        '<meta property="og:type" content="website">',
        '<meta name="twitter:card" content="summary">',
        f'<link rel="alternate" type="application/atom+xml" title="{html.escape(site["title"])}" href="{html.escape(site["feed"])}">',
    ])
    page = re.sub(r"<title>.*?</title>", f"<title>{html.escape(full)}</title>", template, count=1, flags=re.S)
    return page.replace("</head>", f"{head}\n</head>", 1)


def _feed(posts: list[dict], site: dict, updated: str) -> str:
    entries = []
    for p in posts:
        link = f"{site['url']}/blog/{p['slug']}"
        entries.append(
            f"<entry><title>{xml_escape(p['title'])}</title><link href=\"{xml_escape(link)}\"/>"
            f"<id>{xml_escape(link)}</id><updated>{p['date']}T00:00:00Z</updated>"
            f"<summary>{xml_escape(p['excerpt'])}</summary></entry>")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{xml_escape(site['title'])}</title><link href=\"{xml_escape(site['url'])}/\"/>"
            f"<link rel=\"self\" href=\"{xml_escape(site['feed'])}\"/><id>{xml_escape(site['url'])}/</id>"
            f"<updated>{updated}</updated><author><name>{xml_escape(site.get('name', ''))}</name></author>"
            + "".join(entries) + "</feed>\n")


def build(out: Path, base: str, site_url: str) -> dict:
    out = out.resolve()
    index = out / "index.html"
    if not index.is_file():
        raise SystemExit(f"snapshot: {index} is missing — build the page first (tools/console/build-pages.sh)")
    template = index.read_text(encoding="utf-8")
    snap_dir = out / "snapshot"
    if snap_dir.exists():
        shutil.rmtree(snap_dir)

    docs = documents()
    for key, doc in docs.items():
        _json(snap_dir / f"{key}.json", doc)

    site_url = site_url.rstrip("/")
    prof = docs["site"]["profile"]
    ident = prof.get("site") or {}
    site = {"title": ident.get("title") or HUB, "name": prof.get("name") or "",
            "description": ident.get("description") or "", "url": site_url,
            "feed": f"{site_url}/feed.xml", "image": f"{site_url}/{prof.get('avatar') or 'favicon.svg'}"}
    pages = routes(docs)
    for path, (title, desc) in pages.items():
        target = out / path / "index.html" if path else index
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_page(template, title, desc, f"{site_url}/{path}", site), encoding="utf-8")
    (out / "404.html").write_text(_page(template, "Not found", "", f"{site_url}/404.html", site), encoding="utf-8")

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    stamp = now.isoformat().replace("+00:00", "Z")
    urls = "".join(f"<url><loc>{xml_escape(f'{site_url}/{p}')}</loc></url>"
                   for p in sorted(pages) if p not in LEGACY_ROUTES)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/'
                                     f'schemas/sitemap/0.9">{urls}</urlset>\n', encoding="utf-8")
    (out / "feed.xml").write_text(_feed(docs["site"]["posts"], site, stamp), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site_url}/sitemap.xml\n", encoding="utf-8")
    (out / "theme.css").write_text(ftheme.css(), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run = os.environ.get("GITHUB_RUN_ID")
    manifest = {
        "schema": "console-snapshot/v1", "generated_at": stamp, "base": base, "site_url": site_url,
        "commit": _git("rev-parse", "HEAD"), "commit_date": _git("log", "-1", "--format=%cI"),
        "repo": os.environ.get("GITHUB_REPOSITORY") or HUB,
        "run_url": f"{server}/{os.environ.get('GITHUB_REPOSITORY', HUB)}/actions/runs/{run}" if run else None,
        "documents": len(docs), "routes": len(pages),
    }
    _json(snap_dir / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=HERE / "web" / "dist", help="the built page (vite's dist/)")
    ap.add_argument("--base", default="/bamr87/", help="the path the site is served under")
    ap.add_argument("--site-url", default="https://bamr87.github.io/bamr87", help="absolute URL of the site root")
    args = ap.parse_args(argv)
    try:
        manifest = build(args.out, args.base, args.site_url)
    finally:
        shutil.rmtree(_EMPTY_LAKE, ignore_errors=True)
    print(f"snapshot: {manifest['documents']} documents, {manifest['routes']} routes → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
app — the Harness Console's HTTP surface (FastAPI).

Thin by design: every route is a call into core.py (state, allowlist, jobs,
contract). Run it with tools/console/run.sh (native) or `docker compose up -d
console`; open http://127.0.0.1:4001/. Interactive API docs at /docs.

Security posture: loopback by default; an optional shared secret
(DASH_CONSOLE_TOKEN) is required as `Authorization: Bearer …` on every /api
route when set — the knob for running the console anywhere but localhost.
Binding to loopback is not on its own enough: a page on any site can make the
browser resolve its own hostname to 127.0.0.1 (DNS rebinding) and then speak
to this origin as same-origin, which for a console that can dispatch
workflows and run --apply fan-outs with the operator's FLEET_TOKEN is a real
lever. So every request's Host header is checked against a loopback allowlist
(extend it with DASH_CONSOLE_ALLOWED_HOSTS when fronting the console with a
proxy or a real hostname).
A Content-Security-Policy rides alongside that guard: the page is a built
bundle with no inline script, so `script-src 'self'` holds; frame-src names
the observability UIs the Observe pages embed, and frame-ancestors 'none'
stops anything embedding this console in turn. The WebSocket the Terminal
page uses never passes through HTTP middleware, so tui_bridge.py repeats the
Host check and adds an Origin check of its own.
Credentials: jobs inherit the process environment exactly like a terminal
would, and every status document reports credential NAMES and presence only —
never a value or a prefix. The /api/auth routes let the operator hand this
process a credential (it lives in the environment a job inherits, dies with the
process, and is written to the gitignored .env only on an explicit confirm) or
hand a GitHub token to `gh auth login --with-token` over stdin, so the one
surface meant to be self-sufficient no longer dead-ends at "go find a
terminal". DASH_CONSOLE_AUTH=off refuses every credential write.
"""
from __future__ import annotations

import os
import re
import secrets as _secrets
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

import core
import github_link as ghl
import tui_bridge

# The core both surfaces share (tools/fleetcore): the fleet views the TUI
# renders, the keys v1 table, and the bashOS palette.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fleetcore import keys as fkeys  # noqa: E402
from fleetcore import theme as ftheme  # noqa: E402
from fleetcore import views as fviews  # noqa: E402

# The page: a React + Mantine app (web/), built by run.sh into web/dist.
WEB_DIST = Path(os.environ.get("CONSOLE_WEB_DIST") or (Path(__file__).resolve().parent / "web" / "dist"))
app = FastAPI(title="bamr87 Harness Console", version="1.0.0",
              description="Local control plane for the fleet's AI harnesses and schedules — "
                          "with the local data lake, Phoenix traces and the content atlas.")
jobs = core.JobManager()

# Hosts this console answers to. Loopback names only by default; a deployment
# behind a proxy or on a real hostname names itself in DASH_CONSOLE_ALLOWED_HOSTS
# (comma-separated) — and should also set DASH_CONSOLE_TOKEN.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"} | {
    h.strip().lower() for h in (os.environ.get("DASH_CONSOLE_ALLOWED_HOSTS") or "").split(",") if h.strip()
}
tui = tui_bridge.TuiBridge(ALLOWED_HOSTS)


@app.middleware("http")
async def guard_host(request: Request, call_next):
    """Reject a rebound hostname before any route sees it (see module docstring)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip().lower()
    if host and host not in ALLOWED_HOSTS:
        return JSONResponse(status_code=421, content={
            "detail": f"host '{host}' is not allowed — the console answers on loopback only; "
                      "set DASH_CONSOLE_ALLOWED_HOSTS to serve another hostname"})
    return await call_next(request)


# Paths FastAPI renders itself: Swagger UI loads its script from a CDN and
# boots it inline, so the page's strict policy would blank it.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_HOST_RX = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")


def content_policy(path: str, host: str) -> str:
    """The Content-Security-Policy for one response.

    The console page is a built bundle: every script is a file under
    /assets, none is inline, so `script-src 'self'` holds and an injected
    <script> cannot run — the policy the hand-written page (one file of inline
    script) could never carry. Styles keep 'unsafe-inline' because Mantine and
    xterm.js set style attributes; that admits no script.

    frame-src names the observability UIs the Observe pages embed
    (_data/fleet.yml `observability.portal.frame_src`) and frame-ancestors
    'none' stops anything embedding this console — it can dispatch workflows
    with the operator's FLEET_TOKEN. connect-src names the page's own ws://
    origin explicitly, for the Terminal page, because older Safari does not
    let 'self' cover WebSocket schemes; the Host is echoed only when it is a
    plain host[:port], so a crafted Host cannot inject a directive.
    """
    frames = " ".join(core.frame_src())
    if path.startswith(_DOCS_PATHS):
        return f"frame-src 'self' {frames}".strip() + "; frame-ancestors 'none'"
    ws = f" ws://{host} wss://{host}" if host and _HOST_RX.match(host) else ""
    return "; ".join([
        "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
        # The GitHub page shows the connected account's avatar.
        "img-src 'self' data: https://avatars.githubusercontent.com", "font-src 'self' data:", f"connect-src 'self'{ws}",
        f"frame-src 'self' {frames}".strip(), "frame-ancestors 'none'",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'",
    ])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = content_policy(
        request.url.path, (request.headers.get("host") or "").strip())
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("DASH_CONSOLE_TOKEN")
    if not expected:
        return
    # constant-time: the token is a shared secret, so don't leak its prefix
    # through comparison timing.
    # RFC 7235: the scheme is case-insensitive, and neither side should fail
    # on stray whitespace from a paste or an env file.
    scheme, _, credential = (authorization or "").strip().partition(" ")
    if scheme.lower() != "bearer" or not _secrets.compare_digest(
            credential.strip().encode(), expected.strip().encode()):
        raise HTTPException(status_code=401, detail="console token required")


class JobRequest(BaseModel):
    op: str
    params: dict = Field(default_factory=dict)
    confirm: bool = False


class ContractUpdate(BaseModel):
    changes: dict


class CredentialUpdate(BaseModel):
    name: str
    value: str
    persist: bool = False
    confirm: bool = False


class EditorialDecision(BaseModel):
    site: str
    action: str                    # approve | reject | add | status | remove
    key: str
    fields: dict = Field(default_factory=dict)


class EditorialSite(BaseModel):
    fields: dict


class OAuthStart(BaseModel):
    flow: str = "device"           # device | web
    store: str = "session"         # session | gh | env
    scopes: str = ""
    confirm: bool = False


class GithubDisconnect(BaseModel):
    target: str = "session"        # session | gh


class GithubAction(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)
    confirm: bool = False


class GithubAuth(BaseModel):
    action: str = "login"          # login | logout
    token: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "repo_root": str(core.REPO_ROOT), "jobs": len(jobs.order)}


@app.get("/api/state", dependencies=[Depends(require_token)])
def state() -> dict:
    return core.load_state()


@app.get("/api/capabilities", dependencies=[Depends(require_token)])
def caps() -> dict:
    return core.capabilities()


@app.get("/api/ops", dependencies=[Depends(require_token)])
def ops() -> list[dict]:
    return core.list_ops()


@app.get("/api/jobs", dependencies=[Depends(require_token)])
def list_jobs() -> list[dict]:
    return jobs.list()


@app.post("/api/jobs", dependencies=[Depends(require_token)], status_code=201)
def submit_job(req: JobRequest) -> dict:
    try:
        job = jobs.submit(req.op, req.params, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job.to_dict()


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
def job_log(job_id: str, offset: int = Query(default=0, ge=0)) -> dict:
    try:
        return jobs.tail(job_id, offset)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such job")


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def cancel_job(job_id: str) -> dict:
    try:
        return jobs.cancel(job_id).to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail="no such job")


@app.get("/api/lake", dependencies=[Depends(require_token)])
def lake(probe: bool = Query(default=True)) -> dict:
    """The local data lake + Phoenix reachability (dash-gen lake status --json)."""
    return core.lake_status(probe)


@app.get("/api/lake/runs", dependencies=[Depends(require_token)])
def lake_runs(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    return core.lake_runs(limit)


@app.get("/api/lake/lines", dependencies=[Depends(require_token)])
def lake_lines() -> list[dict]:
    """Every workflow in the lake with its GitFactory provenance and kill switch."""
    return core.lake_lines()


@app.get("/api/lake/review", dependencies=[Depends(require_token)])
def lake_review(days: int = Query(default=30, ge=1, le=3650),
                repo: str | None = Query(default=None),
                limit: int = Query(default=10, ge=1, le=100)) -> dict:
    """Local Claude Code sessions + CI agent runs, unified and analyzed."""
    return core.lake_review(days, repo, limit)


@app.get("/api/index/coverage", dependencies=[Depends(require_token)])
def index_coverage() -> dict:
    """Chunk counts per submodule, plus scanner blind spots (dot-directories)."""
    return core.index_coverage()


@app.get("/api/index/search", dependencies=[Depends(require_token)])
def index_search(q: str = Query(default="", max_length=500)) -> dict:
    """Semantic search over the code index, hits below the contract floor dropped."""
    return core.index_query("search", q)


@app.get("/api/index/harmonize", dependencies=[Depends(require_token)])
def index_harmonize(q: str = Query(default="", max_length=500)) -> dict:
    """Which submodules share a pattern, and which do not."""
    return core.index_query("harmonize", q)


@app.get("/api/observability", dependencies=[Depends(require_token)])
def observability() -> dict:
    """The Observe tab's document: the three planes, the Kilo code index, the
    dataset sizes against the disk budget, the ship ledger, and the embed URLs."""
    return core.observe_status()


@app.get("/api/content", dependencies=[Depends(require_token)])
def content(site: str | None = Query(default=None, max_length=64)) -> dict:
    """The content atlas: every declared site analyzed from the lake (topics,
    activity, aging, hygiene, pillar coverage) with its editorial suggestions."""
    try:
        return core.content_report(site)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/content/{site}/docs", dependencies=[Depends(require_token)])
def content_docs(site: str, view: str = Query(default="all", max_length=80),
                 q: str = Query(default="", max_length=120),
                 limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    try:
        return core.content_documents(site, view=view, q=q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/content/{site}/brief", dependencies=[Depends(require_token)])
def content_brief(site: str) -> dict:
    try:
        return core.content_brief(site)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/editorial/decision", dependencies=[Depends(require_token)])
def editorial_decision(req: EditorialDecision) -> dict:
    """Approve/reject a suggestion, add or move a directive — _data/editorial.yml
    in the working tree, comments preserved; returns the git diff."""
    try:
        return core.editorial_decide(req.site, req.action, req.key, req.fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.put("/api/editorial/{site}", dependencies=[Depends(require_token)])
def editorial_site(site: str, req: EditorialSite) -> dict:
    """Set a site's narrative / audience / voice, or upsert one pillar."""
    try:
        return core.editorial_update(site, req.fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/contract", dependencies=[Depends(require_token)])
def contract() -> dict:
    return core.read_contract()


@app.put("/api/contract", dependencies=[Depends(require_token)])
def update_contract(req: ContractUpdate) -> dict:
    try:
        return core.update_contract(req.changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/config", dependencies=[Depends(require_token)])
def config() -> dict:
    """Every editable knob of _data/fleet.yml with its current value."""
    return core.read_config()


@app.put("/api/config", dependencies=[Depends(require_token)])
def update_config(req: ContractUpdate) -> dict:
    """Apply changes to fleet.yml (comments preserved) and return the git diff."""
    try:
        return core.update_config(req.changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/auth", dependencies=[Depends(require_token)])
def auth() -> dict:
    """Credential presence + provenance, gh login state, .env facts. No values."""
    return core.auth_status()


@app.put("/api/auth/credential", dependencies=[Depends(require_token)])
def set_credential(req: CredentialUpdate) -> dict:
    try:
        return core.set_credential(req.name, req.value, req.persist, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.delete("/api/auth/credential/{name}", dependencies=[Depends(require_token)])
def clear_credential(name: str, purge: bool = Query(default=False)) -> dict:
    try:
        return core.clear_credential(name, purge)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.post("/api/auth/github", dependencies=[Depends(require_token)])
def auth_github(req: GithubAuth) -> dict:
    """Sign the gh CLI in with a pasted token (stdin, never argv) or sign it out."""
    try:
        if req.action == "logout":
            return core.gh_logout()
        if req.action != "login":
            raise ValueError("action must be 'login' or 'logout'")
        return core.gh_login(req.token or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/project/{name}", dependencies=[Depends(require_token)])
def project(name: str) -> dict:
    """One project, every signal joined on its name: the registry entry, the
    Apps row and its every open item (fleetcore — what the TUI shows), its
    harness deployment and crons, the attention that names it, and its runs
    and workflows in the lake. The page's project drill-down."""
    try:
        detail = core.project_detail(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no registry project named '{name}'")
    view = fviews.dash_view(core.REPO_ROOT, repo=name)
    detail["row"] = next((r for r in view["rows"] if r["name"] == name), None)
    detail["inbox"] = view["inbox"]
    return detail


@app.get("/api/tui/status", dependencies=[Depends(require_token)])
def tui_status() -> dict:
    """Can the Terminal page start the terminal dash here, and how many run."""
    return tui.status()


@app.websocket("/api/tui")
async def tui_socket(websocket: WebSocket) -> None:
    """The terminal dash on a pty, relayed to xterm.js (tui_bridge.py: the
    Host + Origin checks, the hello-frame token, the session cap)."""
    await tui.serve(websocket)


# --------------------------------------------------------------------------- #
# GitHub — OAuth App sign-in + fleet repo management (github_link.py)
# --------------------------------------------------------------------------- #
def _gh_errors(fn):
    try:
        return fn()
    except ghl.GitHubError as exc:
        raise HTTPException(status_code=exc.status if 400 <= exc.status < 600 else 502, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/github/status", dependencies=[Depends(require_token)])
def github_status() -> dict:
    """Who the console is on GitHub: login, token source and kind, scopes, rate
    limit, and the OAuth App's configuration. Never a token."""
    return ghl.status()


@app.post("/api/github/oauth/start", dependencies=[Depends(require_token)])
def github_oauth_start(req: OAuthStart, request: Request) -> dict:
    """Begin an OAuth App sign-in: the device flow (a code to type at
    github.com/login/device) or the browser flow (a URL to open)."""
    if req.flow == "device":
        return _gh_errors(lambda: ghl.start_device(req.store, req.scopes, req.confirm))
    if req.flow == "web":
        return _gh_errors(lambda: ghl.start_web(req.store, req.scopes, request.headers.get("host") or "", req.confirm))
    raise HTTPException(status_code=400, detail="flow must be 'device' or 'web'")


@app.get("/api/github/oauth/device/{flow_id}", dependencies=[Depends(require_token)])
def github_oauth_poll(flow_id: str) -> dict:
    try:
        return _gh_errors(lambda: ghl.poll_device(flow_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="no such sign-in — start again")


@app.get(ghl.CALLBACK_PATH, include_in_schema=False)
def github_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                          error_description: str | None = None) -> RedirectResponse:
    """GitHub sends the browser back here. A top-level navigation carries no
    bearer token, so this route is guarded by the flow's single-use `state`
    (minted by an authenticated /oauth/start) plus PKCE, and by the Host
    allowlist like every route. The token never reaches the browser: the
    page is redirected with a status word only."""
    try:
        result = ghl.finish_web(code, state, error_description or error)
    except (PermissionError, ValueError, RuntimeError, ghl.GitHubError) as exc:
        result = {"status": "error", "message": str(exc)}
    from urllib.parse import urlencode
    q = {"oauth": result.get("status") or "error"}
    if result.get("status") != "connected":
        q["message"] = (result.get("message") or "")[:200]
    return RedirectResponse(f"/github?{urlencode(q)}", status_code=303)


@app.post("/api/github/disconnect", dependencies=[Depends(require_token)])
def github_disconnect(req: GithubDisconnect) -> dict:
    return _gh_errors(lambda: ghl.disconnect(req.target))


@app.get("/api/github/repos", dependencies=[Depends(require_token)])
def github_repos() -> list[dict]:
    """Every repo the connected account can see, newest push first, with the
    fleet's own (writable) ones marked."""
    return _gh_errors(ghl.list_repos)


@app.get("/api/github/repos/{owner}/{repo}", dependencies=[Depends(require_token)])
def github_repo(owner: str, repo: str) -> dict:
    return _gh_errors(lambda: ghl.repo_detail(f"{owner}/{repo}"))


@app.get("/api/github/repos/{owner}/{repo}/issues/{number}", dependencies=[Depends(require_token)])
def github_issue(owner: str, repo: str, number: int) -> dict:
    return _gh_errors(lambda: ghl.issue_thread(f"{owner}/{repo}", number))


@app.post("/api/github/repos/{owner}/{repo}/actions", dependencies=[Depends(require_token)])
def github_action(owner: str, repo: str, req: GithubAction) -> dict:
    """One write to a fleet repo (issues, runs, workflows) — confirm-gated,
    limited to repos the hub owns, recorded in the action log."""
    return _gh_errors(lambda: ghl.act(f"{owner}/{repo}", req.action, req.params, req.confirm))


@app.get("/api/github/log", dependencies=[Depends(require_token)])
def github_log() -> list[dict]:
    return ghl.action_log()


@app.get("/api/fleet", dependencies=[Depends(require_token)])
def fleet_view(q: str = Query(default="", max_length=120), sort: str = Query(default="featured", max_length=20),
               health: str | None = Query(default=None, max_length=10),
               repo: str | None = Query(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")) -> dict:
    """The terminal dash's Apps / Inbox / Harness data — fleetcore.views, the
    same objects and the same filter/sort functions tools/tui renders with, so
    the two surfaces cannot disagree."""
    return fviews.dash_view(core.REPO_ROOT, q=q, sort=sort, health=health, repo=repo)


@app.get("/api/fleet/docker", dependencies=[Depends(require_token)])
def fleet_docker() -> dict:
    """Containers on every DASH_DOCKER_HOST, attributed to registry rows. In
    the compose service there is no Docker socket on purpose (a write-capable
    console holding one would be root on the Docker host), so each host reports
    its error and the terminal dash's Docker tab is where containers live."""
    return fviews.dash_view(core.REPO_ROOT, docker=True)["docker"]


@app.get("/api/keys")
def keymap() -> list[dict]:
    """keys v1 — the one keymap the page and the TUI both bind (fleetcore.keys)."""
    return fkeys.as_json("web")


@app.get("/api/theme")
def theme_tokens() -> dict:
    """The bashOS palette as data (fleetcore.theme.TOKENS): the Terminal page
    colours xterm.js from the DARK roles, which the TUI always draws in."""
    return {"tokens": ftheme.TOKENS, "levels": ftheme.LEVEL_ROLE}


@app.get("/theme.css", include_in_schema=False)
def theme_css() -> Response:
    return Response(ftheme.css(), media_type="text/css")


@app.get("/api", include_in_schema=False)
def api_root() -> JSONResponse:
    return JSONResponse({"routes": sorted({r.path for r in app.routes
                                            if getattr(r, "path", "").startswith("/api/")})
                         + ["/docs"]})


# --------------------------------------------------------------------------- #
# The page. Every path that is not an API route, /docs or /theme.css is the
# single-page app: a file from web/dist when one exists there, index.html
# otherwise, so /projects/zer0-mistakes is a deep link a reload keeps.
# --------------------------------------------------------------------------- #
_UNBUILT = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Harness Console</title>
<link rel="stylesheet" href="/theme.css"><style>body{font:15px/1.5 system-ui,sans-serif;margin:0;
background:var(--page);color:var(--ink)}main{max-width:640px;margin:12vh auto;padding:0 16px}
code,pre{font-family:ui-monospace,Menlo,monospace}pre{background:var(--surface);padding:12px;
border:1px solid var(--border);border-radius:8px}</style></head><body><main>
<h1>Harness Console</h1><p>The API is running, but the page has not been built yet.</p>
<pre>cd tools/console/web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p><code>tools/dash console</code> does this on start whenever <code>npm</code> is on the PATH.
The API itself is browsable at <a href="/docs">/docs</a>.</p></main></body></html>"""


def _dist_file(path: str) -> Path | None:
    if not path:
        return None
    root = WEB_DIST.resolve()
    candidate = (root / path).resolve()
    if candidate.is_file() and root in candidate.parents:
        return candidate
    return None


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str) -> Response:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="no such API route")
    hit = _dist_file(path)
    if hit:
        # Vite fingerprints everything under assets/, so it can be cached for good.
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(hit, headers={"Cache-Control": cache})
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(_UNBUILT, status_code=503)

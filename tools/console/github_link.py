#!/usr/bin/env python3
"""github_link — sign the console in to GitHub through an OAuth App, and manage
the fleet's repos with the token that sign-in yields.

Two ways to connect, both standard GitHub OAuth App flows:

  device flow   the console asks GitHub for a one-time user code, the operator
                types it at github.com/login/device, and the console polls for
                the token. Needs only the app's CLIENT ID (no secret, no
                callback), so it works the same natively, in Docker and over
                SSH. "Enable Device Flow" must be ticked in the app's settings.
  web flow      the browser is sent to github.com/login/oauth/authorize and
                comes back to /api/github/oauth/callback. Needs the CLIENT
                SECRET too. Protected by a single-use `state` and PKCE (S256).
                Register the callback as http://127.0.0.1/api/github/oauth/callback:
                GitHub lets a loopback callback come back on any port.

The app's identity comes from GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET
(credentials the console can be handed on its Credentials page, like any other).

Where the token goes is the operator's choice, and it never comes back out:

  session   GH_TOKEN in this process's environment — what every job and every
            gh call the console makes inherits; gone when the console stops
  gh        `gh auth login --with-token` over stdin — the CLI's own store keeps it
  env       session + GH_TOKEN written to the gitignored .env (explicit confirm)

Repo management reads any repo the token can see, and WRITES only to fleet
repos the hub owns (the registry's repos under the hub's owner, plus the hub
itself): issues (open, comment, close, reopen, label), workflow runs (re-run
failed jobs, cancel) and workflows (enable, disable). Every write needs
confirm=true and is recorded in an in-memory action log. Nothing here merges,
deletes, pushes, or changes repo settings — the same line the console's jobs
never cross. DASH_CONSOLE_GITHUB_WRITES=off makes the whole surface read-only.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import core

API = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
WEB = (os.environ.get("GITHUB_WEB_URL") or "https://github.com").rstrip("/")
USER_AGENT = "bamr87-harness-console"
DEFAULT_SCOPES = "repo workflow read:org"
CALLBACK_PATH = "/api/github/oauth/callback"
FLOW_TTL = 15 * 60           # GitHub's device codes live 15 minutes; web flows get the same
STORES = ("session", "gh", "env")

GITHUB_WRITES = (os.environ.get("DASH_CONSOLE_GITHUB_WRITES", "on").strip().lower()
                 not in ("0", "off", "false", "no"))

NWO_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
SCOPE_RX = re.compile(r"^[a-z:_]+( [a-z:_]+){0,9}$")
LABEL_RX = re.compile(r"^[^\x00-\x1f]{1,50}$")


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# HTTP — one function, so tests can replace the network wholesale
# --------------------------------------------------------------------------- #
def _http(method: str, url: str, *, headers: dict, body: bytes | None, timeout: float = 20.0):
    """(status, headers, parsed JSON or None). Never raises on an HTTP status."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = {"message": raw.decode("utf-8", "replace")[:300]}
        return exc.code, dict(exc.headers or {}), data
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubError(0, f"GitHub is not reachable: {exc}") from None


def _oauth_post(path: str, fields: dict) -> dict:
    """A form POST to github.com's OAuth endpoints, answered as JSON."""
    status, _, data = _http("POST", WEB + path, body=urllib.parse.urlencode(fields).encode(),
                            headers={"Accept": "application/json", "User-Agent": USER_AGENT,
                                     "Content-Type": "application/x-www-form-urlencoded"})
    if status >= 400 and not isinstance(data, dict):
        raise GitHubError(status, f"GitHub answered {status}")
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# The token the console uses, and where it came from (never the value)
# --------------------------------------------------------------------------- #
_GH_CACHE: dict = {"at": 0.0, "token": None}


def _gh_cli_token() -> str | None:
    if time.time() - _GH_CACHE["at"] < 60:
        return _GH_CACHE["token"]
    token = None
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
        proc = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"], capture_output=True,
                              text=True, timeout=10, env=env, stdin=subprocess.DEVNULL)
        if proc.returncode == 0 and proc.stdout.strip():
            token = proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        token = None
    _GH_CACHE.update(at=time.time(), token=token)
    return token


def token_source() -> tuple[str | None, str | None]:
    """(source name, token). GH_TOKEN, then GITHUB_TOKEN, then gh's own login —
    the order gh itself uses, so the console and its jobs agree on who they are."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return name, os.environ[name]
    tok = _gh_cli_token()
    return ("gh" if tok else None), tok


def token_kind(token: str | None) -> str | None:
    """The token's type from its documented prefix — a kind, never a value."""
    if not token:
        return None
    for prefix, kind in (("gho_", "OAuth app"), ("ghu_", "GitHub App user"), ("ghp_", "classic PAT"),
                         ("github_pat_", "fine-grained PAT"), ("ghs_", "GitHub App installation")):
        if token.startswith(prefix):
            return kind
    return "unknown"


def api(method: str, path: str, payload: dict | None = None, *, token: str | None = None,
        want_headers: bool = False):
    tok = token or token_source()[1]
    if not tok:
        raise GitHubError(401, "not connected to GitHub — connect on the GitHub page")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": USER_AGENT, "Authorization": f"Bearer {tok}"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    status, hdrs, data = _http(method, path if path.startswith("http") else API + path,
                               headers=headers, body=body)
    if status >= 400:
        msg = (data or {}).get("message") if isinstance(data, dict) else None
        raise GitHubError(status, core._scrub(f"GitHub {status}: {msg or 'request failed'}"))
    return (data, hdrs) if want_headers else data


# --------------------------------------------------------------------------- #
# OAuth App configuration + flows
# --------------------------------------------------------------------------- #
def oauth_config() -> dict:
    return {"client_id_set": bool(os.environ.get("GITHUB_OAUTH_CLIENT_ID")),
            "client_secret_set": bool(os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")),
            "device_flow": bool(os.environ.get("GITHUB_OAUTH_CLIENT_ID")),
            "web_flow": bool(os.environ.get("GITHUB_OAUTH_CLIENT_ID") and os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")),
            "default_scopes": DEFAULT_SCOPES,
            "callback_url": f"http://127.0.0.1{CALLBACK_PATH}",
            "new_app_url": f"{WEB}/settings/applications/new",
            "authorized_apps_url": (f"{WEB}/settings/connections/applications/{os.environ['GITHUB_OAUTH_CLIENT_ID']}"
                                    if os.environ.get("GITHUB_OAUTH_CLIENT_ID") else f"{WEB}/settings/applications")}


_FLOWS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _prune() -> None:
    now = time.time()
    for k in [k for k, f in _FLOWS.items() if f["expires_at"] < now - 300]:
        _FLOWS.pop(k, None)


def _check(store: str, scopes: str) -> str:
    core._check_writes()                          # DASH_CONSOLE_AUTH=off refuses connecting too
    if store not in STORES:
        raise ValueError(f"store must be one of {STORES}")
    scopes = " ".join((scopes or DEFAULT_SCOPES).replace(",", " ").split())
    if not SCOPE_RX.match(scopes):
        raise ValueError("scopes must be GitHub scope names separated by spaces")
    return scopes


def _client_id() -> str:
    cid = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
    if not cid:
        raise RuntimeError("no OAuth App configured — set GITHUB_OAUTH_CLIENT_ID on the Credentials page "
                           "(create the app at github.com/settings/applications/new)")
    return cid


def start_device(store: str = "session", scopes: str = "", confirm: bool = False) -> dict:
    scopes = _check(store, scopes)
    if store == "env" and not confirm:
        raise PermissionError("writing the token to .env needs confirm=true")
    data = _oauth_post("/login/device/code", {"client_id": _client_id(), "scope": scopes})
    if "device_code" not in data:
        err = data.get("error_description") or data.get("error") or "GitHub refused the request"
        if data.get("error") == "device_flow_disabled":
            err = "Device flow is not enabled for this OAuth App — tick “Enable Device Flow” in its settings"
        raise GitHubError(400, err)
    flow_id = secrets.token_urlsafe(16)
    with _LOCK:
        _prune()
        _FLOWS[flow_id] = {"kind": "device", "device_code": data["device_code"], "store": store,
                           "scopes": scopes, "interval": int(data.get("interval") or 5),
                           "next_poll": time.time() + int(data.get("interval") or 5),
                           "expires_at": time.time() + int(data.get("expires_in") or FLOW_TTL),
                           "status": "pending", "message": None, "login": None}
    return {"flow_id": flow_id, "user_code": data.get("user_code"), "verification_uri": data.get("verification_uri"),
            "expires_in": int(data.get("expires_in") or FLOW_TTL), "interval": int(data.get("interval") or 5)}


def poll_device(flow_id: str) -> dict:
    """Advance a device flow. Calls GitHub at most once per its interval, however
    often the page asks, so a fast-polling page can never earn a slow_down."""
    with _LOCK:
        flow = _FLOWS.get(flow_id)
        if not flow or flow["kind"] != "device":
            raise KeyError(flow_id)
        if flow["status"] != "pending":
            return _public(flow)
        if time.time() > flow["expires_at"]:
            flow.update(status="expired", message="the code expired — start again")
            return _public(flow)
        if time.time() < flow["next_poll"]:
            return _public(flow)
        flow["next_poll"] = time.time() + flow["interval"]
        device_code, store = flow["device_code"], flow["store"]
    data = _oauth_post("/login/oauth/access_token", {
        "client_id": _client_id(), "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    with _LOCK:
        err = data.get("error")
        if err == "authorization_pending":
            pass
        elif err == "slow_down":
            flow["interval"] = int(data.get("interval") or flow["interval"] + 5)
            flow["next_poll"] = time.time() + flow["interval"]
        elif err in ("expired_token", "access_denied", "device_flow_disabled", "incorrect_client_credentials",
                     "incorrect_device_code", "unsupported_grant_type"):
            flow.update(status="denied" if err == "access_denied" else "expired" if err == "expired_token" else "error",
                        message=data.get("error_description") or err)
        elif data.get("access_token"):
            token = data["access_token"]
            flow.pop("device_code", None)
            flow["status"] = "delivering"
        else:
            flow.update(status="error", message=data.get("error_description") or err or "unexpected answer")
        if flow["status"] != "delivering":
            return _public(flow)
    return _finish(flow, token, store)


def start_web(store: str, scopes: str, host: str, confirm: bool = False) -> dict:
    scopes = _check(store, scopes)
    if store == "env" and not confirm:
        raise PermissionError("writing the token to .env needs confirm=true")
    cid = _client_id()
    if not os.environ.get("GITHUB_OAUTH_CLIENT_SECRET"):
        raise RuntimeError("the web flow needs GITHUB_OAUTH_CLIENT_SECRET — or use the device flow, which does not")
    port = host.rsplit(":", 1)[1] if re.match(r"^[^:]+:\d{1,5}$", host or "") else ""
    redirect_uri = f"http://127.0.0.1{':' + port if port else ''}{CALLBACK_PATH}"
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with _LOCK:
        _prune()
        _FLOWS[state] = {"kind": "web", "verifier": verifier, "redirect_uri": redirect_uri, "store": store,
                         "scopes": scopes, "expires_at": time.time() + FLOW_TTL, "status": "pending",
                         "message": None, "login": None}
    q = urllib.parse.urlencode({"client_id": cid, "redirect_uri": redirect_uri, "scope": scopes, "state": state,
                                "code_challenge": challenge, "code_challenge_method": "S256", "allow_signup": "false"})
    return {"authorize_url": f"{WEB}/login/oauth/authorize?{q}", "redirect_uri": redirect_uri}


def finish_web(code: str | None, state: str | None, error: str | None = None) -> dict:
    """The callback. `state` is single-use and short-lived, and it is the only
    thing that ties a browser landing here to a flow an AUTHENTICATED request
    started — so an unknown state is refused before any code is exchanged."""
    with _LOCK:
        flow = _FLOWS.pop(state or "", None)
    if not flow or flow["kind"] != "web" or flow["expires_at"] < time.time():
        raise PermissionError("unknown or expired sign-in — start it again from the console")
    if error:
        return {"status": "denied", "message": error}
    if not code or len(code) > 200:
        raise ValueError("GitHub sent no authorization code")
    data = _oauth_post("/login/oauth/access_token", {
        "client_id": _client_id(), "client_secret": os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""),
        "code": code, "redirect_uri": flow["redirect_uri"], "code_verifier": flow["verifier"]})
    if not data.get("access_token"):
        return {"status": "error", "message": data.get("error_description") or data.get("error") or "no token"}
    return _finish(flow, data["access_token"], flow["store"])


def _finish(flow: dict, token: str, store: str) -> dict:
    """Hand the token to its destination, then forget it."""
    try:
        if store == "gh":
            r = core.gh_login(token)
            if not r.get("ok"):
                raise GitHubError(400, r.get("message") or "gh refused the token")
        else:
            core.set_credential("GH_TOKEN", token, persist=(store == "env"), confirm=(store == "env"))
        _GH_CACHE.update(at=0.0, token=None)
        me = api("GET", "/user", token=token)
        with _LOCK:
            flow.update(status="connected", login=(me or {}).get("login"),
                        message=f"connected as {(me or {}).get('login')} ({store})")
    except Exception as exc:  # noqa: BLE001 — report it, scrubbed, rather than strand the flow
        with _LOCK:
            flow.update(status="error", message=core._scrub(str(exc)))
    return _public(flow)


def _public(flow: dict) -> dict:
    return {k: flow.get(k) for k in ("status", "message", "login", "store", "scopes")}


def disconnect(target: str) -> dict:
    """Drop the console's GitHub sign-in. `session` clears GH_TOKEN (and revokes
    it at GitHub when the app's secret is known and it is this app's token);
    `gh` signs the CLI out."""
    core._check_writes()
    revoked = False
    if target == "session":
        tok = os.environ.get("GH_TOKEN")
        cid, secret = os.environ.get("GITHUB_OAUTH_CLIENT_ID"), os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")
        if tok and tok.startswith("gho_") and cid and secret:
            basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
            try:
                status, _, _ = _http("DELETE", f"{API}/applications/{cid}/token",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT,
                                              "Authorization": f"Basic {basic}", "Content-Type": "application/json"},
                                     body=json.dumps({"access_token": tok}).encode())
                revoked = status == 204
            except GitHubError:
                revoked = False
        core.clear_credential("GH_TOKEN")
    elif target == "gh":
        core.gh_logout()
    else:
        raise ValueError("target must be 'session' or 'gh'")
    _GH_CACHE.update(at=0.0, token=None)
    return {"ok": True, "revoked": revoked, "status": status()}


def status() -> dict:
    """Who the console is on GitHub — names, scopes, rate, kind; never a token."""
    source, tok = token_source()
    out = {"connected": False, "source": source, "kind": token_kind(tok), "login": None, "name": None,
           "avatar_url": None, "scopes": [], "rate": None, "error": None,
           "session_set": "GH_TOKEN" in core._SESSION_CREDS, "writes_enabled": GITHUB_WRITES and core.AUTH_WRITES,
           "auth_writes": core.AUTH_WRITES, "oauth": oauth_config(), "fleet_owner": _hub_owner()}
    if not tok:
        return out
    try:
        me, hdrs = api("GET", "/user", token=tok, want_headers=True)
        h = {k.lower(): v for k, v in hdrs.items()}
        out.update(connected=True, login=me.get("login"), name=me.get("name"), avatar_url=me.get("avatar_url"),
                   scopes=[s.strip() for s in (h.get("x-oauth-scopes") or "").split(",") if s.strip()],
                   rate={"limit": _int(h.get("x-ratelimit-limit")), "remaining": _int(h.get("x-ratelimit-remaining")),
                         "reset": _int(h.get("x-ratelimit-reset"))})
    except GitHubError as exc:
        out["error"] = str(exc)
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# The fleet — which repos the console may WRITE to
# --------------------------------------------------------------------------- #
def _hub() -> dict:
    return ((core.load_yaml(core.DATA / "fleet.yml") or {}).get("hub") or {})


def _hub_owner() -> str:
    return str(_hub().get("repo") or "bamr87/bamr87").split("/")[0]


def fleet_repos() -> dict[str, str]:
    """owner/name (lowercased) → registry name, for the repos the hub OWNS.
    An external mirror in the registry (microsoft/skills) is readable, not writable."""
    owner = _hub_owner().lower()
    out: dict[str, str] = {}
    for p in core.load_yaml(core.DATA / "projects.yml") or []:
        if not isinstance(p, dict):
            continue
        m = re.match(r"^https?://github\.com/([^/]+/[^/#?]+?)(?:\.git)?/?$", str(p.get("repo_url") or ""))
        if m and m.group(1).split("/")[0].lower() == owner:
            out[m.group(1).lower()] = str(p.get("name"))
    hub = _hub()
    for key in ("repo", "shared"):
        if hub.get(key):
            out.setdefault(str(hub[key]).lower(), str(hub[key]).split("/")[1])
    return out


def _nwo(nwo: str) -> str:
    if not NWO_RX.match(nwo or ""):
        raise ValueError("expected owner/name")
    return nwo


# --------------------------------------------------------------------------- #
# READ
# --------------------------------------------------------------------------- #
def list_repos(pages: int = 3) -> list[dict]:
    fleet = fleet_repos()
    out: list[dict] = []
    for page in range(1, pages + 1):
        batch = api("GET", f"/user/repos?per_page=100&page={page}&sort=pushed"
                           "&affiliation=owner,collaborator,organization_member") or []
        for r in batch:
            full = r.get("full_name", "")
            out.append({
                "full_name": full, "name": r.get("name"), "owner": (r.get("owner") or {}).get("login"),
                "private": r.get("private"), "archived": r.get("archived"), "fork": r.get("fork"),
                "description": r.get("description"), "pushed_at": r.get("pushed_at"),
                "open_issues": r.get("open_issues_count"), "stars": r.get("stargazers_count"),
                "default_branch": r.get("default_branch"), "html_url": r.get("html_url"),
                "language": r.get("language"), "permissions": r.get("permissions") or {},
                "fleet_name": fleet.get(full.lower()), "writable": full.lower() in fleet,
            })
        if len(batch) < 100:
            break
    return out


def _slim_issue(i: dict) -> dict:
    return {"number": i.get("number"), "title": i.get("title"), "state": i.get("state"),
            "state_reason": i.get("state_reason"), "user": (i.get("user") or {}).get("login"),
            "labels": [lb.get("name") for lb in i.get("labels") or [] if isinstance(lb, dict)],
            "comments": i.get("comments"), "created_at": i.get("created_at"), "updated_at": i.get("updated_at"),
            "html_url": i.get("html_url"), "assignees": [a.get("login") for a in i.get("assignees") or []],
            "draft": i.get("draft"), "is_pr": "pull_request" in i}


def repo_detail(nwo: str) -> dict:
    nwo = _nwo(nwo)
    calls = {
        "repo": f"/repos/{nwo}",
        "issues": f"/repos/{nwo}/issues?state=open&per_page=50&sort=updated",
        "pulls": f"/repos/{nwo}/pulls?state=open&per_page=30&sort=updated",
        "runs": f"/repos/{nwo}/actions/runs?per_page=25",
        "workflows": f"/repos/{nwo}/actions/workflows?per_page=100",
        "labels": f"/repos/{nwo}/labels?per_page=100",
    }
    results: dict = {}
    errors: dict = {}

    def get(item):
        key, path = item
        try:
            return key, api("GET", path), None
        except GitHubError as exc:
            return key, None, str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for key, data, err in pool.map(get, calls.items()):
            results[key] = data
            if err:
                errors[key] = err
    if results.get("repo") is None:
        raise GitHubError(404, errors.get("repo") or f"cannot read {nwo}")
    r = results["repo"]
    fleet = fleet_repos()
    return {
        "nwo": r.get("full_name"), "fleet_name": fleet.get(nwo.lower()), "writable": nwo.lower() in fleet,
        "repo": {k: r.get(k) for k in ("description", "private", "archived", "fork", "default_branch", "html_url",
                                       "homepage", "language", "stargazers_count", "forks_count",
                                       "open_issues_count", "pushed_at", "visibility", "topics", "has_issues")}
                | {"permissions": r.get("permissions") or {}},
        "issues": [_slim_issue(i) for i in results.get("issues") or [] if "pull_request" not in i],
        "pulls": [{"number": p.get("number"), "title": p.get("title"), "user": (p.get("user") or {}).get("login"),
                   "draft": p.get("draft"), "head": (p.get("head") or {}).get("ref"),
                   "base": (p.get("base") or {}).get("ref"), "updated_at": p.get("updated_at"),
                   "html_url": p.get("html_url"), "labels": [lb.get("name") for lb in p.get("labels") or []]}
                  for p in results.get("pulls") or []],
        "runs": [{"id": x.get("id"), "name": x.get("name"), "display_title": x.get("display_title"),
                  "event": x.get("event"), "status": x.get("status"), "conclusion": x.get("conclusion"),
                  "branch": x.get("head_branch"), "created_at": x.get("created_at"), "html_url": x.get("html_url"),
                  "run_attempt": x.get("run_attempt"), "workflow_id": x.get("workflow_id")}
                 for x in (results.get("runs") or {}).get("workflow_runs", [])],
        "workflows": [{"id": w.get("id"), "name": w.get("name"), "path": w.get("path"), "state": w.get("state"),
                       "html_url": w.get("html_url")}
                      for w in (results.get("workflows") or {}).get("workflows", [])],
        "labels": [{"name": lb.get("name"), "color": lb.get("color"), "description": lb.get("description")}
                   for lb in results.get("labels") or []],
        "errors": errors,
    }


def issue_thread(nwo: str, number: int) -> dict:
    nwo = _nwo(nwo)
    n = _num(number, "number")
    issue = api("GET", f"/repos/{nwo}/issues/{n}")
    comments = api("GET", f"/repos/{nwo}/issues/{n}/comments?per_page=50") or []
    return {"issue": _slim_issue(issue) | {"body": issue.get("body") or ""},
            "comments": [{"id": c.get("id"), "user": (c.get("user") or {}).get("login"), "body": c.get("body") or "",
                          "created_at": c.get("created_at"), "html_url": c.get("html_url")} for c in comments]}


# --------------------------------------------------------------------------- #
# WRITE — confirm-gated, fleet-scoped, logged
# --------------------------------------------------------------------------- #
ACTION_LOG: deque = deque(maxlen=200)

ACTIONS = {
    "issue.create": "Open an issue",
    "issue.comment": "Comment on an issue or pull request",
    "issue.close": "Close an issue",
    "issue.reopen": "Reopen an issue",
    "issue.labels": "Add / remove labels",
    "run.rerun_failed": "Re-run a run's failed jobs",
    "run.cancel": "Cancel a run",
    "workflow.enable": "Enable a workflow",
    "workflow.disable": "Disable a workflow",
}


def _num(v, name: str) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if n <= 0 or n > 10**12:
        raise ValueError(f"{name} is out of range")
    return n


def _text(v, name: str, lo: int, hi: int) -> str:
    s = str(v or "").strip()
    if not lo <= len(s) <= hi:
        raise ValueError(f"{name} must be {lo}-{hi} characters")
    return s


def _labels(v) -> list[str]:
    items = v if isinstance(v, list) else [x for x in str(v or "").split(",")]
    out = [str(x).strip() for x in items if str(x).strip()]
    if len(out) > 20 or not all(LABEL_RX.match(x) for x in out):
        raise ValueError("labels: at most 20 names, 50 characters each")
    return out


def act(nwo: str, action: str, params: dict | None = None, confirm: bool = False) -> dict:
    nwo = _nwo(nwo)
    p = params or {}
    if action not in ACTIONS:
        raise ValueError(f"unknown action — one of {sorted(ACTIONS)}")
    if not (GITHUB_WRITES and core.AUTH_WRITES):
        raise PermissionError("GitHub writes are switched off (DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH)")
    if nwo.lower() not in fleet_repos():
        raise PermissionError(f"{nwo} is not a fleet repo the hub owns — the console reads it but will not write to it")
    if not confirm:
        raise PermissionError(f"{ACTIONS[action]} writes to GitHub — it needs confirm=true")

    target, call = "", None
    if action == "issue.create":
        body = {"title": _text(p.get("title"), "title", 1, 256), "body": _text(p.get("body"), "body", 0, 65536)}
        if p.get("labels"):
            body["labels"] = _labels(p.get("labels"))
        call = ("POST", f"/repos/{nwo}/issues", body)
    elif action == "issue.comment":
        n = _num(p.get("number"), "number")
        target = f"#{n}"
        call = ("POST", f"/repos/{nwo}/issues/{n}/comments", {"body": _text(p.get("body"), "comment", 1, 65536)})
    elif action in ("issue.close", "issue.reopen"):
        n = _num(p.get("number"), "number")
        target = f"#{n}"
        body: dict = {"state": "closed" if action == "issue.close" else "open"}
        if action == "issue.close":
            reason = p.get("reason") or "completed"
            if reason not in ("completed", "not_planned"):
                raise ValueError("reason must be completed or not_planned")
            body["state_reason"] = reason
        call = ("PATCH", f"/repos/{nwo}/issues/{n}", body)
    elif action == "issue.labels":
        n = _num(p.get("number"), "number")
        target = f"#{n}"
        add, remove = _labels(p.get("add")), _labels(p.get("remove"))
        if not add and not remove:
            raise ValueError("nothing to add or remove")
        call = ("LABELS", n, (add, remove))
    elif action in ("run.rerun_failed", "run.cancel"):
        rid = _num(p.get("run_id"), "run_id")
        target = f"run {rid}"
        call = ("POST", f"/repos/{nwo}/actions/runs/{rid}/{'rerun-failed-jobs' if action == 'run.rerun_failed' else 'cancel'}", None)
    elif action in ("workflow.enable", "workflow.disable"):
        wid = _num(p.get("workflow_id"), "workflow_id")
        target = f"workflow {wid}"
        call = ("PUT", f"/repos/{nwo}/actions/workflows/{wid}/{action.split('.')[1]}", None)

    entry = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "action": action,
             "label": ACTIONS[action], "repo": nwo, "target": target, "ok": False, "url": None, "error": None}
    try:
        if call[0] == "LABELS":
            n, (add, remove) = call[1], call[2]
            if add:
                api("POST", f"/repos/{nwo}/issues/{n}/labels", {"labels": add})
            for name in remove:
                try:
                    api("DELETE", f"/repos/{nwo}/issues/{n}/labels/{urllib.parse.quote(name, safe='')}")
                except GitHubError as exc:
                    if exc.status != 404:          # already absent is the goal state
                        raise
            result = None
        else:
            method, path, body = call
            result = api(method, path, body if body is not None else ({} if method == "POST" else None))
        entry["ok"] = True
        if isinstance(result, dict):
            entry["url"] = result.get("html_url")
            if action == "issue.create":
                entry["target"] = f"#{result.get('number')}"
    except GitHubError as exc:
        entry["error"] = str(exc)
        ACTION_LOG.appendleft(entry)
        raise
    ACTION_LOG.appendleft(entry)
    return entry


def action_log() -> list[dict]:
    return list(ACTION_LOG)

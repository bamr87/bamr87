#!/usr/bin/env python3
"""gh_projects — read GitHub Projects (v2) across every fleet owner and link
project items, issues, pull requests, commits and repos into one graph.

Read-only. GraphQL over stdlib HTTP (`_http` is swappable, so tests run on
recorded fixtures with no network). Results are cached in memory with a TTL.
A token without `read:project` degrades to an honest `scope_missing` result
instead of an error. Token values are never returned, logged or cached.

The read aggregator at the end (`projects_view`, `items_view`) is what the
console's `GET /api/gh-projects*` routes and the MCP's `gh_projects` /
`gh_project_items` serve (epic #468 P1): every owner in one document, each
with its projects or the reason it could not be read; a project's items paged
and capped; a sliding-window GraphQL call budget and a wall clock, past which
an answer is `partial` and says why, never a hang or a spent quota.

Docs: docs/PROJECTS-FRAMEWORK.md § 3a; constitution § 11 (amendment 0006
`projects-write-back`) for the write half, which lives in gh_projects_write.py
and is never imported here.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

API = "https://api.github.com/graphql"
OWNERS: tuple[tuple[str, str], ...] = (
    ("user", "bamr87"),
    ("organization", "year-of-ai"),
    ("organization", "ai-world-view"),
    ("organization", "bash-365"),
    ("organization", "EissaLab"),
)
TTL_SECONDS = 600
MAX_PROJECTS = 50
MAX_ITEMS = 500
PAGE = 100
TOKEN_ENV = ("PROJECTS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
REF_RE = re.compile(r"\b(HUB-\d{3}|(?:N?FR)\d+)\b")
SECRET_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


def redact(text: str) -> str:
    return SECRET_RE.sub("[redacted]", text or "")


def token() -> str | None:
    for k in TOKEN_ENV:
        if os.environ.get(k):
            return os.environ[k]
    return None


def _http(query: str, variables: dict, tok: str, timeout: float = 20) -> dict:  # pragma: no cover - network
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class ScopeMissing(Exception):
    pass


def gql(query: str, variables: dict | None = None, http: Callable | None = None, tok: str | None = None,
        partial: list[str] | None = None) -> dict:
    """One query → its `data`. `partial`, when given, collects the (redacted) messages of errors GitHub
    returned beside data — an owner the token cannot see comes back as `null` with one of those."""
    tok = tok or token()
    if not tok:
        raise ScopeMissing("no token: set PROJECTS_TOKEN (needs read:project)")
    out = (http or _http)(query, variables or {}, tok)
    errs = out.get("errors") or []
    for e in errs:
        if e.get("type") == "INSUFFICIENT_SCOPES" or "read:project" in str(e.get("message", "")):
            raise ScopeMissing("scope missing: read:project")
    if errs and not out.get("data"):
        raise RuntimeError(redact("; ".join(str(e.get("message")) for e in errs)))
    if partial is not None:
        partial.extend(redact(str(e.get("message")))[:300] for e in errs)
    return out.get("data") or {}


PROJECTS_Q = """query($login:String!,$n:Int!){ %s(login:$login){ projectsV2(first:$n){ nodes{
 id number title url closed shortDescription
 fields(first:50){ nodes{ ... on ProjectV2FieldCommon{ id name dataType }
   ... on ProjectV2SingleSelectField{ options{ id name } } } } } } } }"""

ITEMS_Q = """query($id:ID!,$n:Int!,$after:String){ node(id:$id){ ... on ProjectV2{ items(first:$n,after:$after){
 pageInfo{ hasNextPage endCursor } nodes{ id isArchived type
  fieldValues(first:30){ nodes{
   ... on ProjectV2ItemFieldSingleSelectValue{ name field{ ... on ProjectV2FieldCommon{ name } } }
   ... on ProjectV2ItemFieldTextValue{ text field{ ... on ProjectV2FieldCommon{ name } } }
   ... on ProjectV2ItemFieldNumberValue{ number field{ ... on ProjectV2FieldCommon{ name } } }
   ... on ProjectV2ItemFieldIterationValue{ title field{ ... on ProjectV2FieldCommon{ name } } } } }
  content{ __typename
   ... on Issue{ id number title state url body repository{ nameWithOwner } }
   ... on PullRequest{ id number title state url body repository{ nameWithOwner }
       closingIssuesReferences(first:20){ nodes{ number repository{ nameWithOwner } } }
       commits(last:20){ nodes{ commit{ oid messageHeadline } } } }
   ... on DraftIssue{ id title } } } } } } }"""


_cache: dict[str, tuple[float, Any]] = {}


def cached(key: str, fn: Callable[[], Any], ttl: int = TTL_SECONDS, now: Callable[[], float] = time.time,
           keep: Callable[[Any], bool] | None = None) -> Any:
    """`fn()` once per `ttl` per key. `keep` decides whether an answer is stored at all: a read that a
    transient failure cut short is served once and asked again next time, never held for the TTL."""
    hit = _cache.get(key)
    if hit and now() - hit[0] < ttl:
        return hit[1]
    val = fn()
    if keep is None or keep(val):
        _cache[key] = (now(), val)
    else:
        _cache.pop(key, None)
    return val


def clear_cache() -> None:
    _cache.clear()


def list_projects(owners=OWNERS, http: Callable | None = None, tok: str | None = None) -> dict:
    """Every project of every owner. Never raises on a missing scope."""
    out: dict = {"owners": [], "projects": [], "scope_missing": False}
    for kind, login in owners:
        try:
            d = gql(PROJECTS_Q % kind, {"login": login, "n": MAX_PROJECTS}, http, tok)
        except ScopeMissing as e:
            out["scope_missing"] = True
            out["owners"].append({"login": login, "kind": kind, "error": str(e)})
            continue
        nodes = ((d.get(kind) or {}).get("projectsV2") or {}).get("nodes") or []
        out["owners"].append({"login": login, "kind": kind, "projects": len(nodes)})
        out["projects"].extend(project_record(login, p) for p in nodes)
    return out


def project_record(login: str, p: dict) -> dict:
    """One ProjectV2 node → the record every surface shows: its fields, with a single select's options."""
    fields = [{"id": f.get("id"), "name": f.get("name"), "type": f.get("dataType"),
               "options": [o["name"] for o in f.get("options") or []]}
              for f in (p.get("fields") or {}).get("nodes") or [] if f]
    return {"owner": login, "id": p["id"], "number": p["number"], "title": p["title"],
            "url": p["url"], "closed": p.get("closed", False), "fields": fields}


def _fields(item: dict) -> dict:
    vals = {}
    for v in (item.get("fieldValues") or {}).get("nodes") or []:
        if not v or not v.get("field"):
            continue
        name = v["field"].get("name")
        vals[name] = next((v[k] for k in ("name", "text", "number", "title") if k in v), None)
    return vals


def project_items(project_id: str, http: Callable | None = None, tok: str | None = None,
                  max_items: int = MAX_ITEMS) -> list[dict]:
    items, after = [], None
    while len(items) < max_items:
        d = gql(ITEMS_Q, {"id": project_id, "n": PAGE, "after": after}, http, tok)
        page = ((d.get("node") or {}).get("items")) or {}
        for it in page.get("nodes") or []:
            items.append(normalize_item(it))
        if not (page.get("pageInfo") or {}).get("hasNextPage"):
            break
        after = page["pageInfo"]["endCursor"]
    return items[:max_items]


def normalize_item(it: dict) -> dict:
    c = it.get("content") or {}
    kind = {"Issue": "issue", "PullRequest": "pr", "DraftIssue": "draft"}.get(c.get("__typename"), "unknown")
    repo = (c.get("repository") or {}).get("nameWithOwner")
    return {
        "item_id": it["id"], "archived": it.get("isArchived", False), "kind": kind,
        "content_id": c.get("id"), "repo": repo, "number": c.get("number"),
        "title": redact(c.get("title", "")), "state": c.get("state"), "url": c.get("url"),
        "fields": _fields(it), "refs": sorted(set(REF_RE.findall(c.get("body") or ""))),
        "closes": [f"{n['repository']['nameWithOwner']}#{n['number']}"
                   for n in ((c.get("closingIssuesReferences") or {}).get("nodes") or [])],
        "commits": [{"sha": n["commit"]["oid"], "headline": redact(n["commit"]["messageHeadline"]),
                     "refs": sorted(set(REF_RE.findall(n["commit"]["messageHeadline"])))}
                    for n in ((c.get("commits") or {}).get("nodes") or [])],
    }


def node_key(kind: str, repo: str | None, number: Any) -> str:
    return f"{kind}:{repo}#{number}"


def linked_graph(projects: list[dict], items_by_project: dict[str, list[dict]]) -> dict:
    """Nodes: project, item, issue, pr, commit, repo, feature/req. Edges are typed (src, rel, dst)."""
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()

    def add(key, **attrs):
        nodes.setdefault(key, {"key": key, **attrs})
        return key

    for p in projects:
        pk = add(f"project:{p['owner']}/{p['number']}", kind="project", title=p["title"], url=p.get("url"))
        for it in items_by_project.get(p["id"], []):
            ik = add(f"item:{it['item_id']}", kind="item", fields=it["fields"], archived=it["archived"])
            edges.add((pk, "has_item", ik))
            if it["kind"] in ("issue", "pr"):
                ck = add(node_key(it["kind"], it["repo"], it["number"]), kind=it["kind"], title=it["title"],
                         state=it["state"], url=it["url"])
                edges.add((ik, "content", ck))
                rk = add(f"repo:{it['repo']}", kind="repo")
                edges.add((ck, "in_repo", rk))
                for ref in it["refs"]:
                    edges.add((ck, "references", add(f"ref:{ref}", kind="ref")))
                for cl in it["closes"]:
                    repo, num = cl.split("#")
                    edges.add((ck, "closes", add(node_key("issue", repo, int(num)), kind="issue")))
                for cm in it["commits"]:
                    sk = add(f"commit:{it['repo']}@{cm['sha']}", kind="commit", headline=cm["headline"])
                    edges.add((ck, "has_commit", sk))
                    for ref in cm["refs"]:
                        edges.add((sk, "references", add(f"ref:{ref}", kind="ref")))
    return {"nodes": sorted(nodes.values(), key=lambda n: n["key"]),
            "edges": [{"src": s, "rel": r, "dst": d} for s, r, d in sorted(edges)]}


def neighbours(graph: dict, key: str) -> dict:
    rel = [e for e in graph["edges"] if key in (e["src"], e["dst"])]
    keys = {key} | {e["src"] for e in rel} | {e["dst"] for e in rel}
    return {"nodes": [n for n in graph["nodes"] if n["key"] in keys], "edges": rel}


# --------------------------------------------------------------------------- #
# The read aggregator (epic #468 P1): what GET /api/gh-projects,
# GET /api/gh-projects/{id}/items and the MCP's gh_projects / gh_project_items
# serve. Every owner in one document, each with its projects or the reason it
# could not be read; one project's items paged and capped. Two budgets keep a
# read bounded: a sliding window of GraphQL calls shared by every read in this
# process (CALL_BUDGET per BUDGET_WINDOW_S), and a wall clock per answer
# (`budget_s`). Past either, the answer is `partial` and says why. GitHub's
# GraphQL endpoint answers no conditional request (no ETag, no 304), so the
# cache is the TTL above, and only an answer that reflects GitHub's view is
# kept: a read a transient failure cut short is asked again next time.
# --------------------------------------------------------------------------- #
SCHEMA = "gh-projects/v1"
ITEMS_SCHEMA = "gh-project-items/v1"
STATUSES = ("fresh", "partial", "scope_missing", "unavailable")
CALL_BUDGET = 60             # GraphQL calls per window, every read in this process together
BUDGET_WINDOW_S = 600
BUDGET_S, BUDGET_MAX_S = 15.0, 60.0   # wall clock per answer: under the MCP client's 20 s timeout
MIN_CALL_S = 0.5             # less clock than this is not worth opening a connection for
ITEMS_LIMIT = 100
ITEM_KINDS = ("issue", "pr", "draft")
STATUS_FIELD = "Status"
NO_STATUS = "No Status"      # GitHub's own label for an item with no Status value
PROJECT_ID_RX = re.compile(r"PVT_[A-Za-z0-9_-]{1,100}")
SCOPE_HINT = ("the token needs the read:project scope: set PROJECTS_TOKEN to a token that has it, or ask the "
              "maintainer to run `gh auth refresh -s read:project` for the console's own login")


class BudgetSpent(Exception):
    """The call window or the answer's wall clock ran out before this read was sent."""


class NotReadable(Exception):
    """GitHub answered, but not with the owner or project asked for (no access, or no such node)."""


class CallBudget:
    """A sliding window of GraphQL calls. Every read takes one call from it before it is sent; past
    `limit` calls in `window` seconds the read stops and its answer is partial, instead of spending
    the token's whole GraphQL quota (which the decision index and the jobs share)."""

    def __init__(self, limit: int = CALL_BUDGET, window: float = BUDGET_WINDOW_S,
                 now: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.now = int(limit), float(window), now
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _expire(self, t: float) -> None:
        while self._calls and t - self._calls[0] >= self.window:
            self._calls.popleft()

    def take(self) -> None:
        with self._lock:
            t = self.now()
            self._expire(t)
            if len(self._calls) >= self.limit:
                wait = int(self.window - (t - self._calls[0])) + 1
                raise BudgetSpent(f"the GraphQL call budget ({self.limit} per {int(self.window)}s) is spent; "
                                  f"it frees up in {wait}s")
            self._calls.append(t)

    def state(self) -> dict:
        with self._lock:
            self._expire(self.now())
            used = len(self._calls)
        return {"limit": self.limit, "window_s": int(self.window), "used": used, "left": max(0, self.limit - used)}


BUDGET = CallBudget()


class Clock:
    """The wall clock one answer may spend."""

    def __init__(self, seconds: float | None, now: Callable[[], float] = time.monotonic):
        try:
            s = float(seconds) if seconds else BUDGET_S
        except (TypeError, ValueError):
            s = BUDGET_S
        self.seconds, self.now = min(BUDGET_MAX_S, max(1.0, s)), now
        self.start = now()

    def left(self) -> float:
        return self.seconds - (self.now() - self.start)

    def spent(self) -> float:
        return round(self.now() - self.start, 2)


def resolve_token(identity: Callable[[], tuple[str | None, str | None]] | None = None) -> tuple[str | None, str | None]:
    """(source name, token): PROJECTS_TOKEN, else the console's own GitHub identity (`identity`, the
    console passes github_link.token_source: GH_TOKEN, GITHUB_TOKEN, then gh's login). The name is
    what an answer reports; the value never leaves this process."""
    if os.environ.get("PROJECTS_TOKEN"):
        return "PROJECTS_TOKEN", os.environ["PROJECTS_TOKEN"]
    if identity is None:
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            if os.environ.get(name):
                return name, os.environ[name]
        try:
            import github_link  # deferred: it loads the console core, which a token in the env never needs
        except ImportError:
            return None, None
        identity = github_link.token_source
    src, tok = identity()
    return (src, tok) if tok else (None, None)


def _token_pair(token: Any) -> tuple[str | None, str | None]:
    if token is None:
        return resolve_token()
    pair = token() if callable(token) else token
    src, tok = pair if isinstance(pair, tuple) else ("token", pair)
    return (src, tok) if tok else (None, None)


def _metered(http: Callable | None, calls: CallBudget, clock: Clock) -> Callable:
    """`http` with both budgets in front of it: a call is sent only while the window and the clock allow."""
    def call(query: str, variables: dict, tok: str) -> dict:
        left = clock.left()
        if left < MIN_CALL_S:
            raise BudgetSpent(f"the {clock.seconds:g}s time budget ran out before this read was sent")
        calls.take()
        if http is None:  # pragma: no cover - network
            return _http(query, variables, tok, timeout=min(20.0, left))
        return http(query, variables, tok)
    return call


def _why(exc: BaseException) -> tuple[str, bool]:
    """(what went wrong, in one redacted line; whether every later read would fail the same way)."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return "GitHub refused the token (401)", True
        if exc.code in (403, 429):
            return f"GitHub refused the query or its rate limit is spent ({exc.code})", True
        return f"GitHub answered {exc.code}", exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return redact(f"GitHub could not be reached: {exc.reason}")[:300], True
    if isinstance(exc, TimeoutError):
        return "GitHub did not answer in time", True
    if isinstance(exc, ValueError):
        return "GitHub's answer was not JSON", False
    return redact(str(exc))[:300] or type(exc).__name__, False


TRANSIENT = (OSError, ValueError, RuntimeError)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact_doc(obj: Any) -> Any:
    """Every string in a document through `redact`: a title, a field value or a commit headline that
    carries something token-shaped never reaches a page or an agent."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_doc(v) for v in obj]
    if isinstance(obj, dict):
        return {k: redact_doc(v) for k, v in obj.items()}
    return obj


def _owner_projects(kind: str, login: str, http: Callable, tok: str | None) -> list[dict]:
    partial: list[str] = []
    d = gql(PROJECTS_Q % kind, {"login": login, "n": MAX_PROJECTS}, http, tok, partial=partial)
    node = d.get(kind)
    if node is None:
        raise NotReadable(partial[0] if partial else f"the {kind} {login} is not readable with this token")
    return [project_record(login, p) for p in (node.get("projectsV2") or {}).get("nodes") or [] if p]


def _read_projects(owners, http: Callable, tok: str | None, now: float) -> dict:
    rows: list[dict] = []
    projects: list[dict] = []
    stop: str | None = None
    transient = False
    for kind, login in owners:
        row: dict = {"login": login, "kind": kind}
        if stop:
            row.update(status="skipped", error=stop)
            rows.append(row)
            continue
        try:
            got = _owner_projects(kind, login, http, tok)
        except ScopeMissing as e:
            row.update(status="scope_missing", error=str(e))
        except BudgetSpent as e:
            stop, transient = str(e), True
            row.update(status="skipped", error=stop)
        except NotReadable as e:
            row.update(status="error", error=str(e))
        except TRANSIENT as e:
            why, every = _why(e)
            transient = True
            row.update(status="error", error=why)
            if every:
                stop = f"not asked: {why}"
        else:
            row.update(status="ok", projects=len(got))
            projects.extend(got)
        rows.append(row)
    return {"owners": rows, "projects": projects, "generated_at": now, "transient": transient}


def _status(rows: list[dict]) -> str:
    ok = sum(1 for r in rows if r["status"] == "ok")
    if ok == len(rows):
        return "fresh"
    if ok:
        return "partial"
    return "scope_missing" if all(r["status"] == "scope_missing" for r in rows) else "unavailable"


def projects_view(*, owner: str = "", include_closed: bool = True, refresh: bool = False,
                  budget_s: float | None = None, http: Callable | None = None, token: Any = None,
                  calls: CallBudget | None = None, owners=OWNERS, now: Callable[[], float] = time.time) -> dict:
    """Every project of every owner in `owners`, in one document (`gh-projects/v1`).

    Each owner row says `ok` (with its project count), `scope_missing`, `error` or `skipped` (a budget or
    a failure every later read would share stopped the read first), with the reason. `status` is fresh
    (every owner read) · partial · scope_missing (no owner read, for want of the scope or a token) ·
    unavailable. `owner` narrows the answer, `include_closed=False` drops closed projects; the read
    itself always covers every owner, so the cache serves each narrowing. `token` is a (source, value)
    pair or a function returning one; the default is `resolve_token()`."""
    logins = {login.lower(): login for _, login in owners}
    if owner and owner.lower() not in logins:
        raise ValueError(f"owner must be one of {', '.join(logins.values())}")
    src, tok = _token_pair(token)
    calls = calls or BUDGET
    clock = Clock(budget_s)
    key = f"projects:{src}"
    live = {"read": False}

    def build() -> dict:
        live["read"] = True
        return _read_projects(owners, _metered(http, calls, clock), tok, now())

    if refresh:
        _cache.pop(key, None)
    raw = cached(key, build, now=now, keep=lambda d: bool(tok) and not d["transient"])
    rows = [dict(r) for r in raw["owners"] if not owner or r["login"].lower() == owner.lower()]
    projects = [p for p in raw["projects"] if (not owner or p["owner"].lower() == owner.lower())
                and (include_closed or not p.get("closed"))]
    status = _status(rows)
    scope = any(r["status"] == "scope_missing" for r in rows)
    hints = []
    if not tok:
        hints.append("no GitHub token: set PROJECTS_TOKEN, or connect the console to GitHub (the GitHub page)")
    elif scope:
        hints.append(SCOPE_HINT)
    if status in ("partial", "unavailable") and not scope:
        hints.append("an owner could not be read; its row says why, and the next call asks again")
    doc = {
        "schema": SCHEMA, "generated_at": _iso(raw["generated_at"]), "status": status, "complete": status == "fresh",
        "source": "none" if not tok else "live" if live["read"] else "cache",
        "age_s": max(0, int(now() - raw["generated_at"])),
        "ttl_s": TTL_SECONDS, "token_source": src, "scope_missing": scope, "read_only": True,
        "owners": rows, "projects": projects,
        "counts": {"owners": len(rows), "read": sum(1 for r in rows if r["status"] == "ok"),
                   "projects": len(projects), "open": sum(1 for p in projects if not p.get("closed"))},
        "budget": {**calls.state(), "budget_s": clock.seconds, "elapsed_s": clock.spent() if live["read"] else 0.0},
        "hint": " · ".join(hints) or None,
    }
    return redact_doc(doc)


def _read_items(project_id: str, http: Callable, tok: str | None, now: float, max_items: int) -> dict:
    items: list[dict] = []
    after: str | None = None
    more, errors, transient = False, [], False
    while len(items) < max_items:
        partial: list[str] = []
        try:
            d = gql(ITEMS_Q, {"id": project_id, "n": PAGE, "after": after}, http, tok, partial=partial)
        except BudgetSpent as e:  # ScopeMissing is not caught here: the view answers it as scope_missing
            errors.append(str(e))
            transient = more = True
            break
        except TRANSIENT as e:
            errors.append(_why(e)[0])
            transient = more = True
            break
        node = d.get("node")
        if not isinstance(node, dict) or "items" not in node:
            if not items:
                raise NotReadable(partial[0] if partial else f"no project {project_id} is readable with this token")
            break
        page = node.get("items") or {}
        items.extend(normalize_item(it) for it in page.get("nodes") or [] if it)
        info = page.get("pageInfo") or {}
        more = bool(info.get("hasNextPage"))
        if not more:
            break
        after = info.get("endCursor")
    return {"items": items[:max_items], "more": more or len(items) > max_items, "errors": errors,
            "generated_at": now, "transient": transient}


def _status_of(item: dict) -> str:
    v = (item.get("fields") or {}).get(STATUS_FIELD)
    return str(v) if v not in (None, "") else NO_STATUS


def _matches(item: dict, status: str, kind: str, q: str) -> bool:
    if status and _status_of(item).lower() != status.lower():
        return False
    if kind and item.get("kind") != kind:
        return False
    if q:
        hay = " ".join(str(item.get(k) or "") for k in ("title", "repo", "number", "state")).lower()
        return q.lower() in hay
    return True


def items_view(project_id: str, *, limit: int = ITEMS_LIMIT, offset: int = 0, status: str = "", kind: str = "",
               q: str = "", refresh: bool = False, budget_s: float | None = None, http: Callable | None = None,
               token: Any = None, calls: CallBudget | None = None, max_items: int = MAX_ITEMS,
               now: Callable[[], float] = time.time) -> dict:
    """One project's items (`gh-project-items/v1`), paged: the read stops at `max_items` (MAX_ITEMS)
    and says so (`capped`); `limit`/`offset` page what was read, `status` (a Status value, or
    "No Status"), `kind` (issue · pr · draft) and `q` (title, repo, number) filter it, and `counts`
    cover every item read whatever the filter. Raises ValueError on a bad argument and NotReadable
    when GitHub has no such project for this token."""
    if not PROJECT_ID_RX.fullmatch(project_id or ""):
        raise ValueError("project_id must be a Projects (v2) node id (PVT_…)")
    if kind and kind not in ITEM_KINDS:
        raise ValueError(f"kind must be one of {', '.join(ITEM_KINDS)}")
    limit = max(0, min(int(limit), max_items))
    offset = max(0, min(int(offset), max_items))
    src, tok = _token_pair(token)
    calls = calls or BUDGET
    clock = Clock(budget_s)
    key = f"items:{project_id}:{src}"
    live = {"read": False}
    scope_error: str | None = None

    def build() -> dict:
        live["read"] = True
        return _read_items(project_id, _metered(http, calls, clock), tok, now(), max_items)

    if refresh:
        _cache.pop(key, None)
    try:
        raw = cached(key, build, now=now, keep=lambda d: bool(tok) and not d["transient"])
    except ScopeMissing as e:
        scope_error = str(e)
        raw = {"items": [], "more": False, "errors": [scope_error], "generated_at": now(), "transient": False}
    except TRANSIENT as e:  # a failure on the first page, before any item was read
        raw = {"items": [], "more": False, "errors": [_why(e)[0]], "generated_at": now(), "transient": True}
    every = raw["items"]
    rows = [i for i in every if _matches(i, status, kind, q)]
    page = rows[offset: offset + limit]
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for it in every:
        by_status[_status_of(it)] = by_status.get(_status_of(it), 0) + 1
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    if scope_error:
        state = "scope_missing"
    elif raw["errors"]:
        state = "partial" if every else "unavailable"
    else:
        state = "fresh"
    hints = []
    if scope_error:
        hints.append(SCOPE_HINT if tok else "no GitHub token: set PROJECTS_TOKEN, or connect the console to GitHub")
    if raw["more"] and not raw["errors"]:
        hints.append(f"the project holds more than {max_items} items: only the first {max_items} are read")
    elif raw["errors"] and every:
        hints.append("the read stopped early; the next call asks again")
    nxt = offset + len(page)
    doc = {
        "schema": ITEMS_SCHEMA, "project_id": project_id, "generated_at": _iso(raw["generated_at"]),
        "status": state, "complete": state == "fresh" and not raw["more"],
        "source": "none" if not tok else "live" if live["read"] else "cache",
        "age_s": max(0, int(now() - raw["generated_at"])),
        "ttl_s": TTL_SECONDS, "token_source": src, "read_only": True,
        "total": len(every), "matched": len(rows), "limit": limit, "offset": offset,
        "next_offset": nxt if nxt < len(rows) else None, "capped": bool(raw["more"]) and not raw["errors"],
        "max_items": max_items, "statuses": list(by_status), "counts": {"by_status": by_status, "by_kind": by_kind},
        "items": page, "errors": list(raw["errors"]),
        "budget": {**calls.state(), "budget_s": clock.seconds, "elapsed_s": clock.spent() if live["read"] else 0.0},
        "hint": " · ".join(hints) or None,
    }
    return redact_doc(doc)

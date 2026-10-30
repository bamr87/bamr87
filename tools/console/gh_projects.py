#!/usr/bin/env python3
"""gh_projects — read GitHub Projects (v2) across every fleet owner and link
project items, issues, pull requests, commits and repos into one graph.

Read-only. GraphQL over stdlib HTTP (`_http` is swappable, so tests run on
recorded fixtures with no network). Results are cached in memory with a TTL.
A token without `read:project` degrades to an honest `scope_missing` result
instead of an error. Token values are never returned, logged or cached.

Docs: docs/PROJECTS-FRAMEWORK.md § Console surface; amendment
docs/amendments/proposed/projects-write-back.md.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
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


def _http(query: str, variables: dict, tok: str) -> dict:  # pragma: no cover - network
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


class ScopeMissing(Exception):
    pass


def gql(query: str, variables: dict | None = None, http: Callable | None = None, tok: str | None = None) -> dict:
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


def cached(key: str, fn: Callable[[], Any], ttl: int = TTL_SECONDS, now: Callable[[], float] = time.time) -> Any:
    hit = _cache.get(key)
    if hit and now() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now(), val)
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
        for p in nodes:
            fields = [{"id": f.get("id"), "name": f.get("name"), "type": f.get("dataType"),
                       "options": [o["name"] for o in f.get("options") or []]}
                      for f in (p.get("fields") or {}).get("nodes") or [] if f]
            out["projects"].append({"owner": login, "id": p["id"], "number": p["number"], "title": p["title"],
                                    "url": p["url"], "closed": p.get("closed", False), "fields": fields})
    return out


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

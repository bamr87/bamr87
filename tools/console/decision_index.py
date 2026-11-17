#!/usr/bin/env python3
"""decision_index — the fleet's decision queue, answered in one call.

"What does Amr need to decide?" used to mean sweeping every repo one at a
time. This reads the whole fleet with a handful of GitHub GraphQL queries — one
search for every open pull request, one for the gate-labelled issues, one for
the repo inventory, then the merge state, checks and changed paths of those
pull requests in parallel batches — and keeps the answer in an index on disk
(`.fleet/decisions/index.json`, gitignored), so the console's `/api/decisions`,
`tools/dash decisions` and the MCP's `decision_queue` all serve one cache.

The queue has four kinds, listed in this order:
  needs_amr       an issue or PR carrying a gate label (`needs-amr`, constitution § 12.4)
  ratification    an open PR that changes a constitution, an amendment or an ADR (§ 8, § 12.3)
  dependabot      a Dependabot PR whose checks fail, that conflicts, or that is a major bump
  ready_to_merge  a PR that is not a draft, has no conflicts and whose checks and reviews pass

Design for Failure:
  * a hard wall clock (`budget_s`): the answer returns when it runs out, with
    what was read so far and the previous index for the rest, each part dated,
    and the next call resumes with the parts that are still old;
  * an index older than `ttl_s` is refreshed; when GitHub cannot answer (no
    token, a refused token, the rate limit, a 502, no network) the old index is
    served and says so — `status` is fresh · partial · stale · expired ·
    unavailable, never a guess;
  * a 502/504 on a search page halves the page and asks again; a failed
    enrichment batch is split in two;
  * an unreadable or foreign index file is set aside and rebuilt, never trusted;
  * every failure is in the answer (`errors`: stage, kind, message), redacted.

Read-only: GraphQL queries, never a mutation. Token values are never returned,
logged or written. Stdlib + PyYAML; `http` is swappable, so the tests run on
recorded fixtures with no network.

Docs: docs/DECISION-INDEX.md; sub-PRD docs/prd/DECISION-INDEX.md.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import queue as queue_mod
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from gh_projects import redact  # noqa: E402
if str(HERE.parent) not in sys.path:  # tools/fleetcore, the core every surface shares
    sys.path.insert(0, str(HERE.parent))
from fleetcore import yamlio  # noqa: E402

API = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/") + "/graphql"
USER_AGENT = "bamr87-harness-console"
SCHEMA = "decision-queue/v1"
INDEX_SCHEMA = "decision-index/v1"
KINDS = ("needs_amr", "ratification", "dependabot", "ready_to_merge")
KIND_TITLES = {"needs_amr": "Needs Amr", "ratification": "Awaiting ratification",
               "dependabot": "Dependabot: failing or major", "ready_to_merge": "Ready to merge"}
REFRESH_MODES = ("auto", "never", "force")
STATUSES = ("fresh", "partial", "stale", "expired", "unavailable")
TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN")
BUDGET_MIN_S, BUDGET_MAX_S = 1.0, 120.0
HTTP_TIMEOUT_S = 12.0        # GitHub ends a GraphQL query at 10 s; past that the answer is a 502
MIN_CALL_S = 0.25            # less budget than this is not worth opening a connection for
MIN_PAGE = 10
UNKNOWN_RETRY_DELAY_S = 0.6  # GitHub computes `mergeable` after the first ask; one second ask reads it
TITLE_CHARS = 140
MAX_ERRORS = 20
MAX_LIMIT = 500
# A failure of the token, the quota, the network or the clock fails every query alike: nothing more is sent.
GLOBAL_FAILURES = ("auth", "forbidden", "rate_limited", "network", "budget")

# Everything tunable lives in _data/fleet.yml `decisions:`; these are the values a missing key falls back to
# (test_decision_index.py holds the two equal).
DEFAULTS: dict[str, Any] = {
    "ttl_s": 600,
    "max_stale_s": 86400,
    "budget_s": 10,
    "refresh_budget_s": 60,
    "scan_page": 100,
    "enrich_batch": 10,
    "concurrency": 8,
    "max_prs": 1000,
    "min_rate_remaining": 200,
    "labels": {"gate": ["needs-amr"], "hold": ["agent:hold", "blocked"]},
    "dependabot": {"authors": ["dependabot", "dependabot[bot]"]},
    "ratification": {
        "paths": [
            r"(^|/)docs/constitution\.md$",
            r"(^|/)CONSTITUTION\.md$",
            r"(^|/)docs/amendments/(proposed/[^/]+|(?!0000-)\d{4}-[^/]+)\.md$",
            r"(^|/)docs/adr/(?!0000-)\d{4}-[^/]+\.md$",
        ],
        "title": r"\b(amendment|constitution|ratif\w*)\b",
        "skip_branches": ["chore/jev-ratify"],
    },
}
LIMITS = {"ttl_s": (30, 86400), "max_stale_s": (60, 30 * 86400), "budget_s": (BUDGET_MIN_S, BUDGET_MAX_S),
          "refresh_budget_s": (BUDGET_MIN_S, BUDGET_MAX_S), "scan_page": (MIN_PAGE, 100), "enrich_batch": (1, 50),
          "concurrency": (1, 16), "max_prs": (10, 1000), "min_rate_remaining": (0, 5000)}

_ITEM = ("id number title url createdAt updatedAt author{ login __typename } "
         "repository{ nameWithOwner isPrivate } labels(first:30){ nodes{ name } }")
SCAN_Q = """query($q:String!,$n:Int!,$after:String){ search(query:$q,type:ISSUE,first:$n,after:$after){
 issueCount pageInfo{ hasNextPage endCursor } nodes{ __typename
  ... on PullRequest{ %s isDraft baseRefName headRefName }
  ... on Issue{ %s } } }
 rateLimit{ cost remaining resetAt } }""" % (_ITEM, _ITEM)
REPOS_Q = """query($q:String!,$n:Int!,$after:String){ search(query:$q,type:REPOSITORY,first:$n,after:$after){
 repositoryCount pageInfo{ hasNextPage endCursor } nodes{ ... on Repository{ nameWithOwner isPrivate isFork
  issues(states:OPEN){ totalCount } pullRequests(states:OPEN){ totalCount } } } }
 rateLimit{ cost remaining resetAt } }"""
# The slow fields, asked only for the pull requests the scan found and in small parallel batches: one page of
# 100 pull requests carrying them runs past GitHub's own 10 s limit and comes back as a 502.
ENRICH_Q = """query($ids:[ID!]!){ nodes(ids:$ids){ ... on PullRequest{ id mergeable mergeStateStatus reviewDecision
  autoMergeRequest{ enabledAt } files(first:100){ totalCount nodes{ path } }
  commits(last:1){ nodes{ commit{ statusCheckRollup{ state } } } } } }
 rateLimit{ cost remaining resetAt } }"""

HINTS = {
    "no_token": "give the console a GitHub token: the GitHub page, GH_TOKEN, or `gh auth login`",
    "auth": "GitHub refused the token: reconnect on the console's GitHub page, or `gh auth login`",
    "rate_limited": "GitHub's rate limit is spent; the index is served as it is until the limit resets",
    "rate_floor": "the token's remaining quota is under decisions.min_rate_remaining, so the slow reads were skipped",
    "budget": "the time budget ran out; the next call resumes with what is still old, and "
              "`tools/dash decisions refresh` finishes the read under a longer one",
    "busy": "another refresh is running; ask again in a few seconds",
    "network": "GitHub is not reachable from here; the index is served as it is",
    "upstream_timeout": "GitHub timed out on its side; the next call tries again with smaller pages",
}


class Upstream(Exception):
    """GitHub did not answer a query; `kind` is what a caller can act on."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class Budget:
    """The wall clock one answer may spend."""

    def __init__(self, seconds: float):
        self.seconds = float(seconds)
        self._t0 = time.monotonic()

    def spent(self) -> float:
        return time.monotonic() - self._t0

    def left(self) -> float:
        return self.seconds - self.spent()

    def expired(self) -> bool:
        return self.left() <= 0


# --------------------------------------------------------------------------- #
# Configuration: _data/fleet.yml `decisions:` over DEFAULTS, plus who the fleet is
# --------------------------------------------------------------------------- #
_CFG_CACHE: dict[str, tuple[tuple, dict]] = {}


def _merged(base: dict, over: Any) -> dict:
    out = copy.deepcopy(base)
    for key, value in (over or {}).items() if isinstance(over, dict) else ():
        out[key] = _merged(base[key], value) if isinstance(base.get(key), dict) else value
    return out


def _load_yaml(path: Path) -> Any:
    try:
        return yamlio.load(path)
    except (OSError, yaml.YAMLError):
        return None


def _nwo(url: Any) -> str | None:
    m = re.match(r"^https?://github\.com/([^/]+/[^/#?]+?)(?:\.git)?/?$", str(url or ""))
    return m.group(1).lower() if m else None


def load_config(root: Path = ROOT) -> dict:
    """The knobs, the owners to search (`hub.owners`) and the registry's repos. A missing or broken
    fleet.yml leaves the defaults and no owners, which the answer reports instead of guessing one."""
    fleet_path, registry_path = root / "_data" / "fleet.yml", root / "_data" / "projects.yml"
    stamp = tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in (fleet_path, registry_path))
    hit = _CFG_CACHE.get(str(root))
    if hit and hit[0] == stamp:
        return hit[1]
    fleet = _load_yaml(fleet_path)
    fleet = fleet if isinstance(fleet, dict) else {}
    cfg = _merged(DEFAULTS, fleet.get("decisions"))
    for key, (lo, hi) in LIMITS.items():
        try:
            cfg[key] = min(hi, max(lo, type(DEFAULTS[key])(cfg[key])))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    for block, key in (("labels", "gate"), ("labels", "hold"), ("dependabot", "authors"),
                       ("ratification", "paths"), ("ratification", "skip_branches")):
        value = cfg[block].get(key)
        cfg[block][key] = [str(v) for v in value] if isinstance(value, list) else list(DEFAULTS[block][key])
    hub = fleet.get("hub") if isinstance(fleet.get("hub"), dict) else {}
    named = hub.get("owners") or ([str(hub["repo"]).split("/")[0]] if hub.get("repo") else [])
    owners = [str(o) for o in named if re.fullmatch(r"[A-Za-z0-9-]{1,39}", str(o))]
    registry = {n for n in (_nwo(p.get("repo_url")) for p in _load_yaml(registry_path) or [] if isinstance(p, dict)) if n}
    registry |= {str(hub[k]).lower() for k in ("repo", "shared") if hub.get(k)}
    cfg.update(owners=owners, registry=sorted(registry))
    _CFG_CACHE[str(root)] = (stamp, cfg)
    return cfg


def _rx(patterns: Any) -> list[re.Pattern]:
    out = []
    for p in patterns if isinstance(patterns, list) else [patterns]:
        try:
            out.append(re.compile(str(p), re.I))
        except re.error:
            continue  # a pattern that does not compile matches nothing; `status` lists the ones in force
    return out


# --------------------------------------------------------------------------- #
# The token and the one HTTP function (swappable, so tests never reach the network)
# --------------------------------------------------------------------------- #
def resolve_token() -> str | None:
    """GH_TOKEN, then GITHUB_TOKEN, then gh's own login — the console's order (github_link.token_source)."""
    for name in TOKEN_ENV:
        if os.environ.get(name):
            return os.environ[name]
    import github_link  # deferred: it loads the console core, which a cache-only read never needs
    return github_link.token_source()[1]


def _http(query: str, variables: dict, tok: str, timeout: float) -> tuple[int, dict, Any]:  # pragma: no cover - network
    """(status, headers, parsed body). Never raises on an HTTP status; a dead connection raises."""
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = {"message": raw.decode("utf-8", "replace")[:300]}
        return exc.code, dict(exc.headers or {}), body


def gql(query: str, variables: dict, *, http: Callable, tok: str, budget: Budget) -> tuple[dict, list[str]]:
    """One query inside what is left of the budget → (data, the messages of any partial errors)."""
    left = budget.left()
    if left < MIN_CALL_S:
        raise Upstream("budget", "the time budget ran out before this query was sent")
    try:
        status, headers, body = http(query, variables, tok, min(HTTP_TIMEOUT_S, left))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if budget.left() < MIN_CALL_S:  # the socket was given what was left of the budget, and it ran out
            raise Upstream("budget", "the time budget ran out while GitHub was still answering") from None
        raise Upstream("network", redact(f"GitHub is not reachable: {getattr(exc, 'reason', exc)}")) from None
    except ValueError as exc:
        raise Upstream("bad_response", redact(f"GitHub's answer was not JSON: {exc}")) from None
    head = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    message = redact(str(body.get("message") or "")) if isinstance(body, dict) else ""
    if status == 401:
        raise Upstream("auth", "GitHub refused the token (401)")
    if status in (403, 429):
        if head.get("x-ratelimit-remaining") == "0" or head.get("retry-after") or "rate limit" in message.lower():
            reset = _iso(float(head["x-ratelimit-reset"])) if head.get("x-ratelimit-reset", "").isdigit() else None
            raise Upstream("rate_limited", f"GitHub's rate limit is spent ({status})" + (f"; it resets at {reset}" if reset else ""))
        raise Upstream("forbidden", f"GitHub refused the query ({status}): {message[:200] or 'no reason given'}")
    if status in (502, 503, 504):
        raise Upstream("upstream_timeout", f"GitHub answered {status}: the query ran past GitHub's own time limit")
    if status >= 400 or not isinstance(body, dict):
        raise Upstream("http", f"GitHub answered {status}: {message[:200] or 'no body'}")
    errors = [e for e in body.get("errors") or [] if isinstance(e, dict)]
    data = body.get("data")
    if any(e.get("type") == "RATE_LIMITED" for e in errors):
        raise Upstream("rate_limited", "GitHub's rate limit is spent")
    texts = [redact(str(e.get("message") or e.get("type") or "error"))[:200] for e in errors]
    if errors and not data:
        kind = "upstream_timeout" if re.search(r"timed? ?out|something went wrong", " ".join(texts), re.I) else "graphql"
        raise Upstream(kind, "; ".join(texts)[:300])
    return (data if isinstance(data, dict) else {}), texts


def search_all(ask: Callable[[dict], dict], q: str, count_field: str, *, page: int, cap: int) -> dict:
    """Every node of one search, page by page → {nodes, total, complete, error}. A 502/504 halves the page
    and asks again; any other failure stops and keeps the pages already read."""
    nodes: list[dict] = []
    after, total, size = None, None, page
    while True:
        try:
            data = ask({"q": q, "n": size, "after": after})
        except Upstream as exc:
            if exc.kind == "upstream_timeout" and size > MIN_PAGE:
                size = max(MIN_PAGE, size // 2)
                continue
            return {"nodes": nodes, "total": total, "complete": False, "error": {"kind": exc.kind, "message": str(exc)}}
        found = data.get("search")
        if not isinstance(found, dict) or not isinstance(found.get(count_field), int):
            # An answer with no search in it is not "nothing is open": calling it complete would empty the index.
            return {"nodes": nodes, "total": total, "complete": False,
                    "error": {"kind": "bad_response", "message": "GitHub's answer carried no search result"}}
        total = found[count_field]
        nodes.extend(n for n in found.get("nodes") or [] if isinstance(n, dict) and n)
        info = found.get("pageInfo") or {}
        if not info.get("hasNextPage") or not info.get("endCursor"):
            if isinstance(total, int) and total > len(nodes):  # GitHub's search stops at 1000 results
                return {"nodes": nodes, "total": total, "complete": False,
                        "error": {"kind": "truncated", "message": f"the search returned {len(nodes)} of {total}"}}
            return {"nodes": nodes, "total": total, "complete": True, "error": None}
        if len(nodes) >= cap:
            return {"nodes": nodes, "total": total, "complete": False,
                    "error": {"kind": "cap", "message": f"stopped at {len(nodes)} of {total} (decisions.max_prs)"}}
        after = info["endCursor"]


# --------------------------------------------------------------------------- #
# Records: what the index keeps of a pull request, an issue and a repo
# --------------------------------------------------------------------------- #
def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(text: Any) -> float | None:
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def item_record(node: dict, now: float) -> dict | None:
    repo = (node.get("repository") or {}).get("nameWithOwner")
    if not (node.get("id") and repo and node.get("number")):
        return None
    author = node.get("author") or {}
    rec = {
        "id": node["id"], "type": "pr" if node.get("__typename") == "PullRequest" else "issue",
        "repo": repo, "number": node["number"], "title": redact(str(node.get("title") or ""))[:TITLE_CHARS],
        "url": node.get("url"), "author": author.get("login"), "bot": author.get("__typename") == "Bot",
        "private": bool((node.get("repository") or {}).get("isPrivate")),
        "labels": [n["name"] for n in (node.get("labels") or {}).get("nodes") or [] if n and n.get("name")],
        "created_at": node.get("createdAt"), "updated_at": node.get("updatedAt"), "seen_at": now,
    }
    if rec["type"] == "pr":
        rec.update(draft=bool(node.get("isDraft")), base=node.get("baseRefName"), head=node.get("headRefName"))
    return rec


def enrichment(node: dict, updated_at: str | None, paths_rx: list[re.Pattern], now: float) -> dict:
    files = node.get("files") or {}
    paths = [f["path"] for f in files.get("nodes") or [] if f and f.get("path")]
    commit = ((node.get("commits") or {}).get("nodes") or [{}])[0] or {}
    rollup = (commit.get("commit") or {}).get("statusCheckRollup") or {}
    return {
        "mergeable": node.get("mergeable"), "merge_state": node.get("mergeStateStatus"),
        "review": node.get("reviewDecision"), "checks": rollup.get("state"),
        "auto_merge": bool(node.get("autoMergeRequest")), "files": files.get("totalCount"), "files_read": len(paths),
        "governs": [p for p in paths if any(rx.search(p) for rx in paths_rx)][:10],
        "for_updated_at": updated_at, "at": now,
    }


def merge_scan(old: dict, result: dict | None, now: float) -> dict:
    """A stage's records after a scan. A complete scan replaces the stage (what it did not return is closed);
    an incomplete one refreshes what it read and keeps the rest, each record with its own `seen_at`."""
    if result is None:
        return dict(old)
    new: dict[str, dict] = {}
    for node in result.get("nodes") or []:
        rec = item_record(node, now)
        if rec:
            if (old.get(rec["id"]) or {}).get("enrich"):
                rec["enrich"] = old[rec["id"]]["enrich"]
            new[rec["id"]] = rec
    if not result.get("complete"):
        for key, rec in old.items():
            new.setdefault(key, rec)
    return new


def enrich_fresh(rec: dict, ttl: float, now: float) -> bool:
    e = rec.get("enrich")
    return bool(e) and now - e.get("at", 0) <= ttl and e.get("for_updated_at") == rec.get("updated_at")


# --------------------------------------------------------------------------- #
# The index file
# --------------------------------------------------------------------------- #
def index_path(root: Path = ROOT) -> Path:
    p = os.environ.get("DASH_DECISIONS_INDEX")
    return Path(p).expanduser() if p else root / ".fleet" / "decisions" / "index.json"


def empty_index() -> dict:
    return {"schema": INDEX_SCHEMA, "stages": {}, "prs": {}, "issues": {}, "repos": {}, "last": None}


def load_index(path: Path) -> tuple[dict, str | None]:
    """(index, why it was set aside). A missing file is an empty index; so is one that cannot be trusted."""
    if not path.exists():
        return empty_index(), None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return empty_index(), f"the index at {path} could not be read ({type(exc).__name__}); it is being rebuilt"
    ok = (isinstance(doc, dict) and doc.get("schema") == INDEX_SCHEMA
          and all(isinstance(doc.get(k), dict) for k in ("stages", "prs", "issues", "repos")))
    if not ok:
        return empty_index(), f"the index at {path} is not a {INDEX_SCHEMA} document; it is being rebuilt"
    return doc, None


def save_index(path: Path, index: dict) -> str | None:
    """Atomic, owner-only (it can hold a private repo's titles). Returns why it could not be written."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(index, fh, separators=(",", ":"))
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError as exc:
        return f"the index could not be saved to {path}: {exc.strerror or exc}"
    return None


# --------------------------------------------------------------------------- #
# The refresh: a pool of daemon workers under one wall clock
# --------------------------------------------------------------------------- #
class Pool:
    """Daemon workers over a queue of tasks. `wait()` returns when every task is done or the budget is
    gone, whichever comes first; a task may add tasks (a failed batch splits in two)."""

    def __init__(self, workers: int, budget: Budget):
        self.workers, self.budget = max(1, int(workers)), budget
        self._q: queue_mod.SimpleQueue = queue_mod.SimpleQueue()
        self._lock = threading.Lock()
        self._open = 0
        self._threads = 0
        self._idle = threading.Event()
        self._idle.set()
        self.crashed: list[str] = []

    def add(self, task: Callable[[], None]) -> None:
        with self._lock:
            self._open += 1
            self._idle.clear()
            spawn = self._threads < self.workers
            self._threads += spawn
        self._q.put(task)
        if spawn:
            threading.Thread(target=self._work, daemon=True, name="decision-index").start()

    def _work(self) -> None:
        while not self.budget.expired():
            try:
                task = self._q.get(timeout=0.05)
            except queue_mod.Empty:
                with self._lock:
                    if self._open == 0:  # checked and left under one lock, so a later add() starts a worker
                        self._threads -= 1
                        return
                continue
            try:
                task()
            except Exception as exc:  # a task's own bug is reported in the answer, never left as a hung wait
                self.crashed.append(f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._open -= 1
                    if self._open == 0:
                        self._idle.set()
        with self._lock:
            self._threads -= 1

    def wait(self) -> bool:
        return self._idle.wait(max(0.0, self.budget.left()))

    def unfinished(self) -> int:
        with self._lock:
            return self._open


class Collector:
    """What one refresh read: written by the workers, read once by the caller, and closed at the deadline
    so an answer that arrives late cannot change a result that has already been returned."""

    def __init__(self):
        self._lock = threading.Lock()
        self._closed = False
        self.scans: dict[str, dict] = {}
        self.enriched: dict[str, dict] = {}
        self.errors: list[dict] = []
        self.rate: dict | None = None
        self.requests = 0
        self.cut = 0  # reads the budget ended: one line in the answer, however many there were
        self.halted = False

    def scan(self, stage: str, result: dict) -> None:
        with self._lock:
            if not self._closed:
                self.scans[stage] = result

    def enrich(self, rows: dict[str, dict]) -> None:
        with self._lock:
            if not self._closed:
                self.enriched.update(rows)

    def error(self, stage: str, kind: str, message: str, **extra: Any) -> None:
        with self._lock:
            if self._closed:
                return
            self.halted = self.halted or kind in GLOBAL_FAILURES
            if kind == "budget":
                self.cut += 1
            elif len(self.errors) < MAX_ERRORS:
                self.errors.append({"stage": stage, "kind": kind, "message": redact(message)[:300], **extra})

    def note(self, stage: str, rate: Any, partial: list[str]) -> None:
        with self._lock:
            if self._closed:
                return
            self.requests += 1
            if isinstance(rate, dict) and isinstance(rate.get("remaining"), int):
                if self.rate is None or rate["remaining"] < self.rate["remaining"]:
                    self.rate = {"remaining": rate["remaining"], "reset_at": rate.get("resetAt")}
        for text in partial[:3]:
            self.error(stage, "graphql_partial", text)

    def remaining(self) -> int | None:
        with self._lock:
            return self.rate["remaining"] if self.rate else None

    def close(self) -> None:
        with self._lock:
            self._closed = True


def searches_of(cfg: dict) -> dict[str, str]:
    """The three search strings. They are stored with the index: one built from other owners or other
    gate labels answers a different question, and is rebuilt instead of served."""
    owners = " ".join(f"user:{o}" for o in cfg["owners"])
    gate = ",".join('"%s"' % str(label).replace('"', "") for label in cfg["labels"]["gate"])
    return {"prs": f"{owners} is:pr is:open archived:false sort:updated-desc",
            "issues": f"{owners} is:issue is:open archived:false label:{gate} sort:updated-desc",
            "repos": f"{owners} archived:false fork:true"}


def stale_parts(index: dict, cfg: dict, now: float, force: bool) -> dict[str, bool]:
    """Which scans a refresh has to run: everything on `force`, else the stages older than the TTL."""
    out = {}
    for stage in ("prs", "issues", "repos"):
        at = ((index.get("stages") or {}).get(stage) or {}).get("at")
        out[stage] = force or at is None or now - at > cfg["ttl_s"]
    return out


def enrich_order(prs: dict, horizon: float, now: float, force: bool) -> list[str]:
    """The pull requests whose merge state has to be read, in the order the budget is spent on them:
    the ones that can be decided (not drafts) first, then the ones read longest ago."""
    want = [r for r in prs.values() if force or not enrich_fresh(r, horizon, now)]
    want.sort(key=lambda r: (bool(r.get("draft")), (r.get("enrich") or {}).get("at", 0), r.get("repo") or "", r.get("number") or 0))
    return [r["id"] for r in want]


def refresh_index(index: dict, cfg: dict, *, budget: Budget, http: Callable, token: Any, now: float,
                  force: bool = False) -> tuple[dict, dict]:
    """One live read inside `budget` → (the index after it, a report of what it did)."""
    col, pool = Collector(), Pool(cfg["concurrency"], budget)
    parts = stale_parts(index, cfg, now, force)
    # A scan that is read again starts a new cycle, so merge state read in the cycle before goes with it;
    # a call that only resumes (the scan is still fresh) reads what the last one did not reach.
    horizon = cfg["ttl_s"] / 2 if parts["prs"] else cfg["ttl_s"]
    paths_rx = _rx(cfg["ratification"]["paths"])
    searches = searches_of(cfg)
    shapes = {"prs": (SCAN_Q, "issueCount"), "issues": (SCAN_Q, "issueCount"), "repos": (REPOS_Q, "repositoryCount")}
    box: dict[str, Any] = {}

    def ask(stage: str, query: str, variables: dict) -> dict:
        data, partial = gql(query, variables, http=http, tok=box["tok"], budget=budget)
        col.note(stage, data.get("rateLimit"), partial)
        return data

    def enrich_batch(ids: list[str], updated: dict[str, str | None], again: bool = False) -> None:
        if col.halted:
            return
        if again:
            time.sleep(max(0.0, min(UNKNOWN_RETRY_DELAY_S, budget.left() - 1.0)))
        try:
            data = ask("enrich", ENRICH_Q, {"ids": ids})
        except Upstream as exc:
            if exc.kind == "upstream_timeout" and len(ids) > 1:
                mid = len(ids) // 2
                pool.add(lambda: enrich_batch(ids[:mid], updated, again))
                pool.add(lambda: enrich_batch(ids[mid:], updated, again))
            elif not again:  # a failed second ask leaves the first answer in place
                col.error("enrich", exc.kind, str(exc), prs=len(ids))
            return
        rows = {n["id"]: enrichment(n, updated.get(n["id"]), paths_rx, now)
                for n in data.get("nodes") or [] if isinstance(n, dict) and n.get("id") in updated}
        col.enrich(rows)
        unknown = [i for i, row in rows.items() if row["mergeable"] == "UNKNOWN"]
        if unknown and not again and budget.left() > 2.0:
            pool.add(lambda: enrich_batch(unknown, updated, True))

    def plan_enrich(prs: dict) -> None:
        ids = enrich_order(prs, horizon, now, force)
        left = col.remaining()
        if ids and left is not None and left < cfg["min_rate_remaining"]:
            col.error("enrich", "rate_floor", f"{left} requests left on the token, under the floor of "
                      f"{cfg['min_rate_remaining']}: merge state not read for {len(ids)} pull request(s)", prs=len(ids))
            return
        updated = {i: prs[i].get("updated_at") for i in ids}
        for start in range(0, len(ids), cfg["enrich_batch"]):
            batch = ids[start:start + cfg["enrich_batch"]]
            pool.add(lambda batch=batch: enrich_batch(batch, updated))

    def scan(stage: str) -> None:
        query, count_field = shapes[stage]
        result = search_all(lambda v: ask(stage, query, v), searches[stage], count_field,
                            page=cfg["scan_page"], cap=cfg["max_prs"])
        col.scan(stage, result)
        if result["error"]:
            col.error(stage, result["error"]["kind"], result["error"]["message"])
        if stage == "prs" and (result["error"] or {}).get("kind") not in GLOBAL_FAILURES:
            plan_enrich(merge_scan(index.get("prs") or {}, result, now))

    def begin() -> None:
        if not cfg["owners"]:
            col.error("config", "no_owners", "_data/fleet.yml names no hub.owners to search")
            return
        tok = token() if callable(token) else token
        if not tok:
            col.error("auth", "no_token", "no GitHub token: set GH_TOKEN, or connect on the console's GitHub page")
            return
        box["tok"] = tok
        for stage, due in parts.items():
            if due:
                pool.add(lambda stage=stage: scan(stage))
        if not parts["prs"]:
            plan_enrich(index.get("prs") or {})

    pool.add(begin)
    finished = pool.wait()
    col.close()
    if not finished or col.cut:
        col.errors.append({"stage": "budget", "kind": "budget",
                           "message": f"the {budget.seconds:g}s budget ran out before every read finished"})
    for crash in pool.crashed[:3]:
        col.errors.append({"stage": "internal", "kind": "internal", "message": redact(crash)[:300]})

    new = empty_index()
    new["stages"] = {k: dict(v) for k, v in (index.get("stages") or {}).items() if isinstance(v, dict)}
    for stage in ("prs", "issues"):
        result = col.scans.get(stage)
        new[stage] = merge_scan(index.get(stage) or {}, result, now)
        if result is not None:
            meta = new["stages"].setdefault(stage, {})
            meta.update(total=result.get("total"), read=len(result.get("nodes") or []))
            if result["complete"]:
                meta["at"] = now
    for key, row in col.enriched.items():
        if key in new["prs"]:
            new["prs"][key] = {**new["prs"][key], "enrich": row}
    repos = col.scans.get("repos")
    new["repos"] = dict(index.get("repos") or {})
    if repos is not None and repos["complete"]:
        new["repos"] = {n["nameWithOwner"]: {"private": bool(n.get("isPrivate")), "fork": bool(n.get("isFork")),
                                             "open_issues": (n.get("issues") or {}).get("totalCount"),
                                             "open_prs": (n.get("pullRequests") or {}).get("totalCount")}
                        for n in repos["nodes"] if n.get("nameWithOwner")}
        new["stages"]["repos"] = {"at": now, "total": repos.get("total"), "read": len(new["repos"])}
    gained = any(r["complete"] or r["nodes"] for r in col.scans.values()) or bool(col.enriched)
    report = {"attempted": True, "gained": gained, "finished": finished and not col.cut, "requests": col.requests,
              "enriched": len(col.enriched), "errors": list(col.errors), "rate": col.rate,
              "elapsed_s": round(budget.spent(), 2), "budget_s": budget.seconds}
    new["searches"] = searches
    new["last"] = {"at": now, **{k: report[k] for k in ("finished", "requests", "enriched", "errors", "rate",
                                                         "elapsed_s", "budget_s")}}
    return (new if gained else {**index, "last": new["last"]}), report


# --------------------------------------------------------------------------- #
# Classification: which kinds an item is, and why — pure over a record
# --------------------------------------------------------------------------- #
BUMP_RX = re.compile(r"\bfrom\s+[~^<>=\s]*v?(\d[\w.+-]*)\s+to\s+[~^<>=\s]*v?(\d[\w.+-]*)", re.I)


def _lead(version: str) -> tuple:
    """What a breaking change moves: the major, or under 0.x the minor (semver § 4)."""
    nums = [int(x) for x in re.findall(r"\d+", version)[:2]] + [0, 0]
    return (nums[0],) if nums[0] else (0, nums[1])


def bump_of(title: str) -> dict | None:
    """The version move a Dependabot title states; None for a grouped update, which states none."""
    m = BUMP_RX.search(title or "")
    if not m:
        return None
    old, new = m.group(1).rstrip(".-+"), m.group(2).rstrip(".-+")
    return {"from": old, "to": new, "major": _lead(new) > _lead(old)}


def classify(rec: dict, cfg: dict) -> tuple[list[str], list[str], dict]:
    """(kinds in queue order, one reason per kind, the extra fields an item shows)."""
    kinds: list[str] = []
    why: list[str] = []
    extra: dict[str, Any] = {}
    labels = {str(x).lower() for x in rec.get("labels") or []}
    gate = [x for x in cfg["labels"]["gate"] if str(x).lower() in labels]
    if gate:
        kinds.append("needs_amr")
        why.append("labelled " + ", ".join(gate))
    if rec.get("type") != "pr":
        return kinds, why, extra
    e = rec.get("enrich") or {}
    title = rec.get("title") or ""

    if rec.get("head") not in cfg["ratification"]["skip_branches"]:
        if e.get("governs"):
            kinds.append("ratification")
            why.append("changes " + ", ".join(e["governs"][:3]) + (" …" if len(e["governs"]) > 3 else ""))
            extra["governs"] = e["governs"]
        elif (not e or (e.get("files") or 0) > (e.get("files_read") or 0)) \
                and any(rx.search(title) for rx in _rx(cfg["ratification"]["title"])):
            kinds.append("ratification")
            why.append("the title names an amendment or the constitution (its changed files are not all read)")
            extra["heuristic"] = True

    if (rec.get("author") or "").lower() in {str(a).lower() for a in cfg["dependabot"]["authors"]}:
        bump = bump_of(title)
        failing = None if not e else (e.get("checks") in ("FAILURE", "ERROR") or e.get("mergeable") == "CONFLICTING")
        extra["bump"] = bump
        reasons = []
        if bump and bump["major"]:
            reasons.append(f"major bump {bump['from']} → {bump['to']}")
        if failing:
            reasons.append("conflicts with its base" if e.get("mergeable") == "CONFLICTING" else f"checks {e.get('checks')}")
        if reasons:
            kinds.append("dependabot")
            why.append(", ".join(reasons))

    held = [x for x in cfg["labels"]["hold"] if str(x).lower() in labels]
    if (e and not rec.get("draft") and e.get("mergeable") == "MERGEABLE" and e.get("merge_state") in ("CLEAN", "HAS_HOOKS")
            and e.get("checks") in ("SUCCESS", None) and e.get("review") != "CHANGES_REQUESTED" and not held):
        kinds.append("ready_to_merge")
        why.append("mergeable, " + (f"checks {e['checks']}" if e.get("checks") else "no checks")
                   + (f", review {e['review']}" if e.get("review") else ""))
    return kinds, why, extra


# --------------------------------------------------------------------------- #
# The view: status, the queue and the per-repo inventory
# --------------------------------------------------------------------------- #
def parts_of(index: dict, cfg: dict, now: float) -> dict:
    ttl = cfg["ttl_s"]
    out: dict[str, dict] = {}
    for stage in ("prs", "issues", "repos"):
        meta = (index.get("stages") or {}).get(stage) or {}
        at = meta.get("at")
        out[stage] = {"read_at": _iso(at), "age_s": None if at is None else max(0, int(now - at)),
                      "fresh": at is not None and now - at <= ttl, "total": meta.get("total"),
                      "have": len(index.get(stage) or {})}
    prs = list((index.get("prs") or {}).values())
    ats = [p["enrich"]["at"] for p in prs if p.get("enrich")]
    pending = sum(1 for p in prs if not enrich_fresh(p, ttl, now))
    out["enrich"] = {"read_at": _iso(min(ats)) if ats else None,
                     "age_s": max(0, int(now - min(ats))) if ats else None,
                     "fresh": pending == 0, "total": len(prs), "have": len(ats),
                     "pending": pending, "never_read": len(prs) - len(ats)}
    return out


def status_of(index: dict, parts: dict, cfg: dict, now: float) -> tuple[str, int | None]:
    """(status, the age in seconds of the oldest part the queue rests on)."""
    records = list((index.get("prs") or {}).values()) + list((index.get("issues") or {}).values())
    needed = [parts["prs"], parts["issues"], parts["enrich"]]
    if not records and parts["prs"]["age_s"] is None and parts["issues"]["age_s"] is None:
        return "unavailable", None
    ages = [p["age_s"] for p in (parts["prs"], parts["issues"])] + ([parts["enrich"]["age_s"]] if parts["enrich"]["have"] else [])
    age = None if any(a is None for a in ages) else max(ages)
    if all(p["fresh"] for p in needed):
        return "fresh", age
    recent = any(now - r.get("seen_at", 0) <= cfg["ttl_s"] for r in records)
    if recent or parts["prs"]["fresh"] or parts["issues"]["fresh"]:
        return "partial", age
    scan_age = parts["prs"]["age_s"]
    return ("expired" if scan_age is None or scan_age > cfg["max_stale_s"] else "stale"), age


def _item(rec: dict, kinds: list[str], why: list[str], extra: dict, cfg: dict, now: float) -> dict:
    e = rec.get("enrich") or {}
    created = _epoch(rec.get("created_at"))
    item = {
        "key": f"{rec['type']}:{rec['repo']}#{rec['number']}", "kind": kinds[0], "kinds": kinds, "why": why,
        "type": rec["type"], "repo": rec["repo"], "number": rec["number"], "title": rec.get("title"),
        "url": rec.get("url"), "author": rec.get("author"), "labels": rec.get("labels"),
        "draft": rec.get("draft") or None, "private": rec.get("private") or None,
        "updated_at": rec.get("updated_at"), "age_days": None if created is None else max(0, int((now - created) // 86400)),
        "checks": e.get("checks"), "mergeable": e.get("mergeable"), "merge_state": e.get("merge_state"),
        "review": e.get("review"), **extra,
    }
    if rec["type"] == "pr":
        item["enriched"] = bool(e)
        item["read_at"] = _iso(e.get("at")) if e else None
        item["stale"] = (not enrich_fresh(rec, cfg["ttl_s"], now)) or None
    if now - rec.get("seen_at", 0) > cfg["ttl_s"]:
        item["stale"] = True
    return {k: v for k, v in item.items() if v not in (None, [], {})}


def build_items(index: dict, cfg: dict, now: float) -> list[dict]:
    items = []
    for rec in list((index.get("prs") or {}).values()) + list((index.get("issues") or {}).values()):
        kinds, why, extra = classify(rec, cfg)
        if kinds:
            items.append(_item(rec, kinds, why, extra, cfg, now))
    items.sort(key=lambda i: (KINDS.index(i["kind"]), bool(i.get("draft")), i["repo"].lower(), -i["number"]))
    return items


def inventory(index: dict, items: list[dict], cfg: dict) -> list[dict]:
    """One row per repo that has an open pull request, a decision or an open issue the inventory read:
    the pull requests the search found (`open_prs` and its draft / Dependabot / failing / conflicting
    shares), the decisions by kind, and the repo's own open-issue count. `prs_reported` appears only
    where the repo's own pull-request count disagrees with the search."""
    rows: dict[str, dict] = {}
    registry = set(cfg.get("registry") or [])
    authors = {str(a).lower() for a in cfg["dependabot"]["authors"]}

    def row(repo: str) -> dict:
        return rows.setdefault(repo, {"repo": repo, "decisions": 0, "by_kind": {}, "open_prs": 0, "draft_prs": 0,
                                      "dependabot_prs": 0, "failing_prs": 0, "conflicting_prs": 0,
                                      "registry": repo.lower() in registry})

    for rec in (index.get("prs") or {}).values():
        r, e = row(rec["repo"]), rec.get("enrich") or {}
        r["open_prs"] += 1
        r["draft_prs"] += bool(rec.get("draft"))
        r["dependabot_prs"] += (rec.get("author") or "").lower() in authors
        r["failing_prs"] += e.get("checks") in ("FAILURE", "ERROR")
        r["conflicting_prs"] += e.get("mergeable") == "CONFLICTING"
        if rec.get("private"):
            r["private"] = True
    for item in items:
        r = row(item["repo"])
        r["decisions"] += 1
        for kind in item["kinds"]:
            r["by_kind"][kind] = r["by_kind"].get(kind, 0) + 1
    for repo, meta in (index.get("repos") or {}).items():
        if repo in rows or meta.get("open_issues") or meta.get("open_prs"):
            r = row(repo)
            r["open_issues"] = meta.get("open_issues")
            if meta.get("open_prs") != r["open_prs"]:
                r["prs_reported"] = meta.get("open_prs")
            if meta.get("private"):
                r["private"] = True
    return sorted(rows.values(), key=lambda r: (-r["decisions"], -r["open_prs"], r["repo"].lower()))


def view(index: dict, cfg: dict, now: float, *, kind: str = "", repo: str = "", limit: int = 50,
         report: dict | None = None, warnings: list[str] | None = None, budget: Budget | None = None,
         had_index: bool = True) -> dict:
    report = report or {"attempted": False}
    warnings = list(warnings or [])
    parts = parts_of(index, cfg, now)
    status, age = status_of(index, parts, cfg, now)
    every = build_items(index, cfg, now)
    rows = inventory(index, every, cfg)
    want_repo = repo.lower()
    items = [i for i in every if (not kind or kind in i["kinds"])
             and (not want_repo or want_repo in (i["repo"].lower(), i["repo"].lower().split("/")[-1]))]
    counts = {k: sum(1 for i in every if k in i["kinds"]) for k in KINDS}
    errors = list(report.get("errors") or [])
    if not errors and not report.get("attempted") and status != "fresh":
        errors = list(((index.get("last") or {}).get("errors")) or [])  # why the index is the way it is
    if status == "expired":
        warnings.append("the index is older than decisions.max_stale_s: treat every row as a lead to check, not a fact")
    elif status == "stale":
        warnings.append(f"the index was read {age}s ago and could not be refreshed" if age is not None
                        else "the index is old and could not be refreshed")
    if parts["enrich"]["pending"] and status != "unavailable":
        warnings.append(f"merge state, checks and changed files are not current for {parts['enrich']['pending']} of "
                        f"{parts['enrich']['total']} pull request(s): ready_to_merge, ratification and failing "
                        "Dependabot rows may be missing")
    seen, reported = parts["prs"]["have"], sum((m.get("open_prs") or 0) for m in (index.get("repos") or {}).values())
    if parts["prs"]["fresh"] and parts["repos"]["fresh"] and reported != seen:
        warnings.append(f"the search returned {seen} open pull request(s) but the repos report {reported}: "
                        "the search index lags, or the token cannot search a repo it can list")
    hint = next((HINTS[e["kind"]] for e in errors if e.get("kind") in HINTS), None)
    gained = bool(report.get("gained"))
    source = "none" if status == "unavailable" else "cache" if not gained else \
        "live" if status == "fresh" or not had_index else "live+cache"
    doc = {
        "schema": SCHEMA, "generated_at": _iso(now), "status": status, "complete": status == "fresh",
        "source": source, "age_s": age, "read_at": parts["prs"]["read_at"], "ttl_s": cfg["ttl_s"],
        "budget_s": budget.seconds if budget else None, "elapsed_s": round(budget.spent(), 2) if budget else None,
        "counts": counts, "total": len(every), "matched": len(items), "returned": min(len(items), limit),
        "filters": {k: v for k, v in (("kind", kind), ("repo", repo)) if v},
        "items": items[:limit],
        "repos": [r for r in rows if r["decisions"] or r["open_prs"]],
        "inventory": {"repos": len(rows), "open_prs": seen,
                      "open_issues": sum((m.get("open_issues") or 0) for m in (index.get("repos") or {}).values())
                      if index.get("repos") else None,
                      **{k: sum(r[k] for r in rows) for k in ("dependabot_prs", "draft_prs", "failing_prs",
                                                              "conflicting_prs")}},
        "parts": parts,
        "refresh": {k: report.get(k) for k in ("attempted", "gained", "finished", "requests", "enriched", "rate")
                    if report.get(k) is not None},
        "warnings": warnings, "errors": errors[:MAX_ERRORS], "hint": hint,
    }
    return {k: v for k, v in doc.items() if v is not None}


# --------------------------------------------------------------------------- #
# The one entry point every surface calls
# --------------------------------------------------------------------------- #
_REFRESH_LOCK = threading.Lock()


def _clamp_budget(value: Any, default: float) -> float:
    try:
        seconds = float(value) if value else float(default)
    except (TypeError, ValueError):
        seconds = float(default)
    return min(BUDGET_MAX_S, max(BUDGET_MIN_S, seconds))


def queue(root: Path = ROOT, *, kind: str = "", repo: str = "", limit: int = 50, refresh: str = "auto",
          budget_s: float | None = None, http: Callable | None = None, token: Any = None,
          now: Callable[[], float] | None = None, cfg: dict | None = None) -> dict:
    """The decision queue, in one call and inside `budget_s`.

    refresh: `auto` serves the index when it is fresh and reads GitHub when it is not; `never` serves the
    index as it is, whatever its age; `force` reads GitHub now. `token` is a value or a function returning
    one (asked only when a read is needed, inside the budget); `http` and `now` exist for the tests.
    """
    if kind and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if refresh not in REFRESH_MODES:
        raise ValueError(f"refresh must be one of {', '.join(REFRESH_MODES)}")
    if repo and not re.fullmatch(r"(?:[A-Za-z0-9][A-Za-z0-9-]{0,38}/)?(?!\.+$)[A-Za-z0-9._-]{1,100}", repo):
        raise ValueError("repo must be owner/name or a repo name")
    cfg = cfg or load_config(root)
    limit = min(MAX_LIMIT, max(0, int(limit)))
    budget = Budget(_clamp_budget(budget_s, cfg["budget_s"]))
    clock = now or time.time
    path = index_path(root)
    warnings: list[str] = []

    def load() -> dict:
        doc, set_aside = load_index(path)
        if not set_aside and doc.get("searches") not in (None, searches_of(cfg)):
            doc, set_aside = empty_index(), "the index was built for other owners or gate labels; it is being rebuilt"
        if set_aside and set_aside not in warnings:
            warnings.append(set_aside)
        return doc

    index = load()
    had_index = bool(index.get("prs") or index.get("issues") or index.get("stages"))
    report: dict = {"attempted": False}

    def is_fresh(doc: dict) -> bool:
        return status_of(doc, parts_of(doc, cfg, clock()), cfg, clock())[0] == "fresh"

    if refresh == "force" or (refresh == "auto" and not is_fresh(index)):
        if _REFRESH_LOCK.acquire(timeout=max(0.0, budget.left() - MIN_CALL_S)):
            try:
                index = load()  # the holder before us may have just written it
                if refresh == "force" or not is_fresh(index):
                    index, report = refresh_index(index, cfg, budget=budget, http=http or _http,
                                                  token=token if token is not None else resolve_token,
                                                  now=clock(), force=refresh == "force")
                    failed = save_index(path, index)  # also when nothing was read: `status` then says why
                    if failed:
                        warnings.append(failed)
            finally:
                _REFRESH_LOCK.release()
        else:
            report = {"attempted": False, "errors": [{"stage": "refresh", "kind": "busy",
                                                      "message": "another refresh held the index for the whole budget"}]}
            index = load()
    return view(index, cfg, clock(), kind=kind, repo=repo, limit=limit, report=report, warnings=warnings,
                budget=budget, had_index=had_index)


# --------------------------------------------------------------------------- #
# CLI: tools/dash decisions [queue|refresh|status]
# --------------------------------------------------------------------------- #
def _line(item: dict) -> str:
    state = [item.get("merge_state"), f"checks {item['checks']}" if item.get("checks") else None,
             "draft" if item.get("draft") else None, "private" if item.get("private") else None,
             "old" if item.get("stale") else None]
    also = [k for k in item["kinds"][1:]]
    return (f"  {item['repo']}#{item['number']:<5} {'PR ' if item['type'] == 'pr' else 'ISS'} "
            f"{(item.get('title') or '')[:72]:<72}  {' · '.join(s for s in state if s)}"
            + (f"  (+{', '.join(also)})" if also else "") + f"\n      {'; '.join(item['why'])}  {item.get('url') or ''}")


def render(doc: dict, repos: bool = False) -> str:
    age = "never read" if doc.get("age_s") is None else f"read {doc['age_s']}s ago"
    head = (f"Decision queue: {doc['total']} item(s) · {doc['status'].upper()} ({age}, source {doc['source']}"
            + (f", {doc['elapsed_s']}s of a {doc['budget_s']:g}s budget" if doc.get("elapsed_s") is not None else "") + ")")
    out = [head, "  " + " · ".join(f"{KIND_TITLES[k]} {n}" for k, n in doc["counts"].items())]
    for kind in KINDS:
        rows = [i for i in doc["items"] if i["kind"] == kind]
        if rows:
            out += ["", f"{KIND_TITLES[kind].upper()} ({len(rows)})"] + [_line(i) for i in rows]
    if doc["matched"] > doc["returned"]:
        out.append(f"\n… {doc['matched'] - doc['returned']} more (raise --limit)")
    if repos and doc.get("repos"):
        out += ["", "REPOS (decisions · open PRs · drafts · dependabot · failing · open issues)"]
        out += [f"  {r['repo']:<44} {r['decisions']:>3} {r['open_prs']:>4} {r['draft_prs']:>4} {r['dependabot_prs']:>4} "
                f"{r['failing_prs']:>4} {'-' if r.get('open_issues') is None else r['open_issues']:>5}"
                for r in doc["repos"]]
    for w in doc.get("warnings") or []:
        out.append(f"\nwarning: {w}")
    for e in doc.get("errors") or []:
        out.append(f"error [{e.get('stage')}/{e.get('kind')}]: {e.get('message')}")
    if doc.get("hint"):
        out.append(f"hint: {doc['hint']}")
    return "\n".join(out)


def render_status(doc: dict, path: Path) -> str:
    out = [f"Decision index: {path}", f"  status {doc['status']} · {doc['total']} item(s) · ttl {doc['ttl_s']}s"]
    for name, part in doc["parts"].items():
        age = "never read" if part["age_s"] is None else f"{part['age_s']}s old"
        extra = f", {part['pending']} pending" if part.get("pending") else ""
        out.append(f"  {name:<7} {'fresh' if part['fresh'] else 'old  '}  {age}, {part['have']} of {part['total']}{extra}")
    for e in doc.get("errors") or []:
        out.append(f"  last error [{e.get('stage')}/{e.get('kind')}]: {e.get('message')}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/dash decisions", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--json", action="store_true", help="print the document instead of the table")
    shared.add_argument("--budget", type=float, default=None, help="wall clock in seconds (default: fleet.yml decisions)")
    q = sub.add_parser("queue", parents=[shared], help="the decision queue (the default)")
    q.add_argument("--kind", default="", choices=("",) + KINDS)
    q.add_argument("--repo", default="", help="owner/name or a repo name")
    q.add_argument("--limit", type=int, default=100)
    q.add_argument("--refresh", default="auto", choices=REFRESH_MODES)
    q.add_argument("--repos", action="store_true", help="add the per-repo inventory")
    sub.add_parser("refresh", parents=[shared], help="read GitHub now, under the longer refresh budget")
    sub.add_parser("status", parents=[shared], help="the index as it is: no GitHub call")
    argv = list(argv or [])
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "queue")  # bare `dash decisions`, or one that starts with a flag, is the queue
    args = ap.parse_args(argv)
    cfg = load_config(ROOT)
    try:
        if args.cmd == "refresh":
            doc = queue(ROOT, limit=0, refresh="force", budget_s=args.budget or cfg["refresh_budget_s"], cfg=cfg)
        elif args.cmd == "status":
            doc = queue(ROOT, limit=0, refresh="never", cfg=cfg)
        else:
            doc = queue(ROOT, kind=args.kind, repo=args.repo, limit=args.limit, refresh=args.refresh,
                        budget_s=args.budget, cfg=cfg)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(doc, indent=1))
    elif args.cmd == "status":
        print(render_status(doc, index_path(ROOT)))
    elif args.cmd == "refresh":
        print(render_status(doc, index_path(ROOT)))
        for line in [f"warning: {w}" for w in doc.get("warnings") or []] + ([f"hint: {doc['hint']}"] if doc.get("hint") else []):
            print(line)
    else:
        print(render(doc, repos=args.repos))
    if args.cmd == "refresh":  # green only when this read finished, clean: a schedule must not hide a failed one
        return 0 if doc["complete"] and doc["refresh"].get("finished") and not doc["errors"] else 1
    return 1 if doc["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""
File: tools/link_check.py
Description: The fleet's link check. Finds every link the fleet publishes and
             asks each one, once, whether it still answers:

             repos   every tracked Markdown/HTML file of the hub and of each
                     checked-out submodule whose owner is in fleet.yml
                     `hub.owners` (GitHub renders these: the profile README at
                     github.com/bamr87 is the hub's README.md), plus the URL
                     values of the hub data files that feed the profile
                     (`links.data_files`: the registry and the portfolio).
                     Fenced code, inline code and HTML comments are skipped,
                     so an example in a code block is not a link. A relative
                     link to a file (`docs/X.md`, `img/a.png`) is checked
                     against the repo's tracked files, case and all, the way
                     GitHub resolves it.
             sites   every live site in the registry and the portfolio: its
                     sitemap (or a breadth-first crawl when it has none), up to
                     `links.max_pages` pages, and every <a>/<img>/<script>/
                     <link> on them, internal links included.

             Each unique URL is checked once. github.com and
             raw.githubusercontent.com links are answered by the GitHub GraphQL
             API in batches (a repository, a file at a ref, an issue or pull
             request, a commit, a release tag, a workflow badge), because
             github.com answers crawlers with 429; a repository GraphQL cannot
             see is retried over REST, which follows renames. Everything else
             is an HTTP HEAD, then a GET when HEAD is refused.

             ok          answered (after redirects)
             broken      404/410, a name that does not resolve, a GitHub
                         repository/file/issue that does not exist, or a
                         relative link to a file that is not tracked
             error       5xx, timeout, refused, TLS failure (after one retry)
             unverified  the host refused a robot (401/403/429/999)
             moved       a GitHub repository that was renamed (the link still
                         redirects; the new name is reported)

             Read-only: it writes nothing but the report files you ask for and
             a cache of `ok` answers (.fleet/links/cache.json, reused for
             `links.cache_hours`; --fresh ignores it). Exit 1 when anything is
             broken (--fail-on error also counts errors; never: always 0).
             Configuration: _data/fleet.yml `links:`. Doc: docs/LINK-CHECK.md.
Usage: python3 tools/link_check.py [scan] [--repo NAME]... [--no-sites] [--no-repos]
                                   [--json OUT] [--markdown OUT] [--fresh] [--fail-on broken|error|never]
       python3 tools/link_check.py url URL...       # check these URLs only
       python3 tools/link_check.py targets           # the repos and live sites a scan would read
       tools/dash links ...                          # the same
"""
from __future__ import annotations

import argparse
import concurrent.futures
import fnmatch
import html
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

import yaml

HUB = Path(__file__).resolve().parents[1]
CACHE = HUB / ".fleet" / "links" / "cache.json"

DEFAULTS: dict = {
    "extensions": [".md", ".markdown", ".html", ".htm"],
    "data_files": ["_data/projects.yml", "_data/portfolio.yml"],
    "exclude_paths": [],
    "exclude_urls": [],
    "relative_skip_paths": [],
    "workers": 16,
    "per_host": 4,
    "timeout": 15,
    "max_pages": 200,
    "cache_hours": 24,
    "github_batch": 80,
}

STATUSES = ("broken", "error", "moved", "unverified", "ok")
UA = "Mozilla/5.0 (compatible; fleet-link-check/1.0)"

# --------------------------------------------------------------------------- #
# Configuration and targets
# --------------------------------------------------------------------------- #


def load_config(hub: Path = HUB) -> dict:
    cfg = dict(DEFAULTS)
    try:
        fleet = yaml.safe_load((hub / "_data" / "fleet.yml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        fleet = {}
    cfg.update({k: v for k, v in (fleet.get("links") or {}).items() if v is not None})
    hub_cfg = fleet.get("hub") or {}
    cfg["owners"] = [o.lower() for o in (hub_cfg.get("owners") or ["bamr87"])]
    cfg["hub_repo"] = hub_cfg.get("repo") or "bamr87/bamr87"
    return cfg


@dataclass
class Repo:
    name: str
    nwo: str
    path: Path


@dataclass
class Site:
    url: str
    label: str


def _nwo(url: str | None) -> str | None:
    m = re.match(r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+)", url or "")
    return f"{m.group(1)}/{m.group(2).removesuffix('.git')}" if m else None


def _has_checkout(path: Path) -> bool:
    return (path / ".git").exists() and any(p.name != ".git" for p in path.iterdir())


def targets(root: Path, cfg: dict, only: Iterable[str] = ()) -> tuple[list[Repo], list[Site]]:
    """The repos to scan (hub + owned, checked-out submodules) and the live sites."""
    only = {o.lower() for o in only}
    try:
        registry = yaml.safe_load((root / "_data" / "projects.yml").read_text()) or []
    except OSError:
        registry = []
    try:
        portfolio = yaml.safe_load((root / "_data" / "portfolio.yml").read_text()) or {}
    except OSError:
        portfolio = {}
    hub_name = cfg["hub_repo"].split("/")[-1]
    repos: list[Repo] = []
    if not only or hub_name.lower() in only:
        repos.append(Repo(hub_name, cfg["hub_repo"], root))
    seen_sites: dict[str, Site] = {}

    def add_site(url: str | None, label: str) -> None:
        if not url or not re.match(r"https?://", url):
            return
        key = url + "/" if urllib.parse.urlsplit(url).path == "" else url
        seen_sites.setdefault(key, Site(key, label))

    for entry in registry:
        name = str(entry.get("name") or "")
        if only and name.lower() not in only:
            continue
        nwo = _nwo(entry.get("repo_url"))
        owned = bool(nwo) and nwo.split("/")[0].lower() in cfg["owners"]
        if not owned:
            continue
        sub = entry.get("submodule_path")
        if sub and _has_checkout(root / sub):
            repos.append(Repo(name, nwo, root / sub))
        if str(entry.get("status") or "") != "archived":
            add_site(entry.get("live_url"), name)
            add_site(entry.get("docs_url"), name)
    for extra in portfolio.get("extra") or []:
        name = str(extra.get("name") or "")
        if only and name.lower() not in only:
            continue
        add_site(extra.get("live_url"), name)
    return repos, list(seen_sites.values())


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

URL_RE = re.compile(r"""https?://[^\s<>"'`\[\]{}|\\^]+""")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)[^`\n]+?\1")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
HINT_LINK_RE = re.compile(r"<link\b[^>]*\brel\s*=\s*[\"']?(?:preconnect|dns-prefetch)\b[^>]*>", re.I)
HTML_CODE_RE = re.compile(r"<(pre|code|script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
LIQUID_CODE_RE = re.compile(r"{%-?\s*(raw|highlight|comment)\b.*?%}.*?{%-?\s*end\1\s*-?%}", re.S)
MD_TARGET_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'(][^)]*)?\)")
ATTR_TARGET_RE = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", re.I)
REFDEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.M)
YAML_URL_RE = re.compile(r"""^\s*(?:-\s+)?(?:[\w.-]+:\s+)?["']?(https?://[^\s"'#]+)["']?\s*(?:#.*)?$""")
TRAIL = ".,;:!?*_'\""
SKIP_EXT = {".html", ".htm", ".php", ".asp", ".aspx"}


def _blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def strip_code(text: str, markdown: bool = True) -> str:
    """Blank out code, comments and raw blocks, keeping every newline so line
    numbers still point at the source."""
    if markdown:
        out, fence = [], None
        for line in text.split("\n"):
            m = FENCE_RE.match(line)
            if fence:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                    fence = None
                out.append("")
                continue
            if m:
                fence = m.group(1)
                out.append("")
                continue
            out.append(line)
        text = "\n".join(out)
        text = INLINE_CODE_RE.sub(_blank, text)
    text = COMMENT_RE.sub(_blank, text)
    text = HINT_LINK_RE.sub(_blank, text)  # a connection hint names an origin, not a page
    text = HTML_CODE_RE.sub(_blank, text)
    text = LIQUID_CODE_RE.sub(_blank, text)
    return text


FULLWIDTH_STOP = re.compile(r"[\u3000-\u303f\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65]")


def clean_url(url: str) -> str:
    url = re.sub(r"\\([_*\[\]()#~\-.!])", r"\1", url)
    # A URL ends at the first `)` it did not open — `[x](https://a.dev/)-word`
    # and CJK text set without a space — and at fullwidth punctuation.
    depth = 0
    for i, ch in enumerate(url):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                url = url[:i]
                break
            depth -= 1
    m = FULLWIDTH_STOP.search(url)
    if m:
        url = url[:m.start()]
    if "&amp;" in url or "&#" in url:
        url = html.unescape(url)
    while url:
        last = url[-1]
        if last in TRAIL:
            url = url[:-1]
        elif last == ")" and url.count("(") < url.count(")"):
            url = url[:-1]
        else:
            break
    return url


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract(text: str, kind: str = "md") -> list[tuple[int, str, str]]:
    """[(line, target, 'url'|'rel')] from one file's text. kind: md | html | yaml."""
    found: list[tuple[int, str, str]] = []
    if kind == "yaml":
        for n, line in enumerate(text.split("\n"), 1):
            m = YAML_URL_RE.match(line)
            if m:
                found.append((n, clean_url(m.group(1)), "url"))
        return found
    body = strip_code(text, markdown=(kind == "md"))
    for m in URL_RE.finditer(body):
        url = clean_url(m.group(0))
        if url:
            found.append((_line_of(body, m.start()), url, "url"))
    rel_res = (MD_TARGET_RE, ATTR_TARGET_RE, REFDEF_RE) if kind == "md" else (ATTR_TARGET_RE,)
    seen = set()
    for rx in rel_res:
        for m in rx.finditer(body):
            target = m.group(1).strip()
            if is_relative_file(target):
                key = (m.start(1), target)
                if key not in seen:
                    seen.add(key)
                    found.append((_line_of(body, m.start(1)), target, "rel"))
    return sorted(found)


def is_relative_file(target: str) -> bool:
    """A repo-relative link to a FILE: has an extension, is not a page permalink."""
    if not target or target[0] in "#/?~<$" or "://" in target or target.startswith("//"):
        return False
    low = target.lower()
    if low.startswith(("mailto:", "tel:", "data:", "javascript:", "http:", "https:")):
        return False
    if "{{" in target or "{%" in target or "%7b%7b" in low or re.search(r"%[A-Z_]+%", target):
        return False  # Liquid, or a build-time placeholder such as Vite's %BASE_URL%
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path or path.endswith("/"):
        return False
    ext = os.path.splitext(path.rsplit("/", 1)[-1])[1].lower()
    return bool(ext) and ext not in SKIP_EXT and re.fullmatch(r"\.[a-z0-9]{1,8}", ext) is not None


PLACEHOLDER_RE = re.compile(
    r"(your[-_]?(user(name)?|org|repo|domain|site|name)|<[^>]*>|\{\{|\{%|\$\{|%7b%7b|\$[A-Z_]+|\bOWNER\b|\bUSERNAME\b|\bREPO\b|xxx+)",
    re.I,
)
LOCAL_HOSTS = ("localhost", "0.0.0.0", "127.", "10.", "192.168.", "169.254.", "host.docker.internal")
LOCAL_SUFFIXES = (".local", ".localhost", ".test", ".internal", ".example", ".invalid", ".lan", ".home")
EXAMPLE_HOSTS = ("example.com", "example.org", "example.net", "example.edu")


def skip_reason(url: str, cfg: dict) -> str | None:
    """Why a URL is not a link worth checking, or None."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "unparseable"
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return "not http"
    if PLACEHOLDER_RE.search(url):
        return "placeholder"
    if host.startswith(LOCAL_HOSTS) or host.endswith(LOCAL_SUFFIXES) or host == "::1":
        return "local"
    if re.match(r"172\.(1[6-9]|2\d|3[01])\.", host):
        return "local"
    if "." not in host:
        return "local"
    if host in EXAMPLE_HOSTS or any(host.endswith("." + h) for h in EXAMPLE_HOSTS):
        return "example"
    for rx in cfg.get("exclude_urls") or []:
        if re.search(rx, url):
            return "excluded"
    return None


def url_key(url: str) -> str:
    """One key per resource: lower-case scheme and host, no fragment."""
    parts = urllib.parse.urlsplit(url)
    netloc = parts.netloc.lower()
    return urllib.parse.urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


# --------------------------------------------------------------------------- #
# Scan state
# --------------------------------------------------------------------------- #


@dataclass
class Occurrence:
    repo: str       # the repo name, or "site <host/path>"
    where: str      # path inside the repo, or the page URL
    line: int | None = None
    target: str = ""  # the text as written (for relative links)

    def label(self) -> str:
        return f"{self.where}:{self.line}" if self.line else self.where


@dataclass
class Result:
    status: str
    code: int | None = None
    detail: str = ""
    final: str | None = None
    how: str = "http"

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


@dataclass
class Scan:
    occurrences: dict[str, list[Occurrence]] = field(default_factory=lambda: defaultdict(list))
    results: dict[str, Result] = field(default_factory=dict)
    skipped: Counter = field(default_factory=Counter)
    files: int = 0
    repos: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    pages: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, url: str, occ: Occurrence, cfg: dict) -> None:
        reason = skip_reason(url, cfg)
        if reason:
            self.skipped[reason] += 1
            return
        self.occurrences[url_key(url)].append(occ)


# --------------------------------------------------------------------------- #
# Repo sources
# --------------------------------------------------------------------------- #


def tracked_files(path: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(path), "ls-files", "-z"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def _excluded(repo: str, rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        scope, _, glob = pat.rpartition(":") if ":" in pat else ("", "", pat)
        if scope and scope.lower() != repo.lower():
            continue
        if fnmatch.fnmatch(rel, glob) or (glob.endswith("/**") and (rel + "/").startswith(glob[:-2])):
            return True
    return False


class TrackedIndex:
    """Tracked paths per repo, so a relative link resolves the way GitHub does:
    case-sensitive and only to committed files. A hub path inside a submodule
    delegates to that submodule's own index."""

    def __init__(self) -> None:
        self.files: dict[Path, set[str]] = {}
        self.dirs: dict[Path, set[str]] = {}

    def load(self, root: Path, files: list[str]) -> None:
        self.files[root] = set(files)
        dirs = set()
        for f in files:
            parts = f.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        self.dirs[root] = dirs

    def exists(self, root: Path, rel: str) -> bool:
        files = self.files.get(root)
        if files is None:
            return (root / rel).exists()
        if rel in files or rel in self.dirs[root]:
            return True
        for other in self.files:
            if other != root and other.is_relative_to(root):
                sub = other.relative_to(root).as_posix()
                if rel == sub or rel.startswith(sub + "/"):
                    return self.exists(other, rel[len(sub) + 1:]) if rel != sub else True
        return False


def resolve_relative(root: Path, file_rel: str, target: str) -> str | None:
    """The repo-relative path a relative link names, or None when it climbs out."""
    path = urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])
    base = Path(file_rel).parent
    parts: list[str] = []
    for seg in (base / path).as_posix().split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def scan_repos(scan: Scan, repos: list[Repo], cfg: dict, index: TrackedIndex) -> None:
    exts = tuple(e.lower() for e in cfg["extensions"])
    data_files = set(cfg.get("data_files") or [])
    hub_name = cfg["hub_repo"].split("/")[-1]
    listing = {r.path: tracked_files(r.path) for r in repos}
    for repo in repos:
        index.load(repo.path, listing[repo.path])
    for repo in repos:
        scan.repos.append(repo.name)
        for rel in listing[repo.path]:
            low = rel.lower()
            is_data = repo.name == hub_name and rel in data_files
            if not (low.endswith(exts) or is_data):
                continue
            if _excluded(repo.name, rel, cfg.get("exclude_paths") or []):
                continue
            fpath = repo.path / rel
            try:
                if fpath.stat().st_size > 2_000_000:
                    continue
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scan.files += 1
            kind = "yaml" if is_data else ("html" if low.endswith((".html", ".htm")) else "md")
            skip_rel = _excluded(repo.name, rel, cfg.get("relative_skip_paths") or [])
            for line, target, what in extract(text, kind):
                if what == "url":
                    scan.add(target, Occurrence(repo.name, rel, line), cfg)
                    continue
                if skip_rel:
                    continue
                resolved = resolve_relative(repo.path, rel, target)
                key = f"file:{repo.name}:{resolved or target}"
                scan.occurrences[key].append(Occurrence(repo.name, rel, line, target))
                if key in scan.results:
                    continue
                if resolved is None:
                    scan.results[key] = Result("broken", detail="climbs out of the repository", how="file")
                elif index.exists(repo.path, resolved):
                    scan.results[key] = Result("ok", how="file")
                else:
                    scan.results[key] = Result("broken", detail=f"no tracked file {resolved}", how="file")


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class HostGate:
    """At most `limit` requests in flight per host."""

    def __init__(self, limit: int, overrides: dict[str, int] | None = None) -> None:
        self.limit, self.overrides = limit, overrides or {}
        self.lock = threading.Lock()
        self.gates: dict[str, threading.BoundedSemaphore] = {}

    def limit_for(self, host: str) -> int:
        for suffix, n in self.overrides.items():
            if host == suffix or (suffix.startswith(".") and host.endswith(suffix)):
                return n
        return self.limit

    def __call__(self, host: str) -> threading.BoundedSemaphore:
        with self.lock:
            if host not in self.gates:
                self.gates[host] = threading.BoundedSemaphore(self.limit_for(host))
            return self.gates[host]


# github.com's HTML answers crawlers with 429 well before any other host. (GitHub
# Pages serves most of the fleet's sites from one host, and 8 in flight there
# drew 429s too, so it keeps the default.)
HOST_LIMITS = {"github.com": 2, "www.github.com": 2}


def interleave(urls: list[str]) -> list[str]:
    """Round-robin by host, so the pool's threads spread across hosts instead
    of queueing on one host's gate while every other host waits."""
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in sorted(urls):
        by_host[urllib.parse.urlsplit(u).hostname or ""].append(u)
    queues = sorted(by_host.values(), key=len, reverse=True)
    out: list[str] = []
    while queues:
        nxt = []
        for q in queues:
            out.append(q.pop(0))
            if q:
                nxt.append(q)
        queues = nxt
    return out


@dataclass
class Fetched:
    code: int | None
    final: str | None = None
    body: bytes = b""
    ctype: str = ""
    error: str = ""
    dns: bool = False
    retry_after: float | None = None


def _opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(), urllib.request.HTTPSHandler(context=ctx)
    )


def to_uri(url: str) -> str:
    """An IRI as a request line can carry it: IDNA host, percent-encoded rest."""
    if url.isascii() and not re.search(r"[\s\x00-\x1f]", url):
        return url
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    netloc = host + (f":{parts.port}" if parts.port else "")
    safe = "/:@!$&'()*+,;=%~-._"
    return urllib.parse.urlunsplit((parts.scheme, netloc, urllib.parse.quote(parts.path, safe=safe),
                                    urllib.parse.quote(parts.query, safe=safe + "?"), ""))


def fetch(url: str, method: str, timeout: float, read: int = 0) -> Fetched:
    url = to_uri(url)
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en",
    })
    try:
        with _opener().open(req, timeout=timeout) as resp:
            body = resp.read(read) if read else (resp.read(1) if method == "GET" else b"")
            return Fetched(resp.status, resp.geturl(), body, resp.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        wait = (exc.headers or {}).get("Retry-After") if exc.code == 429 else None
        return Fetched(exc.code, exc.geturl() if hasattr(exc, "geturl") else None, error=str(exc.reason),
                       retry_after=float(wait) if wait and str(wait).isdigit() else (5.0 if exc.code == 429 else None))
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            nx = reason.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -999))
            return Fetched(None, error=f"DNS: {reason.strerror or reason}", dns=nx)
        if isinstance(reason, ssl.SSLError):
            return Fetched(None, error=f"TLS: {getattr(reason, 'reason', None) or reason}")
        return Fetched(None, error=str(reason))
    except (TimeoutError, socket.timeout):
        return Fetched(None, error="timeout")
    except (ConnectionError, OSError, ValueError) as exc:
        return Fetched(None, error=type(exc).__name__ + (f": {exc}" if str(exc) else ""))
    except Exception as exc:  # http.client oddities (BadStatusLine, IncompleteRead, …)
        return Fetched(None, error=f"{type(exc).__name__}: {exc}")


def classify(f: Fetched) -> Result:
    if f.code is not None and 200 <= f.code < 400:
        return Result("ok", f.code, final=f.final)
    if f.code in (404, 410):
        return Result("broken", f.code, f"HTTP {f.code}", f.final)
    if f.code in (401, 403, 407, 429, 999):
        return Result("unverified", f.code, f"HTTP {f.code} (refuses robots)", f.final)
    if f.code is not None:
        return Result("error", f.code, f"HTTP {f.code}", f.final)
    if f.dns:
        return Result("broken", None, f.error)
    return Result("error", None, f.error)


def check_http(url: str, gate: HostGate, timeout: float, fetcher: Callable = fetch) -> Result:
    host = urllib.parse.urlsplit(url).hostname or ""
    with gate(host):
        first = fetcher(url, "HEAD", timeout)
        result = classify(first)
        if result.status == "ok" or first.dns:
            return result
        # HEAD is refused or mishandled by enough servers that only a GET may
        # call a link broken, and a GET is also the one retry a timeout gets.
        # A 429 is waited out first (Retry-After, at most 30s), holding the
        # host's gate so the rest of its queue waits too.
        if first.code == 429:
            time.sleep(min(5.0 if first.retry_after is None else first.retry_after, 30.0))
        second = fetcher(url, "GET", timeout)
        if second.code == 429:
            time.sleep(min(5.0 if second.retry_after is None else second.retry_after, 30.0))
            second = fetcher(url, "GET", timeout)
        result = classify(second)
        if result.status == "error" and (result.code or 0) >= 500:
            time.sleep(2)
            result = classify(fetcher(url, "GET", timeout))
    return result


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #

GITHUB_HOSTS = {"github.com", "www.github.com"}
RAW_HOSTS = {"raw.githubusercontent.com"}
# First path segments of github.com that are GitHub's own pages, not an owner.
RESERVED = {
    "about", "account", "apps", "blog", "codespaces", "collections", "contact", "copilot",
    "customer-stories", "dashboard", "enterprise", "events", "explore", "features", "git-guides",
    "github-copilot", "home", "issues", "join", "login", "logout", "marketplace", "mobile", "new",
    "notifications", "orgs", "organizations", "partners", "premium-support", "pricing", "pulls",
    "readme", "resources", "search", "security", "settings", "signup", "site", "solutions",
    "sponsors", "stars", "team", "topics", "trending", "user-attachments", "users", "watching",
    "why-github", "education", "nonprofit", "open-source", "accelerator", "gist", "codeql",
}
# Repo sub-pages a repository's existence is the whole answer for.
REPO_LEVEL = {
    "issues", "pulls", "actions", "releases", "wiki", "compare", "network", "graphs", "stargazers",
    "watchers", "forks", "labels", "milestone", "milestones", "projects", "security", "settings",
    "discussions", "archive", "tags", "branches", "activity", "deployments", "packages", "pkgs",
    "community", "contributors", "pulse", "search", "workflows", "fork", "subscription",
}


@dataclass(frozen=True)
class GhRef:
    owner: str
    repo: str | None
    leaf: tuple | None = None  # ("obj", (expr, ...)) | ("issue", n) | ("release", tag) | ("discussion", n)


def _exprs(segs: list[str], prefix_path: str = "") -> tuple[str, ...]:
    """Candidate `ref:path` expressions for blob/tree segments, since a branch
    name may itself contain slashes (feature/x)."""
    out = []
    for cut in range(1, min(3, len(segs)) + 1):
        ref, rest = "/".join(segs[:cut]), "/".join(segs[cut:])
        if ref == "refs/heads" or ref == "refs":
            continue
        out.append(f"{ref}:{prefix_path}{rest}" if rest or prefix_path else ref)
    return tuple(dict.fromkeys(out))


def parse_github(url: str) -> GhRef | None:
    """What a GitHub URL names, or None when only HTTP can answer it."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    segs = [urllib.parse.unquote(s) for s in parts.path.split("/") if s]
    if host in RAW_HOSTS:
        if len(segs) < 4:
            return None
        rest = segs[2:]
        if rest[:2] == ["refs", "heads"] or rest[:2] == ["refs", "tags"]:
            rest = rest[2:]
        return GhRef(segs[0], segs[1], ("obj", _exprs(rest)))
    if host not in GITHUB_HOSTS or not segs:
        return None
    if segs[0].lower() in RESERVED or segs[0].startswith((".", "-")):
        return None
    if len(segs) == 1:  # a user or organization; `<login>.png` is its avatar
        return GhRef(segs[0].removesuffix(".png"), None)
    owner, repo = segs[0], segs[1].removesuffix(".git")
    if len(segs) == 2:
        return GhRef(owner, repo)
    kind, rest = segs[2].lower(), segs[3:]
    if kind in ("blob", "tree", "raw", "blame", "edit") and rest:
        return GhRef(owner, repo, ("obj", _exprs(rest)))
    if kind == "commit" and rest:
        return GhRef(owner, repo, ("obj", (rest[0],)))
    if kind == "commits" and rest:
        return GhRef(owner, repo, ("obj", _exprs(rest) if len(rest) > 1 else (rest[0],)))
    if kind in ("pull", "issues") and rest and rest[0].isdigit() and int(rest[0]) < 2**31:
        return GhRef(owner, repo, ("issue", int(rest[0])))
    if kind == "discussions" and rest and rest[0].isdigit() and int(rest[0]) < 2**31:
        return GhRef(owner, repo, ("discussion", int(rest[0])))
    if kind == "releases" and len(rest) >= 2 and rest[0] in ("tag", "download"):
        return GhRef(owner, repo, ("release", rest[1]))
    if kind == "actions" and len(rest) >= 2 and rest[0] == "workflows" and rest[1].endswith((".yml", ".yaml")):
        return GhRef(owner, repo, ("obj", (f"HEAD:.github/workflows/{rest[1]}",)))
    return GhRef(owner, repo)


def github_token() -> str | None:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def graphql_call(token: str, query: str, timeout: float = 60) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": UA, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def rest_repo(token: str, nwo: str, timeout: float = 30) -> tuple[int, str | None]:
    """(status, full_name) — REST follows a renamed repository's redirect."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{nwo}",
        headers={"Authorization": f"bearer {token}", "User-Agent": UA, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read()).get("full_name")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def _leaf_field(leaf: tuple, i: int) -> list[str]:
    kind, arg = leaf
    if kind == "obj":
        return [f"l{i}_{j}: object(expression: {json.dumps(e)}) {{ __typename }}" for j, e in enumerate(arg)]
    if kind == "issue":
        return [f"l{i}_0: issueOrPullRequest(number: {arg}) {{ __typename }}"]
    if kind == "discussion":
        return [f"l{i}_0: discussion(number: {arg}) {{ id }}"]
    if kind == "release":
        return [f"l{i}_0: release(tagName: {json.dumps(arg)}) {{ id }}"]
    return []


class GitHubChecker:
    """Answers github.com / raw.githubusercontent.com links through GraphQL in
    batches: one repository node per repo, one aliased field per thing a link
    names inside it. `call(query) -> dict` and `rest(nwo) -> (status, name)`
    are injectable so the tests need no network."""

    def __init__(self, call: Callable[[str], dict], rest: Callable[[str], tuple[int, str | None]],
                 batch: int = 80) -> None:
        self.call, self.rest, self.batch = call, rest, max(1, batch)

    def check(self, refs: dict[str, GhRef]) -> dict[str, Result]:
        repos: dict[str, set] = defaultdict(set)
        owners: set[str] = set()
        for ref in refs.values():
            if ref.repo is None:
                owners.add(ref.owner.lower())
            else:
                key = f"{ref.owner}/{ref.repo}".lower()
                repos[key]
                if ref.leaf:
                    repos[key].add(ref.leaf)
        repo_state: dict[str, tuple[str, str]] = {}   # nwo -> (status, detail)
        leaf_state: dict[tuple[str, tuple], str] = {}  # (nwo, leaf) -> ok|broken|unverified
        owner_state: dict[str, str] = {}

        units: list[tuple[str, list[tuple]]] = []
        for nwo, leaves in sorted(repos.items()):
            leaves_l = sorted(leaves, key=repr)
            if not leaves_l:
                units.append((nwo, []))
            for i in range(0, len(leaves_l), self.batch):
                units.append((nwo, leaves_l[i:i + self.batch]))
        chunks: list[list[tuple[str, list[tuple]]]] = []
        cur: list = []
        size = 0
        for unit in units:
            cost = 1 + sum(len(leaf[1]) if leaf[0] == "obj" else 1 for leaf in unit[1])
            if cur and (size + cost > self.batch or len(cur) >= 40):
                chunks.append(cur)
                cur, size = [], 0
            cur.append(unit)
            size += cost
        if cur:
            chunks.append(cur)

        def run_chunk(chunk: list[tuple[str, list[tuple]]]) -> None:
            fields = []
            for r, (nwo, leaves) in enumerate(chunk):
                owner, name = nwo.split("/", 1)
                inner = ["nameWithOwner"]
                for i, leaf in enumerate(leaves):
                    inner += _leaf_field(leaf, i)
                fields.append(f"r{r}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {' '.join(inner)} }}")
            try:
                resp = self.call("query { " + " ".join(fields) + " }")
            except Exception as exc:  # network or HTTP failure: split once, then give up on the chunk
                if len(chunk) > 1:
                    mid = len(chunk) // 2
                    run_chunk(chunk[:mid])
                    run_chunk(chunk[mid:])
                    return
                for nwo, leaves in chunk:
                    repo_state.setdefault(nwo, ("unverified", f"GitHub API: {exc}"))
                return
            data = resp.get("data") or {}
            errors = resp.get("errors") or []
            limited = any((e.get("type") or "") == "RATE_LIMITED" for e in errors)
            for r, (nwo, leaves) in enumerate(chunk):
                node = data.get(f"r{r}")
                if node is None:
                    repo_state.setdefault(nwo, ("unverified", "GitHub API rate limit") if limited else ("missing", ""))
                    continue
                repo_state[nwo] = ("ok", node.get("nameWithOwner") or nwo)
                for i, leaf in enumerate(leaves):
                    n = len(leaf[1]) if leaf[0] == "obj" else 1
                    hit = any(node.get(f"l{i}_{j}") is not None for j in range(n))
                    leaf_state[(nwo, leaf)] = "ok" if hit else "broken"

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run_chunk, chunks))

        # A repository GraphQL cannot see may have been renamed: REST follows
        # the redirect GitHub keeps for the old name.
        for nwo, (state, _) in list(repo_state.items()):
            if state == "missing":
                status, full = self.rest(nwo)
                if status == 200 and full and full.lower() != nwo:
                    repo_state[nwo] = ("moved", full)
                elif status == 200:
                    repo_state[nwo] = ("ok", full or nwo)
                elif status in (404, 451):
                    repo_state[nwo] = ("broken", "repository not found")
                else:
                    repo_state[nwo] = ("unverified", f"GitHub API answered {status or 'nothing'}")

        if owners:
            names = sorted(owners)
            for i in range(0, len(names), self.batch):
                part = names[i:i + self.batch]
                q = " ".join(f"o{j}: repositoryOwner(login: {json.dumps(n)}) {{ login }}" for j, n in enumerate(part))
                try:
                    resp = self.call("query { " + q + " }")
                    limited = any((e.get("type") or "") == "RATE_LIMITED" for e in resp.get("errors") or [])
                    data = None if limited else (resp.get("data") or {})
                except Exception:
                    data = None
                for j, n in enumerate(part):
                    owner_state[n] = "unverified" if data is None else ("ok" if data.get(f"o{j}") else "broken")

        out: dict[str, Result] = {}
        for url, ref in refs.items():
            if ref.repo is None:
                st = owner_state.get(ref.owner.lower(), "unverified")
                out[url] = Result(st, detail="" if st == "ok" else ("no such user or organization" if st == "broken" else "GitHub API unavailable"), how="github")
                continue
            nwo = f"{ref.owner}/{ref.repo}".lower()
            st, detail = repo_state.get(nwo, ("unverified", "not checked"))
            if st == "broken":
                out[url] = Result("broken", detail=f"repository {ref.owner}/{ref.repo} not found", how="github")
            elif st == "moved":
                out[url] = Result("moved", detail=f"repository renamed to {detail}", final=f"https://github.com/{detail}", how="github")
            elif st == "unverified":
                out[url] = Result("unverified", detail=detail, how="github")
            else:
                ls = "ok" if ref.leaf is None else leaf_state.get((nwo, ref.leaf), "unverified")
                renamed = detail and detail.lower() != nwo
                if ls == "ok" and renamed:
                    out[url] = Result("moved", detail=f"repository renamed to {detail}",
                                      final=f"https://github.com/{detail}", how="github")
                else:
                    out[url] = Result(ls, detail="" if ls == "ok" else _leaf_detail(ref.leaf), how="github")
        return out


def _leaf_detail(leaf: tuple) -> str:
    kind, arg = leaf
    if kind == "obj":
        expr = arg[0]
        if expr.startswith("HEAD:.github/workflows/"):
            return f"no workflow {expr.split('/')[-1]} on the default branch"
        ref, _, path = expr.partition(":")
        return f"no {path or 'commit'} at {ref}" if path else f"no commit or ref {ref}"
    if kind == "issue":
        return f"no issue or pull request #{arg}"
    if kind == "discussion":
        return f"no discussion #{arg}"
    return f"no release {arg}"


# --------------------------------------------------------------------------- #
# Live sites
# --------------------------------------------------------------------------- #


class LinkParser(HTMLParser):
    ATTRS = {"a": "href", "img": "src", "script": "src", "source": "src", "link": "href", "iframe": "src"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[int, str]] = []
        self.base: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "base" and a.get("href"):
            self.base = a["href"]
        attr = self.ATTRS.get(tag)
        if not attr or not a.get(attr):
            return
        if tag == "link" and {"preconnect", "dns-prefetch", "prefetch"} & set(a.get("rel", "").lower().split()):
            return
        self.links.append((self.getpos()[0], a[attr].strip()))


def page_links(page_url: str, body: str) -> list[tuple[int, str]]:
    parser = LinkParser()
    try:
        parser.feed(body)
    except Exception:  # malformed markup still yields what was parsed so far
        pass
    base = urllib.parse.urljoin(page_url, parser.base) if parser.base else page_url
    out = []
    for line, href in parser.links:
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")) or "{{" in href:
            continue
        absolute = urllib.parse.urljoin(base, href)
        if absolute.startswith(("http://", "https://")):
            out.append((line, urllib.parse.urldefrag(absolute)[0]))
    return out


def sitemap_pages(fetcher: Callable, site: str, timeout: float) -> list[str]:
    found: list[str] = []
    todo = [urllib.parse.urljoin(site, "sitemap.xml")]
    seen: set[str] = set()
    while todo and len(seen) < 10:
        sm = todo.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        f = fetcher(sm, "GET", timeout, read=5_000_000)
        if f.code != 200 or b"<loc>" not in f.body:
            continue
        locs = [html.unescape(m.decode("utf-8", "replace").strip()) for m in re.findall(rb"<loc>\s*([^<]+?)\s*</loc>", f.body)]
        if b"<sitemapindex" in f.body:
            todo += locs
        else:
            found += locs
    return found


def _in_site(url: str, site: str) -> bool:
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(site)
    return a.netloc.lower() == b.netloc.lower() and a.path.startswith(b.path)


def _is_page(url: str) -> bool:
    ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
    return ext in ("", ".html", ".htm")


def crawl_site(scan: Scan, site: Site, cfg: dict, gate: HostGate, fetcher: Callable = fetch) -> None:
    timeout, cap = float(cfg["timeout"]), int(cfg["max_pages"])
    label = "site " + site.url.split("://", 1)[1].rstrip("/")
    scan.sites.append(site.url)

    def get_page(url: str) -> tuple[str, Fetched]:
        host = urllib.parse.urlsplit(url).hostname or ""
        with gate(host):
            return url, fetcher(url, "GET", timeout, read=3_000_000)

    root_url, root = get_page(site.url)
    scan.results[url_key(site.url)] = classify(root)
    scan.occurrences[url_key(site.url)]  # the live site is itself a link the profile publishes
    if classify(root).status != "ok":
        return
    pages = [p for p in sitemap_pages(fetcher, site.url, timeout) if _in_site(p, site.url) and _is_page(p)]
    via_sitemap = bool(pages)
    pages = sorted(dict.fromkeys(pages), key=lambda u: (u.count("/"), u))
    queue = [p for p in pages if url_key(p) != url_key(site.url)][: max(0, cap - 1)]
    for p in queue:  # a page the sitemap lists is a link the sitemap publishes
        scan.occurrences[url_key(p)].append(Occurrence(label, urllib.parse.urljoin(site.url, "sitemap.xml")))
    done = {url_key(site.url)}
    fetched = [(site.url, root)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(cfg["workers"])) as pool:
        while True:
            for page_url, f in fetched:
                if f.code != 200 or "html" not in (f.ctype or "html"):
                    continue
                scan.pages += 1
                body = f.body.decode("utf-8", "replace")
                for line, link in page_links(f.final or page_url, body):
                    scan.add(link, Occurrence(label, page_url, line), cfg)
                    k = url_key(link)
                    if (not via_sitemap and _in_site(link, site.url) and _is_page(link)
                            and k not in done and len(done) + len(queue) < cap
                            and k not in {url_key(q) for q in queue}):
                        queue.append(link)
            batch = [q for q in queue if url_key(q) not in done]
            queue = []
            if not batch:
                break
            for q in batch:
                done.add(url_key(q))
            fetched = list(pool.map(get_page, batch))
            for page_url, f in fetched:
                scan.results.setdefault(url_key(page_url), classify(f))


# --------------------------------------------------------------------------- #
# Checking
# --------------------------------------------------------------------------- #


def load_cache(path: Path = CACHE) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict, path: Path = CACHE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=0, sort_keys=True))
    except OSError:
        pass


def check_all(scan: Scan, cfg: dict, *, use_github: bool = True, fresh: bool = False,
              cache_path: Path | None = CACHE, fetcher: Callable = fetch,
              github: GitHubChecker | None = None, progress: bool = False) -> None:
    pending = [u for u in scan.occurrences if u not in scan.results and not u.startswith("file:")]
    cache = {} if (fresh or cache_path is None) else load_cache(cache_path)
    horizon = time.time() - float(cfg.get("cache_hours") or 0) * 3600
    todo = []
    for u in pending:
        hit = cache.get(u)
        if hit and hit.get("status") == "ok" and hit.get("how") == "http" and hit.get("at", 0) >= horizon:
            scan.results[u] = Result("ok", hit.get("code"), how=hit.get("how", "http") + " (cached)")
        else:
            todo.append(u)

    gh_refs: dict[str, GhRef] = {}
    http_urls: list[str] = []
    token = github_token() if (use_github and github is None) else None
    if github is None and token:
        github = GitHubChecker(lambda q: graphql_call(token, q), lambda n: rest_repo(token, n),
                               int(cfg.get("github_batch") or 80))
    for u in todo:
        ref = parse_github(u) if github else None
        (gh_refs.__setitem__(u, ref) if ref else http_urls.append(u))
    if use_github and github is None and any(parse_github(u) for u in todo):
        scan.notes.append("no GitHub token (GH_TOKEN, GITHUB_TOKEN or `gh auth token`): github.com links were checked over HTTP and may come back unverified (429)")

    if gh_refs and github:
        if progress:
            print(f"  github: {len(gh_refs)} links in {len({(r.owner + '/' + (r.repo or '')).lower() for r in gh_refs.values()})} repos/owners …", file=sys.stderr)
        scan.results.update(github.check(gh_refs))

    gate = HostGate(int(cfg["per_host"]), HOST_LIMITS)
    http_urls = interleave(http_urls)
    timeout = float(cfg["timeout"])
    if progress and http_urls:
        print(f"  http: {len(http_urls)} links on {len({urllib.parse.urlsplit(u).hostname for u in http_urls})} hosts …", file=sys.stderr)
    def remember() -> None:
        if cache_path is None:
            return
        now = time.time()
        for u, r in list(scan.results.items()):
            if r.status == "ok" and r.how == "http":
                cache[u] = {"status": "ok", "code": r.code, "how": r.how, "at": now}
        save_cache(cache, cache_path)

    remember()  # the GitHub answers, before the long HTTP tail
    done, started = 0, time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(cfg["workers"])) as pool:
        futs = {pool.submit(check_http, u, gate, timeout, fetcher): u for u in http_urls}
        for fut in concurrent.futures.as_completed(futs):
            scan.results[futs[fut]] = fut.result()
            done += 1
            if done % 1000 == 0:
                remember()
                if progress:
                    print(f"    {done}/{len(http_urls)} in {time.time() - started:.0f}s", file=sys.stderr)
    remember()


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


def display(key: str, occ: Occurrence | None = None) -> str:
    if key.startswith("file:"):
        return occ.target if occ and occ.target else key.split(":", 2)[2]
    return key


def summarize(scan: Scan) -> dict:
    counts = Counter(r.status for k, r in scan.results.items() if k in scan.occurrences)
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for key, occs in scan.occurrences.items():
        res = scan.results.get(key)
        if not res or res.status == "ok":
            continue
        per_repo: dict[str, list[Occurrence]] = defaultdict(list)
        for o in occs:
            per_repo[o.repo].append(o)
        if not per_repo:  # a live site root nobody's file names
            per_repo["live sites"] = []
        for repo, os_ in per_repo.items():
            by_repo[repo].append({
                "url": display(key, os_[0] if os_ else None),
                **res.as_dict(),
                "sources": [o.label() for o in os_],
            })
    for rows in by_repo.values():
        rows.sort(key=lambda r: (STATUSES.index(r["status"]), r["url"]))
    return {
        "schema": "link-check/v1",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repos": scan.repos,
        "sites": scan.sites,
        "files": scan.files,
        "pages": scan.pages,
        "links": len(scan.occurrences),
        "counts": {s: counts.get(s, 0) for s in STATUSES},
        "skipped": dict(scan.skipped),
        "notes": scan.notes,
        "problems": dict(sorted(by_repo.items())),
    }


MARK = {"broken": "✗", "error": "!", "unverified": "?", "moved": "→"}


def render_text(report: dict, show: Iterable[str] = ("broken", "error", "moved"), max_sources: int = 5) -> str:
    c = report["counts"]
    lines = [
        f"links: {report['links']:,} unique from {report['files']:,} files in {len(report['repos'])} repos"
        + (f" and {report['pages']:,} pages of {len(report['sites'])} live sites" if report["sites"] else ""),
        "  " + " · ".join(f"{s} {c[s]:,}" for s in STATUSES)
        + (f" · (not links: {sum(report['skipped'].values()):,} placeholder/local/example)" if report["skipped"] else ""),
    ]
    lines += [f"  note: {n}" for n in report["notes"]]
    show = set(show)
    for repo, rows in report["problems"].items():
        rows = [r for r in rows if r["status"] in show]
        if not rows:
            continue
        lines.append("")
        lines.append(f"{repo}  ({len(rows)})")
        for r in rows:
            detail = r.get("detail") or (f"HTTP {r['code']}" if r.get("code") else r["status"])
            lines.append(f"  {MARK.get(r['status'], ' ')} {r['url']} — {detail}")
            src = r["sources"]
            if src:
                more = f" (+{len(src) - max_sources} more)" if len(src) > max_sources else ""
                lines.append("      " + " · ".join(src[:max_sources]) + more)
    hidden = {s: c[s] for s in STATUSES if s not in show and s != "ok" and c[s]}
    if hidden:
        lines.append("")
        lines.append("not listed: " + ", ".join(f"{n} {s}" for s, n in hidden.items()) + " (--show to list them, or --json)")
    return "\n".join(lines)


def render_markdown(report: dict, show: Iterable[str] = ("broken", "error", "moved"), max_sources: int = 5,
                    max_rows: int = 40) -> str:
    """The report as Markdown, at most `max_rows` links per repo: a job summary
    is capped at 1 MiB, and the full list is the JSON report's job."""
    c = report["counts"]
    out = [
        "## Fleet link check",
        "",
        f"{report['links']:,} unique links from {report['files']:,} files in {len(report['repos'])} repos"
        + (f" and {report['pages']:,} pages of {len(report['sites'])} live sites" if report["sites"] else "") + ".",
        "",
        "| " + " | ".join(STATUSES) + " |",
        "| " + " | ".join("---:" for _ in STATUSES) + " |",
        "| " + " | ".join(f"{c[s]:,}" for s in STATUSES) + " |",
        "",
    ]
    out += [f"> {n}" for n in report["notes"]]
    show = set(show)
    for repo, rows in report["problems"].items():
        rows = [r for r in rows if r["status"] in show]
        if not rows:
            continue
        out += ["", f"### {repo} ({len(rows)})", "", "| | Link | Why | Where |", "| --- | --- | --- | --- |"]
        for r in rows[:max_rows]:
            detail = (r.get("detail") or (f"HTTP {r['code']}" if r.get("code") else r["status"])).replace("|", "\\|")
            src = r["sources"]
            where = ", ".join(f"`{s}`" for s in src[:max_sources]) + (f" +{len(src) - max_sources}" if len(src) > max_sources else "")
            out.append(f"| {MARK.get(r['status'], '')} | {r['url'].replace('|', '%7C')} | {detail} | {where} |")
        if len(rows) > max_rows:
            out += ["", f"… and {len(rows) - max_rows} more: the full list is in the JSON report (`--json`, the `link-check` artifact)."]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def cmd_scan(args: argparse.Namespace, cfg: dict) -> int:
    root = Path(args.root).resolve()
    repos, sites = targets(root, cfg, args.repo)
    if args.repo and not repos and not sites:
        print(f"link_check: no repo or live site named {', '.join(args.repo)}", file=sys.stderr)
        return 2
    if args.max_pages is not None:
        cfg["max_pages"] = args.max_pages
    scan = Scan()
    if not args.no_repos:
        print(f"reading {len(repos)} repos …", file=sys.stderr)
        scan_repos(scan, repos, cfg, TrackedIndex())
    if not args.no_sites and sites:
        print(f"crawling {len(sites)} live sites (≤ {cfg['max_pages']} pages each) …", file=sys.stderr)
        gate = HostGate(int(cfg["per_host"]), HOST_LIMITS)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda s: crawl_site(scan, s, cfg, gate), sites))
    print(f"checking {len(scan.occurrences):,} unique links …", file=sys.stderr)
    check_all(scan, cfg, use_github=not args.no_github_api, fresh=args.fresh, progress=True)
    return finish(scan, args)


def cmd_url(args: argparse.Namespace, cfg: dict) -> int:
    scan = Scan()
    for u in args.urls:
        scan.occurrences[url_key(u)].append(Occurrence("command line", u))
    check_all(scan, cfg, use_github=not args.no_github_api, fresh=True, cache_path=None)
    for u in args.urls:
        r = scan.results[url_key(u)]
        extra = f" — {r.detail}" if r.detail else ""
        final = f" → {r.final}" if r.final and r.final.rstrip("/") != u.rstrip("/") else ""
        print(f"{r.status:10} {r.code or '':>3} {u}{extra}{final}  [{r.how}]")
    return 1 if any(scan.results[url_key(u)].status == "broken" for u in args.urls) else 0


def cmd_targets(args: argparse.Namespace, cfg: dict) -> int:
    repos, sites = targets(Path(args.root).resolve(), cfg, args.repo)
    print(f"repos ({len(repos)}):")
    for r in repos:
        print(f"  {r.name:28} {r.nwo:40} {r.path}")
    print(f"live sites ({len(sites)}):")
    for s in sites:
        print(f"  {s.label:28} {s.url}")
    return 0


def finish(scan: Scan, args: argparse.Namespace) -> int:
    report = summarize(scan)
    show = tuple(args.show.split(",")) if args.show else ("broken", "error", "moved")
    print(render_text(report, show))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    if args.markdown:
        with open(args.markdown, "a" if args.markdown == os.environ.get("GITHUB_STEP_SUMMARY") else "w") as fh:
            fh.write(render_markdown(report, show))
    c = report["counts"]
    if args.fail_on == "never":
        return 0
    bad = c["broken"] + (c["error"] if args.fail_on == "error" else 0)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("scan", "url", "targets", "-h", "--help"):
        argv.insert(0, "scan")
    p = argparse.ArgumentParser(prog="link_check.py", description="The fleet's link check: every link the fleet publishes, checked once (docs/LINK-CHECK.md).")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(HUB), help="the hub checkout to read (default: this one)")
    common.add_argument("--repo", action="append", default=[], help="registry name; repeat for several (default: the whole fleet)")
    common.add_argument("--no-github-api", action="store_true", help="check github.com over plain HTTP")
    s = sub.add_parser("scan", parents=[common], help="scan the fleet (default)")
    s.add_argument("--no-sites", action="store_true", help="skip crawling the live sites")
    s.add_argument("--no-repos", action="store_true", help="skip the repos' files")
    s.add_argument("--max-pages", type=int, help="pages per live site (default: links.max_pages)")
    s.add_argument("--fresh", action="store_true", help="ignore the cache of recent ok answers")
    s.add_argument("--show", help="statuses to list (default broken,error,moved; add unverified)")
    s.add_argument("--json", help="write the full report as JSON (link-check/v1)")
    s.add_argument("--markdown", help="write the report as Markdown (e.g. $GITHUB_STEP_SUMMARY)")
    s.add_argument("--fail-on", choices=("broken", "error", "never"), default="broken")
    u = sub.add_parser("url", parents=[common], help="check these URLs only")
    u.add_argument("urls", nargs="+")
    sub.add_parser("targets", parents=[common], help="list the repos and live sites a scan reads")
    args = p.parse_args(argv)
    cfg = load_config()
    return {"scan": cmd_scan, "url": cmd_url, "targets": cmd_targets}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""stargazer — the open-source radar (`tools/dash stars`; docs/STARGAZER.md).

Reads GitHub for the account's stars, its public star lists, every fleet repo's
topics, the repos rising in the fleet's topics and the repos most like each
fleet project, then writes the committed public document `_data/stars.json`
(schema stars/v1) and the star history `_data/stars_history.json`. The model —
categories, matches, velocities, suspect flags, the incorporate list, the feed
and the session brief — is `tools/fleetcore/stars.py`; this file only reads,
writes and prints.

    tools/dash stars                         the summary (the same as `summary`)
    tools/dash stars refresh [--dry-run]     read GitHub, write both files
    tools/dash stars starred [--q T] [--category C] [--language L] [--project P]
    tools/dash stars trending | incorporate [--project P] | feed | gaining
    tools/dash stars similar <project>       one fleet project's matches
    tools/dash stars show <owner/repo>       one repo, every field
    tools/dash stars brief [--project P | --cwd DIR]   the session brief
    tools/dash stars hook [--install --yes]  the user-level SessionStart hook

Every read command takes --json and --limit. A refresh needs a token (GH_TOKEN,
GITHUB_TOKEN or `gh auth token`); it reads public data only, and a private
repository or star list never reaches the document. Read-only on GitHub, $0.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from fleetcore import stars  # noqa: E402

DOC = ROOT / "_data" / "stars.json"
HISTORY = ROOT / "_data" / "stars_history.json"
UA = "bamr87-stargazer"
GRAPHQL = "https://api.github.com/graphql"
REPO_BATCH = 25     # repository(...) fields per query
SEARCH_BATCH = 6    # search(...) fields per query
STAR_PAGE = 50      # stars per page: 100 with every topic and release is heavy enough for GitHub to answer 502
RETRY_WAITS = (2, 6)  # seconds before the second and third attempt at a 5xx or a dropped connection


class GhError(RuntimeError):
    pass


def _yaml(path: Path):
    import yaml  # PyYAML: only the commands that need the registry import it
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def fleet_yml() -> dict:
    doc = _yaml(ROOT / "_data" / "fleet.yml")
    return doc if isinstance(doc, dict) else {}


def registry() -> list[dict]:
    doc = _yaml(ROOT / "_data" / "projects.yml")
    return [p for p in doc or [] if isinstance(p, dict)] if isinstance(doc, list) else []


def token() -> str | None:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
class GitHub:
    """GraphQL with a wall clock: every call checks the budget first, a 5xx or a dropped connection is tried
    three times, and a partial answer keeps its data with the errors noted."""

    def __init__(self, tok: str, budget_s: float = 240, timeout: float = 45):
        self.tok, self.deadline, self.timeout = tok, time.monotonic() + budget_s, timeout
        self.calls, self.notes = 0, []

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def call(self, query: str, variables: dict | None = None) -> dict:
        if self.left() <= 0:
            raise GhError("the refresh budget ran out")
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        waits = list(RETRY_WAITS)
        while True:
            req = urllib.request.Request(GRAPHQL, data=body, method="POST", headers={
                "Authorization": f"bearer {self.tok}", "User-Agent": UA, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=min(self.timeout, max(5.0, self.left()))) as resp:
                    out = json.loads(resp.read())
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (502, 503, 504) and waits and self.left() > waits[0]:
                    time.sleep(waits.pop(0))
                    continue
                raise GhError(f"GitHub answered {exc.code}") from None
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if waits and self.left() > waits[0]:
                    time.sleep(waits.pop(0))
                    continue
                raise GhError(f"GitHub did not answer: {type(exc).__name__}") from None
        self.calls += 1
        errs = [str(e.get("message") or e)[:200] for e in out.get("errors") or [] if isinstance(e, dict)]
        if not out.get("data"):
            raise GhError("; ".join(errs) or "an empty answer")
        self.notes += [e for e in errs if "Could not resolve to a Repository" not in e]
        return out["data"]


def fetch_starred(gh: GitHub, login: str, cap: int, opts: dict) -> tuple[list[dict], int]:
    q = """query($login: String!, $after: String) { user(login: $login) {
      starredRepositories(first: %d, after: $after, orderBy: {field: STARRED_AT, direction: DESC}) {
        totalCount pageInfo { hasNextPage endCursor } edges { starredAt node { %s } } } } }""" % (STAR_PAGE, stars.REPO_FIELDS)
    out, after, total = [], None, 0
    while len(out) < cap:
        data = gh.call(q, {"login": login, "after": after})
        conn = ((data.get("user") or {}).get("starredRepositories")) or {}
        if not data.get("user"):
            raise GhError(f"no GitHub user {login}")
        total = int(conn.get("totalCount") or 0)
        for e in conn.get("edges") or []:
            rec = stars.from_graphql((e or {}).get("node"), **opts)
            if rec:
                out.append({"starred_at": e.get("starredAt"), "repo": rec})
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
    return out[:cap], total


def fetch_lists(gh: GitHub, login: str) -> list[dict]:
    q = """query($login: String!) { user(login: $login) { lists(first: 50) { nodes {
      name slug description isPrivate items(first: 100) { nodes { ... on Repository { nameWithOwner } } } } } } }"""
    data = gh.call(q, {"login": login})
    out = []
    for n in (((data.get("user") or {}).get("lists") or {}).get("nodes") or []):
        if not n or n.get("isPrivate"):
            continue
        out.append({"name": n.get("name"), "slug": n.get("slug"), "description": n.get("description"),
                    "repos": [i["nameWithOwner"] for i in (n.get("items") or {}).get("nodes") or [] if i and i.get("nameWithOwner")]})
    return out


def fetch_repos(gh: GitHub, nwos: list[str], opts: dict) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    todo = [n for n in dict.fromkeys(nwos) if stars.NWO_RX.match(n)]
    for i in range(0, len(todo), REPO_BATCH):
        chunk = todo[i:i + REPO_BATCH]
        fields = " ".join(f"r{j}: repository(owner: {json.dumps(n.split('/')[0])}, name: {json.dumps(n.split('/')[1])}) "
                          f"{{ {stars.REPO_FIELDS} }}" for j, n in enumerate(chunk))
        data = gh.call(f"query {{ {fields} }}")
        for j, n in enumerate(chunk):
            out[n] = stars.from_graphql(data.get(f"r{j}"), **opts)
    return out


def search(gh: GitHub, queries: list[tuple[str, str]], first: int, opts: dict) -> dict[str, tuple[int, list[dict]]]:
    out: dict[str, tuple[int, list[dict]]] = {}
    for i in range(0, len(queries), SEARCH_BATCH):
        chunk = queries[i:i + SEARCH_BATCH]
        fields = " ".join(f"s{j}: search(query: {json.dumps(q)}, type: REPOSITORY, first: {int(first)}) "
                          f"{{ repositoryCount nodes {{ ... on Repository {{ {stars.REPO_FIELDS} }} }} }}"
                          for j, (_, q) in enumerate(chunk))
        data = gh.call(f"query {{ {fields} }}")
        for j, (key, _) in enumerate(chunk):
            s = data.get(f"s{j}") or {}
            recs = [r for r in (stars.from_graphql(n, **opts) for n in s.get("nodes") or []) if r]
            out[key] = (int(s.get("repositoryCount") or 0), recs)
    return out


# --------------------------------------------------------------------------- #
# the refresh
# --------------------------------------------------------------------------- #
def _from_doc(prev: dict | None, names: list[str]) -> list[dict]:
    repos = (prev or {}).get("repos") or {}
    return [repos[n] for n in names if n in repos]


def collect(gh: GitHub, fleet: dict, reg: list[dict], *, now: datetime, prev: dict | None = None,
            trending: bool = True, discover: bool = True, log=print) -> dict:
    """The raw records `stars.build()` takes. The stars must read; any later phase that fails keeps the last
    document's answer for that phase and says so in `errors`."""
    cfg = stars.config(fleet)
    opts = {"description_chars": int(cfg["description_chars"]), "max_topics": int(cfg["max_topics"])}
    login = cfg["account"]
    raw: dict = {"account": login, "errors": [], "projects": {}, "trending": [], "discovered": {}}

    starred, total = fetch_starred(gh, login, int(cfg["max_starred"]), opts)
    raw["starred"], raw["starred_total"] = starred, total
    log(f"stars: {len(starred)} of {total} read")

    try:
        raw["lists"] = fetch_lists(gh, login)
        log(f"lists: {len(raw['lists'])} public")
    except GhError as exc:
        raw["lists"] = [{**lst} for lst in (prev or {}).get("lists") or []]
        raw["errors"].append(f"star lists not read ({exc}); the last document's kept")

    hub_repo = str((fleet.get("hub") or {}).get("repo") or "bamr87/bamr87")
    projects = stars.fleet_projects(reg, hub_repo, cfg)
    try:
        side = fetch_repos(gh, [p["repo"] for p in projects if p.get("repo")], opts)
        raw["projects"] = {p["name"]: side.get(p["repo"]) for p in projects if p.get("repo")}
        log(f"fleet repos: {sum(1 for v in raw['projects'].values() if v)} of {len(raw['projects'])} read")
    except GhError as exc:
        raw["errors"].append(f"fleet repos' topics not read ({exc}); matched on the registry alone")

    if trending:
        tq = stars.trending_queries(projects, raw["projects"], cfg, now)
        try:
            found = search(gh, [(t["id"], t["q"]) for t in tq], int(cfg["trending"]["per_query"]), opts)
            raw["trending"] = [{**t, "count": found.get(t["id"], (0, []))[0], "repos": found.get(t["id"], (0, []))[1]}
                               for t in tq]
            log(f"trending: {len(tq)} queries, {sum(len(t['repos']) for t in raw['trending'])} repos")
        except GhError as exc:
            raw["trending"] = [{**t, "q": t.get("query"), "repos": _from_doc(prev, t.get("repos") or [])}
                               for t in (prev or {}).get("trending") or []]
            raw["errors"].append(f"trending not read ({exc}); the last document's kept")

    if discover:
        dq = stars.discover_queries(projects, raw["projects"], cfg, now)
        per = int(cfg["discover"]["per_project"])
        try:
            found = search(gh, [(d["project"], d["q"]) for d in dq], per, opts)
            thin = [(d["project"], d["fallback"]) for d in dq if d.get("fallback") and len(found.get(d["project"], (0, []))[1]) < 3]
            if thin:
                wide = search(gh, thin, per, opts)
                for k, (n, recs) in wide.items():
                    have = {r["name"] for r in found.get(k, (0, []))[1]}
                    found[k] = (n, [*found.get(k, (0, []))[1], *(r for r in recs if r["name"] not in have)][:per])
            raw["discovered"] = {k: v[1] for k, v in found.items()}
            log(f"discover: {len(dq)} projects (+{len(thin)} widened), "
                f"{sum(len(v) for v in raw['discovered'].values())} repos")
        except GhError as exc:
            prev_fleet = {f["project"]: f for f in (prev or {}).get("fleet") or []}
            raw["discovered"] = {k: _from_doc(prev, list(f.get("discovered") or [])) for k, f in prev_fleet.items()}
            raw["errors"].append(f"discovery not read ({exc}); the last document's kept")
    raw["errors"] += [f"GitHub: {n}" for n in dict.fromkeys(gh.notes)][:10]
    return raw


def refresh(args) -> int:
    tok = token()
    if not tok:
        print("stars refresh: no GitHub token (GH_TOKEN, GITHUB_TOKEN or `gh auth login`)", file=sys.stderr)
        return 2
    fleet, reg = fleet_yml(), registry()
    now = datetime.now(timezone.utc)
    prev = stars.load(DOC)
    try:
        hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hist = None
    gh = GitHub(tok, budget_s=args.budget)
    started = time.monotonic()
    try:
        raw = collect(gh, fleet, reg, now=now, prev=prev, trending=not args.no_trending, discover=not args.no_discover,
                      log=lambda m: print(f"  {m}", file=sys.stderr))
    except GhError as exc:
        print(f"stars refresh: {exc}; nothing written", file=sys.stderr)
        return 1
    doc, nxt = stars.build(raw, registry=reg, fleet=fleet, history=hist, now=now)
    t = doc["totals"]
    print(f"stars refresh: {t['starred']} starred, {t['trending']} trending, {t['repos']} repos on the radar, "
          f"{t['relevant']} relevant to the fleet, {t['incorporate']} to review, {t['suspect']} suspect — "
          f"{gh.calls} GraphQL calls in {time.monotonic() - started:.1f}s")
    for e in doc["errors"]:
        print(f"  note: {e}", file=sys.stderr)
    if args.dry_run:
        print("  dry run: nothing written")
        return 0
    DOC.write_text(stars.dump(doc), encoding="utf-8")
    HISTORY.write_text(stars.dump_history(nxt), encoding="utf-8")
    print(f"  wrote {_rel(DOC)} and {_rel(HISTORY)}")
    return 0


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _need_doc() -> dict:
    doc = stars.load(DOC)
    if not doc:
        print(f"no radar yet: {_rel(DOC)} is missing — run `tools/dash stars refresh`", file=sys.stderr)
        raise SystemExit(1)
    return doc


def _k(n) -> str:
    return stars._k(n)


def _row(r: dict, extra: str = "") -> str:
    v = r.get("velocity") or {}
    d7 = f"+{v['d7']}" if v.get("d7") else ""
    flag = " ⚠ suspect" if r.get("suspect") else ""
    return (f"  {r.get('name', ''):<44} ★{_k(r.get('stars')):>6} {d7:>6}  {str(r.get('language') or '—'):<12} "
            f"{str(r.get('category') or ''):<9} {extra}{flag}")


def print_summary(d: dict) -> None:
    t = d.get("totals") or {}
    print(f"Open-source radar — {d.get('account')} · {d.get('generated_at')} ({d.get('age_days')}d old)")
    print(f"  {t.get('starred')} starred ({t.get('starred_relevant')} relevant to the fleet) · {t.get('trending')} trending · "
          f"{t.get('incorporate')} to review · {t.get('suspect')} suspect · {t.get('lists')} lists")
    print("  categories: " + ", ".join(f"{c['title']} {c['starred']}" for c in d.get("categories") or [] if c.get("starred")))
    print("  languages:  " + ", ".join(f"{x['name']} {x['count']}" for x in d.get("languages") or []))
    print("Recently starred:")
    for r in d.get("recent") or []:
        print(_row(r, str(r.get("starred_at") or "")[:10]))
    print("To review for the fleet:")
    for i in d.get("incorporate") or []:
        print(f"  {i['repo']:<44} → {i['project']:<18} {i['why']}")
    for e in d.get("errors") or []:
        print(f"  note: {e}")


def read_cmd(args) -> int:
    doc = _need_doc()
    kind = {"similar": "fleet", "show": "repo", "summary": "summary"}.get(args.cmd, args.cmd)
    project = getattr(args, "project", "") or (args.name if args.cmd == "similar" else "")
    q = args.name if args.cmd == "show" else getattr(args, "q", "")
    try:
        out = stars.query(doc, kind=kind, q=q or "", category=getattr(args, "category", "") or "",
                          language=getattr(args, "language", "") or "", project=project or "", limit=args.limit)
    except ValueError as exc:
        print(f"stars {args.cmd}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0
    if kind == "summary":
        print_summary(out)
    elif kind in ("starred", "gaining"):
        for r in out["repos"]:
            print(_row(r, str(r.get("starred_at") or "")[:10]))
        if kind == "starred":
            print(f"  {out['total']} match")
    elif kind == "trending":
        for t in out["queries"]:
            print(f"{t['title']}  ({t['query']})")
            for r in t["repos"]:
                per = (r.get("velocity") or {}).get("per_day")
                print(_row(r, f"{per}★/day" if per else ""))
    elif kind == "incorporate":
        for i in out["items"]:
            print(f"  {i['repo']:<44} → {i['project']:<18} {i['score']:.2f}  {i['why']}{'  (starred)' if i['starred'] else ''}")
    elif kind == "fleet":
        for f in out["projects"]:
            print(f"{f['project']}  ({', '.join(f['terms'][:6])})")
            for label in ("starred", "discovered"):
                for m in f[label]:
                    print(f"  {label:<10} {m['repo']:<44} {m['score']:.2f}  {', '.join(m['shared'])}")
    elif kind == "feed":
        for e in out["feed"]:
            print(f"  {str(e['at'])[:10]}  {e['kind']:<8} {e['text']}")
    else:
        print(json.dumps(out["repo"], indent=1, ensure_ascii=False))
    return 0


def brief_cmd(args) -> int:
    doc = stars.load(DOC)
    if not doc:
        return 0
    project = args.project or stars.project_for(args.cwd or os.getcwd(), doc.get("fleet") or [], ROOT)
    text = stars.brief(doc, project)
    if text:
        print(text)
    return 0


# --------------------------------------------------------------------------- #
# the user-level hook: every local session, not only the hub's
# --------------------------------------------------------------------------- #
HOOK = ROOT / ".claude" / "hooks" / "stars_session_start.py"


def hook_cmd(args) -> int:
    """The hub's own sessions get the brief from .claude/settings.json. A session anywhere else (a submodule
    opened on its own, a worktree, another clone) gets it only from a user-level SessionStart hook in
    ~/.claude/settings.json, which this adds — a change to the operator's machine, so it asks first."""
    path = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    command = f'python3 "{HOOK}" --user'
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError) as exc:
        print(f"stars hook: {path} does not parse ({exc}); not touched", file=sys.stderr)
        return 1
    entries = ((settings.get("hooks") or {}).get("SessionStart") or [])
    present = any(str(h.get("command") or "").endswith("stars_session_start.py\" --user")
                  for e in entries if isinstance(e, dict) for h in e.get("hooks") or [] if isinstance(h, dict))
    print(f"user settings: {path}")
    print(f"hook command:  {command}")
    print(f"installed:     {'yes' if present else 'no'}")
    if present or not args.install:
        if not present:
            print("add it with: tools/dash stars hook --install --yes")
        return 0
    if not args.yes:
        print("dry run: add --yes to write it")
        return 0
    settings.setdefault("hooks", {}).setdefault("SessionStart", []).append(
        {"hooks": [{"type": "command", "command": command}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    print("installed: every new local Claude Code session starts with the radar brief")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/dash stars", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    def reader(name: str, help_: str, *, filters: bool = False, positional: str | None = None):
        p = sub.add_parser(name, help=help_)
        if positional:
            p.add_argument("name", help=positional)
        if filters:
            p.add_argument("--q", default="", help="words that must all appear in the name, description or topics")
            p.add_argument("--category", default="")
            p.add_argument("--language", default="")
        p.add_argument("--project", default="", help="only repos matched to this fleet project")
        p.add_argument("--limit", type=int, default=20)
        p.add_argument("--json", action="store_true")
        return p

    reader("summary", "totals, categories, the newest stars, what to review")
    reader("starred", "starred repos, newest first", filters=True)
    reader("trending", "repos rising this week, this month and in the fleet's topics", filters=True)
    reader("incorporate", "what fleet projects should review")
    reader("feed", "stars, releases, newcomers and spikes, newest first")
    reader("gaining", "starred repos gaining the most stars this week")
    reader("similar", "one fleet project's matches", positional="fleet project (registry name, or bamr87 for the hub)")
    reader("show", "one repo, every field", positional="owner/repo")
    r = sub.add_parser("refresh", help="read GitHub and write _data/stars.json + _data/stars_history.json")
    r.add_argument("--dry-run", action="store_true", help="read and build, write nothing")
    r.add_argument("--no-trending", action="store_true")
    r.add_argument("--no-discover", action="store_true")
    r.add_argument("--budget", type=float, default=240, help="wall clock in seconds (default 240)")
    b = sub.add_parser("brief", help="the text a local Claude Code session starts with")
    b.add_argument("--project", default="")
    b.add_argument("--cwd", default="")
    h = sub.add_parser("hook", help="the user-level SessionStart hook for sessions outside the hub")
    h.add_argument("--install", action="store_true")
    h.add_argument("--yes", action="store_true")

    args = ap.parse_args(argv)
    if not args.cmd:
        args = ap.parse_args(["summary", *(argv or [])])
    if args.cmd == "refresh":
        return refresh(args)
    if args.cmd == "brief":
        return brief_cmd(args)
    if args.cmd == "hook":
        return hook_cmd(args)
    return read_cmd(args)


if __name__ == "__main__":
    sys.exit(main())

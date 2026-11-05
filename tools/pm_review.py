#!/usr/bin/env python3
# ============================================================================
# File:          tools/pm_review.py
# Description:   The fleet's routine PM review (docs/PM.md). Reads every open issue and pull
#                request of the registry repos, their recent comments, pull-request state, releases
#                and the Fleet project's items, and aligns them with three records: the Fleet
#                project (constitution § 9, § 10), the roadmap (_data/roadmap.yml) and each repo's
#                release train (docs/RELEASES.md). It reports what is out of line and plans the
#                fix: Fleet project ops as a preview `tools/dash projects apply` takes (§ 11: plan,
#                show, confirm), roadmap status edits for the working tree, and the release train.
# Usage:         python3 tools/pm_review.py review [--from MODEL.json] [--repo OWNER/NAME]… [--write]
#                python3 tools/pm_review.py plan | roadmap [--write] | releases | status
#                (or tools/dash pm <review|plan|roadmap|releases|status> …)
# Exit:          0 clean · 1 failed · 2 usage
# Never:         writes to GitHub. Every call here is a GET or a GraphQL query; the only writer is
#                the § 11 service, reached through `tools/dash projects apply FILE --confirm`.
# ============================================================================
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import projects_backfill as pb  # noqa: E402

gp, gw = pb.gp, pb.gw

FLEET = ROOT / "_data" / "fleet.yml"
ROADMAP = ROOT / "_data" / "roadmap.yml"
SNAPSHOT = ROOT / "_data" / "pm_review.yml"
OUT_DIR = ROOT / ".fleet" / "pm"
DASH_GEN = ROOT / ".github" / "scripts" / "dash-gen"
SCHEMA = "pm-review/v1"
MODEL_SCHEMA = "pm-review-model/v1"
LANES = ("project", "roadmap", "release", "hygiene")
SEVERITIES = ("high", "medium", "low", "info")
BOARD_MAX_ITEMS = 2000
HISTORY_KEEP = 30

# Everything tunable lives in _data/fleet.yml `pm:`; these are the values a missing key falls back to.
DEFAULTS: dict[str, Any] = {
    "project": {"owner": "bamr87", "number": 14},
    "lanes": list(LANES),
    "scope": {"skip_statuses": ["archived"]},
    "board": {
        # the framework's option name -> the live project's, where the two differ
        "aliases": {"Triaged": "Triage", "Blocked": "Hold"},
        # a Status a person set on purpose: the review never plans over it
        "held": ["Needs Amr", "Hold", "Blocked", "Won't do"],
        "early": ["Inbox", "Triage", "Triaged", "Ready"],
        # pull-request state the project mirrors, where it has the field and the option (#588)
        "mirror_fields": ["CI", "Merge state"],
    },
    "thresholds": {
        "stale_in_progress_days": 14,
        "pr_idle_days": 14,
        "release_pr_waiting_days": 7,
        "unreleased_commits": 5,
        "proposed_aging_days": 30,
    },
    "comments": {"lookback_days": 2},
    "release": {"engines": {}},
    "snapshot": {"max_findings": 150, "max_per_kind": 20},
}

SEVERITY = {
    "gate_not_mirrored": "high", "release_blocked": "high",
    "untracked": "medium", "status_missing": "medium", "priority_missing": "medium", "stale_in_progress": "medium",
    "epic_complete": "medium", "roadmap_shipped": "medium", "roadmap_unlinked": "medium",
    "release_pr_waiting": "medium", "pr_conflicting": "medium", "pr_ci_red": "medium", "awaiting_reply": "medium",
    "closed_not_done": "low", "status_behind": "low", "pr_state_not_mirrored": "low", "priority_conflict": "low", "done_but_open": "low",
    "roadmap_started": "low", "roadmap_declined": "low", "roadmap_untracked_epic": "low",
    "roadmap_priority_drift": "low", "release_unreleased": "low", "pr_changes_requested": "low", "pr_idle": "low",
    "unlabelled": "low", "board_unregistered": "info", "board_unreadable": "info", "option_missing": "info",
    "roadmap_proposed_aging": "info", "repo_unreachable": "info",
}
PRS_Q = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){
 pullRequests(states:OPEN,first:$n,orderBy:{field:UPDATED_AT,direction:DESC}){ nodes{
  number isDraft mergeable mergeStateStatus reviewDecision headRefName
  closingIssuesReferences(first:10){ nodes{ number repository{ nameWithOwner } } }
  commits(last:1){ nodes{ commit{ statusCheckRollup{ state } } } } } } } }"""
CC_RX = re.compile(r"^(?P<type>[a-zA-Z]+)(\([^)]*\))?(?P<bang>!)?:\s")
RELEASE_TITLE_RX = re.compile(r"^chore(\([^)]*\))?: release\b", re.I)
ISSUE_URL_RX = re.compile(r"github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)")
PRIORITY_LABELS = ("P0", "P1", "P2", "P3")
CI_OPTION = {"SUCCESS": "Green", "FAILURE": "Red", "ERROR": "Red", "PENDING": "Pending", "EXPECTED": "Pending"}
MERGE_OPTION = {"CLEAN": "Clean", "HAS_HOOKS": "Clean", "UNSTABLE": "Clean", "DIRTY": "Conflicting", "BEHIND": "Behind",
                "BLOCKED": "Blocked"}
TYPE_LABELS = ("bug", "feature", "chore", "docs", "ci", "refactor", "test")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str | None) -> datetime | None:
    try:
        return datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def days_since(text: str | None, now: datetime) -> int | None:
    dt = parse_iso(text)
    return None if dt is None else max(0, (now - dt).days)


def merged(base: dict, over: dict | None) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merged(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_fleet(path: Path = FLEET) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except OSError:
        return {}


def load_config(fleet: dict | None = None) -> dict:
    return merged(DEFAULTS, (fleet if fleet is not None else load_fleet()).get("pm"))


# --------------------------------------------------------------------------- scope
def fleet_scope(fleet: dict, registry: list[dict], cfg: dict) -> list[dict]:
    """The hub plus every registry repo an owner of the fleet holds. Upstream mirrors
    (an owner outside `hub.owners`) and the statuses the config skips are left out."""
    hub = fleet.get("hub") or {}
    hub_repo = hub.get("repo", "bamr87/bamr87")
    owners = {str(o).lower() for o in hub.get("owners") or [hub_repo.split("/")[0]]}
    skip = set((cfg.get("scope") or {}).get("skip_statuses") or [])
    rows = [{"repo": hub_repo, "name": "hub", "branch": hub.get("default_branch", "main"), "status": "active",
             "hub": True, "registry_release": {}}]
    seen = {hub_repo.lower()}
    for r in registry if isinstance(registry, list) else []:
        m = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", str(r.get("repo_url") or ""))
        if not m:
            continue
        nwo = m.group(1)
        if nwo.lower() in seen or nwo.split("/")[0].lower() not in owners or r.get("status") in skip:
            continue
        seen.add(nwo.lower())
        rows.append({"repo": nwo, "name": r.get("name") or nwo.split("/")[1], "branch": r.get("branch") or "main",
                     "status": r.get("status"), "hub": False, "registry_release": r.get("release") or {}})
    return rows


# --------------------------------------------------------------------------- gather (GETs and queries only)
def open_items(gh: pb.Gh, repo: str) -> list[dict]:
    """Every open issue and pull request of a repo, in the shape pb.derive_fields() reads, plus
    what the review needs on top (author, dates, comment count, milestone)."""
    out: list[dict] = []
    for page in range(1, pb.MAX_PAGES + 1):
        rows = gh.get(f"repos/{repo}/issues", state="open", per_page=pb.PAGE, page=page) or []
        for r in rows:
            out.append({"repo": repo, "number": int(r["number"]), "node_id": r.get("node_id"), "title": r.get("title", ""),
                        "state": "open", "labels": [l["name"] for l in r.get("labels") or []],
                        "kind": "pr" if r.get("pull_request") is not None else "issue", "draft": bool(r.get("draft")),
                        "author": (r.get("user") or {}).get("login"), "created_at": r.get("created_at"),
                        "updated_at": r.get("updated_at"), "comments": int(r.get("comments") or 0),
                        "milestone": (r.get("milestone") or {}).get("title"), "url": r.get("html_url")})
        if len(rows) < pb.PAGE:
            break
    return out


def pr_details(gh: pb.Gh, repo: str) -> tuple[dict, str | None]:
    """Draft, mergeable, review and CI state of each open PR, and the issues it closes. One query."""
    owner, name = repo.split("/", 1)
    try:
        out = gh.graphql(PRS_Q, {"o": owner, "r": name, "n": 100})
    except pb.GhError as e:
        return {}, str(e)[:200]
    nodes = ((((out.get("data") or {}).get("repository") or {}).get("pullRequests") or {}).get("nodes")) or []
    res = {}
    for n in nodes:
        last = ((n.get("commits") or {}).get("nodes") or [{}])[0] or {}
        roll = ((last.get("commit") or {}).get("statusCheckRollup") or {}).get("state")
        res[str(n["number"])] = {
            "draft": bool(n.get("isDraft")), "mergeable": n.get("mergeable"), "merge_state": n.get("mergeStateStatus"),
            "review": n.get("reviewDecision"),
            "head": n.get("headRefName"), "ci": roll,
            "closes": [f"{c['repository']['nameWithOwner']}#{c['number']}"
                       for c in ((n.get("closingIssuesReferences") or {}).get("nodes") or []) if c]}
    return res, None


def recent_comments(gh: pb.Gh, repo: str, since: str) -> dict:
    """Comments since `since`, newest first, keyed by issue number. One page: the newest 100."""
    try:
        rows = gh.get(f"repos/{repo}/issues/comments", since=since, per_page=100, sort="created", direction="desc") or []
    except pb.GhError:
        return {}
    out: dict[str, list[dict]] = {}
    for c in rows:
        num = str(c.get("issue_url", "")).rsplit("/", 1)[-1]
        user = c.get("user") or {}
        login = str(user.get("login") or "")
        out.setdefault(num, []).append({"author": login, "bot": user.get("type") == "Bot" or login.endswith("[bot]"),
                                        "association": c.get("author_association"), "at": c.get("created_at")})
    return out


def bump_of(messages: list[str]) -> dict:
    """Conventional Commit subjects -> what a release would carry (docs/RELEASES.md)."""
    c = {"feat": 0, "fix": 0, "breaking": 0, "other": 0}
    for msg in messages:
        first = (msg or "").split("\n", 1)[0]
        m = CC_RX.match(first)
        kind = m.group("type").lower() if m else ""
        if (m and m.group("bang")) or "BREAKING CHANGE:" in (msg or ""):
            c["breaking"] += 1
        elif kind == "feat":
            c["feat"] += 1
        elif kind in ("fix", "perf"):
            c["fix"] += 1
        else:
            c["other"] += 1
    c["bump"] = "major" if c["breaking"] else "minor" if c["feat"] else "patch" if c["fix"] else None
    return c


def release_state(gh: pb.Gh, row: dict, items: list[dict], prs: dict, cfg: dict) -> dict:
    """Latest release or tag, what has landed since, and the open release PR, for one repo."""
    repo, branch = row["repo"], row.get("default_branch") or row["branch"]
    engines = (cfg.get("release") or {}).get("engines") or {}
    st: dict[str, Any] = {"engine": engines.get(repo) or (row.get("registry_release") or {}).get("engine"),
                          "latest": None, "published_at": None, "unreleased": None, "release_pr": None}
    try:
        rels = [r for r in gh.get(f"repos/{repo}/releases", per_page=5) or [] if not r.get("draft") and not r.get("prerelease")]
        if rels:
            st["latest"], st["published_at"] = rels[0].get("tag_name"), rels[0].get("published_at")
        else:
            tags = gh.get(f"repos/{repo}/tags", per_page=1) or []
            st["latest"] = tags[0].get("name") if tags else None
    except pb.GhError as e:
        st["error"] = str(e)[:160]
        return st
    if not st["engine"]:
        try:
            gh.get(f"repos/{repo}/contents/release-please-config.json")
            st["engine"] = "release-please"
        except pb.GhError:
            st["engine"] = "none"
    if st["latest"]:
        try:
            base = urllib.parse.quote(st["latest"], safe="")
            cmp = gh.get(f"repos/{repo}/compare/{base}...{urllib.parse.quote(branch, safe='')}", per_page=100) or {}
            commits = cmp.get("commits") or []
            un = bump_of([(c.get("commit") or {}).get("message", "") for c in commits])
            un.update(commits=int(cmp.get("ahead_by") or len(commits)), sampled=len(commits))
            st["unreleased"] = un
        except pb.GhError as e:
            st["error"] = str(e)[:160]
    for t in items:
        if t["kind"] != "pr":
            continue
        head = (prs.get(str(t["number"])) or {}).get("head") or ""
        if "autorelease: pending" in t["labels"] or head.startswith("release-please--") or RELEASE_TITLE_RX.match(t["title"]):
            st["release_pr"] = {"number": t["number"], "title": t["title"], "created_at": t["created_at"], "url": t["url"]}
            break
    return st


def gather_repo(gh: pb.Gh, row: dict, cfg: dict, since: str) -> dict:
    out = {**row, "items": [], "prs": {}, "comments": {}, "release": {}, "epics": {}}
    repo = row["repo"]
    try:
        meta = gh.get(f"repos/{repo}")
    except pb.GhError as e:  # a 404 here is "this token cannot see it", never "deleted"
        out["unreachable"] = str(e)[:160]
        return out
    out.update(private=bool(meta.get("private")), archived=bool(meta.get("archived")),
               default_branch=meta.get("default_branch") or row["branch"])
    if out["archived"]:
        return out
    try:
        out["items"] = open_items(gh, repo)
    except pb.GhError as e:
        out["unreachable"] = str(e)[:160]
        return out
    if any(t["kind"] == "pr" for t in out["items"]):
        out["prs"], err = pr_details(gh, repo)
        if err:
            out["pr_error"] = err
    out["comments"] = recent_comments(gh, repo, since)
    if "release" in cfg["lanes"]:
        out["release"] = release_state(gh, out, out["items"], out["prs"], cfg)
    for t in out["items"]:
        if t["kind"] == "issue" and "epic" in t["labels"]:
            try:
                subs = gh.get(f"repos/{repo}/issues/{t['number']}/sub_issues", per_page=100) or []
                out["epics"][str(t["number"])] = {"total": len(subs), "closed": sum(1 for s in subs if s.get("state") == "closed")}
            except pb.GhError:
                continue
    return out


def gather_board(cfg: dict, gh: pb.Gh | None = None) -> dict:
    proj = cfg["project"]
    board = pb.Board(gh or pb.gh_for_projects(), proj["owner"], int(proj["number"]), max_items=BOARD_MAX_ITEMS)
    if not board.load():
        return {"available": False, "error": board.error, "owner": proj["owner"], "number": int(proj["number"])}
    items = [{"repo": it["repo"], "number": int(it["number"]), "item_id": it["item_id"], "kind": it["kind"],
              "state": it.get("state"), "archived": it.get("archived", False), "fields": it.get("fields") or {},
              "title": it.get("title", "")} for it in board.items.values()]
    return {"available": True, "owner": proj["owner"], "number": int(proj["number"]), "project": board.project,
            "items": items, "truncated": len(items) >= BOARD_MAX_ITEMS}


def gather_roadmap_issues(gh: pb.Gh, roadmap: list[dict], repos: list[dict]) -> dict:
    """State of every issue a roadmap entry names: from the open lists where it is there, one GET otherwise."""
    open_keys = {f"{r['repo']}#{t['number']}": t for r in repos for t in r.get("items") or []}
    out = {}
    for e in roadmap:
        m = ISSUE_URL_RX.search(str(e.get("issue_url") or ""))
        if not m:
            continue
        key = f"{m.group(1)}#{m.group(2)}"
        if key in open_keys:
            out[key] = {"state": "open", "labels": open_keys[key]["labels"]}
            continue
        try:
            r = gh.get(f"repos/{m.group(1)}/issues/{m.group(2)}")
            out[key] = {"state": r.get("state"), "state_reason": r.get("state_reason"),
                        "labels": [l["name"] for l in r.get("labels") or []]}
        except pb.GhError as err:
            out[key] = {"state": "unknown", "error": str(err)[:120]}
    return out


def load_roadmap(path: Path = ROADMAP) -> list[dict]:
    try:
        rows = yaml.safe_load(path.read_text()) or []
    except OSError:
        return []
    return [e for e in rows if isinstance(e, dict) and e.get("id")]


def gather(cfg: dict, fleet: dict, only: set[str] | None = None, skip_board: bool = False, jobs: int = 4,
           gh: pb.Gh | None = None, board_gh: pb.Gh | None = None, now: datetime | None = None,
           progress: Callable[[str], None] | None = None) -> dict:
    """Read everything the review needs. Nothing here writes."""
    now = now or now_utc()
    gh = gh or pb.Gh()
    say = progress or (lambda _m: None)
    registry = yaml.safe_load(pb.REGISTRY.read_text()) or []
    scope = [r for r in fleet_scope(fleet, registry, cfg) if not only or r["repo"] in only]
    since = iso(now - timedelta(days=int(cfg["comments"]["lookback_days"])))

    def one(row: dict) -> dict:
        res = gather_repo(gh, row, cfg, since)
        say(f"  {row['repo']}: " + (res.get("unreachable") and "unreachable" or f"{len(res['items'])} open"))
        return res

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        repos = list(pool.map(one, scope))
    roadmap = load_roadmap() if "roadmap" in cfg["lanes"] else []
    triage = {}
    try:
        t = yaml.safe_load(pb.TRIAGE.read_text()) or {}
        triage = {"generated_at": t.get("generated_at"),
                  "failing": {r.get("nwo"): len((r.get("workflows") or {}).get("failing") or []) for r in t.get("by_repo") or []}}
    except OSError:
        pass
    board = {"available": False, "error": "skipped (--skip-board)"} if skip_board or "project" not in cfg["lanes"] \
        else gather_board(cfg, board_gh)
    say(f"  board: {len(board['items'])} items" if board.get("available") else f"  board: {board.get('error')}")
    return {"schema": MODEL_SCHEMA, "generated_at": iso(now), "hub": (fleet.get("hub") or {}).get("repo", "bamr87/bamr87"),
            "repos": repos, "board": board, "roadmap": roadmap, "roadmap_issues": gather_roadmap_issues(gh, roadmap, repos),
            "triage": triage, "partial": bool(only)}


# --------------------------------------------------------------------------- align (pure)
def fit_option(field: str, value: str | None, options: dict, aliases: dict) -> str | None:
    """`value` if the project can hold it, its alias if that can, else None (said, never guessed)."""
    opts = options.get(field)
    if not value or not opts or value in opts:
        return value
    alt = aliases.get(value)
    return alt if alt in opts else None


def pr_mirror(pr: dict) -> dict:
    """The project's CI and Merge state options for one pull request. A state GitHub is still
    computing (UNKNOWN) yields nothing, so a transient answer never becomes an op."""
    ci = pr.get("ci")
    merge = MERGE_OPTION.get(pr.get("merge_state") or "") or {"MERGEABLE": "Clean", "CONFLICTING": "Conflicting"}.get(pr.get("mergeable") or "")
    out = {"CI": "None" if ci is None else CI_OPTION.get(ci), "Merge state": merge}
    return {k: v for k, v in out.items() if v}


def align(model: dict, cfg: dict, decisions: dict, framework: dict, allow: set[str] | None = None) -> dict:
    """Findings, the board ops, the roadmap edits and the release train, from one gathered model."""
    now = parse_iso(model.get("generated_at")) or now_utc()
    lanes, th, bcfg = set(cfg["lanes"]), cfg["thresholds"], cfg["board"]
    board = model.get("board") or {}
    project = board.get("project") or {}
    fields = project.get("fields") or {}
    options = {n: list(f.get("options") or {}) for n, f in fields.items() if f.get("options")}
    bitems = {(it["repo"], int(it["number"])): it for it in board.get("items") or []}
    held, early, aliases = set(bcfg["held"]), set(bcfg["early"]), bcfg["aliases"]
    findings: list[dict] = []
    ops: list[dict] = []
    repos = model.get("repos") or []
    private = {r["repo"] for r in repos if r.get("private")}
    # A repo is public only when the review read it and GitHub said so: an item of a repo that was
    # not read (unreachable, or on the project from outside the scope) is never listed in public.
    public = {r["repo"] for r in repos if r.get("private") is False}
    project_on = bool(board.get("available")) and "project" in lanes

    def add(lane: str, kind: str, ref: str, repo: str, title: str, why: str, proposal: str, auto: bool = False, url: str | None = None):
        if lane not in lanes:
            return
        findings.append({"id": hashlib.sha1(f"{kind}|{ref}".encode()).hexdigest()[:10], "lane": lane, "kind": kind,
                         "severity": SEVERITY.get(kind, "low"), "repo": repo, "ref": ref, "title": title, "why": why,
                         "proposal": proposal, "auto": auto, "url": url,
                         "private": repo not in public and not ref.startswith(("FF-", "roadmap:"))})

    def set_field(t: dict, it: dict, name: str, value: str, basis: str):
        ops.append({"op": "item.set_field", "project_id": project.get("id"), "item_id": it["item_id"],
                    "field_id": fields[name]["id"], "value": value, "field": name, "repo": t["repo"],
                    "number": int(t["number"]), "basis": basis})

    # which open PRs close which issue
    closers: dict[str, list[dict]] = {}
    for r in repos:
        for num, pr in (r.get("prs") or {}).items():
            for ref in pr.get("closes") or []:
                closers.setdefault(ref, []).append({"repo": r["repo"], "number": int(num), "draft": pr.get("draft")})

    open_total = on_board = fielded = 0
    by_repo = []
    open_keys: dict[str, dict] = {}
    for r in repos:
        repo = r["repo"]
        if r.get("unreachable"):
            add("hygiene", "repo_unreachable", repo, repo, repo, f"not readable with this token: {r['unreachable']}",
                "a 404 is not a deletion: check the token's access before acting on it")
            continue
        if r.get("archived"):
            continue
        tracked = 0
        unlabelled = Counter()
        for t in r.get("items") or []:
            key = f"{repo}#{t['number']}"
            open_keys[key] = t
            open_total += 1
            pr = (r.get("prs") or {}).get(str(t["number"])) or {}
            if t["kind"] == "pr" and pr:
                t = {**t, "draft": pr.get("draft", t["draft"])}
            labels = [l.lower() for l in t["labels"]]
            want = pb.derive_fields(t, decisions, framework, options)
            linked = closers.get(key) or []
            via_pr = ("In progress" if all(p["draft"] for p in linked) else "In review") if linked and t["kind"] == "issue" else None
            if t["kind"] == "issue":
                for group, names in (("type", TYPE_LABELS), ("priority", PRIORITY_LABELS)):
                    if not any(n.lower() in labels for n in names):
                        unlabelled[group] += 1
            # ---- project lane
            if project_on:
                it = bitems.get((repo, int(t["number"])))
                if it is None:
                    in_allow = allow is None or repo in allow
                    add("project", "untracked", key, repo, t["title"], f"open {t['kind']} is not on the Fleet project (§ 10.1)",
                        "add it to the project", auto=in_allow and bool(t.get("node_id")), url=t.get("url"))
                    if in_allow and t.get("node_id"):
                        ops.append({"op": "item.add", "project_id": project.get("id"), "content_id": t["node_id"],
                                    "repo": repo, "number": int(t["number"]), "kind": t["kind"], "basis": "untracked"})
                else:
                    tracked += 1
                    cur = it.get("fields") or {}
                    status, prio = cur.get("Status"), cur.get("Priority")
                    if status and prio:
                        fielded += 1
                    target = via_pr or want["Status"]
                    fitted = fit_option("Status", target, options, aliases)
                    if "Status" in fields and not status:
                        if fitted:
                            add("project", "status_missing", key, repo, t["title"], "on the project with no Status (§ 10.4)",
                                f"Status → {fitted}", auto=True, url=t.get("url"))
                            set_field(t, it, "Status", fitted, "status_missing")
                        else:
                            add("project", "option_missing", key, repo, t["title"],
                                f"derived Status {target!r} is not an option of the project", "add the option or an alias in fleet.yml pm.board.aliases")
                    elif "Status" in fields and status not in held and status != "Done":
                        if "needs-amr" in labels and "Needs Amr" in options.get("Status", []):
                            add("project", "gate_not_mirrored", key, repo, t["title"],
                                f"labelled needs-amr but the project says {status!r} (§ 12.4)", "Status → Needs Amr", auto=True, url=t.get("url"))
                            set_field(t, it, "Status", "Needs Amr", "gate_not_mirrored")
                        elif fitted and fitted != status and (t["kind"] == "pr" or (via_pr and status in early)):
                            why = (f"the pull request is {'a draft' if t['draft'] else 'ready for review'}" if t["kind"] == "pr"
                                   else f"{linked[0]['repo']}#{linked[0]['number']} closes it")
                            add("project", "status_behind", key, repo, t["title"], f"{why}, the project says {status!r}",
                                f"Status → {fitted}", auto=True, url=t.get("url"))
                            set_field(t, it, "Status", fitted, "status_behind")
                    elif status == "Done":
                        add("project", "done_but_open", key, repo, t["title"], "Done on the project, still open on GitHub",
                            "close it, or move it back: the project wins on conflict (§ 9), so nothing is planned", url=t.get("url"))
                    label_prio = next((n for n in PRIORITY_LABELS if n.lower() in labels), None)
                    if "Priority" in fields and not prio:
                        basis = f"label {label_prio}" if label_prio else "the default (no priority label)"
                        add("project", "priority_missing", key, repo, t["title"], "on the project with no Priority (§ 10.4)",
                            f"Priority → {want['Priority']} from {basis}", auto=True, url=t.get("url"))
                        set_field(t, it, "Priority", want["Priority"], "priority_missing")
                    elif label_prio and prio and label_prio != prio:
                        add("project", "priority_conflict", key, repo, t["title"], f"label {label_prio}, project {prio}",
                            f"the project wins (§ 9): relabel to {prio}", url=t.get("url"))
                    if t["kind"] == "pr" and pr:
                        drift = {n: v for n, v in pr_mirror(pr).items() if n in bcfg["mirror_fields"] and n in fields
                                 and v in options.get(n, []) and cur.get(n) != v}
                        if drift:
                            add("project", "pr_state_not_mirrored", key, repo, t["title"],
                                "the project is behind the pull request: " + ", ".join(f"{n} is {cur.get(n) or 'unset'}" for n in drift),
                                ", ".join(f"{n} → {v}" for n, v in drift.items()), auto=True, url=t.get("url"))
                            for n, v in drift.items():
                                set_field(t, it, n, v, "pr_mirror")
                    idle = days_since(t.get("updated_at"), now)
                    if status == "In progress" and idle is not None and idle >= int(th["stale_in_progress_days"]):
                        add("project", "stale_in_progress", key, repo, t["title"], f"In progress, no activity for {idle} days",
                            "move it back to Ready, or say what blocks it", url=t.get("url"))
            # ---- hygiene lane: pull requests and replies
            if t["kind"] == "pr" and pr:
                idle = days_since(t.get("updated_at"), now)
                if pr.get("mergeable") == "CONFLICTING":
                    add("hygiene", "pr_conflicting", key, repo, t["title"], "has merge conflicts with its base",
                        "python3 -m tools.jev conflicts triage --pr " + key, url=t.get("url"))
                if pr.get("ci") in ("FAILURE", "ERROR"):
                    add("hygiene", "pr_ci_red", key, repo, t["title"], "its checks are failing", "fix or re-run the checks", url=t.get("url"))
                if pr.get("review") == "CHANGES_REQUESTED":
                    add("hygiene", "pr_changes_requested", key, repo, t["title"], "a reviewer requested changes", "address the review", url=t.get("url"))
                if not t["draft"] and idle is not None and idle >= int(th["pr_idle_days"]):
                    add("hygiene", "pr_idle", key, repo, t["title"], f"ready for review, idle for {idle} days",
                        "merge, close or return it to draft", url=t.get("url"))
            newest = ((r.get("comments") or {}).get(str(t["number"])) or [None])[0]
            if newest and not newest["bot"] and newest.get("association") not in ("OWNER", "MEMBER", "COLLABORATOR"):
                add("hygiene", "awaiting_reply", key, repo, t["title"],
                    f"@{newest['author']} commented on {str(newest.get('at'))[:10]} and nobody has answered", "reply", url=t.get("url"))
            ep = (r.get("epics") or {}).get(str(t["number"]))
            if ep and ep["total"] and ep["closed"] == ep["total"]:
                add("project", "epic_complete", key, repo, t["title"], f"every sub-issue is closed ({ep['total']} of {ep['total']})",
                    "close the epic: closing it is the maintainer's (§ 12.3)", url=t.get("url"))
        on_board += tracked
        for group, n in sorted(unlabelled.items()):
            add("hygiene", "unlabelled", f"{repo}:{group}", repo, repo, f"{n} open issue(s) carry no {group} label (§ 10.3)",
                "label them: tools/dash projects plan compiles a reviewed list")
        if r.get("items"):
            by_repo.append({"repo": repo, "open": len(r["items"]), "on_board": tracked, "private": bool(r.get("private"))})

    # ---- project lane: what the board holds that GitHub has finished with
    reviewed = {r["repo"] for r in repos if not r.get("unreachable")}
    for (repo, num), it in sorted(bitems.items()) if project_on else []:
        if it.get("archived") or it.get("kind") not in ("issue", "pr"):
            continue
        key = f"{repo}#{num}"
        if allow is not None and repo not in allow:
            add("project", "board_unregistered", key, repo, it.get("title", ""), "on the project, from a repo outside the registry",
                "register the repo or archive the item: the write service refuses a repo it does not know")
            continue
        if str(it.get("state") or "").upper() in ("CLOSED", "MERGED") and (it.get("fields") or {}).get("Status") != "Done" \
                and "Status" in fields and "Done" in options.get("Status", []) and (not model.get("partial") or repo in reviewed):
            add("project", "closed_not_done", key, repo, it.get("title", ""),
                f"{str(it['state']).lower()} on GitHub, {(it.get('fields') or {}).get('Status')!r} on the project", "Status → Done", auto=True)
            set_field({"repo": repo, "number": num}, it, "Status", "Done", "closed_not_done")
    if "project" in lanes and not board.get("available"):
        add("project", "board_unreadable", "board", model.get("hub", ""), "Fleet project",
            f"the project could not be read: {board.get('error')}", "run where `gh api graphql` works, with PROJECTS_TOKEN or `gh auth refresh -s project` (§ 11.7)")

    live = [it for it in bitems.values() if not it.get("archived") and str(it.get("state") or "").upper() == "OPEN"]
    queues = {"by_status": dict(Counter((it.get("fields") or {}).get("Status") or "(none)" for it in live).most_common()),
              "by_owner_agent": dict(Counter((it.get("fields") or {}).get("Owner agent") or "(none)" for it in live).most_common()),
              "needs_amr": [{"ref": f"{it['repo']}#{it['number']}", "title": it.get("title", ""), "private": it["repo"] not in public}
                            for it in sorted(live, key=lambda x: (x["repo"] != model.get("hub"), x["repo"], x["number"]))
                            if (it.get("fields") or {}).get("Status") == "Needs Amr"]}
    roadmap_edits, roadmap_summary = align_roadmap(model, cfg, add, closers, bitems, open_keys, now)
    releases = align_releases(model, cfg, add, now)
    order = {"gate_not_mirrored": 0, "closed_not_done": 1, "status_behind": 2, "status_missing": 3, "priority_missing": 4, "pr_mirror": 5, "untracked": 6}
    hub = model.get("hub")
    ops.sort(key=lambda o: (order.get(o["basis"], 9), o["repo"] != hub, o["repo"], o["number"], o.get("field", "")))
    findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), LANES.index(f["lane"]), f["kind"], f["repo"] != hub, f["ref"]))
    return {"generated_at": model.get("generated_at"), "hub": hub, "partial": bool(model.get("partial")), "findings": findings, "ops": ops,
            "roadmap_edits": roadmap_edits, "roadmap": roadmap_summary, "releases": releases, "queues": queues,
            "coverage": {"open_items": open_total, "on_board": on_board, "fielded": fielded,
                         "pct": round(100 * on_board / open_total, 1) if open_total and board.get("available") else None,
                         "by_repo": sorted(by_repo, key=lambda x: (-x["open"], x["repo"]))},
            "board": {"available": bool(board.get("available")), "error": board.get("error"), "title": project.get("title"),
                      "url": project.get("url"), "items": len(bitems), "truncated": bool(board.get("truncated"))},
            "scope": {"repos": len(repos), "unreachable": sorted(r["repo"] for r in repos if r.get("unreachable")),
                      "private": len(private)}}


def align_roadmap(model: dict, cfg: dict, add: Callable, closers: dict, bitems: dict, open_keys: dict, now: datetime):
    roadmap = model.get("roadmap") or []
    states = model.get("roadmap_issues") or {}
    edits: list[dict] = []
    linked_urls = set()
    aging = []
    for e in roadmap:
        fid, status = e["id"], e.get("status")
        m = ISSUE_URL_RX.search(str(e.get("issue_url") or ""))
        key = f"{m.group(1)}#{m.group(2)}" if m else None
        repo = m.group(1) if m else str(e.get("repo_url") or "").replace("https://github.com/", "")
        title = str(e.get("title", ""))
        if key:
            linked_urls.add(key)
        if status == "proposed":
            age = days_since(f"{e.get('created')}T00:00:00", now)
            if age is not None and age >= int(cfg["thresholds"]["proposed_aging_days"]):
                aging.append((age, fid))
            continue
        if status in ("shipped", "declined"):
            continue
        if not key:
            add("roadmap", "roadmap_unlinked", fid, repo, title, f"{status}, with no issue: it is not an item on the Fleet project (§ 10.1)",
                "mirror it to an issue in its repo and set issue_url")
            continue
        st = states.get(key) or {}
        if st.get("state") == "closed":
            if st.get("state_reason") == "not_planned":
                add("roadmap", "roadmap_declined", fid, repo, title, f"{key} was closed as not planned, the roadmap says {status}",
                    "set status: declined with a reason (a person writes the reason)")
            else:
                add("roadmap", "roadmap_shipped", fid, repo, title, f"{key} is closed as completed, the roadmap says {status}",
                    "status → shipped", auto=True)
                edits.append({"id": fid, "from": status, "to": "shipped", "why": f"{key} closed as completed"})
            continue
        if st.get("state") != "open":
            continue
        labels = [l.lower() for l in st.get("labels") or []]
        board_status = ((bitems.get((m.group(1), int(m.group(2)))) or {}).get("fields") or {}).get("Status")
        started = (closers.get(key) and f"{closers[key][0]['repo']}#{closers[key][0]['number']} is open against it") or \
                  ("agent:in-pr" in labels and "it carries agent:in-pr") or \
                  (board_status in ("In progress", "In review") and f"the project says {board_status}")
        if status in ("approved", "backlog") and started:
            add("roadmap", "roadmap_started", fid, repo, title, f"{started}, the roadmap says {status}", "status → in-progress", auto=True)
            edits.append({"id": fid, "from": status, "to": "in-progress", "why": str(started)})
        label_prio = next((n for n in PRIORITY_LABELS if n.lower() in labels), None)
        if label_prio and e.get("priority") and label_prio != e["priority"]:
            add("roadmap", "roadmap_priority_drift", fid, repo, title, f"roadmap {e['priority']}, {key} is labelled {label_prio}",
                "agree on one: edit the roadmap line or relabel the issue")
    loose = 0
    for key, t in sorted(open_keys.items()):
        labels = [l.lower() for l in t["labels"]]
        if t["kind"] != "issue" or "roadmap" not in labels or key in linked_urls:
            continue
        if "epic" in labels:
            add("roadmap", "roadmap_untracked_epic", key, t["repo"], t["title"], "an epic labelled roadmap, with no entry in _data/roadmap.yml",
                "/future-features drafts the entry; nothing lands there without your approval", url=t.get("url"))
        else:
            loose += 1
    if aging:
        aging.sort(reverse=True)
        add("roadmap", "roadmap_proposed_aging", "roadmap:proposed", model.get("hub", ""), "proposed specs awaiting a decision",
            f"{len(aging)} proposed entries are older than {cfg['thresholds']['proposed_aging_days']} days (oldest {aging[0][1]}, {aging[0][0]} days)",
            "approve or decline them on the Work board (/work) or in _data/roadmap.yml")
    by_status = Counter(str(e.get("status")) for e in roadmap)
    return edits, {"entries": len(roadmap), "by_status": dict(sorted(by_status.items())), "linked": len(linked_urls),
                   "labelled_without_entry": loose,
                   "active_unlinked": sum(1 for e in roadmap if e.get("status") in ("approved", "backlog", "in-progress") and not e.get("issue_url"))}


def align_releases(model: dict, cfg: dict, add: Callable, now: datetime) -> list[dict]:
    th = cfg["thresholds"]
    failing = (model.get("triage") or {}).get("failing") or {}
    rows = []
    for r in model.get("repos") or []:
        rel = r.get("release") or {}
        if r.get("unreachable") or r.get("archived") or not rel:
            continue
        repo, engine = r["repo"], rel.get("engine") or "none"
        un = rel.get("unreleased") or {}
        releasable = int(un.get("feat", 0)) + int(un.get("fix", 0)) + int(un.get("breaking", 0))
        pr = rel.get("release_pr")
        state = ("release_pr_open" if pr else "never_released" if not rel.get("latest") else "current" if not releasable
                 else "blocked" if engine == "release-please" else "unreleased")
        red = int(failing.get(repo) or 0)
        row = {"repo": repo, "engine": engine, "latest": rel.get("latest"), "published_at": (rel.get("published_at") or "")[:10] or None,
               "commits": un.get("commits"), "feat": un.get("feat"), "fix": un.get("fix"), "breaking": un.get("breaking"),
               "bump": un.get("bump"), "release_pr": pr and pr["number"], "state": state, "red_main": red,
               "private": bool(r.get("private"))}
        rows.append(row)
        tail = f"; {red} workflow(s) are red on {r.get('default_branch') or r['branch']}" if red else ""
        what = f"{un.get('feat', 0)} feat, {un.get('fix', 0)} fix, {un.get('breaking', 0)} breaking since {rel.get('latest')}" + \
            (f" (counted in the first {un['sampled']} of {un['commits']} commits)" if un.get("sampled") and un.get("commits", 0) > un["sampled"] else "")
        if state == "release_pr_open":
            age = days_since(pr.get("created_at"), now)
            if age is not None and age >= int(th["release_pr_waiting_days"]):
                add("release", "release_pr_waiting", f"{repo}#{pr['number']}", repo, pr.get("title", ""),
                    f"the release PR has been open {age} days{tail}", "merging it tags and publishes the release: that merge is yours", url=pr.get("url"))
        elif state == "blocked":
            add("release", "release_blocked", repo, repo, repo, f"{what}, release-please is adopted, and no release PR is open{tail}",
                "docs/RELEASES.md \"When the release PR cannot be opened\": RELEASE_PLEASE_TOKEN or the Actions PR permission")
        elif state == "unreleased" and releasable >= int(th["unreleased_commits"]):
            how = "cut the next tag (docs/WORKFLOW-VERSIONING.md)" if engine == "hand-cut" else f"tools/adopt-release.sh {repo.split('/')[1]}"
            add("release", "release_unreleased", repo, repo, repo, f"{what} ({un.get('bump')} bump), engine {engine}{tail}", how)
    order = {"blocked": 0, "release_pr_open": 1, "unreleased": 2, "current": 3, "never_released": 4}
    return sorted(rows, key=lambda x: (order[x["state"]], x["repo"]))


# --------------------------------------------------------------------------- plan
def offline_board(model: dict) -> pb.Board:
    """A pb.Board that answers plan()'s state reads from the gathered model, with no network."""
    b = model.get("board") or {}
    board = pb.Board(None, b.get("owner", ""), int(b.get("number") or 0))
    board.project = b.get("project")
    board.items = {(it["repo"], int(it["number"])): it for it in b.get("items") or []}
    return board


def board_preview(model: dict, result: dict, allow: set[str] | None) -> dict:
    """The board ops as a `projects-backfill-plan/v1` preview: `tools/dash projects apply` takes it as is."""
    board = offline_board(model)
    batches = pb.plan_batches(result["ops"], board.state, allow) if result["ops"] else []
    for b in batches:
        b["board"] = True
    return {"schema": pb.PLAN_SCHEMA, "generated_at": result["generated_at"], "source": "pm_review", "repo": model.get("hub"),
            "decisions": str(pb.DECISIONS), "record": "audit-only", "max_items": BOARD_MAX_ITEMS, "batches": batches,
            "board": {"status": "planned" if batches else "nothing to do", "project": result["board"].get("title"),
                      "url": result["board"].get("url"), "adds": sum(1 for o in result["ops"] if o["op"] == "item.add"),
                      "field_sets": sum(1 for o in result["ops"] if o["op"] == "item.set_field")}}


def apply_roadmap_edits(text: str, edits: list[dict]) -> str:
    """The roadmap's status lines, edited in place by the Work board's own editor (every other byte kept)."""
    sys.path.insert(0, str(DASH_GEN))
    import work_board as wb  # noqa: WPS433 - the one roadmap editor; never a second one
    for e in edits:
        text = wb.edit_roadmap(text, e["id"], status=e["to"])
    return text


# --------------------------------------------------------------------------- report
def public_view(result: dict) -> dict:
    """The review with every row of a private repo dropped (the counts stay): what a public job
    summary or artifact may show."""
    out = dict(result)
    out["findings"] = [f for f in result["findings"] if not f["private"]]
    out["releases"] = [r for r in result["releases"] if not r["private"]]
    out["queues"] = {**result["queues"], "needs_amr": [q for q in result["queues"]["needs_amr"] if not q["private"]]}
    out["private_omitted"] = len(result["findings"]) - len(out["findings"])
    return out


def drain(ops: int, batches: int) -> str:
    """How long the § 11.5 caps make a plan take: 50 ops a batch, 200 an hour."""
    if not ops:
        return "nothing to apply"
    hours = -(-ops // gw.MAX_OPS_PER_HOUR)
    return f"{batches} batch(es)" + (f", about {hours} hours at the service's hourly cap" if hours > 1 else "")


def snapshot(result: dict, preview: dict, cfg: dict, previous: dict | None = None) -> dict:
    """The committed, public snapshot. Items of private repos are counted, never listed."""
    prev = previous or {}
    seen = set(str(prev.get("seen") or "").split())
    public = [f for f in result["findings"] if not f["private"]]
    cap, per_kind = int(cfg["snapshot"]["max_findings"]), int(cfg["snapshot"]["max_per_kind"])
    kept, used = [], Counter()
    for f in public:
        if len(kept) >= cap or used[f["kind"]] >= per_kind:
            continue
        used[f["kind"]] += 1
        kept.append({"id": f["id"], "lane": f["lane"], "kind": f["kind"], "severity": f["severity"], "ref": f["ref"],
                     "title": f["title"][:120], "why": f["why"], "proposal": f["proposal"], "planned": f["auto"],
                     "new": bool(seen) and f["id"] not in seen})
    cov = result["coverage"]
    day = str(result["generated_at"])[:10]
    entry = {"date": day, "open_items": cov["open_items"], "on_board": cov["on_board"], "coverage_pct": cov["pct"],
             "findings": len(result["findings"]), "planned_ops": len(result["ops"])}
    history = [h for h in prev.get("history") or [] if h.get("date") != day] + [entry]
    return {
        "schema": SCHEMA, "generated_at": result["generated_at"],
        "project": {**{k: result["board"][k] for k in ("available", "title", "url", "items", "truncated")},
                    **({"error": result["board"]["error"]} if result["board"].get("error") else {})},
        "scope": result["scope"],
        "coverage": {**{k: cov[k] for k in ("open_items", "on_board", "fielded", "pct")},
                     "by_repo": [{k: v for k, v in r.items() if k != "private"} for r in cov["by_repo"] if not r["private"]]},
        "findings": {"total": len(result["findings"]), "new": sum(1 for f in result["findings"] if seen and f["id"] not in seen),
                     "private_omitted": len(result["findings"]) - len(public),
                     "by_lane": dict(Counter(f["lane"] for f in result["findings"])),
                     "by_kind": dict(sorted(Counter(f["kind"] for f in result["findings"]).items())),
                     "by_severity": dict(Counter(f["severity"] for f in result["findings"])), "items": kept},
        "plan": {"board": {"ops": len(result["ops"]), "adds": preview["board"]["adds"], "field_sets": preview["board"]["field_sets"],
                           "batches": len(preview["batches"]), "by_basis": dict(sorted(Counter(o["basis"] for o in result["ops"]).items()))},
                 "roadmap": result["roadmap_edits"]},
        "roadmap": result["roadmap"],
        "queues": {"by_status": result["queues"]["by_status"], "by_owner_agent": result["queues"]["by_owner_agent"],
                   "needs_amr": [{"ref": q["ref"], "title": q["title"][:120]} for q in result["queues"]["needs_amr"] if not q["private"]]},
        "releases": [{k: v for k, v in r.items() if k != "private"} for r in result["releases"] if not r["private"]],
        "history": history[-HISTORY_KEEP:],
        "seen": " ".join(sorted(f["id"] for f in result["findings"])),
        "note": ("Written by tools/pm_review.py (fleet-pm.yml). Read-only review: nothing here was applied. Board ops are applied "
                 "through `tools/dash projects apply` after a person has read them (constitution § 11.4). Private repos are counted, not listed."),
    }


def markdown(result: dict, preview: dict, out_dir: Path | None = None) -> str:
    cov, f = result["coverage"], result["findings"]
    lines = [f"# Fleet PM review — {str(result['generated_at'])[:10]}", ""]
    if result.get("partial"):
        lines += ["> Partial run (`--repo`): totals cover the named repos only.", ""]
    board = result["board"]
    tracked = f"{cov['on_board']} of {cov['open_items']} open items are on the project ({cov['pct']}%), {cov['fielded']} with Status and Priority" \
        if board["available"] else f"the project was not readable ({board.get('error')})"
    lines += [f"- **Project:** {tracked}.",
              f"- **Roadmap:** {result['roadmap'].get('entries', 0)} entries, {result['roadmap'].get('linked', 0)} linked to an issue, "
              f"{result['roadmap'].get('active_unlinked', 0)} active with none.",
              f"- **Releases:** " + ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in Counter(r["state"] for r in result["releases"]).items()) + ".",
              f"- **Needs Amr:** {len(result['queues']['needs_amr'])} item(s) wait on you"
              + (": " + ", ".join(q["ref"].replace(str(result.get("hub")) + "#", "#") for q in result["queues"]["needs_amr"][:15]) if result["queues"]["needs_amr"] else "") + ".",
              f"- **Findings:** {len(f)} ({', '.join(f'{n} {s}' for s, n in Counter(x['severity'] for x in f).items())})"
              + (f", plus {result['private_omitted']} in private repos, not listed" if result.get("private_omitted") else "") + ".",
              f"- **Plan:** {len(result['ops'])} project op(s) in {drain(len(result['ops']), len(preview['batches']))}, "
              f"{len(result['roadmap_edits'])} roadmap edit(s). Nothing was applied.", ""]
    for lane, head in (("project", "Project alignment"), ("roadmap", "Roadmap alignment"), ("release", "Release management"), ("hygiene", "Pull requests, replies and labels")):
        rows = [x for x in f if x["lane"] == lane]
        if not rows:
            continue
        lines += [f"## {head}", ""]
        for kind, n in Counter(x["kind"] for x in rows).most_common():
            group = [x for x in rows if x["kind"] == kind]
            lines += [f"**{kind.replace('_', ' ')}** ({n})", ""]
            for x in group[:12]:
                lines.append(f"- `{x['ref']}` {x['title'][:90]}: {x['why']}. *{x['proposal']}*")
            if n > 12:
                lines.append(f"- … and {n - 12} more")
            lines.append("")
    if result["releases"]:
        lines += ["## Release train", "", "| Repo | Engine | Latest | Since | Bump | Release PR | State |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in result["releases"]:
            if r["state"] in ("never_released", "current"):
                continue
            since = f"{r.get('feat') or 0} feat, {r.get('fix') or 0} fix" + (f", {r['breaking']} breaking" if r.get("breaking") else "")
            lines.append(f"| {r['repo']} | {r['engine']} | {r['latest'] or '—'} | {since} | {r['bump'] or '—'} | "
                         f"{'#' + str(r['release_pr']) if r['release_pr'] else '—'} | {r['state'].replace('_', ' ')} |")
        quiet = Counter(r["state"] for r in result["releases"] if r["state"] in ("never_released", "current"))
        lines += ["", f"{quiet.get('current', 0)} repo(s) are current and {quiet.get('never_released', 0)} have never cut a release.", ""]
    lines += ["## Applying the plan", ""]
    if preview["batches"]:
        path = (out_dir or OUT_DIR) / "board-plan.json"
        lines += [f"`tools/dash pm plan` prints every op as before → after. After reading it: "
                  f"`HARNESS_PROJECTS_WRITES=1 tools/dash projects apply {path} --confirm` (§ 11.4; 50 ops a batch, 200 an hour).", ""]
    if result["roadmap_edits"]:
        lines += ["`tools/dash pm roadmap --write` edits the status lines in the working tree; committing the diff is the approval.", ""]
    if not preview["batches"] and not result["roadmap_edits"]:
        lines += ["Nothing to apply.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands
def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except OSError:
        raise ValueError(f"{path} is missing: run `tools/dash pm review` first") from None


def cmd_review(args) -> int:
    fleet = load_fleet()
    cfg = load_config(fleet)
    out_dir = Path(args.out)
    say = (lambda _m: None) if args.quiet or args.json else (lambda m: print(m, file=sys.stderr, flush=True))
    if args.model:
        model = _load_json(Path(args.model))
        if model.get("schema") != MODEL_SCHEMA:
            raise ValueError(f"{args.model} is not a {MODEL_SCHEMA} file")
    else:
        say("gathering (read-only: GETs and GraphQL queries)…")
        model = gather(cfg, fleet, only=set(args.repo) or None, skip_board=args.skip_board, jobs=args.jobs, progress=say)
    decisions, framework, allow = pb.load_decisions(), pb.load_framework(), pb.registry_repos()
    result = align(model, cfg, decisions, framework, allow)
    preview = board_preview(model, result, allow)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    view = public_view(result) if args.public else result
    if not args.public:  # the full model and review name private repos' items: local runs only
        (out_dir / "model.json").write_text(json.dumps(model, indent=1, default=str) + "\n")
    (out_dir / "review.json").write_text(json.dumps(view, indent=1, default=str) + "\n")
    pb.write_preview(preview, out_dir / "board-plan.json")
    md = markdown(view, preview, out_dir)
    (out_dir / "review.md").write_text(md + "\n")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    if args.write:
        path = Path(args.snapshot)
        if result["partial"]:
            raise ValueError("refused: a partial run (--repo) is never written to the snapshot")
        try:
            previous = yaml.safe_load(path.read_text()) or {}
        except OSError:
            previous = {}
        doc = snapshot(result, preview, cfg, previous)
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=4096))
        say(f"snapshot: {path}")
    if args.json:
        print(json.dumps({"findings": len(result["findings"]), "ops": len(result["ops"]), "batches": len(preview["batches"]),
                          "roadmap_edits": result["roadmap_edits"], "coverage": {k: v for k, v in result["coverage"].items() if k != "by_repo"},
                          "out": str(out_dir)}, indent=1))
    else:
        print(md)
        print(f"\nfiles: {out_dir}/review.md · review.json · board-plan.json" + ("" if args.public else " · model.json"))
    return 0


def cmd_plan(args) -> int:
    preview = _load_json(Path(args.out) / "board-plan.json")
    if not preview.get("batches"):
        print("nothing planned for the Fleet project")
        return 0
    print(f"Fleet project plan from {preview['generated_at']} — dry run, nothing written to GitHub (constitution § 11.4)")
    for b in preview["batches"]:
        print(f"\nbatch {b['index']} plan_id {b['plan_id']}: {b['changes']} change(s) in {len(b['ops'])} op(s)")
        for op, row in zip(b["ops"], b["rows"]):
            print(f"  {op['repo']:<28} {pb.describe(op, row)}   [{op.get('basis')}]")
    total = sum(b["changes"] for b in preview["batches"])
    print(f"\n{total} change(s) in {len(preview['batches'])} batch(es)")
    print(f"apply with: HARNESS_PROJECTS_WRITES=1 tools/dash projects apply {Path(args.out) / 'board-plan.json'} --confirm")
    return 0


def cmd_roadmap(args) -> int:
    edits = _load_json(Path(args.out) / "review.json").get("roadmap_edits") or []
    if not edits:
        print("the roadmap's status lines agree with GitHub")
        return 0
    for e in edits:
        print(f"{e['id']}: {e['from']} → {e['to']}   ({e['why']})")
    if args.write:
        path = Path(args.roadmap)
        path.write_text(apply_roadmap_edits(path.read_text(), edits))
        print(f"\nwrote {len(edits)} status line(s) to {path} in the working tree; `git diff` it, and commit to approve")
    else:
        print("\ndry run: --write edits the working tree (never commits)")
    return 0


def cmd_releases(args) -> int:
    rows = _load_json(Path(args.out) / "review.json").get("releases") or []
    print(f"{'repo':<40} {'engine':<15} {'latest':<12} {'feat':>4} {'fix':>4} {'brk':>4} {'bump':<6} {'PR':<6} state")
    for r in rows:
        print(f"{r['repo']:<40} {r['engine']:<15} {str(r['latest'] or '—'):<12} {str(r.get('feat') if r.get('feat') is not None else '—'):>4} "
              f"{str(r.get('fix') if r.get('fix') is not None else '—'):>4} {str(r.get('breaking') if r.get('breaking') is not None else '—'):>4} "
              f"{str(r['bump'] or '—'):<6} {('#' + str(r['release_pr'])) if r['release_pr'] else '—':<6} {r['state'].replace('_', ' ')}"
              + (f"  ({r['red_main']} red)" if r.get("red_main") else ""))
    return 0


def cmd_status(args) -> int:
    try:
        doc = yaml.safe_load(Path(args.snapshot).read_text()) or {}
    except OSError:
        print(f"no snapshot at {args.snapshot}: the loop has not published one yet (tools/dash pm review --write)")
        return 0
    cov, f = doc.get("coverage") or {}, doc.get("findings") or {}
    print(f"PM review {doc.get('generated_at')}: {cov.get('on_board')} of {cov.get('open_items')} open items on the project "
          f"({cov.get('pct')}%), {f.get('total')} findings ({f.get('new')} new), "
          f"{((doc.get('plan') or {}).get('board') or {}).get('ops')} project op(s) and {len((doc.get('plan') or {}).get('roadmap') or [])} roadmap edit(s) planned")
    for lane, n in (f.get("by_lane") or {}).items():
        print(f"  {lane:<8} {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pm_review", description="The fleet's routine PM review: project, roadmap and release alignment. Read-only.")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("review", help="gather, align, plan and report (reads GitHub; writes only local files)")
    r.add_argument("--from", dest="model", help="replay a saved model.json instead of reading GitHub")
    r.add_argument("--repo", action="append", default=[], help="review only this owner/name (repeatable; never written to the snapshot)")
    r.add_argument("--skip-board", action="store_true", help="do not read the Fleet project")
    r.add_argument("--jobs", type=int, default=4, help="repos read in parallel")
    r.add_argument("--write", action="store_true", help="also write the committed snapshot (_data/pm_review.yml)")
    r.add_argument("--snapshot", default=str(SNAPSHOT))
    r.add_argument("--summary", help="append the Markdown report to this file (the job summary)")
    r.add_argument("--public", action="store_true", help="leave every private repo's rows out of the report and the local files (CI)")
    r.add_argument("--json", action="store_true")
    r.add_argument("--quiet", action="store_true")
    for name, text in (("plan", "the Fleet project ops of the last review, before → after"),
                       ("roadmap", "the roadmap status edits of the last review"),
                       ("releases", "the release train of the last review"), ("status", "the committed snapshot's headline")):
        p = sub.add_parser(name, help=text)
        if name == "roadmap":
            p.add_argument("--write", action="store_true", help="edit _data/roadmap.yml in the working tree (never commits)")
            p.add_argument("--roadmap", default=str(ROADMAP))
        if name == "status":
            p.add_argument("--snapshot", default=str(SNAPSHOT))
    for p in sub.choices.values():
        p.add_argument("--out", default=str(OUT_DIR), help="where the review's local files live (default .fleet/pm)")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return {"review": cmd_review, "plan": cmd_plan, "roadmap": cmd_roadmap, "releases": cmd_releases, "status": cmd_status}[args.cmd](args)
    except (pb.GhError, ValueError, gw.Refused) as e:
        print(f"error: {gp.redact(str(e))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

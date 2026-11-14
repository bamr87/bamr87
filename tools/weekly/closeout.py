#!/usr/bin/env python3
# ============================================================================
# File:          tools/weekly/closeout.py
# Description:   Friday's close-out (docs/WEEKLY.md): one disposition for every open pull request
#                and issue in the fleet, by rules alone, from the decision index and the PM review's
#                model, and a live read of each merge candidate against the review gate (constitution
#                § 12.1, § 12.3). It reads and it lists. It never merges and never closes: "ready to
#                merge" is a list for the maintainer, or for a Claude Code session the maintainer
#                asks, to act on after its own recheck.
# Usage:         imported by tools/weekly/cli.py; `tools/dash weekly close` runs it
# Never:         writes to GitHub. The only `gh` calls here are `gh pr view` and `gh api repos/…`.
#                An automated merge and close were built and taken out again after two independent
#                reviews (docs/WEEKLY.md "Design record"); they return only as their own change.
# ============================================================================
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from tools.weekly import core

SCHEMA = "weekly-closeout/v1"

#: In the order the report lists them. `who` is who moves the row next.
DISPOSITIONS: dict[str, dict[str, str]] = {
    "merge": {"title": "Ready to merge", "who": "you, or Claude Code when you ask",
              "next": "passes every gate a machine can read; the routine lists it and never merges it (§ 12.2)"},
    "ratify": {"title": "Awaiting ratification", "who": "Amr",
               "next": "amends the constitution, an amendment or an ADR: only the maintainer merges it (§ 8)"},
    "amr": {"title": "Waiting on Amr", "who": "Amr", "next": "held by the review gate or a repo rule (§ 12.3)"},
    "resolve": {"title": "Conflicting", "who": "JEV", "next": "`tools/dash conflicts sweep` resolves it or hands it over (§ 12.7)"},
    "fix": {"title": "Checks failing", "who": "Claude Code", "next": "carried into next week's Unblock lane"},
    "wait": {"title": "Not settled", "who": "nobody yet", "next": "checks or merge state still computing; Sunday reads it again"},
    "stale": {"title": "Stale", "who": "the close-out agent, then Amr",
              "next": "close, carry or decide: the agent proposes, you act"},
    "carry": {"title": "Carried", "who": "next week", "next": "open and moving; Sunday ranks it"},
}
ORDER = tuple(DISPOSITIONS)

DEFAULTS: dict = {
    "stale_days": 30,
    "draft_stale_days": 14,
    # Repos whose own constitution keeps every merge with the maintainer. A repo that allows only
    # squash merges needs no entry: its setting is read, and the routine merges no other way.
    "never_merge": [],
    # A changed path that puts a pull request behind the review gate (§ 12.3), matched without regard
    # to case. `weekly.closeout.gate_paths` ADDS to this list; it never replaces it. The list covers the
    # governing documents, everything GitHub runs, what holds credentials, budgets and permissions,
    # what deploys, and the code that runs unattended on the maintainer's machine, this routine included.
    "gate_paths": [
        r"(^|/)\.github/",
        r"(^|/)_data/(fleet|agents|standards|agent_roles|specs|mcp_servers)\.yml$",
        r"(^|/)\.claude/(settings[^/]*\.json$|hooks/)",
        r"(^|/)\.mcp\.json$",
        r"(^|/)\.git(modules|attributes)$",
        r"(^|/)docs/(constitution\.md|amendments/|adr/)",
        r"(^|/)(CONSTITUTION|AGENTS|CLAUDE|SECURITY)\.md$",
        r"(^|/)CODEOWNERS$",
        r"(^|/)(infra|compose)/",
        r"(^|/)((docker-)?compose[^/]*\.ya?ml|Dockerfile[^/]*)$",
        r"(^|/)\.env",
        r"(^|/)\.(vscode|devcontainer)/",
        r"(^|/)\.pre-commit-config\.ya?ml$",
        r"(^|/)tools/(dash|dash-gen|[^/]+\.sh)$",
        r"(^|/)tools/(weekly|jev|fleetcore)/",
        r"(^|/)tools/(pm_review|projects_backfill)\.py$",
        r"(^|/)tools/console/[^/]+\.py$",
        r"^[^/]+\.py$",          # a module at a repo's root shadows a library of the same name for everything run from there
        r"(^|/)(templates|specs)/",
    ],
    # A head branch whose merge does more than land code: release-please's pull request tags and
    # publishes a release when it merges, so that merge is the maintainer's.
    "release_heads": ["release-please--"],
    # A repo's own content gate, named by its constitution (§ 12.3): extra paths that hold a pull
    # request in that repo only. {owner/repo: [regex, …]}
    "repo_gate_paths": {},
    "skip_issue_labels": ["epic"],
    "keep_issue_labels": ["P0", "P1", "roadmap", "agent:in-pr"],
}
GATE_LABELS = {"gate": ["needs-amr"], "hold": ["agent:hold", "blocked"]}
#: A Dependabot title's version move, as the decision index reads it.
BUMP_RX = re.compile(r"\bfrom\s+[~^<>=\s]*v?(\d[\w.+-]*)\s+to\s+[~^<>=\s]*v?(\d[\w.+-]*)", re.I)


def _listed(value: Any) -> list[str]:
    """A config value that should be a list of names, as one. A bare string is one name, not its
    characters; anything else that is not a list is no names at all."""
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, (list, tuple, set)) else []


def config(fleet: dict) -> dict:
    """The close-out's knobs. Lists replace their default, except `gate_paths`, which only ever grows:
    a config entry must not be able to open the gate."""
    given = (fleet.get("weekly") or {}).get("closeout")
    given = given if isinstance(given, dict) else {}
    cfg = core.merged(DEFAULTS, given)
    cfg["gate_paths"] = list(dict.fromkeys([*DEFAULTS["gate_paths"], *_listed(given.get("gate_paths"))]))
    for key in ("never_merge", "release_heads", "skip_issue_labels", "keep_issue_labels"):
        cfg[key] = _listed(cfg.get(key))
    if not cfg["release_heads"]:
        cfg["release_heads"] = list(DEFAULTS["release_heads"])
    own = cfg.get("repo_gate_paths")
    cfg["repo_gate_paths"] = {str(k): _listed(v) for k, v in own.items()} if isinstance(own, dict) else {}
    return cfg


# ---- whose pull requests the routine may merge --------------------------------------------------

def _base(login: str) -> tuple[str, bool]:
    """A login without its bot spelling, and whether it was spelled as a bot (`app/x`, `x[bot]`)."""
    name = str(login or "").strip().lower()
    marked = name.startswith("app/") or name.endswith("[bot]")
    return name.removeprefix("app/").removesuffix("[bot]"), marked


def trust(fleet: dict) -> dict:
    """Whose pull requests an agent may merge: the authors JEV already resolves conflicts for, plus
    Dependabot. People and bots are kept apart, because a person can register the login a bot is
    known by: a name listed as `x[bot]` or `app/x` is trusted only as a bot, a bare name only as a
    person."""
    people, bots = set(), set()
    for raw in _listed((fleet.get("jev") or {}).get("allowed_authors")):
        name, marked = _base(raw)
        if name:
            (bots if marked else people).add(name)
    dependabot = {_base(a)[0] for a in (_listed(((fleet.get("decisions") or {}).get("dependabot") or {}).get("authors"))
                                        or ["dependabot", "dependabot[bot]"])}
    return {"people": people, "bots": bots | dependabot, "dependabot": dependabot}


def trusted_author(login: str, is_bot: bool, who: dict) -> bool:
    name, marked = _base(login)
    if not name:
        return False
    return name in who["bots"] if (is_bot or marked) else name in who["people"]


def major_bump(title: str) -> bool | None:
    """Whether a Dependabot title states a breaking move (the major, or under 0.x the minor). None
    when it states no versions, as a grouped update does: then a major bump cannot be ruled out."""
    m = BUMP_RX.search(title or "")
    if not m:
        return None

    def lead(version: str) -> tuple:
        nums = [int(x) for x in re.findall(r"\d+", version)[:2]] + [0, 0]
        return (nums[0],) if nums[0] else (0, nums[1])
    return lead(m.group(2)) > lead(m.group(1))


def _days(stamp: str | None, now: datetime) -> int | None:
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (now - (at if at.tzinfo else at.replace(tzinfo=timezone.utc))).days)


def _held(labels: Iterable[str], gate_cfg: dict, extra: Iterable[str] = ()) -> list[str]:
    """The labels on an item that hold it. The configured ones are added to the built-in three and
    never replace them: an emptied list in a config or a saved file cannot switch the gate off."""
    have = {str(x).lower() for x in labels}
    named = (gate_cfg or {}).get("labels") if isinstance(gate_cfg, dict) else None
    named = named if isinstance(named, dict) else {}
    wanted = [*GATE_LABELS["gate"], *GATE_LABELS["hold"], *_listed(named.get("gate")), *_listed(named.get("hold")), *extra]
    return [x for x in dict.fromkeys(wanted) if str(x).lower() in have]


def _row(rec: dict, kind: str, disposition: str, why: str, now: datetime) -> dict:
    return {
        "key": f"{kind}:{rec.get('repo')}#{rec.get('number')}", "type": kind, "repo": rec.get("repo"),
        "number": rec.get("number"), "title": core.redact(str(rec.get("title") or ""))[:140], "url": rec.get("url") or "",
        "author": rec.get("author") or "", "labels": sorted(str(x) for x in rec.get("labels") or []),
        "updated_at": rec.get("updated_at"), "age_days": _days(rec.get("created_at"), now),
        "idle_days": _days(rec.get("updated_at"), now), "disposition": disposition, "why": why,
        "private": bool(rec.get("private")),
    }


def dispose_pr(rec: dict, kinds: Iterable[str], why_by_kind: dict[str, str], cfg: dict, gate_cfg: dict,
               who: dict, now: datetime) -> dict:
    """One open pull request's disposition. The first rule that holds wins, most restrictive first, so
    a gated pull request is never offered for merging however green it is."""
    e = rec.get("enrich") or {}
    kinds = set(kinds)
    held = _held(rec.get("labels") or [], gate_cfg)
    idle = _days(rec.get("updated_at"), now) or 0
    author, marked = _base(rec.get("author") or "")
    is_bot = bool(rec.get("bot")) or marked

    def row(disposition: str, why: str) -> dict:
        out = _row(rec, "pr", disposition, why, now)
        out.update(draft=bool(rec.get("draft")), checks=e.get("checks"), mergeable=e.get("mergeable"),
                   merge_state=e.get("merge_state"), bot=is_bot)
        return out

    if rec.get("private"):
        return row("amr", "a private repo: the routine never acts on one")
    if held:
        return row("amr", "labelled " + ", ".join(held))
    if "ratification" in kinds:
        return row("ratify", why_by_kind.get("ratification") or "changes a governing document")
    if any(str(rec.get("head") or "").startswith(prefix) for prefix in cfg["release_heads"]):
        return row("amr", "a release pull request: merging it tags and publishes the release")
    if rec.get("draft"):
        if idle >= int(cfg["draft_stale_days"]):
            return row("stale", f"a draft untouched for {idle} days")
        return row("carry", "a draft in progress")
    if not e:
        return row("wait", "its merge state has not been read yet")
    if e.get("mergeable") == "CONFLICTING":
        return row("resolve", "conflicts with its base")
    if e.get("checks") in ("FAILURE", "ERROR"):
        return row("fix", f"checks {e['checks']}")
    if "dependabot" in kinds:
        return row("amr", why_by_kind.get("dependabot") or "a Dependabot bump that needs a decision")
    if is_bot and author in who["dependabot"]:
        bump = major_bump(str(rec.get("title") or ""))
        if bump is None:
            return row("amr", "a Dependabot update that states no versions, so a major bump cannot be ruled out")
        if bump:
            return row("amr", "a major Dependabot bump")
    if e.get("review") == "CHANGES_REQUESTED":
        return row("fix", "changes were requested")
    ready = (e.get("mergeable") == "MERGEABLE" and e.get("merge_state") in ("CLEAN", "HAS_HOOKS"))
    if not ready or e.get("checks") in ("PENDING", "EXPECTED"):
        if idle >= int(cfg["stale_days"]):
            return row("stale", f"not mergeable ({e.get('merge_state') or 'unknown'}) and untouched for {idle} days")
        return row("wait", f"merge state {e.get('merge_state') or 'unknown'}, checks {e.get('checks') or 'none'}")
    if e.get("checks") != "SUCCESS":
        return row("amr", "no check ran on it, so nothing proves it is green (§ 12.1)")
    if str(rec.get("repo") or "").lower() in {str(r).lower() for r in cfg["never_merge"]}:
        return row("amr", "this repo's own rules keep every merge with the maintainer")
    if not trusted_author(rec.get("author") or "", is_bot, who):
        return row("amr", f"its author ({rec.get('author') or 'unknown'}) is not on the trusted list")
    return row("merge", "mergeable, checks SUCCESS, no gate label, no governing document")


def dispose_issue(item: dict, in_pr: dict[str, str], cfg: dict, gate_cfg: dict, now: datetime) -> dict | None:
    """One open issue's disposition, or None for an epic (its sub-issues are the work)."""
    lower = {str(x).lower() for x in item.get("labels") or []}
    if lower & {str(x).lower() for x in cfg["skip_issue_labels"]}:
        return None
    key = f"{item.get('repo')}#{item.get('number')}"
    held = _held(lower, gate_cfg, ["agent:blocked"])
    idle = _days(item.get("updated_at"), now) or 0
    if held:
        return _row(item, "issue", "amr", "labelled " + ", ".join(held), now)
    if key in in_pr:
        return _row(item, "issue", "carry", f"{in_pr[key]} is open for it", now)
    if idle >= int(cfg["stale_days"]) and not lower & {str(x).lower() for x in cfg["keep_issue_labels"]}:
        return _row(item, "issue", "stale", f"untouched for {idle} days, no priority above P2", now)
    return _row(item, "issue", "carry", "open", now)


def pm_pr_record(item: dict, state: dict | None) -> dict:
    """A PM-model pull request in the decision index's record shape, for a run the index could not
    serve. The head branch comes with it, so the release rule still fires."""
    state = state or {}
    enrich = {"mergeable": state.get("mergeable"), "merge_state": state.get("merge_state"), "review": state.get("review"),
              "checks": state.get("ci")} if state else {}
    return {**item, "type": "pr", "draft": bool(item.get("draft") or state.get("draft")), "enrich": enrich,
            "head": state.get("head"), "bot": _base(item.get("author") or "")[1]}


def build(index: dict | None, model: dict | None, fleet: dict, now: datetime,
          classify: Callable[[dict, dict], tuple[list, list, dict]] | None = None, gate_cfg: dict | None = None) -> dict:
    """Every open pull request and issue with its disposition. `index` is the decision index (all open
    pull requests, with merge state); `model` is the PM review's (all open issues). Either may be
    missing: the result says which source it rests on. When the index answers, it is the only source
    of pull requests (the model's are older, and one the index lacks has usually closed since); the
    model's pull requests are used only when there is no index."""
    cfg = config(fleet)
    gate_cfg = gate_cfg or {"labels": GATE_LABELS}
    who = trust(fleet)
    rows: list[dict] = []
    seen: set[str] = set()
    have_index = bool((index or {}).get("prs"))

    def kinds_of(rec: dict) -> tuple[list, dict]:
        kinds, why, _ = classify(rec, gate_cfg) if classify else ([], [], {})
        return kinds, dict(zip(kinds, why))

    for rec in ((index or {}).get("prs") or {}).values():
        kinds, why = kinds_of(rec)
        row = dispose_pr(rec, kinds, why, cfg, gate_cfg, who, now)
        rows.append(row)
        seen.add(row["key"])
    repos = [r for r in (model or {}).get("repos") or [] if not r.get("archived")]
    in_pr: dict[str, str] = {}
    for repo in repos:  # first, every "closes" in the fleet: a pull request can close another repo's issue
        for number, state in (repo.get("prs") or {}).items():
            for ref in (state or {}).get("closes") or []:
                in_pr[str(ref)] = f"{repo.get('repo')}#{number}"
    for repo in repos:
        prs = repo.get("prs") or {}
        for item in repo.get("items") or []:
            item = {**item, "private": bool(repo.get("private"))}
            if str(item.get("kind", "")).startswith("p"):
                key = f"pr:{item.get('repo')}#{item.get('number')}"
                if key in seen or have_index:
                    continue
                rec = pm_pr_record(item, prs.get(str(item.get("number"))) or prs.get(item.get("number")))
                kinds, why = kinds_of(rec)
                rows.append(dispose_pr(rec, kinds, why, cfg, gate_cfg, who, now))
                seen.add(key)
            elif not repo.get("private"):
                row = dispose_issue(item, in_pr, cfg, gate_cfg, now)
                if row:
                    rows.append(row)
    return tally({"schema": SCHEMA, "generated_at": now.isoformat(), "rows": rows, "scanned": False,
                  "sources": {"index": have_index, "model": bool((model or {}).get("repos"))}})


def tally(result: dict) -> dict:
    """Sort the rows and count them. Called again after the gate scan moves rows between dispositions."""
    rows = result["rows"]
    rows.sort(key=lambda r: (ORDER.index(r["disposition"]), r["type"] != "pr", str(r["repo"]).lower(), -(r["number"] or 0)))
    result["counts"] = {d: {"pr": sum(r["disposition"] == d and r["type"] == "pr" for r in rows),
                            "issue": sum(r["disposition"] == d and r["type"] == "issue" for r in rows)} for d in ORDER}
    result["open"] = {"pr": sum(r["type"] == "pr" for r in rows), "issue": sum(r["type"] == "issue" for r in rows)}
    return result


# ---- the decision index, as the routine reads it ----------------------------------------------

def read_index(root: Path, offline: bool = False) -> tuple[dict | None, Callable | None, dict | None, str]:
    """(index, classify, the index's own config, a note on how fresh it is). The decision index reads
    every open pull request across the owners in a handful of GraphQL queries; offline, or when GitHub
    cannot answer, the last index on disk is used and the note says how old it is."""
    import sys
    sys.path.insert(0, str(core.ROOT / "tools" / "console"))
    try:
        import decision_index as di
    except ImportError as exc:
        return None, None, None, f"the decision index could not be loaded ({exc})"
    cfg = di.load_config(root)
    note = "read from disk, no GitHub call"
    if not offline:
        try:
            doc = di.queue(root, refresh="force", limit=0, budget_s=cfg.get("refresh_budget_s") or 60)
            note = f"{doc.get('status')}, {doc.get('source')}" + ("; " + doc["warnings"][0] if doc.get("warnings") else "")
        except Exception as exc:  # a failed refresh never stops the run: the index on disk still answers
            note = f"the refresh failed ({type(exc).__name__}: {str(exc)[:120]}); using the index on disk"
    index, set_aside = di.load_index(di.index_path(root))
    if set_aside:
        return None, di.classify, cfg, set_aside
    return index, di.classify, cfg, note


# ---- lists a person can act on ------------------------------------------------------------------

def list_files(result: dict, folder: Path) -> dict[str, str]:
    """One `owner/repo number` list per disposition that needs someone, so a loop in a terminal can walk
    it. Returns {disposition: path} for the lists written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = {}
    for d in ("merge", "ratify", "amr", "resolve", "fix", "stale"):
        rows = [r for r in result["rows"] if r["disposition"] == d and r["type"] == "pr"]
        if rows:
            path = folder / f"{d}-prs.txt"
            path.write_text("".join(f"{r['repo']} {r['number']}\n" for r in rows))
            written[d] = str(path)
    return written


def render(result: dict, lists: dict[str, str], cap: int = 12) -> list[str]:
    """The report's close-out section."""
    o, lines = result["open"], ["## Close-out", ""]
    src = result["sources"]
    if not src["index"]:
        lines += ["> The decision index could not be read, so pull requests come from the PM review's older merge state.", ""]
    lines += [f"{o['pr']} open pull requests and {o['issue']} open issues, each with one disposition.", ""]
    if result.get("note"):
        lines += [f"The decision index: {result['note']}.", ""]
    if result["counts"]["merge"]["pr"]:
        lines += ["Ready to merge means every gate a machine can read has passed, read from live GitHub at this run."
                  if result.get("scanned") else
                  "This run did not read the candidates' changed files, so ready to merge here is only mechanical: "
                  "mergeable and green, with the path gate (§ 12.3) still to read. A run that is not offline reads it.", ""]
    lines += ["| Disposition | PRs | Issues | Who moves it | What happens |", "| --- | ---: | ---: | --- | --- |"]
    for d in ORDER:
        c = result["counts"][d]
        if c["pr"] or c["issue"]:
            meta = DISPOSITIONS[d]
            lines.append(f"| {meta['title']} | {c['pr']} | {c['issue']} | {meta['who']} | {meta['next']} |")
    for d in ORDER:
        if d == "carry":
            continue
        rows = [r for r in result["rows"] if r["disposition"] == d]
        if not rows:
            continue
        lines += ["", f"### {DISPOSITIONS[d]['title']} ({len(rows)})", ""]
        if d in lists:
            lines += [f"List: `{lists[d]}`", ""]
        lines += [f"- [{r['repo']}#{r['number']}]({r['url']}): {r['title']} ({r['why']})" for r in rows[:cap]]
        if len(rows) > cap:
            lines.append(f"- and {len(rows) - cap} more")
    return lines + [""]


# ---- the live gate: everything § 12.1 and § 12.3 ask that a machine can read ---------------------

PR_FIELDS = ("number,state,isDraft,title,mergeable,mergeStateStatus,reviewDecision,headRefOid,headRefName,baseRefName,"
             "labels,files,statusCheckRollup,author,updatedAt")


def live_pr(repo: str, number: int, runner: Callable = core.run) -> dict | None:
    r = runner(["gh", "pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS], timeout=60)
    try:
        doc = json.loads(r.stdout) if r.returncode == 0 else None
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def repo_facts(repo: str, runner: Callable = core.run) -> dict:
    """What the routine must know about a repo before it merges there: whether it accepts a merge
    commit, and which branch is the default. A value that could not be read is None, and None holds."""
    r = runner(["gh", "api", f"repos/{repo}", "--jq", "{allow_merge_commit, default_branch, private}"], timeout=30)
    try:
        doc = json.loads(r.stdout) if r.returncode == 0 else {}
    except json.JSONDecodeError:
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    allow, branch, private = doc.get("allow_merge_commit"), doc.get("default_branch"), doc.get("private")
    return {"allow_merge_commit": allow if isinstance(allow, bool) else None,
            "default_branch": branch if isinstance(branch, str) and branch else None,
            "private": private if isinstance(private, bool) else None}


def checks_green(rollup: Any) -> tuple[bool, str]:
    """Every check finished, none failed, and at least one succeeded. A skipped or neutral check
    does not fail the pull request, as on GitHub, but it proves nothing either: a pull request whose
    every check was skipped is not green. Anything still running is not green."""
    rows = [c for c in (rollup or []) if isinstance(c, dict)]
    if not rows:
        return False, "no check ran on it"
    passed = 0
    for c in rows:
        name = c.get("name") or c.get("context") or "a check"
        if c.get("__typename") == "StatusContext" or "state" in c and "conclusion" not in c:
            if str(c.get("state") or "").upper() != "SUCCESS":
                return False, f"{name} is {c.get('state') or 'unknown'}"
            passed += 1
            continue
        if str(c.get("status") or "").upper() != "COMPLETED":
            return False, f"{name} has not finished"
        conclusion = str(c.get("conclusion") or "").upper()
        if conclusion not in ("SUCCESS", "SKIPPED", "NEUTRAL"):  # an empty or unknown conclusion is not a pass
            return False, f"{name} concluded {c.get('conclusion') or 'unknown'}"
        passed += conclusion == "SUCCESS"
    if not passed:
        return False, "no check succeeded on it: every one was skipped"
    return True, f"{len(rows)} checks green"


def gate_patterns(cfg: dict, repo: str) -> list[tuple[re.Pattern, str]]:
    """The gated paths for a repo, compiled. A pattern that does not compile raises: a gate that
    cannot be read holds everything (the caller turns the error into a hold)."""
    own = next((v for k, v in (cfg.get("repo_gate_paths") or {}).items() if str(k).lower() == repo.lower()), [])
    return ([(re.compile(str(p), re.I), "the review gate holds (§ 12.3)") for p in cfg["gate_paths"]]
            + [(re.compile(str(p), re.I), "this repo's own content gate holds (§ 12.3)") for p in own or []])


def gate_verdict(pr: dict, cfg: dict, gate_cfg: dict, who: dict, repo: str = "", facts: dict | None = None) -> tuple[str, str] | None:
    """Why a live pull request is not ready for an agent to merge, as (where it belongs, why), or None
    when nothing holds it. This is the whole of § 12.1 and § 12.3 that a machine can read, applied to
    what GitHub says now and to nothing remembered: anything it cannot read counts as a reason.
    `gone` means the pull request is no longer open. `facts` is `repo_facts`; the scan always passes
    it. One limit no read removes: a required check that has not started yet has no entry to read."""
    state = pr.get("state")
    if state in ("MERGED", "CLOSED"):
        return "gone", f"it is {state.lower()}"
    if state != "OPEN":
        return "wait", "its state could not be read"
    labels, head = pr.get("labels"), pr.get("headRefName")
    if not isinstance(pr.get("isDraft"), bool) or not isinstance(head, str) or not head \
            or not isinstance(labels, list) or not all(isinstance(l, dict) and isinstance(l.get("name"), str) for l in labels):
        return "amr", "its labels, draft state or head branch could not be read"
    if pr["isDraft"]:
        return "carry", "it is a draft"
    held = _held([l["name"] for l in labels], gate_cfg)
    if held:
        return "amr", "labelled " + ", ".join(held)
    if repo.lower() in {str(r).lower() for r in cfg["never_merge"]}:
        return "amr", "this repo's own rules keep every merge with the maintainer"
    if any(head.startswith(prefix) for prefix in cfg["release_heads"]):
        return "amr", "a release pull request: merging it tags and publishes the release"
    if facts is not None:
        if facts.get("private") is not False:
            return "amr", "a private repo, or one whose visibility could not be read: the routine never acts on one"
        if facts.get("allow_merge_commit") is not True:
            return "amr", ("this repo does not allow merge commits, and the routine merges no other way (§ 12.2)"
                           if facts.get("allow_merge_commit") is False else "this repo's merge settings could not be read")
        if not facts.get("default_branch") or pr.get("baseRefName") != facts["default_branch"]:
            return "amr", f"it targets {pr.get('baseRefName') or 'an unknown branch'}, not the repo's default branch"
    author = pr.get("author") if isinstance(pr.get("author"), dict) else {}
    login, is_bot = str(author.get("login") or ""), bool(author.get("is_bot"))
    if not trusted_author(login, is_bot, who):
        return "amr", f"its author ({login or 'unknown'}) is not on the trusted list"
    name, marked = _base(login)
    if (is_bot or marked) and name in who["dependabot"]:
        bump = major_bump(str(pr.get("title") or ""))
        if bump is None:
            return "amr", "a Dependabot update that states no versions, so a major bump cannot be ruled out"
        if bump:
            return "amr", "a major Dependabot bump"
    files = pr.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, dict) and f.get("path") for f in files):
        return "amr", "its changed files could not be read"
    if len(files) >= 100:
        return "amr", "it changes 100 files or more, past what one read returns"
    if not all(isinstance(f.get("changeType"), str) and f["changeType"] for f in files):
        return "amr", "how its files changed could not be read, so a rename cannot be ruled out"
    moved = [f["path"] for f in files if f["changeType"].upper() in ("RENAMED", "COPIED")]
    if moved:
        return "amr", f"it renames or copies {moved[0]}, and the path it came from cannot be read"
    try:
        patterns = gate_patterns(cfg, repo)
    except re.error as exc:
        return "amr", f"a gated path in the config does not compile ({exc}), so nothing can be called ready"
    for f in files:
        for rx, whose in patterns:
            if rx.search(str(f["path"])):
                return "amr", f"it changes {f['path']}, which {whose}"
    if pr.get("reviewDecision") == "CHANGES_REQUESTED":
        return "fix", "changes were requested"
    if pr.get("mergeable") == "CONFLICTING":
        return "resolve", "conflicts with its base"
    if pr.get("mergeable") != "MERGEABLE" or pr.get("mergeStateStatus") not in ("CLEAN", "HAS_HOOKS"):
        return "wait", f"merge state {pr.get('mergeStateStatus') or 'unknown'} ({pr.get('mergeable') or 'unknown'})"
    ok, why = checks_green(pr.get("statusCheckRollup"))
    if ok:
        return None
    return ("amr" if why.startswith("no check") else "fix" if "concluded" in why else "wait"), why


def gate_scan(result: dict, fleet: dict, gate_cfg: dict, runner: Callable = core.run, workers: int = 6) -> dict:
    """Read every merge candidate from live GitHub once and move the held ones where they belong. The
    index knows merge state and checks but not which files a pull request changes, so until this runs
    "ready" only means mechanically ready. After it, a `merge` row has passed every gate a machine can
    read, as of the scan. Whoever merges it reads it again first (§ 12.1): the scan is a list, not a
    permission."""
    cfg, who = config(fleet), trust(fleet)
    rows = [r for r in result["rows"] if r["disposition"] == "merge" and r["type"] == "pr"]
    with ThreadPoolExecutor(workers) as pool:
        repos = sorted({row["repo"] for row in rows})
        facts = dict(zip(repos, pool.map(lambda repo: repo_facts(repo, runner), repos)))

        def one(row: dict) -> tuple[dict, tuple[str, str] | None]:
            pr = live_pr(row["repo"], row["number"], runner)
            if pr is None:
                return row, ("wait", "it could not be read from GitHub, so its changed files are unknown")
            return row, gate_verdict(pr, cfg, gate_cfg, who, row["repo"], facts[row["repo"]])
        verdicts = list(pool.map(one, rows))
    gone = set()
    for row, verdict in verdicts:
        if verdict is None:
            continue
        if verdict[0] == "gone":
            gone.add(row["key"])
        else:
            row.update(disposition=verdict[0], why=verdict[1])
    result["rows"] = [r for r in result["rows"] if r["key"] not in gone]
    result["scanned"] = True
    return tally(result)

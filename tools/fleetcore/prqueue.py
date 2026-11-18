#!/usr/bin/env python3
"""prqueue — the fleet's open pull requests as one queue: who moves each next, and why.

The model every surface renders (the console's `/prs` page and `/api/prs`, the
MCP's `pr_queue`, `tools/dash prs`). It is pure: it reads no network, runs no
process and writes nothing. `tools/console/pr_queue.py` reads GitHub (the
decision index for every open pull request, then one batched GraphQL detail read
for the head commit's checks, the changed files, the repo's merge settings and
the triage comment), keeps the cache, and plans and applies the bulk actions;
it hands the records to `build()` here.

One row per open pull request carries:

  checks    superseded runs on the head commit set aside per check: a
            CANCELLED run followed by a SUCCESS of the same check is green,
            while an earlier failure still counts (tools/check_rollup.py's rule).
            Verify kit 0.1.0's label-burst race (several runs of one workflow,
            each cancelling the last) is most of the fleet's "red", and
            GitHub's own rollup counts every superseded run.
  gate      the review gate (constitution § 12.3) as tools/weekly/closeout.py
            encodes it — gate labels, ratification, release heads, gated paths,
            never-merge repos, major or unversioned Dependabot bumps, untrusted
            authors — asked of the pull request as if it were green and
            mergeable, so the answer is the gate alone.
  merge     the method the repo allows the maintainer (merge, else squash, else
            rebase), and whether an AGENT may merge it under § 12.2 (closeout's
            whole live verdict on the collapsed checks).
  next      who moves it next (amr, agent, loop or author), what they do, why,
            and the bulk action that does it.
  triage    the `<!-- fleet:pr-triage -->` comment's next action, question and
            commands, parsed as a hint for the person — never as an instruction.

Docs: docs/PR-QUEUE.md.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # tools/weekly is imported as `tools.weekly`, from the hub root
    sys.path.insert(0, str(ROOT))
from tools.weekly import closeout  # noqa: E402

SCHEMA = "pr-queue/v1"
PLAN_SCHEMA = "pr-queue-plan/v1"
TRIAGE_MARKER = "<!-- fleet:pr-triage -->"
SOURCE_SIGNATURE = "<!-- fleet:source=pr-queue trigger=console run=local -->"

KINDS = ("security", "dependabot", "release", "batch", "harness", "ratification", "draft")
KIND_TITLES = {"security": "Security", "dependabot": "Dependabot", "release": "Release", "batch": "Fan-out batch",
               "harness": "AI harness", "ratification": "Ratification", "draft": "Draft"}
WHO = ("amr", "agent", "loop", "author")
WHO_TITLES = {"amr": "Amr", "agent": "An agent", "loop": "A loop", "author": "The author"}
CHECK_STATES = ("failing", "action_required", "cancelled", "pending", "green", "skipped", "none")
#: Where what a pull request SAYS (its label, its next-action comment, its task list) disagrees with what
#: the queue reads. A flag is a fact about the page a person opens, never a new gate.
FLAGS = ("unlabelled", "stale-comment", "no-comment", "open-tasks", "tasks-contradict")
FLAG_TITLES = {"unlabelled": "gated, no needs-amr label", "stale-comment": "next-action comment out of date",
               "no-comment": "no next-action comment", "open-tasks": "unticked tasks in the description",
               "tasks-contradict": "an unticked CI task while every check passes"}
GATE_LABEL = "needs-amr"

DEFAULTS: dict[str, Any] = {
    "ttl_s": 600,              # a detail record older than this, or read for an older updated_at, is read again
    "budget_s": 20,            # the wall clock of one /api/prs answer
    "refresh_budget_s": 90,    # `tools/dash prs refresh`
    "detail_batch": 5,         # pull requests per detail query: the checks and files make each one heavy
    "concurrency": 6,
    "max_targets": 50,         # pull requests per plan (§ 11.5 caps a plan at 50 ops)
    "batch_min_repos": 2,      # a head branch open in this many repos is a fan-out batch
    "rerun_wait_s": 900,       # how long a re-run may take before the next one on the same pull request starts
    "harness_paths": [],       # ADDS to HARNESS_PATHS
    "merge": {"enabled": False},
    "close": {"enabled": False},
    "agent": {"enabled": False, "model": "", "max_turns": 40, "usd": 2.0, "max_prs": 5, "timeout_s": 1800},
    "repo_rules": {},
}
#: What makes a pull request an AI-harness change: the files an agent reads as its instructions or runs as.
HARNESS_PATHS = [
    r"(^|/)\.claude/",
    r"(^|/)(CLAUDE|AGENTS)\.md$",
    r"(^|/)\.mcp\.json$",
    r"(^|/)\.github/(agents|prompts|instructions|copilot-instructions\.md)",
    r"(^|/)\.github/workflows/[^/]*(claude|copilot|agent|ai[-_]|evolv|scout|doctor)[^/]*\.ya?ml$",
    r"(^|/)tools/jev/steps/",
]
HARNESS_HEADS = re.compile(r"^(ci/harness|chore/agent-context|ci/evolve-lane|chore/harness)", re.I)
SECURITY_TEXT = re.compile(r"\bsecurity\b|\bCVE-\d{4}-\d+|\bGHSA-[\w-]+|\bvulnerab", re.I)
RELEASE_TITLE = re.compile(r"^chore(\([^)]*\))?: release\b|^release[: ]", re.I)
#: Heads a batch is never made of: they repeat by convention, not because one change was fanned out.
NOT_BATCH = re.compile(r"^(dependabot/|release-please--|renovate/|main$|master$|dev$|develop$|gh-pages$)", re.I)
BOT_CI_AUTHORS = {"github-actions", "app/github-actions"}

FAILING = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ERROR"}
CANCELLED = {"CANCELLED", "STALE"}
PASSING = {"SUCCESS"}
NEUTRAL = {"SKIPPED", "NEUTRAL"}


def _listed(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, (list, tuple, set)) else []


def _merged(base: dict, over: Any) -> dict:
    out = json.loads(json.dumps(base))
    for key, value in (over or {}).items() if isinstance(over, dict) else ():
        out[key] = _merged(base[key], value) if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return out


def config(fleet: dict) -> dict:
    """`_data/fleet.yml` `pr_queue:` over DEFAULTS, plus the close-out's gate config and trust list it
    reuses. A switch that is not literally `true` is off."""
    cfg = _merged(DEFAULTS, (fleet or {}).get("pr_queue"))
    for key in ("merge", "close", "agent"):
        cfg[key] = cfg[key] if isinstance(cfg.get(key), dict) else dict(DEFAULTS[key])
        cfg[key]["enabled"] = cfg[key].get("enabled") is True
    rules = cfg.get("repo_rules")
    cfg["repo_rules"] = {str(k).lower(): v for k, v in rules.items() if isinstance(v, dict)} if isinstance(rules, dict) else {}
    cfg["harness_paths"] = list(dict.fromkeys([*HARNESS_PATHS, *_listed(cfg.get("harness_paths"))]))
    for key, lo, hi in (("ttl_s", 30, 86400), ("budget_s", 1, 120), ("refresh_budget_s", 1, 120), ("detail_batch", 1, 20),
                        ("concurrency", 1, 16), ("max_targets", 1, 50), ("batch_min_repos", 2, 50), ("rerun_wait_s", 0, 3600)):
        try:
            cfg[key] = min(hi, max(lo, type(DEFAULTS[key])(cfg[key])))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    cfg["closeout"] = closeout.config(fleet or {})
    cfg["trust"] = closeout.trust(fleet or {})
    return cfg


def rule(cfg: dict, repo: str, key: str, default: Any = None) -> Any:
    """One repo's own rule from `pr_queue.repo_rules` (owner/name, any case)."""
    return (cfg.get("repo_rules") or {}).get(str(repo).lower(), {}).get(key, default)


# --------------------------------------------------------------------------- #
# Checks: one row per check, the latest run of it on the head commit
# --------------------------------------------------------------------------- #
def _check_state(kind: str, status: str, conclusion: str) -> str:
    if kind == "status":
        return {"SUCCESS": "green", "PENDING": "pending", "EXPECTED": "pending"}.get(conclusion, "failing")
    if status and status != "COMPLETED":
        return "pending"
    if conclusion in PASSING:
        return "green"
    if conclusion in NEUTRAL:
        return "skipped"
    if conclusion in CANCELLED:
        return "cancelled"
    if conclusion == "ACTION_REQUIRED":
        return "action_required"
    return "failing"  # FAILURE, TIMED_OUT, STARTUP_FAILURE and anything unknown: not a pass


def _workflow_of(c: dict) -> str:
    if c.get("workflowName"):  # `gh pr view --json statusCheckRollup`
        return str(c["workflowName"])
    run = ((c.get("checkSuite") or {}).get("workflowRun") or {})  # the GraphQL rollup
    return str(((run.get("workflow") or {}).get("name")) or "")


def _run_id_of(c: dict) -> int | None:
    run = ((c.get("checkSuite") or {}).get("workflowRun") or {})
    if isinstance(run.get("databaseId"), int):
        return run["databaseId"]
    m = re.search(r"/actions/runs/(\d+)", str(c.get("detailsUrl") or c.get("targetUrl") or ""))
    return int(m.group(1)) if m else None


def collapse_checks(contexts: Iterable[dict] | None) -> list[dict]:
    """Every check on the head commit, with superseded runs set aside. A check run's key is its workflow
    and its name, a status context's its context; the latest is the one that finished (or started)
    last and always counts. An earlier run is set aside only when it cannot change the verdict: a
    CANCELLED (or STALE) run, or a pass, followed by a later run of the same check. An earlier failure
    still counts even when a later run passed — the rule tools/check_rollup.py applies in the close-out
    (bamr87/bamr87#862), so the queue is never looser than the gate. `superseded` counts the runs set
    aside; a kept earlier run carries `earlier: true`."""
    groups: dict[tuple, list[dict]] = {}
    for order, c in enumerate(x for x in contexts or [] if isinstance(x, dict)):
        is_status = c.get("__typename") == "StatusContext" or ("context" in c and "conclusion" not in c and "name" not in c)
        if is_status:
            name, key_kind = str(c.get("context") or "a status"), "status"
            status, conclusion = "COMPLETED", str(c.get("state") or "").upper()
            at = str(c.get("createdAt") or "")
            workflow = ""
        else:
            name, key_kind = str(c.get("name") or "a check"), "check"
            status, conclusion = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
            at = str(c.get("completedAt") or c.get("startedAt") or "")
            if at.startswith("0001-"):  # gh prints the zero time for a run that has not finished
                at = str(c.get("startedAt") or "")
            workflow = _workflow_of(c)
        row = {"name": name, "workflow": workflow, "kind": key_kind, "status": status, "conclusion": conclusion,
               "state": _check_state(key_kind, status, conclusion), "at": at or None,
               "url": c.get("detailsUrl") or c.get("targetUrl") or None, "run_id": _run_id_of(c),
               "event": ((c.get("checkSuite") or {}).get("workflowRun") or {}).get("event"), "_order": order}
        groups.setdefault((key_kind, workflow.lower(), name.lower()), []).append(row)
    rows: list[dict] = []
    for runs in groups.values():
        runs.sort(key=lambda r: (r["at"] or "", r["_order"]))
        last = runs[-1]
        kept = [dict(r, earlier=True) for r in runs[:-1] if r["state"] not in ("cancelled", "green", "skipped")]
        last["superseded"] = len(runs) - 1 - len(kept)
        rows += [last, *kept]
    rows.sort(key=lambda r: (CHECK_STATES.index(r["state"]), r["workflow"].lower(), r["name"].lower(), bool(r.get("earlier"))))
    return [{k: v for k, v in r.items() if v is not None and k != "_order"} for r in rows]


def checks_summary(collapsed: list[dict], rollup: str | None = None) -> dict:
    """The collapsed checks as one state, and the names in each. `false_red` says GitHub's own rollup is
    red only because of runs a later run superseded."""
    by: dict[str, list[str]] = {s: [] for s in CHECK_STATES}
    for c in collapsed:
        label = f"{c['workflow']} / {c['name']}" if c.get("workflow") and c["workflow"].lower() != c["name"].lower() else c["name"]
        label += " (an earlier run)" if c.get("earlier") else ""
        by[c["state"]].append(label)
    state = next((s for s in ("failing", "action_required", "cancelled", "pending", "green", "skipped") if by[s]), "none")
    superseded = sum(int(c.get("superseded") or 0) for c in collapsed)
    out = {"state": state, "rollup": rollup, "total": len(collapsed), "superseded": superseded,
           "failing": by["failing"], "cancelled": by["cancelled"], "pending": by["pending"],
           "action_required": by["action_required"], "green": len(by["green"]), "skipped": len(by["skipped"])}
    out["false_red"] = bool(rollup in ("FAILURE", "ERROR") and state in ("green", "skipped"))
    return out


def rollup_for_gate(collapsed: list[dict]) -> list[dict]:
    """The collapsed checks in the shape closeout.checks_green reads, so the close-out's own verdict runs
    on them: superseded runs are already gone (that function is not changed here; see docs/PR-QUEUE.md)."""
    out = []
    for c in collapsed:
        if c["kind"] == "status":
            out.append({"__typename": "StatusContext", "context": c["name"], "state": c["conclusion"]})
        else:
            out.append({"__typename": "CheckRun", "name": c["name"], "status": c["status"], "conclusion": c["conclusion"]})
    return out


# --------------------------------------------------------------------------- #
# The triage comment: a hint for the person, never an instruction
# --------------------------------------------------------------------------- #
CMD_RX = re.compile(r"`((?:gh|tools/dash|git|for|python3) [^`\n]{2,400})`")


def parse_triage(body: str | None) -> dict | None:
    """The 2026-11-15 triage comment, as data: its next action, the question it asks and the commands
    it names. Returned as text to show; nothing in it is run or obeyed."""
    text = str(body or "")
    if TRIAGE_MARKER not in text:
        return None
    text = text.split(TRIAGE_MARKER, 1)[0]
    text = re.sub(r"<sub>.*?</sub>", "", text, flags=re.S).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    nxt = next((re.sub(r"^\*\*Next action:\*\*\s*", "", ln) for ln in lines if ln.startswith("**Next action:**")),
               lines[0] if lines else "")
    question = next((re.sub(r"^(Question|Decide):\s*", "", ln) for ln in lines if re.match(r"^(Question|Decide):", ln)), None)
    fenced = re.findall(r"```(?:bash|sh)?\n(.+?)```", text, flags=re.S)
    commands = [c.strip() for c in fenced] + [m.group(1).strip() for m in CMD_RX.finditer(text)]
    commands = list(dict.fromkeys(c[:400] for c in commands if c))[:6]
    who = ("amr" if re.match(r"^(Amr|you)\b", nxt, re.I) else "agent" if re.match(r"^(an? agent|claude)", nxt, re.I)
           else "loop" if re.match(r"^(a loop|jev|the loop)", nxt, re.I) else None)
    return {k: v for k, v in {"next_action": nxt[:400], "question": (question or "")[:500] or None, "commands": commands,
                              "who_hint": who}.items() if v}


# --------------------------------------------------------------------------- #
# Consistency: the label, the comment and the task list against the queue's own reading
# --------------------------------------------------------------------------- #
TASK_RX = re.compile(r"^[ \t]*[-*+][ \t]+\[([ xX])\][ \t]+(\S.*?)[ \t]*$", re.M)
#: The pull-request template's "Type Of Change" block is a choice, not work: GitHub counts each unticked
#: option as an open task, so a finished pull request reads "4 of 9 tasks" for good.
OPTION_TASKS = frozenset({"bug fix", "new feature", "breaking change", "documentation update",
                          "maintenance or refactor", "test improvement"})
CI_TASK_RX = re.compile(r"\bci is green\b|\btests? pass(es)?\b|\bchecks? (pass|are green)\b", re.I)
_TASK_TEXT = re.compile(r"[*_`]")
_MERGE_WORD = re.compile(r"\bmerges?\b", re.I)
_CONFLICT_WORD = re.compile(r"\bconflicts?\b|\brebase\b|\bupdate (the )?branch\b", re.I)
_FAILING_WORD = re.compile(r"\bfailing\b|\bfix (the |its )?(ci|checks?)\b|\bred checks?\b", re.I)


def tasks_of(body: str | None) -> dict | None:
    """The description's task list: `total` and `done` as GitHub counts them, `open` without the
    template's unticked options, the first open items, and whether one of them says CI is not green
    yet. None when the description has no checkbox."""
    found = TASK_RX.findall(str(body or ""))
    if not found:
        return None
    opened = [_TASK_TEXT.sub("", text).strip() for mark, text in found if mark == " "]
    options = [t for t in opened if t.lower().rstrip(".") in OPTION_TASKS]
    work = [t for t in opened if t.lower().rstrip(".") not in OPTION_TASKS]
    return {"total": len(found), "done": len(found) - len(opened), "open": len(work), "options": len(options),
            "items": [t[:100] for t in work[:5]], "ci_open": any(CI_TASK_RX.search(t) for t in work)}


def label_of(gate: dict, labels: Iterable[str], detail: dict) -> dict:
    """§ 12.4: a gated pull request carries the needs-amr label. `missing` is a gated one that does not;
    `repo_has_label` False means the label cannot be added until the repo has it."""
    labelled = GATE_LABEL in set(labels or [])
    state = "labelled" if labelled else "missing" if gate.get("gated") and detail.get("read") else "not-needed"
    out: dict[str, Any] = {"state": state}
    has = (detail.get("repo") or {}).get("gate_label")
    if has is not None:
        out["repo_has_label"] = bool(has)
    return out


def comment_of(triage: dict | None, detail: dict, *, draft: bool, mergeable: str | None, checks_state: str) -> dict:
    """The next-action comment against the pull request today: `none`, `current`, or `stale` with each
    fact that contradicts it. Only facts decide; the wording of a hand-written comment is never judged."""
    if not triage:
        return {"state": "none"}
    said = str(triage.get("next_action") or "")
    commands = " ".join(triage.get("commands") or [])
    why = []
    if detail.get("head_at") and triage.get("updated_at") and str(detail["head_at"]) > str(triage["updated_at"]):
        why.append("commits were pushed after it was written")
    if "gh pr ready" in commands and not draft:
        why.append("it says mark it ready; it is ready")
    says_merge = "gh pr merge" in commands or bool(_MERGE_WORD.search(said))
    if says_merge and mergeable == "CONFLICTING":
        why.append("it says merge; the pull request conflicts with its base")
    if says_merge and checks_state == "failing":
        why.append("it says merge; a check is failing")
    if _CONFLICT_WORD.search(said) and mergeable == "MERGEABLE":
        why.append("it says resolve a conflict; there is none")
    if _FAILING_WORD.search(said) and checks_state in ("green", "skipped"):
        why.append("it says fix failing checks; they pass")
    return {"state": "stale", "why": why} if why else {"state": "current"}


def flags_of(label: dict, comment: dict, tasks: dict | None, checks_state: str, read: bool) -> list[str]:
    if not read:  # nothing was read, so nothing can be said to disagree
        return []
    out = []
    if label["state"] == "missing":
        out.append("unlabelled")
    if comment["state"] == "stale":
        out.append("stale-comment")
    if comment["state"] == "none":
        out.append("no-comment")
    if tasks and tasks["open"]:
        out.append("open-tasks")
    if tasks and tasks.get("ci_open") and checks_state == "green":
        out.append("tasks-contradict")
    return out


# --------------------------------------------------------------------------- #
# One row
# --------------------------------------------------------------------------- #
def _days(stamp: Any, now: datetime) -> int | None:
    try:
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (now - (at if at.tzinfo else at.replace(tzinfo=timezone.utc))).days)


def _base_login(login: str) -> str:
    return str(login or "").lower().removeprefix("app/").removesuffix("[bot]")


def kinds_of(rec: dict, detail: dict | None, cfg: dict, batch_heads: set[str], index_kinds: Iterable[str] = ()) -> list[str]:
    detail = detail or {}
    labels = [str(x).lower() for x in rec.get("labels") or []]
    head, title = str(rec.get("head") or ""), str(rec.get("title") or "")
    paths = [f.get("path") or "" for f in detail.get("files") or []]
    out = []
    if any("security" in lb for lb in labels) or SECURITY_TEXT.search(title) or SECURITY_TEXT.search(head) \
            or any(re.search(r"(^|/)SECURITY\.md$", p, re.I) for p in paths):
        out.append("security")
    if _base_login(rec.get("author") or "") in cfg["trust"]["dependabot"]:
        out.append("dependabot")
    if any(head.startswith(p) for p in cfg["closeout"]["release_heads"]) or RELEASE_TITLE.search(title):
        out.append("release")
    if head in batch_heads:
        out.append("batch")
    harness = [re.compile(p, re.I) for p in cfg["harness_paths"]]
    if any(rx.search(p) for p in paths for rx in harness) or HARNESS_HEADS.search(head) or "harness" in labels:
        out.append("harness")
    if "ratification" in set(index_kinds):
        out.append("ratification")
    if rec.get("draft"):
        out.append("draft")
    return out


def _gate_pr(rec: dict, detail: dict, *, live: bool, collapsed: list[dict]) -> dict:
    """A pull request in the shape `gh pr view --json` gives closeout.gate_verdict. `live=False` asks the
    gate alone: the pull request as if it were green, mergeable and not a draft."""
    files = detail.get("files")
    pr = {"state": "OPEN", "isDraft": bool(rec.get("draft")) if live else False, "headRefName": rec.get("head") or "",
          "baseRefName": rec.get("base"), "title": rec.get("title") or "",
          "labels": [{"name": str(x)} for x in rec.get("labels") or []],
          "author": {"login": rec.get("author") or "", "is_bot": bool(rec.get("bot"))},
          "files": [{"path": f.get("path"), "changeType": f.get("change")} for f in files] if isinstance(files, list) else None}
    if isinstance(files, list) and int(detail.get("files_total") or 0) > len(files):
        pr["files"] = None  # a read that did not return every file cannot rule a gated path out
    if live:
        e = rec.get("enrich") or {}
        pr.update(mergeable=detail.get("mergeable") or e.get("mergeable"),
                  mergeStateStatus=detail.get("merge_state") or e.get("merge_state"),
                  reviewDecision=detail.get("review") or e.get("review"), statusCheckRollup=rollup_for_gate(collapsed))
    else:
        pr.update(mergeable="MERGEABLE", mergeStateStatus="CLEAN", reviewDecision=None,
                  statusCheckRollup=[{"name": "gate-only", "status": "COMPLETED", "conclusion": "SUCCESS"}])
    return pr


def merge_method(repo_facts: dict | None) -> str | None:
    """The method the maintainer's merge uses: a merge commit where the repo allows one (§ 12.2), else the
    one method the repo allows (zer0-mistakes is squash only). None when nothing could be read."""
    f = repo_facts or {}
    for key, method in (("merge_commit", "merge"), ("squash", "squash"), ("rebase", "rebase")):
        if f.get(key) is True:
            return method
    return None


def gate_of(rec: dict, detail: dict, cfg: dict, index_kinds: Iterable[str] = ()) -> dict:
    """The review gate alone (§ 12.3, closeout.gate_verdict on the hypothetical green pull request)."""
    if not detail.get("read"):
        return {"gated": True, "reason": "its changed files have not been read yet, so the gate cannot be ruled out"}
    verdict = closeout.gate_verdict(_gate_pr(rec, detail, live=False, collapsed=[]), cfg["closeout"],
                                    {"labels": closeout.GATE_LABELS}, cfg["trust"], str(rec.get("repo") or ""))
    if verdict is None:
        if "ratification" in set(index_kinds):
            return {"gated": True, "reason": "it changes a governing document: only the maintainer merges it (§ 8)"}
        return {"gated": False, "reason": "no gate label, governing path, release head or repo rule holds it"}
    where, why = verdict
    if where == "amr":
        return {"gated": True, "reason": why}
    return {"gated": False, "reason": why}


def agent_merge_of(rec: dict, detail: dict, cfg: dict, collapsed: list[dict]) -> dict:
    """Whether an agent may merge it now under § 12.2 (merge commit only, public repo, default branch),
    by closeout's whole verdict on the collapsed checks. Always rechecked live before a merge."""
    if not detail.get("read"):
        return {"ok": False, "why": "not read yet"}
    repo = detail.get("repo") or {}
    facts = {"allow_merge_commit": repo.get("merge_commit"), "default_branch": repo.get("default_branch"),
             "private": repo.get("private")}
    verdict = closeout.gate_verdict(_gate_pr(rec, detail, live=True, collapsed=collapsed), cfg["closeout"],
                                    {"labels": closeout.GATE_LABELS}, cfg["trust"], str(rec.get("repo") or ""), facts)
    return {"ok": True, "why": "every gate a machine can read has passed (§ 12.1, § 12.3)"} if verdict is None \
        else {"ok": False, "why": verdict[1]}


def next_of(rec: dict, detail: dict, checks: dict, gate: dict, agent_merge: dict, cfg: dict, now: datetime) -> dict:
    """Who moves the pull request next, what they do and why, and the bulk action that does it (`act`)."""
    ref = f"{rec.get('repo')}#{rec.get('number')}"

    def nxt(who: str, action: str, why: str, act: str | None = None, command: str | None = None) -> dict:
        return {k: v for k, v in {"who": who, "action": action, "why": why, "act": act, "command": command}.items() if v}

    if not detail.get("read"):
        return nxt("loop", "read its checks and files", "the queue has not read this pull request's detail yet",
                   command="tools/dash prs refresh")
    e = rec.get("enrich") or {}
    mergeable = detail.get("mergeable") or e.get("mergeable")
    state = detail.get("merge_state") or e.get("merge_state")
    review = detail.get("review") or e.get("review")
    idle = _days(rec.get("updated_at"), now) or 0
    login = _base_login(rec.get("author") or "")
    if rec.get("draft"):
        if idle >= int(cfg["closeout"]["draft_stale_days"]):
            return nxt("amr", "close it, or say who finishes it", f"a draft untouched for {idle} days", "close")
        if checks["state"] == "failing":
            return nxt("agent", "fix the failing checks", "failing: " + ", ".join(checks["failing"][:3]), "agent")
        if checks["state"] in ("green", "skipped") and mergeable != "CONFLICTING":
            return nxt("amr", "mark it ready for review", "a draft whose checks pass", "ready",
                       f"gh pr ready {rec.get('number')} --repo {rec.get('repo')}")
        return nxt("author", "finish the draft", "a draft in progress")
    if mergeable == "CONFLICTING":
        return nxt("loop", "resolve the conflict (JEV)", "conflicts with its base (§ 12.7)", None,
                   f"tools/dash conflicts resolve --pr {ref}")
    if checks["state"] == "failing":
        return nxt("agent", "fix the failing checks", "failing: " + ", ".join(checks["failing"][:3]), "agent")
    if checks["state"] == "action_required":
        return nxt("amr", "approve the held workflow run", "a run waits for approval: "
                   + ", ".join(checks["action_required"][:3]))
    if checks["state"] == "cancelled":
        return nxt("agent", "re-run the cancelled checks", "cancelled with no later run: "
                   + ", ".join(checks["cancelled"][:3]), "rerun")
    if checks["state"] == "none" and login in BOT_CI_AUTHORS:
        return nxt("amr", "make CI run: push to it with FLEET_TOKEN, or close and reopen it",
                   "opened with GITHUB_TOKEN, which fires no workflow, so nothing ever checked it")
    if state == "BEHIND":
        return nxt("agent", "update the branch from its base", "behind its base, and the repo requires it up to date",
                   "update-branch")
    if review == "CHANGES_REQUESTED":
        return nxt("agent", "address the review comments", "changes were requested", "agent")
    if checks["state"] == "pending":
        return nxt("loop", "wait for the checks", "running: " + ", ".join(checks["pending"][:3]))
    if gate["gated"]:
        method = merge_method(detail.get("repo")) or "merge"
        return nxt("amr", "review and merge it", gate["reason"], "merge",
                   f"gh pr merge {rec.get('number')} --repo {rec.get('repo')} --{method}")
    if state == "BLOCKED":
        return nxt("amr", "review it: branch protection blocks the merge", "merge state BLOCKED (a required review?)")
    if state not in ("CLEAN", "HAS_HOOKS", "UNSTABLE"):
        return nxt("loop", "wait for GitHub to compute mergeability", f"merge state {state or 'unknown'}")
    if checks["state"] in ("none", "skipped"):
        return nxt("amr", "decide: nothing proves it green", "no check succeeded on it (§ 12.1)", "merge")
    if agent_merge["ok"]:
        return nxt("agent", "merge it (§ 12.2: merge commit, live recheck)", agent_merge["why"], "merge")
    return nxt("amr", "merge it", agent_merge["why"], "merge")


def row(rec: dict, detail: dict | None, cfg: dict, now: datetime, batch_heads: set[str],
        index_kinds: Iterable[str] = ()) -> dict:
    detail = detail or {}
    index_kinds = list(index_kinds)
    collapsed = collapse_checks(detail.get("contexts")) if detail.get("read") else []
    e = rec.get("enrich") or {}
    checks = checks_summary(collapsed, detail.get("rollup") or e.get("checks"))
    if not detail.get("read"):
        checks["state"] = {"FAILURE": "failing", "ERROR": "failing", "PENDING": "pending", "EXPECTED": "pending",
                           "SUCCESS": "green"}.get(str(e.get("checks") or ""), "none")
        checks["unread"] = True
    gate = gate_of(rec, detail, cfg, index_kinds)
    agent_merge = agent_merge_of(rec, detail, cfg, collapsed)
    triage = parse_triage((detail.get("triage") or {}).get("body"))
    if triage:
        triage.update({k: v for k, v in (("url", (detail.get("triage") or {}).get("url")),
                                          ("updated_at", (detail.get("triage") or {}).get("updated_at"))) if v})
    out = {
        "key": f"{rec.get('repo')}#{rec.get('number')}", "repo": rec.get("repo"), "number": rec.get("number"),
        "title": rec.get("title"), "url": rec.get("url"), "author": rec.get("author"), "bot": bool(rec.get("bot")),
        "draft": bool(rec.get("draft")), "private": bool(rec.get("private")), "labels": sorted(rec.get("labels") or []),
        "created_at": rec.get("created_at"), "updated_at": rec.get("updated_at"),
        "age_days": _days(rec.get("created_at"), now), "idle_days": _days(rec.get("updated_at"), now),
        "head": rec.get("head"), "base": rec.get("base"), "head_sha": detail.get("head_sha"),
        "mergeable": detail.get("mergeable") or e.get("mergeable"), "merge_state": detail.get("merge_state") or e.get("merge_state"),
        "review": detail.get("review") or e.get("review"), "files": detail.get("files_total") or e.get("files"),
        "checks": checks, "check_runs": collapsed,
        "kinds": kinds_of(rec, detail, cfg, batch_heads, index_kinds),
        "batch": rec.get("head") if rec.get("head") in batch_heads else None,
        "gate": gate, "merge_method": merge_method(detail.get("repo")), "agent_merge": agent_merge,
        "next": next_of(rec, detail, checks, gate, agent_merge, cfg, now),
        "triage": triage, "read": bool(detail.get("read")), "read_at": detail.get("read_at"),
        "review_threads": detail.get("unresolved_threads"),
    }
    tasks = detail.get("tasks") if isinstance(detail.get("tasks"), dict) else None
    label = label_of(gate, out["labels"], detail)
    comment = comment_of(triage, detail, draft=out["draft"], mergeable=out["mergeable"], checks_state=checks["state"])
    out.update(tasks=tasks, label=label, comment=comment,
               flags=flags_of(label, comment, tasks, checks["state"], out["read"]))
    return {k: v for k, v in out.items() if v is not None}


def batch_heads_of(records: Iterable[dict], min_repos: int) -> dict[str, list[str]]:
    """Head branches open in at least `min_repos` repos: one change fanned out (`chore/agent-context-kit`)."""
    repos: dict[str, set[str]] = {}
    for rec in records:
        head = str(rec.get("head") or "")
        if head and not NOT_BATCH.search(head):
            repos.setdefault(head, set()).add(str(rec.get("repo") or "").lower())
    return {h: sorted(r) for h, r in repos.items() if len(r) >= min_repos}


def build(records: Iterable[dict], details: dict[str, dict], cfg: dict, now: datetime,
          index_kinds: dict[str, list[str]] | None = None) -> dict:
    """Every open pull request as one row, the fan-out batches and the counts. `records` are the
    decision index's pull-request records; `details` the detail reads by record id."""
    records = [r for r in records if isinstance(r, dict) and r.get("repo") and r.get("number")]
    heads = batch_heads_of(records, cfg["batch_min_repos"])
    index_kinds = index_kinds or {}
    rows = [row(rec, details.get(rec.get("id") or "") or {}, cfg, now, set(heads), index_kinds.get(rec.get("id") or "", []))
            for rec in records]
    for r in rows:  # what each bulk action would do here, by the last read; the plan asks GitHub again
        r["applies"] = [a for a in ACTIONS if applies(a, r, cfg)[0]]
    rows.sort(key=lambda r: (WHO.index(r["next"]["who"]), not r["gate"]["gated"], str(r["repo"]).lower(), -int(r["number"])))
    batches = []
    for head, repos in sorted(heads.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        members = [r for r in rows if r.get("head") == head]
        batches.append({"head": head, "count": len(members), "repos": len(repos),
                        "green": sum(r["checks"]["state"] in ("green", "skipped") for r in members),
                        "gated": sum(r["gate"]["gated"] for r in members), "draft": sum(r["draft"] for r in members),
                        "keys": [r["key"] for r in members]})
    counts = {
        "total": len(rows),
        "who": {w: sum(r["next"]["who"] == w for r in rows) for w in WHO},
        "kinds": {k: sum(k in r["kinds"] for r in rows) for k in KINDS},
        "gated": sum(r["gate"]["gated"] for r in rows),
        "ungated": sum(not r["gate"]["gated"] for r in rows),
        "checks": {s: sum(r["checks"]["state"] == s for r in rows) for s in CHECK_STATES},
        "false_red": sum(bool(r["checks"].get("false_red")) for r in rows),
        "agent_mergeable": sum(bool(r["agent_merge"]["ok"]) for r in rows),
        "unread": sum(not r["read"] for r in rows),
        "triaged": sum(bool(r.get("triage")) for r in rows),
        "flags": {f: sum(f in r.get("flags", []) for r in rows) for f in FLAGS},
        "tasks": {"with": sum(bool(r.get("tasks")) for r in rows),
                  "done": sum((r.get("tasks") or {}).get("done", 0) for r in rows),
                  "total": sum((r.get("tasks") or {}).get("total", 0) for r in rows)},
        "repos_without_gate_label": len({r["repo"] for r in rows if (r.get("label") or {}).get("repo_has_label") is False}),
    }
    return {"schema": SCHEMA, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": rows, "batches": batches,
            "counts": counts, "actions": actions_view(cfg)}


# --------------------------------------------------------------------------- #
# The bulk actions: what each one does, and which rows it applies to
# --------------------------------------------------------------------------- #
ACTIONS: dict[str, dict[str, Any]] = {
    "ready": {"title": "Mark ready for review", "op": "prs-act", "writes": "the draft state",
              "governed": "§ 11.1 (draft state of a pull request)"},
    "update-branch": {"title": "Update branch from base", "op": "prs-act", "writes": "a merge commit of the base onto the head branch",
                      "governed": "§ 12.7 (a base merge with a merge commit, never a rebase or force-push)"},
    "rerun": {"title": "Re-run cancelled or failed checks", "op": "prs-act", "writes": "workflow re-runs, one at a time per pull request",
              "governed": "the console's GitHub page (re-run) · § 11.8"},
    "comment": {"title": "Post or update the next-action comment", "op": "prs-act",
                "writes": "one comment per pull request, edited in place by its marker",
                "governed": "§ 11.8 · § 19.2 (one comment, found by its marker)"},
    "needs-amr": {"title": "Add needs-amr", "op": "prs-act", "writes": "the needs-amr label",
                  "governed": "§ 11.1 (labels) · § 12.4 (the gate mechanism)"},
    "agent": {"title": "Dispatch a capped local Claude Code session", "op": "prs-agent", "spend": True,
              "writes": "one commit pushed to each pull request's branch, then needs-amr",
              "governed": "§ 10.9 (local first) · § 29 (registered agent local:pr-queue-agent) · § 12.7's gate on a model's change"},
    "close": {"title": "Close as superseded", "op": "prs-act", "writes": "the pull request's state, with a comment saying why",
              "governed": "not in § 11.1's allowlist for pull requests: behind pr_queue.close.enabled until an amendment says so",
              "switch": "close"},
    "merge": {"title": "Merge", "op": "prs-act", "writes": "a merge, by the repo's allowed method, matched to the head commit",
              "governed": "§ 11.2 says the console never merges, and § 12.2 lets an agent merge only ungated pull requests: "
                          "behind pr_queue.merge.enabled until an amendment says a merge the maintainer confirms in the "
                          "console is his own", "switch": "merge"},
}


def action_enabled(action: str, cfg: dict) -> tuple[bool, str]:
    meta = ACTIONS.get(action)
    if meta is None:
        return False, f"unknown action {action!r}"
    switch = meta.get("switch")
    if switch and not cfg[switch]["enabled"]:
        return False, f"off: _data/fleet.yml pr_queue.{switch}.enabled is false ({meta['governed']})"
    if action == "agent" and not cfg["agent"]["enabled"]:
        return False, "off: _data/fleet.yml pr_queue.agent.enabled is false"
    return True, "on"


def actions_view(cfg: dict) -> list[dict]:
    out = []
    for aid, meta in ACTIONS.items():
        ok, why = action_enabled(aid, cfg)
        out.append({"id": aid, "title": meta["title"], "op": meta["op"], "writes": meta["writes"],
                    "governed": meta["governed"], "enabled": ok, "why": why, "spend": bool(meta.get("spend"))})
    return out


def applies(action: str, r: dict, cfg: dict) -> tuple[bool, str]:
    """Whether a bulk action has anything to do on a row, from the queue's last read. The plan asks GitHub
    again before anything is written; this is what the page counts beside each action."""
    checks, nxt = r.get("checks") or {}, r.get("next") or {}
    repo = str(r.get("repo") or "")
    if action == "ready":
        return (True, "a draft") if r.get("draft") else (False, "not a draft")
    if action == "update-branch":
        if r.get("mergeable") == "CONFLICTING":
            return False, "conflicts with its base: JEV resolves it (tools/dash conflicts resolve)"
        if r.get("merge_state") == "BEHIND":
            return True, "behind its base"
        return False, f"merge state {r.get('merge_state') or 'unknown'}, not BEHIND"
    if action == "rerun":
        if checks.get("cancelled") or checks.get("failing"):
            return True, f"{len(checks.get('cancelled') or [])} cancelled, {len(checks.get('failing') or [])} failing"
        return False, "no cancelled or failing check"
    if action == "comment":
        return True, "posts or edits the next-action comment"
    if action == "needs-amr":
        return (False, "already labelled needs-amr") if "needs-amr" in {str(x).lower() for x in r.get("labels") or []} \
            else (True, "adds the gate label")
    if action == "agent":
        if r.get("private"):
            return False, "a private repo: the agent never clones one"
        if checks.get("state") == "failing" or r.get("review") == "CHANGES_REQUESTED":
            return True, "failing checks" if checks.get("state") == "failing" else "changes requested"
        return False, "no failing check and no change requested"
    if action == "close":
        return True, "closes it with the reason you give"
    if action == "merge":
        if repo.lower() in {str(x).lower() for x in cfg["closeout"]["never_merge"]}:
            return False, "this repo's own rules keep every merge with the maintainer, outside any agent"
        if r.get("draft"):
            return False, "a draft"
        if checks.get("state") not in ("green",):
            return False, f"checks {checks.get('state')}"
        if r.get("mergeable") != "MERGEABLE":
            return False, f"mergeable {r.get('mergeable') or 'unknown'}"
        return True, nxt.get("why") or "green and mergeable"
    return False, f"unknown action {action!r}"


# --------------------------------------------------------------------------- #
# Plans: deterministic, so the confirm applies exactly what was shown
# --------------------------------------------------------------------------- #
def plan_id(action: str, params: dict, items: list[dict]) -> str:
    """A plan's identity: the action, its parameters and every pull request's op with the state it was
    planned against (head commit, labels, the comment it edits). Any change there is a new plan, so a
    stale preview is refused (§ 11.4)."""
    core = [{k: i.get(k) for k in ("key", "do", "op", "head_sha", "against")} for i in items]
    blob = json.dumps({"schema": PLAN_SCHEMA, "action": action, "params": params, "items": core}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def comment_body(r: dict, note: str | None, today: str) -> str:
    """The next-action comment: the queue's own reading, in the triage comment's shape, under the triage
    marker so it is edited in place (§ 19.2), with the source signature (§ 19.4)."""
    nxt = r.get("next") or {}
    lines = [f"**Next action:** {WHO_TITLES.get(nxt.get('who', ''), 'Someone')}: {nxt.get('action', 'decide')}.",
             f"Why: {nxt.get('why', 'no reason recorded')}."]
    gate = r.get("gate") or {}
    lines.append(("Gated (§ 12.3): " if gate.get("gated") else "Not gated: ") + str(gate.get("reason") or "") + ".")
    checks = r.get("checks") or {}
    if checks.get("false_red"):
        lines.append(f"Checks: green once the {checks.get('superseded', 0)} superseded run(s) are set aside; "
                     "GitHub's rollup still shows the cancelled ones.")
    if nxt.get("command"):
        lines.append(f"`{nxt['command']}`")
    if note:
        lines.append(note.strip())
    lines.append(f"\n<sub>From the Harness Console PR queue, applied at the maintainer's confirm, {today}.</sub>")
    return "\n".join(lines) + f"\n{TRIAGE_MARKER}\n{SOURCE_SIGNATURE}"

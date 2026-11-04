#!/usr/bin/env python3
# ============================================================================
# File:          tools/projects_backfill.py
# Description:   The hub's issue-triage and Fleet-board backfill pass — constitution § 10 (every
#                item on the Fleet project with Status and Priority) applied through § 11 (plan,
#                show, confirm). Reads the reviewed decisions in _data/projects_backfill.yml,
#                compiles them into the write-back service's ops (tools/console/gh_projects_write.py),
#                previews every batch as before → after with a deterministic plan id, and applies
#                only with HARNESS_PROJECTS_WRITES=1 and --confirm. Issues and pull requests go
#                through REST (`gh api`); project items need GraphQL, which is skipped — and said
#                so — where it is not reachable. Amendment 0003 rollout phase 1; issues #453, #473.
# Usage:         python3 tools/projects_backfill.py inventory [--live] [--json]
#                python3 tools/projects_backfill.py plan [--board] [--json] [--out FILE]
#                python3 tools/projects_backfill.py apply FILE --confirm [--batch N]
#                (or tools/dash projects <inventory|plan|apply> …)
# Exit:          0 clean · 1 refused or failed · 2 usage
# Never:         merge, delete, settings, label creation, token values in output.
# ============================================================================
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "console"))
import gh_projects as gp  # noqa: E402
import gh_projects_write as gw  # noqa: E402

DECISIONS = ROOT / "_data" / "projects_backfill.yml"
FRAMEWORK = ROOT / "templates" / "projects" / "framework.yml"
REGISTRY = ROOT / "_data" / "projects.yml"
TRIAGE = ROOT / "_data" / "fleet_triage.yml"
PREVIEW_DIR = ROOT / ".fleet" / "projects"
AUDIT = Path(os.environ.get("HARNESS_PROJECTS_AUDIT", str(PREVIEW_DIR / "github-writes.jsonl")))
SCHEMA = "projects-backfill/v1"
PLAN_SCHEMA = "projects-backfill-plan/v1"
PAGE = 100
MAX_PAGES = 20
CLOSE_REASONS = ("completed", "not_planned")
BOARD_FIELDS = ("Status", "Priority", "Area")
STAGE_ORDER = ("hold", "done", "needs-amr", "in_pr", "blocked", "ready", "queued")
GRAPHQL_BLOCKED = ("GraphQL is not available", "not available", "INSUFFICIENT_SCOPES", "read:project")


class GhError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- gh
class Gh:
    """`gh api` as a function. The runner is injectable so tests never touch the network."""

    def __init__(self, run: Callable | None = None, env: dict | None = None):
        self._run = run or self._subprocess
        self._env = env
        self._cache: dict[str, Any] = {}

    @staticmethod
    def _subprocess(args: list[str], stdin: str | None, env: dict | None) -> tuple[int, str, str]:
        full = dict(os.environ)
        if env:
            full.update(env)
        try:
            r = subprocess.run(args, input=stdin, capture_output=True, text=True, env=full, timeout=120)
        except FileNotFoundError:
            return 127, "", "gh: not installed"
        except subprocess.TimeoutExpired:
            return 124, "", "gh: timed out"
        return r.returncode, r.stdout, r.stderr

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> Any:
        args = ["gh", "api", "-X", method, path]
        for k, v in (params or {}).items():
            args += ["-f", f"{k}={v}"]
        stdin = None
        if body is not None:
            args += ["--input", "-"]
            stdin = json.dumps(body)
        rc, out, err = self._run(args, stdin, self._env)
        if rc != 0:
            raise GhError(f"{method} {path}: {gp.redact((err or out).strip())[:400]}")
        out = out.strip()
        return json.loads(out) if out else {}

    def get(self, path: str, **params) -> Any:
        key = path + ("?" + urllib.parse.urlencode(sorted(params.items())) if params else "")
        if key not in self._cache:
            self._cache[key] = self.call("GET", path, params=params or None)
        return self._cache[key]

    def forget(self, prefix: str = "") -> None:
        for k in [k for k in self._cache if k.startswith(prefix)]:
            del self._cache[k]

    def graphql(self, query: str, variables: dict) -> dict:
        return self.call("POST", "graphql", body={"query": query, "variables": variables})


def gh_for_projects() -> Gh:
    """A `gh` that uses PROJECTS_TOKEN when it is set (§ 11.7), the ambient login otherwise."""
    tok = os.environ.get("PROJECTS_TOKEN")
    return Gh(env={"GH_TOKEN": tok} if tok else None)


# --------------------------------------------------------------------------- inputs
def load_decisions(path: Path = DECISIONS) -> dict:
    d = yaml.safe_load(path.read_text()) or {}
    errs = validate_decisions(d)
    if errs:
        raise ValueError("; ".join(errs))
    return d


def validate_decisions(d: dict) -> list[str]:
    errs = []
    if d.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", str(d.get("repo", ""))):
        errs.append("repo must be owner/name")
    issues = d.get("issues") or {}
    close = issues.get("close") or []
    labels = issues.get("labels") or []
    subs = issues.get("sub_issues") or []
    closed = set()
    for row in close:
        n = row.get("number")
        if not isinstance(n, int):
            errs.append(f"close: number missing on {row}")
            continue
        if row.get("reason") not in CLOSE_REASONS:
            errs.append(f"close #{n}: reason must be one of {CLOSE_REASONS}")
        if not row.get("why"):
            errs.append(f"close #{n}: why is required")
        if n in closed:
            errs.append(f"close #{n}: listed twice")
        closed.add(n)
    seen = set()
    for row in labels:
        n = row.get("number")
        if not isinstance(n, int):
            errs.append(f"labels: number missing on {row}")
            continue
        if n in closed:
            errs.append(f"labels #{n}: the issue is also being closed")
        if n in seen:
            errs.append(f"labels #{n}: listed twice")
        seen.add(n)
        add, rem = row.get("add") or [], row.get("remove") or []
        if not add and not rem:
            errs.append(f"labels #{n}: nothing to add or remove")
        if set(add) & set(rem):
            errs.append(f"labels #{n}: a label is both added and removed")
        if not row.get("why"):
            errs.append(f"labels #{n}: why is required")
    parents = set()
    for row in subs:
        p = row.get("parent")
        kids = row.get("children") or []
        if not isinstance(p, int) or not kids or not all(isinstance(k, int) for k in kids):
            errs.append(f"sub_issues: parent and children must be issue numbers ({row})")
            continue
        if p in closed or set(kids) & closed:
            errs.append(f"sub_issues #{p}: a parent or child is being closed")
        if p in parents:
            errs.append(f"sub_issues #{p}: listed twice")
        parents.add(p)
    return errs


def load_framework(path: Path = FRAMEWORK) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def registry_repos(path: Path = REGISTRY, hub: str = "bamr87/bamr87") -> set[str]:
    """owner/name of every registry repo plus the hub — the § 11 repo allowlist."""
    allow = {hub}
    try:
        rows = yaml.safe_load(path.read_text()) or []
    except OSError:
        return allow
    for r in rows if isinstance(rows, list) else []:
        url = str(r.get("repo_url") or "")
        m = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if m:
            allow.add(m.group(1))
    return allow


# --------------------------------------------------------------------------- issue ops
def compile_issue_ops(d: dict, resolve_id: Callable[[int], int]) -> list[dict]:
    """Decisions → § 11 ops, in the order they should apply: labels, links, closes."""
    repo = d["repo"]
    issues = d.get("issues") or {}
    ops: list[dict] = []
    for row in issues.get("labels") or []:
        n = row["number"]
        if row.get("add"):
            ops.append({"op": "issue.labels.add", "repo": repo, "number": n, "labels": sorted(row["add"])})
        if row.get("remove"):
            ops.append({"op": "issue.labels.remove", "repo": repo, "number": n, "labels": sorted(row["remove"])})
    for row in issues.get("sub_issues") or []:
        for child in row["children"]:
            ops.append({"op": "issue.sub_issue.add", "repo": repo, "number": row["parent"],
                        "sub_issue_id": resolve_id(child), "child": child})
    for row in issues.get("close") or []:
        ops.append({"op": "issue.state.set", "repo": repo, "number": row["number"], "state": "closed",
                    "state_reason": row["reason"]})
    return ops


class IssueApi:
    """REST reads and the allowlisted REST mutations for issues and pull requests."""

    def __init__(self, gh: Gh):
        self.gh = gh

    def issue(self, repo: str, n: int) -> dict:
        return self.gh.get(f"repos/{repo}/issues/{n}")

    def issue_id(self, repo: str, n: int) -> int:
        return int(self.issue(repo, n)["id"])

    def sub_issue_ids(self, repo: str, n: int) -> set[int]:
        rows = self.gh.get(f"repos/{repo}/issues/{n}/sub_issues", per_page=PAGE)
        return {int(r["id"]) for r in rows or []}

    def state(self, op: dict) -> dict | None:
        """The service's `state(op)`: the target's current values for exactly what the op sets."""
        name, repo, n = op["op"], op.get("repo"), op.get("number")
        if not repo or n is None:
            return None
        try:
            it = self.issue(repo, n)
        except GhError:
            return None
        labels = sorted(l["name"] for l in it.get("labels") or [])
        if name.endswith("labels.add") or name.endswith("labels.remove"):
            return {"labels": labels, "state": it.get("state")}
        if name == "issue.state.set":
            return {"state": it.get("state"), "labels": labels}
        if name == "issue.sub_issue.add":
            linked = op["sub_issue_id"] in self.sub_issue_ids(repo, n)
            return {"sub_issue_id": op["sub_issue_id"] if linked else None}
        if name in ("issue.edit", "pr.edit"):
            return {k: it.get(k) for k in ("title", "body")}
        if name == "issue.assignees.set":
            return {"assignees": sorted(a["login"] for a in it.get("assignees") or [])}
        if name == "issue.milestone.set":
            return {"milestone": (it.get("milestone") or {}).get("title")}
        if name == "pr.draft.set":
            return {"draft": it.get("draft")}
        return {"labels": labels, "state": it.get("state")}

    def execute(self, op: dict) -> dict:
        name, repo, n = op["op"], op["repo"], op["number"]
        base = f"repos/{repo}/issues/{n}"
        if name.endswith("labels.add"):
            out = self.gh.call("POST", f"{base}/labels", body={"labels": list(op["labels"])})
            res = {"labels": sorted(l["name"] for l in out or [])}
        elif name.endswith("labels.remove"):
            for lab in op["labels"]:
                try:
                    self.gh.call("DELETE", f"{base}/labels/{urllib.parse.quote(lab, safe='')}")
                except GhError as e:  # already gone is the desired state
                    if "404" not in str(e) and "Label does not exist" not in str(e):
                        raise
            res = {"removed": sorted(op["labels"])}
        elif name == "issue.state.set":
            body = {"state": op["state"]}
            if op["state"] == "closed":
                body["state_reason"] = op.get("state_reason", "completed")
            out = self.gh.call("PATCH", base, body=body)
            res = {"state": out.get("state"), "state_reason": out.get("state_reason")}
        elif name == "issue.sub_issue.add":
            out = self.gh.call("POST", f"{base}/sub_issues", body={"sub_issue_id": int(op["sub_issue_id"])})
            res = {"parent": n, "sub_issue_id": op["sub_issue_id"], "number": out.get("number")}
        elif name in ("issue.edit", "pr.edit"):
            out = self.gh.call("PATCH", base, body=dict(op.get("set") or {}))
            res = {k: out.get(k) for k in ("title",)}
        elif name == "issue.assignees.set":
            out = self.gh.call("PATCH", base, body={"assignees": list(op["assignees"])})
            res = {"assignees": sorted(a["login"] for a in out.get("assignees") or [])}
        elif name == "issue.milestone.set":
            out = self.gh.call("PATCH", base, body={"milestone": op["milestone"]})
            res = {"milestone": (out.get("milestone") or {}).get("title")}
        elif name == "pr.draft.set":
            raise GhError("pr.draft.set needs GraphQL (convertPullRequestToDraft); not in the REST executor")
        else:
            raise GhError(f"{name}: no executor")
        self.gh.forget(base)
        return res


# --------------------------------------------------------------------------- board rules
def _canonical(framework: dict, field: str) -> dict[str, str]:
    rows = ((framework.get("labels") or {}).get("canonical") or {})
    return {lab: m["value"] for lab, m in rows.items() if (m or {}).get("field") == field}


def derive_fields(item: dict, decisions: dict, framework: dict, options: dict[str, list[str]] | None = None) -> dict:
    """Status / Priority / Area for one issue or PR from its labels (framework canonical map first,
    then the decisions file's `board:` extras, then the defaults). `options` are the project's real
    option names per field; a derived value the project cannot hold falls back honestly."""
    labels = [l.lower() for l in item.get("labels") or []]
    rules = decisions.get("board") or {}
    status_rules = rules.get("status") or {}
    stat_map = {k.lower(): v for k, v in _canonical(framework, "Status").items()}
    opts = options or {}

    def allowed(field: str, value: str | None) -> str | None:
        return value if value and (field not in opts or value in opts[field]) else None

    status = None
    if item.get("state", "open").lower() != "open":
        status = status_rules.get("closed", "Done")
    elif item.get("kind") == "pr":
        status = status_rules.get("pr_draft", "In progress") if item.get("draft") else status_rules.get("pr", "In review")
    else:
        stage_labels = {"hold": "agent:hold", "done": "agent:done", "in_pr": "agent:in-pr", "blocked": "agent:blocked",
                        "ready": "agent:ready", "queued": "agent:queued"}
        for stage in STAGE_ORDER:
            if stage == "needs-amr":
                if "needs-amr" in labels:
                    status = allowed("Status", status_rules.get("needs-amr", "Needs Amr")) or stat_map.get("agent:blocked", "Blocked")
                    break
                continue
            lab = stage_labels[stage]
            if lab in labels and lab in stat_map:
                status = stat_map[lab]
                break
        if status is None:
            for lab, val in status_rules.items():
                if lab not in ("closed", "default", "pr", "pr_draft", "needs-amr") and lab.lower() in labels:
                    status = val
                    break
        if status is None:
            status = status_rules.get("default", "Triaged")
    prio_map = {k.lower(): v for k, v in _canonical(framework, "Priority").items()}
    priority = next((prio_map[l] for l in labels if l in prio_map), (rules.get("priority") or {}).get("default", "P2"))
    area_rules = rules.get("area") or {}
    area_map = {k.lower(): v for k, v in _canonical(framework, "Area").items()}
    area_map.update({k.lower(): v for k, v in (area_rules.get("labels") or {}).items()})
    area = next((v for lab, v in area_map.items() if lab in labels), None)  # rule order, not label order
    if area is None:
        title = (item.get("title") or "").lower()
        for name, words in (area_rules.get("keywords") or {}).items():
            if any(re.search(r"\b" + re.escape(w.lower()) + r"\b", title) for w in words):
                area = name
                break
    if area is None:
        area = area_rules.get("default", "platform")
    return {"Status": status, "Priority": priority, "Area": area}


# --------------------------------------------------------------------------- board (GraphQL)
PROJECT_Q = """query($login:String!,$n:Int!){ user(login:$login){ projectV2(number:$n){ id title url closed
 fields(first:50){ nodes{ ... on ProjectV2FieldCommon{ id name dataType }
   ... on ProjectV2SingleSelectField{ options{ id name } } } } } } }"""
ADD_M = """mutation($p:ID!,$c:ID!){ addProjectV2ItemById(input:{projectId:$p,contentId:$c}){ item{ id } } }"""
SET_SELECT_M = """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue(
 input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){ projectV2Item{ id } } }"""
SET_TEXT_M = """mutation($p:ID!,$i:ID!,$f:ID!,$t:String!){ updateProjectV2ItemFieldValue(
 input:{projectId:$p,itemId:$i,fieldId:$f,value:{text:$t}}){ projectV2Item{ id } } }"""


def graphql_unavailable(err: str) -> bool:
    return any(s in err for s in GRAPHQL_BLOCKED) or "403" in err


class Board:
    """One Fleet project: its fields, option ids and items, read once through GraphQL."""

    def __init__(self, gh: Gh, owner: str, number: int):
        self.gh, self.owner, self.number = gh, owner, number
        self.project: dict | None = None
        self.items: dict[tuple[str, int], dict] = {}
        self.error: str | None = None

    def _gql(self, query: str, variables: dict) -> dict:
        out = self.gh.graphql(query, variables)
        errs = out.get("errors") or []
        if errs and not out.get("data"):
            raise GhError(gp.redact("; ".join(str(e.get("message")) for e in errs)))
        return out.get("data") or {}

    def load(self) -> bool:
        try:
            d = self._gql(PROJECT_Q, {"login": self.owner, "n": self.number})
            p = (d.get("user") or {}).get("projectV2")
            if not p:
                self.error = f"project {self.owner}/{self.number} not found or not readable"
                return False
            fields = {}
            for f in (p.get("fields") or {}).get("nodes") or []:
                if f and f.get("name"):
                    fields[f["name"]] = {"id": f["id"], "type": f.get("dataType"),
                                         "options": {o["name"]: o["id"] for o in f.get("options") or []}}
            self.project = {"id": p["id"], "title": p["title"], "url": p.get("url"), "fields": fields}
            for it in gp.project_items(p["id"], http=lambda q, v, _t: self.gh.graphql(q, v), tok="gh"):
                if it["kind"] in ("issue", "pr") and it.get("repo"):
                    self.items[(it["repo"], int(it["number"]))] = it
            return True
        except (GhError, RuntimeError, gp.ScopeMissing) as e:
            self.error = "graphql_unavailable: " + str(e)[:300] if graphql_unavailable(str(e)) else str(e)[:300]
            return False

    def options(self) -> dict[str, list[str]]:
        return {n: list(f["options"]) for n, f in (self.project or {}).get("fields", {}).items() if f["options"]}

    def state(self, op: dict) -> dict | None:
        key = (op.get("repo"), op.get("number"))
        it = self.items.get(key)
        if op["op"] == "item.add":
            return {"present": it is not None}
        if op["op"] == "item.set_field":
            if it is None:
                return None
            return {op["field_id"]: (it.get("fields") or {}).get(op.get("field"))}
        return None

    def execute(self, op: dict) -> dict:
        p = self.project or {}
        if op["op"] == "item.add":
            d = self._gql(ADD_M, {"p": op["project_id"], "c": op["content_id"]})
            item_id = ((d.get("addProjectV2ItemById") or {}).get("item") or {}).get("id")
            self.items[(op["repo"], op["number"])] = {"item_id": item_id, "fields": {}, "repo": op["repo"],
                                                     "number": op["number"], "kind": "issue"}
            return {"item_id": item_id}
        if op["op"] == "item.set_field":
            field = p["fields"][op["field"]]
            if field["options"]:
                oid = field["options"].get(op["value"])
                if not oid:
                    raise GhError(f"{op['field']}: the project has no option {op['value']!r}")
                self._gql(SET_SELECT_M, {"p": op["project_id"], "i": op["item_id"], "f": op["field_id"], "o": oid})
            else:
                self._gql(SET_TEXT_M, {"p": op["project_id"], "i": op["item_id"], "f": op["field_id"], "t": str(op["value"])})
            self.items[(op["repo"], op["number"])].setdefault("fields", {})[op["field"]] = op["value"]
            return {"field": op["field"], "value": op["value"]}
        raise GhError(f"{op['op']}: no executor")


def board_ops(board: Board, targets: list[dict], decisions: dict, framework: dict) -> tuple[list[dict], list[str]]:
    """Adds for items missing from the project; field sets for items already on it (a second plan
    after the adds land sets their fields: an item id exists only once the item does)."""
    ops, notes = [], []
    p = board.project or {}
    fields = p.get("fields") or {}
    for name in BOARD_FIELDS:
        if name not in fields:
            notes.append(f"the project has no {name!r} field — its values are not planned")
    options = board.options()
    for t in targets:
        key = (t["repo"], t["number"])
        it = board.items.get(key)
        if it is None:
            ops.append({"op": "item.add", "project_id": p.get("id"), "content_id": t["node_id"],
                        "repo": t["repo"], "number": t["number"], "kind": t["kind"]})
            continue
        want = derive_fields(t, decisions, framework, options)
        for name in BOARD_FIELDS:
            f = fields.get(name)
            if not f:
                continue
            value = want[name]
            if f["options"] and value not in f["options"]:
                notes.append(f"#{t['number']}: {name}={value!r} is not an option of the project; skipped")
                continue
            if (it.get("fields") or {}).get(name) != value:
                ops.append({"op": "item.set_field", "project_id": p.get("id"), "item_id": it["item_id"],
                            "field_id": f["id"], "value": value, "field": name, "repo": t["repo"], "number": t["number"]})
    return ops, notes


# --------------------------------------------------------------------------- targets
def open_items(gh: Gh, repo: str) -> list[dict]:
    """Every open issue and pull request of a repo, in the shape derive_fields() and board_ops() read."""
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        rows = gh.get(f"repos/{repo}/issues", state="open", per_page=PAGE, page=page) or []
        for r in rows:
            out.append({"repo": repo, "number": int(r["number"]), "node_id": r.get("node_id"), "title": r.get("title", ""),
                        "state": r.get("state", "open"), "labels": [l["name"] for l in r.get("labels") or []],
                        "kind": "pr" if r.get("pull_request") else "issue", "draft": bool(r.get("draft"))})
        if len(rows) < PAGE:
            break
    drafts = {}
    if any(t["kind"] == "pr" for t in out):
        for page in range(1, MAX_PAGES + 1):
            rows = gh.get(f"repos/{repo}/pulls", state="open", per_page=PAGE, page=page) or []
            drafts.update({int(r["number"]): bool(r.get("draft")) for r in rows})
            if len(rows) < PAGE:
                break
    for t in out:
        if t["kind"] == "pr":
            t["draft"] = drafts.get(t["number"], t["draft"])
    return out


# --------------------------------------------------------------------------- plan / apply
def chunk(ops: list[dict], size: int = gw.MAX_OPS_PER_PLAN) -> list[list[dict]]:
    return [ops[i:i + size] for i in range(0, len(ops), size)]


def plan_batches(ops: list[dict], state: Callable, allow: set[str] | None) -> list[dict]:
    batches = []
    for i, part in enumerate(chunk(ops), start=1):
        p = gw.plan(part, state, allow)
        batches.append({"index": i, "plan_id": p["plan_id"], "ops": part, "rows": p["rows"], "changes": p["changes"]})
    return batches


def describe(op: dict, row: dict) -> str:
    n = op.get("number")
    name = op["op"]
    if name == "issue.labels.add":
        what = " ".join("+" + l for l in op["labels"])
    elif name == "issue.labels.remove":
        what = " ".join("-" + l for l in op["labels"])
    elif name == "issue.state.set":
        what = f"{(row.get('before') or {}).get('state', '?')} → {op['state']} ({op.get('state_reason', '')})"
    elif name == "issue.sub_issue.add":
        what = f"← #{op.get('child', op.get('sub_issue_id'))}"
    elif name == "item.add":
        what = f"add {op.get('kind', 'item')} to the project"
    elif name == "item.set_field":
        what = f"{op.get('field')}: {(row.get('before') or {}).get(op['field_id'])!r} → {op['value']!r}"
    else:
        what = json.dumps(row.get("after"), sort_keys=True)
    return f"#{n:<5} {name:<22} {what}" + ("   (already)" if row.get("noop") else "")


def write_preview(preview: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(preview, indent=1, sort_keys=True, default=str) + "\n")
    return out


def record_applied(path: Path, rec: dict) -> None:
    """Append one record under the decisions file's trailing `applied:` key without reserialising it."""
    text = path.read_text()
    lines = [f"- plan_id: {rec['plan_id']}", f"  at: {rec['at']}", f"  batch: {rec['batch']}",
             f"  applied: {rec['applied']}", f"  noop: {rec['noop']}"]
    block = "\n".join(lines) + "\n"
    if re.search(r"^applied:\s*\[\]\s*$", text, re.M):
        text = re.sub(r"^applied:\s*\[\]\s*$", "applied:\n" + block.rstrip("\n"), text, count=1, flags=re.M)
    elif re.search(r"^applied:\s*$", text, re.M):
        text = text.rstrip("\n") + "\n" + block
    else:
        text = text.rstrip("\n") + "\napplied:\n" + block
    path.write_text(text if text.endswith("\n") else text + "\n")


def cmd_inventory(args) -> int:
    if args.live:
        gh = Gh()
        rows = []
        for repo in sorted(registry_repos()):
            try:
                r = gh.get(f"repos/{repo}")
                prs = gh.get(f"repos/{repo}/pulls", state="open", per_page=PAGE)
                rows.append({"repo": repo, "open_issues": int(r.get("open_issues_count", 0)) - len(prs),
                             "open_prs": len(prs), "archived": r.get("archived", False)})
            except GhError as e:
                rows.append({"repo": repo, "error": str(e)[:120]})
        src = "live"
    else:
        t = yaml.safe_load(TRIAGE.read_text()) or {}
        rows = [{"repo": r.get("nwo"), "open_issues": (r.get("issues") or {}).get("open", 0),
                 "open_prs": (r.get("prs") or {}).get("open", 0), "archived": r.get("archived", False),
                 "external": r.get("external", False)}
                for r in t.get("by_repo") or []]
        src = f"_data/fleet_triage.yml ({t.get('generated_at')})"
    total_i = sum(int(r.get("open_issues") or 0) for r in rows)
    total_p = sum(int(r.get("open_prs") or 0) for r in rows)
    if args.json:
        print(json.dumps({"source": src, "repos": rows, "open_issues": total_i, "open_prs": total_p}, indent=1))
    else:
        print(f"inventory ({src}): {len(rows)} repos, {total_i} open issues, {total_p} open PRs")
        for r in rows:
            flags = " ".join(k for k in ("archived", "external") if r.get(k))
            print(f"  {str(r.get('repo')):<40} issues {str(r.get('open_issues', '?')):>4}  prs {str(r.get('open_prs', '?')):>3}"
                  + (f"  {flags}" if flags else "") + (f"  {r['error']}" if r.get("error") else ""))
    return 0


def cmd_plan(args) -> int:
    decisions = load_decisions(Path(args.decisions))
    framework = load_framework()
    allow = registry_repos()
    repo = decisions["repo"]
    gh = Gh()
    api = IssueApi(gh)
    ops = compile_issue_ops(decisions, lambda n: api.issue_id(repo, n))
    batches = plan_batches(ops, api.state, allow)
    preview = {"schema": PLAN_SCHEMA, "generated_at": now_iso(), "repo": repo, "decisions": str(Path(args.decisions)),
               "batches": batches, "board": {"status": "not requested"}}
    if args.board:
        proj = decisions.get("project") or {}
        board = Board(gh_for_projects(), proj.get("owner", "bamr87"), int(proj.get("number", 14)))
        if board.load():
            targets = open_items(gh, repo)
            bops, notes = board_ops(board, targets, decisions, framework)
            bbatches = plan_batches(bops, board.state, allow)
            for b in bbatches:
                b["index"] = len(preview["batches"]) + b["index"]
                b["board"] = True
            preview["batches"].extend(bbatches)
            preview["board"] = {"status": "planned", "project": board.project["title"], "url": board.project.get("url"),
                                "items_on_project": len(board.items), "targets": len(targets), "notes": notes,
                                "adds": sum(1 for o in bops if o["op"] == "item.add"),
                                "field_sets": sum(1 for o in bops if o["op"] == "item.set_field")}
        else:
            preview["board"] = {"status": "skipped", "reason": board.error}
    out = write_preview(preview, Path(args.out) if args.out else PREVIEW_DIR / f"plan-{time.strftime('%Y%m%d-%H%M%S')}.json")
    if args.json:
        print(json.dumps({"preview": str(out), "batches": [{"index": b["index"], "plan_id": b["plan_id"],
                                                             "ops": len(b["ops"]), "changes": b["changes"]} for b in preview["batches"]],
                          "board": preview["board"]}, indent=1))
        return 0
    print(f"plan for {repo} — dry run, nothing written to GitHub (constitution § 11.4)")
    for b in preview["batches"]:
        kind = "board" if b.get("board") else "issues"
        print(f"\nbatch {b['index']} ({kind}) plan_id {b['plan_id']}: {b['changes']} change(s) in {len(b['ops'])} op(s)")
        for op, row in zip(b["ops"], b["rows"]):
            print("  " + describe(op, row))
    bd = preview["board"]
    print(f"\nboard: {bd.get('status')}" + (f" — {bd.get('reason')}" if bd.get("reason") else ""))
    for note in bd.get("notes") or []:
        print(f"  note: {note}")
    total = sum(b["changes"] for b in preview["batches"])
    print(f"\n{total} change(s) in {len(preview['batches'])} batch(es); preview {out}")
    print(f"apply with: HARNESS_PROJECTS_WRITES=1 tools/dash projects apply {out} --confirm")
    return 0


def cmd_apply(args) -> int:
    preview = json.loads(Path(args.file).read_text())
    if preview.get("schema") != PLAN_SCHEMA:
        print(f"refused: {args.file} is not a {PLAN_SCHEMA} preview", file=sys.stderr)
        return 2
    if not gw.enabled():
        print(f"refused: writes are off — set {gw.FLAG}=1 (constitution § 11.3)", file=sys.stderr)
        return 1
    if not args.confirm:
        print("refused: preview the plan, read it, then re-run with --confirm (constitution § 11.4)", file=sys.stderr)
        return 1
    decisions = load_decisions(Path(preview.get("decisions") or DECISIONS))
    allow = registry_repos()
    repo = preview["repo"]
    gh = Gh()
    api = IssueApi(gh)
    board: Board | None = None
    rc = 0
    for b in preview["batches"]:
        if args.batch and b["index"] != args.batch:
            continue
        if b.get("board"):
            if board is None:
                proj = decisions.get("project") or {}
                board = Board(gh_for_projects(), proj.get("owner", "bamr87"), int(proj.get("number", 14)))
                if not board.load():
                    print(f"batch {b['index']}: skipped — {board.error}")
                    rc = 1
                    break
            state, execute = board.state, board.execute
        else:
            gh.forget()
            state, execute = api.state, api.execute
        res = gw.apply(b["plan_id"], b["ops"], state, execute, confirm=True, actor="projects_backfill",
                       repo_allow=allow, audit=AUDIT)
        if res.get("refused"):
            print(f"batch {b['index']}: {res['refused']}")
            rc = 1
            break
        results = res.get("results") or []
        errors = [r for r in results if r.get("result") == "error"]
        noop = sum(1 for r in results if r.get("result") == "noop")
        print(f"batch {b['index']}: applied {res['applied']}, already satisfied {noop}, errors {len(errors)}")
        for r in errors:
            print(f"  error {r.get('target')}: {r.get('error')}")
        record_applied(Path(preview.get("decisions") or DECISIONS),
                       {"plan_id": b["plan_id"], "at": now_iso(), "batch": b["index"], "applied": res["applied"], "noop": noop})
        if errors:
            rc = 1
            break
    print(f"audit: {AUDIT}")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="projects_backfill", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("inventory", help="open issues / PRs per registry repo")
    i.add_argument("--live", action="store_true", help="count through the API instead of the committed triage snapshot")
    i.add_argument("--json", action="store_true")
    p = sub.add_parser("plan", help="compile the decisions, read the current state, preview before → after")
    p.add_argument("--board", action="store_true", help="also plan the Fleet project items (GraphQL)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", help="preview file (default .fleet/projects/plan-<stamp>.json)")
    p.add_argument("--decisions", default=str(DECISIONS))
    a = sub.add_parser("apply", help="apply a previewed plan, batch by batch, through the § 11 service")
    a.add_argument("file")
    a.add_argument("--confirm", action="store_true")
    a.add_argument("--batch", type=int, help="apply one batch only")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        return {"inventory": cmd_inventory, "plan": cmd_plan, "apply": cmd_apply}[args.cmd](args)
    except (GhError, ValueError, gw.Refused) as e:
        print(f"error: {gp.redact(str(e))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

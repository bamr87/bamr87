#!/usr/bin/env python3
"""gh_projects_write — guarded write-back to GitHub Projects (v2), issues and PRs.

OFF BY DEFAULT. Governed by the proposed amendment
docs/amendments/proposed/projects-write-back.md (constitution § 11).

  plan(ops, state)   dry run: validates every op against the ALLOWLIST, refuses
                     anything on the DENYLIST, computes before→after for each op,
                     marks ops that are already satisfied as no-ops (idempotency)
                     and returns a deterministic plan_id. Never touches the network.
  apply(plan_id, ops, state_reader, confirm=True)
                     needs HARNESS_PROJECTS_WRITES=1 AND confirm=True; re-reads the
                     current state and refuses when the plan no longer matches it
                     (stale plan); enforces per-plan and per-hour caps; appends one
                     audit record per op to the JSONL audit log, token values redacted.

Never: merge, delete, transfer, settings, branch protection, secrets, workflows,
visibility. Those are refused even when the flag and confirm are set.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from gh_projects import redact

FLAG = "HARNESS_PROJECTS_WRITES"
MAX_OPS_PER_PLAN = 50
MAX_OPS_PER_HOUR = 200
AUDIT_DEFAULT = Path(os.environ.get("HARNESS_PROJECTS_AUDIT", "state/audit/github-writes.jsonl"))

# op name -> (target kind, required args). Anything not here is refused.
ALLOWLIST: dict[str, tuple[str, tuple[str, ...]]] = {
    "project.create": ("owner", ("owner_id", "title")),
    "project.update": ("project", ("project_id",)),
    "project.field.create": ("project", ("project_id", "name", "data_type")),
    "item.add": ("project", ("project_id", "content_id")),
    "item.set_field": ("item", ("project_id", "item_id", "field_id", "value")),
    "item.clear_field": ("item", ("project_id", "item_id", "field_id")),
    "item.move": ("item", ("project_id", "item_id")),
    "item.archive": ("item", ("project_id", "item_id")),
    "item.unarchive": ("item", ("project_id", "item_id")),
    "issue.edit": ("issue", ("repo", "number")),
    "issue.labels.add": ("issue", ("repo", "number", "labels")),
    "issue.labels.remove": ("issue", ("repo", "number", "labels")),
    "issue.assignees.set": ("issue", ("repo", "number", "assignees")),
    "issue.milestone.set": ("issue", ("repo", "number", "milestone")),
    "issue.state.set": ("issue", ("repo", "number", "state")),
    "issue.sub_issue.add": ("issue", ("repo", "number", "sub_issue_id")),
    "pr.edit": ("pr", ("repo", "number")),
    "pr.labels.add": ("pr", ("repo", "number", "labels")),
    "pr.labels.remove": ("pr", ("repo", "number", "labels")),
    "pr.draft.set": ("pr", ("repo", "number", "draft")),
}
DENY_WORDS = ("merge", "delete", "remove_repo", "transfer", "settings", "protection", "secret",
              "workflow", "visibility", "ruleset", "collaborator", "webhook")
EDITABLE = {"issue.edit": {"title", "body"}, "pr.edit": {"title", "body"}, "project.update":
            {"title", "short_description", "readme", "closed"}}


class Refused(Exception):
    pass


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _check(op: dict, repo_allow: set[str] | None) -> None:
    name = str(op.get("op", ""))
    if any(w in name.lower() for w in DENY_WORDS):
        raise Refused(f"refused: {name!r} is never allowed (no merges, deletes or settings changes)")
    if name not in ALLOWLIST:
        raise Refused(f"refused: {name!r} is not on the mutation allowlist")
    _, req = ALLOWLIST[name]
    missing = [k for k in req if k not in op]
    if missing:
        raise Refused(f"refused: {name} missing {missing}")
    if name in EDITABLE:
        extra = set(op.get("set", {})) - EDITABLE[name]
        if extra:
            raise Refused(f"refused: {name} cannot set {sorted(extra)}")
    if name == "issue.state.set" and op["state"] not in ("open", "closed"):
        raise Refused("refused: issue state must be open|closed")
    if repo_allow is not None and "repo" in op and op["repo"] not in repo_allow:
        raise Refused(f"refused: {op['repo']} is not a registry repo")


def _target(op: dict) -> str:
    for k in ("item_id", "number", "content_id", "project_id", "owner_id"):
        if k in op:
            return f"{op.get('repo') or op.get('project_id') or ''}:{k}={op[k]}"
    return "?"


def _desired(op: dict) -> Any:
    name = op["op"]
    if name == "item.set_field":
        return {op["field_id"]: op["value"]}
    if name == "item.clear_field":
        return {op["field_id"]: None}
    if name in ("item.archive", "item.unarchive"):
        return {"archived": name == "item.archive"}
    if name.endswith("labels.add") or name.endswith("labels.remove"):
        return {"labels": sorted(op["labels"])}
    if name in EDITABLE:
        return dict(sorted(op.get("set", {}).items()))
    for k in ("state", "draft", "assignees", "milestone", "title", "content_id", "sub_issue_id"):
        if k in op:
            return {k: op[k]}
    return {}


def _satisfied(op: dict, before: dict | None) -> bool:
    if before is None:
        return False
    name, want = op["op"], _desired(op)
    if name.endswith("labels.add"):
        return set(want["labels"]) <= set(before.get("labels", []))
    if name.endswith("labels.remove"):
        return not (set(want["labels"]) & set(before.get("labels", [])))
    if name == "item.add":
        return bool(before.get("present"))
    if name == "project.create":
        return bool(before.get("exists"))
    return all(before.get(k) == v for k, v in want.items())


def plan(ops: list[dict], state: Callable[[dict], dict | None], repo_allow: set[str] | None = None) -> dict:
    """Dry run. `state(op)` returns the target's current values (or None). No network here."""
    if len(ops) > MAX_OPS_PER_PLAN:
        raise Refused(f"refused: {len(ops)} ops exceeds the per-plan cap of {MAX_OPS_PER_PLAN}")
    rows = []
    for op in ops:
        _check(op, repo_allow)
        before = state(op)
        rows.append({"op": op["op"], "target": _target(op), "before": before, "after": _desired(op),
                     "noop": _satisfied(op, before)})
    canon = json.dumps({"ops": ops, "before": [r["before"] for r in rows]}, sort_keys=True, default=str)
    return {"plan_id": hashlib.sha256(canon.encode()).hexdigest()[:16], "dry_run": True, "rows": rows,
            "changes": sum(1 for r in rows if not r["noop"]), "enabled": enabled()}


def _recent_count(audit: Path, now: float) -> int:
    if not audit.exists():
        return 0
    n = 0
    for line in audit.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("result") == "applied" and now - rec.get("ts", 0) < 3600:
            n += 1
    return n


def _audit(audit: Path, rec: dict) -> None:
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("a") as f:
        f.write(redact(json.dumps(rec, sort_keys=True, default=str)) + "\n")


def apply(plan_id: str, ops: list[dict], state: Callable[[dict], dict | None], execute: Callable[[dict], dict],
          confirm: bool = False, actor: str = "console", repo_allow: set[str] | None = None,
          audit: Path | None = None, now: Callable[[], float] = time.time) -> dict:
    """Apply a previously previewed plan. `execute(op)` performs one allowlisted mutation."""
    if not enabled():
        return {"applied": 0, "refused": f"writes disabled: set {FLAG}=1 (off by default)"}
    if not confirm:
        return {"applied": 0, "refused": "refused: preview the plan, ask the user, then call again with confirm=true"}
    fresh = plan(ops, state, repo_allow)
    if fresh["plan_id"] != plan_id:
        return {"applied": 0, "refused": "refused: stale plan — the targets changed since the preview; plan again"}
    audit = audit or AUDIT_DEFAULT
    t = now()
    if _recent_count(audit, t) + fresh["changes"] > MAX_OPS_PER_HOUR:
        return {"applied": 0, "refused": f"refused: hourly cap of {MAX_OPS_PER_HOUR} ops"}
    applied, results = 0, []
    for op, row in zip(ops, fresh["rows"]):
        rec = {"ts": t, "actor": actor, "plan_id": plan_id, "op": op["op"], "target": row["target"],
               "before": row["before"], "after": row["after"]}
        if row["noop"]:
            rec["result"] = "noop"
        else:
            try:
                rec["response"] = execute(op)
                rec["result"] = "applied"
                applied += 1
            except Exception as e:  # recorded, then stop: no partial guessing
                rec["result"] = "error"
                rec["error"] = str(e)
                _audit(audit, rec)
                results.append(rec)
                break
        _audit(audit, rec)
        results.append(rec)
    return {"applied": applied, "plan_id": plan_id, "results": json.loads(redact(json.dumps(results, default=str)))}

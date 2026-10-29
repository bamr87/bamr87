#!/usr/bin/env python3
"""The fleet console as an MCP server — the third surface, for agents.

The browser page and the terminal dash are two front ends on one core
(fleetcore) and one runtime (the Harness Console's job API). This is the same
again for an AI client: Claude Code, Claude Desktop, the bashOS kernel or any
other MCP host gets the views a person sees and can run what a person can run —
no more.

  read     fleet_overview · fleet_apps · fleet_inbox · fleet_docker ·
           fleet_work · fleet_workflows · workflow_lint — straight from
           fleetcore.views (and dash-gen's work_board and workflow_atlas) over
           the committed signals and the checkout; work with no console running
  act      console_ops · console_run · console_jobs · console_job_log ·
           console_cancel — through fleetcore.client to the console, so the
           allowlist, parameter validation and the confirm-before-GitHub-write
           gate are the console's, enforced server-side. `console_run` with
           confirm=false is refused for a writing operation and says so; the
           agent's host is expected to put that decision in front of a human.

Transport: MCP over stdio (newline-delimited JSON-RPC 2.0), standard library
only, like the rest of fleetcore. Registered in the repo's .mcp.json as `fleet`.

  DASH_CONSOLE_URL    console endpoint (default http://127.0.0.1:4001)
  DASH_CONSOLE_TOKEN  bearer token; when unset, the DASH_CONSOLE_TOKEN line of
                      the repo's gitignored .env is used — parsed, never sourced
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/, for fleetcore

from fleetcore import fleet as fl  # noqa: E402
from fleetcore import views  # noqa: E402
from fleetcore.client import ConsoleClient, ConsoleError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SERVER = {"name": "fleet", "title": "bamr87 fleet console", "version": "0.1.0"}
INSTRUCTIONS = (
    "The bamr87 fleet: ~46 registry projects, their health, triage and harness signals, and the Harness "
    "Console's allowlisted operations. Read with fleet_* tools. Act with console_run: it runs exactly what "
    "the console's Jobs tab runs. An operation that writes to GitHub is refused unless confirm=true — ask "
    "the user before setting it. Follow a job with console_job_log."
)

# Row fields an agent needs; the full row is ~35 keys and most are noise.
ROW_FIELDS = ("name", "status", "category", "featured", "worst_level", "health", "triage_level", "triage_score",
              "ci_last", "ci_pass", "last_commit_days", "triage_issues", "triage_prs", "security_alerts",
              "failing", "reasons", "triage_reasons", "docker_up", "docker_total", "repo_url", "live_url")


def _dotenv_token(root: Path = ROOT) -> str:
    env = root / ".env"
    if not env.is_file():
        return ""
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == "DASH_CONSOLE_TOKEN":
            return value.strip().strip("'\"")
    return ""


def console() -> ConsoleClient:
    return ConsoleClient(os.environ.get("DASH_CONSOLE_URL", "http://127.0.0.1:4001"),
                         token=os.environ.get("DASH_CONSOLE_TOKEN") or _dotenv_token())


# ------------------------------------------------------------------ tools
def t_overview(_: dict) -> dict:
    v = views.dash_view(ROOT)
    return {"kpis": v["kpis"], "sources": v["sources"],
            "tripped_wires": [w for w in v["trip_wires"] if w.get("tripped")],
            "attention": [{k: r[k] for k in ("name", "worst_level", "triage_score", "triage_reasons")}
                          for r in views.dash_view(ROOT, sort="triage")["rows"] if r["worst_level"] == "red"][:10]}


def t_apps(a: dict) -> dict:
    v = views.dash_view(ROOT, q=str(a.get("query") or ""), sort=str(a.get("sort") or "featured"),
                        health=a.get("health"))
    limit = int(a.get("limit") or 50)
    return {"count": len(v["rows"]), "query": v["query"],
            "rows": [{k: r.get(k) for k in ROW_FIELDS} for r in v["rows"][:limit]]}


def t_inbox(a: dict) -> dict:
    v = views.dash_view(ROOT, repo=a.get("repo") or None)
    limit = int(a.get("limit") or 30)
    return {"repo": v["repo"], "count": len(v["inbox"]), "items": v["inbox"][:limit]}


def t_docker(_: dict) -> dict:
    return views.docker_view(fl.load_snapshot(ROOT).rows)


WORK_FIELDS = ("key", "kind", "repo", "ref", "title", "lane", "priority", "priority_source", "rank", "loop",
               "next_run", "url", "note")


def t_work(a: dict) -> dict:
    """The Work board, in the order the loops take it, with the human's pins
    and overrides applied (_data/work_queue.yml) — what to pick up next."""
    sys.path.insert(0, str(ROOT / ".github" / "scripts" / "dash-gen"))
    import work_board  # noqa: WPS433 — dash-gen's own module, only when asked

    doc = work_board.build(work_board.load_inputs(ROOT, local=True))
    rows = [it for it in doc["items"]
            if (not a.get("lane") or it["lane"] == a["lane"]) and (not a.get("repo") or it["repo"] == a["repo"])
            and (not a.get("kind") or it["kind"] == a["kind"]) and (not a.get("next_only") or it["next_run"])]
    limit = int(a.get("limit") or 25)
    return {
        "lanes": {lane["id"]: lane["count"] for lane in doc["lanes"]},
        "loops": [{k: lp.get(k) for k in ("id", "label", "cap", "eligible", "next_run", "drain_runs", "drain_days")}
                  for lp in doc["loops"]],
        "hints": [h["text"] for h in doc["hints"]],
        "count": len(rows),
        "items": [{k: it.get(k) for k in WORK_FIELDS} for it in rows[:limit]],
    }


def _atlas():
    sys.path.insert(0, str(ROOT / ".github" / "scripts" / "dash-gen"))
    import workflow_atlas  # noqa: WPS433 — dash-gen's own module, only when asked
    return workflow_atlas


WORKFLOW_FIELDS = ("id", "name", "group", "purpose_text", "triggers", "switch", "lines", "findings")


def t_workflows(a: dict) -> dict:
    """The hub's workflows as one model (the workflow atlas): one workflow or
    action in full, or the catalog with every finding; `health` adds run
    health and failure causes from the local lake."""
    wa = _atlas()
    atlas = wa.scan(ROOT)
    if a.get("workflow"):
        wid = str(a["workflow"])
        hit = next((w for w in atlas["workflows"] if w["id"] == wid), None) or \
            next((x for x in atlas["actions"] if x["id"] == wid), None)
        if hit is None:
            raise ValueError(f"no workflow or action called {wid!r}")
        return {"item": hit, "findings": [f for f in atlas["findings"] if f["target"] == wid]}
    out = {"summary": atlas["summary"], "findings": atlas["findings"],
           "rules": [{k: r[k] for k in ("id", "severity", "title", "fix", "gate")} for r in atlas["rules"]],
           "workflows": [{k: w.get(k) for k in WORKFLOW_FIELDS} for w in atlas["workflows"]],
           "actions": [{"id": x["id"], "used_by": x["used_by"], "findings": x["findings"]} for x in atlas["actions"]]}
    if a.get("health"):
        h = wa.lake_health(None, atlas["hub"], int(a.get("days") or 30), ROOT)
        out["health"] = {k: h.get(k) for k in ("present", "error", "days", "totals", "classes", "ghosts", "class_hints")}
        out["health"]["workflows"] = [{k: w[k] for k in ("path", "runs", "success_rate", "verdict", "causes", "last_failure")}
                                      for w in h.get("workflows") or []]
    return out


def t_workflow_lint(a: dict) -> dict:
    """Lint a draft workflow against the hub's standards and fleet.yml."""
    wa = _atlas()
    text = str(a["text"])
    if len(text) > 200_000:
        raise ValueError("a workflow draft is limited to 200 KB")
    wid = str(a.get("id") or "draft")
    if not wa.ID_RX.match(wid):
        raise ValueError("id must be lowercase letters, digits and dashes, starting with a letter")
    res = wa.lint_text(text, wa.load_fleet(ROOT), f".github/workflows/{wid}.yml")
    w = res["workflow"]
    return {"findings": res["findings"], "tally": res["tally"],
            "parsed": {k: w.get(k) for k in ("name", "triggers", "crons", "dispatch_inputs", "switch", "ai_sites", "parse_error")}}


def t_ops(_: dict) -> dict:
    return {"ops": console().ops()}


def t_run(a: dict) -> dict:
    return {"job": console().submit(str(a["op"]), a.get("params") or {}, confirm=bool(a.get("confirm")))}


def t_jobs(a: dict) -> dict:
    return {"jobs": console().jobs()[: int(a.get("limit") or 20)]}


def t_log(a: dict) -> dict:
    tail = console().tail(str(a["job_id"]), int(a.get("offset") or 0))
    text = tail.get("text") or ""
    if len(text) > 20000:  # keep a result inside an agent's context; page with offset
        tail["text"], tail["truncated"] = text[-20000:], True
    return tail


def t_cancel(a: dict) -> dict:
    return {"job": console().cancel(str(a["job_id"]))}


def _schema(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


READ = {"readOnlyHint": True, "openWorldHint": False}
TOOLS: dict[str, dict] = {
    "fleet_overview": dict(fn=t_overview, annotations=READ, schema=_schema(),
                           description="Fleet KPIs, signal freshness, tripped harness wires and the red repos."),
    "fleet_apps": dict(fn=t_apps, annotations=READ, description=(
        "Registry projects with health, CI, triage, open work and containers — the Apps view. "
        "Filter by text and level, sort like the dashboards."), schema=_schema({
            "query": {"type": "string", "description": "substring of name/description/stack"},
            "sort": {"type": "string", "enum": list(fl.SORTS)},
            "health": {"type": "string", "enum": list(fl.LEVELS)},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100}})),
    "fleet_inbox": dict(fn=t_inbox, annotations=READ, description=(
        "The fleet inbox (flagged issues, PRs and failing workflows, highest priority first), or every open "
        "item of one repo."), schema=_schema({
            "repo": {"type": "string", "description": "registry name for the drill-down"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 150}})),
    "fleet_docker": dict(fn=t_docker, annotations={"readOnlyHint": True, "openWorldHint": True},
                         schema=_schema(), description="Containers on every DASH_DOCKER_HOST, attributed to projects."),
    "fleet_work": dict(fn=t_work, annotations=READ, description=(
        "Every open issue, PR, roadmap spec, spec package and BACKLOG.md item, in the order the loops take "
        "it (the Work board): the human's pins and priority overrides first, the next run's picks marked, "
        "each loop's capacity and drain time. Read it before choosing what to work on."), schema=_schema({
            "lane": {"type": "string", "enum": ["triage", "ready", "doing", "review", "blocked", "hold"]},
            "repo": {"type": "string", "description": "registry name"},
            "kind": {"type": "string", "enum": ["issue", "pr", "roadmap", "spec", "backlog"]},
            "next_only": {"type": "boolean", "description": "only what a loop's next run takes"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200}})),
    "fleet_workflows": dict(fn=t_workflows, annotations=READ, description=(
        "The hub's GitHub Actions as one model (the workflow atlas): every workflow and composite action with "
        "its triggers, crons, inputs, jobs, Claude call sites and kill switch, and every finding against the "
        "standards. Pass `workflow` for one in full; `health` adds run health and failure causes (capacity · "
        "config · transient · dependency · defect) from the local lake. Read it before changing a workflow."),
        schema=_schema({
            "workflow": {"type": "string", "description": "a workflow file stem (fleet-pulse) or action id (claude-cost)"},
            "health": {"type": "boolean", "description": "add run health from the local lake"},
            "days": {"type": "integer", "minimum": 1, "maximum": 365}})),
    "workflow_lint": dict(fn=t_workflow_lint, annotations=READ, description=(
        "Lint a draft workflow (YAML text) against the hub's standards and _data/fleet.yml: permissions, "
        "timeouts, concurrency, crons, kill switch, Claude budget and usage-limit pairing, null dispatch inputs, "
        "PR token, bare pushes. Nothing is written."),
        schema=_schema({"text": {"type": "string", "description": "the workflow file's YAML"},
                        "id": {"type": "string", "description": "the file stem it will have (its fleet.yml keys)"}}, ["text"])),
    "console_ops": dict(fn=t_ops, annotations=READ, schema=_schema(), description=(
        "The Harness Console's allowlisted operations: id, title, params, and whether one can write to GitHub.")),
    "console_run": dict(fn=t_run, description=(
        "Run one allowlisted operation as a console job (the same job the browser and the TUI list). "
        "Writing operations are refused unless confirm=true — get the user's go-ahead first."),
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
        schema=_schema({"op": {"type": "string"},
                        "params": {"type": "object", "description": "the operation's params, see console_ops"},
                        "confirm": {"type": "boolean", "default": False}}, ["op"])),
    "console_jobs": dict(fn=t_jobs, annotations=READ, description="Recent console jobs, newest first.",
                         schema=_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 200}})),
    "console_job_log": dict(fn=t_log, annotations=READ, description=(
        "A job's log from `offset` and its status; call again with the returned offset to follow it."),
        schema=_schema({"job_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}, ["job_id"])),
    "console_cancel": dict(fn=t_cancel, description="Cancel a running console job.",
                           annotations={"readOnlyHint": False, "destructiveHint": True},
                           schema=_schema({"job_id": {"type": "string"}}, ["job_id"])),
}


# ------------------------------------------------------------------ protocol
def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # a notification (initialized, cancelled, …): no reply
        return None

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return ok({"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": t["description"], "inputSchema": t["schema"],
                              "annotations": t["annotations"]} for n, t in TOOLS.items()]})
    if method == "tools/call":
        params = msg.get("params") or {}
        tool = TOOLS.get(params.get("name"))
        if tool is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {params.get('name')!r}"}}
        try:
            result, is_error = tool["fn"](params.get("arguments") or {}), False
        except ConsoleError as exc:  # the console's own answer — a refusal is information, not a crash
            result, is_error = {"error": str(exc)}, True
        except (KeyError, ValueError, TypeError) as exc:
            result, is_error = {"error": f"bad arguments: {exc}"}, True
        return ok({"content": [{"type": "text", "text": json.dumps(result, default=str, indent=1)}],
                   "isError": is_error})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Harness Console MCP server — the console's HTTP API for any MCP client.

Read tools wrap the console's GET routes (fleet, harness health and scorecard,
live snapshot, sessions, jobs and logs, spend, the data lake's traces and
workflow lines, observability, semantic code search, deep dive, work board).
Write tools (run an allowlisted op, cancel a job, flip a workflow kill switch)
are NOT registered unless HARNESS_MCP_ALLOW_WRITES=1, are annotated
destructive, and every one also needs confirm=true per call; the console's own
allowlist and confirm-before-GitHub-write gate still apply server-side.

Transports
  stdio            python3 -m mcp_layer.server               (Claude Code, Cursor, local agents)
  streamable HTTP  python3 -m mcp_layer.server --http [--port 4002]
                   binds 127.0.0.1, requires `Authorization: Bearer <HARNESS_MCP_TOKEN>`
                   (its own token, never the console's), refuses to start without one.
  --fleet-compat   also registers the legacy `fleet` server's console_run / console_cancel (the merged
                   tools/fleetcore/mcp_server.py; `.mcp.json` `fleet` runs this), whose writing ops the console
                   itself refuses without confirm=true.

Env: DASH_CONSOLE_URL (default http://127.0.0.1:4001), DASH_CONSOLE_TOKEN,
HARNESS_MCP_TOKEN, HARNESS_MCP_ALLOW_WRITES, HARNESS_MCP_HOST, HARNESS_MCP_PORT,
HARNESS_MCP_MAX_CHARS (default 60000). Tokens are never printed or returned.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/console, for mcp_layer

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from mcp_layer.client import Console, ConsoleError, dotenv_value  # noqa: E402

VERSION = "0.1.0"
INSTRUCTIONS = (
    "bamr87 Harness Console: the fleet's control plane. Start with console_overview, then drill in: "
    "fleet_status, harness_health, live_snapshot, jobs_list/job_log, spend_vs_budget, lake_runs, workflow_lines, "
    "code_search, deep_dive. Write tools exist only when the operator enabled them; each needs confirm=true and "
    "you must ask the user before setting it."
)
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
ROW_FIELDS = ("name", "status", "category", "featured", "worst_level", "health", "triage_level", "triage_score",
              "ci_last", "ci_pass", "last_commit_days", "failing", "reasons", "docker_up", "docker_total", "repo_url")


def truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def max_chars() -> int:
    try:
        return max(2000, int(os.environ.get("HARNESS_MCP_MAX_CHARS", "60000")))
    except ValueError:
        return 60000


def clip(obj: Any, limit: int | None = None) -> Any:
    """Keep a tool result inside the client's context: oversized payloads become a marked, truncated string."""
    limit = limit or max_chars()
    text = json.dumps(obj, default=str)
    if len(text) <= limit:
        return obj
    return {"truncated": True, "total_chars": len(text), "json_prefix": text[:limit]}


def build_server(console: Console | None = None, allow_writes: bool | None = None,
                 fleet_compat: bool | None = None) -> MCPServer:
    c = console or Console()
    compat = truthy(os.environ.get("HARNESS_MCP_FLEET_COMPAT")) if fleet_compat is None else fleet_compat
    writes = truthy(os.environ.get("HARNESS_MCP_ALLOW_WRITES")) if allow_writes is None else allow_writes
    mcp = MCPServer(name="harness-console", title="bamr87 Harness Console", version=VERSION, instructions=INSTRUCTIONS)

    def call(fn, *a, **kw):
        try:
            out = fn(*a, **kw)
            # A bare list becomes one object, so every client sees one JSON document (and structured content).
            return clip({"count": len(out), "items": out} if isinstance(out, list) else out)
        except ConsoleError as e:
            # Surface as a tool error (isError) with the console's reason; never the token.
            raise ToolError(str(e)) from None

    def state() -> dict:
        return c.get("/api/state")

    # ------------------------------------------------------------ read tools
    @mcp.tool(annotations=READ)
    def console_overview() -> Any:
        """Console health, git head, signal freshness, KPIs and whether MCP write tools are enabled."""
        def run():
            s = state()
            h = s.get("health", {})
            return {"console": c.get("/api/health"), "generated_at": s.get("generated_at"), "git": s.get("git"),
                    "sources": s.get("sources"), "tripped_wires": h.get("tripped_count"),
                    "harness_totals": s.get("harnesses", {}).get("totals"), "mcp_writes_enabled": writes,
                    "console_url": c.url}
        return call(run)

    @mcp.tool(annotations=READ)
    def fleet_status(q: str = "", sort: str = "featured", limit: int = 50) -> Any:
        """Every registry project with health, triage, CI and docker status. q filters by text; sort: featured|triage|name|health."""
        def run():
            v = c.get("/api/fleet", q=q, sort=sort)
            rows = v.get("rows", v if isinstance(v, list) else [])
            out = {k: v[k] for k in ("kpis", "sources") if isinstance(v, dict) and k in v}
            out["rows"] = [{k: r.get(k) for k in ROW_FIELDS if k in r} for r in rows[: max(1, min(limit, 200))]]
            out["total"] = len(rows)
            return out
        return call(run)

    @mcp.tool(annotations=READ)
    def fleet_docker() -> Any:
        """Containers on every Docker host the console knows about."""
        return call(c.get, "/api/fleet/docker")

    @mcp.tool(annotations=READ)
    def project_detail(name: str) -> Any:
        """One registry project: its row, harness, health and links."""
        return call(c.get, f"/api/project/{name}")

    @mcp.tool(annotations=READ)
    def harness_health() -> Any:
        """The hub's six-layer harness health: scorecard, trip wires (tripped first) and notes."""
        def run():
            h = state().get("health", {})
            wires = sorted(h.get("trip_wires", []), key=lambda w: not w.get("tripped"))
            return {**{k: h.get(k) for k in ("generated_at", "scorecard", "tripped_count", "note", "sources")},
                    "trip_wires": wires}
        return call(run)

    @mcp.tool(annotations=READ)
    def harness_scorecard(repo: str = "") -> Any:
        """Per-repo AI harness inventory: totals, trends, attention list; pass repo to get one repo's entry."""
        def run():
            hs = state().get("harnesses", {})
            if repo:
                repos = hs.get("repos", {})
                hit = repos.get(repo) if isinstance(repos, dict) else next((r for r in repos if r.get("name") == repo), None)
                if hit is None:
                    raise ConsoleError(f"no harness entry for {repo!r}")
                return hit
            return {k: hs.get(k) for k in ("generated_at", "totals", "trends", "throughput", "attention", "note")}
        return call(run)

    @mcp.tool(annotations=READ)
    def live_snapshot() -> Any:
        """One-shot live view: sessions, Claude live usage, jobs, spend, health, deep dive, observability.
        Needs the console's /api/live route (bamr87/bamr87#432)."""
        def run():
            try:
                return c.get("/api/live")
            except ConsoleError as e:
                if e.status == 404:
                    raise ConsoleError("this console has no /api/live yet — it ships with bamr87/bamr87#432") from None
                raise
        return call(run)

    @mcp.tool(annotations=READ)
    def sessions() -> Any:
        """Active and idle local agent sessions (Claude Code / desktop) from the live collector (#432)."""
        def run():
            try:
                return c.get("/api/live").get("sessions")
            except ConsoleError as e:
                if e.status == 404:
                    raise ConsoleError("sessions come from /api/live (bamr87/bamr87#432); use agent_activity instead") from None
                raise
        return call(run)

    @mcp.tool(annotations=READ)
    def agent_activity(days: int = 7, repo: str = "", limit: int = 10) -> Any:
        """Local Claude Code sessions + CI agent runs, unified and analysed (the /activity page)."""
        return call(c.get, "/api/lake/review", days=days, repo=repo or None, limit=limit)

    @mcp.tool(annotations=READ)
    def ops_list() -> Any:
        """The console's allowlisted operations (what a job can run), with params and whether they write remotely."""
        return call(c.get, "/api/ops")

    @mcp.tool(annotations=READ)
    def jobs_list(status: str = "", limit: int = 25) -> Any:
        """Recent console jobs, newest first. status filters (running, finished, failed, ...)."""
        def run():
            jobs = c.get("/api/jobs")
            if status:
                jobs = [j for j in jobs if j.get("status") == status]
            return jobs[: max(1, min(limit, 200))]
        return call(run)

    @mcp.tool(annotations=READ)
    def job_log(job_id: str, offset: int = 0, tail_chars: int = 20000) -> Any:
        """A job's status and log from offset; the log is cut to its last tail_chars characters."""
        def run():
            d = c.get(f"/api/jobs/{job_id}", offset=offset)
            log = d.get("log", "")
            if isinstance(log, str) and len(log) > tail_chars:
                d = {**d, "log": log[-tail_chars:], "log_truncated": True}
            return d
        return call(run)

    @mcp.tool(annotations=READ)
    def spend_vs_budget() -> Any:
        """Claude spend and GitHub Actions minutes over the window, against the budgets in _data/fleet.yml."""
        def run():
            s = state()
            usage, contract = s.get("usage", {}), s.get("contract", {})
            budgets = {k: v for k, v in contract.items() if "budget" in k.lower()}
            for k, v in contract.items():
                if isinstance(v, dict):
                    budgets.update({f"{k}.{kk}": vv for kk, vv in v.items() if "budget" in kk.lower() or "cap" in kk.lower()})
            ai = usage.get("ai", {})
            return {"ai": {k: v for k, v in ai.items() if k not in ("by_day", "runs")} if isinstance(ai, dict) else ai,
                    "actions": {k: v for k, v in usage.get("actions", {}).items() if k not in ("by_day", "by_workflow", "runs")},
                    "budgets": budgets}
        return call(run)

    @mcp.tool(annotations=READ)
    def lake_status() -> Any:
        """The data lake (traces plane): reachability, row counts, Phoenix link."""
        return call(c.get, "/api/lake")

    @mcp.tool(annotations=READ)
    def lake_runs(limit: int = 50) -> Any:
        """Recent agent/workflow runs (traces) from the data lake."""
        return call(c.get, "/api/lake/runs", limit=limit)

    @mcp.tool(annotations=READ)
    def workflow_lines(filter: Literal["all", "failing", "noswitch", "ai"] = "all", repo: str = "", limit: int = 100) -> Any:
        """Every workflow with provenance, kill switch and last verdict. filter=noswitch finds scheduled agents that cannot be stopped."""
        def run():
            rows = c.get("/api/lake/lines")
            if repo:
                rows = [r for r in rows if r.get("nwo") == repo or r.get("nwo", "").endswith("/" + repo)]
            if filter == "noswitch":
                rows = [r for r in rows if not r.get("switch")]
            elif filter == "ai":
                rows = [r for r in rows if r.get("ai")]
            elif filter == "failing":
                rows = [r for r in rows if str(r.get("last_conclusion") or r.get("verdict") or "").lower() in ("failure", "failed", "fail")]
            return {"total": len(rows), "rows": rows[: max(1, min(limit, 500))]}
        return call(run)

    @mcp.tool(annotations=READ)
    def observability() -> Any:
        """The log and metrics planes (Elasticsearch/Kibana, Prometheus/Grafana, Phoenix, index): status and links."""
        return call(c.get, "/api/observability")

    @mcp.tool(annotations=READ)
    def code_search(q: str, mode: Literal["search", "harmonize"] = "search") -> Any:
        """Semantic search over the fleet worktrees (Qdrant code index). mode=harmonize finds near-duplicate code."""
        return call(c.get, f"/api/index/{mode}", q=q)

    @mcp.tool(annotations=READ)
    def index_coverage() -> Any:
        """Which repos the semantic code index covers and how fresh it is."""
        return call(c.get, "/api/index/coverage")

    @mcp.tool(annotations=READ)
    def deep_dive() -> Any:
        """Daily deep-dive progress: cycle x/N, today's and next repo, per-repo status and scores."""
        return call(c.get, "/api/data/deep_dive")

    @mcp.tool(annotations=READ)
    def work_board() -> Any:
        """The Work board: every open item on the loops' lanes in the order they take them."""
        return call(c.get, "/api/work")

    @mcp.tool(annotations=READ)
    def loops() -> Any:
        """The control-plane loops (scheduled AI lanes) and their state."""
        return call(lambda: state().get("loops"))

    # ------------------------------------------------------------- resources
    # ------------------------------------- the `fleet` server's tools (merged)
    # tools/fleetcore/mcp_server.py's read tools work from the committed signals, with no console running;
    # its console_* tools are aliases of the routes above. Same names, so `mcp__fleet__*` permissions keep working.
    def fleet_fn(name: str):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # tools/, for fleetcore
        from fleetcore import mcp_server as legacy
        return getattr(legacy, name)

    def local(fn_name: str, args: dict) -> Any:
        try:
            return clip(fleet_fn(fn_name)(args))
        except (ImportError, OSError, KeyError, ValueError, TypeError) as e:
            raise ToolError(f"{fn_name}: {e}") from None

    @mcp.tool(annotations=READ)
    def fleet_overview() -> Any:
        """Fleet KPIs, signal freshness, tripped harness wires and the red repos — from the committed signals."""
        return local("t_overview", {})

    @mcp.tool(annotations=READ)
    def fleet_apps(query: str = "", sort: str = "featured", health: str = "", limit: int = 50) -> Any:
        """Registry projects with health, CI, triage, open work and containers (the Apps view), from committed signals."""
        return local("t_apps", {"query": query, "sort": sort, "health": health or None, "limit": limit})

    @mcp.tool(annotations=READ)
    def fleet_inbox(repo: str = "", limit: int = 30) -> Any:
        """The fleet inbox (flagged issues, PRs, failing workflows, highest priority first), or one repo's open items."""
        return local("t_inbox", {"repo": repo, "limit": limit})

    @mcp.tool(annotations=READ)
    def fleet_work(lane: str = "", repo: str = "", kind: str = "", next_only: bool = False, limit: int = 25) -> Any:
        """The Work board in the order the loops take it, pins and overrides applied, next run's picks marked."""
        return local("t_work", {"lane": lane, "repo": repo, "kind": kind, "next_only": next_only, "limit": limit})

    @mcp.tool(annotations=READ)
    def console_ops() -> Any:
        """Alias of ops_list (the legacy `fleet` name)."""
        return ops_list()

    @mcp.tool(annotations=READ)
    def console_jobs(limit: int = 20) -> Any:
        """Alias of jobs_list (the legacy `fleet` name)."""
        return jobs_list(limit=limit)

    @mcp.tool(annotations=READ)
    def console_job_log(job_id: str, offset: int = 0) -> Any:
        """Alias of job_log (the legacy `fleet` name)."""
        return job_log(job_id, offset)

    @mcp.resource("harness://overview", mime_type="application/json", description="console_overview as a resource")
    def r_overview() -> str:
        return json.dumps(console_overview(), default=str)

    @mcp.resource("harness://health", mime_type="application/json", description="Harness health scorecard and trip wires")
    def r_health() -> str:
        return json.dumps(harness_health(), default=str)

    @mcp.resource("harness://ops", mime_type="application/json", description="Allowlisted operations")
    def r_ops() -> str:
        return json.dumps(ops_list(), default=str)

    @mcp.resource("harness://deep-dive", mime_type="application/json", description="Deep-dive ledger")
    def r_deep() -> str:
        return json.dumps(deep_dive(), default=str)

    @mcp.resource("harness://live", mime_type="application/json", description="Live snapshot (needs #432)")
    def r_live() -> str:
        return json.dumps(live_snapshot(), default=str)

    # ------------------------------------------------- guarded write tools
    if writes:
        def need(confirm: bool, what: str) -> None:
            if not confirm:
                raise ToolError(f"refused: {what} is destructive — ask the user, then call again with confirm=true")

        @mcp.tool(annotations=WRITE)
        def run_op(op: str, params: dict | None = None, confirm: bool = False) -> Any:
            """DESTRUCTIVE. Start an allowlisted console operation as a job (see ops_list). Needs confirm=true;
            the console additionally refuses remote-writing ops unless confirmed."""
            need(confirm, f"running op {op!r}")
            return call(c.post, "/api/jobs", {"op": op, "params": params or {}, "confirm": True})

        @mcp.tool(annotations=WRITE)
        def cancel_job(job_id: str, confirm: bool = False) -> Any:
            """DESTRUCTIVE. Cancel a running console job. Needs confirm=true."""
            need(confirm, f"cancelling job {job_id}")
            return call(c.post, f"/api/jobs/{job_id}/cancel", {})

        @mcp.tool(annotations=WRITE)
        def workflow_kill_switch(owner: str, repo: str, workflow_id: int, enabled: bool, confirm: bool = False) -> Any:
            """DESTRUCTIVE. Enable or disable a GitHub Actions workflow (the kill switch) through the console's
            GitHub link. Needs confirm=true and GitHub writes enabled in the console."""
            action = "workflow.enable" if enabled else "workflow.disable"
            need(confirm, f"{action} on {owner}/{repo} workflow {workflow_id}")
            return call(c.post, f"/api/github/repos/{owner}/{repo}/actions",
                        {"action": action, "params": {"workflow_id": workflow_id}, "confirm": True})

    if writes or compat:
        @mcp.tool(annotations=WRITE)
        def console_run(op: str, params: dict | None = None, confirm: bool = False) -> Any:
            """DESTRUCTIVE (legacy `fleet` name). Run one allowlisted operation as a console job. The console refuses
            a writing operation unless confirm=true — get the user's go-ahead first."""
            return call(c.post, "/api/jobs", {"op": op, "params": params or {}, "confirm": bool(confirm)})

        @mcp.tool(annotations=WRITE)
        def console_cancel(job_id: str) -> Any:
            """DESTRUCTIVE (legacy `fleet` name). Cancel a running console job."""
            return call(c.post, f"/api/jobs/{job_id}/cancel", {})

    return mcp


# ---------------------------------------------------------------- HTTP auth
class BearerAuth:
    """ASGI wrapper: every request needs `Authorization: Bearer <token>` (constant-time compare)."""

    def __init__(self, app, token: str):
        if not token:
            raise ValueError("refusing to serve MCP over HTTP without a token")
        self.app, self._token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope.get("headers") or []).get(b"authorization", b"")
            ok = got.startswith(b"Bearer ") and hmac.compare_digest(got[7:].strip(), self._token)
            if not ok:
                body = b'{"error":"unauthorized"}'
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def http_token() -> str:
    """HARNESS_MCP_TOKEN only — the HTTP face has its own secret, so the console token never leaves the machine."""
    return os.environ.get("HARNESS_MCP_TOKEN") or dotenv_value("HARNESS_MCP_TOKEN")


def http_app(server: MCPServer, host: str, port: int, token: str, extra_hosts: list[str] | None = None):
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"] + (extra_hosts or [])
    sec = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                    allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in extra_hosts or []])
    return BearerAuth(server.streamable_http_app(transport_security=sec, host=host), token)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Harness Console MCP server")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default=os.environ.get("HARNESS_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("HARNESS_MCP_PORT", "4002")))
    ap.add_argument("--allow-host", action="append", default=[], help="extra Host header to accept (e.g. a tunnel name)")
    ap.add_argument("--fleet-compat", action="store_true",
                    help="register the legacy fleet server's console_run/console_cancel too (stdio .mcp.json `fleet`)")
    ap.add_argument("--list-tools", action="store_true", help="print the tool catalog and exit")
    a = ap.parse_args(argv)
    server = build_server(fleet_compat=True if a.fleet_compat else None)
    if a.list_tools:
        import anyio
        for t in anyio.run(server.list_tools):
            kind = "WRITE" if t.annotations and t.annotations.destructive_hint else "read"
            print(f"{kind:5}  {t.name}")
        return 0
    if not a.http:
        server.run("stdio")
        return 0
    token = http_token()
    if not token:
        print("harness-mcp: set HARNESS_MCP_TOKEN (env or .env) before serving HTTP — the console token is not reused", file=sys.stderr)
        return 2
    if a.host not in ("127.0.0.1", "localhost", "::1") and not Path("/.dockerenv").exists():
        print(f"harness-mcp: WARNING binding {a.host} — reachable beyond this machine; bearer auth still required", file=sys.stderr)
    import uvicorn
    print(f"harness-mcp: streamable HTTP on http://{a.host}:{a.port}/mcp (bearer auth; writes "
          f"{'ENABLED' if truthy(os.environ.get('HARNESS_MCP_ALLOW_WRITES')) else 'disabled'})", file=sys.stderr)
    uvicorn.run(http_app(server, a.host, a.port, token, a.allow_host), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

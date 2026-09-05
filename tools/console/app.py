#!/usr/bin/env python3
"""
app — the Harness Console's HTTP surface (FastAPI).

Thin by design: every route is a call into core.py (state, allowlist, jobs,
contract). Run it with tools/console/run.sh (native) or `docker compose up -d
console`; open http://127.0.0.1:4001/. Interactive API docs at /docs.

Security posture: loopback by default; an optional shared secret
(DASH_CONSOLE_TOKEN) is required as `Authorization: Bearer …` on every /api
route when set — the knob for running the console anywhere but localhost.
Binding to loopback is not on its own enough: a page on any site can make the
browser resolve its own hostname to 127.0.0.1 (DNS rebinding) and then speak
to this origin as same-origin, which for a console that can dispatch
workflows and run --apply fan-outs with the operator's FLEET_TOKEN is a real
lever. So every request's Host header is checked against a loopback allowlist
(extend it with DASH_CONSOLE_ALLOWED_HOSTS when fronting the console with a
proxy or a real hostname).
Credentials: jobs inherit the process environment exactly like a terminal
would, and every status document reports credential NAMES and presence only —
never a value or a prefix. The /api/auth routes let the operator hand this
process a credential (it lives in the environment a job inherits, dies with the
process, and is written to the gitignored .env only on an explicit confirm) or
hand a GitHub token to `gh auth login --with-token` over stdin, so the one
surface meant to be self-sufficient no longer dead-ends at "go find a
terminal". DASH_CONSOLE_AUTH=off refuses every credential write.
"""
from __future__ import annotations

import os
import secrets as _secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import core

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="bamr87 Harness Console", version="0.3.0",
              description="Local control plane for the fleet's AI harnesses and schedules — "
                          "with the local data lake and Phoenix traces.")
jobs = core.JobManager()

# Hosts this console answers to. Loopback names only by default; a deployment
# behind a proxy or on a real hostname names itself in DASH_CONSOLE_ALLOWED_HOSTS
# (comma-separated) — and should also set DASH_CONSOLE_TOKEN.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"} | {
    h.strip().lower() for h in (os.environ.get("DASH_CONSOLE_ALLOWED_HOSTS") or "").split(",") if h.strip()
}


@app.middleware("http")
async def guard_host(request: Request, call_next):
    """Reject a rebound hostname before any route sees it (see module docstring)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip().lower()
    if host and host not in ALLOWED_HOSTS:
        return JSONResponse(status_code=421, content={
            "detail": f"host '{host}' is not allowed — the console answers on loopback only; "
                      "set DASH_CONSOLE_ALLOWED_HOSTS to serve another hostname"})
    return await call_next(request)


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("DASH_CONSOLE_TOKEN")
    if not expected:
        return
    # constant-time: the token is a shared secret, so don't leak its prefix
    # through comparison timing.
    if not authorization or not _secrets.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="console token required")


class JobRequest(BaseModel):
    op: str
    params: dict = Field(default_factory=dict)
    confirm: bool = False


class ContractUpdate(BaseModel):
    changes: dict


class CredentialUpdate(BaseModel):
    name: str
    value: str
    persist: bool = False
    confirm: bool = False


class GithubAuth(BaseModel):
    action: str = "login"          # login | logout
    token: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "repo_root": str(core.REPO_ROOT), "jobs": len(jobs.order)}


@app.get("/api/state", dependencies=[Depends(require_token)])
def state() -> dict:
    return core.load_state()


@app.get("/api/capabilities", dependencies=[Depends(require_token)])
def caps() -> dict:
    return core.capabilities()


@app.get("/api/ops", dependencies=[Depends(require_token)])
def ops() -> list[dict]:
    return core.list_ops()


@app.get("/api/jobs", dependencies=[Depends(require_token)])
def list_jobs() -> list[dict]:
    return jobs.list()


@app.post("/api/jobs", dependencies=[Depends(require_token)], status_code=201)
def submit_job(req: JobRequest) -> dict:
    try:
        job = jobs.submit(req.op, req.params, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job.to_dict()


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
def job_log(job_id: str, offset: int = Query(default=0, ge=0)) -> dict:
    try:
        return jobs.tail(job_id, offset)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such job")


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def cancel_job(job_id: str) -> dict:
    try:
        return jobs.cancel(job_id).to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail="no such job")


@app.get("/api/lake", dependencies=[Depends(require_token)])
def lake(probe: bool = Query(default=True)) -> dict:
    """The local data lake + Phoenix reachability (dash-gen lake status --json)."""
    return core.lake_status(probe)


@app.get("/api/lake/runs", dependencies=[Depends(require_token)])
def lake_runs(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    return core.lake_runs(limit)


@app.get("/api/lake/lines", dependencies=[Depends(require_token)])
def lake_lines() -> list[dict]:
    """Every workflow in the lake with its GitFactory provenance and kill switch."""
    return core.lake_lines()


@app.get("/api/lake/review", dependencies=[Depends(require_token)])
def lake_review(days: int = Query(default=30, ge=1, le=3650),
                repo: str | None = Query(default=None),
                limit: int = Query(default=10, ge=1, le=100)) -> dict:
    """Local Claude Code sessions + CI agent runs, unified and analyzed."""
    return core.lake_review(days, repo, limit)


@app.get("/api/contract", dependencies=[Depends(require_token)])
def contract() -> dict:
    return core.read_contract()


@app.put("/api/contract", dependencies=[Depends(require_token)])
def update_contract(req: ContractUpdate) -> dict:
    try:
        return core.update_contract(req.changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/config", dependencies=[Depends(require_token)])
def config() -> dict:
    """Every editable knob of _data/fleet.yml with its current value."""
    return core.read_config()


@app.put("/api/config", dependencies=[Depends(require_token)])
def update_config(req: ContractUpdate) -> dict:
    """Apply changes to fleet.yml (comments preserved) and return the git diff."""
    try:
        return core.update_config(req.changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/api/auth", dependencies=[Depends(require_token)])
def auth() -> dict:
    """Credential presence + provenance, gh login state, .env facts. No values."""
    return core.auth_status()


@app.put("/api/auth/credential", dependencies=[Depends(require_token)])
def set_credential(req: CredentialUpdate) -> dict:
    try:
        return core.set_credential(req.name, req.value, req.persist, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.delete("/api/auth/credential/{name}", dependencies=[Depends(require_token)])
def clear_credential(name: str, purge: bool = Query(default=False)) -> dict:
    try:
        return core.clear_credential(name, purge)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.post("/api/auth/github", dependencies=[Depends(require_token)])
def auth_github(req: GithubAuth) -> dict:
    """Sign the gh CLI in with a pasted token (stdin, never argv) or sign it out."""
    try:
        if req.action == "logout":
            return core.gh_logout()
        if req.action != "login":
            raise ValueError("action must be 'login' or 'logout'")
        return core.gh_login(req.token or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api", include_in_schema=False)
def api_root() -> JSONResponse:
    return JSONResponse({"routes": ["/api/state", "/api/capabilities", "/api/ops", "/api/jobs",
                                    "/api/lake", "/api/lake/runs", "/api/lake/lines",
                                    "/api/lake/review",
                                    "/api/contract", "/api/config", "/api/auth",
                                    "/api/auth/credential", "/api/auth/github", "/docs"]})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

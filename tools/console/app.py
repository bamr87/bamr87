#!/usr/bin/env python3
"""
app — the Harness Console's HTTP surface (FastAPI).

Thin by design: every route is a call into core.py (state, allowlist, jobs,
contract). Run it with tools/console/run.sh (native) or `docker compose up -d
console`; open http://127.0.0.1:4001/. Interactive API docs at /docs.

Security posture: loopback by default; an optional shared secret
(DASH_CONSOLE_TOKEN) is required as `Authorization: Bearer …` on every /api
route when set — the knob for running the console anywhere but localhost.
The console never holds GitHub or Claude credentials itself; jobs inherit the
process environment exactly like a terminal would, and the UI only ever sees
which credential NAMES are present.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import core

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="bamr87 Harness Console", version="0.1.0",
              description="Local control plane for the fleet's AI harnesses and schedules.")
jobs = core.JobManager()


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("DASH_CONSOLE_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="console token required")


class JobRequest(BaseModel):
    op: str
    params: dict = Field(default_factory=dict)
    confirm: bool = False


class ContractUpdate(BaseModel):
    changes: dict


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


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api", include_in_schema=False)
def api_root() -> JSONResponse:
    return JSONResponse({"routes": ["/api/state", "/api/capabilities", "/api/ops", "/api/jobs",
                                    "/api/contract", "/docs"]})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

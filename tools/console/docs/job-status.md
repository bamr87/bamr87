# Job status for agents

> Planned (feature `console-job-status`, roadmap FF-0033): lets the bot that sent a console job see its state, ages and why it may be slow.

## Problem

A job sent through the console (`run_op`) returns a receipt. `jobs_list` and `job_log` show the raw `status` and log, but not whether a running job is still making progress or why it is slow. A slow Claude Code session lookup could not be diagnosed this way.

## What it adds

Per job:

| Field | Meaning |
| --- | --- |
| `state` | `queued`, `running`, `stalled`, `done` or `failed` (derived from `status`, `exit_code` and progress) |
| `age_s` | seconds since the job was sent (`created`) |
| `idle_s` | seconds since last progress: log growth, or a heartbeat line |
| `diagnostics` | list of reasons it may be slow, each `{code, detail}` |

Diagnostic codes (first set): `queue_wait` (queued behind a job holding the same lock), `collector_lag` (the live collector's `sessions.json` is older than its interval), `long_step` (a step running past its typical duration), `no_heartbeat` (no log growth past the stall threshold).

A running job becomes `stalled` when `idle_s` passes a threshold (default 120 s, per-op override in the op's entry).

## Surfaces

- API: `GET /api/jobs/{id}/status`; `GET /api/jobs` rows gain `state`, `age_s`, `idle_s`, `diagnostics`.
- MCP (read tools): `job_status(job_id)`; `jobs_list` gains the same fields and a `state` filter.
- UI: the Jobs page shows the state badge, both ages and the diagnostics.

## Prior art reused

`Job` / `JobManager` in `../core.py`, `jobs_list`, `job_log`, `sessions`, `ops_list` in `../mcp_layer/server.py`, and the live collector from #432.

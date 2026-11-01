---
id: ADP-08
chapter: 8
title: Memory Management
book_pages: "Ch. 8 (21 pp.)"
status: partial
evidence_repos: [bamr87/bamr87, bamr87/README]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Memory Management

## Summary

An agent that does more than answer one question needs memory. Gulli splits it in two. **Short-term (contextual) memory** is what sits in the context window right now: recent turns, tool results, reflections. It is limited, costly to reprocess and lost when the session ends, so it has to be curated by summarizing, trimming and keeping only what matters. **Long-term (persistent) memory** lives outside the model in databases, knowledge graphs or vector stores. The agent queries it and pulls relevant pieces back into the short-term context. Long-term memory comes in three kinds: *semantic* (facts), *episodic* (past experiences or runs) and *procedural* (rules and instructions, which the agent can update). Frameworks give these parts names, such as a session/thread, a scoped state dictionary (`user:`, `app:`, `temp:` prefixes in ADK) and a searchable memory service. The book's rule of thumb is to use this pattern "whenever the agent is expected to learn or adapt based on past successes, failures, or newly acquired information" (ch. 8, "At a Glance").

## When to use / not

- Use it for multi-step tasks, recurring bots that should not repeat past mistakes, and personalization.
- Skip it for stateless one-shot transforms. Persisting those only adds privacy risk and staleness.

## Failure modes

- Unbounded growth (cost, slow recall).
- Stale memory treated as truth.
- Secrets written into memory.
- Changing state directly instead of through recorded events.
- No eviction or provenance.
- Recall that floods the context window.

## Fleet evidence (hub commit 2321b3a7c1199688042339d68b628f9d08bb46eb; README commit d4ea571b470cc826ff8ab10323e3aff68f64111d)

| Memory kind | Fleet implementation | Permalink |
|---|---|---|
| Procedural (long-term rules every agent loads) | `AGENTS.md` + `.claude/skills/*` + constitution are the fleet's standing instructions, versioned in git | [AGENTS.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/AGENTS.md), [.claude/skills](https://github.com/bamr87/bamr87/tree/2321b3a7c1199688042339d68b628f9d08bb46eb/.claude/skills) |
| Short-term context injection at session start | SessionStart hook adds standing context to every Claude Code session; fails open | [settings.json L16-25](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.claude/settings.json#L16-L25), [future_features_session_start.py L1-12](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.claude/hooks/future_features_session_start.py#L1-L12) |
| Episodic (past sessions, turns, tool calls) | Data lake `.dash-lake/fleet.sqlite`: `sessions`, `session_turns`, `session_tools` tables; mtime-skip makes re-ingest idempotent | [fleet_lake.py L128-142](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/fleet_lake.py#L128-L142), [L1577-1583](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/fleet_lake.py#L1577-L1583), architecture [HARNESS-OPS.md L96-109](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/HARNESS-OPS.md#L96-L109) |
| Episodic recall exposed to agents | Console MCP read tools `agent_activity`, `lake_status`, `lake_runs` | [mcp_layer/server.py L321-388](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/console/mcp_layer/server.py#L321-L388) |
| Bounded, redacted event memory (eviction + provenance) | Activity spool capped at 5000 events, oldest dropped with a `dropped` marker, token redaction before write | [fleet_activity.py L50](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleet_activity.py#L50), [L94-101](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleet_activity.py#L94-L101), [L196-215](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleet_activity.py#L196-L215) |
| Semantic (distilled fleet facts) + fingerprinted AI cache | README context pyramid (cards/facts/apex) served read-only over MCP; AI cache keyed by fingerprint, so an unchanged corpus makes 0 API calls | [mcp/server.py L1-19](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/mcp/server.py#L1-L19), [PLAN.md L555](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/PLAN.md#L555) |

### Reproduce

```bash
git clone -q https://github.com/bamr87/bamr87 /tmp/hub && cd /tmp/hub && git checkout -q 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q .github/scripts/dash-gen/test_fleet_lake.py   # episodic store: session ingest
python3 -m pytest -q tools/test_backlog_fanout.py                  # exercises fleet_activity emit/retry events
git clone -q https://github.com/bamr87/README /tmp/readme && cd /tmp/readme && git checkout -q d4ea571b470cc826ff8ab10323e3aff68f64111d
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"context_status","arguments":{}}}' | python3 mcp/server.py
```

Expected (run 2026-10-31): `24 passed`, `11 passed`; `context_status` returns JSON with `generated_at 2026-10-26T03:14:56+00:00`, `project_count 7` and per-project fingerprints. Green CI: hub [Python tests 41256758330](https://github.com/bamr87/bamr87/actions/runs/41256758330); README [CI 41174877803](https://github.com/bamr87/README/actions/runs/41174877803).

## Gaps

1. **GAP: no queryable long-term semantic memory for bots ("second brain").** The planned `brain.db` and second-brain MCP server do not exist on `main` of bamr87/bamr87 or bamr87/README. Searching code and issues for `brain` finds nothing. → [bamr87/README#46](https://github.com/bamr87/README/issues/46).
2. **GAP: no recall over session content.** `session_turns.text` is stored, but no MCP tool searches past sessions by meaning or keyword. `agent_activity` only returns aggregates. → [bamr87/bamr87#546](https://github.com/bamr87/bamr87/issues/546).
3. **GAP: no memory summarization or compaction policy** for long sessions or the lake (the book's short-term curation). The spool caps size by dropping events; nothing summarizes them. → [bamr87/bamr87#546](https://github.com/bamr87/bamr87/issues/546) (digest option).
Editor note: the console MCP test (`tools/console/test_mcp_layer.py`) was rerun with its optional deps (`uv run --with mcp --with pytest --with pyyaml python -m pytest -q test_mcp_layer.py`): 36 passed. The aggregate `agent_activity` reads are verified; recall over session content is still the gap in item 2.

## Cross-links

ADP-14 RAG (long-term recall is retrieval; same store), ADP-19 monitoring (the lake is shared), ADP-12 (retry events in the spool); constitution §16 (MCP layer per repo), §15 testing evidence; [#409](https://github.com/bamr87/bamr87/issues/409) fleet activity log PRD.

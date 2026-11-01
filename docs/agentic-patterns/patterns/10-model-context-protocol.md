---
id: ADP-10
chapter: 10
title: Model Context Protocol (MCP)
book_pages: 167-182
status: proven
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Tools
---
# Model Context Protocol (MCP)

## Summary

MCP standardizes how agents discover and call external capabilities. A server exposes tools, resources and prompts over JSON-RPC (stdio or streamable HTTP); any compliant client lists and invokes them, so integrations are written once instead of per-framework. Gulli contrasts it with ad-hoc function calling: MCP is the open, client/server, discoverable layer on top. Design concerns he stresses include agent-friendly (not raw) API wrapping, auth, and limiting what the server exposes.

## When to use / not

- Use: one capability needed by several agent hosts (Claude Code, Cursor, custom kernels).
- Avoid: a single in-process tool used by one agent; exposing write ops without gating.

## Failure modes

- Over-broad servers.
- Unauthenticated HTTP transports.
- Tool output too large.
- Writes without human confirm.

## Fleet evidence

1. **Repo-level MCP registration.** `.mcp.json` registers github, memory, playwright and the in-house `fleet` server (`tools/console/mcp.sh --fleet-compat`). https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.mcp.json
2. **Harness Console MCP server.** `tools/console/mcp_layer/server.py`: stdio + streamable HTTP (loopback, own bearer token), write tools only registered when explicitly enabled, annotated destructive, and need `confirm=true` per call. https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/console/mcp_layer/server.py
3. **Fleetcore stdlib MCP server** (compat entry). https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleetcore/mcp_server.py
4. Policy: constitution §16 L192 requires MCP manifests per the MCP Registry `server.json` schema. https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md#L192

Reproduce (run 2026-10-31):

```bash
git clone https://github.com/bamr87/bamr87 && cd bamr87 && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q tools/test_fleetcore_mcp.py           # observed: 8 passed
cd tools/console && uv run --with mcp --with pytest --with pyyaml python -m pytest -q test_mcp_layer.py
# observed: 36 passed (without --with pyyaml, MergedFleet::test_fleet_reads_use_committed_signals fails: No module named 'yaml')
```

Editor note: the one failure seen in the first run was an environment issue (PyYAML not in the ad-hoc env), not a product defect. With PyYAML all 36 pass.

## Gaps

- No `server.json` (MCP Registry manifest) for the console MCP server, despite §16. → [#541](https://github.com/bamr87/bamr87/issues/541) (`agent:queued`).

## Cross-links

ADP-05 Tool Use, ADP-15 A2A; constitution §16; #528 kill switches (kill-switch write tool).

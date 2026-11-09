# MCP servers inventory — consolidation checklist

> First consolidation set for epic [#683](https://github.com/bamr87/bamr87/issues/683) / backlog [#684](https://github.com/bamr87/bamr87/issues/684).
> Audit date: **2026-11-05** (America/Denver). Hub tree + cheap GitHub API reads of related repos. No submodule checkout edits.
> Tick when a follow-up PR registers the row as canonical, migrates it, or documents legacy/spoke ownership.

## Hub — client configs

- [ ] `.mcp.json` — root agent MCP client: `github`, `memory`, `sequentialthinking`, `context7`, `playwright`, `fleet`
- [ ] `verify/mcp.json` — verify-kit Playwright MCP for Claude Code evidence passes
- [ ] `templates/verify/mcp.json` — seed copy of verify Playwright MCP for fan-out

## Hub — servers / runtime

- [ ] `tools/console/mcp_layer/` + `tools/console/mcp.sh` + `tools/dash mcp` — Harness Console MCP (HUB-031); stdio + HTTP `:4002`
- [ ] `docker-compose.yml` profile `mcp` — always-on sidecar `127.0.0.1:4002/mcp` (bearer `HARNESS_MCP_TOKEN`)
- [ ] `docker-compose.yml` profile `mcp-tunnel` — cloudflared quick tunnel to `mcp` (unstable hostname)
- [ ] `tools/fleetcore/mcp_server.py` — legacy fleet MCP (delegates to mcp_layer; `FLEET_MCP_STDLIB=1` old loop)
- [ ] Opt-in `ccusage` MCP snippet (`docs/DASH.md`) — documented, not in committed `.mcp.json`

## Hub — docs / specs (align)

- [ ] `tools/console/docs/mcp-layer.md` — operator guide for console MCP
- [ ] `_data/specs.yml` UPS requiring `.mcp.json` baseline (`github`, `memory`, `sequentialthinking`, `context7`)
- [ ] `docs/agentic-patterns/patterns/10-model-context-protocol.md` — ADP-10 evidence
- [ ] #541 — Console MCP Registry `server.json` (AI-ready § 16)

## Related repos (cheaply visible)

- [ ] `githubai` `verify/mcp.json` — Playwright verify kit only (no root `.mcp.json`)
- [ ] `githubai` `ai-seed/.github/instructions/mcp.instructions.md` — agent instructions for MCP
- [ ] `gitorio` `verify/mcp.json` — Playwright verify kit
- [ ] `gitorio` gitnexus MCP route — app-served MCP surface (spoke-owned)
- [ ] `it-journey` `verify/mcp.json` — Playwright verify kit
- [ ] `it-journey` `scripts/ai/mcp/github-readonly.json` — github MCP with `${GITHUB_MCP_TOKEN}`
- [ ] `it-journey` `scripts/quest/mcp.json` + `mcp_server.py` — quest-system MCP server
- [ ] `bashos` `verify/mcp.json` — Playwright verify kit copy
- [ ] `ocrmd` `verify/mcp.json` — Playwright verify kit copy
- [ ] Fleet docker census `fleet-aieo-mcp-server` / `fleet-aieo-mcp-audit` — AIEO compose services (no host ports); confirm owner path

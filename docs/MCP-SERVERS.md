# MCP server lifecycle

> Status: **proposed** (constitution § 25, amendment `mcp-lifecycle`; epic [#683](https://github.com/bamr87/bamr87/issues/683), backlog [#684](https://github.com/bamr87/bamr87/issues/684)).
> Feature: `HUB-NEW` / slug `mcp-lifecycle`. Requirement: `FR-NEW:mcp-lifecycle`. Roadmap: `FF-0040`.
> Sub-PRD / user stories: [`docs/prd/MCP-SERVERS.md`](prd/MCP-SERVERS.md).
> Operator guide for the console MCP layer (implementation): [`tools/console/docs/mcp-layer.md`](../tools/console/docs/mcp-layer.md).

This is the hub's **centralized** standard for building, registering, configuring and running Model Context Protocol (MCP) servers across the monorepo and related fleet repos. HUB-031 remains the Harness Console MCP implementation; this doc is the lifecycle umbrella.

## Inventory (today)

See the consolidation checklist: [`mcp-servers-inventory.md`](mcp-servers-inventory.md) and issue #684.

Hub highlights:

| Kind | Where | Notes |
| --- | --- | --- |
| Agent client config | [`.mcp.json`](../.mcp.json) | `github`, `memory`, `sequentialthinking`, `context7`, `playwright`, `fleet` |
| Verify kit client | [`verify/mcp.json`](../verify/mcp.json) | Playwright only |
| Console MCP server | `tools/console/mcp_layer/` | stdio + HTTP `:4002`; `tools/dash mcp` |
| Compose | profiles `mcp`, `mcp-tunnel` | Opt-in sidecar + cloudflared quick tunnel |
| Legacy | `tools/fleetcore/mcp_server.py` | Delegates to mcp_layer |

## Registry

Canonical list: [`_data/mcp_servers.yml`](../_data/mcp_servers.yml) (`mcp-servers/v1`).

Every fleet-known MCP server gets a row before it is treated as supported. Status values:

- `canonical` — preferred hub entry
- `legacy` — still works; do not extend; migrate when touched
- `spoke` — owned by another repo; hub tracks for fan-out
- `proposed` — planned / issue-linked

Secret fields store **names only** (`HARNESS_MCP_TOKEN`, `GITHUB_TOKEN`, …). Never values.

## Client config schema

Committed files use:

```json
{
  "mcpServers": {
    "<id>": {
      "command": "…",
      "args": ["…"],
      "env": { "SOME_TOKEN": "${SOME_TOKEN}" }
    }
  }
}
```

HTTP clients (Cursor / remote) may use `url` + `headers` with `${env:NAME}` style interpolation — still no literals.

**Forbidden in git:** personal access tokens, API keys, `sk-…`, `ghp_…`, `gho_…`, bearer literals, private key PEM blocks.

## Naming

- Ids: kebab-case, unique in the registry.
- Keep agent-facing name `fleet` for the console MCP until a migration PR updates `.mcp.json`, permissions (`mcp__fleet__*`), and the registry together.

## Transports and tunnels

| Transport | Use | Guard |
| --- | --- | --- |
| stdio | Local Claude Code / Cursor / `dash mcp` | Default for interactive agents |
| streamable HTTP | Remote agents / compose `mcp` | Loopback bind; `Authorization: Bearer $HARNESS_MCP_TOKEN`; Host allowlist |
| Quick tunnel | Temporary remote demo | Opt-in; hostname unstable; do not commit URL |
| Named tunnel / Tailscale | Standing remote | Document host in allow-list env; refresh docs when DNS changes |

## Auth, writes, kill switch

- Console MCP HTTP auth: `HARNESS_MCP_TOKEN` (separate from `DASH_CONSOLE_TOKEN`).
- Writes: off unless `HARNESS_MCP_ALLOW_WRITES=1`; tools need `confirm=true`.
- GitHub-mutating ops still pass through the console allowlist and workflow kill switches.

## Health

- Compose `mcp` healthcheck: `/mcp` answering **401** (server up, auth required) is healthy.
- `tools/dash mcp --list-tools` / `--tunnel-url` for operator checks.
- P1: `dash mcp status` summarizing registry + live probes.

## Versioning

- Record npm package / Python module identity on the registry row.
- Prefer the UPS baseline for always-on agent servers; document `@latest` when the verify kit intentionally floats.
- Breaking tool renames: registry `notes` + migration window on the epic.

## Lint

```bash
python3 tools/mcp_servers_lint.py check .          # warn-only (default)
python3 tools/mcp_servers_lint.py check . --gate   # hard fail (after adoption)
```

Checks committed MCP JSON configs and `_data/mcp_servers.yml`: shape, inline-secret heuristics, `${ENV}` for secret-looking keys, unknown server ids (warn).

## Fan-out

Hub first. Spoke repos get a seed-kit PR (epic #683 P3) that aligns `verify/mcp.json` / baseline `.mcp.json` and flips the lint from warn to fail. Do not edit submodule checkouts in the ratification PR.

## Related

- Constitution § 16 (AI-ready), § 25 (this standard); HUB-031
- [`tools/console/docs/mcp-layer.md`](../tools/console/docs/mcp-layer.md)
- #541 MCP Registry `server.json`; ADP-10
- Inventory: [`mcp-servers-inventory.md`](mcp-servers-inventory.md)

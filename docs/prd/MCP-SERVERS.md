# PRD — MCP server lifecycle

> Draft / proposed. Requirement id assigned at merge as `FR-NEW:mcp-lifecycle` → predicted **FR84**.
> Feature: `HUB-NEW:mcp-lifecycle`. Epic [#683](https://github.com/bamr87/bamr87/issues/683). Backlog [#684](https://github.com/bamr87/bamr87/issues/684).
> Standard: [`docs/MCP-SERVERS.md`](../MCP-SERVERS.md). Amendment: `mcp-lifecycle` (§ 25).

## Problem

MCP servers are already in daily use (console layer, hub `.mcp.json`, verify Playwright, spoke kits) but setup and config are copy-pasted, tunnels go stale, and nothing stops a token from landing in JSON. Operators and agents lack one registry and one failure model.

## Goals

1. One hub registry and standard for MCP lifecycle.
2. No credentials in committed MCP configs.
3. Warn-then-fail lint so adoption can roll out safely.
4. Clear Design-for-Failure for tunnels, auth, and write kill switches.
5. Path to fan-out without editing every spoke in the ratification PR.

## Non-goals (this slice)

- Building a full console MCP admin UI.
- Automating Cloudflare named-tunnel login.
- Publishing MCP Registry `server.json` (#541) — P2.
- Renaming `fleet` → `harness-console` without a migration PR.

## User stories

| ID | As a… | I want… | So that… |
| --- | --- | --- | --- |
| US1 | fleet operator | a single registry of MCP servers | I know what is canonical vs legacy vs spoke |
| US2 | agent author | a documented `.mcp.json` / verify schema | I can add a server without inventing config |
| US3 | security-conscious owner | lint that rejects inline tokens | secrets never ship in git |
| US4 | remote-agent user | tunnel rules and a refresh command | a quick-tunnel hostname change does not strand me |
| US5 | console operator | write tools off by default with confirm | a confused agent cannot mutate GitHub unchecked |
| US6 | spoke maintainer | a later fan-out kit | my repo adopts the same schema without a hub rewrite |

## Requirements (draft FR text)

`FR-NEW:mcp-lifecycle`: The hub must provide a centralized MCP server lifecycle — registry (`_data/mcp_servers.yml`), standard (`docs/MCP-SERVERS.md`), constitution § 25, and a warn-then-fail config lint — so every fleet MCP server is named, configured without inline secrets, transported safely (stdio / loopback HTTP / opt-in tunnel), health-checked, and ready for spoke fan-out.

## Acceptance

- Amendment + § 25 merged (Amr).
- Registry stub lists the #684 inventory.
- Lint warn-only passes on hub; `--gate` fails fixtures with inline secrets / bad shape.
- Feature + FR compile at merge; FF-0040 linked.

## Design for Failure

Mirror the amendment table: tunnel loss, stale URL, auth expiry, write kill switch, secret-in-JSON, registry drift, spoke lag.

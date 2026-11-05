# NEW — MCP server lifecycle is centrally managed from the hub

- **Status:** proposed (ratification pending — Amr ratifies by merging this PR)
- **Number:** NEW
- **Date:** 2026-11-05
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:**
- **Affects:** constitution § 25 (new, follows § 24 `visual-evidence` on main; renumber only if a later amendment claims 25 first); § 16 by reference (AI-ready foundation / MCP); feature `HUB-NEW:mcp-lifecycle`; requirement `FR-NEW:mcp-lifecycle`; roadmap FF-0040; docs `MCP-SERVERS.md`, `prd/MCP-SERVERS.md`; data `_data/mcp_servers.yml`
- **Supersedes:** none (extends § 16 and HUB-031 without changing console write gates)
- **Related:** epic #683, backlog #684; HUB-031 / `tools/console/docs/mcp-layer.md`; #541 MCP Registry `server.json`; ADP-10; UPS `.mcp.json` baseline in `_data/specs.yml`; process mirror #678 / #679 / PR #680 / § 24 / FF-0039; Design for Failure (DFF, `.github/copilot-instructions.md`)

## Context

Amr's direction: a **centralized, consolidated, harmonized** way to build, manage, set up and configure MCP servers across the monorepo and related fleet repos — single registry/manifest, naming, config schema, auth/secrets (no tokens in repo), transport and tunnel conventions, health checks, versioning, Design-for-Failure, and fan-out from the hub.

Today MCP is real but fragmented. A 2026-11-05 inventory (hub + cheap spoke reads; no submodule edits) found: hub `.mcp.json` (six servers), `verify/mcp.json` + template, Harness Console MCP layer (HUB-031) with compose profiles `mcp` / `mcp-tunnel`, legacy `tools/fleetcore/mcp_server.py`, opt-in ccusage docs, spoke `verify/mcp.json` copies, it-journey quest + github-readonly MCP configs, gitorio gitnexus MCP route, and open #541 for Registry `server.json`. See #684 and `docs/mcp-servers-inventory.md`.

## Prior art

Per 0008, reuse what exists:

- **HUB-031 / `tools/console/mcp_layer/` / `docs/mcp-layer.md`:** production console MCP (stdio + streamable HTTP, bearer auth, write kill switch). Fit: reference server implementation and transport/security rules. Extend, do not fork.
- **`.mcp.json` + UPS baseline:** agent client registration with `${ENV}` secret refs. Fit: client schema. Codify.
- **`verify/mcp.json` kit:** Playwright-only verifier MCP. Fit: kit shape for fan-out. Keep distinct from interactive agent MCP.
- **§ 16 AI-ready / ADP-10 / #541:** per-repo MCP exposure and Registry `server.json`. Fit: later P2; this amendment is the lifecycle umbrella.
- **Build-vs-adopt:** adopt console MCP + `.mcp.json` patterns; new pieces are the constitution rule, hub registry, warn-then-fail lint, and fan-out.

## Amendment

New constitution section:

> ## 25. MCP server lifecycle
>
> _(amendment `mcp-lifecycle`, numbered at merge — see the [amendment log](amendments/README.md); follows § 24 `visual-evidence` on main; renumber only if another amendment claims 25 first; extends § 16)_
>
> 1. **Hub owns the lifecycle** — every MCP server the fleet builds, runs or registers for agents is declared in a hub registry (`_data/mcp_servers.yml`), documented under `docs/MCP-SERVERS.md`, and configured without credentials in git.
> 2. **Single registry** — the registry lists each server's id, owner repo/path, role (client-config | hub-server | spoke-server | kit), transport(s), entrypoint, health probe, required secret *names* (never values), and status (`canonical` | `legacy` | `spoke` | `proposed`).
> 3. **Config schema** — committed MCP client configs (`.mcp.json`, `verify/mcp.json`, kit templates) use the MCP `mcpServers` object shape; secret values appear only as `${ENV_NAME}` (or equivalent host env interpolation); literal tokens, PATs, API keys and passwords are forbidden in the tree.
> 4. **Naming** — server ids are kebab-case, stable, and unique in the registry; the interactive console/fleet server remains registered to agents as `fleet` (HUB-031) unless a migration PR updates permissions and the registry together.
> 5. **Transports** — stdio for local agent hosts; streamable HTTP only on loopback by default with a dedicated bearer (`HARNESS_MCP_TOKEN` for the console MCP, never the console's own token on the wire to clients); non-loopback bind requires an explicit allow-host list.
> 6. **Tunnels** — public or remote access is opt-in (`mcp-tunnel` profile or `dash mcp --tunnel`); quick-tunnel hostnames are unstable and must not be committed; prefer a named tunnel or Tailscale for standing remote access; `dash mcp --tunnel-url` is the refresh path.
> 7. **Writes and kill switch** — MCP write tools stay off unless an explicit env flag enables them; destructive tools require `confirm=true`; console allowlists and workflow kill switches remain authoritative for GitHub writes.
> 8. **Health and versioning** — HTTP MCP servers expose a probe the compose/healthcheck or `dash mcp` can run; package pins prefer dist-tags the registry documents (`@latest` only when the UPS baseline allows); breaking tool renames need a registry note and a migration window.
> 9. **Enforcement** — `tools/mcp_servers_lint.py` validates client configs and registry rows (schema, no inline secrets, unknown ids); warn-only per repo until adoption/fan-out, then hard fail. Fleet fan-out follows the 0007 pattern.
> 10. **Fit with § 16 / HUB-031** — AI-ready per-repo MCP exposure and the console MCP layer stay the implementations; this section is the lifecycle and governance umbrella.

## Design for Failure

| Failure | Behaviour |
| --- | --- |
| Tunnel loss / quick-tunnel hostname change | Treat URL as ephemeral; refresh via `dash mcp --tunnel-url`; never commit `*.trycloudflare.com`; clients get 401/timeout, not silent success |
| Stale remote URL in a connector | Operator refreshes; health probe fails closed; document named-tunnel migration |
| Auth expiry / wrong bearer | HTTP server refuses to start without `HARNESS_MCP_TOKEN`; bad bearer → 401; do not fall back to `DASH_CONSOLE_TOKEN` for client auth |
| Write tools left enabled | Default `HARNESS_MCP_ALLOW_WRITES=0`; compose profile does not enable writes; confirm gate still required |
| Secret pasted into `.mcp.json` | Lint fails (once hard); rotate the leaked credential; scrub history if needed |
| Registry drift (server exists but unlisted) | Inventory checklist on #684; lint warns on unknown ids once the registry is populated |
| Spoke still on old verify kit | Warn-only until fan-out PR; hub template remains the seed |

## Open questions

- Exact registry filename/schema version (`mcp-servers/v1`) — default `_data/mcp_servers.yml` in this PR; confirm at review.
- Whether Cursor project `.cursor/mcp.json` is in-scope for the lint (usually gitignored / local) — default: lint committed files only.
- MCP Registry (`server.json`, #541) publication for the console server — tracked as epic P2, not a P0 blocker.
- Renaming agent-facing `fleet` → `harness-console` — only with an explicit migration PR.

## Consequences

- Agents and humans add or change an MCP server via registry row + config + docs in the same PR.
- Follow-up on #684: populate registry statuses, wire warn-only into hub CI, then P1 `dash mcp status` / console inventory.
- Follow-up (epic #683 P2): consolidate duplicates; #541 `server.json`.
- Follow-up (epic #683 P3): spoke fan-out kit.
- Feature fragment `features/features.d/mcp-lifecycle.yml` (`HUB-NEW`, `FR-NEW:mcp-lifecycle`); roadmap `FF-0040`.
- Predicted ids at merge (as of 2026-11-05 on main): amendment **0024**; feature **HUB-084**; requirement **FR84**. Section number **§ 25**.
- Ratification: Amr ratifies this amendment by merging the PR; agents propose, never merge (§ 8).

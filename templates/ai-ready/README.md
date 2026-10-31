# templates/ai-ready — the AI-ready foundation kit (spec)

> Spec for the kit every repo starts from to meet constitution § 16: an API layer, an MCP server, agent docs and machine-readable metadata, sized to the repo type. Spec only for now; the files land in follow-up PRs after ratification.

## Files (planned)

| File | Seeded to | Purpose |
| --- | --- | --- |
| `ai-ready.template.yml` | `ai-ready.yml` | The manifest: `type`, `api` (OpenAPI path, data API index or CLI JSON commands), `mcp` (server path, transport, `server.json`), `llms_txt`, `schema_md`, `agent_card`, and `not_applicable` entries, each with a reason. |
| `ai-ready.schema.json` | (hub only) | JSON Schema 2020-12 for the manifest. |
| `llms-txt/` | build step | Generator for `llms.txt` from the README, AGENTS.md, API docs and data API index (generalised from the hub's machine API, docs/MACHINE-API.md). |
| `data-api/` | build step | Static JSON data API generator for content sites: `/api/v1/index.json` discovery, `schema_version`, `status: degraded` instead of build failure. |
| `mcp-service/` | `mcp/` | MCP server skeleton for apps, services and tools, based on `tools/fleetcore/mcp_server.py`: read tools by default, writes behind confirmation. |
| `mcp-site/` | `mcp/` | **Per-site content MCP server** for content sites: `search`, `read_page`, `list_collections`, `query_data_api`, reading the site's own static data API. Every content site runs its own; there is no shared fleet server. |
| `server.json.template` | `server.json` | MCP Registry manifest (schema 2025-12-11, name `io.github.<owner>/<repo>`). |
| `cli-json/` | (library) | Helper that adds a `--json` mode to CLI commands. |
| `agent-card.template.json` | `/.well-known/agent-card.json` | A2A Agent Card, only for repos that run an agent. |
| `threshold.yml` | (hub only) | The fleet-wide minimum AIEO score: `min_score: 60` (**PLACEHOLDER; Amr sets the real value**). It fails builds only after AIEO passes its § 13 eval set. |
| `VERSION` | — | Kit provenance and changelog. |

## Requirements by repo type

| Type | API layer | MCP | Agent docs | Metadata |
| --- | --- | --- | --- | --- |
| App or service | REST + committed OpenAPI 3.1 | own server (`mcp-service/`) | AGENTS.md + llms.txt | `ai-ready.yml`, `server.json`; Agent Card if it runs an agent |
| Content site | static JSON data API | own server (`mcp-site/`) | AGENTS.md + llms.txt | `ai-ready.yml`, `server.json`, JSON-LD |
| Tool or CLI | `--json` on every command | own server wrapping the CLI | AGENTS.md + llms.txt | `ai-ready.yml`, `server.json` |
| Library, theme or kit | — | — | AGENTS.md + llms.txt | `ai-ready.yml` |

## Open gap: hosting a content site's MCP server (for Amr)

A static GitHub Pages site cannot host a live MCP server. Options, none chosen yet:

1. **Serverless or edge deployment** per site (for example a Cloudflare Worker, already used in the fleet) serving MCP over Streamable HTTP. Gives a remote endpoint, but each site needs a deployment and possibly an account.
2. **Local stdio server shipped in the repo** (`mcp/`), published as a package, that clients run locally against the site's public static data API. No hosting and $0, but no remote URL.
3. **Both:** (2) as the baseline everywhere, plus (1) where a remote endpoint is wanted.
4. **A self-hosted container** on the forge host, one per site or one process per site.

Until Amr picks, the `ai-ready` check accepts (1) or (2) and reports which.

## Validation

`tools/conformance.py` check `ai-ready` runs the structural checks offline and calls the in-hub AIEO (`tools/aieo/`) for the score. It is warn-only per repo until that repo's fan-out PR lands, then a hard failure. A score below `threshold.yml` fails only once AIEO passes its own eval set.

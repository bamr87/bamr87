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
| `mcp-site/` | `mcp/` | **Per-site content MCP server** for content sites, a **local stdio server** shipped in the repo that clients run: `search`, `read_page`, `list_collections`, `query_data_api`, reading the site's own static data API. Every content site runs its own; there is no shared fleet server. |
| `server.json.template` | `server.json` | MCP Registry manifest (schema 2025-12-11, name `io.github.<owner>/<repo>`). |
| `cli-json/` | (library) | Helper that adds a `--json` mode to CLI commands. |
| `agent-card.template.json` | `/.well-known/agent-card.json` | A2A Agent Card, only for repos that run an agent. |
| `threshold.yml` | (hub only) | The fleet-wide minimum AIEO score: `min_score: 80`. It fails builds only after AIEO passes its § 13 eval set. |
| `VERSION` | — | Kit provenance and changelog. |

## Requirements by repo type

| Type | API layer | MCP | Agent docs | Metadata |
| --- | --- | --- | --- | --- |
| App or service | REST + committed OpenAPI 3.1 | own server (`mcp-service/`) | AGENTS.md + llms.txt | `ai-ready.yml`, `server.json`; Agent Card if it runs an agent |
| Content site | static JSON data API | own local stdio server (`mcp-site/`) | AGENTS.md + llms.txt | `ai-ready.yml`, `server.json`, JSON-LD |
| Tool or CLI | `--json` on every command | own server wrapping the CLI | AGENTS.md + llms.txt | `ai-ready.yml`, `server.json` |
| Library, theme or kit | — | — | AGENTS.md + llms.txt | `ai-ready.yml` |

## Content-site MCP hosting (resolved)

A static GitHub Pages site cannot host a live MCP server, so each content site ships a **local stdio MCP server** in its repo (`mcp/`), published as a package, which clients run locally against the site's public static data API. No hosted endpoint, $0. Its `server.json` declares `transport: stdio`.

## Validation

`tools/conformance.py` check `ai-ready` runs the structural checks offline and calls the in-hub AIEO (`tools/aieo/`) for the score. It is warn-only per repo until that repo's fan-out PR lands, then a hard failure. A score below `threshold.yml` fails only once AIEO passes its own eval set.

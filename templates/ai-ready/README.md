# templates/ai-ready — the AI-ready foundation kit

> The kit every repo starts from to meet constitution § 16: an API layer, an MCP server, agent docs and machine-readable metadata, sized to the repo type. Mostly spec still: the Files table marks each file `present` or `planned`, and every planned row links the issue that builds it.

## Files

| File | Seeded to | Status | Purpose |
| --- | --- | --- | --- |
| `ai-ready.template.yml` | `ai-ready.yml` | planned · spec [#494](https://github.com/bamr87/bamr87/pull/494); build issue not filed yet | The manifest: `type`, `api` (OpenAPI path, data API index or CLI JSON commands), `mcp` (server path, transport, `server.json`), `llms_txt`, `schema_md`, `agent_card`, and `not_applicable` entries, each with a reason. |
| `ai-ready.schema.json` | (hub only) | planned · [#495](https://github.com/bamr87/bamr87/issues/495) | JSON Schema 2020-12 for the manifest. |
| `llms-txt/` | build step | planned · spec [#494](https://github.com/bamr87/bamr87/pull/494); build issue not filed yet | Generator for `llms.txt` from the README, AGENTS.md, API docs and data API index (generalised from the hub's machine API, docs/MACHINE-API.md). |
| `data-api/` | build step | planned · spec [#494](https://github.com/bamr87/bamr87/pull/494); build issue not filed yet | Static JSON data API generator for content sites: `/api/v1/index.json` discovery, `schema_version`, `status: degraded` instead of build failure. |
| `mcp-service/` | `mcp/` | planned · spec [#494](https://github.com/bamr87/bamr87/pull/494); build issue not filed yet | MCP server skeleton for apps, services and tools, based on `tools/fleetcore/mcp_server.py`: read tools by default, writes behind confirmation. |
| `mcp-site/` | `mcp/` | planned · [#547](https://github.com/bamr87/bamr87/issues/547) | **Per-site content MCP server** for content sites, a **local stdio server** shipped in the repo that clients run: `search`, `read_page`, `list_collections`, `query_data_api`, reading the site's own static data API. Every content site runs its own; there is no shared fleet server. |
| `server.json.template` | `server.json` | planned · [#547](https://github.com/bamr87/bamr87/issues/547) (the hub console's own `server.json`: [#541](https://github.com/bamr87/bamr87/issues/541)) | MCP Registry manifest (schema 2025-12-11, name `io.github.<owner>/<repo>`). |
| `cli-json/` | (library) | planned · spec [#494](https://github.com/bamr87/bamr87/pull/494); build issue not filed yet | Helper that adds a `--json` mode to CLI commands. |
| `agent-card.template.json` | `/.well-known/agent-card.json` | present | A2A Agent Card, only for repos that run an agent (see [Agent Card template](#agent-card-template)). |
| `threshold.yml` | (hub only) | planned · [#495](https://github.com/bamr87/bamr87/issues/495) | The fleet-wide minimum AIEO score: `min_score: 80`. It fails builds only after AIEO passes its § 13 eval set. |
| `VERSION` | — | present | Kit provenance and changelog. |
| `test_ai_ready_kit.py` | (hub only) | present | Kit tests: this table against the tree, VERSION's `files:`, every JSON template parses, and the Agent Card's A2A v1.0 shape. |

## Agent Card template

`agent-card.template.json` is an A2A **v1.0** AgentCard, the current A2A release (v1.0.1; § 16.4 asks for v0.3 or later). Version 1.0 moved the endpoint into `supportedInterfaces[]` (`url`, `protocolBinding`, `protocolVersion`), so a v0.3-style card with a top-level `url` does not validate against v1.0. Seed it only into a repo that runs an agent, serve it at `/.well-known/agent-card.json`, and fill these tokens:

| Token | Fill with |
| --- | --- |
| `__PROJECT_NAME__` | The repo name: the card's `name`, its documentation URL and the skill's tag. |
| `__OWNER__` | The repo owner, for the provider and documentation URLs. |
| `__AGENT_DESCRIPTION__` | What the agent does, written for another agent deciding whether to call it. |
| `__AGENT_URL__` | The absolute HTTPS URL of the agent's A2A JSON-RPC endpoint. |
| `__AGENT_VERSION__` | The agent's own version, not the kit's. |
| `__SKILL_ID__`, `__SKILL_NAME__`, `__SKILL_DESCRIPTION__`, `__SKILL_EXAMPLE__` | One skill; copy the object for each further skill. |

The defaults are one JSON-RPC interface; streaming, push notifications and the extended card off; plain text and JSON in and out; and a `bearer` HTTP auth scheme required on every call. The scheme declares only the kind of credential: the token is issued by the agent's operator and never appears in the card or the repo (§ 16.9). Turn a capability on only when the agent supports it. No fan-out seeds this kit yet.

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

The kit's own tests, `python3 templates/ai-ready/test_ai_ready_kit.py` (run by CI's python-tests), fail when a `present` row's file is missing, a `planned` row has no issue link, a file in the kit has no row, VERSION's `files:` drifts, a JSON template does not parse, or the Agent Card leaves the A2A v1.0 AgentCard shape (the REQUIRED fields of `a2a.proto` and the field names its JSON Schema allows). They run on stdlib and PyYAML; the full JSON Schema validation against the published schema (`https://a2a-protocol.org/v1.0.1/spec/a2a.json`) is a one-off command recorded in the PR that added the card.

<!-- kit: governance v0.1.0 -->
# NEW — AI-ready foundation: every repo exposes an API layer, MCP, agent docs and machine-readable metadata, validated by AIEO

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution new § 16; `tools/aieo/` (new home of AIEO, migrated from `bamr87/zer0-CMS` `apps/aieo/`) (follows § 15 `major-change-evidence`, 0010; § 13 is 0011); specs UPS-AGENT, UPS-BE-12/31, UPS-DOC (by reference); `templates/` (new `templates/ai-ready/` kit); features `HUB-NEW:ai-ready-foundation`, `HUB-NEW:aieo-ai-readiness`; requirements `FR-NEW:ai-ready-foundation`, `FR-NEW:aieo-ai-readiness`
- **Supersedes:** none (extends § 7, § 14 and UPS-AGENT)
- **Related:** 0007 `public-docs-site` (warn-then-fail rollout), 0008 `harness-prior-art-research`, 0011 `eval-baseline-risk-tiers`, docs/MACHINE-API.md, docs/AI-INTEGRATION.md, specs/AGENT-CONTEXT.md, specs/BACKEND.md, `tools/fleetcore/mcp_server.py`, `bamr87/zer0-CMS` `apps/aieo/`

## Context

Amr's direction: "there also needs to be an amendment that all repos have common foundation models like an API layer, and MCP. essentially, every repo should be AI friendly and integrated. the AIEO engine should also be built to validate this."

Today AI-friendliness is uneven and unchecked. AGENTS.md is canonical under UPS-AGENT but present in only some repos. OpenAPI is a backend SHOULD/MUST (UPS-BE-12, UPS-BE-31) only for services. The hub alone publishes a machine API (`/api/v1/*.json`, `llms.txt`). MCP servers exist ad hoc: the harness console (`tools/fleetcore/mcp_server.py`), it-journey's quest server (`scripts/quest/mcp_server.py`) and AIEO's own tools. No rule says what every repo exposes to agents, and nothing scores it.

## Prior art

Per 0008, existing standards and fleet assets come first; the only new pieces are a definition, a kit and a conformance check.

**External standards**

- **Model Context Protocol (MCP)** and the **MCP Registry `server.json`** (schema `2025-12-11`, `io.github.<owner>/<name>` names): the standard way to expose tools and resources to agents, and to describe a server for discovery. Fit: the MCP layer and its manifest. Adopt.
- **OpenAPI 3.1:** already the fleet's API contract (UPS-BE-12, UPS-BE-31). Fit: the API layer for apps and services. Adopt as-is.
- **llms.txt** (llmstxt.org): a plain-markdown index for LLMs at the site root. The hub already derives one (docs/MACHINE-API.md). Fit: agent discovery for every public site. Adopt.
- **A2A Agent Card** (`/.well-known/agent-card.json`, A2A v0.3+): describes an *agent* service and its skills. Fit: only repos that run an agent (the harness, JEV, QA Lead). Adopt for those only; optional elsewhere.
- **schema.org JSON-LD:** structured metadata in pages. zer0-mistakes already ships it (docs/seo/aieo), and AIEO scores it. Fit: content-site metadata. Adopt.

**Fleet assets**

- **UPS-AGENT (specs/AGENT-CONTEXT.md) and the `agent-context` kit:** AGENTS.md canonical, CLAUDE.md a pointer. Fit: the agent-docs layer. Reuse; no new rule.
- **UPS-DOC and § 14:** every repo has a public site. Fit: the place llms.txt, the static data API and JSON-LD are served. Reuse.
- **Hub machine API (docs/MACHINE-API.md):** `/api/v1/index.json` discovery plus `llms.txt`, `schema_version`, `status: degraded` instead of build failures. Fit: the reference shape for a content site's static data API. Generalise into the kit.
- **Harness console MCP (`tools/fleetcore/mcp_server.py`, the user-harness-console server) and `.mcp.json`:** a working stdio MCP server and client config. Fit: reference implementation for a tool repo's MCP server. Reuse its pattern.
- **`verify/mcp.json` (gitorio, githubai, it-journey):** an MCP *client* config for the Playwright verifier, not a server. Fit: none for exposure; noted so it is not mistaken for compliance.
- **SCHEMA framework (`SCHEMA.md`, `bamr87/SCHEMA`, `tools/schema_lint.py`):** structural contracts per repo. Fit: machine-readable structure. Reuse; the AI-ready manifest points to it.
- **AIEO (`bamr87/zer0-CMS` `apps/aieo/`):** an existing AI Engine Optimization engine with a CLI, a FastAPI backend, prompt-driven pattern scoring and an MCP server (`aieo_score_content`, `aieo_list_patterns`, `aieo_landing_audit`, ...). The original `bamr87/aieo` was imported with full history by zer0-CMS#44 and then deleted (docs/CONSOLIDATION.md), which is why it 404s. Fit: the validator. Migrate it into the hub's `tools/aieo/` (Amr's decision) and extend it with a repo-readiness pattern pack; do not rebuild.
- **`tools/conformance.py`:** the fleet's existing gate. Fit: hosts the check id. Extend.
- **Build-vs-adopt:** adopt every standard above. Build only the `templates/ai-ready/` kit, a repo-readiness mode in AIEO (after migrating it into the hub's `tools/aieo/`) and one conformance check id. The AIEO build is tracked in the hub issue linked from this PR, starting with its own prior-art pass on external AI-readiness, llms.txt and MCP validators.

## Amendment

Add constitution § 16 "AI-ready foundation" with this text:

> 1. **Common foundation** — every active fleet repo is AI-ready: an agent can discover what it is, read its docs, query its data and call its capabilities without scraping. Every repo exposes four layers, sized to its type (item 2): an **API layer**, an **MCP layer**, **agent docs** and **machine-readable metadata**.
> 2. **By repo type** — the type comes from the repo's `_data/fleet.yml` entry.
>    - **Apps and services:** a documented REST API with a committed OpenAPI 3.1 document (UPS-BE-12, UPS-BE-31); an MCP server that wraps the main read operations (writes behind confirmation, as the harness console does).
>    - **Content sites:** a static JSON data API on the public site, shaped like the hub's (`/api/v1/index.json` discovery, `schema_version`, `status: degraded` instead of build failure); schema.org JSON-LD on pages. Each site runs its own real MCP server (search, read a page, list collections, query the data API) with a `server.json` manifest; a manifest alone does not satisfy the MCP layer. **Open gap, for Amr:** a static GitHub Pages site cannot host a live MCP server. Options, none chosen yet: (a) a separate serverless or edge deployment per site (for example a Cloudflare Worker, already used in the fleet) serving MCP over Streamable HTTP; (b) a local stdio server shipped in the repo (`mcp/`) and published as a package that clients run against the site's static data API; (c) both, with (b) as the baseline and (a) where a remote endpoint is wanted; (d) a self-hosted container on the forge host. Until Amr picks, the check accepts (a) or (b) and reports which.
>    - **Tools and CLIs:** a `--json` output mode on every user-facing command, documented in the README; an MCP server, or a `server.json` manifest for a server that wraps the CLI.
>    - **Libraries, themes and kits:** agent docs and metadata only; the API and MCP layers are not required.
> 3. **Agent docs everywhere** — `AGENTS.md` per UPS-AGENT, and `llms.txt` at the root of the public site (§ 14) linking the README, AGENTS.md, API docs and the data API index.
> 4. **Machine-readable metadata** — every repo has an `ai-ready.yml` manifest at its root naming its type, its API layer (OpenAPI path, data API index or CLI JSON commands), its MCP server or `server.json`, its `llms.txt` URL and its `SCHEMA.md`. MCP manifests follow the MCP Registry `server.json` schema. A repo that runs an agent also publishes an A2A Agent Card at `/.well-known/agent-card.json`.
> 5. **Shared kit, not from scratch** — the hub ships `templates/ai-ready/` (spec in its README: manifest, `llms.txt` generator, static data API generator, an MCP server skeleton for services and tools and a per-site content MCP server for content sites, both based on `tools/fleetcore/mcp_server.py`, `server.json` template, a CLI `--json` helper and the score threshold). It is fanned out like the other kits and stamped `<!-- kit: ai-ready vX.Y.Z -->`. A repo extends the kit rather than building its own.
> 6. **AIEO validates** — the AIEO engine, which lives in the hub's `tools/aieo/` (migrated from `bamr87/zer0-CMS` `apps/aieo/` by PR), scores AI-readiness per repo: the presence and validity of each layer (OpenAPI parses, `server.json` matches the registry schema, `llms.txt` resolves and links live pages, `--json` output parses, JSON-LD validates) and, via its content patterns, how usable the agent docs are. `tools/conformance.py` runs this as check `ai-ready`, calling the in-hub AIEO. The check is warn-only for each repo until that repo's fan-out PR lands, then a hard failure.
> 7. **AIEO is held to § 13** — AIEO's scoring is an agent decision, so it must meet the § 13 eval-set requirements before its score can fail a build. Until then, only the structural checks (presence and schema validity) can fail, and the score is advisory. Once AIEO passes its evals, a repo whose score is below the minimum also fails. The minimum is **60/100 (PLACEHOLDER; Amr sets the real value)** and lives in `templates/ai-ready/` as one fleet-wide number.
> 8. **Exemptions** — archived repos and repos marked `archived` or `retired` in `_data/fleet.yml` are exempt. A repo may claim a layer as not applicable only with a one-line reason in `ai-ready.yml`, which the completeness review (§ 15) accepts or rejects.
> 9. **Secrets and private repos** — no layer exposes secrets or private data. A private repo exposes its layers to the fleet only (no public `llms.txt` or data API), and its check runs with $0 Actions spend.

## Consequences

- Follow-up: build `templates/ai-ready/` and add the `ai-ready` check id to `tools/conformance.py` and `templates/conformance/conformance.yml` (feature `HUB-NEW:aieo-ai-readiness`).
- Follow-up: migrate AIEO from `bamr87/zer0-CMS` `apps/aieo/` into the hub's `tools/aieo/` by PR, then add its repo-readiness mode (`aieo repo <path> --json`, plus an MCP tool), tracked in the hub issue linked from this PR. AIEO's reusable content-scoring workflow ran on the deleted original repo and is re-homed in the hub.
- Follow-up: the zer0-CMS copy of `apps/aieo/` is **not** removed until Amr OKs it; removing it would be a separate zer0-CMS PR.
- Open: how content sites host their MCP server (item 2 gap), and the real minimum score (item 7 placeholder).
- Follow-up: add a `type:` field to `_data/fleet.yml` entries where it is missing (registry edit, no settings).
- Follow-up: drop the stale `aieo` row (`bamr87/aieo`, `projects/aieo`) from `_data/conformance.yml` by regenerating it.
- Fan-out: one PR per spoke repo after ratification adds the kit and turns that repo's check from warn to fail.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

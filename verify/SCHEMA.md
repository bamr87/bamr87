---
schema: "0.1"
coverage: listed
---

# SCHEMA — verify

> The hub's own agent-verification harness (kit: `templates/verify/`): how to run the dash like a user, the user scenarios both `runner.mjs` and a Claude Code pass execute, and the Playwright MCP config. Outputs go to `test/evidence/` (see root `SCHEMA.md`).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `verify.yml` | file | Run config (`verify/v1`): build + static serve of the Jekyll site with an empty baseurl, viewports, paths, agent guardrails | required |
| `runner.mjs` | file | Rendered copy of the kit's Playwright scenario runner (machine seed — refresh from `templates/verify/runner.mjs`, never hand-edit) | generated |
| `mcp.json` | file | Playwright MCP server definition the verification agent drives the site with | required |
| `scenarios/` | dir | One `scenario/v1` YAML per user path through a dash page (`id`, `feature: HUB-NNN`, steps) | terminal |
| `BRIEF.md` | file | Ephemeral brief written by fleet-verify.yml for the agent pass (gitignored) | generated |
| `AGENT-REPORT.md` | file | Ephemeral report the agent pass writes; the workflow posts it (gitignored) | generated |

## Placement

- New dash page → `scenarios/<slug>.yml` naming its `HUB-NNN` feature, then link it from `features/features.yml`.

## Forbidden

- No hand edits to `runner.mjs` — change `templates/verify/runner.mjs` (snapshot to `archive/` first) and re-render.

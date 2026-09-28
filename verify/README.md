# verify

The hub's own agent-verification harness (kit: `templates/verify/`, standard: [`docs/VERIFICATION.md`](../docs/VERIFICATION.md)) — how to run the dash like a user.

- `verify.yml` — run config (`verify/v1`): build + static serve of the Jekyll site, viewports, paths, agent guardrails.
- `scenarios/*.yml` — one `scenario/v1` user path per dash page, each naming its `HUB-NNN` feature.
- `runner.mjs` — rendered copy of the kit's Playwright runner (machine seed; change `templates/verify/runner.mjs` instead).
- `mcp.json` — the Playwright MCP server the verification agent drives the site with.

Outputs land in `test/evidence/`. Run it with `tools/dash verify`.

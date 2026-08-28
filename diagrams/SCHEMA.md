---
schema: "0.1"
coverage: listed
---

# SCHEMA — diagrams

> Illustrations of the harness and its loops: typed archify JSON IR beside the self-contained HTML it compiles to. Rendered by `tools/render-diagrams.sh`, served at `/diagrams/`, embedded on the dash's `/harness/` page.

## Conventions

- One diagram = one `<name>.<type>.json` source (`type` ∈ architecture | workflow | sequence | dataflow | lifecycle — the archify type router) and one delivered `<name>.<type>.html`.
- The HTML is **generated** by `node .claude/skills/archify/bin/archify.mjs deliver` at showcase quality; never hand-edit it — edit the JSON and re-run `tools/render-diagrams.sh`.
- Diagrams describe the control plane (docs/HARNESS.md), not project internals; a project's own architecture belongs in that project's repo.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `*.json` | pattern | archify JSON IR — the source of truth for each diagram | required |
| `*.html` | pattern | Delivered self-contained diagram (validated, deterministic) | generated |

## Placement

- New diagram → `<name>.<type>.json` here, then `tools/render-diagrams.sh`; link it from docs/HARNESS.md and `pages/_dash/harness.md` if it illustrates the harness.

## Forbidden

- No hand edits to `*.html`; no diagram of a submodule's internals here.

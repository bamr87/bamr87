---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console/design-system

> The Harness Console's design language as a React package (`@bamr87/harness-console-ui`), plus the Claude Design sync config that publishes it.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What the package is, how to build and sync it | required |
| `package.json` | file | Package manifest; always-latest dev dependencies, no lockfile | required |
| `tsconfig.json` | file | Declaration-only TypeScript config for `dist/*.d.ts` | required |
| `build.mjs` | file | One-shot build: esbuild ESM bundle, tsc declarations, stylesheet copy | required |
| `.gitignore` | file | Ignores build output and the staged design-sync scripts | required |
| `src/` | dir | One component per file, `index.ts` barrel, `styles.css` (tokens + `hc-*` classes) | terminal |
| `.design-sync/` | dir | Claude Design sync inputs: `config.json`, `conventions.md`, authored `previews/`, `NOTES.md` | terminal |
| `dist/` | generated | Build output (`index.js`, `.d.ts`, `styles.css`) | generated |
| `ds-bundle/` | generated | Converter output uploaded to Claude Design | generated |
| `.ds-sync/` | generated | Staged converter scripts and their `node_modules` | generated |
| `node_modules/` | generated | Installed dependencies | generated |

## Placement

- A new component → `src/<Name>.tsx` (JSDoc on the component, props interface exported), a line in `src/index.ts`, its styles in `src/styles.css` under an `hc-` prefix, and an authored `.design-sync/previews/<Name>.tsx`.
- A colour or spacing token → `src/styles.css` on `:root, .hc-root`, with its dark value in both dark blocks.

## Forbidden

- No lockfile and no pinned versions. No hard-coded hex in components; use the `var(--…)` tokens.

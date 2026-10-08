---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console/web

> The Harness Console's page: React + TypeScript on Mantine, built by Vite into `dist/` and served by `../app.py`.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What the page is, how to build and develop it, how the source is laid out | required |
| `SCHEMA.md` | file | This contract | required |
| `package.json` | file | Manifest; always-latest (`*`) dependencies, no lockfile | required |
| `.npmrc` | file | `package-lock=false` — npm never writes a lockfile here | required |
| `.gitignore` | file | Ignores `node_modules/`, `dist/` and `*.tsbuildinfo`; re-includes `public/`, which the root `.gitignore` ignores as Jekyll output | required |
| `tsconfig.json` | file | Strict TypeScript, type-check only (Vite bundles) | required |
| `vite.config.ts` | file | Build to `dist/`; the dev server's proxy to a running console (HTTP + the `/api/tui` WebSocket) | required |
| `index.html` | file | The entry document — links `/theme.css` (fleetcore's palette) and the bundle | required |
| `public/` | dir | Files copied verbatim into `dist/` (`favicon.svg`) | terminal |
| `src/` | dir | The app: `main.tsx`, `nav.ts`, `theme.ts`, `styles.css`, and `api/`, `lib/`, `components/`, `jobs/`, `github/`, `pages/` (see README) | terminal |
| `dist/` | generated | Vite's build output — what the console serves; gitignored, rebuilt by `../run.sh` | generated |
| `node_modules/` | generated | Installed dependencies | generated |
| `tsconfig.tsbuildinfo` | generated | TypeScript's incremental-build cache (`tsc -b`) | generated |

## Placement

- A new page → `src/pages/<Name>.tsx`, its route in `src/main.tsx`, its nav entry in `src/nav.ts`, and its URL builder in `src/lib/links.ts`.
- A new API document → its type in `src/api/types.ts` and a Query hook in `src/api/hooks.ts`.
- A list → `components/DataTable.tsx`, with `href` (or `onActivate`) so every row drills down, and `keys` so keys v1 navigates it.
- Something that runs an operation → `jobs/RunButton.tsx` or `useRunner().runOp()`; never `POST /api/jobs` directly, which would skip the confirm gate.

## Forbidden

- No lockfile, no pinned versions. No hex colour for a role fleetcore already defines; use the `var(--…)` roles from `/theme.css`. No inline `<script>` in `index.html` (the console's CSP is `script-src 'self'`). No credential value held in page state beyond the input that sends it.

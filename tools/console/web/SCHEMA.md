---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console/web

> The Harness Console's page: React + TypeScript on Mantine, built by Vite into `dist/` and served by `../app.py` — and, built a second way (`../build-pages.sh`: base `/bamr87/`, `VITE_STATIC=1`), the public site on GitHub Pages (docs/CONSOLE-PAGES.md).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What the page is, how to build, develop and test it, how the source is laid out | required |
| `SCHEMA.md` | file | This contract | required |
| `package.json` | file | Manifest; always-latest (`*`) dependencies, no lockfile; scripts `dev`, `build`, `typecheck` and `test` (Vitest, with jsdom for the one test that needs a DOM) | required |
| `.npmrc` | file | `package-lock=false` — npm never writes a lockfile here | required |
| `.gitignore` | file | Ignores `node_modules/`, the two build outputs (`dist/`, `dist-pages/`) and `*.tsbuildinfo` | required |
| `tsconfig.json` | file | Strict TypeScript over the app and its unit tests, type-check only (Vite bundles) | required |
| `vite.config.ts` | file | Build to `dist/` (or `CONSOLE_OUT`) under `CONSOLE_BASE`; the public build's CSP `<meta>`; a site build's front door, mark and frame origins (`VITE_FRONT_DOOR`, `VITE_SITE_MARK`, `CONSOLE_FRAME_SRC`, set by `../build-pages.sh`); the dev server's proxy to a running console (HTTP + the `/api/tui` WebSocket) | required |
| `vitest.config.ts` | file | Vitest's settings for the unit tests (`src/**/*.test.ts`, plain Node unless a file asks for jsdom); separate from `vite.config.ts` so a test run takes nothing from the page build's inputs and a build never loads Vitest (UPS-QA-12) | required |
| `index.html` | file | The entry document — links `/theme.css` (fleetcore's palette) and the bundle | required |
| `public/` | dir | Files copied verbatim into the build (`favicon.svg`; `headshot-448.jpg`, the avatar `_data/profile.yml` names, a 448 px copy of the full-size `headshot.jpg` kept beside it; `social-preview.png`, its 1280x640 `site.image` link card, also the repo's GitHub social preview; `readme-hero.jpg`, the profile README's hero screenshot; `bash-365-mark.svg`, the mark `_data/profile.yml` `sites.bash-365` names, an unchanged copy of bash-365.com's `assets/brand/favicon.svg`) | terminal |
| `src/` | dir | The app: `main.tsx`, `nav.ts`, `theme.ts`, `styles.css`, and `api/`, `lib/`, `components/`, `jobs/`, `github/`, `pages/`, `assist/` (see README); a module's unit tests sit beside it as `<module>.test.ts` | terminal |
| `dist/` | generated | Vite's build output — what the console serves; gitignored, rebuilt by `../run.sh` | generated |
| `dist-pages/` | generated | The public site built locally by `../build-pages.sh` (page + snapshot); gitignored — CI builds into `_site/` | generated |
| `node_modules/` | generated | Installed dependencies | generated |
| `tsconfig.tsbuildinfo` | generated | TypeScript's incremental-build cache (`tsc -b`) | generated |

## Placement

- A new page → `src/pages/<Name>.tsx`, its route in `src/main.tsx`, its nav entry in `src/nav.ts`, and its URL builder in `src/lib/links.ts`.
- A new API document → its type in `src/api/types.ts` and a Query hook in `src/api/hooks.ts`.
- A list → `components/DataTable.tsx`, with `href` (or `onActivate`) so every row drills down, and `keys` so keys v1 navigates it.
- Something that runs an operation → `jobs/RunButton.tsx` or `useRunner().runOp()`; never `POST /api/jobs` directly, which would skip the confirm gate. The docked assistant's messages go through `runOp` too.
- Something an assistant session may do to the page → an action in `src/assist/pageBridge.ts` and its twin in `../page_bridge.py` (the allowlist and the argument check), never a selector or a script from the session.
- A unit test → beside the module it tests, `src/<dir>/<module>.test.ts`; one that needs a DOM is `<module>.dom.test.ts` with `// @vitest-environment jsdom` on its first line. Vitest's settings stay in `vitest.config.ts` (UPS-QA-12), apart from the page build's `vite.config.ts`. A browser scenario is not a unit test: it goes under the hub's `verify/` (docs/VERIFICATION.md).

## Forbidden

- No confirming question outside a Mantine modal: the page bridge keeps every modal out of an assistant session's reach, and `../test_console.py` fails a file that sends `confirm: true` without one. No lockfile, no pinned versions. No hex colour for a role fleetcore already defines; use the `var(--…)` roles from `/theme.css`. No inline `<script>` in `index.html` (the console's CSP is `script-src 'self'`). No credential value held in page state beyond the input that sends it. No unit test that reaches the network or depends on the machine's locale, time zone, environment or real browser storage: it stubs `fetch`, the build's settings and the globals it needs.

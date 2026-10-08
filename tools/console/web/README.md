# Harness Console — the page

The browser front end of the [Harness Console](../README.md). It is a React + TypeScript app on [Mantine](https://mantine.dev) (app shell, Spotlight palette, modals, notifications), [TanStack Query](https://tanstack.com/query) and [React Router](https://reactrouter.com), with [xterm.js](https://xtermjs.org) for the Terminal page. Vite builds it into `dist/`, which `../app.py` serves at every non-API path.

```bash
npm install && npm run build   # dist/ — what the console serves (run.sh does this on start)
npm run dev                    # :5173 with hot reload, proxied to a console on :4001 (CONSOLE_URL to change)
npm run typecheck
```

Dependencies are always-latest (`*`), and `.npmrc` sets `package-lock=false`, so no lockfile is ever written (fleet policy, [docs/DEPENDENCIES.md](../../../docs/DEPENDENCIES.md)).

## How it is put together

| Path | Role |
| --- | --- |
| `src/main.tsx` | Providers and the route table |
| `src/nav.ts` | The information architecture: eight sections of pages. keys v1's `1`–`8` and `]` / `[` follow it |
| `src/theme.ts` | Points Mantine's CSS variables at the bashOS palette from `/theme.css` (`tools/fleetcore/theme.py`). No hex value lives here |
| `src/styles.css` | Console-only roles: validated chart series, meter tracks, log colours |
| `src/api/` | `client.ts` (fetch + the one-prompt console token), `types.ts` (API document shapes), `hooks.ts` (one Query hook per document) |
| `src/lib/` | `format.ts`, `ansi.ts` (SGR → HTML for job logs), `links.ts` (every internal route and GitHub link, in one place) |
| `src/components/` | the shell, `DataTable` (sortable, linkable rows with keys v1 navigation), the palette, the global keymap, charts, small UI pieces |
| `src/jobs/` | `JobRunner` (the confirm gate, submit, the live-log drawer), `OpForm`, `RunButton`, `JobLog` |
| `src/github/` | the GitHub surface: `ConnectPanel` (OAuth App setup, device / browser flows), `RepoManager` (issues, PRs, runs, workflows), `useGhAction` (every write: say, ask, POST with confirm, log) |
| `src/pages/` | one file per page, plus the drill-downs (`ProjectPage`, `ContentSite`, loop, job and operation pages) |

Rules the code keeps:

- Every entity links to its page through `lib/links.ts`, so a repo name or operation opens the same drill-down everywhere.
- Status is always an icon plus a label (`Status`), never colour alone. Chart series colours were validated for colour-vision deficiency in both themes, and every chart has a table view.
- A view, key or colour the terminal dash shows too comes from `tools/fleetcore` through the API (`/api/fleet`, `/api/keys`, `/theme.css`, `/api/theme`) and is never copied here.
- The bundle carries no inline script, so the console's `script-src 'self'` policy holds.

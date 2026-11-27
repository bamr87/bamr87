# Harness Console — the page

The browser front end of the [Harness Console](../README.md). It is a React + TypeScript app on [Mantine](https://mantine.dev) (app shell, Spotlight palette, modals, notifications), [TanStack Query](https://tanstack.com/query) and [React Router](https://reactrouter.com), with [xterm.js](https://xtermjs.org) for the Terminal page. Vite builds it into `dist/`, which `../app.py` serves at every non-API path.

```bash
npm install && npm run build   # dist/ — what the console serves (run.sh does this on start)
../build-pages.sh              # dist-pages/ — the public site: base /bamr87/, VITE_STATIC=1, plus the snapshot
CONSOLE_SITE=bash-365 ../build-pages.sh   # another site of the same console: its title, mark and front door from _data/profile.yml `sites:`
npm run dev                    # :5173 with hot reload, proxied to a console on :4001 (CONSOLE_URL to change)
npm run typecheck              # tsc over the app and its tests
npm test                       # the unit tests (Vitest), offline — see Tests below
```

Dependencies are always-latest (`*`), and `.npmrc` sets `package-lock=false`, so no lockfile is ever written (fleet policy, [docs/DEPENDENCIES.md](../../../docs/DEPENDENCIES.md)).

## How it is put together

| Path | Role |
| --- | --- |
| `src/main.tsx` | Providers and the route table |
| `src/nav.ts` | The information architecture: nine sections of pages, the profile first and then the console. keys v1's `1`–`9` and `]` / `[` follow it |
| `src/theme.ts` | The one theme object: `createTheme` tokens + `components:` defaults, and the CSS-variables resolver that points Mantine at the bashOS palette from `/theme.css` (`tools/fleetcore/theme.py`) and declares the console's own roles per colour scheme |
| `src/styles.css` | Base rules only (body background, link colour); everything else is a CSS module |
| `src/styles/` | `Table.module.css` (every table, via the theme) and `utils.module.css` (one-line layout roles) |
| `postcss.config.cjs` | Mantine's standard PostCSS setup: `postcss-preset-mantine` + breakpoint variables |
| `src/api/` | `client.ts` (the one `api()` every page calls, + the one-prompt console token), `backend.ts` (which backend answers: the console, the published snapshot, or a remote console; the browser-held GitHub token), `static.ts` (an `/api` path → the snapshot file `../snapshot.py` wrote), `ghdirect.ts` (the console's GitHub routes and workflow dispatch, answered from the browser against api.github.com), `types.ts`, `hooks.ts` (one Query hook per document) |
| `src/lib/` | `format.ts`, `ansi.ts` (SGR → HTML for job logs), `links.ts` (every internal route and GitHub link, in one place), `prefs.ts` (what this browser remembers: open sidebar sections, recent pages) |
| `src/components/` | the shell (`Shell`, `ShellNav`: the folding sidebar and its live counts; `pageTitle`: a page names itself once; `ErrorBoundary`: a page that throws costs that page), `DataTable` (sortable, linkable rows with keys v1 navigation), the palette, the global keymap, `Charts` (Mantine Progress meters + the lazily loaded `Columns` bar chart on `@mantine/charts`), `Viz` (the Overview's story pieces in the console's roles: segmented bar, bullet, inline-SVG sparkline, delta, weekday × hour heat strip, freshness timeline — identity never colour alone, a tooltip on every mark), small UI pieces (`ui.tsx`: Badge pills, ColorSwatch dots, Progress meters, tiles) |
| `src/jobs/` | `JobRunner` (the confirm gate, submit, the live-log drawer), `OpForm`, `RunButton`, `JobLog` |
| `src/github/` | the GitHub surface: `ConnectPanel` (OAuth App setup, device / browser flows), `RepoManager` (issues, PRs, runs, workflows), `useGhAction` (every write: say, ask, POST with confirm, log) |
| `src/assist/` | the docked assistant ([ADR 0013](../../../docs/adr/0013-console-page-assistant.md)): `AssistDock` (the panel in the shell's aside: the mode control, the thread of messages with each session's steps, the Allow/Deny prompt, the composer, pairing), `session` (the dock's state outside React: this tab's page-bridge session and its long poll, the mode, the prompts, the conversation) and `pageBridge` (the page's half of `../page_bridge.py`: the snapshot, the eight actions, and the rules no session can lift — refs only, never inside a modal dialog, never a secret field) |
| `src/pages/` | one file per page, plus the drill-downs (`ProjectPage`, `ContentSite`, loop, job and operation pages); the profile (`Home`, `Profile` — pages and posts, `Portfolio`), the registries (`Registries`: roadmap, features, engagements, toolbox), the bashOS desktop (`Desktop`: the OS shell drawn from the vendored reducer in `src/vendor/bashos/`, each window hosting `Apps`' `AppPane`), the app portal (`Apps`: the launcher grid and the framed workspace, styled by `Apps.module.css`), the generated repo app (`RepoApp`: what a repo with no frontend in the shell opens as, on the Apps page and in a Desktop window), the Work board (`Work`, with `WorkBoard` — lanes, cards and drag and drop, `WorkItem` — the drawer, `WorkFlow` — throughput, `workPlan` — the staged plan), the harness refinement (`Refine`: surface, plans, review queue, evidence, library), the assistant (`Assist`, with `jobs/AssistAnswer` — a job's question and answer), GitHub Projects (`GhProjects`: owners, a project picker, items as a table or a board by Status; console-only, read-only), the voice model editor (`Voices`: defaults, site profiles, personas and assignment rules as forms, preview, dry run, draft PR), the loop switches (`Switches`: every loop's kill switch against its live variable, one table per repo, a flip previewed with a reason in a dialog and applied behind the confirm; console-only; `switchPlan` — the rules the page applies) and `Connect` |
| `src/**/*.test.ts` | the unit tests, each beside the module it tests ([Tests](#tests)) |

Rules the code keeps:

- **Theme and layout come from Mantine, not from hand-written CSS.** `src/theme.ts` is the one theme object: `createTheme` (tokens, breakpoints, `other` for the layout constants) plus `components:` defaults through the Styles API (every `Table` is dense through `theme.components.Table.classNames`; `Badge`, `Progress`, `Kbd`, `NavLink`, `AppShell` carry their defaults there). The palette is still fleetcore's: the CSS-variables resolver points Mantine's variables at `/theme.css` and declares the console's own roles (chart series, meter tracks, ANSI log colours) per colour scheme. No stylesheet carries a palette.
- **Styling is CSS modules + style props.** Component styles live in a `*.module.css` beside the component (`DataTable.module.css`, `Charts.module.css`, `JobLog.module.css`, `pages/TerminalPage.module.css`, …), processed by Mantine's standard PostCSS setup (`postcss.config.cjs`: `postcss-preset-mantine` for `rem()`, `light-dark()` and `@mixin hover`; `postcss-simple-vars` for breakpoint variables in media queries). One-line layout roles are `src/styles/utils.module.css` (`nowrap`, `preWrap`, `flexFill`, `tileLink`, `embed`, …). `src/styles.css` is base rules only. **No inline `style={{…}}` objects**: the only `style` props left set a CSS custom property whose value is data (`--tick`, `--term-bg`), which is Mantine's own pattern for dynamic values. State on a row is a `data-*` attribute the module styles, never a class string the page assembles.
- **Widgets are Mantine components.** Status pills are `Badge`, meters are `Progress`, health dots are `ColorSwatch` + `VisuallyHidden`, key caps are `Kbd`, and charts are `@mantine/charts` (`BarChart` on Recharts) with the console's series roles as `var(--series-*)` colours. Status is always an icon plus a label (`Status`), never colour alone, and every chart keeps a table view.
- **A page names itself in its `PageHeader`**, which is its one `h1`; `Section` is an `h2`. The shell turns that name into the tab title, the route announcement and the palette's recent list, so no page sets `document.title`.
- **Everything the mouse does has a keyboard path.** A list goes through `DataTable`, whose headers are buttons reporting `aria-sort` and whose rows carry a link or take focus. Enter belongs to the focused control; `GlobalKeys` opens the selected row only when nothing is focused. An open menu or list keeps its own arrows and Escape.
- **A failure stays the size of what failed.** `Load` keeps a query's last answer on screen when a refresh fails and offers Try again when there is nothing to show; a 4xx is not retried; `ErrorBoundary` holds a page that throws. A new page gets all of this by using `Load`.
- Every entity links to its page through `lib/links.ts`, so a repo name or operation opens the same drill-down everywhere.
- The public build lives under `/bamr87/`: navigate through React Router (it carries the `basename`), point at files with `asset()` from `api/backend.ts`, and never write a bare `/path` into an `href` or `src`.
- A page never asks which backend it is on to fetch data — only to decide what to offer (`hasConsole()`): a lever that needs a console says so (`LocalOnly`, `runnableHere`) instead of failing.
- A view, key or colour the terminal dash shows too comes from `tools/fleetcore` through the API (`/api/fleet`, `/api/keys`, `/theme.css`, `/api/theme`) and is never copied here.
- **A site's identity is a setting.** What `/` is (`FRONT_DOOR`) and the mark (`MARK`) come from the build (`api/backend.ts`, set by `../build-pages.sh` from `_data/profile.yml` `sites:`); the title, who the site is by and what the desktop shows come from the site document. `to.home()` and `to.desktop()` (`lib/links.ts`) say where each is in this build, so no page writes `/` or `/desktop` for either, and no site's name is written in `src/` (`../test_pages.py` holds that; [docs/CONSOLE-PAGES.md](../../../docs/CONSOLE-PAGES.md#site-builds-the-same-console-at-another-address)).
- The bundle carries no inline script, so the console's `script-src 'self'` policy holds.

## Tests

```bash
npm test                                  # every unit test, once (what CI and tools/run-all-tests.sh run)
npx vitest                                # watch mode: reruns the tests of what you save
npx vitest run src/api/static.test.ts     # one file; a folder (src/lib) works too
npx vitest run -t 'asset'                 # the tests whose name matches
```

The unit tests are [Vitest](https://vitest.dev), configured in [`vitest.config.ts`](vitest.config.ts), the file the fleet standard names (UPS-QA-12) and the fleet's other apps use; it takes nothing from the page build's settings. They hold the logic that needs no browser: number, age and cron formatting (`lib/format`), every link builder (`lib/links`), the ANSI decoder (`lib/ansi`), what a browser remembers (`lib/prefs`), the retired-URL table (`lib/legacy`), the navigation map (`nav`), the Work board's staged plan (`pages/workPlan`), the Switches page's levers (`pages/switchPlan`: what a toggle asks for, when Apply is offered), the three backends behind `api()` (`api/backend`: the base path, `asset()` and which backend answers; `api/static`: the snapshot router; `api/client`: the console token and the one prompt; `api/ghdirect`: GitHub from the browser, with its gates), and the page bridge's rules (`assist/pageBridge`). What a person sees is still proved in a real browser by the scenarios under `verify/` ([docs/VERIFICATION.md](../../../docs/VERIFICATION.md)); these tests are the fast half, and `console-web.yml` runs them on every pull request that touches the page.

Rules the tests keep:

- **A test sits beside its module**, as `<module>.test.ts`, and opens with a comment saying what it holds. The build type-checks it with the rest of `src/` (`tsc -b`); nothing imports a test file, so none reaches the bundle.
- **A test states intended behaviour.** It asserts what the module's comments and the docs say should happen, on inputs whose answer is known beforehand; it is never a record of what the code returned. A case that exposes a bug is fixed in the module or reported, not written down as the expected value.
- **Plain Node unless a DOM is the subject.** A file that needs one asks in its first line (`// @vitest-environment jsdom`, the DOM the fleet's other apps test on) and is named `<module>.dom.test.ts`; `assist/pageBridge.dom.test.ts` is the only one. jsdom has no layout engine, so that file gives every element a size, supplies the two browser functions jsdom leaves out (`scrollIntoView`, `matchMedia`) and hands the bridge jsdom's own `window`, which its pointer events need as their `view`.
- **The build's settings and the browser's state are the test's to name.** `BASE_URL`, `VITE_STATIC`, `VITE_FRONT_DOOR` and `VITE_SITE_MARK` are read when a module loads, so a test sets them with `vi.stubEnv`, calls `vi.resetModules()` and imports the module afresh (each file's `load()`). `window`, `localStorage`, `sessionStorage` and `fetch` are `vi.stubGlobal` fakes. Each is put back after every test (`unstubEnvs`, `unstubGlobals`, `restoreMocks`), and no test depends on the machine's locale, time zone or environment.
- **Both addresses.** Anything that builds a URL is tried at `/` (a console) and at `/bamr87/` (GitHub Pages).
- **No network.** `fetch` is always a stub that records what was asked, so a test can also assert that nothing was asked (a refused write, a local-only route).
- **A test file is source under `src/`, so the hub's source checks read it too.** `../test_console.py` requires any file that spells the confirm a page sends (`confirm: true`) to gather it in a confirm modal, so a test passes it through a named constant; `../test_pages.py` allows no site's name, address or mark from `_data/profile.yml` `sites:` anywhere in `src/`.

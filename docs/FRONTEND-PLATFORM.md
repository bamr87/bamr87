# Fleet frontend platform — layers, tiers and fan-out

> How the fleet's frontends share one platform without sharing one framework: six standard layers (tokens, Web Components, one app shell with micro-frontends, one OIDC identity, contracts, a registry with conformance), four tiers, the surfaces, bashOS as the OS shell that hosts them, the frontend component every repo gets, the app portal that opens every frontend inside the Harness Console, the public and private modes, who owns what, and the fan-out plan. Rule: constitution § 18 ([amendment 0016](amendments/0016-fleet-design-consistency.md)); composition and surfaces: [ADR 0005](adr/0005-console-as-fleet-portal.md) (proposed); phases: [DESIGN-HARMONIZATION.md](DESIGN-HARMONIZATION.md); shell item: roadmap FF-0032.

## Principle

Standardize the layers *between* frameworks, not the framework. A Jekyll site, a Next.js app, a Godot game and a Kotlin Multiplatform app stay what they are; they agree on tokens, components, identity, contracts and a registry. A repo adopts only the layers its tier asks for.

## The six layers

| # | Layer | Standard | Hub artifact | Consumed by |
| --- | --- | --- | --- | --- |
| 1 | Design tokens | One [W3C Design Tokens](https://www.designtokens.org/) JSON source built with Style Dictionary into CSS custom properties (`--fleet-*`, web), Swift and Kotlin constants (mobile), and desktop/terminal themes | `@bamr87/fleet-tokens` (versioned releases, `fleet-tokens vX.Y.Z` stamp) | every `shell` and `tokens` tier repo; zer0-mistakes through a pinned release |
| 2 | Components | Framework-neutral Web Components (Lit) for the shared set (UPS-FE-10..29: app shell regions, skip link, theme toggle, feedback, toast, search, 404); native mirrors (Compose, SwiftUI) read the same tokens | `@bamr87/fleet-components` | React/Next/Vue apps wrap them; Jekyll includes render them; native apps mirror them |
| 3 | App shell + micro-frontends | One shell owns nav, auth, layout, command palette (⌘K) and the launcher. A frontend mounts on the ladder of [ADR 0005](adr/0005-console-as-fleet-portal.md): link, frame (the default, any framework), bridged frame (`fleet-bridge`), federated React module (Module Federation 2.0, first-party plugins with a `fleet-mfe.json`). Desktop and mobile: the shell as a PWA first, then Tauri, Capacitor or the native shell in fleet-mobile | `@bamr87/fleet-shell` (successor to `@bamr87/harness-console-ui`, FF-0032) | `shell` tier apps and consoles |
| 4 | Identity | One OIDC provider for every app; the shell does the login and passes tokens to micro-frontends | zer0-id (Go OIDC/OAuth2/WebAuthn, experiment) as the candidate provider | `shell` tier apps; sites and games stay anonymous |
| 5 | Integration via contracts | API gateway with OpenAPI (REST) or SDL (GraphQL) contracts checked in each repo; one event bus with schema'd events; deep-link URLs (`fleet://<slug>/<path>` and the https twin) as universal navigation; agents through MCP and A2A | contract files beside each API (UPS-BE), the event catalog, the deep-link map | apps, consoles, agents |
| 6 | Registry + conformance | The `frontend:` block on each `_data/projects.yml` entry (type, tier, framework, surfaces, token_version, entry_url, shell, enforce); the shell launcher is generated from it and from `_data/ports.yml` (`tools/fleetcore/apps.py`: `tools/dash apps`, `tools/frontend_registry.py launcher`, the console's `/api/apps`); UPS-FE-70..73 report drift | registry block, `tools/frontend_registry.py` (drift check (o)), `tools/conformance.py` | everyone |

## Tiers

| Tier | Who | Layers required | Checks |
| --- | --- | --- | --- |
| `shell` | apps and consoles (`type: app` or `console`) | 1–6 | UPS-FE-70, 71, 72, 73 |
| `tokens` (site) | Jekyll and static sites (`type: site`); zer0-mistakes sites get tokens through the theme | 1, 6 (2 optional) | UPS-FE-70, 71, 73 |
| `tokens` (game) | games (`type: game`): Bashcrawl, rewind-arcade, Godot titles — exempt from the shell, so the game keeps its own full-screen layout | 1, 6 | UPS-FE-70, 71, 73 |
| `tokens` (extension) | VS Code extensions (`type: ext`): webviews map `--vscode-*` through the token file | 1, 6 | UPS-FE-70, 71, 73 |
| `none` | no frontend (CLIs, libraries, infra, kernels, firmware, external upstreams) | — | every row N/A (pass) |

Rollout is **warn-then-fail per repo**: every UPS-FE-70..73 result is a warning until the registry sets `frontend.enforce: true` for that repo (after its adoption PR merges), then a failure. The checks are static greps inside the existing conformance run: no new workflow, no extra Actions minutes on private repos.

A **fork** is a tracked copy of a token or shell build (`fleet-tokens.*`, `fleet-shell.*`) that does not carry the stamp of a published release equal to the registry `token_version`. Extending (overriding a token, adding a component, registering a micro-frontend) is allowed; forking is not (UPS-FE-73).

## Surfaces

| Surface | Shell runtime | Tokens as |
| --- | --- | --- |
| Browser | the Harness Console is the shell (`@bamr87/fleet-shell` once extracted, FF-0032); frontends are framed, bridged or federated per ADR 0005 | CSS custom properties |
| Desktop OS | the web shell installed as a PWA; Tauri where a native API is needed (Electron only with a documented reason); Godot reads an exported theme | CSS, Godot theme resource |
| Mobile | the web shell as a PWA first; fleet-mobile (Compose Multiplatform) as the native shell, or Capacitor wrapping the web shell, reading the same launcher | Kotlin and Swift constants |
| VS Code | planned: an extension in the hub hosting the web shell in a webview, with the launcher as a tree; extension webviews map `--vscode-*` | CSS |
| Terminal | `tools/dash apps` (list, address, open, check) and the terminal dash; terminal themes (bashOS) | ANSI theme |

## The OS shell: bashOS

The console's **Desktop** page (`/desktop`) is the bashOS desktop in the browser ([ADR 0005](adr/0005-console-as-fleet-portal.md) decision 9, proposed): an icon for every fleet app, each opened in a window. Three layers, each owned once:

| Layer | What it is | Owner |
| --- | --- | --- |
| **OS shell** | the desktop, the dock of icons, floating windows, the taskbar, the shareable layout | bashOS: its layout reducer, vendored byte-identical in `tools/console/web/src/vendor/bashos/`, and its paper palette (`--os-*` in `/theme.css`) |
| **App Shell** | what every window shares: where the app runs, a device size, a path, reload, open outside | the hub (`AppPane`, the app portal below) |
| **App** | a fleet frontend at its live or local address, the generated repo app, or one of the console's own pages | each repo; the hub |

| You want to | Do this |
| --- | --- |
| Open an app in a window | click its icon; shift-click for a second window (Live beside Local) |
| Fill half the desktop, or all of it | drag the window to the left or right edge, or to the top; double-click the title bar |
| Get a window back | its button on the taskbar; `⌘\` cycles |
| Open a page of the console in a window | the **bashOS** button on the taskbar lists every page; the **Console** icon opens Overview; the palette (`⌘K`) opens what you pick |
| Arrange everything | the tile and cascade buttons on the taskbar |
| Send someone this desktop | the link button: a `?windows=` address of ids and geometry, never of URLs |
| See every repo, with or without a frontend | the **Fleet** icon; a repo without one opens as the generated repo app |

A console page in a window is the same page without its header and sidebar: the window is its frame, links inside it stay inside it, and the window's title and the shared layout follow where it goes. On a phone the desktop is a home screen: the icons, then one app at a time; there the **Console** icon leaves for the classic console, which has its own way around.

## A frontend component for every repo

Every repo gets one, so every repo is an app on the desktop ([ADR 0005](adr/0005-console-as-fleet-portal.md) decision 10, proposed). The kind follows from the registry: **own** (it has a web frontend), **preview** (an editor extension, a mobile or desktop app: a web preview of it), **terminal** (its terminal UI in a shell window), **generated** (no UI: the repo app the shell builds from the repo's README, feature index, docs and commands). Regenerate this table with `tools/dash apps plan`; the phases (F1 to F4) are in the ADR.

Until a repo's own component is in the shell it opens as the **generated repo app** (`tools/console/web/src/pages/RepoApp.tsx`), so all 39 repos are apps today: an overview from the registry and the hub's signals (health, CI, open work, the standards audit, automation, how to get it), the repo's README, its open work and its automation. A console reads the README from the repo's checkout on the operator's machine; the public site carries none.

| repo | frontend component | state | next step |
| --- | --- | --- | --- |
| README | own (mkdocs) | in the shell | the bridge and the public and private modes (P3, P4) |
| scripts | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| skills | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| it-journey | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| zer0-mistakes | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| gitorio | own (react-vite-tailwind) | in the shell | the bridge and the public and private modes (P3, P4) |
| law-ai | own (nextjs-tailwind) | in the shell | the bridge and the public and private modes (P3, P4) |
| githubai | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| fredgar-ai | own (react-vite+django) | in the shell | the bridge and the public and private modes (P3, P4) |
| vs-sonic-pi | preview | generated app for now | a web preview published beside the repo (F3) |
| zpl-viewer | preview | generated app for now | a web preview published beside the repo (F3) |
| bashcrawl | own (react-vite-tailwind) | in the shell | the bridge and the public and private modes (P3, P4) |
| bamr87.github.io | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| lifehacker.dev | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| djangoerp | own (django-templates) | in the shell, local only | a public build with an address (F2) |
| zer0-CMS | own (react-mantine+vscode+django) | in the shell, local only | a public build with an address (F2) |
| bashos | terminal | generated app for now | its terminal UI in a shell window and a demo for the public page (F3) |
| ocrmd | own (static-html) | generated app for now | an address: a public build or a dev-stack port (F2) |
| rewind-arcade | own (react-vite-tailwind-canvas) | in the shell | the bridge and the public and private modes (P3, P4) |
| outbox | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| cv-pro | own (react-vite-tailwind) | generated app for now | an address: a public build or a dev-stack port (F2) |
| godotgo | own (godot) | generated app for now | an address: a public build or a dev-stack port (F2) |
| bash-365-apex | own (static-html) | in the shell | the bridge and the public and private modes (P3, P4) |
| year-of-ai.github.io | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| ai-world-view.github.io | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| bash-365.com | own (jekyll-zer0) | in the shell | the bridge and the public and private modes (P3, P4) |
| fleet-infra | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| kvlite | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| netprobe | terminal | generated app for now | its terminal UI in a shell window and a demo for the public page (F3) |
| fleet-observe | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| zer0-id | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| sec-lab | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| edgar-pipeline | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| recon-engine | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| zer0-kernel | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| sensor-mesh | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| fleet-mobile | preview | generated app for now | a web preview published beside the repo (F3) |
| schema-lang | generated | generated app for now | a component of its own in place of the generated repo app (F4) |
| ragio-ai | own (static-html+fastapi) | generated app for now | an address: a public build or a dev-stack port (F2) |

## The app portal

The console's **Apps** page (`/apps`) is the launcher rendered: every frontend in the table below, opened inside the shell at `/apps/<id>`. It is the first level of composition that needs nothing from a repo ([ADR 0005](adr/0005-console-as-fleet-portal.md), level L1), so it works for every framework in the fleet today.

| You want to | Do this |
| --- | --- |
| See every frontend and where it runs | **Fleet → Apps** in the console, or `tools/dash apps` (`json` for the `fleet-launcher/v1` document) |
| Open one inside the console | click it, or `tools/dash apps open <app> [--target local]` |
| Switch between the deployed site and your machine | the **Live / Local** switch; a stopped stack shows `tools/dash dev up <project>` |
| See it at a phone or tablet size | the device presets, which are `verify/verify.yml` `viewports:` |
| Move inside the app | the path box (a path, never another address) |
| Check that each address answers and can be framed | `tools/dash apps check [app …] [--target live|local|all] [--strict]` |
| Open a repo that has no frontend | it is in the same list (filter **No interface**) and opens at `/apps/<id>` as the generated repo app |

**Targets.** `live` is `frontend.entry_url` (else `live_url`): give the address the site is served from, not one that forwards to it, because the shell frames only origins the registry declares. `local` is each browser-facing service of a compose-hosted stack at its `_data/ports.yml` port, the `frontend` band before `jekyll`, `docs` and `api`. A devenv-hosted project has no local target yet: its port is picked at launch.

**What a frontend owes the portal.** Nothing to be listed. To be framed it must not refuse the shell: no `X-Frame-Options`, and a `frame-ancestors` policy only if it names the shell's origins (`https://bamr87.github.io`, `http://127.0.0.1:4001`). To work on the public page when it shares the page's origin it must tolerate a frame without storage access, so guard `localStorage` and `sessionStorage` reads.

**Where it stops.** The portal frames; it does not start a stack, run a repo's verify scenarios or read a framed app's route. Those are the next phases of ADR 0005.

## Modes: public and private

Every frontend has two modes ([ADR 0005](adr/0005-console-as-fleet-portal.md) decision 6, [ADR 0006](adr/0006-django-management-backend.md); both proposed).

| Mode | What a person gets | Depends on |
| --- | --- | --- |
| **Public** | everything that needs no account: the static build or the anonymous view | its own origin only — no backend, no sign-in |
| **Private** | the same frontend, signed in | a Django backend the registry declares for it: `local` (Docker on this machine) or `cloud` (an https host) |

The Harness Console already works this way and is the reference: the page on GitHub Pages is the public mode, and the same page served by or connected to a console is the private one. Planned, not built: `modes` and `backends` on each registry `frontend:` block, the launcher carrying them, a mode switch in the portal, and one sign-in client shared by every frontend (authorization code with PKCE, bearer tokens, a backend chosen by its declared name).

## Token source

Proposed: the hub token source is **seeded from zer0-mistakes' existing tokens** (`_design-system/tokens/*.css`: colors, spacing, typography, radius, shadows, motion, layers, breakpoints, skins), converted once to W3C JSON in the hub. The bashOS palette (`tools/fleetcore`) becomes a **theme variant** of that source (like the zer0 skins), not the base. zer0-mistakes then consumes the published package at a pinned version instead of owning a parallel copy. This is an open question for Amr (below).

## Ownership

- **Hub (Platform):** the token source and its builds, the component library, the shell, the registry `frontend:` schema, the contracts (gateway, event catalog, deep-link map), UPS-FE-70..73 and the fan-out.
- **Sites:** the zer0 theme family (zer0-mistakes) and the content sites; zer0 consumes the tokens through a pinned release.
- **Bashcrawl & Games:** bashcrawl, rewind-arcade, godotgo (tokens tier, game type).
- **Law AI Lead:** law-ai (and lawmode); law-ai conforms through its own `docs/constitution.md` amendment citing § 18.
- **Tools:** gitorio, githubai, zer0-CMS, the VS Code extensions.
- **Each owning bot:** its repos' adoption PRs and § 15 evidence. Repos with their own governance (law-ai's constitution, year-of-ai's genome) conform through their own amendment or genome entry that cites § 18; a fan-out never overwrites them.

## Registry

Every submodule carries a `frontend:` block; `TBD` marks what inspection could not decide. Regenerate this table with `python3 tools/frontend_registry.py table`.

| repo | type | tier | framework | surfaces | shell |
| --- | --- | --- | --- | --- | --- |
| README | site | tokens | mkdocs | browser | none |
| scripts | none | none | none | — | none |
| skills | none | none | none | — | none |
| it-journey | site | tokens | jekyll-zer0 | browser | zer0 |
| zer0-mistakes | site | tokens | jekyll-zer0 | browser | zer0 |
| gitorio | app | shell | react-vite-tailwind | browser | own |
| law-ai | app | shell | nextjs-tailwind | browser | own |
| githubai | none | none | none | — | none |
| fredgar-ai | app | shell | react-vite+django | browser | own |
| vs-sonic-pi | ext | tokens | vscode-webview | vscode | none |
| zpl-viewer | ext | tokens | vscode-webview | vscode | none |
| bashcrawl | game | tokens | react-vite-tailwind | browser | none |
| bamr87.github.io | site | tokens | jekyll-zer0 | browser | zer0 |
| lifehacker.dev | site | tokens | jekyll-zer0 | browser | zer0 |
| djangoerp | app | shell | django-templates | browser | own |
| zer0-CMS | app | shell | react-mantine+vscode+django | browser, vscode | own |
| bashos | none | none | python-tui | terminal | none |
| ocrmd | app | shell | static-html | browser | own |
| rewind-arcade | game | tokens | react-vite-tailwind-canvas | browser | none |
| outbox | none | none | none | — | none |
| cv-pro | app | shell | react-vite-tailwind | browser | own |
| godotgo | game | tokens | godot | desktop, browser | none |
| bash-365-apex | site | tokens | static-html | browser | none |
| year-of-ai.github.io | site | tokens | jekyll-zer0 | browser | zer0 |
| ai-world-view.github.io | site | tokens | jekyll-zer0 | browser | zer0 |
| bash-365.com | site | tokens | jekyll-zer0 | browser | zer0 |
| fleet-infra | none | none | none | — | none |
| kvlite | none | none | none | — | none |
| netprobe | none | none | go-tui | terminal | none |
| fleet-observe | none | none | none | — | none |
| zer0-id | none | none | TBD | — | none |
| sec-lab | none | none | none | — | none |
| edgar-pipeline | none | none | none | — | none |
| recon-engine | none | none | none | — | none |
| zer0-kernel | none | none | none | — | none |
| sensor-mesh | none | none | none | — | none |
| fleet-mobile | app | shell | compose-multiplatform | mobile | TBD |
| schema-lang | none | none | none | — | none |
| ragio-ai | app | shell | static-html+fastapi | browser | own |

## Fan-out plan

1. **Ratify** § 18 (#554) with the wording changes proposed alongside this doc; until then nothing below changes a submodule.
2. **Tokens** — convert zer0's tokens to W3C JSON in the hub, build CSS/Kotlin/Swift/Godot outputs, publish `@bamr87/fleet-tokens` v1.0.0; zer0-mistakes adopts it first (Sites).
3. **Shell** — extract the Harness Console shell (FF-0032) into `@bamr87/fleet-shell` with the launcher generated from the registry; the console runs on it.
4. **Adoption issues** — one issue per frontend repo, `Adopt fleet frontend platform (§18, tier X)`, labelled `agent:queued`, blocked on #554 ratification; owners pick them up afterwards.
5. **Adoption PRs** — sites and games first (tokens only), then apps (tokens, then shell); each merge sets `frontend.enforce: true` and fills `token_version`.
6. **Steady state** — token and shell releases fan out like other kits; UPS-FE-73 flags stale or forked copies.

## Open questions for Amr

- Token source: zer0's tokens as the fleet base with bashOS as a variant (Sites' request), or bashOS as the base?
- Package distribution: npm on GitHub Packages, or a vendored stamped build?
- Identity: [ADR 0006](adr/0006-django-management-backend.md) proposes that a frontend's private mode signs in to its Django backend. Still open: one account across the fleet (the hub's Django or zer0-id as the single OIDC provider, the other backends relying on it) or an account per app.
- Micro-frontend runtime: proposed in [ADR 0005](adr/0005-console-as-fleet-portal.md) — frames with a bridge by default, Module Federation 2.0 for first-party React plugins, no single-spa.
- Desktop and mobile install: proposed in ADR 0005 — the shell as a PWA first; Tauri or Capacitor only where a store or a native API is needed.
- Should the public shell be served from an origin of its own? Seven apps share `bamr87.github.io` with it, so they run isolated in its frames and gitorio does not render there.
- Owners for fredgar-ai, djangoerp, cv-pro, ocrmd, ragio-ai and fleet-mobile.

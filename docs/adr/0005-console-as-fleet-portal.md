# ADR 0005 — The Harness Console is the fleet's portal: one launcher from the registry, frontends mounted by frame and bridge, one shell per surface

- **Status**: proposed
- **Date**: 2026-11-04
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-04); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: constitution § 18 (fleet design consistency) and § 10.8 (prior art first), [docs/FRONTEND-PLATFORM.md](../FRONTEND-PLATFORM.md) (the six layers this ADR settles layer 3 of), [docs/DESIGN-HARMONIZATION.md](../DESIGN-HARMONIZATION.md), roadmap FF-0032, bamr87/bamr87#583 (enterprise AppShell), #585 (bashOS as the operating layer), #623 (the first federated plugin), [docs/VERIFICATION.md](../VERIFICATION.md), [docs/FLEET-COMPOSE.md](../FLEET-COMPOSE.md)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer asked (2026-11-04) for the Harness Console to be the app shell for every other repo: one portal where each repo's frontend can be viewed, navigated, used and validated, connected either to the live site or to a local Docker version, with the end goal of a common frontend framework that does not depend on the operating system or the device (browser, VS Code extension, terminal, and a mobile app later), governed across the fleet.

**Evidence from the hub.**

- The registry already describes every frontend (`_data/projects.yml` `frontend:`, constitution § 18) and `tools/frontend_registry.py launcher` already generated a launcher manifest from it, but nothing rendered that manifest. The console's project page linked out to a live site in a new tab and knew nothing about a local stack.
- The fleet has 23 frontends on about ten frameworks: Jekyll with the zer0 theme (7), React with Vite (5), Next.js, Django templates, MkDocs, static HTML, Godot, Compose Multiplatform, two VS Code webview extensions and two terminal UIs. No single UI framework can absorb them, and [FRONTEND-PLATFORM.md](../FRONTEND-PLATFORM.md) already says so: standardize the layers between frameworks, not the framework.
- Six projects have a compose-hosted dev stack with fixed loopback ports in `_data/ports.yml`. The console could not open any of them.
- FRONTEND-PLATFORM.md left the composition runtime open ("Module Federation or single-spa?") and that question blocked FF-0032 and #623.
- The verify kit already defines a device matrix (`verify/verify.yml` `viewports:`) and a `--base` override, so "validate this frontend at this address and size" has its inputs; no surface put them together.

**Measured in this change (2026-11-04).** Every one of the 14 live frontends answers and sends neither `X-Frame-Options` nor a `frame-ancestors` policy, so all can be framed. Two could still not be framed from the console: `bash-365.com` in the registry pointed at the apex domain, whose page only forwards the browser to `www.bash-365.com`, an origin no registry entry declared; the fix was a registry address, and the probe now reports an address that moves to an undeclared origin. Framed without access to their own origin's storage, six of the seven apps hosted under `bamr87.github.io` render; gitorio renders blank, and the zer0 theme (`halfmoon.js`, `background-customizer.js`) and MkDocs Material throw on `localStorage`. Evidence: `test/evidence/apps/`.

**Why now.** The registry block, the launcher projection, the port allocation and the device matrix all exist; the portal is the piece that makes them one thing a person uses, and it decides the open composition question the shell work is waiting on. § 10.8 requires this record before a console surface is built.

### Prior art survey (§ 10.8)

- **Framed apps with a message bridge** (Shopify App Bridge, Salesforce Canvas, the iframe plugins of Backstage and Grafana, VS Code webviews). Fit: the only composition that takes a Jekyll site, a Next.js app, a Django page and a Godot web export alike, with the browser's origin boundary as the isolation. Limits: no shared DOM, and a framed site cannot use its cookies when it is cross-site to the shell.
- **Module Federation 2.0** (`@module-federation/vite`). Fit: React remotes that share the shell's React and Mantine as singletons, which is what #623 plans for a hub-built plugin. Not fit for a frontend on another stack.
- **single-spa.** Fit: several SPA frameworks sharing one document, each exporting lifecycles. Not fit for static sites and server-rendered apps, and it couples every app's build to the shell.
- **Web Components (Lit).** Fit: the shared component set (layer 2). Not a way to mount a whole existing app.
- **Backstage.** Fit as a model: a catalog drives a portal with plugins. Not adopted as a product: it needs its own Node backend and plugins rewritten for it, and the hub's registry and console already are the catalog.
- **One model rendered per surface** (server-driven UI). Fit: what `tools/fleetcore` already does for the console, the TUI and the MCP server (views, keys, theme). It is the contract a terminal can share with a browser.
- **Cross-platform UI toolkits** (Flutter, React Native, Compose Multiplatform, Tauri, Capacitor, Electron). Fit: writing one new app for many devices; fleet-mobile is Compose Multiplatform. They cannot host the existing frontends, so none is the fleet's common framework.
- **Progressive Web App.** Fit: makes the web shell installable on a desktop or a phone with no wrapper and no store.
- **VS Code webviews and Simple Browser.** Fit: a webview is a frame host, so the same shell URL loads inside the editor.

**Build versus adopt.** Adopt framed composition with a bridge, Module Federation for first-party React plugins only, the web platform as the common runtime and a PWA as the first install path. Do not adopt single-spa, Backstage or a cross-platform toolkit as the fleet framework. Build the launcher and the portal page: they are a projection of the hub's own registries, about 250 lines of Python and one page, and no existing tool reads those registries.

## Decision

1. **The Harness Console is the fleet's portal.** One launcher, `fleet-launcher/v1`, is generated from the registry (`_data/projects.yml` `frontend:` joined to `_data/ports.yml`) by `tools/fleetcore/apps.py`. Every surface renders that document and none keeps its own list: the console's **Apps** page (`/apps`, `GET /api/apps`, the public snapshot), `tools/dash apps`, and later the TUI, the VS Code extension and the mobile shell.

2. **A frontend is mounted on a four-step ladder, and a repo climbs only as far as its tier asks.**

   | Level | What it is | What the repo must do | Who |
   | --- | --- | --- | --- |
   | L0 link | the launcher opens the address in a new tab | declare an address | every frontend |
   | L1 frame | the shell shows the frontend in a sandboxed frame, at a chosen target and device size | allow the shell's origins to frame it | sites, games and apps; the default, live today for all 14 live frontends |
   | L2 bridge | the framed frontend loads `fleet-bridge`, a small script speaking a versioned `postMessage` protocol: it reports its route and title, takes navigation and theme from the shell, and offers commands to the palette | load one script (the zer0 theme includes it once for every Jekyll site) | `shell`-tier apps that keep their own framework |
   | L3 federated | a React module mounted in the shell's own document through Module Federation 2.0 | be built as a remote with the shell's shared singletons | first-party plugins in the hub (#623) |

   This answers the open question in FRONTEND-PLATFORM.md: Module Federation at L3 only; single-spa is not adopted.

3. **A frontend has targets.** `live` is `frontend.entry_url` (else `live_url`). `local` is each browser-facing service of a compose-hosted dev stack at its `_data/ports.yml` port on 127.0.0.1, the most page-like band first, with the command that starts it (`tools/dash dev up <project>`). A later `preview` target is a pull request's preview deployment. A devenv-hosted project has no local target until the two port maps are reconciled, because the port it is served on is picked at launch.

4. **The shell frames only what the registry declares.** A frame's address is a registry target plus a path inside it; a query string selects a target and never supplies a URL. Frames are sandboxed without top-navigation. A cross-origin frontend keeps its own origin; a frontend served from the shell's own origin is framed without `allow-same-origin`. The console's Content-Security-Policy lists the launcher's origins one by one in `frame-src` and `connect-src`, so admitting an origin is a reviewed registry change. The public page asks no address anything until a reader opens an app, and asks a local address only on a click.

5. **The web platform is the common runtime and the launcher is the common contract.** There is one shell per surface, each generated from the same documents:

   | Surface | Shell | State |
   | --- | --- | --- |
   | Browser | the Harness Console (local, and the public build) | this change |
   | Terminal | `tools/dash apps` now; the TUI's Apps tab opening and checking a frontend; a terminal UI (bashos, netprobe) launched in the console's Terminal page | list, address, open and check in this change |
   | VS Code | an extension kept in the hub that hosts the shell in a webview and lists the launcher as a tree | planned |
   | Mobile and desktop install | the console as a Progressive Web App first; fleet-mobile and a Tauri or Capacitor wrapper read the same launcher when a store or a native API is needed | planned |

   Shared visual language stays with layers 1 and 2 (tokens, Web Components); this ADR does not change them.

6. **Validation belongs to the portal.** Reachability and the frame policy are checked per target (`tools/dash apps check`, and the browser's own check on the page). The device presets are the verify kit's viewports. Running a repo's verify scenarios against the selected target from the portal, showing the evidence, and a per-app panel of the UPS-FE-70..73 results are the next phase.

7. **Governance follows the existing rule.** The registry is the single list. New conformance rows (a frontend allows the shell to frame it, declares its targets, and at shell tier loads the bridge) arrive in their own PR, warn-only per repo until its adoption PR merges, as § 18.4 already prescribes. If the maintainer wants "uses the shared shell" in § 18.2 to read "mounts into the shared shell at L1 or L2", that is a constitution amendment proposed with those rows, not by this ADR.

Files this decision adds or changes now: `tools/fleetcore/apps.py`, `tools/frontend_registry.py` (`launcher` delegates, `probe` is new), `tools/dash` (`apps`), `tools/console/app.py` (`/api/apps`, the policy), `tools/console/snapshot.py`, `tools/console/web/src/pages/Apps.tsx`, `verify/scenarios/apps.yml`.

## Consequences

**Positive**

- Every frontend the registry declares is reachable from one page, at its live address or its local stack, with no change in any fleet repo.
- One projection feeds the browser, the terminal and the public site, so the surfaces cannot disagree about where an app runs.
- The composition question is settled without a rewrite: L1 works for every framework today, and the richer levels are opt-in per repo.
- The portal is a sensor. Its first run found a wrong registry address and three storage defects that no gate had caught.
- The console's policy stays an allowlist: the origins it frames are the registry's, reviewed in a PR.

**Negative**

- A frame is not a shared document. Until L2 the shell cannot read a framed app's route or title, and until the identity layer exists a cross-site framed app that signs in with cookies may be refused them by the browser; the fallback is a new tab.
- An app on the shell's own origin runs isolated on the public page, so it starts without saved state and one that needs browser storage may not render there (gitorio today). The real fix is to serve the public shell from an origin of its own.
- `connect-src` and `frame-src` now carry the fleet's origins. The list is exact and registry-derived, but it is wider than `'self'`.
- A Django app sends `X-Frame-Options: DENY` by default, so the local targets of djangoerp, fredgar-ai and zer0-CMS are expected to refuse the frame until each sets `frame-ancestors` for the shell (not verified here: no stack was started, § 10.5).
- Checking a stopped local stack writes one connection-refused line per port to the browser's console; that is how a browser reports the question the page asks.

## Alternatives considered

- **Rewrite every frontend onto one UI framework.** About ten frameworks and a game engine; the cost is every repo, and Jekyll content sites and a Godot game gain nothing from React.
- **Module Federation or single-spa as the default.** Both require each app to be built for the shell, and neither can host a static or server-rendered site. Kept for first-party React plugins only.
- **A reverse proxy that serves every app under the console's origin.** Gives one origin and shared cookies, but removes the browser's isolation between the control plane and forty repos' JavaScript, and it cannot run on the static public site.
- **Adopt Backstage.** A second catalog and a second backend beside the registry and the console.
- **Keep linking out.** No portal, no validation, and layer 3 of the platform stays undecided.

## Supersedes / Superseded by

- Supersedes: none (settles the composition-runtime question FRONTEND-PLATFORM.md left open)
- Superseded by: none

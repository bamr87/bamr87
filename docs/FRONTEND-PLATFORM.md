# Fleet frontend platform — layers, tiers and fan-out

> How the fleet's frontends share one platform without sharing one framework: six standard layers (tokens, Web Components, one app shell with micro-frontends, one OIDC identity, contracts, a registry with conformance), four tiers, three surfaces, who owns what, and the fan-out plan. Rule: proposed amendment [`fleet-design-consistency`](amendments/proposed/fleet-design-consistency.md) (§ 18); phases: [DESIGN-HARMONIZATION.md](DESIGN-HARMONIZATION.md); shell item: roadmap FF-0032.

## Principle

Standardize the layers *between* frameworks, not the framework. A Jekyll site, a Next.js app, a Godot game and a Kotlin Multiplatform app stay what they are; they agree on tokens, components, identity, contracts and a registry. A repo adopts only the layers its tier asks for.

## The six layers

| # | Layer | Standard | Hub artifact | Consumed by |
| --- | --- | --- | --- | --- |
| 1 | Design tokens | One [W3C Design Tokens](https://www.designtokens.org/) JSON source built with Style Dictionary into CSS custom properties (`--fleet-*`, web), Swift and Kotlin constants (mobile), and desktop/terminal themes | `@bamr87/fleet-tokens` (versioned releases, `fleet-tokens vX.Y.Z` stamp) | every `shell` and `tokens` tier repo; zer0-mistakes through a pinned release |
| 2 | Components | Framework-neutral Web Components (Lit) for the shared set (UPS-FE-10..29: app shell regions, skip link, theme toggle, feedback, toast, search, 404); native mirrors (Compose, SwiftUI) read the same tokens | `@bamr87/fleet-components` | React/Next/Vue apps wrap them; Jekyll includes render them; native apps mirror them |
| 3 | App shell + micro-frontends | One shell owns nav, auth, layout, command palette (⌘K) and the launcher. Web: Module Federation or single-spa (`fleet-mfe.json` per app). Desktop: Tauri wrapping the same shell. Mobile: Capacitor or the native shell in fleet-mobile | `@bamr87/fleet-shell` (successor to `@bamr87/harness-console-ui`, FF-0032) | `shell` tier apps and consoles |
| 4 | Identity | One OIDC provider for every app; the shell does the login and passes tokens to micro-frontends | zer0-id (Go OIDC/OAuth2/WebAuthn, experiment) as the candidate provider | `shell` tier apps; sites and games stay anonymous |
| 5 | Integration via contracts | API gateway with OpenAPI (REST) or SDL (GraphQL) contracts checked in each repo; one event bus with schema'd events; deep-link URLs (`fleet://<slug>/<path>` and the https twin) as universal navigation; agents through MCP and A2A | contract files beside each API (UPS-BE), the event catalog, the deep-link map | apps, consoles, agents |
| 6 | Registry + conformance | The `frontend:` block on each `_data/projects.yml` entry (type, tier, framework, surfaces, token_version, entry_url, shell, enforce); the shell launcher is generated from it (`tools/frontend_registry.py launcher`); UPS-FE-70..73 report drift | registry block, `tools/frontend_registry.py` (drift check (o)), `tools/conformance.py` | everyone |

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
| Browser | `@bamr87/fleet-shell` web build; micro-frontends via Module Federation or single-spa | CSS custom properties |
| Desktop OS | Tauri wrapping the web shell (Electron only with a documented reason); Godot reads an exported theme | CSS, Godot theme resource |
| Mobile | fleet-mobile (Compose Multiplatform) as the native shell, or Capacitor wrapping the web shell | Kotlin and Swift constants |
| VS Code, terminal | webview + `--vscode-*` map; terminal themes (bashOS) | CSS, ANSI theme |

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
- Identity: is zer0-id the fleet OIDC provider, or an external one (GitHub OAuth, Auth0, Keycloak)?
- Micro-frontend runtime: Module Federation (Vite plugin) or single-spa?
- Desktop: Tauri as the default wrapper?
- Owners for fredgar-ai, djangoerp, cv-pro, ocrmd, ragio-ai and fleet-mobile.

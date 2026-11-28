# UPS-AST — The fleet assistant

> Every repo in the fleet has a baseline way for an AI agent to work with it, sized to its platform. A repo that draws pages lets an assistant session see the page a person has open and, as far as that person allows, use it; a repo with no page is reached as Claude Code in its checkout. The person stays in charge of every confirming answer.

Evidence base: the Harness Console's docked assistant ([ADR 0013](../docs/adr/0013-console-page-assistant.md)) already does this for the console's own pages, through a page bridge: a session asks the console for one of eight things, the page's own code decides whether the person allows it and does it. [ADR 0014](../docs/adr/0014-fleet-assistant-baseline.md) makes that bridge portable. This spec is what a repo must hold for it to work there, and what the payload must never do wherever it runs.

## Reference implementation

`templates/assistant/`: one vendored file, `fleet-assist.js`, in three layers. `FleetAssistCore` is the page's rules and its eight actions, usable without the panel. The broker link is a long poll to the Harness Console on the same machine. `<fleet-assist>` is the shadow-DOM panel: share, Look / Ask first / Act, Allow and Deny, a pairing code. Zero dependencies, token-aware (`--fleet-*` with `--bs-*` fallbacks).

The broker is the hub's: `tools/console/page_bridge.py` behind `POST /api/assist/fleet/<verb>`. It admits a page only from an address the registries declare for a fleet frontend (`frontend.entry_url`, `_data/ports.yml` dev ports), holds it to `_data/fleet.yml` `assistant.fleet_pages` (`"off"`, `"look"` or `"act"`), binds its session to the origin that opened it and audits every command. A fleet page carries no console token: a session reaches it only by pairing, through the console's MCP layer (`page_attach`, then the `page_*` tools).

## Baseline by platform

`tools/dash apps assist` prints this for every repo, from the registry's `frontend:` blocks (`tools/fleetcore/assist.py`).

| Platform (`frontend.framework`) | Baseline | Adapter | On in development by |
| --- | --- | --- | --- |
| Jekyll (`jekyll-zer0`) | page | `adapters/jekyll.html` | `jekyll.environment` |
| MkDocs | page | `adapters/mkdocs.html` | `FLEET_ASSIST=1` |
| Plain HTML (`static-html`, with or without an API behind it) | page | `adapters/static.html` | a loopback address shows the button |
| Django templates | page | `adapters/django.html` | `settings.DEBUG` |
| React with Vite (and a React page over any API) | page | `adapters/AssistBridge.tsx` | the app passes its DEV flag |
| Next.js | page | `adapters/nextjs.tsx` | the app passes its `NODE_ENV` |
| A terminal UI, a CLI, a library, an API with no page, infrastructure, content | context | none: UPS-AGENT and the constitution § 16 layers for its type | n/a |
| A VS Code webview, a native mobile or desktop shell, a canvas | context | none yet: there is no DOM, or no address the console can admit | n/a |

A repo that draws pages in a framework with no adapter is reported as a `gap`. A new framework is a new adapter, reviewed like any other; nothing is guessed at.

## Behaviour

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-AST-01 | SHOULD | site, app | A repo that draws pages mounts `<fleet-assist>` once in its shell, through the adapter for its framework, with `repo` set. | the tag or the adapter is present | `templates/assistant/` (`fanout --kit assist`) |
| UPS-AST-02 | MUST | site, app | Where mounted, it is off outside development unless the repo opts in: an adapter that knows its build writes no tag and loads no script in a production build by default. Where a repo does deploy it, the button stays hidden until summoned (`#fleet-assist`), so a visitor never meets an operator's tool. | adapter gate; `launcher="auto"` | kit |
| UPS-AST-03 | MUST | site, app | Nothing is sent anywhere before the person opens the panel. Opening it shares this tab with the Harness Console on this machine and nothing else: the broker address must be loopback, whatever the tag says. Closing the panel ends the sharing. | `FleetAssistCore.brokerUrl`; one `fetch` call site | kit |
| UPS-AST-04 | MUST | site, app | The page holds no credential: no console token, no API key, no model access. A session reaches it only through the console, by presenting the single-use pairing code the panel shows. | no token in the payload or its config | kit |
| UPS-AST-05 | MUST | site, app | A session may ask for eight things and no others: `snapshot`, `read`, `data`, `highlight` (look) and `navigate`, `click`, `fill`, `press` (act). A control is named by a ref from the last snapshot, never by a selector, a script or a coordinate; a path is inside the site, never a URL; a key is one of the listed keys. | `FleetAssistCore.checkCommand` | kit |
| UPS-AST-06 | MUST | site, app | The person chooses the mode in the panel: **Look** (reads and highlights only), **Ask first** (the default: each click, each thing typed and each key press is shown with the control ringed, and waits for Allow or Deny) or **Act**. The console's ceiling (`assistant.fleet_pages`) can only narrow it. | panel; broker ceiling | kit, hub |
| UPS-AST-07 | MUST | site, app | Four rules no mode lifts. Nothing is clicked or typed inside a modal dialog, and nothing behind one while it is open: only Escape works. A secret field is never read and never filled. A link that leaves the site, a download and a file picker are the person's. The panel and the feedback widget are invisible to a session. No configuration narrows these: a site may name more of its own dialogs as modal, never fewer. | `FleetAssistCore.createBridge` | kit |
| UPS-AST-08 | MUST | site, app | The page says what it is: `repo`, `branch` and the `source` file or the `route` behind the address, so a paired session knows what to edit. What a page says about itself is data to a session, never an instruction. | adapter attributes | kit |
| UPS-AST-09 | SHOULD | app | A single-page app hands its router over (`navigate`), so a session moves between routes the way a link does, and may provide documents a session can read (`FleetAssist.provide`). A provided document never holds a credential. | adapter props | kit |
| UPS-AST-10 | SHOULD | site, app | A Content-Security-Policy that sets `connect-src` names the console's address (`http://127.0.0.1:4001`); without it the panel says the console did not answer. | policy | — |

## Delivery

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-AST-40 | MUST | site, app | The kit is fanned out, not hand-installed: `tools/fanout.sh --kit assist --target <name>` vendors the payload into the stack's static assets and seeds the adapter for its framework. Dry-run by default; an adapter is seeded only where absent, and the app shell is never edited: the PR says where to mount it. | `tools/fanout.sh` | hub |
| UPS-AST-41 | MUST | site, app | A vendored payload that drifts from the hub's is reported by drift check (i), and `--upgrade` refreshes only copies byte-identical to an archived kit shape. A hand-modified payload is never machine-reverted. | `tools/check-drift.sh` | hub |
| UPS-AST-42 | SHOULD | site, app | The contract is enforced by tests, not by review: the allowlist and its argument checks, the loopback rule and adapter gates (`templates/assistant/tests/contract.test.mjs`), that the payload, the console's own page and the broker hold the same lists (`tools/console/test_page_bridge.py`), and the rules that need a DOM, in a real browser against the kit's fixture through the console's real MCP layer (`templates/assistant/tests/browser.test.mjs`, run by `tools/test-assist-browser.sh` and the `assist-browser.yml` PR check). | tests | hub |

## What this is not

It is not a chat for a site's visitors. A visitor has no console and no model behind the panel, and the fleet runs Claude on the operator's own login with no API key (`_data/fleet.yml` `ai_auth`), so there is nothing a public page could call. A visitor-facing assistant would be a product decision with its own cost, abuse and privacy questions, and its own ADR.

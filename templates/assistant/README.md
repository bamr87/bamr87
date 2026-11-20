# templates/assistant — the fleet assistant kit

> `<fleet-assist>`: one component that lets an assistant session see the page a person has open, in any stack, and use it as far as that person allows. Spec: [`specs/ASSIST.md`](../../specs/ASSIST.md) (UPS-AST). Decision: [ADR 0014](../../docs/adr/0014-fleet-assistant-baseline.md).

| File | Purpose |
| --- | --- |
| `fleet-assist.js` | The payload, in three layers: `FleetAssistCore` (the page's rules and its eight actions), the link to the Harness Console on this machine, and `<fleet-assist>` (the panel). Zero dependencies, shadow DOM, token-aware (`--fleet-*` with `--bs-*` fallbacks). |
| `adapters/jekyll.html` | Include for a Jekyll site, the zer0-mistakes theme's consumers included. On in development (`jekyll.environment`). |
| `adapters/mkdocs.html` | `overrides/main.html` for MkDocs. On with `FLEET_ASSIST=1`. |
| `adapters/static.html` | Two lines for a page of plain HTML. |
| `adapters/django.html` | Django template include (translate 1:1 to ERB for Rails). On with `settings.DEBUG`. |
| `adapters/AssistBridge.tsx` | React wrapper for Vite and Next client components: hands the app's router over, and `provideDocument()` for documents a session may read. `enabled` has no default. |
| `adapters/nextjs.tsx` | `AssistBridgeNext`: the App Router wired in. |
| `tests/contract.test.mjs` | 10 contract tests. `npm test` — `node:test`, no dependencies. |
| `tests/fixture.html` · `tests/fixture-2.html` | A page with one of everything the rules are about, and the page a navigation lands on. |
| `test_assistant_kit.py` | Holds this table and `VERSION` to the tree, and runs the contract tests where Node is installed (the hub's CI discovers it). |
| `VERSION` · `package.json` | Kit provenance and changelog; the npm manifest `@bamr87/fleet-assist`. |

## How it works

The payload does nothing until someone opens its panel. Opening it shares that tab with the Harness Console running on the same machine (`http://127.0.0.1:4001` unless the tag says another loopback address). A Claude Code session then reaches the page through the console: the panel shows a single-use pairing code, and the session presents it with the console MCP layer's `page_attach`. From there the session has the `page_*` tools: `page_snapshot` reads what is on screen as an outline with a ref per control, `page_read` and `page_data` read more, `page_highlight` points, and `page_navigate`, `page_click`, `page_fill` and `page_press` act.

The session never touches the page. It asks the console for one of those eight things, the console queues it, and the payload decides, in the tab, whether the person allows it. The page tells the session which repo it is and which source file is behind the address, so "fix this heading" has somewhere to go.

## Install

The fan-out does this for a fleet repo, as a pull request, dry-run by default:

```bash
tools/fanout.sh --kit assist --target <name>            # what it would seed
tools/fanout.sh --kit assist --target <name> --apply    # open the PR
tools/dash apps assist                                  # which adapter each repo gets
```

By hand, in any stack:

1. Vendor `fleet-assist.js` into the repo's static assets (`assets/js/`, `public/`, `static/js/`). Never hot-link the hub.
2. Mount the element once in the shell with the adapter for your stack, with at least `repo="owner/name"`.
3. Make sure the page's origin is one the console admits: the repo's `frontend.entry_url` in `_data/projects.yml`, or its dev port in `_data/ports.yml`. An address the registries do not declare is refused.
4. If the site sends a Content-Security-Policy with `connect-src`, add the console's address to it.

## Use it

1. Start the console (`tools/dash up`) and the site's dev server.
2. On the page, open **Assistant** (bottom left) and choose **Pair a Claude Code session**.
3. In a Claude Code session that has the console's MCP server with the `page` scope (`HARNESS_MCP_SCOPES=page`), say: attach to my page with code `XXXX-XXXX`.

The panel has three modes. **Look**: the session reads and points. **Ask first** (the default): it can also move between pages, and each click, each thing it types and each key press is shown to you with the control ringed and waits for Allow or Deny. **Act**: it uses the page without asking. The console's `assistant.fleet_pages` setting can narrow this for every page at once.

## What a session can never do

- Name a control by anything but a ref from the last snapshot: no selector, no script, no coordinate.
- Click or type inside a modal dialog, or use the page behind one while it is open. Only Escape works. A confirmation is yours to answer.
- Read or fill a secret field (a password input, or a field whose name says token, secret, key or credential).
- Follow a link that leaves the site, start a download or use a file picker.
- See or use this panel, or the feedback widget.

## Attributes

`broker` (a loopback address only) · `repo` · `branch` · `source` · `route` · `page-title` · `base` (the site's path prefix) · `framework` · `env` · `app-version` · `root` (CSS selector of the page frame; default the `<main>` element) · `launcher` (`auto`: a button on a loopback address and hidden elsewhere until the address ends `#fleet-assist`; `button`; `summon`) · `position` (`left` | `right`) · `label`.

## JS API

```js
FleetAssist.open();  FleetAssist.close();  FleetAssist.state();   // { open, mode, shared, paired }
FleetAssist.configure({ navigate, base, root, pages, modal });     // a single-page app hands its router over
FleetAssist.provide('cart', () => store.getState().cart);          // a document page_data can read
FleetAssistCore.createBridge(env).run(command);                    // the rules, without the panel
```

## Privacy

No cookies, no analytics and no request of any kind until the panel is opened. After that the page talks to one address, on the same machine, and holds no token. The session id lives in `sessionStorage`, for this tab only, so that a site of plain pages keeps its session when a navigation loads the next page. Closing the panel ends the session. What a snapshot contains is what is on screen, minus secret fields; the console scrubs credential shapes from every answer as a backstop.

## Limits

- A snapshot reads the page's own DOM. It does not read inside an iframe, an open or closed shadow root, or a canvas.
- The modal rule is deliberately broad: a search box or a menu drawn as a modal dialog cannot be used by a session either.
- On a deployed `https` site, a browser may ask before letting the page reach an address on your machine. On a dev server it does not.
- A fleet page is reached by pairing only. The console's docked assistant is not started against one yet (ADR 0014, phase 3).

## Changing the kit

- The lists at the top of `fleet-assist.js` are a contract with the console's broker and its own page. `tools/console/test_page_bridge.py` fails when they disagree; change all three together.
- Snapshot the outgoing `fleet-assist.js` into `archive/` **before** editing it once it has been fanned out, or every deployed copy reads as hand-modified and `--upgrade` stops reaching the fleet.
- `npm test` before committing, and run the fixture in a browser against a console: the rules that need a DOM are proven there (`test/evidence/fleet-assist/`).

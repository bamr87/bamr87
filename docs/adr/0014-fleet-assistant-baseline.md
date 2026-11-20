# ADR 0014 — The fleet assistant baseline: one page bridge, an adapter per platform, and the console as the one broker

- **Status**: proposed
- **Date**: 2026-11-19
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-19: turn the console's page assistant into fleet-wide functionality for every repo across the stack, with at a minimum a baseline AI agent integration per platform)
- **Related**: [ADR 0013](0013-console-page-assistant.md) (the docked assistant and the page bridge, which this makes portable), [ADR 0005](0005-console-as-fleet-portal.md) (the console as the fleet's portal, whose launcher names every frontend's address), constitution § 10.5 to § 10.9 (hands off the Mac, read-only tools, honest cost, prior art, local first), § 13 (risk tiers and spend), § 16 (the AI-ready foundation, sized to a repo's type), § 18 (fleet design consistency), [specs/ASSIST.md](../../specs/ASSIST.md) (UPS-AST), [templates/assistant/](../../templates/assistant/README.md), [specs/FEEDBACK.md](../../specs/FEEDBACK.md) (the delivery pattern this copies)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

ADR 0013 put Claude Code beside every page of the Harness Console: a session can read the page a person has open and, in the mode that person chooses, use it. That works for one product. The fleet has 41 active repos. Nineteen of them draw pages in a browser, in six framework families: Jekyll on the zer0-mistakes theme (7), React with Vite (6), plain HTML (3), MkDocs, Next.js and Django templates (1 each). The other 22 have no page: libraries, CLIs, terminal UIs, infrastructure, two VS Code extensions, a mobile shell and a canvas game.

Today an agent working on one of those 19 sees its source and nothing of what it renders. The person describes the page in words, or pastes a screenshot. The request is that every repo has a baseline AI agent integration sized to its platform, and that where there is a page the agent can see it and interact with it.

### What already exists

- The page bridge (ADR 0013): a broker in the console (`tools/console/page_bridge.py`), the page's half in the console's React app (`pageBridge.ts`), and the session's half as MCP tools (`page_snapshot`, `page_click`, …). Its rules are the valuable part: refs instead of selectors, the person's mode, nothing inside a modal dialog, no secret fields.
- The app launcher (ADR 0005, `tools/fleetcore/apps.py`): for every repo, its framework and the addresses its frontend answers at, live and local. The console's Content-Security-Policy is already built from that list.
- The feedback kit (`templates/feedback/`, UPS-FB): a zero-dependency web component vendored into every stack through one adapter per framework, fanned out as pull requests, held byte-identical by a drift check. It is the fleet's proven way to put one piece of page code in many stacks.
- The agent-context kit and constitution § 16: `AGENTS.md`, `.claude/settings.json` and the API, MCP and metadata layers each repo type owes. That is already the baseline for a repo with no page.

### Prior art, and build or adopt (§ 10.8)

ADR 0013 surveyed the field for one page: browser automation over the DevTools protocol (Playwright MCP, Chrome DevTools MCP), a browser extension that drives the person's own browser (Claude in Chrome), in-page agent frameworks, and the WebMCP proposal. Its finding holds here. The automation tools drive a browser the agent owns, not the tab the person is looking at, and bring their own trust model. The extension reaches the person's tab but answers to no fleet rule: it has no Ask-first mode tied to the page, no modal rule, and no knowledge of which repo and source file a page came from.

What is new at fleet scale is the delivery question, and there the fleet has its own prior art in the feedback kit. So the decision is to adopt the fleet's delivery pattern and to build nothing new on the agent side: the same broker, the same MCP tools, the same rules, with the page's half rewritten once as framework-free code. Playwright MCP remains the right tool for an agent testing a page nobody is looking at (the verifier), and nothing here replaces it.

## Decision

1. **Three baselines, read from the registry.** Every repo is `page` (it draws pages in a framework the kit has an adapter for), `context` (it has no page a browser can outline, and is reached as Claude Code in its checkout on the agent-context kit and its § 16 layers) or `gap` (it draws pages in a framework no adapter covers). `tools/dash apps assist` computes this from the registry's `frontend:` blocks (`tools/fleetcore/assist.py`). A gap is reported, never guessed at. Today: 19 page, 22 context, 0 gap.

2. **One payload, one adapter per framework.** `templates/assistant/fleet-assist.js` is the page's half of the bridge with no dependencies: the rules and the eight actions (`FleetAssistCore`), the link to the console, and a shadow-DOM panel (`<fleet-assist>`). Adapters mount it in Jekyll, MkDocs, plain HTML, Django templates, React and Next.js. It is vendored, fanned out as pull requests (`tools/fanout.sh --kit assist`, dry-run by default, the shell never edited) and held byte-identical by drift check (i), exactly as the feedback widget is.

3. **The console is the one broker, and a fleet page holds no token.** A page shares itself by calling `POST /api/assist/fleet/<verb>` on the console on the same machine. Those calls take no console token, on purpose: a public page must never hold one, and a page session is an offer to be driven, so holding one grants nothing. What guards them instead: the `Origin` must be an address the registries declare for a fleet frontend (the launcher's list, each loopback dev port under both of its names); a session answers only to the origin that opened it; fleet pages have their own ceiling (`_data/fleet.yml` `assistant.fleet_pages`) and their own cap, so they cannot crowd out the console's dock; and the payload refuses any broker that is not a loopback address. The session id rides in the request body, never in an address, so no access log keeps it.

4. **A fleet page is reached by pairing only.** The panel shows a single-use code; a Claude Code session presents it through the console's MCP layer (`page_attach`) and then has the `page_*` tools. That session is the person's own Claude Code, in a terminal or an editor, with the repo's source in reach, which is the point: it sees the page and can change what renders it. The console does not start a session of its own against a fleet page in this decision; `page_bridge.has()` says no for one.

5. **The same rules everywhere, held by a test.** The payload enforces what the console's page enforces: a control is a ref from the last snapshot; nothing is clicked or typed inside a modal dialog or behind an open one; a secret field is never read or filled; a link that leaves the site is the person's; Look, Ask first and Act are the person's choice. A modal is recognised in the forms the fleet's stacks draw one: the native `<dialog>` shown modally, `aria-modal`, Bootstrap's `.modal.show` and Mantine's roots. `tools/console/test_page_bridge.py` holds the payload, the console's page and the broker to the same lists.

6. **Off outside development, and not for visitors.** Every adapter that knows its build writes no tag in production unless the repo opts in, and where a repo does deploy it the button is hidden until summoned. There is no assistant for a site's visitors: a visitor has no console, and the fleet runs Claude on the operator's own login with no API key, so there is nothing a public page could call. A visitor-facing assistant would be a different decision.

7. **A site of plain pages keeps its session.** Navigating such a site loads a new address, which ends the page's code. The payload keeps its session id in `sessionStorage` (this tab only) and picks the session up on the next page; a command in hand when the page unloads is answered on a request that outlives it. The broker hands a command to a session's newest poll only, because the old page's poll is still waiting with nobody behind it. That last rule fixes a loss that would otherwise follow every navigation, and it applies to the console's own page too.

8. **Rollout is phased, and each phase is the maintainer's to start.** This ADR's pull request builds the kit, the broker's fleet routes, the spec and the planner, and proves them against a fixture. It opens no pull request in any fleet repo.

### Phases

| Phase | What | Gate |
| --- | --- | --- |
| P0 (this PR) | Kit 0.1.0, the broker's fleet routes, UPS-AST, `dash apps assist`, the fan-out arm, evidence on the fixture | this ADR accepted |
| P1 | The zer0-mistakes theme carries the include, so one change reaches the seven Jekyll sites; fan-out pull requests for one repo per remaining family (README, gitorio, law-ai, djangoerp, ocrmd) | the maintainer starts the fan-out |
| P2 | The console's own page adopts `FleetAssistCore` (one implementation of the rules, not two held equal by a test), and its tab routes move the session id into the body | P1 has run on real stacks |
| P3 | In-product conversation: the console's Apps page frames a fleet app, and the docked assistant is started against that page | P2; a spend decision |
| P4 | A machine check for UPS-AST-01 in `tools/conformance.py`, then the rest of the 19 | P1 pull requests merged |
| P5 | A `postMessage` link for VS Code webviews; `tools/dash apps assist` reads the § 16 manifest for the context baseline | the ai-ready kit lands |

## Consequences

**Positive**

- A person working on any fleet page can hand that page to their Claude Code session with a code, and the session knows the repo and the source file behind it.
- One set of rules protects every page, and the person's yes stays theirs on every stack.
- The delivery reuses three things that already exist: the launcher's origin list, the fan-out, and the drift check.
- Every repo has a named baseline, and the registry says which.

**Negative, and what limits it**

- Until P2 there are two implementations of the page's rules: the console's TypeScript and the kit's JavaScript. A test holds their lists equal; it cannot hold their behaviour equal. P2 removes the second copy.
- The console gains routes that take no token. They hand out no data and no capability beyond being driven, they answer to registered origins only, and a local process that forges an `Origin` gains a session nobody is paired with. The ceiling `assistant.fleet_pages: "off"` closes them.
- The modal rule is broad on purpose. On a site that draws its search or its navigation as a modal dialog, a session cannot use it and must say so.
- A page's text is read by a session with the person's own tools. The payload marks everything it returns as data, and the MCP layer says so in its instructions, but a hostile page is still a prompt-injection surface, as any page an agent reads is. The fleet's own pages are the scope; the origin allowlist keeps it there.
- A deployed `https` page reaching an address on the person's machine may be asked about by the browser first. Development servers are not.
- Nineteen repos each gain one vendored file. The drift check and `--upgrade` keep them current; a hand-edited copy is left alone and reported.

## Alternatives considered

- **Give each repo a browser-automation MCP server.** No fleet code, but the agent drives a browser of its own rather than the tab the person is in, there is no Ask-first tied to the page, and each repo would configure it separately. Kept for testing, not adopted for this.
- **A broker in each stack's backend.** Works for Django, impossible for a static site, and multiplies the trust surface by the number of backends. The console is already on the machine.
- **A browser extension.** Reaches any page with no vendored file, but it is a second product to build, sign and keep current, and it would see pages that are not the fleet's.
- **A chat widget for visitors.** Needs a hosted model endpoint, an API key the fleet has switched off, and abuse and privacy controls. Out of scope, and a different decision.
- **Give the fleet page the console's token.** Simplest to build, and wrong: a token in a public page's reach is a token published.

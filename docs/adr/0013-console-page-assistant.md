# ADR 0013 — The docked assistant and the page bridge: an agent session may see and use the console page a person has open, and the confirming yes stays theirs

- **Status**: proposed
- **Date**: 2026-11-18
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-18: build the AI assistant into the console so that Claude Code is inside the web console and can see and interact with the loaded page, frontend and backend)
- **Related**: constitution § 10.5 to § 10.9 (hands off the Mac, read-only tools, honest cost, prior art, local first), § 11.4 and § 11.8 (dry run then confirm, the OPS remote-write path), § 13.5 to § 13.8 (tracing, risk tiers, earned autonomy, the lethal trifecta), § 25 (MCP server lifecycle); ADR 0004 P2 (the read-only Assist page this extends); HUB-075; `docs/HARNESS.md` roadmap ("the assistant in the console")

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

The console already has an assistant (ADR 0004 P2, shipped 2026-11-04): the Assist page sends one question to one capped, headless Claude Code session that reads the fleet through the console's own MCP layer and writes nothing. Three things keep it from being "Claude Code in the console".

- **It cannot see what the person sees.** The only context it gets is an optional 300-character text field. A question such as "why is this row red" or "where do I run this" has to be retyped as a description of the page.
- **It lives on one page and forgets.** Asking means leaving the page the question is about, and every question starts from nothing.
- **It cannot show or do anything.** When the answer is "open Operations, filter for drift, press Run", the person does all of it by hand, though the page is right there.

A fourth fact shapes the design. The console the maintainer opens every day runs in a container that has no `claude` CLI (checked on 2026-11-18: `fleet-console-1` has none on its PATH, the host has 2.1.308), so on that console the existing assistant reports that it cannot run at all. The Claude Code sessions that do exist on the machine are the interactive ones in a terminal or an editor, and they already hold the `fleet` MCP server.

### What must not change

The console can dispatch workflows, push secrets and file issues with the operator's token. Every one of those asks first, in a dialog, and the constitution makes that yes a person's (§ 11.4, § 13.6: money and external actions wait for the maintainer). An agent that can click in the page must not be able to click that dialog, read a credential out of a field, or be talked into either by text it reads on the page (§ 13.8).

### Prior art and existing tools

Surveyed from the author's knowledge at the time of this PR; no project's current release was re-checked for it.

| Tool | What it is | Fit |
| --- | --- | --- |
| Claude in Chrome (Anthropic's extension) | A general agent that sees and acts in the person's own browser | Reaches any site, the console included, but knows nothing of this console's gates: a confirm dialog is one more button to it. Needs the extension; its runs are outside `ai-run`'s cap, ledger and redaction |
| Playwright MCP (already in `.mcp.json`) | An agent drives a separate, isolated browser | The right tool for verification, and it stays that. It is never the tab the person has open, and it shares none of that tab's state |
| Chrome DevTools MCP | An agent attaches to a Chrome instance over the debugging protocol | Can reach the real tab, with full control including script evaluation. No allowlist and no notion of a human-only control; needs Chrome started for remote debugging |
| WebMCP / MCP-B (`navigator.modelContext`) | A proposed way for a page to declare tools to an in-browser agent | The closest in spirit: page-declared, typed tools. Early and browser-dependent, and it still needs an agent in the browser to call them. The eight actions here could be offered that way later |
| CopilotKit, AG-UI | A React framework for in-app copilots with frontend actions | Brings its own runtime and calls a model API directly. The fleet's Claude auth is OAuth through the CLI (`ai_auth:`; no API key since 2026-11-15), so it has no credential to use, and it would duplicate the cap and ledger `ai-run` already holds |
| assistant-ui, Vercel AI SDK UI | Chat UI components over a streaming chat endpoint | The console's assistant is a job, not a streaming endpoint. The thread is about two hundred lines of Mantine; a library would add a protocol to adapt to and save little |
| Claude Agent SDK with in-process tools | Host the agent loop inside the console process | Would bypass `dash-gen ai-run`, which is where the dollar cap, the usage-limit rule, the trace redaction and the ledger row live (§ 13.5, § 29.2), or reimplement them |
| browser-use, Stagehand | Libraries where a model drives its own Playwright browser | A separate browser with their own model keys; not the person's page, and not the fleet's auth |
| Claude Code in the Terminal page | Run the interactive CLI in the page's terminal | Literally the CLI in a browser, but the terminal bridge runs one allowlisted program (the dash TUI); a general shell from a web page is a different security model, and it still could not see the page |

### Build or adopt

**Adopt** Claude Code as the agent (headless through `dash-gen ai-run`, or the interactive session a person already has), MCP as the tool protocol (the console's existing layer), and Mantine for the panel. **Build** only the piece nothing above provides: a small bridge between a session's tools and the open tab that keeps the console's own confirmations human. The deciding requirement is that last one. Every adoptable tool treats the page as a surface to automate; this console needs one specific part of that surface to be out of reach, and that rule has to live in code the session cannot change.

## Decision

1. **The assistant docks beside every console page.** A header button opens a panel in the shell's aside (`tools/console/web/src/assist/`). It is beside the page, not over it, so the person keeps reading and using the page while the assistant works. A message is still the `assist` op, one capped session through `ai-run`, with two additions: it continues a **conversation** (the console replays the earlier questions and answers into the prompt from its own records, never from the request; `assistant.conversation_messages` caps the length) and it carries the **page** the person has open.

2. **A page bridge connects a session to an open tab** (`tools/console/page_bridge.py`, `/api/assist/page…`). It is a queue with an allowlist of eight actions: `snapshot`, `read`, `data`, `highlight` (look) and `navigate`, `click`, `fill`, `press` (act). A session's MCP tool posts one action; the tab's own code picks it up on a long poll, does it in the DOM as that person, and posts back what happened. An element is named by a ref from the last snapshot, never by a selector or a script; a path is an in-app path, never a URL.

3. **Three settings bound what a session may do, and two rules have no setting.**
   - The **ceiling** is `_data/fleet.yml` `assistant.page_access`: `off`, `look` or `act`.
   - The **mode** is the person's choice in the dock for this tab: *Look*, *Ask first* (each click, fill and key press is shown to them and waits up to 90 seconds for their yes) or *Act*. *Act* is not remembered across a reload.
   - **Sharing** is the dock being open: closing it ends the session.
   - **Nothing is clicked or typed inside a modal dialog.** Every confirming question this console asks is a Mantine modal (the job runner's confirm, the GitHub and Work board confirms, the token prompt), so the rule is structural: the page's code refuses any click, fill or key but Escape there, in every mode, and while a modal is open it refuses to use the page behind it too, as the overlay does for a person. A test holds the premise (every place the page sends `confirm: true` gathers it in a modal).
   - **A secret field is never read and never filled**, and a link that leaves the console is the person's to open. The dock itself is invisible to a session.

4. **Spend goes through the one gate.** The dock starts a message with `runOp`, like every other operation. The first message of a conversation gets the "This spends Claude budget" dialog, which states the envelope (how many messages, the cap of each); a later message that continues that confirmed conversation in the same tab is sent without asking again. A new conversation, another tab or a reload asks again.

5. **Two kinds of session reach a page, by two capabilities.** A session id is 128 random bits. The **docked session** gets its page's id in the environment of the one MCP server process the console starts for that message, with the `page` scope and every other write surface pinned off. A **paired session**, the interactive Claude Code in a terminal or an editor, gets a page only with a pairing code the person switches on in the dock and reads to it: eight characters, single use, ten minutes, and wrong guesses lock pairing. The page tools exist on the stdio transport only, because an HTTP MCP server is one process shared by every client; a paired session gets the look tools by default and the act tools only with `HARNESS_MCP_SCOPES=page` (§ 25.7).

6. **Every command is recorded.** One append-only JSONL line each (when, which session by prefix, docked or paired, the action, its target, the mode, the outcome), credential shapes scrubbed; a fill is recorded by its length, never its text (§ 13.5). The dock lists what was done to the page.

7. **The assistant still holds no write tool.** Its tools are the fleet MCP server and reading the hub checkout, as before. What it can change, it changes through the page, where every gate the person has still stands. Starting an operation is a click on that operation's Run button; an operation that writes or spends then opens its dialog, which is the person's.

## Consequences

**Positive**

- The assistant answers about what is on the screen, from the documents the page itself loaded (`page_data` reads the page's query cache), and can point at the thing it means.
- "Do it for me" has one gate model, the page's own. No second allowlist of operations an agent may start, and no new path around `confirm: true`.
- It works on the container console today through pairing, with the Claude Code session the maintainer already has, which is the local-first route (§ 10.9). A console on the host can start sessions itself.
- A $0 stand-in (`tools/console/assist_standin.py`) exercises the whole path without a model, so the plumbing can be verified without asking for a spend.

**Negative**

- A new trust path: a compromised or confused session, in *Act* mode, can do on the page what the person could do without a dialog. That includes starting $0 local operations and editing the working tree's `_data/fleet.yml` through the Config page. *Ask first* is the default, and *Act* is a deliberate, per-load choice; the audit line records each action.
- The modal rule is structural, so it also blocks harmless dialogs (the key sheet, the palette). A session navigates by path instead.
- Page text reaches a model. The prompt and the tool descriptions say it is data, and the secret-field rule and the scrub are the backstops, but a snapshot of a page that shows an issue title shows that title.
- The docked session needs the `claude` CLI where the console runs. In the container it reports that plainly and offers pairing; putting the CLI in the image is a separate decision (§ 21).
- One more long poll per open dock, held on a threadpool thread; `page_bridge.MAX_SESSIONS` bounds it.

## Alternatives considered

- **A scoped MCP tool that starts operations** (`job_dispatch` for the docked session). Rejected: it is a second gate beside the page's, and with `--permission-mode dontAsk` the model would set `confirm=true` itself. Driving the page keeps the yes with the person.
- **Mark each confirming button as human-only.** Rejected for the structural rule: a mark is forgotten on the next button someone adds; "never inside a modal" cannot be.
- **`--resume` for conversation continuity.** Not chosen: the ledger keys a resumed session to one row and treats the CLI's cost as cumulative, and how `--max-budget-usd` applies across a resume is not something this change could verify without spending. Replaying the transcript keeps every message one independently capped session with its own row.
- **Server-sent events or a WebSocket for the page's side.** A long poll through the page's ordinary `api()` path carries the bearer token and the token prompt for free; `EventSource` cannot set a header, and the WebSocket path has its own Host and Origin checks to repeat.
- **Page tools on the HTTP MCP transport**, so a remote agent could pair. Rejected for now: one server process serves every remote client, so a pairing would be shared by all of them. It needs a per-client binding first.
- **The adoptable tools** in the table above, each for the reason given there.

## Supersedes / Superseded by

- Supersedes: none (extends ADR 0004 P2's read-only assistant; that section stands)
- Superseded by: none

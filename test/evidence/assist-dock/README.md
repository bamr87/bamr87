# The docked assistant and the page bridge — evidence

> **Feature:** `HUB-NEW:console-page-assistant` (`features/features.d/console-page-assistant.yml`, [ADR 0013](../../../docs/adr/0013-console-page-assistant.md)) · **Scenario:** [`verify/scenarios/assist-dock.yml`](../../../verify/scenarios/assist-dock.yml), **PASS** on the public build at two viewports (`report.json`) · **Console pass:** **PASS** by hand, on a console started from this branch, end to end on a scripted stand-in for the model at $0 · **Not verified:** an answer from the real model (it spends; that yes is the maintainer's) · 2026-11-18.

What a person can do after this change: open the assistant beside any console page, ask about what is on it, have it point at things, and let it move around and use the page as far as the mode they pick allows, with each click asked first by default. What they are protected from: no session can answer one of this console's confirming dialogs, read or fill a secret field, or see the dock itself.

## The public build (the runner)

`node verify/runner.mjs --base http://127.0.0.1:4020 --only assist-dock` against `CONSOLE_BASE=/ tools/console/build-pages.sh`, desktop 1280×800 and mobile 390×844. The published page has no console behind it, so it must offer no dock.

| Image | What to look at |
| --- | --- |
| `desktop-assist-public.png` | `/assist` on the public build: the header has search, jobs, refresh and theme and **no** assistant button; the banner *Runs on a console*; no "Open the docked assistant" |
| `mobile-assist-public.png` | the same at 390 px; nothing scrolls sideways |

The scenario also asserts no `[data-testid='assist-toggle']` and no `[data-assist-dock]` on `/assist` and on `/loops`.

## A running console (the interactive pass)

Three consoles were started from this branch on loopback, each with no credentials (`GH_TOKEN`, `FLEET_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` unset, `DASH_CONSOLE_GITHUB_WRITES=off`), its own job directory and its own `DASH_AI_LEDGER`: `:4014` with [`tools/console/assist_standin.py`](../../../tools/console/assist_standin.py) first on its PATH as `claude`; `:4015` with no `claude` on its PATH at all, which is how the console's container is built; `:4016` serving `origin/main`'s page for the *before* images. The live console on `:4001` was not touched. Driven with the Playwright MCP.

The stand-in is not a model. It takes the flags `ai-run` passes, starts the real MCP server from `--mcp-config`, calls page tools chosen by keywords in the question, and prints the stream-json `ai-run` parses. So in these images the dock, the `assist` job, `ai-run`, the MCP layer over stdio, the page bridge and the browser are all real, and only the reasoning is canned; each answer says so.

| Image | Viewport | What to look at |
| --- | --- | --- |
| `before-desktop.png`, `before-mobile.png` | 1280×800, 390×844 | `/loops` on `origin/main`'s page: no assistant button in the header |
| `closed-desktop.png`, `closed-mobile.png` | 1280×800, 390×844 | the same page on this branch with the dock closed: the sparkle button is the only difference; the page keeps its full width |
| `open-desktop.png` | 1280×800 | the dock open beside `/loops`: the page narrows, nothing is covered; *Look / Ask first / Act* with *Ask first* selected; the green dot and *Sharing this page: it asks before each action*; three suggestions; the composer's caption *Each message is one capped session: up to $2 (API-equivalent (estimate)), claude-sonnet-5-5* |
| `first-message-confirm-desktop.png` | 1280×800 | the first message of a conversation goes through the console's own gate: *This spends Claude budget*, naming the page attached and what the session can and cannot do, then the envelope (*This conversation can hold 20 messages. Each is one session capped at $2… You are asked once for the conversation, not again for each message*). The second and third messages of this conversation were sent without a dialog |
| `answer-points-desktop.png` | 1280×800 | the answer in the thread (Markdown, *2 steps*, `$0.0000 (API-equivalent (estimate))`, *3 turns*, *the session's log*), and on the page the ring and the note *here* that `page_highlight` drew around one loop card |
| `ask-approval-desktop.png` | 1280×800 | *Ask first*: the session asked to click **Run** on `/ops/config-show`. The button is ringed with *Click the button "Run"*, the dock shows *The assistant asks to — Click the button "Run"* with a countdown and **Deny** / **Allow**, the header button carries a dot, and Send has become **Stop** |
| `declined-desktop.png` | 1280×800 | after **Deny**: nothing was clicked, no job started, and the answer reports *did not click "Run": … declined: the person did not allow it* |
| `confirm-dialog-desktop.png` | 1280×800 | *Act* mode, a paired session filled the question on `/ops/assist` and clicked *Run — spends Claude budget*: the page stops at the *This spends Claude budget* dialog. What the session tried next is in the transcript below |
| `conversation-mobile.png` | 390×844 | the dock at phone width takes the page's width under the header; after a reload the conversation is still there, the mode has gone back from *Act* to *Ask first* |
| `no-cli-pairing-desktop.png` | 1280×800 | the console with no `claude` CLI: *This console cannot start a session itself*, the two ways forward (pair a session; run a console on the host, with the command and a copy button), and at the foot the pairing switch on, the code and *one use, 10 min* |

[`paired-session-transcript.txt`](paired-session-transcript.txt) is what a **paired** session saw, through the real MCP layer (`build_server(page=True, scopes="page")`, `page_attach` with the code the dock showed): it filled the question and clicked Run, the dialog opened, and then `page_click` on *Run it* inside it, `page_press` Enter, a `page_click` and a `page_fill` on the page behind it, and `page_navigate` were each refused with the reason; `page_press` Escape closed the dialog. The console's job list afterwards held no job for that question.

Also checked by hand, not pictured: in *Ask first*, **Allow** on a fill typed `contract` into the Operations filter and the list narrowed (React saw the input); in *Act* a click on a link navigated in-app and a click on **Run** for `config-show` started that $0 job and opened its drawer, which Escape closed; `page_data` listed the documents the page had loaded; the audit file held one line per command with the session named by an eight-character prefix; the prompt of the second message carried the first exchange under *THE CONVERSATION SO FAR*; the MCP config written for a docked message was mode `0600` and named only the `fleet` server with `HARNESS_MCP_SCOPES=page` and writes pinned off.

## Tests

- `python3 tools/console/test_page_bridge.py` — 22 tests: the allowlist, refs not selectors, in-app paths, the ceiling and the mode, the ask flag, liveness and timeouts, closing, caps, pairing, redaction, the audit line.
- `tools/console/test_console.py` — the `assist` op with a conversation and a page, the config, the session's steps, the bridge's routes, that every confirming yes in the page is a modal and the dock sends none, and the stand-in's ledger guard. This run also moved the file's `__main__` guard to the end: four tests defined after it (the refine and assist ones) had never run as a script, which is how CI runs it.
- `tools/console/test_mcp_layer.py` — 108 tests, nine new for the page tools.

## Not covered

Chromium only. No message was sent to the real model, so the quality of its answers and how well it follows the page rules in `assist.page.txt` are not shown here; what is shown is that the page enforces those rules whatever a session sends. The docked session was not run inside the console's container, which has no `claude` CLI. Light theme only; the dock uses the palette roles and no colour of its own. The stand-in wrote two rows to the real AI ledger during this pass before `DASH_AI_LEDGER` was set; both were removed, and the stand-in now refuses to run without a scratch ledger.

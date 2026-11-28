# The fleet assistant kit — evidence

> **Feature:** `HUB-NEW:fleet-assistant-baseline` (`features/features.d/fleet-assistant-baseline.yml`, [ADR 0014](../../../docs/adr/0014-fleet-assistant-baseline.md), [UPS-AST](../../../specs/ASSIST.md)) · **Kit:** [`templates/assistant/`](../../../templates/assistant/README.md) 0.1.0 · **Result:** PASS on the kit's fixture, by hand, on 2026-11-19. No fleet repo carries the payload yet, so there is no evidence from a real site.

What a person can do after this change: on a page of a site that carries the kit's payload, open a small Assistant panel, share that page with the Harness Console on the same machine, and pair a Claude Code session with it by a single-use code. The session then reads the page, learns which repo and source file it came from, points at things and, in the mode the person picks, navigates, clicks and types. What they are protected from: no session can answer a dialog, read or fill a secret field, follow a link off the site, or use the page at all in Look mode.

## How it was run

Nothing here spent Claude budget: the "session" is the console's real MCP layer driven by a script, which is what a paired Claude Code session calls.

- The page: `templates/assistant/tests/fixture.html`, served from another origin than the console (`python3 -m http.server 4777 --bind 127.0.0.1 --directory templates/assistant`).
- The console: this branch, credential-free, on `127.0.0.1:4011`, with the fixture's origin admitted (`DASH_CONSOLE_ASSIST_ORIGINS=http://127.0.0.1:4777`). The live console on `:4001` was not touched.
- The browser: Chromium through the Playwright MCP server, 1280×800 and 390×844.

## Now held by an automated run

Since bamr87/bamr87#938 the rules this hand run proved are also held by a script, on every pull request that touches the kit, the page bridge, the console's fleet routes or the MCP layer: `templates/assistant/tests/browser.test.mjs`, run by `tools/test-assist-browser.sh` locally ($0, no model, its own console on a free loopback port) and by `.github/workflows/assist-browser.yml` in CI. It drives this same fixture in headless Chromium through the console's real MCP layer, the way the run below did, and a self-test step proves it goes red when `dialog[open]` is dropped from `MODAL`.

| Rule | Automated run | Still by hand |
| --- | --- | --- |
| Look refuses every act (click, fill, Enter, navigate) | ✅ | |
| Ask first: Deny comes back declined, page unchanged; Allow runs | ✅ | the ringed control while the prompt waits (`ask-approval-desktop.png`) |
| Nothing inside or behind the native `<dialog>` or the Bootstrap-style `.modal.show` (click, fill, Enter, navigate); Escape closes it unanswered | ✅ | the screenshot (`dialog-refused-desktop.png`) |
| The secret field is neither read, filled nor shown in a snapshot | ✅ | |
| The link that leaves the site is refused | ✅ | |
| No `configure({ modal })` value (none, non-matching, broken) unprotects a dialog | ✅ | naming more dialogs as modal (`#form`) |
| After a navigation, by the session or by the person while a long poll waits, the same session carries on and the next command reaches the new page | ✅ | |
| The disabled control, `page_highlight`, `page_data`, a `//host` path, the commands-a-minute cap | | ✅ (`paired-session-transcript.txt`) |
| How the panel looks, desktop and 390×844 | | ✅ (`shared-desktop.png`, `panel-mobile.png`) |

## What to look at

| File | What it shows |
| --- | --- |
| `shared-desktop.png` | The panel on a page of plain HTML: sharing with the console, the three modes, a pairing code, the repo and source file in the footer. |
| `ask-approval-desktop.png` | Ask first: the session asked to click "Say hello". The control is ringed on the page and the panel waits for Allow or Deny. |
| `dialog-refused-desktop.png` | A confirm dialog the session opened by clicking "Delete everything". Its attempts on "Yes, delete", on Enter and on the form behind the dialog were refused: the status line under the form is still empty and the name field still reads "Ada". |
| `panel-mobile.png` | The panel at 390×844. |
| `paired-session-transcript.txt` | The whole Act-mode run through the real MCP layer, right after a page reload: attach (the page says which repo and source file it is), snapshot, highlight, fill, select, tick, save; then each refusal: the secret field (fill and read), the link that leaves the site, the disabled control, the native modal (click inside, Enter, click and fill behind, navigate), the Bootstrap-style modal (fill, click), a `//host` path; then a navigation to a second page, where the same session carries on. The last two steps hit the bridge's 40-commands-a-minute cap, which is the cap working. |
| `ask-first-transcript.txt` | The same session in Ask first: the first click was denied in the panel and came back as declined, the second was allowed and ran. |

## What this found

Running it for real turned up one loss the unit tests had not: after a page navigates, its last long poll is still waiting in the console with nobody behind it, and it took the next command, which then timed out. The broker now hands a command to a session's newest poll only (`test_only_the_newest_poll_of_a_session_is_handed_a_command`). The same loss was possible on the console's own page after a reload.

A review of the payload after the pull request opened found that `FleetAssist.configure({ modal })` replaced the built-in list of what counts as a modal dialog, so a site could have switched the dialog rule off with one call. It is additive now: a site can name more of its own dialogs as modal, never fewer. Checked in the browser against the fixture's confirm dialog with no setting, with a selector that matches nothing and with a broken selector: in all three the click inside the dialog and the fill behind it were refused and nothing was deleted; naming `#form` as a dialog made its fields the person's too.

Two snapshot faults were fixed on the way: a checkbox wrapped in its label was missing from the outline, and a select wrapped in its label was named with its own options.

## Not shown

- A real model. How well Claude follows the page's refusals on a fleet page is not shown here; the rules hold whatever a session sends.
- A real fleet site. The adapters were seeded into stand-ins of each stack (the fan-out's `seed_assist`), not mounted in a running Jekyll, Django, React, Next.js or MkDocs site.
- A deployed `https` page reaching the console, where a browser may ask the person first.

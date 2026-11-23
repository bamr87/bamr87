# The assistant, observed — evidence

> **Feature:** `HUB-NEW:assist-observability` (`features/features.d/assist-observability.yml`; serves FR92 and FR139) · **Issues:** bamr87/bamr87#940 (the shared pages view), and the registration and read-back gaps found on 2026-11-20 · **Result:** PASS, by hand, on 2026-11-20. The Claude Code session that drove the fleet page was a script calling the console's real MCP layer, so nothing here spent Claude budget.

What a person can do after this change: on the console's Assist page, see which pages of other fleet sites are sharing themselves right now and end one; see what the assistant did (each message's outcome and cost, each page command a session sent, by whom, to which page, in which mode, with what result); and see the assistant's registration in the agent inventory. The same document is read by an MCP tool, a terminal command and the lake.

## How it was run

- The console: this branch, credential-free, on `127.0.0.1:4011`. Its page audit and its AI ledger were scratch files (`DASH_CONSOLE_PAGE_AUDIT`, `DASH_AI_LEDGER`), seeded with real records: the eleven audit lines and the two `console assist` ledger rows that the validation console on `:4010` left on 2026-11-19 and 2026-11-20. So the two messages in the screenshots are real assistant messages (`claude-sonnet-5-5`, $0.17 and $0.15, API-equivalent (estimate)); everything dated 2026-11-20 14:19 and later is this run.
- The fleet page: `templates/assistant/tests/fixture.html` (kit 0.1.1), served from another origin (`python3 -m http.server 4777 --bind 127.0.0.1 --directory templates/assistant`), admitted with `DASH_CONSOLE_ASSIST_ORIGINS`.
- The paired session: `page_attach` with the panel's code, then page tools, through the real MCP layer in process.
- The browser: Chromium through the Playwright MCP server, 1280×900 and 390×844.
- The live console on `:4001` and the validation console on `:4010` were not touched.

## What to look at

| File | What it shows |
| --- | --- |
| `shared-desktop.png` | The Assist page, **Shared pages**: the fixture page listed with its repo and source file, its origin, the mode, that it is listening, one paired session, four commands and the eight characters the audit calls it, with **End**. Below it, **How it is observed**: two messages, 28 page commands, 7.1% of them met a no. |
| `activity-desktop.png` | **How it is observed**: the messages from the AI ledger and the page activity from the page bridge's audit, newest first: who asked (`paired`, `operator`), which page, what was done to which target, the mode, the outcome, how long it took. A fill is `fill e3 (3 chars)`: its length, never its text. |
| `ended-desktop.png` | After **End**: the list is empty and the console says the sharing ended. The audit has the line (`operator`, `end`). |
| `panel-ended-desktop.png` | The fixture page at that moment. Its panel reads "This page is not shared. Sharing was ended from the console. Share again to carry on." |
| `paired-session-ended-transcript.txt` | The paired session across the End: it reads and fills the page and is refused by the page's own rules (a control in a dialog, a secret field, a link off the site); then, after the operator's End, its next tool is refused with "the operator ended this page's sharing from the console", and the one after says no page is attached. |
| `inventory-desktop.png` | **In the agent inventory**: `local:console-assist`, its model, cap, switch, where its run records land, its KPIs, the sources it reads and its two contract gaps. |
| `shared-mobile.png` | The same page at 390×844. The table scrolls inside its own frame; the page does not scroll sideways. |
| `public-desktop.png`, `public-mobile.png` | The published build of `/assist` (`verify/scenarios/assist-dock.yml`, which passed at both sizes): no shared page, no End, no activity, and the inventory entry, which is committed data. |
| `terminal-activity.txt` | `tools/dash apps assist activity --days 0` over the same two files, with no console running. |

## What else was checked, and how

- **The lake.** `tools/dash-gen lake --lake <a copy of the live lake> assist --days 0` read the eleven validation-console audit lines and the two ledger rows in; a second run read nothing new. Both messages had a transcript in the lake, and the report found two Claude Code sessions whose transcripts show a page tool call: one docked (in the ledger) and one paired (not in it, priced from its transcript). The copy was a scratch file; the live lake was not opened for writing.
- **The real records exist.** The two `console assist` ledger rows each have a transcript under `~/.claude/projects/` (entrypoint `sdk-cli`) and a row in the lake's `sessions` table, so "a message is a ledger row, a transcript and a lake session" is observed, not assumed.
- **Tests.** `tools/console/test_page_bridge.py` (41), `tools/test_fleetcore_assistlog.py` (14), the three route tests in `tools/console/test_console.py`, `tools/console/test_mcp_layer.py` (110), `.github/scripts/dash-gen/test_fleet_lake.py`, `test_ai_run.py` (35) and `test_agent_inventory.py`.

## What this found

- **Real assistant messages had been sent.** The AI ledger held two `console assist` rows from the validation console. An earlier statement in this work that no real message had been sent was wrong; the rows, their transcripts and their lake sessions are what the checks above rest on.
- **The page's own refusals read as faults.** A click the page refuses because it is inside a dialog comes back as outcome `page`. The first cut of the page showed those in red and left them out of "met a no". They are the rules working, so `page` is counted and shown with the other noes.
- **A test run hung on standard input.** `test_ai_run.py`, started from a shell whose standard input never closes, waited on its stub CLI forever, because a session with no prompt inherits standard input. It passes with `< /dev/null`. Nothing was changed for this: it is how the runner treats a pipe.

## Not shown

- **The telemetry label arriving.** `ai-run` now sets `OTEL_RESOURCE_ATTRIBUTES` (`fleet.source=console-assist`, …) on the session it starts, and a test shows the stub CLI receives it. Whether Claude Code exports it for a headless session, and whether it lands in the log plane and Prometheus, needs one real message with telemetry on.
- **The shipped audit line in the log plane.** The console prints each audit line on stderr (the test console's log has them); no log plane was running to receive it.
- **The daily lake step.** `tools/install-harness-review.sh` has the new `lake assist` step, but the LaunchAgent on this Mac runs the job it was installed with until the installer is run again.
- **A real fleet site.** As for the kit itself: the page was the kit's fixture.

# The Overview tells the fleet's story — evidence

> **Feature:** `HUB-NEW:overview-story` (`features/features.d/overview-story.yml`) · **Scenario:** [`verify/scenarios/overview-story.yml`](../../../verify/scenarios/overview-story.yml), **PASS** on the public build at two viewports (`report.json`) · **Console pass:** **PASS** by hand on a credential-free console started from this branch · **Not verified:** a lever that needs a GitHub token (the kit upgrade dry run), and the page on a shallow clone, where the trends have one point and the footnote says so · 2026-11-19.

What a person gets after this change: the front door answers four questions before any scrolling (how healthy the fleet is, which way each budget is moving against its ceiling, what waits on the maintainer, how current the inputs are), every count carries its direction or its cap instead of standing alone, the attention queue groups the findings one lever clears, and every signal sits on one freshness timeline. Nothing on the page writes anywhere by itself; the lever buttons start the same operations they did.

## The public build (the runner)

`node verify/runner.mjs --base http://127.0.0.1:4031 --only overview-story` against `CONSOLE_BASE=/ tools/console/build-pages.sh`, desktop 1280×800 and mobile 390×844. The published page has no console behind it, so the *Waiting on you* cell says the decision index is read on a console. The scenario also asserts that the strip starts above the fold, that the heat strip has 168 cells (7 weekdays × 24 UTC hours), that the queue is grouped by lever and becomes one table under *Flat*, that at least one stamped source sits on the timeline, and that nothing scrolls sideways.

| Image | Viewport | What to look at |
| --- | --- | --- |
| `desktop-overview-top.png` | 1280×800 | the status strip: *Fleet health* 19 of 46 repos green with the red/amber/green bar; *Attention* **20+**, "the list stops there" (the generator keeps the strongest 20), the severity bar, "7 levers · the biggest clears 6 · at the cap for 8 days" (from the registry file's git history); *Budgets* both projected months against their ceilings, Claude **−30.4% WoW · better**, Actions **+37.3% WoW · worse**; *Waiting on you* says it is read on a console; *Signals* 120d oldest input (engagements). Below: the Nodes line and the two budget cards with their meters, week-over-week turns and fifteen-day sparklines |
| `desktop-overview-full.png` | 1280×800, full page | the whole story in order: budgets, the harnesses against the standard (13 of 122 conformant as a bar, the most-missed controls as ranked bars, scheduled 20.0 against observed 93.9 AI runs a day with the cap of 30 as a tick), flow (the issue-pipeline funnel intake → ready → in-pr → blocked → done, pull requests ready against draft), health (each scorecard metric as a bullet against its threshold with the better-is arrow, the trip wires with the one tripped on top), the weekday × UTC-hour heat strip with **Mon 06** ringed, the attention queue grouped by lever (two critical budget breaches under *Budget settings*, two failing harnesses under *Build fix queue*, six under one *Upgrade seeds (dry run)*, the rebuild-plan findings under one group), and the freshness timeline with engagements far right at 120 days |
| `mobile-overview-top.png` | 390×844 | the strip stacks one cell per row, nothing truncates, the pills wrap under their titles |
| `mobile-overview-full.png` | 390×844, full page | the same story at phone width; the heat strip's 24 columns fit; the timeline's axis spans the row above the lanes; no horizontal scroll |

## A running console (the interactive pass)

A console was started from this branch on loopback with no credentials (`GH_TOKEN`, `FLEET_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` unset, `DASH_CONSOLE_GITHUB_WRITES=off`), its own job directory, state directory and `DASH_AI_LEDGER`, and `DASH_DECISIONS_INDEX` pointing at a copy of the operator's decision index so that no read of GitHub was made. The live console on `:4001` was not touched. Driven with the Playwright MCP.

| Image | Viewport | What to look at |
| --- | --- | --- |
| `console-overview-top.png` | 1280×800 | the same strip on a console: *Waiting on you* reads **29** decisions from the index (needs Amr 17 · awaiting ratification 1 · Dependabot 3 · ready to merge 9), says the index was read 20.1 h ago with two caveats, and its pill says *stale*; the Nodes line now probes (mac up, forge off, placement drift 0) |
| `console-lever-job-pill.png` | 1280×800 | after a click on **Build fix queue** in its lever group: the row carries a **succeeded** pill above the button, linked to the job (`tools/dash-gen remediate`, an offline read of the committed triage); it read *running* with a spinner while the job ran, and the job drawer that opened was closed for the picture. The other row of the group, and the other groups, are unchanged |

Also checked by hand, not pictured: `/api/state` on that console carries `history.source: git` with 41 committed days of the registry, the newest point being 2026-11-18 (attention 20, 13 of 122 conformant, projected $287.18 / 57,846 min); the conformant-harness sparkline in *Against the standard* draws from it; *Flat* returns the queue to one sortable table whose rows open their project; a click on a page lever (*Budget settings*, *Open schedules*, *Open the rebuild plan*) navigates in-app.

Not verified here: a lever that needs a GitHub token (*Upgrade seeds (dry run)* runs the fan-out's dry run, which reads GitHub), and the published page from a shallow clone, where `registry_history` yields a single point and the footnote reads "1 day(s) of it here".

# PRD — Agentic loops dashboard

> **Status: Draft / proposed.** One dashboard of every live and routine agentic loop, and the product BASH Consulting shows first: the end-to-end test of this build-out, including its reporting and marketing; the first example of harnessing and visualizing the power of AI; the way an operator puts their arms around agents and frameworks that are available, powerful and omnipresent; the first and foundational application Bash 365 is based on and evolves from; and the installation wizard and the creation of all the wizards, also known as the AI agents. The brand line is "A born-again solutions hero." Design only. This pull request implements nothing. Accepted when the maintainer merges it.
> Features: `HUB-NEW` slugs `agentic-loops-dashboard`, `agentic-loops-activity` and `agentic-loops-foundation` in [`features/features.d/`](../../features/features.d/). Numbers are assigned at merge ([amendment 0002](../amendments/0002-conflict-free-numbering.md)).
> Requirements: `FR-NEW:agentic-loops-board`, `FR-NEW:agentic-loops-populations`, `FR-NEW:agentic-loops-flight`, `FR-NEW:agentic-loops-history`, `FR-NEW:agentic-loops-statistics`, `FR-NEW:bash-consulting-showcase`, `FR-NEW:harness-ai-visualize`, `FR-NEW:bash-365-foundation`, `FR-NEW:agent-wizard-installation`, `NFR-NEW:agentic-loops-complement`, `NFR-NEW:agentic-loops-redaction`, `NFR-NEW:agentic-loops-degraded`, declared on those fragments and numbered at merge.
> Roadmap: `FF-NEW:agentic-loops-dashboard` in [`_data/roadmap.d/agentic-loops-dashboard.yml`](../../_data/roadmap.d/agentic-loops-dashboard.yml).
> Governing rules: [`docs/constitution.md`](../constitution.md) § 10, § 10.8, § 11, § 13, § 26 and § 28. No constitution section is opened here. A later write that creates an agent is named as the follow-up amendment `agent-wizard-creation` and is not written in this pull request.

## 1. Problem

Agents and harnesses work across the fleet in two shapes. Routine loops run on a schedule: Grok bot routines, JEV and fleet loops, console jobs, and scheduled workflows. Live sessions start when someone or something asks: Claude Code, cloud agents, and console executions. Their status, progress, history and activity sit on separate console pages, ledgers and designs. An operator cannot open one place and see who is working, on which repo, whether the work is in flight or completed, and what the counts say.

Amr asked for that place on 10 November 2026. He also set what the place is for. It is the showcase for BASH Consulting, and the first real test of this build-out from end to end, including the reporting and the marketing behind it. It is the first example of harnessing the power of AI and of visualizing that power. AI capabilities are available, powerful and omnipresent, and this is an approach and an example of a way to put your arms around these agents and frameworks and visualize them. It is the first and foundational application that Bash 365 will be based on and will evolve from. It is the installation wizard and the creation of all the wizards, also known as the AI agents. The BASH Consulting line he added to the brand, the voice and the identity is "A born-again solutions hero."

The audience is Amr and the fleet operators. A journalist workflow belongs to the agent news feed, which is a different product.

## 2. Goals and non-goals

**Goals**

- One operations dashboard of every agent and harness, the repo it is on, and its current status.
- Both populations on that dashboard: routine and scheduled loops, and live and ad-hoc sessions, distinguished from each other.
- In-flight work distinguished from completed work, with progress, history and activity for each.
- Basic statistics from telemetry the fleet already keeps: counts, durations, success and failure, idle and stale, and cost where a figure already exists.
- Stale, failed and missing telemetry visible as those states, with secrets kept off the page.
- The same product carries the BASH Consulting showcase, the end-to-end report and the marketing, the visualization of AI, the Bash 365 foundation, and the installation wizard for the wizards (the AI agents).
- The BASH Consulting brand, voice and identity include the line "A born-again solutions hero." The line is how the showcase speaks. It does not replace the dashboard.

**Non-goals**

- Building the dashboard, a page, a collector, a workflow or a wizard in this pull request.
- A social feed of posts, comments and reactions. That product is [AGENT-NEWS-FEED.md](AGENT-NEWS-FEED.md) (pull request [#818](https://github.com/bamr87/bamr87/pull/818)).
- Replacing the Harness Console pages that already show sessions, health, cost and jobs, or copying their stores into a new database.
- Replacing the fleet activity log, the pipeline map, `/live`, the activity replay, the fleet graph or the Loops page.
- Agents publishing the report, the marketing, a chronicle entry or a news-feed post on their own.
- Creating, installing or configuring an agent, changing repository settings, secrets, branch protection or tags, or merging anything, in this pull request.
- Hand-assigning `HUB-NNN`, `FRn`, `NFRn` or `FF-NNNN`.

## 3. How this sits beside what the fleet already has

The dashboard is a view over these records. It links them. It does not become a second copy of them.

| Existing piece | What it already owns | What this dashboard asks of it |
| --- | --- | --- |
| Harness Console, `HUB-013`, [HARNESS-OPS.md](../HARNESS-OPS.md) | The local control plane at 127.0.0.1:4001 and the static site. | The dashboard is a console view. It does not add a second app. |
| `/loops` | The control-plane loops and their outputs. | A routine row links here. The Loops page stays the list of those loops. |
| `/schedules` | Crons, caps and collisions. | A scheduled row links its cron. The schedule board stays the editor of caps. |
| `/workflows`, [WORKFLOW-ATLAS.md](../WORKFLOW-ATLAS.md) | Hub workflows, the standards they are held to, and why runs fail. | A scheduled-workflow row links the workflow and its latest run. |
| `/jobs`, `HUB-064` | Console jobs, live logs, and the planned per-job state, age and slowness diagnostics. | An in-flight or completed console job links its job. Job control stays on `/jobs` under § 11. |
| `/live`, `HUB-030`, and `/activity` | Real-time sessions, live usage, jobs and spend, and the activity page of local sessions and CI agent runs. | A live row links the session. `/live` stays the five-second snapshot. |
| `/harnesses`, `/harnesses/health` | The harness inventory and the scorecard. | A harness row links its health. The scorecard stays the scorecard. |
| `/costs`, `HUB-032` | Claude spend and Actions minutes, with estimates labelled as estimates. | A cost on a row is copied from this ledger or from `/live` when the figure is already there. This dashboard does not price a run the ledger left unpriced. |
| Agent inventory, `HUB-092`, `_data/agents.yml` | Every registered CI agent, loop step, JEV tier and LaunchAgent, with owner, trigger, switch, cap and model. | Actor names come from this inventory. The dashboard does not keep a second roster. |
| Pipeline map, `HUB-025`, `HUB-026`, [HARNESS-PIPELINE-MAP.md](HARNESS-PIPELINE-MAP.md) | A diagram of named loops, bot handlers and workflow files, with running, idle, failed and unknown derived from the activity log and job status. | A row may link a map node. The map stays the illustration of that pipeline. |
| Fleet activity log, `HUB-024`, [FLEET-ACTIVITY-LOG.md](FLEET-ACTIVITY-LOG.md) | A proposed append-only record of bot decisions, including declines and retries. | When the log exists, history can cite a decision. Until it exists, history says the log is missing. |
| Fleet activity replay, `HUB-072`, [FLEET-ACTIVITY-REPLAY.md](FLEET-ACTIVITY-REPLAY.md) | A proposed animated timeline of agents, harnesses and containers. | A row may link a replay window once that view exists. This dashboard is the operations board, not the animation. |
| Fleet graph and outcome learning, `HUB-096`, `HUB-097`, `FF-0050` | What the control plane relates to, and what became of each loop's output, in shadow. | The dashboard may link a graph node or a learning row. It does not steer a loop and it does not replace the graph. |
| Agent news feed, [#818](https://github.com/bamr87/bamr87/pull/818) | Posts, comments and reactions on GitHub Discussions. | An operator may later point at this dashboard from a post they choose to write. The dashboard does not publish posts. |
| Quest Log showcase, `HUB-066`, [SHOWCASE.md](../SHOWCASE.md) | Articles and LinkedIn drafts for BASH Consulting, each a pull request a person merges. | The reporting and marketing in this epic follow that rule: a person reviews, a person publishes. |
| Issue #479 | A proposed live map of loops and harnesses. The replay PRD treats #479 as the structure layer. | This dashboard is the operations board of status, statistics and history. It links a map. It does not redraw one. |

## 4. User stories

Stories are for Amr and fleet operators. Work items stay on the Fleet project, new tools stay read-only until a person confirms a write, cost figures stay labelled, and nothing here runs on Amr's Mac (constitution § 10).

| Id | As a… | I want… | So that… | Requirement |
| --- | --- | --- | --- | --- |
| US1 | fleet operator (Amr) | one dashboard of every agent and harness, the repo it is on, and its current status | I can see the fleet's agentic work without opening each page myself | `FR-NEW:agentic-loops-board` |
| US2 | fleet operator | routine and scheduled loops distinguished from live and ad-hoc sessions | I can tell a cron, a JEV loop or a Grok routine from a Claude Code session, a cloud agent or a console execution | `FR-NEW:agentic-loops-populations` |
| US3 | fleet operator | in-flight work distinguished from completed work | I can see what is still running and what has finished | `FR-NEW:agentic-loops-flight` |
| US4 | fleet operator | the progress, the history and the activity of one loop | I can follow what it did, not only its latest status | `FR-NEW:agentic-loops-history` |
| US5 | fleet operator | counts, durations, success and failure, idle and stale, and a cost figure only when telemetry already has one | I can judge the loops from numbers the fleet already keeps | `FR-NEW:agentic-loops-statistics` |
| US6 | fleet operator | a stale, failed, idle or missing-telemetry loop to show that state | a quiet or absent source is not presented as a healthy loop | `NFR-NEW:agentic-loops-degraded` |
| US7 | fleet operator | secrets, tokens and private-repo bodies kept off the dashboard, and an estimated cost labelled API-equivalent (estimate) | the page is safe to read, including a public snapshot | `NFR-NEW:agentic-loops-redaction` |
| US8 | fleet operator | a row to open the console page, job, session, workflow run or report that already holds the detail | this board organizes those records and leaves them where they are | `NFR-NEW:agentic-loops-complement` |
| US9 | Amr, for BASH Consulting | this dashboard to be the showcase and the first end-to-end test of the build-out, including the report and the marketing, spoken as "A born-again solutions hero" | the company can show the work in its own voice, and a person reviews anything that is published | `FR-NEW:bash-consulting-showcase` |
| US10 | Amr | this to be the first example of harnessing the power of AI and of visualizing that power | I can put my arms around agents and frameworks that are available, powerful and omnipresent, and see them | `FR-NEW:harness-ai-visualize` |
| US11 | a Bash 365 builder | this application to be the first foundation Bash 365 is based on and evolves from | later Bash 365 work starts from this product | `FR-NEW:bash-365-foundation` |
| US12 | fleet operator | this to be the installation wizard and the creation of the wizards, the AI agents | installing and seeing the agents starts in one place | `FR-NEW:agent-wizard-installation` |

## 5. The board — `FR-NEW:agentic-loops-board`

The board is one view. Each row is one agent or harness at work, or one that has finished, on one repo when the work is about a repo.

| Field | Meaning |
| --- | --- |
| Actor | An id from `_data/agents.yml`, or the name of a live session the console already records. An actor the inventory does not know is shown as unknown, not given a new id. |
| Repo | `owner/name` when the work names one repository. Fleet-wide work says so. |
| Status | `working`, `idle`, `stale`, `failed`, `completed` or `unknown`. |
| Links | One or more links to the console page, job, session, workflow run, issue or pull request that already holds the detail. |

The row is a view assembled at read time. It is not a new system of record. GitHub, the console's job store, the ledgers and the inventories remain the records.

## 6. The two populations — `FR-NEW:agentic-loops-populations`

Every row carries `kind: routine` or `kind: live`, and a source name.

| Kind | Source name | What it covers | Where a row reads from today |
| --- | --- | --- | --- |
| routine | `grok-routine` | Scheduled Grok bot routines | The agent inventory, the loop switches and the workflow runs that already record that routine. A routine with no run record is listed and marked telemetry-missing. |
| routine | `jev-loop` | JEV loop steps, including conflict tiers | JEV step specs and the loop runner's run records. |
| routine | `fleet-loop` | The hub's scheduled fleet loops (pulse, issue pipeline, scout, PM, fan-out, token rotation, and the loops on `/loops`) | `/loops`, `/schedules` and the workflow atlas. |
| routine | `console-job` | A console job run on a schedule or as a repeated operation | `/jobs`. |
| routine | `scheduled-workflow` | A GitHub workflow with a `schedule:` | `/workflows` and the workflow's latest run. |
| live | `claude-code` | A Claude Code session, local or headless | `/live` and `/activity`. |
| live | `cloud-agent` | A cloud agent session | Shown when an existing fleet source already records it. Until a source exists, the population is on the board and marked telemetry-missing. |
| live | `console-execution` | A console job or execution someone started | `/jobs` and `/ops`. |

A source the table does not name does not get a row invented for it. Adding a source is a later change to this table, in the implementation that first has the telemetry.

## 7. In flight and completed — `FR-NEW:agentic-loops-flight`

Each row is `in-flight` or `completed`.

- In flight: a session, job or run that has started and has not finished, including `working`, `idle` while still the current run, `stale` and `unknown` while the run is expected to still be open.
- Completed: a run that has finished, with `completed` or `failed`, and a duration when the source recorded start and finish.

The board can show one population, the other, or both. Completed rows remain reachable as history. They do not disappear when the next run starts. How long completed rows stay on the default view is an open question in § 18. The requirement is that completed work is still visible.

## 8. Progress, history, activity and statistics

**Progress, history and activity — `FR-NEW:agentic-loops-history`**

Opening a row shows the progress the source already has, the recent activity (runs, sessions, jobs) and the history of earlier completed runs for that actor. History cites the underlying record by link. It does not transcribe a transcript, a log body or a private repository into the dashboard.

Where the activity log or the replay does not exist yet, the row says that history source is missing and still shows whatever `/jobs`, `/live`, `/activity` and the workflow run already provide.

**Statistics — `FR-NEW:agentic-loops-statistics`**

The board shows counts of rows by kind, source, status and flight; durations where start and finish exist; success and failure among completed rows; and idle and stale counts. A cost figure appears on a row only when `/costs`, the AI usage ledger or `/live` already has one for that run. A run with no figure shows no cost. The dashboard does not estimate one.

## 9. Complement, redaction and failure — the non-functional requirements

**Complement — `NFR-NEW:agentic-loops-complement`**

The dashboard reads and links the pieces in § 3. It does not replace their pages, their stores or their write paths. Turning the dashboard off leaves `/loops`, `/live`, `/jobs`, `/costs`, `/workflows` and the inventories working. The agent news feed stays the conversation. This board stays the operations view.

**Redaction — `NFR-NEW:agentic-loops-redaction`**

A row, a history line and a public snapshot contain no token, secret, credential or private-repository body. The same redaction the activity log and the PM review already use applies before anything is rendered. A cost that is an estimate is labelled API-equivalent (estimate), as constitution § 10.7 requires. The public Pages build uses a redacted sample or aggregate counts, never a live session body.

**Degraded states — `NFR-NEW:agentic-loops-degraded`**

`stale`, `failed`, `idle` and `unknown` are visible. Missing telemetry is a visible gap on that row or that population, with the source named. The board does not fill a gap with a guessed status, a guessed duration or a guessed cost. A source that is down is announced. The rows that can still be read from other sources still render.

## 10. BASH Consulting showcase — `FR-NEW:bash-consulting-showcase`

This product is the showcase for BASH Consulting. It is the first real test of this build-out from end to end. The test includes the dashboard itself and the reporting and the marketing behind it. Those three are requirements of this epic. They are not a second product and they are not a later campaign bolted on.

The end-to-end test, when the implementation exists, is an operator walking the board: live and routine loops, status, a completed run's history, the statistics, a stale or missing source shown as such, and a link that opens the underlying record. The report is that walk, written down. The marketing is the BASH Consulting telling of the same walk: harnessing AI, and showing it.

Reporting and marketing are drafts a person reviews. The precedent is the Quest Log showcase ([SHOWCASE.md](../SHOWCASE.md)): a pull request a person merges, on the personal side and on the BASH Consulting side. This epic does not add a publisher. An agent does not post the report to GitHub Discussions, to LinkedIn, to the daily chronicle (constitution § 23) or to lifehacker.dev. If a later design wants an agent to publish, that design names its amendment before any publisher is built. This PRD does not propose that publisher.

### Brand, voice and identity

Add to the BASH Consulting brand, voice and identity the idea behind Bash: "A born-again solutions hero."

The spelling is the point. The brand line uses born-again, the ordinary word, for the hero. The play is on Bash, the Bourne-again shell: Bash was named as a pun on born again and the Bourne shell, and Bourne-again is the shell's name, with Bourne spelled as in that name. Born-again and Bourne-again are not substitutes for each other. The line is the voice of the report and the marketing in this epic. The operational requirements in § 5–§ 9 stay the dashboard: agents, repos, status, statistics, progress, history, activity, in flight and completed. The line does not stand in for those requirements, and this pull request does not restyle bash-365.com.

## 11. Visualizing the power of AI — `FR-NEW:harness-ai-visualize`

This product is the first example of harnessing the power of AI and of visualizing that power. The whole idea is that AI capabilities are available, powerful and omnipresent. The dashboard is an approach, and an example, of a way to put your arms around these agents and frameworks and visualize them.

The visualization is the board in § 5–§ 8: the agents, the frameworks they run in, the repos, the status, the history and the statistics, in one picture an operator can scan. It is an operations picture. It is not a social timeline and it is not an animation of container events. Those remain the news feed and the replay.

## 12. The foundation of Bash 365 — `FR-NEW:bash-365-foundation`

This product is the first and foundational application that Bash 365 will be based on and will evolve from. Bash 365 is the company presence at bash-365.com (`bash-365/bash-365.com`). Later Bash 365 work starts from this application: the same picture of agents and loops, the same distinction of live and routine, in flight and completed, and the same rule that a missing source stays visible.

This pull request does not edit the bash-365.com submodule, and it does not move the Azure cost dashboard (`FF-0044`) or the cloud phone offering (`FF-0045`). Those stay their own epics. Adopting this application on the company site is a later change in that repository, after this PRD is accepted and the hub view exists.

## 13. The installation wizard and the wizards — `FR-NEW:agent-wizard-installation`

Think of this as the installation wizard and the creation of all the wizards, also known as the AI agents.

The dashboard is that wizard. It is where an operator installs the picture of the fleet's agents and frameworks and sees them as one set. The wizards are the AI agents: the registered agents in `_data/agents.yml`, the loops they run, and the live sessions. Creation, in this requirement, means that this product is the place those wizards are brought into one organized picture and, later, the place an operator starts from when a new wizard is added.

This pull request does not create an agent, write `_data/agents.yml`, install a LaunchAgent, change a workflow, or open a GitHub settings page. The first implementation of the wizard is read-only: it presents the agents and loops that already exist, including the ones whose telemetry is missing.

A later phase may let an operator start the creation of an agent from the wizard. Creating an agent is not a GitHub Projects edit under constitution § 11, and it is not a software change this direction pull request may make (constitution § 26). That write waits for the follow-up amendment named in § 19. Until Amr merges it, the wizard does not create agents.

## 14. Design for Failure

| Failure | Detection | Behaviour | Recovery | What is learned |
| --- | --- | --- | --- | --- |
| A loop is stale | The current run is older than its schedule, or a session has no heartbeat inside the window the source already uses | The row is `stale`, stays in flight, and links the run | The operator opens the underlying job, workflow or session. The dashboard does not retry it | Stale is a status, not an empty cell |
| A loop failed | The source's conclusion is failure, timed out or startup failure | The row is `failed` and completed, with the link | The operator opens the run. The dashboard does not rerun it | Failure stays visible after the next success starts, in history |
| Telemetry is missing | The population is in § 6 and no source returned a record | The row or the population is `unknown`, labelled telemetry-missing, and names the source that was absent | The implementation adds a read-only source later, or the operator accepts the gap | A gap is not filled with a healthy status |
| A source plane is down | The console, GitHub or a ledger read fails | A banner names the plane. Rows from other sources still render | Retry the read. The board does not cache a private body to paper over the outage | One plane down does not blank the board |
| A secret or a private body is in a payload | The shared redaction patterns match, or the repo is private | The field is dropped. The row can still show actor, status and a link | Rotate the secret if it was already exposed. The public snapshot never receives the raw payload | Redaction happens before render |
| An estimate is shown as metered spend | A figure whose source is an estimate | The label API-equivalent (estimate) is required. A figure with no source is omitted | Correct the label. Do not invent a price | § 10.7 |
| The public site would show a live session | The Pages build is about to embed `/live` or a job log | The snapshot is a redacted sample or counts only | Rebuild the snapshot. Live bodies stay on the local console | The retired Jekyll `/dashboard` redirect to `/projects` is unrelated. This product is a new view |
| Someone treats the board as a publisher | A path that posts the report, the marketing or a news-feed item | There is no such path in this product | A person publishes a reviewed draft, as [SHOWCASE.md](../SHOWCASE.md) already does | Agents do not auto-publish |
| The wizard is asked to create an agent | A control that would write an agent, a workflow or a setting | The control is absent until § 19 is merged by Amr | File the amendment. Claude Code implements the write only after that merge, under § 26 | Creation is specified as purpose and gated as a write |
| The board is read as the news feed or as the replay | A request to comment, react or animate from this page | The board links those products and does not host them | Open [#818](https://github.com/bamr87/bamr87/pull/818) or `HUB-072` | US8 is the check |
| Claude Code is unavailable for the implementation | The handoff issue sits with no executor | The work stops. This PRD stays the spec | Amr decides the path under § 26 and § 28. A Grok bot does not build the dashboard | Direction ends at this document |

Risk tier (constitution § 13): reading the board is low. The board has no write in the phases this PRD makes available. A later creation write is external and stays off until the follow-up amendment is merged. Nothing in this design runs on Amr's Mac (constitution § 10.5).

## 15. Prior art and build-vs-adopt

Needs assessment (constitution § 10.8): Amr wants one operations picture of every live and routine agentic loop, with status, statistics, progress, history and activity, in flight and completed, and he wants that picture to be the BASH Consulting showcase, the visualization of AI, the foundation of Bash 365, and the installation wizard for the agents. The brand line for that showcase is "A born-again solutions hero." The fleet already stores most of the rows in separate console pages. It has no one board that holds both populations, and it has no product that states this purpose.

| Option | Fit |
| --- | --- |
| `/loops`, `/schedules`, `/workflows`, `/jobs`, `/live`, `/activity`, `/harnesses`, `/costs` | The right records for the populations they already cover. Wrong shape for one board. Link them. |
| Pipeline map, `HUB-025` | The right illustration of a fixed set of nodes. Wrong shape for live sessions, history and the company purpose. Link a node. |
| `/live`, `HUB-030` | The right five-second snapshot of sessions and spend. It forgets history. Link the session. |
| Fleet activity replay, `HUB-072` | The right animation of runtime order. Wrong shape for an operations board and a showcase. Link a window later. |
| Fleet graph, `FF-0050` | The right structural model and the shadow learning. Wrong shape for the operator's status board. Link a node. |
| Agent news feed, [#818](https://github.com/bamr87/bamr87/pull/818) | The right conversation. Wrong product for status and statistics. Leave it as the feed. |
| Quest Log showcase, `HUB-066` | The right rule for marketing: a person merges the draft. Adopt the rule. The subject of this epic's report is this dashboard. |
| A new store of runs | A second ledger beside jobs, workflows and `/costs`. Do not build. |
| A new agent roster | A second list beside `_data/agents.yml`. Do not build. |
| An agent publisher for the report | A write the constitution does not grant, and a social product this epic is not. Do not build. |
| bash-365.com Azure cost dashboard, `FF-0044` | A cost page for one Azure subscription. A different dashboard. Leave it. |

Decision (proposed): build, later, a read-only console view that composes the existing pages and ledgers into the rows in § 5–§ 8, with degraded states when a source is missing. Adopt the agent inventory as the actor list. Adopt the showcase rule that a person publishes. Adopt none of the existing pages as a replacement for this board, and do not let this board replace them. The wizard's first build presents existing agents. It does not create one.

## 16. Phases

P0 is this pull request. Later phases are implementation. Constitution § 26 sends that work to Claude Code after Amr accepts this PRD, as sub-issues of one epic on project #14 (constitution § 10.2). This pull request does not file them. The agent's GitHub CLI is read-only, so no issue is opened here.

| Phase | What lands | Acceptance |
| --- | --- | --- |
| P0, this pull request | This sub-PRD, three feature fragments, one roadmap fragment | `number plan` is clean. Schema, governance and numbering checks pass. No page, workflow, setting, secret or catalog number is written. No amendment is opened. |
| P1, the board | A read-only console view of the rows in § 5–§ 7, linking the existing pages | An operator sees routine and live rows, in flight and completed, and opens the underlying record. A missing cloud-agent source shows as telemetry-missing. No new store. |
| P2, history and statistics | Progress, history, activity and the statistics in § 8, from telemetry that already exists | Counts, durations, success and failure, idle and stale match the sources. Cost appears only when a source already has a figure, labelled when it is an estimate. |
| P3, failure states | The Design-for-Failure behaviour in § 14 for stale, failed, missing and down | A stale loop is `stale`. A down source banners and does not blank other rows. Nothing is retried from the board. |
| P4, showcase | The end-to-end report and the BASH Consulting marketing drafts, in the voice "A born-again solutions hero" | The drafts describe this dashboard and use that line, born-again in the line, Bourne-again only for the shell. Each is a pull request a person merges. No agent publishes. |
| P5, Bash 365 | A spoke adoption, in bash-365.com, after the hub view exists | That change is its own pull request in that repository. This epic stays the foundation it adopts. |
| P6, the wizard | The read-only installation picture of the agents that already exist | The operator sees the wizards, which are the AI agents, from `_data/agents.yml` and the rows. No agent is created. |

P0 does not start P1. P1 waits until this PRD is merged, so the requirement ids exist. P6 does not include a create button. A create path is § 19, then a Claude Code implementation, in that order.

Verification of P0 is `skip-evidence`: the change is a document and catalog fragments, with no behaviour a user can exercise ([VERIFICATION.md](../VERIFICATION.md)). P1 is the first phase with a page. That phase records a console scenario and an evidence bundle, and adds the route to `snapshot.STATIC_ROUTES` in the same implementation pull request.

## 17. Cost

| Tier | What | Cost |
| --- | --- | --- |
| 0 | Reading existing console documents, ledgers and inventories | No model. Local reads. |
| 1, optional, later | A capped draft of the P4 report from rows the operator already selected | API-equivalent (estimate), inside `_data/fleet.yml` `budget:`, off unless a person runs it. The person still publishes. |

No scheduled agent is added to refresh a private copy of the board or to post the showcase. The board reads the sources when the operator opens it.

## 18. Open questions

- The route name. Proposed: the implementation pull request chooses one new console route and registers it in `snapshot.STATIC_ROUTES`. This PRD does not reserve the path, so it does not collide with the retired Jekyll `/dashboard` redirect, which serves `/projects`.
- How long completed rows stay on the default view. Proposed: the default view shows in-flight plus a recent completed window, and history holds the rest, bounded the way other console lists are bounded.
- Whether cloud-agent rows are empty-by-design in P1. Proposed: yes. The population is named, and it reads `unknown` until a fleet source records those sessions.
- Whether the public snapshot shows counts only or a redacted sample. Proposed: counts, plus a sample that has already been redacted. Never a live log.
- Who may file the P4 drafts. Proposed: Claude Code opens the draft pull requests, and Amr merges them, which is the showcase rule already in [SHOWCASE.md](../SHOWCASE.md).

## 19. Follow-up amendment (not written, not ratified)

This PRD names one constitution change and does not make it. A change to the constitution is an amendment, proposed with `**Number:** NEW` and ratified only when the maintainer merges it. The dashboard specified for implementation in § 16 does not need that amendment, because it is read-only and it does not publish.

Proposed slug, for a later pull request, and only if an operator should create an agent from the wizard: `agent-wizard-creation`.

It would say who may create a wizard (an AI agent), through which confirm path, with no settings changes, no secrets in the repo, and no merge. `Affects` would name § 11, § 26, § 28, § 29, `FR-NEW:agent-wizard-installation` and `HUB-NEW:agentic-loops-foundation`. Until that pull request is merged by Amr, the wizard does not create agents.

No amendment is proposed for publishing. This PRD does not ask agents to publish.

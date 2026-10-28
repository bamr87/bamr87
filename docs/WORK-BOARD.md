# The Work board

> Every open issue, pull request, roadmap spec, spec package and backlog item in one place, in the order the loops will take it, with drag and drop to reorder, move and reprioritise that work and a file the loops read back.

The fleet's work lives in five places, each with its own state machine: issues in GitHub labels, pull requests in the PR itself, roadmap specs in `_data/roadmap.yml`, spec packages in each spec-driven repo's `specs/NNN-slug/spec.md`, and follow-ups in that repo's `BACKLOG.md`. Each loop ranks what it can see by a formula: the [issue pipeline](ISSUE-PIPELINE.md) by a priority score, readiness and age, and [`/spec-driven:evolve`](SPEC-DRIVEN.md) by severity, kind and id. The Work board puts all five on one page, shows which items the next run of each loop will take, and lets a person overrule the formula where it is wrong. It writes that judgement to `_data/work_queue.yml`, which the loops read.

| | |
| --- | --- |
| **Page** | Harness Console → Harnesses → **Work board** (`/work`); read-only on the [public site](CONSOLE-PAGES.md) |
| **Builder** | [`.github/scripts/dash-gen/work_board.py`](../.github/scripts/dash-gen/work_board.py) |
| **The human's order** | [`_data/work_queue.yml`](../_data/work_queue.yml), via [`work_queue.py`](../.github/scripts/dash-gen/work_queue.py) |
| **Read by** | the issue pipeline (queue order and priority), repo-evolution (each weekly brief), the `fleet_work` MCP tool |
| **API** | `GET /api/work` · `POST /api/work/preview` · `POST /api/work/apply` · `GET /api/work/item` · `GET /api/github/repos/{o}/{r}/pulls/{n}/specs` |
| **Tests** | `python3 .github/scripts/dash-gen/test_work_board.py` · `python3 tools/console/test_console.py` · `python3 tools/test_fleetcore_mcp.py` |

## The lanes

Every item sits on one of six lanes, mapped from its own state:

| Lane | Issue (labels) | PR | Roadmap spec | Spec package | BACKLOG.md item | Drained by |
| --- | --- | --- | --- | --- | --- | --- |
| **Triage** | no `agent:` stage label | — | `proposed` | `draft` | `## Open` | T1 intake; you (approval, `/clarify`) |
| **Ready** | `agent:ready` | — | `approved`, `backlog` | `clarified`, `planned` | — | T2 implement; `/evolve` |
| **In flight** | open PR or `agent:in-pr` | draft | `in-progress` | `in-progress` | `## Claimed` | T3 complete; the spec chain |
| **Review** | — | open | — | — | — | you |
| **Blocked** | `agent:blocked` | — | — | — | — | you |
| **On hold** | `agent:hold` | — | — | — | — | nobody |

Shipped and declined roadmap specs, shipped and superseded spec packages, `## Done` backlog items and closed issues leave the board. Spec packages and `BACKLOG.md` items are read from submodule checkouts, so only a running console shows them. The published page says so instead of showing an empty lane.

## What a drag does

Every change is **staged** first. The board sends the plan to `/api/work/preview` and draws the result, so the lanes, the next-run cut lines and the throughput numbers all show the plan before anything is written. **Apply** writes it after one confirmation; **Undo** steps back one change.

| Gesture | On | Becomes |
| --- | --- | --- |
| Drag within a lane | any item | a **pin**: the item and every card above it go into `order:` in `work_queue.yml`, so pinned items come first in that lane, in that order, ahead of anything the formula ranks |
| Drag to the empty end of a lane | an issue or a roadmap spec | a lane move only, with no pin |
| Drag across lanes | an issue | `agent:` label changes on GitHub (e.g. Blocked → Ready is `+agent:ready −agent:blocked`), through the console's GitHub write path: confirm-gated, limited to fleet repos the hub owns, recorded in the action log |
| Drag across lanes | a roadmap spec | its `status:` line in `_data/roadmap.yml` |
| Drag across the priority columns | a roadmap spec | its `priority:` line in `_data/roadmap.yml` |
| Drag across the priority columns | anything else | a `priority:` override in `work_queue.yml` |
| Drawer → Note | any item | a `notes:` entry: shown on the board and in the evolution brief, never read by a loop |

A PR, a spec package and a `BACKLOG.md` item cannot change lane on the board. Their state belongs to the PR, to `spec.md` (the spec chain moves it) and to the append-only `BACKLOG.md`. The server refuses such a plan and names the reason. They can still be pinned and reprioritised. The same moves work without a mouse: focus a card, then `Alt+↑/↓` to reorder, `Alt+←/→` to move a lane (or a priority step on the Priorities tab), or use the card's `⋯` menu, which is also the touch path.

Files are written to the **working tree, never committed**. The apply result shows the `git diff`; committing it is the approval of record, as with every other console write. Label changes are immediate, because labels are the issue pipeline's state. Until the next issue-pipeline snapshot catches up, the board keeps a moved issue in its new lane, marked *moved*.

## How the loops read it

- **Issue pipeline** ([`issue_pipeline.py`](../.github/scripts/dash-gen/issue_pipeline.py)). A pinned issue's `rank` goes first in `queue_sort_key`, ahead of priority, readiness and age, so a pin takes a slot in the next run (still within the per-repo and cross-repo sub-caps). A `priority:` override replaces the computed priority; T1's work order says a human set it, and T1 applies that label. Pinned pipeline PRs go first at T3. The snapshot now carries every open issue (`backlog:`) and every pipeline PR, not only the capped queues, so the board can show what waits behind the cut.
- **Repo-evolution** ([`evolution.py`](../.github/scripts/dash-gen/evolution.py)). Each weekly brief gets a section, *The maintainer's order*, listing the repo's pins and overrides in order with their notes. It is an order of preference for a pass that has a choice; issues stay the pipeline's lane.
- **Agents.** The `fleet` MCP server's `fleet_work` tool returns the board in the loops' order, so an interactive session can read what to pick up next.
- **`/spec-driven:evolve`** runs inside a member repo and reads that repo's own `BACKLOG.md` with the kit's picker, which knows nothing of the hub. The board marks the item it will take next (*/evolve next*), and a pin shows where you disagree.

The board's next-run cut line is not an imitation of the pipeline. `work_board.py` builds the same per-repo records and calls `issue_pipeline.build_queues` itself, and `test_work_board.py` holds the two equal. While the committed snapshot predates the full `backlog:` list, issues outside the capped queues are read from `fleet_triage.yml` with label-only priorities. They only fill slots the scored issues leave, and the board says the cut line is approximate.

## Throughput

The **Throughput** tab answers "is the work balanced?" before you drag anything:

- **Loops**: each loop's schedule, its cap per run, how many items are eligible, what the next run takes, and the drain time (runs and days at today's caps, counting the per-repo and cross-repo sub-caps). Each card links to the caps in `_data/fleet.yml`.
- **By repository**: every repository's items per lane, and how many of the issue pipeline's next-run slots it gets.
- **Balance**: what the board sees, each with its lever. For example, one repository holds more intake issues than its per-repo cap can clear in a week, ready issues outside the hub compete for the cross-repo slots, the blocked lane has grown with no loop draining it, PRs sit idle, or pins point at items that have closed.

Pinning moves an item up a loop's queue; raising a cap moves the whole lane. The first is a board change, the second a [Config](../tools/console/README.md) edit.

## Drilling in

Click a card (or press Enter) to open its drawer:

- **Issue**: its stage, priority source (and the score behind it), readiness, autonomy verdict, and the gaps the pipeline found, each marked agent-closable or human-closable. With a console or a GitHub token, the issue's body is read live.
- **Pull request**: CI, draft and mergeable state, linked issues, and **the spec packages it changes, read at its head commit** with the spec-driven kit's own rules: status, task progress, unresolved `OQ-N`, requirements no task covers, the packages it only mentions, and the `BACKLOG.md` items it adds or moves. A removed backlog line is flagged, because the gate refuses one.
- **Roadmap spec**: the whole entry (problem, proposal, acceptance, scope, risks), plus a status select. Declining one needs a reason, written as `reason:`.
- **Spec package**: requirement counts, open questions with the `/clarify` lever, every task and its state, and `spec.md` itself.
- **Backlog item**: kind, severity, section, where it surfaced, and the spec that claimed it, one click away.

Every drawer carries the same levers as the board (lane, priority, pin, note), and they stage into the same plan.

## `_data/work_queue.yml`

```yaml
schema: work-queue/v1
updated_at: '2026-10-27'
order:                       # first in their lane, in this order
  - issue:bamr87/zer0-mistakes#566
  - backlog:law-ai/BL-20261018-03
priority:                    # replaces the computed priority (never a roadmap spec's)
  issue:bamr87/zer0-mistakes#565: P0
notes:                       # why — shown, never read by a loop
  issue:bamr87/zer0-mistakes#565: blocks the zer0-cms cutover
```

Keys are `issue:<owner>/<repo>#<n>`, `pr:<owner>/<repo>#<n>`, `roadmap:FF-NNNN`, `spec:<project>/<NNN-slug>` and `backlog:<project>/BL-YYYYMMDD-NN`. A hand edit is fine. A malformed entry costs that entry, never the run, and every reader reports what it dropped. Apply prunes keys whose items have closed, but only when the source was seen whole. The triage snapshot caps issues per repository, and a submodule that is not checked out has no specs; neither is evidence that an item closed.

## What it refuses to do

- Merge, close, push or commit anything. Its GitHub writes are the console's `issue.labels` action and nothing else.
- Move an item whose state another system owns (a PR, a spec's status, a `BACKLOG.md` section).
- Write a label without `confirm=true`, or to a repository the hub does not own.
- Publish a submodule checkout. The public snapshot's board has no spec or backlog items and no levers.

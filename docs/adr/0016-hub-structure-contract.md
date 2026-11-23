# ADR 0016 — The hub structure contract: declared layers and limits, a ledger that only shrinks, and one pass over the checks a change owes

- **Status**: proposed
- **Date**: 2026-11-22
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-22: review the repo's architecture, then address every issue the review found)
- **Related**: [ADR 0006](0006-django-management-backend.md) (the Django backend beside the console), [ADR 0010](0010-fleet-graph-and-outcome-learning.md) (the fleet graph, which models what the control plane manages; this models the code that manages it), [ADR 0011](0011-one-framework-many-instances.md) (the stack installs for any owner), constitution § 20 (the editor is a front door); [docs/ARCHITECTURE.md](../ARCHITECTURE.md); `HUB-NEW:architecture-contract`, `HUB-NEW:focus-checks`

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### What the review claimed and what the measurements said

A review of the hub on 2026-11-22 (at `113094cf`) named six structural risks. Each was measured before anything was changed. Three held as stated, one was real but much smaller than stated, and two did not hold.

| # | Claim | Measured | Verdict |
| --- | --- | --- | --- |
| 1 | The shared core is split three ways with no package boundary; 152 files patch `sys.path` | 111 of the 152 are test files, which run standalone by design. 41 non-test modules change `sys.path`, in 66 statements. The static import graph is close to a clean layering (generators, core, engines, surfaces) with 5 imports that go up a layer, each a lazy import inside one function | Real, smaller than stated |
| 2 | A few very large modules carry most of the weight | 15 source files are past 1,500 lines; `tools/console/core.py` was 4,299 and `tools/jev/loop.py` 3,254 | Held |
| 3 | `_data/fleet.yml` (3,500 lines, 37 sections) is a collision point | It is hot: 93 commits in 30 days, and 3 of the 8 open pull requests touch it. But git merges edits to separate sections cleanly and the conflict ledger (`_data/jev_resolutions.yml`) holds no row. The measurable cost is elsewhere: 43 places open the file and about ten modules carry their own loader | Did not hold as stated |
| 4 | Committed snapshots make git the database, at a cost | 141 of the last 500 commits are automation writing data, ids or pointers, which is by design. Every `_data` blob in history comes to 5.6 MiB of an 81 MiB pack; the weight is evidence screenshots and a few binaries | Did not hold |
| 5 | The console front end has no unit tests | 0 test files for about 19,000 lines of TypeScript; only `tsc` and the browser scenarios | Held |
| 6 | Each change has a wide footprint, learned one CI failure at a time | 3 of the 8 open pull requests touch `tools/dash`, 3 touch `AGENTS.md` and 2 touch `.vscode/launch.json`; every companion entry is enforced, each by a different gate | Held |

### The constraint that shapes the answer

The hub's code is install-free on purpose. A generator runs as `python3 .github/scripts/dash-gen/<name>.py` on a bare interpreter in CI, in a fleet repo that has the hub checked out at `.fleet-hub`, and three tools are vendored byte-identical across the fleet as single files. That is why modules put directories on `sys.path` themselves, and why nothing enforces which unit may import which. The review's first recommendation, one installable package, would trade that property away. What was missing is narrower: the layering the code already follows was never written down, so nothing stopped it eroding, and nothing stopped a 4,000-line file gaining its next section.

### How the fleet does the same things

The maintainer's guidance of the same day is that refactor work reads the submodules' patterns and aligns to them. For unit tests there is a pattern, and the hub follows it (decision 4). Eight fleet repos carry an `ARCHITECTURE.md`, seven of them at `docs/ARCHITECTURE.md`, which is where the hub's now sits. For the structure rules there is none: no fleet repo has an import-layer contract, a file-size limit or an architecture test, and the Universal Project Standard has no structure requirement. The hub's contract is therefore the first variant, and offering it to the fleet is a separate step that this ADR does not take.

### If nothing is decided

If nothing is decided, the handful of upward imports become fifty, the largest files keep growing because the next function always fits, and the front end stays the one part of the control plane with no fast test.

## Decision

1. **The structure is a contract, checked on every pull request.** [`_data/architecture.yml`](../../_data/architecture.yml) (`architecture/v1`) declares four rules and [`tools/architecture.py`](../../tools/architecture.py) measures the hub's own source against them: a code unit imports from its own layer or a lower one (`generators` < `core` < `engines` < `surfaces`); a non-test Python module does not change `sys.path`; a source file stays under 1,500 lines; a committed `_data` file stays under 512 KB. [`tools/test_architecture.py`](../../tools/test_architecture.py) runs the check against the live tree, so `python-tests.yml` gates it with no new workflow. The contract is its own file and not a section of `fleet.yml`: `fleet.yml` is the control plane's runtime settings, and this is the shape of the code that reads them.
2. **What the tree already carries is recorded, and the record only shrinks.** An upward import is listed in `layer_exceptions` with the file, the name and a `why` that says where the shared code belongs; the tool never adds one. An oversized or path-changing file is in the ledger with the number it is held to, recorded with 50 to 100 lines of headroom so that a small fix does not have to edit the ledger. `architecture.py ledger --write` lowers numbers and drops entries, adds one only with `--accept-new`, and never raises one: a raise is a hand edit a reviewer sees. A file that has dropped under the limit, or more than twice the headroom under its number, fails the check until the ledger is re-recorded, so a reduction cannot be spent later.
3. **The two largest modules are split now, without rewriting a function.** `tools/console/core.py` went from 4,299 to 1,922 lines, with five modules it loads and re-exports (`core_adapters.py`, `core_jobs.py`, `core_config.py`, `core_auth.py`, `core_refine.py`), and `tools/jev/loop.py` from 3,254 to 1,697, with seven (`loop_common.py`, `loop_budget.py`, `loop_runs.py`, `loop_host.py`, `loop_context.py`, `loop_publish.py`, `loop_canary.py`). No function body was rewritten. In `loop.py`, 161 of 164 top-level names are byte-identical and three reach a seam the tests replace through the engine module. In `core.py`, 198 of 276 are identical and 78 differ only in that a name `core.py` still owns is written `core.<name>`: the sibling modules import `core` and refuse to load before it. Every name importable from either module before is importable from it now, and no test's patch target changed. The `OPS` table stayed in `core.py` because `tools/fleetcore/graph.py` reads it from that file as text. Both moves were checked by comparing the syntax tree of every top-level statement with the original, and by running the 149 loop tests and every console test on an interpreter that has FastAPI.
4. **The front end gets a unit test runner.** Vitest runs 543 tests in 14 files beside the modules they test (`tools/console/web/src/**/*.test.ts`): base-path and backend selection, the static snapshot reader, the GitHub-direct client, links, formatting, ANSI rendering, navigation, the work-plan logic and the page bridge's rules. They take a few seconds and need no browser. The setup follows the fleet standard and the fleet's other apps: Vitest, tests beside the module, settings in `vitest.config.ts`, jsdom for the one file that needs a DOM (UPS-QA-12). `console-web.yml` runs them after the build, and `tools/run-all-tests.sh` runs them where the page's dependencies are installed. Writing them surfaced seven suspected defects in existing code; those are reported with the change and not fixed in it.
5. **One command names the checks a change owes.** [`tools/focus.py`](../../tools/focus.py) reads the change against `origin/main`, looks up [`_data/checks.yml`](../../_data/checks.yml) (`checks/v1`) and lists, or with `--run` runs, only the gates and tests whose paths the change touched, plus the test beside each changed module. It adds no rule. A check whose `needs:` is missing on the machine is reported as not run, never as passed. A new gate adds its entry to the registry in the same change.
6. **The rest is repaired in this order.** First the ledger, largest file first, each moved without rewriting and with the same proof: `fleet_lake.py`, `fleet-config.py`, `issue_pipeline.py`, `conformance.py`, `harness_registry.py`, then the rest. Second the layer exceptions: by moving the shared code down (the reader of the assistant's audit record below the lake, the review-gate rules and the decision index into the core, the PR queue's row logic and the JEV work-root helpers below their callers), and for the MCP compatibility entry point by retiring the fallback it serves. Third one loader for `_data/fleet.yml` in the lowest layer, replacing the private ones; only then is splitting that file into sections a small change.

## Consequences

**Positive**

- The layering is enforced without an install step, so every script still runs from a bare checkout.
- A large file cannot grow past its number and a new one cannot appear, while a change that adds a few lines to a listed file passes untouched.
- A reduction is permanent in the change that makes it.
- A missing companion entry is found locally in one pass. On this change `focus.py` named 25 checks; 24 of them ran in about 90 seconds and the loop runner's own tests took seven minutes more.
- The console's pure logic has tests that run in seconds, without a browser.

**Negative**

- The check reads imports statically. An import by file path (`importlib`, `runpy`) and a subprocess call are not seen, so a new one of those still needs a reviewer.
- The ledger is one more file a pull request can conflict on, when two changes re-record the same entry. The headroom keeps that rare.
- A pull request that takes a listed file past its number has to split it or raise the number by hand. That friction is the point, and it lands on whoever makes the file bigger.
- `_data/checks.yml` repeats, for machines, the table of commands in `AGENTS.md`. Until that table is generated from the registry the two can drift; `tools/test_focus.py` holds the registry to tools that exist, not to the table.
- A split file is a large diff. Each one here moves code without rewriting it and carries a mechanical proof, and each can land as its own pull request.
- The sections of `core.py` are not importable on their own: they read shared state through `core`, so `core` must load first. That keeps one owner for every name a test replaces, at the price of a module cycle that only the load order makes safe.

## Alternatives considered

- **One installable package for the hub's code (`pyproject.toml`, `pip install -e .`)** — the review's first recommendation. It needs `dash-gen` moved out of `.github/scripts/` into an importable package and an install step in every workflow, fleet caller and vendored copy, and it ends the property that a script runs from a bare checkout. The contract gives the boundary without that cost. Worth revisiting if ADR 0011's portability work needs a distributable hub.
- **Split `_data/fleet.yml` into `_data/fleet.d/` sections now** — 43 places open the file and no conflict has been recorded. It becomes a small change once there is one loader (decision 6), and not before.
- **Move the committed snapshots to a data branch or a release asset** — rejected on the measurement: 5.6 MiB of history. The size limit on a single `_data` file is the cheap guard. Committed YAML stays the fleet's memory ([docs/HARNESS.md](../HARNESS.md)).
- **Split every oversized file in one change** — the review burden and the conflict surface are too large for one pull request. The ledger holds the rest where they are.
- **Compare each file with `origin/main` instead of keeping a ledger** — needs history in CI and cannot run offline in a test; a ledger is a reviewed file.
- **A lettered check in `tools/check-drift.sh`** — the gate script is 1,060 lines of Bash and another open pull request edits it. A test file runs in the same CI job and in `tools/run-all-tests.sh` with no change to the script.
- **Scaffold every companion entry for a new surface** — writing into `.vscode/launch.json`, a feature fragment, a scenario and three indexes from one command is a second implementation of each format. Naming the checks a change owes reuses the gates that already hold those formats.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none

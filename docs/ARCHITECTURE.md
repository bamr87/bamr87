# Architecture

> How the hub's own code is laid out, the four structural rules it is held to, and the one command that names the checks a change owes. The rules are a contract in `_data/architecture.yml`, checked on every pull request. Decision: [ADR 0016](adr/0016-hub-structure-contract.md).

The hub is a control plane: it holds about forty project submodules it never builds, and everything else exists to register, check, document and automate them. This page is about that machinery, not about the projects.

| | |
| --- | --- |
| **Contract** | [`_data/architecture.yml`](../_data/architecture.yml) (`architecture/v1`): limits, layers, layer exceptions, the ledger |
| **Gate** | [`tools/architecture.py`](../tools/architecture.py) `check` · `report [--json]` · `ledger [--write] [--accept-new]` |
| **Runs** | on every pull request through [`tools/test_architecture.py`](../tools/test_architecture.py) (`python-tests.yml` runs every `tools/test_*.py`) |
| **Checks for a change** | [`tools/focus.py`](../tools/focus.py) over [`_data/checks.yml`](../_data/checks.yml) (`checks/v1`) |
| **Diagram** | [`diagrams/hub-architecture.architecture`](../diagrams/hub-architecture.architecture.json), rendered to `diagrams/hub-architecture.architecture.html` |

## The shape

Data moves in one direction. The registries in `_data/` are written by hand, the generators turn them and GitHub's signals into committed snapshots and the local lake, the shared core loads those, and the surfaces serve them. Loops run the generators on a schedule and reach the fleet only through pull requests and issues. Gates hold the registries and their projections equal, and only the maintainer merges.

| Layer | Where | What it does |
| --- | --- | --- |
| Registries and config | `_data/` | `projects.yml` is the source of truth; `fleet.yml` holds the control plane's settings |
| Generators | `.github/scripts/dash-gen/` | Deterministic projections: snapshots, the lake, the README span, the atlases |
| Shared core | `tools/fleetcore/` | The one model the surfaces share: fleet views, the graph, the PR queue, nodes |
| Engines | `tools/jev/`, `tools/weekly/` | The local loop runner, conflict triage, numbering, the weekly routine |
| Surfaces | `tools/console/`, `tools/tui/`, `tools/dash`, the MCP layer | Four front doors onto the same operations |
| Gates | `tools/check-drift.sh`, `tools/conformance.py`, `tools/schema_lint.py`, `tools/architecture.py` | Fail a change that breaks a registry, a projection, a schema or the structure |
| Standards and kits | `specs/`, `templates/` | What every fleet repo is built to, fanned out as pull requests |

The hub's code is install-free on purpose. Every script runs from a checkout on a bare interpreter, in CI, in a fleet repo that has the hub at `.fleet-hub`, and as a vendored single file. Nothing therefore enforces a package boundary for it, and the contract below is that boundary written down.

## The four rules

Run `python3 tools/architecture.py report` to see every number behind them.

### Layers

Code units are ordered low to high: `generators`, `core`, `engines`, `surfaces`. A unit imports from its own layer or a lower one, never a higher one. The loose scripts directly under `tools/` are entry points and are not layered. An import that goes up today is listed in `layer_exceptions` with the file, the imported name and a `why`; each is a lazy import inside one function, and the `why` says where the shared code belongs.

When the check reports an upward import, move the shared code down a layer: a function two layers both need belongs in the lower one. If the change cannot wait for that, add a `layer_exceptions` entry by hand with a `why`. The tool never adds one.

### Paths

A non-test Python module that changes `sys.path` is listed in the ledger with how many times it does. A new module does not get to: import through a module that is already on the path. A script directly under `tools/` already has `tools/` on its path, so `import fleetcore` needs nothing, and a module the console imports is found through `app.py`. Test files run standalone by design and are not counted.

### Sizes

A source file past `limits.module_lines` (1,500) is listed in the ledger with the number it is held to: its length when recorded plus 50 to 100 lines, so a small fix fits and most pull requests never touch the ledger. A file that is not listed may not pass the limit, and a listed file may not pass its number. Tests are not counted. `sources:` in the contract says which files this covers: the hub's Python, shell, the console's TypeScript and the workflows.

When a file reaches its number, move a section out along a seam: a cohesive part with the state only it uses, into a sibling module the original re-exports. Tests that replace a name on the old module are pointed at the module that now owns it. Raising a number is a hand edit to the contract, visible in review, with the reason in the pull request.

### Data

A committed `_data` file past `limits.data_file_kb` (512) fails. Committed snapshots are the fleet's memory and are cheap: on 2026-11-22 every `_data` blob in history came to 5.6 MiB of an 81 MiB pack. The limit exists so one snapshot cannot grow without anyone deciding it should.

## The ledger only shrinks

The ledger at the end of the contract records what the tree carries past a limit. A reduction has to be recorded in the change that makes it: a listed file that has dropped under the limit, or more than twice `ledger_headroom_lines` under its number, fails the check until the ledger says so. That is one command.

```bash
python3 tools/architecture.py ledger --write
```

`--write` lowers numbers and drops entries. It adds an entry only with `--accept-new`, and it never raises one.

## The checks a change owes

A change is done when the drift gate is green and the focused tests for what it touched pass. `tools/focus.py` reads the change against `origin/main` (committed, staged, unstaged and untracked), looks up `_data/checks.yml`, and names every check that change owes: the registry's checks whose paths it touched, and the test file beside each changed module.

```bash
python3 tools/focus.py
```

```bash
python3 tools/focus.py --run --keep-going
```

It adds no rule: each entry is an existing gate or test, and the registry only says which paths owe it. A check whose `needs:` is missing on this machine (`actionlint`, `shellcheck`, the console's `node_modules`) is reported as not run, never as passed. A new gate adds its entry to `_data/checks.yml` in the same change.

## What is not decided here

[ADR 0016](adr/0016-hub-structure-contract.md) records what was considered and left alone: packaging the hub's code as one installable distribution, splitting `_data/fleet.yml` into sections, and moving committed snapshots out of git.

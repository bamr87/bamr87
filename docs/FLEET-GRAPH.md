# The fleet graph

> Everything the control plane manages and how it relates, as one model you can ask: what depends on this, what does this need, how are these two connected, and what is missing.

The hub keeps a dozen maps, each correct about its own subject: the registry, the workflow atlas, the switches map, the agent inventory, the feature index, the roadmap, the decision logs and four operator surfaces. A question that crosses two of them had no answer short of reading both. The graph joins them, from the committed files and the checkout, in under a second, with no network, no model and no write ([ADR 0010](adr/0010-fleet-graph-and-outcome-learning.md)).

| | |
| --- | --- |
| **Module** | [`tools/fleetcore/graph.py`](../tools/fleetcore/graph.py) (`fleet-graph/v1`) |
| **CLI** | `tools/dash graph [summary \| find \| show \| impact \| lineage \| path \| check \| export]`, each with `--json` |
| **MCP** | `fleet_graph` (`action`, `node`, `to`, `text`, `kind`, `depth`, `limit`); no console needed |
| **API** | `GET /api/graph?action=…&node=…` · operation `graph-check` |
| **Page** | none yet: the operation's log on the console's Operations page; a Graph page is the next phase |
| **Tests** | `python3 tools/test_fleetcore_graph.py` (the model, the builders on a fixture checkout, the hub's own graph) · `python3 tools/test_fleetcore_mcp.py` · `python3 tools/console/test_console.py` |

## Ask it

```bash
tools/dash graph                                   # counts by kind and relation, and every input read
tools/dash graph find pulse --kind workflow        # nodes by text
tools/dash graph show loop:hub/fleet-pulse         # one node and every edge in and out
tools/dash graph impact claude-cost --depth 2      # what depends on the claude-cost action
tools/dash graph impact _data/actions_usage.yml    # what reads a data file, through the source that names it
tools/dash graph lineage agent:ci:bamr87:fleet-pulse   # what an agent needs: sources, files, actions, secrets by name
tools/dash graph path var:FLEET_PULSE_ENABLED source:actions-usage
tools/dash graph check                             # the findings; exit 1 on an error, or on a warning with --strict
tools/dash graph export --out /tmp/graph.json      # the whole graph, when another tool wants it
```

A node is named `<kind>:<key>`, and any unique tail of an id is accepted: `claude-cost` finds `action:bamr87/bamr87:claude-cost`. An ambiguous tail lists what it matched.

## The model

A node has a kind, a label and attributes. An edge has a relation. Both vocabularies are closed: a builder that needs a new kind or relation adds it to `KINDS` or `RELS` in the module.

| Kind | Is | Read from |
| --- | --- | --- |
| `repo` | the hub or a registry project | `_data/projects.yml`, `_data/fleet.yml` `hub` |
| `workflow`, `action`, `ext` | a workflow file, a hub composite action, an action from elsewhere | the workflow atlas for the hub; `_data/harness_registry.yml` for other repos' AI workflows and crons |
| `loop`, `group`, `var` | a switched loop, its switch group, the repository variable that gates it | `_data/fleet.yml` `switches` |
| `secret` | a secret a workflow reads, by name only | the workflow atlas |
| `agent`, `source` | an AI agent, a data source it reads | `_data/agents.yml` |
| `file` | a file in the hub checkout, with whether it exists | every builder that names one |
| `feature`, `req` | a feature and the PRD requirement it serves | `features/features.yml` |
| `roadmap`, `adr`, `amendment`, `issue` | a roadmap entry, a decision, an amendment, an issue one of them names | `_data/roadmap.yml`, `docs/adr/`, `docs/amendments/` |
| `cmd`, `op`, `route`, `tool`, `page` | a dash command, a console operation, an API route, an MCP tool, a console page | `tools/dash`, `tools/console/core.py`, `app.py`, `mcp_layer/server.py`, `snapshot.py` |

Each relation says which end depends on the other, and that is what `impact` and `lineage` follow.

| The source depends on the target | The target depends on the source | No dependency |
| --- | --- | --- |
| `uses`, `runs`, `gated_by`, `in_group`, `reads`, `reads_var`, `reads_secret`, `stored_at`, `defined_in`, `part_of`, `implemented_in`, `calls` | `publishes`, `writes`, `serves`, `affects` | `owns`, `manages`, `twin_of`, `documented_in`, `tested_by`, `verified_by`, `targets`, `tracked_by` |

Containment carries no dependency on purpose. Every workflow is owned by a repo, so a walk that followed `owns` would reach everything. `path` uses containment only when nothing else connects two nodes, and says so.

## The checks

`tools/dash graph check` prints findings in three severities. Only an error fails it.

| Rule | Severity | Means |
| --- | --- | --- |
| `dangling-edge` | error | an edge names a node no builder declared: a builder bug |
| `source-without-writer` | warning | an agent reads a source nothing is declared to write (constitution § 29.4) |
| `loop-without-workflow` | warning | a switched hub loop names a workflow file the hub does not have |
| `scheduled-without-loop` | warning | a hub workflow runs on a cron with no entry in the switches map (§ 17.1) |
| `uses-missing` | warning | a workflow or action calls a hub action or workflow that does not exist |
| `feature-file-missing` | warning | a feature names code, a doc, a test or a scenario that is not in the checkout |
| `route-without-tool` | note | an API route that returns data has no MCP tool that calls it |
| `command-without-operation` | note | a dash command no console operation runs |

The two notes are the surface-parity audit: what a person can do at a terminal or see on a page that an agent over MCP cannot. An exemption is one line in `ROUTE_EXEMPT` or `COMMAND_EXEMPT` with its reason (credentials stay out of an agent's reach, a command that starts a surface is not an operation). A test fails when an exemption names something that no longer exists.

How a tool is matched to a route: the layer's source is parsed, and each tool is credited with every `/api/…` path its body names, through helpers and through other tools it calls. A read tool reaches a route's `GET`; a write tool reaches its other methods too. A path the tool builds (`/api/index/{mode}`) reaches every route of that shape. A tool that reads the checkout instead of calling the console reaches no route, which is why the routes it replaces are exempt by name.

## Limits

- **Declared facts only.** The graph knows that an agent reads a source because the inventory says so. It does not parse Python to find a function that opens a file, so `impact` of a data file lists its declared readers, not every script that touches it.
- **Other repositories are shallow.** For a repo that is not the hub the graph holds what the committed scans hold: its AI workflows, their crons and switches. A workflow there that calls the hub's `claude-run` or `ai-lane` without `claude-code-action` is not in the scan yet, so it is not in the graph.
- **Built, not stored.** Nothing commits the graph and the public site does not serve it. The console caches a build for 30 seconds.
- **Source-shaped inputs.** The surface builders read `OPS`, `STATIC_ROUTES` and the layer's `@mcp.tool` functions from source. If one of those is restructured, its builder reads nothing and the hub's own test fails on the empty input.

## Adding to it

- **A new registry or surface:** write a `build_<part>` function that adds nodes and edges, register it in `BUILDERS` and `PARTS`, and add a fixture case to `tools/test_fleetcore_graph.py`. Parse through the owner's parser when one exists.
- **A new check:** a rule in `RULES` with its severity and fix, the test in `check()`, and a case in `CheckTests`. A check that should fail a pull request is a gated change (ADR 0010 decision 3).
- **A new exemption:** one line with the reason. The test that every exemption names something real will hold it.

Last modified: 2026-11-10

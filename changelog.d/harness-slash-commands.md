### Added

- Claude Code slash commands that run the harness and its loops one stage at a time: `/harness:status`, `:inventory`, `:health`, `:decisions`, `:graph`, `:gates`, `:refine`, `:learn`, `:lake`; `/loops:list` and one command per loop of the console's loops table (`:pulse`, `:issues`, `:conflicts`, `:pm`, `:credentials`, `:evolution`, `:scout`, `:fanout`, `:upkeep`), each taking the stage first (`plan`, `rehearse`, `run`, `show`, `publish`, `ci`); and `/console:ops`, `:run`, `:jobs`. A stage that writes to GitHub or spends Claude budget asks first.
- `tools/dash ops` (`list`, `show`, `run`, `loops`, `jobs`): the Harness Console's operation allowlist from a terminal, with the console's validation and confirm gate; a run joins the running console's job list and locks when that console serves the same checkout. The slash commands run every stage through it.
- Console operations `agents`, `pm`, `conflicts`, `conflicts-resolve` and `evidence`, the `jev_conflicts` and `fleet_pm` loops on the Loops page, `jev-conflicts` and `fleet-pm` in the dispatch list, and a select for a parameter with fixed choices.

### Changed

- `/dash-status` and `/evolve` are folded into `/harness:status` and `/loops:evolution` (its `hub` stage is the hub's own evolution chain).
- The harness surface check and the catalog read a `.claude/commands/` subdirectory as a namespace (`loops/scout.md` is `/loops:scout`).

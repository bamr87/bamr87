<!-- changelog.d/jev-step-repo-evolution-evolve.md -->
### Added

- `tools/jev/steps/repo-evolution/evolve.yml` + `evolve.prompt.txt`: the evolution agent's step spec (ADR 0002 P3, bamr87/bamr87#488) — the prompt `repo-evolution.yml` carries inline is held byte-equal to its render with the matrix expressions, `--model claude-opus-5-5` and `--max-turns 120` are the literals of `_data/fleet.yml` `evolution.model` / `evolution.max_turns`, and the `evolve` step pins the spec pair's hash as `JEV_STEP_SHA256`.
- `python3 -m tools.jev loop run repo-evolution [--target NAME]`: the evolution agent's step on the local loop runner, one repository per attempt; `dash-gen targets` (the planner: CI's plan job, now with `--offline` and the spec's render in every row), `dash-gen evolve-file` (the filer: a complete dry run of the patch and the draft PR body; `--apply` refused until #488's publish step), the `repo_evolution_evolve` adapter.
- `loop-step/v1` optional extensions: `workspace.github_credential: fleet-read` (the step's one `GH_TOKEN` route, held exact by parity) and `local.on_budget_hit: publish-flagged` (a budget hit previewed flagged PARTIAL, as CI's publish step marks it; a turn exhaustion still discarded).

### Changed

- `_data/fleet.yml` gains `evolution.model: claude-opus-5-5`, the exact id the workflow's `--model opus` resolved to; `test_evolution.py` reads the hard rules from the spec's render and holds the workflow's literals to `fleet.yml`.

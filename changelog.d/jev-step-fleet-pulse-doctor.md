<!-- changelog.d/jev-step-fleet-pulse-doctor.md -->
### Added

- `tools/jev/steps/fleet-pulse/doctor.yml` + `doctor.prompt.txt`: the fleet doctor's step spec (ADR 0002 P3, bamr87/bamr87#488) — the prompt `fleet-pulse.yml` carries inline is held byte-equal to it, `--model claude-opus-5-5` and `--max-turns 240` are the literals of `_data/fleet.yml` `remediation.model` / `remediation.max_turns`, and the `fix` step pins the spec pair's hash as `JEV_STEP_SHA256`.
- `python3 -m tools.jev loop run fleet-pulse [--target KEY]`: the doctor's agent step on the local loop runner, one candidate per attempt; `dash-gen remediate --plan-dir` (the planner: the queue split per candidate, the evidence `gh` would read fetched into each brief), `dash-gen doctor-file` (the filer: a complete dry run; `--apply` refused until #488's publish step), the `fleet_pulse_doctor` adapter.
- `loop-step/v1` optional extensions: `inputs: {}` for a prompt with no token, `workspace.cwd: hub`, `workspace.brief_file`, `workspace.github_credential: fleet-write` (parity holds CI's token routes exact), `local.harvest: patch`; `loop doctor [loop [step]]` runs one step's host checks.

### Changed

- `_data/fleet.yml` `budget.loops.monthly_usd`: $25 → $50, so the month can afford one $40 doctor attempt (`test_ai_budget.py` pairs the two).

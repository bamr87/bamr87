### Added

- `tools/dash refine reflect` (`python3 -m tools.jev refine reflect`, ADR 0004 P1 part one): the incident reflector — the lake's review of local sessions and CI agent runs, the trip wires, the local runs and the library become at most `reflect.max_entries` candidate lessons from ONE capped Read/Glob/Grep session inside `budget.loops`, validated by the engine and previewed; `publish <stamp> --apply` files them as a draft PR, and a `--scheduled` run never does. `refine reflect doctor [--live]` is its $0 probe and ≤ $0.10 read-fence canary; `tools/install-harness-review.sh` installs the daily `com.bamr87.harness-review` LaunchAgent (lake sessions, lake sync, lake review, the guarded weekly reflection).
- `_data/fleet.yml` `harness_refinement.reflect` (`max_entries: 5`, `days: 7`, `every_days: 7`, `timeout_minutes: 20`), validated so a month of scheduled reflections at `stage_usd` fits under `budget.loops`' scheduled stop.

### Changed

- `_data/fleet.yml` `harness_refinement.enabled: true` (the maintainer's yes, 2026-11-07), for the incident reflector; the JEV guards allow `gh pr create` only with `--draft` and `git worktree` only as `add --detach` or `remove`.

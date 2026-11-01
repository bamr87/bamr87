### Added

- `tools/dash loop` (`python3 -m tools.jev loop`): runs a loop's agent step locally with headless Claude Code — `list`, `doctor` (`--live`: the one-time ≤ $0.10 canary), `plan`, `run` (a capped, isolated, sandboxed attempt per item and a dry-run preview of the exact issue bodies; `--apply` files it in the same run; `--rehearse` stops before the model call at $0), `publish <run> --apply` (files a reviewed dry run, once), `show` and `budget`. repo-scout is the first step it runs ([docs/JEV.md](../docs/JEV.md#the-loop-runner-p1), ADR 0002 P1, #486).
- `_data/fleet.yml` `budget.loops` (`monthly_usd: 25`, `scheduled_stop_pct: 80`): the monthly ceiling for every local loop attempt, API-equivalent (estimate), inside `harnesses.budget.monthly_ai_usd` with `budget.jev`.

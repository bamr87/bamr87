### Fixed

- Harness inventory: an AI cron collision is counted per weekday and names the minute the crons share. The count ignored the day, so five weekly lanes at 14:xx on five different days read as "5 AI crons share 14:00 UTC"; of the three collisions reported on 2026-11-11 only one was real (13 crons in the 06 UTC hour on Monday, 12 of them at exactly 06:17). `throughput.hour_collisions` entries gain `days` and `same_minute`; the `/schedules` page marks an hour from that list.
- Harness inventory: `tools/dash harnesses gaps` reads `harnesses.exempt` live, so an exemption keeps a `--gaps` fan-out away before the next scan. `lifehacker.dev` is exempt: its automation was shut down on 2026-11-05 and the fan-out would have seeded a new `@claude` handler into it.
- `claude-run`: a run stopped by its turn cap fails the step. `run.sh` treated only the dollar cap as final, so `error_max_turns` fell through to the single-shot API fallback, and in a repo that ships one the step ended green on one completion while the agent's work was cut off.
- Harness inventory: the credential wiring is read from the code, not the comments, and a lane's turn cap is its `max-turns:` input, not another command's `--max-turns` flag in the same file (three it-journey lanes passed `turn-cap` that way).

### Changed

- `claude-run` and `ai-lane.yml` take a `permission-mode` input: `acceptEdits` (the default, and what the runner always passed), `default` or `plan`. A read-only reviewer on `claude-run` can keep its tool allowlist as the whole grant; any other mode is refused before the CLI runs.
- `ai-runner` kit 0.3.0: the lane caller template passes a turn cap with a dollar cap sized to it (`max-turns: "120"`, `max-budget-usd: "20"`) and its cron is a placeholder (`__CRON__`). A lane copied from the 0.2.x template was one control short of the harness standard, and twelve lanes kept its example cron.

### Fixed

- Harness inventory: an AI cron collision is counted per weekday and names the minute the crons share. The count ignored the day, so five weekly lanes at 14:xx on five different days read as "5 AI crons share 14:00 UTC"; of the three collisions reported on 2026-11-11 only one was real (13 crons in the 06 UTC hour on Monday, 12 of them at exactly 06:17). `throughput.hour_collisions` entries gain `days` and `same_minute`; the `/schedules` page marks an hour from that list.
- Harness inventory: `tools/dash harnesses gaps` reads `harnesses.exempt` live, so an exemption keeps a `--gaps` fan-out away before the next scan. `lifehacker.dev` is exempt: its automation was shut down on 2026-11-05 and the fan-out would have seeded a new `@claude` handler into it.

### Changed

- `ai-runner` kit 0.3.0: the lane caller template passes a turn cap with a dollar cap sized to it (`max-turns: "120"`, `max-budget-usd: "20"`) and its cron is a placeholder (`__CRON__`). A lane copied from the 0.2.x template was one control short of the harness standard, and twelve lanes kept its example cron.

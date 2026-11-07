### Fixed

- `_data/token_rotation.yml`: an applied rotation now publishes each repo it wrote in its post-write condition (`state: ok`, `age_days: 0`, the write time), keeps what the survey saw as `observed_state` / `observed_age_days` / `observed_oldest_age_days`, and takes `counts` and `oldest_age_days` over the post-write rows; the harness scorecard, the `credential-overdue` wire and the `oauth-secret` coverage gap read an applied `action: written` row as present and fresh, so a credential the run just wrote no longer reads as missing or overdue.

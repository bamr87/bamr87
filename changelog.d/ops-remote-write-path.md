<!-- changelog.d/ops-remote-write-path.md -->
### Added

- The OPS remote-write path (constitution § 11.8, amendment `ops-remote-write-path`; option (a) of bamr87/bamr87#487): the console `loop-run` op takes `apply` (and `run_id` to publish an earlier reviewed preview) behind the confirm gate, and `dash-gen doctor-file --apply --reviewed-bodies` publishes the fleet doctor dry run as one pushed branch and a draft PR, or the hub issue, as CI would, with the token probed by `gh api user` and never with `--scheduled`.

<!-- changelog.d/canary-probe-grants.md -->
### Fixed

- `tools/jev` loop runner (HUB-060): the live canary appends the `cat` and `python3` probe grants a step's allowlist lacks (the doctor grants no `python3`), recorded in its verdict, so a narrower step's sandbox can be proven instead of judged inconclusive.

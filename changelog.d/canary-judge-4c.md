<!-- changelog.d/canary-judge-4c.md -->
### Fixed

- `tools/jev` loop runner (HUB-060): the per-run sandbox evidence works on Claude Code 2.1.308 — the sandbox runtime's per-command line is read from its stderr under `SRT_DEBUG` (which the agent environment now sets) and recorded by `ai-run` in the outcome file, the `--settings` read-fence line is required as well, and the live canary's judge no longer reads a traceback's echoed source as a network success, pairs each `cat` with a python twin, and plants neutrally named fixture files (bamr87/bamr87#560, decision 4c).

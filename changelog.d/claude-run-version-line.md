### Fixed

- `claude-run`: after the install, the step always prints `claude-run: Claude Code <version> on Node <version>`, and warns, naming `$RUNNER_TEMP/npm-install.log`, when an install that exited 0 left no `claude` on PATH, so an install that "succeeded" with the wrong release is visible in the run log (#499).

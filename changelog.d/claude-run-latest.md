### Fixed

- `.github/actions/claude-run`: installs `@anthropic-ai/claude-code@latest` explicitly. Claude Code now declares `engines: node>=22`, so on the fleet's Node 20 a bare package name made npm fall back to 2.1.197, which current models reject (`400 … version 2.1.280 or newer is required`); every `claude-run` step on Node 20 failed over to the API path. The CLI is a native binary and runs on any Node.

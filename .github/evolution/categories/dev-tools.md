## Category emphasis: developer tools / scripts

This is a **developer-tooling / scripts** project. Weight your pass accordingly:

- Improve usability: clear `--help`/usage text, sensible defaults, helpful error messages.
- Harden shell/CLI scripts: quote variables, check exit codes, fail fast on errors,
  validate arguments (follow any bash conventions documented in the repo).
- Add or update usage examples in the README for each tool/command.
- Keep changes backward compatible — these tools are invoked by other automation.
- Where a script is non-obvious, add a short comment explaining intent, not mechanics.
- Run shellcheck/linters on anything you touch if they are available.

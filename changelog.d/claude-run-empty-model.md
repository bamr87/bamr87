### Fixed

- `claude-run` (and so `ai-lane.yml`): an empty `model:` in the consumer's `_data/ai.yml` resolves to the fleet default, as the kit's seeded file says it does. It used to reach the CLI as `--model ""`. `--model` and `AI_MODEL` still win, and a named model is used as before.

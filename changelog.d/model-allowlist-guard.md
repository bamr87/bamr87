### Fixed

- Three `_data/fleet.yml` model fields named ids outside `ai_models.allowed`: the verify agent's `sonnet` alias and JEV conflict tiers 1 and 2 (`claude-haiku-4-5-20251001`, `claude-sonnet-5`). They are now `claude-sonnet-5-5`, `claude-haiku-5-5` and `claude-sonnet-5-5`, and `test_ai_budget.py` fails any Claude `model:` in `fleet.yml` that is not an exact allowed id (#540).

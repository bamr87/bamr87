# test

Verification outputs for the hub — the evidence bundles written by `verify/runner.mjs` and the Claude Code verification pass (kit: `templates/verify/`, standard: [`docs/VERIFICATION.md`](../docs/VERIFICATION.md)).

- `evidence/<scenario id>/` — one bundle per user scenario: a screenshot per viewport, `report.json`, and a README saying what each image proves. Linked from `features/features.yml`.

Unit tests for the hub's own tooling live beside the modules (`.github/scripts/dash-gen/test_*.py`, `tools/test_*.py`, `tools/console/test_*.py`), not here. Regenerate evidence with `tools/dash verify`; never hand-edit a screenshot.

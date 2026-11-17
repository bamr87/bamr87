# test/evidence/

Evidence bundles for the dash's own user scenarios (`verify/scenarios/*.yml`), written by `tools/dash verify` (`verify/runner.mjs`): one `<scenario id>/` directory with screenshots at every viewport, `report.json` (every step, timings, console errors, evals), and a README explaining what the images prove. Linked from `features/features.yml` so the fleet index (`/features/`) can show them. Regenerate rather than edit. Standard: [`docs/VERIFICATION.md`](../../docs/VERIFICATION.md).

A scenario that needs a fixture snapshot cannot live in `verify/scenarios/`, which CI runs against the committed one. Its bundle keeps the `scenario.yml` beside the images, and its README gives the fixture recipe and says what the fixture does not cover ([`merge-fix-pr/`](merge-fix-pr/README.md) is one).

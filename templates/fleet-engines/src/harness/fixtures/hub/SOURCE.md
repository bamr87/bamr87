# Hub fixtures — provenance

Every file here is copied from `bamr87/bamr87` at commit `00fa7ae` (the `fleet-pulse` publish commit of 2026-09-01 06:48 UTC that wrote `_data/harness_health.yml`), so the inputs are exactly the ones the hub's generator read. The four signal files are reduced to the fields `.github/scripts/dash-gen/harness.py` reads (`generated_at`, `totals`, the per-workflow cost rows, the token ages); `fleet-harness.yml` is the `harness:` block of `_data/fleet.yml`; `harness_health.yml` is the committed output, verbatim.

The golden test in `../../health.test.ts` reproduces the committed output from these inputs. Re-fixture when the hub's generator changes: `git -C <hub> show <commit>:_data/<file>` and reduce with the same field lists.

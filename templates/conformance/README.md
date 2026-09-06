# templates/conformance — the in-repo UPS gate

> A thin caller of the hub's reusable `fleet-conformance.yml`, which runs `tools/conformance.py` against the repo on every PR so the Universal Project Standard is checked where the code lives.

| File | Purpose |
| --- | --- |
| `conformance.yml` | Caller workflow → `bamr87/bamr87/.github/workflows/fleet-conformance.yml@main` (`__DEFAULT_BRANCH__` substituted). Advisory (`gate: false`) until the repo's MUST rows pass. |
| `VERSION` | Kit provenance + changelog. |

Inputs the caller may set: `kinds` (comma-separated, detected when empty), `tier`, `gate`, `hub-ref`. The report lands in the job summary and an `ups-conformance` artifact. Locally the same check is `tools/dash spec check <path>`.

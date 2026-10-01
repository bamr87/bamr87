# features/

The hub's own **feature index** — the file an agent reads before touching an area of the dash: what it does for a user, where it lives, where it is documented, and what proves it works. Schema `features/v1` (field reference in [`templates/verify/features.template.yml`](../templates/verify/features.template.yml)); the fleet standard is [`docs/VERIFICATION.md`](../docs/VERIFICATION.md).

| File | Purpose |
| --- | --- |
| `features.yml` | One entry per capability: `HUB-NNN` id, `surface` (`ui` for a dash page, `infra` for a loop/gate, `cli`), `link`, `docs`, `tests`, `scenarios` (`verify/scenarios/*.yml`), `evidence` (`test/evidence/<slug>/`), `verified` stamp |

```bash
python3 tools/features_index.py check .        # validate (dangling paths warn, bad ids fail)
python3 tools/features_index.py coverage .     # per-feature: tests / scenarios / evidence / verified
tools/dash verify                              # run the scenarios → test/evidence/<id>/ + report.json
tools/dash verify --stamp --by human           # record verified: on every feature whose scenarios passed
tools/dash features fleet --write              # aggregate the fleet → _data/features_index.yml → /features/
```

The hub is one row of the fleet index like any submodule: its coverage is graded from the same files, and the `/features/` page shows it.

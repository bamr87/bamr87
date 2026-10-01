---
schema: "0.1"
coverage: listed
---

# SCHEMA — features

> The hub's own feature index (`features/v1`): what the dash does for a user, where each capability lives and is documented, and what proves it. Seeded from `templates/verify/`; aggregated with every submodule's index by `dash features fleet --write`.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | How the index is used and validated | required |
| `features.yml` | file | THE feature index — one entry per capability with surface, route, docs, tests, scenarios, evidence, verified stamp (`python3 tools/features_index.py check .`) | required |

## Placement

- New dash surface or loop → one entry in `features.yml` (stable `HUB-NNN` id) with at least a `docs:` link and a test or scenario; a `verify/scenarios/*.yml` for anything with a route.

## Forbidden

- No prose feature lists here — descriptions live in the entry, explanations in `docs/`.

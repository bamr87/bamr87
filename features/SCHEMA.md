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
| `features.d/` | dir | Pending feature entries — one unnumbered `HUB-NEW` fragment per file, compiled into `features.yml` at merge (amendment 0002); see its SCHEMA | |

## Placement

- New dash surface or loop → one fragment in `features.d/<slug>.yml` (`id: HUB-NEW`) with at least a `docs:` link and a test or scenario; a `verify/scenarios/*.yml` for anything with a route. The `HUB-NNN` id is assigned at merge, never in the pull request.

## Forbidden

- No prose feature lists here — descriptions live in the entry, explanations in `docs/`.

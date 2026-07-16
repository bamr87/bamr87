---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data

> The dash's registries: single-source-of-truth YAML read by the Jekyll site, dash-gen, the gates, and the evolution loop.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `projects.yml` | file | THE project registry — cross-checked against .gitmodules by the drift gate | required |
| `standards.yml` | file | Standardization tier baselines consumed by `dash audit` | required |
| `health_thresholds.yml` | file | Thresholds for the monitor board's attention signals | |
| `actions_usage.yml` | file | Actions usage snapshot for the analytics pages | |
| `ai_activity.yml` | file | AI/evolution activity feed data | |
| `roadmap.yml` | file | Feature roadmap entries surfaced on the dash | |
| `scripts.yml` | file | Catalog of fleet scripts | |
| `skills.yml` | file | Catalog of Claude skills across the fleet | |
| `templates.yml` | file | Catalog of seedable template kits | |
| `navigation/` | dir | Jekyll navigation data | terminal |

## Placement

- New registry file → here, one `.yml` per concern, registered above.

## Forbidden

- No secrets or tokens — registries are public site data.

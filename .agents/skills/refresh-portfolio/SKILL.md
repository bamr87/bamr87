---
name: refresh-portfolio
description: Regenerate the dash's monitoring data and the profile README project list from the registry. Use after editing _data/projects.yml or when the portfolio/README looks stale.
---

# refresh-portfolio

## Steps

1. Run `tools/dash-gen health` to refresh `_data/project_health.yml` (requires `gh auth` / `GH_TOKEN`). This drives the Dashboard and Monitor pages.
2. Run `tools/dash-gen readme` to rewrite the `<!-- AUTO:projects -->` span of the profile `README.md` from the registry.
3. Summarize what changed (new/removed projects, repos that moved to 🔴/🟠).

## Notes

- `project_health.yml` is ephemeral (gitignored) — do not commit it.
- Only the README AUTO span is committable; everything else outside the markers is hand-maintained — never touch it.

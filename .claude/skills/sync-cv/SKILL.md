---
name: sync-cv
description: Synchronize the CV (bamr87/cv data/cv.json) with the fleet — regenerate the registry's cv_portfolio.json projection, diff it against the CV's projects/skills, and propose a curated merge PR. Use when the CV's portfolio looks stale, after registry changes, or when asked to "sync the cv", "update my cv from the fleet", or "refresh the cv portfolio".
---

# sync-cv

The hub is the orchestrator in the cv ⇄ cv-builder-pro ⇄ hub triangle: [bamr87/cv](https://github.com/bamr87/cv) stores the CV of record (`data/cv.json`, CVData schema), [bamr87/cv-builder-pro](https://github.com/bamr87/cv-builder-pro) is the editor/export engine, and this repo knows the fleet — so it projects its registry into the CV's contract and proposes the sync.

## Steps

1. Regenerate the projection: `tools/dash-gen cv` (deterministic; commit `_data/cv_portfolio.json` if it changed — registry edits are the only thing that moves it).
2. Read the CV of record: `projects/cv/data/cv.json` (init the submodule if empty: `git submodule update --init projects/cv`). Its `projects` are professional **engagement portfolios**; fleet repos belong alongside them as open-source portfolio entries, not replacements.
3. Diff the fragment against the CV: which `fleet-*` projects (and stacks in the `Open-Source & Fleet Stacks` group) are missing, changed, or now archived-and-gone? Featured entries carry the most weight.
4. Propose the merge — **curated, never mechanical**: pick the CV-worthy subset, fill each adopted entry's `startDate` (repo creation ≈ `gh api repos/bamr87/<slug> --jq .created_at`), drop the adoption-metadata keys (`featured`, `fleet_status`), and keep descriptions in the CV's voice. Never invent facts; archived/dead projects come off.
5. Apply per the submodule workflow (commit in `projects/cv` on a branch, push to bamr87/cv, open a PR there; `npm run build` inside it so `CV.md` regenerates — its CI fails on drift). The hub only bumps the pointer after that PR merges.

## Notes

- `_data/cv_portfolio.json` is a **proposal surface**, not a write path — nothing may auto-overwrite `data/cv.json`; a human (or an explicitly-asked agent PR) owns what the CV claims.
- Experiences/education stay human-curated; this loop covers projects + skills only.
- The CV repo's own loops (publish, freshness, releases, jd/ tailoring) are documented in its README; this skill only feeds it fleet content.

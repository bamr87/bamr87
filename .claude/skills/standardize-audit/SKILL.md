---
name: standardize-audit
description: Audit the submodule fleet against the tiered standardization baseline and explain each required gap with the concrete fix. Use to see "which repos are off-standard" or before a fan-out.
---

# standardize-audit

## Steps
1. Run `tools/dash audit` for the full conformance matrix (`tools/dash audit <name>`
   for one repo; add `--json` to parse). Tiers and requirements come from
   [`_data/standards.yml`](../../../_data/standards.yml); the standard is
   documented in [`docs/STANDARDS.md`](../../../docs/STANDARDS.md).
2. For each repo with **required** gaps (red `✗`), name the missing artifact and
   the fix, tiered by what the repo is:
   - README / LICENSE / .gitignore → add the file (LICENSE: pick an SPDX id, add
     it to the registry `license:` field).
   - CI → adopt the reusable gate (`/standardize-project <repo>` seeds the caller).
   - agent context → add `CLAUDE.md` (+ `AGENTS.md`).
   - release automation → `tools/adopt-release.sh <repo>`.
3. Recommended (amber `!`) gaps are surfaced but not blocking — mention them.
4. Offer to open the fixes as PRs via `/standardize-project` (one repo) or the
   `standardize-fanout.yml` workflow (fleet-wide `.editorconfig` + CI).

## Guardrail
Never judge a repo against the wrong tier — forks and pure-content repos have a
lower bar by design (`tier_overrides` in `_data/standards.yml`). If a repo's tier
looks wrong, fix the override, don't add files it shouldn't have.

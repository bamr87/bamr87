---
name: drift-report
description: Run the dash drift gate and explain every failure in plain language with the exact fix. Use when CI drift-check fails or before opening a PR.
---

# drift-report

## Steps

1. Run `tools/check-drift.sh --report` (never fails) to list all drift. Add `--remote` (or `--ci`) for the GitHub-reality check (g); `--links` needs a locally built `_site` + lychee.
2. For each issue, explain the cause and the fix:
   - **(a) registry/.gitmodules parity** → fix `_data/projects.yml` or `.gitmodules`; run the `update-registry` skill. A **stray/unregistered `projects/*` dir** also fails (a) → route to the `onboard-dir` skill (adopt it or remove it).
   - **(b) stale README AUTO span** → run `tools/dash-gen readme`.
   - **(c) broken internal links** (`--links` only; advisory) → fix the pages lychee names, or rebuild `_site`.
   - **(d) missing README** → create the missing `README.md`.
   - **(e) submodule branch drift** (local-only; skipped when submodules aren't checked out) → `git -C <sub> checkout <declared-branch>` (verify no in-progress work first; some submodules sit on feature branches intentionally).
   - **(f) standardization conformance** (advisory, never gates) → route to the `standardize-audit` skill (`tools/dash audit` for the per-repo matrix).
   - **(g) GitHub-reality drift** (`--remote`/`--ci` only; advisory) — repo renamed/deleted on GitHub, or declared branch ≠ GitHub default → route to the `update-registry` skill to reconcile `repo_url`/`.gitmodules`/branch.
   - **(h) SCHEMA.md pyramid** → schema errors: run `python3 tools/schema_lint.py check .` and fix what it names; stale generated `projects/SCHEMA.md`: run `python3 tools/gen-projects-schema.py` (never hand-edit it).
3. Offer to apply the safe, non-destructive fixes.

## Guardrail

Do not force-checkout a submodule that has uncommitted or unpushed work — surface it and ask first.

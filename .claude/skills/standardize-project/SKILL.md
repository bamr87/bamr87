---
name: standardize-project
description: Bring one existing submodule up to its standardization tier baseline — add the missing README/LICENSE/.editorconfig/CI/agent-context and open a PR in the submodule's own repo. Use to fix a repo flagged by standardize-audit.
---

# standardize-project

Fixes what `standardize-audit` finds, for a single repo. Pairs with the audit the way `evolve-project` pairs with `triage-attention`.

## Steps

1. `tools/dash audit <name>` — get the repo's tier and its missing **required** artifacts.
2. Work **in the submodule's own repo** (commit there first, then bump the root pointer — see [`CLAUDE.md`](../../../CLAUDE.md)):
   ```bash
   cd projects/<name>
   git checkout <branch>            # read the branch from .gitmodules
   git checkout -b chore/standardize
   ```
3. Add only what its tier requires (see [`docs/STANDARDS.md`](../../../docs/STANDARDS.md)):
   - `.editorconfig` → copy the root [`.editorconfig`](../../../.editorconfig) (canonical template).
   - `LICENSE` → the repo's SPDX license; also set `license:` in the registry.
   - `CI` → copy `templates/standard-ci/ci.yml`, substituting `__DEFAULT_BRANCH__`.
   - `README` / `CLAUDE.md` → seed from `docs/README-TEMPLATE.md` and the repo's actual stack (don't invent features it doesn't have).
   - release automation → `tools/adopt-release.sh <name>`.
4. Commit (Conventional Commits) and open a PR in `bamr87/<name>`. Do **not** write audit/report `.md` files into the submodule tree.
5. Re-run `tools/dash audit <name>` to confirm the gaps closed.

## Guardrails

Surgical: add the standard artifacts, don't refactor the repo. Match the repo's own conventions. For forks, only standardize what bamr87 adds — don't fight upstream.

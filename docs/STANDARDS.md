# Standardization

The dash holds ~40 submodules to a shared baseline so any one of them is navigable, buildable, and safe to hand to an agent. A flat checklist would punish experiments and forks unfairly, so the baseline is **tiered by what a repo is**.

The machine-readable definition is **[`_data/standards.yml`](../_data/standards.yml)**; this page is its narrative. Enforcement and reporting:

```bash
tools/dash audit            # full conformance matrix (all submodules)
tools/dash audit <name>     # one repo, verbose
tools/dash audit --gate     # exit non-zero if a required artifact is missing
```

`tools/check-drift.sh` runs the gate slice in CI, and `.github/workflows/standardize-fanout.yml` opens PRs that bring repos up to it.

## Tiers

Tier is assigned by (in precedence order): an explicit `tier:` on the registry entry → `tier_overrides` in `standards.yml` → the registry `status` (active/maintenance → **active**, experiment → **experiment**, archived → **archived**) → fallback **experiment**. Forks and pure-content repos are set via `tier_overrides`.

| Tier | Who | Baseline |
| --- | --- | --- |
| **active** | production / maintained apps & libs | README, LICENSE, .gitignore, agent context, CI, tests **required**; .editorconfig, container, release automation **recommended** |
| **experiment** | early / single-commit | README, LICENSE, .gitignore **required**; CI, agent context, .editorconfig **recommended**; tests/container/release not expected |
| **content** | markdown / knowledge bases | README, LICENSE, .gitignore **required**; agent context, .editorconfig **recommended**; no build/tests/release |
| **fork** | forks of upstream projects | rely on upstream; README + LICENSE **recommended**; standardize only what bamr87 _adds_ |
| **archived** | read-only / retired | README **required**; LICENSE **recommended**; nothing else |

`required` missing → **fail** (red). `recommended` missing → **warn** (amber). Not-expected → grey.

## The artifacts

| Artifact | Satisfied by |
| --- | --- |
| README | `README.md` / `.rst` |
| LICENSE | `LICENSE*` / `COPYING*` |
| .gitignore | `.gitignore` |
| .editorconfig | `.editorconfig` (a copy of the root [`.editorconfig`](../.editorconfig) is the canonical template) |
| CI | `.github/workflows/` with ≥1 workflow |
| Agent context | `CLAUDE.md` / `AGENTS.md` / `.github/copilot-instructions.md` / `.cursorrules` |
| Tests | a test dir or runner config (`tests/`, `pytest.ini`, `cypress/`, `*.config.ts`…) |
| Container | `Dockerfile` / `.devcontainer/` / `docker-compose.yml` / `compose.yml` |
| Release automation | `release-please-config.json` / `.release-please-manifest.json` / `CHANGELOG.md` |

## Bringing a repo up to standard

1. `tools/dash audit <name>` — see what's missing for its tier.
2. `.editorconfig`: fan out the root template (`standardize-fanout.yml`, or the `/standardize-project` skill for a single repo).
3. Agent context: fan out the agent-context kit — dispatch `standardize-fanout.yml` with artifacts `agent-context,claude` (a `CLAUDE.md` scaffold plus the `@claude` mention workflow; defaults stay `editorconfig,ci`), or use the `/standardize-project` skill for one repo. Fan-outs ride [`tools/fanout.sh`](../tools/fanout.sh) — dry-run by default, additive-only, PRs only. See [AI-INTEGRATION.md](AI-INTEGRATION.md).
4. LICENSE / release automation: `tools/adopt-release.sh <name>` scaffolds the release-please pipeline; add the SPDX id to the registry `license:` field.
5. CI: adopt the reusable [`standard-ci.yml`](../.github/workflows/standard-ci.yml) via a short caller workflow (what the fan-out drops in).

Changes are always committed in the submodule's own repo first, then the pointer is bumped in root — see [MONOREPO.md](MONOREPO.md).

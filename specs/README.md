# Universal Project Standard (UPS)

> One spec every repo in the fleet is built to — layout, quality gates, agent context, design system, core UI components, API conventions, operations — written so an AI agent can apply it to any stack without asking.

The hub already standardizes **file presence** ([`_data/standards.yml`](../_data/standards.yml): README, LICENSE, CI, tests… per tier) and **fans out kits** ([`templates/`](../templates/)). This directory adds the layer above both: what those files must *contain*, what every product must *do* for its users, and how every stack maps onto one set of conventions. It was derived from a full review of the hub and all ~40 submodules on 2026-09-01; every requirement cites the fleet repo it was lifted from, so adoption is extraction, not invention.

## How to read a requirement

Each spec is a table of requirements. Every row has:

| Column | Meaning |
| --- | --- |
| `id` | Stable id `UPS-<AREA>-<NN>`. Never reused; deprecated ids stay in the table marked `retired`. |
| `level` | RFC 2119: **MUST** (gate fails without it), **SHOULD** (warn; deviate only with a documented reason in the repo's `AGENTS.md`), **MAY** (recommended pattern). `retired` rows stay in the table for history and never gate. |
| `applies` | Which [stack kinds](STACKS.md) the row binds: `all`, `site`, `app`, `api`, `lib`, `cli`, `ext`, `content`. |
| `satisfied by` | The concrete file, config key, or behaviour an auditor looks for. |
| `seed` | The hub kit or tool that provides it (`—` when it must be written by hand; that is a gap the roadmap tracks). |

The machine-readable copy is [`_data/specs.yml`](../_data/specs.yml). Prose here is the narrative; the YAML is what tooling reads. When they disagree the YAML wins and the prose is a bug.

## Applicability

1. Determine the repo's **tier** from the registry (`_data/projects.yml` → `_data/standards.yml` precedence). `fork` repos are bound only for what bamr87 adds; `archived` repos are bound by nothing here.
2. Determine the repo's **kind(s)** from [STACKS.md](STACKS.md). A repo can be several (a Django API with a React `frontend/` is `api` + `app`).
3. A requirement binds when its `applies` column includes `all` or one of the repo's kinds, and the tier is not exempt.
4. `MUST` rows are the gate. A repo is **UPS-conformant** when every binding `MUST` passes and every failing `SHOULD` is waived in its `AGENTS.md` under a `## Standard deviations` heading with a one-line reason (and in `.github/sdlc.yml` `deviations:`). `AGENTS.md` is the canonical agent file and `CLAUDE.md` a pointer to it (decision D4); during the transition the waiver is also accepted in `CLAUDE.md`.

## The specs

| Spec | Area id | What it governs | Lifted mainly from |
| --- | --- | --- | --- |
| [REPOSITORY.md](REPOSITORY.md) | `REPO` | Layout, required files and their content, README/CHANGELOG/SECURITY/CONTRIBUTING contracts, containers, `tools/` | hub `.editorconfig`, `README.template.md`, `SUBMODULES.md`, zer0-mistakes |
| [AGENT-CONTEXT.md](AGENT-CONTEXT.md) | `AGENT` | `AGENTS.md` (canonical) required sections and the `CLAUDE.md` pointer, `.claude/` baseline, SCHEMA.md pyramid, guardrails, MCP, what never fans out | `templates/agent-context/`, `templates/schema/`, `AGENTS.md` |
| [QUALITY.md](QUALITY.md) | `QA` | Lint/format/test/CI per stack, coverage floor, pre-commit, commits, branches, releases, dependency policy, site quality (Lighthouse/axe/contrast). Machine contract for the site-quality rows: [`QUALITY.contract.yml`](QUALITY.contract.yml) | `standard-ci.yml`, `docs/RELEASES.md`, `docs/DEPENDENCIES.md`, ruff/vitest/playwright usage across the fleet |
| [FRONTEND.md](FRONTEND.md) | `FE` | Design tokens, theming, the core component set, accessibility, SEO/meta, analytics + consent, the UX audit gate | zer0-mistakes `_design-system/`, law-ai `ux_audit.py`, fredgar `states.tsx`, gitorio `theme.test.ts` |
| [FEEDBACK.md](FEEDBACK.md) | `FB` | The universal "submit feedback → GitHub issue" component: data contract, issue body, labels that feed the issue pipeline, fallbacks, privacy | zer0-mistakes `page-feedback.js` + `_data/feedback_types.yml`; seeded by `templates/feedback/` |
| [BACKEND.md](BACKEND.md) | `BE` | HTTP API conventions: error envelope, health/version endpoints, versioning, pagination, auth headers, OpenAPI, the client contract | fredgar `lib/http.ts`, aieo `services/api.ts`, `.github/instructions/development` |
| [OPERATIONS.md](OPERATIONS.md) | `OPS` | Config and env vars, structured logging, error reporting, security artifacts and scanning, secrets, data/migrations | `_data/fleet.yml` token contract, `docs/TOKEN-ROTATION.md`, `issue-evidence.sh` credential scrubbing |
| [WORK.md](WORK.md) | `WORK` | Planning & delivery: the `.github/sdlc.yml` profile, one backlog of record, the fleet Definition of Done, ADRs, changelog hygiene, pinned shared workflows, freshness. Machine contract: [`WORK.contract.yml`](WORK.contract.yml) | `templates/community/`, `templates/sdlc/`, `templates/spec-driven/`, law-ai and gitorio (AO-SDLC), zer0-mistakes `_data/backlog.yml` |
| [STACKS.md](STACKS.md) | — | The stack-family profiles: canonical toolchain, layout, and which rows bind, for Jekyll, React/Vite, Next, Django, Rails, Python lib/CLI, Bash, VS Code extension, Ruby gem, content | the survey |
| [CONFORMANCE.md](CONFORMANCE.md) | — | How a repo declares the spec version it meets, how the audit runs, the adoption order, and the fleet gap list as of 2026-09-01 | `tools/audit-standards.sh`, `check-drift.sh` |

## Where things live (the hub as the central repository)

The full catalogue — every spec, kit, reference implementation, registry, tool, loop, skill, and doc — is the generated root [`CATALOG.md`](../CATALOG.md).

| Kind of artifact | Home | Consumer |
| --- | --- | --- |
| Specs (this) | `specs/` + `_data/specs.yml` | agents, `dash audit`, humans |
| Seedable kits (files copied into repos) | `templates/<kit>/` with `VERSION` + `archive/` | `tools/fanout.sh`, `standardize-fanout.yml` |
| Baseline tiers (which artifacts are required) | `_data/standards.yml` | `tools/audit-standards.sh` |
| Fleet config (versions, caps, tokens, labels) | `_data/fleet.yml` | every loop |
| Skills, commands, agents for the hub | `.claude/` | Claude Code in the hub |
| Copilot-format personas, instructions, prompts | `.github/{agents,instructions,prompts}` | hub skills, read in place |
| Reference UI implementation | `projects/zer0-mistakes/` (`_design-system/`, `_includes/components/`) | Jekyll sites via `remote_theme`; other stacks via the extracted kits |

Rule: **a standard is not real until it has (a) a row here, (b) a satisfying artifact a repo can hold, and (c) a seed or an audit.** A row with `seed: —` and no audit is a proposal, and belongs on the roadmap until one of those exists.

## How an agent uses this

- **Creating a repo**: read [STACKS.md](STACKS.md) for the family, apply every `MUST` for `all` + that kind, run the kits listed in each row's `seed`, then fill the hand-written rows. Record `spec: "1.0"` in the registry entry.
- **Changing a repo**: before touching a directory, read its `SCHEMA.md` and `README.md` (README-First); after, confirm the rows in the area you touched still hold (README-Last).
- **Auditing**: `tools/dash spec check <path>` runs the machine-checkable rows against one repo (`--gate` for CI); `tools/dash spec fleet --write` snapshots every submodule into `_data/conformance.yml`, which the weekly repo-evolution brief turns into adoption PRs; the `conformance` fan-out artifact runs the same checker in each repo's own CI. Details in [CONFORMANCE.md](CONFORMANCE.md).
- **Deviating**: add the id and reason under `## Standard deviations` in the repo's `AGENTS.md` and to `.github/sdlc.yml` `deviations:` (a `CLAUDE.md` section is accepted during the D4 transition). Undocumented deviation is non-conformance.

## Versioning

This is UPS **1.0** (draft until the first fleet audit is committed). Rows are added with new ids; changed semantics get a new id and the old one is `retired`. The spec version a repo meets is declared in the registry (`spec:` field, see CONFORMANCE.md), so a bump here does not silently move every repo out of conformance.

# Conformance: declaring, auditing, adopting

> How a repo says which spec version it meets, how the hub checks it, the order to adopt in, and where the fleet stands today.

## Declaring

Add to the repo's registry entry in [`_data/projects.yml`](../_data/projects.yml), beside the existing `schema:` and `release:` blocks:

```yaml
  spec:
    version: "1.0"          # UPS version the repo targets
    status: adopted         # none | pending | adopted   (pending = adoption PR open)
    audited: 2026-09-15     # date of the last passing audit, or null
    deviations: 2           # count of waived SHOULD rows recorded in CLAUDE.md
```

`kinds:` may be declared beside it (see the registry header); when absent the checker detects them from the tree.

Waivers live in the repo, not the hub: a `## Standard deviations` section in `CLAUDE.md` listing `UPS-<AREA>-<NN> — <one-line reason>`. A `MUST` cannot be waived; if a `MUST` is wrong for a whole stack family, change the spec (new id, retire the old).

## Auditing

`tools/dash audit <name>` checks the file-presence tiers in `_data/standards.yml`. The UPS audit is [`tools/conformance.py`](../tools/conformance.py) (`dash spec`), driven by [`_data/specs.yml`](../_data/specs.yml). It runs in three places so the same checker measures every repo:

| Where | Command | Output |
| --- | --- | --- |
| One repo, locally | `tools/dash spec check <path> [--kinds a,b] [--tier t] [--gate] [--json]` | text or JSON; `--gate` exits non-zero on any MUST failure |
| The whole fleet, locally | `tools/dash spec fleet --write` | [`_data/conformance.yml`](../_data/conformance.yml): per-repo kinds, tier, pass counts, failing rows; the **repo-evolution brief** reads it so the weekly agent pass closes real gaps |
| Each repo's own CI | the `conformance` fan-out artifact → reusable [`fleet-conformance.yml`](../.github/workflows/fleet-conformance.yml) | job summary + `ups-conformance` artifact; advisory until the caller sets `gate: true` |

How it decides:

1. Kinds come from the registry `kinds:` field when set, otherwise from the tree (`dash spec kinds <path>` shows the detection); tier from the registry / `_data/standards.yml` precedence. `fork` and `archived` are skipped.
2. A row binds when its `applies` includes `all` or one of the repo's kinds.
3. Rows with an implemented check (static: file presence, byte parity, greps — no build, no network) are evaluated; rows without one are counted as `manual`. Jekyll sites on the zer0-mistakes theme satisfy theme-provided FE rows automatically, except the feedback widget, which needs `page_feedback.enabled: true` in the consumer's `_config.yml`.
4. MUST failures are red, SHOULD failures amber; the `## Standard deviations` waiver in `CLAUDE.md` is not yet read by the checker (roadmap), so a waived SHOULD still shows amber.

The machine-checked set grows by adding a function to `tools/conformance.py`; the manual checklist below covers the rest until then.

## Adoption order (per repo)

The order is chosen so each step is a small PR that leaves the repo better even if the next never lands, and so that seeds go first and hand-written work last.

1. **Hygiene** — dedupe checkouts (REPO-08), remove committed `node_modules`/lockfiles (REPO-07, QA-40), `.editorconfig` (REPO-17). Kits: `standardize`, `deps-latest`.
2. **Agent context** — `CLAUDE.md` sections filled (AGENT-02), `claude.yml`, `.claude/settings.json`, labels created (AGENT-32). Kit: `standardize --artifacts agent-context,claude,claude-settings`.
3. **Community files** — LICENSE, SECURITY.md, CONTRIBUTING.md, CODEOWNERS, issue/PR templates, dependabot (REPO-12..19, QA-41). Kit: `community` (to build).
4. **Quality** — CI caller, formatter, linter, test runner with ≥1 test, release-please (QA-*). Kits: `standardize --artifacts ci`, `adopt-release`.
5. **Schema** — SCHEMA.md pyramid + gate (AGENT-20). Kit: `schema`.
6. **Feedback** — mount the widget, enable on consumer sites (FB-*). Kit: `feedback`.
7. **Design tokens + shell** — token file, colour mode, AppShell, skip link, 404, error boundary, toast, states (FE-01..20). Kit: `design-tokens` (to build); components lifted per the FE seed column.
8. **Meta, consent, analytics** — FE-24/25. Kit: `design-tokens` snippets.
9. **API + ops** — envelope, health/version, settings, logging, security headers (BE-*, OPS-*). Kit: `api` (to build).
10. **Gates** — UX audit, Lighthouse, OpenAPI diff, coverage (FE-60, FE-53, QA-17, QA-14). Kit: `ux-audit` (to build).

Fleet-wide, steps 1–6 are fan-out-able today or with one new kit each; steps 7–10 need the kits listed as gaps below.

## Manual checklist (until the audit is tooled)

Copy into the adoption PR description; tick what passes.

```text
REPO  01 02 03 06 07 08 10 11 12 13 14 17 18 20 31 32
AGENT 01 02 03 04 06 11 20 21 22 30 31 32
QA    01 02 03 04 05 07 10 11 12 13 15 17 20 21 22 30 31 32 33 34 40 41
FE    01 02 03 04 05 06 08 09 10 11 12 13 14 15 16 17 18 19 20 24 25 30 31 32 35 40 42 50 51 52
FB    01 02 03 04 05 06 07 08 20 21 22 23 24 30 31 32
BE    01 02 03 04 06 10 11 20 21 22 30 31 40 41 50
OPS   01 02 03 10 11 12 16 20 21 22 23 24 30 31 33 40 42
```

## Fleet status at 2026-09-01 (from the review)

| Gap | Scope | Fix |
| --- | --- | --- |
| Feedback widget dead on 7 consumer sites; absent in every app | FB-01, FB-31, FB-32 | `templates/feedback/` kit + theme fallback taxonomy |
| Four token vocabularies; no shared component kit; no React app consumes the design system's React specs | FE-01..09, FE-10..20 | `design-tokens` kit extracted from `zer0-mistakes/_design-system/tokens`; component lift per FE seed column |
| Skip link in 3 surfaces; OG meta outside Jekyll in 1; analytics outside Jekyll in 0; consent in 1 | FE-11, FE-24, FE-25 | shell + head snippets in the `design-tokens` kit |
| UX audit exists in 1 repo (law-ai) | FE-60 | `ux-audit` kit generalised from `law-ai/scripts/ux_audit.py` |
| Three `ApiError` shapes, no envelope, no health/version contract, no OpenAPI in CI | BE-10..40 | `api` kit: middleware + client + settings + logging |
| No `SECURITY.md`, `CONTRIBUTING.md`, CODEOWNERS, labels, dependabot fan-out; 12 owned repos without LICENSE | REPO-12..19, QA-41, AGENT-32 | `community` kit |
| `templates/release-pipeline/` lacks `VERSION`/`archive/`; only 5 repos on release-please | QA-32 | version the kit; fan out |
| Duplicate checkouts (`fredgar-ai`≡`edgar-data-parse`, `zer0-cms`≡`vscode-front-matter`); 4 stray unregistered dirs; `amrs-project` superseded by `djangoerp` | REPO-08 | registry + `.gitmodules` reconciliation, retire `amrs-project` |
| VS Code extensions: 4 toolchains, 1 with no tests, committed `node_modules` in 3 repos | QA-13, REPO-07 | `vscode-extension` profile + kit |
| Cypress in 1 repo; pytest config in 3 places; `test/` vs `tests/` | QA-11, QA-12, REPO-02 | per-repo migration PRs (grandfather `test/`) |
| `standard-ci` passes on zero tests; no Bash detection | QA-10, QA-04 | `standard-ci.yml` change |
| Hub dash has no feedback path | FB-33 | mount the kit on the dash |
| `_data/templates.yml` under-reports the kits; `.husky` vestigial | — | catalog refresh; delete `.husky` |

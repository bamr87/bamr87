# UPS-WORK — Planning & delivery

> How work enters, moves through and leaves a fleet repo: the SDLC declaration, the one backlog of record, the Definition of Done, decision records, the changelog, pinned shared workflows, and freshness. The other areas say what a repo contains; this one says how change flows through it.

Evidence base (2026-10-03, SDLC harmonization survey of 67 repos): structured backlogs exist in 5 (law-ai and gitorio `BACKLOG.md`; zer0-mistakes and lifehacker.dev `_data/backlog.yml`; it-journey `.issues/`). Spec packages exist in 2 (law-ai, gitorio). ADR logs exist in 5, in 3 formats. Four PR templates carry four different checklists. No repo uses milestones, and one Projects v2 board is active.

The exact paths, keys and regexes a checker reads for every row are in [`WORK.contract.yml`](WORK.contract.yml). This file states the rules; the contract is what `tools/conformance.py` is keyed to.

## Decisions this area encodes

All six were settled on 2026-10-03. None is a switch.

| Id | Decision | Where it shows up |
| --- | --- | --- |
| D1 | The default backlog of record is **GitHub Issues with the fleet labels**. A file backlog (`BACKLOG.md` or `_data/backlog.yml`) is allowed only when declared in `.github/sdlc.yml`, and it must be linted in CI. | WORK-01, WORK-02, WORK-09, WORK-14 |
| D2 | Decision records use law-ai's format: `docs/adr/NNNN-slug.md` with Status, Context, Decision, Consequences, Alternatives, Supersedes. gitorio's `docs/DECISIONS.md` (Wave 2) and year-of-ai's `lineage/decisions/` (Wave 4a) migrate later; until then they are accepted through `adr_path`. | WORK-04, WORK-13 |
| D3 | Shared workflows live in the hub (`bamr87/bamr87/.github/workflows/`). `bamr87/.github`'s `ci.yml` is retired; the shared CI gate is `standard-ci.yml`. | WORK-10, UPS-QA-20 |
| D4 | **`AGENTS.md` is canonical in every repo; `CLAUDE.md` is a short pointer** that imports it (`@AGENTS.md`). `.claude/commands/` stay. | WORK-12, UPS-AGENT-07/08/09 (replacing AGENT-01/02/03) |
| D5 | **Every repo has a `CHANGELOG.md`, content repos included**, written by release-please through the hub's reusable `release-please.yml`. Nobody edits it by hand. | WORK-05, UPS-REPO-21 (replacing REPO-13), UPS-QA-32/33 |
| D6 | Repos are typed `app`, `library`, `site`, `docs`, `demo`, `control-plane` or `fork`, and each type maps onto the UPS kinds below. | WORK-01, [Repo types](#repo-types-d6) |

## The SDLC declaration

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-WORK-01 | MUST | all except fork | The repo declares its SDLC profile in `.github/sdlc.yml` (`schema: sdlc/v1`: `type`, optional `kinds`, `tier`, `backlog.mode`, a `modules` map, `adr_path`, `release.type`, `deviations`), valid against the kit's JSON Schema. The hub registry `sdlc:` block may carry the same keys; the file wins when both exist. | file valid against `templates/sdlc/sdlc.schema.json`, or registry block | `templates/sdlc/sdlc.yml` |

## Backlog of record

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-WORK-02 | MUST | all except content, fork | There is exactly one **backlog of record**. `issues` mode (the default, D1): GitHub Issues carrying the fleet labels. `file` mode: the declared `BACKLOG.md` or `_data/backlog.yml`, linted by a CI job; a sync job alone is not a lint. Other planning files link to it (WORK-11). | file mode: file + CI lint step; issues mode: not visible offline (see WORK-14) | `templates/sdlc/`, `templates/spec-driven/tools/backlog_lint.py` |
| UPS-WORK-09 | MUST | all | Issue forms in the tree apply exactly one fleet type label (`_data/fleet.yml` `issue_pipeline.labels.types`) and never a GitHub-default duplicate (`enhancement`, `documentation`, `priority:Px`). `page_feedback.yml` is exempt from the type-label clause because UPS-FB-07 fixes its label. Inherited forms are not visible offline. | `.github/ISSUE_TEMPLATE/*` labels | `templates/community/.github/ISSUE_TEMPLATE/` |
| UPS-WORK-14 | SHOULD | all | The repo's GitHub labels include every name in the fleet taxonomy (states, types, priorities, sizes), and the GitHub-default duplicates have been renamed into it rather than left beside it. Checked online by the fleet scorecard, never by the in-repo gate. | `gh label list` vs `labels.yml` | `templates/community/labels.yml` (label-sync job) |
| UPS-WORK-11 | SHOULD | all except content | Planning files other than the backlog of record (`ROADMAP.md`, `TODO.md`, `PRD.md`, and the same names under `docs/`) hold no item lists: no task-list checkboxes and no backlog ids. Each one links to the backlog of record (the repo's Issues, or the declared backlog file) or to the hub's `_data/roadmap.yml`, where cross-repo initiatives (`FF-NNNN`) live. | no `- [ ]` lines or `BL-`/`T-` ids; a backlog link present | — |

## Delivery: Definition of Done, decisions, changelog

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-WORK-03 | MUST | all except fork | The repo's PR template (its own, or the default inherited from the owner's `.github` repo) carries the fleet **Definition of Done** between `<!-- fleet-dod:start v1 -->` and `<!-- fleet-dod:end -->`: Conventional title (drives release-please), CI green, tests, docs and features updated, `AGENTS.md` updated, ADR if hard to reverse, backlog of record updated, clean diff with no secrets. A repo may add boxes below the end marker, never inside it. | marker block with the kit's boxes, in order | `templates/community/.github/pull_request_template.md` |
| UPS-WORK-04 | MUST | app, api, lib, cli, ext | Decisions that are hard to reverse are recorded as `NNNN-slug.md` ADRs (law-ai format, D2) with a `README.md` index, under `adr_path` (default `docs/adr`). | ≥1 ADR + index | `templates/sdlc/docs/adr/` |
| UPS-WORK-13 | SHOULD | site | Sites keep the same ADR log as WORK-04. | ≥1 ADR + index | `templates/sdlc/docs/adr/` |
| UPS-WORK-05 | SHOULD | all except fork | Changelog hygiene: **at most one** `## [Unreleased]` heading (release-please writes none, so zero is normal), and the newest version heading equals the newest `vX.Y.Z` tag. | parser check | `templates/sdlc/CHANGELOG.template.md` |
| UPS-WORK-06 | SHOULD | all | The feature catalog lives in one place (`features/features.yml`, no `_data/features.yml` duplicate) and carries no hand-maintained version header. | parser check | `templates/verify/` |
| UPS-WORK-12 | MUST | all except fork | `AGENTS.md § Conventions` names the backlog of record, the Definition of Done location and the ADR path (`adr_path`), so agents and humans follow one loop (D4). | text check | `templates/sdlc/AGENTS.template.md` |

## Spec-driven module

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-WORK-07 | MUST | all (`modules.spec_driven: true` only) | Spec packages `specs/NNN-slug/{spec,plan,tasks}.md` are validated by `spec_validator.py`, and `BACKLOG.md` by `backlog_lint.py`, in a CI spec-gate job that every other job in its workflow `needs`. The four shared tools are byte-identical to the hub kit's copies. | CI job + byte parity | `templates/spec-driven/` |

## Shared workflows

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-WORK-10 | MUST | all | Reusable workflows and composite actions from `bamr87/bamr87` or `bamr87/.github` are referenced at `@vMAJOR`, `@vMAJOR.MINOR.PATCH` or a full 40-character SHA (a trailing `# vX.Y.Z` comment is allowed). Branch refs such as `@main` are rejected. The only exemption is a local `./` path, which is how the hub calls its own workflows; the hub's remote self-references count like anyone else's. Tag scheme: [`docs/WORKFLOW-VERSIONING.md`](../docs/WORKFLOW-VERSIONING.md). | `uses:` refs | fan-out of `@v1` callers |

## Freshness

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-WORK-08 | SHOULD | all except content | No spec stays `in-progress` for more than 30 days without a commit; no `P0`/`P1` issue sits idle for more than 30 days; the backlog file is touched within 60 days of the last code commit. Reported in the fleet scorecard, never gating. | scorecard | — |

## Repo types (D6)

`.github/sdlc.yml` `type:` uses the plan's vocabulary. Specs bind through UPS kinds, so each type maps onto kinds; a repo lists `kinds:` explicitly only when it is several things at once (e.g. `[app, api]`, `[lib, cli]`).

| type | default kinds | release-please `release.type` (D5) | typical repos |
| --- | --- | --- | --- |
| `app` | `app` (add `api` for a server) | `node`, `python` or `ruby` by ecosystem, else `simple` | gitorio, law-ai, fredgar-ai |
| `library` | `lib` (add `cli` / `ext`) | `node`, `python` or `ruby` by ecosystem, else `simple` | zer0-mistakes (gem), zer0-image-generator |
| `site` | `site` | `simple` | Jekyll sites on the zer0 theme |
| `docs` | `content` | `simple` | year-of-ai and ai-world-view member repos |
| `demo` | `site` | `simple` | demos and showcases |
| `control-plane` | `site`, `hub` | `simple` | bamr87/bamr87 |
| `fork` | `fork` | none (upstream's changelog) | forks tracking an upstream |

`hub` is a marker kind: no row targets it yet, so the control plane is checked as a `site`.

## Deviations

A waived SHOULD row is listed in two places: `.github/sdlc.yml` `deviations: [{id, reason, until}]`, and the `## Standard deviations` section of `AGENTS.md` (D4). During the transition the checker also accepts that section in `CLAUDE.md`. A MUST row cannot be waived; if it is wrong for a whole family, change the spec.

## Resolved questions

These were open in the Wave 1 draft (raised in #316) and are settled here and in the contract:

1. **[Unreleased]:** at most one, not exactly one. release-please writes none (WORK-05).
2. **ADR levels:** one level per row. WORK-04 is MUST for app/api/lib/cli/ext, and the new WORK-13 is SHOULD for sites.
3. **`adr_path`:** a top-level key in `.github/sdlc.yml` and in the registry block, defaulting to `docs/adr`.
4. **`modules`:** a map of booleans in `.github/sdlc.yml`. The registry block may use a map or a list of enabled names. `demo` is a repo type (D6), not a UPS kind.
5. **Offline labels:** the in-repo gate checks issue forms only (WORK-09). Label presence on GitHub is the separate, online, scorecard-only WORK-14.
6. **Sync vs lint:** a sync job does not satisfy WORK-02's lint.
7. **`page_feedback`:** exempt from WORK-09's type-label clause (UPS-FB-07 owns its label), but still may not use a duplicate label.
8. **WORK-10 vs QA-40:** the spec wins, and both rows use the same ref rule (`@vN`, `@vX.Y.Z`, full SHA; no branches). The hub's remote self-references count; local `./` paths are exempt.
9. **Kit path:** the spec-driven tools live in `templates/spec-driven/` (a top-level kit, versioned on its own), not `templates/sdlc/spec-driven/`.
10. **DoD wording:** the `fleet-dod` markers and the kit's box titles are the contract, not keywords.
11. **WORK-11:** rewritten as a file check (no item lists in planning files, plus a backlog link) instead of the undefined "link check".

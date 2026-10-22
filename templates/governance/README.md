# templates/governance — constitution, amendments, and the PRD ↔ feature link

The fleet kit that gives every repo the same governing chain, so an AI agent (or a person) always knows **which rules hold, how they change, what the product must do, and what it does today**:

```
docs/constitution.md ──▶ AGENTS.md ──▶ PRD (FRn / NFRn) ◀──▶ features/features.yml (ID-NNN)
        ▲                                                   │
docs/amendments/NNNN-*.md (ratified by merged PR)           └── PRD "Feature catalog" block (generated)
```

Spec rows: [UPS-WORK-15](../../specs/WORK.md) (PRD ↔ feature catalog) and [UPS-WORK-16](../../specs/WORK.md) (constitution + amendment log), both `SHOULD` with `rollout: warn` in `specs/WORK.contract.yml`. Validator: [`tools/governance_lint.py`](../../tools/governance_lint.py). Fan-out: `tools/fanout.sh --kit governance` (branch `docs/feature-catalog`).

## Where it came from (precedents, not invention)

| Piece | Basis |
| --- | --- |
| Constitution sections | `bamr87/law-ai` `docs/constitution.md` — the fleet's only ratified constitution (mission, locked stack, gates, HITL, spec workflow, autonomy) — via the spec-driven kit's `constitution.template.md`, same path `docs/constitution.md` |
| Amendment records | law-ai's dated inline amendments tied to ADRs ("amended 2026-09-04, ADR 0007"; "amendments require an ADR and review by a human maintainer"), gitorio's `proposals/PROPOSED-*-amendment.md`, year-of-ai's ratify-by-merge `lineage/decisions/`; numbered like the sdlc kit's ADR log (`docs/adr/NNNN-slug.md`) |
| Feature catalog | the verify kit's `features/features.yml` (`features/v1`, itself lifted from zer0-mistakes / it-journey / barodybroject), extended additively |

## The rules

**Feature catalog** (`features/features.yml`, schema `features/v1` — still a strict superset):

- one entry per user-facing capability, stable id `PREFIX-NNN` (prefix per repo, never reused);
- new optional fields: `status` (`shipped` · `partial` · `planned` · `deprecated` · `tbd`) and `prd: [FR1, NFR2]`
(or `§4` for a PRD without requirement ids, `[TBD]` when unknown); top-level `prd: path` when the PRD is not `PRD.md` / `docs/PRD.md`;
- grounded only: every entry cites where it lives (`link`, `docs`); a feature nobody can locate is `status: tbd`.

**PRD**: requirement bullets carry ids (`FR1:`, `NFR1:`; `governance_lint.py prd-ids --write` tags untagged ones in a `## N. Requirements` section). The `## Feature catalog` section holds a generated block between `<!-- features:start v1 … -->` and `<!-- features:end -->`: every feature id linked to the catalog, its status, location and requirement refs, then the requirement → feature trace. Regenerate with `prd-sync --write`; never hand-edit it (same rule as the README AUTO span and the release-please CHANGELOG).

**Constitution** (`docs/constitution.md`): mission, invariants, authority/precedence, the human-vs-agent role table, how the artifacts relate, change process, quality gates, Amendments section. Tailor every `TODO:` from the repo's AGENTS.md / README / PRD; unknown = **TBD**.

**Amendments** (`docs/amendments/`): `README.md` index, `0000-template.md`, append-only `NNNN-kebab-slug.md` records with `Status`, `Date`, `Proposed by`, `Ratified by` (the merged PR), `Affects` (constitution §, PRD ids, feature ids), `Supersedes`. `0001-ratify-constitution.md` ships with the kit: merging the PR that adds it ratifies the constitution. Agents propose; only the maintainer ratifies (merges).

**AGENTS.md / CLAUDE.md** must reference the constitution so agents read it first.

## Commands

```bash
python3 tools/governance_lint.py check projects/<repo>          # errors + warnings (exit 1 on error)
python3 tools/governance_lint.py prd-ids projects/<repo> --write # tag FRn / NFRn
python3 tools/governance_lint.py prd-sync projects/<repo> --write # regenerate the PRD block
python3 tools/governance_lint.py fleet                           # every checked-out submodule + the hub
tools/fanout.sh --kit governance --target <name|all> [--apply]   # seed, tag, sync, lint → PR
```

## Jekyll sites

`docs/` and `features/` are not site content. Add `docs/constitution.md`, `docs/amendments`, and `features` to `_config.yml` `exclude:` when `docs` is not already excluded. year-of-ai repos list the new files in `genome/manifest.yml` when they carry one.

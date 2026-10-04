---
schema: "0.1"
coverage: listed
---

# SCHEMA — specs

> The Universal Project Standard: the requirement specs every fleet repo is built to, one UPPERCASE topic file per area, mirrored machine-readably in `_data/specs.yml`.

## Conventions

- One file per area id (`REPO`, `AGENT`, `QA`, `FE`, `FB`, `BE`, `OPS`, `WORK`); requirement ids are `UPS-<AREA>-<NN>` and are never reused.
- Every requirement row states `level` (MUST/SHOULD/MAY, or `retired`), `applies` (stack kinds from STACKS.md), `satisfied by`, and `seed`.
- `_data/specs.yml` is the machine-readable twin; when prose and YAML disagree the YAML wins.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | Master index: how to read a row, applicability, where artifacts live, versioning | required |
| `REPOSITORY.md` | file | UPS-REPO: layout, required files and their content contracts | required |
| `AGENT-CONTEXT.md` | file | UPS-AGENT: agent context files, `.claude/` baseline, SCHEMA pyramid, guardrails | required |
| `QUALITY.md` | file | UPS-QA: lint/format/test/CI/commits/releases/dependencies | required |
| `FRONTEND.md` | file | UPS-FE: design tokens, core components, accessibility, SEO, analytics, UX gate | required |
| `FEEDBACK.md` | file | UPS-FB: the universal feedback → GitHub issue component contract | required |
| `BACKEND.md` | file | UPS-BE: HTTP API conventions and the client contract | required |
| `OPERATIONS.md` | file | UPS-OPS: config, logging, error reporting, security, secrets, data | required |
| `WORK.md` | file | UPS-WORK: SDLC profile, backlog of record, Definition of Done, ADRs, changelog, pinned shared workflows, freshness | required |
| `WORK.contract.yml` | file | Machine-checkable contract for the UPS-WORK rows (paths, keys, regexes per id) that `tools/conformance.py` is keyed to; hand-written, not generated | required |
| `QUALITY.contract.yml` | file | Machine-checkable contract for the UPS-QA site-quality rows (60..63; draft, `rollout: warn`): paths, schema, ref rule and result per id; hand-written, not generated | required |
| `STACKS.md` | file | Stack-family profiles and the applicability matrix | required |
| `CONFORMANCE.md` | file | Declaring, auditing, and adopting the spec; the fleet gap list | required |

## Placement

- New area → `specs/<AREA-TOPIC>.md` + an `areas:` entry and rows in `_data/specs.yml` + a row in the README table.
- New requirement → a row in the area file **and** `_data/specs.yml`, next free id.
- Reference implementation for a requirement → `templates/<kit>/` (registered in `templates/SCHEMA.md`), never here.

## Forbidden

- No code or seedable files here — specs describe, kits provide.
- No secret values, tokens, or per-repo overrides.
- No editing a row's semantics in place: retire the id and add a new one.

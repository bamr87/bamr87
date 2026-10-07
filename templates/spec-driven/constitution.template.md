<!-- kit: spec-driven v__KIT_VERSION__ · lands at docs/constitution.md. The non-negotiables every spec is checked against;
     section list distilled from bamr87/law-ai docs/constitution.md. Keep what applies; amend only by ADR (docs/adr/). -->
# __PROJECT_NAME__ — Constitution

## 1. Mission alignment

TODO: who the project serves, and the changes it rejects outright.

## 2. Tech stack

TODO: the locked stack. Changing it needs an ADR.

## 3. Code quality gates

TODO: the lint, type and format gates every change passes.

## 4. Testing standards

TODO: what must be tested, and the coverage floor.

## 5. Security baselines

TODO: secrets, untrusted input, permissions.

## 6. Human in the loop

TODO: what agents may never do (for example: merge, change settings, delete data).

## 7. Spec-driven workflow

`/specify` → `/clarify` → `/plan` → `/tasks` → `/implement` → `/evolve`. Specs live in `specs/NNN-slug/` and are gated by `tools/spec_validator.py`; follow-ups go to `BACKLOG.md`.

## 8. Documentation

README-First, README-Last; `docs/README.md` is the index; `AGENTS.md` is the canonical agent guide.

## 9. Autonomy and kill switches

TODO: which lanes run unattended, and their `<LANE>_ENABLED` switches (default off).

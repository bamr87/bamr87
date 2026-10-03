<!-- kit: sdlc v__KIT_VERSION__ · AGENTS.md is the CANONICAL agent instructions file (decision D4, UPS-AGENT-07/08).
     Keep these six `##` headings, in this order. CLAUDE.md is a pointer to this file and carries no rules of its own. -->

# __PROJECT_NAME__

## What this repo is

TODO: one paragraph. Who it serves, and what "done" means for a change here.

## Stack & commands

```bash
# TODO: the exact commands. An agent runs these verbatim.
# install:
# run:
# test:
# lint:
# build:
```

## Layout

TODO: the top-level directories and what lives in each, or "see `SCHEMA.md`".

## Conventions

- **Backlog of record:** GitHub Issues with the fleet labels. Pick up issues labelled `agent:ready`; never touch `agent:hold` or `human-review`. <!-- File-backlog repos: "BACKLOG.md (append-only, BL-YYYYMMDD-NN), declared in .github/sdlc.yml" -->
- **Definition of Done:** the checklist in `.github/pull_request_template.md` (the fleet default is inherited when the repo has none). Every box is ticked before merge.
- **Decisions:** ADRs in `docs/adr/NNNN-slug.md`, indexed in `docs/adr/README.md`. Add one for anything hard to reverse.
- **Commits:** Conventional Commits (`feat fix docs style refactor test chore perf ci build`). The PR title is the squash subject.
- **Branches:** `feature/`, `fix/`, `docs/`, `refactor/`, `test/` or `chore/` off `__DEFAULT_BRANCH__`.
- **Changelog:** `CHANGELOG.md` is written by release-please from the PR titles. Never edit it, or a version number, by hand.
- **Never:** push to `__DEFAULT_BRANCH__` directly, commit lockfiles or secrets, suppress type errors, leave empty exception handlers, or edit generated files by hand.

## Fleet context

Member of the bamr87 fleet. The standards live in the hub: <https://github.com/bamr87/bamr87/tree/main/specs> (the Universal Project Standard). The repo's SDLC declaration is `.github/sdlc.yml`. Commit here first; the hub bumps its submodule pointer afterwards.

## Standard deviations

none
<!-- Or one line per waived row, matching .github/sdlc.yml `deviations:`:
- UPS-WORK-07 waived until 2027-01-01: reason -->

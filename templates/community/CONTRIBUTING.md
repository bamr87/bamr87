<!-- kit: community v__KIT_VERSION__ · the fleet default CONTRIBUTING (UPS-REPO-15). Inherited from the owner's
     .github repo by every repo without its own; a repo adds its own copy only to document EXTRA gates. -->

# Contributing

Thanks for helping. This is the default guide for every repo in the bamr87 fleet. If a repo has its own `CONTRIBUTING.md`, read that too: it adds repo-specific gates on top of this one.

## 1. Pick the work

- **Backlog of record: GitHub Issues** with the fleet labels. Work that is ready to pick up is labelled `agent:ready`. To propose something new, open an issue with one of the forms; it enters triage as `agent:queued`.
- A few repos declare a **file backlog** instead (`BACKLOG.md` in spec-driven repos, `_data/backlog.yml` in others). They say so in `.github/sdlc.yml` and in `AGENTS.md`, and CI lints the file. In those repos, pick from the file's open items, and never delete an item: move it to Done.
- Never pick up anything labelled `agent:hold` or `human-review` without asking.

## 2. Branch

Branch off the default branch: `feature/…`, `fix/…`, `docs/…`, `refactor/…`, `test/…` or `chore/…`. Never push to the default branch directly.

## 3. Read the agent instructions

`AGENTS.md` is the canonical guide for humans and agents alike: what the repo is, the exact install, run, test, lint and build commands, the layout, and the conventions. (`CLAUDE.md` is a pointer to it.) Read the nearest `README.md` before changing a directory, and update it afterwards (README-First, README-Last).

## 4. Commit with Conventional Commits

`type(scope): description`, with types `feat fix docs style refactor test chore perf ci build`. Squash-merge is the default, so **the PR title is the commit that lands**, and it drives the next version:

| Title | Release effect |
| --- | --- |
| `fix: …` | patch |
| `feat: …` | minor |
| `feat!: …`, or a `BREAKING CHANGE:` footer | major |
| `docs: …` | patch in docs and content repos (their release config counts documentation as the product); no release elsewhere |
| `chore:` `refactor:` `test:` `ci:` `perf:` `style:` `build:` | no release on their own |

## 5. Run the gates locally

Run the commands in `AGENTS.md` § Stack & commands before you push. Spec-driven repos also run `python3 tools/spec_validator.py --strict` and `python3 tools/backlog_lint.py`. The CI gate (the hub's reusable `standard-ci.yml`, or the repo's own `ci.yml`) is the source of truth.

## 6. Open the pull request

Fill in the template and tick every box in the **Definition of Done**. A box that does not apply says why. Link the issue (`Closes #N`) or the backlog item.

## 7. Record decisions and follow-ups

- Anything hard to reverse (stack, data model, security model, what automation may do) gets an ADR: `docs/adr/NNNN-slug.md`, from `docs/adr/0000-template.md`.
- Work you discover along the way goes into the backlog of record as a new issue or item. It is never left implicit in a PR comment.

## 8. Releases

Every repo keeps a `CHANGELOG.md`, and none of them are written by hand. release-please opens a release PR from the Conventional Commit titles; merging it bumps the version, updates `CHANGELOG.md`, tags `vX.Y.Z` and creates the GitHub Release. Never edit version numbers or the changelog by hand.

## Submodule rule

Most fleet repos are also vendored into the hub ([bamr87/bamr87](https://github.com/bamr87/bamr87)) as git submodules. Commit and push **here** first; the hub bumps its pointer afterwards.

## Standards

The fleet standard (UPS) lives in [bamr87/bamr87 `specs/`](https://github.com/bamr87/bamr87/tree/main/specs). A deliberate deviation is recorded in the repo's `AGENTS.md` under `## Standard deviations`, with a one-line reason.

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

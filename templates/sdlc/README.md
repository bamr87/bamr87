# SDLC kit

The core per-repo files that make every fleet repo follow one delivery loop: declare the SDLC profile, keep one backlog of record, record decisions, and let release-please write the changelog. It seeds UPS-WORK-01/04/05/12, UPS-AGENT-07/08/09, UPS-REPO-21 and UPS-QA-32/33. The rules are in [`specs/WORK.md`](../../specs/WORK.md); the machine contract a conformance check reads is [`specs/WORK.contract.yml`](../../specs/WORK.contract.yml).

The community-health files (PR template with the Definition of Done, issue forms, labels, CONTRIBUTING, SECURITY) are the separate [`community/`](../community/README.md) kit, inherited through the owner `.github` repos. The spec-driven module's tools are the separate `spec-driven/` kit.

## Decisions baked in

All settled on 2026-10-03; nothing here is a switch.

- **D1** — the backlog of record is GitHub Issues with the fleet labels. `backlog.mode: file` is the declared exception.
- **D2** — ADRs in law-ai's format at `adr_path` (default `docs/adr`).
- **D4** — `AGENTS.md` is canonical; `CLAUDE.md` is a pointer that imports it with `@AGENTS.md`. `.claude/commands/` stay.
- **D5** — every repo, content repos included, has a `CHANGELOG.md` written by release-please through the hub's reusable workflow. Nobody maintains it by hand.
- **D6** — `type:` is one of `app`, `library`, `site`, `docs`, `demo`, `control-plane`, `fork`, mapped onto UPS kinds.

## Files

| Kit file | Lands at | Requirement |
| --- | --- | --- |
| `sdlc.yml` | `.github/sdlc.yml` | UPS-WORK-01 |
| `sdlc.schema.json` | stays in the hub | the JSON Schema (2020-12) `.github/sdlc.yml` must validate against |
| `AGENTS.template.md` | `AGENTS.md` | UPS-AGENT-07/09, UPS-WORK-12 |
| `CLAUDE.template.md` | `CLAUDE.md` | UPS-AGENT-08 |
| `CHANGELOG.template.md` | `CHANGELOG.md` (only when absent) | UPS-REPO-21, UPS-WORK-05 |
| `docs/README.template.md` | `docs/README.md` (only when absent) | — |
| `docs/adr/README.md`, `0000-template.md`, `0001-record-architecture-decisions.md` | `docs/adr/` | UPS-WORK-04/13 |
| `release/release.yml` | `.github/workflows/release.yml` | UPS-REPO-21, UPS-QA-32/33 |
| `release/release-please-config.<type>.json` | `release-please-config.json` (pick one) | UPS-REPO-21 |
| `release/.release-please-manifest.json` | `.release-please-manifest.json` | UPS-REPO-21 |
| `content-queue/backlog.yml` | `_data/backlog.yml` (module `content_queue` only) | — |
| `test_sdlc_kit.py` | — | the kit's own tests |

## Release type by repo type (D5)

| `type` | config to copy | why |
| --- | --- | --- |
| `docs`, `site`, `demo`, `control-plane` | `release-please-config.simple.json` | version + CHANGELOG + GitHub Release, no package; `docs` commits are a visible, releasable section so content-only changes still cut a release |
| `app`, `library` with a `package.json` that is not private | `release-please-config.node.json` | bumps `package.json` |
| `app`, `library` with `pyproject.toml` packaging metadata | `release-please-config.python.json` | bumps `pyproject.toml` |
| `app`, `library` with a `*.gemspec` | `release-please-config.ruby.json` | bumps `lib/<gem>/version.rb` (fix `version-file` if the gem name differs) |
| any other `app` or `library` | `release-please-config.simple.json` | |
| `fork` | none | forks keep upstream's changelog |

All four configs share one Keep-a-Changelog section map (`feat` → Added, `fix` → Fixed, `perf`/`refactor`/`deps` → Changed, `revert` → Removed). They differ only in `release-type`, the ruby `version-file`, and whether `docs` is visible (only in `simple`). `tools/adopt-release.sh` picks the same release type by the same detection.

The caller, `release/release.yml`, references `bamr87/bamr87/.github/workflows/release-please.yml@v1`. Tags are cut by Fleet Ops (scheme in `docs/WORKFLOW-VERSIONING.md`); never point it at `@main` (UPS-WORK-10).

## Backlog of record, issue mode (the default)

- **Item** = one GitHub issue. Its type label comes from the issue form; its state starts at `agent:queued`.
- **Triage** (Repo Janitor or a human) adds a priority `P0`–`P3` and a `size:*`, then moves it to `agent:ready`.
- **Claim**: a PR that `Closes #N` moves the issue to `agent:in-pr`; merging moves it to `agent:done`.
- **Brakes**: `agent:hold` and `human-review` are honoured by every automation (UPS-AGENT-32).
- **Cross-repo initiatives** live in the hub's `_data/roadmap.yml` (`FF-NNNN`) and link the issues; per-repo planning files hold no item lists (UPS-WORK-11).

In file mode (`backlog.mode: file`), the declared `BACKLOG.md` or `_data/backlog.yml` is the backlog of record and a CI job lints it (UPS-WORK-02). Spec-driven repos use the `spec-driven/` kit's `backlog_lint.py`.

## Adopting it in a repo

1. Copy the files per the table, substituting `__PROJECT_NAME__`, `__DEFAULT_BRANCH__` and `__KIT_VERSION__`.
2. Set `type`, `kinds` (only when the type default is wrong), `tier`, `backlog`, `modules` and `release.type` in `.github/sdlc.yml`.
3. Fill every `TODO:` line in `AGENTS.md`. Move any rules from an existing `CLAUDE.md` into `AGENTS.md`, then replace `CLAUDE.md` with the pointer.
4. Pick the release-please config for the repo's type. Set the manifest to the current version, and the CHANGELOG's baseline heading to match.
5. Run `python3 templates/sdlc/test_sdlc_kit.py --target <repo>` from the hub to validate the profile against the schema.

## Changing the kit

Snapshot any file you change into `archive/` first, bump `VERSION`, and run `python3 templates/sdlc/test_sdlc_kit.py`. A change to `sdlc.schema.json` is a contract change: update `specs/WORK.contract.yml` in the same PR.

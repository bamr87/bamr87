<!-- kit: governance v0.1.0 -->
# 0002 — Assign sequential ids at merge, not in a pull request

- **Status:** ratified
- **Number:** 0002
- **Date:** 2026-10-29
- **Proposed by:** agent (Claude Opus 5, on a branch opened by bamr87)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/440 (merged 2026-10-30 by @bamr87)
- **Affects:** constitution §2 (invariants), §5 (how the artifacts relate), §6 (change process), §8 (amendments); PRD FR28, NFR11; feature HUB-035
- **Supersedes:** none
- **Related:** [docs/JEV.md](../JEV.md), [tools/jev/README.md](../../tools/jev/README.md), [docs/DEPENDENCIES.md](../DEPENDENCIES.md), [specs/WORK.md](../../specs/WORK.md) UPS-WORK-15 / UPS-WORK-16

## Context

Every sequential id in this repository is chosen by whoever opens a pull request, from the state of `main` at the moment they looked. That is a read-modify-write with no lock, and the fleet now runs enough parallel work — four scheduled agent loops, a three-tier issue pipeline, seven fan-outs and a human — that the race is routine rather than theoretical.

It shows up in six places, and each one fails differently:

- **`features/features.yml`.** Two branches both append `HUB-033`. Git reports a conflict on the last line of the file, which is annoying; the dangerous case is the one where it does not, because the branches appended in different places. Then `main` has two features with one id, and the PRD trace, the fleet index and every issue that cites the id are all quietly wrong.
- **PRD requirement ids.** `FR28` and `NFR11` are picked the same way, from the same stale read, with the same two outcomes.
- **Amendment numbers.** Two proposals both read `0001` and both write `0002-*.md`. The file names differ, so **git reports nothing at all** — there is no conflict to resolve, only two amendment 0002s in an append-only log that promises numbers are never reused.
- **`CHANGELOG.md`.** Every pull request that announces anything edits the same handful of lines under the same `## [Unreleased]` heading. The conflict is guaranteed and it is always spurious: two entries never actually disagree.
- **Generated projections.** The PRD's Feature catalog block, `CATALOG.md`, `docs/README.md`, `projects/SCHEMA.md`, `_data/specs.yml`, `_data/cv_portfolio.json` are all derived. Resolving a conflict in one by hand produces a file that looks plausible, passes review, and is wrong until the next regeneration silently rewrites it. Nobody should ever be reading those diffs, and today everybody does.
- **Committed `_data` lists.** Several are pure appends where order carries no meaning, and git conflicts on them anyway.

The cost is not the merge itself. It is that the resolutions are *hand-made*, on files whose correct content is a function of something else, by whoever happens to be on the pull request — including an agent, which is exactly the situation in which a plausible-looking wrong answer is least likely to be caught.

The constitution already says the right thing about one of these (§5: the PRD's feature block and `CHANGELOG.md` are generated and never hand-edited). It does not say what that implies for a *merge*, and it says nothing about who picks a number.

## Amendment

Four changes to [the constitution](../constitution.md).

**§2 (Invariants) — add:**

> - A pull request never assigns a sequential id. New entries carry a placeholder (`HUB-NEW`, `FR-NEW:<key>`, `NFR-NEW:<key>`, `number: NEW`) and reference each other by slug; the number is assigned on the default branch, by one serialized process, and is never reused. _(amendment 0002)_
> - A generated file is never hand-merged. Its conflicts are resolved by regenerating it, and CI fails on drift rather than trusting the resolution. _(amendment 0002)_

**§5 (How the artifacts relate) — add three rows and amend two:**

> | `features/features.d/<slug>.yml` | What a pull request is adding | Proposer | One entry per file, `id: HUB-NEW`; compiled into `features/features.yml` at merge |
> | `changelog.d/<slug>.md` | What a pull request is announcing | Proposer | Keep a Changelog fragment; folded into `CHANGELOG.md`'s `[Unreleased]` at merge |
> | `docs/amendments/proposed/<slug>.md` | A proposal awaiting a number | Proposer | `**Number:** NEW`; numbered, moved and indexed at merge |
>
> `features/features.yml` and `CHANGELOG.md` gain the rule **"Compiled from fragments at merge; not edited by a pull request"**.

**§6 (Change process) — the "Required in the same PR" column becomes:**

> | New or changed user-facing feature | A `features/features.d/<slug>.yml` fragment (`status`, `link`/`docs`, `prd:`) — not a row in `features/features.yml` |
> | New or changed requirement | The requirement declared in that fragment's `prd_new:` with a slug key; ids are assigned at merge and never reused |
> | Change to this constitution | A record in `docs/amendments/proposed/<slug>.md` (§8) |

**§8 (Amendments) — step 1 becomes:**

> 1. **Propose** — open a PR that adds the record as `docs/amendments/proposed/<kebab-slug>.md` with `**Number:** NEW` (copied from [0000-template.md](0000-template.md)) *and* the edit to this file it describes. Name what it affects. The number is assigned when the PR is merged, by `tools/jev/number.py`; a record that has been numbered is append-only history and is never renumbered.

Steps 2–4 are unchanged: an agent never approves or merges its own amendment, merging ratifies, numbers are never reused.

## Consequences

**For a human or an agent opening a pull request.** Three new files instead of three edits to shared ones. `python3 -m tools.jev number next` still answers "what number will this get?" — it just answers it as information, not as a commitment. Nothing about review, Definition of Done or the gates changes.

**For the default branch.** `.github/workflows/jev-number.yml` runs on every push to `main` that touches a fragment directory, under a `concurrency: jev-number` group so assignment is serialized. It assigns the next free id, compiles the fragments into `features/features.yml`, `PRD.md`, `CHANGELOG.md` and `docs/amendments/NNNN-*.md`, rewrites every slug reference to its number, regenerates the PRD feature block, the docs index and `CATALOG.md`, and publishes through `.github/actions/utilities/publish-data` — the hub's sanctioned bot-commit path, which falls back to a pull request when branch protection refuses a push. No `--admin`, no force-push to a protected branch.

**For merges.** `.gitattributes` marks every generated file `merge=jev-regen` (a driver that keeps *ours* and records the path for regeneration — `tools/jev/merge-regen.sh`, opt-in per clone with `git config merge.jev-regen.driver`) and marks two genuinely append-only files `merge=union`. CI regenerates and fails on drift, so the merge resolution never decides a generated file's content.

**For the transition.** Nothing existing moves. `HUB-001`–`HUB-032`, `FR1`–`FR27`, `NFR1`–`NFR10` and amendment `0001` keep their numbers and their places. `governance_lint.py` and `features_index.py` keep reading the compiled files exactly as they do now, and the fragment directories are additive. The lint that rejects a hand-picked next number (`python3 -m tools.jev number lint`) reports on every pull request from today and **gates** only when `_data/fleet.yml` `jev.numbering.enforce` is set to `true` — which is a one-line change to make after ratification, and which this pull request deliberately does not make, since it adds `HUB-033`, `FR28` and `NFR11` by hand under the old rule.

**What this does not claim.** The scheme removes the *mechanical* collisions. Two features that genuinely overlap still need a human to notice; two amendments that contradict each other still need one to be withdrawn. It buys correctness on ids, not on judgement.

## Fan-out plan

After ratification, in this order. Each step is a `tools/fanout.sh` pass — dry run first, additive, PR-only, never merged by the agent — and each waits for the previous one to be green in the fleet.

| # | Scope | What goes out | Why this order |
| --- | --- | --- | --- |
| 1 | **The hub** (this PR) | The scheme, `tools/jev/`, both workflows, the docs | The hub proves the kit on itself before anyone else runs it; `jev.numbering.enforce` flips to `true` here first |
| 2 | **`bamr87/SCHEMA`** | The `features.d` / `changelog.d` / `proposed` `SCHEMA.md` files | The schema kit is vendored FROM this repo (docs/SCHEMA-FRAMEWORK.md): improvements go upstream first, then re-vendor, or the fleet's copies drift |
| 3 | **`templates/governance/`** → every repo that already has the governance kit | `features/features.d/`, `docs/amendments/proposed/`, the amended constitution §2/§5/§6/§8 text, `number.py` by reference | These repos already carry a constitution and an amendment log, so they have the exact collision this fixes |
| 4 | **The four repos with the most parallel agent traffic** — `it-journey`, `zer0-mistakes`, `README`, `gitorio` | The full kit including `.gitattributes` and the merge driver | Highest conflict rate, and the loudest signal if anything is wrong |
| 5 | **Repos where release-please owns `CHANGELOG.md`** | Everything EXCEPT `changelog.d/` | release-please already solves the changelog race; a second compiler on the same file would fight it |
| 6 | **The rest of the registry** (`auto_evolve` opt-ins first) | The full kit | Routine once 3–5 are green |
| 7 | **Follow-up, not part of this fan-out** | Update `bamr87/it-journey`'s `scripts/prd-machine/prd-machine.py` input to mark the JEV row (Roadmap, 2027 Q1) as *in progress: first capability = conflict triage, `bamr87/bamr87` `tools/jev`* | That PRD is generated; it is edited at its source, in its own repo, in its own pull request — never here |

A repo opts out by not taking the pull request. Nothing in the hub depends on a fleet repo having adopted the scheme.

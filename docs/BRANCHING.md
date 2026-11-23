# Branching

> The fleet's branch model in one place: `main` is the only long-lived branch, every other branch is short-lived and named for what made it, every change lands by pull request with a merge commit, and the default branch carries one ruleset that enforces exactly that.

| | |
| --- | --- |
| **Policy** | `_data/fleet.yml` `branches:` (the prefixes, the merge method, the protection's shape) |
| **Tool** | [`tools/branch_policy.py`](../tools/branch_policy.py) (`classify`, `protect`, `check`), wrapped by [`tools/protect-branch.sh`](../tools/protect-branch.sh) and `tools/dash protect` |
| **Standard** | [UPS-QA-35](../specs/QUALITY.md) (names), [UPS-QA-36](../specs/QUALITY.md) (the ruleset), [UPS-QA-24](../specs/QUALITY.md) (the CI gate), [UPS-QA-34](../specs/QUALITY.md) (submodules) |
| **Rules it serves** | [constitution § 12](constitution.md) (merge authority and the review gate), § 4 (who changes branch protection) |
| **Decision** | [ADR 0015](adr/0015-branch-model-and-fleet-ruleset.md) |
| **Tests** | `python3 tools/test_branch_policy.py` (offline; `gh api` is a fake) |

## The model

1. **One trunk.** Every repo's default branch is `main`, and every submodule tracks it (read the branch from `.gitmodules` all the same: [SUBMODULES.md](SUBMODULES.md)). There is no `develop` and no `release/*`. Versions come from tags that release-please cuts on `main` ([RELEASES.md](RELEASES.md)), and a reusable workflow is referenced at a tag or a SHA, never `@main` (UPS-WORK-10), so a push to `main` cannot break a caller.
2. **Short-lived branches, named for what made them.** The prefix says whose branch it is, and tools read it (the next section).
3. **Nothing is pushed to `main`.** Every change arrives by pull request. The two sanctioned exceptions both go through [`publish-data`](../.github/actions/utilities/publish-data/action.yml), which pushes when protection allows and otherwise opens a pull request: the data snapshots the loops publish, and the daily submodule pointer bumps (each SHA was reviewed in its own repo).
4. **A merge commit, never a squash or a rebase** (constitution § 12.2). The history keeps the commits a reviewer saw. A branch that falls behind has its base merged in, never rebased: the PR queue's `update-branch` and JEV's conflict tiers both do that ([JEV.md](JEV.md)). A merge-commit flow does not need an up-to-date head, so the ruleset does not require one.
5. **Conflicts are prevented, not resolved.** A pull request never picks the next number: it writes a fragment (`HUB-NEW`, `FF-NEW`, `number: NEW`) and `jev-number.yml` assigns the id on `main` (amendment 0002). The fully generated `CATALOG.md` and `docs/README.md` are regenerated on `main` only, and CI fails a pull request that edits them (amendment 0004).
6. **Who merges.** An agent merges only a pull request that is mergeable and not held by the review gate (§ 12.1–12.2). A gated pull request (`needs-amr`: governance, ADRs, secrets, settings, branch protection, deploys, non-trivial conflict resolutions) is the maintainer's, and the merge is the ratification (§ 12.3–12.5).
7. **Local work is never lost.** Commits that exist only on the Mac are mirrored to `wip/mac/<branch>` on their repo's own remote by the weekly close-out, after a secret scan and the maintainer's `confirm --apply` ([WEEKLY.md](WEEKLY.md)).

## Branch names

`python3 tools/branch_policy.py classify <name>` says which kind a name is. The longest declared prefix wins, so `chore/jev-ratify` is automation although `chore/` is a work prefix.

| Kind | Prefixes | Who opens it | What follows from it |
| --- | --- | --- | --- |
| **work** | a Conventional Commit type, `feat/ fix/ docs/ style/ refactor/ perf/ test/ build/ ci/ chore/`, or `feature/` | a person, or an agent at a person's request | reviewed and ratified like any change; the hub's fan-outs reuse stable work branches (`chore/standardize-baseline`, `ci/pr-review`, …) named in their own code |
| **session** | `claude/` | a Claude Code cloud session, whose platform names the branch | a person directed it, so it is work: its merge ratifies what it carries |
| **automation** | `agent/issue-`, `ai-evolution/`, `chore/jev-`, `wip/mac/`, `wtd/`, `dependabot/`, `release-please--` | a loop, which creates, reuses and deletes the branch | a person does not push to it; jev ratify does not count a merge from `wtd/`, `dependabot/` or a workflow's own `branch:` as a ratification ([JEV.md](JEV.md#ratification-records)) |

A name that matches nothing is `unknown`. The hub's drift check (s) warns on a pull request whose head is unknown, and `test_branch_policy.py` fails when a branch name the hub's own tools create is not declared. To add a loop, declare its prefix in `_data/fleet.yml` `branches.automation` with its owner, in the same pull request as the loop.

## The fleet ruleset

`tools/dash protect <repo>` plans one ruleset, `fleet-default-branch`, on the repo's default branch. It is a dry run unless `--apply` is given, and only the maintainer applies it: an agent never changes branch protection (constitution § 4), but may plan it and audit it.

| Rule | Setting | Why |
| --- | --- | --- |
| Target | `~DEFAULT_BRANCH` | follows a rename of the default branch |
| Pull request | required; **merge commit the only allowed method** | § 12.2, enforced by GitHub rather than by each agent's prompt |
| Approvals | 0 (`--approvals N` where the repo's own constitution asks for review) | the review gate is the `needs-amr` label (§ 12.3–12.4). Agents open pull requests with the maintainer's token, so the maintainer is the author, and GitHub never lets an author approve their own pull request: a required approval is one nobody can give |
| Required checks | named with `--checks`, as the check run reports (a reusable-workflow caller job `ci` reports as `ci / ci`) | UPS-QA-24. A name that has not reported on the default branch is refused, because a required check that never reports holds every pull request; `--allow-unseen` admits one that runs only on pull requests |
| Up to date before merge | off (`--strict` turns it on) | a merge commit does not need it, and with dozens of open agent pull requests it would re-run CI on all of them after every merge |
| Force push, deletion | blocked | the trunk's history is the record |
| Linear history | **never** | it forbids the merge commit § 12.2 requires; the policy refuses to load if asked for it |
| Bypass | repository admins (`--enforce-admins` removes it) | parity with the classic protection's default, so `publish-data`'s sanctioned push under `FLEET_TOKEN` still lands |

The ruleset is created or updated by name, so other rulesets and settings a person made are left alone. A re-run without `--checks` or `--approvals` keeps the live ruleset's values, so a plan changes only what the policy or the flags change.

```bash
tools/dash protect bamr87/zer0-mistakes --checks 'ci / ci'
```

```bash
tools/dash protect bamr87/zer0-mistakes --checks 'ci / ci' --apply
```

```bash
tools/dash protect --all --check
```

`--check` is read-only and exits 1 on an error finding. It reads what GitHub enforces on the branch from every source (`GET repos/{repo}/rules/branches/{branch}`) and the classic protection beside it, and reports: a linear-history rule from any source, a ruleset that allows only squash or rebase, the repo setting that turns merge commits off, a required approval, a required check that has not reported on the default branch, a missing fleet ruleset, and no required check at all.

### Moving off the old protection

Until 2026-11, `tools/protect-branch.sh` PUT classic branch protection: linear history, one required approval, the checks up to date, and `CI / ci` as the required check. Each of those blocks the fleet's own flow: linear history forbids § 12.2's merge commit, the approval cannot be given on an agent's pull request, and `CI / ci` is the checks page's label (`<workflow> / <job>`) rather than the check run's name (`ci / ci`), so it never reports. A repo that still carries it shows those findings under `--check`. `--apply --drop-classic` writes the ruleset first and then deletes the classic protection, so the branch is never left unprotected.

### Limits

- **Private repos** need GitHub Pro (or a paid organisation plan) for rulesets and for classic protection alike. The tool says so when it cannot read the rulesets.
- **The hub itself** is not in `dash protect --all`, which walks the active submodules. The hub's loops publish straight to `main` through `publish-data` (`jev-number.yml` with `FLEET_TOKEN`, falling back to `GITHUB_TOKEN`, which an admin bypass does not cover), so each publisher is checked against the bypass before the hub gets the ruleset: ADR 0015's later phase.
- **Merge-method wording in the kits.** The community kit's Definition of Done and `CONTRIBUTING.md`, and the sdlc kit's `AGENTS.md` template, still say the pull request title is the squash subject. Changing the Definition of Done is a fleet rollout (a `fleet-dod` v2 that every repo's conformance check compares, and the inherited copy in `bamr87/.github`), so it is ADR 0015's second phase rather than part of the first.

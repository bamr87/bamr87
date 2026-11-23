# ADR 0015 — The branch model, declared once: work, session and automation prefixes, and one ruleset per repo that allows only the merge commit § 12.2 requires

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/954 (merged 2026-11-23 by @bamr87)
- **Date**: 2026-11-21
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-21: "fix all, and make any improvements where possible; identify a redesign if needed", after a review of the fleet's branch philosophy found the protection tool contradicting constitution § 12)
- **Related**: constitution § 4 (who changes branch protection), § 12 (merge authority and the review gate); [specs/QUALITY.md](../../specs/QUALITY.md) UPS-QA-24, UPS-QA-31 (retired here), UPS-QA-35 and UPS-QA-36 (added here); [docs/BRANCHING.md](../BRANCHING.md); [ADR 0012](0012-merge-readiness.md) (merge readiness, whose queue reads the merge method a repo allows)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

The fleet's branch philosophy is sound and mostly unwritten: `main` is the only long-lived branch, everything lands by pull request with a merge commit (§ 12.2), ids are assigned at merge so branches do not collide (amendment 0002), and submodules are committed in their own repo first (UPS-QA-34). It was spread across the constitution, five docs, a spec row and the tools. Read side by side on 2026-11-21, three of those sources contradicted § 12:

- **`tools/protect-branch.sh`, wrapped by `dash protect --all`, set classic protection that blocks the fleet's own merges.** It required linear history, which forbids the merge commit § 12.2 gives every agent merge. It required one approving review, but agents open pull requests with the maintainer's token, so the maintainer is the author and GitHub never lets an author approve their own pull request. Its default required check, `CI / ci`, is the checks page's `<workflow> / <job>` label; the check run the standard CI caller produces is named `ci / ci`, so the required check never reports and every pull request waits on it. It also PUT the whole protection, replacing whatever a person had set, and it applied on every run, with no plan.
- **UPS-QA-31 named branch prefixes the hub's own tools do not use.** It allowed `feature/ fix/ docs/ refactor/ test/ chore/`. `tools/fanout.sh` opens `feat/fleet-assist`, `feat/fleet-logging`, `feat/page-feedback`, `ci/pr-review`, `ci/site-quality` and `style/markdown-oneline`; six of the 32 branch names the hub creates broke its own MUST row. It named three automation prefixes; the loops use seven (`agent/issue-`, `ai-evolution/`, `chore/jev-`, `wip/mac/`, `wtd/`, `dependabot/`, `release-please--`), and jev ratify kept its own list of two. Claude Code cloud sessions branch on `claude/`, which the platform chooses, and no row named it.
- **The kits still describe a squash flow.** The community kit's Definition of Done says the pull request title "becomes the squash subject", and its `CONTRIBUTING.md` and the sdlc kit's `AGENTS.md` template say the same.

No repo is known to carry the old protection today (`docs/JEV.md` records that the hub's `main` has no required checks), so the cost so far is latent. It would land the first time anyone ran `dash protect --all`.

### Prior art (§ 10.8)

- **GitHub repository rulesets.** A pull-request rule can name the merge methods it allows (`allowed_merge_methods`), a ruleset is addressed by name and layers with others, and `GET repos/{repo}/rules/branches/{branch}` returns every rule that applies to a branch from every source. That is § 12.2 enforced by the platform, and an audit that sees what GitHub enforces. Rulesets need GitHub Pro on a personal account's private repos, as classic protection does.
- **Classic branch protection.** One object per branch, replaced wholesale by its PUT; no merge-method control (that is a repo setting shared by every branch); linear history is the only history rule it offers.
- **Organisation rulesets.** One definition for every repo. `bamr87` is a personal account, so there is no organisation to hold them (the same reason `_data/fleet.yml` exists).
- **Commit types as branch prefixes.** A common convention (`feat/`, `fix/`, `ci/`, …) that ties a branch's name to the commits it will carry; the hub's fan-outs already followed it.

## Decision

1. **The branch model is declared once, in `_data/fleet.yml` `branches:`.** It holds the default branch, the merge method (`merge`), three kinds of prefix, and the protection's shape. **Work** prefixes are the Conventional Commit types plus `feature/`. **Session** prefixes cover an agent session a person directs (`claude/`); its pull request is that person's work. **Automation** prefixes are namespaces a loop owns, each with its owner. The longest declared prefix wins. The policy refuses to load if it asks for linear history or declares a prefix twice.
2. **`tools/branch_policy.py` is the one implementation.** `classify` names a branch's kind. `protect` plans one ruleset, `fleet-default-branch`, and writes it only with `--apply`. `check` audits a repo's live protection from every source, read-only. `tools/protect-branch.sh` and `tools/dash protect` wrap it.
3. **The ruleset** targets `~DEFAULT_BRANCH` and enforces the rest of the model:
   - **Merge method:** pull requests are required, and a merge commit is the only allowed method.
   - **Approvals:** none required, unless `--approvals N` is given because a repo's own constitution asks for a review. The review gate stays the `needs-amr` label (§ 12.3–12.4).
   - **Checks:** only checks named as their check runs report, and a name that has not reported on the default branch is refused unless `--allow-unseen`. The branch need not be up to date with its base (`--strict` turns that on).
   - **History:** force pushes and deletion are blocked, and there is never a linear-history rule.
   - **Bypass:** repository admins may bypass it, matching classic protection's old default; `--enforce-admins` removes that.

   Rerunning keeps the live values for anything the flags do not name. `--drop-classic` replaces old classic protection only after the ruleset is in place.
4. **Who does what.** Only the maintainer applies the ruleset (§ 4). An agent may plan it and audit it.
5. **The standard follows.** UPS-QA-31 is retired in favour of **UPS-QA-35**, the naming row, which points at the declared prefixes instead of copying them. **UPS-QA-36** (SHOULD) is the ruleset's shape, checked by `dash protect --check`. UPS-QA-24 now names `dash protect` as the way to meet and check it.
6. **Drift is caught where it starts.**
   - **Hub tests:** `test_branch_policy.py` fails when a branch name the hub's own tools create is undeclared, or when jev ratify's automation prefixes are not in the declared automation list.
   - **Pull requests:** the drift gate's check (s) gates on the policy loading, and warns on a pull request whose head branch matches no declared prefix.

### Phases

| Phase | Delivers | Done when |
| --- | --- | --- |
| P0, this pull request | The policy block, `tools/branch_policy.py` and its tests, the wrapper and `dash protect`, UPS-QA-35/36, drift check (s), [docs/BRANCHING.md](../BRANCHING.md) | `tools/dash protect <repo>` prints a plan and writes nothing; `--check` finds the old protection's three faults on a fixture |
| P1 | The fleet audit and adoption: the maintainer runs `tools/dash protect --all --check`, then applies the ruleset repo by repo with each repo's CI gate named | Every active public repo passes `--check`; private repos are listed with the plan they lack |
| P2 | The merge method in the kits: a `fleet-dod` v2 whose title box drops "squash subject", the community kit's `CONTRIBUTING.md` and the sdlc kit's `AGENTS.md` template (each snapshotted into `archive/` first), and the inherited copies in `bamr87/.github` | UPS-WORK-03 passes on v2 across the fleet, and no kit says squash |
| P3 | The hub's own ruleset, after each publisher that pushes to the hub's `main` is checked against the bypass (`publish-data` falls back to a pull request where it is refused) | The hub's `main` carries the ruleset and every loop still publishes |

## Consequences

**Positive**

- § 12.2 is enforced by GitHub rather than by each agent's prompt. A squash or rebase button is not offered where the ruleset applies.
- `dash protect` can no longer block every merge in a repo: it plans first, refuses a required check that never reports, refuses when the repo setting turns merge commits off, and leaves other people's protection alone.
- One list of branch prefixes, read by the tool, the drift gate, the spec and the tests, replaces three lists that disagreed.
- The audit reports what GitHub enforces on the branch, from every source, instead of what one API returns.

**Negative**

- Rulesets are a second protection mechanism beside classic protection until a repo drops its classic one; `--check` reads both.
- A required approval is no longer the default. A repo that wants human approval on every change must say so with `--approvals`, and its constitution must name it (§ 12.4).
- The admin bypass keeps the old default's escape hatch: the maintainer's token, and `FLEET_TOKEN` with it, can still push past the ruleset. Removing it waits on P3's review of every publisher.
- Until P2 lands, the kits describe a squash flow that the ruleset does not allow.

## Alternatives considered

- **Fix the classic PUT in place** (linear history off, no approval). It fixes the immediate fault but cannot restrict the merge method, still replaces whatever protection a person set, and leaves the audit reading one API.
- **Squash merges everywhere**, matching the kits instead of § 12.2. It rewrites what a reviewer saw into one commit, the ratification job merges its record pull requests with a merge commit by design (`gh pr merge --merge --match-head-commit`), and it would need a constitutional amendment. The constitution wins over a kit's prose.
- **Required approvals with a bot reviewer.** A distinct bot identity could approve agent pull requests (#565), but an approval from a bot is not a human review, and the review gate already names when a person must look.
- **Enforce branch names with a push ruleset** (`creation` restricted to patterns). Branch names are a convention whose violation costs nothing at merge; a warning on the pull request is enough, and a push rule would block a platform-named branch the policy has not yet declared.

## Supersedes / Superseded by

- Supersedes: none (UPS-QA-31 is retired by this decision; the classic protection `tools/protect-branch.sh` applied before 2026-11 is replaced by the ruleset)
- Superseded by: none

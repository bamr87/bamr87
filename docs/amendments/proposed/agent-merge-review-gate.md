# NEW — Agent merge of mergeable PRs, and a review gate for human review

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-30
- **Proposed by:** Grok Bot (agent), for Amr
- **Ratified by:** (blank until merged)
- **Affects:** constitution § 4, new § 12; AGENTS.md "Never"; feature `HUB-NEW:review-gate`; requirement `FR-NEW:review-gate`
- **Supersedes:** none (§ 8 step 2 and § 11.2 are unchanged)
- **Related:** fleet-wide repo amendments that conform to this one; it-journey editorial charter PR bamr87/it-journey#889; prior-art proposal #480 (no overlap)

## Context

§ 4 forbids an agent from merging its own PRs, so every green, routine PR waits on the maintainer. The fleet rule is changing: agents may merge, but only a PR that meets an explicit *mergeable* definition, and anything that needs human review must pass a review gate first.

## Amendment

§ 4's AI-agent row: "May" gains "merge a PR that is mergeable under § 12"; "May not" changes "Merge its own PRs" to "Merge a PR that is not mergeable under § 12, or any PR the review gate holds".

New § 12 "Merge authority and the review gate" (full text in `docs/constitution.md`):

- **Mergeable PR checklist** — all of: (1) required CI checks green; (2) required reviews satisfied; (3) no merge conflicts; (4) the review gate passed wherever human review is required — rechecked against live state just before merging. Otherwise the agent waits.
- **How** — merge commits only; no squash/rebase, no `--admin` or bypass, no force-push.
- **Gated categories** — amendments, constitution or standards; secrets, tokens, budgets, billing; settings, branch protection, rulesets, permissions; security-sensitive changes; deploys or anything touching the maintainer's machines; non-trivial conflicts; destructive or data-deleting changes; items labelled `agent:hold`, `blocked` or `needs-amr`; repo-specific content gates (e.g. it-journey's editorial charter for structural changes).
- **Mechanism** — `needs-amr` label + Fleet project status *Needs Amr*; passes only on maintainer approval/merge and label removal; optional required review in branch protection, turned on only by the maintainer.
- **Never** — agents never merge gated PRs; amendments are ratified only by the maintainer merging.
- **Conformance** — each repo constitution conforms or files its own amendment.

## Consequences

- Agents may close out routine green PRs; gated work still waits for Amr.
- Each fleet repo with a constitution gets a conforming amendment PR (fan-out).
- Follow-up: a `needs-amr` label and a check that fails while it is present (feature `HUB-NEW:review-gate`); the project status option *Needs Amr* must exist on the Fleet project.

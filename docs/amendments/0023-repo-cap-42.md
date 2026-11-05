# 0023 — The bamr87 account holds at most 42 repositories, and a new repo needs a consolidation

- **Status:** ratified (ratification pending — Amr ratifies by merging this PR)
- **Number:** 0023
- **Date:** 2026-11-04
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:** https://github.com/bamr87/bamr87/pull/660 (merged 2026-11-05 by @bamr87)
- **Affects:** constitution § 22 (new, follows § 21 `container-management`); feature `0023` follow-up (`HUB-NEW`, not created here); requirements: none yet
- **Supersedes:** none
- **Related:** none

## Context

The fleet keeps growing one repository at a time, and each new repo adds maintenance, CI, fan-out PRs and review load. Amr, as owner, sets two hard rules on the size of the `bamr87` user account so the fleet stays small enough to keep healthy.

Repo count at proposal time (2026-11-04, read-only, nothing changed):

- `gh api users/bamr87 --jq .public_repos` → **42**
- `gh repo list bamr87 --limit 500 --json name | jq length` → **42** (all 42 are public; no private repos visible to this token)

The account is therefore **exactly at the cap** — it does not exceed 42, but no repo can be added without first merging or absorbing one.

## Amendment

New constitution section:

> ## 22. Repository cap and consolidation
>
> 1. **Rule 1 — hard cap of 42** — the `bamr87` GitHub user account holds no more than **42 repositories in total** (public and private, archived included) at any time. This is a hard limit, not a target.
> 2. **Rule 2 — consolidate to add** — any request to add a new repository to the `bamr87` account must, in that same request, merge or absorb an existing repository into another one, so the net repository count stays flat or drops. A request without its consolidation is not actioned.
> 3. **At the cap** — a new repository is created only after an existing one has been merged or absorbed into another; Amr decides which.
> 4. **Scope** — the `bamr87` user account only; organisations Amr owns are out of scope (open question below).
> 5. **Enforcement** — detection is a follow-up (for example a sentinel check that counts the account's repositories and fails above 42); agents never create a repository in the account without Amr's approval and the paired consolidation.

## Open questions

- Should organisations owned by Amr have their own cap, or count toward this one?
- Do forks count the same as source repos? (As written: yes, every repository counts.)

## Consequences

- Agents and tools that propose a new repo must name the existing repo being merged or absorbed in the same request.
- Follow-up (not implemented here): a sentinel / fleet check that reads the account's repository count and reports above 42, plus a `HUB-NEW` feature fragment for it.
- Ratification: Amr ratifies this amendment by merging the PR; agents propose, never merge (§ 8).

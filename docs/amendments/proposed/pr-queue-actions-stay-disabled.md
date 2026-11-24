<!-- kit: governance v0.1.0 -->
# NEW — The console PR queue's merge and close stay disabled (completes 0035 with option 3)

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-11-24
- **Proposed by:** Platform Architect (Grok Bot), at the maintainer's direction (2026-11-24: "Draft the 0035 follow-up amendment with option 3"); direction-setting work under § 26.2 and § 28
- **Ratified by:** the merged PR URL (leave blank until merged)
- **Affects:** constitution § 11.2 (one sentence added); amendment [0035](../0035-pr-queue-maintainer-actions.md) (its Status line and index cell become `superseded`); no PRD requirement, feature id or `_data/fleet.yml` value changes
- **Supersedes:** [0035](../0035-pr-queue-maintainer-actions.md) `pr-queue-maintainer-actions`, which was merged in [#905](https://github.com/bamr87/bamr87/pull/905) carrying all three options and no chosen rule; this record completes it with option 3
- **Related:** [bamr87/bamr87#863](https://github.com/bamr87/bamr87/issues/863) (closed as completed 2026-11-18), [bamr87/bamr87#905](https://github.com/bamr87/bamr87/pull/905), [bamr87/bamr87#864](https://github.com/bamr87/bamr87/pull/864) (the PR queue), § 11.1, § 11.2, § 11.8, § 12.2–12.5, § 19.5

## Context

Amendment 0035 asked the maintainer to choose whether a merge or close he confirms in the Harness Console PR queue counts as his own action: option 1 (allow both), option 2 (close only) or option 3 (keep disabled, no constitution change). Its `## Amendment` section said that, before merge, the record would be cut down to the chosen option and the matching constitution edit added in the same pull request.

#905 was merged on 2026-11-18 with all three options still in the record and its `## Amendment` section still reading "Pending Amr's choice". No `docs/constitution.md` edit landed with it, and the post-merge job recorded 0035 as `ratified`. So the log holds a ratified record that states no rule. The shipped state matches option 3 in effect: `_data/fleet.yml` `pr_queue.merge.enabled` and `pr_queue.close.enabled` are both `false`, and § 11.1–11.2 are unchanged.

Records are append-only (§ 8). A numbered record is never rewritten, so the choice is recorded here, and 0035 is marked superseded by this record (§ 8.4).

The maintainer chose option 3 on 2026-11-24.

## Amendment

Option 3 is adopted. The PR queue's merge and close actions stay disabled. A maintainer's confirm in the queue does not make a merge or a close his own action under § 11, and nothing in 0035 authorises either.

Constitution § 11.2 gains one sentence at its end (the rest of the item is unchanged):

> The console PR queue's merge and close actions fall under this item: they stay disabled (`_data/fleet.yml` `pr_queue.merge.enabled` and `pr_queue.close.enabled` are `false`), a maintainer's confirm in the queue does not lift it, and enabling either needs a new ratified amendment that amends this item. _(amendment `pr-queue-actions-stay-disabled`, numbered at merge; completes 0035 with its option 3)_

Amendment 0035's `**Status:**` line and its index status cell read `superseded` by this record. No other text of 0035 changes.

## Consequences

- **No switch or setting changes.** `pr_queue.merge.enabled` and `pr_queue.close.enabled` stay `false`. This pull request does not touch `_data/fleet.yml`, code or any repository setting. A pull request that sets either switch to `true` without a later ratified amendment breaks § 11.2 and is refused (§ 12.3).
- **The six enabled queue actions are unaffected.** Everything else the PR queue does today keeps working under § 11.1 and § 11.8.
- **The maintainer merges and closes on GitHub,** as today.
- **Revisiting it** takes a new amendment that amends § 11.2 and answers 0035's two open questions (does a confirm satisfy § 12.4 for a gated PR, and is a confirmed queue comment still automation under § 19.5?). It should follow two things: the hub's open CodeQL alerts in `tools/console/app.py` are cleared, and the fleet bot-identity decision (#565) is made, so that a queue comment is not posted under the maintainer's account.
- **No PRD, feature catalog or AGENTS.md change** is needed. The PR-queue feature already documents both switches as off.
- Merging this pull request ratifies the amendment. An agent never merges it (§ 8, § 12.5).

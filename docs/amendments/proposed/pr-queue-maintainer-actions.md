<!-- kit: governance v0.1.0 -->
# NEW — A merge or close the maintainer confirms in the console PR queue is his own action

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-11-16
- **Proposed by:** Platform Architect (Grok Bot), from [bamr87/bamr87#863](https://github.com/bamr87/bamr87/issues/863) (direction-setting work under § 26.2 and § 28.5)
- **Ratified by:** (leave blank until merged)
- **Affects:** constitution § 11.1, § 11.2, § 12.2, § 12.4, § 12.5, § 19.5; the PR-queue feature and its bulk-actions requirement and roadmap entry, which #864 proposes as fragments (`features/features.d/pr-queue.yml`); they are cited here by name, not by `NEW` slug reference, so this record numbers cleanly whichever of the two pull requests lands first
- **Supersedes:** none (adds a maintainer-confirm exception; does not let an agent merge or close on its own initiative)
- **Related:** [bamr87/bamr87#863](https://github.com/bamr87/bamr87/issues/863), [bamr87/bamr87#864](https://github.com/bamr87/bamr87/pull/864), § 11.8 OPS remote-write path, amendment `ops-remote-write-path` (0020), `projects-write-back` (0006), `agent-merge-review-gate` (0009), `fleet-pr-review` (0017)

## Context

The Harness Console PR queue (`/prs`, `tools/dash prs`, branch `feature/console-pr-queue`, PR #864) lists every open pull request of the hub and the registry repos and applies bulk actions after Amr confirms a plan rebuilt from live GitHub. Six actions ship enabled. **Merge** and **close** ship disabled behind `_data/fleet.yml` `pr_queue.merge.enabled` and `pr_queue.close.enabled` (both `false`), because the constitution does not yet allow them:

- **§ 11.2:** the console's write-back never merges.
- **§ 11.1:** the allowlist names title, body, labels and draft state for pull requests. It does not name open/closed state, so a close is not on it.
- **§ 12.2:** an agent merges only a pull request that is mergeable and ungated, and only with a merge commit. Most of what waits on Amr is gated (§ 12.3; 181 of 218 open pull requests on 2026-11-15), and zer0-mistakes allows squash only.
- **§ 19.5:** automation never comments under Amr's personal token. The queue's next-action comment goes out under the console's identity, which today is Amr's login.

A merge or close Amr selects and confirms in the console is arguably his own action, executed by Claude Code through the OPS remote-write path (§ 11.8). The constitution has to say so first. Nothing in this record, and nothing in #863, authorises a merge or a close until Amr ratifies one of the options below and a later gated PR flips the switches.

Live state of the implementation PR, for context only (2026-11-16 morning MST): #864 is open, labelled `feature` + `needs-amr`, `mergeable_state: unstable`, because **CodeQL failed** on head `3e776e1` (3 new alerts: 1 critical, 1 high, 1 medium; check completed 2026-11-15 10:07 PM MST). Other required checks on that head were green. CodeQL must be cleared before any enablement PR, independent of this amendment.

## Decision Amr must make

Pick **one** option. Two open questions apply to options 1 and 2 and must be answered in the ratified text:

1. Does the maintainer's confirm also satisfy **§ 12.4** for a `needs-amr` / gated pull request, or must the label still be removed by hand first?
2. Is a queue comment that the maintainer confirmed still "automation" under **§ 19.5**? (Recommended answer: yes, so it must not use Amr's personal token, even if the merge itself is his action.)

Repo-specific rules (lifehacker.dev is never merged by an *agent*; gitorio Dependabot merges go through `dep:merge-approved`, ADR-039) still apply. If option 1 treats the confirm as the maintainer's own merge, say explicitly whether lifehacker.dev may be merged from the queue.

## Option 1 — Allow both merge and close (broadest)

**Tradeoffs.** Matches the original ask (select many, confirm, merge or close). Highest power: one confirm could cover a large batch, including — if question 1 is "yes" — gated work. Highest audit burden. Conflicts with a literal reading of § 11.2 and § 12.5 until those sentences are carved. Zer0-mistakes and any squash-only repo need an exception to § 12.2's "merge commit only."

**Evidence / audit (all must hold before an apply runs, and are recorded):**

- Plan rebuilt from live GitHub immediately before apply; refused if any selected pull request moved since the preview (`plan_id` + head SHA).
- Merge uses `--match-head-commit` and the method the *repo* allows; never `--admin` or `--auto`.
- Each result appended to the OPS / PR-queue audit log (who, when, plan_id, action, before, after, head SHA, outcome); token values redacted.
- A dry run and one real apply of a merge plan on two pull requests, recorded, before the switches are relied on in routine use (acceptance in #863).
- Comments, if any, post as the fleet app or `github-actions[bot]`, never as Amr's personal token (§ 19.5).
- The enablement PR that sets `pr_queue.merge.enabled` and `pr_queue.close.enabled` to `true` is itself gated (§ 12.3) and comes after this amendment merges.

**Exact constitution text** (option 1, recommended wording if this option is chosen). Add a new item 9 under § 11, and amend the cited sentences:

> 9. **Maintainer-confirmed PR-queue actions** — a merge or close of a pull request that the maintainer selected in the Harness Console PR queue (`/prs`, `tools/dash prs`), after reading a per-pull-request plan rebuilt from live GitHub, and confirmed (`confirm=true`, same `plan_id`) is the **maintainer's own action**, applied by Claude Code through the OPS remote-write path (item 8). It is not an agent merge under § 12.2 and is not forbidden by item 2. The apply is refused if any selected pull request moved since the preview. A merge uses `--match-head-commit` and the method the repository allows, and never `--admin` or `--auto`. Each repository's own merge rules still hold. Every result is recorded in the append-only write log. This item does not let any agent merge or close on its own initiative.
>
> *Amend § 11.1* by appending, after the pull-request clause: "Close (open/closed state) and merge of a pull request are allowed only as a maintainer-confirmed PR-queue action (item 9), not as a general allowlist mutation."
>
> *Amend § 11.2* by appending: "Exception: item 9."
>
> *Amend § 12.2* by appending: "A merge carried out under § 11.9 uses the method the repository allows (including squash where the repository requires it) and is the maintainer's merge, not an agent merge."
>
> *Amend § 12.5* by appending one of the following, according to Amr's answer to question 1:
>
> - (Q1 = confirm satisfies the gate): "A confirm under § 11.9 on a plan that lists each gated pull request, the § 12.3 reason it is gated, and an explicit `include_gated` acknowledgement is the maintainer's approval under § 12.4; the apply removes `needs-amr` as part of the same recorded action. Amendment PRs are still ratified only by that confirm-and-apply, which counts as the maintainer merging them (§ 8)."
> - (Q1 = label must be removed first): "§ 11.9 does not bypass the gate. A gated pull request is refused by a merge or close plan until the maintainer has removed `needs-amr` (or otherwise passed § 12.4) beforehand."
>
> *Amend § 19.5* by appending: "A PR-queue next-action or result comment is automation even when the maintainer confirmed the plan, and still must not use the maintainer's personal token. The merge or close itself under § 11.9 may authenticate with a token that is allowed to merge, and is recorded as the maintainer's action, not as an automated review or approval under this section."

## Option 2 — Close only

**Tradeoffs.** Useful for clearing stale or withdrawn PRs without giving the queue merge authority. Close is reversible (reopen). Still requires a § 11.1 allowlist change, because open/closed state is not listed for pull requests today. Does not solve the "select all and merge" request. Gated-amendment risk is lower than merge, but closing an amendment PR is still a direction act and should follow the same Q1 choice (refuse unless the plan acknowledges gated items, or require the label off first).

**Evidence / audit:** same as option 1, minus merge method / `--match-head-commit` / `--admin`. Close is still refused if the pull request moved; each close is logged; comments still obey § 19.5; `pr_queue.close.enabled` is flipped in a later gated PR; `pr_queue.merge.enabled` stays `false`.

**Exact constitution text** (option 2):

> 9. **Maintainer-confirmed PR-queue close** — a close of a pull request that the maintainer selected in the Harness Console PR queue, after reading a per-pull-request plan rebuilt from live GitHub, and confirmed (`confirm=true`, same `plan_id`) is the **maintainer's own action**, applied by Claude Code through the OPS remote-write path (item 8). It is not on the general § 11.1 allowlist for unconfirmed write-back. The apply is refused if any selected pull request moved since the preview. Every result is recorded. This item does not allow a merge, and does not let any agent close a pull request on its own initiative.
>
> *Amend § 11.1* by appending: "Close (open/closed state) of a pull request is allowed only as a maintainer-confirmed PR-queue action (item 9)."
>
> *Do not amend § 11.2 or § 12.2.* Merge remains forbidden for the console and for agents except as § 12 already allows.
>
> *Amend § 12.5 / § 19.5* with the same Q1/Q2 sentences as option 1, but worded for close only (`merge or close` → `close`).

## Option 3 — Keep disabled (no constitution change)

**Tradeoffs.** Safest, and the current shipped state of #864. The queue remains a dashboard plus the six already-enabled actions. Amr merges and closes on GitHub (or by a later, separate amendment). Does not fulfil the bulk-merge/close ask. No enablement PR. #863 can be closed as "won't do, for now" only if Amr says so in his own words.

**Evidence / audit:** none beyond leaving the switches `false`. Any later attempt to set them `true` without a ratified amendment is a § 12.3 / § 11 violation and must be refused.

**Exact constitution text:** none. Do not add a § 11.9. Do not change § 11.1, § 11.2, § 12.2, § 12.5 or § 19.5.

## Consequences (after ratification)

- Option 1 or 2: a follow-up **gated** PR sets the matching `pr_queue.*.enabled` flag(s) to `true`. The code already sits behind those switches; `tools/console/test_pr_queue.py` covers merge with the switch on and the refusal with it off (per #863). That PR is software, so Claude Code executes it (§ 26), and it must not land while #864's CodeQL failure is still open.
- Option 3: no switch change. Note the decision on #863.
- AGENTS.md / `docs` for the console gain a short pointer to the new item only if option 1 or 2 is ratified; that follow-up may ride in the enablement PR.
- Merging the pull request that carries this record ratifies it. An agent never merges it (§ 8, § 13.9).

## Amendment

**Pending Amr's choice.** This pull request carries all three options so Amr can pick one; it is a decision record, not yet a single ratifiable amendment. Before it is merged, this section is replaced with only the chosen option's quoted constitution text, the other options are deleted from the record, and the matching edit to `docs/constitution.md` is added in the same pull request (§ 8). If Amr picks option 3, the record says "no constitution change" and no `docs/constitution.md` edit is made.

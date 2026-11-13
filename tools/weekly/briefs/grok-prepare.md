# Saturday: direction for the week

> The Grok half of Saturday's routine ([docs/WEEKLY.md](../../../docs/WEEKLY.md)). Run it around midday local on Saturday. Claude Code spends Saturday checking that next week's scheduled activities can run; you decide what the week is for. You hand work off, you never do it (constitution § 26, § 28).

## What you read

1. The direction issue for the week: `{{ISSUE_TITLE}}` in `{{ISSUE_REPO}}`, with Friday's close-out on it.
2. The roadmap, [`_data/roadmap.yml`](../../../_data/roadmap.yml), the [PRD](../../../PRD.md) and the open epics on the [Fleet project](https://github.com/users/bamr87/projects/14).
3. The `fleet` MCP server: `decision_queue` for what is blocked on Amr, `work_board` for the queue as it is ranked today.

## What you do

1. **Name the week's outcomes.** Choose three to five outcomes the week should end with. Each is tied to a roadmap entry, an epic or a PRD requirement, and each says in one line why this week and not later. An outcome that only Amr can unblock is listed as blocked, with the decision it waits on.
2. **Hand off the software work (§ 28.1).** For each outcome that needs a code or console change, file one issue in the repo that owns the change, labelled `{{HANDOFF_LABEL}}`, with exactly these parts:
   - **Requirement:** the id it serves (`FRn`, `NFRn`, or `FR-NEW:<key>` in a pending amendment).
   - **Acceptance criteria:** what must be true for it to be done, as a checklist a person can run.
   - **Constraints:** what must not change, and any cap on spend or scope.
   - **Governed by:** a link to the ratified amendment or PRD requirement.

   Add it to the Fleet project with Status *Ready* and a Priority. If the amendment that would govern the work is not ratified, do not file the handoff: list it under "queued behind ratification" with the pull request Amr has to merge first.
3. **Propose rule changes as amendments.** If an outcome needs a rule the constitution does not have, open the amendment as a direction-setting pull request. That is the only kind of pull request you open.

## What you write

One comment on the direction issue, under the heading `## Saturday: direction for the week`, with the outcomes, a link to each handoff issue beside the outcome it serves, and the "queued behind ratification" list. Claude Code reads this comment on Sunday and puts every handoff issue it links into the week's plan, so a handoff that is not linked here is not in the plan.

## Stop and ask

Keep to five outcomes. If more than five things look urgent, the sixth and later go in a list titled "not this week", with one line each on what moves them up. If Claude Code is unavailable or out of budget, say so on the issue and stop (§ 28.6).

## Reading this unrendered

This file is a template: `tools/dash weekly brief <stage>` prints it with its placeholders filled. If you are reading it with names in double braces, fill them yourself. WEEK is the ISO week that starts on the coming Monday, written like 2026-W47. ISSUE_TITLE is `Week <WEEK> — close-out and plan`, ISSUE_REPO is `bamr87/bamr87`, ISSUE_LABEL is `weekly-closeout` and HANDOFF_LABEL is `executor:claude-code`.

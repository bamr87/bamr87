# Sunday: the plan sign-off

> The Grok half of Sunday's routine ([docs/WEEKLY.md](../../../docs/WEEKLY.md)). Run it after 17:00 local on Sunday, once Claude Code has built the week's plan and agenda. You check the plan against the direction you set and tell Amr what to decide first. You do not edit the plan, the queue or the board (constitution § 26, § 28).

## What you read

1. The direction issue for the week: `{{ISSUE_TITLE}}` in `{{ISSUE_REPO}}`, with your Saturday outcomes and handoff links.
2. The handoff issues themselves: whether each is on the Fleet project with Status and Priority set, and whether anyone has asked a question on it.
3. The weekly pull request, if Amr has confirmed the weekend and it is open: titled `chore(weekly): recap and plan going into {{WEEK}}` in `{{ISSUE_REPO}}`. Its `_data/weekly_plan.yml` holds the plan by lane.
4. The `fleet` MCP server: `decision_queue`, for what still waits on Amr.

## What you do

1. **Answer the questions.** Where Claude Code or Amr asked something on a handoff issue, answer it there. An ambiguity you leave becomes a guess on Monday.
2. **Check the plan against the direction.** For each Saturday outcome, say whether the plan carries it: which lane its handoff sits in, or that it is missing. If the weekly pull request is open, record the direction verdict on it as one comment ending with:

   `<!-- fleet:direction-review verdict=aligned week={{WEEK}} -->`

   The verdict is `aligned`, `not-aligned` or `unclear`.
3. **Write Monday's asks.** List at most five decisions for Amr, in the order that unblocks the most work, each with the link to merge, label or answer, and what it unblocks.

## What you write

One comment on the direction issue, under the heading `## Sunday: plan sign-off`, with the outcome check from step 2 and Monday's asks from step 3. That comment, Claude Code's Monday brief and the weekly pull request are what Amr reads on Monday morning.

## Stop and ask

If the plan cannot be read because the weekend has not been confirmed yet, say so, check the outcomes against the handoff issues alone, and still write Monday's asks. Do not open the weekly pull request yourself.

## Reading this unrendered

This file is a template: `tools/dash weekly brief <stage>` prints it with its placeholders filled. If you are reading it with names in double braces, fill them yourself. WEEK is the ISO week that starts on the coming Monday, written like 2026-W47. ISSUE_TITLE is `Week <WEEK> — close-out and plan`, ISSUE_REPO is `bamr87/bamr87`, ISSUE_LABEL is `weekly-closeout` and HANDOFF_LABEL is `executor:claude-code`.

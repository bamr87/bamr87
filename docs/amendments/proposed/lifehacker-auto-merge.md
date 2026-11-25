<!-- kit: governance v0.1.0 -->
# NEW — lifehacker.dev's auto-merge may publish a bot's content without a human merge

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-11-25
- **Proposed by:** agent (Claude Code), at the maintainer's request (2026-11-25: "switch them all on.")
- **Ratified by:**
- **Affects:** constitution § 23 item 6; `_data/fleet.yml` `switches.loops` `lifehacker.dev/auto-merge`; bamr87/lifehacker.dev `auto-merge.yml`, its constitution § 1 mission 3 (its own amendment 0005), AGENTS.md and PRD (companion pull request); requirements: none; features: none
- **Supersedes:** none (amends § 23 item 6 as left by amendment 0037 `lifehacker-drafting-lines`)
- **Related:** 0037 `lifehacker-drafting-lines`; constitution § 12.2, § 12.3, § 17; bamr87/lifehacker.dev#800 (the hold)

## Context

Amendment 0037 restarted lifehacker.dev's three drafting lines and kept its auto-merge held, because § 23.6 and lifehacker.dev's own constitution (§ 1 mission 3) both said a human merges. On 2026-11-25 the maintainer asked for every switch to be on, auto-merge included.

`auto-merge.yml` merges a bot's open pull request labelled `auto:content`, `source/triage-bot` or `source/ai-usage-bot` when its checks are green and it is mergeable. Two of its behaviours do not fit the fleet's rules, and this amendment's companion pull request fixes both:

- **Its smuggle guard classifies the diff as a whole.** `scripts/ci/classify_changes.rb` reports a diff of `pages/` plus `agencies/` as plain `content`, so an agency change (which lifehacker.dev's constitution § 9.5 reserves for a human merge), a doc or a feature-catalog edit could ride along. The guard now classifies each file on its own: a file outside content and data comes back as `pipeline` and the pull request goes to a human.
- **It squash-merges.** § 12.2 says an automated merge uses a merge commit. It now runs `gh pr merge --merge`.

What reviews a bot's content pull request before auto-merge is its checks: the build and content harness (front matter, drift, brand voice, the Prime Directive) on every pull request, and the AI brand reviewer when the brand lint raises a candidate. No agent reads every piece. This amendment says so in the rule instead of calling the checks a human review.

**Switch flips already made (§ 17.4; the activity-log store, bamr87/bamr87#409, does not exist yet):** at 20:48 UTC on 2026-11-25, Claude Code set lifehacker.dev's `AUTO_MERGE_ENABLED` and `OPENAI_IMAGES_ENABLED` (the weekly epic's painted hero image, one OpenAI image call a week) to `true` at the maintainer's instruction. Auto-merge stays idle until the companion pull request lifts `HUB_ORIGINATION_HOLD`. Every other switch on bash-365.com, it-journey and lifehacker.dev was already on. The four lifehacker.dev variables still `false` (`AI_USAGE_ENABLED`, `BRAND_SWEEP_ENABLED`, `EXPLORER_ENABLED`, `FLEET_ENABLED`) gate workflows deleted in lifehacker.dev `8a7c6af`, so they switch nothing and were left alone.

## Amendment

In constitution § 23 item 6, replace the sentence "Rule 4 applies to every line: each draft is a pull request, nothing publishes until reviewed by a human and/or an agent, and a human merges — lifehacker.dev's auto-merge stays held." with:

> Each draft is a pull request, and nothing publishes before it is reviewed: by a human, who merges it, or, while lifehacker.dev's auto-merge switch is on, by its gates. The auto-merge line merges a pull request carrying one of its bots' labels (`auto:content`, `source/triage-bot`, `source/ai-usage-bot`), with a merge commit, only when every changed file is content or generated data, every check on it is green (the build and content harness, and the AI brand review where it runs), and it carries no `needs-human` label. This is the one place where checks alone stand in for rule 4's review; turning the switch off returns every merge to a human.

## Consequences

- With `AUTO_MERGE_ENABLED=true`, a bot's green content pull request on lifehacker.dev publishes without anyone reading it first, within minutes of its pipeline finishing (and at the daily 06:13 UTC backstop). Mistakes are caught after publishing, by a reader, the site explorer or a later fix.
- `gh variable set AUTO_MERGE_ENABLED -R bamr87/lifehacker.dev --body false` stops it at once, and every merge goes back to a human. The switch is the off-ramp; no amendment is needed to use it.
- The companion lifehacker.dev pull request carries its amendment 0005 (mission 3: "a human remains the only merge gate" becomes "a human holds the merge gate, and may delegate it to green checks for the autopilot's own content"), removes the hold from `auto-merge.yml`, makes its guard per-file and its merge a merge commit, and updates AGENTS.md, the PRD and the colophon. Merge it after this record, never before.
- `_data/fleet.yml`: `lifehacker.dev/auto-merge` moves to `state: 'on'` and loses its `hold:` block.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

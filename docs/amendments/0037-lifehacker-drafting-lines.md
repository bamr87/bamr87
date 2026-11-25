<!-- kit: governance v0.1.0 -->
# 0037 — lifehacker.dev's drafting lines run again, and a human still merges

- **Status:** ratified
- **Number:** 0037
- **Date:** 2026-11-24
- **Proposed by:** agent (Claude Code), at the maintainer's request (2026-11-24: "resolve blockers, turn on lifehackers automation.")
- **Ratified by:** https://github.com/bamr87/bamr87/pull/985 (merged 2026-11-25 by @bamr87)
- **Affects:** constitution § 23 item 6; `_data/fleet.yml` `switches.loops` (the 18 variable-gated `lifehacker.dev/*` records); bamr87/lifehacker.dev `content-factory.yml`, `weekly-epic.yml`, `wire-scout.yml` and AGENTS.md (companion pull request); requirements: none; features: none
- **Supersedes:** none (amends § 23 item 6, from amendment 0021 `writing-chronicle`)
- **Related:** bamr87/lifehacker.dev#800 (the hold, merged 2026-11-06), #801 (hub-originated intake, open), #802 (the 2026-11-05 shutdown); lifehacker.dev constitution § 1 mission 3; constitution § 12, § 17

## Context

Amendment 0021 made lifehacker.dev the fleet's news agency and held its autonomous publishing "until hub-originated intake is in place". lifehacker.dev#800 carried the hold into code: `HUB_ORIGINATION_HOLD: "true"` idles `content-factory.yml`, `weekly-epic.yml`, `wire-scout.yml` and `auto-merge.yml` whatever their switches say. Every `*_ENABLED` variable there was set to `false` on 2026-10-31.

The intake has not been built. lifehacker.dev's `_data/hub_intake.yml` still reads `status: planned`, and #801 is open. Meanwhile the site's own lines have been idle for almost three weeks, with 119 pieces waiting in its content queue (read 2026-11-23). On 2026-11-24 the maintainer asked for lifehacker.dev's automation to be turned on.

Two rules bind what "on" can mean:

- This item and rule 4 of § 23: nothing publishes until reviewed by a human and/or an agent, and a human merges.
- lifehacker.dev's own constitution, § 1 mission 3: "a human remains the only merge gate … no change reaches the apex domain lifehacker.dev without a human merge."

The three drafting lines only open pull requests. A piece publishes when its pull request merges. `auto-merge.yml` is the one line that merges without a human. So drafting can resume without touching either merge rule, and auto-merge cannot.

**Switch flips already made (recorded here and in `_data/fleet.yml`, § 17.2 and § 17.4; the activity-log store, bamr87/bamr87#409, does not exist yet):** at 16:16 UTC on 2026-11-24, Claude Code set 12 of lifehacker.dev's repository variables from `false` to `true` at the maintainer's instruction: `AGENT_REVIEW_ENABLED`, `AUTO_FIX_ENABLED`, `AUTO_UPDATE_ENABLED`, `CONTENT_FACTORY_ENABLED`, `CONTENT_SCOUT_ENABLED`, `ISSUE_FACTORY_ENABLED`, `LOOP_TUNER_ENABLED`, `QUEST_FORGE_ENABLED`, `THEME_SCOUT_ENABLED`, `TRIAGE_ENABLED`, `WEEKLY_EPIC_ENABLED` and `WIRE_SCOUT_ENABLED`. `AUTO_MERGE_ENABLED` was set to `true` at the same time and back to `false` while this record was written, because auto-merge stays held. `AI_USAGE_ENABLED`, `BRAND_SWEEP_ENABLED`, `EXPLORER_ENABLED` and `FLEET_ENABLED` were not changed and stay `false`. The lines the hold does not cover ran the same day. The content scout opened lifehacker.dev#832, labelled `auto:content`, and it is waiting for a human.

## Amendment

Replace constitution § 23 item 6 with:

> 6. **lifehacker.dev is the fleet's news agency** — lifehacker.dev is part of the fleet's writing and chronicling operations: a synthesized, curated news agency built from fleet activity, written for a wider audience in the voices of its site characters. Its articles originate in the hub (the console / monorepo writing section) once hub-originated intake is in place; it synthesizes them from reviewed hub entries. Until then, and alongside it, its own drafting lines — the content factory, the weekly epic and the wire scout — draft from its own backlog, its configured news sources and the prior week's publications. Rule 4 applies to every line: each draft is a pull request, nothing publishes until reviewed by a human and/or an agent, and a human merges — lifehacker.dev's auto-merge stays held. _(amendment `lifehacker-drafting-lines`, numbered at merge)_

## Consequences

- The companion lifehacker.dev pull request removes `HUB_ORIGINATION_HOLD` from `content-factory.yml`, `weekly-epic.yml` and `wire-scout.yml`, so their repository variables decide again, and updates AGENTS.md. Merge it after this record, never before, because it lifts a hold this constitution imposes.
- `auto-merge.yml` keeps `HUB_ORIGINATION_HOLD: "true"`, and `AUTO_MERGE_ENABLED` stays `false`. That puts two locks on the one line that merges without a human. Turning it on needs an amendment to this item and to lifehacker.dev's constitution § 1.
- Once the hold is lifted, the lines run on these schedules (UTC): the wire scout daily at 21:40, the content factory daily at 22:40, and the weekly epic on Mondays at 19:40. Each opens at most one pull request per run. Agent review and auto-fix (both switched on above) work on those pull requests, and a human merges.
- The drafting lines open pull requests with `secrets.FLEET_TOKEN || github.token`. Actions may not create pull requests on lifehacker.dev, so they depend on `FLEET_TOKEN`, which was working on 2026-11-24 (the content scout's #832). If it expires, the lines write and push a branch but open no pull request.
- Spend: the three lines use the fleet's Claude OAuth credential. The content factory and the weekly epic have job timeouts (20 and 30 minutes). The wire scout has none, so GitHub's 6-hour default applies. None of the three has a per-run dollar cap. Adding caps is a follow-up and is not part of this amendment.
- `_data/fleet.yml`: the 18 variable-gated `lifehacker.dev/*` loop records move from `unverified` to the live values read on 2026-11-24 (13 records `on`, 5 records `off`; the issue factory's two workflows share one variable). The three lifted lines lose their `hold:` block, and auto-merge's block now cites this amendment.
- Hub-originated intake (#801) is still the target. When it lands, its drafts are pull requests under the same rule. The three lines then either draw from it or a later amendment retires them.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

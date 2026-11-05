# 0021 — The writing section keeps a daily chronicle of fleet operations, AI prompting and agent activity

- **Status:** ratified (ratification pending — Amr ratifies by merging this PR)
- **Number:** 0021
- **Date:** 2026-11-04
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:** https://github.com/bamr87/bamr87/pull/663 (merged 2026-11-05 by @bamr87)
- **Affects:** constitution § 23 (new, follows § 22 `repo-cap-42` in PR #660; becomes § 22 if that does not merge first); `pages/posts/`; `_data/voices/` (new shared voice config + schema), `tools/voices.py` (new); bamr87/lifehacker.dev (publishing hold, PR #800); bamr87/zer0-CMS (adoption follow-up); feature `0021` follow-up (`HUB-NEW`, not created here); requirements: none yet
- **Supersedes:** none
- **Related:** hub issue #662 (organize writings/journals/posts for correct display in console and online); `repo-cap-42` (PR #660, section numbering only)

## Context

Fleet work — operations, prompts to AI, agent runs and their PRs — happens daily but is only recoverable from scattered logs, PRs and transcripts. Amr, as owner, wants the monorepo's writing section to be the human-readable record of what happened each day.

The writing section is `pages/posts/` (dated `YYYY-MM-DD-slug.md` posts with front matter; `draft: true` shows only in the console). `tools/console/site_docs.py` reads it and the harness console serves it via `/api/site` and `/api/site/post/{slug}` as its Writing section, identical to the public Pages build.

## Amendment

New constitution section:

> ## 23. Writing section chronicles fleet activity
>
> _(amendment `writing-chronicle`, numbered at merge — see the [amendment log](amendments/README.md); follows § 22 `repo-cap-42` (PR #660), renumber to § 22 if that amendment does not merge first)_
>
> 1. **Rule — daily chronicle** — the monorepo's writing section, `pages/posts/` (dated `YYYY-MM-DD-slug.md`, rendered by `tools/console/site_docs.py` as the console's and public site's Writing section), chronicles, documents, journals and notes, repo-wide and fleet-wide, all fleet operations, AI prompting and any activity agents are working on, pushing, committing and deploying across all repos, in a summarized chronicle fashion, so Amr or other readers can read and recall what happened each day.
> 2. **Form** — one chronicle entry per day with activity (`pages/posts/YYYY-MM-DD-chronicle.md`, category `chronicle`), summarizing, per repo, operations, prompts given, agents run, work in progress, pushes, commits, PRs opened or merged, deployments, and outcomes; summaries, not raw transcripts.
> 3. **Redaction** — a chronicle never records tokens, secrets, credentials, keys, or private values; anything secret-shaped is redacted before commit.
> 4. **Drafts by default, reviewed before publishing** — every chronicle entry lands as a draft (`draft: true`, console-only); nothing publishes until it has been reviewed by a human and/or an agent, and only then is `draft: true` removed.
> 5. **Enforcement** — generation (a daily chronicle generator, `HUB-NEW`) is a follow-up; until it lands, agents add or append the day's entry by PR.
> 6. **lifehacker.dev is the fleet's news agency** — lifehacker.dev is part of the fleet's writing and chronicling operations: a synthesized, curated news agency built from fleet activity, written for a wider audience in the voices of its site characters. Its articles originate in the hub (the console / monorepo writing section); it synthesizes them from reviewed hub entries, and rule 4 applies there too — nothing publishes until reviewed by a human and/or an agent, and a human merges. Its own autonomous publishing stays held until hub-originated intake is in place.
> 7. **One voice model** — AI voices, styles, personas and content config for lifehacker.dev and zer0-CMS use one shared model, `voices/v1`: canonical in the hub at `_data/voices/voices.yml` with its schema `_data/voices/voices.schema.json` (fields aligned with zer0-CMS ADR 0010 `VoiceProfile`, plus a persona layer). Admins edit that file; the console's editor reads it and writes edits back to it as a PR, never a separate database copy; both sides validate against the schema, and `tools/voices.py check --against` flags drift in any consumer copy.

## Open questions

- **Privacy / secret redaction:** chronicles never record tokens, secrets, credentials or keys (rule 3). Should the generator run a secret scanner (e.g. gitleaks patterns) as a hard gate before commit?
- **Former-employer content:** how, if at all, should chronicles treat content concerning Amr's former employer? Undecided — no rule is set by this amendment; Amr to decide.
- ~~Should entries default to `draft: true` or be public by default?~~ **Decided (Amr, 2026-11-04):** drafts by default; nothing publishes until reviewed by a human and/or an agent (rule 4).
- Granularity: one entry per day, or per day per repo?

## Consequences

- Agents finishing fleet work add to or create the day's chronicle entry in `pages/posts/`.
- lifehacker.dev's autonomous publishing workflows are held in code by bamr87/lifehacker.dev#800 (turns off only when Amr merges it); re-enabling via hub intake is a follow-up.
- Follow-up (`HUB-NEW`, not implemented here): console Voices editor that reads `_data/voices/voices.yml` and writes edits back as a PR, with schema validation and a drift indicator.
- Follow-up: zer0-CMS adopts `voices/v1` (ADR 0010 `VoiceProfile` import/export) rather than a separate voice system.
- Follow-up (not implemented here): `HUB-NEW` daily chronicle generator that summarizes the day's PRs, agent runs and operations into `pages/posts/YYYY-MM-DD-chronicle.md`, with redaction.
- Ratification: Amr ratifies this amendment by merging the PR; agents propose, never merge (§ 8).

## Revisions

- 2026-11-04: on Amr's review, scope widened from fleet operations and AI prompting to repo-wide/fleet-wide — any activity agents are working on, pushing, committing and deploying across all repos; daily entries summarize per repo. Linked hub issue #662.
- 2026-11-04: on Amr's review, rule 4 made explicit — chronicle entries are drafts by default (`draft: true`) and nothing publishes until reviewed by a human and/or an agent; the drafts-vs-public open question is resolved accordingly.
- 2026-11-04: on Amr's review, added rule 6 (lifehacker.dev as the fleet's curated news agency, originating from the hub, drafts-until-reviewed, autonomous publishing held — bamr87/lifehacker.dev#800) and rule 7 (one shared `voices/v1` model for lifehacker.dev and zer0-CMS, canonical at `_data/voices/voices.yml`, console writes back by PR, schema validation and drift check; new SDLC persona cast for lifehacker.dev).

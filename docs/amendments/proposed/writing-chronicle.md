# NEW — The writing section keeps a daily chronicle of fleet operations, AI prompting and agent activity

- **Status:** proposed (ratification pending — Amr ratifies by merging this PR)
- **Number:** NEW
- **Date:** 2026-11-04
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:** the merged PR URL (leave blank until merged)
- **Affects:** constitution § 23 (new, follows § 22 `repo-cap-42` in PR #660; becomes § 22 if that does not merge first); `pages/posts/`; feature `AMEND-NEW:writing-chronicle` follow-up (`HUB-NEW`, not created here); requirements: none yet
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

## Open questions

- **Privacy / secret redaction:** chronicles never record tokens, secrets, credentials or keys (rule 3). Should the generator run a secret scanner (e.g. gitleaks patterns) as a hard gate before commit?
- **Employer-sensitive content:** should work done for an employer, or anything employer-confidential, be excluded or kept to draft-only entries? (As written: not explicitly excluded — Amr to decide.)
- ~~Should entries default to `draft: true` or be public by default?~~ **Decided (Amr, 2026-11-04):** drafts by default; nothing publishes until reviewed by a human and/or an agent (rule 4).
- Granularity: one entry per day, or per day per repo?

## Consequences

- Agents finishing fleet work add to or create the day's chronicle entry in `pages/posts/`.
- Follow-up (not implemented here): `HUB-NEW` daily chronicle generator that summarizes the day's PRs, agent runs and operations into `pages/posts/YYYY-MM-DD-chronicle.md`, with redaction.
- Ratification: Amr ratifies this amendment by merging the PR; agents propose, never merge (§ 8).

## Revisions

- 2026-11-04: on Amr's review, scope widened from fleet operations and AI prompting to repo-wide/fleet-wide — any activity agents are working on, pushing, committing and deploying across all repos; daily entries summarize per repo. Linked hub issue #662.
- 2026-11-04: on Amr's review, rule 4 made explicit — chronicle entries are drafts by default (`draft: true`) and nothing publishes until reviewed by a human and/or an agent; the drafts-vs-public open question is resolved accordingly.

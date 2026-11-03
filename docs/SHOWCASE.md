# Quest Log showcase

> The Quest Log campaign: each repo the daily deep dive processes is also showcased on LinkedIn (an article and a post on Amr's profile, a post on the BASH Consulting page) and given a better first screen, each piece a PR Amr merges.

## Goal

Showcase all of Amr Abdel-Motaleb's work so far (GitHub `bamr87`) on LinkedIn, on the personal profile and on the BASH Consulting company page, as posts and as articles.

"The Quest Log" is a series inside the Badwill Impairment journey. Its kickoff post, [Badwill Impairment](https://bamr87.github.io/posts/2026/11/01/badwill-impairment/) (bamr87/bamr87.github.io#52, open as of 1 November 2026), has a `# The Quest Log` section that frames each project as a level or a side quest with a "Skill unlocked" line. Every showcase reuses that frame and that voice: dry, satirical about corporate process, short punchy lines, true. The series page is <https://bamr87.github.io/quest-log/>.

## How it rides the deep dive

The [daily deep dive](DEEP-DIVE.md) reviews one repo a day, every repo once per cycle. Cycle 1 runs from 2026-10-30 to 2026-12-10 (42 days); as of 1 November 2026 the rotation in `_data/deep-dive.yml` holds 38 repos, so days 39–42 (2026-12-07 to 2026-12-10) are free.

| Day | What the showcase takes |
| --- | --- |
| Day N of the rotation | The ledger's repo for day N, once that day's deep dive is recorded `done`: the article's "What the deep dive found" is that run's score, findings, issues and PRs |
| A day with room, or a catch-up slot | The first repo in `showcase_missed`: deep dive done this cycle, before today, no showcase yet |
| Before or after the cycle | Nothing |

No deep dive, no showcase. `python3 tools/deep_dive.py today --json` prints the day's repo, its slug (`showcase_slug`) and what was missed (`showcase_missed`); the procedure is the [`deep-dive-showcase`](../.claude/skills/deep-dive-showcase/SKILL.md) skill, written for whatever runs the deep dive: the scheduled routine, or Amr by hand.

## The five pieces

For a repo `R`, `SLUG` is `quest-log-` plus `R` lowercased with dots as hyphens (`quest-log-bamr87-github-io`), and `DATE` is the day the showcase is made.

| # | Piece | Repo | Where it lives | Voice |
| --- | --- | --- | --- | --- |
| 1 | Article, 900–1,500 words, 3–5 screenshots | bamr87/bamr87.github.io | `pages/_posts/quest-log/DATE-SLUG.md`, images in `assets/images/quest-log/SLUG/`, card `preview.png` (1200x627); served at `https://bamr87.github.io/posts/YYYY/MM/DD/SLUG/` | Amr, in the Quest Log voice |
| 2 | Personal LinkedIn post, 700–1,300 characters | bamr87/bamr87.github.io, in the article's PR | `.zer0/drafts/linkedin/DATE-SLUG.md`, the zer0-CMS lane's draft dialect (outside the Jekyll build) | Amr, first person |
| 3 | Company LinkedIn post, about 500–1,000 characters | bash-365/bash-365.com | `drafts/linkedin/DATE-SLUG.md`, an external link card to the article | BASH Consulting, per bash-365's `linkedin-share` skill and brand rules |
| 4 | Presentation and marketing update | the repo itself | its README's first screen (pitch, hero screenshot, Live / Source / Read the story); its live site's first impression when weak; a GitHub About proposal (description, homepage, topics, a 1280x640 social preview) in the PR body | the repo's own |
| 5 | Record | bamr87/bamr87 | the row's `showcase` in `_data/deep-dive.yml`, written by `tools/deep_dive.py record`; projected into `_data/deep_dive.json` with a `showcased` count | — |

Every piece follows one truth rule: each fact comes from the repo, its live site, the deep-dive ledger or its issues and PRs, or the kickoff post; numbers are counted and dated; nothing about users, adoption, metrics, clients, employers, testimonials or biography is invented; a plan is called a plan. Humor is aimed at corporate process in general, never at a named company or person, and never at the reader.

## Who approves what

Agents draft and open pull requests; Amr approves by merging. Nothing posts or publishes from an agent's work, and no agent changes a repo setting ([constitution](constitution.md) § 4; PRD NFR8 for the deep-dive routine).

| Piece | Approved by | What the approval does |
| --- | --- | --- |
| Article and personal draft | Amr merging the site PR | GitHub Pages publishes the article; the personal draft becomes the approved text to post |
| Company draft | Amr merging the bash-365.com PR | **publishes it to the company page**, so it merges only after the article is live, and at most one company post a day |
| Presentation update | Amr merging the repo's PR | the README and the site change |
| GitHub About box | Amr, in the repo's settings | the routine only proposes it |
| Personal post | Amr, posting it or approving it in the zer0-CMS studio | it goes up on Amr's profile |
| LinkedIn article | Amr, pasting it into LinkedIn's article editor | it goes up on Amr's profile or the page |
| Record | Amr merging the hub PR | the ledger and `/deep-dive` show the showcase |

Merge order: the kickoff post (bamr87.github.io#52) first, because every article links to it; then each article; then its company draft, once the article answers at its URL, one company post a day.

## How each piece reaches LinkedIn

- **Company posts.** bash-365.com publishes a merged draft: a push to `main` under `drafts/linkedin/` runs `linkedin-publish.yml`, which runs zer0-CMS's distribution lane live, posts the draft as the BASH Consulting page, records it in `.github/linkedin-log.json` and sets the draft to `published`. The ledger keeps a page from posting twice. The rules are in bash-365's `drafts/linkedin/README.md` and zer0-CMS's `docs/DISTRIBUTION.md`.
- **Personal posts.** bamr87.github.io has no LinkedIn lane by design: its `zer0.json` carries no `distribution` block, and posts reach Amr's profile through a zer0-CMS studio LinkedIn channel that only Amr can connect. Until that channel is connected, Amr posts the staged text by hand, with the article's link. The draft is kept in the lane's dialect so either path reads it; the studio seeds its own first commentary from the article's `sub-title`, and the staged text replaces that seed.
- **Articles.** LinkedIn's API publishes posts, including link-card posts, but not LinkedIn articles, so no lane can publish one. The article page is written to paste cleanly into LinkedIn's article editor by hand, on either the profile or the page: plain Markdown, H2 and H3 only, no Liquid, wikilinks or raw HTML, captioned images. Paste the body, set the cover image to `preview.png`, re-upload any image the paste dropped, and end with the link to the canonical page.

## Outside the rotation

The rotation is every non-archived repo owned by `bamr87`, forks included. Four repos the kickoff post names belong to other organizations, so the deep dive never reaches them and they get no showcase from it:

| Repo | Kickoff post |
| --- | --- |
| [bash-365/csv-vscoode](https://github.com/bash-365/csv-vscoode) | Level 0010, the spreadsheet |
| [bash-365/bash-365.com](https://github.com/bash-365/bash-365.com) | the sites side quests |
| [year-of-ai/year-of-ai.github.io](https://github.com/year-of-ai/year-of-ai.github.io) | the sites side quests |
| [ai-world-view/ai-world-view.github.io](https://github.com/ai-world-view/ai-world-view.github.io) | the sites side quests |

Proposal, pending Amr's decision: give them the cycle's four free days, 2026-12-07 to 2026-12-10, one each. Those days are also the rotation's catch-up slots, so a missed deep dive or a missed showcase comes first, and the ledger would need a decision on whether these repos join `_data/deep-dive.yml` at all.

## The catch-up

Days 1–3 came before this procedure: it-journey (scheduled 2026-10-30, run early on 2026-10-29), bamr87 (2026-10-31) and bamr87.github.io (2026-11-01). Their showcases were made together, outside the procedure, in one catch-up dated 2026-11-02. They have the same five pieces and the series shape the skill now sets down, and they are recorded with the same `record` call.

Two things set the catch-up apart:

- Three articles share one date, so each carries a timestamp just after midnight Mountain time (00:10, 00:20 and 00:30, in rotation order). That is the one exception to the skill's bare date.
- bamr87.github.io's deep dive had filed its issues but was not yet recorded `done` as of 2 November 2026. Its article prints no score and says why.

The procedure takes over from day 4. The catch-up's three company drafts join the queue at one company post a day.

## Where the parts are

| Part | Location |
| --- | --- |
| The procedure | [`.claude/skills/deep-dive-showcase/SKILL.md`](../.claude/skills/deep-dive-showcase/SKILL.md) |
| The ledger and its tool | `_data/deep-dive.yml`, [`tools/deep_dive.py`](../tools/deep_dive.py) ([DEEP-DIVE.md](DEEP-DIVE.md), schema `showcase.*`) |
| The kickoff post | bamr87/bamr87.github.io `pages/_posts/badwill-impairment/2026-11-01-badwill-impairment.md` |
| The Badwill Impairment charter | bamr87/zer0-CMS `packages/books/library/badwill-impairment/campaign.md` |
| Company-page drafting rules | bash-365/bash-365.com `.claude/skills/linkedin-share/SKILL.md` |
| The LinkedIn lanes | bamr87/zer0-CMS `docs/DISTRIBUTION.md` |
| The portfolio standard the presentation PR follows | [PORTFOLIO.md](PORTFOLIO.md) |

The Badwill Impairment charter gives the company page bash-365.com cross-posts only. Company posts that share bamr87.github.io articles widen that, so the charter's row changes when Amr approves this campaign.

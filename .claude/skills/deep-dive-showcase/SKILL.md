---
name: deep-dive-showcase
description: "Make the Quest Log showcase for a repo the daily deep dive has processed: the long-form article and Amr's personal LinkedIn draft on bamr87.github.io, the BASH company-page LinkedIn draft on bash-365.com, a presentation PR in the repo itself (README first screen, live-site first impression, a GitHub About proposal), and the ledger record. Use after a deep-dive run, on a catch-up day, or when asked to \"showcase <repo>\", \"write the Quest Log for <repo>\" or \"run the showcase\". Drafts and opens PRs only: never posts, merges or changes a repo setting."
---

# deep-dive-showcase

The per-day procedure of the Quest Log campaign ([`docs/SHOWCASE.md`](../../../docs/SHOWCASE.md)), for whatever runs the daily deep dive ([`docs/DEEP-DIVE.md`](../../../docs/DEEP-DIVE.md)): the scheduled routine, or Amr by hand. One repo per run. It writes files, opens pull requests and records them in the ledger. Nothing posts or publishes because of it: Amr approves each piece by merging its pull request.

| # | Piece | Repo | Path | Reaches readers |
| --- | --- | --- | --- | --- |
| 1 | Article (long form) | bamr87/bamr87.github.io | `pages/_posts/quest-log/DATE-SLUG.md`, images in `assets/images/quest-log/SLUG/` | the site, when the PR merges; LinkedIn's article editor, pasted by hand |
| 2 | Personal LinkedIn post | bamr87/bamr87.github.io (same PR) | `.zer0/drafts/linkedin/DATE-SLUG.md` | Amr's profile: the zer0-CMS studio once Amr connects it; until then Amr posts it by hand |
| 3 | Company LinkedIn post | bash-365/bash-365.com | `drafts/linkedin/DATE-SLUG.md` | the BASH Consulting page: **merging the draft publishes it** (`linkedin-publish.yml`) |
| 4 | Presentation update | the deep-dived repo | its README's first screen, its live site, an About proposal in the PR body | the repo and its site, when the PR merges |
| 5 | Record | bamr87/bamr87 (this hub) | `_data/deep-dive.yml` row `showcase` via `tools/deep_dive.py record` | `/deep-dive`, through `_data/deep_dive.json` |

## Rules that hold throughout

- **Truth rule.** Every factual claim (features, numbers, dates, stack, status) comes from the repo, its live site, the deep-dive ledger or its issues and PRs, or the Badwill Impairment kickoff post (already fact-checked). Count numbers yourself and date them ("as of 3 November 2026"). Never invent users, adoption, metrics, clients, employers, testimonials or biography. Name a plan as a plan.
- **Humor** stays dry and aimed at corporate process in general. Never at a real named company or person, and never at the reader.
- **Approval is a merge.** Draft, open PRs, record. Never merge, post, approve a draft (`status: approved` is Amr's edit), set `ZER0_LINKEDIN_PUBLISH`, change a repo setting (About box, topics, social preview, Pages), or read, print or touch a secret or `.env`.
- **Work in a scratch clone or worktree of each repo, off its default branch.** Never in the hub's `projects/` submodule working trees. Read each repo's `AGENTS.md` / `CLAUDE.md` before writing there; its rules win inside it. Never hand-edit a generated file there: change the source and regenerate.
- **Gates are reported, not assumed.** A gate that cannot run here (no Ruby, no zer0-CMS checkout, no browser) is written as "not run, because …" in the PR body, never as passed.

## 1. Inputs

1. **Which repo.** In the hub:

   ```bash
   python3 tools/deep_dive.py today --json
   # {"date": …, "cycle": 1, "day": 4, "kind": "scheduled", "repo": "fredgar-ai",
   #  "showcase_slug": "quest-log-fredgar-ai", "showcase_missed": ["it-journey", …]}
   ```

   - `kind: scheduled`: showcase `repo` once its deep dive is recorded `done` (the article's "What the deep dive found" is that run's output). If it is not done, there is no showcase for it today.
   - `kind: catch_up`: `repo` is the deep dive's catch-up; the showcase takes the first of `showcase_missed`.
   - On any day with room, and on every catch-up slot, `showcase_missed` lists repos whose deep dive is done this cycle, before today, with no showcase yet. Take the first.
   - `not_started` or `cycle_over`: nothing to do.

2. **The ledger row** (findings, score, next focus, issues, PRs, open counts):

   ```bash
   python3 -c "import sys,yaml; print(yaml.safe_dump([r for r in yaml.safe_load(open('_data/deep-dive.yml'))['repos'] if r['repo']==sys.argv[1]][0], sort_keys=False, allow_unicode=True))" REPO
   ```

3. **The deep dive's issues and PRs**, with their state as of today:

   ```bash
   gh issue list -R bamr87/REPO --label deep-dive --state all --json number,title,state,url
   gh pr list    -R bamr87/REPO --label deep-dive --state all --json number,title,state,url
   ```

4. **The repo's place in the Quest Log.** The kickoff post is `pages/_posts/badwill-impairment/2026-11-01-badwill-impairment.md` in bamr87/bamr87.github.io: on `main` once bamr87.github.io#52 merges, until then on that PR's head branch (`gh pr view 52 -R bamr87/bamr87.github.io --json headRefName -q .headRefName`). Its `# The Quest Log` section has numbered levels (`**Level NNNN: the <role>.**`, each ending in a `*Skill unlocked: …*` line) and side-quest group bullets. Use exactly the level or group the post gives the repo. Some repos are described there without being named (the backlog and plumbing bullets); match one only when the description plainly fits the repo's own README, otherwise call it a side quest and give no level. Never invent a level number. A level's article reuses the post's bold opener and its first line, and its `*Skill unlocked: …*` line, word for word. A side quest gets its own `**Side quest: the <role>.**` opener and its own Skill unlocked line, and the close names its group (`listed under The sites`).

5. **The earlier entries.** Read the two or three most recent Quest Log articles and drafts (`pages/_posts/quest-log/` on bamr87.github.io's `main` and its open `feat(posts): Quest Log` PRs). Reuse their structure; never reuse their jokes. Each article has its own corporate target.

6. **The repo itself**: its README, `AGENTS.md`, `features/features.yml`, PRD and releases when present, and its live site (`gh repo view bamr87/REPO --json description,homepageUrl,repositoryTopics,latestRelease`).

## 2. Names

| Name | Rule | Example |
| --- | --- | --- |
| `SLUG` | `showcase_slug` from step 1: `quest-log-` + the repo name lowercased, dots as hyphens, no leading or doubled hyphen | `quest-log-bamr87-github-io`, `quest-log-github` for `.github` |
| `DATE` | the run's date, `YYYY-MM-DD` | `2026-11-05` |
| Article URL | `https://bamr87.github.io/posts/YYYY/MM/DD/SLUG/` (permalink `/:collection/:year/:month/:day/:slug/`) | |
| Site branch | `feature/quest-log-<repo, lowercased, dots as hyphens>` | `feature/quest-log-fredgar-ai` |
| bash-365 branch | `feature/linkedin-quest-log-<same>` | |
| Presentation branch | the repo's own convention, else `feature/presentation-deep-dive` | |
| Hub record branch | `chore/deep-dive-showcase-<repo>-c<cycle>d<day>` (the record PRs' pattern) | `chore/deep-dive-showcase-fredgar-ai-c1d4` |

Write `date:` as a bare `DATE`, not a timestamp: the site sets no `timezone:`, so GitHub Pages builds in UTC, and an evening Mountain-time timestamp moves the URL to the next day. The one exception is a date that carries more than one showcase, as the catch-up of 2026-11-02 did. Give each a timestamp just after midnight Mountain time, in rotation order (`2026-11-02T00:10:00-07:00`, then `T00:20`, then `T00:30`), so the series page, newest first, keeps them in order. `lastmod:` equals `date:`.

## 3. Screenshots

Take 3–5 shots that each show something the article says: the live site's first screen, the one feature that matters most, the deep dive's own output (an issue, a PR, a passing gate), a terminal for a command-line tool. A shot that only decorates is cut.

```bash
npx -y playwright screenshot --channel chrome --viewport-size=1280,800 --wait-for-timeout 2000 URL shot.png
npx -y playwright screenshot --channel chrome --viewport-size=1280,800 --full-page URL long.png
```

`--channel chrome` drives the installed Chrome, so no browser is downloaded (npx still fetches the `playwright` package, latest, per the hub's dependency policy); the wait lets a client-rendered page finish past its spinner.

A repo with a verify kit (`verify/verify.yml`, `node verify/runner.mjs`) can be shot through it instead. When a cookie banner or sticky header covers the page, use a Playwright script that hides it (`page.addStyleTag`), or choose another view. Then convert, size and look:

```bash
# Article images: 1280 px wide JPEG, quality about 80, aim for 250 KB or less each.
sips -s format jpeg -s formatOptions 80 --resampleWidth 1280 shot.png --out 01-name.jpg
# LinkedIn and Open Graph card: 1200x627 PNG.
sips --resampleWidth 1200 shot.png --out wide.png && sips -c 627 1200 wide.png --out preview.png
# GitHub social preview for the presentation PR: 1280x640 PNG.
sips -c 640 1280 shot.png --out social-preview.png
sips -g pixelWidth -g pixelHeight preview.png; ls -l *.jpg *.png
```

Off macOS, ImageMagick does the same (`magick shot.png -resize 1280x -quality 80 01-name.jpg`; `magick shot.png -resize 1200x -gravity center -crop 1200x627+0+0 +repage preview.png`).

**Look at every image** (the Read tool, or open it) before keeping it. Reject error pages, cookie banners, sign-in walls, blank canvases, spinners, and anything that shows a token, an email address or private data.

**No browser:** invent nothing. Write the article without images, leave `preview:` out of its front matter, say "screenshots pending" in the site PR body and record it (`--showcase-note "screenshots pending"`, step 10).

## 4. The article

`pages/_posts/quest-log/DATE-SLUG.md` in bamr87.github.io, 900–1,500 words. It must paste cleanly into LinkedIn's article editor: plain Markdown, H2 and H3 only (the layout renders the title, so no H1 in the body), no Liquid, no wikilinks, no raw HTML, one paragraph per line (the repo's `unwrap-prose` gate). US English, as in the kickoff post (labeled, color, organization).

Front matter, in this order:

```yaml
---
title: "<Project>: <plain promise>"            # 60 characters or less, sentence case after the colon
sub-title: "<the LinkedIn hook>"               # 140 characters or less; the zer0-CMS studio seeds Amr's commentary from it
description: "<120 to 155 characters, no trailing period>"
author: bamr87
date: DATE                                     # bare; § 2 has the one exception
lastmod: DATE
tags: [badwill-impairment, quest-log, <topic>, ...]   # up to 6; the first three become #BadwillImpairment #QuestLog #Topic
categories: [quest-log]
preview: /images/quest-log/SLUG/preview.png    # the theme prefixes /assets; omit when screenshots are pending
---
```

Shape, in order. The headings are the series' own, so every entry reads as one of a set:

1. **The opener**, under no heading: the bold `**Level NNNN: the <role>.**` or `**Side quest: the <role>.**` line from step 1.4, the corporate absurdity it answers in one or two dry lines, then the turn to the project. Short, punchy, true.
2. **`## What it is, and who it is for`.**
3. **`## How it works`**: the real architecture, plainly (stack, the moving parts, where the data goes), each part led by a bold run-in sentence (`**One list decides.**`).
4. **The screenshots**, under `## The tour` or a heading named for what they show, or set in the sections above where each makes its point. Each is a Markdown image with real alt text and an italic caption line under it:

   ```markdown
   ![The fredgar-ai home page listing company financials](/assets/images/quest-log/quest-log-fredgar-ai/01-home.jpg)

   *The home page, as of 5 November 2026.*
   ```

5. **`## What the deep dive found`**, in this order:
   - The series paragraph, word for word. In the hub's own article, "run from this hub" replaces "run from my hub repository":

     > The deep dive is a daily AI review routine run from my hub repository. At 06:00 Denver time it takes one of my repositories, every non-archived one once per 42-day cycle, reviews it, files what it finds as issues and pull requests labeled deep-dive, and records the run in a ledger with a public [dashboard](https://bamr87.github.io/bamr87/deep-dive/). It never merges, force-pushes or touches a setting or a secret. I merge its fixes. This series rides on it.

   - A sentence that opens `Day N of cycle C` and gives the run's date, then the ledger's score in bold: `**Score: NN out of 100.**` A row with no score yet gets `**No score yet.**` and no number.
   - Bold run-in lead-ins, as they apply: `**What it filed.**`, `**What is solid.**`, `**What got fixed.**`, then `**What is open**, as of D Month YYYY:`, with every issue and PR linked by full URL and its state checked on that date. Anything the writer found beyond the ledger goes last, under `**One more, found while writing this.**`
6. **`## What is built, and what is still a plan`**: `Built and running:` and `Still a plan:`, with plans named as plans.
7. **`## How to try it`**: bullets led by `**Live:**` and `**Source:**`, then `**Run it:**` or others as the repo needs.
8. **The close**, under no heading: the `*Skill unlocked: …*` line, then one paragraph:

   ```markdown
   This is Level NNNN of [the Quest Log in Badwill Impairment](https://bamr87.github.io/posts/2026/11/01/badwill-impairment/#the-quest-log). The other levels and side quests arrive one deep dive at a time on the [Quest Log series page](https://bamr87.github.io/quest-log/).
   ```

   A side quest reads `This is a side quest from [the Quest Log in Badwill Impairment](…#the-quest-log), listed under <group>.` in the first sentence.

Every link to another page on bamr87.github.io is an **absolute** `https://bamr87.github.io/...` URL: the branch is cut from `main`, where a page may not exist yet, and the site's link check (`htmlproofer --disable-external`) skips absolute URLs. Images keep their site path (`/assets/images/...`), since they ship in the same PR. The series page is built outside this procedure; if its source says how a new article joins it, follow that, otherwise add nothing.

Mechanical checks, all of which must print nothing (the first two count words and images):

```bash
A=pages/_posts/quest-log/DATE-SLUG.md
awk 'f>=2; /^---$/{f++}' "$A" | grep -v '^!\[' | sed -E 's/\]\([^)]*\)/]/g' | wc -w   # 900-1500: what a reader sees, alt text and URLs left out
grep -c '^!\[' "$A"                                              # 3-5, or 0 with screenshots pending
grep -nE '^# |^#{4,} ' "$A"                                      # no H1, nothing below H3
grep -nE '\{%|\{\{|\[\[' "$A"                                    # no Liquid, no wikilinks
grep -nE '<[A-Za-z/!][^>]*>' "$A"                                # no raw HTML (autolinks included)
grep -noE '\]\([^)]*\)' "$A" | grep -vE '\]\((https?://|/assets/images/quest-log/)'   # no relative page links
grep -nE '^!\[\]' "$A"                                           # every image has alt text
```

## 5. The personal LinkedIn draft

`.zer0/drafts/linkedin/DATE-SLUG.md` in the same bamr87.github.io branch, in the zer0-CMS lane's dialect (the dot folder stays out of the Jekyll build). Exactly:

```markdown
---
type: article
status: pending
source: pages/_posts/quest-log/DATE-SLUG.md
title: "<article title>"
url: <article URL>
---

<commentary>
```

The commentary is exactly what posts on Amr's profile, above the article's link card:

- First person, in Amr's dry, satirical voice from the Badwill post.
- The payoff lands inside the first 140 characters, where LinkedIn folds.
- 700–1,300 characters.
- Never restates the card's title or description.
- One soft call to read the article.
- Ends with exactly three hashtags: `#BadwillImpairment #QuestLog #<Topic>`, the topic being the article's third tag in CamelCase.

The series shape, so the posts read as a set. The hook opens from the article's `sub-title`, reworded for the post. The second paragraph places the project: `That is <Project>, Level NNNN of my Quest Log: …`, or `That is <Project>, a side quest in my Quest Log.` The deep dive appears as `Day N of my daily deep dive …` with its score, or says plainly that there is no score yet. The call to read names what the article adds (`The screenshots and every open issue are in the article.`). The jokes are the article's own, never one from an earlier entry.

Preview it (the fold, the length, the brand guard and every gate, with no network call):

```bash
<zer0-CMS>/content/.venv/bin/python <zer0-CMS>/content/manage.py linkedin preview --site <site clone> DATE-SLUG
```

Fix every `ERROR` the brand guard reports. bamr87.github.io has no LinkedIn lane block in `zer0.json` by design (Amr's profile is a studio channel), so expect `no_author`, and the not-yet-cleared gates any pending draft has (`status_not_accepted`, `publish_disabled`, `no_credential`); `preview` exits 1 because of `no_author`, and that alone is not a defect of the draft. `source_missing` means the article is dated after today or the path is wrong.

## 6. The company LinkedIn draft

`drafts/linkedin/DATE-SLUG.md` in bash-365.com. Read bash-365's [`linkedin-share`](https://github.com/bash-365/bash-365.com/blob/main/.claude/skills/linkedin-share/SKILL.md) skill, `.github/instructions/brand.instructions.md` and `.github/instructions/content-style.instructions.md` there first; they win on voice. The article lives on another site, so the draft is an external link card written by hand (not `scripts/linkedin.sh draft`, which drafts from a bash-365 post). Exactly:

```markdown
---
type: article
status: pending
link: <article URL>
title: "<article title>"
description: "<article description>"
---

<commentary>
```

- BASH Consulting company-page voice. The angle: what this piece of the founder's work shows about building governed, AI-assisted systems a business can trust. It is the practice's own tooling, not a client case.
- No banned phrases; acronyms expanded on first use; no exclamation marks; never invent metrics, clients or certifications.
- Exactly one call to action; 2–3 CamelCase hashtags; the payoff before the 140-character fold; about 500–1,000 characters.
- `title` and `description` are the article's front-matter values, byte for byte.
- Name the founder once, in full: "our founder, Amr Abdel-Motaleb", or "Our founder's …" with the full name in the next sentence.
- US dates ("November 1"), where the article writes "1 November".
- Hashtags `#AIGovernance #Automation #<Topic>`, the topic fitting the angle (`#Education`, `#SmallBusiness`, `#DataQuality` so far).
- Vary the call to action from the last few company drafts. The page's followers see them one a day.

```bash
ZER0_CMS_DIR=<zer0-CMS> scripts/linkedin.sh preview DATE-SLUG     # from the bash-365.com clone
```

Fix every `ERROR`. On a clean pending draft the gates left are `status_not_accepted`, `publish_disabled` and `no_credential`; none of them is yours to lift, and `preview` exits 0. The preview also notes `using the fallback card image assets/images/office.jpg`: the external-link dialect carries no image, so the card takes bash-365's `fallbackImage`, not the article's `preview.png`. That is expected. Do not add an image key the lane does not read; `no_thumbnail: true` is the only other choice, and it is Amr's.

## 7. The presentation update

On a branch in the deep-dived repo, following its `AGENTS.md`, its generators and its gates:

- **The README's first screen**, in this order:
  - a bold one-line pitch (`**A curriculum that checks its own homework:** …`) that agrees with the `>` tagline under the H1 and the GitHub description ([`docs/PORTFOLIO.md`](../../../docs/PORTFOLIO.md) §1);
  - a line of links: `**[Live](…)** · **[Source](…)** · **[Read the story](<article URL>)**`;
  - a hero screenshot committed in the repo (where its `SCHEMA.md` places images), linked to the live site, with a dated caption.

  Put all three between the badge row and `## Overview`, so the portfolio skeleton (UPS-DOC-10) still holds. If the README or a span of it is generated, change the generator's source and regenerate. Two READMEs are pages in their own right and take a lighter touch. bamr87/bamr87's is the GitHub profile, so the block sits inside its centered header. bamr87.github.io's is the résumé served at `/profile/`, so it gets one line pointing at the series page and the site's own entry, with no hero.
- **The live site's first impression**, when the repo has one and it is weak: meta description, Open Graph image, hero copy.
- **The GitHub About proposal**, in the PR body only, never applied:
  - description: one sentence per `docs/PORTFOLIO.md` §1 (about 120 characters; GitHub's limit is 350);
  - homepage per §3;
  - 5–10 topics from the §2 vocabulary;
  - a 1280x640 social-preview image committed in the repo, which Amr uploads in Settings if the proposal is accepted.

## 8. Gates

| Repo | Run |
| --- | --- |
| bamr87.github.io | `python3 tools/unwrap-prose.py --check <article> <draft>`; `python -m pytest -q scripts/tests` (from the repo root); `LANG=C.UTF-8 bundle exec jekyll build`, then the link check from `link-check.yml` (`bundle exec htmlproofer ./_site --disable-external --checks Links --no-enforce-https --allow-missing-href --no-check-internal-hash`); the checks in § 4; the lane preview in § 5 |
| bash-365.com | `scripts/linkedin.sh preview DATE-SLUG`; `python3 scripts/content_lint.py` (the repo-wide editorial gate stays green) |
| the deep-dived repo | the "done" bar in its `AGENTS.md`, including its prose and generator checks |
| bamr87 (the record) | `python3 tools/test_deep_dive.py`; `python3 tools/deep_dive.py json --check` |

## 9. Pull requests

Open them in this order, each with a Conventional Commit title in its repo's convention. When an agent opens one, its commits end with a blank line and the agent's `Co-Authored-By:` trailer, and its body ends with the line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Add each to the Fleet project (constitution § 10.1) when the token has the `project` scope, and say so when it does not.

| PR | Title | Label | Body says |
| --- | --- | --- | --- |
| Site (bamr87.github.io) | `feat(posts): Quest Log — <Project>` | none | what is in it; the personal LinkedIn text, quoted in full; how to publish the article on LinkedIn by hand (below); merge order; the gates and their results; "screenshots pending" when it applies |
| Company (bash-365.com) | `feat(posts): linkedin draft — SLUG` | none | **merging this publishes it to the company page**; merge only after the article is live, and only one company post per day; the gates |
| Presentation (the repo) | the repo's convention, for example `docs(readme): first screen and About proposal` | `deep-dive` | what changed and why; the GitHub About proposal; the gates |
| Record (bamr87) | `chore(deep-dive): record the <repo> showcase — cycle C day N` | `deep-dive` | the four links it records |

Neither the site PR nor the company PR carries `deep-dive`. `refresh` counts open `deep-dive` items against the repo they live in, so the label on a site PR would count as bamr87.github.io's own deep-dive work, and bash-365.com has no such label (the search covers repos owned by bamr87 only). The ledger's `showcase` links those two PRs instead. When the showcased repo is bamr87.github.io itself, its presentation PR does carry the label.

**Publishing the article on LinkedIn by hand** (for the site PR body): open the live page; in LinkedIn choose Write article (on Amr's profile, or as the BASH page); paste the body; set the cover image to `preview.png`; upload any image the paste dropped, with its caption; end with a link to the canonical page on bamr87.github.io.

**Merge order:** bamr87.github.io#52 (the kickoff post the article links to), then the site PR, then the company PR once the article URL answers, at most one company post a day. The presentation PR's "Read the story" link works once the article is live; the record PR can merge any time after the PRs exist.

## 10. Record

In a hub branch (`chore/deep-dive-showcase-<repo>-c<cycle>d<day>`), with the URLs from step 9:

```bash
python3 tools/deep_dive.py record REPO --date DATE \
  --article https://bamr87.github.io/posts/YYYY/MM/DD/SLUG/ \
  --linkedin-personal https://github.com/bamr87/bamr87.github.io/pull/N \
  --linkedin-company https://github.com/bash-365/bash-365.com/pull/N \
  --presentation-pr https://github.com/bamr87/REPO/pull/N \
  [--showcase-note "screenshots pending"]
python3 tools/test_deep_dive.py && python3 tools/deep_dive.py json --check
```

Showcase flags alone leave the run's status alone. The call rewrites `_data/deep-dive.yml` and `_data/deep_dive.json` together, as every record does; commit both. When a LinkedIn post goes up, run it again with the post's URL in place of the draft PR (`--linkedin-personal` or `--linkedin-company`); a link given again replaces the old one, and presentation PRs accumulate. When it fits, the showcase record rides in the same PR as the day's deep-dive record.

## Guardrails

- One repo per run, and no showcase without a finished deep dive.
- Nothing here posts, merges, approves, or changes a setting; the only things that reach LinkedIn are what Amr merges, pastes or approves.
- `_data/deep-dive.yml` is changed through `tools/deep_dive.py`, never by hand; `_data/deep_dive.json` is never edited.
- A gate that did not run is reported as not run.

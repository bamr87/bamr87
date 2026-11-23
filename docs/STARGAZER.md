# Stargazer: the open-source radar

> Every repository the account has starred on GitHub, sorted, categorised and measured; the repositories rising this week, this month and in the topics the fleet's projects carry; and the repositories most like each fleet project, with a short list worth a review. One committed document feeds the console page, the CLI, the MCP server and the brief every local Claude Code session starts with. Read-only on GitHub, $0.

A star is a note to self: "this is good, come back to it". The fleet never came back. Its projects re-solved problems that a starred repo already solved, and no session knew the stars existed. Stargazer turns the stars into input. It reads them with what is trending around the fleet, matches all of it against each project, and puts the result where work starts: the console's **Stars** page and the first message of every local session.

| | |
| --- | --- |
| **Model** | [`tools/fleetcore/stars.py`](../tools/fleetcore/stars.py): categories, matches, star velocity, suspect flags, the review list, the feed, the session brief. Pure: no network, no writes |
| **Tool** | [`tools/stargazer.py`](../tools/stargazer.py): reads GitHub, writes the two data files, answers the read commands |
| **CLI** | `tools/dash stars …` |
| **Data** | [`_data/stars.json`](../_data/stars.json) (`stars/v1`, public) and [`_data/stars_history.json`](../_data/stars_history.json) (`stars-history/v1`) |
| **Loop** | [`.github/workflows/stargazer.yml`](../.github/workflows/stargazer.yml), daily 06:53 UTC, off until `vars.STARGAZER_ENABLED` is `true`; a manual dispatch always runs |
| **Console** | **Fleet → Stars** (`/stars`, `/api/stars`), the `stars-refresh` operation, the Stargazer loop on **Loops** |
| **MCP** | `fleet_stars` (`kind`: summary · starred · trending · incorporate · fleet · feed · gaining · repo) |
| **Sessions** | [`.claude/hooks/stars_session_start.py`](../.claude/hooks/stars_session_start.py), a SessionStart hook |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) `stars:` and `schedule.stargazer` |
| **Tests** | [`tools/test_stargazer.py`](../tools/test_stargazer.py) (offline) |

## Run it

```bash
tools/dash stars                         # the summary: totals, categories, newest stars, what to review
tools/dash stars refresh                 # read GitHub, write _data/stars.json + _data/stars_history.json
tools/dash stars refresh --dry-run       # read and build, write nothing
tools/dash stars starred --category agents --language Python
tools/dash stars starred --q "jekyll theme" --project zer0-mistakes
tools/dash stars trending                # each search, fastest risers first
tools/dash stars incorporate --project githubai
tools/dash stars similar fleet-observe   # one project: its terms, starred and discovered matches
tools/dash stars show HarnessRouter/harnessrouter
tools/dash stars feed                    # stars, releases, newcomers, spikes
tools/dash stars brief --cwd projects/githubai   # what a session there starts with
```

Every read command takes `--json` and `--limit`. A refresh needs a GitHub token (`GH_TOKEN`, `GITHUB_TOKEN` or `gh auth token`) and takes about 20 GraphQL calls and 90 seconds; `--budget` caps the wall clock (default 240 s).

## What a refresh reads

1. **The stars**, newest first, 100 a page, up to `stars.max_starred`, with each repo's topics (all 20), language, license, stars, forks, dates, latest release and owner.
2. **The public star lists**: GitHub's own curation ("✨ Inspiration"). Each becomes a filter and a tag.
3. **Every fleet repo's own GitHub side** (topics, language, description), the 44 registry projects that are not archived and the hub itself as `bamr87`.
4. **Trending**: GitHub has no trending API, so each list is one search. Two are configured (`stars.trending.queries`): repos created this week with 50+ stars and this month with 300+. Then, for each of the fleet's `fleet_topics` strongest topics (claude-code, jekyll, django, …), the repos created in the last `topic_window_days` with the most stars ("Rising in #topic").
5. **Discovery**: one search per fleet project, seeded by its two most specific tags (the rarer across the fleet, the more specific): `topic:a topic:b stars:>100 pushed:>(a year ago)`. A project whose narrow search finds fewer than three repos gets a second search on its first tag alone.

Searches go 6 to a GraphQL query and repositories 25 to a query. If the stars cannot be read, nothing is written. If a later phase fails (lists, fleet repos, trending, discovery), the last document's answer for it is kept and `errors` says so; the page shows a "partial" banner.

**Private data never enters the document.** It is public site data. A private repository the token can see, or a private star list, is dropped while the document is built. Run under GitHub Actions, the job token sees public data only anyway.

## What the model decides

**Categories.** Each repo gets one category from a built-in taxonomy: AI agents and coding assistants, LLMs and RAG, DevOps and infrastructure, web, static sites and docs, developer tools, security, data and finance, learning and curated lists, games and creative, systems, and other. Topics vote 3, a part of a hyphenated topic ½, a keyword in the name or description 1. A topic that only names a language (`typescript`, `nodejs`) votes 1, so an agent platform written in TypeScript is still an agent platform. Every category scoring 2 or more is also a tag. A `stars.categories` list in fleet.yml replaces the taxonomy.

**Matches.** Every repo is compared with every fleet project by tf-idf cosine over one bag of terms. Topics and stack tags weigh 3, each part of a hyphenated one 1, the language 1.5, and description and name words 1. The project's side is its registry stack, category and description plus its own GitHub topics and language. A term most repos carry ("ai") weighs little. A repo keeps its three best matches above `relevance.min_score` (0.10), each with the shared terms that explain it, topics first and in their own spelling. The fleet's own repos (any `hub.owners` owner) match nothing.

**Health** is the last push: active (30 days), maintained (6 months), slowing (a year), stale, or archived.

**Velocity.** Every refresh appends each repo's star count to the history. The history keeps one sample a day for 10 days, then one a week for 13 weeks, and drops repos that leave the radar. Stars gained over 1, 7 and 30 days come from it; a repo under a year old also gets stars a day since it was created. "Your stars, gaining fastest" and the feed's spikes read it.

**Suspect.** Star farming is common in trending lists, and the fake repos are often malware. A repo is flagged when it is young (45 days) with no forks at all for 100+ stars, or when its stars a day pass `suspect.stars_per_day` (150) and it shows a strong sign (almost no forks for its stars, a throwaway-looking owner such as `name12345`) or two weak ones (no license, no description). A flagged repo carries its reasons and is shown with a warning, and it is never recommended: not in the review list, a project's matches or a brief.

**To review** (`incorporate`) lists the repos closest to a fleet project (`relevance.incorporate_min`, 0.20) that are alive and neither suspect nor the fleet's own. They are ranked by similarity × popularity × liveliness, a starred repo counts ×1.3, and each project gets at most three. Each item says which project and why. The list proposes; nothing is filed or adopted.

**The feed** shows stars, releases of starred repos, spikes (7-day gain over 5% and 100 stars), and newcomers: repos first seen after the history began, inside the last week, so the first read does not flood it.

## Every local session starts with it

`.claude/hooks/stars_session_start.py` runs at the start of every Claude Code session in the hub (and its worktrees). It finds the project from the session's working directory: a submodule by its registry path, else the hub, or anywhere else the fleet repo whose GitHub `origin` the checkout has. It then adds the brief to the session's context (about 2,000 characters, `stars.brief.max_chars`):

- the starred repos most like that project, with why;
- in a hub session, or when nothing matched, the starred repos the fleet's projects should look at;
- what was starred lately;
- the trending repos like a fleet project: the session's own project only, or the whole fleet's in the hub;
- and the instruction: before building something new, check whether one of these already does it, read it if it bears on the task, and say whether to adopt, borrow from or skip it.

Third-party text is data. The brief says so, clips descriptions, leaves suspect repos out and names trending repos without their descriptions. The hook is standard library only and reads one JSON file. It never parses fleet.yml or touches the network, and any error ends it silently. `STARS_SESSION_BRIEF=0` silences it for a session; `stars.brief.enabled: false` everywhere, on the next refresh.

**Sessions outside the hub.** A submodule opened as its own project, another clone or an unrelated repo does not read the hub's `.claude/settings.json`. One user-level hook covers them all, and adding it changes your machine, so it is a separate, explicit step:

```bash
tools/dash stars hook                    # is it installed? (reads ~/.claude/settings.json)
tools/dash stars hook --install          # dry run: says what it would add
tools/dash stars hook --install --yes    # adds one SessionStart hook; the rest of the file is kept
```

The installed command passes `--user`. In a project that already runs the hook from its own settings (the hub and its worktrees), it stays quiet, so no session gets the brief twice.

## The console page

**Fleet → Stars** (`/stars`) renders `/api/stars`, which is the committed document. The published site carries the same document, so the page reads the same there. Five tabs, each a URL (`?tab=`):

- **Radar**: totals, starred repos by category and language (pick one to filter), stars per month, how alive the starred repos are, the top of the review list and the latest events.
- **Starred**: every starred repo, filtered by search, category, language, star list and fleet project, sortable by stars, 7-day gain, push date, health and match.
- **Trending**: your stars gaining fastest, then each search with stars a day, age and the closest fleet project; suspect rows are marked.
- **Fleet match**: every project with how many starred and discovered repos are close to it, then one project's terms and its starred and discovered matches with the shared terms.
- **Feed**: events by day.

A repo opens in a drawer (`?repo=owner/name`) with every field, its matches, why it is suspect if it is, and a `claude "Review github.com/<repo> for <project>: …"` command to copy into a local session. On a console, **Read GitHub now** runs `stars-refresh` (read-only, needs a token); the job refreshes the page when it ends.

## Settings

`_data/fleet.yml` `stars:`; every key is optional, the defaults are `DEFAULTS` in the model.

| Key | Default | What it does |
| --- | --- | --- |
| `account` | the first of `hub.owners` | whose stars |
| `max_starred` | 2000 | stars read per refresh |
| `trending.queries` | new this week, new this month | each `{id, title, q}`; `{d7}` in `q` is the date seven days ago (any `{dN}`) |
| `trending.per_query` / `fleet_topics` / `topic_window_days` / `topic_min_stars` | 12 / 6 / 120 / 50 | the searches |
| `discover.enabled` / `per_project` / `min_stars` / `pushed_days` | true / 8 / 100 / 365 | the per-project searches |
| `relevance.min_score` / `incorporate_min` / `max_matches` / `per_project` / `incorporate_max` / `incorporate_per_project` | 0.1 / 0.2 / 3 / 6 / 30 / 3 | matching and the review list |
| `suspect.young_days` / `stars_per_day` / `min_fork_ratio` | 45 / 150 / 0.015 | the star-farming heuristic |
| `feed.days` / `max` / `spike_ratio` / `spike_min` / `radar_days` | 45 / 120 / 0.05 / 100 / 7 | the feed |
| `brief.enabled` / `max_repos` / `max_chars` / `recent_days` / `stale_days` | true / 5 / 2200 / 21 / 14 | the session brief (saved into the document, so the hook never reads fleet.yml) |
| `categories` | the built-in taxonomy | `[{id, title, topics, keywords, languages}]`, replaces it |
| `aliases` | none | `{term: term}`, e.g. `golang: go` |
| `hub_stack` | the hub's themes | the stack the hub is matched on |

## Turning the loop on

The workflow is a new loop, so its schedule is off by default. After this lands and one manual run looks right:

```bash
gh workflow run stargazer.yml -R bamr87/bamr87 -f dry_run=true   # read and build, upload, publish nothing
gh variable set STARGAZER_ENABLED -R bamr87/bamr87 --body true    # then record the flip in _data/fleet.yml switches
```

Until then, `tools/dash stars refresh` and a commit of the two files keep the radar current.

# Stargazer: the open-source radar

> Every repository the account has starred on GitHub, sorted, categorised and measured; the repositories rising this week, this month and in the topics the fleet's projects carry; the repositories most like each fleet project, with a short list worth a review; and an AI pass that reviews them (adopt · borrow · watch · skip) and groups the stars into themes. One committed document feeds the console page, the CLI, the MCP server, a Grafana dashboard and the brief every local Claude Code session starts with. Read-only on GitHub; only the AI pass spends, capped and behind a yes.

A star is a note to self: "this is good, come back to it". The fleet never came back. Its projects re-solved problems that a starred repo already solved, and no session knew the stars existed. Stargazer turns the stars into input. It reads them with what is trending around the fleet, matches all of it against each project, and puts the result where work starts: the console's **Stars** page and the first message of every local session.

| | |
| --- | --- |
| **Model** | [`tools/fleetcore/stars.py`](../tools/fleetcore/stars.py): categories, matches, star velocity, suspect flags, the review list, the feed, the session brief. Pure: no network, no writes |
| **Tool** | [`tools/stargazer.py`](../tools/stargazer.py): reads GitHub, writes the two data files, answers the read commands |
| **CLI** | `tools/dash stars …` |
| **Data** | [`_data/stars.json`](../_data/stars.json) (`stars/v1`, public), [`_data/stars_history.json`](../_data/stars_history.json) (`stars-history/v1`) and [`_data/stars_ai.json`](../_data/stars_ai.json) (`stars-ai/v1`, the AI pass) |
| **AI pass** | `tools/dash stars review --yes`, the console's `stars-review` operation; `local:stars-review` in [`_data/agents.yml`](../_data/agents.yml) |
| **Grafana** | dashboard `fleet-stars` ([`tools/observability/grafana/dashboards/fleet-stars.json`](../tools/observability/grafana/dashboards/fleet-stars.json), rendered by `tools/dash stars grafana --write`), fed by `tools/dash stars metrics --push` |
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
tools/dash stars review                  # the AI pass: what it would review, in how many sessions, at what cap
tools/dash stars review --yes            # run it (spends; capped per session, recorded in the AI ledger)
tools/dash stars metrics                 # the radar as Prometheus gauges; --push sends them to the OTel collector
tools/dash stars grafana                 # check the committed dashboard against its render (--write rewrites it)
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

## The AI pass: reviews and themes

`tools/dash stars review` asks a model what the deterministic radar cannot: what a repo actually is, and whether the fleet should use it. Without `--yes` it prints the plan (which repos, how many sessions, the model, the cap per session and in all) and spends nothing.

- **Reviews.** The repos come in order: every repo the account starred (newest first; all but its own, which are the fleet), then the rest of the review list, then the trending repos like a fleet project. Suspect and fleet-owned repos are never sent, and neither is a repo whose review is current (written from the same description, topics and closest projects, younger than `stars.ai.max_age_days`). So a daily pass reviews only what is new. They go 12 to a session, at most 4 sessions a run (`--batches N` raises that for one run, up to 20). For each repo the model returns a one-line summary, a kind, a verdict (**adopt**: a fleet project should use it · **borrow**: take an idea, pattern or piece · **watch**: promising, not yet · **skip**: no use to the fleet), the fleet project it serves best, why, and up to three concrete ideas.
- **Themes.** One more session groups every starred repo into 6–12 themes named by what the repos are *for*, each with the fleet projects it feeds. It runs when the set of stars changed since the last grouping, or with `--groups`.

Every session goes through `dash-gen ai-run`: one `claude -p` with the prompt on stdin, an empty temporary working directory, no MCP server and every tool denied, so the model reads its prompt and nothing else. Each session is capped at `stars.ai.budget_usd`, uses the usage-limit skip, and has its cost (API-equivalent, an estimate) recorded in the AI ledger. Repo text sits inside a fenced `<repos>` block that the prompt calls data, never instructions. The answer is held to a schema: a repo it was not given, an unknown verdict or kind, or a project outside the fleet is dropped or nulled, and every string is cleaned and clipped. A batch whose answer does not parse is retried once as two halves (a shorter answer is the one that comes back).

The results land in `_data/stars_ai.json` and are laid over the radar (`attach_ai`): each reviewed repo gets an `ai` block, marked `stale` when its inputs changed since. The review list drops a `skip` and ranks `adopt` and `borrow` higher. The themes become `groups`. A refresh lays the committed file over every new read, so the daily CI build carries the AI layer without calling a model. The brief shows the verdict and the first idea beside a repo and leaves out repos the AI judged `skip`. In the console, **Review with AI** runs the same command behind the spend confirm. The agent is registered as `local:stars-review` in `_data/fleet.yml` `harness.agents` (switch `stars.ai.enabled`, model and cap from `stars.ai`).

## Grafana: the radar over time

Each refresh and each review pushes the radar to the local OTel collector as gauges (OTLP/JSON to `observability.claude_code.endpoint`, the ingress Claude Code's own metrics use). Prometheus scrapes them from the collector, and the **`fleet-stars`** dashboard in Grafana's *Fleet* folder draws them. A push is best effort: without the metrics profile (`tools/dash observe up`) it says so and moves on. `tools/dash stars metrics` prints the gauges in the Prometheus text format; `--push` sends them by hand, and so does the console's **Push to Grafana**.

| Gauge | Labels | What |
| --- | --- | --- |
| `fleet_stars_repo_stars`, `…_gain_7d`, `…_stars_per_day`, `…_similarity` | `repo`, `category`, `language`, `health`, `starred`, `project`, `verdict`, `suspect` | per repo: stars, 7-day gain, stars a day since creation, similarity to the closest fleet project |
| `fleet_stars_category_repos`, `fleet_stars_language_repos` | `category`/`title`, `language` | starred repos by category and language |
| `fleet_stars_project_matches` | `project`, `source` | starred and discovered repos close to each project |
| `fleet_stars_ai_verdicts`, `fleet_stars_total` | `verdict`, `kind` | the verdict counts and the totals |

The collector keeps a pushed series for an hour (`metric_expiration`), and Prometheus keeps the samples. So the panels read `last_over_time(…[30d])` (or `[2d]` per repo) to hold the last push between refreshes, and *Stars over time* takes each day's highest count, which draws a continuous line from one push a day. The dashboard is rendered, never hand-edited: `tools/dash stars grafana --write` writes it and `tools/test_stargazer.py` holds the committed file equal to the render. On a console the Stars page links straight to it (**Open in Grafana**).

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

**Fleet → Stars** (`/stars`) renders `/api/stars`, which is the committed document. The published site carries the same document, so the page reads the same there. Seven tabs, each a URL (`?tab=`):

- **Radar**: totals, starred repos by category and language (pick one to filter), stars per month, how alive the starred repos are, the top of the review list and the latest events.
- **Starred**: every starred repo, filtered by search, category, language, star list and fleet project, sortable by stars, 7-day gain, push date, health and match.
- **Trending**: your stars gaining fastest, then each search with stars a day, age and the closest fleet project; suspect rows are marked.
- **Fleet match**: every project with how many starred and discovered repos are close to it, then one project's terms and its starred and discovered matches with the shared terms.
- **Themes**: the AI groups over the stars, each with its summary, the fleet projects it feeds and its repos.
- **Map**: every repo close to a fleet project as a dot. Similarity to the fleet is across, stars (log) are up, the dot's size is how fast it rises and its colour is the category. Upper right is popular and relevant: look there first. *Starred only* narrows it, and a dot opens the repo.
- **Feed**: events by day.

Every table carries the AI verdict (hover for the summary), the review list shows each item's first idea, and the drawer has the full **AI review** (summary, verdict, the project it serves, why, ideas, model and date).

A repo opens in a drawer (`?repo=owner/name`) with every field, its AI review, its matches, why it is suspect if it is, and a `claude "Review github.com/<repo> for <project>: …"` command to copy into a local session. On a console, **Read GitHub now** runs `stars-refresh` (read-only, needs a token), **Review with AI** runs `stars-review` (asks first: it spends), **Push to Grafana** runs `stars-metrics`, and **Open in Grafana** opens the dashboard; a job that ends refreshes the page.

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
| `ai.enabled` / `model` / `budget_usd` / `max_turns` / `timeout_s` | true / `claude-sonnet-5-5` / 1.0 / 2 / 420 | the AI pass: its switch, an exact model id, the cap of one session (API-equivalent) |
| `ai.batch` / `max_batches` / `max_age_days` / `groups_min` / `groups_max` | 12 / 4 / 90 / 6 / 12 | repos per session, sessions per run, when a review is redone, how many themes |
| `metrics.push` / `endpoint` / `timeout_s` | true / `observability.claude_code.endpoint` / 3 | the push to the OTel collector after a refresh or a review; `STARS_OTLP_ENDPOINT` overrides it |

## Turning the loop on

The workflow is a new loop, so its schedule is off by default. After this lands and one manual run looks right:

```bash
gh workflow run stargazer.yml -R bamr87/bamr87 -f dry_run=true   # read and build, upload, publish nothing
gh variable set STARGAZER_ENABLED -R bamr87/bamr87 --body true    # then record the flip in _data/fleet.yml switches
```

Until then, `tools/dash stars refresh` and a commit of the two files keep the radar current.

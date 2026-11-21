# Link check

> Every link the fleet publishes — in the owned repos' Markdown and HTML, in the data the profile README is generated from, and on every live site — checked once, and each broken one reported with the file and line or the page that publishes it. Read-only: it files nothing and changes nothing.

The profile at github.com/bamr87 linked to `bamr87/zer0-demo-cookbook` weeks after that repository was archived during the zer0-CMS consolidation and then deleted. Nothing noticed, because the only link checks in the fleet were per-site (it-journey, bamr87.github.io, bash-365.com, zer0-mistakes) and the hub's own `check-drift.sh --links` reads only its built site. The link check reads the whole fleet the way a visitor meets it.

| | |
| --- | --- |
| **Tool** | [`tools/link_check.py`](../tools/link_check.py): `scan` (the default), `url URL…`, `targets` |
| **CLI** | `tools/dash links …` (the same arguments) |
| **Loop** | [`.github/workflows/link-check.yml`](../.github/workflows/link-check.yml), Wednesdays 10:43 UTC, off until `vars.LINK_CHECK_ENABLED` is `true`; a manual dispatch always runs |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) `links:` and `schedule.link_check` |
| **Output** | the terminal (or the job summary), `--json` (`link-check/v1`), `--markdown`; a local cache of `ok` answers in `.fleet/links/` |
| **Tests** | [`tools/test_link_check.py`](../tools/test_link_check.py) (offline) |

## Run it

```bash
tools/dash links                                  # the whole fleet: repos + live sites
tools/dash links --repo bamr87                    # one repo (the profile README) and its live site
tools/dash links --no-sites                       # files only, no crawl
tools/dash links --show broken,error,moved,unverified --json /tmp/links.json
tools/dash links url https://github.com/bamr87/zer0-demo-cookbook
tools/dash links targets                          # the repos and sites a scan reads
```

It exits 1 when a link is broken (`--fail-on error` also counts unreachable links; `--fail-on never` always exits 0). A local run reuses `ok` answers younger than `links.cache_hours` (24); `--fresh` asks every link again. github.com links need a GitHub token: `GH_TOKEN`, `GITHUB_TOKEN` or `gh auth token`, read-only use of public data; without one they are checked over HTTP and mostly come back `unverified`.

## What it reads

1. **Repos.** The hub and every checked-out submodule whose owner is in `hub.owners` (an upstream such as microsoft/skills is not ours to fix). Every tracked file with an extension in `links.extensions` (`.md`, `.markdown`, `.html`, `.htm`), minus `links.exclude_paths`. Fenced code, inline code, HTML comments, `<pre>`/`<code>`/`<script>`/`<style>` and Liquid `raw`/`highlight` blocks are blanked first, so a command in a code block is not a link. A relative link to a file (`docs/X.md`, `../img/a.png`; not a permalink such as `about/` or a page `.html`) is resolved from the file's folder against the repo's **tracked** files, case-sensitively, the way GitHub resolves it — a link that only works on a case-insensitive Mac is broken.
2. **Profile data.** The URL values of `links.data_files` in the hub — `_data/projects.yml` and `_data/portfolio.yml`, which `dash-gen readme` turns into the profile README's portfolio. A link there is reported at its line in the data, which is where it is fixed.
3. **Live sites.** The `live_url` and `docs_url` of every owned, non-archived registry entry and every `live_url` in the portfolio's `extra:`. Each site's own `sitemap.xml` (sitemap indexes followed) gives its pages, shallowest first, up to `links.max_pages` (200); a site with no sitemap is crawled breadth-first from its home page instead. Every `<a href>`, `<img src>`, `<script src>`, `<source src>`, `<iframe src>` and `<link href>` (not `preconnect`/`dns-prefetch`) on those pages is a link, internal ones included — a broken permalink shows up here even when the source file looks right. A site whose home page does not answer is one broken link and is not crawled.

Not links: anything that is not `http(s)`, placeholders (`your-username`, `<owner>`, `{{ … }}`, `${…}`), local and private addresses (`localhost`, `127.*`, `10.*`, `192.168.*`, `*.test`, `*.local`, a host with no dot), `example.com/.org/.net` and `links.exclude_urls`. They are counted, not checked.

### What is excluded, and why

`links.exclude_paths` holds records, not surfaces: the hub's dated `_reports/` (links to runs GitHub has since expired) and `test/evidence/`, the README context engine's crawled `context/`, and README's `docs/<repo>/` folders, which are aggregated copies of other repos' docs — their originals are scanned, and the rendered copies are reached by crawling bamr87.github.io/README/. A pattern is a glob against a repo-relative path; `repo:glob` limits it to one repo.

## How each link is checked

Every link is checked once, however many files carry it, and the report lists every place it appears.

- **github.com and raw.githubusercontent.com** go to the GraphQL API in batches (`links.github_batch` fields per query, four queries in flight), because github.com's HTML answers a crawler with 429. One `repository` node per repo, one aliased field per thing a link names inside it: a file or folder at a ref (`blob`, `tree`, `raw`, `blame`, `edit`; a branch with a slash in its name is tried at each split), an issue or pull request, a commit, a release tag, a workflow file behind an `actions/workflows/x.yml` badge, a discussion. Any other page of a repo (`actions/runs/…`, `compare`, `wiki`) is answered by the repo existing. A user or organization link asks `repositoryOwner`. A repository GraphQL cannot see is asked again over REST, which follows a rename: a renamed repo is `moved`, with its new name. The whole fleet costs a few hundred GraphQL points.
- **Everything else** is an HTTP `HEAD`, then a `GET` when `HEAD` does not answer `ok` (enough servers mishandle `HEAD` that only a `GET` may call a link broken), and one more `GET` after a 5xx. At most `links.per_host` (4) requests are in flight per host — 8 on `*.github.io`, 2 on github.com's HTML — and `links.workers` (32) overall, interleaved across hosts.

| Status | Meaning | Exit 1? |
| --- | --- | --- |
| `broken` | 404 or 410; a name that does not resolve; a GitHub repository, file, issue, release or workflow that does not exist; a relative link to a file that is not tracked | yes |
| `error` | 5xx, a timeout, a refused connection or a TLS failure, after the retries | with `--fail-on error` |
| `moved` | a GitHub repository that was renamed: the link still redirects, but the new name belongs in the source | no |
| `unverified` | the host refused a robot (401, 403, 429, LinkedIn's 999) — not evidence either way; listed with `--show unverified` | no |
| `ok` | answered, after redirects | no |

## The weekly run

`link-check.yml` checks out every submodule at its recorded pointer (shallow, LFS skipped), runs `link_check.py scan --fresh` with the job's own `GITHUB_TOKEN` (`contents: read`), writes the broken, error and moved links to the job summary grouped by the repo or site that publishes them, and uploads the full report (`links.json`, `links.txt`) as the `link-check` artifact for 30 days. It never files an issue (fleet-pulse's doctor is the fleet's one filer), never pushes, and by default never fails on a broken link: one dead third-party page would otherwise turn every run red and hide the next finding. Dispatch it with `fail_on: broken` to use it as a gate, `repo` to check one repo or site, `sites: false` to skip the crawl.

Its schedule is declared in `_data/fleet.yml` `schedule.link_check` (`test_schedule.py`), its switch in `switches.loops` as `hub/link-check`. It is a new loop, so its cron runs only once `vars.LINK_CHECK_ENABLED` is `true`:

```bash
gh variable set LINK_CHECK_ENABLED -R bamr87/bamr87 --body true
```

## Fixing what it finds

Fix the link where the report says it lives. A link in a generated file is fixed in its source: the profile README's portfolio is generated from `_data/projects.yml` and `_data/portfolio.yml` (`tools/dash-gen readme`), and README's `docs/<repo>/` copies come from the original repo. A link inside a submodule is fixed in that submodule's own repository, then the pointer is bumped (docs/SUBMODULES.md). A link to a page that moved goes to the new address; a link to something that is gone is removed, or pointed at an archived copy when the page was a citation.

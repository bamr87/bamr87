# Content atlas

The control plane already watches the fleet's machinery: workflow runs and their cost (Actions analytics), agent spend and turns (the lake, Phoenix), and what CI said (the log plane). None of that answers what the owner of a content site asks: what does this site publish, about what, how fresh is it, which topics are growing and which were dropped, and does the mix still match the story the site is meant to tell?

The **content atlas** answers those questions for every content site in the fleet. It also works in the other direction. A human records an **editorial plan** (a narrative plus pillars with target shares), approves or rejects the atlas's suggestions against it, and files the approved directives as issues in each site's own repository, where that site's content loop or a person picks them up.

```text
 content repos ──sync──▶ lake (.dash-lake/fleet.sqlite, content_* tables)
 (checkout / cached clone)          │
                                    ▼ report (offline)
 _data/editorial.yml ◀── approve / reject ── Harness Console → Content
   narrative, pillars,                          (or `dash content plan`)
   directives                                   │
        │                                       ▼
        └──────────── file --apply ──▶ one issue per approved directive
                                       in the site's repo (editorial:directive)
```

## The three files

| File | Committed | Owner | Holds |
| --- | --- | --- | --- |
| `_data/fleet.yml` → `content:` | yes | the contract | which sites are watched and how: scan roots, date semantics, hygiene rules, suggestion thresholds, the directive label |
| `_data/editorial.yml` | yes | **a human** | per site: `narrative`, `audience`, `voice`, `pillars` (match rules and `target_share`), and `directives` (the decisions) |
| `.dash-lake/fleet.sqlite` → `content_sites`, `content_docs`, `content_commits` | **no** (gitignored) | `dash content sync` | the extracted corpus: every document's front matter, body metrics and git history, plus each site's commit stream |

The lake is a cache of other repos, so it never enters git. The plan records decisions, so it goes through review like any other decision. The console and the CLI write the plan in the working tree with its comments preserved (a ruamel round-trip, byte-identical outside the edited lines), and committing the change is the approval of record.

## Commands

```bash
tools/dash content sync                    # every declared site (local checkout, else a cached blob-less clone)
tools/dash content sync --site it-journey  # one site;  --no-fetch = local checkouts/cache only
tools/dash content report [--site S] [--json]
tools/dash content brief --site lifehacker.dev
tools/dash content plan show [--site S]
tools/dash content plan approve|reject --site S --key pillar-gap:quests
tools/dash content plan add --site S --key human:my-idea --title "…" [--brief …] [--kind write] [--pillar id]
tools/dash content plan status --site S --key K --status done
tools/dash content file --site S           # DRY RUN: what would be filed
tools/dash content file --site S --apply   # one issue per approved directive, in the site's repo
```

The same operations run as jobs in the **Harness Console** (`tools/dash console`, then the **Content** tab). They are listed under the `content` group on the Jobs tab, and `content-file` with apply asks for confirmation like every other GitHub write.

## Where a site is read from

`sync` resolves each site in this order. The first match wins.

1. An explicit `checkout:` path on the site entry.
2. A sibling checkout named after the site or its repo under any `content.search_roots` entry. The defaults are `..`, so `~/code/lifehacker.dev` next to `~/code/bamr87` is found, and `projects`. `DASH_CONTENT_ROOTS` (an `os.pathsep` list) is searched first.
3. The checked-out submodule.
4. A **blob-less clone** (`git clone --filter=blob:none`) cached under `.dash-lake/content/<site>` and re-fetched on each sync. It keeps the whole commit history, which aging depends on, while downloading only the blobs of the current tree. Public repos clone without a token.

A local checkout is read as it stands, uncommitted drafts included, because those drafts are what an editor wants to see.

## What is extracted

The atlas reads files the same way Jekyll does. Anything under a `_name` directory is a collection (`pages/_posts/hacks/x.md` → collection `posts`, section `hacks`). A Markdown file without front matter is not a document. `_config.yml`'s `exclude` list is honoured, except when a site declares explicit `roots:`. irony-works needs that exception: its `vault/` reaches the build through `transplant.mjs`, so Jekyll's exclude says nothing about it.

For every document the atlas records the title, description, author, collection and section, tags and categories, the publication date (front matter, then the filename's `YYYY-MM-DD-` prefix, then `planted`/`created`), `lastmod`, and draft status. It also measures words, headings, links, wikilinks and images, excluding code fences and Liquid. From **one** `git log` pass it takes the first and last commit dates and the commit count. Each commit is classified as human or bot by its author.

Two details matter for correct numbers:

- **Shallow clones.** The boundary commit of a `--depth` clone "adds" every file, which would date the whole site to the day of the clone. The atlas skips boundary commits (it reads `.git/shallow`), and those files fall back to their front-matter dates.
- **`dates: git`.** In a knowledge base like `2005` or `china`, the front-matter `date` is the date of the subject (an article about 2005 is dated 2005). Set on a site, `dates: git` dates publication by first commit instead.

## What is analyzed

The analysis is pure SQL and Python over the lake: offline, deterministic, and fixture-tested.

- **Totals:** published documents, drafts, words, documents new in the last `recent_days`, last published, median age since last update, stale documents (untouched for `stale_days`), and documents with hygiene issues.
- **Activity:** documents published per month over 24 months, and content commits per week over 26 weeks, split into human and bot/agent. On an autopilot site, the bot share is the number to watch.
- **Aging:** a histogram over `aging_buckets`.
- **Structure:** collections and sections, each with document count, recent count, stale count and newest date. Authors, including the persona bylines on lifehacker.dev.
- **Topics:** top tags, each with its trend (last window vs the window before), plus rising and fading tags. A shared-topics table lists tags covered by two or more sites: candidates for cross-linking between sister sites, or signs that two narratives are competing for the same reader.
- **Hygiene:** `frontmatter-invalid`, `missing-<key>` for each key in `quality.require`, `description-length` outside `quality.description`, and `thin` below `quality.min_words`. `quality` can be overridden per site because the schemas genuinely differ: irony-works entries have no `description`, and it-journey's CI requires 120–160 characters.
- **Pillar coverage:** for each pillar, the documents it matches (any of `tags`, `categories`, `sections`, `collections`, `keywords` in the title or description, and `paths` prefixes), its share of all documents, its share of **recent** work compared with `target_share`, and the age of its newest piece. Documents that match no pillar are reported along with their top tags.

## Suggestions and the approval loop

Suggestions are deterministic and computed from the numbers above. Each one has a **stable key**, so a decision stays in force across re-syncs, and a key the plan already carries, in any state, is never suggested again.

| Key | Fires when | Kind |
| --- | --- | --- |
| `cadence` | nothing published for more than `cadence_days` | cadence |
| `pillar-gap:<id>` | recent share < target × `gap_ratio` | write |
| `pillar-over:<id>` | recent share > target × `over_ratio` (with ≥ 3 recent pieces) | hold |
| `pillar-stale:<id>` | the pillar's newest piece is older than `stale_days` | refresh |
| `define-pillars` | the site has no pillars yet (lists the top observed tags) | pillar |
| `unmapped` | more than `unmapped_share` of documents match no pillar | pillar |
| `refresh:<path>` | the oldest substantive stale documents (`refresh_top` per site) | refresh |
| `hygiene:<issue>` | any document has that front-matter issue | fix |

A directive moves through these states:

```text
proposed ──approve──▶ approved ──file --apply──▶ filed ──issue closed──▶ done
    │                    │                          │
    └──reject──▶ rejected ◀──────reject─────────────┘      (rejected/done → reopen → proposed)
```

`file` dedupes on a hidden marker (`<!-- editorial-directive key=… site=… -->`) against every issue carrying the label, open or closed. A directive filed from another machine, or one whose plan edit was never committed, is re-linked rather than filed twice. A closed issue marks its directive `done` on the next `file --apply` pass. The issue body quotes the site's narrative, so whoever picks it up in the site's repo sees the direction along with the task.

## Seeding and tuning the plan

The committed `_data/editorial.yml` was seeded on 2026-09-26 from each site's own CLAUDE.md and its observed mix. The targets are starting values, not measurements. The first report on that seed already showed things worth deciding:

- **it-journey:** machine-authored quest reports were 77% of new work against a 20% target, and the curriculum (quests) was 22% against 60%. The perfection loop's output was crowding out the curriculum.
- **lifehacker.dev:** docs made up 25% of recent work against a 10% target, and The Wire was under target.
- **irony-works:** four nursery drafts had front matter that does not parse as YAML. An unquoted `domain: …` colon breaks the whole mapping, so any YAML reader of those entries, Jekyll included, gets nothing from them.

To tune: move a target on the Content tab (Save targets), re-match a pillar, or reject a suggestion that does not apply. The wargames mirror, for example, carries a pre-rejected `cadence`, because a vendored mirror changes only when upstream does.

## Adding a site

Add an entry to `_data/fleet.yml` → `content.sites`. A registry project needs only `name:`, because the repo, live URL and branch come from `_data/projects.yml`. A site outside the registry also needs `repo:`. Run `tools/dash content sync --site <name>`, then write its narrative and pillars on the Content tab, which creates the entry in `_data/editorial.yml`. `test_content_atlas.py` fails if the plan names a site the contract does not declare.

## Limits

- **Read-only on content.** Only `file --apply` writes to a site repo, and it writes an issue, never a commit. The site's own loop and a human still decide what ships.
- **Local-only.** Nothing is published. The lake stays on this machine, like the rest of the local stack (docs/HARNESS-OPS.md, "The local stack").
- **Issues are the delivery channel.** Issues reach every site today: it-journey's issue autopilot and lifehacker.dev's triage both consume them. A per-site adapter would let a directive feed a site's native queue directly, for example lifehacker.dev's `_data/backlog.yml` or irony-works' domain rotation. None exists yet.

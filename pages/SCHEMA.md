---
schema: "0.1"
coverage: listed
---

# SCHEMA — pages

> The public site's long-form content: Markdown with YAML front matter, read by `tools/console/site_docs.py` and rendered by the console's page (docs/CONSOLE-PAGES.md).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `profile/` | dir | Long-form pages, each at `/<slug>` (About, Experience, Services, Contact) | terminal |
| `posts/` | dir | Dated writing, `YYYY-MM-DD-<slug>.md`, at `/blog/<slug>`, or at `/blog/YYYY-MM-DD-<slug>` for a series entry or a slug two files share; drafts show only on a console | terminal |

## Placement

- New standalone page → `profile/<slug>.md` (front matter: title, description, order, icon), then add the slug to `PROFILE_PAGES` in `tools/console/web/src/nav.ts` and a row in `tools/console/snapshot.py` `STATIC_ROUTES`.
- Dated writing → `posts/YYYY-MM-DD-<slug>.md`, slug in lowercase letters, digits and hyphens. Front matter: `title`, `date`, `excerpt` (or `description`; with neither, the first paragraph is the excerpt), `categories`, `tags`, `draft`. `draft: true` keeps a post off the public build: it shows only on a console.
- A one-off post is served at `/blog/<slug>`. A series entry is served at its dated stem, `/blog/YYYY-MM-DD-<slug>`, from the first one on, so no entry's address moves when the next lands; so is every post of a slug two files share. The series are listed in `SERIES` in `tools/console/site_docs.py`: the daily `YYYY-MM-DD-chronicle.md` (constitution § 23.2) and the weekly `YYYY-MM-DD-weekly-retro.md`, both drafted by the weekly routine. A new series is added there, and `tools/console/test_pages.py` holds every post to an address of its own.
- A chronicle or retro lands as a draft and is published only after a human or an agent has reviewed it, by removing `draft: true` (§ 23.4); `tools/dash weekly confirm --apply` is that review for the posts the weekly routine drafts (docs/WEEKLY.md).
- A new dashboard surface is a console page, not Markdown → `tools/console/web/src/pages/` (see tools/console/web/SCHEMA.md).

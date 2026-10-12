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
| `posts/` | dir | Dated writing, `YYYY-MM-DD-slug.md`, at `/blog/<slug>`; drafts show only on a console | terminal |

## Placement

- New standalone page → `profile/<slug>.md` (front matter: title, description, order, icon), then add the slug to `PROFILE_PAGES` in `tools/console/web/src/nav.ts` and a row in `tools/console/snapshot.py` `STATIC_ROUTES`; dated writing → `posts/YYYY-MM-DD-<slug>.md` (`draft: true` keeps it off the public build).
- A new dashboard surface is a console page, not Markdown → `tools/console/web/src/pages/` (see tools/console/web/SCHEMA.md).

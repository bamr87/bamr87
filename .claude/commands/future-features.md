---
description: Turn an idea into a full feature spec and place it on the right repo's roadmap (_data/roadmap.yml)
argument-hint: "[idea — optionally naming the target project]"
---

# Future Features — capture an idea as a roadmap-ready feature request

Idea: $ARGUMENTS

You are running the Future-Features capture flow. Turn the idea above into a
**complete, reviewable feature request** and place it on the correct repo's
roadmap. **Never** write to the backlog without explicit human approval.

This is the manual, single-idea entry point. The `feature-scout` sub-agent does
the same for ideas mined from a whole conversation — both share the schema and
backlog below.

## 1. Read the contracts
- **Backlog + schema:** [`_data/roadmap.yml`](../../_data/roadmap.yml) — read the
  header; every entry MUST conform, and ids are monotonic `FF-NNNN`.
- **Target repos:** [`_data/projects.yml`](../../_data/projects.yml) — the catalog.

## 2. Resolve the target repo (exactly one)
- If the idea names a project/repo explicitly, use it.
- Else match the idea's keywords / stack / domain against `_data/projects.yml`.
- If the idea is about **this monorepo / the dash / the profile / registry / CI
  itself**, target `bamr87` (`https://github.com/bamr87/bamr87`) — it is **not**
  in the registry.
- If two+ projects genuinely fit, **ask** with `AskUserQuestion` (offer the top
  candidates). Don't guess on a coin-flip.

## 3. Draft the full spec
Author every required schema field: `title`, `status: proposed`, `priority`,
`effort`, `category`, `problem`, `proposal`, `acceptance` (criteria list), plus
`scope.in`/`scope.out` and `risks` where useful. Be concrete and specific to the
chosen repo — read that project's README/code if it sharpens the scope. Assign
the next free `FF-NNNN` id (scan existing ids), set `source: manual`, `created`
to today's date, `issue_url: null`.

## 4. Present for review
Show the **rendered spec** (human-readable) AND the **exact YAML block**. Then use
`AskUserQuestion` with options: **Approve**, **Approve + open GitHub issue**,
**Edit**, **Reject**. Apply any edits and re-show before writing.

## 5. On approval — backlog it
- Append the YAML entry to `_data/roadmap.yml` (keep ids monotonic; keep the file
  valid YAML).
- If **Approve + open GitHub issue**: open an issue in the target repo with the
  `gh` CLI (repo convention — not MCP write tools, per
  `.github/docs/skills-agents-principles.md`):
  `gh issue create --repo <owner/repo> --title "<feature>" --body "<spec>" --label enhancement --label roadmap`
  — then set the entry's `issue_url`.
- Confirm the new id and the file changed. Don't commit/push unless asked; the
  surrounding session/PR handles that.

If **Reject**, write nothing.

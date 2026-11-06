---
description: Turn an idea into a full feature spec and place it on the right repo's roadmap (_data/roadmap.yml)
allowed-tools: Read, Edit, AskUserQuestion, Bash(gh issue create:*)
argument-hint: '[idea — optionally naming the target project]'
---

# Future Features — capture an idea as a roadmap-ready feature request

Idea: $ARGUMENTS

You are running the Future-Features capture flow. Turn the idea above into a **complete, reviewable feature request** and place it on the correct repo's roadmap. **Never** write to the backlog without explicit human approval.

This is the manual, single-idea entry point. The `feature-scout` sub-agent does the same for ideas mined from a whole conversation — both share the schema and backlog below.

## 1. Read the contracts

- **Backlog + schema:** [`_data/roadmap.yml`](../../_data/roadmap.yml) — read the header; every entry MUST conform. Ids (`FF-NNNN`) are **assigned at merge** — a new entry is a fragment [`_data/roadmap.d/<slug>.yml`](../../_data/roadmap.d/README.md) with `id: FF-NEW`; never pick a number.
- **Target repos:** [`_data/projects.yml`](../../_data/projects.yml) — the catalog.

## 2. Resolve the target repo (exactly one)

- If the idea names a project/repo explicitly, use it.
- Else match the idea's keywords / stack / domain against `_data/projects.yml`.
- If the idea is about **this monorepo / the dash / the profile / registry / CI itself**, target `bamr87` (`https://github.com/bamr87/bamr87`) — it is **not** in the registry.
- If two+ projects genuinely fit, **ask** with `AskUserQuestion` (offer the top candidates). Don't guess on a coin-flip.

## 3. Draft the full spec

Author every required schema field: `title`, `status: proposed`, `priority`, `effort`, `category`, `problem`, `proposal`, `acceptance` (criteria list), plus `scope.in`/`scope.out` and `risks` where useful. Be concrete and specific to the chosen repo — read that project's README/code if it sharpens the scope. Set `id: FF-NEW` and choose a kebab-case slug (the fragment filename) — never a number; set `source: manual`, `created` to today's date, `issue_url: null`.

## 4. Present for review

Show the **rendered spec** (human-readable) AND the **exact YAML block**. Then use `AskUserQuestion` with options: **Approve**, **Approve + open GitHub issue**, **Edit**, **Reject**. Apply any edits and re-show before writing.

## 5. On approval — backlog it

- Write the entry as a new fragment `_data/roadmap.d/<slug>.yml` (one mapping, `id: FF-NEW`; valid YAML). Do **not** append to `_data/roadmap.yml` — `tools/jev/number.py` numbers and appends it on `main` (`python3 -m tools.jev number plan` previews the id).
- If **Approve + open GitHub issue**: open an issue in the target repo with the `gh` CLI (repo convention — not MCP write tools, per `.github/docs/skills-agents-principles.md`): `gh issue create --repo <owner/repo> --title "<feature>" --body "<spec>" --label enhancement --label roadmap` — then set the fragment's `issue_url`, and refer to the entry in the issue as `FF-NEW:<slug>` (edit to the assigned id after merge). If the repo has Issues disabled or the create fails, skip it and keep `issue_url: null` — the local backlog is the source of truth.
- Confirm the slug and the fragment written (the number comes at merge). Don't commit/push unless asked; the surrounding session/PR handles that.

If **Reject**, write nothing.

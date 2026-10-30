<!-- kit: governance v0.1.0 · seeded from bamr87/bamr87 templates/governance/. Owned by this repo after seeding;
     change it ONLY through an amendment record in docs/amendments/ (see § 8). Validate: python3 <hub>/tools/governance_lint.py check . -->
# bamr87 — Constitution

> The rules every change to this repo must satisfy, whoever makes it — a human or an AI agent.
> Agents read this before [AGENTS.md](../AGENTS.md) conventions, the [PRD](../PRD.md), or the
> [feature catalog](../features/features.yml). Ratified by merged PR; amended only per § 8.

## 1. Mission

The `bamr87/bamr87` repo is simultaneously the GitHub profile README, the fleet control plane ("dash") that vendors every project as a Git submodule, and the public Harness Console site. It hosts shared standards, kits and reusable actions (e.g. `claude-run`) that the rest of the fleet consumes.

_Source: [PRD.md](../PRD.md)._

## 2. Invariants (non-negotiable)

These rules are lifted from the repo's own agent guide; breaking one is grounds to reject a PR.

- `_data/projects.yml` is the project registry; `.gitmodules` must agree on submodule paths, URLs, and branches. _(AGENTS.md)_
- Never commit a lockfile. _(CLAUDE.md)_
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers. _(CLAUDE.md)_
- Add/remove/rename files in the nearest `SCHEMA.md` in the same change. New directories need their own schema and a parent Structure row; follow `Placement` and `Forbidden`. _(AGENTS.md)_
- The Pages build runs under `/bamr87/`, so every in-app link goes through React Router's `basename` and every file URL through `asset()` (`web/src/api/backend.ts`) — never a bare `/path`. _(AGENTS.md)_
- Overrides live in the hub's `.fleet/compose/`, never in submodules. _(AGENTS.md)_
- Branches: all track `main`. Read the branch from `.gitmodules`; don't assume. _(CLAUDE.md)_
- Don't bundle changes across multiple submodules into one PR. _(CLAUDE.md)_
- Secrets (tokens, API keys) are never printed, logged or committed. _(fleet rule)_
- `CHANGELOG.md`, when present, is not hand-edited once release-please owns it. _(fleet rule)_

## 3. Authority and precedence

When two documents disagree, the higher one wins and the lower one is fixed in the same PR:

1. This constitution (and its ratified amendments in [docs/amendments/](amendments/))
2. [AGENTS.md](../AGENTS.md) — how to work here (commands, conventions, Definition of Done)
3. The PRD ([`PRD.md`](../PRD.md)) — what the product must do (requirement ids `FRn` / `NFRn`)
4. [features/features.yml](../features/features.yml) — what it does today (stable feature ids)
5. ADRs in [docs/adr/](adr/) and specs — why and how a specific change was made
6. Code, tests, generated files

## 4. Roles: humans and AI agents

| Actor | May | May not |
| --- | --- | --- |
| Maintainer (human) | Ratify amendments, PRD changes and releases by merging PRs; change settings, secrets, branch protection | — |
| AI agent | Read this file first; open PRs on a branch with Conventional Commit titles; update the feature catalog, PRD block and docs in the same PR as the change; propose amendments | Merge its own PRs; push to the default branch; force-push; change repo settings or branch protection; print or commit secrets; invent features or requirements (unknown = **TBD**) |

## 5. How the artifacts relate

| Artifact | Answers | Owned by | Rule |
| --- | --- | --- | --- |
| `docs/constitution.md` | What must always hold | Maintainer | Changes only by amendment (§ 8) |
| `docs/amendments/NNNN-*.md` | How and why the rules changed | Proposer → maintainer | Append-only; ratified by merged PR |
| `AGENTS.md` / `CLAUDE.md` | How to work here | Repo | Must link this file; `CLAUDE.md` imports `@AGENTS.md` |
| PRD | What the product must do | Maintainer | Requirements carry stable ids (`FRn`, `NFRn`) |
| `features/features.yml` | What the product does, where, proven how | Repo | Every user-facing feature has an id, `status`, location and `prd:` refs |
| PRD "Feature catalog" block | PRD → feature trace | Generated | `governance_lint.py prd-sync`; never hand-edit |
| `docs/adr/NNNN-*.md` | Why a hard-to-reverse decision was made | Proposer | One ADR per decision; an amendment may cite one |
| `CHANGELOG.md` | What shipped | release-please | Generated from Conventional Commits; never hand-edit |

## 6. Change process

| Change | Required in the same PR |
| --- | --- |
| Typo, docs fix, refactor with no user-visible effect | Conventional Commit title |
| New or changed user-facing feature | Entry in `features/features.yml` (`status`, `link`/`docs`, `prd:`), regenerated PRD block |
| New or changed requirement | PRD edit with a new `FRn`/`NFRn` id (ids are never reused), feature `prd:` refs updated |
| Hard-to-reverse technical decision | ADR in `docs/adr/` |
| New or changed work item (issue / PR) in a registry repo | Item in the portfolio project with required fields (§ 9) |
| Change to this constitution | Amendment record in `docs/amendments/` (§ 8) |

## 7. Quality gates

Every PR passes the checks the repo's guide names:

- `tools/check-drift.sh` _(AGENTS.md)_
- `tools/console/build-pages.sh` _(AGENTS.md)_
- `python3 tools/schema_lint.py check .` _(AGENTS.md)_
- `python3 .github/scripts/dash-gen/test_machine_api.py` _(AGENTS.md)_
- `python3 -m pytest .github/scripts/dash-gen/test_cv_fragment.py -q` _(AGENTS.md)_
- `python3 tools/console/test_pages.py` _(AGENTS.md)_
- `python3 <bamr87/bamr87>/tools/governance_lint.py check .` (feature catalog ↔ PRD, constitution, amendments)
- `python3 <bamr87/bamr87>/tools/projects_lint.py check` (work-tracking spec; live coverage when the token can read projects — § 9)

## 8. Amendments

This constitution changes only through a numbered record in [docs/amendments/](amendments/) (`NNNN-kebab-slug.md`, copied from [0000-template.md](amendments/0000-template.md)):

1. **Propose** — open a PR that adds the record (`Status: proposed`) *and* the edit to this file it describes. Name what it affects: constitution sections, PRD requirement ids, feature ids.
2. **Review** — the maintainer reviews; an agent never approves or merges its own amendment.
3. **Ratify** — merging the PR ratifies it. The record says `Status: ratified` and `Ratified by:` the PR. A rejected or withdrawn PR keeps its record with that status; numbers are never reused.
4. **Supersede** — a later amendment may replace an earlier one; mark the old record `superseded by NNNN`.

Records are append-only history: fix a ratified rule with a new amendment, never by editing an old record. [0001](amendments/0001-ratify-constitution.md) ratifies this document.

## 9. Work tracking

GitHub Projects (v2) are the system of record for work across the fleet ([amendment 0003](amendments/0003-github-projects-work-tracking.md), [plan](PROJECTS-FRAMEWORK.md)):

- One **Fleet Portfolio** project holds every open issue and PR of every registry repo; **domain projects** hold a subset. Projects, fields, options, lifecycle and the label map are defined only in [templates/projects/framework.yml](../templates/projects/framework.yml).
- Required fields: Status, Priority, Area, Repo; plus Feature ID (`HUB-NNN`, a `features.yml` id) and PRD req (`FRn`/`NFRn`) when the item changes a feature or a requirement.
- Status lifecycle: Inbox → Triaged → Ready → In progress → In review → Done, with Blocked and Won't do. Labels mirror fields; the project wins on conflict.
- Agents read and move items only through the console MCP layer or the sync workflow.


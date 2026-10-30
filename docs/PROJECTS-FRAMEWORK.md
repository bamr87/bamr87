# Fleet work-tracking framework — GitHub Projects (v2)

> Status: **proposed** — [amendment 0003](amendments/0003-github-projects-work-tracking.md), features `github-projects-framework`, `projects-coverage-gate`, `projects-sync-console` and PRD requirements `projects-coverage`, `projects-sync`, `projects-scope-honest` (fragments in `features/features.d/`; ids assigned at merge, amendment 0002).
> Spec (single source): [templates/projects/framework.yml](../templates/projects/framework.yml). Gate: `python3 tools/projects_lint.py check`.

## 1. Current state (audit 2026-10-29)

| Area | Finding |
| --- | --- |
| Projects (v2) | **None readable.** `gh project list` fails for bamr87, year-of-ai, ai-world-view, bash-365, EissaLab and zer0-mistakes: the harness token has `gist, read:org, repo, workflow`, no `read:project`/`project`. Existence of projects is therefore unverified. |
| Open work | bamr87: 145 issues / 62 PRs; year-of-ai 17/1; ai-world-view 8/0; bash-365 7/1; EissaLab 3/0 (gh search). `fleet_triage.yml`: 45 repos scanned, 128 open issues, 47 PRs, 18 repos red. |
| Labels (hub) | 50 labels, overlapping vocabularies: GitHub defaults (`bug`, `enhancement`, `documentation`…), `agent:*` state machine (queued/ready/in-pr/blocked/hold/done), `P0–P3`, `size:xs–xl`, `area:*` (docs/a11y/feat/perf), and ad-hoc (`daily-analysis`, `actions-review`, `optimization`). `docs` and `documentation`, `feature` and `enhancement` duplicate each other. |
| Templates | Hub: `bug_report.yml`, `feature_request.yml`, `documentation.yml`, `page_feedback.yml` + legacy `custom.md`, `issue_template.md`. None asks for a feature id or PRD req. `bamr87/.github` has `workflow-templates/`, no project workflow. |
| Milestones | 0 in the hub; none used fleet-wide. |
| Flow today | Issues → issue-pipeline (`issue-pipeline.yml`, `_data/issue_pipeline.yml`) labels `agent:*` → AI lane / bots open PRs → human merge. Status lives in labels and in `_data/fleet_triage.yml` / the console Work board, not in a project. Nothing links an item to HUB-NNN or FRn. |

## 2. Design

### Hierarchy
- **Fleet Portfolio** (user-owned `bamr87`, so it can hold items from every org): every open issue/PR in the registry + hub. Views: Inbox, Board by Status, Roadmap by Iteration, By Repo, By Feature, Bots.
- **Domain projects** (subsets, same fields): Platform & Harness, Sites & Content, Security & Dependencies, and an org program per org once it has >10 open items.
- Domain membership is derived (repo / Area / labels) by the sync — items are never curated by hand in two places.

### Fields
Status, Priority, Area, Repo (required); Size, Iteration (2 weeks), Owner (Amr or a bot team / JEV); Feature ID (`HUB-NNN`-style, any repo prefix) and PRD req (`FRn`/`NFRn`) required when an item changes a feature or requirement. Text fields, validated by pattern against `features.yml`/PRD, because single-select options cap at 50 and the fleet has hundreds of ids.

### Lifecycle
Inbox → Triaged → Ready → In progress → In review → Done, plus Blocked and Won't do. `agent:*` labels become a mirror of Status (written by the sync), so the issue pipeline keeps working unchanged in phase 1–2.

### Label harmonization
Canonical set = Priority (`P0–P3`), Size (`size:*`), Area (`area:*`, `security`, `dependencies`), type (`bug`, `feature`, `chore`, `docs`, `ci`, `refactor`, `test`), and the `agent:*` mirror. Aliases are renamed (`documentation`/`docs`→`area:docs`, `enhancement`/`area:feat`→`feature`, `github_actions`→`ci`); `custom`, `optimization`, `daily-analysis`, `actions-review` retire. The map lives in `framework.yml`; the existing `standardize-fanout` applies it per repo.

### Automation
1. **Auto-add**: reusable workflow `bamr87/.github/.github/workflows/project-auto-add.yml` (skeleton: `templates/projects/auto-add.yml`) using `actions/add-to-project` with a `PROJECTS_TOKEN` (GitHub App preferred over PAT).
2. **projects_sync.py** (phase 2, hub): reconcile project fields/views from the spec; map labels→fields; mirror Status→`agent:*`; fill Feature ID/PRD req from issue forms or `Refs: HUB-NNN` / `FRn` in PR bodies; nightly from `fleet-pulse`.
3. **features ↔ project**: each `features.yml` entry with `status: planned|partial` gets a tracking item (draft issue) in the portfolio; `status` changes propagate both ways; PRD requirements without an open item are reported.
4. Issue forms gain optional *Feature ID* and *PRD req* inputs.

### Governance
- Constitution § 9 + amendment 0003 (this PR). `tools/projects_lint.py`: `check` (offline, in the gates now) and `coverage` (live; warning 30 days, then error). Reports `scope_missing` rather than passing silently (NFR-NEW:projects-scope-honest).
- Console: dash-gen collector → `_data/projects_board.yml` (coverage per repo, untracked items, missing fields, WIP by Status/Owner) and a **Projects** panel next to Triage/Work.
- MCP layer: read tool `projects_board`, confirm-gated write `project_item_set` (behind `HARNESS_MCP_ALLOW_WRITES`). Bots: Fleet Ops triages Inbox; Repo Janitor applies the label map; Security Warden owns the Security project; QA Lead moves In review→Done on verified evidence; Platform Architect owns the spec. JEV / conflict-triage consumes project Status instead of its own state once that stream lands (coordinated — no duplication here).

### DevOps methodology
Constitution § 10 (amendment `projects-devops-methodology`, numbered at merge) adds the working rules on top of this framework: the Fleet portfolio project is [user project #14](https://github.com/users/bamr87/projects/14); every task (including AI-agent and submodule work) is an item there with Status and Priority; multi-phase work is an `epic` (`#6E40C9`) with ordered sub-issues (scope, acceptance criteria, guardrails); no change to the live Mac before an approved deploy step; read-only-by-default tools; AI cost labelled "API-equivalent (estimate)". Phase 4 fan-out also adds a § 10 pointer to each submodule's `AGENTS.md`.

## 3. Rollout (all after ratification)

| Phase | What | Gate |
| --- | --- | --- |
| 0 — ratify | Merge this PR. Grant `project` scope (`gh auth refresh -s project`) or create the GitHub App / `PROJECTS_TOKEN`. | Amr |
| 1 — create | Create Fleet Portfolio + Platform project from the spec; publish auto-add workflow v1 in `bamr87/.github`; wire hub + bamr87 repos. Backfill open items. | coverage report (warn) |
| 2 — sync | `projects_sync.py`, label→field map, `agent:*` mirror, issue-form fields, features/PRD sync. | `projects_lint coverage` warn |
| 3 — console | collector, `_data/projects_board.yml`, Projects panel, MCP tools; bots switched to project Status. | console test_pages |
| 4 — fan-out | Label harmonization + auto-add caller per repo via `standardize-fanout`, in waves: (a) hub, `.github`, zer0-mistakes; (b) bamr87 user repos; (c) year-of-ai, ai-world-view; (d) bash-365, EissaLab. Org programs created when >10 open items. | per-wave PRs, never auto-merged |
| 5 — enforce | `coverage` becomes an error 30 days after ratification; milestones retired in favour of Iteration. | quality gate |

## 3a. Console surface and write-back (epic #468)

The console reads and writes Projects through two modules, governed by constitution § 11 (amendment `projects-write-back`, proposed):

| Module | Role |
| --- | --- |
| [`tools/console/gh_projects.py`](../tools/console/gh_projects.py) | Read-only GraphQL over every owner (bamr87, year-of-ai, ai-world-view, bash-365, EissaLab), TTL cache, item normalisation, and the linked graph (project → item → issue/PR → commit → repo → FEAT/FR). A token without `read:project` returns `scope_missing`, never an error. |
| [`tools/console/gh_projects_write.py`](../tools/console/gh_projects_write.py) | Write-back: mutation `ALLOWLIST`, deny words (merge, delete, settings…), `plan()` dry run with a deterministic `plan_id` and no-op detection, `apply()` only with `HARNESS_PROJECTS_WRITES=1` + `confirm=true` + the same `plan_id`, stale-plan refusal, 50 ops/plan and 200/hour caps, redacted JSONL audit (`state/audit/github-writes.jsonl`, override `HARNESS_PROJECTS_AUDIT`). |

Token: `PROJECTS_TOKEN` (else `GH_TOKEN`/`GITHUB_TOKEN`) with `read:project` to read and `project` plus issues/PR write on registry repos to apply; Amr provisions it in the console credential store or as an Actions secret. Phases: P0 #469 (this layer, flag off), P1 #470 read API + MCP + page, P2 #471 linked view, P3 #472 confirm UI + MCP write tools, P4 #473 auto-add + backfill #453, P5 #474 deploy (needs Amr).

## 4. Post-ratification actions (not done in this PR)
Grant token scope; create projects/fields/views; publish the reusable workflow; add `PROJECTS_TOKEN` secret; rename/retire labels; edit issue forms; add callers per repo.

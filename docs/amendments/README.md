<!-- kit: governance v0.1.0 -->
# Amendments — bamr87

The append-only log of changes to [the constitution](../constitution.md). Process: constitution § 8.

- A proposal is written as [`proposed/<kebab-slug>.md`](proposed/) with `**Number:** NEW` (copy [0000-template.md](0000-template.md)); `python3 -m tools.jev number apply` numbers it `NNNN-kebab-slug.md` here at merge and appends its row below. Numbers are never reused (amendment [0002](0002-conflict-free-numbering.md)).
- Status: `proposed` → `ratified` (PR merged) | `rejected` | `withdrawn` | `superseded`.
- Validate: `python3 <bamr87/bamr87>/tools/governance_lint.py check .`

| # | Title | Status | Affects |
| --- | --- | --- | --- |
| [0001](0001-ratify-constitution.md) | Ratify the constitution | ratified on merge | whole constitution |
| [0002](0002-conflict-free-numbering.md) | Assign sequential ids at merge, not in a pull request | proposed | constitution §2, §5, §6, §8; FR28, NFR11; HUB-035 |
| [0003](0003-github-projects-work-tracking.md) | GitHub Projects as the fleet's system of record for work | proposed | § 6, § 7, § 9; FR-NEW:projects-coverage, FR-NEW:projects-sync, NFR-NEW:projects-scope-honest; HUB-NEW:github-projects-framework, HUB-NEW:projects-coverage-gate, HUB-NEW:projects-sync-console |

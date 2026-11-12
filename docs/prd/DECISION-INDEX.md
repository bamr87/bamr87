# PRD — Decision index

> **Status: proposed.** Implemented in the pull request that proposes it; the requirements below are ratified when the maintainer merges it.
> Feature: `HUB-NEW` (slug `decision-index`) in [`features/features.d/decision-index.yml`](../../features/features.d/decision-index.yml). Number assigned at merge.
> Requirements: `FR-NEW:decision-index`, `NFR-NEW:decision-index-budget`. Serves [`FR26`](../../PRD.md) (the MCP layer's read tools) and [`NFR20`](../../PRD.md) (surface parity), and reports on the gates of [`FR42`](../../PRD.md) and [`FR57`](../../PRD.md).
> Operator doc: [`docs/DECISION-INDEX.md`](../DECISION-INDEX.md).

## 1. Overview / problem

Only the maintainer ratifies amendments, passes the review gate and merges gated pull requests (constitution § 8, § 12). What waits on him is spread over about forty repos. Answering "what do I need to decide?" meant sweeping each repo for its issues, pull requests and check states: hundreds of GitHub calls and many minutes, for a question asked every day by a person and by the agents working for him.

## 2. Goals and non-goals

**Goals:** one call that returns the whole decision queue; an answer in seconds when GitHub must be read and at once when it was read lately; a hard time limit with a partial answer instead of a wait; an answer that always says how old and how complete it is; the same answer on the CLI, the console API and MCP.

**Non-goals:** a console page (a later change, with a verify scenario and evidence); merging, labelling or commenting from the queue (constitution § 11 and § 12 are unchanged); a scheduled refresh workflow; ranking or recommending which decision to take first; Dependabot security alerts (pull requests only).

## 3. Requirements

- **FR-NEW:decision-index** — The product must answer in one call, on the CLI, the console API and MCP, what waits on the maintainer across every repo of the hub's owners: issues and pull requests carrying the review-gate label, pull requests that change a constitution, an amendment or an ADR, Dependabot pull requests that fail or are a major bump, and pull requests that are ready to merge, each with the reason it is listed and a per-repo inventory of open pull requests, Dependabot pull requests and issues.
- **NFR-NEW:decision-index-budget** — The decision queue must answer inside a declared time budget from a local index that is refreshed when older than its TTL; when GitHub cannot be read in time or at all it must return what it has, state whether the answer is fresh, partial, stale, expired or unavailable, name each failure, never present old data as current, never write to GitHub and never publish or return a token or a private repo's items.

## 4. User stories

| ID | As… | I want… | So that… |
| --- | --- | --- | --- |
| US1 | Amr | one command that lists everything waiting on my decision, grouped by kind, with a link each | I start the day on the list, not on a sweep |
| US2 | Amr | to see why each item is on the list (the label, the files it changes, the bump, its merge state) | I can decide from the row, or know what to open |
| US3 | Amr | amendment, constitution and ADR pull requests listed apart from routine merges | ratification is never buried under Dependabot |
| US4 | an agent asked "what does Amr need to decide?" | one MCP read tool that returns the queue | I answer in one call instead of forty, inside my context |
| US5 | an agent or a script | the answer to say how old and how complete it is | I never report a stale queue as today's |
| US6 | Amr on a slow connection or a spent rate limit | the last answer, dated, instead of a spinner or an error | I can still work from it and know what to distrust |
| US7 | the operator of the console | the index to stay on my machine | a private repo's titles never reach the public site |
| US8 | the owner of the fleet's GitHub quota | a read that costs about a dozen requests and stops when the quota is low | the question does not starve the loops |

## 5. Phases

| Phase | Acceptance |
| --- | --- |
| P0 Index, CLI, API, MCP (this change) | `tools/dash decisions`, `/api/decisions` and `decision_queue` return one document; a cold read of the live fleet finishes inside `decisions.budget_s`; the fixture tests cover every row of § 6 |
| P1 Console page | a Decisions page over `/api/decisions` with a verify scenario and an evidence bundle; the sidebar counts the queue |
| P2 Warm index | a console job or LaunchAgent runs `decisions-refresh` on a cadence, registered where schedules are declared |

## 6. Design for Failure

| Failure | Behaviour | Signal in the answer |
| --- | --- | --- |
| GitHub slower than the budget | return at the budget with the scan's rows, the merge state read so far and the previous index for the rest; the next call resumes | `status: partial`, error `budget`, `parts.enrich.pending` |
| No token, refused token, no access | serve the index; send nothing further | error `no_token` / `auth` / `forbidden`, `hint` |
| Rate limit spent | serve the index; do not retry | error `rate_limited` with the reset time |
| Quota under the floor | run the scans, skip the merge-state queries | error `rate_floor` |
| GitHub 502 / 504 | halve the search page, split the batch, ask again | none when it recovers; `upstream_timeout` when one item cannot be read |
| Network down | serve the index | error `network`, `status: stale` |
| Search truncated at 1000 | do not call the scan complete; drop nothing | error `truncated` |
| Index older than the TTL and unreadable GitHub | serve it, dated | `status: stale`, then `expired` past `max_stale_s` |
| No index and no GitHub | return an empty queue that says so | `status: unavailable` |
| Corrupt or foreign index file | set aside, rebuild, never serve | a warning |
| Index not writable | answer anyway | a warning |
| Concurrent refreshes | one reads, the other waits inside its budget | error `busy` when the wait ran out |
| Console down | the CLI needs none; the MCP tool reads the index in its own process | `via` |

## 7. Prior art and build decision

Constitution § 10.8. The survey is in the operator doc ([Prior art and the build decision](../DECISION-INDEX.md#prior-art-and-the-build-decision)): the PM review, the triage snapshot and inbox, the Work board, per-repo `gh` calls and the Fleet project each answer a neighbouring question, and none joins the four kinds inside an interactive budget. Decision: build one small read-only module beside `gh_projects.py`, reusing the console's token resolution, redaction and MCP client.

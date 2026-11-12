# Decision index

> What waits on the maintainer across the whole fleet, answered in one call from a local index: `needs-amr` items, pull requests awaiting ratification, failing or major Dependabot pull requests and ready-to-merge pull requests. Read-only, $0, no model.

"What does Amr need to decide?" used to be answered by sweeping every repo one at a time: list its issues, list its pull requests, read each one's checks. Across about forty repos that is hundreds of calls and, in practice, many minutes. The decision index asks GitHub the same thing in a handful of GraphQL queries, keeps the answer on disk, and serves it until it is old. Measured on 2026-11-11 against the live fleet (81 open pull requests, 15 gate-labelled issues, 60 repositories): a cold read took 6.3 s and 12 queries, and the next call took 0.2 s and none.

| | |
| --- | --- |
| **Module** | [`tools/console/decision_index.py`](../tools/console/decision_index.py) (`decision-queue/v1`; the index file is `decision-index/v1`) |
| **Config** | `_data/fleet.yml` `decisions:`; the owners searched are `hub.owners` |
| **CLI** | `tools/dash decisions [queue \| refresh \| status] [--kind K] [--repo R] [--limit N] [--refresh auto\|never\|force] [--budget S] [--repos] [--json]` |
| **API** | `GET /api/decisions?kind=…&repo=…&limit=…&refresh=…&budget=…` · operations `decisions`, `decisions-refresh` |
| **MCP** | `decision_queue` (`kind`, `repo`, `limit`, `refresh`, `budget_s`); with no console it reads the same index in the MCP process |
| **Page** | none yet: the operations' logs on the console's Operations page |
| **Index** | `.fleet/decisions/index.json` (gitignored, mode 600; `DASH_DECISIONS_INDEX` moves it) |
| **Tests** | `python3 tools/console/test_decision_index.py` · `test_console.py` (the route) · `test_mcp_layer.py` (the tool) |
| **Requirements** | [docs/prd/DECISION-INDEX.md](prd/DECISION-INDEX.md) |

## Run it

```bash
tools/dash decisions                          # the queue: served from the index, read from GitHub when it is past its TTL
tools/dash decisions --kind ratification      # one kind: needs_amr | ratification | dependabot | ready_to_merge
tools/dash decisions --repo zer0-mistakes --repos   # one repo, with the per-repo inventory
tools/dash decisions --refresh never --json   # the index as it is: no GitHub call, the document the API returns
tools/dash decisions refresh                  # read GitHub now under the longer budget; exits 1 unless the read finished clean
tools/dash decisions status                   # how old each part of the index is, and the last read's errors
```

The token is the console's: `GH_TOKEN`, then `GITHUB_TOKEN`, then the `gh` login. It needs to read the repos (`repo` for private ones) and nothing else. Every call is a GraphQL query; the module holds no mutation.

## The queue

An item can be of several kinds; it is listed under the first, and `kinds` names them all.

| Kind | An item is one when | Read from |
| --- | --- | --- |
| `needs_amr` | an open issue or pull request carries a gate label (`decisions.labels.gate`, by default `needs-amr`: the review gate of constitution § 12.4) | the search |
| `ratification` | an open pull request changes a constitution, an amendment record or an ADR (`decisions.ratification.paths`), which only the maintainer's merge ratifies or accepts (§ 8, § 12.3); the ratification-record branch `chore/jev-ratify` is automation's and is left out | its changed files |
| `dependabot` | a Dependabot pull request's checks fail, it conflicts with its base, or its title states a major bump (under 0.x, a minor one) | its title and checks |
| `ready_to_merge` | a pull request is not a draft, is `MERGEABLE` and `CLEAN`, its checks pass (or the repo has none), no review asks for changes, and it carries no hold label (`decisions.labels.hold`) | its merge state |

Every item says `why` in words, and carries its `checks`, `mergeable`, `merge_state`, `review`, `labels`, `age_days` and `url`. A draft, a pull request that is behind or conflicting, and one whose checks fail are not decisions yet; they are counted per repo in the inventory. A grouped Dependabot update states no version, so it is listed as a major bump only when its title says so; it still appears when it fails or is ready.

`repos` is the inventory: per repo the decisions by kind, the open pull requests the search found with their draft, Dependabot, failing and conflicting shares, and the repo's own open-issue count. `prs_reported` appears where a repo's own pull-request count disagrees with the search, and a warning names the difference fleet-wide: that is how a search that silently returned less than the truth shows.

## How it reads the fleet

| Step | Query | Why this shape |
| --- | --- | --- |
| Scan | one `search` for every open pull request under `hub.owners`, one for the gate-labelled issues, one for the repositories with their open-issue and pull-request counts; all three at once | three queries cover what a per-repo sweep needs over a hundred for |
| Enrich | `nodes(ids: …)` for the pull requests the scan found, `enrich_batch` at a time, `concurrency` at once: `mergeable`, `mergeStateStatus`, `reviewDecision`, the check rollup, the changed paths | these fields are slow on GitHub's side. One page of 100 pull requests carrying them ran past GitHub's own 10 s limit and came back as a 502; ten at a time, eight in flight, took about four seconds for 81 |

A pull request whose `mergeable` is still `UNKNOWN` is asked once more, because GitHub computes it after the first ask. The budget goes first to pull requests that can be decided (not drafts), then to the ones read longest ago.

## Freshness

`status` is derived from the age of each part, never assumed.

| `status` | Means | What a caller should do |
| --- | --- | --- |
| `fresh` | both scans and every pull request's merge state were read within `ttl_s` | use it |
| `partial` | some parts are current and some are not: a read was cut by the budget, or one query failed | use the rows that are there; `warnings` says what may be missing, and the next call resumes with only the old parts |
| `stale` | nothing is within `ttl_s` and GitHub could not be read; the index is at most `max_stale_s` old | use it as of `read_at`; `errors` says why |
| `expired` | older than `max_stale_s` | treat every row as a lead to check |
| `unavailable` | there is no index and GitHub could not be read | fix what `hint` names |

`refresh=auto` (the default) reads GitHub only when the status is not `fresh`, and only the parts that are old. `never` serves the index whatever its age and makes no call. `force` reads everything now. An item whose own data is older than the TTL carries `stale: true`; a pull request whose merge state was never read carries `enriched: false`.

## Design for Failure

| Failure | What happens | What the answer says |
| --- | --- | --- |
| GitHub is slow | the answer returns at `budget_s` with what was read: the label and title rows from the scan, the merge state of as many pull requests as fitted, and the previous index for the rest | `status: partial`, an error of kind `budget`, `parts.enrich.pending`; `tools/dash decisions refresh` or the next call finishes it |
| No token | no call is made; the index is served | error `no_token`; `hint` names the GitHub page, `GH_TOKEN` and `gh auth login` |
| The token is refused (401), or lacks access (403) | the index is served; queued queries are not sent | error `auth` or `forbidden` |
| The rate limit is spent | not retried; the index is served | error `rate_limited` with the reset time |
| The token's quota is low (`min_rate_remaining`) | the scans run, the merge-state queries do not: a decision queue must not spend the quota every other loop shares | error `rate_floor`; label and title rows are complete |
| A 502 or 504 on a search page | the page is halved (down to 10) and asked again | nothing, when the smaller page works |
| A 502 on a merge-state batch | the batch is split in two until the one pull request that cannot be read is alone | error `upstream_timeout` for that one; the rest are read |
| The network is down | the index is served | error `network` |
| The search returns less than it counted (GitHub's 1000-result cap) | the scan is not called complete, so nothing it did not return is dropped | error `truncated` |
| A scan fails part way | what it read is refreshed; what it did not reach keeps its older date | `status: partial`, `stale: true` on the older rows |
| GraphQL answers with data and errors | the data is used | error `graphql_partial` |
| The index file is corrupt, foreign, or built for other owners or gate labels | it is set aside and rebuilt; it is never served | a warning |
| The index cannot be written | the answer is still returned | a warning |
| Two calls to one console refresh at once | one reads; the other waits inside its own budget, then serves what the first wrote (two processes may both read: the file is replaced whole, so the later one wins) | error `busy` when the wait ran out |
| The console is down | `tools/dash decisions` needs no console; the MCP tool reads the same index in its own process | `via` on the MCP answer |
| A bug in one query's handling | the task's error is caught and reported; the wait never hangs | error `internal` |

Error messages and titles pass the console's redaction; a token value is never returned, logged or written to the index.

## What it never does

- Write to GitHub. The module sends three GraphQL documents, each a `query`, and `test_decision_index.py` holds that. Merging, labelling and commenting stay with the maintainer and with the § 11 write-back service.
- Publish. The index is read with the operator's token and can hold a private repo's titles, so `/api/decisions` is not part of the public snapshot (`test_pages.py` holds that) and the file is gitignored and owner-only.
- Run on a schedule or call a model. Nothing refreshes it unless someone asks; a schedule that wants a warm index runs the `decisions-refresh` operation.
- Decide. `ready_to_merge` reports GitHub's own merge state; whether an agent may merge is still constitution § 12, rechecked against live state at merge time.

## Configuration

`_data/fleet.yml` `decisions:` holds every knob, and `decision_index.DEFAULTS` holds the same values as the fallback (`test_decision_index.py` keeps them equal). `ttl_s` and `budget_s` are the two that matter day to day; `labels.gate` widens the queue (`jev:needs-human` and `human-review` are the other human brakes the fleet uses); `ratification.paths` are regular expressions over changed paths. `tools/dash config show decisions` prints the block.

## Prior art and the build decision

Constitution § 10.8 asks for this before a new console surface.

- **Need.** The question is asked daily, by the maintainer and by agents acting for him. The per-repo sweep took minutes and hundreds of calls against a quota every loop shares.
- **`tools/dash pm` (the PM review).** Reads every open issue and pull request per repo, daily, and aligns them with the Fleet project. It answers "what is out of line with the project", takes minutes by design and is a snapshot from the morning. Not a fit for an interactive question; its `gate_not_mirrored` finding stays the check that the label and the project agree.
- **`_data/fleet_triage.yml` and the fleet inbox (`fleet_inbox`).** Committed daily; flags items by health, not by who must decide, and holds no merge state.
- **The Work board (`/api/work`, `work_board`).** Every open item on the loops' lanes, about 390,000 characters. It orders work for the loops; it does not say what is ready to merge or what awaits ratification.
- **`gh search prs` / `gh pr list` per repo.** What the sweep was. No merge state in search results, one call per repo for the rest.
- **GitHub Projects (the *Needs Amr* status).** Covers the gate label only when the project mirrors it, and reading project items needs the `project` scope.
- **Decision.** Build, small: one module beside `gh_projects.py`, reusing its redaction, the console's token resolution and the MCP layer's client. Nothing existing joins the four kinds, and none answers inside an interactive budget.

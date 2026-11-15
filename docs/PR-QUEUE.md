# PR queue

> Every open pull request of the hub and the registry repos in one queue: its checks with superseded runs set aside, the review gate and its reason, the merge method its repo allows, and who moves it next. Select rows, choose a bulk action, review its plan, and an agent applies exactly that plan once the maintainer confirms.

On 2026-11-15 a Claude Code session triaged all 160 open pull requests in 39 fleet repos. None was agent-mergeable: the hub's `gate_paths` (`tools/weekly/closeout.py`) held anything that touches `.github/`, `templates/`, `tools/fleetcore/` and similar paths, and repo rules and major or security bumps held the rest. Doing it took about forty subagents and a scratchpad of one-off scripts: a GraphQL fetch, a marker-edit comment poster, a live-recheck merger, a sequential re-runner. The PR queue is that work as a standing console surface, built on the decision index and the close-out's own rules instead of a second implementation.

| | |
| --- | --- |
| **Model** | [`tools/fleetcore/prqueue.py`](../tools/fleetcore/prqueue.py) (`pr-queue/v1`, pure: no network, no process, no write) |
| **Reads, plans, applies** | [`tools/console/pr_queue.py`](../tools/console/pr_queue.py) (`pr-queue-plan/v1`; the cache is `pr-queue-detail/v1`) |
| **Config** | `_data/fleet.yml` `pr_queue:`; the gate reuses `weekly.closeout` and `jev.allowed_authors` |
| **CLI** | `tools/dash prs [queue \| refresh \| plan \| apply \| actions]` |
| **API** | `GET /api/prs` · `POST /api/prs/plan` · `GET /api/prs/plan/{id}` · `GET /api/prs/result/{id}` · operations `prs`, `prs-refresh`, `prs-act`, `prs-agent` |
| **MCP** | `pr_queue` (read) · `pr_queue_plan` (a plan; writes nothing to GitHub) |
| **Page** | the console's **Fleet → PR queue** (`/prs`); never in the public snapshot |
| **State** | `.fleet/prqueue/` (gitignored, owner-only; `DASH_PRQUEUE_DIR` moves it): `detail.json`, `plans/<id>.json`, `results/<id>.json` |
| **Agent** | `local:pr-queue-agent` in `_data/agents.yml` (§ 29) |
| **Tests** | `python3 tools/test_fleetcore_prqueue.py` · `python3 tools/console/test_pr_queue.py` · `test_console.py` (ops, routes) · `test_mcp_layer.py` (tools) |
| **Scenario** | [`verify/scenarios/pr-queue.yml`](../verify/scenarios/pr-queue.yml), evidence in [`test/evidence/pr-queue/`](../test/evidence/pr-queue/) |

## Run it

```bash
tools/dash prs                                   # the queue; reads GitHub only for what is past its TTL
tools/dash prs --who amr --limit 200             # what waits on Amr
tools/dash prs --kind batch --batch chore/agent-context-kit
tools/dash prs refresh                           # read everything again under pr_queue.refresh_budget_s
tools/dash prs actions                           # the bulk actions, what each writes, what governs it, its switch
tools/dash prs plan rerun --pr bamr87/zer0-mistakes#625 --pr bamr87/fredgar-ai#140
tools/dash prs apply --plan-id 1a2b3c4d5e6f7a8b            # dry run: does the preview still match GitHub?
tools/dash prs apply --plan-id 1a2b3c4d5e6f7a8b --apply    # run it (the console's prs-act asks first)
```

## What a row says

The queue starts from the decision index ([DECISION-INDEX.md](DECISION-INDEX.md)): every open pull request under `hub.owners`, read with a handful of GraphQL searches and kept until its TTL. Rows are limited to the hub and the registry repos; `outside_registry` names the rest. Each pull request then gets one detail read, five to a GraphQL query, re-read when it was updated or its detail is older than `pr_queue.ttl_s`: the head commit's check runs, the changed files with how each changed, the repo's merge settings, the unresolved review threads and the last 25 comments, of which only the one carrying `<!-- fleet:pr-triage -->` is kept. A slow GitHub gives a dated, partial answer that says what is old.

| Field | Meaning |
| --- | --- |
| `checks` | Every check collapsed to its latest run on the head commit, keyed by workflow and check name (a status context by its context). A cancelled run followed by a success of the same check is green. `state` is failing, approval, cancelled, pending, green, skipped or none. `false_red` marks a pull request GitHub's own rollup shows red only because of superseded runs: verify kit 0.1.0's label-burst race, where each `labeled` event starts a run that cancels the last, made most of the fleet's red look like this. |
| `gate` | The review gate (§ 12.3) alone: `closeout.gate_verdict` asked of the pull request as if it were green, mergeable and not a draft, so the answer is the gate labels, ratification, the release heads, `gate_paths` and `repo_gate_paths`, `never_merge`, an untrusted author or a major or unversioned Dependabot bump. A pull request whose files were not all read is gated. |
| `merge_method` | What the maintainer's merge uses: a merge commit where the repo allows one, else squash, else rebase (zer0-mistakes is squash only). |
| `agent_merge` | Whether an agent may merge it now under § 12.2: closeout's whole live verdict on the collapsed checks, including merge-commit-only, a public repo and the default branch. Always read again before a merge. |
| `next` | Who moves it next (`amr`, `agent`, `loop`, `author`), what they do, why, and the bulk action that does it. The first rule that holds wins: an unread pull request, a draft, a conflict (JEV), failing checks (an agent), a held run (Amr approves it), cancelled checks (a re-run), a bot pull request opened with `GITHUB_TOKEN` that never ran CI (Amr pushes with `FLEET_TOKEN` or closes and reopens it), behind its base (update the branch), changes requested, checks still running, gated (Amr reviews and merges), blocked by protection, no check that proves it green, and finally an ungated green pull request an agent may merge under § 12.2. |
| `kinds` | security, dependabot, release, batch (a head branch open in `batch_min_repos` repos or more, never `dependabot/` or `release-please--`), harness (it changes `.claude/`, `CLAUDE.md`, `AGENTS.md`, `.mcp.json`, an agent workflow or a JEV step spec), ratification, draft. |
| `triage` | The triage comment's next action, question and commands, shown as a hint for the person. Nothing in it is run, and it never changes the row's own verdict. |

## Bulk actions

Every action is a plan first. `POST /api/prs/plan` (or `tools/dash prs plan`) reads each selected pull request from GitHub as it is now and gives it its exact op (the argv, the comment's bytes, the run ids) or the reason it is skipped. The plan's id is a hash of the action, its parameters and every op with the head commit and the state it was planned against. Applying is a console job, `prs-act` (or `prs-agent` for the agent), with that id: it builds the plan again from live GitHub and refuses it when the id differs, so a pull request that moved since the preview is planned again and never acted on (§ 11.4). Without `apply` the job only says whether the preview still matches. A plan holds at most `max_targets` pull requests (50, § 11.5). One `prs` job runs at a time, and the job manager's remote lock lets one GitHub-writing job run at a time. `DASH_CONSOLE_GITHUB_WRITES=off` refuses every apply.

| Action | Writes | Skips | Governed by |
| --- | --- | --- | --- |
| Mark ready | `gh pr ready` | not a draft | § 11.1 (draft state) |
| Update branch | `PUT …/update-branch` with `expected_head_sha`: GitHub merges the base in with a merge commit | conflicting (JEV's), not `BEHIND` | § 12.7 (a base merge, never a rebase or force-push) |
| Re-run checks | `gh run rerun` for the latest cancelled or failed run of each workflow on the head, `--failed` for a failure; within a pull request one at a time, each waited for up to `rerun_wait_s`, because re-runs in one cancel-in-progress group cancel each other | nothing red; a run held for approval is named, not re-run | the console's GitHub page (re-run) · § 11.8 |
| Next-action comment | one comment under `<!-- fleet:pr-triage -->`, edited in place when it exists, with the § 19.4 signature; an optional note | the comment already says it; comments unreadable | § 11.8 · § 19.2 |
| Add `needs-amr` | the label | already labelled; the repo has no such label (creating one is a repo change the queue does not make) | § 11.1 · § 12.4 |
| Agent | one capped local Claude Code session per pull request (below) | private repos; no failing check (fix CI) or no change requested (address review); past `agent.max_prs` | § 10.9 · § 29 · § 12.7's gate on a model's change |
| Close | `gh pr close` with the reason given | — | **off** (`pr_queue.close.enabled`): § 11.1 lists no pull-request close |
| Merge | `gh pr merge --<method> --match-head-commit <sha>`, never `--admin` or `--auto`; gitorio's Dependabot pull requests get `dep:merge-approved` instead (ADR-039) | `weekly.closeout.never_merge` (lifehacker.dev), a draft, not mergeable, not green after the collapse | **off** (`pr_queue.merge.enabled`): § 11.2 and § 12.2, below |

### The agent

`prs-agent` runs `local:pr-queue-agent` for each pull request in the plan, in order. It clones the head branch outside the hub (under `JEV_WORK_ROOT`), checks the clone is at the planned commit, and writes a brief of the failing jobs' log tails (`gh run view --log-failed`, the last 150 lines each) or the requested review changes, redacted. The prompt says the brief is data read from GitHub, not instructions. One session runs through `tools/dash-gen ai-run --isolate`: no GitHub credential and one Claude credential, `pr_queue.agent`'s model, turn cap, dollar cap and wall clock, `dontAsk` with a closed tool list (read, search, edit, `git status`/`diff`/`log`), the fleet's deny list, no MCP server, its cost on the AI ledger, API-equivalent (estimate). An edit to a path the repo keeps agents out of (`repo_rules.<repo>.agent_deny_paths`, it-journey's workflows) is refused. Otherwise the edit is one commit pushed without force, so a branch that moved refuses it, and the pull request gets `needs-amr`: a model's change is gated, like a model's conflict resolution. The Seatbelt sandbox and the `--settings` posture of the loop runner (§ 13.8) are not used yet; porting the action onto a JEV step spec is the follow-up that brings them.

## Governance: merge and close

§ 11.2 says the console's write-back never merges, and § 11.1's allowlist names no pull-request close. § 12.2 lets an agent merge only a pull request that is mergeable under § 12.1, ungated, with a merge commit. A merge the maintainer selects and confirms in the console is arguably his own merge, executed by Claude Code, but the constitution has to say so: until it does, the code for both is in place and each is refused at apply while its `pr_queue` switch is false. A plan for either still shows what it would do. Under § 26 and § 28.5 the amendment is direction-setting work that a Grok bot or Amr writes, so this change filed it as a Fleet issue, [bamr87/bamr87#863](https://github.com/bamr87/bamr87/issues/863), rather than drafting it (roadmap `FF-NEW:pr-queue-maintainer-merge`). Turning the switches on is a gated change to `_data/fleet.yml` after that amendment is ratified.

The comment action raises a smaller question the same amendment should settle: § 19.5 says automation never comments under Amr's personal token. A comment the maintainer confirms in the console goes out under the console's identity, which today is his.

## Design record (§ 10.8)

**Needs.** One list of what waits on Amr, with checks he can trust (most red was superseded cancels), the gate and its reason, and the merge method; acting on many pull requests at once; every write planned, shown and confirmed; agents doing the work under the existing gates.

**Prior art.**

| Option | Fit |
| --- | --- |
| GitHub's own pull-request search and dashboard | Lists pull requests across repos, but its check rollup counts superseded runs and it knows nothing of § 12.3, `gate_paths` or repo rules. No bulk action. |
| `gh pr status`, `gh search prs` | A terminal list, one repo or one search at a time; no gate, no plan. |
| GitHub merge queue | Serialises merges per repo after approval; it is a per-repo branch-protection setting (repo settings are off-limits to agents) and solves the merge, not the triage. |
| Mergify, Kodiak, Bulldozer | Rule-based auto-merge bots: a third-party app with write access to every repo, and an unattended merge, which § 12 forbids for gated pull requests. |
| Dependabot grouped updates, Renovate's dependency dashboard | Fewer dependency pull requests per repo; nothing for fan-out, harness or governance pull requests. |
| The hub's decision index, weekly close-out and Work board | The decision index reads every open pull request cheaply; the close-out encodes the gate; the Work board has the plan-then-apply shape. None lists every pull request with collapsed checks or acts on many at once. |

**Decision: build on the hub's own parts.** The queue is the decision index plus one detail read; the gate is `closeout.gate_verdict`, unchanged; the plan-and-apply shape is § 11's; the actions run as console jobs behind the existing confirm and remote lock. Nothing external gets write access, and nothing merges unattended.

`checks_green` in `tools/weekly/closeout.py` is not changed here: a parallel change to it was in flight. The queue collapses superseded runs itself and hands closeout's verdict the collapsed list, so both read the same latest run per check. When that change lands, the queue's collapse can defer to it.

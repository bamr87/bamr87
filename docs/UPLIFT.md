# Fleet uplift

> The hub's inbound arc: what one fleet repo improved that the others still lack, found by comparing file contents across the local checkouts, captured as a hub issue, and deployed by the loops the hub already has. No GitHub read, no model, $0.

The hub pushes out: kits through [`tools/fanout.sh`](../tools/fanout.sh), backlog items through the [backlog fan-out](BACKLOG-FANOUT.md). It works inside one repo: the [scout](SCOUT.md) files issues there, the [evolution loop](EVOLUTION.md) writes code there. Nothing carried an improvement back up. A fix the issue pipeline made in one repo's copy of a shared workflow stayed in that repo, and the other copies kept the fault until someone noticed. Uplift is that missing arc. It reads what every fleet repo did on its default branch and answers one question from file contents:

**A repo changed a file. Which other repos still hold a version of that file the repo held before its change?**

A byte-identical earlier version means that repo never changed the file on its own, so it can take the new content as it is. That is a comparison, not an estimate, so the capture step needs no model. Judgment is asked for once, afterwards: is the change general, or specific to the repo that made it?

| | |
| --- | --- |
| **Module** | [`tools/uplift.py`](../tools/uplift.py) (`fleet-uplift/v1`) |
| **Config** | `_data/fleet.yml` `uplift:`; the owners compared are `hub.owners` |
| **CLI** | `tools/dash uplift [scan \| show <key> \| brief \| file <key> \| verify \| status] [--days N] [--repo NAME] [--json]` |
| **Console** | Operations → *Fleet uplift* (the `uplift` operation: the scan as a job); `tools/dash ops run uplift` and the `/harness:uplift` slash command run the same |
| **Session** | the `uplift` skill ([`.claude/skills/uplift/`](../.claude/skills/uplift/SKILL.md)): a Claude Code session reads the work order, judges each candidate and previews the issues |
| **Reads** | each submodule checkout's `origin/<branch>` as of its last fetch, and the hub's own; local git only |
| **Writes** | `.fleet/uplift/` (the last scan, the issue previews; gitignored). `file --apply`, typed by a person, is the one GitHub write: an issue on the hub |
| **Tests** | `python3 tools/test_uplift.py` (real git repositories in a temp dir, a stubbed `gh`); `tools/dash uplift verify` checks a live scan against a second method |

## Run it

```bash
tools/dash uplift                        # the scan: candidates, rollouts in flight, forked files, features
tools/dash uplift --days 30 --repo bashos   # a longer window; only changes made in bashos, still compared against everyone
tools/dash uplift show u-ad193bc4fd      # one candidate or rollout in full, with its diff
tools/dash uplift brief --top 5          # the work order a session reads: the evidence, then the questions judgment answers
tools/dash uplift file u-ad193bc4fd      # a preview of the hub issue, written to .fleet/uplift/previews/
tools/dash uplift file u-ad193bc4fd --apply   # file exactly the previewed bytes (typed by the maintainer)
tools/dash uplift verify                 # re-derive who is behind a second way and compare it with the scan
tools/dash uplift status                 # the last scan's headline, without reading git
```

A scan of the whole fleet takes about five seconds. In a linked worktree, whose own `projects/` is empty, it reads the main checkout's submodules; `--projects DIR` or `UPLIFT_PROJECTS` names another folder.

## What a scan finds

Every file a repo changed in the window is compared against what every repo holds now, and lands in one of four classes.

| Class | What the contents say | What to do with it |
| --- | --- | --- |
| **Candidate** | One or two repos hold the new content, and other repos hold a version the changing repo held before | Capture it: `uplift file <key>`. It is one repo's own improvement, not yet anywhere else |
| **Rollout in flight** | The new content is a hub source, came in on a fan-out branch, carries a kit stamp that is new or newer, or is already held by `rollout_min` repos | Nothing to capture: the hub already owns it. The repos listed as behind have not taken it, which is the deployment's progress |
| **Forked** | `fork_min` repos took the same earlier version to different contents | Usually a seed each repo fills in. Add the path to `uplift.ignore_paths` if so; reconcile the variants if they are competing fixes |
| **Local** | Nobody else holds an earlier version | Counted, never listed: the repo's own business |

A candidate carries its **route**, also read from contents:

- **`kit`**: the earlier version is byte-identical to a hub source (`uplift.hub_sources`: `templates/` and the vendored payloads), or it carries a `kit: <name> v<version>` stamp. The change is made once in the kit, the kit's version is bumped, and the kit's fan-out with `upgrade` deploys it. Patching the copies would be wrong twice: an edited copy is skipped by every later upgrade.
- **`patch`**: the hub owns no source for the file, so the same patch goes to each repo behind. Three or more identical copies suggest the file belongs in a kit, and the view says so.

Two repos that changed one file in two ways are both candidates, each marked "2 repos changed it differently", because that is a decision for a person and not a fork.

A chain of edits is one move. A repo that took a file from A to B to C in the window is ahead of a repo holding A and of a repo holding B. A deletion counts: a repo that deleted a file others still hold unchanged is a candidate marked `(deleted)`.

A kit stamp separates a kit arriving from a repo's own edit. When the stamp is new, or newer than in the version just before, the repo took a kit upgrade and wrote nothing: a rollout. When the repo edits a stamped file and the stamp stays as it was, the edit is the repo's own, and its route is that kit.

The diff a view or an issue shows runs from the earlier version most repos behind hold to what the changing repo holds now. After a kit upgrade and an edit on top, that is the edit alone, which is what those repos would actually receive. A repo behind on another earlier version takes the same new file, but that diff does not apply to it, and the view and the issue name those repos instead of claiming the diff fits everyone.

### The feature lane

Each repo's feature index (`features/features.yml`) is read at the start of the window and now. A feature whose id is new, or whose status became `shipped`, is listed under the repo that declared it. A title that is new in `rollout_min` repos at once came from the hub (a kit added the entry to each), so it is listed once as fleet-wide. An index created inside the window is counted, not listed feature by feature. The hub's own features are left out: they are already the hub's.

No comparison can say whether a sibling wants a feature, so this lane only lists. The question it raises (would a repo of the same kind want this?) is answered by a session, and the answer is a roadmap entry (`/future-features`), not a patch.

## What proves nothing, and is not reported

- An **empty file**. Every repo's empty `__init__.py` has the same contents, so it is evidence of nothing.
- A **rename**, with or without an edit before it. The file moved; by its old path it was neither improved nor deleted.
- A file that **came back to where it started** inside the window: an edit that was reverted, or a file added and deleted again.
- An **ignored path** (`uplift.ignore_paths`: changelogs, release manifests, lockfiles), an **ignored author** (`uplift.ignore_authors`: Dependabot and the Actions bots) and an **ignored subject** (`uplift.ignore_subjects`: release commits, submodule bumps).
- A **new file**. It has no earlier version for anyone to be behind on. A new shared file reaches the scan only through the feature lane.

## Capture: one hub issue per candidate

`uplift file <key>` writes the issue to `.fleet/uplift/previews/<key>.md` and calls nothing. The body opens with the marker `<!-- fleet-uplift key="u-…" -->` and holds the change's origin with its pull request link, the repos behind, the diff, the route with its instruction, and acceptance criteria whose last line is checkable: the next scan no longer lists the key.

`uplift file <key> --apply` files it, and is held to these rules:

- **Only previewed bytes are filed.** With no preview, or when the candidate changed since its preview (another repo took the change, the origin edited the file again), or when the preview file was edited by hand, it refuses and names the reason.
- **A repo less visible than the hub is never filed from.** The hub is public. A private origin, or one whose visibility cannot be read, is withheld: its diff stays on this machine.
- **A credential-shaped string withholds the candidate** before anything is written, preview included.
- **A candidate is filed once, ever.** The marker is looked for in every issue carrying the `uplift` label, open or closed, so a candidate that was closed as specific to its repo is not proposed again.
- **Caps.** One run takes at most `file.max_per_run` keys, and files nothing while `file.max_open` uplift issues are open.
- **A rollout is refused.** There is nothing to capture.

The filed issue carries the `uplift` label and no state label, so the [issue pipeline](ISSUE-PIPELINE.md) takes it at intake on its next run. `file.hold: true` adds `agent:hold`, and the pipeline then waits for a person.

## Abstract, generalize, deploy: who does what

Uplift adds one sensor and one filer. Everything after the capture is a loop the hub already runs.

| Step | Who | How |
| --- | --- | --- |
| **Observe** | `tools/dash uplift scan` | Local git, byte comparison. Deterministic |
| **Judge** | A Claude Code session with the `uplift` skill, or the maintainer | Reads `uplift brief`: is the change general, where does it belong, who gets it, what proves it landed. Proposes only |
| **Capture** | `tools/dash uplift file <key> --apply`, typed by the maintainer | One hub issue, previewed first |
| **Generalize** | The issue pipeline (intake → implement), or a session | For route `kit`: a pull request that changes the kit in `templates/` and bumps its version |
| **Deploy** | `fanout.yml` with the kit and `upgrade` (`tools/fanout.sh --kit <kit> --upgrade`); for route `patch` the issue's `applies_to:` line, which the backlog fan-out reads | Pull requests in each repo, dry run by default, never merged by an agent |
| **Confirm** | The next `tools/dash uplift scan` | The candidate is gone. While the deployment is under way it shows as a rollout in flight, with the repos still behind |

An issue for route `kit` carries no `applies_to:` line on purpose: a kit change deploys through the kit, and one tracking pull request per repo would be the wrong deployment.

## Design for failure

- **A repo that cannot be read is said to be unread.** A missing checkout, a checkout git cannot open (with git's own reason) or a missing `origin/<branch>` is listed under NOT READ. It is never reported as a quiet repo.
- **A fleet nobody read is a refusal, not an empty report.** When no fleet repo can be read (a wrong `--projects`, a copy with no submodules), every command exits 2 and says so. `--days` below 1 and a `--projects` folder that does not exist are refused the same way.
- **Stale is said.** A checkout last fetched more than `stale_days` ago is listed under STALE: commits pushed since are not seen. The daily workspace sync keeps the checkouts fresh; the scan itself never fetches.
- **The hub is a member.** The registry lists submodules only, so the scan adds the hub itself (`hub.repo`) to the comparison. The hub can be behind, and its name is kept out of `applies_to:`, which takes fan-out targets.
- **External upstreams and archived repos are never compared**, as an origin or as a repo behind. The fan-out engine never writes to them either.
- **Nothing is published.** The scan can hold a private repo's commit titles and diffs, so it lives in `.fleet/uplift/` and never in `_data/`, which is public site data.

## Check the scan itself

`tools/dash uplift verify` re-derives who is behind a second way and compares the two. The scan reads each commit's raw diff and chains the versions a path went through. The check uses neither: for every commit of the window it asks git which blob each shared path held there, and calls a repo behind when what it holds now is one of those blobs. Every (path, repo behind, new content) the scan lists must be found this way, and everything found this way that the scan does not list must fall under an exclusion named above: an ignored path, only ignored commits, a forked seed, a rename, back where it started. Anything else fails the command with exit 1 and is a defect in the scan.

Run on the live fleet on 2026-11-22:

| Window | Commits | Listed by the scan | Confirmed by the second method | False positives | Unexplained |
| --- | --- | --- | --- | --- | --- |
| 14 days | 836 | 229 | 229 | 0 | 0 |
| 90 days | 3,291 | 345 | 345 | 0 | 0 |
| 365 days | 6,602 | 486 | 486 | 0 | 0 |

The same validation pass checked what the comparison is used to claim. For the 17 edit candidates of the 14-day window, the shown change was applied with `git apply` to what each repo behind really holds: in 154 of 154 repos on the diff's starting version it applied and produced the origin's exact bytes, and in the 2 repos on another earlier version it did not, which is why the views and the issue now name those repos apart. Filing was run end to end against a recording stand-in for `gh`: a refused apply with no preview, then the preview, then the apply made exactly the calls expected (the label listing, two visibility reads, the label, the issue) and the filed body was byte-identical to the preview. The read-only calls were also run against GitHub itself. No issue has been filed on GitHub. Inside the console container, with the console's own interpreter, a scan of the fleet took 4 seconds.

Found this way and fixed: a file edited and then renamed was reported as deleted; a file added and deleted again was reported as a deletion although the repo was back where it started; an unreadable checkout was reported as a missing branch; the issue text said the diff fits every repo behind; and `--days 0`, a negative window and a `--projects` folder that does not exist each gave an empty report that read as a quiet fleet.

## What it cannot see

The comparison is exact, and that is its limit.

- A repo that **adapted** a shared file holds different contents, so it is counted ("3 repos hold the file with other contents") and not compared. Whether the change applies to it is a judgment.
- A **pattern** is not a file. A fix to one site's own code that another site should copy in its own words has no twin for the comparison to find. It surfaces only if the repo declares it as a feature, or when a session reads the repo.
- Only the **default branch as of the last fetch** is read, along its first parent. Work on a branch is not activity yet.

## The first scan (2026-11-20)

Fourteen days, 41 of 41 repos read, 862 commits, about five seconds: 18 candidates, 8 rollouts in flight, 1 forked file, and features declared or shipped in 22 repos.

- **One need, solved three times.** `law-ai`, `djangoerp` and `ragio-ai` each taught `release-please-config.json` to write the release version into their own files, each for a `/version` endpoint, in three separate pull requests. Two of the three started from the sdlc kit's seed, which 11 and 4 other repos still hold. That is the pattern uplift exists to catch: the kit should carry it once.
- **Rollouts nobody was tracking.** Kit `pr-review` v0.2.0 is in 2 repos with 30 behind. The verify kit's runner is at v0.2.0 in 5 repos and v0.3.0 in 5 more, with 15 on the archived v0.1.0. Kit `conformance` v0.2.0 is in 32 with `lifehacker.dev` and `recon-engine` behind. `tools/unwrap-prose.py` is current in 30 with 3 behind.
- **The same fix in fewer bytes.** `bamr87.github.io` recompressed five heavy images that `bash-365.com`, `zer0-mistakes` and `lifehacker.dev` hold unchanged.
- **Candidates that judgment closes.** `bashos` tailored its issue forms for bashOS (30 repos behind) and `githubai` filled the date into the seeded ADR 0001 (32 behind): exact matches, and specific to their repo, though the second says the kit should not seed a `YYYY-MM-DD` placeholder. `bashcrawl`'s change to its `conformance` caller has 34 repos behind and is one trailing comment. The count says how far a change could travel, never whether it should.
- **A fork.** `verify/scenarios/smoke-home.yml` was taken to five different contents by five repos, and 14 still hold the seed: a placeholder each repo fills in.

## Phases

| Phase | What | State |
| --- | --- | --- |
| P0 | The scan, the views, the work order, the previewed filing, the console operation, the session skill | This document |
| P1 | A capped headless review session on the JEV rails (weekly, previews only, never files), registered in `_data/agents.yml` with its KPIs and eval set | Needs the maintainer's yes: it spends, and a step spec is gated config |
| P2 | The weekly routine's Sunday plan reads the last scan | Not started |
| P3 | A console page for candidates and rollout progress, and an MCP tool | Not started |
| P4 | A patch fan-out for route `patch`, so the same change opens as a pull request in each repo behind | Not started |

## Configuration

`_data/fleet.yml` `uplift:` holds every setting with its comment: the window, the two thresholds, the hub sources, what is ignored, what marks a rollout, and the filing caps. [`tools/uplift.py`](../tools/uplift.py) carries the same values as its fallback and `test_uplift.py` holds the two equal, so a change is made in both. The exact kit branches are not configured: they are read from `tools/fanout.sh`, so a new kit is covered when it is added.

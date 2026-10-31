# `.github/scout/` — the repo-scout brief

Version-controlled prompt material for the daily **repo-scout loop** ([`repo-scout.yml`](../workflows/repo-scout.yml), documented in [`docs/SCOUT.md`](../../docs/SCOUT.md)). The scout visits a small sample of repositories every day and files well-formed **issues** there — features, fixes, updates — for the issue pipeline to implement. This directory is the *tunable* half of what the agent reads. The *hard rules* (propose-only, never edit or push, the lane boundaries with the other loops) are the JEV step spec [`tools/jev/steps/repo-scout/`](../../tools/jev/steps/README.md) — `scout.prompt.txt` beside its `scout.yml` — which the plan job renders per leg from the hub at the run's commit and `tools/test_jev_spec.py` pins byte for byte. They stay outside this directory, so an edit here still cannot loosen them. They are no longer in `.github/workflows/`, so the `workflow`-scope barrier — which `GITHUB_TOKEN` pushers and the Claude GitHub App token cannot cross — reaches them only through the Scout step's `JEV_STEP_SHA256` pin: `python3 -m tools.jev steps check` refuses a spec pair whose content hash differs from it, so an edit to the hard rules is also an edit to `repo-scout.yml`. `FLEET_TOKEN` already holds `workflows:write`, so for it the maintainer's review is the only control, as it was before. `CODEOWNERS` is not enforced (no branch protection), and a change under `tools/jev/steps/` is gated under constitution § 12.3, so no agent merges it ([ADR 0002](../../docs/adr/0002-agent-step-specs-and-local-runner.md#governance-trade-off)).

| File | Purpose |
| --- | --- |
| `scout-prompt.md` | What to look for (fix → update → feature), what a proposal must contain, and the working method. Contains `{{PLACEHOLDER}}` tokens filled per repository. |

The same brief and spec also drive a local run on a workstation through JEV's loop runner ([`docs/SCOUT.md`](../../docs/SCOUT.md#run-it-locally)).

Category emphasis is shared with the evolution loop: [`../evolution/categories/<category>.md`](../evolution/categories/) is appended to every scout brief too, so a documentation project and a dev tool are scouted with the same weighting they are evolved with.

## How the brief is assembled

[`dash-gen scout`](../scripts/dash-gen/repo_scout.py) — the deterministic `plan` job — writes one `scout-workorders/scout-workorder-<name>.md` per repository in today's sample, plus `plan.json`:

```text
<!-- repo-scout key="owner/repo" -->          ← hidden marker (first line; copied into every issue the run files)
# Scout brief — <name>
## Repository                                 ← registry facts
## Signals                                    ← _data/fleet_triage.yml: attention, failing workflows, open issues/PRs
## Conformance gaps                           ← _data/conformance.yml: failing Universal Project Standard rows
## Open issues — do NOT propose these again   ← live list, so a proposal can never duplicate one
## Proposals from earlier scout visits        ← this loop's own open issues in the repo
## Focus for this run                         ← the dispatch `focus` input, if any
<scout-prompt.md>                             ← rendered goals + method
<../evolution/categories/<category>.md>
```

The agent answers with one file, `.scout/proposals.json` (git-excluded inside the target checkout):

```json
{
  "proposals": [
    {"title": "…", "kind": "fix|update|feature", "type": "bug|feature|docs|chore|ci|refactor|test|security",
     "priority": "P0|P1|P2|P3", "size": "size:xs|size:s|size:m|size:l|size:xl",
     "body": "## Problem\n…\n## Proposal\n…\n## Acceptance criteria\n- [ ] …\n## Scope\n…"}
  ],
  "notes": "what you saw that is not worth an issue"
}
```

The workflow's `file` job then validates, dedupes against the repo's open issues, caps at `scout.max_issues_per_repo`, and files what survives with `FLEET_TOKEN` — the agent itself never holds a write credential.

Placeholders: `{{REPO_NAME}}`, `{{NWO}}`, `{{BRANCH}}`, `{{CATEGORY}}`, `{{STACK}}`, `{{DESCRIPTION}}`, `{{STATUS}}`, `{{MAX_ISSUES}}`, `{{KINDS}}`, `{{TYPES}}`, `{{PRIORITIES}}`, `{{SIZES}}`.

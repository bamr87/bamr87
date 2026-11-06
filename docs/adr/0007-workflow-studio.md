# ADR 0007 — The Workflow Studio: the atlas grown to the fleet, one read model on every surface, every change planned and reviewed

- **Status**: proposed
- **Date**: 2026-11-05
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-05: "a centralized console/studio that allows for greater management of all workflows and their configurations/interactions"); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: constitution § 10.8 (prior art first), § 11 (write-back), § 12.3 (gated changes), § 13.6 (irreversible actions), § 20 (the editor is a front door), [ADR 0005](0005-console-as-fleet-portal.md), [ADR 0006](0006-django-management-backend.md), [docs/WORKFLOW-ATLAS.md](../WORKFLOW-ATLAS.md), [docs/WORKFLOW-OPTIMIZATION.md](../WORKFLOW-OPTIMIZATION.md), #698, #699
- **Tracking**: #719

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer runs about forty repositories from one hub and needs to answer four questions without reading logs: did this check really check anything, why did this workflow run, what does this workflow touch, and what happens across the fleet if I change it. Agents need the same answers through the MCP server, because they open most of the pull requests.

**Evidence from the hub.** A review of every workflow on 2026-11-05 covered 412 files in 42 repositories and 9,989 runs over 14 days. It took custom scripts, because no surface could answer the questions above:

- 22 of the 25 repositories that run `fleet-verify.yml` have never run a scenario in CI. Each run waits 180 seconds for a server the kit's empty `app:` block never started, then passes. 82 of 94 sampled runs skipped their scenarios and stayed green.
- `tools/check-drift.sh --ci` makes at least 475 API calls per run on the shared `GITHUB_TOKEN`. In the busiest hours that spent the quota, which turned 41 `build-dash` and `verify` runs red and left 29 drift runs green with nothing read. No surface showed any of it as one cause.
- 541 runs never started, 514 of them waiting for an approval that GitHub requires on pull requests opened by `github-actions[bot]`. 272 of those appear as failures with zero jobs, so failure rates were overstated.
- Run timestamps cannot be used as durations: `updated_at` on those zero-job runs moved days later, which inflated a naive total from 315 hours to 4,392.
- The atlas (#425) is the right model, but it reads the hub's 36 workflows only. The other 376 files have no catalog, lint or trigger view.

**What the console already has.** The atlas (`/workflows`): catalog, standards, run health, retire list and designer, for the hub. The repo manager: re-run, cancel, enable and disable, confirm-gated. `_data/fleet.yml` with `dash config sync` and `dash secrets sync`. `fanout.yml` for dry-run, PR-only kit changes. The lake for run history. The gap is one fleet-wide model, and a way to see desired against actual.

**Why now.** ADR 0005 made the console the fleet's portal and ADR 0006 settled where new state lives, so a fleet workflow surface now has a home. § 10.8 requires this record before it is built.

### Prior art survey (§ 10.8)

- **GitHub's Actions tab and repository insights.** Fit: the authoritative per-repository view. Limits: no fleet view, and `bamr87` is a personal account, so there are no organization-level settings to lean on.
- **Backstage GitHub Actions plugin.** Fit: recent runs, logs and re-runs per catalog entity. Limits: one repository per entity, and ADR 0005 already declined Backstage as a product.
- **GitHub Workflow Dashboard (open source).** Fit: a browser view of run status across repositories and organizations. Limits: status only; it holds no configuration, policy or interaction model.
- **Datadog CI Visibility and Honeycomb build events.** Fit: deep pipeline observability. Limits: paid or per-job instrumentation across every repository, and neither manages configuration. The hub already has an OpenTelemetry plane.
- **Blacksmith and similar runner vendors.** Fit: analytics bundled with faster runners. Limits: queue time here is about 3 seconds and Actions cost is $0 net on the billing meter, so runners are not the constraint.
- **actionlint and zizmor.** Fit: static rule engines. actionlint is already in the drift gate; zizmor found useful results in this review and fits as a rule source, with `unpinned-uses` off because the fleet rides major tags.
- **OpenSSF Scorecard.** Fit: security posture per repository. Already adopted by `scorecard-sweep.yml`.
- **Dependabot and Renovate.** Fit: moving action and reusable-workflow refs. Already in use; they do not explain or plan changes.

**Build versus adopt.** Adopt actionlint, zizmor and Scorecard as rule sources. Adopt no dashboard: each covers run status, which is the smallest part of the need, and none models this fleet's kits, kill switches, budgets or governance. Build the fleet model and views on the atlas and console that exist.

## Decision

1. **The Workflow Studio is the atlas grown to the fleet, not a new product.** `/workflows` becomes the Studio. The fleet model, `fleet-workflows/v1`, is built by running the atlas's existing `parse_workflow()`, `lint_workflow()` and `classify_failure()` over every repository's files. There is no second parser. The name avoids "Fleet Studio", which is GitFactory's.

2. **One read model, every surface.** The model lives in the service layer (`tools/fleetcore/`, ADR 0006 decision 2). The console, the TUI, the MCP server and `tools/dash workflows --fleet` all render it. The public snapshot carries the catalog and the standards, with no run health.

3. **Reading the fleet never spends a shared CI quota.** A local sync (`tools/dash workflows sync`) reads each repository's workflow files with the operator's token and conditional requests and stores them in the lake beside run history. It never runs on a pull request and never uses `GITHUB_TOKEN`. A sync reports how many repositories it read, and a surface shows "not read" instead of a pass when that number falls short.

4. **A check has more states than pass and fail.** The Studio reports `verified`, `passed-empty` (green, did nothing), `never-ran`, `quota`, `real-failure` and `cancelled`, each with its evidence. Fleet health is computed from these, so a green check that verified nothing does not count as healthy.

5. **Git stays the source of truth; the Studio shows desired against actual.** Desired state comes from `_data/fleet.yml`, the kits and the standards. Actual state comes from GitHub: variables, secret names, Actions settings, reusable refs and kit versions. A row never overrides a file (ADR 0006 decision 3).

6. **Every write is a plan, in one of three lanes.** No lane merges, deletes runs, writes a secret value or changes a ruleset.

   | Lane | What it changes | How |
   | --- | --- | --- |
   | Run control | re-run, cancel, enable, disable | the existing confirm-gated repo manager actions, batched across repositories |
   | Repository settings | variables and kill switches | a plan and its diff, applied with `confirm=true` through the OPS remote-write path (§ 11, § 13.6) |
   | Workflow files | any change to YAML | a change set: dry-run diff, lint, then one pull request per repository through `fanout.yml`, labelled and tracked to merge; never a direct push |

7. **Why did this run is a first-class question.** A simulator answers it for a real run and for a hypothetical change: given changed files, or a pull request, it lists which workflows fire and which filter decided. It reads the same model, so an agent can ask it before opening a pull request.

8. **The standards grow with the incidents.** New atlas rules, each landing at `warn`: `pr-scope`, `verify-empty`, `api-budget`, `caller-ref`. `node-alias` already landed with the S0 fixes (#726). Rules hold for the fleet through the same engine, with `hub_rules=False` for rules that only make sense on the hub.

9. **Records follow ADR 0006.** Change sets and their approvals are JSONL under the audit path until phase B4 lands, then Django models. The route family starts in FastAPI and moves with the strangler.

## Delivery

| Phase | Delivers | Acceptance |
| --- | --- | --- |
| S0 (#720) | The standalone fixes from the review, no Studio needed | No `setup-node` quota failures for 14 days; `verify` reports `not verified` when it has no app |
| S1 (#721) | `fleet-workflows/v1`, `dash workflows sync`, CLI and MCP, read-only | All registered repositories read; the model matches a hand count for three repositories |
| S2 (#722) | Studio read views: catalog, check states, interaction map, schedule and quota timeline, simulator | The simulator reproduces PR #693's five workflows; `passed-empty` shows the 22 verify repositories |
| S3 (#723) | Configuration matrix: desired against actual, read-only | Every fleet variable and reusable ref shown with its drift |
| S4 (#724) | Run control and settings lanes behind § 11 | Every write shows its plan, needs `confirm`, and lands in the audit log |
| S5 (#725) | Change sets through `fanout.yml` | One change set opens dry-run, then PRs, and tracks them to merge; none merges itself |

## Consequences

- **Positive:** one place answers why something ran, what it touches and whether it checked anything. Health numbers stop counting zero-job runs as failures and empty passes as successes. Fleet changes get a preview before they fan out.
- **Negative:** the lake gains a second sync to run, and sync is manual today. The model can lag GitHub, so every view shows its read time. The Studio adds to a console that is mid-port to Django.
- **Risks:** a write lane is a powerful target, so S4 and S5 ship only behind the existing token, allowlist and confirm rules. Rule growth can create noise, so rules start at `warn`.

## Alternatives considered

- **Adopt a dashboard or observability product.** It would show run status sooner, but not configuration, kits or interactions, and it would add a second source of truth.
- **Keep extending per-repository pages.** No new model, but cross-repository questions stay manual, which is the need.
- **Build it as a separate app.** Cleaner boundaries, but a second copy of the auth, jobs and audit the console already has, against ADR 0005.
- **Fix the workflows and skip the Studio.** Phase S0 does this and is worth doing regardless, but the same class of problem went unseen for weeks because nothing showed it.

## Supersedes / Superseded by

None.

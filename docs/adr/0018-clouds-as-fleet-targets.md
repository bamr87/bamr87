# ADR 0018 — Clouds are fleet targets: providers declared once, deployments read from the repos, and one neutral contract each for identity, infrastructure, workload, telemetry and cost

- **Status**: proposed
- **Date**: 2026-11-27
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-27: as the bash-365 organization grows, the framework must manage and monitor any repo on AWS, Google Cloud and Azure without being tied to one cloud or one AI, with the site, the OS and the localhost platform aligned; build the foundations and the toolsets first)
- **Related**: [ADR 0003](0003-fleet-platform-nodes-iac-and-scale-out.md) (nodes, OpenTofu, "a path to any cluster"), [ADR 0005](0005-console-as-fleet-portal.md) (the console is the portal on every surface), [ADR 0011](0011-one-framework-many-instances.md) (the stack installs for any owner), [ADR 0016](0016-hub-structure-contract.md) (the structure contract); constitution § 10.5, § 10.6, § 10.8 and § 13.6; [docs/CLOUDS.md](../CLOUDS.md), [docs/PLATFORM.md](../PLATFORM.md), [infra/azure/README.md](../../infra/azure/README.md); roadmap `FF-0044` (the Azure cost dashboard); pull request #993 (the bash-365 portal on Azure); `HUB-NEW:fleet-clouds`

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer asked how bashOS, bash-365.com and the three large clouds can be managed and monitored for any repo in the fleet, from a framework that depends on no single cloud and no single AI, with the public site, the OS and the localhost platform showing the same thing. The request names three foundations. Two of them have a decision record and an epic already. This record decides the third.

| Foundation | Where it is decided | State on 2026-11-27 |
| --- | --- | --- |
| Whose control plane it is, and where it shows: one framework, an instance per owner, one console on every surface | ADR 0011, ADR 0005 | ADR 0011 stopped at P0, so the `bash-365` repos are still half managed; the console builds once per site (`sites.bash-365`, served at `os.bash-365.com` once its switch is on) |
| Which AI does the work: one agent-loop contract, harnesses behind adapters | [docs/prd/HARNESS-PROTOCOL.md](../prd/HARNESS-PROTOCOL.md), epic #632; the harness standard's routes | Not started; every agent call goes through one CLI and no ledger records a provider |
| Where a repo's deliverable runs, and who watches it there | **nothing** | This record |

**Evidence: the fleet already runs on three platforms, and nothing models it.** Measured on 2026-11-27 by reading the hub and the 40 owned repos checked out beside it (the registry lists 45: three owned repos are not submodules of the hub, and two belong to another owner and are never read):

- 20 deployments in 16 repos. 15 are GitHub Pages. 3 are Azure Static Web Apps: bash-365.com in production, bashcrawl wired, and the hub's own bash-365 portal, merged the same day (#993). 2 are Cloudflare Workers, the chat proxy in zer0-mistakes and in year-of-ai.github.io.
- AWS and Google Cloud hold nothing the fleet deploys: no workflow signs in to either and no file declares a resource on either. They appear only as optional application code (an S3 storage backend in fredgar-ai, Secrets Manager and SES in zer0-CMS's parodynews app, the Firebase client in cv-pro).
- The registry cannot say where a repo is hosted. `_data/projects.yml` has `live_url` and no field for a provider, a service or a region. bashcrawl gained an Azure workflow on 2026-11-21 and its `live_url` still names its Pages address.
- Each Azure deployment brought its own pattern. There are three Bicep trees, three bootstrap scripts and three Entra applications. Two workflows name the identity's ids as secrets (`AZURE_CLIENT_ID`), the third as variables (`PORTAL_AZURE_CLIENT_ID`). What they share is the part worth keeping: all three sign in with GitHub's OIDC token and store no credential.
- Cloud credentials sit outside the token contract. `_data/fleet.yml` `tokens:` names ten secrets and none belongs to a cloud. `CLOUDFLARE_API_TOKEN` is stored in two repos, and nothing audits or rotates it.
- Infrastructure exists that no workflow deploys. zer0-CMS carries an `azd` project for parodynews (twelve infrastructure files), and its own workflow lists the Azure deploy under "Not ported yet". githubai carries a Worker configuration that is deployed by hand.
- Nothing in the hub reads a deployment. The only tool that touches a live site is the weekly link check. No tool reads GitHub's deployment records, asks whether an address answers, or reads what a cloud costs: the Costs page covers Actions minutes and Claude usage. Four repos each wrote their own post-deploy probe.
- The infrastructure-as-code decision has an unrecorded exception. ADR 0003 chose OpenTofu and promised "any cloud through OpenTofu providers". Every Azure resource in the fleet is Bicep, and `infra/README.md` calls Azure "the exception" without a record that says why or for how long.

**Constraints.**

- § 10.5 and § 13.6: changing a cloud is a deploy, an external and high-risk action the maintainer approves.
- § 10.6: a new tool is read-only by default, with allowlists, caps, time limits and redaction.
- `_data/` is public site data. A subscription id, an account id or a project id is not written there.
- A pull request check never reads the whole fleet, and CI holds no cloud credential today.
- ADR 0011: no new literal owner, and what belongs to one instance (its accounts, its switches) is separable from what belongs to the framework (how a provider is recognised).
- ADR 0016: the shared core is pure, and `_data/fleet.yml` is already the file most changes touch.

**If nothing is decided.** The fourth cloud deployment arrives as a fourth private pattern. The first use of AWS or Google Cloud brings a stored key, because no federated pattern exists for either. The console, the published site and bashOS keep showing a fleet that does not know where it runs, and each new site writes its own probe.

### Prior art survey (§ 10.8)

| Candidate | Fit | Decision |
| --- | --- | --- |
| Backstage catalog with cloud plugins | A component catalog with deployment annotations and per-cloud plugins | Rejected: a service to host, and its annotations are declared by hand, so they drift from the workflows |
| GitHub OIDC federation (an IAM OIDC provider on AWS, Workload Identity Federation on Google Cloud, a federated credential on Entra) | A short-lived token per job and no stored credential, on all three clouds | **Adopted** as the identity rule. All three Azure deployments already use it |
| GitHub Deployments and Environments | One record of what was deployed where and when, whatever the cloud; Pages and the portal job already write it | **Adopted** as the deploy ledger (P2) |
| OpenTofu | One language and a provider for each cloud; already the fleet's tool for nodes (ADR 0003) | **Adopted** for AWS, Google Cloud and anything that spans providers |
| Bicep | Azure only, with `what-if` as its plan; three deployments in the fleet use it | **Kept** for Azure |
| Pulumi, Crossplane | Infrastructure in a general-purpose language; infrastructure from inside a cluster | Rejected in ADR 0003, for the same reasons |
| OpenTelemetry Collector | Already the fleet's collector; an HTTP check receiver for uptime, and contrib receivers for each cloud's monitoring API | **Adopted** for uptime (P2); each cloud receiver is evaluated in P7 |
| Prometheus Blackbox exporter, Uptime Kuma | Synthetic checks | Not adopted while the collector's own receiver does the job without another container; revisit in P2 if it does not |
| FOCUS (FinOps Open Cost and Usage Specification) | One billing schema; AWS, Azure and Google Cloud each export their billing in it | **Adopted** as the cost schema (P5), with each provider's export confirmed in that phase |
| Each cloud's resource graph (Azure Resource Graph, the AWS Resource Groups Tagging API, Cloud Asset Inventory), through its own CLI | Read-only inventory by label | **Adopted** for inventory (P4) |
| Steampipe, CloudQuery | SQL over every cloud's API | Candidate in P4 if three CLIs prove too uneven; one more engine to run |
| Infracost | The cost of an infrastructure change before it is applied | Candidate in P5 |
| Cloud Custodian | Policy as code across clouds | Out of scope until there is more than a handful of resources to hold to a policy |
| A hosted cloud-management or posture service | Inventory, cost and posture in one place | Rejected: fleet data leaves the house, it is paid, and the fleet's rule is local first |

**Build versus adopt.** Adopt the standards: federated identity, GitHub's deployment records, OpenTofu and Bicep, OpenTelemetry and FOCUS. Build one small thing no tool provides: a reader that maps every deployment from the repos' own files, and the one document every surface shows.

## Decision

1. **A provider is declared once, as data.** `_data/fleet.yml` `clouds:` declares each platform the fleet deploys to and does not operate: GitHub, Azure, AWS, Google Cloud and Cloudflare. An entry says how a deployment to the provider is recognised in a repo's files (an action, a command, a host, a marker file), how the fleet is expected to sign in (`oidc`, `platform` or `secret`), which files declare its resources as code, and whether the hub may read it (`enabled`). A cloud is not a node: a node is a machine the fleet operates over SSH and places hub workloads on (ADR 0003), and a virtual machine or a cluster the fleet operates in a cloud is still a node.
2. **Which repo deploys where is read, never declared.** [`tools/fleetcore/clouds.py`](../../tools/fleetcore/clouds.py) reads each owned repo's checkout: its workflows, its registry address, and its infrastructure files. The map therefore cannot disagree with what the repos do, and a new deployment appears the day its workflow lands. What the reader cannot see, it says: a repo that was not read is named and never counted as clean, a sign-in it cannot classify reads `unknown`, and infrastructure no workflow deploys is reported as exactly that.
3. **The code names no vendor.** Every vendor fact is in `clouds:`. A new provider or a new service is an entry and no code, and a test fails the build if the reader names one.
4. **One document for every surface.** `status_doc()` returns `fleet-clouds/v1`: the providers with their switches and counts, every deployment with its evidence and how it signs in, the infrastructure files, the findings, and what was and was not read. `tools/dash cloud` prints it now. The console's API and page, the MCP tool, the published site and the TUI read the same document in P1, so `127.0.0.1:4001`, `os.bash-365.com` and a console that bashOS supervises show one thing.
5. **A deployment meets five neutral contracts, whatever its provider.**
   - **Identity.** A deployment signs in with a federated login and stores no cloud credential. It holds one identity scoped to its own resources; the hub holds one read-only identity per provider. A stored credential where the provider's rule is `oidc` is a warning. A provider that cannot federate (Cloudflare) is `secret`, and its credential's name belongs in the token contract.
   - **Infrastructure.** Resources are declared as code in the repo that owns them, a script is a dry run unless told to apply, and the maintainer applies. AWS, Google Cloud and anything that spans providers use OpenTofu. Azure stays on Bicep, because three working deployments use it and its `what-if` is the same contract as a plan. `tools/dash infra` plans the nodes today and is to plan both from P3. This is the record for the exception `infra/README.md` describes.
   - **Workload.** Every service has a `kind` that means the same on every provider: `static`, `container`, `function`, `stack` or `cluster`. An image is addressed by digest from GHCR, and compose stays the definition a cluster's manifests are generated from (ADR 0003, phases 6 and 10).
   - **Telemetry.** OpenTelemetry carries what a deployment emits into the fleet's own planes. Whether an address answers is a synthetic check from the fleet's collector. Whether a deployment ran is GitHub's deployment record, the same API for every cloud.
   - **Cost.** Each provider's billing is read as a FOCUS export into the lake and shown on the Costs page beside Actions minutes and AI spend, against a budget declared per provider.
6. **Every resource carries four labels.** `project`, `env`, `managed-by` and `source`, where `source` is `<owner>/<repo> <path>`: the join from a cloud resource back to the registry. The portal's Bicep carries all four today; bashcrawl's carries two.
7. **The hub reads a provider only when its switch is on.** Every provider but GitHub ships `enabled: false`. Turning one on is a deploy step that arrives with the phase that reads it. A read is read-only, uses the operator's own CLI login in a local session or the federated read-only identity in a scheduled workflow, runs a fixed allowlisted command with a time limit, redacts what it stores, and never runs in a pull request check.
8. **No value in `_data/`.** `clouds:` describes how a workflow is recognised. An account, subscription or project id is a repo variable, and a credential is a secret.

### Phases

| Phase | Delivers | Changes a cloud? |
| --- | --- | --- |
| P0, this pull request | This record; `clouds:` with five providers; `tools/fleetcore/clouds.py`; `tools/dash cloud`; [docs/CLOUDS.md](../CLOUDS.md) | No. It reads files already on disk |
| P1, surfaces | `GET /api/clouds`, the console's Clouds page, MCP `fleet_clouds`, the TUI, the fleet graph's builder, and a committed snapshot so the published sites show the map | No |
| P2, deployed and up | GitHub's deployment records into the lake; a synthetic check of every deployment's address through the collector, with its dashboard and an attention signal; the four private probes replaced by one kit | No |
| P3, identity | A read-only identity per provider, as code, trusting one GitHub environment; the three Azure identities described by one pattern; cloud credential names in the token contract; the warning for a stored credential becomes a gate | Yes: one identity per provider, applied by the maintainer |
| P4, inventory and drift | A read-only collector per enabled provider: resources by label into the lake, and the plan of each infrastructure directory as its drift | No. It reads |
| P5, cost | Each provider's FOCUS export into the lake; budgets in `clouds:`; the Costs page; `FF-0044` built on it | Yes: one export and one budget per provider |
| P6, deploying | A deploy kit in `templates/`: one reusable workflow per `kind` with the provider as an input, the federated login, the labels, the post-deploy check and the deployment record; OpenTofu modules for a static site and a container service on AWS and Google Cloud | Only when a repo adopts it |
| P7, workloads | Logs, metrics and traces from running deployments into the planes; ties to ADR 0003 phases 3, 4 and 10 | Yes |

Every phase after P0 is its own pull request under the tracking epic that follows acceptance. Creating an identity, an export or a budget, and switching a provider on, stay the maintainer's.

## Consequences

**Positive**

- The fleet's hosting is one command and one document, correct on the day it is read, with no registry field to keep in step.
- AWS and Google Cloud have a pattern before their first use: a federated login, declared resources, the four labels. The first deployment to either is recognised without a code change.
- The same reader serves another owner. It takes the instance to read as an argument and takes how a provider is recognised from the framework (ADR 0011), so a `bash-365` control plane gets the map on its first run.
- The findings are useful today: two stored cloud credentials nothing rotates, and two sets of infrastructure nothing deploys.
- The one unrecorded exception to ADR 0003 has a record and a boundary.

**Negative**

- The map is what a repo can deploy, read from its files. A workflow that skips itself, or one that has never run, still appears. P2 adds what ran and what answers.
- Recognition is a list someone keeps. A deploy action that is not listed is invisible until it is added, and a deployment hidden inside a called workflow or a local composite action is not seen.
- The reader needs the repos on disk. An instance with no checkouts reads nothing; reading the workflow files the lake already holds is P1's alternative source.
- `clouds:` adds about 150 lines to the file most changes touch.
- Two infrastructure languages stay in use, and a module cannot be shared between Azure and the other two.

## Alternatives considered

- **Declare each repo's hosting in the registry** — a second copy of what the workflows already say. It drifts the way bashcrawl's `live_url` did. It stays open as an override for a deployment that cannot be read from files.
- **Start with one workflow that hides the provider** — deferred to P6. With three cloud deployments on one provider, the abstraction would be designed from a single example.
- **Rewrite the Azure Bicep in OpenTofu now** — three working deployments would be rewritten for no gain until a module is shared across clouds.
- **Model a cloud account as a node** — a node runs hub workloads over SSH; a provider runs a repo's deliverable behind an API. They share neither the placement rules nor the link.
- **One registry for cloud providers and AI providers together** — the idea is the same (a neutral contract, the vendor in data), but AI routes have their own contract under way (epic #632 and the harness standard). They meet on the Costs page, not in one block.
- **Read the clouds first and map the repos later** — it would need an identity on every provider before showing anything, and it finds only what was already deployed. Reading the repos needs nothing and also finds what is about to be.

## Supersedes / Superseded by

- Supersedes: none. It bounds ADR 0003's "any cloud through OpenTofu providers": Azure stays on Bicep.
- Superseded by: none

# ADR 0020 — The platform is hosted on Google Cloud and entered through the main site: one machine that is a fleet node, one file that says what is hosted, and a sign-in page that links to each service's own sign-in

- **Status**: proposed
- **Date**: 2026-11-28
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-28: "make sure the main site has a login portal and option into the zer0-cms platform hosted on GCP", then "essentially, the whol bashos framework/platform and repos should be hosted on GCP and accessible through the main site")
- **Related**: [ADR 0003](0003-fleet-platform-nodes-iac-and-scale-out.md) (nodes, and a cloud machine as one), [ADR 0005](0005-console-as-fleet-portal.md) (the portal), [ADR 0006](0006-django-management-backend.md) (private mode and the fleet's sign-in), [ADR 0018](0018-clouds-as-fleet-targets.md) (the contracts every deployment meets); constitution § 10.5, § 10.6, § 10.7, § 10.8 and § 13.6; [docs/HOSTING.md](../HOSTING.md), [infra/gcp/README.md](../../infra/gcp/README.md); zer0-CMS ADR 0004 (a cloud-agnostic deploy) and its PLAN milestone H1; pull request #993 (the portal on Azure); `HUB-NEW:platform-hosting`

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer wants the whole platform (the bashOS framework, the Harness Console, zer0-CMS and each repo's application) hosted on Google Cloud and reached through the main site, bash-365.com, which gets a sign-in page with a way into zer0-CMS first. "Hosted" means it runs there. The repositories stay on GitHub.

**Evidence: nothing runs on Google Cloud, and the main site has no way in.** Read on 2026-11-28:

- No fleet repo deploys to Google Cloud and no file declares a resource there (ADR 0018's measurement of the day before).
- The main site is a Jekyll site on Azure Static Web Apps. It has no sign-in, portal or application link. Its header is drawn from one data file with five of the six top-level items its own rule allows.
- The portal (the console's bash-365 build) was wired for Azure Static Web Apps one day earlier (#993) and is switched off.

**Evidence: the platform is shaped like a machine.** Read from the repos that make it up:

- **zer0-CMS** is one image that runs as four roles (web, worker, scheduler, relay) plus two event consumers. It needs Postgres with the vector extension and Redis. It keeps files on disk that it treats as the record: media, the outbox belt, and checkouts of the sites it writes back to. It has no storage backend other than the filesystem.
- **The Harness Console** reads the hub's checkout, runs jobs as subprocesses and holds the fleet's GitHub credentials.
- **bashOS** is a layer installed onto a machine. It supports Debian 13 and supervises the console as a service.
- **Each repo's application** is a compose stack (`tools/dash dev up`).
- zer0-CMS decided its own deploy on 2026-10-22 (its ADR 0004): cloud-agnostic, release images on GHCR, a production compose file, a Helm chart. None of it is built: its PLAN milestone H1 is unchecked and last in its order, no workflow publishes its image, and there is no production compose file.

**Evidence: sign-in exists in one place, and it must be linked, not framed.**

- zer0-CMS has sign-in built: local accounts, an emailed code, passkeys, a second factor, and single sign-on through any OpenID Connect provider. Sign-up is closed by default, and a new account sees nothing until an operator gives it a group.
- Its sign-in screen is its studio, on its own origin. Its content policy forbids being framed by another site, and its cookies are for its own host only. A link is the only way in from another site, and that is the right way.
- It verifies an address by emailed code, so nobody can sign in until it has an email sender.
- The Harness Console has no sign-in. ADR 0006's private mode, which would give it one, has only its first phase built.

**Constraints.**

- § 10.5 and § 13.6: creating or changing anything in a cloud is a deploy the maintainer approves.
- § 10.7: cost is stated honestly. A machine is billed for every hour it exists, unlike the static sites.
- ADR 0018: OpenTofu for Google Cloud, a federated login with no stored key, the four labels, a dry run by default, no account identifier in `_data/`.
- ADR 0003: a machine the fleet operates is a node; SSH is its only API; its services bind its loopback.
- zer0-CMS's own rule (its business-packaging plan): no client data on a server without a backup that has been restored once.
- DNS for bash-365.com is hosted by Microsoft 365, so a new host name is a record the maintainer adds there.

**If nothing is decided.** The first service is put on Google Cloud by hand, with a key in a secret and a port opened to get it working. The console is exposed with a token because that is the quickest way to reach it. The main site links to an address that moves.

### Prior art survey (§ 10.8)

| Candidate | Fit | Decision |
| --- | --- | --- |
| Serverless containers with a managed database and a managed cache | The web role scales to zero; everything is patched for us | Not first: six always-on processes and files on disk that are the record do not fit it without changing the platform. Each piece is a candidate later (G7) |
| A Kubernetes cluster | ADR 0003's scale-out target, with manifests generated from compose | Not first: a cluster to run one instance of one platform. It stays phase 10 of ADR 0003 |
| **One virtual machine running compose** | Runs every part unchanged; it is the production compose file zer0-CMS already decided on, and a node as ADR 0003 defines one | **Adopted** as the first host |
| **The provider's identity-aware tunnel with OS Login** | SSH as the operator's own cloud identity, no stored key, no port 22 open to the internet, no charge | **Adopted** as the only way to reach the machine |
| An identity-aware proxy in front of web traffic | A sign-in gate with no application code | Later (G4): it needs a load balancer that is billed while idle. It is how the console could be reached before private mode exists |
| **zer0-CMS's own sign-in** (django-allauth, headless) | Built: passkeys, a second factor, OpenID Connect, sign-up closed | **Adopted** as the first sign-in |
| One sign-in for the fleet (the hub's Django backend of ADR 0006, or zer0-id) | One account across every application | Later (G6): neither is built, and ADR 0006 leaves the choice open |
| A reverse proxy on the machine with automatic certificates (Caddy, Traefik) | One container terminates TLS for every host | Chosen in G2, with its own prior-art step |
| A provider load balancer with managed certificates | Nothing to renew, and the place an identity-aware proxy attaches | Later (G7): billed while idle |
| **Workload Identity Federation** | A deploy job signs in with GitHub's own token; no key exists | **Adopted** (ADR 0018) |
| Azure, where the main site and the portal are | Already in use, with a working pattern | The maintainer's direction is Google Cloud for the platform. The static main site stays where it is until it is moved on purpose |

**Build versus adopt.** Adopt a virtual machine, the provider's tunnel, federated sign-in for jobs and the platform's own sign-in for people. Build nothing new: one data file, two OpenTofu modules and a page on the main site.

## Decision

1. **Google Cloud hosts the platform.** The platform is bashOS, the Harness Console, zer0-CMS and each repo's application. It runs on Google Cloud; its source stays on GitHub.
2. **Its first host is one machine that is a fleet node.** A virtual machine on Debian with bashOS installed, running the same compose stacks as any node. Once it exists it is enrolled in `_data/fleet.yml` `nodes:` and placed, linked and configured like any other (ADR 0003). Nothing about the platform is rewritten to fit the cloud.
3. **One file says what is hosted.** [`_data/hosting.yml`](../../_data/hosting.yml) names the provider and region, the main site that is the way in, the machine, and each service with its host, its sign-in path and what it still needs. The OpenTofu modules read it themselves, so there is no second copy.
4. **Three switches, shipped off, flipped in order.** `node.enabled` creates the machine. `node.public` opens ports 80 and 443. A service's `enabled` lists it on the main site, and may be true only when nothing is left in its `needs` and the front door is open. Each flip is a pull request and then a plan the maintainer reads and applies.
5. **Two ways into the machine, and no third.** SSH, only through the provider's identity-aware tunnel, as the operator's own identity. HTTP and HTTPS from the internet, only while `node.public` is true. Every other port is reachable only over the node's link.
6. **The main site is the way in.** It carries a sign-in page that lists each enabled service and links to that service's own sign-in. A service is linked and never framed: it signs people in on its own origin, so its cookies and its content policy stay its own. Each service has its own host name under the main site's domain.
7. **Only a service with its own sign-in is public.** A service may be opened to the internet only when it signs people in itself and its sign-up is closed. The Harness Console is not such a service: it stays on the machine's loopback, reached over the link, until private mode (ADR 0006) gives it a sign-in or an identity-aware proxy stands in front of it (G4). The read-only portal build is a different thing and may be served from anywhere.
8. **Data outlives the machine and leaves it.** Databases, media and the checkouts the platform writes to sit on a disk that survives the machine and is snapshotted daily. Database backups are written to a bucket the machine can add to and read from and cannot delete from. No client data goes on the machine before a backup has been restored once as a drill.
9. **ADR 0018's contracts hold.** OpenTofu; a federated login for jobs and no service account key; the four labels, with `source` written `<owner>_<repo>--<path>` because a Google Cloud label cannot hold a slash or a space; a plan by default and an apply only from a saved plan; a budget alert; and no project id, number, billing account or address in the repo.
10. **Managed services replace pieces when they pay for themselves.** A managed database, a bucket for media, a load balancer, then a cluster (ADR 0003, phase 10): each is its own change, with the cost it adds and the work it removes stated in it.
11. **What does not move.** The main site stays on Azure Static Web Apps. The portal's Azure deployment (#993) stays as built and off until G4 decides where the portal is served. `clouds.providers.gcp.enabled` in `_data/fleet.yml` is a different switch: it says whether the hub may read the provider's API (ADR 0018, P3), and it stays false.

### Phases

| Phase | Delivers | Creates or changes anything in a cloud? |
| --- | --- | --- |
| G0, this pull request | This record; `_data/hosting.yml` with every switch off; `infra/gcp/foundation` and `infra/gcp/node`, validated by CI; `infra/gcp/deploy.sh`; `tools/test_hosting.py`; [docs/HOSTING.md](../HOSTING.md). In bash-365.com, its own pull request: the sign-in page, listing nothing until a service is enabled | No |
| G1, the landing zone and the machine | The maintainer chooses the project and applies `foundation`, then flips `node.enabled` and applies `node`; bashOS installed; the machine enrolled in `nodes:` | Yes: the maintainer's applies. From here the machine is billed |
| G2, zer0-CMS on the machine | In zer0-CMS: its image published on a release tag and its production compose file (its PLAN H1). On the machine: the stack, a reverse proxy with certificates, an email sender. The DNS record; `node.public`; then `services.cms.enabled`, and the main site offers it | Yes |
| G3, backups | Database backups to the bucket on a schedule, and a restore drill recorded, before any client data | Yes |
| G4, the console and the portal | The console behind an identity-aware proxy or private mode, never a bare token; where the portal build is served decided | Yes |
| G5, each repo's application | A repo's compose stack on the machine with its own host and its own sign-in, one repo per change | Yes |
| G6, one sign-in | The fleet's identity provider decided (ADR 0006) and each service signed in through it | Yes |
| G7, managed services | A managed database, a media bucket, a load balancer, a cluster: each when it pays for itself | Yes |

Every phase after G0 is its own pull request under the tracking epic that follows acceptance. Choosing the project, linking billing, adding a DNS record, setting a secret and every apply stay the maintainer's.

## Consequences

**Positive**

- The platform runs in the cloud without being rewritten: the same image roles, the same compose stacks, the same node model.
- One file and three switches describe the whole of it, and nothing exists or is reachable until the maintainer flips one.
- The main site gains one stable way in, and a visitor never meets a service that is not ready: the page lists only what is enabled.
- No key is stored anywhere: a job federates, a person signs in as themselves, and the machine cannot erase its own backups.
- It reuses decisions already made: ADR 0003 for the machine, ADR 0018 for how it is declared, zer0-CMS's ADR 0004 for how its stack is run.

**Negative**

- A machine costs money for every hour it exists, and the budget alert warns without capping. The static sites cost nothing; this does. The amount depends on the machine type in `_data/hosting.yml` and should be read from the provider's calculator before G1.
- One machine is one point of failure, and patching it is ours. Snapshots and off-machine backups limit what a loss costs; they do not prevent an outage.
- zer0-CMS has to build its deploy milestone first. Its plan put that last; this moves it forward, in its own repository and by its own rules.
- Nobody can sign in until the platform has an email sender, and choosing one is a decision not yet made.
- The console is not reachable from the main site until G4. Reaching it sooner would mean exposing a program that holds the fleet's credentials.
- The modules are validated by CI and have never been applied. The first plan is where a wrong assumption shows.
- Two clouds are in use, and the OpenTofu state for this one lives on the maintainer's Mac until it is moved to a bucket.

## Alternatives considered

- **Serverless containers from the start** — the platform would have to change first: a storage backend, the workers' model, the files it treats as the record. It becomes a candidate piece by piece (G7).
- **A cluster from the start** — a control plane to run for one instance. ADR 0003 already places it last.
- **Host the platform on Azure, beside the main site** — it would work, and the maintainer's direction is Google Cloud.
- **One host name with a path per service** — every service would share one origin, so one service's script could read another's cookies. A host name each keeps them apart.
- **Frame each service inside the main site** — zer0-CMS's own content policy forbids it, and it is right to: a framed sign-in is where credentials are phished.
- **Open the console with a bearer token** — it holds the fleet's GitHub credentials and runs jobs. A token in a browser is not a sign-in.
- **Let CI apply the modules** — CI would hold a credential that can create machines. The maintainer applies from a plan they have read.

## Supersedes / Superseded by

- Supersedes: none. It applies ADR 0003 to a machine in a cloud and ADR 0018 to Google Cloud's first use.
- Superseded by: none

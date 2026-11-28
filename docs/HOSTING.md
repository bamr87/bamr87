# Hosting — the platform on Google Cloud, entered through the main site

> Where the platform runs in the cloud, how a person gets into it from bash-365.com, and the three switches that decide what exists and what is reachable. Nothing here has been applied.

The decision record is [ADR 0020](adr/0020-platform-on-google-cloud.md). This page covers phase G0: the description, the infrastructure as code and the rules. Where repos deploy today is [CLOUDS.md](CLOUDS.md); how a machine becomes a node is [PLATFORM.md](PLATFORM.md).

## The model in one paragraph

The platform (bashOS, the Harness Console, zer0-CMS and each repo's application) is hosted on **Google Cloud**, first on **one machine that is a fleet node**: a virtual machine on Debian with bashOS, running the same compose stacks as any node. **The main site is the way in**: bash-365.com carries a sign-in page that links to each hosted service's own sign-in. A service signs people in on its own host, so it is linked and never framed. One file, [`_data/hosting.yml`](../_data/hosting.yml), says what is hosted, and three switches in it, all shipped off, decide what exists and what the internet can reach.

```text
   a visitor                     bash-365.com  (the main site, Azure Static Web Apps)
       │                                  │  /sign-in/  lists each ENABLED service
       ▼                                  ▼
   https://cms.bash-365.com/studio/  ─────────────────────────────┐
       │  ports 80 and 443, only while node.public is true         │ DNS: Microsoft 365
       ▼                                                           │
 ┌───────────── Google Cloud · one machine · a fleet node ────────┴──────────────┐
 │ reverse proxy with certificates (G2)                                           │
 │   └─ zer0-CMS: web · worker · scheduler · relay · Postgres (vector) · Redis    │
 │ bashOS · the Harness Console on loopback (never public: G4)                    │
 │ data disk: databases, media, checkouts  ── daily snapshots                     │
 │                                         ── backups to a bucket it cannot erase │
 └──────▲──────────────────────────────────────────────────────────────────────── ┘
        │ SSH, only through the provider's identity-aware tunnel, as yourself
   the maintainer:  infra/gcp/deploy.sh  (plans by default, applies a saved plan)
```

## The three switches

All three are in `_data/hosting.yml` and all three ship `false`. Flipping one is a pull request, then a plan you read and apply.

| Switch | While it is `false` | Flip it when |
| --- | --- | --- |
| `node.enabled` | `infra/gcp/node` plans nothing; no machine exists and nothing is billed | the landing zone is applied and you are ready for a machine that costs money every hour |
| `node.public` | no rule lets the internet reach ports 80 and 443; the machine is reached only by SSH through the tunnel | a service on the machine answers, has its own sign-in with sign-up closed, and its DNS record exists |
| `services.<name>.enabled` | the main site's sign-in page does not offer the service | nothing is left in the service's `needs` and `node.public` is true |

`tools/test_hosting.py` holds the order: `node.public` needs `node.enabled`, and a service cannot be enabled while it still owes something or while the front door is shut.

## Operate — the short card

```bash
gcloud auth application-default login      # once, as yourself
export GCP_PROJECT_ID=<the project>        # never committed
infra/gcp/deploy.sh foundation             # plan the landing zone
infra/gcp/deploy.sh foundation --apply     # apply exactly that plan
infra/gcp/deploy.sh node                   # plan the machine (nothing while node.enabled is false)
python3 tools/test_hosting.py              # the rules, offline
```

`deploy.sh` needs OpenTofu (`brew install opentofu`). It never applies without `--apply`, and `--apply` uses the plan the last run saved and refuses if the module or `_data/hosting.yml` changed since. State lives in `~/.local/state/bamr87-infra/`, outside every checkout.

## A development instance

`_data/hosting.yml` `dev:` describes a second, smaller machine for review and validation. It is the same module as the platform's machine with its own state, and three rules that `tools/test_hosting.py` holds:

- **Never public.** `dev.public` is always false. It is reached through the identity-aware tunnel and shows up on your own `127.0.0.1`.
- **Nothing durable.** No data disk, no snapshots, no backups bucket and no deletion protection, so `infra/gcp/deploy.sh dev --destroy` and then `--apply` removes all of it.
- **No client data.** It runs a service's development stack with made-up content. Sign-in codes are printed to the app's log because it has no email sender.

```bash
infra/gcp/deploy.sh dev              # plan, then: infra/gcp/deploy.sh dev --apply
infra/gcp/dev/up.sh                  # zer0-CMS's own `docker compose --profile content`, on the machine
infra/gcp/dev/up.sh --tunnel         # forward it, then open http://127.0.0.1:8000/studio/
```

It is billed for every hour it exists, like any machine. `dev.enabled: false` and an apply, or the `--destroy` plan, ends that.

## What is created

| Module | Creates | Billed while idle |
| --- | --- | --- |
| [`infra/gcp/foundation`](../infra/gcp/foundation/SCHEMA.md) | the APIs the platform uses; a keyless sign-in for GitHub Actions (Workload Identity Federation) with a deploy identity for each service that names one; a pull-through of ghcr.io; a budget alert when `GCP_BILLING_ACCOUNT` is set | No |
| [`infra/gcp/node`](../infra/gcp/node/SCHEMA.md) | a private network with two firewall rules; a fixed address; the machine; a data disk with daily snapshots; a backups bucket; the machine's own identity with three roles | Yes: the machine, its disks, its address and its snapshots |

The budget alert warns at 50, 90 and 100 percent of its amount. It does not stop spending. Read the machine type's price in the provider's calculator before flipping `node.enabled`.

## How a person gets in

1. They open the main site and choose **Sign in**.
2. The sign-in page lists each service whose `enabled` is true, with a link to `https://<host><sign_in>`.
3. The service signs them in on its own host. For zer0-CMS that is its studio: a local account with an emailed code, a passkey or a second factor, or single sign-on through an OpenID Connect provider. Sign-up is closed, and a new account sees nothing until an operator gives it a group.

Nothing is framed and no session is shared between the main site and a service. Each service has its own host name under the main site's domain, so its cookies and its content policy stay its own.

## What is public, and what is not

- **Public, once its switches are on:** a service that has its own sign-in with sign-up closed. zer0-CMS is the first.
- **Never public as it is:** the Harness Console. It holds the fleet's GitHub credentials and runs jobs, and it has no sign-in. On the machine it binds loopback and is reached over the node's link, until private mode (ADR 0006) or an identity-aware proxy stands in front of it (ADR 0020, G4).
- **Public already, and separate:** the read-only portal build of the console. It is a static site and may be served from anywhere.

## Security

- **No stored key.** A workflow signs in with GitHub's own token through Workload Identity Federation, and only from a repo and GitHub environment `_data/hosting.yml` names. A person signs in as themselves. No service account key is created.
- **No SSH from the internet.** Port 22 is open only to the provider's identity-aware tunnel. The operator connects with `gcloud compute ssh <name> --tunnel-through-iap` and their own identity; no SSH key is written to the project or the machine.
- **The machine cannot erase its backups.** It may add a backup to the bucket and read one back. It may not delete one, and the bucket keeps versions.
- **What holds data cannot be planned away.** The data disk and the backups bucket carry `prevent_destroy`, and the machine has deletion protection.
- **No identifier in the repo.** The project id, its number, the billing account and the machine's address come from the environment or from an apply's output. `_data/` is public site data.
- **CI holds no cloud credential.** `.github/workflows/infra.yml` formats and validates the modules. Only the maintainer plans and applies.

## What is yours

- Choosing the Google Cloud project and linking billing.
- Every `infra/gcp/deploy.sh … --apply`.
- Each switch in `_data/hosting.yml`.
- The DNS record for each host, in the Microsoft 365 admin center.
- Every secret a service needs, and the choice of an email sender.

## What comes next

| Phase | Adds |
| --- | --- |
| G1 | The landing zone and the machine applied; bashOS installed; the machine enrolled in `_data/fleet.yml` `nodes:` |
| G2 | zer0-CMS on the machine: its image and production compose file (built in its own repo), a reverse proxy with certificates, an email sender, its DNS record, and the main site offering it |
| G3 | Database backups on a schedule and a restore drill, before any client data |
| G4 | The console behind a sign-in, and where the portal build is served |
| G5 | Each repo's application, one per change |
| G6 | One sign-in for every service |
| G7 | Managed services where they pay for themselves, then a cluster |

## Files

| File | Role |
| --- | --- |
| `_data/hosting.yml` | What is hosted: the provider and region, the main site, the machine, each service, and the three switches |
| `infra/gcp/foundation/` | The landing zone in OpenTofu |
| `infra/gcp/node/` | The machine in OpenTofu |
| `infra/gcp/deploy.sh` | Plan a target (`foundation`, `node`, `dev`), apply its saved plan, or plan the development instance's removal |
| `infra/gcp/dev/` | The scripts that start a service's development stack on the development instance and forward it to your loopback |
| `tools/test_hosting.py` | The rules of `hosting.yml`, no identifier in the repo, the switches gating every resource, the two ways in, and the script planning by default |
| `.github/workflows/infra.yml` | Formats and validates each module; holds no credential |
| [ADR 0020](adr/0020-platform-on-google-cloud.md) | The decision, the prior art and the phases |

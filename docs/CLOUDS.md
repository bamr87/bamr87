# Clouds — where each repo's deliverable runs

> Which fleet repo deploys to which platform, how it signs in there, and whether its resources are declared as code: read from the repos' own files, for any provider, with one command.

The decision record is [ADR 0018](adr/0018-clouds-as-fleet-targets.md). This page covers what is built, which is phase P0: the provider model and the reader. The phases that read a cloud itself (what ran, what answers, what exists, what it costs) are listed [at the end](#what-comes-next).

## The model in one paragraph

A **provider** is a platform the fleet deploys to and does not operate: GitHub, Azure, AWS, Google Cloud, Cloudflare. `_data/fleet.yml` `clouds:` declares each one once: how a deployment to it is recognised, how the fleet is expected to sign in, which files declare its resources, and whether the hub may read it. **Which repo deploys where is never declared.** `tools/fleetcore/clouds.py` reads it from each owned repo's checkout, so the map cannot disagree with what the repos do. A provider is not a node: a node is a machine the fleet operates and places hub workloads on ([PLATFORM.md](PLATFORM.md)).

```text
   _data/fleet.yml  clouds:                       each owned repo's checkout
   providers · services · sign-in rule            .github/workflows/*.yml · live_url · CNAME
   infrastructure file patterns · read switch     infra/**/*.bicep · *.tf · wrangler.toml · …
                      │                                          │
                      └────────────┬─────────────────────────────┘
                                   ▼
                    tools/fleetcore/clouds.py   status_doc()   →   fleet-clouds/v1
                                   │
            tools/dash cloud  (now)   ·   console · MCP · published site · TUI  (P1)
```

## Operate — the short card

```bash
tools/dash cloud                                  # providers, every deployment, and the count of findings
tools/dash cloud map --provider azure             # only one provider's deployments
tools/dash cloud map --repo bash-365.com          # only one repo's
tools/dash cloud check                            # the findings, warnings first
tools/dash cloud check --strict                   # the same, exit 1 on a warning
tools/dash cloud json                             # the document (fleet-clouds/v1)
tools/dash cloud --instance ~/some-other-hub      # another control plane's registry and checkouts (or FLEET_HOME)
```

Every command only reads files in checkouts that are already on disk. It opens no network connection, runs no other program, needs no credential and writes nothing.

## What counts as a deployment

| Evidence | What the reader looks at | Example |
| --- | --- | --- |
| `workflow` | A step in `.github/workflows/*.yml` that uses a provider's action, or whose script runs its command line. Comment lines are ignored | `uses: actions/deploy-pages@v5`; `swa deploy ./_site` |
| `live_url` | The registry's `live_url` on a provider's own host, when no workflow deploys that service | a branch-built Pages site at `<owner>.github.io` |
| `file:<name>` | A marker file at the repo root, when no workflow deploys that service | `CNAME` for a Pages site on its own domain |

Jobs of one workflow that deploy the same service are one deployment, listed with every job and every GitHub environment they name. An environment name the workflow works out at run time reads `(computed)`.

The registry's `live_url` is shown beside one deployment only: the service whose own host it is on, else the repo's only static deployment. A repo that deploys twice does not get one address printed beside both.

## How a deployment signs in

The reader classifies each deployment from the steps of its jobs, worst first:

| Reads | Means | Recognised by |
| --- | --- | --- |
| `secret` | The job holds a stored credential | the provider's sign-in step or the deploy step takes an input listed under `secret`, or the deploy step is handed a repo secret and signs in no other way |
| `unknown` | The reader could not tell | a deploy command with no sign-in step it recognises |
| `oidc` | The job exchanges GitHub's own token for a short-lived one and stores nothing | the sign-in step takes an input listed under `oidc` |
| `platform` | The platform's own token | a provider whose rule is `platform`, with no other sign-in |

One job with a stored credential decides how the whole deployment reads. `GITHUB_TOKEN` is the platform's token and never counts as stored. The document lists the **names** of the secrets and variables a deployment's sign-in and deploy steps refer to, never a value: the names are in the workflow files already.

## The findings

`tools/dash cloud check` prints them. They are advice: nothing here fails a build until ADR 0018's P3 makes the first one a gate.

| Rule | Level | Fires when |
| --- | --- | --- |
| `stored-credential` | warn | a deployment signs in with a stored credential and the provider's rule is `oidc` |
| `unmanaged-credential` | note | a stored credential's name is not in `_data/fleet.yml` `tokens:`, so nothing audits or rotates it |
| `identity-unknown` | note | how a deploying workflow signs in could not be read from its steps |
| `no-iac` | note | a repo deploys to a provider from a workflow, and no file in the repo declares the resources it deploys to |
| `iac-without-deploy` | note | a repo declares a provider's resources and no workflow deploys to that provider: applied by hand, or not yet |

## What the reader does not see

It reports what a repo **can** deploy, from its files. Read the map with these limits in mind:

- **A repo that was not read is named, never counted as clean.** A registry repo that is not checked out, or is not a submodule of the instance, is listed under `NOT read`. A repo under another owner is counted and never opened.
- **It does not know whether a deployment ran or answers.** A workflow that skips itself for a missing variable still appears. What ran and what answers arrive in P2.
- **A deployment inside a called workflow or a local composite action is not seen**, unless the called workflow is itself one of the listed actions. No fleet repo deploys that way today.
- **A deploy action that is not listed is invisible** until it is added to `clouds:`.
- **Infrastructure files are searched with limits**: hidden directories, the directories under `clouds.scan.skip_dirs` and nested checkouts are skipped, six directories deep, 400 files a repo. A search that was cut short sets `iac_cut` on the repo's row.

## The document

`status_doc()` is the one thing every surface reads. Its schema marker is `fleet-clouds/v1`: adding a field is free, renaming one changes the marker.

| Key | Holds |
| --- | --- |
| `providers` | each declared provider: `id`, `title`, `enabled` and `state` (`on` or `off`), its sign-in rule, its services with their `kind`, and counts of deployments, repos and infrastructure files |
| `deployments` | each deployment: `repo`, `provider`, `service`, `kind`, `evidence`, `workflow`, `jobs`, `environments`, `urls`, `identity` (how it signs in), `expected` (the provider's rule), and the `secrets` and `vars` names |
| `iac` | per repo and provider, the files that declare resources (the first five and the count) |
| `repos` | every repo that was read: its workflow count, any workflow file that could not be parsed, and the providers it deploys to |
| `read` | how many checkouts were read, the repos that were not and why, and how many belong to another owner |
| `findings` | the rows of the table above |
| `summary` | totals, the deployments on a provider the hub does not read (`unwatched`), deployments per `kind`, findings per level |

A service's `kind` means the same on every provider: `static`, `container`, `function`, `stack` or `cluster`.

## Adding a provider or a service

Edit `_data/fleet.yml` `clouds:` and nothing else. The reader names no vendor, and `tools/test_fleetcore_clouds.py` fails if it starts to.

```yaml
clouds:
  providers:
    example:
      title: Example Cloud
      enabled: false              # the read switch; a new provider ships off
      identity: oidc              # oidc | platform | secret: how a deployment is expected to sign in
      login:
        - uses: example/login     # the sign-in action
          oidc: [role]            # an input that means a federated login
          secret: [access-key]    # an input that means a stored credential
      services:
        sites:
          kind: static
          uses: [example/sites-deploy]
          run: ['example sites push']
      iac:
        - { name: '*.tf', contains: example/provider }
```

`tools/dash cloud` then finds the provider's deployments in every repo. An instance of the framework (ADR 0011) inherits how each provider is recognised and lays its own `clouds:` over it, so it sets a switch without copying the list.

## The read switch

`enabled` says whether the hub may call a provider's API. Every provider but GitHub ships `false`, and P0 calls none, so today the switch only shows in the `READ` column and in the count of deployments nothing watches. Turning a provider on is a deploy step the maintainer approves (constitution § 10.5), and it arrives with the phase that reads that provider.

## What comes next

| Phase | Adds |
| --- | --- |
| P1 | `GET /api/clouds`, the console's Clouds page, MCP `fleet_clouds`, the TUI, the fleet graph, and a committed snapshot so the published sites show the map |
| P2 | What ran (GitHub's deployment records) and what answers (a synthetic check of every address through the fleet's collector) |
| P3 | One federated, read-only identity per provider, as code; cloud credential names in the token contract; `stored-credential` becomes a gate |
| P4 | Each enabled provider's resources by label, and the drift between them and the files that declare them |
| P5 | Each provider's billing as a FOCUS export, with a budget, on the Costs page |
| P6 | A deploy kit: one reusable workflow per `kind`, with the provider as an input |
| P7 | Logs, metrics and traces from running deployments into the fleet's planes |

## Files

| File | Role |
| --- | --- |
| `_data/fleet.yml` `clouds:` | The providers: how each is recognised, its sign-in rule, its infrastructure file patterns, its read switch, and what a search skips |
| `tools/fleetcore/clouds.py` | The reader and `status_doc()`; `python3 -m fleetcore.clouds` is `tools/dash cloud` |
| `tools/test_fleetcore_clouds.py` | Fixture tests with two made-up providers, the committed model, and the rule that the reader names no vendor |
| [ADR 0018](adr/0018-clouds-as-fleet-targets.md) | The decision, the prior art, the five contracts and the phases |
| [`infra/`](../infra/README.md) | The infrastructure the hub itself declares: OpenTofu for nodes, Bicep for the portal on Azure |

# PRD — Automatic credential rotation

> **Status: Draft / proposed (backlog).** Schedule- and event-triggered rotation for the credentials the weekly credential loop does not reach, through the protocol the fleet already has ([TOKEN-ROTATION.md](../TOKEN-ROTATION.md)). Its first trigger is a GitHub secret-scanning alert, which starts a rotation of the affected key instead of only flagging it (§ 7.1). Design only. This pull request implements nothing: no workflow, tool, setting, secret or `_data/fleet.yml` change. Accepted when the maintainer merges it.
> Feature: `HUB-NEW:credential-auto-rotation`, a fragment in [`features/features.d/`](../../features/features.d/). Numbers are assigned at merge ([amendment 0002](../amendments/0002-conflict-free-numbering.md)).
> Requirements: `FR-NEW:credential-rotation-contract`, `FR-NEW:credential-rotation-alert-trigger`, `FR-NEW:credential-rotation-triggers`, `FR-NEW:credential-rotation-methods`, `NFR-NEW:credential-rotation-failure`, `NFR-NEW:credential-rotation-audit`, declared on that fragment and numbered at merge.
> Roadmap: `FF-NEW:credential-auto-rotation`, a fragment in [`_data/roadmap.d/`](../../_data/roadmap.d/).
> Predicted ids (`python3 -m tools.jev number plan`, 2026-11-11): `HUB-105`, `FR113`–`FR116` (the alert trigger is `FR114`), `NFR25`–`NFR26`, `FF-0053`. A pull request that merges first moves the numbers. The slugs do not move.
> Direction and incidents: [bamr87/bamr87#788](https://github.com/bamr87/bamr87/issues/788) (Amr's direction: a routine that updates tokens across the fleet), [bamr87/bamr87#460](https://github.com/bamr87/bamr87/issues/460), [ai-world-view/ai-world-view.github.io#29](https://github.com/ai-world-view/ai-world-view.github.io/issues/29), [bamr87/bamr87#761](https://github.com/bamr87/bamr87/issues/761).
> Governing rules: [`docs/constitution.md`](../constitution.md) § 2 (secrets are never printed, logged or committed), § 10, § 11.8, § 12.3, § 13.6 and § 17; UPS-OPS-20 and UPS-OPS-22 in [`specs/OPERATIONS.md`](../../specs/OPERATIONS.md). No constitution section is opened here. § 15 names one follow-up amendment and does not write it.

## 1. Problem

The fleet has a key rotation protocol: the token contract in `_data/fleet.yml` `tokens:` and the weekly credential loop that reads it ([TOKEN-ROTATION.md](../TOKEN-ROTATION.md)). It keeps the hub's fleet-scoped secrets current in every repository the hub's owner holds. Three credentials are broken today, and each one sits outside that loop for a different reason.

| Credential (name only) | Incident | Since | Why the loop did not catch or heal it |
| --- | --- | --- | --- |
| zer0-CMS Google API key | [#460](https://github.com/bamr87/bamr87/issues/460): a public secret-scanning alert, type `google_api_key`, marked `publicly_leaked` | Alert open since 2026-10-21 (21 days) | The loop starts on a schedule and judges age. Nothing in it reads a secret-scanning alert, and a third-party provider key is not in the contract |
| ai-world-view org `CLAUDE_CODE_OAUTH_TOKEN` | [ai-world-view.github.io#29](https://github.com/ai-world-view/ai-world-view.github.io/issues/29): the daily probe reports the token degraded | Issue open since 2026-09-19 (53 days); secret last set 2026-08-18 (85 days) | The loop surveys and writes repository secrets in repos owned by the hub's owner (`fleet_repos()` in `tools/fleet-config.py`). An organization secret under another owner is outside both, and the ledger has no `ai-world-view` row |
| `bamr87/it-journey` `AUTO_PR_GITHUB_TOKEN` | [#761](https://github.com/bamr87/bamr87/issues/761): the token is set but rejected, so 7 of 7 scheduled Issue Autopilot runs failed at checkout from 2026-10-31 to 2026-11-06 | Runs failing since 2026-10-31; secret last set 2026-07-02 (132 days) | A repo-specific secret. UPS-OPS-22 asks only that it be documented by name, so it has no entry in `tokens:` and no row in `token-rotation.yml` `env:` |

Ages are as of 2026-11-11. In all three cases something detected the failure (GitHub's scanner, a repo's own probe, the fleet doctor), an issue was filed, and nothing started a rotation. The gap is between detection and action, and it is the same gap [#788](https://github.com/bamr87/bamr87/issues/788) asks the console to close.

Amr's direction on 2026-11-11 closes it for the leak first. A secret-scanning alert for a covered credential must start the rotation of the affected key, not only flag it, and the zer0-CMS `google_api_key` alert tracked in #460 is the first one wired (§ 7.1).

The audience is Amr as the owner of every credential here, and the agents that keep filing issues about dead credentials they cannot fix.

## 2. Goals and non-goals

**Goals**

- Every credential the fleet's automation depends on is declared by name in one contract, with its owner, where it lives, how it is rotated and how often.
- A secret-scanning alert for a covered credential starts a rotation of the affected key by itself. It is the protocol's first trigger, wired first for `google_api_key` alerts on zer0-CMS (#460).
- A rotation also starts on its schedule and on the other events: a failed health probe, a run of consumer failures, an approaching expiry.
- A credential a provider can re-issue through an API is rotated with no human step. A credential only a person can mint is rotated with one prepared human step and a check afterwards.
- Every rotation follows Design for Failure: detection, containment, recovery, verification and an audit trail, with containment first (revoke or restrict) when the trigger is a leak.
- No secret value, or part of one, is ever printed, logged, committed or written to an issue.

**Non-goals**

- Implementing any of it in this pull request. No workflow, tool, schedule, `_data/fleet.yml` entry, repository setting or secret changes here.
- Rotating, revoking or re-issuing any of the three credentials now. Their incidents stay with their issues.
- Fixing the consumers. The presence-only `||` token chain in it-journey's `issue-autopilot.yml` and the literal test fixture in zer0-CMS are fixed in those repositories under #761 and #460.
- A new secrets manager, or a second contract beside `_data/fleet.yml` `tokens:`.
- Rewriting git history to remove a leaked value. Agents never force-push (constitution § 4). Revocation is the containment.
- Replacing `dash keys`, which already owns `ANTHROPIC_API_KEY` ([AI-INTEGRATION.md](../AI-INTEGRATION.md#anthropic-api-keys-per-workspace)).
- Hand-assigning `HUB-NNN`, `FRn`, `NFRn` or `FF-NNNN`.

## 3. The protocol this reuses

This PRD defines no new protocol. It extends the one in [TOKEN-ROTATION.md](../TOKEN-ROTATION.md), and every row below stays what it is.

| Existing piece | What it already does | What this backlog item asks of it |
| --- | --- | --- |
| Token contract, `_data/fleet.yml` `tokens:` | Names each secret, its `scope` (`fleet` or `hub`), its purpose, its consumers and its `rotation:` policy (`max_age_days`, `lifetime_days`, `renew_before_days`, `value_prefixes`) | New scopes for a single repository, an organization and a third-party provider, plus an owner, a rotation class and triggers (§ 6) |
| Weekly loop, `token-rotation.yml` and `dash secrets` | Propagates the hub's value to missing, stale or behind-the-hub copies; audits ages from GitHub's `updated_at`; re-mints only through the opt-in refresh grant; hub first; probes `FLEET_TOKEN` for `secrets:write` before anything else | The same order and guardrails for the new scopes. Its schedule stays the heartbeat, and events become a second way in (§ 7) |
| `dash keys` and `api-keys.yml` | Assisted rotation of the per-workspace Anthropic keys: a person creates the key, the tool proves it with one cheap call, writes it hub first, records the ledger, then disables the key it replaced; a daily expiry check keeps one issue open | The model for every assisted rotation here (§ 8). It is not replaced |
| Ledgers, `_data/token_rotation.yml` and `_data/api_keys.yml` | Names, ages, states and outcomes, published through `utilities/publish-data`. Never a value | One more kind of row: a rotation event with its trigger and its steps (§ 10) |
| The one tracking issue ([#148](https://github.com/bamr87/bamr87/issues/148)) and the `credential-overdue` trip wire ([HARNESS.md](../HARNESS.md)) | One issue updated in place with what the loop needs from a person; a wire that trips when a credential is past its policy plus grace | The place a prepared human step is posted, and the escalation when it is not done |
| `secret-expiry-watch.yml` in ai-world-view.github.io (year-of-ai.github.io runs a workflow of the same name) | A daily single-attempt probe of the repo's credentials that keeps one sticky issue and closes it when the probe passes | A detection source the hub reads. Today nothing consumes its signal |
| GitHub secret scanning and push protection (UPS-OPS-20) | Finds a committed credential and reports its type, its validity and whether it leaked publicly | The first trigger: an alert for a covered credential starts a rotation (§ 7.1). The alert is read, not re-implemented |
| Kill switches, `_data/fleet.yml` `switches:` (constitution § 17) | The only way a loop is paused or resumed | The containment for a dead credential that is burning runs (§ 9) |

The protocol has three gaps, and each of the three credentials falls into one of them.

1. **Scope.** `scope:` is `fleet` or `hub`. A secret on one repository, an organization secret and a provider key held outside GitHub cannot be declared, so they are neither audited nor rotated.
2. **Trigger.** A rotation starts on Monday 02:07 UTC or by hand. A leak alert, a rejected probe or a consumer that fails seven times in a row starts nothing.
3. **Method.** Re-minting exists for one credential (the Claude OAuth refresh grant) and assisted rotation for one more (`dash keys`). There is no adapter for a provider that can re-issue a key through an API, and no general prepare-and-verify flow for a credential a person must mint.

## 4. User stories

Stories are for Amr, who owns every credential in § 5, and for the agents that meet a dead credential. Work items stay on the Fleet project, a new tool is read-only until a person confirms a write, and nothing here runs on Amr's Mac (constitution § 10).

| Id | As a… | I want… | So that… | Requirement |
| --- | --- | --- | --- | --- |
| US1 | fleet operator (Amr) | every credential my automation reads declared by name, with its owner, where it lives, how it rotates and how often | no loop depends on a secret that nobody is watching | `FR-NEW:credential-rotation-contract` |
| US2 | fleet operator | a secret-scanning alert for a covered credential to start the rotation of the affected key by itself: contain it first, mint the replacement, update the secret that uses it, verify, resolve the alert as revoked and close the tracking issue | a leaked key is dealt with whether or not I have seen the alert, and the alert is not one more open issue | `FR-NEW:credential-rotation-alert-trigger`, `NFR-NEW:credential-rotation-failure` |
| US3 | fleet operator | a degraded or expiring token to start its own rotation | a credential does not stay dead for weeks behind an open issue | `FR-NEW:credential-rotation-triggers` |
| US4 | fleet operator | a key the provider can re-issue through an API rotated with no step from me | a 90-day rotation happens every 90 days | `FR-NEW:credential-rotation-methods` |
| US5 | fleet operator | one prepared step when only I can mint: the command or the link, the scopes, the expiry and where the value goes | my part is two minutes, not an investigation | `FR-NEW:credential-rotation-methods` |
| US6 | fleet operator | the new credential checked after I act, by what it can do and by its consumer running | a wrong scope or a mistyped value is caught before the next scheduled run fails | `FR-NEW:credential-rotation-methods`, `NFR-NEW:credential-rotation-failure` |
| US7 | maintainer of a fleet repo | a loop that is failing on a dead credential paused until the replacement is verified | it stops spending runs and minutes on a failure it cannot fix | `NFR-NEW:credential-rotation-failure` |
| US8 | owner of the credentials | a record of every rotation (what fired, what ran, who acted, how it ended) with no value in it | I can audit a rotation from a public repository | `NFR-NEW:credential-rotation-audit` |
| US9 | agent (fleet doctor, issue pipeline, Claude Code) | a credential failure classified as one, with a link to the rotation already in flight | I do not file a duplicate issue or attempt a code fix for an authentication problem | `FR-NEW:credential-rotation-triggers` |
| US10 | fleet operator | the alert found two ways, by a `secret_scanning_alert` webhook delivery and by a scheduled poll of the alerts API | a missed delivery, or a receiver that is down, does not hide a leak | `FR-NEW:credential-rotation-alert-trigger` |
| US11 | fleet operator | the rotation opened anyway when automation cannot finish it (no provider API, no access, a key it cannot match, a copy in my local `.env`), with the remaining steps handed to me in order, containment first, and checked after I act | I never have to notice the alert myself, and my part is only what automation cannot do | `FR-NEW:credential-rotation-alert-trigger`, `FR-NEW:credential-rotation-methods` |
| US12 | owner of the credentials | an alert that is a test fixture, or a key that is not mine, resolved by me and never marked revoked by automation | the alert's record says what happened | `FR-NEW:credential-rotation-alert-trigger`, `NFR-NEW:credential-rotation-audit` |

## 5. Covered credentials

Names only. The facts below were read on 2026-11-11 from the three issues, from `gh secret list` (names and dates; GitHub never returns a value) and from the repositories' own documents. Anything not read is marked **TBD**.

| Credential | Owner | Scope and location | Rotation | Proposed schedule |
| --- | --- | --- | --- | --- |
| zer0-CMS Google API key (`GEMINI_API_KEY`) | Amr, through the Google Cloud project that issues it | Provider key held outside GitHub | Automated (`gcloud services api-keys`), started by a secret-scanning alert or the schedule | 90 days |
| ai-world-view org `CLAUDE_CODE_OAUTH_TOKEN` | Amr, through the `ai-world-view` organization and the Claude subscription | Organization Actions secret | Assisted (`claude setup-token` browser sign-in) | 30 days before expiry, or 180 days |
| `bamr87/it-journey` `AUTO_PR_GITHUB_TOKEN` | Amr, through the `bamr87` account | Repository Actions secret | Assisted (GitHub web form) | 14 days before expiry; fine-grained, 90-day maximum |

### 5.1 zer0-CMS Google API key

| Field | Value |
| --- | --- |
| Name | `GEMINI_API_KEY`, the one Google-issued key zer0-CMS names (its `.env.example` and `SECURITY.md`). Secret-scanning type `google_api_key` |
| Owner | Amr (`bamr87`), as owner of the Google Cloud project that issues the key. Project: **TBD** |
| Scope and location | A third-party provider key, not a GitHub credential. The image generator's Gemini provider reads it from the environment (`packages/zer0-image-generator/`). The value lives in a local `.env`; whether the image-generator panel's own credential store also holds a copy is **TBD**. It is not an Actions secret on `bamr87/zer0-CMS` (which holds `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` and `RELEASE_PLEASE_TOKEN`), and it is not in the hub's token contract |
| Incident | Secret-scanning alert #1 on the public repository: `google_api_key`, `publicly_leaked: true`, validity `unknown`, open since 2026-10-21, in `content/tests/ops/test_logging.py`. The triage in #460 reads the flagged literal as a fixture of the log-redaction test. The owner's confirmation that it never was a live key is outstanding, and the alert is still open. Until that confirmation the protocol treats the alert as a leak |
| Rotation | **Automated.** Google's API Keys API through `gcloud services api-keys`. On the 90-day schedule: `create` a replacement with the same API and application restrictions, hand its key string to each consumer's secret store over stdin, verify, then `delete` the old key. On a secret-scanning alert the order turns round (§ 7.1): `delete` the affected key first, or narrow it with `update` where the contract says restrict, then `create`, update the consumers, verify, resolve the alert as `revoked` and close the tracking issue. The job signs in with GitHub OIDC through Workload Identity Federation, so no Google credential is stored. `undelete` restores a deleted key for 30 days; it is for a scheduled rotation that went wrong and never for a leaked key. Until the project and the federation exist (**TBD**) the human-in-the-loop fallback applies: the same steps in the same order, prepared for the Cloud console. A copy in a local `.env` is always a step for Amr, because automation does not write to his machine (constitution § 10.5) |
| Schedule | Every 90 days, with the age read from the key's `createTime` |
| Triggers | **First trigger:** an open secret-scanning alert of type `google_api_key` on any fleet repository starts a rotation of the affected key at once, containment first (§ 7.1). Alert #1 on `bamr87/zer0-CMS` (#460) is the first one wired. Then: age of 90 days, and a health probe the provider rejects |
| Verification | One read-only list-models call with the new key sent in the `x-goog-api-key` header, never in a URL. The old key's id absent from `api-keys list`. The alert resolved as `revoked` by the protocol once the old key is gone and the new one is proved, and the tracking issue (#460) closed. If the owner confirms the fixture instead, he resolves the alert as `used_in_tests` and nothing is marked revoked |

### 5.2 ai-world-view org `CLAUDE_CODE_OAUTH_TOKEN`

| Field | Value |
| --- | --- |
| Name | `CLAUDE_CODE_OAUTH_TOKEN` |
| Owner | Amr, as owner of the `ai-world-view` organization and of the Claude subscription the token is minted under (`claude setup-token` ties the token to whoever ran it) |
| Scope and location | An organization-level Actions secret on `ai-world-view`, last set 2026-08-18 (GitHub lists it among the organization secrets shared with `ai-world-view/ai-world-view.github.io`, which holds no repository-level copy). That is older than the hub's own copy (2026-09-30 in `_data/token_rotation.yml`): the loop's "behind the hub" condition, in a place the loop cannot see. Consumers are the site's Claude lanes; which other repositories of the organization read it is **TBD** |
| Incident | ai-world-view.github.io#29, "Secret Expiry Watch — credential degraded", open since 2026-09-19 and refreshed on 2026-11-11: still degraded |
| Rotation | **Assisted.** `claude setup-token` needs a browser sign-in and has no headless equivalent ([TOKEN-ROTATION.md](../TOKEN-ROTATION.md#what-rotate-can-actually-mean-here)). Automation prepares the step on the one tracking issue: the command, the `gh secret set CLAUDE_CODE_OAUTH_TOKEN --org ai-world-view` line that reads the value from stdin, and the trigger that fired. It verifies afterwards. If the organization may carry the hub's own credential (**TBD**: one subscription or two), no mint is needed and the step is a propagation of the hub's copy. The opt-in refresh grant is the unattended path where Amr has provisioned it |
| Schedule | A re-mint 30 days before the one-year expiry (`lifetime_days: 365`, `renew_before_days: 30`, the contract's existing policy), or at 180 days of age, whichever comes first |
| Triggers | The daily probe reports `degraded` on two consecutive days. Three consecutive `401` results in a consuming workflow. The expiry lead. The age limit. A `429` is a spent usage window, which is capacity and never a trigger ([AI-INTEGRATION.md](../AI-INTEGRATION.md#spend-guardrails)) |
| Verification | The organization secret's `updated_at` is later than the trigger. The one-turn probe answers. The sticky issue closes itself. The next scheduled consumer run authenticates |

### 5.3 `bamr87/it-journey` `AUTO_PR_GITHUB_TOKEN`

| Field | Value |
| --- | --- |
| Name | `AUTO_PR_GITHUB_TOKEN` |
| Owner | Amr (`bamr87`). It is a personal access token of that account |
| Scope and location | A repository-level Actions secret on `bamr87/it-journey`, last set 2026-07-02. The `resolve` job of `.github/workflows/issue-autopilot.yml` reads it as the checkout token and as `GH_TOKEN`, first in a presence-only `\|\|` chain ahead of `PAT_TOKEN` (set the same day) and `github.token`. It is in neither `_data/fleet.yml` `tokens:` nor `token-rotation.yml` `env:` |
| Incident | #761: GitHub rejects the token, the chain never tries the next one, and every `resolve` leg fails at checkout. 7 of 7 scheduled runs failed from 2026-10-31 to 2026-11-06 |
| Rotation | **Assisted.** GitHub has no API that mints a personal access token. The owner creates it in the web form. Automation prepares the step: the token's name, the single repository, the permissions the consumer needs (contents, pull requests and issues write, per #761), a 90-day expiry, and where the value goes (the hub `.env`, then `dash secrets push --only AUTO_PR_GITHUB_TOKEN`, which hands it to `gh secret set` over stdin, once the contract can target one repository). It verifies afterwards. #761 also names the durable alternative, a hub-rotated token in place of a repo-local one, and a GitHub App installation token minted per run would remove the stored token altogether. That choice is Amr's and is not made here |
| Schedule | Fine-grained, with a 90-day maximum lifetime, rotated 14 days before expiry. The expiry is read from the `github-authentication-token-expiration` response header by a probe that runs where the secret lives, so the hub never holds the value |
| Triggers | Three consecutive scheduled Issue Autopilot runs that fail in the checkout or authentication step. A probe the API rejects with `401`. An expiry 14 days away or less. A secret-scanning alert for the token |
| Verification | The secret's `updated_at` is later than the trigger. A capability probe with the new token reads the repository and confirms the declared permissions; it is a probe, not a presence check. A dispatched `resolve` run passes checkout. The next scheduled run is green or skipped |

## 6. The contract — `FR-NEW:credential-rotation-contract`

The token contract stays the one place a credential is declared. It gains what the three cases above need.

| Addition | Meaning |
| --- | --- |
| `scope: repo` | A repository secret on named repositories, in any fleet owner (`hub.owners`) |
| `scope: org` | An organization secret on one of the fleet's organizations |
| `scope: provider` | A third-party key whose issuer is not GitHub and whose copies may live outside GitHub secrets |
| `owner` | The account or person who can mint and revoke it |
| `rotation.class` | `automated` (a provider API mints and revokes), `assisted` (a person mints, automation prepares and verifies) or `propagate` (the hub's value is copied; the weekly loop's job today) |
| `rotation.triggers` | Which events in § 7 start a rotation, and their thresholds |
| `rotation.secret_scanning` | The secret-scanning alert types that mean this credential (`google_api_key` for the Google key), which is what makes an alert "covered", and whether containment is `revoke` or `restrict` |
| A probe and the consumers | How the credential is checked by what it can do, and which workflows fail when it is dead |

A sketch of two entries, to show the shape. The keys are settled in the implementation pull request, and nothing is added to `_data/fleet.yml` here.

```yaml
tokens:
  - name: GEMINI_API_KEY
    scope: provider                   # new; today: fleet | hub
    provider: google-api-keys
    owner: bamr87
    consumers: [bamr87/zer0-CMS]
    rotation:
      enabled: true
      class: automated                # automated | assisted | propagate
      max_age_days: 90
      triggers: [secret-scanning, age, probe]
      secret_scanning:
        types: [google_api_key]       # an alert of this type starts a rotation
        contain: revoke               # revoke | restrict

  - name: AUTO_PR_GITHUB_TOKEN
    scope: repo                       # new; today: fleet | hub
    targets: [bamr87/it-journey]
    owner: bamr87
    used_by: [issue-autopilot.yml]
    rotation:
      enabled: true
      class: assisted                 # automated | assisted | propagate
      max_age_days: 90
      renew_before_days: 14
      value_prefixes: ["github_pat_"]
      triggers: [expiry, age, probe, consumer-failures, secret-scanning]
      consumer_failures: 3
```

A secret a fleet workflow reads that the contract does not declare is reported by name as a gap. That report is how `AUTO_PR_GITHUB_TOKEN` and `PAT_TOKEN` would have been seen before July's token expired. Every existing rule of the contract still holds: drift check (l) for the names a workflow must list, a fleet-wide secret written hub first, and a token probed for what it can do instead of checked for presence.

## 7. Schedule and triggers

A rotation starts in one of six ways. The secret-scanning alert comes first: it is the first trigger this backlog item wires, and the only one that begins with containment. Age, expiry and manual are what the protocol does today.

| Trigger | Signal and where it is read | Starts |
| --- | --- | --- |
| 1. Secret-scanning alert | An open GitHub secret-scanning alert whose type a declared credential lists, on any fleet repository (§ 7.1) | At once, containment first |
| 2. Degradation | A capability probe the provider rejects with `401` or `403`, from the credential's health check (`secret-expiry-watch.yml` where a repository has one, the hub's probe otherwise) | After two consecutive failures |
| 3. Consumer failures | N consecutive runs of a declared consumer that fail in its authentication or checkout step | N = 3 by default |
| 4. Expiry | A known expiry (the token-expiration header of a GitHub token, the Console's `expires_at`, or `lifetime_days`) less `renew_before_days` | On the scheduled run |
| 5. Age | The secret's `updated_at`, or the provider's creation time, is older than `max_age_days` | On the scheduled run |
| 6. Manual | `dash secrets rotate` for one name, or the console job #788 asks for | On demand |

### 7.1 The first trigger: a secret-scanning alert starts a rotation — `FR-NEW:credential-rotation-alert-trigger`

When GitHub secret scanning raises an alert for a covered credential, the protocol starts a rotation of the affected key. It does not stop at an issue. The first alert type wired is `google_api_key`, and the first alert is #1 on `bamr87/zer0-CMS`, tracked in [#460](https://github.com/bamr87/bamr87/issues/460).

**Covered** means the alert's `secret_type` is one a declared credential lists (§ 6). The repository can be any fleet repository, because a key leaks where it was pasted, which is not always where it is used. An alert of a type no credential lists is reported as an undeclared credential (§ 6) and starts nothing. `publicly_leaked` and `validity` set a rotation's priority. They do not decide whether it starts.

**Detection.** Two paths feed one queue, keyed by repository and alert number.

| Path | How | Latency | Needs |
| --- | --- | --- | --- |
| Scheduled poll of the secret-scanning alerts API. It ships first and stays as the backstop | `GET /repos/{owner}/{repo}/secret-scanning/alerts?state=open&hide_secret=true` for each fleet repository, on the fleet's scheduled read. With `hide_secret=true` the response carries no secret, so detection never holds the value | One poll interval. Daily is the proposal; the target is **TBD** | A token that can read secret-scanning alerts on every fleet repository. Whether `FLEET_TOKEN` can is **TBD** |
| `secret_scanning_alert` webhook. The fast path | GitHub delivers the event when an alert is created or reopened. GitHub Actions has no workflow trigger of that name (`actionlint` rejects `on: secret_scanning_alert` as an unknown event), so a receiver forwards each delivery to the hub as a `repository_dispatch` that carries the repository and the alert number and nothing else | Seconds to minutes | A webhook or a GitHub App on the fleet's repositories, and a receiver. Both are settings and infrastructure only Amr adds. Neither is in this pull request |

The poll ships first because it needs nothing new. The webhook is added for speed, and the poll stays on: a delivery that is missed, or a receiver that is down, is caught by the next poll. Both paths keep the standing rule that a pull-request or push check never reads the whole fleet ([WORKFLOW-OPTIMIZATION.md](../WORKFLOW-OPTIMIZATION.md)).

**What a rotation started by an alert does**, in this order:

1. **Start.** Open the rotation: one ledger event keyed by repository and alert number, and the tracking issue. That is the open issue that already tracks the alert (#460 for the first one), or a new one labelled `security`, `tokens` and `P0`. This step needs no person and is the same for every rotation class.
2. **Identify the affected key.** Inside the rotation job, read the alert's secret in memory and compare it with the key strings of the declared credential's keys. The value is never a command argument, a URL parameter or a log line. If the provider cannot be reached to compare, the declared credential is treated as the affected key.
3. **Contain.** Revoke the affected key. Where the contract says `restrict`, narrow it first (for a Google key, its API and application restrictions) so the leaked string is useless to anyone else; a restricted key is still revoked once its replacement is verified.
4. **Mint the replacement**, with the restrictions the old key had.
5. **Update the consuming secret**: each consumer's secret store, over stdin, hub first where the secret is fleet-scoped.
6. **Verify**: a capability probe of the new key, each consumer running, and the old key gone from the provider.
7. **Resolve the alert as `revoked`**, with a resolution comment that links the rotation record.
8. **Close the tracking issue** with a values-free summary, and record the outcome.

Nothing is minted or written to a consumer before containment.

**Human-in-the-loop fallback.** The rotation always starts (step 1). A person is brought in only for a step automation cannot perform, and only for that step.

| When automation cannot act | What happens instead |
| --- | --- |
| The credential's class is `assisted`: no provider API mints it (a Claude OAuth token, a personal access token) | The mint is a prepared step (§ 8). Containment and everything after the mint stay automatic where an API allows them |
| The provider adapter has no access yet (the Google Cloud project and its federation are **TBD** today) | Every provider step is prepared for the provider's console, in the same order, containment first |
| The alert's secret matches no key the owner controls (a test fixture, a false positive, someone else's key) | Nothing is revoked on a guess, and automation never resolves the alert as `revoked`. The issue asks the owner to resolve it as `used_in_tests` or `false_positive`, or to name the project that holds the key |
| A consumer's copy lives where automation may not write (a local `.env`; constitution § 10.5) | The replacement is minted, and the step names the new key's id for the owner to fetch |
| The path is switched off, or not yet switched on (§ 9) | The alert is still detected. The issue says the rotation is waiting on the switch, and carries the prepared steps |

In the fallback the tracking issue carries the remaining steps as one ordered list that starts with containment, each with its exact command or link and no value. Automation checks each step as it is done (the old key gone, the secret's `updated_at` moved, the probe passing), then performs every later step it can, including resolving the alert and closing the issue. A step not done inside the policy's grace is reminded on the same issue and trips `credential-overdue`.

**Acceptance criteria**

1. **Detected.** An open alert of a covered type on any fleet repository is detected by the scheduled poll within one interval, and by the webhook path within minutes once that path exists. The poll requests alerts with the secret hidden.
2. **Started without a person.** Detection opens a rotation by itself: a ledger event keyed by repository and alert number, and the tracking issue attached or opened. On its first run it opens one for zer0-CMS alert #1 on #460.
3. **Containment first.** The affected key is revoked, or restricted where the contract says so, before a replacement is minted or any consumer is written.
4. **Completed without a person** where the credential is `automated` and the adapter has access: mint, update each consuming secret, verify, resolve the alert as `revoked`, close the tracking issue.
5. **Fallback.** Where automation cannot perform a step, the rotation still starts, the issue carries the remaining steps in order from containment, and automation verifies each one and performs every later step it can.
6. **Once.** A webhook delivery and a poll for the same alert, or repeated polls, produce one rotation. A reopened alert starts a new one.
7. **Never a false `revoked`.** An alert whose secret matches no key the owner controls is not resolved by automation. The owner resolves it, and the record says who did and how.
8. **Fails loudly.** A step that fails leaves the alert open and the issue saying what is needed. A leaked key that was deleted is never restored.
9. **No value anywhere.** The alert's secret, the old key and the new key appear in no log, ledger, issue, pull request, command argument or URL.
10. **Switch.** The path has a kill switch. With it off, alerts are still detected, and each one's issue says the rotation is waiting on the switch.

### 7.2 The other triggers — `FR-NEW:credential-rotation-triggers`

Degradation, consumer failures, expiry, age and manual start a rotation with the old credential still valid, so they follow the scheduled order in § 8. Rules that hold for every trigger, the alert included:

- Fleet-wide signals are read on a schedule, never from a pull-request or push check. The detection latency of a polled signal is therefore one scheduled read, and its target is **TBD**.
- A rate limit or a spent usage window (`429`) is capacity. Only an authentication failure counts.
- A trigger that fires while a rotation for the same credential is open joins it. One credential has at most one open rotation and one issue.
- A signal source that is off or unreachable reads `unknown`, never healthy. The protocol already keeps `unreachable` apart from `missing` for the same reason.
- The thresholds above (two probes, three runs, 90, 180 and 14 days) are proposals. They live in `_data/fleet.yml`, never in a workflow.

## 8. Rotation methods — `FR-NEW:credential-rotation-methods`

| Class | When | What automation does | What a person does |
| --- | --- | --- | --- |
| `automated` | The provider can create and revoke the credential through an API (a Google API key) | Contains, mints, validates, distributes, verifies and revokes | Nothing |
| `assisted` | Only a person can mint (a browser sign-in for `claude setup-token`, GitHub's token form, the Claude Console) | Prepares the step, waits, validates and distributes what the person supplied, verifies | Mints the credential and hands it over through `.env` or `gh secret set` stdin |
| `propagate` | The hub already holds the right value | Copies it to the declared targets, hub first | Nothing |

An assisted rotation has three parts.

1. **Prepare.** One issue, updated in place, states the credential by name, the trigger that fired, the exact command or link, the scopes or permissions and the expiry to choose, and where the value goes. It never asks for a value in a comment.
2. **Wait.** The issue stays open and is refreshed on each scheduled run. Past the policy's grace the `credential-overdue` wire trips. Nothing is rewritten while it waits, apart from the containment in § 9.
3. **Verify.** When a new value appears (the secret's `updated_at` moves past the trigger), automation checks its shape against `value_prefixes`, probes what it can do, runs or waits for the consumer, records the rotation and closes the issue.

The order of steps depends on why the rotation started.

| Started by | Order |
| --- | --- |
| Age, expiry, degradation, consumer failures, manual | mint → validate → distribute, hub first → verify the consumers → revoke the old credential → record |
| A secret-scanning alert (§ 7.1) | contain the affected key (revoke, or restrict first) → mint → validate → update the consuming secrets → verify → resolve the alert as `revoked` → close the tracking issue → record |

On the scheduled path the old credential stays valid until the new one is proved in every consumer, so a failed rotation costs nothing. On the alert path the consumer is down between containment and the update, and that is accepted: a leaked credential that still works is worse than a loop that is paused. Restricting first is the way to avoid the gap where the provider lets a key be narrowed to its legitimate caller.

## 9. Design for Failure — `NFR-NEW:credential-rotation-failure`

Every rotation passes through five stages.

| Stage | What it is | For the three credentials |
| --- | --- | --- |
| Detection | A trigger in § 7 fires and names the credential, its scope and its evidence | The secret-scanning alert, by webhook or by poll (zer0-CMS). The daily probe (ai-world-view). Three failed runs or the expiry header (it-journey) |
| Containment | Limit the damage before repairing | Leak: revoke or restrict the affected key first, started by the alert itself. Dead credential: pause the consumer that is burning runs, through the switches map (constitution § 17). The protocol plans the switch change and applies it under that map's own dry-run and confirm rule |
| Recovery | Mint or receive the replacement, validate it, distribute it hub first | `gcloud services api-keys create` (zer0-CMS). A prepared `claude setup-token` step (ai-world-view). A prepared token form (it-journey) |
| Verification | Prove the new credential by what it can do and by its consumer running; prove the old one is gone when it was revoked; then resolve the alert as `revoked` and close the tracking issue | § 5's Verification rows. A secret write that succeeded is not a rotation that succeeded |
| Audit trail | Record the trigger, each step, who or what acted and the outcome, with no value | § 10 |

Amr's direction is that the alert starts the rotation and that containment needs no one to notice it. Two rules bound how that is switched on, and neither turns it back into a flag. First, the path has a kill switch like every loop (constitution § 17), and as a new loop it is off until Amr turns it on. Second, a revocation and a secret write are external actions, which constitution § 13.6 starts at the high tier that waits for Amr's yes. The weekly propagation writes secrets unattended today under the protocol he ratified. Whether a new unattended revocation needs its own ratification is § 15's question, and it is settled in the gated pull request that switches the path on. While the path is off the fallback in § 7.1 applies: the rotation still starts by itself, and containment is the first prepared step.

| Failure | Detection | Behaviour | Recovery |
| --- | --- | --- | --- |
| A covered key leaks: a secret-scanning alert opens | The webhook delivery, or the scheduled poll (§ 7.1) | A rotation starts by itself, containment first; the consumer may go down; the alert is cited by its URL and its value is never copied | Mint, update the consumers, verify; resolve the alert as `revoked`; close the tracking issue |
| A webhook delivery is missed, or the receiver is down | The next poll finds an open alert with no rotation | The poll starts the rotation; the gap is recorded as detection latency | The receiver is repaired; the poll stays on as the backstop |
| The poll cannot read a repository's alerts | A `403` or `404`, or secret scanning disabled there | The repository reads `unknown`, never clean, and is named | Amr fixes the token's permission or the repository's setting; the protocol changes neither |
| The same alert arrives twice (webhook and poll, or two polls) | The rotation's key: repository and alert number | One rotation; the second arrival joins it | Nothing to do |
| An alert is reopened, or a new alert names the replacement | A new delivery or poll result | A new rotation, containment first; the replacement is treated as leaked | The source of the repeat leak is fixed in its repository |
| The alert is a test fixture, a false positive or someone else's key | No key the owner controls matches the alert's secret | Nothing is revoked on a guess; automation never resolves the alert as `revoked`; the claim is recorded with who made it | The owner resolves it as `used_in_tests` or `false_positive`; the fixture is fixed in its repository (#460) |
| The affected key cannot be identified | The adapter's sign-in or permission probe fails | The declared credential is treated as affected; the ordered steps go to the owner, containment first | The owner contains by hand; access is granted before the next alert |
| Containment succeeded and the mint failed | The mint step's result | The consumer stays down; the leaked key is never restored; the issue is `P0` and says so | The mint is retried on the next run, or handed to the owner |
| A consumer's copy cannot be written (a local `.env`, a missing permission) | The update step's result per consumer | The other consumers are updated; the alert stays open; the issue names the copy that is left | The owner updates it; verification then finishes the rotation |
| The alert cannot be resolved, or the issue cannot be closed | GitHub refuses the write | The rotation is recorded as done except for that step, which the issue names | The owner resolves the alert as `revoked` |
| The tracking issue asks for more than the rotation (#460 also asks for the fixture change) | Its own acceptance criteria | The rotation posts its result and closes only an issue it can finish; otherwise the issue stays open and names what remains | The remaining work lands in its repository |
| A person resolves the alert while the rotation runs | The alert's state at the resolve step | A matched key is still contained and replaced; the person's resolution is left as it is | The record shows both |
| A token is degraded or expired | Probe rejected twice; consumer `401` | The consumer is paused through its switch; one issue carries the prepared step | The person mints; automation verifies and the switch change is reversed the same way |
| The human step is not done | The issue's age passes the policy's grace | Reminders on the same issue, never a new one; `credential-overdue` trips; the consumer stays paused | The step is done, or Amr retires the credential and its consumer |
| The new value is malformed or under-scoped | `value_prefixes` mismatch, or the capability probe fails | Refused before any target is written; the old credential stays in place | The person supplies another; nothing was split |
| The fan-out is partial | Per-target result; `max_failures` | Hub first; a hub failure aborts the fan-out; a later failure stops the remaining writes and is listed per target | The run is idempotent and is repeated; the ledger shows which targets hold which generation |
| The old credential is revoked before the new one is proved | The order check on the scheduled path | Refused: revocation is the last step unless the trigger is a secret-scanning alert | For a Google key on the scheduled path, `undelete` within 30 days |
| The rotating credential is itself dead | The probe of `FLEET_TOKEN`, or of the organization or provider sign-in, before anything else | Audit only; the issue says which capability is missing; nothing is written | Amr restores that credential first |
| The provider or GitHub is unavailable | A failed call that is not an authentication failure | The run stops before any revocation and changes nothing | The next scheduled run resumes from the ledger |
| A value reaches a log | The Actions masker is registered before first use; a suspected exposure is itself a leak | The exposed credential is treated as leaked | A second rotation, containment first |
| A detection source is off | The watch's switch is off, or secret scanning is disabled on a repository | The credential reads `unknown` and the source is named | The source is turned on by its owner; the protocol does not change a repository setting |
| The loop itself misbehaves | Its own kill switch (`vars.<NAME>_ENABLED`, constitution § 17) | Scheduled runs stop; alerts are still detected and each issue says the rotation is waiting on the switch; a manual run still works | Amr re-enables it |

## 10. Audit trail — `NFR-NEW:credential-rotation-audit`

The ledger stays the record, published through `utilities/publish-data` and never by a bare push. A rotation adds one event.

| Field | Content |
| --- | --- |
| Credential | Name, scope, target (repository, organization or provider), rotation class |
| Trigger | Which one, when, and the evidence as a link: an alert's repository, number and URL, a run URL, an issue. Never the alert's `secret` field |
| Steps | Each of detect, start, identify, contain, mint, validate, distribute, verify, revoke, resolve the alert, close the issue, with its time and its result per target, and whether automation or a person performed it |
| Actor | The workflow run, or the login of the person who confirmed or minted |
| Identity of the credential | The provider's key id or the secret's `updated_at`. Never the key string |
| Outcome | Completed, waiting on a person, refused, failed, with the reason |

What never appears, in the ledger, a log, an issue, a pull request, a commit or a chat: a secret value, a fragment of one, or a hash of one. A value travels by two channels only, an environment variable in and `gh secret set` stdin (or the provider's own client) out, and it is registered with the Actions log masker before anything else happens. It is never placed in a command's arguments or a URL. A leaked value is referred to by its alert, not quoted. The detection poll asks for alerts with `hide_secret=true`, so only the rotation job's matching step ever holds a leaked value, and only in memory. `_data/` is public site data, so the ledger must be safe to publish as it is.

## 11. Prior art and build-vs-adopt

Needs assessment (constitution § 10.8): three credentials are broken at once, each detected by something and repaired by nothing, and Amr's direction in #788 is one routine that keeps tokens current across the fleet. The fleet has a protocol that does this for the hub's fleet-scoped secrets and nothing for the rest.

| Option | Fit |
| --- | --- |
| The weekly credential loop (`token-rotation.yml`, `dash secrets`) | The right contract, order, guardrails and ledger. Wrong reach: two scopes, a schedule only. Extend it |
| `dash keys` and `api-keys.yml` | Assisted rotation that already works: prove, write hub first, record, disable the replaced key. Adopt it as the model for `assisted` |
| `secret-expiry-watch.yml` (ai-world-view, year-of-ai) | The right probe. Its signal ends in an issue nobody acts on. Adopt it as a detection source |
| GitHub secret scanning and push protection | The right leak detector, already required by UPS-OPS-20. Adopt its alerts as the first trigger, read through the alerts API and the `secret_scanning_alert` webhook |
| Google's API Keys API (`gcloud services api-keys`) with Workload Identity Federation | Create, delete and undelete with no stored Google credential. Adopt it for the Google adapter |
| GitHub App installation tokens, OIDC and Workload Identity Federation | Remove the stored secret, so nothing is left to rotate. Prefer them where a consumer can use them; each is its own decision (#761; [AI-INTEGRATION.md](../AI-INTEGRATION.md#keyless-stage-2-workload-identity-federation)) |
| A secrets manager with rotation built in (Google Secret Manager, HashiCorp Vault, Doppler, Infisical) | Built for this. Also a second source of truth beside the token contract and one more service to run, for three credentials. Do not adopt now; revisit if the provider-key count grows |

Decision (proposed): extend the existing protocol. Adopt GitHub's alerts, the repositories' probes and the providers' own APIs as they are. Build only the contract additions, the trigger evaluation, the prepare-and-verify flow and one provider adapter.

## 12. Phases

P0 is this pull request. Later phases are implementation, which constitution § 26 sends to Claude Code after Amr accepts this PRD, as ordered sub-issues of one epic on project #14 (constitution § 10.2). This pull request does not file them.

| Phase | What lands | Acceptance |
| --- | --- | --- |
| P0, this pull request | This sub-PRD, one feature fragment, one roadmap fragment, a pointer in TOKEN-ROTATION.md | `number plan` is clean. Schema, governance and numbering checks pass. No workflow, setting, secret or `_data/fleet.yml` change |
| P1, the alert starts a rotation | The Google key declared in the contract with its alert type; the scheduled poll of the secret-scanning alerts API; an alert for a covered credential opens a rotation by itself (the ledger event, the tracking issue, the ordered steps). No provider or secret write yet, so every step after the start runs through the fallback | The first run opens a rotation for zer0-CMS alert #1 on #460. § 7.1 criteria 1, 2, 5, 6, 7, 9 and 10 hold |
| P2, automated rotation of the Google key | The Google adapter through Workload Identity Federation: identify, contain, mint, update, verify, resolve the alert as `revoked`, close the issue. The 90-day schedule runs on the same adapter | § 7.1 criteria 3, 4 and 8 hold end to end on a test key with no human step. Switched on by a gated pull request (§ 9, § 15) |
| P3, the other credentials and triggers | The PAT and the organization token declared; undeclared secrets reported; the degradation, consumer-failure, expiry and age triggers; prepare, wait and verify | Each of the other two incidents fires its trigger. A person mints once from the prepared step; a bad value is refused before any write |
| P4, the webhook path | `secret_scanning_alert` deliveries forwarded to the hub as `repository_dispatch`; the poll stays as the backstop | An alert starts its rotation within minutes. A dropped delivery is still caught by the poll |
| P5, the console surface | #788's console job and fan-out preview over the same protocol | The console previews the plan by name and applies it through the confirm-gated `secrets-push` path (constitution § 11.8) |

P0 does not start P1. Each later phase ships with a kill switch that a manual dispatch bypasses, a cron that is off the hour and declared in `_data/fleet.yml` `schedule:`, and a `.vscode/launch.json` entry for any new `tools/dash` surface. Verification of P0 is `skip-evidence`: a document and catalog fragments, with nothing a user can exercise ([VERIFICATION.md](../VERIFICATION.md)).

## 13. Cost

| What | Cost |
| --- | --- |
| Trigger evaluation, contract checks, ledger | No model. Deterministic scripts on reads the fleet already schedules |
| The Claude token probe | One single-turn call per probe, already run daily by `secret-expiry-watch.yml`: a fraction of a cent, API-equivalent (estimate) |
| The secret-scanning poll | One read-only list call per fleet repository on each poll |
| The Google and GitHub probes | One read-only API call each |
| Actions minutes | Inside the existing loops' budgets in `_data/fleet.yml` `budget:`. A new scheduled job states its minutes before it is switched on |

No AI agent is added, so nothing is registered in `_data/agents.yml`.

## 14. Open questions

- Is the string behind zer0-CMS alert #1 a fixture, as #460 reads it? Proposed: Amr confirms on #460. If it is, the first rotation the alert starts ends with him resolving the alert as `used_in_tests`, nothing is revoked, and the Google key keeps its 90-day schedule.
- Which Google Cloud project issues the key, is it a standard API key the API Keys API manages, and may the hub hold a Workload Identity Federation pool there? Where else does the value live?
- Does the `ai-world-view` organization carry the hub's Claude credential or its own? Its copy predates the hub's, so a propagation may be all it needs. Which credential may write an organization secret there? `FLEET_TOKEN` is a fine-grained token, and whether it reaches another owner's organization secrets is **TBD**.
- Does `AUTO_PR_GITHUB_TOKEN` stay a rotated PAT, move to a hub-rotated token, or become a GitHub App token? Is `PAT_TOKEN` deleted?
- Where does the alert poll run: the daily fleet pulse, the weekly Scorecard sweep, or a job of its own? Daily means up to a day between a leak and its rotation starting, until the webhook path exists.
- Where does the webhook receiver run, and is it a repository webhook or a GitHub App? The hub has no always-on public endpoint today.
- Can `FLEET_TOKEN` read secret-scanning alerts on every fleet repository, and resolve one? If it cannot resolve, that step falls to the owner.
- Which credentials are contained by `restrict` instead of `revoke`? Proposed: `revoke` unless a consumer cannot be re-keyed in the same run.
- Does a rotation event extend `_data/token_rotation.yml` or get a sibling ledger?
- Are the thresholds right: two probes, three runs, 90, 180 and 14 days?

## 15. Follow-up amendment (not written, not ratified)

This PRD names one constitution change and does not make it. Amr's direction is that a secret-scanning alert starts the rotation and contains the key with no confirm. Constitution § 13.6 starts an external action at the high tier, which waits for his yes, and § 13.7 lowers a tier only after 25 clean approvals. The constitution outranks this PRD (constitution § 3), so the two must agree before the unattended path is switched on.

Proposed slug, for a later pull request: `credential-auto-revoke`. It would say that a secret-scanning alert for a covered credential may contain, replace and resolve without a confirm, for which rotation classes (first: a Google API key through its adapter), what evidence the rotation must record, and that the audit event and a `P0` issue are written when it starts. `Affects` would name § 12.3, § 13.6, `FR-NEW:credential-rotation-alert-trigger`, `NFR-NEW:credential-rotation-failure` and `HUB-NEW:credential-auto-rotation`. Amr may instead rule that § 13 does not govern a deterministic loop; the weekly propagation already writes secrets unattended. Either way the decision is his, in the gated pull request that switches the path on. Until then the rotation still starts by itself on every alert, and its containment is the first prepared step of the fallback in § 7.1.

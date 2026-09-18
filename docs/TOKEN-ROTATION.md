# Token Rotation — the weekly credential loop

The fleet is ~40 repositories, each carrying its own `CLAUDE_CODE_OAUTH_TOKEN` for the seeded `claude.yml` workflow. Until this loop existed, every one of those secrets was placed by hand and never looked at again: nobody knew how old any copy was, a newly-registered repo silently had none, and a credential that had been deleted or had expired announced itself only when somebody's `@claude` mention started failing with a 401.

This is the third of the fleet's reconciliation loops. [`fleet-pulse.yml`](../.github/workflows/fleet-pulse.yml) fixes broken **workflows**; [`issue-pipeline.yml`](../.github/workflows/issue-pipeline.yml) resolves open **issues**; [`token-rotation.yml`](../.github/workflows/token-rotation.yml) keeps **credentials** current. All three read their guardrails from [`_data/fleet.yml`](../_data/fleet.yml).

## TL;DR

```bash
dash secrets plan                    # per-repo credential ages, read-only
dash secrets rotate                  # what the weekly run would do (dry run)
dash secrets rotate --apply          # do it
```

Runs automatically every **Monday 02:07 UTC** (`schedule.rotate_tokens`).

---

## What "rotate" can actually mean here

This is the constraint that shapes everything below, so it goes first.

`claude setup-token` opens a browser, prints a **one-year** credential, and [saves it nowhere](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token). Anthropic documents no programmatic way to re-mint one, and the token is tied to the subscription of whoever ran the command. There is no headless equivalent — so a weekly job cannot, by itself, conjure a new credential the way it could rotate a cloud key.

What a weekly job *can* do splits into three jobs, and it is worth being precise about which of them are unconditional:

| | What it does | Runs unattended? |
| --- | --- | --- |
| **Propagate** | Write the hub's value to every fleet repo whose copy is **missing** or older than `max_age_days` | **Always** |
| **Audit** | Record each repo's secret age, read from GitHub's own `updated_at`, into `_data/token_rotation.yml` | **Always** |
| **Variables** | Bring every repo's canonical repository variables into line with the hub's live values | **Always** |
| **Re-mint** | Obtain a genuinely *new* credential | Only with the optional refresh grant |

Propagate is the one that pays for itself immediately: it is what enrols a newly-registered repo and re-heals a secret somebody deleted, without anyone having to remember to. Audit is what turns "I think the fleet is fine" into a diffable file. Re-mint is the part that needs help.

### The re-mint problem, and the two ways out

**Option A — the OAuth refresh grant (opt-in, unofficial).** The Claude Code CLI's own login flow uses a standard OAuth refresh grant, and provisioning its refresh token on the hub lets the loop mint a fresh access token weekly with no human involved. It is **not documented by Anthropic** and can change without notice, so the loop treats a failed grant as "ask a human", never as an error that costs the propagation pass. Turn it on by setting one hub secret:

```bash
gh secret set CLAUDE_CODE_OAUTH_REFRESH_TOKEN -R bamr87/bamr87
```

The grant returns a *new* refresh token and invalidates the one it was given, so the loop writes the replacement straight back to the hub. If that write fails, the loop says so and falls back to propagate-only rather than stranding itself.

**Option B — Workload Identity Federation (documented, zero credentials).** Anthropic's own answer to "don't store a rotating secret" is [WIF](https://code.claude.com/docs/en/github-actions#set-up-for-an-organization): the action exchanges the workflow's GitHub OIDC token for a short-lived Anthropic token, so there is nothing to rotate at all. It needs `anthropic_federation_rule_id` and `anthropic_organization_id` inputs, `id-token: write`, and — the blocker here — **admin access to an Anthropic organization console**, which a personal account does not have. This is the same constraint that made `_data/fleet.yml` necessary in the first place: no org-level place to centralize, so declare the contract in version control and project it outward with tooling.

If this fleet ever moves onto a Team or Enterprise plan, WIF is strictly better than everything on this page and this loop should shrink to an audit.

**Without either**, the loop still runs every week: it propagates, it audits, and when the credential approaches the end of its year (`lifetime_days - renew_before_days`, currently 335 days) it opens **one** tracking issue asking for a fresh `claude setup-token`. Re-seed it with:

```bash
claude setup-token                                       # mint
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bamr87/bamr87   # seed the hub
```

…and the next weekly run carries it to the whole fleet. You never touch the other 40 repos.

---

---

## The hub is the master copy

Everything this loop writes comes from **bamr87/bamr87's own stored secrets and variables**. `_data/fleet.yml` declares the *contract* — which names exist, which are fleet-scoped, what the policy is — and the hub holds the *values*. One place to fix a value; the loop carries it everywhere.

The two halves reach the fleet by different routes, because GitHub treats them differently:

| | Can the API read the value? | So the source is… | A repo is rewritten when… |
| --- | --- | --- | --- |
| **Secrets** | **No** — never, not even your own | the hub's workflow reading `${{ secrets.X }}` | its copy is missing, older than `max_age_days`, **or older than the hub's copy** |
| **Variables** | **Yes** — name *and* value | the hub's live variables, read through the API | its value **differs** from the hub's |

### "Older than the hub" beats "older than 45 days"

A repo is stale for either of two reasons, and the second matters more.

Age is the weak signal — it's the propagation heartbeat, and all a timestamp can tell you on its own. The strong one is **the repo's copy is older than the hub's**: that says plainly *the hub holds something you do not*, whatever the age. Both timestamps come from the same API call, so it costs nothing to check.

Without that second rule, a human updating the hub's token reaches only the repos that happen to be missing or old — and every repo written inside the heartbeat window keeps the **old** credential. The fleet ends up split across two, which is the exact outcome `hub_first` exists to prevent.

That is not hypothetical. On 2026-08-24 the hub's token was updated at 22:26Z, and three repos — `zer0-mistakes` (1d), `githubai` (4d), `irony-works` (16d) — were all classified *current* by age and would have been skipped, leaving 28 repos on the new token and 3 on the old.

The rule converges rather than churning: once a repo has been written its copy is newer than the hub's, so it goes quiet until the hub changes again. One extra write per repo per hub update, then nothing.

That asymmetry explains the one part of this design that looks inconsistent at first glance. Secrets are audited by **age** because age is the only signal available: nothing can compare a repo's secret to the hub's, so the loop falls back to "how long since anyone wrote it". Variables are compared by **value**, which is strictly better — one that still matches the hub is correct however old it is, and one that has drifted is wrong however fresh.

It also explains a maintenance wart worth knowing about. Because a workflow cannot enumerate `secrets.*`, every fleet-scoped secret has to be named by hand in `token-rotation.yml`'s `env:` block. A secret in the contract but missing from that list can never propagate, and would fail *silently* — the contract would look right while every run wrote nothing. **Drift-gate check (l)** fails CI on exactly that, so the list cannot quietly fall behind the contract.

If the hub lacks a variable the contract declares, the run falls back to the value declared in `fleet.yml` and says so. Set it on the hub to make it authoritative.

## How a run goes

```
secrets    probe secrets:write ─→ survey ages ─→ mint (or seed) ─→ validate shape ─→ hub ─→ fleet ─┐
variables  read the hub's live values ─→ diff each repo ─→ write only what differs ────────────────┴─→ ledger ─→ issue?
```

**Probe before anything else.** Listing a repo's secret *names* is already an admin-level call, so one `gh api repos/{hub}/actions/secrets` answers the only question that matters up front. A PAT that quietly lost `secrets:write` passes a generic validity probe and then 403s on all 41 writes, one at a time. This follows the house rule the issue pipeline learned the hard way: **probe a token, never merely presence-check it**.

**Survey ages from `updated_at`.** The secrets API returns names and timestamps but never values — exactly the shape an audit needs, and the reason no separate rotation clock exists. Each repo lands in one of four states, and `unreachable` is deliberately kept distinct from `missing`: *I cannot see it* and *it is not there* are different findings, and conflating them sends you chasing secrets that are already set.

**Validate the shape before writing anything.** A candidate value must match one of the token's declared `value_prefixes`. The fleet has ~41 call sites reading this one secret; a malformed value breaks all of them simultaneously, and the repo that would have to fix it is the hub, whose own agent needs the same credential. A cheap prefix check against a very expensive failure mode.

**Hub first, always.** If the hub cannot take the new credential, the fleet must not either — the fan-out aborts and everything stays on the credential it already has.

**Who gets written depends on whether the value is new.** A freshly *minted* credential goes to **every reachable repo**: the old one is being replaced, and a fleet split across two credentials is worse than one that was never rotated. A merely *re-seeded* value only fills the gaps — missing and stale copies — so a weekly no-op run writes nothing and leaves 41 audit-log entries unwritten.

---

## Configuration

Everything lives in [`_data/fleet.yml`](../_data/fleet.yml). Per-token policy sits on the contract entry:

```yaml
tokens:
  - name: CLAUDE_CODE_OAUTH_TOKEN
    scope: fleet
    rotation:
      enabled: true
      max_age_days: 45          # propagation heartbeat — rewrite copies older than this
      lifetime_days: 365        # the credential's own life (claude setup-token mints a year)
      renew_before_days: 30     # ask a human this far ahead of that deadline
      value_prefixes: ["sk-ant-oat", "sk-ant-oa"]
      refresh:                  # optional; omit or leave the secret unset for propagate-only
        secret: CLAUDE_CODE_OAUTH_REFRESH_TOKEN
        client_id: …
        endpoints: [platform.claude.com, console.anthropic.com]
```

Fleet-wide guardrails sit in the `rotation:` block: `hub_first`, `only_stale`, `max_repos`, `max_failures`, `fail_on_unreachable`, the tracking-issue settings, and the `ledger` path.

`max_repos: 0` means no cap, on purpose. The point is fleet-wide consistency, and a partial rotation leaves call sites split across two credentials — raise the failure tolerance rather than capping the fan-out.

### Token contract impact

`FLEET_TOKEN` needs **admin (`secrets:write`)** across the fleet on top of its existing scopes. This is the only workflow that requires it. Without it the loop degrades honestly: it reports every repo as unreachable, opens the tracking issue explaining exactly that, and writes nothing.

---

## The ledger

`_data/token_rotation.yml` is committed weekly through [`utilities/publish-data`](../.github/actions/utilities/publish-data/action.yml) — never a bare `git push` to a protected branch, per the house rule that already cost this fleet three weeks of data once.

It records secret **names, ages, and outcomes only**. No credential value is written to it, to any other file, or to a log: the only channel a value travels is an environment variable in and `gh secret set`'s stdin out, and both the access token and the refresh token are registered with the Actions log scrubber before anything else happens.

```yaml
tokens:
  - name: CLAUDE_CODE_OAUTH_TOKEN
    source: refresh          # refresh | seed | none
    minted: true
    oldest_age_days: 91
    attention: []
    counts: {repos: 34, ok: 30, stale: 2, missing: 1, unreachable: 1, written: 34, failed: 0}
    repos:
      - {nwo: bamr87/it-journey, state: ok, age_days: 3, action: written}
```

---

## When it needs you

The loop files **one** issue, updated in place each week rather than forked into a new one every Monday. It is deduped on an exact title, not a body marker — GitHub's issue search does not reliably match text inside an HTML comment.

| Reason | What happened | What to do |
| --- | --- | --- |
| `needs-mint` | The credential is nearing the end of its year and nothing can re-mint it unattended | `claude setup-token`, then seed the hub |
| `needs-seed` | Repos are missing or stale, but no value was available this run | Check `CLAUDE_CODE_OAUTH_TOKEN` is still set on the hub |
| `bad-value` | A candidate did not match the declared shape, so nothing was written | This is the guard working — check what got seeded |
| `write-failures` | Some repos rejected the write | `FLEET_TOKEN` lost `secrets:write` on those repos |
| `refresh-store-failed` | The new refresh token could not be stored | Re-seed `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`; the old one is now spent |

There is a sixth shape the issue can take, and it is deliberately worded to be unmistakable: **the job broke before it could probe for secret access**. Nothing was audited and nothing was written, and — importantly — that is *not* evidence that `FLEET_TOKEN` is missing a scope. The probe's output is empty rather than `false`, and the report says so, because the first scheduled run conflated the two and filed an issue blaming a missing scope for what was actually a workflow that could not load one of its own composite actions. Read the run log and start at the first red step.

---

## Running it by hand

```bash
dash secrets plan                                  # ages only, writes nothing
dash secrets plan --json                           # same, machine-readable
dash secrets rotate                                # dry run: what would be written
dash secrets rotate --apply                        # propagate the hub's value to the gaps
dash secrets rotate --source refresh --apply       # force a re-mint via the OAuth grant
dash secrets rotate --repo bamr87/it-journey --apply
dash secrets rotate --force --apply                # write every reachable repo
dash secrets rotate --no-variables --apply         # secrets only, skip the variable pass
```

A manual `workflow_dispatch` is a **dry run unless you tick `apply`**, so you can see the plan before touching 40 repos. Scheduled runs always apply.

Values are read from the environment and nowhere else:

```bash
CLAUDE_CODE_OAUTH_TOKEN="$(pbpaste)" dash secrets rotate --apply
```

## See also

- [`docs/AI-INTEGRATION.md`](AI-INTEGRATION.md) — the AI layer's auth matrix and Claude call sites
- [`.github/TOKENS.md`](../.github/TOKENS.md) — GitHub token precedence for CI
- [`_data/fleet.yml`](../_data/fleet.yml) — the token contract itself
- [Claude Code authentication](https://code.claude.com/docs/en/authentication) · [GitHub Actions setup](https://code.claude.com/docs/en/github-actions)

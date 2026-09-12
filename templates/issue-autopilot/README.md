# `templates/issue-autopilot/` — the Issue Autopilot kit

The canonical issue-triage engine for the fleet, extracted from the two forks `bamr87/it-journey` and `bamr87/zer0-mistakes` each maintained by hand (FF-0018, [bamr87/bamr87#129](https://github.com/bamr87/bamr87/issues/129)).

**OPT-IN.** Named explicitly via `--artifacts issue-autopilot`; never in the default artifact set. Nothing acquires this loop by being standardized.

## The policy boundary (the point of the kit)

| | kit-owned | repo-owned |
| --- | --- | --- |
| **what** | the engine: classification math, batching, the budget gate, the close gate, the tests | the policy: which issues match which disposition, what the labels are called, how much one run may do, what the resolver may touch, which features are on |
| **where** | `scripts/issues/*.py` | `.issues/config.yml`, `.issues/budget.yml` |
| **who edits it** | the hub, then re-seed | the repo, by hand |
| **refreshed by** | `fanout.sh --upgrade` | never — the kit has no code path that writes any file under `.issues/` |

A bug in the engine is fixed **once**, upstream. A misrouted issue is fixed in **one** repo's `config.yml`. That split is the whole design; the two forks existed because there was nowhere to put the first kind of fix.

> **Do not hand-edit a seeded `scripts/issues/*.py`.** `--upgrade` refreshes a file only when it is byte-identical to the current kit shape or an archived one, so a local edit permanently strands that copy from every future improvement — which is precisely how the forks this kit replaces came to exist. Send engine changes upstream and re-seed.

## What lands in a target repo

| kit file | seeded to | when |
| --- | --- | --- |
| `triage.py` | `scripts/issues/triage.py` | absent, or `--upgrade` on a machine-seeded copy |
| `dispatch.py` | `scripts/issues/dispatch.py` | ” |
| `verify_close.py` | `scripts/issues/verify_close.py` | ” |
| `test_verify_close.py` | `scripts/issues/test_verify_close.py` | ” |
| `test_triage_engine.py` | `scripts/issues/test_triage_engine.py` | ” |
| `SKILL.template.md` | `.claude/skills/issue-triage/SKILL.md` | only when absent |
| `issue-triager.template.md` | `.claude/agents/issue-triager.md` | only when absent |
| `issue-resolver.template.md` | `.claude/agents/issue-resolver.md` | only when absent |
| `issue-verifier.template.md` | `.claude/agents/issue-verifier.md` | only when absent |

Never seeded: **anything under `.issues/`**. A repo adopting the loop from scratch writes its own `config.yml` and `budget.yml`; the skeletons carry `TODO(adopt)` markers pointing at every decision that requires.

The engine test files are seeded alongside the engine deliberately: they are the only thing that will tell an adopting repo that its next `--upgrade` changed behaviour. Wire them into the repo's own CI — both run under bare `python3`, no pytest, no network.

`verify_close.py` and the verifier skeleton are seeded **whether or not** the repo enables the lane, and that is deliberate: the flag is the switch, not the file set. Turning the lane on is then one line of config rather than a second fan-out, and until it is on both files are inert — the engine emits no candidates, so the gate has nothing to select and the agent has nothing to assess (its skeleton opens by saying exactly that).

## The one flag: `features.verify_close`

```yaml
# .issues/config.yml
features:
  verify_close: true    # default: false
```

The verify-and-close lane is the **only** path by which the autopilot ever closes a HUMAN-authored issue: the read-only `issue-verifier` writes a verdict, and `verify_close.py` acts on it only when the verdict is `resolved` with `high` confidence *and* the default branch's full CI suite is green (it fails CLOSED on any API error, pending run, or failure).

It is therefore **off unless a repo asks for it in writing**, and off means invisible: with the flag absent the engine emits no `verify_candidate` key on any record, no `verify_candidates` count, and no status line. A repo that has never run the lane gets a `plan.json` byte-identical to its pre-kit output — not merely equivalent. Only a real YAML `true` enables it; a truthy string is treated as a typo, and the safe reading of a typo on an issue-closing switch is "off".

Everything else the two forks had diverged on is **unconditional**, because it is inert unless a repo's config actually uses it:

| converged feature | flagged? | why |
| --- | --- | --- |
| verify-and-close lane | **yes** — `features.verify_close` | closes human issues; changes behaviour on adoption |
| `any_of` OR-groups in a `match` | no | a config with no `any_of` key can never trigger it |
| `action: skip` → the "Left alone (protected)" batch | no | a config with no `skip` disposition produces no such batch |
| batching | n/a | **present in both forks already** — the founding issue's claim that it was it-journey-exclusive was wrong. Nothing to reconcile |

## Adoption

Each repo adopts in **one PR in its own repo** (never bundled — see [`SUBMODULES.md`](../../SUBMODULES.md)):

```bash
# dry run first — the default
tools/fanout.sh --kit standardize --artifacts issue-autopilot --upgrade --target <name>
tools/fanout.sh --kit standardize --artifacts issue-autopilot --upgrade --target <name> --apply
```

Both forks' current engine bytes are in `archive/`, so `--upgrade` recognizes them as machine seeds and converts them in place rather than reporting them as hand-modified.

| repo | config change needed | why |
| --- | --- | --- |
| `it-journey` | **none** | the lane defaults off, which is what it does today |
| `zer0-mistakes` | add `features: {verify_close: true}` | it runs the lane today; the kit will not write its config, by design |

Both repos already have hand-authored skill and agent files, so the four skeletons are skipped by the additive-only guard. They exist for the next repo.

## Parity is tested, not asserted

`test_triage_engine.py` imports **both archived pre-kit engines** and runs them beside the canonical one over the same issue fixtures, using each repo's real disposition rules, then asserts the resulting `plan.json` **and** the rendered worklist Markdown are equal:

- lane OFF → canonical `==` the it-journey fork
- lane ON → canonical `==` the zer0-mistakes fork

```bash
python3 templates/issue-autopilot/test_triage_engine.py
python3 templates/issue-autopilot/test_verify_close.py
```

This is why `archive/` is load-bearing twice over: it is the byte-identity basis for `--upgrade` *and* the fixture set that makes "behaviour parity" a check rather than a claim. Deleting an archived engine silently removes a proof.

## Measured divergence at extraction

Full diff, not an estimate — see `VERSION` for the detail.

| file | it-journey | zer0-mistakes | divergence |
| --- | ---: | ---: | --- |
| `dispatch.py` | 17883 B | 17883 B | **byte-identical** |
| `triage.py` | 37571 B | 41285 B | 78 added / 8 changed lines, all on the zer0 side, in three features |
| `verify_close.py` | — | 7107 B | zer0 only |
| `test_verify_close.py` | — | 4130 B | zer0 only |

## Related

- [`docs/ISSUE-PIPELINE.md`](../../docs/ISSUE-PIPELINE.md) — the hub's own three-tier issue loop. Different thing: that one works the fleet's issues from the hub; this kit is the per-repo loop each submodule runs on its own queue.
- [`docs/HARNESS-OPS.md`](../../docs/HARNESS-OPS.md) — how kits are deployed and upgraded across the fleet.
- [`templates/agent-context/VERSION`](../agent-context/VERSION) — the `.claude/` fan-out position this kit is a sanctioned exception to.

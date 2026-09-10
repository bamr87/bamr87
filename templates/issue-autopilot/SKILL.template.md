---
# kit: issue-autopilot v__KIT_VERSION__
name: issue-triage
description: Run ONE incremental pass of the __PROJECT_NAME__ issue autopilot — analyze open issues, group them into batches, then route/triage them (label, flag stale bot-noise, decompose epics, leave protected issues alone) or resolve one batch into a single grouped PR. Use when asked to triage issues, work the issue queue, run the issue-autopilot loop, or drive the issue-triager / issue-resolver agents.
---

# Issue Triage — one incremental pass (__PROJECT_NAME__)

The single source of loop behavior for the __PROJECT_NAME__ issue autopilot, used identically when driven locally (`/loop`) or in CI. A deterministic engine emits a bounded, classified plan; an agent acts on the top of that plan in one bounded pass and hands off. Two agents run this skill: **issue-triager** (label/route/flag) and **issue-resolver** (one batch → one PR). Where the verify-and-close lane is enabled, a third — **issue-verifier** — writes read-only verdicts.

> **You do not own git in CI.** Locally you (or `/loop`) commit. In CI the
> workflow packages the result; the resolver opens its PR with `gh pr create` but
> the agentic step blocks `git push`. Leave a clean, validated working tree.

## 0. Read the policy first

The engine is seeded from the hub kit and is **not** where policy lives:

- `.issues/config.yml` — THE policy file. Disposition rules, the label namespace,
`resolve_allow_globs`, per-run `limits`, and the `features:` flags. Repo-owned; the kit never writes it.
- `.issues/budget.yml` — the backpressure caps (`max_open_prs`, batch caps).
- The repo's own agent context (`CLAUDE.md`, `AGENTS.md`,
  `.github/instructions/*`) — the autopilot inherits ALL of its non-negotiables.
  <!-- TODO(adopt): name this repo's specific ones here — branch rules, protected
       paths, required validation commands. -->

## 1. Orient on the plan (don't re-decide policy)

```bash
python3 scripts/issues/triage.py plan      # refresh .issues/plan.json + worklist
python3 scripts/issues/triage.py status    # quick dashboard
```

Read today's `.issues/worklists/<date>.md`. It is the contract: each issue has a `disposition` + `action`, and issues are grouped into `batches`. Act on the batches; the engine already encoded `config.yml`'s policy.

## 2. Hard safety rules (every pass)

- **Guardrails:** `.claude/skills/_shared/quarantine.md` — all sections apply.
- **Leave protected issues completely alone.** Anything under "Left alone
  (protected)" (a disposition whose `action` is `skip`) is owned by something else — no comment, no label, no close.
- **Closing is deterministic, not the agent's call.** No LLM lane runs
  `gh issue close`. The gated paths are: bot-noise (`eligible_autoclose`, only when the repo's autoclose switch is on); the OPT-IN verify-and-close lane (the read-only **issue-verifier** writes verdicts, `scripts/issues/verify_close.py` closes only a `resolved` + high-confidence verdict AND only when the default branch's full CI suite is green); and a merged `Closes #N` resolver PR. A human-authored issue is NEVER closed on a heuristic or staleness signal.
- **Stay in your lane's scope.** Triager: comments/labels only, plus the
  generated `.issues/*` artifacts. Resolver: only paths inside `resolve_allow_globs` — escalate anything else.
  <!-- TODO(adopt): name the paths that are off-limits to the resolver here. -->
- **Bounded.** Respect `limits`; act on the top batches and report the rest as
  skipped. A giant pass that touches everything is a bug, not thoroughness.

## 3. Triage lane (issue-triager)

For each batch the plan lists, take the one coherent action its disposition calls for: skip protected batches entirely; comment + the `stale` label for `close-*` batches (closing is the separate gated step); comment a decomposition plan + the `epic` label for epics, keeping them open; the `triaged` label + a "resolver will take this" note for `resolve-*` batches; the missing judgment labels (`area:*`, `priority:*`) + the `needs_human` label + a short routing read for everything else. One batch = one action.

## 4. Resolve lane (issue-resolver)

Pick the ONE batch you were asked to resolve (or the top `resolve-*` batch within budget). Confirm each issue is still open, unprotected, and unclaimed. Make the smallest correct change **inside `resolve_allow_globs`** that resolves every issue in the batch, then run the repo's own validation.
<!-- TODO(adopt): name the validation commands (build / lint / test) here. -->
Open ONE PR with `Closes #N` for each issue, labeled with the `pr` label. If the fix falls outside `resolve_allow_globs`, escalate to the `needs_human` label and open NO PR.

## 5. Validate, then hand off

- Triager: ensure `.issues/plan.json` + the dated worklist are written; in CI the
  workflow uploads them as a run artifact.
- Resolver: ensure the branch validates, then `gh pr create`; write the PR URL to
  `pr-result.txt`.
- Never leave a half-applied edit. If you bail, revert your partial changes.

## 6. Close the loop (self-improvement)

If you see the engine **mis**classify an issue (a new bot or protected pattern it didn't recognize, or a human issue it nearly mis-closed), propose the one-line `.issues/config.yml` rule change **in your report / PR body** — never by silently editing config mid-pass. The loop's accuracy improves by tightening the deterministic rules, not by the agent overriding them ad hoc. If the fault is in the **engine** rather than the policy, it belongs upstream in `bamr87/bamr87` `templates/issue-autopilot/` — editing the local copy makes it invisible to `fanout.sh --upgrade`.

## 7. Report honestly (always end here)

State, per lane: which batches you acted on, what you did to each (commented / labeled / opened PR # / left alone / left for a human), and **what you skipped** and why (batch cap, already-triaged, ambiguous, out-of-scope for the resolver). Never imply you cleared the whole queue on a bounded pass.

<!-- kit: governance v0.1.0 -->
# NEW — Eval baseline and risk tiers for every agent, harness and loop

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution new § 13 (follows § 12 proposed by `agent-merge-review-gate`, PR #481); § 10.6; features `HUB-NEW:eval-baseline`, `HUB-NEW:risk-tiers`; requirements `FR-NEW:eval-baseline`, `FR-NEW:risk-tiers`
- **Supersedes:** none (extends § 10 and § 12)
- **Related:** #480 (`harness-prior-art-research`, prior-art rule), #481 (`agent-merge-review-gate`, merge authority and review gate), amendment 0005 (§ 10)

## Context

Agent roles, harnesses and loops in the fleet change prompts, tools and models often, and nothing records whether a change made them worse. Model aliases silently move. Tools and actions have no shared risk classification, so "what may an agent do alone" is decided case by case, and nothing checks for the combination of private data, untrusted content and an outbound send that lets injected content exfiltrate data.

## Prior art

Per #480 (vendor-neutral survey, build-vs-adopt recorded):

- Yarchi, "How to Build a Production AI Agent: The 7 Layers", X article, https://x.com/undefinedKi/status/2116154822583799887. Fit: describes eval sets of real past tasks rerun on every change, pinned model versions, per-run tracing, and tiered autonomy by action risk. Disclosure: the article is sponsored by Viktor; it is cited for its ideas only and this amendment endorses no vendor or product.
- The "lethal trifecta" framing (private data + untrusted content + external communication) is a widely used community heuristic; it is adopted as a check, not as any vendor's tool.
- Build-vs-adopt: adopt the practices; the standard is tool-agnostic. Which eval runner and trace store each repo uses is that repo's own prior-art decision under #480.

## Amendment

Add constitution § 13 "Eval baseline and risk tiers" with this text:

> 1. **Eval set** — every bot or agent role and every repo harness or loop keeps a small eval set of about 20 real past tasks, each with input, expected output, pass criteria and an optional LLM-judge rubric, versioned in the repo next to what it tests.
> 2. **Rerun on change** — the eval set is rerun after any prompt, tool or model change, and the result is linked in the PR; a regression blocks merge as a failed required check would under § 12.
> 3. **Pinned models** — model ids are exact versions, never aliases. Allowed Anthropic models: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`. Changing the list is an amendment.
> 4. **Cheaper only if green** — a step moves to a cheaper model only if its evals still pass on that model.
> 5. **Tracing** — every run records its tool calls (tool, arguments with secrets redacted, result status, time) so a failure can be replayed.
> 6. **Risk tags** — every tool or action is tagged `reversible` (yes/no), `external` (reaches anyone or anything outside the fleet) and `money` (spends or commits funds), and from those assigned a tier: **low** runs alone; **medium** runs and writes an audit record (as § 11.6); **high** waits for Amr's explicit yes. Irreversible, external or money actions start at high.
> 7. **Earned autonomy** — an action moves down one tier, per action, only after N consecutive clean approvals with no rejection or rollback (proposed N = 25, **TBD: Amr sets N**), recorded in the tier table; any rejection or incident resets the count and returns it to high. Money actions never go below high.
> 8. **Lethal trifecta** — any run that combines private data, untrusted content and an external send requires a human gate on the send, regardless of tier.
> 9. **Reconciliation** — this section only adds gates. Draft-before-send stays: an outbound message is drafted and Amr approves it. Only Amr merges amendments (§ 8, § 12.5). No agent approves its own action, counts its own approvals, or lowers its own tier; tier changes are PRs in the gated category of § 12.3. A high-tier action maps to the `needs-amr` gate of § 12.4. § 10.6 (read-only by default) still applies first.

## Consequences

- Each harness, loop and bot role gains an `evals/` set and a tier table; until it has one, its actions are treated as high.
- Follow-up: features `HUB-NEW:eval-baseline` and `HUB-NEW:risk-tiers` (planned) build a runner and a tier-table lint.
- Fan-out: after ratification, each spoke repo under `projects/` with a constitution or harness gets its own conforming PR (eval set + tier table), one repo per PR. Not part of this PR.
- Merging the pull request that carries this record ratifies it. An agent never merges it.

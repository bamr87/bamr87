# ADR 0017 — ADR 0008 withdrawn: typed decisions go back to direction, and its cost levers join the Workflow Studio

- **Status**: proposed
- **Date**: 2026-11-25
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-25: consolidate the ADRs, starting by superseding ADR 0008 and moving its cost levers into ADR 0007); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: [ADR 0008](0008-typed-decisions-as-pipeline-gates.md) (superseded here), [ADR 0007](0007-workflow-studio.md) (which gains the cost levers), [ADR 0002](0002-agent-step-specs-and-local-runner.md) (the local loop runner), [ADR 0009](0009-agentic-efficacy-model.md) and [ADR 0010](0010-fleet-graph-and-outcome-learning.md) (the outcome tracking and the advice flow control reads), [docs/prd/AGENTIC-SDLC.md](../prd/AGENTIC-SDLC.md), [the typed-decision research brief of 2026-11-21](../research/2026-11-21-typed-decision-layer-brief.md), PRD FR86–FR88 and NFR17, constitution § 10.9 (local first), § 11 (write-back), § 12.3 (gated changes), § 28.5 (who owns direction), epic bamr87/bamr87#737
- **Tracking**: #739

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

ADR 0008 was accepted on 2026-11-06 (#745). It adopted a design note's four layers and chose a hosted decision model, TypeSafe Jev, behind one composite action, with a decision lockfile, fixed confidence thresholds, traces and replay, a typed pre-classification in front of the doctor and the issue pipeline, a patch screen, and test selection and matrix pruning promoted from shadow. Its first phase, A0, was an offline evaluation that could still reject the model.

Nineteen days later:

- **Nothing is built.** There is no `_data/decisions.yml`, no `.github/actions/typed-decision/`, no `tools/jev/decisions.py`, no eval set under `tools/jev/evals/decisions/`, and none of the five cost-lever rules. Every phase of epic #737 is open, and A0 (#738) carries `agent:hold` and `needs-amr`.
- **The research went the other way on the model.** The brief of 2026-11-21 "does not recommend buying TypeSafe's Jev model". It recommends open-source patterns that sit behind the existing loop runner: two confidence thresholds with abstention between them, typed questions with an `other` escape, shadow labels promoted one band at a time, and a cascade from code to a cheap classifier to a stronger model to a person. ADR 0008's own survey found only the model and its SDK on 2026-11-06; the four ecosystem pieces it planned around were not found.
- **The fleet's AI posture moved.** Claude runs on the operator's OAuth login, the API key has been disabled since 2026-11-15 (`_data/fleet.yml` `ai_auth:`), and AI work runs in a local session when one can do the job (§ 10.9, amendment 0027). ADR 0008 adds a vendor and a credential to the token contract and asks the model from a hosted runner.
- **Its names are taken.** The decision index (`tools/dash decisions`, `/api/decisions`, `_data/fleet.yml` `decisions:`) now holds the key under which ADR 0008's plan put its executor and its promotions (`decisions.executor`, `decisions.promoted`).
- **Its money case was weak by its own account.** Its alternatives record that Actions cost is $0 net on the billing meter.

An accepted record is read as the plan, so while ADR 0008 stands a reader takes a vendor, a lockfile name and fixed thresholds as decided. Two of its phases are not about typed decisions: A1 (#739), the cost levers as atlas rules, needs no model, and A7 (#748), flow control, is what ADR 0010's advice is written for.

## Decision

1. **ADR 0008 is superseded.** None of its design is in effect, and nothing is to be built to it: not the decision model or its credential, the `typed-decision` action, `_data/decisions.yml`, the 0.85 and 0.95 thresholds, decision traces and replay, the pre-classification and patch screen in front of the doctor and the issue pipeline, or the trim and verify loops. Its header says `superseded` and links here.
2. **The cost levers move to ADR 0007.** ADR 0008's decision 4 (five atlas rules at `warn`, each naming its incident, with the billing meter as the only source of minutes) is the mechanism of ADR 0007's decision 8, so it becomes ADR 0007's decision 10, in a section this change adds. #739 delivers it under ADR 0007's epic (#719) instead of #737.
3. **Flow control is not withdrawn.** A7 (#748) is about work-in-process limits and loop balance, not typed decisions, and ADR 0010 names it as the reader of its advice. It stays open and moves under ADR 0009's epic (#773), beside the outcome tracking (E3, #777) it depends on.
4. **What ADR 0008 restated stays where it already lives.** Actions stays the substrate for the gates on a pull request, so amendment 0027's note on ADR 0008 still holds for them; branch protection, required checks and the § 12 gate stay the guardrails; agents keep the permissions the token contract gives them; and no repository is created for any of this (§ 22). None of these depended on ADR 0008.
5. **Typed decisions go back to direction.** FR86–FR88 and NFR17 stay as written: they belong to the PRD, and revising them is the direction owners' work (§ 28.5), not this record's. A design that meets them is a new ADR. It starts from the 2026-11-21 brief, runs behind the local loop runner (ADR 0002) before any CI gate, adds no vendor credential, takes a name the decision index does not hold, and proves its accuracy on this fleet's own history before anything is trimmed or gated. The constitution's clause on local models (a model on an enrolled node may run "a typed decision" only when pinned and evaluated) stays as written and governs such a design when one exists.
6. **The issue changes are the maintainer's.** After the merge the plan is: #739 moves under #719 and #748 under #773, then #737 and the phases that served only the withdrawn design (#738, #740–#744) close as not planned. Those are GitHub writes under § 11, planned and confirmed by the maintainer; this change makes none of them.

## Consequences

**Positive**

- The index stops listing as accepted a plan nobody is building, and the vendor, the lockfile name and the thresholds stop reading as decided.
- The one part that needs no model, the cost levers, has a single home beside the atlas's other planned rules, under the epic that builds the atlas.
- Flow control keeps a parent beside the outcome tracking it reads.
- A future typed-decision design starts from the research and the fleet's current posture rather than from a record that predates both.

**Negative**

- Until their owners revise them, FR86–FR88 and NFR17, feature HUB-088 (`planned`), roadmap entry FF-0043 (`proposed`), [docs/prd/AGENTIC-SDLC.md](../prd/AGENTIC-SDLC.md) (which still says "Draft / proposed") and the local typed decisions in [docs/ONPREM-COMPUTE.md](../ONPREM-COMPUTE.md) phase P6 describe the withdrawn design. They are direction (§ 28.5), so this record names them and leaves them.
- Withdrawing a record accepted 19 days ago is churn in the record itself. The alternative is a plan that reads as live and is not.
- Until a new design is accepted, no model's answer may skip CI work or lower a gate. Nothing did, because nothing was built.

## Alternatives considered

- **Leave ADR 0008 accepted and wait for A0.** A0 has been on hold since 2026-11-06, the research it would test argues against the model it names, and while it waits the record reads as the plan.
- **Mark ADR 0008 `deprecated` with no successor.** Simpler, but the cost levers and flow control would lose their place, and a deprecation has no section for the reasons and no forward link.
- **Rewrite ADR 0008 around the brief's patterns.** An accepted record is never rewritten ([docs/adr/README.md](README.md)), and the redesign has not been done: the brief is a survey, not a decision.
- **Write the new typed-decision design now and supersede ADR 0008 with it.** It would decide ahead of the evidence again, which is how ADR 0008 came to be withdrawn, and the requirements it would serve are direction's to revise first (§ 28.5).
- **A standalone ADR for the cost levers.** ADR 0007's decision 8 already lists the atlas rules to come, and one list is the point of consolidating.

## Supersedes / Superseded by

- Supersedes: [ADR 0008](0008-typed-decisions-as-pipeline-gates.md)
- Superseded by: none

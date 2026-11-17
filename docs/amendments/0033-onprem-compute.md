<!-- kit: governance v0.1.0 -->
# 0033 — On-premise compute: an enrolled node runs local sessions and local models, and a self-hosted runner only behind fences

- **Status:** proposed
- **Number:** 0033
- **Date:** 2026-11-15
- **Proposed by:** agent (Claude Opus 5.5, in a Claude Code session at Amr's request on 2026-11-15: "Add a plan to incorporate the new machine build that can run local LLMs and Claude Code sessions for other processing on-premise for zero cost … if it changes standards or principles, draft an amendment for Amr to ratify.")
- **Ratified by:** (leave blank until merged)
- **Affects:** constitution new § 30 (follows § 29 `agentic-efficacy-contract`; renumber to the next free section if another amendment claims 30 first); § 10.5, § 10.7, § 10.9, § 13.3–§ 13.4, § 13.6, § 17 and § 29 by reference; `_data/fleet.yml` `nodes:` and `ai_models.allowed` (a `local` provider, follow-up); feature `HUB-116`; requirements `FR132`, `FR133`, `NFR32`
- **Supersedes:** none. It narrows, for an enrolled on-premise node only, the ruling in [ADR 0002](../../adr/0002-agent-step-specs-and-local-runner.md) and #484 that ruled out a self-hosted runner; the ruling stands for the Mac
- **Related:** [docs/ONPREM-COMPUTE.md](../../ONPREM-COMPUTE.md) (the plan), [ADR 0003](../../adr/0003-fleet-platform-nodes-iac-and-scale-out.md) and [PLATFORM.md](../../PLATFORM.md) (nodes), [0027](../0027-local-first-ai.md) (local first), [WEEKLY.md](../../WEEKLY.md), [WEEKLY-CLOSEOUT.md](../../WEEKLY-CLOSEOUT.md), bamr87/bashos#99, bamr87/bashos#100

## Context

Amr has a new on-premise machine: a 16-core Ryzen 9 9950X3D2, 64 GB of RAM, a Radeon RX 9070 XT with 16 GB of VRAM and 12 TB of local storage. It can serve local LLMs and host Claude Code sessions, which no fleet machine could do before. The Mac is protected by § 10.5 and sleeps; forge has no usable GPU.

Four things the constitution does not yet say make that machine harder to use well than it should be:

1. **§ 10.9 says "a local session" without saying where.** Its examples (`tools/dash loop`, `tools/dash conflicts`) all ran on the maintainer's workstation. Nothing says a session on an enrolled node is the same kind of thing, held to the same switches, caps and ledger.
2. **§ 13.3 pins models from `ai_models.allowed`, which lists Anthropic models only.** A local model has no place on the list, so it is either forbidden or unregulated. Neither is right: § 13.4 already says when a cheaper model may take a step (when its evals still pass), and a local model is the cheapest there is.
3. **§ 10.7 asks for honest cost, but "on-premise" invites the word "free".** Local inference spends no API money, but a Claude Code session on the node still draws on the subscription, and the machine draws power.
4. **A self-hosted runner was ruled out** by ADR 0002 and #484, for the Mac and on public repositories. A runner on a separate machine is a different risk, but the public-repository risk remains: a fork's pull request can run code on it. If one is ever wanted, the fences must be in the constitution before the runner exists, not after.

Prior art (§ 10.8) is recorded in the plan's design record ([ONPREM-COMPUTE.md, section 10](../../ONPREM-COMPUTE.md#10-design-record-constitution--108)): Ollama for serving, systemd timers as the Linux twin of the LaunchAgents, `oneos-remote` for driven sessions, and GitHub's own guidance against self-hosted runners on public repositories.

## Amendment

Add to the constitution:

> ## 30. On-premise compute
>
> 1. **Enrolled nodes** — an on-premise machine does fleet work only as a node declared in `_data/fleet.yml` `nodes:`, `enabled: false` until its deploy step. Every step that changes it is a deploy (§ 10.5, § 13.6), planned before it is applied, and it is reached only over SSH with keys. Its services bind its loopback, and nothing it runs listens on the LAN without a token.
> 2. **A local session may run on a node** — a local session under § 10.9 may run on an enrolled node, from the node's own git checkout, through the same entry points, kill switches (§ 17), caps, AI ledger and sandbox as on the maintainer's workstation, and every scheduled job there is registered as an agent (§ 29). Housekeeping on a node acts only on that node's own checkouts, worktrees, clones and session state. It reaches another machine's only when the maintainer opts that machine in, and it never ends a running session. The fleet never needs a node to be up: work that prefers it falls back or waits, and says which.
> 3. **Local models are a tier under § 13** — a model served on an enrolled node may run a step, a JEV tier, a typed decision or an embedding job only when it is pinned by exact tag and digest under a `local` provider in `ai_models.allowed` (§ 13.3) and the step's eval set passes on it (§ 13.4). It receives no secret, runs with the step's own tool allowlist, and never becomes the default model of a session. Claude Code with an allowed Anthropic model stays the executor for implementation and review (§ 26).
> 4. **Honest on-premise cost** — on-premise work is reported as what it is (§ 10.7): $0 metered API spend for local-model runs, and no hosted runner minutes for work that moves onto a node; a Claude Code session on a node draws on the same subscription as anywhere else and stays API-equivalent (estimate); electricity is a real cost, measured and stated as energy beside the run. Local-model runs carry their own cost source in the ledger and are never summed with API figures. Nothing is called free that is not.
> 5. **A self-hosted runner only behind fences** — a self-hosted GitHub Actions runner on an enrolled node is allowed only when all of these hold: (a) only `schedule` and `workflow_dispatch` workflows on the default branch target its labels, and a drift check fails any workflow reachable from `pull_request`, `pull_request_target`, `issue_comment`, `workflow_run` or another event a fork can raise that does; (b) the repository requires approval for fork pull-request workflows from all external contributors, a setting only the maintainer changes, and approving such a run is a review of every workflow file it changes; (c) the runner is ephemeral, runs as its own unprivileged user in a container or VM, and cannot read the maintainer's home, keys, Claude credentials or `.env`; (d) it has a kill switch (§ 17), is registered as an agent (§ 29), and stays off until the maintainer registers it. A runner on the maintainer's workstation stays ruled out (ADR 0002).

## Consequences

- Nothing changes on any machine when this merges. Each phase of [ONPREM-COMPUTE.md](../../ONPREM-COMPUTE.md#9-rollout) is its own pull request or deploy step, and Amr approves each deploy.
- The node joins `nodes:` disabled (phase 2). `tools/fleetcore/nodes.py` and its tests take the new host as they took forge.
- `ai_models.allowed` gains a `local` provider when the first local model is pinned (phase 3). That edit is gated (§ 13.3, § 12.3), and `test_ai_budget.py` and the ledger learn the `local` cost source with it.
- The Mac's installers gain a `--systemd` mode for the node (phase 4). Each timer is an agent under § 29 and a loop under § 17.
- The console's weekly lanes get a local adapter on the node (phase 5), which closes their `R6:no-local-entry` gap without a runner. A runner arrives, if ever, only with an ADR that amends ADR 0002 and with every fence of item 5 in place first.
- AGENTS.md gains a standing-rule line pointing at § 30 after ratification; that follow-up is not in this pull request.
- Merging the pull request that carries this record ratifies it. An agent never merges it (§ 8).

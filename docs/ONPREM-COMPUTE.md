# On-premise compute

> A plan to enrol Amr's new on-premise machine as a fleet node that serves local LLMs, hosts Claude Code sessions, takes over the local housekeeping a GitHub-hosted runner cannot see, and moves work off metered APIs and hosted minutes. Proposed; nothing here is deployed.

| | |
| --- | --- |
| **Status** | Proposed plan. Nothing on any machine changes until Amr approves each deploy step (constitution § 10.5) |
| **Feature** | `HUB-NEW:onprem-compute` ([`features/features.d/onprem-compute.yml`](../features/features.d/onprem-compute.yml)), numbered at merge |
| **Requirements** | Existing: FR64 (node placement and deploy steps), FR56 and FR65 (local loop runs), FR130 (the weekend routine), FR131 (the console's weekly lanes). Proposed in the feature fragment: `FR-NEW:onprem-session-host`, `FR-NEW:onprem-local-inference`, `NFR-NEW:onprem-runner-isolation` |
| **Amendment** | Proposed constitution § 30, [`docs/amendments/proposed/onprem-compute.md`](amendments/proposed/onprem-compute.md); Amr ratifies it by merging |
| **Builds on** | [PLATFORM.md](PLATFORM.md) and [ADR 0003](adr/0003-fleet-platform-nodes-iac-and-scale-out.md) (nodes), [FORGE-HOST.md](FORGE-HOST.md), [WEEKLY.md](WEEKLY.md) and [WEEKLY-CLOSEOUT.md](WEEKLY-CLOSEOUT.md) (the weekend), [JEV.md](JEV.md) (local runs and tiers), [AI-INTEGRATION.md](AI-INTEGRATION.md) (auth and cost) |
| **Related work** | bashOS [#100](https://github.com/bamr87/bashos/pull/100) (Amrchy, and the `x870e-dark-hero` machine profile), [#99](https://github.com/bamr87/bashos/pull/99) (one-os, `oneos-remote`), [#103](https://github.com/bamr87/bashos/pull/103) (one-USB) |

## 1. The machine

Amr picked the build up on 2026-11-10 and added the cooler on 2026-11-11.

| Part | Component | What it means for the fleet |
| --- | --- | --- |
| CPU | AMD Ryzen 9 9950X3D2 Dual Edition: Zen 5, 16 cores and 32 threads, 3D V-Cache on both dies | Several Claude Code sessions, test suites and native amd64 image builds at once, and CPU-side layers for models that do not fit the GPU |
| Board | ASUS ROG Crosshair X870E Dark Hero (AM5) | Already the first one-os machine profile: `bashos one-os machine check x870e-dark-hero --system bashos` (bashOS #100) |
| Memory | Corsair Vengeance RGB 64 GB (2 × 32 GB) DDR5-6000 | Room for containers, sandboxes and model weights spilled out of VRAM |
| GPU | ASUS Radeon RX 9070 XT Prime White OC, 16 GB VRAM, RDNA 4 (`gfx1201`) | Local inference. It is AMD, so ROCm or Vulkan, **not CUDA** ([section 3](#3-local-llms)) |
| Fast disk | WD Black SN8100 2 TB, PCIe Gen5 NVMe | OS, the hub checkout, container images and the model store |
| Scratch disk | WD Blue SA510 2 TB SATA SSD | Worktrees, loop sandboxes, clones and build caches, all under one root that housekeeping owns ([section 6](#6-the-housekeeping-a-hosted-runner-cannot-do)) |
| Bulk disk | WD Black 8 TB HDD | The local archive: weekly git bundles, snapshots and retired session transcripts. It is in the same box, so it is **not** an off-box `backup:` under FR64's durable-data rule |
| Case, power, cooling | ASUS ProArt PA602 Wood; ASUS ROG Strix Platinum White 1000 W; ASUS Ryuo IV 360 LCD | Headroom for sustained CPU and GPU load at once |

### Its role

The fleet has two machines today ([PLATFORM.md](PLATFORM.md)). The **Mac is the edge**: the editor, the working tree, the browser and Claude Code. **forge is a workload node**: an i7-3820 with 32 GB and a GTX 660 on nouveau, which carries the planes the Mac cannot afford. Neither can run a useful local model, and neither is a good place to leave long Claude Code sessions running.

The new machine joins as a **second workload node with a GPU**, and as a **session host**. This plan calls it `onprem` until Amr names the host; the name is an open question ([section 11](#11-open-questions-for-amr)). It is additive: forge keeps what ADR 0003 placed on it until Amr decides otherwise.

```text
        _data/fleet.yml nodes:  (placement; each node enabled: false until its deploy step)
                                          │
 ┌───────── Mac · EDGE ──────────┐     ┌──┴── onprem · WORKLOAD + SESSIONS ──────┐   ┌───── forge · WORKLOAD ─────┐
 │ editor · browser              │     │ Ollama (Vulkan or ROCm) on loopback     │   │ the planes (ADR 0003 P3)   │
 │ interactive Claude Code       │     │ Claude Code in tmux: ssh, oneos-remote  │   │ bashos-harness console     │
 │ console :4001                 │     │ systemd timers: tools/dash weekly,      │   └────────────────────────────┘
 │ weekly LaunchAgent for its    │     │   loop, conflicts, refine reflect       │
 │   own worktrees and sessions  │     │ own checkout, scratch, archive disk     │
 │ node-link (SSH, forwarding)   │═══▶ │ optional (phase 5): ephemeral runner    │
 └───────────────────────────────┘     └─────────────────────────────────────────┘
```

## 2. Operating system and access

**OS.** The intended OS is bashOS on Amrchy, the Arch-based Omarchy fork that bashOS #100 folds in; `bashos os install` also supports Debian 13, which forge runs. One fact weighs on that choice: AMD's ROCm support matrix lists only Ubuntu and RHEL for the Radeon RX 9000 series, so on Amrchy ROCm runs from a container or not at all ([section 3](#3-local-llms)). Vulkan works on either.

**Access.** SSH with keys only, the same as forge: SSH is the only API to a workload node. The Mac gets a `~/.ssh/config` alias, and services on the node bind its loopback and are reached through the existing forwarding-only link (`tools/dash node key`). Nothing new listens on the LAN. Reaching it off the LAN waits for ADR 0003's overlay-network decision (Tailscale, Headscale or WireGuard).

**Users.** Amr's own login is for interactive sessions. Scheduled work runs as a separate unprivileged user, so a loop's agent can never read Amr's interactive credentials, SSH keys or `.env`.

## 3. Local LLMs

### The runtime

| Path | How | Fit |
| --- | --- | --- |
| **Vulkan** (Mesa RADV) | llama.cpp's Vulkan backend, or Ollama's | Works on any distro, Amrchy included, with no ROCm install. **The baseline** |
| **ROCm 7.x** | AMD's official stack; RDNA 4 (`gfx1201`) is supported on Linux | AMD lists Ubuntu and RHEL only. On Amrchy, run the ROCm userspace in a container from AMD's Ubuntu images, with `/dev/kfd` and `/dev/dri` passed through and the host's in-kernel `amdgpu` driver. Community reports note `gfx1201` teething bugs, so verify with `rocminfo` and a real load before relying on it |
| CUDA | — | Not available: the GPU is AMD |

Phase 3 runs the same models and prompts through both paths and keeps the faster one that passes. Whichever wins, **Ollama** is the serving layer, because the fleet already uses it: the code index embeds through Ollama (`.env.example`, `OLLAMA_URL` in `docker-compose.yml`), and [JEV.md](JEV.md) already names local inference through Ollama as an alternative that fits tier 1. Ollama binds the node's loopback, and the Mac reaches it through a link forward on 11434, the same way it reaches every placed service.

### What fits in 16 GB

- Dense models up to about 14B parameters run fully on the GPU at 4- to 8-bit quantization; about 20–24B fits at 4-bit with little room left for context.
- Mixture-of-experts models with few active parameters (the 30B-A3B class) can split between VRAM and the 64 GB of RAM, more slowly.
- Context costs VRAM (the KV cache), so every served model sets its context length explicitly.
- Which models are used is decided by evals, not by this document (§ 13.4: cheaper only if green). Each is pinned by exact tag and digest under a `local` provider in `_data/fleet.yml` `ai_models.allowed` (amendment § 30.3).

### What local models do, ranked by fit

1. **Embeddings for the code index** (Qdrant and Ollama). Already $0 on the Mac; moving them to the node frees the Mac. The first use, because nothing judges its output but the search.
2. **Bulk text work that deterministic code checks**: triage labels, chronicle summaries, error-signature clustering in the logs plane. Only behind a typed decision with a threshold, and only where its eval set passes.
3. **A local JEV tier** for small conflicts, below Haiku: `tier1-local`, shadow first, promoted only when its evals pass. A failure falls through to the next tier, as today.
4. **Private material** that should not reach a hosted API at all.

**What they do not do:** implementation PRs, reviews, the close-out agent, or anything the fleet holds to frontier quality. Claude Code with Claude models stays the executor for those (constitution § 26).

### Claude Code against a local model

Ollama 0.14 and later serves the Anthropic Messages API (`/v1/messages`), so `claude -p` can drive a local model with `ANTHROPIC_BASE_URL=http://127.0.0.1:11434` and a placeholder token. Reports are mixed: tool use depends heavily on the model, context length must be set, and Claude Code does not fall back to Claude if the endpoint fails. So this is used only for a step whose eval set passes on that model, only in that step's environment, and **never** as the default environment of a session, so a local model can never silently stand in for Claude.

## 4. Claude Code sessions on the node

**Install.** The Claude Code CLI on the node, signed in with Amr's subscription: `claude setup-token` writes the OAuth token, kept in a mode-0600 file outside every checkout. Auth follows `CLAUDE_AUTH_ORDER` (`oauth,api_key`, `_data/fleet.yml` `ai_auth:`), and every headless call keeps its `--max-budget-usd` cap. The hub is a real git clone on the node (ADR 0003 P1 replaces forge's rsync copy the same way), with submodules initialized as a task needs them.

| How | Command | When |
| --- | --- | --- |
| **Interactive, from the Mac** | `ssh -t onprem 'tmux new -A -s claude-<task> -c ~/dev/bamr87'`, then `claude` | Long sessions that should survive the Mac sleeping or travelling |
| **Driven by one-os** | `scripts/oneos-remote claude start <name> --cwd …`, then `wait`, `view`, `send`; `claude run` for one headless prompt (bashOS #99) | A session another session watches and steers, with a recording. Its screenshot and input features were built on KDE Plasma (Wayland) and are untested on Hyprland; its Claude Code features need no desktop |
| **Headless loops** | `tools/dash loop run …`, `tools/dash conflicts sweep`, `tools/dash weekly …`, `tools/dash refine reflect`, from the node's checkout | The hub's existing local entry points, unchanged: the same switches, caps, ledger and sandboxes as on the Mac (FR56, FR65) |
| **From the console** | The Harness Console on the node as `bashos-harness.service` on loopback, as on forge ([FORGE-HOST.md](FORGE-HOST.md#the-harness-console-as-a-bashos-service)); the Mac tunnels to it | `loop-run` and `dispatch` run where the work is; the MCP `loops` and `console_jobs` tools see the same API |

**Scheduling.** The Mac's local loops are LaunchAgents (`tools/install-weekly.sh`, `install-conflict-sweep.sh`, `install-harness-review.sh`). The node's twin is a **systemd user timer** per installer, added as a `--systemd` mode of the same installer, so there is still one installer per job and the agent inventory still reads one job per installer (§ 29.1).

**Concurrency.** Sixteen cores and 64 GB allow several sessions at once. The binding limit is the subscription's usage window, not the hardware, so scheduled sessions are capped (two at a time to start) in `_data/fleet.yml`.

## 5. The console and the weekend

The weekend already has two halves that meet on the week's issue ([WEEKLY.md](WEEKLY.md#beside-the-consoles-weekly-lanes)): the console's CI lanes from #841 repair pull requests on GitHub, and the Mac's `tools/dash weekly` LaunchAgent tidies what only the Mac can see. The node adds a third place where work happens, so it gets its own local half rather than a share of the Mac's.

| Day | Console lane (GitHub-hosted, #841) | Mac routine (LaunchAgent) | The node adds |
| --- | --- | --- | --- |
| **Friday** close-out | `weekly_closeout`, 20:17 UTC: repairs failing and conflicting PRs on their branches. **Stays on GitHub**: it needs nothing local | `close`, 22:37 local: saves, tidies and dispositions the Mac's own branches, worktrees and sessions. **Stays on the Mac** | Its own `weekly close` for its own checkouts, worktrees, scratch and sessions ([section 6](#6-the-housekeeping-a-hosted-runner-cannot-do)), with the same classifier and save-before-remove. The close-out agent's capped session can run here instead of on the Mac |
| **Saturday** gather / prepare | `weekly_gather`: a draft plan from the carry-over | `prepare`: can next week's schedule run; its "This Mac" checks | A **"This node"** row in `prepare`: reachable, disk, GPU visible, Ollama answering, Claude CLI signed in, timers loaded, last housekeeping result |
| **Sunday** finalize / plan | `weekly_finalize`: the week-ahead brief | `plan`: rank, lanes, the Monday brief | The node's free session slots and its pinned local models as an input, so the plan can say which "Do" items can run there unattended |

**Closing the `R6:no-local-entry` gap.** The three console lanes have no local entry point ([WEEKLY-CLOSEOUT.md](WEEKLY-CLOSEOUT.md#operating-it-from-the-console)). The node offers two ways to close it:

- **A. A local adapter (recommended).** The lane's prompt and caps rendered once and run as `claude -p` on the node from a systemd timer, behind the same `vars.*_ENABLED` switch read from `_data/fleet.yml` `switches:`. This is § 10.9's local-first rule, and it needs no GitHub setting.
- **B. A self-hosted runner.** `ai-lane.yml` would take a `runs-on` input (a kit change in `templates/ai-runner/`, never in the copy) and the lane would run on the node's runner. This is allowed only under amendment § 30.5 ([section 8](#8-security)), and it should wait until A shows something only a runner can do.

**In the console.** `tools/dash node status` and `plan` show the node once it is in `nodes:`; the TUI's `DASH_DOCKER_HOST` gains `ssh://onprem`; the Loops page lists the node-hosted loops with their switches; the agent inventory registers each new timer (§ 29.1, drift check (p)).

## 6. The housekeeping a hosted runner cannot do

A GitHub-hosted runner starts empty and ends wiped. The close-out brief asks the Friday lane to prune leftover `/tmp` clones and worktrees, but on a hosted runner there are none to see: they live on whichever machine ran the session. The same holds for stashes, `~/bamr87-*` folders, idle tmux sessions, stuck `claude` processes and the session transcripts under `~/.claude/`.

**Today, on the Mac.** `tools/dash weekly close` and `tidy` already do this with proof: on 2026-11-13 `tidy` found 25 folders and 2.3 GB, removed 18 dead worktrees, kept their branches, and left 7 it could not prove safe. That stays the Mac's job. The node never reaches into the Mac (§ 10.5); if Amr later opts the Mac in, the node may read its inventory over SSH, read-only, so one report covers both.

**Going forward, on the node.** As sessions move to the node, so do their worktrees, clones and session state, and the node's own Friday run cleans them:

| What | How | Never |
| --- | --- | --- |
| Worktrees and `~/bamr87-*` folders | The weekly classifier as is: only `dead` worktrees and proven-merged branches go, after a verified bundle to the archive on the 8 TB disk | Removes anything `live`, `dirty`, `recent`, `local-only` or `unknown` |
| Clones and sandboxes | All scratch under one root on the SATA SSD, so tidy has one place to look; a clone is removed only after `git status` is clean and nothing is unpushed | Deletes a clone it cannot classify; it lists it |
| Idle or stuck Claude Code sessions | A new inventory class: each tmux session and `claude` process, its idle time and its transcript's last write; one idle past a threshold is reported with the exact command that ends it | Kills, signals or attaches to a running session. Ending one is Amr's call |
| Session transcripts | Past a retention age, moved to the archive disk | Deletes them |
| Docker | Dangling images and build cache pruned past a retention age | Touches a volume |
| Runner work directories (option B only) | An ephemeral runner leaves nothing: each job gets a fresh one | — |

## 7. Cost

"Zero cost" is true for some of this and not for the rest, so each line says which (constitution § 10.7).

| Item | Before | On the node | What is honest to say |
| --- | --- | --- | --- |
| **Local-model inference** | Hosted-model tokens, recorded as API-equivalent (estimate) under OAuth, metered under an API key | **$0 metered API spend**; no tokens leave the house | Only where a local model passes the step's evals. The ledger records these runs under a new cost source, `local`, never summed with API figures (FR31) |
| **GitHub-hosted runner minutes** | Hosted minutes for every lane | **No hosted minutes** for work that moves onto the node | Standard hosted runners are already free on public repos, so for most of the fleet the gain is reach and concurrency, not dollars. Minutes moved off private repos do come off the included quota |
| **Claude Code sessions** | Drawn on Amr's Claude subscription, in CI (OAuth first) or on the Mac | **The same subscription** | Not zero marginal usage. Moving a session to the node changes where it runs, not what it draws. Every figure stays API-equivalent (estimate) |
| **Electricity** | — | **A real, small cost** | Measured with a wall meter in phase 1 and recorded as energy. Rough envelope until then: idle around 80–120 W, sustained GPU inference around 350–450 W, all-core CPU plus GPU around 600 W. At a 100 W average that is 2.4 kWh a day, about 72 kWh a month. The money figure comes from Amr's own tariff and stays out of the repo |
| **The hardware** | — | Bought | A sunk cost, outside the ledger; this repo records no prices |

## 8. Security

- **SSH keys only**, loopback binds, and the forwarding-only link key, exactly as [PLATFORM.md](PLATFORM.md#security) sets for forge.
- **Secrets stay where they are:** `.env` (mode 0600) and the OAuth token file on the node, GitHub secrets in GitHub. `FLEET_TOKEN` is handed only to a filer under § 11.8, never left in the scheduled user's environment. Nothing secret enters a local model's prompt or the repo.
- **Local models** run with the step's own tool allowlist and sandbox, from weights pinned by digest; Ollama never listens on the LAN. § 13.8 holds: private data plus untrusted content plus an outward send needs a human gate on the send, whatever model is in the middle.
- **A self-hosted runner on a public repository is the risky part.** GitHub recommends self-hosted runners only for private repositories, because a fork's pull request can run code on the runner. Labels are not a control: a fork can add `runs-on: [self-hosted, onprem]` to a workflow in its own diff. So a runner, if Amr ever wants one, is allowed only under amendment § 30.5:
  1. it never runs a fork's pull request: only `schedule` and `workflow_dispatch` workflows on the default branch target its labels, and a drift check fails a workflow reachable from `pull_request`, `pull_request_target`, `issue_comment`, `workflow_run` or any other event a fork can raise that does;
  2. the repository requires approval for fork pull-request workflows from all external contributors, a setting only Amr changes, and approving such a run means reading every workflow file it changes;
  3. it is ephemeral (just-in-time or `--ephemeral`, one job, then gone), runs as its own unprivileged user in a container or VM, and cannot read Amr's home, SSH keys, Claude credentials or `.env`;
  4. it has a § 17 kill switch, stays off until Amr registers it, and is registered in the agent inventory.

  ADR 0002 and #484 ruled out a self-hosted runner. That ruling stands for the Mac; § 30.5 opens only this narrow door for an enrolled node, and a phase that uses it adds an ADR that amends ADR 0002.

## 9. Rollout

Every phase is its own pull request or deploy step, reversible, and changes no machine until Amr approves it (§ 10.5, § 13.6).

| Phase | Scope | Changes a machine? | Who | To undo |
| --- | --- | --- | --- | --- |
| **P0** | This plan, the feature fragment and the proposed amendment | No | Agent; Amr merges to ratify | Close the PR |
| **P1** Bring-up | Install the OS (bashOS on Amrchy, or Debian 13) from the bashOS ISO or one-USB; SSH keys; disk layout; `bashos one-os machine check x870e-dark-hero`; a wall-meter baseline at idle and under load | The node only | Amr | Reinstall |
| **P2** Enrol, disabled | A PR adds `nodes.hosts.onprem` with `enabled: false`, its `ssh:` alias, `checkout:`, `capacity:` and GPU; `tools/dash node status` and `plan`; the Ansible inventory and a `--check --diff` run; the hub cloned on the node | No (the PR); the node (the deploy) | Agent PR; Amr deploys | Revert the PR; `enabled: false` |
| **P3** Local inference | Ollama on loopback with Vulkan, compared with ROCm in a container; the link forward; code-index embeddings moved; `ai_models.allowed.local` pins; the first eval runs; the `local` cost source in the ledger | The node | Agent PRs; Amr deploys | Point `OLLAMA_URL` back at the Mac |
| **P4** Session host and housekeeping | The Claude CLI signed in; the installers' `--systemd` mode; `weekly`, `conflicts sweep` and `refine reflect` timers on the node, each behind its switch and in `_data/agents.yml`; the "This node" checks in `prepare`; the session-state inventory class | The node | Agent PRs; Amr installs the timers | Disable the timers or flip the switch |
| **P5** The weekly lanes locally | The local adapter for `weekly_closeout`, `weekly_gather` and `weekly_finalize` (option A), closing `R6:no-local-entry`. Option B, the runner, only if A shows a need, under § 30.5 and with an ADR that amends ADR 0002 | The node | Agent PR; Amr arms | Flip the switch; the CI lanes still exist |
| **P6** A local model tier | `tier1-local` in JEV and local typed decisions, in shadow for at least 14 days, then promoted per step on green evals | No (config); the node runs it | Agent PR; Amr merges the gated promotion | Remove the tier |

### Next steps for Amr

1. Read this plan and the amendment, and merge the PR if you agree. Merging ratifies § 30; leaving the amendment out is also fine, and the plan still stands as a design doc.
2. Answer the open questions in [section 11](#11-open-questions-for-amr), above all the host name and the OS.
3. Do P1 on the machine: install, SSH keys, and a wall-meter reading at idle and under load.
4. Then ask Claude Code for the P2 pull request.

## 10. Design record (constitution § 10.8)

**Need.** Work the fleet wants done locally has nowhere good to run. The Mac sleeps, travels and is protected by § 10.5; forge is too slow for the devenv image and has no usable GPU. The console's weekly lanes run where they cannot see local state (`R6:no-local-entry`). Every AI step today buys a hosted model, even ones a small local model could do, and every agent session competes with Amr's interactive work on the Mac.

**Prior art.** From documentation and general knowledge; none trialled on this machine yet.

| Option | Fit |
| --- | --- |
| Ollama | **Adopted** as the serving layer: already used by the code index, Vulkan and ROCm backends, an Anthropic-compatible endpoint since 0.14 |
| llama.cpp server | Kept as the fallback and the benchmark baseline; Ollama builds on it |
| vLLM on ROCm | Rejected for now: built for datacenter GPUs, and consumer RDNA 4 support is less mature; revisit if throughput binds |
| LM Studio | Rejected: a desktop app, not a headless service |
| GitHub self-hosted runner (ephemeral or just-in-time) | Optional, phase 5, under § 30.5 only; GitHub advises against it on public repositories |
| actions-runner-controller | Rejected: needs Kubernetes, which ADR 0003 defers to phase 10 |
| `act` | Rejected by ADR 0002: it does not run locally and faithfully |
| systemd user timers | **Adopted**: the Linux twin of the Mac's LaunchAgents, one per installer |
| Salt schedule, cron | Rejected for loops: Salt owns steady state (ADR 0003), and cron lacks persistent catch-up after downtime |
| `oneos-remote` (bashOS #99) | **Adopted** for driven and recorded sessions; plain `ssh` plus `tmux` for interactive ones |
| Claude Code cloud sessions | Rejected for housekeeping: they cannot see the node's checkouts or sessions |

**Decision.** Enrol the machine through the node model the hub already has (ADR 0003) and run the hub's existing local entry points on it, rather than build a second control plane. What is new is small: a node entry, systemd modes for three installers, an Ollama service and its pins, a `local` cost source, a session-state inventory class, and a local adapter for the weekly lanes. The runner stays optional and fenced.

## 11. Open questions for Amr

- **Host name.** `onprem` is a placeholder for the node id, the SSH alias and any runner label.
- **OS.** bashOS on Amrchy (one platform with bashOS #100) or Debian 13 (forge's base, and closer to ROCm's supported list). Vulkan works on both.
- **forge.** Keep it as the planes host, move the planes to the new node, or retire it.
- **Always on?** Whether the node stays up overnight and at weekends decides whether it can carry scheduled housekeeping and the planes, or wakes by Wake-on-LAN.
- **The runner.** Wanted at all, once the local adapter exists?
- **First local-model job.** Code-index embeddings are proposed; another candidate is welcome.
- **Interactive default.** Whether the node becomes where Amr's own sessions usually run, with the Mac as a thin client.

## When something goes wrong

| Failure | Detection | Recovery |
| --- | --- | --- |
| The node is off or unreachable | `tools/dash node status`; Saturday's "This node" row | Loops that prefer it fall back to the Mac or CI, or wait, and say which; wake it by Wake-on-LAN. The fleet never needs the node to be up |
| A GPU driver or ROCm update breaks inference | Ollama's health probe; eval runs fail | Switch to the Vulkan backend; steps on local tiers fall through to the next tier |
| A local model's output is wrong | The step's eval set and its typed-decision threshold | Demote the tier; the step returns to its hosted model |
| The OAuth token expires | The headless run's auth probe | `claude setup-token` on the node, by Amr |
| Housekeeping is unsure about something | The classifier returns `unknown`, `dirty` or `live` | It keeps the thing and lists it; nothing is removed on doubt |
| A disk fills | `prepare`'s disk check; the node's alerts once Salt (ADR 0003 P5) is on it | Prune scratch and caches; models and archives are never pruned automatically |
| The runner is abused (option B) | Workflow drift check; the runner's job log | Unregister it, flip its switch; it is ephemeral and holds no secrets |

<!-- kit: governance v0.1.0 -->
# 0020 — The OPS remote-write path: how the console and the local loop runner write to GitHub

- **Status:** proposed
- **Number:** 0020
- **Date:** 2026-11-03
- **Proposed by:** agent (Claude Fable 5.1, on a branch opened for bamr87). Option (a) of bamr87/bamr87#487 is the agent's recommendation, made under the maintainer's 2026-11-03 instruction to continue the epic's remaining work; the maintainer had not picked (a) or (b) — their merge of this PR is the choice and the ratification.
- **Ratified by:** the merged PR URL (left blank until merged)
- **Affects:** constitution § 11 (scope line; new item 8 "The OPS remote-write path"); feature HUB-069; ADR 0002 (appended "P2 — the write path"); `tools/console/core.py` (`loop-run` `apply`), `.github/scripts/dash-gen/fleet_doctor_file.py` (`--apply`); docs/HARNESS-OPS.md, docs/JEV.md, docs/DAILY-ANALYSIS.md, tools/console/README.md
- **Supersedes:** none (clarifies 0006 `projects-write-back`; extends § 10.6 and § 13.6)
- **Related:** bamr87/bamr87#487 (P2), #488 (P3), epic #484; [ADR 0002](../../adr/0002-agent-step-specs-and-local-runner.md); `tools/console/gh_projects_write.py`; `tools/jev/loop.py` (`publish_phase`, `apply_item`, `probe_publish_token`)

## Context

§ 11 (amendment 0006) was written for one capability: the Projects editing service, `tools/console/gh_projects_write.py`, whose `ALLOWLIST` names project, item, issue-field and PR-field mutations and nothing else. Read literally it says the console may write to GitHub *only* through that allowlist. But the console already carries a second, older family of writes that the allowlist cannot express and that 0006 never meant to forbid: the `remote` operations (`content-file`, `deploy-*`, `dispatch`, `secrets-push`), each run as a job behind `confirm=true`, one at a time under the job manager's single remote lock, with the same `tools/dash` and `tools/dash-gen` code CI runs. And P1 of epic #484 (ADR 0002) built the local loop runner's publish gate on the same shape: `--apply` typed by the maintainer is the § 13.6 yes, the publish token is probed with `gh api user` before any spend, the same filer CI runs (`tools/dash-gen scout-file`, `doctor-file`) writes with `GH_TOKEN` in that one subprocess, held to the reviewed bytes, never with `--scheduled`.

Issue #487 asked the maintainer to pick between (a) a clarifying amendment that scopes § 11 to the Projects service and names the OPS remote-write path as sanctioned, and (b) routing every loop-run write through `gh_projects_write` plans, which would need `issue.create` and draft `pr.create` in the allowlist and make P2 and P3 depend on #472. The maintainer chose (a) on 2026-11-03.

Why (a): the § 11 allowlist is a field-editing vocabulary (set, clear, move, archive) with no create verb and no branch or commit, so a draft PR with a pushed branch cannot be a plan step without redesigning the service; the engine's publish path already carries every control § 11 asks for (dry run then confirm, a deterministic preview id, idempotence through the open-marker dedupe and the `O_EXCL` result claim, an append-only run record, a scoped token never printed) in code that is tested end to end; and (b) would hold the loop runner's `apply`, from the console and from a terminal alike, behind #472's schedule for no gain in safety.

## Amendment

1. § 11's opening sentence gains its scope: "The console may write to GitHub Projects (v2), issues and pull requests across every registry owner through the Projects editing service (`tools/console/gh_projects_write.py`) only under these rules; every other write the console or the local loop runner makes goes through the OPS remote-write path (item 8), never around either."
2. Add § 11.8 **The OPS remote-write path** (text as in `docs/constitution.md` § 11.8): a console operation that writes to GitHub, and the local loop runner's `apply`, is sanctioned only as a `remote` operation run with `confirm=true` (the § 13.6 yes; `--apply` typed by the maintainer on a terminal is that yes), one such job at a time under the job manager's remote lock; a dry run first and only its reviewed bytes filed; the token `FLEET_TOKEN` resolved as the engine does and probed with `gh api user` before any spend or write, handed to the filer as `GH_TOKEN` in that one subprocess, never printed, logged or placed in argv; the same `tools/dash` / `tools/dash-gen` filer CI runs, carrying its § 13.6 risk tier and writing only what CI's job writes (labels, issues, one pushed branch and a draft PR); never a merge, force-push, delete or settings change; refused with `--scheduled`, with a dirty engine and when its dedupe list cannot be read; every write recorded in the run record and the job document. The existing `remote` operations are this path; the MCP reaches it only through the console's job API.

## Consequences

- The console's `loop-run` op accepts `apply` (and `run_id`, to publish an earlier reviewed preview) behind the existing confirm gate; the TUI and the `fleet` MCP reach it through the same job API, so nothing new bypasses the gate. `apply` with `rehearse`, or any `scheduled` parameter, is refused at the op.
- `dash-gen doctor-file --apply --reviewed-bodies <dir>` publishes the fleet doctor's dry run the way CI's doctor would: a scratch clone, the fix branch, the reviewed patch committed, one push of `HEAD:refs/heads/<branch>` with git's receive-pack pinned and the credential read from gh, and a draft PR with the labels CI uses — or, for a submodule candidate, the hub issue. The P3 evolve and agent-fill steps (#488) follow the same shape.
- Option (b) is not taken: `gh_projects_write.py`'s `ALLOWLIST` is unchanged and still has no create verb; a later amendment may route a write through it where a plan step fits.
- Agents still propose and never merge; an agent's console or terminal `apply` is the maintainer's confirm, never its own.
- Merging the pull request that carries this record ratifies it (§ 8.3); `jev-number.yml` assigns its number and appends its row to the index.

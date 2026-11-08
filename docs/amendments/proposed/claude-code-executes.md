# NEW — Claude Code executes; Grok bots set direction only

- **Status:** proposed (ratification pending — Amr ratifies by merging this PR)
- **Number:** NEW
- **Date:** 2026-11-05
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:**
- **Affects:** constitution § 26 (new; follows § 24 on main and proposed § 25 from open PR #685 `mcp-lifecycle` — this section is **§ 26** if #685 lands first, else renumber to **§ 25**); § 4 (roles table); § 8 and § 12 by reference; feature `HUB-NEW:claude-code-executes`; requirement `FR-NEW:claude-code-executes`; roadmap FF-NEW:claude-code-executes; `AGENTS.md` agent-roles
- **Supersedes:** none (narrows which AI actors may open which PRs; does not change maintainer merge authority or § 12.3 ratification-record PRs)
- **Related:** epic-style handoff via Fleet issues / console jobs; in-flight non-amendment PRs (hub #607; lifehacker.dev #800; scripts #36/#37; bash-365.com open work); Design for Failure (DFF); process mirrors #678/#680, #683/#685

## Context

Amr's direction: **all changes sent to the Harness Console, or that modify software, must be executed by Claude Code.** The only PRs or changes Grok bots (Amr's Grok Bot assistants and their subagents) may make are **constitutional or amendment PRs that set direction**.

Today § 4 treats "AI agent" as one row: any agent may open implementation PRs and, when mergeable under § 12, merge them. That conflicts with Amr's split: Grok bots are the **architect / director** surface; Claude Code (local CLI and console-dispatched sessions) is the **executor** for software and console-affecting work.

## Prior art

- **§ 4 / § 8 / § 12:** agents propose amendments; only the maintainer ratifies; gated PRs need Amr. Fit: keep ratification with Amr; add actor split.
- **§ 11 / console jobs / issue pipeline:** plan → confirm → apply; issue-pipeline never merges. Fit: handoff channel from Grok → Claude Code.
- **`claude-run` / JEV loop runner / console `loop-run`:** existing Claude Code execution paths. Fit: executor runtime. Reuse.
- **Build-vs-adopt:** adopt Claude Code sessions and Fleet issues as the handoff; new pieces are the constitution rule, AGENTS.md roles, and a warn-only author lint.

## Terms

| Term | Meaning |
| --- | --- |
| **Claude Code** | Anthropic Claude Code sessions that execute work: the local CLI in a checkout, and sessions dispatched from the Harness Console / hub workflows (`claude-run`, loop-run, issue-pipeline implement tier, and equivalents). |
| **Grok bots** | Amr's Grok Bot assistants operating under Cursor / xAI Grok Bot (including named bots such as Grok Bot primary, Platform Architect, Fleet Ops, Tools, Sites, Content & Comms, Researcher, Bashcrawl & Games, Law AI Lead, and any subagents they dispatch). |
| **Direction-setting PR** | A PR whose *purpose* is to propose or amend fleet direction: `docs/constitution.md`, `docs/amendments/proposed/*` (and the compiled amendment on merge), and the `changelog.d/*` fragment that announces that amendment. Feature/`prd_new` / roadmap fragments that exist **only to support that amendment** may ship in the same PR. |
| **Software or console change** | Any other change: application or tooling code, console UI/API, compose, workflows that are not solely the amendment machinery, site content implementations, scripts, submodule product code, verification runners, etc. |

## Amendment

New constitution section (and § 4 update below):

> ## 26. Claude Code executes; Grok bots set direction
>
> _(amendment `claude-code-executes`, numbered at merge — see the [amendment log](amendments/README.md); follows § 24 on main and proposed § 25 `mcp-lifecycle` (PR #685) — this is § 26 if that lands first, else renumber to § 25; amends § 4; extends § 8 and § 12)_
>
> 1. **Executor** — every change that modifies software, or that is sent to the Harness Console to be applied as an execution (ops, jobs, loop-run apply, write-back that carries out work rather than only recording direction), is executed by **Claude Code** (local CLI or console-/workflow-dispatched session).
> 2. **Director** — **Grok bots** may open PRs only when the PR is **direction-setting**: constitution text, amendment records under `docs/amendments/` (proposed → numbered at merge), and the matching `changelog.d/` entry. They may include `features/features.d/`, `prd_new`, and `_data/roadmap.yml` fragments **only inside that same amendment PR** when those fragments define the capability the amendment introduces.
> 3. **What Grok bots may still do without a software PR** — file and comment on GitHub issues; draft console plans that stop before apply; propose handoff issues labelled for Claude Code execution; read and review. They do **not** open implementation PRs, push product commits, or apply console write-back that executes software changes.
> 4. **Handoff** — when a Grok bot determines software or console work is needed, it files a Fleet issue (and/or a console job / loop step) that states the goal, acceptance criteria, and constraints; Claude Code picks that up and opens the implementation PR.
> 5. **Maintainer override** — Amr may always direct otherwise; an explicit Amr OK is required before a Grok bot executes software work when Claude Code is unavailable or out of budget (Design for Failure).
> 6. **Ratification unchanged** — only Amr merges amendments (§ 8); § 12.3 ratification-record PRs remain automation, not Grok implementation work.
> 7. **Enforcement** — a warn-then-fail check (`tools/claude_code_executes_lint.py` and/or a workflow) flags PRs authored by known Grok-bot identities whose diff is not direction-setting; warn-only until adoption, then hard fail. Labels such as `direction-setting` / `executor:claude-code` may assist humans and CI.
> 8. **Fleet** — spoke repos conform or file their own amendment saying how they do.

### § 4 roles table (replace the single "AI agent" row with two)

> | Actor | May | May not |
> | --- | --- | --- |
> | Maintainer (human) | Ratify amendments, PRD changes and releases by merging PRs; change settings, secrets, branch protection; explicitly OK a fallback when Claude Code cannot run (§ 26.5) | — |
> | Claude Code (executor) | Execute software and Harness Console–bound changes via PRs and sanctioned console jobs; follow § 10–§ 12; merge only when mergeable under § 12 and not gated | Merge gated PRs; push to default; force-push; change settings; print or commit secrets; invent requirements (unknown = **TBD**) |
> | Grok bots (director) | Propose direction-setting amendment PRs (§ 26.2); file/comment issues; hand off execution to Claude Code (§ 26.4); read and review | Open or push software/console implementation PRs; apply console execution write-back; merge any PR; change settings; print or commit secrets |

## Design for Failure

| Failure | Behaviour |
| --- | --- |
| Claude Code unavailable or out of budget | Grok bot files/updates the handoff issue with the blocker; **does not** implement; waits for Amr's explicit OK to either (a) retry Claude Code later, (b) authorize a one-shot Grok exception, or (c) Amr executes |
| Ambiguous PR (amendment + large software diff) | Split: direction-setting PR first; software via Claude Code handoff; CI warns on mixed Grok-authored PRs |
| In-flight Grok-authored non-amendment PRs | Open question (below); until decided, do not force-close; label and hand off |
| Mis-identified author | Warn-only lint; allowlist/blocklist in `_data/agent_roles.yml`; false positives get `direction-setting` label after Amr confirms |
| Spoke repo without Claude Code path | File spoke amendment or route execution through hub Claude Code with Amr OK |

## Open questions (for Amr)

1. **Issues / backlog / roadmap / PRD outside an amendment PR** — proposal in this text: Grok bots may file issues and comments freely, and may edit PRD/feature/roadmap **only as fragments inside an amendment PR**. Confirm or tighten (e.g. Grok may also open pure roadmap-issue PRs).
2. **In-flight Grok-authored non-amendment PRs** — e.g. hub [#607](https://github.com/bamr87/bamr87/pull/607); lifehacker.dev [#800](https://github.com/bamr87/lifehacker.dev/pull/800); scripts [#36](https://github.com/bamr87/scripts/pull/36)/[#37](https://github.com/bamr87/scripts/pull/37); bash-365.com open PRs (formerly cited #77/#78). Options: (a) Amr merges or closes, (b) retitle/relabel and hand to Claude Code to recreate, (c) grandfather until merge. **Default until Amr picks: (c) grandfather + label `pre-§26`.**
3. **Exact Grok identity list for CI** — bot logins / app slugs / `author_association` signals to treat as Grok bots (`_data/agent_roles.yml`).
4. **Section number** — § 26 vs § 25 if #685 does not merge first.
5. **May Grok bots merge mergeable *direction-setting* PRs?** — proposal: **no**; Amr always merges amendments (§ 8). Claude Code also does not merge gated amendment PRs.

## Consequences

- Grok bots stop opening software/console implementation PRs after ratification; they hand off.
- `AGENTS.md` gains an Agent roles section mirroring § 26.
- Feature `HUB-NEW:claude-code-executes` + `FR-NEW:claude-code-executes`; roadmap `FF-NEW:claude-code-executes`.
- Warn-only `tools/claude_code_executes_lint.py` ships with the PR; hard-fail later.
- Predicted ids at merge (main tip 2026-11-05): if #685 merges first → amendment **0025**, HUB-**085**, FR**85**, § **26**; if this merges first → amendment **0024**, HUB-**084**, FR**84**, and section renumber to **§ 25** until #685 lands.
- Ratification: Amr ratifies by merging this PR (merge commit); agents propose, never merge (§ 8).

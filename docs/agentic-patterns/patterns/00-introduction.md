---
id: ADP-00
chapter: 0
title: "Introduction: what makes a system an agent, and the fleet's agent levels"
book_pages: "Intro: 'What makes an AI system an Agent?'"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Content & Comms
---
# What makes a system an agent?

## Summary

A plain language model only answers. An agent is a system that pursues a goal by working through a loop:
1. Get the goal.
2. Gather what it needs to know.
3. Plan.
4. Act with tools.
5. Learn from how it went.

Gulli describes an agent as a system that can "perceive its environment and take actions to achieve a specific goal" (book, intro). He then lays out levels of increasing capability. Under Fleet evidence, each level is mapped to real parts of Amr's fleet: the hub bamr87/bamr87 and its ~38 submodules.

## When to use / not

- Use an agent when the work needs several steps, tools, or decisions that depend on what earlier steps found.
- Use a plain model call (Level 0) when one prompt and one answer are enough. Each extra level adds cost and more places to fail.

## Failure modes

- Calling a single prompt an "agent" when nothing loops or acts.
- Claiming a higher level than the code shows, for example self-improvement that isn't built.
- Specialist agents with no shared hand-off contract or coordinator.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

All links point to commit 2321b3a7c1199688042339d68b628f9d08bb46eb.

| Level | Book's idea (paraphrased) | Fleet example | Status |
|---|---|---|---|
| 0: Reasoning core | A model with no tools, memory or outside access. It answers only from what it learned in training. | The single-shot **API fallback** in the universal runner. It sends one prompt, and the tool list is ignored. [run.sh L3, L48](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/run.sh#L1-L50), [L341-343](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/run.sh#L341-L343), [action.yml L42-43](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/action.yml#L42-L43) | proven (code) |
| 1: Connected problem-solver | Uses tools such as search, APIs or retrieval, over several steps. | Claude Code steps with an allow-list of tools (`gh`, `git`, `jq`, Playwright MCP), for example [issue-pipeline L373](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L373) and [fleet-verify L361](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/fleet-verify.yml#L361) | proven: green run [41181601564](https://github.com/bamr87/bamr87/actions/runs/41181601564) |
| 2: Strategic problem-solver | Plans multi-part work and manages the context each step gets. Example: read a bug report, then write, test and submit a patch. Can improve itself. | Issue Pipeline. Tier 1 builds a focused evidence bundle (real clone, lint, test, build) and rewrites the issue. Tier 2 implements it and opens a draft PR. Tier 3 drives CI to green. [L1-32](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L1-L32), [L276-319](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L276-L319). Self-improvement, where the system rewrites its own prompts from feedback, isn't present. | partial |
| 3: Collaborative multi-agent | A team of specialist agents with a coordinator, like departments in a company. | Specialist roles are defined as named agents ([.claude/agents/](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.claude/agents): feature-scout, verifier). Separate loops each own one job: fleet-pulse fixes workflows, issue-pipeline resolves issues, repo-scout, fan-out. Hand-offs go through labels and issues ([L24-32](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L24-L32)). The bot team outside GitHub (Platform Architect, Content & Comms, and others) works the same way. There is no formal agent-to-agent protocol and no single coordinator agent. | partial |

### Reproduce

```bash
git clone --depth 1 https://github.com/bamr87/bamr87 /tmp/hub && cd /tmp/hub
sed -n 335,345p .github/actions/claude-run/run.sh             # Level 0 single-shot fallback
grep -n -- "--allowedTools" .github/workflows/*.yml           # Level 1 tool allow-lists
ls .claude/agents                                             # Level 3 named roles -> feature-scout.md verifier.md
gh run view 41181601564 -R bamr87/bamr87 --json jobs -q '.jobs[]|"\(.name) \(.conclusion)"'  # Level 2 chain, all success
```

All four commands were run on 2026-10-31 (MDT), and the output matched what is described above. The Level 0 fallback is shown from code only: no run that took the fallback path was found. Read-only checks; no Actions minutes were used.

## Gaps

- **Level 2 self-improvement:** the system doesn't yet feed run results back into its own prompts. Filed as [#535](https://github.com/bamr87/bamr87/issues/535) (agent:queued). This also covers ADP-09's gap 1.
- **Level 3:** there is no formal agent-to-agent hand-off contract or coordinator. This touches constitution §16 (A2A), so it is a standards item for Platform Architect / needs-amr. Filed as [#536](https://github.com/bamr87/bamr87/issues/536) (needs-amr). Related: #495, #492, #530.

## Cross-links

ADP-01 Prompt Chaining, ADP-07 Multi-Agent, ADP-09 Learning/Adaptation, ADP-17 Reasoning; constitution §15, §16; #480 (prior art).

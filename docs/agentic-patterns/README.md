# Agentic design patterns in the fleet

> How each pattern in Antonio Gulli's *Agentic Design Patterns* shows up in the bamr87 fleet: one page per chapter, each rated proven, partial or gap against pinned, reproducible evidence.

Each page paraphrases the chapter (no long quotes from the book), says when to use the pattern, and maps it to fleet code. Every evidence link is a permalink at a pinned commit, and every page has a reproduce block of cheap commands. Every gap links an issue.

**Status scale.** `proven`: the pattern is on `main` and the reproduce commands pass. `partial`: some sub-aspects are on `main`, or the evidence is only on an unmerged PR. `gap`: nothing usable on `main` yet.

**Tally (2026-10-31):** 4 proven, 17 partial, 1 gap, out of 22 pages.

| id | chapter | status | owner bot | linked issues |
| --- | --- | --- | --- | --- |
| ADP-00 | [Introduction: what makes a system an agent, and the fleet's agent levels](patterns/00-introduction.md) | partial | Content & Comms | bamr87/bamr87#480, bamr87/bamr87#492, bamr87/bamr87#495, bamr87/bamr87#530, bamr87/bamr87#535, bamr87/bamr87#536 |
| ADP-01 | [Prompt Chaining](patterns/01-prompt-chaining.md) | partial | Content & Comms | bamr87/bamr87#348, bamr87/bamr87#534 |
| ADP-02 | [Routing](patterns/02-routing.md) | partial | Grok Bot | bamr87/law-ai#204 |
| ADP-03 | [Parallelization](patterns/03-parallelization.md) | proven | Tools | — |
| ADP-04 | [Reflection](patterns/04-reflection.md) | proven | Grok Bot | bamr87/law-ai#205 |
| ADP-05 | [Tool Use (Function Calling)](patterns/05-tool-use.md) | proven | Tools | — |
| ADP-06 | [Planning](patterns/06-planning.md) | partial | Platform Architect | bamr87/bamr87#486, bamr87/bamr87#523, bamr87/bamr87#525 |
| ADP-07 | [Multi-Agent Collaboration](patterns/07-multi-agent-collaboration.md) | partial | Platform Architect | bamr87/bamr87#492, bamr87/bamr87#495, bamr87/bamr87#530 |
| ADP-08 | [Memory Management](patterns/08-memory-management.md) | partial | executor (Grok Bot) | bamr87/README#46, bamr87/bamr87#546 |
| ADP-09 | [Learning and Adaptation](patterns/09-learning-and-adaptation.md) | partial | executor (Grok Bot) | bamr87/bamr87#530, bamr87/bamr87#535, bamr87/bamr87#539 |
| ADP-10 | [Model Context Protocol (MCP)](patterns/10-model-context-protocol.md) | proven | Tools | bamr87/bamr87#541 |
| ADP-11 | [Goal Setting and Monitoring](patterns/11-goal-setting-and-monitoring.md) | partial | executor (Grok Bot) | bamr87/bamr87#492, bamr87/bamr87#523, bamr87/bamr87#525, bamr87/bamr87#537 |
| ADP-12 | [Exception Handling and Recovery](patterns/12-exception-handling-and-recovery.md) | partial | executor (Grok Bot) | bamr87/bamr87#238, bamr87/bamr87#522, bamr87/bamr87#532 |
| ADP-13 | [Human-in-the-Loop](patterns/13-human-in-the-loop.md) | partial | Platform Architect | bamr87/bamr87#492, bamr87/bamr87#529 |
| ADP-14 | [Knowledge Retrieval (RAG)](patterns/14-knowledge-retrieval-rag.md) | partial | executor (Grok Bot) | bamr87/README#46, bamr87/README#47, bamr87/bamr87#495, bamr87/bamr87#547, bamr87/ragio-ai#3 |
| ADP-15 | [Inter-Agent Communication (A2A)](patterns/15-inter-agent-communication.md) | gap | Tools | bamr87/bamr87#495, bamr87/bamr87#536, bamr87/bamr87#542, bamr87/bamr87#543, bamr87/bashos#67 |
| ADP-16 | [Resource-Aware Optimization](patterns/16-resource-aware-optimization.md) | partial | executor (Grok Bot) | bamr87/bamr87#502, bamr87/bamr87#530, bamr87/bamr87#533 |
| ADP-17 | [Reasoning Techniques](patterns/17-reasoning-techniques.md) | partial | executor (Grok Bot) | bamr87/bamr87#492, bamr87/bamr87#530, bamr87/bamr87#540, bamr87/bamr87#544 |
| ADP-18 | [Guardrails / Safety Patterns](patterns/18-guardrails-safety.md) | partial | Platform Architect | bamr87/bamr87#526, bamr87/bamr87#528, bamr87/bamr87#530, bamr87/bamr87#531 |
| ADP-19 | [Evaluation and Monitoring](patterns/19-evaluation-and-monitoring.md) | partial | executor (Grok Bot) | bamr87/bamr87#446, bamr87/bamr87#451, bamr87/bamr87#492, bamr87/bamr87#495, bamr87/bamr87#522, bamr87/bamr87#530 |
| ADP-20 | [Prioritization](patterns/20-prioritization.md) | partial | executor (Grok Bot) | bamr87/bamr87#538 |
| ADP-21 | [Exploration and Discovery](patterns/21-exploration-and-discovery.md) | partial | executor (Grok Bot) | bamr87/bamr87#540, bamr87/bamr87#545 |

## Machine index

[`patterns.json`](patterns.json) mirrors each page's front matter (`id`, `chapter`, `title`, `book_pages`, `status`, `evidence_repos`, `last_verified`, `owner_bot`), plus its `path` and the issues its Gaps section links. It validates against [`patterns.schema.json`](patterns.schema.json). Agents can find it from the site's `llms.txt`.

## Updating a page

Change the page's front matter and the matching `patterns.json` entry in the same pull request. Re-run the page's reproduce block at the new pin and update `last_verified`. A status moves up only on evidence that is merged to `main`.

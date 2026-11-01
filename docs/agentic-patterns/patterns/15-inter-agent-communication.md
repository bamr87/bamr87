---
id: ADP-15
chapter: 15
title: Inter-Agent Communication (A2A)
book_pages: 231-245
status: gap
evidence_repos: [bamr87/bamr87, bamr87/outbox]
last_verified: 2026-10-31
owner_bot: Tools
---
# Inter-Agent Communication (A2A)

## Summary
Where MCP connects an agent to tools, A2A connects agents to each other across frameworks and vendors. Each agent publishes an Agent Card (JSON at a well-known URL) describing identity, endpoint, skills, auth and modalities; clients discover it and exchange tasks and messages over HTTP/JSON-RPC, with synchronous, streaming (SSE) or push-notification interaction. Gulli positions it as the interoperability layer for multi-agent systems built by different teams.

## When to use / not
- Use: independent agents owned by different teams/frameworks that must delegate work.
- Avoid: agents in one process/framework (use the framework's own multi-agent primitives).

## Failure modes
Stale or over-claiming Agent Cards, unauthenticated endpoints, long tasks without status/streaming, no task ID tracing.

## Fleet evidence (partial — policy only)
1. Constitution §16 L192 mandates an Agent Card at `/.well-known/agent-card.json` for any repo running an agent. https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md#L192
2. The ai-ready README (L17) lists an `agent-card.template.json`, but that file is **not committed** at this SHA (`git ls-files templates/ai-ready | grep -i card` returns nothing). Another gap.
3. Informal inter-bot protocol: outbox `agents/` holds prose "agent cards" for Grok Bot group chats (`agents/grok_bots_kickoff.md`) — human-pasted instructions, not A2A. https://github.com/bamr87/outbox/blob/fcbc4c6032c0fd89054dc7bf52b7f59eb640dc92/agents/grok_bots_kickoff.md

Reproduce:
```bash
for r in bamr87 bashos gitorio githubai outbox; do git clone -q --depth 1 https://github.com/bamr87/$r; done
find . -name 'agent-card*.json' -not -path '*/node_modules/*'   # observed: 0 published cards
```

## Gaps
- **No published Agent Card / A2A endpoint anywhere in the fleet.** Filed: https://github.com/bamr87/bashos/issues/67 (P2, size:s).
- `templates/ai-ready/agent-card.template.json` is referenced in the kit README but missing. → [#542](https://github.com/bamr87/bamr87/issues/542) (`agent:queued`).
- No A2A server/client exchange. It would be a networked service, so it is out of scope for bashOS (hard rule 2); the candidate owner is the hub console. → [#543](https://github.com/bamr87/bamr87/issues/543) (`needs-amr`). Related: [#536](https://github.com/bamr87/bamr87/issues/536), #495.

## Cross-links
ADP-07 Multi-Agent, ADP-10 MCP; constitution §16.

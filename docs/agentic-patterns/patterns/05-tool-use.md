---
id: ADP-05
chapter: 5
title: Tool Use (Function Calling)
book_pages: 79-99
status: proven
evidence_repos: [bamr87/bashos, bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Tools
---
# Tool Use (Function Calling)

## Summary
Tool use lets a model act beyond its training data: the agent advertises tools (name, description, typed parameters), the model emits a structured call, the runtime executes it and feeds the result back for the next reasoning step. Gulli treats it as the bridge from "LLM that talks" to "agent that does": APIs, search, code execution, databases. The critical design work is in the tool contract (clear schemas and descriptions), the execution layer (validation, errors returned as data), and the permission boundary (what a model may touch).

## When to use / not
- Use: live data, deterministic computation, side effects that must be audited.
- Avoid: giving broad write/network tools when read-only suffices; tools with vague descriptions.

## Failure modes
Hallucinated arguments, unhandled tool errors crashing the loop, over-privileged tools, huge outputs blowing the context.

## Fleet evidence
1. **Deny-by-default tool profiles per agent.** bashOS `src/bashos/opencode/project.py` L75-95 `build_agents`: a read-only inspection agent and a sealed no-tool agent, tools supplied by the policy module; the engine executes tools (bashOS hard rule 1). https://github.com/bamr87/bashos/blob/66fb61d884e4acaab3ac65c1c007fd690d95101f/src/bashos/opencode/project.py#L75-L95 Tests: `tests/test_opencode.py` L43 `test_mutating_and_outbound_tools_are_denied_and_hidden`, L57 `test_sealed_profile_offers_no_tools_at_all`.
2. **Typed tool schemas, errors as tool results, output truncation.** hub `tools/fleetcore/mcp_server.py` (`_schema` L205, `handle` L272); tests `tools/test_fleetcore_mcp.py` (`test_bad_arguments_are_tool_errors`, `test_long_logs_are_truncated_to_the_tail`). https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleetcore/mcp_server.py#L205

Reproduce (run 2026-10-31):
```bash
git clone https://github.com/bamr87/bashos && cd bashos && git checkout 66fb61d884e4acaab3ac65c1c007fd690d95101f
uv run --with-editable . --with pytest python -m pytest -q tests/test_opencode.py -k "mutating_and_outbound or sealed_profile"
# observed: 2 passed
git clone https://github.com/bamr87/bamr87 && cd bamr87 && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q tools/test_fleetcore_mcp.py
# observed: 8 passed
```
Note: the full `tests/test_opencode.py` had 15 failures in a bare clone without `make install`/the opencode engine; not used as evidence.

## Gaps
None found.

## Cross-links
ADP-10 MCP (standardized tool transport), ADP-18 Guardrails; constitution §16.

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

Tool use lets a model do things its training data can't. The agent lists the tools it has, each with a name, a description and typed inputs. The model replies with a structured request to call one. The runtime runs the tool and hands the result back, and the model uses it for its next step. Gulli treats this as the bridge from a model that talks to an agent that acts, through APIs, search, code and databases. Most of the design work is in three places: the tool contract (clear inputs and descriptions), the code that runs the tool (check inputs, and return errors as data instead of crashing), and the permission boundary (what the model is allowed to touch).

## When to use / not

- Use: live data, deterministic computation, side effects that must be audited.
- Avoid: giving broad write/network tools when read-only suffices; tools with vague descriptions.

## Failure modes

- Hallucinated arguments.
- Unhandled tool errors crashing the loop.
- Over-privileged tools.
- Huge outputs blowing the context.

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

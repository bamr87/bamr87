---
id: ADP-02
chapter: 2
title: Routing
book_pages: "Ch. 2 (13 pp.)"
status: partial
evidence_repos: [bamr87/law-ai]
last_verified: 2026-10-31
owner_bot: Grok Bot
---
# Routing

## Summary

Routing turns a fixed pipeline into a conditional one: a component inspects the input (or state) and decides which path, tool, or sub-agent handles it next. Gulli describes several ways to decide: ask an LLM to classify, compare embeddings, apply hand-written rules, or use a small trained classifier. The router is usually a coordinator that delegates instead of answering itself. Good routers have a clear set of routes, a well-defined default for inputs they can't place, and logs that show why each route was chosen.

## When to use / not

- **Use** when inputs vary in kind (intent, domain, difficulty, cost tier) and each kind needs a different handler. Also use it for resilience, falling back across providers.
- **Skip** when there is only one meaningful path, or when a deterministic rule already decides the case. In that case don't put an LLM in the loop.

## Failure modes

- Misclassification with no fallback.
- A silent default that hides errors.
- Routing loops.
- LLM-router cost and latency on every request.
- Routes that drift away from their handlers.

## Fleet evidence (bamr87/law-ai @ 0870d4c)

1. **Provider routing/fallback (LLM_PROVIDER_CHAIN).** The default chain is set in [settings/base.py L40](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/settings/base.py#L40) as `claude_code,anthropic_api,xai,ollama`. It is resolved in [router.py L89-135](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/core/llm/router.py#L89-L135) and tried in order in `aroute` [L453-516](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/core/llm/router.py#L453-L516). Tiers with a remembered credential failure are skipped, each attempt is recorded, and `LLMUnavailableError` is raised when every tier fails. Each call is logged with the chain attempted (`_log_call`, [L397-420](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/core/llm/router.py#L397-L420)).
2. **Content routing (rules tier).** `classify` in [playbooks.py L260-300](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/lsat/services/playbooks.py#L260-L300) sends an LSAT question to an archetype playbook in this order: an explicit stamp wins, then cue patterns with priority and concept-overlap tie-breaks, then a primary-concept fallback, then `None` when the case is ambiguous. It is deterministic and makes no model call.

### Reproduce

```bash
T=$(mktemp -d) && git clone -q https://github.com/bamr87/law-ai $T/law-ai && cd $T/law-ai && git checkout -q 0870d4c56ed495a6fad97af33c79885264522c39
cd backend && uv sync -q --managed-python -p 3.13 --all-extras --all-groups
uv run --managed-python -p 3.13 pytest -p no:cacheprovider --no-cov -W ignore \
  tests/lsat/test_revise.py tests/core/test_llm_chain.py tests/lsat/test_playbooks.py
```

Expected: `122 passed` (verified 2026-10-31 on the box; no model calls, providers stubbed). Tests: `tests/core/test_llm_chain.py` (chain order/fallback) and `tests/lsat/test_playbooks.py` (classifier).

## Gaps

- There is no intent router that sends free-form user or matter requests to specialist agents with a confidence-gated fallback. Filed as **https://github.com/bamr87/law-ai/issues/204** (agent:queued, feature, P2).

## Cross-links

ADP-01 Prompt Chaining, ADP-04 Reflection, ADP-05 Tool Use, ADP-12 Exception Handling (provider fallback); constitution §15 testing evidence, #528 kill switches.

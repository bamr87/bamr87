---
id: ADP-14
chapter: 14
title: Knowledge Retrieval (RAG)
book_pages: "Ch. 14 (17 pp.)"
status: partial
evidence_repos: [bamr87/README, bamr87/ragio-ai, bamr87/it-journey, bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Knowledge Retrieval (RAG)

## Summary

Retrieval-augmented generation (RAG) adds a lookup step before the model answers. The question first goes to an outside knowledge base. The system finds the most relevant pieces of text, called **chunks**, and adds them to the prompt. Matching is done with embeddings (numbers that capture meaning), with keyword search, or with both together (**hybrid** search, for example dense vectors plus BM25). The model then answers from that evidence. RAG gives the model fresh and private knowledge, cuts down on made-up answers and, most important, lets the answer carry **citations** to the exact source. Gulli covers chunking, embeddings, vector stores and similarity as the core ideas. He then describes two extensions. **GraphRAG** searches a knowledge graph, which helps with questions about how things relate. **Agentic RAG** adds an agent that checks the sources, settles conflicts between them and searches again, instead of trusting the top few results (ch. 14, "Agentic RAG"). His rule of thumb: use RAG when answers must rest on "specific, up-to-date, or proprietary information" with citations someone can check (ch. 14, "At a Glance").

## When to use / not

- Use it for Q&A over fleet docs, repo context for agents, and support or research bots that must cite sources.
- Skip it when the facts fit in the prompt, or for pure reasoning or transforms. Don't retrieve a stale index without saying it is stale.

## Failure modes

- A stale index.
- Coverage holes (the corpus misses the thing asked about).
- Chunks that cut context.
- Top-k noise.
- Uncited answers.
- No retrieval eval, so tuning is guesswork.

## Fleet evidence

Fleet design: **one read path per site**. Constitution §16.2 requires every content site to expose "a static JSON data API … and their own MCP server, shipped as a local stdio server" ([constitution.md L190](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md#L190)). The kit spec names a per-site `mcp-site/` server with `search`/`read_page` tools ([templates/ai-ready/README.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/templates/ai-ready/README.md)). The README context engine is the fleet-wide retrieval layer, and it-journey is an existing per-site server.

| RAG stage | Implementation | Permalink |
|---|---|---|
| Fleet-wide retrieval over MCP (lexical, term-frequency + prefix expansion; results cite paths) | README `search_context` → `query.search` | [server.py L139-147](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/mcp/server.py#L139-L147), [query.py L87-110](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/scripts/context_engine/query.py#L87-L110) |
| Staleness reporting (index freshness surfaced, not hidden) | `context_status` tool; "one read path" principle | [server.py L193-196](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/mcp/server.py#L193-L196), [PLAN.md L123](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/PLAN.md#L123) |
| Per-site MCP server (content site, §16) | it-journey `search_quests` full-text ranked hits with context | [scripts/quest/mcp_server.py L255-277, L332-342](https://github.com/bamr87/it-journey/blob/64826f271595d893029839d32bc32dd5883c1392/scripts/quest/mcp_server.py#L255-L277) |
| Full RAG: chunking into timestamp windows | ragio-ai `build_windows` | [chunk.py L16-45](https://github.com/bamr87/ragio-ai/blob/45469526b92072132cf85f282683ed84379f0858/ragio/chunk.py#L16-L45) |
| Hybrid dense + BM25 retrieval (Qdrant) | `vector_store` / `retriever` | [index.py L42-47](https://github.com/bamr87/ragio-ai/blob/45469526b92072132cf85f282683ed84379f0858/ragio/index.py#L42-L47), [rag.py L54-62](https://github.com/bamr87/ragio-ai/blob/45469526b92072132cf85f282683ed84379f0858/ragio/rag.py#L54-L62) |
| Neighbor expansion + overlap merge (fixes chunks that cut context) | `retrieve`, `_merge_overlaps` | [rag.py L65-113](https://github.com/bamr87/ragio-ai/blob/45469526b92072132cf85f282683ed84379f0858/ragio/rag.py#L65-L113) |
| Augmentation with labelled, timestamp-cited evidence under a char budget | `build_prompt` | [rag.py L116-137](https://github.com/bamr87/ragio-ai/blob/45469526b92072132cf85f282683ed84379f0858/ragio/rag.py#L116-L137) |
| Retrieval eval (hit@1/3/5) | `run_eval` over `eval/questions.jsonl` | [evaluate.py L17-31](https://github.com/bamr87/ragio-ai/blob/45469526b92072132cf85f282683ed84379f0858/ragio/evaluate.py#L17-L31) |

### Reproduce

```bash
git clone -q https://github.com/bamr87/README /tmp/readme && cd /tmp/readme && git checkout -q d4ea571b470cc826ff8ab10323e3aff68f64111d
python3 -m pytest -q tests/unit/test_cases/test_context_engine.py      # incl. test_search_* (L570-580)
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_context","arguments":{"query":"bashcrawl","limit":2}}}' | python3 mcp/server.py
printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_context","arguments":{"query":"ragio","limit":2}}}' | python3 mcp/server.py
```

Expected (run 2026-10-31): `63 passed`. The `bashcrawl` query returns `card:bashcrawl`, score 62, path `context/cards/bashcrawl.md`. The `ragio` query returns **"no matches in the context layer"** (coverage gap below). Green CI: README [CI 41174877803](https://github.com/bamr87/README/actions/runs/41174877803); ragio-ai [CI 41227047769](https://github.com/bamr87/ragio-ai/actions/runs/41227047769) (lint/standards only, no retrieval tests). ragio-ai retrieval needs Qdrant + Ollama + an indexed corpus, so it was **not run here**; its evidence is code only.

## Gaps

1. **GAP: fleet retrieval is lexical only.** Embedding retrieval behind the same `search_context` contract is listed as future work ([PRD.md L110](https://github.com/bamr87/README/blob/d4ea571b470cc826ff8ab10323e3aff68f64111d/PRD.md#L110)). → [bamr87/README#47](https://github.com/bamr87/README/issues/47).
2. **GAP: index coverage.** `context_status` reports only 7 projects (generated 2026-10-26 03:14 UTC = Oct 25, 9:14 PM MDT). Fleet repos such as ragio-ai are not searchable. → [bamr87/README#47](https://github.com/bamr87/README/issues/47).
3. **GAP: second-brain store (`brain.db` + `mcp/server.py` memory/RAG server) is not implemented** in any repo checked (shared with ADP-08) → [bamr87/README#46](https://github.com/bamr87/README/issues/46).
4. **GAP: per-site MCP kit is spec-only.** `templates/ai-ready/` holds only README + VERSION, and `tools/aieo/` is absent, so §16 per-site MCP servers are hand-built per repo (it-journey). → [bamr87/bamr87#547](https://github.com/bamr87/bamr87/issues/547) (needs-amr; related #495).
5. **GAP: no runnable retrieval eval in CI.** ragio-ai has 3 eval questions and no tests. README has no retrieval-quality eval. → [bamr87/ragio-ai#3](https://github.com/bamr87/ragio-ai/issues/3).
Future work (not a gap): Agentic RAG / GraphRAG. Nothing implements a re-query loop or a graph store, and the README PRD lists a relationship graph as future work. It is not required by any fleet standard, so no issue is filed.

## Cross-links

ADP-08 Memory (long-term memory = this retrieval layer), ADP-10 MCP / tool use, ADP-19 evaluation; constitution §16 (AI-ready, per-site MCP), §14 (`llms.txt`), §15 testing evidence.

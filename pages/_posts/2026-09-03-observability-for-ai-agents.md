---
title: "Giving Your AI Agents a Flight Recorder"
date: 2026-09-03
categories:
    - ai
    - observability
tags:
    - claude-code
    - opentelemetry
    - openinference
    - phoenix
    - sqlite
    - observability
excerpt: You cannot improve what you cannot measure, and AI agents are the least-instrumented software most teams now run. Here is how I built a two-plane trace pipeline for Claude Code — and the two silent bugs it exposed.
draft: true
---

We have spent decades learning to instrument software. We have metrics, traces, structured
logs, and an entire industry built on the premise that production behaviour must be
observable. Then we handed our codebases to AI agents and, for the most part, went back to
reading scrollback.

That is the gap I set out to close this week: capture every Claude Code session — the ones I
run at my terminal *and* the ones GitHub Actions runs unattended at 3am — into something I
can query, cost, and review.

## The two-plane problem

The first useful insight is that "Claude runs" is not one population. It is two, and they
live in completely different places:

| | Local plane | CI plane |
| --- | --- | --- |
| Where it runs | My laptop | GitHub Actions runners |
| What it leaves behind | `~/.claude/projects/*.jsonl` | Workflow run logs |
| How you read it | Parse the transcript | Scrape `claude-code-action`'s output |
| Lifetime | Until I clean my home dir | 90 days, then GitHub deletes it |

My control plane already extracted the CI half into a local SQLite lake. The local half had
a pipe — read the JSONL, build spans, ship to a trace viewer — and **kept nothing**. Which
meant that answering "what did I spend on this repo last month" required the trace viewer to
be running, and answering it *offline* was impossible.

The general lesson, and it is not specific to AI: **a pipe is not a pipeline.** If your
extraction step has no durable landing zone, every question you might later want to ask has
to be anticipated *now*, while the data is briefly in memory. Land the data first. Analyze it
second. The split is what makes the analysis reproducible.

```text
GitHub Actions ──┐
                 ├──▶  fleet.sqlite  ──▶  review (offline)
~/.claude/*.jsonl┘                   └─▶  OpenInference spans ──▶ Phoenix
```

## Idempotency is harder than it looks

An agent transcript is an **append-only file that is still being written**. Yesterday's
session had 13 turns; today, because I resumed it, it has 22. Re-extracting has to be safe.

There are three plausible designs and only one is right:

1. *Insert everything, every time.* Duplicates on every run. Obviously wrong.
2. *Insert only what is new.* Requires knowing what "new" means, and a transcript can be
   rewritten, not just extended.
3. *Replace the session's rows wholesale.* The rows always mirror the file. Correct.

I went with (3), plus an mtime check so unchanged transcripts are skipped entirely. The test
that matters is not "does re-running produce the same count" — it is **"does re-running a
*shortened* transcript shrink the table"**. If it does not, you are accumulating history and
calling it state.

```python
conn.execute("DELETE FROM session_turns WHERE key=?", (key,))
conn.execute("DELETE FROM session_tools WHERE key=?", (key,))
```

## OpenInference: don't invent a schema

There is a real temptation, when you have agent data, to design your own tables and your own
dashboards. Resist it. **OpenInference** is an OpenTelemetry semantic convention for LLM
applications — it standardises the attribute names for model, token counts, cost, tool calls,
and the span kinds (`AGENT`, `LLM`, `TOOL`, `CHAIN`) that describe an agent's shape.

Emit those names and every tool that speaks the convention — Arize Phoenix, in my case —
gives you cost breakdowns, latency percentiles and trace trees for free. You write an
exporter, not a UI.

One detail worth stealing: **derive your trace and span IDs deterministically**, as a hash of
a stable key.

```python
def det_id(key: str, nbytes: int) -> int:
    # never zero: 0 is the invalid trace/span id in OTel
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:nbytes], "big") or 1
```

Now re-exporting is an *upsert* at the trace store rather than a duplicate. Idempotency at
both ends of the pipe. I used that same key as the primary key in SQLite, so a stored session
row and its trace are joinable — the analysis and the visualisation can never disagree about
what they are describing.

## The two bugs, and why they are the same bug

Building this turned up two defects. Neither had ever thrown an error.

**One.** The pricing table had no row for the current default model. `cost_usd()` returned
`0.0` for unpriced models, so every session on that model costed to **zero dollars** — on a
page whose entire purpose is tracking AI spend. It had been quietly under-reporting for weeks.

**Two.** A capability probe used `importlib.util.find_spec("ruamel.yaml")` to detect an
optional dependency. On a *dotted* name, `find_spec` imports the parent package first and
**raises** `ModuleNotFoundError` if it is missing — the precise condition the probe existed
to detect. The endpoint returned a 500 on exactly the machines it was written to serve.

Both are the same failure mode: **a default that silently substitutes for an answer.** `0.0`
for "I don't know the price". An exception where `False` was meant. Neither is loud, so
neither gets fixed until someone stares at the number and thinks *that can't be right.*

The durable fix is not just the missing row — it is making the gap **speak**:

```python
unpriced = [m for m in models_seen if normalize_model(m) not in PRICING]
if unpriced:
    findings.append({"severity": "warn",
                     "detail": f"{', '.join(unpriced)} — counted but costed at $0, "
                               "so every total below understates spend"})
```

A system that reports *"I am missing a price for this model"* is worth far more than one that
confidently reports `$0.00`. When you write a fallback, ask what happens if it fires forever.

## Working with AI on this kind of task

A few things that made the collaboration productive, beyond the usual "give good context":

**Make the agent find the prior art first.** My opening move was not "write an extractor", it
was reading the 1,332-line module that already existed. It turned out ~70% of the job was
done; the actual gap was narrow and specific. An agent that starts writing immediately will
happily build you a parallel system next to the one you already have.

**Refactor under existing tests, before adding anything.** I needed shared parsing helpers
between the new extractor and the old exporter. I extracted them and ran the existing suite
*first* — nine tests green — establishing the refactor was behaviour-preserving before a
single new line depended on it. Cheap, and it turns "did I break the exporter?" from a worry
into a fact.

**Let the test fail before you trust it.** One of my new assertions failed. My instinct was
to fix the code — but the code was right: a streamed turn's *final* usage message carries the
complete totals, so it replaces the earlier partial one wholesale. My assertion encoded a
guess about the data format. I fixed the test and wrote the reasoning into a comment. **When
a test fails, one of two things is wrong, and it is not always the code.**

**Verify on real data, not just fixtures.** Fixtures confirm the logic you thought of. Running
the extractor against the live transcript of the very session doing the work caught the $0
pricing bug instantly — a number no fixture would have questioned. The arithmetic checked out
end to end: 45 turns + 57 tool calls + 1 root span = 103 spans exported.

**Push back on your own "fixes".** Mid-session I "corrected" a model's price, then noticed a
comment three lines up explaining that the existing value was a deliberate choice for
comparability over time. I reverted it. An agent reading a table without reading the prose
around it will make that mistake every time — and so will a human in a hurry.

## What this gets you

```bash
$ dash lake sessions     # extract the local plane
$ dash lake sync         # extract the CI plane
$ dash lake review       # analyze both, offline

Claude activity review — last 30d
  total: $6.52 · 45 turns · 1 traces (1 not yet in Phoenix)
  top tools: Bash×57(1✗), Skill×1
  findings
    · [both] traces not shipped to Phoenix — 1 session has no export ledger entry
```

Cost per repo. Which tools fail most. Which CI agent runs hit permission denials — a signal
that the allowlist is narrower than the prompt needs. How much of my prompt spend came from
cache, which is the difference between an expensive agent and a cheap one.

None of that is exotic. It is the same observability discipline we would apply to any other
production workload. Agents have simply not been getting it — and if you are letting them
open pull requests while you sleep, that is a strange place to have a blind spot.

*The implementation is open source in my monorepo's control plane, in `fleet_lake.py`.*

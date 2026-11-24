# Cheap typed-decision layers routed by confidence

> Five open-source reference patterns for a cheap typed-decision layer routed by confidence, checked 21 November 2026.

Research brief for a typed-decision design draft in `bamr87/bamr87` under `docs/`.  
Read-only. No GitHub writes, issues, PRs, comments, or posts.  
Checked Saturday, 21 November 2026, America/Chicago (CST).

The Jev Engineering audit canvas (read via ReadCanvas; the public `cursor.com/canvas/...` URL is login-gated) already marks the four gaps this brief is meant to fill as **Missing**: calibrated confidence (#3), typed questions with an `other`/`none` exit (#4), a shadow week then band-by-band promotion (#13), and cheap done-checks so a loop can stop itself (#18). Escalation today is by conflict size, not confidence; turn and dollar caps stop a run, not “the work is already done.” This brief does not recommend buying TypeSafe’s Jev model. It recommends open-source patterns that can sit behind the existing loop runner without replacing `tools/jev/classify.py`.

## The five reference patterns

### 1. Two-threshold confidence bands, with abstention in the middle

**Sources.** MAPIE `BinaryClassificationController` ([docs example](https://mapie.readthedocs.io/en/latest/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/), [repo](https://github.com/scikit-learn-contrib/MAPIE)); Tian et al., “Just Ask for Calibration,” EMNLP 2023 ([ACL](https://aclanthology.org/2023.emnlp-main.330/), [arXiv:2305.14975](https://arxiv.org/abs/2305.14975)); “verbalization logprobs,” ACL Findings 2026 ([PDF](https://aclanthology.org/2026.findings-acl.1671.pdf)); optional scorer: open-source [cleanlab/tlm](https://github.com/cleanlab/tlm) (a stronger variant of BSDetector, Chen & Mueller, [ACL 2024](https://aclanthology.org/2024.acl-long.283/)). Self-consistency vote share is a cheap extra signal when a question is worth multiple samples (Wang et al., [arXiv:2203.11171](https://arxiv.org/abs/2203.11171)).

**Mechanism.** Do not treat a raw “I am 90% sure” string as a probability. Tian et al. show verbalized confidence can be *better* than token logprobs on RLHF models, but the 2026 Findings paper shows vanilla verbalization is extremely sparse (one model “verbalizes only eight unique confidence values on SST-2, with over half being exactly 95%”) and that weighting the digit tokens by logprobs (“verbalization logprobs”) “addresses sparsity and achieves the best AUARC (+2.3 points over vanilla verbalization) without incurring additional inference cost.” Then *calibrate* that score on labeled data. MAPIE’s LLM-as-judge example is the right control surface: two thresholds on the same score, not one.

> “if the score is below the lower threshold, the answer is classified as ‘not hallucinated’; if the score is above the upper threshold, the answer is classified as ‘hallucinated’; if the score is between the two thresholds, the judge abstains.”  
> — MAPIE, Risk Control for LLM as a Judge with Abstention

In their worked example, naive single-cut thresholds met a 0% abstention rate but missed the precision target on held-out data; risk-controlled thresholds `(0.40, 0.50)` held precision with about an 8% abstention rate.

**Applies to the fleet.** A typed-decision layer should return `{choice, score, distribution}` and route on *bands*, not a single cutoff: auto-act only in the high band, escalate the middle band to current Claude with a reason slot, and treat the low band (or `other`) as human. Fit the two cuts on shadow labels so that “90%” is actually right about 90% of the time. Log the raw score, the calibrated score, both thresholds, and which layer answered. Do not adopt Cleanlab’s hosted TLM API as a dependency; if a cheap scorer is needed, the open `cleanlab/tlm` algorithm or a tiny regression head like FrugalGPT’s DistilBERT scorer is the OSS path.

### 2. Typed question schemas that always include an `other` / `none` escape

**Sources.** Instructor for PHP, “Always include a fallback option” ([docs](https://docs.instructorphp.com/packages/instructor/techniques/classification)); Python Instructor `Literal` / `Enum` ([docs](https://python.useinstructor.com/concepts/types/)); ohmeow on mapping unrecognized values onto `OTHER` ([post](https://ohmeow.com/posts/2024-07-06-llms-and-enums.html)); Claude Code `AskUserQuestion` ([tools reference](https://code.claude.com/docs/en/tools-reference)); LangGraph `interrupt(..., response_schema=...)` ([interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [MCP elicitation](https://docs.langchain.com/langsmith/server-mcp-elicitation)); Outlines constrained `choice` / JSON enums ([docs](https://dottxt-ai.github.io/outlines/reference/generation/generation/)). DSPy 2.6 replaces `Assert`/`Suggest` with `BestOfN` / `Refine` plus a `reward_fn` and `threshold` ([docs](https://dspy.ai/current/tutorials/output_refinement/best-of-n-and-refine/)).

**Mechanism.** Constrain the model to a closed list, but never make the list exhaustive. Instructor’s classification guide is explicit:

> “Adding an `OTHER` or `UNKNOWN` case gives the model an escape hatch when the input does not fit neatly into your predefined categories. Without it, the model is forced to pick an incorrect label.”

Claude Code hard-wires the same idea into the human UI: “Answer by picking an option, or type your own text through the `Other` row or the notes field.” LangGraph can pause and validate the resume value against a Pydantic / `Literal` schema (`langgraph>=1.2.12`), so a `Choice` model can be `option: Literal["keep", "rewrite", "other"]` plus an optional `details` field. Outlines can *guarantee* a listed token is emitted, so `OTHER` must be in the choice set or the model cannot say it. ohmeow’s `BeforeValidator` that maps unknown strings onto `OTHER` is the right defensive default when the provider is not constrained.

**Applies to the fleet.** Every pick-from-a-list call (intake type, next tool, source relevant, command safe, task done) should be a versioned schema with criteria and a required `other`/`none` member. Never auto-route `other`; pass the first guess along and, if two layers disagree, show both answers. Hash and eval the question the same way step specs are already pinned.

### 3. Shadow-mode silent labels, then promote one confidence band at a time

**Sources.** Mohinee Indurkar, “Shadow mode: earning a skeptical team’s trust…” (17 September 2026, [post](https://mohinee.github.io/2026/shadow-mode-earning-trust/)); FrugalGPT cascade thresholds ([paper](https://arxiv.org/abs/2305.05176), [repo](https://github.com/stanford-futuredata/FrugalGPT)); RouteLLM threshold calibration ([repo](https://github.com/lm-sys/RouteLLM), [paper](https://arxiv.org/abs/2406.18665), [blog](https://www.lmsys.org/blog/2024-07-01-routellm/)). Label Studio and Argilla are useful for *review queues*, not as a promotion engine: Label Studio pre-annotates and can “Auto accept annotation suggestions” in interactive image labeling ([guide](https://labelstud.io/guide/ml.html)); Argilla attaches scored suggestions that annotators still submit ([docs](https://docs.argilla.io/latest/how_to_guides/annotate/)). Neither Community product implements “shadow for a week, then lower the threshold one band.”

**Mechanism.** The model sees live traffic and writes a label, confidence, and metadata. Nothing it produces is served. A human (or the current Claude path) still decides. After enough real cases, pick the *lowest* auto-accept threshold whose precision *lower bound* still clears the target, with a minimum sample size. Indurkar’s script uses a 95% Wilson interval; in the worked table a 0.95 slice “looks like 97%” on 168 cases, but the lower bound is 93%, so the script refuses that cut and starts at 0.90, automating about 11% of cases. Then keep sampling the auto-accepted slice, and re-run the picker when the model, prompt, or traffic drifts.

FrugalGPT and RouteLLM are the same idea on the *model* axis: accept a cheap answer only above a learned threshold, otherwise escalate. FrugalGPT, on HEADLINES with a DistilBERT scorer: “If the score of this [GPT-J] answer is greater than 0.96, the answer is accepted… Otherwise, J1-L is queried. J1-L’s answer is accepted if its score is greater than 0.37; otherwise, GPT-4 is invoked.” RouteLLM instead scores the *query* before generation and calibrates the cut to a target strong-model percentage (`calibrate_threshold --strong-model-pct 0.5`).

**Applies to the fleet.** Run the cheap classifier in silent parallel with today’s Claude / `$0` path for a shadow week (or until unusual cases appear). Automate only the high band first. Promote the next band only after the lower bound still holds. Rehearse / dry-run is not this: those preview a change, they do not accumulate agreement statistics. Treat a prompt or model-id change as a new model: re-shadow before it takes traffic.

### 4. Confidence cascade: code, then a cheap classifier, then a stronger model with a reason, then a human

**Sources.** FrugalGPT (above); RouteLLM (above). This is the article’s cascade, already half-built in the hub as conflict tiers 0–3, except `auto_tiers` is still `[tier0]` and the ladder is sized by conflict, not by probability.

**Mechanism.** FrugalGPT: “LLM cascade sends a query to a list of LLM APIs sequentially. If one LLM API’s response is reliable, then its response is returned… It returns the generation if the score is higher than a threshold τᵢ, and queries the next service otherwise.” The scorer can be “a simple regression model that learns whether a generation is correct from the query and a generated answer.” RouteLLM is the pre-generation counterpart: `calculate_strong_win_rate(prompt)` vs a calibrated cost threshold, with no second generation if the weak model is enough.

**Applies to the fleet.** Keep exact rules in `classify.py`. Add a bounded classifier for pick-from-list steps. If its calibrated score is below the current band, escalate to pinned Claude *with a reason slot*. If both are unsure, or the choice is `other`, hand off to a human and show both answers. Do not put irreversible actions (send, pay, publish, delete, permissions) on this ladder at all.

### 5. Cheap, deterministic done-checks; a judge only when the evidence is not mechanical

**Sources.** OpenHands Stop hooks ([hooks guide](https://docs.openhands.dev/openhands/usage/customization/hooks), [SDK `on_stop.sh`](https://github.com/OpenHands/software-agent-sdk/blob/main/.openhands/hooks/on_stop.sh)); OpenHands `/goal` judge ([goal loop](https://docs.openhands.dev/sdk/guides/convo-goal)); Aider lint/test gates ([docs](https://aider.chat/docs/usage/lint-test.html)); Ralph Loop completion promises ([plugin README](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/ralph-loop/README.md), [Huntley](https://ghuntley.com/ralph/)); SWE-agent `while not step_output.done` plus `submit` / `exit` ([docs](https://swe-agent.com/latest/reference/agent/)); Reflexion, stop when the evaluator passes or `max trials` is hit ([repo](https://github.com/noahshinn/reflexion), [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)). LangGraph `recursion_limit` ([GRAPH_RECURSION_LIMIT](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)) is a safety cap, analogous to the fleet’s turn/dollar caps, not a done-check.

**Mechanism.** The cheap pattern is a hook that runs when the agent tries to finish and can *deny* the stop. OpenHands: “A `Stop` hook can force the agent to keep working if linting checks haven't passed yet,” by printing `{"decision": "deny", "reason": "..."}` and exiting `2`. Aider does the same mid-edit: `--auto-lint` is on by default; `--auto-test` plus `--test-cmd` re-invokes the model on a non-zero test exit. The OpenHands `/goal` loop is the *paid* check: after `FinishAction`, a second LLM returns `{score, complete, missing}` and “the agent cannot finish just by claiming success — the judge has to see the green output first,” with parse failures conservatively treated as `complete=False`. Ralph’s `<promise>COMPLETE</promise>` is only a stop *signal*; the official README says the technique is good for “Tasks with automatic verification (tests, linters)” and always wants `--max-iterations` as the escape hatch. Use a promise only *after* the cheap gate is green.

**Applies to the fleet.** After each loop turn, run a cheap, code-level done-check first: tests green, required file exists, issue already has the expected label, PR already opened, acceptance criteria in the step spec all true. If that check is decisive, stop (or refuse to stop) without spending another model call. If it is ambiguous, ask a typed “is this done?” question with `done` / `not_done` / `other` and route on confidence. Keep turn and dollar caps as the recursion-limit backstop so a loop cannot burn the budget after the work is finished, and cannot spin forever if the check never goes green.

## Supporting notes

**Confidence methods, ranked for a cheap layer.** (1) Constrained enum + a numeric `confidence` field, then calibrate on labels (temperature scaling or MAPIE). (2) Verbalization logprobs when the API returns token logprobs, to unsparsify a verbalized percent. (3) Self-consistency vote share when a decision is worth N cheap samples; Wang et al.: “if multiple reasoning paths lead to the same answer, we have greater confidence that the final answer is correct.” (4) A tiny dedicated scorer (FrugalGPT’s DistilBERT, RouteLLM’s `mf` router, or open TLM/BSDetector) trained or evaluated on *this* decision’s shadow log. Fine-tuning verbalized confidence (e.g. [ConfTuner](https://github.com/liushiliushi/ConfTuner)) is more than this layer needs at the start.

**What not to copy from labeling tools.** Label Studio Community “can manually sort tasks and retrieve predictions to mimic an active learning process”; auto-accept of suggestions is a UI convenience, mainly documented for image regions, not a statistically defended promotion of a confidence band. Argilla suggestions carry scores you can filter on, but submission stays human. Implement promotion from the shadow log, not from a labeling product’s default button.

**Name collision.** The hub’s JEV engine (conflict numbering, loop specs, isolation) is not TypeSafe AI’s Jev model. Patterns above are the engineering layer the audit already recommended putting behind the existing runner.

## Link check (curl `-L`, 21 November 2026, CST)

All of the primary sources cited above returned HTTP 200, including papers, official docs, and repos. Two URLs did not:

- The audit canvas `https://cursor.com/canvas/store-ecae274f-8a58-44f1-9d6f-1810735ef947/8d41f03d-8f98-400d-8b31-86a320614b50` redirects to Cursor login (403 to an unauthenticated fetch). The page was read successfully with ReadCanvas.
- The TMLR PDF on OpenReview (`https://openreview.net/pdf?id=cSimKw5p6R`) returned 403 to this fetch. The same FrugalGPT paper is available at [arXiv:2305.05176](https://arxiv.org/abs/2305.05176) (200).

## Out of scope

No GitHub mutations. No vendor trial. No constitution amendment drafted here. A later mandate that every pick-from-list call must use a calibrated classifier would extend constitution § 13 and would need Amr’s explicit OK.

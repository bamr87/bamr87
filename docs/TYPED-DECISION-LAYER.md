# Cheap typed-decision layer

> Design draft: a cheap, typed, confidence-routed decision slot for JEV loops. A pinned cheap model (Haiku, already on the allowed list) answers Choice, Score and Noul questions with a required other-or-none exit; two calibrated thresholds create an abstention band; exact rules stay in `tools/jev/classify.py`. Off by default, then shadow, then one confidence band at a time. The hub's JEV engine is not TypeSafe AI's Jev model.

**Status: Design draft / proposed.** Nothing here is implemented. This branch is documentation only; no pull request has been opened. Written 21 November 2026, America/Chicago (CST), at the maintainer's request on a voice call, after the 8 November fleet audit of [How to Cut Your Agent Bill by 90% With Jev Engineering and Kimi K3](https://x.com/Mr_Buzzoni/status/2104783226833186920).

The audit's recommendation stands: adopt the *pattern*, not the vendor. Do not replace [`tools/jev/classify.py`](../tools/jev/classify.py). Adding TypeSafe Jev, or any other new model, to `_data/fleet.yml` `ai_models.allowed` is a gated change (constitution § 12.3 and § 13.3). Mandating the layer for every pick-from-list call fleet-wide would extend constitution § 13 and needs an amendment.

## Related work (do not invent ids)

| Artifact | Role |
| --- | --- |
| [HUB-088](../features/features.yml) (planned) | "Typed decisions gate the pipeline": lockfile, traces, trim and verify loops. Docs: [docs/prd/AGENTIC-SDLC.md](prd/AGENTIC-SDLC.md). Decision: [ADR 0008](adr/0008-typed-decisions-as-pipeline-gates.md) (accepted, PR #745, 6 November 2026). |
| [FR86](../PRD.md), [FR87](../PRD.md), [FR88](../PRD.md), [NFR17](../PRD.md) | Existing requirements this design must satisfy: consume decisions only through the typed-decision path against `_data/decisions.yml`; write a replayable trace; shadow-then-promote trims; fail closed on a miss, a timeout or `other`. |
| [FR133](../PRD.md) | A typed decision may run on an enrolled on-premise node only when that model is pinned under a local provider in `ai_models.allowed` and its evals pass. |
| Epic [#737](https://github.com/bamr87/bamr87/issues/737), phase A2 [#740](https://github.com/bamr87/bamr87/issues/740) | The CI-side node, still on `agent:hold`. This draft does not start those issues. |
| Proposed `HUB-NEW:typed-decision-layer` | The *loop-side* layer this page specifies — calibration, the two-threshold cascade into existing JEV loops, deterministic done-checks, and shadow-band promotion. Declared in [`features/features.d/typed-decision-layer.yml`](../features/features.d/typed-decision-layer.yml) with `FR-NEW` / `NFR-NEW` placeholders. The compiler assigns numbers on `main`; this branch does not pick them. |

HUB-088 remains the pipeline feature. This feature shares its lockfile schema and trace shape, and extends the same primitive into the loop runner without changing what HUB-088 already promised.

## 1. Outcome, in one paragraph

A pick-from-a-list step in a JEV loop — intake type, next tool, source relevant, command still on the allowlist but unusual, or "is this turn's work done" when the mechanical checks are inconclusive — is asked as a versioned, hashed, typed question against a trimmed state pack. Code answers first. If the question is still open, a cheap pinned model returns a choice, a full distribution and a calibrated score. Auto-act only in the high band. Abstain in the middle and escalate to the current stronger model with a reason slot. Treat the low band, `other`/`none`, a model error and any irreversible action as a human's. The current path keeps deciding until a shadow log, a Wilson lower bound and a minimum sample size justify promoting one band. Turn and dollar caps stay the backstop; they are not the done-check.

## 2. Name collision and prior art (§ 10.8)

**JEV** in this repo is the hub's agent logic engine: conflict-free numbering, the deterministic classifier, loop step specs, the local runner and harness refinement ([docs/JEV.md](JEV.md), [tools/jev/README.md](../tools/jev/README.md)). **TypeSafe Jev** is a third-party decision-only model named in the article and in ADR 0008. They are not the same thing. This design never uses "Jev" alone for the vendor model.

ADR 0008 already recorded the build-versus-adopt call for the *pipeline* node: evaluate TypeSafe Jev offline on fleet history (epic phase A0, [#738](https://github.com/bamr87/bamr87/issues/738)), keep `claude -p` as the fallback, and do not take the vendor as a dependency until that spike says yes. This draft does not reopen A0 and does not add a vendor. The cheap executor proposed here is `claude-haiku-5-5`, which is already the cheapest exact id in `ai_models.allowed` and already the JEV tier-1 model. TypeSafe Jev, or any other calibrated specialist, may later sit behind the same schema as an optional executor if the maintainer gates it onto the allowed list after evals pass (§ 13.4).

The 8 November audit scored 22 article practices as 5 incorporated, 11 partial, 6 missing and 0 in progress. This layer is aimed at the missing six (calibrated confidence, typed questions with an exit, no auto-route of `other` plus dual-answer review, a shadow week, cheap done-checks, vision/PDF escalation) and at the partial cascade, per-action thresholds, decision logs and per-request routing. A Researcher's brief of 21 November (CST) added five open-source patterns, folded in below and cited in [References](#references).

## 3. Typed question schema

Three question types, taken from the article and already named in ADR 0008 (`choice`, `score`, `yesno`). This draft keeps the article's type names in the schema, and maps `noul` to ADR 0008's `yesno` so one lockfile can serve both the pipeline and the loops.

| Type | Asks | Returns | Rules |
| --- | --- | --- | --- |
| `choice` | Pick one of the listed options | `choice`, a probability for every option (they sum to 1), `confidence` | Required `other` or `none` member. Up to a documented cap (the article's 255 is a vendor limit, not ours). |
| `score` | Place the input on an ordered rubric | `score` (may land between levels) and the distribution | 2 to 10 levels. Every level is written so it stands alone — never "worse than the previous." |
| `noul` | Yes or no | `noul`, the probability of *yes* | 0.5 means the model cannot tell, never a vague "medium." Phrase the question so a high number means yes. A required exit is the third label `other` when "yes or no" does not apply (see done-checks). |

### 3.1 Required other-or-none exit

Every `choice` includes a required `other` or `none` option, written as a situation ("none of the above fits"), not a mood. This is also the Instructor classification rule, the always-present Other row in Claude Code's `AskUserQuestion`, and the reason a LangGraph `Literal` schema includes `"other"`. Constrained decoders (Outlines and similar) can only emit a listed token, so the exit has to be *in* the list. A defensive validator maps an unrecognized string onto `other` rather than crashing or guessing.

**`other` is never auto-routed.** The first layer's guess is passed to the next layer as context. If both layers are unsure, or they disagree, both answers are shown in the human review queue. This is article concept 10, and it is stricter than a bare `jev:needs-human` label.

### 3.2 Question-writing craft

Most bad answers start as a bad question. The article's rules, kept here as the playbook HUB-088 did not yet write:

- The question id is never sent to the model. Meaning lives in `instructions` and `criteria`.
- One judgment per question. Split "is this urgent and from a paying customer" and combine the answers in code.
- Describe situations, not degrees. "Mentions cancelling or a chargeback" is checkable; "very frustrated" is not.
- Point at exact fields with backticked paths (`order.charges`, `pack.lake_issues`). Per-question field pointers are how the already-incorporated context pack ([`tools/jev/context.py`](../tools/jev/context.py), 16,000-character cap, redaction, priority trim) becomes a first-class input, rather than a single blob.
- Filter state in code first. Send evidence, not "the research looks mostly done."
- Turn extraction into selection. The layer cannot invent a value that is not in the schema. If a vendor name is needed, pass the known list and ask it to pick, with `other`.
- Questions in one call are evaluated in parallel against the same state (speculative fan-out). They cannot read each other's answers. If a later question depends on new evidence, fetch it and ask again. Unrelated questions do not share a call.

### 3.3 Versioning, hashing, lockfile

Questions are treated like step specs (constitution § 13.1–13.4, the existing `JEV_STEP_SHA256` pin). Each decision is an entry in `_data/decisions.yml` (`schema: decisions/v1`), the lockfile ADR 0008 and FR86 already require:

- `id`, `kind` (`choice` / `score` / `noul`), `instructions`, `criteria` or `rubric`, `fields` (pointers into the trimmed pack), `threshold_low`, `threshold_high` (see [§ 4](#4-confidence-calibration)), `conservative` (the branch taken in the abstention or failure case), `consumers`, `risk` (§ 13.6 tag), `fingerprint` (a hash of the fields that change behaviour, written by `python3 -m tools.jev decisions lock`).
- A change to criteria is a change to production behaviour. It is versioned, tested on the labelled set, and rolled back when it drifts. A changed fingerprint is a new policy; replay refuses to compare traces across fingerprints unless explicitly asked (FR87).
- Loop questions are hashed the same way. The runner records the fingerprint beside the step-spec hash so an eval regression names both.

The first *loop* questions (pipeline questions stay those listed in AGENTIC-SDLC § 4.1):

| id | kind | When it is asked | Conservative branch |
| --- | --- | --- | --- |
| `intake-type` | `choice` | Issue-pipeline tier 1, where `evals/t1-intake` already labels type and exit | `other` (leave to the current model path / a human) |
| `loop-done` | `noul` with an `other` exit (`done` / `not_done` / `other`) | After each loop turn, *only* when the deterministic done-check is inconclusive | `other` (keep going under the turn cap, or hand to a human if the cap is close) |
| `source-relevant` | `noul` | When a loop is about to spend a frontier turn on a retrieved source | `other` (include the source; do not drop evidence automatically) |
| `command-unusual` | `noul` | A command that is on the allowlist but not in the common set (audit concept 16) | `other` (do not run; surface for review). Allowlists and denylists stay in code. |

Start with one high-frequency decision, as the article advises. The audit recommended issue-pipeline intake or in-loop "is this done." Those two are the proposed pilots.

## 4. Confidence calibration

The target is honest probabilities: answers given 90% should be right about 90% of the time *on this fleet's labelled data*. Individual answers can still be wrong; the number tells the router which ones to act on. Haiku is not a model trained for calibrated decisions (ADR 0008 already noted that a sampled Claude answer is a convention, not a measurement). Calibration is therefore a *harness* property, not something we assume from the vendor card.

### 4.1 How to get a score from the cheap model

In preferred order, from the 21 November research brief:

1. **Constrained enum plus a numeric `confidence` field**, with the full distribution over options. This is the schema the lockfile already describes.
2. **Verbalization logprobs**, when the API returns token logprobs. Tian et al. (EMNLP 2023) found verbalized confidence can beat raw token logprobs on RLHF models, but ACL Findings 2026 showed vanilla verbalized percents are extremely sparse (one model used only eight values, and more than half were exactly 95%). Weighting the digit tokens by their logprobs unsparsifies the number at no extra inference cost. Use this whenever logprobs are available for the verbalized score; do not trust the raw "I am 90% sure" string.
3. **Self-consistency vote share** when a decision is worth several cheap samples (Wang et al.). Agreement across samples is an extra signal, not a replacement for (1) or (2).
4. **A tiny dedicated scorer** (FrugalGPT's DistilBERT-style regression head, RouteLLM's router, or the open `cleanlab/tlm` algorithm) trained or evaluated on *this* decision's shadow log, only if (1)–(3) cannot hold a reliability target. Do not take Cleanlab's hosted API as a dependency.

### 4.2 Two thresholds, abstention in the middle

A single cutoff is not enough. MAPIE's LLM-as-judge controller places two thresholds on the same calibrated score:

- below the *lower* cut: treat as the conservative / negative branch (or "not confident enough to act");
- above the *upper* cut: auto-act on the model's choice, provided that choice is not `other`;
- between the two: the judge *abstains* and the cascade moves to the next layer.

MAPIE's worked example found that naive single-cut thresholds could show 0% abstention and still miss a precision target on held-out data; risk-controlled pairs such as `(0.40, 0.50)` held precision with a small abstention rate. Starting numbers for this fleet, until shadow data replaces them, follow TypeSafe's published *examples* (not defaults) and ADR 0008: a high-band floor around 0.90 before a routine act, 0.95 before anything that skips work or tightens or loosens a gate, and no automatic act at all on a § 13.6 high-risk / irreversible path. Per-action cuts are higher for anything destructive. The cuts live in the lockfile, not in a workflow file, and they move only from missed-failure or mis-route data, by a gated PR (§ 12.3).

### 4.3 Calibration method and eval sets

Fit a calibrator (temperature scaling first; isotonic regression if the reliability curve is not a simple stretch) on labelled shadow outcomes: the cheap model's raw score versus whether the current path, or a human, later agreed. Report **expected calibration error (ECE)** and a reliability diagram per decision id. The eval gate (§ 13.2, § 13.4) fails a cheaper-model or criteria change when ECE or accuracy regresses beyond the bounds recorded with the eval set.

Each decision grows an eval set under `evals/` (or `tools/jev/evals/decisions/`, as A0 already planned) toward about 20 real past cases (§ 13.1), sourced from shadow logs and from `_data/jev_resolutions.yml` / loop run records. `intake-type` can start from `evals/t1-intake`. The runner is `tools/evals.py`. Until a decision's calibrator has been fit and the 90%-is-90% target holds on a held-out slice, that decision stays in `shadow` regardless of the global flag.

Log, for every call (this closes audit gap 14 and extends FR87 and constitution § 29): exact model id, raw score, calibrated score, full distribution, both thresholds, which cascade layer answered, the fingerprint, the conservative branch, and the eventual outcome once it is known. Cost figures are labelled API-equivalent (estimate) (§ 10.7).

## 5. Routing logic

Every decision falls through four layers and stops at the first one that is sure. This is the article's cascade, FrugalGPT's "return the generation if the score is higher than τᵢ, else query the next service," and RouteLLM's idea of spending the strong model only on the uncertain slice. Today's JEV conflict ladder is the same shape but sized by *conflict*, not by probability (`classify.py` plus `jev.tiers`; `auto_tiers` is currently `[tier0, tier1, tier2]` in `_data/fleet.yml`, with `ci_tiers: [tier0]`). This layer does not replace that ladder. It adds a confidence router *inside* a loop step and, later, beside a conflict triage that already has a deterministic answer.

| Layer | What it handles | Sure when |
| --- | --- | --- |
| 1. Code | Exact rules: retries, budgets, allowlists, date math, counting, test exit codes, "the file exists," "the label is already set." `classify.py` stays here. | The rule fired. |
| 2. Cheap typed model | Bounded pick-from-list questions above the high-band threshold, choice ≠ `other`. Default executor: pinned `claude-haiku-5-5`. | Calibrated score ≥ `threshold_high` and the exit was not taken. |
| 3. Stronger model that writes a reason | The abstention band, anything the cheap model answered `other`, and anything that needs prose or vision. Default executor: the step's current pinned model (today usually `claude-sonnet-5-5` or `claude-opus-5-5`). It receives the cheap model's guess and distribution as context, and must return a choice, a reason, and whether it is sure. | It says it is sure, and its own band clears the per-action cut. |
| 4. Human | Irreversible actions; both layers unsure or in disagreement; `other` after the strong model; model errors, timeouts and usage limits. | A person acts. The review shows both answers side by side. |

**Hard rules, which no flag can weaken:**

- Irreversible actions — send, pay, publish, delete, change permissions, merge, force-push, settings, secrets — never enter this ladder. They stay with a human under constitution § 11, § 12 and § 13.6–13.8. JEV still never merges a pull request (NFR11).
- `other` / `none` is never auto-routed, at any layer.
- A model error, timeout or usage limit takes the conservative branch and never fails the step (NFR17, ADR 0008).
- Vision, screenshots, scanned PDFs and very long threads skip the text-only cheap layer and go to a vision-capable allowed model (currently Sonnet or Opus). The context pack stays text-only until a later, separate change; this is only the escalation path (audit concept 20).
- Counting, dates, permissions and allowlists stay in code even when a typed question is nearby (audit concept 8, already incorporated).

RouteLLM-style *pre-generation* scoring (estimate whether the cheap model is enough before calling it) is optional later, once the shadow log can train a scorer. The first ship is the FrugalGPT-style cascade: always try code, then the cheap model, then escalate on the calibrated score.

## 6. Integration with existing JEV loops

The layer plugs into the loop runner ([`tools/jev/loop.py`](../tools/jev/loop.py), `tools/dash loop run`) and, for the intake pilot, the issue-pipeline tier-1 step. It does not change `classify.py`. It does not merge, force-push, or edit `main`.

### 6.1 Default off, then shadow, then on

A new block in `_data/fleet.yml` (name to be confirmed; proposed `jev.decisions`):

```yaml
jev:
  decisions:
    mode: off          # off | shadow | on
    executor: claude-haiku-5-5    # must be an exact id in ai_models.allowed
    reason_executor: claude-sonnet-5-5
    # per-decision overrides and promoted bands live in _data/decisions.yml
```

- `off` (default): today's path is unchanged. No cheap-model call is made. This is how the layer ships so current behaviour cannot break.
- `shadow`: the cheap model is asked and the trace is written; the current path still decides. Promotion math runs over that log. Rehearse and dry-run are *not* this: they preview a change, they do not accumulate agreement statistics.
- `on`: the high band of a *promoted* decision may auto-act. Everything else still shadows or escalates.

A prompt change, a model-id change or a criteria change is a new policy (new fingerprint). That decision returns to `shadow` until the band is earned again.

Kill switch: a `vars.*_ENABLED` (or a field in the central switches map, constitution § 17) so a scheduled run can disable the layer without a deploy. Changing thresholds, promotions, the lockfile schema, or `ai_models.allowed` is a § 12.3 gated PR with `needs-amr`.

### 6.2 Shadow promotion: Wilson lower bound and a minimum sample size

Indurkar's shadow-mode write-up is the promotion rule, not a labelling-tool button (Label Studio and Argilla may host a review queue; they are not the engine):

1. Log the cheap model's label, raw and calibrated scores, and the current path's (or a human's) decision, in silent parallel, for at least a week or until unusual cases appear.
2. For each candidate high-band cut, compute precision and a **95% Wilson lower bound**, and refuse a cut whose lower bound is below the target or whose sample size is below a declared minimum.
3. Promote the *lowest* cut that still clears the bound — Indurkar's worked table is the cautionary example: a 0.95 slice that "looked like 97%" on 168 cases was refused because its lower bound was 93%; promotion started at 0.90 and covered about 11% of cases.
4. Automate only that top band first. The next lower band waits for its own window.
5. Keep sampling the auto-accepted slice. A miss demotes the band, raises the cut, and lands a regression case in the eval set (the same spirit as FR88, applied to loop decisions rather than test selection).
6. A promotion PR cites the window, the bounds and the sample sizes, and is gated.

### 6.3 Deterministic done-checks first

Turn caps and dollar caps stop a run today; they do not notice that the work is already done (audit concept 18). After each loop turn:

1. Run a *code* done-check: tests green, required files present, the expected label or draft PR already exists, every acceptance criterion in the step spec that can be checked mechanically is true. This is the OpenHands Stop-hook pattern (`{"decision": "deny", "reason": "..."}` when lint or tests have not passed) and Aider's `--auto-lint` / `--auto-test` gates. A Ralph-style "COMPLETE" promise, if one is ever used, counts only *after* this gate is green; `--max-iterations` (our turn cap) stays the escape hatch. LangGraph's `recursion_limit` is a cap, not a done-check — same as our dollar cap.
2. If that check is decisive, stop or refuse to stop **without another model call**.
3. If it is ambiguous, ask `loop-done` (`done` / `not_done` / `other`) and route on the two-threshold cascade. Parse failures and `other` are conservatively "not done" (OpenHands `/goal` treats an unreadable judge verdict as `complete=False`).
4. Caps still bind: a loop cannot burn the rest of the budget after a green done-check, and cannot spin forever if the check never goes green.

### 6.4 Budget and the eval gate

Every cheap-model and reason-model call site is capped and recorded:

- Loop calls count under `budget.loops` (today $50/month, scheduled stop at 80%), plus a per-attempt cap, and appear in `budget.call_sites` once a workflow or local verb owns them.
- A new `budget.jev.decisions_*` (or a call-site row) caps the cheap layer separately so it cannot silently eat the conflict engine's $10 monthly ceiling.
- Every figure is API-equivalent (estimate) under OAuth (§ 10.7).
- A step moves work onto the cheap model only if that decision's evals still pass (§ 13.4). Offline evals stay in `tools/test_evals.py`; a model rerun is local and named, as today.

The implementation sketched in ADR 0008 § 4.2 still holds for the shared primitive: `python3 -m tools.jev decisions ask` is the one code path, used by a composite action in CI and by the loop runner locally, so traces are byte-comparable (ADR 0002). This draft does not implement that module.

### 6.5 What does not change

- `tools/jev/classify.py` and `evals/jev-classify` stay deterministic, $0, and network-free.
- `jev.auto_tiers`, conflict size envelopes, and `jev:needs-human` keep their current meaning until a later, explicit design proposes confidence-based conflict triage — out of scope here.
- Constitution § 11 write-back, § 12 merge authority, draft-PR-only loops, and "hands off the Mac" (§ 10.5) are untouched.
- No new vendor credential is required to begin: Haiku is already in the auth and budget matrix ([docs/AI-INTEGRATION.md](AI-INTEGRATION.md)).

## 7. Rollout phases

Phases are proposed work, not a new epic until the maintainer asks for one. They are ordered so that nothing auto-acts before the eval gate and the shadow window exist. Dates are targets, not promises.

| Phase | Delivers | Acceptance |
| --- | --- | --- |
| **D0** Design (this document and the `HUB-NEW` fragment) | The schema, the cascade, the promotion rule, the open questions below | Maintainer review of this draft; a later PR may land it |
| **D1** Lockfile, `decisions ask` in shadow, traces | `_data/decisions.yml` with the four loop questions; `tools/jev/decisions.py` (`ask`, `lock`, `lint`); traces with distribution, both thresholds and layer; `mode: shadow` available, default still `off`; `test_decisions.py` | A local `tools/dash loop run --rehearse` writes a trace and does not change the current decision; lint rejects a question with no exit option |
| **D2** Calibrator and eval sets | Labelled shadow scores, temperature scaling, ECE report, eval cases for `intake-type` (from `t1-intake`) and `loop-done`; verbalization-logprob path if the API exposes logprobs | 90%-is-90% holds on a held-out slice for at least one decision, or the report says it does not and the decision stays in shadow |
| **D3** Deterministic done-check in the runner | Code-level stop/continue after each turn; `loop-done` asked only when ambiguous | A loop whose tests and acceptance criteria are already green stops without a further model call, under the same caps |
| **D4** First band promotion | One decision, high band only, by a gated PR that cites Wilson bounds and sample size | The promoted band's lower bound still clears the target on a held-out window; a miss demotes and adds a case |
| **D5** Dual-answer review and vision escalation | Human handoff shows both layers' answers; screenshots and scanned PDFs skip the cheap layer | A disagreement fixture renders both answers; a pack that includes a PDF or image never calls the text-only executor |

A0–A6 of HUB-088 remain the CI plan and can run in parallel. D1 should share `tools/jev/decisions.py` with A2 rather than fork it.

## 8. Risks

- **Miscalibration.** A 0.95 from Haiku that is really 0.70 would auto-act wrongly. Mitigation: two thresholds, shadow-only until ECE and the Wilson bound hold, fail closed, `other` never auto-routed.
- **Sparse verbalized confidence.** Models bunch on 95%. Mitigation: verbalization logprobs and a fitted calibrator; no auto-act on raw prose percents.
- **Silent skip of a done-check miss.** The worst loop failure is stopping early, or never stopping. Mitigation: deterministic checks first; `other` and parse failures mean not-done; caps remain.
- **Double spend in shadow.** The cheap call is extra cost until a band is promoted. Mitigation: monthly cap, start with one high-frequency decision, cheap executor.
- **Name and vendor confusion.** Future work must keep saying "hub JEV" vs "TypeSafe Jev."
- **Scope creep into a constitution mandate.** Out of scope without an amendment.
- **Logprobs may be unavailable** on the current Anthropic route. Mitigation: fall back to a constrained distribution plus a numeric field, then calibrate; do not block D1 on logprobs.
- **ADR 0008 starting thresholds vs MAPIE pairs.** The 0.85 / 0.95 single cuts in AGENTIC-SDLC are examples for *pipeline* skips and gates. Loop routing uses a *pair* of cuts. A later pass should make the lockfile fields one schema with both `threshold` (legacy single cut, treated as `threshold_high`) and `threshold_low`.

## 9. Open questions and decisions for Amr

These are the choices this draft will not make on its own:

1. **Executor.** Proceed with pinned `claude-haiku-5-5` as the cheap layer (already allowed), and keep TypeSafe Jev as an optional future executor behind the same schema, gated under § 12.3 if it is ever added? Or wait for A0 (#738) before any cheap-model call, even Haiku?
2. **First pilot.** `intake-type` (eval cases already exist) or `loop-done` (the audit's cost leak), or both in shadow together?
3. **Promotion math.** Adopt Wilson 95% lower bounds plus a declared minimum *n* (Indurkar's rule) as the written standard for every band promotion, including HUB-088's later CI promotions?
4. **Lockfile ownership.** One `_data/decisions.yml` for pipeline (HUB-088) and loops (this feature), or two files with one schema?
5. **Where the strong-model reason slot runs.** Always the step's current pinned model, or a single `reason_executor` (proposed: Sonnet) so the cheap layer has a stable escalation target?
6. **Human review surface.** Extend the existing `jev:needs-human` / `needs-amr` triage report with a side-by-side dual-answer block, or a small console view later?
7. **Constitution.** Confirm that this stays an opt-in layer (flag default `off`) and that a later "every pick-from-list call must use a calibrated classifier" rule would be a § 13 amendment, not a silent expansion of this draft.
8. **Eval backlog.** AGENTIC-SDLC and [docs/EVALS.md](EVALS.md) still list T2/T3, repo-scout, fleet-pulse and JEV model-tier evals as to-come. Should D2 wait on any of those, or is a focused `intake-type` / `loop-done` set enough to start?

## 10. What this branch contains, and what it does not

- Added [`docs/TYPED-DECISION-LAYER.md`](TYPED-DECISION-LAYER.md) (this page) and [`features/features.d/typed-decision-layer.yml`](../features/features.d/typed-decision-layer.yml).
- Did not edit `features/features.yml` or `PRD.md` (the compiler owns numbers; a pull request never picks the next `HUB-NNN` or `FRn`).
- Did not regenerate [`docs/README.md`](README.md); that index is produced by `python3 tools/docs_index.py --write` and should be run when a pull request is opened. The page has a `>` summary under its H1 so the generator can pick it up. `docs/SCHEMA.md` already covers new `UPPERCASE-TOPIC.md` files with the `*.md` pattern.
- Did not open a pull request, merge, force-push, edit `main`, or change repository settings.

## References

The 8 November audit canvas (store `ecae274f-8a58-44f1-9d6f-1810735ef947`, canvas `8d41f03d-8f98-400d-8b31-86a320614b50`) and the Researcher's 21 November brief (`/workspace/typed-decision-patterns/brief.md`; links checked HTTP 200 that day, CST). Use the arXiv copy of FrugalGPT; the OpenReview PDF returned 403 to that fetch.

### Article and hub sources

- Mr. Buzzoni, [How to Cut Your Agent Bill by 90% With Jev Engineering and Kimi K3](https://x.com/Mr_Buzzoni/status/2104783226833186920) (29 September 2026).
- [docs/JEV.md](JEV.md), [docs/EVALS.md](EVALS.md), [docs/constitution.md](constitution.md) (§ 10.7, § 11, § 12.3, § 13, § 29), [ADR 0008](adr/0008-typed-decisions-as-pipeline-gates.md), [ADR 0002](adr/0002-agent-step-specs-and-local-runner.md), [ADR 0009](adr/0009-agentic-efficacy-model.md), [docs/prd/AGENTIC-SDLC.md](prd/AGENTIC-SDLC.md), [PRD.md](../PRD.md) FR86–FR88, NFR17, FR133.

### 1. Two-threshold bands, verbalization logprobs, calibration

- MAPIE, [Risk Control for LLM as a Judge with Abstention](https://mapie.readthedocs.io/en/latest/generated/risk_control/2-advanced-analysis/plot_risk_control_llm_as_a_judge/) ([repo](https://github.com/scikit-learn-contrib/MAPIE)). "If the score is between the two thresholds, the judge abstains."
- Tian et al., [Just Ask for Calibration](https://aclanthology.org/2023.emnlp-main.330/), EMNLP 2023 ([arXiv:2305.14975](https://arxiv.org/abs/2305.14975)).
- [Verbalization logprobs](https://aclanthology.org/2026.findings-acl.1671.pdf), ACL Findings 2026.
- Optional open scorer: [cleanlab/tlm](https://github.com/cleanlab/tlm) (stronger variant of BSDetector, Chen & Mueller, [ACL 2024](https://aclanthology.org/2024.acl-long.283/)).
- Wang et al., [Self-Consistency Improves Chain of Thought Reasoning](https://arxiv.org/abs/2203.11171).

### 2. Typed schemas with a required OTHER exit

- Instructor, [Always include a fallback option](https://docs.instructorphp.com/packages/instructor/techniques/classification); Python Instructor [types](https://python.useinstructor.com/concepts/types/).
- ohmeow, [Mapping unrecognized values onto OTHER](https://ohmeow.com/posts/2024-07-06-llms-and-enums.html).
- Claude Code, [`AskUserQuestion`](https://code.claude.com/docs/en/tools-reference) (Other row always present).
- LangGraph, [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) and [MCP elicitation](https://docs.langchain.com/langsmith/server-mcp-elicitation).
- Outlines, [constrained generation](https://dottxt-ai.github.io/outlines/reference/generation/generation/).

### 3. Shadow mode, Wilson lower-bound promotion, minimum n

- Mohinee Indurkar, [Shadow mode: earning a skeptical team's trust](https://mohinee.github.io/2026/shadow-mode-earning-trust/) (17 September 2026). Promotion uses the lowest cut whose 95% Wilson lower bound still clears the precision target, with a minimum sample size.
- Label Studio and Argilla are review queues, not the promotion engine: [Label Studio ML guide](https://labelstud.io/guide/ml.html), [Argilla annotate](https://docs.argilla.io/latest/how_to_guides/annotate/).

### 4. Confidence cascade (FrugalGPT, RouteLLM)

- Chen et al., [FrugalGPT](https://arxiv.org/abs/2305.05176) ([repo](https://github.com/stanford-futuredata/FrugalGPT)). "It returns the generation if the score is higher than a threshold τᵢ, and queries the next service otherwise."
- [RouteLLM](https://github.com/lm-sys/RouteLLM) ([arXiv:2406.18665](https://arxiv.org/abs/2406.18665), [blog](https://www.lmsys.org/blog/2024-07-01-routellm/)). Scores the query up front and calibrates the cut to a target share of strong-model calls.

### 5. Deterministic done-checks first; typed judge only when ambiguous

- OpenHands, [Stop hooks](https://docs.openhands.dev/openhands/usage/customization/hooks) and [SDK `on_stop.sh`](https://github.com/OpenHands/software-agent-sdk/blob/main/.openhands/hooks/on_stop.sh); paid fallback: [goal loop](https://docs.openhands.dev/sdk/guides/convo-goal).
- Aider, [`--auto-lint` / `--auto-test`](https://aider.chat/docs/usage/lint-test.html).
- Ralph Loop, [plugin README](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/ralph-loop/README.md) (and [Huntley](https://ghuntley.com/ralph/)): a COMPLETE promise only after a green gate; `--max-iterations` is the cap.
- SWE-agent, [agent reference](https://swe-agent.com/latest/reference/agent/); Reflexion ([repo](https://github.com/noahshinn/reflexion), [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)).
- LangGraph `recursion_limit` is a safety cap, not a done-check: [GRAPH_RECURSION_LIMIT](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT).

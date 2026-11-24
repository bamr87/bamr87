# Critical review: MeMo: Memory as a Model (arXiv:2605.15156v2)

> Critical review of Quek et al., “MeMo: Memory as a Model” (arXiv:2605.15156v2), prepared 23 November 2026.

**Paper:** Quek, Lee, Leong, Verma, Prakash, Chen, Low, Rus, and Solar-Lezama, “MeMo: Memory as a Model,” arXiv:2605.15156v2 [cs.CL] (also cs.AI, cs.LG), 29 pages including appendices.

**Authors and affiliations.** Equal contributions from Ryan Wei Heng Quek (NUS Institute of Data Science; NUSGS ISEP; A\*STAR; NUS Computer Science), Sanghyuk Lee (University of Tokyo; Liquid AI; CSAIL, MIT), Alfred Wei Lun Leong (NUS Computer Science; AI Singapore), and Arun Verma (Singapore-MIT Alliance for Research and Technology), who is also the corresponding author. Additional authors: Alok Prakash (SMART), Nancy F. Chen (A\*STAR), Bryan Kian Hsiang Low (NUS / SMART), Daniela Rus (CSAIL, MIT / SMART), and Armando Solar-Lezama (CSAIL, MIT / SMART).

**Dates (America/Chicago).** Version 1 was submitted Thursday, 14 May 2026, at 12:51 PM CDT (17:51:34 UTC). Version 2, the version reviewed here, was submitted Wednesday, 20 May 2026, at 12:53 PM CDT (17:53:38 UTC). The official HTML copy is dated 20 May 2026 on the arXiv stamp.

**License and availability.** The arXiv abstract page licenses the paper under [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/). The PDF itself points only to “supplementary materials” for code and data and does not give a URL. A public reproduction repo, a project page, and model/data artifacts do exist and were verified live on 23 November 2026:

- Code: [https://github.com/arunv3rma/MeMo](https://github.com/arunv3rma/MeMo) (MIT License; created 16 May 2026, last push 21 May 2026 6:14 AM CDT; 60 stars at the time of this review)
- Project page: [https://arunv3rma.github.io/blogs/memo/](https://arunv3rma.github.io/blogs/memo/)
- Hugging Face collection: [https://huggingface.co/collections/Glow-AI/memo-memory-as-a-model](https://huggingface.co/collections/Glow-AI/memo-memory-as-a-model)
- Dataset: [https://huggingface.co/datasets/Glow-AI/MeMo](https://huggingface.co/datasets/Glow-AI/MeMo)
- Released checkpoints are named with `_best_epoch` and, for NarrativeQA, `NQA10`, which matters for the evaluation critique below.

**How this review was prepared.** The HTML at [https://arxiv.org/html/2605.15156v2](https://arxiv.org/html/2605.15156v2), the abstract page, and both PDFs (v1 and v2) were fetched and read in full. v1 and v2 were diffed at sentence level. Related-work and artifact URLs below were HTTP-checked (all 200 unless noted).

---

## 1. Problem and core claims

The problem, as the authors see it, is that LLMs are “effectively frozen for extended periods after pretraining” (Sec. 1), so they go stale, while full retraining is too expensive. Existing fixes fall into three buckets, each with a characteristic failure: retrieval and in-context learning struggle with cross-document synthesis and retrieval noise; continual pretraining and fine-tuning cause catastrophic forgetting and cannot touch closed models; latent-memory methods (soft tokens, KV caches, tokenizer-tied modules) couple the memory to a specific model.

MeMo’s proposal is to treat *memory as a model*: keep a frozen **Executive** LLM for reasoning, and train a smaller dedicated **Memory** model on a synthetic “reflection” QA dataset distilled from the target corpus by a **Generator** LLM. At inference the Executive queries the Memory model in natural language through a three-stage multi-turn protocol. The Memory model never sees source documents at inference; it answers from parameters only.

The paper’s five advertised advantages (abstract and Sec. 1) are that MeMo (a) captures complex cross-document relationships, (b) is robust to retrieval noise, (c) avoids catastrophic forgetting in the Executive, (d) needs no access to the Executive’s weights or logits, so it is plug-and-play with open and closed models, and (e) has retrieval cost independent of corpus size at inference, because the Memory model is fixed-size. The formal objective, corrected in v2, is Definition 1 (Sec. 3): find a mechanism \((\Phi, f)\) that *maximizes expected accuracy* of \(f(\mathcal{M}_\theta, \Phi(\mathcal{D}), q)\) without modifying the frozen Executive parameters \(\theta\).

The design principle, stated in Sec. 1, is:

> “reflections, corpus-derived structures that require no knowledge of future queries, yet naturally serve as the precise interface through which any query can access the underlying corpus without ever observing it directly.”

---

## 2. Method

**Data synthesis (Sec. 4.1, Alg. 1).** A frozen Generator (Qwen2.5-32B-Instruct in the experiments, with YaRN scaling to a 131K context) turns the corpus into a reflection QA set in five steps: (1) direct and indirect fact extraction from chunks, (2) consolidation of related pairs into multi-fact questions, (3) verification and rewriting for self-containment, or discard, (4) entity-surfacing QA aimed at the reversal curse, and (5) cross-document synthesis over pre-defined document groups, producing “converging clues” and “parallel properties.” No document IDs or watermarks are written into the pairs. The resulting corpora are large: 1,639,995 QA pairs for BrowseComp-Plus, 1,276,676 for NarrativeQA, and 664,762 for MuSiQue (App. F, Table 11). Gzip compression ratios of 5.45×–7.03× (App. K) show substantial lexical overlap, which is unsurprising because later steps are derived from earlier ones.

**Training (Sec. 4.2).** The Memory model is initialized from a smaller pretrained LM (main results use Qwen2.5-14B-Instruct; ablations use 1–2B models from Qwen, Gemma, and Liquid’s LFM2.5) and trained with supervised fine-tuning, next-token loss on answer tokens only, never conditioning on source documents. Main runs are full SFT for 3 epochs (AdamW, LR \(2\times10^{-5}\), DeepSpeed ZeRO-2, max length 8096). LoRA is compared in App. O and is consistently worse, sometimes collapse-level worse (LFM2.5-1.2B LoRA is 0.78% on BrowseComp-Plus vs 37.33% full SFT).

**Continual integration (Sec. 4.3, 5.5).** For \(K\) disjoint corpora the authors train one Memory model each, form task vectors, and merge (Linear, task arithmetic, SLERP, TIES, DARE-Linear, DARE-TIES). This is meant to avoid retraining on the union, whose cost they write as \(\Theta(K^2)\) versus \(\Theta(K)\) for merging.

**Inference (Sec. 4.4, App. J).** A structured three-stage protocol, with separate temperatures and budgets:

- Stage 1, Grounding (1 turn): Executive decomposes the query into atomic sub-questions; Memory answers each independently (Executive temp 0.4, Memory 0.1).
- Stage 2, Entity identification (7 turns): Executive narrows candidate entities (temps 0.4 / 0.1). Helpers track “uncertain answer streaks,” and fall back to a best unconfirmed candidate if nothing is pinned.
- Stage 3, Answer seeking and synthesis (8 turns, or 15 in an ablation): Executive asks follow-ups conditioned on the entity (temps 1.0 / 0.3), can pivot if the entity looks wrong, and synthesizes at temp 0.3.

The authors argue that Memory replies are “compact natural-language snippets whose lengths are independent of the corpus size, ensuring constant-time inference” (Sec. 4.4). That is constant *in corpus size*, not in the number of turns.

**Evaluation protocol (Sec. 5).** Three benchmarks: a 300-question English subsample of BrowseComp-Plus (3,541 documents, equal number of evidence and negative docs), NarrativeQA (293 questions; see the 10-vs-105 document discrepancy below), and MuSiQue (1,000 questions, 5,296 documents, same evidence/negative construction). Baselines: BM25, NV-Embed-V2, HippoRAG2, Cartridges, and a Perfect Retrieval upper bound (gold evidence only, top-\(k=9\) with adaptive backoff for retrieval methods). The same trained Memory model is queried by Qwen2.5-32B-Instruct (mean ± std over 3 runs) or Gemini-3-Flash (single run). Binary accuracy is judged by Gemini-2.5-Flash-Lite via DeepEval. Main numbers are reported “at the best training epoch.”

---

## 3. Key results (exact numbers)

Headline numbers are Table 2 (Memory model = Qwen2.5-14B-Instruct, best epoch). Accuracy in percent:

| Method | BrowseComp-Plus Qwen / Gemini | NarrativeQA Qwen / Gemini | MuSiQue Qwen / Gemini |
|---|---|---|---|
| Perfect Retrieval (upper bound) | 79.67 ± 1.45 / 88.33 | 51.42 ± 0.52 / 60.41 | 62.83 ± 0.90 / 73.00 |
| BM25 | 1.11 ± 0.69 / 27.00 | 10.24 ± 0.34 / 14.33 | 20.00 ± 0.30 / 23.20 |
| NV-Embed-V2 | 50.67 ± 0.33 / 57.00 | 20.59 ± 0.86 / 26.62 | 37.47 ± 0.15 / 46.60 |
| HippoRAG2 | **56.11 ± 0.51** / 66.33 | 21.39 ± 0.20 / 23.21 | 42.17 ± 0.12 / 57.00 |
| Cartridges | 0.00 ± 0.00 / — | 3.75 ± 0.11 / — | 8.57 ± 0.40 / — |
| **MeMo** | 54.22 ± 0.84 / **66.67** | **26.85 ± 0.39 / 53.58** | **48.30 ± 1.25 / 60.20** |

The authors’ own gloss in Sec. 5.1 is mostly fair, with one numerical slip:

> “On NarrativeQA, the most challenging benchmark (App. I), MeMo achieves 26.85% with Qwen2.5-32B-Instruct and 53.58% with Gemini-3-Flash, substantially surpassing all baselines.”

That NarrativeQA Gemini result is the paper’s strongest empirical point: 53.58% versus HippoRAG2 at 23.21%, and not far from Perfect Retrieval at 60.41%. The MuSiQue wins are also clear. The BrowseComp-Plus claim is weaker. With Qwen, MeMo *trails* HippoRAG2 (54.22 vs 56.11). With Gemini the two are essentially tied (66.67 vs 66.33). The paper itself explains why retrieval can win here: “its answers are absent from Executive model’s parametric knowledge (App. I), making direct access to evidence documents especially valuable” (Sec. 5.1). A separate slip: Sec. 5.1 says MeMo’s MuSiQue scores are “48.30% and 58.70%,” but Table 2 lists the Gemini number as 60.20, not 58.70. The typo is in both v1 and v2.

**Plug-and-play.** Switching the Executive from Qwen2.5-32B-Instruct to Gemini-3-Flash, with the Memory model held fixed, “yields gains of 12.45%, 26.73%, 11.90% on BrowseComp-Plus, NarrativeQA and MuSiQue, respectively” (Sec. 5.1). This is the cleanest support for claim (d).

**Noise robustness (Sec. 5.2, Table 3; App. L, Table 17).** Adding one negative document per evidence document (\(0N\to 1N\)) drops NV-Embed-V2 and HippoRAG2 by up to 6.22 points on BrowseComp-Plus and up to 5.16 on MuSiQue. MeMo moves +0.55 on BrowseComp-Plus (53.67 → 54.22) and −1.77 on MuSiQue (50.07 → 48.30), both within one standard deviation. At \(2N\), HippoRAG2 falls 11.55 points on BrowseComp-Plus and NV-Embed-V2 falls 9.27 on MuSiQue. *MeMo is not reported at \(2N\)*, even though the Table 17 caption still talks about MeMo results. The robustness claim is therefore only supported at the 0-versus-1 setting used in the main corpus, and even that corpus already uses a truncated negative set (App. D) because Step 5 is quadratic.

**Memory size and family (Tables 4–5).** A 14B Memory model beats a 1.5B model on every column, sometimes modestly (MuSiQue + Gemini: 60.20 vs 59.70) and sometimes clearly (BrowseComp-Plus + Qwen: 54.22 vs 44.11). At the 1–2B scale, Qwen, Gemma3, and LFM2.5 are in a similar band; the framework is not obviously family-specific. Full SFT dominates LoRA (Table 20).

**Merging (Table 6, Table 12, Fig. 2).** On NarrativeQA split into two ~640k-pair subsets, Merge-TIES (\(\rho=0.3\)), the best of 14 configurations, costs about 48 8×H100 GPU-hours versus about 72 for a full retrain (a 33% saving at \(K=2\); they extrapolate 5.5× at \(K=10\)). Accuracy falls sharply: 15.81 ± 0.39 vs 26.85 ± 0.39 with Qwen (−11.04 points) and 34.47 vs 53.58 with Gemini (−19.11 points). The merged model still beats the retrieval baselines on this benchmark. The rest of the sweep is much worse (SLERP at \(t=0.5\) is 7.85 ± 1.71). Merging is a cheaper *partial* substitute, not a free lunch.

**Protocol ablation (App. J.2, Table 16), Qwen Executive, 14B Memory:**

| Setup | BrowseComp-Plus | NarrativeQA | MuSiQue |
|---|---|---|---|
| Single turn | 32.56 ± 1.58 | 24.80 ± 0.20 | 37.57 ± 1.15 |
| Unstructured, 15 turns | 47.33 ± 0.88 | 26.73 ± 2.17 | 40.13 ± 1.12 |
| Unstructured, 50 turns | 48.67 ± 1.00 | 27.19 ± 0.71 | 40.57 ± 0.31 |
| Structured, 7+8 turns (default) | **54.22 ± 0.84** | 26.39 ± 1.75 | **48.30 ± 1.25** |
| Structured, 7+15 turns | 51.44 ± 2.41 | **27.76 ± 0.20** | 47.57 ± 0.95 |

Unstructured iteration plateaus from 15 to 50 turns. Structure helps most on the multi-hop sets. On NarrativeQA, the default 7+8 budget actually *loses* to unstructured 50 turns, and only 7+15 recovers the lead. The authors admit “the stage budget used in our experiments was selected without systematic tuning” (App. J.2). Extra Stage-3 turns can also *hurt* BrowseComp-Plus and MuSiQue, which they attribute to error accumulation and entity-pivot mistakes.

**Pipeline leave-one-out (App. E, Table 9), 1.5B Memory, Qwen Executive.** Removing Step 5 (cross-document synthesis) is devastating: NarrativeQA 24.00 → 6.37, MuSiQue 42.90 → 24.17, but it also deletes almost all the data (0.002× and 0.195× retention). Data volume and step quality are confounded. Removing Step 3 *raises* NarrativeQA from 24.00 ± 0.20 to 28.90 ± 0.86, which the authors attribute to a rewriting loop that corrupts long-form narrative QA. The main pipeline still includes Step 3 on NarrativeQA, so the headline 26.85% may understate what a domain-tuned pipeline could do.

**Closed-book vs perfect retrieval (App. I, Table 13).** Qwen scores 0.00 / 5.35 / 17.03 with no context on the three datasets, and 79.67 / 51.42 / 62.83 with perfect retrieval. Gemini is 1.33 / 26.62 / 41.80 versus 88.33 / 60.41 / 73.00. The tasks are not fully memorized, but Gemini already knows a non-trivial fraction of NarrativeQA and MuSiQue with no documents at all, which inflates some Gemini columns.

**Cost (App. F–G, Sec. 5.5).** Data generation is reported as about 240, 200, and 150 GPU-hours for BrowseComp-Plus, NarrativeQA, and MuSiQue. Training the 14B Memory model is about 180, 150, and 90 GPU-hours. Step 5 is \(O(k \cdot C^2 \cdot Q^2)\) (App. C, App. D), which is why they refused to use the full negative sets (BrowseComp-Plus averages 78 negatives per question, up to 197). Compute reporting is internally inconsistent: App. G says “all experiments were conducted using NVIDIA H200 GPUs,” App. F says “H100 and H200,” and Table 6 reports “8×H100 GPU-hours,” with a single 640k-pair SFT run costing ≈24 GPU-hours — hard to reconcile with 150 GPU-hours for the full NarrativeQA 14B run, which is only about twice the data.

---

## 4. Strengths

- The modular split is clean and well motivated: freeze the reasoner, put new knowledge in a separate, queryable Memory model, and keep the interface in ordinary language so a closed API can be the Executive. Table 1, after the v2 corrections, is a fair high-level map of that design space.
- The NarrativeQA result, especially with Gemini, is genuinely interesting. Long documents with median length 65,925 tokens (App. D, Table 7) are a setting where fixed-context RAG is uncomfortable, and MeMo’s 53.58% versus HippoRAG2’s 23.21% is a large gap, approaching the 60.41% perfect-retrieval ceiling.
- The authors actually test plug-and-play: one Memory model, two Executives, including a proprietary model. Many “model-agnostic memory” papers do not do this.
- The supporting analysis is broader than the usual conference minimum: pipeline LOO, model size and family, full SFT vs LoRA, a 14-way merge sweep, single-turn vs unstructured vs structured protocols, and a closed-book versus perfect-retrieval check.
- They are candid, in App. B and the impact statement (App. A), that training is expensive, that a fixed-size Memory model will eventually hit a capacity wall, and that parametric memory “may obscure the provenance of retrieved information.”
- Code, data, and “best epoch” checkpoints were released, even though the paper itself never prints the URLs.

---

## 5. Weaknesses and threats to validity

**Evaluation design.** The most serious issue is oracle model selection on the test task. Table 2 and several ablations “report results at the best training epoch,” Figs. 3–5 plot accuracy on the evaluation benchmarks versus epoch, and the Hugging Face checkpoints are literally named `_best_epoch`. There is no held-out validation split described for early stopping. That overstates the deployable number. Gemini-3-Flash results are a single run with no standard deviation, so the 66.67 vs 66.33 “win” on BrowseComp-Plus is not meaningful. The judge is Gemini-2.5-Flash-Lite, i.e. the same vendor as one Executive, and there is no human agreement study. NarrativeQA is historically scored with overlap metrics on free-form answers; binary LLM-as-judge can quietly change the task. Protocol budgets were not systematically tuned, and the default 7+8 setup is not even best on NarrativeQA (Table 16). The main-text NarrativeQA score of 26.85 ± 0.39 also does not match either structured row in Table 16 (26.39 ± 1.75 or 27.76 ± 0.20), a reporting inconsistency that is never explained.

**A factual error in the main dataset description.** Section 5 says NarrativeQA uses “293 questions across 105 documents.” Footnote 5, Table 7 (\(n=10\) full documents, 75 chunks), Table 8 (\(n_{\text{group}}=10\)), and the released `NQA10` checkpoints all say **10 documents** from the validation split, following HippoRAG2, with 294 questions minus one duplicate. Ten long books or scripts, not 105, is the actual scale of the “most challenging” headline result.

**Baselines.** There is no simple parametric control: no continual pretraining or SFT of a 14B model on the raw corpus or on ordinary (non-reflection) QA. Cartridges is described as the “closest existing parametric baseline,” but it scores 0.00 ± 0.00 on BrowseComp-Plus and 3.75 / 8.57 on the other two sets. That is almost certainly a failed or mismatched implementation (Cartridges needs white-box access to the Executive and is trained as a KV cache for that model), not evidence that parametric memory is useless. GraphRAG is cited ([15], arXiv:2404.16130) and never compared. HippoRAG2 is re-run with Qwen2.5-32B-Instruct rather than the original Llama 3.3 70B, which the authors flag in footnote 6; that is honest, but it also means they are not reproducing the published HippoRAG2 number. Retrieval methods are limited to top-\(k=9\). MeMo is allowed 16 or more model-to-model turns. That is not a matched inference-compute comparison.

**The robustness and “constant-cost” claims are narrower than they sound.** MeMo is not evaluated at \(2N\) noise. Negative documents were already downsampled because of quadratic synthesis cost (App. D), so the “realistic corpus” is still a curated slice. Inference cost is independent of corpus size only in Memory-model parameter count; it is linear in a long, untuned turn budget, and no token, latency, or dollar comparison versus RAG is reported. Training and synthesis cost *do* depend on corpus size, and they are large (hundreds of GPU-hours per dataset, plus a 32B Generator over long context). “Avoids catastrophic forgetting” is true by construction for the frozen Executive; they do not measure whether the Memory model itself forgets when merged or updated, and the merge results suggest it does.

**Reproducibility, despite the late code release.** The paper still says only “datasets and code are in the supplementary materials.” The GitHub repo and Hugging Face collection, verified in this review, are not cited. That is a fixable omission, but anyone working from the PDF alone would not find them. The arXiv source tarball is the TeX, not the code. Hyperparameters and prompts are partly specified (Tables 10, 14, 18–19), but the “best epoch” policy and the 105-document typo would send a reimplementer down the wrong path. App. G versus Table 6 compute figures cannot both be right as written.

**Internal numerical sloppiness.** Besides 105 vs 10 documents and 58.70 vs 60.20: Table 9’s prose says removing Step 3 leaves MuSiQue at 41.78% and 1.100× data, while the table says 41.70 ± 0.78 and 1.128×; Table 20’s Qwen-14B MuSiQue full-SFT number is 50.07 ± 0.81, which is the \(0N\) figure from Table 3, not the main \(1N\) figure of 48.30 ± 1.25; Table 17’s caption promises MeMo rows that are not there. These are not fatal, but they are not the standard one wants from a paper that leans on close numerical comparisons.

**Threats to validity, in brief.** Internal: test-set epoch selection, single-run Gemini, LLM-as-judge, unmatched inference budgets, a likely broken Cartridges baseline, LOO confounded with data volume, Step 3 kept even when it hurts NarrativeQA. External: three English QA benchmarks, one 10-document long-context set, truncated negatives, no measurement on truly streaming or frequently edited corpora, Memory-model capacity untested at scale, no provenance evaluation. Construct: “constant-time retrieval” and “robust to retrieval noise” are both partly definitional (a parametric memory is not a retriever) rather than demonstrated at the scales the introduction implies.

---

## 6. What changed in v2 versus v1

v1 is 14 May 2026 (490 KB PDF); v2 is 20 May 2026 (495 KB). There are no new datasets, no new baselines, and no new experiments. The important edits are:

1. **Definition 1 was relaxed.** v1 required, for all \(q \in Q\), \(P\{f(\mathcal{M}_\theta, \Phi(\mathcal{D}), q)=a^\star(q)\}=1\) — i.e. perfect accuracy. v2 maximizes expected accuracy. That is the right objective; the v1 statement was formally unattainable and did not match the experiments.
2. **Table 1 checkmarks were corrected.** Parametric methods (CPT, SFT) are now marked as having constant-size memory (✓, was ×). Latent memory methods are now marked as *not* constant-size (×, was ✓). A new footnote 2 says RAG is assumed to use a fixed, task-agnostic embedding model, so the index can be reused across Executives, and ICL prompts are assumed to be raw text.
3. **Table 4’s MuSiQue / Qwen-14B number was aligned with Table 2:** 50.07 ± 0.81 in v1 (the \(0N\) number) becomes 48.30 ± 1.25 in v2 (the main \(1N\) number). Table 20 was not similarly cleaned up.
4. Copy-edits: “up to date” → “up-to-date,” “both both” → “both,” “rather at inference time” → “at inference time,” a missing period in Sec. 1, “pp” → “%” in several places, and small citation-number shifts.

v2 is a typo-and-formalism patch, not a scientific revision. The 105-document error, the 58.70 typo, and the missing MeMo \(2N\) results all survive into v2. The GitHub repo was created two days after v1 and last pushed the day after v2; the PDF was not updated to cite it.

---

## 7. Related work worth comparing (links verified, all HTTP 200)

MeMo sits at the intersection of RAG, parametric knowledge injection, and compressed/latent memory. The paper’s closest neighbors, with canonical links:

- **HippoRAG and HippoRAG 2** (Gutiérrez et al.): graph-augmented, non-parametric “memory” via OpenIE triples and Personalized PageRank. This is MeMo’s strongest retrieval baseline, and the fairest published alternative if the goal is cross-document association without training a new LM. Paper: [arXiv:2502.14802](https://arxiv.org/abs/2502.14802). Code: [https://github.com/OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG). The earlier HippoRAG paper is NeurIPS 2024.
- **Cartridges** (Eyuboglu et al., 2025): trains a corpus-specific KV cache by “self-study” (synthetic conversations + context distillation). Conceptually the closest parametric baseline, but white-box and Executive-specific, which is why Gemini numbers are omitted. The 0% BrowseComp-Plus score in MeMo should not be taken as a Cartridges result until reproduced from the official code. Paper: [arXiv:2506.06266](https://arxiv.org/abs/2506.06266). Code: [https://github.com/HazyResearch/cartridges](https://github.com/HazyResearch/cartridges).
- **Memory Decoder** (Cao et al., 2025): a pretrained plug-and-play memory decoder that imitates a \(k\)NN retriever, but only for models that share a tokenizer. This is the right comparison for claim (d). [arXiv:2508.09874](https://arxiv.org/abs/2508.09874).
- **AutoCompressor** (Chevalier et al., EMNLP 2023), **Gist tokens** (Mu et al., NeurIPS 2023), and **ICAE** (Ge et al., ICLR 2024): compress context into soft tokens bound to a specific model. AutoCompressor preprint: [arXiv:2305.14788](https://arxiv.org/abs/2305.14788).
- **Microsoft GraphRAG** (Edge et al., 2024), cited but not compared: [arXiv:2404.16130](https://arxiv.org/abs/2404.16130).
- **BrowseComp-Plus** (Chen et al., 2025), the deep-research benchmark MeMo subsamples (830 queries and 100,195 documents in the original; MeMo uses 300 questions and 3,541 documents): [arXiv:2508.06600](https://arxiv.org/abs/2508.06600), [https://texttron.github.io/BrowseComp-Plus/](https://texttron.github.io/BrowseComp-Plus/).
- **NV-Embed-V2**: [arXiv:2405.17428](https://arxiv.org/abs/2405.17428). **MuSiQue**: [arXiv:2108.00573](https://arxiv.org/abs/2108.00573). **NarrativeQA**: TACL 2018. **TIES-Merging**: Yadav et al., NeurIPS 2023. **Gemini 3 Flash model card** (December 2025): [PDF](https://storage.googleapis.com/deepmind-media/Model-Cards/Gemini-3-Flash-Model-Card.pdf).

Comparisons the paper does *not* make, and that a follow-up should: a raw-corpus or simple-QA SFT/CPT memory of the same size; official Cartridges; GraphRAG or RAPTOR; and agent-memory systems (MemGPT, Mem0, A-MEM, and the paper’s own cited MemGen, ICLR 2026) if the intended use is an evolving workspace rather than a static corpus. MeMo is a corpus-distillation method, not a conversational memory.

---

## 8. Relevance to Amr

Amr’s setup is a multi-repo GitHub fleet harness: `bamr87/bamr87` as control plane, a Gitorio cockpit, Claude Code CI agents with budget caps, verification gates, a typed-decision layer (confidence bands, a required other-or-none option, shadow promotion, done-checks), and three governing artifacts (`blueprint.yaml`, a recipe, and `events.jsonl`). MeMo is not a fleet-orchestration paper, and most of it should not be copied wholesale. A few pieces do transfer.

**What does not apply.** Training a 14B Memory model, with a 32B Generator, for hundreds of GPU-hours per corpus, is a poor fit for a budget-capped CI fleet whose knowledge (issues, PRs, roadmaps, constitutions) changes constantly. The merge shortcut, which already drops NarrativeQA by 11–19 points at \(K=2\), would be worse on a many-repo, high-churn knowledge base. Replacing `events.jsonl` or AGENTS.md with a parametric memory would also fight the audit rule. The authors themselves warn, in App. A, that this design “may obscure the provenance of retrieved information.” That is disqualifying for any path that has to be logged, reviewed, or undone.

**What does apply, concretely.**

1. *Keep the Executive frozen; put knowledge in a separate, model-agnostic interface.* The empirical payoff of training Memory once and then swapping Qwen for Gemini, including a closed model, is the one MeMo result that maps directly onto a fleet that already upgrades or routes across models (and that wants Claude, or anything else, to stay a black box). Prefer a natural-language or structured-text memory interface over KV-cache or logit-level schemes such as Cartridges or Memory Decoder. Those lock you to one Executive.

2. *Distill cross-artifact “reflections,” don’t only retrieve raw docs.* Step 5 — questions that join facts across documents — is the only synthesis step whose removal truly collapses accuracy, and it is the right analogy for linking `blueprint.yaml`, the recipe, `events.jsonl`, and per-repo AGENTS.md / constitutions / feature catalogs. A cheap version of this (offline or periodic QA or fact cards, with citations back to the source file and commit) is useful. A citation-free trained LM is not.

3. *Structure the query loop; cap turns; treat “unconfirmed” as first-class.* Table 16 is the result that speaks to the typed-decision layer. Unstructured multi-turn plateaus (15 vs 50 turns barely move). A staged protocol with budgets helps on multi-hop tasks, but extra turns past the budget can *corrupt* state through bad pivots. Their “uncertain answer streak” tracker, best-unconfirmed-candidate fallback, and explicit unconfirmed flag after a pivot are close cousins of confidence bands, a required other-or-none option, and done-checks. Use those ideas; do not assume more loop iterations are better.

4. *Do not tune on the test task.* MeMo’s “best training epoch” reporting is a cautionary example for shadow promotion. Checkpoint or threshold promotion should follow the already-planned shadow week and a Wilson-style lower bound, not peak accuracy on the live eval set. If a judge model is used as a done-check, do not use the same family as the Executive without a control, which is the risk in MeMo’s Gemini-judging-Gemini numbers.

5. *Count synthesis and turn cost, not just model size.* “Retrieval cost independent of corpus size” hides a quadratic data-generation bill and a 16-turn inference protocol. For a fleet already worrying about usage pace, any memory layer needs a budget in GPU-hours or API tokens, and a cheaper done-check than another LLM call whenever tests or lint can settle the question.

---

## Sources consulted

- [https://arxiv.org/abs/2605.15156](https://arxiv.org/abs/2605.15156) and v1/v2 abstract pages; arXiv API entry for 2605.15156
- [https://arxiv.org/html/2605.15156v2](https://arxiv.org/html/2605.15156v2) (full HTML)
- [https://arxiv.org/pdf/2605.15156v2](https://arxiv.org/pdf/2605.15156v2) and [https://arxiv.org/pdf/2605.15156v1](https://arxiv.org/pdf/2605.15156v1) (full PDFs, sentence-level diff)
- Code and artifacts, all verified live: [https://github.com/arunv3rma/MeMo](https://github.com/arunv3rma/MeMo), [https://arunv3rma.github.io/blogs/memo/](https://arunv3rma.github.io/blogs/memo/), [https://huggingface.co/collections/Glow-AI/memo-memory-as-a-model](https://huggingface.co/collections/Glow-AI/memo-memory-as-a-model), [https://huggingface.co/datasets/Glow-AI/MeMo](https://huggingface.co/datasets/Glow-AI/MeMo)
- Related-work URLs listed in Sec. 7, all HTTP 200 on 23 November 2026 (America/Chicago)

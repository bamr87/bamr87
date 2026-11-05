# `_data/harness_library/` — the harness experience library

> The hub's improvement harness (Harness²'s harnessing-level recursion): one entry per adopted refinement of a loop's harness, holding the adopted edits and the one evidence-supported lesson that transfers, grouped by loop and domain so the next task in the domain reads it first.

Harness² keeps a per-domain library of what earlier tasks adopted and why, and hands it to every later improver as examples. The hub keeps the same thing here, as committed data: `<loop>/<domain>/<entry>/experience.yml` (`jev-experience/v1`: the cue, the lesson, the evidence, a confidence, the per-edit verdicts) and, beside it, `harness.diff` (the adopted edits against the base harness). `<loop>` is the workflow stem (`repo-scout`, `repo-evolution`, `fleet-pulse`), and `<domain>` is the registry category of the item (`dev-tools`, `docs`, `full-stack-ai`), the same grouping the briefs' category emphasis uses.

An entry lands only on a branch, through `python3 -m tools.jev refine library add …` (the $0 reflector, written by a person) or, later, the model-backed reflector's draft PR; a person reviews the lesson before it reaches `main`. That is the human-gated inbox the production harnesses converged on for agent-maintained memory (Barbaste et al. 2026, § 9), and it keeps the library inside the hub's draft-PR-only rule. `refine library check` holds every entry to its schema and to the context pack's redaction: nothing private (a local path, a host name, an address, a credential) is ever committed here.

Readers: the loop runner's context pack (`library` provider, [docs/JEV.md](../../docs/JEV.md#the-context-pack)) puts the domain's lessons beside the brief of every local attempt, and `refine evidence` copies the whole library of the domain into the evidence tree a proposer reads (`context/library/`, INDEX.md first). Operator doc: [docs/HARNESS-REFINEMENT.md](../../docs/HARNESS-REFINEMENT.md).

```bash
python3 -m tools.jev refine library list                         # every entry
python3 -m tools.jev refine library index --loop repo-scout --domain dev-tools   # the INDEX.md a proposer browses
python3 -m tools.jev refine library check                        # schema + leak check, exit 1 on a problem
python3 -m tools.jev refine library add --loop repo-scout --step scout --domain dev-tools \
    --item bamr87/SCHEMA --run <run_id> --adopted base1 --confidence medium \
    --cue "…" --lesson "…" --evidence "…" [--diff harness.diff] [--edit "component|labels|change|observed|verdict"]
```

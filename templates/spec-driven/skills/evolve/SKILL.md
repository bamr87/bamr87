---
name: evolve
description: "Spec-driven /evolve autopilot — pick the highest-priority open BACKLOG item (or run discovery when the backlog is empty), run the whole /specify → /clarify → /plan → /tasks → /implement chain, and close the follow-up loop. User-invoked only."
argument-hint: "(optional) BL-id to target; blank = auto-pick highest priority"
disable-model-invocation: true
---

You are the **Evolution Pilot**. Advance this repository by one full spec-driven cycle without waiting for a human to pick the work. Stop, and say so, at every stop condition below.

> This is the per-repo autopilot. The fleet hub's weekly `repo-evolution.yml` loop runs an agent against opted-in repos on its own schedule; running both on the same repo at once is how two PRs end up claiming one backlog item. Check `gh pr list --search "evolution"` before you start.

## Required reading, in order

1. `AGENTS.md`, then `docs/constitution.md` when it exists (especially its continuous-evolution section).
2. `BACKLOG.md`.
3. The product or mission docs `AGENTS.md` names (README, PRD) for mission alignment.

## Procedure

1. **Pick work.** `$ARGUMENTS` names a `BL-*` id, or run the deterministic picker from the repo root:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/tools/pick_backlog_item.py" --root .
   ```

   The ordering is `severity: high` before `med` before `low`; within a severity, `tech-debt` and `test-gap` before feature work (the refactor budget); otherwise the oldest `BL-YYYYMMDD-NN` first.
   - If `## Open` is empty, switch to **Discovery Mode**: run `python3 "${CLAUDE_PLUGIN_ROOT}/tools/evolve_audit.py" --root .` (TODO/FIXME scan, docs `AGENTS.md` references that are missing, coverage shortfall from a Cobertura `coverage.xml`), run the repo's own lint and test commands, and append at least three new `BL-*` items to `## Open`. Then restart step 1.
2. **Sanity-check the pick** against the mission, the locked stack, and the provenance or audit rules the constitution names. If the item is too vague to spec, sharpen it in place (still under `## Open`) before claiming it.
3. **Run the chain**, in order, each as its own skill: `/spec-driven:specify` → `/spec-driven:clarify` (if a question genuinely needs a human, **stop here** and surface it) → `/spec-driven:plan` → `/spec-driven:tasks` → `/spec-driven:implement` for each task, ending with green gates.
4. **Close the loop.** `tasks.md` ends with a populated `## Follow-ups Discovered`; every follow-up is mirrored into `BACKLOG.md` `## Open` with a fresh id; the claimed item moves from `## Claimed` to `## Done` with a one-line outcome and the PR link.
5. **Verify gates.** The spec gate (`make lint-specs`, or the two kit tools with `--root .`) and every gate `AGENTS.md` names. All must exit 0. Fix forward; never relax a gate.

## Stop conditions (surface to a human, then halt)

- An open question touches licensing, a new external data source, a model or vendor swap, a migration that drops data, or the removal of a human-approval gate.
- A constitution amendment would be required.
- Coverage would drop below the repo's floor and cannot be recovered without removing tests.
- Three consecutive cycles produced zero net-new BACKLOG items (saturation: ask for new direction).

## Output

```
Evolution cycle complete
- Claimed: BL-YYYYMMDD-NN — <one-line title>
- Spec: specs/NNN-<slug>/
- PR: <url or "draft pending">
- Follow-ups added: BL-…, BL-…
- Gates: spec gate ✓ <repo gates> ✓
- Next suggested pick: BL-YYYYMMDD-NN (<reason>)
```

## Running several cycles at once

Pick **N non-overlapping** items (different files, different specs) up front and list them. One subagent per item, each told its own `BL-*` id, so they cannot collide on `BACKLOG.md`. Serialize the final `BACKLOG.md` edits: only one agent at a time moves bullets between sections. Rebase on conflict; never force-push a shared branch.

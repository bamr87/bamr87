# The spec-driven loop (AO-SDLC), run from the hub

> How a fleet repo turns a backlog item into a merged change with a machine-checked spec record, using machinery the hub owns.

How a fleet repo turns a backlog item into a merged change with a persistent, machine-checked record: `BACKLOG.md` → `/specify` → `/clarify` → `/plan` → `/tasks` → `/implement` → gates → PR → follow-ups → `BACKLOG.md`. The hub owns every moving part of the loop; a repo owns only its content (its specs, its backlog, its constitution) and declares that it runs the loop. The requirement is [`specs/WORK.md`](../specs/WORK.md) UPS-WORK-07; the machine contract is [`specs/WORK.contract.yml`](../specs/WORK.contract.yml); the kit is [`templates/spec-driven/`](../templates/spec-driven/README.md).

The loop was first built inside [bamr87/law-ai](https://github.com/bamr87/law-ai) (its `AO-SDLC_Outline_Guide.md` v2.0, 2026-08-11) and ported to gitorio; on 2026-10-25 the machinery was lifted out of both and into this kit so that a product repo carries no SDLC harness of its own. law-ai is the reference consumer.

## The loop at a glance

```
                 ┌────────────────────────────────────────────────┐
                 │                 BACKLOG.md                     │
                 │   append-only register of BL-YYYYMMDD-NN items │
                 └───────┬────────────────────────────▲───────────┘
        pick (human      │                            │  mirror follow-ups
        or /evolve)      ▼                            │  (the repo's constitution)
   ┌──────────┐   ┌──────────┐   ┌────────┐   ┌───────┴───┐   ┌────────────┐
   │ /specify │──▶│ /clarify │──▶│ /plan  │──▶│  /tasks   │──▶│ /implement │
   └──────────┘   └──────────┘   └────────┘   └───────────┘   └─────┬──────┘
     spec.md       resolves        plan.md      tasks.md            │
     (draft)       every OQ-N                   (FR-linked)         ▼
                                                        ┌───────────────────┐
                                                        │  Gates:           │
                                                        │  the repo's own   │
                                                        │  lint/type/test + │
                                                        │  the spec gate    │
                                                        └─────────┬─────────┘
                                                                  ▼
                                                            PR → CI → merge
```

- **Spec packages** `specs/NNN-slug/{spec,plan,tasks}.md` are the persistent memory of a change: agents re-derive context from them, CI validates against them, and `git blame` on them answers "why is the code like this". A spec carries stable `FR-*` / `NFR-*` / `AC-*` ids; every id is referenced by a task; `tasks.md` ends with a populated `## Follow-ups Discovered` section.
- **`BACKLOG.md`** is the append-only register (`- **BL-YYYYMMDD-NN** — *kind, severity* — text`, sections `## Open` / `## Claimed` / `## Done`). Every `/implement` cycle mirrors its follow-ups into it; a `/specify` claims from it; nothing is ever deleted (resolved items move to `## Done`).
- **The spec gate** is two stdlib tools: `spec_validator.py` (the three files exist, no template placeholders, no unresolved `OPEN QUESTION OQ-N`, every requirement covered by a task, `shipped` means every task is `[x]`, the follow-ups section exists, and the repo's review questions are answered) and `backlog_lint.py` (format, unique ids, append-only against the previous commit, an optional stale report). The two run in CI, as a Claude Code hook after every edit to `BACKLOG.md` or `specs/`, and as `make lint-specs` on a laptop.
- **Governance stays in the repo.** `docs/constitution.md` is the repo's own rules (mission, locked stack, quality gates, provenance, approval gates); `specs/_review_questions.json` declares the questions a spec must answer (law-ai's constitution §13, "who is the stronger here?", is the example); `specs/_template/` is the repo's own template once seeded. The kit never writes to any of them after the first seed.

## Three ways in, one kit

A repo consumes the kit **by reference**: nothing is vendored except one 70-line resolver. The machinery is versioned once, here.

| Surface | What the repo adds | What it gets |
| --- | --- | --- |
| **Claude Code plugin** `spec-driven@bamr87` | `.claude/settings.json`: `extraKnownMarketplaces.bamr87` (`github: bamr87/bamr87`, `sparsePaths: [.claude-plugin, templates/spec-driven]`) + `enabledPlugins["spec-driven@bamr87"] = true` | the skills `/spec-driven:specify`, `:clarify`, `:plan`, `:tasks`, `:implement`, `:evolve`; the `backlog-triager` agent (`@agent-spec-driven:backlog-triager`); the PostToolUse gate hook (`hooks/hooks.json` → `hooks/gate-check.sh`, tools from `${CLAUDE_PLUGIN_ROOT}/tools/`). Loads after the user trusts the workspace. |
| **Reusable workflow** [`spec-gate.yml`](../.github/workflows/spec-gate.yml) | one `uses: bamr87/bamr87/.github/workflows/spec-gate.yml@v2` job (in `ci.yml` when other jobs must `needs:` it, else the standalone caller `templates/spec-driven/workflows/spec-gate.yml`) | `spec_validator.py --strict` + `backlog_lint.py` against the caller, from a sparse checkout of the kit at `hub-ref` (default `main`); optional `stale-report` + `file-issue` (one idempotent `backlog-triage` issue; the caller declares `issues: write`) |
| **Resolver** `tools/fleet-kit.sh` | the one vendored file (byte-identical to `templates/spec-driven/fleet-kit.sh`), plus `.fleet/` in `.gitignore` | `KIT="$(tools/fleet-kit.sh)"` prints the kit directory: an explicit `FLEET_KIT_DIR`/`FLEET_HUB`, a hub checkout the repo is a submodule of, or a cached sparse clone of the hub at `FLEET_REF` (default `main`). `make lint-specs` runs `$KIT/tools/spec_validator.py --root . --strict` and `$KIT/tools/backlog_lint.py --root .` |

The declaration that binds UPS-WORK-07 is `.github/sdlc.yml`: `modules: { spec_driven: true }` and `backlog: { mode: file, file: BACKLOG.md }` ([`templates/sdlc/`](../templates/sdlc/README.md)). The checker accepts either the by-reference gate (a `uses:` of `spec-gate.yml`) or an in-repo one, and compares vendored copies against the kit only where a repo still tracks them.

### Adopting it in a repo

1. Declare the module in `.github/sdlc.yml`.
2. Enable the plugin in `.claude/settings.json` (the two keys above) and delete any vendored `.claude/commands/{specify,…,evolve}.md`, `.claude/hooks/gate-check.sh` and `prompts/` chain: the plugin replaces them.
3. Add the `uses:` job to CI and make the other jobs `needs:` it. The check context GitHub reports for a reusable-workflow job is `<caller job name> / <called job name>` (`Spec Drift Gate / Spec gate`); a branch ruleset that requires the gate names that.
4. Vendor `tools/fleet-kit.sh`, gitignore `.fleet/`, and point `make lint-specs` (or the repo's equivalent) at `$(tools/fleet-kit.sh)/tools/…`. Delete the old `scripts/spec_validator.py`, `backlog_lint.py`, `next_backlog_id.py`, `pick_backlog_item.py`, `evolve_audit.py`.
5. Seed `specs/_template/`, `BACKLOG.md`, `docs/constitution.md` and `specs/_review_questions.json` only where absent (`tools/fanout.sh --kit spec-driven` does the seeding; the plugin's `/spec-driven:specify` seeds the template on first use).

`tools/fanout.sh --kit spec-driven --target <repo>` opens the adoption PR with the resolver and the caller; the plugin enablement and the `sdlc.yml` declaration are the two human lines it names.

## Autopilot: per-repo `/evolve` and the fleet's loops

`/spec-driven:evolve` is the per-repo autopilot: it picks the top `## Open` item with the deterministic ordering in `tools/pick_backlog_item.py` (severity, then the refactor budget, then age), runs the whole chain, and closes the follow-up loop; with an empty backlog it runs **Discovery Mode** (`tools/evolve_audit.py`: TODO/FIXME scan, docs `AGENTS.md` names that are missing, a coverage shortfall from a Cobertura `coverage.xml`) and files at least three items first. It is user-invoked only (`disable-model-invocation`) and halts on every stop condition that needs a human: licensing, a new external data source, a model or vendor swap, a data-dropping migration, the removal of an approval gate, a constitution amendment.

The scheduled loops are the hub's, not the repo's. A repo that used to run its own weekly audit workflow retires it and opts into [`repo-evolution.yml`](EVOLUTION.md) (`auto_evolve: true` in the registry: one draft PR per repo per week, in the repo's own upstream, Opus, draft-only) and lets [`repo-scout.yml`](SCOUT.md) and the [issue pipeline](ISSUE-PIPELINE.md) file and resolve issues. The spec gate's `stale-report` + `file-issue` replaces a hand-rolled "stale backlog → issue" step, and the fleet scorecard's UPS-WORK-08 reports freshness (an `in-progress` spec idle past 30 days, a backlog file untouched past 60) without gating.

## Autonomy levels

| Level | Meaning | Where a fleet repo is |
| --- | --- | --- |
| 1 — Assisted | AI suggests, a human executes | completions |
| 2 — Collaborative | agents draft, humans gate | the chain run interactively; humans review the spec, the PR, the merge. **The default.** |
| 3 — Supervised autonomous | agents run end to end with oversight gates | `/spec-driven:evolve`, `repo-evolution.yml`, the issue pipeline's tiers: every one opens a draft PR and none merges |
| 4 — Fully autonomous | minimal human touch | deliberately not implemented anywhere in the fleet; raising autonomy is a constitution amendment in the repo, not a flag |

## Files

| Path | Role |
| --- | --- |
| [`templates/spec-driven/`](../templates/spec-driven/README.md) | the kit: plugin manifest, `skills/`, `agents/`, `hooks/`, `tools/`, `fleet-kit.sh`, `workflows/spec-gate.yml` caller, seed templates, `archive/`, `VERSION` |
| [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) | the `bamr87` marketplace; lists `spec-driven` at `./templates/spec-driven` |
| [`.github/workflows/spec-gate.yml`](../.github/workflows/spec-gate.yml) | the reusable gate (interface in [`WORKFLOW-VERSIONING.md`](WORKFLOW-VERSIONING.md)) |
| [`specs/WORK.md`](../specs/WORK.md) UPS-WORK-07 · [`tools/conformance.py`](../tools/conformance.py) | the requirement and its checker |
| `tools/fanout.sh --kit spec-driven` | the adoption PR |

The kit's own tests: `python3 templates/spec-driven/test_spec_driven_kit.py` (layout, plugin manifests, a round trip in a temp repo, the resolver, the audit) and `--target <repo>` to report a consumer's state.

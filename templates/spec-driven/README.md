# `spec-driven/`: the AO-SDLC kit, consumed by reference

The spec-driven workflow (`/specify` → `/clarify` → `/plan` → `/tasks` → `/implement` → `/evolve`) that bamr87/law-ai and bamr87/gitorio run, as one versioned kit that a repo **references** rather than copies. A repo opts in with `modules: { spec_driven: true }` in `.github/sdlc.yml` (see `templates/sdlc/`). From then on [`specs/WORK.md`](../../specs/WORK.md) UPS-WORK-07 binds it, the machine-readable rule is in [`specs/WORK.contract.yml`](../../specs/WORK.contract.yml), and the operator doc is [`docs/SPEC-DRIVEN.md`](../../docs/SPEC-DRIVEN.md).

## What the kit is

Three surfaces over one directory:

| Surface | Entry point | What a consumer does |
| --- | --- | --- |
| **Claude Code plugin** `spec-driven` | `.claude-plugin/plugin.json`; published by the hub root's `.claude-plugin/marketplace.json` (marketplace `bamr87`) | `.claude/settings.json`: `extraKnownMarketplaces.bamr87` = `{ "source": { "source": "github", "repo": "bamr87/bamr87", "sparsePaths": [".claude-plugin", "templates/spec-driven"] } }` and `enabledPlugins["spec-driven@bamr87"] = true`. Loads once the user trusts the workspace. Gives `/spec-driven:specify`, `:clarify`, `:plan`, `:tasks`, `:implement`, `:evolve` (`skills/`), the `backlog-triager` agent (`agents/`), and the gate hook (`hooks/hooks.json` → `hooks/gate-check.sh`, tools from `${CLAUDE_PLUGIN_ROOT}/tools/`). |
| **Reusable workflow** | `bamr87/bamr87/.github/workflows/spec-gate.yml` (caller template: `workflows/spec-gate.yml`) | one `uses: …/spec-gate.yml@v2` job; every other job in that workflow `needs:` it. The gate checks out this directory beside the caller and runs `tools/spec_validator.py --root . --strict` + `tools/backlog_lint.py --root .`; `stale-report` + `file-issue` keep one idempotent `backlog-triage` issue. |
| **Resolver** | `fleet-kit.sh` → vendored as `tools/fleet-kit.sh` | `KIT="$(tools/fleet-kit.sh)"` prints this directory (an explicit `FLEET_KIT_DIR` / `FLEET_HUB`, a hub checkout the repo is a submodule of, or a cached sparse clone at `.fleet/hub` on `FLEET_REF`, default `main`; `--update` refreshes). `make lint-specs` runs `$KIT/tools/…`. Gitignore `.fleet/`. |

## Contract

- **Byte-identity files.** `tools/spec_validator.py`, `tools/backlog_lint.py`, `tools/next_backlog_id.py` and `tools/pick_backlog_item.py` must be byte-identical to this kit's copies wherever a repo still tracks them (under `tools/` or `scripts/`); `fleet-kit.sh` likewise. A by-reference consumer tracks only the resolver. Never edit a copy in a leaf repo; change the kit and bump `VERSION`.
- **Repo-specific behaviour is data.** Review questions a spec must answer go in `specs/_review_questions.json` (format in the `spec_validator.py` docstring). With no file there are no questions. `review-questions.example.json` is law-ai's constitution §13 check.
- **The hook** (`hooks/gate-check.sh`) runs both gates after an edit to `BACKLOG.md` or `specs/` and blocks with the failure output. In plugin mode `hooks/hooks.json` wires it and the tools come from the plugin; vendored at `.claude/hooks/gate-check.sh` it finds `tools/` or `scripts/`.
- **Templates are seeded once.** After that the repo owns `specs/_template/`, `BACKLOG.md` and `docs/constitution.md`. `spec_validator.py` relies on the `TEMPLATE_MARKERS` that `specs/_template/` keeps; `/spec-driven:specify` seeds the template from the plugin when a repo has none.
- **CI** (UPS-WORK-07): one workflow job is the spec gate — a `uses:` of `spec-gate.yml`, or an in-repo job running `spec_validator.py` and `backlog_lint.py` — and every other job in that workflow transitively `needs` it. Check out with `fetch-depth: 2` and compare the backlog against `HEAD^1` (the reusable gate does both).
- **Autopilot.** `/spec-driven:evolve` is user-invoked only and halts on every stop condition that needs a human. Scheduled evolution is the hub's `repo-evolution.yml` (`auto_evolve: true` in the registry), not a per-repo workflow.

## Files and where they land

| Kit file | Consumed as | Kind |
| --- | --- | --- |
| `.claude-plugin/plugin.json`, `skills/*/SKILL.md`, `agents/backlog-triager.md`, `hooks/hooks.json` | the plugin (nothing lands in the repo) | by reference |
| `tools/spec_validator.py`, `tools/backlog_lint.py`, `tools/next_backlog_id.py`, `tools/pick_backlog_item.py`, `tools/evolve_audit.py` | the plugin's `${CLAUDE_PLUGIN_ROOT}/tools/`, the reusable workflow, `$(tools/fleet-kit.sh)/tools/` — or vendored at `tools/` | by reference (byte-identity when vendored) |
| `fleet-kit.sh` | `tools/fleet-kit.sh` | byte-identity |
| `workflows/spec-gate.yml` | `.github/workflows/spec-gate.yml`, or its `uses:` job moved into `ci.yml` | kit-owned caller |
| `hooks/gate-check.sh` | the plugin hook; or `.claude/hooks/gate-check.sh` wired as a PostToolUse `Write\|Edit` hook | kit-owned |
| `specs/_template/{spec,plan,tasks}.md` | `specs/_template/` | seed once |
| `BACKLOG.template.md` | `BACKLOG.md` (`__PROJECT_NAME__` substituted) | seed once |
| `constitution.template.md` | `docs/constitution.md` | seed once |
| `review-questions.example.json` | `specs/_review_questions.json` (optional) | example |
| `archive/*-0.0.0-{law-ai,gitorio}.*` | nowhere; used by upgraders to recognise pre-kit copies | provenance |
| `test_spec_driven_kit.py` | nowhere; the kit's own tests | test |

## Adoption

1. Declare it in `.github/sdlc.yml`: `modules: { spec_driven: true }` and `backlog: { mode: file, file: BACKLOG.md }` (D1: a file backlog must be declared and linted).
2. Enable the plugin in `.claude/settings.json` (the two keys above). Delete any vendored chain: `.claude/commands/{specify,clarify,plan,tasks,implement,evolve}.md`, `.claude/hooks/gate-check.sh`, a `prompts/` directory.
3. Add the `uses:` job (`workflows/spec-gate.yml`, or inside `ci.yml`) and make the other jobs `needs:` it. A branch ruleset requiring it names the context `<caller job name> / Spec gate`.
4. Vendor `fleet-kit.sh` as `tools/fleet-kit.sh`, gitignore `.fleet/`, and point `make lint-specs` at `$(tools/fleet-kit.sh)/tools/…`. Delete old `scripts/` or `tools/` copies of the gates.
5. Seed `specs/_template/`, `BACKLOG.md`, `docs/constitution.md` and (optionally) `specs/_review_questions.json` only if absent.
6. Check it: `python3 templates/spec-driven/test_spec_driven_kit.py --target <repo>` (from a hub checkout) reports which mode a repo is in and whether anything it vendors has drifted.

`tools/fanout.sh --kit spec-driven --target <repo>` does steps 3–5 as a PR and names steps 1–2 in its body.

## Tests

`python3 templates/spec-driven/test_spec_driven_kit.py` is stdlib-only. It checks the kit's layout and `VERSION`, the plugin and marketplace manifests, the hook wiring, a full round trip in a temp repo (seed → both gates pass → break the backlog → lint fails → the hook blocks, in vendored and plugin mode), review-question warnings with and without the JSON file, the id minter, the picker, the discovery audit, and the resolver (parent-hub mode).

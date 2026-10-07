# `spec-driven/`: the AO-SDLC spec-driven kit

The spec-driven workflow (`/specify` → `/clarify` → `/plan` → `/tasks` → `/implement` → `/evolve`) that bamr87/law-ai and bamr87/gitorio run, as one versioned kit. A repo opts in with `modules: { spec_driven: true }` in `.github/sdlc.yml` (see `templates/sdlc/`). From then on, [`specs/WORK.md`](../../specs/WORK.md) UPS-WORK-07 binds it, and the machine-readable rule is in [`specs/WORK.contract.yml`](../../specs/WORK.contract.yml).

## Contract

- **Byte-identity files.** The files `tools/spec_validator.py`, `tools/backlog_lint.py`, `tools/next_backlog_id.py` and `tools/pick_backlog_item.py` must be byte-identical to this kit's copies wherever a repo tracks them, under `tools/` or `scripts/`. The contract's `spec_driven_kit` and `spec_driven_tools` definitions name this directory and these four files. Never edit a copy in a leaf repo; change the kit and bump `VERSION`.
- **Repo-specific behaviour is data.** Review questions a spec must answer go in `specs/_review_questions.json` (format in the `spec_validator.py` docstring). With no file there are no questions. `review-questions.example.json` is law-ai's constitution §13 check, which used to be hard-coded.
- **The hook** (`hooks/gate-check.sh`) is a Claude Code PostToolUse hook that runs both gates after an edit to `BACKLOG.md` or `specs/` and blocks with the failure output. It finds the tools in `tools/` (the fleet default) or `scripts/` (law-ai's layout). It isn't a byte-identity file, but keep it in step.
- **Templates are seeded once.** After that the repo owns `specs/_template/`, `BACKLOG.md` and `docs/constitution.md`. `spec_validator.py` relies on the `TEMPLATE_MARKERS` that `specs/_template/` keeps.
- **CI** (UPS-WORK-07): one workflow job runs `spec_validator.py`, every other job in that workflow transitively `needs` it, and the same workflow runs `backlog_lint.py`.

## Files and where they land

| Kit file | Lands at | Kind |
| --- | --- | --- |
| `tools/spec_validator.py` | `tools/spec_validator.py` | byte-identity |
| `tools/backlog_lint.py` | `tools/backlog_lint.py` | byte-identity |
| `tools/next_backlog_id.py` | `tools/next_backlog_id.py` | byte-identity |
| `tools/pick_backlog_item.py` | `tools/pick_backlog_item.py` | byte-identity |
| `hooks/gate-check.sh` | `.claude/hooks/gate-check.sh` (wire it as a PostToolUse `Write\|Edit` hook) | kit-owned |
| `specs/_template/{spec,plan,tasks}.md` | `specs/_template/` | seed once |
| `BACKLOG.template.md` | `BACKLOG.md` (`__PROJECT_NAME__` substituted) | seed once |
| `constitution.template.md` | `docs/constitution.md` | seed once |
| `review-questions.example.json` | `specs/_review_questions.json` (optional) | example |
| `archive/*-0.0.0-{law-ai,gitorio}.*` | nowhere; used by upgraders to recognise pre-kit copies | provenance |
| `test_spec_driven_kit.py` | nowhere; the kit's own tests | test |

## Adoption

1. Declare it in `.github/sdlc.yml`: `modules: { spec_driven: true }` and `backlog: { mode: file, file: BACKLOG.md }` (D1: a file backlog must be declared and linted).
2. Copy the four tools and the hook. Seed `specs/_template/`, `BACKLOG.md` and `docs/constitution.md` only if they are absent.
3. Add a CI job that runs `python3 tools/spec_validator.py` and `python3 tools/backlog_lint.py`, and make the other jobs `needs` it. Check out with `fetch-depth: 2` and set `BACKLOG_LINT_BASE: HEAD^1`; otherwise the append-only check compares HEAD with itself.
4. Check it: `python3 templates/spec-driven/test_spec_driven_kit.py --target <repo>` (run from a hub checkout) reports the byte-identity and layout of a leaf repo.

**Migrating law-ai and gitorio.** Swap each repo's copies for the kit's. law-ai also gets `specs/_review_questions.json` copied from `review-questions.example.json`. Kit 0.1.0 reproduces both repos' current output exactly: law-ai with 53 specs and 526 backlog entries, gitorio with 14 specs and 98 entries. Until they're migrated, their copies differ from the kit, and UPS-WORK-07 reports that.

## Tests

`python3 templates/spec-driven/test_spec_driven_kit.py` is stdlib-only. It checks the kit's layout, that `VERSION` lists every file, that the archives are present, a full round trip in a temp repo (seed → both gates pass → break the backlog → lint fails → the hook blocks), review-question warnings with and without the JSON file, the id minter, and the picker.

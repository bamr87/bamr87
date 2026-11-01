---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev

> JEV, the harness-level agent logic engine: the assign-at-merge numbering compiler (`number.py`), the tiered pull-request conflict triage and resolution engine (`conflicts.py`, `classify.py`, `ledger.py`), the loop step specs (`spec.py`, `steps/`), the headless Claude Code executor layer (`headless.py`), the local loop runner built on them (`loop.py`, `workspace.py`, `adapters/`), and its context pack (`context.py`). Entry point `python3 -m tools.jev`; doc `docs/JEV.md`.

## Conventions

- Python 3.12, stdlib + PyYAML. Every GitHub call goes through `common.gh`, which refuses `--admin` and refuses `pr merge`; every subprocess returns a `Run` rather than raising, because a failing trial merge is data.
- A module is importable with no side effects: configuration is read when a function asks for it, never at import.
- Tests live beside the other hub gates as `tools/test_jev_*.py` (collected by `run-all-tests.sh` and `python-tests.yml`), not in this directory.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | How to run JEV, set up the merge driver, and read the tier ladder | required |
| `__init__.py` | file | Package marker and version | required |
| `__main__.py` | file | The CLI entry point — the `number`, `conflicts`, `generated`, `steps` and `loop` command groups | required |
| `common.py` | file | Hub paths, `_data/fleet.yml` `jev:` / `budget.jev` reader, the `gh` and `git` wrappers (no hooks, no fsmonitor), the guards they apply (no merge, no `--admin`, no destructive or settings verb, no `gh api` but a GET or an inline GraphQL query, no force-push in any spelling), the shared `owner/repo` and bare-file-name checks, the subprocess helper (merged or replaced environment) and the named-keys `.env` reader | required |
| `classify.py` | file | The deterministic classifier: conflicted file → kind, and (files, hunks, lines, history) → one tier | required |
| `number.py` | file | The assign-at-merge compiler: fragments → `features/features.yml`, `PRD.md`, `CHANGELOG.md`, `docs/amendments/NNNN-*.md`; plus the hand-picked-number lint | required |
| `conflicts.py` | file | Detect, trial-merge, triage, resolve by tier, validate, push a merge commit, escalate | required |
| `ledger.py` | file | `_data/jev_resolutions.yml` — append-only cost records and the monthly cap arithmetic | required |
| `merge-regen.sh` | file | The `jev-regen` git merge driver: keep ours, record the path for regeneration | required |
| `generated.py` | file | Main-only generated files: list them, guard pull requests against editing them, regenerate them on main | required |
| `headless.py` | file | The local loop runner's headless Claude Code layer: the § 13.8 isolation flags, the `--settings` sandbox document, the agent environment built from scratch, the CLAUDE_AUTH_ORDER credential choice, redaction, the SIGINT-first streaming runner, the outcome classifier, the $0 probes, the per-run posture checks and the canary's judge (imported by dash-gen `ai-run`, never the reverse) | required |
| `spec.py` | file | Loop step specs: load and validate a `steps/<loop>/<step>.yml` and its optional `local:` block, resolve its `_data/fleet.yml` references (exact model ids only), render its prompt and argv templates in one pass, and hold it equal to its workflow, the kill switch included (`steps check`, `steps render`) | required |
| `loop.py` | file | The local loop runner, `python3 -m tools.jev loop` (`list`, `doctor [--live]`, `plan`, `run`, `publish`, `show`, `budget`): gates, the host checks, the `budget.loops` ceiling, the plan, tier 0, classify, the workspace, the attempt through `dash-gen ai-run`, the per-run posture checks, harvest and validation, the dry-run preview, the `--apply` gate and the filing, the canary, and the run record under `.fleet/runs/` | required |
| `workspace.py` | file | The runner's throwaway workspaces: a hardened clone outside the hub under `~/.cache/jev/work`, an engine-held pristine GIT_DIR that every engine git call on the clone uses, a tamper baseline over `.git` and any nested `.git`, a no-follow, regular-file-only harvest, and a `destroy` that never chmods through a symlink | required |
| `context.py` | file | The loop runner's context pack, engine half: this loop's earlier attempts on the item (`attempts.jsonl`, `validate.json`), the planes' `fleet-context/v1` document through `ctx.dash_gen(['context', …])` (a subprocess, never an import), the markdown render (data inside fences no row can close, a size cap trimmed lowest priority first), redaction, the 0600 `context.md` / `context.json` in the item's run directory, the brief pointer paragraph and the status line; modes `auto`, `off`, `require` (tested by `tools/test_jev_context.py`) | required |
| `adapters/` | dir | One adapter per loop the runner can run (the contract and `REGISTRY`); see its SCHEMA | |
| `steps/` | dir | The loop step specs themselves, one directory per loop workflow (data only); see its SCHEMA | |

## Placement

- New JEV capability → a module here plus a `tools/test_jev_<name>.py`, a row in this table, and a section in `docs/JEV.md`.
- New loop agent step → a spec pair under `steps/<workflow stem>/` (see `steps/SCHEMA.md`), never a prompt inline in a workflow.
- A loop step that runs locally → its spec's `local:` block, plus `adapters/<name>.py` registered in `adapters.REGISTRY`, plus `tools/test_jev_adapter_<name>.py`.

## Forbidden

- No `gh pr merge`, no `--admin`, no repository-settings call, no `gh api` write — asserted in `common.assert_no_admin`; no force-push — asserted in `common.assert_safe_git`; both covered by `tools/test_jev_conflicts.py`.
- No secret, token or model credential in this directory; the `claude` CLI reads its own environment.
- No import of dash-gen (`.github/scripts/dash-gen/`) from any module here; dash-gen imports `tools.jev` lazily, never the reverse.
- No GitHub credential in a local loop-step agent's environment, and no loop-step `claude -p` outside `headless.claude_flags` and `headless.agent_env` (ADR 0002, P1) — except `conflicts.claude_argv` (tiers 1–2), not yet isolated and switched off by `jev.auto_tiers: [tier0]`; it moves onto headless.py before tier1 or tier2 is enabled.
- No `--dangerously-skip-permissions`, `bypassPermissions` or `--bare` in an agent argv.
- No publish without the § 13.6 gate, no unattended (`--scheduled`) local filing, and no sandbox-posture attempt without a passing isolation probe and canary for the installed CLI.
- No workspace inside the hub tree, and no run record outside the gitignored `.fleet/runs/`.

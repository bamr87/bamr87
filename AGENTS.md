# Agent guide — bamr87 dash

## Boundaries and entrypoints

- This root repo is the fleet control plane plus a GitHub profile and Jekyll site. `projects/*` are independent Git submodules with their own dependencies, tests, and releases; there is no shared package build. Read the target project's README and agent instructions before working there.
- `_data/projects.yml` is the project registry; `.gitmodules` must agree on submodule paths, URLs, and branches. Read those files instead of hardcoding a project list or assuming `main`. When committing submodule work, commit in that repo first, then record its SHA in the parent; see [SUBMODULES.md](SUBMODULES.md).
- `tools/dash` is the shell command router. `tools/dash-gen` wraps `.github/scripts/dash-gen/dash_gen.py`; generator implementations and most control-plane tests live beside that Python entrypoint. `tools/console/` is the local FastAPI Harness Console.
- The published Pages site is the root Jekyll site (`pages/_dash/`, `index.md`, `_config.yml`), built by `.github/workflows/build-dash.yml`. MkDocs belongs to `projects/README/`; its `docs/` contains aggregated copies, so edit the original project sources rather than those copies.
- Orient through [SCHEMA.md](SCHEMA.md) and the schema chain to the target directory. Detailed references: [docs/DASH.md](docs/DASH.md) for architecture, [CATALOG.md](CATALOG.md) for available tools/kits, [CLAUDE.md](CLAUDE.md) for operational context, and `.github/instructions/*.instructions.md` by `applyTo` scope. House rule: read the relevant README first and update it to reflect the change.

## Development and focused verification

Run the following from the repository root. Prefer the `devenv` container (`/workspace`); create `.env` from `.env.example` before first startup if it is absent.

```bash
tools/dash up                         # shared workspace, console, Postgres, Redis
docker compose exec devenv bash      # commands below run from /workspace
python3 -m pip install -r .github/scripts/dash-gen/requirements.txt
```

The generator requires PyYAML and PyGithub. CI uses Python 3.12 and Ruby 3.3; fleet defaults live in `_data/fleet.yml` under `toolchain`. `tools/dash-gen` and `tools/check-drift.sh` honor `PYTHON=/path/to/python` when using a local virtual environment.

| Scope | Command / behavior |
| --- | --- |
| Root drift gate | `tools/check-drift.sh` — registry parity, generated README, schema, dependency policy, action manifests; `--ci` also makes advisory GitHub API checks |
| Schema only | `python3 tools/schema_lint.py check .` — schema warnings also fail the drift gate |
| One generator test file | `python3 .github/scripts/dash-gen/test_machine_api.py` — offline fixtures |
| One unittest case | `python3 .github/scripts/dash-gen/test_machine_api.py MachineApiTests.test_degraded_without_inputs` |
| CV projection tests | `python3 -m pytest .github/scripts/dash-gen/test_cv_fragment.py -q` — requires pytest; this file has no standalone runner |
| Root config smoke test | `bundle exec rake test` — parses Jekyll config and checks registry keys; no site build |
| Shell changes | `shellcheck tools/*.sh tools/observability/*.sh` |
| Workflow changes | `actionlint .github/workflows/*.yml` |

- `tools/run-all-tests.sh` (also `tools/dash test`) runs root checks, direct `test_*.py` invocations under dash-gen and console, then checked-out submodule suites. It skips projects without installed local dependencies; green means only the executed checks passed. Run the CV pytest command separately when changing that projection.
- Markdown prose is **one paragraph per line**. Check edited files with `python3 tools/unwrap-prose.py --check AGENTS.md README.md` (substitute the changed paths; `--write` fixes). Respect `.prettierignore`: Prettier can corrupt Liquid in `pages/` and `index.md`, and desynchronize generated Markdown.
- Hook activation is clone-specific: Husky, pre-commit, and the global prose hook compete through `core.hooksPath`. Diagnose with `bash tools/audit-git-hooks.sh`. The root has no `package.json`, despite `.husky/pre-commit` invoking `pnpm lint-staged`.

## Sources of truth and generated files

- `_data/fleet.yml` owns control-plane settings (toolchains, schedules, budgets, token names, container groups); `_data/standards.yml` owns tier requirements. `_data/` is public site data, not a place for credential values.
- After registry/submodule changes, regenerate affected projections rather than editing their output:

  ```bash
  tools/dash-gen readme                 # README AUTO:projects span only
  tools/gen-projects-schema.py          # projects/SCHEMA.md
  tools/dash-gen cv                     # _data/cv_portfolio.json proposal
  tools/check-drift.sh
  ```

- Add/remove/rename files in the nearest `SCHEMA.md` in the same change. New directories need their own schema and a parent Structure row; follow `Placement` and `Forbidden`. `projects/*` are terminal boundaries of the hub schema. Regenerate `CATALOG.md` with `tools/gen-catalog.py` after adding catalogued tools/docs/kits; regenerate `_data/specs.yml` with `tools/gen-specs-data.py` after editing requirement tables in `specs/`.
- `_data/project_health.yml`, `_data/project_health_meta.yml`, `_data/ai_activity.yml`, `_site/`, and `.fleet/compose/` are ephemeral/ignored. Other snapshots such as `_data/fleet_triage.yml` and `_data/actions_usage.yml` are intentionally committed; check the generator's README before refreshing data.
- Dependency policy deliberately floats versions: no exact package pins, upper bounds, or committed lockfiles. Actions use major tags; pre-commit revisions and fleet-governed toolchain versions are exceptions. See [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md). `tools/schema_lint.py` is vendored from `bamr87/SCHEMA`: fixes go upstream, then are re-vendored.

## Site and fleet gotchas

- `tools/dash serve` installs gems and serves the dash on port 4000 using `_config.yml,_config_dev.yml` (Docker, with native fallback). The dev override clears the production `/bamr87` base URL. `remote_theme: bamr87/zer0-mistakes` does **not** import the theme's config or data; required settings must exist here. Restart Jekyll after config changes.
- Production build order is `bundle exec jekyll build` with `JEKYLL_ENV=production`, then `tools/dash-gen machine-api --out _site`. Jekyll alone does not emit the machine API. For fleet prioritization, start at [api/v1/index.json](https://bamr87.github.io/bamr87/api/v1/index.json), then the linked fleet inbox; see [docs/MACHINE-API.md](docs/MACHINE-API.md).
- Fleet apps run as **separate Compose projects** on the shared `fleet` network; combining their compose files with `include:` collides on service names. Use `tools/dash up <project>` or `tools/dash up --group jekyll`; generate port/network overrides with `tools/dash gen compose` from registry `dev_port` values. Overrides live in the hub's `.fleet/compose/`, never in submodules. The hub's Compose project name defaults to `fleet`, so worktrees share its services and volumes. See [docs/CONTAINERS.md](docs/CONTAINERS.md).

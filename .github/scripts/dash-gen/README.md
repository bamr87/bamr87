# dash-gen

Registry-driven generator for the development dash. Reads the single source of
truth — [`_data/projects.yml`](../../../_data/projects.yml) — and:

- **`health`** → gathers live GitHub signals (stars, CI build stats, issues, PRs,
  commit activity, security alerts, latest release) per project, computes an
  **attention level** (red/amber/green + reasons) from
  [`_data/health_thresholds.yml`](../../../_data/health_thresholds.yml),
  and writes `_data/project_health.yml`. This file is **ephemeral** —
  generated at deploy time, gitignored, never committed.
- **`readme`** → rewrites only the `<!-- AUTO:projects -->` span of the profile
  [`README.md`](../../../README.md) from the registry's static facts. Deterministic
  and safe to commit. `--check` fails (non-zero) if the span is stale instead of
  writing — used by the drift gate.
- **`all`** → `health` then `readme`.

## Usage

```bash
pip install -r .github/scripts/dash-gen/requirements.txt
gh auth login                       # health needs GitHub API access (or GH_TOKEN in CI)

python .github/scripts/dash-gen/dash_gen.py health
python .github/scripts/dash-gen/dash_gen.py readme [--check]

# or via the wrapper:
tools/dash-gen health
tools/dash-gen readme
```

GitHub access uses the `gh` CLI, so failures degrade gracefully (a project that
can't be reached yields nulls, not a crash).

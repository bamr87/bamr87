# Machine API

Stable, agent-facing JSON published on GitHub Pages so bots can prioritize fleet work without scraping the Bootstrap dash.

**Start URL:** https://bamr87.github.io/bamr87/api/v1/index.json

Also: https://bamr87.github.io/bamr87/llms.txt

## Endpoints

| Path | Source | Purpose |
| --- | --- | --- |
| `/api/v1/index.json` | derived | Discovery, how-to-use, current top inbox hint |
| `/api/v1/fleet.json` | `_data/fleet_triage.yml` | Priority `inbox[]` + totals + compact `by_repo` |
| `/api/v1/health.json` | `_data/project_health.yml` (ephemeral) | Per-repo attention board |
| `/api/v1/harness.json` | `_data/harness_health.yml` | Scorecard + trip wires |
| `/api/v1/issues.json` | `_data/issue_pipeline.yml` | Pipeline stages / caps |
| `/llms.txt` | derived | Plain-text agent discovery |

`schema_version` is currently `1.0`. Missing inputs emit `status: "degraded"` with a reason — never a hard build failure.

## How bots should use it

1. `GET /api/v1/index.json`
2. `GET /api/v1/fleet.json` and work `inbox[]` in array order (failing workflows first)
3. Optionally `GET /api/v1/health.json` for attention levels when present
4. Prefer `agent:ready` / P0–P1; skip `agent:blocked` unless unblocking

Human mirrors: `/triage/`, `/monitor/`.

## Generation

```bash
# after registries exist (and optionally after dash-gen health):
python .github/scripts/dash-gen/dash_gen.py machine-api --out _site
```

`build-dash.yml` runs this after `jekyll build` and before the Pages artifact upload. Outputs live under `_site/` only — they are **not** committed.

## Tests

```bash
python3 .github/scripts/dash-gen/test_machine_api.py
```

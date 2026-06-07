# dash/ — the central dashboard site

A Jekyll site that consumes the **`bamr87/zer0-mistakes`** remote theme and serves
the portfolio, dashboard, monitoring board, and toolbox at
`https://bamr87.github.io/bamr87/`.

## What's here

| Path | Purpose |
|---|---|
| `_data/projects.yml` | **The project registry — single source of truth.** Edit this to add/update projects. |
| `_data/project_health.yml` | Generated monitoring data (gitignored, built at deploy). Do not edit/commit. |
| `_data/health_thresholds.yml` | Tunable thresholds for the attention (red/amber/green) calculation. |
| `_data/navigation/main.yml` | Header navigation. |
| `_data/{scripts,skills,templates}.yml` | Toolbox catalogs. |
| `index.md` | Landing page + "Needs Attention" strip. |
| `portfolio.md` `dashboard.md` `monitor.md` `toolbox.md` `resume.md` `docs.md` | Dash pages (registry-driven). |
| `_config.yml` / `_config_dev.yml` | Production / local-dev configuration. |
| `Gemfile` | GitHub Pages compatible toolchain. |

## Local development

```bash
# From repo root, via the dev container (Jekyll on port 4000):
docker compose up -d devenv
docker compose exec devenv bash -lc \
  'cd /workspace/dash && bundle install && bundle exec jekyll serve -H 0.0.0.0 -c _config.yml,_config_dev.yml'
# → http://localhost:4000

# Or natively:
cd dash && bundle install && bundle exec jekyll serve -c _config.yml,_config_dev.yml
```

To populate the live monitoring board locally:

```bash
gh auth login            # one-time
tools/dash-gen health     # writes dash/_data/project_health.yml
```

## Deployment

`.github/workflows/build-dash.yml` regenerates health data, builds this site, and
deploys to GitHub Pages on push to `main` (paths `dash/**`, `README.md`) and on a
6-hourly schedule. Pages **Source** must be set to **"GitHub Actions"**.

## How it stays current

The registry feeds every surface. To add a project, append an entry to
`_data/projects.yml`; the portfolio, dashboard, monitor, and the profile
`README.md` AUTO section all update from it. See [`docs/DASH.md`](../docs/DASH.md).

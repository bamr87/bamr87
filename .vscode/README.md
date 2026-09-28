# VS Code Launch Configurations

[`launch.json`](launch.json) is Docker-first. Every F5 runs `docker compose exec` / `up` against [`docker-compose.yml`](../docker-compose.yml) so VS Code, the CLI, and CI execute the same containerized code. Nothing installs or runs on the host except:

- **Edge** attaching to a container-published port
- **Extension Host** (VS Code itself), after compile inside `devenv`

Coverage: the local control-plane stack ([`docs/HARNESS-OPS.md`](../docs/HARNESS-OPS.md) "The local stack") **and** one entry per Git submodule under `projects/` (registry: [`_data/projects.yml`](../_data/projects.yml), paths from [`.gitmodules`](../.gitmodules)).

## Groups

| Group | What it covers |
| --- | --- |
| **1-view** | Jekyll dash in Docker: Edge against `localhost:<port>` with compose up/stop, attach to a running browser, or force-rebuild first |
| **2-generators** | `dash-gen` inside `devenv` (subcommand picker + harness inventory live / `--offline` / `--gaps`), Harness Console compose logs on :4001, lake sync/status/export |
| **3-verify** | dash-gen fixture test (`test_*.py` are plain scripts, not pytest) via `devenv python3` |
| **4-docs** | MkDocs compose service for `projects/README/` on **:8001**; `projects/ai-seed/` via devenv on **:8003** |
| **5-jekyll** | Submodule Jekyll sites via devenv on **4010–4020** (livereload 35730–35740) so they never collide with the hub dash on :4000 |
| **6-apps** | Vite/Node via devenv: cv-builder-pro :5000, gitnexus :8080, gitorio :5174, rewind-arcade :5175, aieo UI :5176, fredgar-ai UI :5177, plus `cv` build/watch |
| **7-python** | Django runserver via devenv (barodybroject :8010, fredgar-ai :8011, law-ai :8012, djangoerp :8013), aieo FastAPI :8002, pytest on the open file |
| **8-ext** | Compile inside devenv (`devenv: compile …` tasks), then Extension Host on the host |
| **9-cli** | Python/Node CLIs via devenv defaulting to `--help` (bashos, ocrmd, lawmode, wtd, books, gwtp) plus bashcrawl `npm test` and pytest for githubai / zer0-image-generator |
| **10-content** | scripts (current file via devenv `python3`), 1987 `index.md` and microsoft/skills `Agents.md` via devenv `head` (no host `code`) |

Live `dash-gen` gathers use compose env (`GH_TOKEN`/`FLEET_TOKEN`/`GITHUB_TOKEN`); every generator degrades rather than dies without it. `lake` takes a sub-subcommand, which is why it has its own entries rather than a slot in the picker.

## Ports

Hub compose map: **4000** dash · **4001** console · **5000** CV Builder · **5173** Vite HMR · **8000** MkDocs-in-devenv · **8001** compose MkDocs · **6006** Phoenix.

Submodule servers bind **0.0.0.0** inside `devenv` and publish on loopback:

| Range | Use |
| --- | --- |
| 4010–4020 / 35730–35740 | Jekyll + LiveReload |
| 5174–5177 | Vite apps (gitorio, rewind-arcade, aieo, fredgar-ai) |
| 8080 | gitnexus (`npm run dev`) |
| 8002 | aieo FastAPI |
| 8003 | ai-seed MkDocs |
| 8010–8013 | Django fleet |

If an existing `devenv` was started before those mappings existed, recreate it: `docker compose up -d --force-recreate devenv`.

## Tasks ([`tasks.json`](tasks.json))

Silent preLaunch helpers:

- `Docker: Ensure devenv` / `console` / `mkdocs` / `phoenix` / `lake stack`
- `devenv: compile csv-vscoode` / `vs-sonic-pi` / `zpl-viewer` / `zer0-cms` (depends on Ensure devenv)

Gems, npm, and pip live **inside devenv**, not on the host. Install there, e.g. `docker compose exec -T -w /workspace/projects/<name> devenv npm install`.

## Inputs

- `portNumber`: compose port map — 4000 Jekyll dash (default), 5000 CV Builder, 5173 Vite HMR, 8000 MkDocs.
- `dashGenCommand`: the `dash-gen` subcommand list (see [`.github/scripts/dash-gen/README.md`](../.github/scripts/dash-gen/README.md)).

## Notes

- The pre-2026 Django and PostHog configurations that used to live here targeted repositories this one doesn't contain; recover them from git history if ever wanted.

Last modified: 2026-09-19


# VS Code Launch Configurations

[`launch.json`](launch.json) wraps the local control-plane stack documented in [`docs/HARNESS-OPS.md`](../docs/HARNESS-OPS.md) ("The local stack") **and** one debug entry per Git submodule under `projects/` (registry: [`_data/projects.yml`](../_data/projects.yml), paths from [`.gitmodules`](../.gitmodules)). Hub entries are debuggers around a `tools/` entrypoint or Docker Compose, so VS Code, the CLI, and CI execute the same code.

## Groups

| Group | What it covers |
| --- | --- |
| **1-view** | Jekyll dash in Docker: Edge against `localhost:<port>` with compose up/stop, attach to a running browser, or force-rebuild first |
| **2-generators** | `dash-gen` under debugpy (subcommand picker + harness inventory live / `--offline` / `--gaps`), Harness Console on :4001, lake sync/status/export |
| **3-verify** | Open dash-gen fixture test (`test_*.py` are plain scripts, not pytest) |
| **4-docs** | MkDocs serve/build for `projects/README/` (owns the MkDocs site) and `projects/ai-seed/` on :8001 |
| **5-jekyll** | Submodule Jekyll sites on **4010–4020** (livereload 35730–35740) so they never collide with the hub dash on :4000 |
| **6-apps** | Vite/Node apps: cv-builder-pro :5000, gitnexus :8080, gitorio :5174, rewind-arcade :5175, aieo UI :5176, fredgar-ai UI :5177, plus `cv` build/watch |
| **7-python** | Django runserver (barodybroject :8010, fredgar-ai :8011, law-ai :8012, djangoerp :8013), aieo FastAPI :8002, pytest on the open file |
| **8-ext** | Extension Host: csv-vscoode, vs-sonic-pi, zpl-viewer, zer0-cms |
| **9-cli** | Python/Node CLIs defaulting to `--help` (bashos, ocrmd, lawmode, wtd, books, gwtp) plus bashcrawl `npm test` and pytest for githubai / zer0-image-generator |
| **10-content** | scripts (current file), 1987 `index.md`, microsoft/skills `Agents.md` |

Live `dash-gen` gathers use `gh` auth (`GH_TOKEN`/`GITHUB_TOKEN`); every generator degrades rather than dies without it. `lake` takes a sub-subcommand, which is why it has its own entries rather than a slot in the picker.

## Ports

Hub compose map stays **4000** dash · **4001** console · **5000** CV Builder · **5173** Vite HMR · **8000** MkDocs. Submodule servers use offsets (4010+, 5174+, 8001+, 8010+) so two F5s do not collide. gitnexus keeps **8080** because that is what `npm run dev` binds.

## Inputs

- `portNumber`: compose port map — 4000 Jekyll dash (default), 5000 CV Builder, 5173 Vite HMR, 8000 MkDocs.
- `dashGenCommand`: the `dash-gen` subcommand list (see [`.github/scripts/dash-gen/README.md`](../.github/scripts/dash-gen/README.md)).

## Notes

- Jekyll / Vite / Django / CLI configs assume that submodule's own gems/npm/venv are already installed (`bundle install`, `npm install`, `pip install -e .` inside `projects/<name>/`).
- Extension Host configs need a prior compile (`out/` or `dist/` per that repo's `package.json` `main`).
- Content entries for 1987 and skills open the working tree; they are not long-lived servers.
- The pre-2026 Django and PostHog configurations that used to live here targeted repositories this one doesn't contain; recover them from git history if ever wanted.

Last modified: 2026-09-19

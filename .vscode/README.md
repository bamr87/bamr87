# VS Code Launch Configurations

`launch.json` wraps the same local control-plane stack documented in [`docs/HARNESS-OPS.md`](../docs/HARNESS-OPS.md) ("The local stack") — every configuration is a debugger around a `tools/` entrypoint or the Docker compose services, so VS Code, the CLI, and CI all execute the same code.

Groups (as they appear in the Run and Debug dropdown):

- **1-view** — the Jekyll dash in Docker: launch Edge against `localhost:<port>` with compose brought up/stopped around the session (`Docker: Compose Up (Detached)` / `Docker: Compose Stop` from `tasks.json`), attach to a running browser, or force-rebuild the containers first.
- **2-generators** — `dash-gen` under debugpy: a subcommand picker mirroring `tools/dash gen <cmd>`, plus dedicated entries for the AI-harness inventory (`harnesses` live scan, `--offline` reuse of the committed scan, and `--gaps` fan-out targeting). Live gathers use your `gh` auth (`GH_TOKEN`/`GITHUB_TOKEN`); every generator degrades rather than dies without it.
- **2-generators** also carries **🎛️ Harness Console** — the local control plane's FastAPI front end under uvicorn with reload (`tools/console/`, opens http://127.0.0.1:4001/) — and the **🌊 Lake** entries: `lake sync` (extract GitHub runs/jobs/steps/logs/issues/workflows/`.factory/` into `.dash-lake/fleet.sqlite`), `lake status`, and `lake export --local --dry-run` (OpenInference traces for Phoenix, previewed without sending). `lake` takes a sub-subcommand, which is why it has its own entries rather than a slot in the picker.
- **3-verify** — debug the open dash-gen fixture test directly (`test_*.py` are dependency-light plain scripts, not pytest).
- **4-docs** — MkDocs serve/build for the **README submodule** (`projects/README/`), which owns the MkDocs site; the hub's own `mkdocs.yml` was removed.

Inputs:

- `portNumber`: compose port map — 4000 Jekyll dash (default), 5000 CV Builder, 5173 Vite HMR, 8000 MkDocs.
- `dashGenCommand`: the `dash-gen` subcommand list (see [`.github/scripts/dash-gen/README.md`](../.github/scripts/dash-gen/README.md)).

The pre-2026 Django and PostHog configurations that used to live here targeted repositories this one doesn't contain (and the file had become structurally invalid JSON); recover them from git history if ever wanted.

Last modified: 2026-09-02

---
name: run-dash
description: Run, drive, and orchestrate the bamr87 dash — the hub for ~40 submodule projects. Use to get the orchestration map, see project health/status, generate a per-project "work order" before dispatching Claude Code into a submodule, or serve/screenshot the Jekyll dash site. Triggers: "run the dash", "start the dash", "dash status", "what should I work on", "orchestrate the submodules", "serve the dash site", "screenshot the dash".
---

# run-dash — orchestrate the bamr87 hub

This repo is a **hub**: ~40 independent project repos vendored as git submodules,
with `_data/projects.yml` as the single source of truth. You don't usually "run"
this repo — you use it to **decide which submodule to work on and dispatch into it
with the right context**. That decision is what the driver gives you.

Three surfaces, in the order you'll reach for them:

1. **`driver.py`** (in this skill dir) — the orchestration map + per-project work
   order. **This is the primary agent path.** It joins the registry × `.gitmodules`
   × submodule checkout-state × health × local context files, and prints the exact
   copy-paste to enter a submodule on its correct branch.
2. **`tools/dash`** — the project's own CLI for `status` / `monitor` / health.
3. **The Jekyll dash site** — the human-facing portfolio/monitor at `:4000`.

All paths below are relative to the repo root (the unit). The driver's own path
from root is `.claude/skills/run-dash/driver.py`.

## Prerequisites

The driver needs only Python 3 + PyYAML (the same dep `tools/dash-gen` uses) and git.
**If `tools/dash status` works, PyYAML is already installed for the right
interpreter** — the driver uses the same bare `python3`. Only if you hit
`ModuleNotFoundError: No module named 'yaml'` do you have the wrong one (e.g. a
login shell resolving `/usr/bin/python3` 3.9 instead of the Homebrew 3.x that the
dash tooling uses):

```bash
python3 -c "import yaml" || python3 -m pip install pyyaml
```

For the health column and `tools/dash monitor`, `gh` must be authenticated
(`gh auth status` should show a logged-in account). For the dash *site*, you need
Docker running and (for a screenshot) Google Chrome.

## Run (agent path) — the orchestration driver

**Start here every time.** Get the whole-hub map:

```bash
python3 .claude/skills/run-dash/driver.py map
```

This prints every project ranked by attention (🔴/🟠/🟢 when health data exists),
with a state column: `●` checked out, `·` not yet checked out, `▲` moved, `◇`
external. In a fresh clone/worktree **every submodule is `·` (uninitialized)** —
that's expected; the hub is metadata until you init the one you want.

Then get a **work order** for the project you're about to touch:

```bash
python3 .claude/skills/run-dash/driver.py project cv-builder-pro
```

It prints the repo URL, stack, live health, the **declared branch**, the
checkout state, and a copy-paste *dispatch* block — e.g. for an uninitialized
submodule:

```text
  git submodule update --init projects/cv-builder-pro
  cd projects/cv-builder-pro
  git checkout main     # submodules land in detached HEAD
  git pull --ff-only
```

Once the submodule is checked out, re-running `project <name>` reads the *real*
`package.json` scripts / manifests instead of guessing, and tells you whether the
submodule already has its own `run-*` skill. Accepts a registry `name`, `slug`, or
path. Add `--json` (any position) for machine-readable output.

Refresh the health column first if it's missing or stale:

```bash
tools/dash gen health      # writes _data/project_health.yml (EPHEMERAL — gitignored, never commit)
```

Release-pipeline adoption + current version per repo:

```bash
python3 .claude/skills/run-dash/driver.py releases
```

### The dash's own CLI

```bash
tools/dash status          # submodule + registry + drift summary
tools/dash monitor         # refresh health, print repos needing attention (🔴/🟠/🟢)
```

`tools/dash status` is read-only and fast. `tools/dash monitor` hits the GitHub
API for all ~40 repos (≈30–60s).

## Run the dash site (Jekyll) + screenshot

⚠️ **`tools/dash serve` does not work on a clean machine** — see Gotchas. Use this
standalone-container path instead. It serves from a temp copy so the worktree
stays pristine, and uses a free port (`:4000` is often already taken):

```bash
# 1. copy the site out (submodules are empty; theme comes from remote_theme)
BUILD=/tmp/dash-preview
rm -rf "$BUILD" && mkdir -p "$BUILD/projects"
rsync -a --exclude='.git' --exclude='projects' --exclude='_site' --exclude='node_modules' ./ "$BUILD"/

# 2. serve with the github-pages stack (Ruby 3.1 image), host port 4001
docker rm -f dash-preview 2>/dev/null || true
docker run -d --name dash-preview -v "$BUILD":/srv/jekyll -p 4001:4000 \
  --entrypoint /bin/sh jekyll/jekyll:latest \
  -c "cd /srv/jekyll && bundle install && bundle exec jekyll serve -H 0.0.0.0 -c _config.yml,_config_dev.yml"

# 3. wait until it answers (first run does a full `bundle install`, a few minutes)
until [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:4001/)" = "200" ]; do sleep 5; done
echo "dash up on http://localhost:4001/"
```

The orchestration surfaces are `/dashboard/` (command center — counts + "needs
attention"), `/monitor/` (the color-coded health board), and `/projects/`
(portfolio). Screenshot one with headless Chrome (no chromium-cli on this machine):

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --window-size=1440,2200 \
  --screenshot="$PWD/.claude/skills/run-dash/dash-screenshot.png" \
  http://localhost:4001/dashboard/
```

`dash-screenshot.png` in this skill dir is a reference capture of `/dashboard/`.
Tear down when done:

```bash
docker rm -f dash-preview && rm -rf /tmp/dash-preview
```

## Gotchas (verified the hard way)

- **`tools/dash serve` is broken on a clean machine.** Its docker path runs
  `docker compose exec devenv … bundle exec jekyll serve`, but `.devcontainer/`
  installs only node/python/docker — **no Ruby/Jekyll/Bundler**. Its native
  fallback needs Ruby ≥ 2.7 (`github-pages` gem), but system Ruby here is 2.6.10.
  Use the standalone `jekyll/jekyll` container above.
- **`:4000` is often already in use** by an unrelated Jekyll container (the user
  runs several). `lsof -i :4000` to check; serve on `:4001` (or any free port).
- **Every submodule is uninitialized by default** — `git submodule status` shows a
  leading `-`, the dirs are empty. Init only the one you need; don't
  `--init --recursive` all 40 unless you mean it. The driver shows this as state `·`.
- **Submodules land in detached HEAD**, and `projects/scripts`, `projects/jekyll`,
  `projects/edgar-data-parse` track **`master`** (not `main`); `projects/sonic-pi`
  tracks **`dev`**. Always `git checkout <declared-branch>` from the work order —
  don't assume `main`.
- **In a git worktree, the drift gate reports every submodule as drifted** (it sees
  the worktree's branch name, e.g. `claude/…`, instead of the declared branch).
  This is a worktree artifact, not real drift — `tools/dash status` will show ~40
  DRIFT lines that don't apply. Verify on the main checkout if in doubt.
- **`_data/project_health.yml` is ephemeral and gitignored.** `tools/dash gen
  health` / `monitor` regenerate it; never commit it.
- **Run/test commands in the work order are heuristics until the submodule is
  checked out.** After init, the driver reads the real `package.json`; before that
  it guesses from the registry's `stack` tags (e.g. it'll guess `pytest` for the
  bash-heavy `scripts` repo). Trust the post-checkout reading.
- **`frontmatter-cms-mvp` is external** (no submodule) — clone it standalone; the
  driver flags it with `◇`.

## Troubleshooting

- **`driver.py` → `requires PyYAML` / `No module named 'yaml'`**: wrong
  interpreter. Use the `python3` that runs `tools/dash` (Homebrew 3.x here), or
  `python3 -m pip install pyyaml` for the one on your PATH. A bare login shell may
  resolve `/usr/bin/python3` 3.9, which lacks it.
- **Health column blank / "no health data"**: run `tools/dash gen health` (needs
  `gh` authenticated), then re-run the driver.
- **`tools/dash monitor` errors or all-null health**: `gh auth status` — an expired
  token makes every repo degrade to null (the generator won't crash, just empty).
- **Container serves but page is unstyled / 404 theme**: `remote_theme:
  bamr87/zer0-mistakes` needs network and may hit GitHub rate limits. Re-run, or set
  `remote_theme: false` per the note in `_config_dev.yml` and vendor the theme.

## After: authoring a per-submodule run skill

When you've initialized a submodule and want a reusable launch harness for *it*,
`cd` into the submodule and run `/run-skill-generator` there — it'll create
`projects/<name>/.claude/skills/run-<name>/`, which this driver then detects and
surfaces (`+run-skill` in the map).

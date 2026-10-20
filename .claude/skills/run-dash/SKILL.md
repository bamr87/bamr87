---
name: run-dash
description: Run, drive, and orchestrate the bamr87 dash — the hub for ~40 submodule projects. Use to get the orchestration map, see project health/status, generate a per-project "work order" before dispatching Claude Code into a submodule, or serve/screenshot the dash site (the Harness Console's page, built static). Triggers: "run the dash", "start the dash", "what should I work on", "orchestrate the submodules", "serve the dash site", "screenshot the dash". (For a plain read-only status readout, /dash-status owns that.)
---

# run-dash — orchestrate the bamr87 hub

This repo is a **hub**: ~40 independent project repos vendored as git submodules, with `_data/projects.yml` as the single source of truth. You don't usually "run" this repo — you use it to **decide which submodule to work on and dispatch into it with the right context**. That decision is what the driver gives you.

Three surfaces, in the order you'll reach for them:

1. **`driver.py`** (in this skill dir) — the orchestration map + per-project work order. **This is the primary agent path.** It joins the registry × `.gitmodules` × submodule checkout-state × health × local context files, and prints the exact copy-paste to enter a submodule on its correct branch.
2. **`tools/dash`** — the project's own CLI for `status` / `monitor` / health.
3. **The dash site** — the human-facing portfolio + console: the public static build at `:4000` (`tools/dash serve`), or the live console at `:4001` (`tools/dash console`).

All paths below are relative to the repo root (the unit). The driver's own path from root is `.claude/skills/run-dash/driver.py`.

## Prerequisites

The driver needs only Python 3 + PyYAML (the same dep `tools/dash-gen` uses) and git. **If `tools/dash status` works, PyYAML is already installed for the right interpreter** — the driver uses the same bare `python3`. Only if you hit `ModuleNotFoundError: No module named 'yaml'` do you have the wrong one (e.g. a login shell resolving `/usr/bin/python3` 3.9 instead of the Homebrew 3.x that the dash tooling uses):

```bash
python3 -c "import yaml" || python3 -m pip install pyyaml
```

For the health column and `tools/dash monitor`, `gh` must be authenticated (`gh auth status` should show a logged-in account). For the dash _site_, you need Docker running and (for a screenshot) Google Chrome.

## Run (agent path) — the orchestration driver

**Start here every time.** Get the whole-hub map:

```bash
python3 .claude/skills/run-dash/driver.py map
```

This prints every project ranked by attention (🔴/🟠/🟢 when health data exists), with a state column: `●` checked out, `·` not yet checked out, `▲` moved, `◇` external. In a fresh clone/worktree **every submodule is `·` (uninitialized)** — that's expected; the hub is metadata until you init the one you want.

Then get a **work order** for the project you're about to touch:

```bash
python3 .claude/skills/run-dash/driver.py project cv-pro
```

It prints the repo URL, stack, live health, the **declared branch**, the checkout state, and a copy-paste _dispatch_ block — e.g. for an uninitialized submodule:

```text
  git submodule update --init projects/cv-pro
  cd projects/cv-pro
  git checkout main     # submodules land in detached HEAD
  git pull --ff-only
```

Once the submodule is checked out, re-running `project <name>` reads the _real_ `package.json` scripts / manifests instead of guessing, and tells you whether the submodule already has its own `run-*` skill. Accepts a registry `name`, `slug`, or path. Add `--json` (any position) for machine-readable output.

Refresh the health column first if it's missing or stale:

```bash
tools/dash-gen health      # writes _data/project_health.yml (EPHEMERAL — gitignored, never commit)
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

`tools/dash status` is read-only and fast. `tools/dash monitor` hits the GitHub API for all ~40 repos (≈30–60s).

## Run the dash site + screenshot

The site is the Harness Console's page built static, exactly as GitHub Pages publishes it (docs/CONSOLE-PAGES.md). It needs Python 3 with PyYAML and Node (current LTS), and nothing else:

```bash
tools/dash serve                      # builds at the root and serves http://127.0.0.1:4000
DASH_SERVE_PORT=4002 tools/dash serve # :4000 is often taken by an unrelated container
tools/dash console                    # the live console instead — same page, with every operation (:4001)
```

The orchestration surfaces are `/overview` (attention queue, KPIs, signal freshness), `/projects` (every project with health and triage) and `/portfolio` (the cards). Screenshot one with headless Chrome:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --window-size=1440,2200 --virtual-time-budget=5000 \
  --screenshot="$PWD/.claude/skills/run-dash/dash-screenshot.png" \
  http://127.0.0.1:4000/overview
```

`--virtual-time-budget` matters: the page renders after it fetches its snapshot. The capture is a local, gitignored artifact (`.claude/skills/run-dash/*.png` is ignored) — never commit it.

## Gotchas (verified the hard way)

- **`:4000` is often already in use** by an unrelated container (the user runs several Jekyll sites). `lsof -i :4000` to check; `DASH_SERVE_PORT` picks another.
- **A deep link 404s** only on a build made for the Pages subpath (`/bamr87/`) served at the root. `tools/dash serve` builds at the root; `tools/console/build-pages.sh` alone builds for Pages.
- **Every submodule is uninitialized by default** — `git submodule status` shows a leading `-`, the dirs are empty. Init only the one you need; don't `--init --recursive` all 40 unless you mean it. The driver shows this as state `·`.
- **Submodules land in detached HEAD.** All track **`main`** except `projects/sonic-pi` (**`dev`**, upstream fork) — but always `git checkout <declared-branch>` from the work order (the declared branch comes from `.gitmodules`), don't assume.
- **In a git worktree, the drift gate reports every submodule as drifted** (it sees the worktree's branch name, e.g. `claude/…`, instead of the declared branch). This is a worktree artifact, not real drift — `tools/dash status` will show ~40 DRIFT lines that don't apply. Verify on the main checkout if in doubt.
- **`_data/project_health.yml` is ephemeral and gitignored.** `tools/dash-gen health` / `monitor` regenerate it; never commit it.
- **Run/test commands in the work order are heuristics until the submodule is checked out.** After init, the driver reads the real `package.json`; before that it guesses from the registry's `stack` tags (e.g. it'll guess `pytest` for the bash-heavy `scripts` repo). Trust the post-checkout reading.

## Troubleshooting

- **`driver.py` → `requires PyYAML` / `No module named 'yaml'`**: wrong interpreter. Use the `python3` that runs `tools/dash` (Homebrew 3.x here), or `python3 -m pip install pyyaml` for the one on your PATH. A bare login shell may resolve `/usr/bin/python3` 3.9, which lacks it.
- **Health column blank / "no health data"**: run `tools/dash-gen health` (needs `gh` authenticated), then re-run the driver.
- **`tools/dash monitor` errors or all-null health**: `gh auth status` — an expired token makes every repo degrade to null (the generator won't crash, just empty).

## After: authoring a per-submodule run skill

When you've initialized a submodule and want a reusable launch harness for _it_, author `projects/<name>/.claude/skills/run-<name>/` inside the submodule (the `skill-creator` skill in `projects/skills/.github/skills/skill-creator/` guides authoring). This driver then detects and surfaces it (`+run-skill` in the map).

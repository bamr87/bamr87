# bashOS — consolidating the fleet's CLIs and TUIs into one terminal framework

A plan to put every fleet repo with a terminal surface on one framework, **bashOS**, so each repo extends a shared foundation for its own purpose instead of rebuilding one. Together they form a single, comprehensive terminal tool.

Status: **Phase 0 in progress**, 2026-10-01. §9 records the owner's decisions: two remain open (wtd, optional scope). The four unregistered repos are now registered (§9.5). On 2026-10-07 the hub's two front ends, the Harness Console and the terminal dash, were put on one shared core and one runtime (§10). That is the first slice of keys v1, theme v1 and the bridge.

> **Read the inventory date before acting on a row.** Line counts and library usage below come from a static scan of the checked-out submodules on 2026-10-01. Re-run the scan before a phase starts.

## 1. The short version

- **20 repos** have a terminal surface (§2.1). Two already contain a full framework, four ship full-screen TUIs, three ship `gum`/`fzf` menu UIs (plus a duplicate in the hub root), and the rest are subcommand CLIs.
  - **5 UI stacks:** Textual, TermForge, gum/fzf/Zellij menus, bare `read`/`select` prompts, framework-free web front ends.
  - **5 CLI styles:** Typer, Click, argparse, `parseArgs`, bash case-dispatch.
  - They duplicate each other in **seven places** (§2.2).
- **Two real frameworks already exist**, written independently:
  - the **bashOS desktop**: Python/Textual, with tiled windows, launcher, command palette, themes and snapshot tests.
  - **TermForge** inside bashcrawl: JavaScript, zero dependencies; one kernel drives a browser game, a real TTY and a telnet server.
- **Decision: the framework is bashOS, and it lives in the existing `bamr87/bashos` repo.** TermForge joins it as bashOS's JavaScript runtime. The two runtimes share versioned contracts, not code.
  - **`bashos` (PyPI)** is the Python/Textual core: desktop shell, widget kit, CLI kit, testing kit. The AI kernel that bashOS is today becomes the `bashos[ai]` extra.
  - **`@bamr87/bashos` (npm)** is the portable JS runtime (formerly TermForge) for the browser, TTY and telnet.
  - **`bashos.sh`** is the bash kit for shell scripts.
  - **chui** is the environment the tools run in.
- **bashOS is also the flagship**: one desktop where every repo's app is a window, and one CLI (`bashos <app> <command>`) over every app's commands.
- **Common keybindings (`keys v1`, §6.1).** The current bashOS desktop keys don't survive the fleet's own environment: chui's Zellij swallows 5 of the 8, VS Code's terminal swallows `F1` and `ctrl+q`, and `ctrl+shift+w` arrives as `ctrl+w`. The new keymap uses the single-key conventions every popular TUI shares, with chords as aliases.
- **Six phases.** Phase 1 restructures with **zero behaviour change**, gated by the donors' existing tests (bashcrawl's golden transcripts, bashOS's snapshot tests).

## 2. What exists today

### 2.1 Inventory

**Frameworks**

| Repo | What it is | Stack | Size | What it contributes |
| --- | --- | --- | --- | --- |
| `bashos` → `src/bashos/desktop/` | **bashOS desktop**: window manager (tiling, maximize, cycle), taskbar, launcher, palette providers, modals, light/dark themes, history, shell exec panel, responsive breakpoints. Apps: AI Console, Health, Doctor, Engine, Commands, Trace, OpenCode TUI. | Python 3.11+, Textual 8, Typer, Rich | shell ~1.3k lines (incl. TCSS); apps ~0.8k; package ~4.9k + tests | The Python runtime, the app registry (`AppSpec`), a snapshot-tested Pilot harness, and a PyPI release path (`release.yml`; 0.1.0 published 2026-08-12) |
| `bashcrawl` → `termforge/` | **TermForge**: a brand-neutral terminal kernel (Shell, VFS with live *providers*, Line protocol v1, TerminalView). DOM and ANSI sinks; browser, TTY and telnet hosts; a btop-style compositor; a half-block pixel framebuffer. Apps: the game, `procwatch` (host metrics), `agentwatch` (AI-agent dashboard). | JS, zero npm deps, dual-mode classic/CJS files | ~12k lines incl. tests + golden fixtures | The JS runtime and the **Line protocol** (`docs/schemas/terminal-protocol.v1.md`): output as data, so any host can render it |

**Full-screen TUIs**

| Repo | What it is | Stack | Size |
| --- | --- | --- | --- |
| hub `tools/tui/` | Fleet command center: Apps / Inbox / Attention / Monitor / Harness / Docker (PR #304) | Python, Textual | ~1.5k + ~0.8k tests |
| `wtd` | Typer CLI + Rich output + a Textual TODO-tree dashboard; a `fleet` command group (see §9.4) | Python, Typer, Rich, Textual | 17k total; dashboard 369; `cli.py` 1.3k |
| `bashos` apps | AI console with streaming, engine inspector, trace viewer | (above) | (above) |
| `bashcrawl` | The game, in the browser and over TermForge in a TTY | (above) | (above) |

**Menu UIs (`gum` / `fzf` / Zellij)**

| Repo | What it is | Stack |
| --- | --- | --- |
| `chui` *(registered 2026-10-01)* | Rebuildable macOS terminal: Oh My Zsh, Powerlevel10k, Zellij, fzf/zoxide/lazygit/btop. `chui` menu (`tui.sh`), `$HOME` mapper, `forge` remote box. Its Zellij config is live on the owner's machine via symlink. | zsh/bash, gum ×18, fzf ×37, Zellij ×24 |
| `it-journey` | `journey.sh`: a gum + glow menu over quests, docs, Docker and workflows. Also the *Terminal Mastery* quests, incl. "Terminal Artificer" (build gum frontends). | bash, gum ×48 |
| `amrchy` *(fork, not registered)* | Fork of an upstream Linux desktop distro; has its own plugin mechanism (`omarchy-plugin-add`) | bash, ~87k lines, gum ×219 |
| hub root | `setup-terminal.sh` ("Terminal Enchantment"), `theme-benchmark.sh`, `validate-plugins.sh`, `validate-vscode-terminal.sh`, `install_omz.sh`: a second Oh My Zsh setup beside chui. (`tools/setup-terminal.sh` correctly delegates to chui.) | bash |

**Subcommand CLIs**

| Repo | Entry point | Style |
| --- | --- | --- |
| hub | `tools/dash`: 45 subcommands over 22 `dash-gen` Python modules | bash case-dispatch → argparse |
| `retro-pi` *(private; registered 2026-10-01)* | `retropi doctor/install/build/package`; bash **3.2** so it runs on stock macOS and a Raspberry Pi | bash |
| `scripts` | `forkme`, `stashme`, `git_init`, `project-init`, `rename-directory` | bash, `read -p` / `select` |
| `zer0-mistakes` | release/build/validate/publish toolchain; `scripts/lib/common.sh` | bash, ~38k lines |
| `ocrmd` *(private)* | `ocrmd scan/annotate/etl/read/send/sinks/library/search/ocr-bench` | Typer |
| `drsai` | `drsai …` | Typer + Rich |
| `lawmode` | `lawmode …` | Click + Rich |
| `aieo` | `aieo audit/context/dashboard/optimize/prd` | Click |
| `git-with-the-program` | `gwtp` | TypeScript, `node:util` `parseArgs` |
| `outbox` *(registered 2026-10-01)* | `outbox run/watch/suite` (`watch` follows a ledger live) | argparse |
| `raising-eliza` *(registered 2026-10-01)* | ELIZA engine (`work/eliza.py`) + HTTP gate + web page; **no terminal front-end yet** | argparse |
| `README`, `wargames`, `cv`, hub `dash-gen` | assorted generators and tools | argparse / node |

**Web twins** (not terminal apps, but they re-implement the same screens and should share the theme):

- the bashOS web GUI: 2.2k lines of framework-free JS over `/api`, with the same Console / Commands / Runs / Health / Engine scenes as the Textual desktop.
- the hub Harness Console: FastAPI, 3.2k lines of Python plus 1.3k web.

### 2.2 Duplication this plan removes

| What is duplicated | Where |
| --- | --- |
| A terminal desktop / compositor | bashOS WM (Python) **and** TermForge's compositor (JS) |
| A live agent / fleet activity dashboard | hub TUI, wtd dashboard + `wtd fleet`, TermForge `agentwatch`, `outbox watch`, bashOS Health/Trace (five) |
| The terminal environment install | chui **and** the hub-root `setup-terminal.sh` family; amrchy is the Linux analogue |
| Shell logging/prompt helpers | ≥64 shell files in 10 repos define their own `log_info()`-style functions; zer0-mistakes, bashcrawl and retro-pi each keep a private `lib/` |
| CLI plumbing | Typer (bashos, wtd, ocrmd, drsai), Click (lawmode, aieo), argparse (README, wargames, outbox, raising-eliza, dash-gen), `parseArgs` (TermForge, gwtp), bash case-dispatch (dash, retropi, scripts, chui) |
| Textual upgrades, absorbed alone by each app | bashos `textual>=8.2,<9` (a ceiling, against `docs/DEPENDENCIES.md`), wtd `textual>=0.47.0` (a floor 8 majors stale), hub unpinned |
| Generic TUI bug fixes | PR #304 fixed four bug classes in the hub TUI that any Textual app can have: cursor reset on repaint, markup injection from `str` cells, teardown races, a reactive shadowing `DOMNode.query`. The fix lives in one repo. |

## 3. Target architecture

```text
 ┌──────────────────────── bashOS desktop (the flagship) ─────────────────────────┐
 │ one desktop, every installed app a window · one CLI: bashos <app> <command>    │
 └────────────────────────────────────────────────────────────────────────────────┘
  apps (each repo ships one; each also runs standalone)
   ai-console · fleet (hub) · ocr-library · eliza · outbox-watch · retro
   bashcrawl · procwatch · agentwatch · quest-browser · home-map · shell
 ┌─────────────────────────── bashOS framework · bamr87/bashos ───────────────────┐
 │ spec/  terminal-protocol v1 · app v1 · command v1 · theme v1 · keys v1         │
 │ src/bashos/      core: desktop shell, widget kit, CLI kit, testing  (PyPI)     │
 │ src/bashos/ai/   the AI kernel — LangGraph + OpenCode   (PyPI extra: [ai])     │
 │ js/              @bamr87/bashos — Shell+VFS kernel; web/tty/telnet/stdio hosts │
 │ sh/              bashos.sh — log, prompt, menu; gum/fzf optional; bash 3.2     │
 └────────────────────────────────────────────────────────────────────────────────┘
  environment   chui (macOS) · amrchy plugin (Linux): zsh + p10k + Zellij, themed from theme v1
```

Five layers, each owned in one place:

| Layer | Owns | Lives in |
| --- | --- | --- |
| L0 Environment | shell, prompt, multiplexer, fonts, the installer, key passthrough (§6.1) | chui; an amrchy plugin |
| L1 Contracts | the versioned specs both runtimes implement | `bashos/spec/` |
| L2 Runtimes | the Python core (+ `[ai]`), the JS runtime, the bash kit | `bashos/{src,js,sh}/` |
| L3 Apps | each repo's domain UI and commands: **domain code never moves** | each repo |
| L4 Distribution | the bashOS desktop (everything), standalone single-app shells, web embeds | bashos; each repo; zer0-mistakes |

### 3.1 Why two runtimes and not one

- **Textual alone regresses bashcrawl.** The game's flagship is a free web app on static GitHub Pages. Textual's browser modes (`textual-serve`, `textual-web`) need a live Python process behind them, which a static site can't host.
- **TermForge alone regresses everything else.** It is a shell and compositor, not a widget toolkit: no tables, forms, CSS, command palette or snapshot testing. Porting ~10k lines of Textual UI onto it would be a rewrite with a worse result.
- **They already meet at a seam.** TermForge's output is *data*: Line-protocol records, plus `hud()` panels as pre-formatted records. A Python widget can render that data, and a JS host can embed any process that speaks it. So the two runtimes share **contracts, not code**.
- **Each runtime gets a lane.**
  - Python: the rich local desktop, dashboards, anything with tables, forms or windows.
  - JS: sandboxed shells, the browser, telnet, teaching, anything that must run with zero install.
- **Rule: no feature parity between runtimes beyond the contracts.**

### 3.2 Why the framework can live inside bashOS without dragging the AI stack along

The objection to housing the framework inside bashOS was coupling: every app would import LangGraph. The package split removes it:

| Install | Gets | Dependencies |
| --- | --- | --- |
| `pip install bashos` | the framework core: desktop shell, widget kit, CLI kit, testing kit, app discovery | `textual`, `rich`, `typer`, `pyyaml` |
| `pip install "bashos[ai]"` | + today's bashOS: LangGraph kernel, OpenCode engine, loops, auth, the AI apps | + `langgraph`, `langchain-*`, `claude-agent-sdk`, `httpx` |
| `pip install "bashos @ git+https://github.com/bamr87/bashos"` | the same, from `main` (the git channel) | same |
| `npm i @bamr87/bashos` | the JS runtime | none (zero-dependency rule) |

- **Enforced:** CI imports `bashos` and opens the desktop with no AI package installed.
- **Unchanged for the owner:** `bin/bashos` keeps installing `.[ai]`, so the experience stays the same.
- **Breaking:** this is a breaking change for `pip install bashos`, so it ships as **0.2.0**. That's acceptable at pre-1.0 with one known consumer.

### 3.3 The contracts (`spec/`)

| Spec | Status | Defines |
| --- | --- | --- |
| `terminal-protocol v1` | **exists** in bashcrawl; promote unchanged | output records `{kind, text}` and `{kind: control, action}`; 8 display kinds; pipeline stdin derivation; additive versioning |
| `app v1` | new; generalizes TermForge's App descriptor and bashOS's `AppSpec` | `id`, `title`, `icon`, `singleton`, a factory (Python) or `createSession` (JS), `commands`, optional `hud()`; discovery via Python entry-point group `bashos.apps` and JS `package.json` `"bashos": {"apps": …}` or `--app <path>` |
| `command v1` | new; generalizes bashOS's "one spec, three runtimes" `.claude/commands/` and TermForge pack `meta` | one record per command (name, summary, usage, args, options, examples, output schema, side-effect/confirm flag), generating: Typer subcommand, palette entry, `man`/help, bash/zsh/fish completion, `--json`, and an **MCP tool listing**, so agents call the same commands people do |
| `theme v1` | new | semantic tokens (bg, fg, accent, success, warn, error, dim, magic, art, banner), emitted as a Textual `Theme`, the ANSI SGR map, CSS variables (DOM sink, bashOS web GUI, Harness Console), gum styles, and p10k / Zellij / Terminal.app / VS Code palettes for chui |
| `keys v1` | new | the common keymap (§6.1) |

### 3.4 Python core — `bashos`

Seeded from today's desktop and hardened with what the hub TUI learned:

- **Desktop shell:** `DesktopApp`, window manager, taskbar, launcher, palette providers, modals, theme switcher, history, exec panel, `-compact/-standard/-wide` breakpoints.
- **Widget kit**, from the hub TUI (PR #304) and wtd:
  - `RecordTable`: cursor-stable rebuilds by row key, markup-safe cells, clipping.
  - A detail pane, filter chips and drill-down routing.
  - A **source status line**: each data source's age, flagged STALE past a threshold.
  - The `@ui` teardown guard, and a streamed-subprocess runner with progress.
  - From wtd: a status-styled tree view.
- **New widgets:**
  - A Line-protocol renderer, so JS-runtime records draw in a window with theme kinds.
  - `JsAppWindow`: hosts any JS app through `host-stdio.js`.
  - A markdown/doc reader (replaces `glow`).
  - Forms that replace `gum choose/input/confirm/filter`.
- **`run_standalone(app)`**: a single-app shell, so every app also runs alone (`tools/dash tui` stays a one-liner).
- **CLI kit**: a Typer app built from `command v1` records, with `--json`, exit codes 0/1/2, no prompts under `CI=true`, `NO_COLOR` honoured. That is the UPS `cli` row in `specs/STACKS.md`, implemented once.
- **Testing kit**: Pilot fixtures, snapshot helpers, markup-safety and teardown assertions, `keys v1` conformance assertions, and the mutation-check recipe PR #304 used.

### 3.5 JavaScript runtime — `@bamr87/bashos`

- **What moves:** everything in `bashcrawl/termforge/` today, into `bashos/js/`: core, node hosts, the compositor, the pixel screen, telnet. `procwatch` and `agentwatch` move as reference apps.
- **Additions:**
  - `host-stdio.js`: JSON Line protocol over stdin/stdout, the bridge into the Python desktop.
  - A `theme v1` loader for both sinks.
  - A `<bashos-terminal>` web component for embedding a sandboxed terminal in any page.
  - An ESM entry beside the dual-mode files.
  - **Readline editing for its line editor**, which today decodes ←/→ but ignores them and has no `ctrl+a/e/w/u/k`.
- **Renaming:** the classic-script global becomes `BashOS`, with `TermForge` kept as an alias, so bashcrawl's web runtime and its golden transcripts don't churn in the same step.
- **Zero dependencies stays a hard rule.**

### 3.6 Shell kit — `bashos.sh`

- **bash 3.2-compatible** (stock macOS, Raspberry Pi OS).
- **Helpers:** `bos_info/warn/error/step/debug`, `bos_run` (dry-run aware), and `bos_confirm/choose/input/filter/spin`. Each prompt uses gum when present, else fzf, else `read`/`select`.
- **Non-interactive by default where it matters:** under `CI=true` prompts take their defaults; `NO_COLOR` is honoured; gum styles are generated from `theme v1`.
- **Distribution:** exactly like `schema_lint.py` and `fleet-feedback.js`. Vendored into each repo, kept byte-identical by drift check (i), and delivered with `tools/fanout.sh --kit bashos-sh`.

### 3.7 The flagship desktop

What makes today's bashOS distinctive (LangGraph kernel, OpenCode engine, loops, auth, its AI apps) moves under `bashos.ai` and the `[ai]` extra. The desktop itself becomes *the framework core + the AI kernel + a curated app set*:

- `bashos` opens the desktop and discovers every installed `bashos.apps` plugin: fleet dash, ocrmd library, ELIZA, outbox watch, retro launcher, and bashcrawl / procwatch / agentwatch through the JS bridge.
- `bashos <app> <command> [--json]` runs any plugin command one-shot, with generated completions.
- The bashOS web GUI keeps its scenes, takes `theme v1`, and can use the JS runtime's DOM terminal for its console pane.

## 4. Per-repo plan

Sizes: **S** ≈ a day, **M** ≈ a few days, **L** ≈ one to two weeks of focused work.

| Repo | Role in the target | Moves out | Stays | Work | Phase | Size |
| --- | --- | --- | --- | --- | --- | --- |
| `bashos` | framework home + flagship | AI code → `src/bashos/ai/` (same repo) | everything; it *gains* `js/`, `sh/`, `spec/` | split core / `[ai]`; desktop → framework API; `AppSpec` dict → `bashos.apps` entry points; drop the `<9` ceiling; apply `keys v1`; 0.2.0 to PyPI; npm job for `js/` | 1, 2, 5 | L |
| `bashcrawl` | JS runtime donor, then consumer | `termforge/`, `docs/termforge/`, `docs/schemas/terminal-protocol.v1.md`, goldens → `bashos/js` and `bashos/spec`, **history preserved** (`git filter-repo` over those paths) | the game runtime, `web/`, `entrance/`, content registries, playtest harness | depend on `@bamr87/bashos`; keep the committed vendor mirror for Pages, sourced from the package; retarget `vendor_termforge.py --check` | 1 | L |
| hub `tools/tui` | first external app plugin | generic widgets (above) → widget kit | `fleet.py`, `host.py`, the six tabs | `app.py` becomes an `app v1` plugin (`bamr87-dash`); `tools/dash tui` runs it standalone; keymap per §6.1 | 4 | M |
| `wtd` | open: §9.4 | TODO-tree dashboard → widget kit tree view (either way) | per §9.4 | per §9.4 | 4 | S–M |
| `chui` | environment layer | — | zsh / p10k / Zellij config | Zellij unlock-first + VS Code meta passthrough (§6.1); `tui.sh` → `bashos.sh`; palettes from `theme v1`; a Zellij layout opening the desktop + the fleet app; install bashOS; absorb the hub-root duplicates | 3, 5 | M |
| hub root terminal scripts | duplicates of chui | whatever chui lacks → chui | `tools/setup-terminal.sh` (the delegator) | delete the five root scripts and their `SCHEMA.md` rows | 3 | S |
| `amrchy` (fork) | Linux environment | — | upstream code, untouched | an omarchy plugin that installs bashOS + the theme | 5 | S |
| `it-journey` | teaching + content | — | quests, `journey.sh` | `journey.sh` → `bashos.sh` now; later a quest-browser app; live `<bashos-terminal>` practice in *Terminal Mastery* quests; a "Terminal Artificer II" quest that builds a bashOS app | 3, 5 | M |
| `zer0-mistakes` | largest bash consumer; the theme | `scripts/lib/common.sh` helpers converge on `bashos.sh` (23 files define their own) | the toolchain | adopt `bashos.sh`; add `_includes/bashos-terminal.html` so every theme site can embed a terminal | 3, 5 | M |
| `scripts` | bash tools | — | the tools | prompts and menus via `bashos.sh` | 3 | S |
| `retro-pi` (private) | bash 3.2 CLI | — | manifests, cores, frontend | `retropi` → `bashos.sh`; optional retro-launcher app over `gamelist.py` | 3, 4 | S/M |
| `raising-eliza` | showcase app | — | the revived engine | a terminal front-end: a Python window in the desktop + a JS port for browser and telnet | 4 | S |
| `outbox` | dashboard app | — | the harness | `outbox watch` → an app on the shared agent-activity widget (agentwatch's `TaskSource` model) | 4 | S |
| `ocrmd` (private) | CLI + app | — | the OCR pipeline, its Typer CLI | a library app: documents, pages, search, scan status | 4 | M |
| `aieo`, `lawmode`, `drsai`, `README`, `wargames`, `cv`, `gwtp`, `dash-gen` | CLIs | — | everything | meet the UPS `cli` rules via `bashos.cli` **when next touched**; no forced Click→Typer rewrites | 6 | S each |
| hub `tools/dash` | CLI dispatcher | — | stays bash | output via `bashos.sh`; its 45 subcommands exported as a `command v1` catalog so they appear in the palette | 5 | S |
| bashOS web GUI, Harness Console | web twins | — | — | consume `theme v1`; optional DOM terminal panes | 5 | S |
| `wargames` | content mirror | — | — | optional: browser worlds for the first Bandit levels | 5 | M |

Nothing in `projects/skills/` or the `amrchy` fork's own code is modified (consume, don't change).

## 5. Phases

Phases 1 → 2 → 4 → 5 run in that order. Phase 3 can run beside Phase 2, and Phase 6 starts once Phase 2 lands.

### Phase 0 — Decide and specify · S · *in progress*

- **Done:**
  - Decisions 1, 2, 3, 5, 6 (§9).
  - chui, raising-eliza, outbox and retro-pi registered as submodules.
- **Remaining:**
  - Decision 4 (wtd) and decision 7 (optional scope).
  - Drafts of `app v1`, `command v1`, `theme v1` and `keys v1` (the last from §6.1); `terminal-protocol v1` promoted.
  - A draft `specs/TERMINAL.md`, and a `terminal:` block in `_data/fleet.yml` (default theme, keymap version).
  - `NPM_TOKEN` reaches `bamr87/bashos`: its contract in `_data/fleet.yml` is `scope: hub` today, so widen it before `dash secrets sync` can provision it.
- **Before Phase 1:** put `agent:hold` on, and set `auto_evolve: false` for, bashos and bashcrawl, so the issue pipeline and the evolution loop don't open PRs against code that is moving.

### Phase 1 — Restructure, zero behaviour change · L

- **Python, inside `bamr87/bashos`:**
  - Separate the framework core from `bashos.ai` along the dependency line.
  - Move the AI dependencies to `[ai]`.
  - Release 0.2.0 through the existing `release.yml` → PyPI.
- **JS:** move `bashcrawl/termforge` into `bashos/js/` with history, identifiers unchanged. bashcrawl consumes `@bamr87/bashos`.
- **CI:**
  - `node --test` plus the golden transcripts.
  - pytest, Pilot and snapshots.
  - Dependency-rule tests: JS `core/` touches no DOM or `node:*`; the core imports no AI package.
- **Gate:**
  - bashcrawl's golden transcripts replay byte-identically, and its web bundle is byte-identical.
  - bashOS's three SVG snapshots are unchanged.
  - `pip install bashos` without `[ai]` opens the desktop.
  - Both repos' CI is green.
- **Phase 1b:** rename `TermForge` identifiers to `BashOS`, with the compatibility alias.

### Phase 2 — Contracts, keys and the bridge · M

- **Deliverables:**
  - `theme v1` and `keys v1` in both runtimes, with the bashOS desktop moved to §6.1.
  - `command v1` and its generators.
  - The Line-protocol renderer.
  - `host-stdio.js` + `JsAppWindow`.
  - Entry-point discovery and `run_standalone`.
- **Gate:**
  - bashcrawl runs as a window in the desktop.
  - One theme switch recolours the desktop *and* the embedded JS app.
  - `bashos list` shows commands from at least two packages.
  - The desktop is fully usable inside chui's Zellij and VS Code's terminal (§6.1).

### Phase 3 — Shell kit and environment keys · M (parallel with Phase 2)

- **Deliverables:**
  - `bashos.sh`, with a bash-3.2 CI job (container) and a macOS job.
  - Drift check (i) parity for it.
  - Fan-out to chui, scripts, retro-pi, zer0-mistakes, it-journey, bashcrawl `lib/` and hub `tools/`.
  - The hub-root duplicates retired into chui.
  - chui's key passthrough (§6.1).
- **Gate:**
  - Parity is green across adopters, and no adopter still defines its own logging helpers.
  - Nothing in chui's environment intercepts a `keys v1` binding.

### Phase 4 — Apps · L

- **Deliverables:**
  - The hub TUI as a plugin, with its PR #304 fixes moved into the widget kit.
  - The wtd tree view.
  - One agent-activity widget shared by agentwatch, outbox and the Trace app.
  - ELIZA, the ocrmd library and the retro launcher.
- **Gate:**
  - Each app runs standalone and inside the desktop.
  - Each passes the `keys v1` conformance test and ships Pilot tests.
  - Each lists its features in `features/features.yml` with verify scenarios (`docs/VERIFICATION.md`).

### Phase 5 — Environment, flagship, web · M

- **Deliverables:**
  - chui installs bashOS, ships the Zellij layout and exports palettes.
  - The amrchy plugin.
  - The curated app set and `bashos <app> <command>`.
  - `<bashos-terminal>` + the zer0-mistakes include, with it-journey embeds.
  - Optional: telnet / SSH serving, loopback by default.
- **Gate:**
  - On a fresh Mac, `make install` in chui followed by `bashos` opens with fleet, AI, ELIZA and bashcrawl windows.
  - An it-journey quest page runs a live sandboxed terminal.

### Phase 6 — Govern · S, then continuous

- **Deliverables:**
  - `specs/TERMINAL.md` checks in `tools/conformance.py` (`dash spec`), with `_data/specs.yml` regenerated.
  - A `tui` capability row in `specs/STACKS.md`.
  - An "adopt bashOS" lane in the evolution-loop briefs.
  - `fanout.sh --kit bashos-app` to scaffold new apps.
- **Gate:**
  - The conformance index grades every terminal repo.
  - A new repo can scaffold an app in one command.

## 6. What the finished tool does

- **A real terminal desktop.** Tiled windows, launcher, palette, themes, notifications, and mouse support. Breakpoints adapt from a laptop split to an ultrawide.
- **Every command three ways.** From one `command v1` record:
  - a palette entry in the TUI;
  - a one-shot CLI with `--json` and completion;
  - an MCP tool an agent can call.
- **Live data, honestly labelled.** Providers and sources carry their age and turn STALE past a threshold (the hub reuses `harness.trip_wires.stale_data_days`). Views reload when data changes on disk, and long jobs stream progress.
- **Portable where it counts.** The same JS app runs in a browser tab, a terminal and over telnet. Any zer0-mistakes site can embed a sandboxed terminal.
- **One look and one keymap everywhere.** The desktop, web twins, gum menus, zsh prompt and multiplexer all render from `theme v1`, and every app answers to `keys v1`.
- **Shell-native.** A real shell exec panel, Zellij layouts, and `bashos.sh` so shell scripts feel like part of the same tool.
- **Agent-native.** `--json` on everything, MCP listings, and bashcrawl's playtest pattern generalized: an agent drives the real app and scores it.
- **Tested like a product.**
  - Golden transcripts for JS apps, Pilot plus snapshots for Python apps.
  - Markup-safety, teardown and keymap guards built in, not rediscovered per repo.
- **Fun on purpose.** The pixel framebuffer, DAEMON STORM, ELIZA on telnet, and bashcrawl as a window.

### 6.1 `keys v1` — common bindings

**The problem, measured on 2026-10-01.** A key only works if every layer above the app passes it through: the terminal, the editor, the multiplexer. Here is what today's bashOS desktop keys run into in the fleet's own environment:

| Key | bashOS today | chui's Zellij (live config, normal mode) | VS Code terminal | tmux | Apple Terminal |
| --- | --- | --- | --- | --- | --- |
| `F1` | help | — | ✗ Show All Commands (in VS Code's default skip-shell list) | — | needs `fn` on Mac keyboards by default |
| `F2` | launcher | — | ok | — | needs `fn` by default |
| `ctrl+p` | palette (Textual default) | ✗ pane mode | ✗ Quick Open on Linux/Windows | — | ok |
| `ctrl+n` | new console | ✗ resize mode | ok | — | ok |
| `ctrl+o` | cycle windows | ✗ session mode | ok | — | ok |
| `ctrl+t` | theme | ✗ tab mode | ok | — | ok |
| `ctrl+b` | maximize | — | ok | ✗ the prefix | ok |
| `ctrl+q` | quit (Textual default) | ✗ **quits Zellij — the whole session** | ✗ Quick Open View, `⌃Q` on every platform (in the skip-shell list) | — | ok |
| `ctrl+shift+w` | close window | — | arrives as `ctrl+w` | — | arrives as `ctrl+w` — legacy key encoding can't carry shift on ctrl+letter (only the kitty keyboard protocol can) |

The hub TUI and wtd avoid this, using single keys, but they disagree with each other: `s` is *sort* in one and *spawn subtasks* in the other, and `c` is *category* versus *complete*. Help is `?` in two apps and `F1` in one.

**The rules.**

1. **Primary bindings are unmodified keys.** They reach the app in every host: Apple Terminal, VS Code, Zellij, tmux, SSH, telnet, a browser tab.
2. **Meanings follow the TUIs people already know** (less, vim, htop/btop, lazygit, k9s, gh-dash) and Textual's own defaults.
3. **Chords are aliases, never the only way.** Every action is also in the command palette.
4. **Desktop window keys use `alt`.** Once chui passes Meta through, `alt` is the one modifier no layer in the fleet's environment claims.
5. **Text inputs and REPLs keep readline keys**, which are the common bindings there. `esc` leaves an input, so single keys work again.

**Universal — the same meaning in every app:**

| Action | Primary | Alias | Known from |
| --- | --- | --- | --- |
| Quit | `q` (outside text inputs; asks when work is running) | `ctrl+q` where it reaches | less, htop, btop, lazygit · Textual |
| Help / all keys | `?` | `F1` | lazygit, k9s, gh-dash |
| Command palette | `:` | `ctrl+p` | vim, k9s, helix · Textual |
| Search / filter text | `/` | — | vim, less, k9s, lazygit |
| Back · cancel · leave input · clear the active filter | `esc` | — | universal |
| Open / drill in | `enter` | — | universal |
| Toggle / mark | `space` | — | lazygit, ranger · Textual Tree |
| Move | arrows, `j` / `k` | — | vim, lazygit, k9s |
| Top / bottom | `g` / `G` | `home` / `end` | vim, less |
| Page | `pgup` / `pgdn` | `ctrl+u` / `ctrl+d` outside inputs | vim, less |
| Next / previous tab | `]` / `[` | `tab` / `shift+tab` move focus | lazygit · Textual |
| Go to tab N | `1`–`9` | — | lazygit (panels 1–5) |
| Refresh | `r` | `R` = full / remote refresh | gh-dash (`r`) |
| Copy the current item (id / URL) | `y` | — | vim (yank) |
| Open in browser | `o` | — | gh-dash |
| Edit in `$EDITOR` | `e` | — | lazygit, k9s |

**Conventional** — when an app has the concept, it uses this key; otherwise the key is free:

- `s` sort
- `f` filter
- `n` new
- `d` delete (always confirms)
- `h` / `l` move between side-by-side panes

**Desktop** — the bashOS window manager:

| Action | Primary | Alias |
| --- | --- | --- |
| App launcher | `alt+a` | `F2` |
| New window (console) | `alt+n` (Zellij's own new-pane key) | — |
| Close window | `alt+w` | — |
| Next / previous window | `alt+]` / `alt+[` (mirrors `]` / `[` for tabs) | — |
| Go to window N | `alt+1`–`alt+9` | — |
| Maximize / restore | `alt+f` (mnemonic: `f` is fullscreen in chui's Zellij pane mode) | — |
| Theme | palette (`:theme`) | `alt+t` |
| Quit the desktop | `q` from any window that doesn't use it | `ctrl+q` |

**REPLs and text inputs** (AI console, ELIZA, JS shells, search boxes):

- **Readline keys:** `ctrl+a` / `ctrl+e` (line start/end), `ctrl+w` (delete word), `ctrl+u` / `ctrl+k` (delete to start/end), `←` / `→`, `↑` / `↓` history, `tab` completion, `ctrl+l` clear screen.
- **Leaving:** `ctrl+c` cancels the line or the running job; `ctrl+d` exits on an empty line; `esc` cancels a run, then leaves the input.
- **Coverage today:** Textual's `Input` already has these; the JS runtime's line editor needs them (§3.5).

**Remapping existing apps:**

| App | Today | `keys v1` |
| --- | --- | --- |
| bashOS desktop | `F1` help · `F2` launcher · `ctrl+n` new · `ctrl+o` cycle · `ctrl+b` maximize · `ctrl+shift+w` close · `ctrl+t` theme · `ctrl+q` quit | `?` (`F1` alias) · `alt+a` (`F2` alias) · `alt+n` · `alt+]` / `alt+[` · `alt+f` · `alt+w` · `:theme` / `alt+t` · `q` (`ctrl+q` alias) |
| bashOS AI console | `esc` stops a run | `esc` stops a run, a second `esc` leaves the input |
| hub TUI | `d` Docker poll · `x` clear filters | `r` refreshes everything incl. Docker · `esc` clears filters (`x` kept as alias); adds `j`/`k`, `g`/`G`, `]`/`[`, `y`, `:` |
| wtd dashboard | `s` spawn · `c` complete · `e` execute | `n` new subtasks · `space` complete · `x` execute |
| JS runtime REPL | append-only line editor | readline editing |

**Environment changes — chui owns these:**

- **Zellij:** switch chui's config to *unlock-first*. It starts `locked`, `ctrl+g` unlocks, and mode keys become plain letters inside normal mode. That is the same pattern as Zellij's own non-colliding preset, and it returns every `ctrl` key to the apps. Today the live config claims `ctrl+p/t/n/o/q` in its default mode.
- **VS Code:** set `terminal.integrated.macOptionIsMeta: true` so `alt` chords arrive as Meta. It isn't set on the owner's machine, so option keys currently type characters. Nothing else needs to change: `F1` and `ctrl+q` are only aliases, so VS Code keeping them is fine.
- **Apple Terminal:** chui's `macos-keys.py` already sets *Use Option as Meta*.

## 7. Fleet integration

- **Registry:** chui, raising-eliza, outbox and retro-pi are registered (2026-10-01). bashos's description changes to the framework framing when Phase 1 lands.
- **Standards:** `specs/TERMINAL.md` adds UPS-TERM requirements:
  - `keys v1` conformance and theme tokens;
  - `--json`, and no prompts under `CI=true`;
  - `NO_COLOR` plus an ASCII fallback for dumb terminals and telnet;
  - minimum size and breakpoint behaviour;
  - markup-safe rendering and teardown safety;
  - Pilot/snapshot or golden-transcript tests;
  - a help screen;
  - no secrets in config.
- **Dependencies:** always-latest (`docs/DEPENDENCIES.md`) stays the rule. The framework absorbs Textual's churn with a nightly CI run against the newest release, so consumers depend on the `bashos` API rather than on Textual directly. bashos's `<9` ceiling goes.
- **Distribution:**
  - PyPI (`bashos`, existing trusted-publishing `release.yml`) plus git installs.
  - npm (`@bamr87/bashos`, a new job in the same repo, `docs/RELEASES.md`).
  - `bashos.sh` is vendored, and drift check (i) holds its parity.
- **Agents:** loops pause on bashos and bashcrawl for Phase 1 only. Afterwards the evolution brief gains an adoption lane, and the issue pipeline can take "adopt `bashos.sh`" issues.
- **PR hygiene:** one PR per repo, never bundled across submodules (`SUBMODULES.md`). Kit delivery goes through `tools/fanout.sh` (dry-run default, PRs only). Private repos need `FLEET_TOKEN`, because a repo-scoped token 404s on them.

## 8. Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Textual breaking changes under always-latest | high | one place absorbs them (the framework); nightly CI on latest; consumers' snapshots catch visual drift |
| Scope creep ("comprehensive") | high | phase gates; every phase ships on its own; optional items marked optional |
| "bashOS" now names a framework *and* an AI desktop | medium | the package split (§3.2) is the boundary; docs say "bashOS framework" vs "bashOS desktop" |
| 0.2.0 drops the AI stack from a bare `pip install bashos` | medium | `[ai]` extra; `bin/bashos` installs it; `bashos doctor` names the missing extra |
| Extraction breaks bashcrawl's Pages build | medium | byte-identical vendor mirror check; golden transcripts; switch the consumer only after the package passes them |
| Two runtimes double the maintenance | medium | contracts are the only shared surface; no parity mandate; one lane per runtime |
| bash 3.2 / Raspberry Pi constraints | medium | `bashos.sh` CI in a bash-3.2 container and on a stock macOS runner |
| Agent loops open conflicting PRs mid-migration | medium | `agent:hold` + `auto_evolve: false` on the donors for Phase 1 |
| Muscle memory for the old desktop keys | low | old chords stay as aliases wherever they still reach; `?` lists both |
| Private repos invisible to CI tokens | medium | `FLEET_TOKEN` for fan-out (known fleet issue) |
| Telnet/SSH exposure | low | loopback by default; LAN is opt-in, matching the Harness Console |

## 9. Decision record

1. **Name: bashOS.** The framework is bashOS and lives in the existing `bamr87/bashos` repo. TermForge becomes its JS runtime. *(Owner, 2026-10-01.)*
2. **Flagship: the bashOS desktop.** *(Owner, 2026-10-01.)*
3. **Python publishing: PyPI and git.** PyPI through bashos's existing trusted-publishing `release.yml` (the name is the owner's: 0.1.0, 2026-08-12), and git installs from `main`. *(Owner, 2026-10-01.)*
4. **wtd: open.** The owner asked why it was archived. The record:
   - **2026-08-10:** hub PR #88's fleet audit set `status: archived` and `maintained: false`: "last substantive commit 2026-05; the 2026-07/08 activity is entirely hub fan-out; its concept space is carried by githubai."
   - **2026-08-19:** nine days later, wtd PR #15 redesigned it into an autonomous agent-fleet platform (0.2.0). Feature work continued into September (last feature commit 2026-09-08), so **the registry label went stale almost immediately**.
   - **2026-08-28:** its live dispatcher was producing poor work. Every one of the 8 hub "CI failing" tickets it filed was stale, and 5 of its 7 `wtd/*` PRs were closed.
   - **2026-09-05:** with the owner's approval it was disarmed: `WTD_FLEET_ENABLED=false`, and its ten drafts closed.
   - **Today:** it is not archived on GitHub, and its kill switch is still off.
   - **Its overlap:** its fleet role duplicates the hub's own loops (fleet-pulse doctor, issue pipeline, repo evolution).
   - **Recommendation:** keep the dispatcher off, since the hub's loops own that job. Correct the registry entry to tell this history. Fold wtd's terminal value (the TODO tree, routines, fleet status views) into bashOS as widgets or an app, not as a second control plane.
5. **Registration: done.** chui, raising-eliza, outbox and retro-pi are now registry entries *and* submodules, following the 2026-09-07 reconciliation precedent for live repos. Drift parity, README span and `projects/SCHEMA.md` all pass. *(Owner, 2026-10-01.)*
6. **Keymap: the bashOS desktop keys become the fleet standard, updated to common bindings (§6.1).** *(Owner, 2026-10-01.)*
7. **Optional scope: open.** Wargames browser worlds, telnet/SSH serving, the retro launcher.

## 10. The fleet console: one core, browser and terminal

The hub had two front ends over the same fleet that shared nothing:

- the **Harness Console** (FastAPI and one hand-written page, 11 tabs, write-capable through an allowlist);
- the **terminal dash** (Textual, 6 tabs, read-only).

Each loaded the same YAML through its own loader, with its own idea of "stale" and its own red. They now sit on one core and one runtime. This is the hub-side half of keys v1 and theme v1, and a working instance of the §3 "one model, two renderers" shape.

```text
                 tools/fleetcore  (stdlib + PyYAML)
     fleet.py · host.py · views.py · keys.py · theme.py · client.py
          │                                         │
   Harness Console (runtime)                 terminal dash
   FastAPI: /api/fleet  /api/keys            Textual: same views,
   /theme.css  /api/jobs  (OPS allowlist,    Bindings from keys.py,
   confirm gate, one JobManager)             bashos-dark theme
     │ TCP 127.0.0.1:4001     │ unix socket ─── Jobs tab + `:` palette
     ▼                        │ (console-run volume, tui only)
   browser page: Projects, keys v1, `?` sheet, `:` palette,
   and the Terminal page — the TUI itself on a pty over /api/tui
```

| Concern | Before | Now |
| --- | --- | --- |
| Data | `console/core.py` and `tui/fleet.py`, separately | `fleetcore/fleet.py` + `views.py`. The page's Projects view is `/api/fleet`, filtered and sorted by the TUI's own functions on the server |
| Keys | TUI only, ad hoc | keys v1 as data (`fleetcore/keys.py`). The TUI builds its Bindings from it, and the page binds the same table from `/api/keys` |
| Colour | a dataviz palette in the page, hex literals in the TUI | the bashOS palette (`fleetcore/theme.py`, mirrored from `bashos.desktop.theme`), served as `/theme.css` and registered as Textual `bashos-dark` |
| Actions | page only | one runtime. The TUI's Jobs tab and `:` palette submit to the console's job API, so a job started in either shows in both, and the allowlist and confirm gate stay server-side |
| Agents | — | the `fleet` MCP server (`fleetcore/mcp_server.py`, in `.mcp.json`): read tools over the same views, act tools through the same job API and confirm gate, so an agent gets exactly what a person gets |
| Docker | — | `docker compose run --rm tui` starts `console` and joins it over a Unix socket in a volume only these two mount. Reaching the socket is the authorization, so the DNS-rebinding allowlist stays loopback-only |

Not yet converged, in the order worth doing:

1. **The console's other ten tabs in the terminal.** Harnesses, Schedules, Loops and Costs come first, since they read committed YAML. For each, move its loader from `console/core.py` into `fleetcore`, serve it, and add a TUI tab. Content, Config and Auth are forms and stay browser-first.
2. **theme v1 from bashOS itself.** `fleetcore/theme.py` copies bashOS's values today. When `bashos` publishes the tokens as data (Phase 2), the table becomes an import.
3. **The bashOS desktop.** The fleet dash becomes a bashOS app: an `AppSpec` window that hosts the dash screens, loaded through the `bashos.apps` entry point (Phase 2's bridge). The bashOS GUI and this console are then two web front ends, and the decision is which one hosts the other. Recommendation: the console stays the fleet's runtime (it owns the allowlist and the credentials), and the bashOS GUI opens it as an app.
4. ~~**The TUI in the browser.**~~ Done (2026-10): the console's Terminal page runs the real Textual app on a pty relayed over the `/api/tui` WebSocket and draws it with xterm.js in the bashOS dark palette. One program, two hosts; nothing re-implemented.
5. **Docker in the browser.** The console holds no Docker socket on purpose: a write-capable service holding one would be root on the Docker host. Containers show in the TUI, and the page says so.

## 11. Next steps

1. Owner: decide §9.4 (wtd) and §9.7 (optional scope).
2. Draft `app v1`, `theme v1`, `keys v1` (from §6.1) and `command v1`; promote `terminal-protocol v1`.
3. Pause the agent loops on bashos and bashcrawl; widen the `NPM_TOKEN` contract (today hub-only) and provision it on bashos.
4. Phase 1 in `bamr87/bashos`: the core / `[ai]` split, then the JS move from bashcrawl.
5. Turn each phase into roadmap entries per repo through the future-features pipeline (`_data/roadmap.yml`, human-approved).
6. Converge the rest of the console in the order §10 lists, starting with the Harnesses and Costs tabs in the terminal.

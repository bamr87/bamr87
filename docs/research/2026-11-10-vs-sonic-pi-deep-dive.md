# vs-sonic-pi outside research (deep-dive cycle 1, day 12)

> Outside research for bamr87/vs-sonic-pi on Sonic Pi v5 compatibility and ranked proposals P1–P9, dated 10 November 2026.

**Date:** 10 November 2026 (America/Denver)  
**Repo:** [bamr87/vs-sonic-pi](https://github.com/bamr87/vs-sonic-pi) (remote read only; no clone, no issues, no PRs)  
**Audience:** Tools, to file as `deep-dive` issues/feature requests if they agree  
**Method:** cursor-github MCP reads of `AGENTS.md`, `README.md`, `package.json`, `docs/PRD.md`, `features/features.yml`, `CHANGELOG.md`, and the connection/language/log/UI modules; GitHub issue search; WebSearch/WebFetch of peer projects and Sonic Pi `daemon.rb` on tags `v4.6.0` and branch `dev` (current v5 protocol).

## 1. What vs-sonic-pi already ships

Do **not** re-file these as new features. They are present in `package.json`, the README, and the TypeScript modules named below.

| Area | Shipped capability |
| --- | --- |
| Language | `.spi` / `.sonicpi` TextMate grammar; completions for synths, samples, FX, scales, chords, notes, function names, and **context-aware option keys** after `use_synth` / `with_fx` (`src/language/CompletionProvider.ts`); hover docs; 31 snippets |
| Run / stop | Run, Run Selection, Stop; editor title/context menus; `live_loop` **▶ Run loop** CodeLens; New Loop File; Beautify Buffer |
| Server | Auto-connect; `/ping` → `/ack`; spawn `daemon.rb` with bundled Ruby; parse daemon STDOUT; persist `port-info`; token on every OSC send; `/daemon/keep-alive` every **2 s** with token; `/daemon/exit` on shutdown; Restart Daemon; `audioInputs` flag |
| Feedback | Output channel ("Sonic Pi Log"); inline / Problems-panel diagnostics; status bar; `openLog` |
| Learning | 85-chapter tutorial tree + webview; 55 bundled examples; language reference webview; Getting Started walkthrough |
| Other | Start/stop/save WAV recording; Codespaces/devcontainer headless server + HTTP audio stream player |

`features/features.yml` is **stale** relative to the code and README: SONICPI-009 (autocomplete), 010 (hover), 013 (error reporting), 014 (status bar) and 015 (daemon auto-start) are marked `tbd` / `implemented: false`, but they are shipped. SONICPI-019–022 (cue log, MIDI monitor, audio scope, multi-buffer workspaces) remain genuine gaps and match PRD Phase 3 (FR-19–22).

README and PRD still say compatibility is **Sonic Pi v4.x**. Sonic Pi **v5.0.0** was released on 7 August 2026 ([release notes](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0)). That matters for proposal 1.

## 2. Issue check (remote)

GitHub search `repo:bamr87/vs-sonic-pi is:issue` returned **two** issues:

- Open: [#37 Adopt fleet frontend platform (§18, tier tokens)](https://github.com/bamr87/vs-sonic-pi/issues/37) — fleet design-token work, blocked on hub ratification. Not a product feature.
- Closed: [#2 CI failure: Node 18 incompatible with vitest 4](https://github.com/bamr87/vs-sonic-pi/issues/2) — already fixed.

**None of the proposals below duplicate an existing issue.** There are no open `deep-dive` or feature-request issues at all.

## 3. Protocol fact (needed for several proposals)

Official `daemon.rb` is the supported boot API for external editors ([Sam Aaron on #3205](https://github.com/sonic-pi-net/sonic-pi/issues/3205); comments at the top of [`daemon.rb` on `dev`](https://github.com/sonic-pi-net/sonic-pi/blob/dev/app/server/ruby/bin/daemon.rb)). Clients must:

1. Spawn `daemon.rb` and read **one stdout line** of ports + token (do not scrape log files).
2. Send `/daemon/keep-alive` **more often than every 3 s**, with the token as the first argument.
3. Send the token as the first argument on OSC commands to the Spider server.
4. Shut down with `/daemon/exit` + token.

vs-sonic-pi already does (2)–(4) correctly (`Heartbeat.ts` default 2000 ms; `OscTransport.send` prepends the token). The stdout **field layout changed in v5**:

| Version | Stdout line (space-separated) | Source |
| --- | --- | --- |
| v4.6.0 | 8 integers: `daemon gui-listen gui-send scsynth osc-cues tau tau-phx token` | [`daemon.rb` @ v4.6.0](https://github.com/sonic-pi-net/sonic-pi/blob/v4.6.0/app/server/ruby/bin/daemon.rb) (`puts` of those eight values) |
| v5 / `dev` (Nov 2026) | 7 fields: `daemon gui-listen gui-send scsynth osc-cues token engine-secret` where `engine-secret` is **64 hex digits**, not an integer | [`daemon.rb` on `dev`](https://github.com/sonic-pi-net/sonic-pi/blob/dev/app/server/ruby/bin/daemon.rb) line that prints ports; header comment lists the same order |

`parseDaemonOutput` in [`PortDiscovery.ts`](https://github.com/bamr87/vs-sonic-pi/blob/main/src/connection/PortDiscovery.ts) requires **at least eight numeric fields**. A v5 line has seven tokens and a trailing hex secret, so `Number(...)` is `NaN` and the parser returns `undefined`. A spawned v5 daemon would then look like a boot timeout.

Older PRD / `docs/08-daemon-spawner.md` text still describes a ~30 s heartbeat, a ~90 s kill switch, and `spider.log` scraping. That documentation is outdated; the **code** already uses the 2 s / 3 s v4 contract and a `port-info` file. The live risk is the v5 field change, not the heartbeat interval.

## 4. Comparison table

Status notes are from the linked pages as of this research date. Star counts and last-update dates were not re-audited beyond the pages fetched.

| Project | Host | Run / stop | Server / daemon (v4+) | Logs / cues | Language / docs | Distinct UX | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **bamr87/vs-sonic-pi** | VS Code | F5 / Shift+F5 / selection; `live_loop` CodeLens | Spawns `daemon.rb`, token, 2 s keep-alive, restart, Codespaces headless | Combined log + diagnostics; **no cue pane** | Completions, hover, snippets, 85-chapter tutorial, examples, reference | Recording, beautify, audio stream (headless) | Broadest VS Code feature set reviewed; README still targets v4.x; v5 stdout unparsed |
| [Sonic Pi GUI](https://sonic-pi.net) v4 / [v5.0.0](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0) | Qt app | Run / stop; ten buffers; v5 Sets (`.sonicpi`) | Owns `daemon.rb` | Cue viewer (internal, MIDI, OSC, `cue`); log; scopes | v5: richer completions with previews/sliders; docs pane with **runnable** examples; Quickstart Cards | v5: run flash + per-`live_loop` mini-scope; volume/drive; Link/MIDI clock | Parity target in the PRD. v5 also added live audio-device switching via SuperSonic |
| [s00500.sonic-pi-extension](https://marketplace.visualstudio.com/items?itemName=s00500.sonic-pi-extension) ([s00500/vscode-sonic-pi](https://github.com/s00500/vscode-sonic-pi)) | VS Code | F5 run (same lineage as jakearl) | Adapted “for Sonic Pi v4 and up” | Not documented beyond the jakearl base | Completions, hovers, examples, tutorial content | — | Current Marketplace fork of jakearl + llloret; README is thin; still the most-installed alternative |
| [JacksonKearl/vscode-sonic-pi](https://github.com/JacksonKearl/vscode-sonic-pi) ([jakearl Marketplace](https://marketplace.visualstudio.com/items?itemName=jakearl.vscode-sonic-pi)) | VS Code | F5, Open Examples | Pre-v4 paths; community reports of breakage on 4.3+ ([in-thread thread](https://in-thread.sonic-pi.net/t/vs-code-extension/3935?page=3)) | Limited | Completions, hovers | — | Last Marketplace build around 2021; language-support ancestor of vs-sonic-pi |
| [llloret/sonic-pi-vscode-editor](https://github.com/llloret/sonic-pi-vscode-editor) | VS Code (dev-mode) | Alt/Cmd-R run, Alt/Cmd-S stop, Alt/Cmd-T selection (native-style) | Configurable auto-launch of the backend | **Logs and cues** in the Output panel; error highlight | Snippets with choosers (`fx`, `us`, `sa`) | — | Unreleased-as-extension ancestor of run/stop; last meaningfully active years ago; Linux untested per README |
| [mactkg/vscode-sonic-pi](https://github.com/mactkg/vscode-sonic-pi) | VS Code | Send / stop | Assumes a running app | **Cannot display logs** (known issue) | — | **Eval flash** colors (`sonicpi.flashBackgroundColor`) | Small, older; last release 2020 |
| [SunderB/sb-atom-sonic-pi](https://github.com/SunderB/sb-atom-sonic-pi) | Atom | Run / stop | v4.0+ server control | Logs | Autocomplete | — | Atom is discontinued; not regularly maintained (README) |
| [porras/sonic-pi-mode](https://github.com/porras/sonic-pi-mode) | Emacs | Send buffer / stop | Starts/connects the v4 daemon | — | — | **Volume control** command | Explicitly 4.x only; successor of sonic-pi.el |
| [repl-electric/sonic-pi.el](https://github.com/repl-electric/sonic-pi.el) | Emacs | Send buffer / stop | `jack-in` / connect (pre-v4 server layout) | — | Highlight | — | Older stack (Sonic Pi 2/3 era) |
| [magicmonty/sonicpi.nvim](https://github.com/magicmonty/sonicpi.nvim) | Neovim | Send buffer / stop | v4+ daemon start/stop + keep-alive; **no external CLI** | **Logs and cues** | Completions/help parsed from Sonic Pi server docs; nvim-cmp; LSP-style `.sonicpi` | — | Strongest editor-plugin protocol peer; Sam Aaron pointed at it on #3205 |
| [lilyinstarlight/vim-sonic-pi](https://github.com/lilyinstarlight/vim-sonic-pi) | Vim / Neovim | Eval / stop / record | Via [emlyn/sonic-pi-tool](https://github.com/emlyn/sonic-pi-tool) or [lpil/sonic-pi-tool](https://github.com/lpil/sonic-pi-tool); README notes v4 tool work was incomplete | Log window | — | Recording | Relies on an external CLI; sonic-pi-cli is a weaker fallback ([Widdershin/sonic-pi-cli](https://github.com/Widdershin/sonic-pi-cli)) |
| [dermusikman/sonicpi.vim](https://github.com/dermusikman/sonicpi.vim) | Vim | Buffer / selection send | sonic-pi-cli or sonic-pi-tool | — | **Omnicomplete of synth-specific params** | — | Good language-UX prior art; pre-v4 defaults |
| [tidalcycles/vscode-tidalcycles](https://github.com/tidalcycles/vscode-tidalcycles) ([Marketplace](https://marketplace.visualstudio.com/items?itemName=tidalcycles.vscode-tidalcycles)) | VS Code | Shift+Enter line, Ctrl+Enter block, hush | Spawns GHCi / SuperDirt, not OSC-to-Sonic-Pi | GHCi output; eval count | Hover/completion levels | **`tidalcycles.feedbackColor` eval flash** | Best VS Code live-coding UX reference |
| [pulsar-tidalcycles](https://github.com/tidalcycles/pulsar-tidalcycles) | Pulsar | Line / selection / whole editor; mute | GHCi | OSC eval highlighting | — | Osc-triggered eval | Same family as the old Atom Tidal package |
| [strudel-box](https://marketplace.visualstudio.com/items?itemName=deep2universe.strudel-box) | VS Code | Ctrl/Cmd+Enter eval, Ctrl/Cmd+. stop | In-editor Strudel REPL (no Sonic Pi) | File browser / now playing | `.strudel` editor | Playlist, instant audio | In-process engine; Hydra/CSound not loaded |
| [bonzonkim/strudel.nvim](https://github.com/bonzonkim/strudel.nvim) | Neovim | Line / file eval | Browser Strudel via OSC + Puppeteer | — | Offline catalog completions | **In-buffer per-note token flash** in time with audio | Strongest “code lights up with the beat” reference |
| [Flok](https://codeberg.org/munshkr/flok) | Web P2P editor | Slot eval to many REPLs (Tidal, Hydra, Strudel, sclang, …) | `flok-repl`; **Sonic Pi target still unfinished** ([issue #29](https://codeberg.org/munshkr/flok/issues/29)) | — | Multi-language slots | Collaboration | Do not treat as a ready Sonic Pi integration. Hydra itself is a browser visual synth, not an editor plugin |

Related implementation references (not editors): official [C++ API](https://github.com/sonic-pi-net/sonic-pi/tree/dev/app/api) used by the Qt GUI; [SunderB/sonic-pi-js-api](https://github.com/sunderb/sonic-pi-js-api) (`save_and_run_buffer` / `workspace_zero`…`workspace_nine`).

## 5. Ranked improvement proposals

Effort: **S** = hours to about a day; **M** = a few days; **L** = a week or more, or needs protocol/hardware research. None of these are already open as issues. Items marked “catalogued” are already named in the PRD / `features.yml` as Phase 3 / `tbd`.

### 1. Sonic Pi v5 daemon stdout and SuperSonic protocol compatibility — **P1**

- **Area:** OSC / server handling  
- **Rationale:** v5 (7 August 2026) replaced scsynth with SuperSonic and changed the daemon stdout contract from eight integers (v4.6) to seven fields ending in a hex `engine-secret`. The current parser will reject that line, so `DaemonSpawner` cannot attach to a current official install. This is the highest-leverage gap: most other features assume a working connection. Support both layouts, detect version from field count/types, keep the token as the first OSC argument, and **never log the engine-secret**. Optionally document v4 vs v5 support in the README (it still says v4.x).  
- **Sources:** [daemon.rb `dev` print + comments](https://github.com/sonic-pi-net/sonic-pi/blob/dev/app/server/ruby/bin/daemon.rb); [daemon.rb v4.6.0](https://github.com/sonic-pi-net/sonic-pi/blob/v4.6.0/app/server/ruby/bin/daemon.rb); [v5.0.0 release](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0); [PortDiscovery.ts](https://github.com/bamr87/vs-sonic-pi/blob/main/src/connection/PortDiscovery.ts); [issue #3205](https://github.com/sonic-pi-net/sonic-pi/issues/3205) (stdout is the supported API). Related hardening already done upstream: [PR #3524](https://github.com/sonic-pi-net/sonic-pi/pull/3524) (GEM_PATH warnings corrupting the port line).  
- **Effort:** M  
- **Duplicates existing feature/issue?** No. Code already implements the *v4* contract well; this is a v5 compatibility fix, not a new spawn feature.

### 2. Dedicated cue (and MIDI) viewer — **P2**

- **Area:** UX / performance feedback  
- **Rationale:** The native GUI’s cue pane is how live coders see `cue`/`sync`, incoming OSC, and MIDI. vs-sonic-pi’s `LogManager` handles `/log/multi_message`, `/log/info`, `/error`, `/syntax_error`, and `/scsynth/info` only — no cue stream. llloret and sonicpi.nvim already split logs and cues. This is PRD FR-19 and, if MIDI events are shown in the same pane or a sibling view, FR-20. A VS Code Output channel or a sidebar/webview is enough for v1; do not block on a scope.  
- **Sources:** [PRD FR-19 / FR-20](https://github.com/bamr87/vs-sonic-pi/blob/main/docs/PRD.md); [LogManager.ts](https://github.com/bamr87/vs-sonic-pi/blob/main/src/log/LogManager.ts); [llloret README](https://github.com/llloret/sonic-pi-vscode-editor); [sonicpi.nvim](https://github.com/magicmonty/sonicpi.nvim); [Sonic Pi MIDI tutorial (cue paths)](https://sonic-pi.net/tutorial-11.html).  
- **Effort:** M  
- **Duplicates existing feature/issue?** Catalogued as SONICPI-019 / 020 (`tbd`). No GitHub issue.

### 3. Eval flash and optional live-loop activity feedback — **P3**

- **Area:** UX  
- **Rationale:** Live-coding editors almost all flash the evaluated range so the performer can see what just ran. mactkg already did this in VS Code; TidalCycles exposes `tidalcycles.feedbackColor`; Sonic Pi v5 flashes triggered code and can show a mini-scope beside each `live_loop`. vs-sonic-pi has no flash. A configurable decoration on Run / Run Selection / CodeLens is a small win. A later stretch is cue-timed or per-loop highlighting (strudel.nvim’s in-buffer token flash).  
- **Sources:** [mactkg flash settings](https://github.com/mactkg/vscode-sonic-pi); [TidalCycles VS Code settings](https://marketplace.visualstudio.com/items?itemName=tidalcycles.vscode-tidalcycles); [v5.0.0 GUI notes](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0); [strudel.nvim visuals](https://github.com/bonzonkim/strudel.nvim).  
- **Effort:** S for flash; L if bound to audio/cues  
- **Duplicates existing feature/issue?** No.

### 4. Performance keybindings and “run current loop or block” — **P4**

- **Area:** UX  
- **Rationale:** The native GUI uses Alt/Cmd-R (run) and Alt/Cmd-S (stop); llloret copied those. TidalCycles/Pulsar use Shift+Enter (line) and Ctrl+Enter (block). vs-sonic-pi binds F5 / Shift+F5 / Ctrl+F5, which work under `editorLangId == sonicpi` but collide with the muscle memory of VS Code’s debugger and of Sonic Pi itself. CodeLens can run one `live_loop`, but there is no keyboard command for “run the loop or block at the cursor” without a selection. Add a setting or keybinding preset (Sonic Pi / Tidal-like / current F5) and a “Run current loop or block” command.  
- **Sources:** [llloret keybindings](https://github.com/llloret/sonic-pi-vscode-editor); [vscode-tidalcycles](https://marketplace.visualstudio.com/items?itemName=tidalcycles.vscode-tidalcycles); [pulsar-tidalcycles](https://github.com/tidalcycles/pulsar-tidalcycles); [package.json keybindings](https://github.com/bamr87/vs-sonic-pi/blob/main/package.json); v5 “Keyboard Shortcuts preferences tab”.  
- **Effort:** S  
- **Duplicates existing feature/issue?** No. Does not replace CodeLens; it makes the same action keyboard-first.

### 5. Runnable examples in the tutorial / docs webview — **P5**

- **Area:** Docs / tutorial  
- **Rationale:** The built-in 85-chapter tutorial is a real differentiator, but `TutorialWebview` sets `enableScripts: false` and only renders markdown — readers cannot Run a chapter example in place. Sonic Pi v5 rebuilt the Docs pane around syntax-highlighted, **play/stop-from-the-help-pane** examples and Quickstart Cards. A conservative v1: “Insert into editor” and “Run this example” buttons on fenced code blocks (requires a careful webview CSP, unlike the current no-script page).  
- **Sources:** [TutorialWebview.ts](https://github.com/bamr87/vs-sonic-pi/blob/main/src/ui/TutorialWebview.ts); [v5.0.0 “rebuilt Docs help pane”](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0); [official tutorial](https://sonic-pi.net/tutorial.html).  
- **Effort:** M  
- **Duplicates existing feature/issue?** No. Tutorial *viewer* is shipped (SONICPI-018); run-from-docs is not.

### 6. Safer attach-or-spawn connection policy — **P6**

- **Area:** OSC / server handling  
- **Rationale:** The PRD’s main operational risk is a port / daemon conflict with the Qt GUI. The extension may spawn `daemon.rb` when no `port-info` file exists, even if the official app is already running (the GUI does not necessarily write *this* extension’s `~/.sonic-pi/port-info`). Conversely, if the user follows the README (“open the Sonic Pi application”), a second daemon is the failure mode. A clearer policy: probe an existing server first; only spawn if ping fails; if the GUI is detected, attach or tell the user not to start a second backend; surface scsynth device info (`/scsynth/info` is already logged) when audio is silent. This pairs with proposal 1, because attach/spawn both need a parser that understands the version in use. Official guidance remains: start `daemon.rb` yourself and read stdout — do not scrape `spider.log`.  
- **Sources:** [PRD §14 port-conflict risk](https://github.com/bamr87/vs-sonic-pi/blob/main/docs/PRD.md); [ConnectionManager.ts](https://github.com/bamr87/vs-sonic-pi/blob/main/src/connection/ConnectionManager.ts); [Sam Aaron on controlling the server](https://in-thread.sonic-pi.net/t/control-sonic-pi-server-via-python-on-windows/8957); [#3205](https://github.com/sonic-pi-net/sonic-pi/issues/3205).  
- **Effort:** M  
- **Duplicates existing feature/issue?** No. Auto-start (SONICPI-015) is already shipped; this is conflict handling and UX, not “add a spawner”.

### 7. Multi-buffer workspaces / Sets — **P7**

- **Area:** Features / live performance  
- **Rationale:** The native GUI has ten named workspaces (`workspace_zero`…`workspace_nine`). v5 adds Sets: save/load all ten buffers as one `.sonicpi` file. vs-sonic-pi already uses a stable per-document buffer id so re-running a file replaces the previous job (CHANGELOG), but it does not map tabs onto Sonic Pi workspaces or offer Sets. PRD FR-22. Useful for sets with several loops in separate files. The JS API’s `save_and_run_buffer` is a concrete model.  
- **Sources:** [PRD FR-22](https://github.com/bamr87/vs-sonic-pi/blob/main/docs/PRD.md); [v5 Sets](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0); [sonic-pi-js-api](https://github.com/sunderb/sonic-pi-js-api); [SonicPiAPI docs](https://sunderb.me/sonic-pi-js-api/latest/SonicPiAPI.html).  
- **Effort:** M–L  
- **Duplicates existing feature/issue?** Catalogued as SONICPI-022 (`tbd`). No GitHub issue.

### 8. Refresh language data and completions for the v5 DSL — **P8**

- **Area:** Language support  
- **Rationale:** Completions and hover already cover a large v4 catalog and even option keys for a given synth/FX. v5 adds `set_drive!`, `link_audio`, `use_bpm :midi`, game-controller cues, new scales/chords, and a much richer official completion popup (inline docs, sample preview, option sliders). The cheapest valuable step is to re-run `npm run extract-data` against a v5 checkout and add hover/completion for the new functions. Signature Help for opts would approach sonicpi.vim’s contextual omnicomplete without copying the full v5 GUI playground. Sample preview from hover is optional and needs audio.  
- **Sources:** [v5.0.0 synths, theory, and completion UI](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0); [CompletionProvider.ts](https://github.com/bamr87/vs-sonic-pi/blob/main/src/language/CompletionProvider.ts); [AGENTS.md `extract-data`](https://github.com/bamr87/vs-sonic-pi/blob/main/AGENTS.md); [sonicpi.vim omnicomplete](https://github.com/dermusikman/sonicpi.vim).  
- **Effort:** S for data refresh; M for signature help / richer UI  
- **Duplicates existing feature/issue?** No. SONICPI-009 is already shipped; this is a catalog/version update.

### 9. Audio scope (optional per-loop mini-scope) — **P9**

- **Area:** UX (stretch)  
- **Rationale:** The native app’s scope (and v5’s triggered scopes plus per-`live_loop` mini-oscilloscopes) is the remaining large parity hole. PRD FR-21 already marks it a stretch. `daemon.rb` notes that the scsynth/SuperSonic port is needed “for connecting to the boost shared memory for scope data.” Codespaces `openAudioStream` is an HTTP MP3 player, **not** a scope — do not confuse the two. Reasonable order: get v5 protocol working (proposal 1), then a simple waveform/level webview, then per-loop scopes if the engine API allows it.  
- **Sources:** [PRD FR-21](https://github.com/bamr87/vs-sonic-pi/blob/main/docs/PRD.md); [daemon.rb scope comment](https://github.com/sonic-pi-net/sonic-pi/blob/dev/app/server/ruby/bin/daemon.rb); [v5.0.0 scopes](https://github.com/sonic-pi-net/sonic-pi/releases/tag/v5.0.0).  
- **Effort:** L  
- **Duplicates existing feature/issue?** Catalogued as SONICPI-021 (`tbd`). Audio stream already exists and should not be re-filed as a scope.

### 10. (Not recommended this cycle) Collaborative Flok-style sessions

- Flok’s Sonic Pi target is still incomplete ([issue #29](https://codeberg.org/munshkr/flok/issues/29); comments through 2026). Troop and similar tools speak OSC, but this is a product bet, not a gap in an otherwise complete editor. Revisit only after proposals 1 and 2 are solid.

## 6. Docs / catalog debt (not user-facing features)

Worth a small Tools/docs PR, not a `deep-dive` feature epic:

- Mark SONICPI-009, 010, 013, 014, 015 as `shipped` in `features/features.yml` and regenerate the PRD catalog.
- Update PRD / `docs/08-daemon-spawner.md`: heartbeat is 2 s / 3 s timeout, not ~30 s / ~90 s; discovery uses `port-info` and daemon STDOUT, not `spider.log`; document both v4.6 (8 ints) and v5 (token + engine-secret) layouts.
- README compatibility line should name the tested Sonic Pi versions once proposal 1 lands.

## 7. Suggested filing order for Tools

1. **v5 daemon protocol** (blocker for current official installs)  
2. **Cue / MIDI viewer** (largest missing live-coding pane)  
3. **Eval flash** (small, high-visibility UX)  
4. **Keybinding presets + run current loop/block** (small)  
5. **Runnable tutorial examples**  
6. **Attach-or-spawn policy** (can share a PR with 1)  
7. **Workspaces / Sets**  
8. **v5 language data** (can start in parallel with 1 once a v5 tree is available)  
9. **Scope** only after 1 is proven  

No GitHub items were opened by this research.

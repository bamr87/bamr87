# The Switches page: every loop's kill switch, read live, flipped through the map — evidence

> **Feature:** `HUB-057` (FR54, constitution § 17, amendment 0014) · **Scenario:** `verify/scenarios/console-switches.yml` · **Result:** **PASS** (2/2 viewports on the public build) plus a hand-driven pass on two worktree consoles · **Captured:** 2026-11-25 with Playwright (system Chrome, headless) from scratch scripts that are not committed.

No apply was made against GitHub. On the running console the flip dialog was opened, a reason typed, **Preview** pressed and the dialog cancelled; **Apply** was never pressed. Afterwards `gh variable list -R bamr87/it-journey` still read `THEME_SCOUT_ENABLED=true` with its 2026-11-23 `updatedAt`, and the worktree's `.fleet/switches/` held only preview plans: no result, no audit line, no activity record.

## The public build (the scenario)

`CONSOLE_BASE=/ tools/console/build-pages.sh` into a scratch directory, served statically on `127.0.0.1:4021`; the scenario's steps run by hand with Playwright (the hub's runner needs `@playwright/test`, which this worktree does not install). At both viewports `/switches` answered 200, the page header read **Switches**, the **Runs on a console** banner was shown, no switch table was rendered (`[data-switches-repo]` count 0; the snapshot has no `switches` document) and the page did not scroll sideways.

| Image | Viewport | What to look at |
| --- | --- | --- |
| `switches-public--desktop.png` | 1280×800 | the page under Harnesses → Switches, the description, and the banner saying the switches are read with the operator's token |
| `switches-public--mobile.png` | 390×844 | the same at phone width |

## A running console, GitHub writes on

`CONSOLE_PORT=4011 tools/dash console` from this worktree (`CONSOLE_AUTO_HEALTH=0`, its own `DASH_CONSOLE_JOBS` in scratch), reading GitHub with the maintainer's `gh` login (reads only). The map then held 79 loops in 4 repos: 67 on, 12 off, 1 drift; `bash-365/bash-365.com` reads but is not writable (the console writes only to repos the hub owns).

| Image | What it shows |
| --- | --- |
| `switches--desktop.png` (1440×900) | the header badges (on, off, drift, **writes on**), **Read GitHub again**, the level badges, the commit note, and the hub's table: loop, switch, effective, live value (`unset` for an unset opt-out variable reads on), the map's state (`unverified ?` for the hub records nobody has verified), drift, hold, variable, semantics, workflow; **All on / All off** for the repo |
| `switches--mobile.png` (390×844) | the same at phone width; the switch sits beside its loop and the table scrolls inside its card, nothing scrolls the page sideways |
| `switches-full--desktop.png` | the whole page: bamr87/bamr87, bamr87/it-journey (21 new records, all on and verified), bamr87/lifehacker.dev and bash-365/bash-365.com (6 new records, read-only, levers disabled) |
| `switches-drift-hold--desktop.png` | `lifehacker.dev/auto-merge`: the variable reads `'true'`, the map says `off`, so a **drift** badge, and a **held** badge for `HUB_ORIGINATION_HOLD` — its effective state is off whatever the variable says |
| `switches-modal--desktop.png` | the toggle of `it-journey/theme-scout` opened the dialog: a required reason, **Preview** pressed — plan `993efca7e9067b28`, `THEME_SCOUT_ENABLED 'true' → 'false'; map on → off`, and the exact `_data/fleet.yml` diff (state, reason, `set_by` bamr87, `set_at` 2026-11-25, the flip line kept as context) — then **Check it still matches**, **Apply to 1** and **Cancel**; Cancel was pressed |
| `switches-modal--mobile.png`, `switches-modal-actions--mobile.png` | the same dialog at 390 wide, top and scrolled to its buttons |

`POST /api/jobs` with `switches-apply`, `apply: true` and no confirm answered **409** (`… resubmit with confirm=true`); the same operation without `apply`, run as a job, printed `plan 993efca7e9067b28 still matches: 1 to do (1 variable(s), 1 map record(s)), 0 skipped. Nothing written (dry run); --apply writes it.`

## A running console, GitHub writes off

The same worktree on `127.0.0.1:4019` with `DASH_CONSOLE_GITHUB_WRITES=off`.

| Image | What it shows |
| --- | --- |
| `switches-writes-off--desktop.png` | a **writes off** badge, the warning banner naming `DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH`, the reason repeated under each repo, **All on / All off** and every toggle disabled |
| `switches-writes-off--mobile.png` | the same at 390 wide |

No console error was logged in any capture.

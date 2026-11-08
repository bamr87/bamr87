# Local stacks from the portal — evidence

> **Feature:** `HUB-078` (phase P1, #702, of [ADR 0005](../../../docs/adr/0005-console-as-fleet-portal.md)) · **Result:** **PASS** (interactive pass) · **Verified:** 2026-11-06 against a console from this branch on `127.0.0.1:4012`

An app's Local target can now be started, stopped and read from the App Shell, on the Apps page and in a Desktop window, as console jobs. There is no scenario: the public build has no console and shows only the terminal command, which `verify/scenarios/apps.yml` already covers.

**No real stack was started (constitution § 10.5).** The test console ran with a stand-in `docker` first on its `PATH`. It recorded every call and never reached the daemon. Its `up -d` served a throwaway page on gitorio's port after six seconds, like a stack booting, and its `down` stopped that page. `tools/dash dev up gitorio` and `tools/fleet-dev.sh` were the real ones. After the pass, real Docker had no gitorio container.

| Image | What it shows |
| --- | --- |
| `console-stopped-desktop.png` | a stopped Local target: **Start the stack**, the terminal command, Check again |
| `console-starting-desktop.png` | **Starting gitorio…**: the job finished and the page is waiting for the address to answer |
| `console-running-desktop.png` | the app framed with no reload, **Logs** and **Stop the stack** beside its address |
| `console-window-running-desktop.png` | the same in a Desktop window |
| `console-window-failed-desktop.png` | a start that failed: **The last start failed**, a link to its log, and Start offered again |
| `console-no-docker-desktop.png` | a console with no Docker access: no Start button, the reason, and the terminal command |
| `console-stopped-mobile.png` | a stopped target at 390 wide; no sideways scroll |

Measured in that pass, not pictured:

- **The cycle.** Start, then the frame loaded by itself about 9 seconds later; Logs showed the stack's lines; Stop returned the page to stopped. In a Desktop window the same, with the drawer closed at once.
- **Refusals.** `POST /api/jobs` with `dev-up` for `bamr87` and for `--all` answered 400.
- **A failed start's log** opened as a window on the Desktop.

## What the pass found

1. **A stop within 90 seconds of a start still showed "Starting…"**, because any recent start counted. Fixed: the newest start or stop decides.
2. **Clicking Start before the operations list had loaded** gave "Unknown operation". Fixed: the button appears once the list is known.
3. **Closing the job drawer quickly left the page stale**: documents refresh only while the drawer's log is open, so a stopped stack still showed its frame. Fixed: the App Shell asks the address again whenever its stack's job ends.

## Not covered

Chromium only. A real stack has not been started from the portal: that is the first deploy step, and it needs the maintainer's yes (§ 10.5). Real start times, a Django app's frame policy on a live local stack, and the Docker VM's memory under a started stack are therefore unobserved. The core console in Docker has no socket on purpose, so Start works from a native console (`tools/dash console`); the container shows the terminal command.

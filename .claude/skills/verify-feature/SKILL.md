---
name: verify-feature
description: "Verify a feature, change, or fix the way a USER experiences it — in the hub or in any fleet repo: read the feature index for context, run the app per verify/verify.yml, drive it in a real browser (Playwright MCP / verify/runner.mjs), capture screenshots + metrics into an evidence bundle, link it from features/features.yml, and report PASS/FAIL/NOT VERIFIED honestly. Also the fleet view: read _data/features_index.yml, explain a repo's coverage gaps, and seed the verify kit. Use when asked to \"verify\", \"test this in the browser\", \"prove it works\", \"add evidence\", \"what does <repo> do\", \"which features are untested\", or \"deploy the verify kit\"."
---

# verify-feature (hub)

The agent verification loop, runnable from a Claude Code session in the hub — against the dash itself or against a submodule. Full doc: [`docs/VERIFICATION.md`](../../../docs/VERIFICATION.md). The repo-local twin this skill seeds into fleet repos is [`templates/verify/SKILL.template.md`](../../../templates/verify/SKILL.template.md); follow the same eight steps so a hub pass and an in-repo pass produce the same shape.

| Piece | Where |
| --- | --- |
| Fleet index (read first) | `_data/features_index.yml` → `/features/`; rebuild offline with `tools/dash features fleet --write` |
| One repo's index | `<repo>/features/features.yml` (`features/v1`; legacy shape accepted) — `tools/dash features check|coverage <path>` |
| Run config / scenarios / runner | `<repo>/verify/{verify.yml,scenarios/,runner.mjs,mcp.json}` |
| Evidence | `<repo>/test/evidence/<slug>/` (screenshots, `report.json`, README) |
| Browser | Playwright MCP — `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_fill_form`, `browser_resize`, `browser_console_messages`, `browser_take_screenshot` (hub `.mcp.json` registers it; a repo's `verify/mcp.json` is the same server) |
| CI | `fleet-verify.yml` (reusable) ← each repo's `verify.yml`; the `verify` PR label requests the agent pass |
| Kit + fan-out | `templates/verify/` · `tools/dash verify deploy [--gaps|--target N] [--apply]` · `verify-fanout.yml` |
| Config | `_data/fleet.yml` → `verification:` (labels, agent model/turns, coverage floors, fan-out caps) |

## Steps

1. **Orient from the index, not the code.** For a repo question ("what does X do", "what's untested"), read its row in `_data/features_index.yml`: `counts`, `pct`, `gaps`, `items[*].{surface,link,docs,tests,scenarios,evidence,verified,dangling}`. Quote those — they are deterministic and graded from files on disk. If the snapshot is stale, `tools/dash features fleet --write` (offline, seconds).

2. **Scope a change to feature ids.** From the diff/issue/request, list the ids it touches (`link`/`docs` paths → files). A touched capability with no entry gets one first (stable id, `surface`, `link`, `docs`).

3. **Run the app as `verify/verify.yml` says** — `app.build`, then `app.start` in the background (or serve `app.static_dir`), poll `app.url + app.ready`. For the hub: `tools/dash verify` builds `_site` with an empty baseurl and serves it; against a running `tools/dash serve`, pass `--base http://127.0.0.1:4000/bamr87`. Do not invent another port; fix the config if it is wrong.

4. **Run what exists.** `node verify/runner.mjs --feature <ID>` (hub: `tools/dash verify --only <id>`). Read PASS/FAIL lines and `test/evidence/<id>/report.json`. A pre-existing failure is reported first.

5. **Drive it yourself** through the Playwright MCP at desktop (1280) and mobile (390): navigate, snapshot to read, interact, screenshot at each proof point; check sideways scroll, focus, console errors, empty/404 states, both colour modes. Obey `agent.never`.

6. **Write the scenario** (`verify/scenarios/<slug>.yml`, `scenario/v1`) that replays your path, re-run it, and **fill the evidence README** the runner scaffolded (what the images prove; before/after for a fix; "Not covered").

7. **Link back + stamp.** `scenarios:` and `evidence:` on the entry; `node verify/runner.mjs --feature <ID> --stamp --by agent` (or `--by human` when the user drove). `tools/dash features check <repo>` must be clean.

8. **Deliver per the submodule rule.** Changes in a submodule are committed and pushed there first (`SUBMODULES.md`), one repo per PR; the hub bumps the pointer. Never bundle several submodules. Then `tools/dash features fleet --write` so the fleet index reflects it.

## Seeding the kit

`tools/dash verify deploy --target <name>` (dry run; `--apply` opens the PR on `test/agent-verification`), or `--gaps` for every repo the committed index grades as user-facing with no index/kit. Additive-only, external upstreams skipped, `.claude/` artifacts only when no verification skill exists. After merge the repo owner (or an `@claude` mention) fills `verify/verify.yml` `app:` and replaces the `TODO-001` entry — the fan-out PR body lists the steps.

## Report shape

Per feature: **PASS / FAIL / NOT VERIFIED** · scenario id · evidence dir · one sentence. Then findings (step, viewport, image) and "Not covered". Never describe behaviour you did not observe in the browser; a non-user-visible change gets `skip-evidence` and a reason, not manufactured evidence.

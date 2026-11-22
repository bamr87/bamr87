# templates/ux-audit/

Fleet UX audit kit — the computational floor + evidence bundle for continuous UI/UX review across bamr87 repos. Named as the gap in [`specs/FRONTEND.md`](../../specs/FRONTEND.md) (UPS-FE-53, UPS-FE-60).

## Roles

| Plane | Where | What |
| --- | --- | --- |
| **Define** | `bamr87/bamr87` | `ux:` on `_data/projects.yml`, caps in `_data/fleet.yml`, this kit |
| **Gate (leaf)** | each UI repo | `ux-gate.yml` runs axe + R1–R13 on PRs that touch UI |
| **Critique (hub)** | hub scheduled loop | specialists consume evidence bundles; draft PRs only (see `docs/UX-HARNESS.md`) |

## What this kit seeds

| File | Seeded as | Purpose |
| --- | --- | --- |
| `ux.manifest.example.yml` | `ux.yml` (only if absent) | surfaces, personas, preview command |
| `scripts/ux_audit.py` | `scripts/ux_audit.py` | UPS-FE-60 R1–R13 machine rules |
| `scripts/collect_evidence.mjs` | `scripts/collect_evidence.mjs` | Playwright screens + axe JSON |
| `scripts/layout_capture.mjs`, `layout_probe.mjs` | `scripts/` | rendered layout capture: geometry + wireframe SVG + screenshot per page and width, rules L1–L6 |
| `scripts/layout_compare.mjs` | `scripts/` | change (base → head) and consistency (one role across sites) from captures |
| `workflows/ux-gate.yml` | `.github/workflows/ux-gate.yml` | PR gate |
| `prompts/*.md` | `.ux-audit/prompts/` (opt-in) | specialist critique prompts |
| `AGENT_PROMPT.md` | `.ux-audit/AGENT_PROMPT.md` | how an agent consumes an evidence bundle |

## Fan-out

```bash
# dry-run first — OPT-IN kit, never in the default set
tools/fanout.sh --kit ux-audit --target gaps --dry-run
tools/fanout.sh --kit ux-audit --target it-journey   # example leaf
```

Selection for `gaps`: registry entries with `ux.enabled: true` (or `kinds` ∩ {site,app,ext} and `live_url` set) that lack a seeded stamp.

## Leaf quick start

1. Copy `ux.manifest.example.yml` → `ux.yml` and list real surfaces.
2. `python3 scripts/ux_audit.py --root .` (or `--root frontend` for monorepo apps).
3. `node scripts/collect_evidence.mjs` (requires `playwright`, `@axe-core/playwright`).
4. Keep `ux-gate.yml` on UI-touching PRs.

## Layout capture (L1–L6)

The R-rules read source; axe reads accessibility. Neither sees how a page lays out once rendered: a nav strip that hides its scrollbar and clips its own current item passes both (lifehacker.dev/news/wire/, 2026-11-14). The layout capture loads each surface at three widths and measures the boxes.

```bash
npm i -D playwright js-yaml && npx playwright install chromium        # once, in the leaf
node scripts/layout_capture.mjs --manifest ux.yml --base-url http://127.0.0.1:4000 --out layout/base
# … change something …
node scripts/layout_capture.mjs --manifest ux.yml --base-url http://127.0.0.1:4000 --out layout/head
node scripts/layout_compare.mjs --base layout/base --head layout/head    # rules fixed / introduced, boxes moved
node scripts/layout_compare.mjs --consistency layout/head                # one role across sites
```

Per page and width (`phone` 375×812, `tablet` 768×1024, `desktop` 1280×800) it writes `<id>--<width>.json` (every visible landmark, heading, text, link, control and image box, the rules broken, the pattern anchors), `<id>--<width>.svg` (a wireframe drawn from that geometry, violations in red) and `<id>--<width>.png`; plus `summary.json` (`schema: ux-layout/v1`) and `summary.md`.

| Rule | Severity | Fires when |
| --- | --- | --- |
| L1 page-overflow | error | the page pans sideways (overflow the root clips with `overflow-x: hidden`/`clip` does not count) |
| L2 current-clipped | error | the current item (`aria-current` / `.active`) is cut off by its container or the viewport |
| L3 squeezed-label | warn, phone | a label of 32 characters or fewer wraps in a box narrower than 55% of the screen |
| L4 indented-column | warn, phone | a 3+ line text block starts more than 32px right of the content edge, outside a card, article or list item |
| L5 long-lead | warn, phone | text at 18px or larger runs more than 5 lines |
| L6 hidden-scroller | warn | controls sit off-screen in a strip whose scrollbar is hidden |

The score (100 − 15 per error − 5 per warning) is provisional: a trend line, not a gate. **Warn-only by default**: `--fail-on error|warn` (capture) and `--fail-on regression` (compare) turn findings into exit 1 once a repo decides to gate. A run that captured nothing exits 2, because absent is not zero. `--inject-css FILE` previews a fix before it ships; `UX_CHROMIUM_PATH` points at a Chromium when the bundled one is missing. Geometry, not pixels, is the unit of comparison: a pixel diff counts everything content pushed down and cannot compare two sites whose content differs; boxes can.

The hub runs this over the registry's `ux.surfaces` as `dash ux` ([docs/UX-HARNESS.md](../../docs/UX-HARNESS.md)). The kit's own tests (`tests/`, fixtures only, no network) run with `npm test` here and in `.github/workflows/ux-audit-selftest.yml`; `package.json` and `tests/` are hub-only and never seeded.

## Exempt markers

- File-wide: `ux-audit: exempt — <reason>`
- Single rule: `ux-audit: exempt-R7 — <reason>`

## Reference

App-specific deeper rules (shell/scroller contracts, LSAT parity, …) live in `bamr87/law-ai` `scripts/ux_audit.py`. This kit stays portable on purpose.

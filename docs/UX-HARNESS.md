# UX Harness — continuous UI/UX audit for the fleet

> Continuous UI/UX audit for the fleet: the `ux-audit` kit's computational gate and the hub's critique loop.

> **Status:** kit 0.2.0 (`templates/ux-audit/`). The computational gate and the layout capture (`dash ux`, rules L1–L6) are real; the layout capture is warn-only and runs on demand; the hub critique loop is designed here and capped in `_data/fleet.yml` but not wired as a cron yet.

## Why it lives in bamr87

bamr87 is the control plane: `_data/projects.yml` decides **which** repos are in scope, `templates/ux-audit/` defines **what** gets seeded, `_data/fleet.yml` caps **how often / how much**, and leaf repos run the gate. That matches the existing harness pattern (`docs/HARNESS.md`, `docs/HARNESS-OPS.md`).

## Scope rule

A repo is UX-in-scope when:

1. `ux.enabled` is true on its `_data/projects.yml` entry, **or**
2. `ux` is omitted but `live_url` is set and `status` is not `archived` (pilot default).

Out of scope: pure libs/CLIs/content unless they opt in with `ux.enabled: true`.

### `ux:` registry fields

```yaml
ux:
  enabled: true
  tier: active          # active | experiment | content
  surfaces:             # optional override of leaf ux.yml; read by `dash ux`
    - url: https://example.com/
      role: home
    - url: /news/wire/  # relative URLs join live_url
      role: section     # captures sharing a role are compared across sites
  personas: [first-time, returning]
  preview:              # documented for leaf; not executed by the hub
    command: "npm run preview"
    ready_url: http://127.0.0.1:4173/
  baselines: none       # none | visual | journey
```

## Kit

`templates/ux-audit/` (see its README) seeds:

- `ux.yml` manifest example
- `scripts/ux_audit.py` — UPS-FE-60 R1–R13 (stdlib)
- `scripts/collect_evidence.mjs` — Playwright + axe evidence MVP
- `scripts/layout_capture.mjs` + `layout_probe.mjs` + `layout_compare.mjs` — rendered layout capture, rules L1–L6 (below)
- `.github/workflows/ux-gate.yml`
- specialist prompts + agent consumption guide

Fan-out is **OPT-IN** (`tools/fanout.sh --kit ux-audit`). Never part of the default standardize artifact set.

## Two planes

| Plane | Trigger | Blocking? | Output |
| --- | --- | --- | --- |
| Leaf computational gate | PR paths touching UI | Yes (R-rules) | annotations / job fail |
| Evidence collector | PR or dispatch | Advisory in 0.1.0 | `evidence/` artifact |
| Hub critique loop | schedule / manual (roadmap) | No — draft PRs only | ranked findings |

## Layout capture (`dash ux`)

The R-rules read source and axe reads accessibility; neither sees how a page lays out once rendered. On 2026-11-14 lifehacker.dev/news/wire/ was cramped and clipped at phone width while every gate stayed green: the page never scrolled sideways, and a nav strip that clips its own current item breaks no WCAG rule. `dash ux` is the first reader of the registry's `ux.surfaces`: it loads each page in Chromium at 375, 768 and 1280px through the kit's layout capture and writes, per page and width, a geometry snapshot (every visible box), a wireframe SVG drawn from it, a screenshot, and the layout rules it broke.

```bash
cd templates/ux-audit && npm install --no-package-lock && npx playwright install chromium   # once
tools/dash ux targets --repo lifehacker.dev             # what the registry declares
tools/dash ux capture --repo lifehacker.dev --repo zer0-mistakes   # → .fleet/ux/<UTC stamp>/
tools/dash ux capture --repo lifehacker.dev --role section --inject-css fix.css --out .fleet/ux/fix
tools/dash ux compare .fleet/ux/<base> .fleet/ux/fix    # rules fixed / introduced, boxes resized, added, removed
tools/dash ux consistency .fleet/ux/<run>               # one role across sites, by its anchors
```

The rules (L1 page pans sideways, L2 current item clipped, L3 squeezed label, L4 indented column, L5 long lead, L6 hidden scroller) and their thresholds are in [the kit README](../templates/ux-audit/README.md#layout-capture-l1l6). Three properties hold:

- **Warn-only.** Findings never change the exit code unless `--fail-on` asks; gating needs a ratified amendment extending § 18. A run that captured nothing exits 2: absent is not zero.
- **Geometry is the unit, not pixels.** A pixel diff counts every pixel that content pushed down and cannot compare two sites whose content differs. The structural diff names the boxes that resized, appeared or disappeared, and `consistency` separates a layout difference (x, width, font size) from a content one (y, line count).
- **Read-only.** It loads public pages and writes only under `.fleet/ux/` (gitignored).

The first run (2026-11-22, [evidence](../test/evidence/ux-layout-capture/README.md)) scored lifehacker.dev/news/wire/ 65 at phone width and 100 with the theme's section-layout fix previewed through `--inject-css`, and found the same defects on the theme's own section page, so the fix belongs in zer0-mistakes `_layouts/section.html`.

## Caps (`_data/fleet.yml` → `ux_audit:`)

Keep critique under the same throughput/budget discipline as other harnesses. Defaults are conservative; raise deliberately.

## Roadmap

1. ~~Schema + kit MVP~~ (this change)
2. Fan-out to pilot live_url repos
3. `dash-gen` → `_data/ux_registry.yml` + `/ux/` dash page
4. Hub critique workflow with specialist prompts and re-gate
5. Visual baselines (UPS-FE-61) where leaves opt in — the layout capture (`dash ux`, kit 0.2.0) is the measuring half; committed baselines, a scheduled sweep of every surface and the lake rows a console page would trend are next

## References

- `specs/FRONTEND.md` — UPS-FE-50…61
- `templates/ux-audit/` — kit
- `bamr87/law-ai` `scripts/ux_audit.py` — app-specific reference rules

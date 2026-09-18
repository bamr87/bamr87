# templates/ux-audit/

Fleet UX audit kit — the computational floor + evidence bundle for continuous
UI/UX review across bamr87 repos. Named as the gap in
[`specs/FRONTEND.md`](../../specs/FRONTEND.md) (UPS-FE-53, UPS-FE-60).

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
| `workflows/ux-gate.yml` | `.github/workflows/ux-gate.yml` | PR gate |
| `prompts/*.md` | `.ux-audit/prompts/` (opt-in) | specialist critique prompts |
| `AGENT_PROMPT.md` | `.ux-audit/AGENT_PROMPT.md` | how an agent consumes an evidence bundle |

## Fan-out

```bash
# dry-run first — OPT-IN kit, never in the default set
tools/fanout.sh --kit ux-audit --target gaps --dry-run
tools/fanout.sh --kit ux-audit --target it-journey   # example leaf
```

Selection for `gaps`: registry entries with `ux.enabled: true` (or
`kinds` ∩ {site,app,ext} and `live_url` set) that lack a seeded stamp.

## Leaf quick start

1. Copy `ux.manifest.example.yml` → `ux.yml` and list real surfaces.
2. `python3 scripts/ux_audit.py --root .` (or `--root frontend` for monorepo apps).
3. `node scripts/collect_evidence.mjs` (requires `playwright`, `@axe-core/playwright`).
4. Keep `ux-gate.yml` on UI-touching PRs.

## Exempt markers

- File-wide: `ux-audit: exempt — <reason>`
- Single rule: `ux-audit: exempt-R7 — <reason>`

## Reference

App-specific deeper rules (shell/scroller contracts, LSAT parity, …) live in
`bamr87/law-ai` `scripts/ux_audit.py`. This kit stays portable on purpose.

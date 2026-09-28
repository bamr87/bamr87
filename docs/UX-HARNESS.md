# UX Harness — continuous UI/UX audit for the fleet

> **Status:** v0 kit (`templates/ux-audit/` 0.1.0). Computational gate is real; hub critique loop is designed here and capped in `_data/fleet.yml` but not fully wired as a cron yet.

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
  surfaces:             # optional override of leaf ux.yml
    - url: https://example.com/
      role: home
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
- `.github/workflows/ux-gate.yml`
- specialist prompts + agent consumption guide

Fan-out is **OPT-IN** (`tools/fanout.sh --kit ux-audit`). Never part of the default standardize artifact set.

## Two planes

| Plane | Trigger | Blocking? | Output |
| --- | --- | --- | --- |
| Leaf computational gate | PR paths touching UI | Yes (R-rules) | annotations / job fail |
| Evidence collector | PR or dispatch | Advisory in 0.1.0 | `evidence/` artifact |
| Hub critique loop | schedule / manual (roadmap) | No — draft PRs only | ranked findings |

## Caps (`_data/fleet.yml` → `ux_audit:`)

Keep critique under the same throughput/budget discipline as other harnesses. Defaults are conservative; raise deliberately.

## Roadmap

1. ~~Schema + kit MVP~~ (this change)
2. Fan-out to pilot live_url repos
3. `dash-gen` → `_data/ux_registry.yml` + `/ux/` dash page
4. Hub critique workflow with specialist prompts and re-gate
5. Visual baselines (UPS-FE-61) where leaves opt in

## References

- `specs/FRONTEND.md` — UPS-FE-50…61
- `templates/ux-audit/` — kit
- `bamr87/law-ai` `scripts/ux_audit.py` — app-specific reference rules

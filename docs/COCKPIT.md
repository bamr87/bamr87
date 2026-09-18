# Cockpit — Gitorio as the one-stop harness & orchestration platform

> **Status:** Accepted direction (2026-09-18). Implementation phased; this ADR is the contract.
> **Related:** [HARNESS.md](./HARNESS.md) (six-layer architecture), [HARNESS-OPS.md](./HARNESS-OPS.md) (fleet ops + local stack), [UX-HARNESS.md](./UX-HARNESS.md) (UX capability kit), [DASH.md](./DASH.md) (registry + CLI).

## Decision

**Gitorio is the product UI** — the single local cockpit for defining, designing, managing, monitoring, and refining AI harnesses and orchestration across the fleet.

**bamr87 is the platform runtime** — registry, `fleet.yml` contract, kits, `tools/dash` / `dash-gen`, fan-out, data lake, and Phoenix. Humans should not need a second ops GUI.

**GitHub Pages / Jekyll dash (:4000) is a static projection** of committed `_data/*.yml`. It is not the operator console.

```text
Gitorio (cockpit) ──jobs/API──► bamr87 devenv (tools/dash, kits, fan-out)
        │                              │
        │ reads                        │ writes via PR / working tree only
        ▼                              ▼
 hub YAML + lake.sqlite + Phoenix    fleet repos (Actions, switches, factory--*.yml)
        │
        ▼
 GitHub Pages = read-only billboard
```

## Why

The local stack already exists as three services (HARNESS-OPS):

| Service | Role today | Role under this ADR |
| --- | --- | --- |
| Harness Console `:4001` | Write-capable ops UI over allowlisted `tools/dash` | **Bridge / job API** until Gitorio absorbs its tabs; then headless or removed |
| Data lake + Phoenix `:6006` | Local extract/review/traces | Unchanged backend for Insight / Traces |
| Jekyll dash `:4000` / Pages | Read-only twin | Unchanged static projection |

Gitorio already owns Design (canvas/compiler), Fleet Observe, and a Harness tab that ports `dash-gen harness`. The gap is not philosophy — it is **one front door**.

## Non-negotiables

1. **Source of truth stays files in bamr87** (`_data/projects.yml`, `_data/fleet.yml`, kit `VERSION`s, generated registries). Gitorio edits them only through allowlisted dash jobs (diff + confirm + PR / working-tree), never silent pushes to `main`.
2. **No second contract store** inside Gitorio (no parallel caps DB). Blueprints *consume* caps and kill switches; they do not replace `fleet.yml`.
3. **Compiler output remains plain GitHub Actions YAML** in leaf repos. Production must not require Gitorio to be online.
4. **Lake and Phoenix stay local-only** (gitignored lake; no run-log publication to Pages).
5. **Draft-only / never-merge** agent behavior and fan-out PR discipline are unchanged.
6. **Pages never gains write UI.**

## Cockpit map (tab → backend)

| Gitorio surface | Operator job | Backend |
| --- | --- | --- |
| **Floor** | Design / compile blueprints → `factory--*.yml` | Gitorio compiler (existing) |
| **Fleet** | Roster, lines, live status, arm/disarm | `harness_registry.yml` + GitHub Actions API |
| **Harness** | Six-layer scorecard + trip wires | Hub YAML + live Fleet Ops eval (existing parity) |
| **Caps** | Edit `fleet.yml` blocks with diff | Allowlisted `tools/dash` config ops (console Config today) |
| **Deploy** | Kit gaps → dry-run → PR | `harness-fanout` / `tools/dash harnesses deploy` |
| **Auth** | Credential presence for this process / `gh` | Console Auth semantics (env / `gh auth`, never echo secrets) |
| **Insight** | Cost, waste, attention | `tools/dash lake review` (+ committed usage ledgers) |
| **Traces** | Per-run agent trees | Phoenix `:6006` (embed or deep-link by run/session id) |
| **UX** | Surfaces, evidence, critique queue | `templates/ux-audit` + `ux:` on projects + future `ux_registry.yml` |
| **Jobs** | Live log of allowlisted ops | Same job runner the console uses |
| **Docs** | Operator maps | Existing delivered maps / docs tab |

## Local topology

```bash
# from a bamr87 checkout with submodules (control-plane root)
docker compose up -d devenv phoenix console   # engine + lake API bridge + traces
# gitorio: app vite (compose service TBD)  → http://127.0.0.1:5173
# phoenix                                  → http://127.0.0.1:6006
# jekyll/pages (optional)                  → http://127.0.0.1:4000
# console bridge (until absorbed)          → http://127.0.0.1:4001
```

Target UX: one entrypoint, e.g. `tools/dash cockpit` / `make cockpit`, that brings up the stack and opens Gitorio.

Environment contract (illustrative):

| Var | Purpose |
| --- | --- |
| `BAMR87_ROOT` | Mount/path to hub checkout |
| `DASH_API` | Base URL for allowlisted jobs (console `:4001` or successor) |
| `PHOENIX_URL` | Trace UI |
| `HUB_REPO` | Default `bamr87/bamr87` for hub reads |

## Phased delivery

### Phase 0 — Platform glue
- Compose (or documented parallel) run of Gitorio against bamr87 devenv
- Gitorio can read hub files + call dash job API + open Phoenix
- `tools/dash cockpit` (or equivalent) documented in HARNESS-OPS

### Phase 1 — Absorb console (order matters)
1. **Caps** — `fleet.yml` block editor with diff + confirm  
2. **Deploy** — gaps dry-run → apply/PR  
3. **Auth** — parity with console credential rules  
4. **Jobs** — allowlisted ops + live logs  
Then stop sending operators to `:4001` by default (API may remain).

### Phase 2 — Unified Attention
- One home board: trip wires ∪ harness gaps ∪ spend anomalies ∪ UX NEW fingerprints
- Insight tab over lake review JSON

### Phase 3 — UX module
- Inventory from `projects.yml` `ux:` + kit stamp
- Evidence browser; critique only after caps + leaf gate exist (see UX-HARNESS.md)

### Phase 4 — Refine-in-product
- From a failure → propose guide / sensor / cap / blueprint patch
- Still lands as PR; ratchet remains file-based (HARNESS.md)

## Explicitly out of scope (for now)
- Rewriting `tools/dash` in TypeScript
- Replacing Phoenix with a custom trace product
- Making Pages interactive
- Mid-run dollar enforcement (still HARNESS checklist #7 — prerequisite before heavy critique automation)
- Multi-tenant SaaS packaging

## Consequences

**Good:** One bookmark for orchestration; VS Code for code; Pages for shareable static status; clear shell/engine split.  
**Tradeoff:** Gitorio must stay honest about allowlists and PR-only writes — a cockpit that bypasses `tools/dash` would recreate the silent-push failure mode the harness was built to prevent.  
**Follow-up:** Gitorio epic tracks Phase 0–4; bamr87 tracks compose/`cockpit` entrypoint and any headless console API cleanup.

## Acceptance (Phase 0 done when)
- [ ] Operator can start local stack and use **only Gitorio** to view Harness + Fleet against live hub data
- [ ] At least one write path (Caps or Deploy) goes through allowlisted dash jobs with confirm + diff
- [ ] Pages remains read-only; lake/Phoenix remain local
- [ ] This doc linked from HARNESS-OPS.md “local stack” section

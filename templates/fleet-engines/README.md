# `@bamr87/fleet-engines` — the fleet's engines, versioned once

The pure logic behind every fleet console, published from the hub and consumed **by dependency**: GitFactory's Fleet Ops cockpit, Observe map and Harness tab run it in the browser; zer0-CMS's Fleet console runs it inside VS Code. One implementation, one rulebook, one set of tests.

```bash
npm install @bamr87/fleet-engines
```

```ts
import { parseFleetManifest, extractFacts, auditWorkflow, harnessHealth } from '@bamr87/fleet-engines';
```

## What is in it

| Module | What it does | Pure? |
| --- | --- | --- |
| `harness/lanes` | The `fleet/v1` vocabulary (`FleetLane`, `FleetManifest`), `parseFleetManifest` (tolerant, never throws), `laneForPath` | yes |
| `harness/manifest-yaml` | `toFleetManifestYaml(lanes, meta)` — a manifest document from lanes, deterministic emitter | yes |
| `fleet/parse`, `fleet/facts` | Reverse-import any repo's `.github/workflows/*.yml`: triggers, sinks, the AI runner (the hub's `claude-run` by reference, a vendored copy, `claude-code-action`, the bare CLI, the agentic engine), kill switches, guards, permissions, pins | yes |
| `fleet/audit` | The rulebook: the fleet's conventions as data (`AUDIT_RULES`) and the checkers (`auditWorkflow`, `auditRepo`, `gradeFor`). Every rule is one entry — meta, applies, violations — so the published rulebook and the checks cannot drift | yes |
| `fleet/metrics` | Run-level rollups per workflow and repo | yes |
| `fleet/import` | The one orchestrator: fetches workflows + the manifest through a `GithubClient` you inject | I/O via the client only |
| `harness/health` | The hub's harness scorecard and six trip wires, recomputed from committed signals | yes |
| `harness/signals`, `harness/hubread`, `harness/hub-paths` | Live signals from a scan; the eight hub reads; the hub's paths and snapshot shape | I/O via the client only |
| `github/types`, `github/telemetry` | The `GithubClient` contract (22 members) every console implements over its own fetch, `RepoRef`, `GithubError`; ETag-polled run telemetry | yes |

Not in it, on purpose: a fetch client (each consumer brings its own: a browser client, an editor client over VS Code's fetch and SecretStorage, a fixture client for demos), and the blueprint → lanes direction, which belongs to GitFactory's compiler.

## Where it came from

Lifted verbatim from GitFactory (`bamr87/gitorio` `app/src/{fleet,harness,github}`) at the commit named in `VERSION`, with two seams cut so it stands alone; GitFactory switches to consuming this package next (its backlog item), and the copy there is retired, never edited. The tests came with the code: 230+ cases over 39 real-fleet workflow fixtures and the hub's own committed signal files.

## Developing

```bash
cd templates/fleet-engines
npm install --no-package-lock     # always-latest: floors, no lockfile
npm test                          # vitest, node environment
npm run typecheck
npm run build                     # dist/ (ESM + d.ts); prepack runs it for publish
```

`fleet-engines-contract.yml` runs the tests, the typecheck and the build on every change here; `publish-kits.yml` builds, packs and publishes on a version bump. Bump `version` in `package.json` **and** `VERSION` together.

# templates/verify — agent verification kit

> The fleet standard for proving a feature, change, or fix works **the way a user experiences it**: a feature index every agent reads for context, declarative user scenarios both a Playwright runner and an AI agent execute, evidence bundles (screenshots + metrics + explanation) linked back to the feature, and a CI caller that runs it all — with an optional Claude Code pass that drives the live app through the Playwright MCP. Spec: [`specs/QUALITY.md`](../../specs/QUALITY.md) "Verification" (UPS-QA-50..53). Operator doc: [`docs/VERIFICATION.md`](../../docs/VERIFICATION.md).

| Template | Seeds | Purpose |
| --- | --- | --- |
| `features.template.yml` | `features/features.yml` (only when absent) | The feature index, `features/v1` — a strict superset of the shape zer0-mistakes, it-journey, and barodybroject already use. Per feature: id, surface, route, docs, tests, scenarios, evidence, screenshots, provenance, `verified:` stamp. |
| `verify.template.yml` | `verify/verify.yml` | How to run the app like a user: build/start command, base URL, readiness path, viewports, where scenarios and evidence live, what the agent must never do. |
| `scenario.template.yml` | `verify/scenarios/smoke-home.yml` | A `scenario/v1` user path: `goto` / `click` / `fill` / `press` / `select` / `hover` / `wait` / `expect` / `screenshot` / `eval`, executed once per viewport. |
| `runner.mjs` | `verify/runner.mjs` | Dependency-light Playwright executor (`@playwright/test` + `yaml`): runs scenarios → `test/evidence/<id>/` (screenshots, `report.json`, README scaffold) + aggregate report; `--stamp` writes `verified:` into the index with comments preserved. |
| `mcp.json` | `verify/mcp.json` | The Playwright MCP server the verification agent drives the app with (CI passes `--mcp-config verify/mcp.json`; locally `claude --mcp-config verify/mcp.json`). |
| `verify.yml` | `.github/workflows/verify.yml` | Thin caller of the hub's reusable [`fleet-verify.yml`](../../.github/workflows/fleet-verify.yml): index validation + scenarios on every PR; the agent pass on `verify`-labelled PRs or dispatch. Advisory until `gate: true`. |
| `SKILL.template.md` | `.claude/skills/verify-feature/SKILL.md` | The repo-local skill: scope from the index → start the app → run existing scenarios → drive it via the MCP → write a scenario → write the evidence README → link back + stamp → report honestly. |
| `verifier.template.md` | `.claude/agents/verifier.md` | The acceptance-tester subagent persona that follows the skill and never claims what it did not observe. |
| `EVIDENCE-README.template.md` | (reference) | The shape of a `test/evidence/<slug>/README.md`. |
| `VERSION` | — | Kit provenance + changelog. |

## Seed it

```bash
tools/fanout.sh --kit verify --target <name>            # dry run: branch + diffstat
tools/fanout.sh --kit verify --target <name> --apply    # push + PR (test/agent-verification)
tools/dash verify deploy --target <name> [--apply]      # same, via the CLI
```

Additive-only: a repo that already has `features/features.yml`, `verify/`, or a `verify.yml` workflow keeps its own. The `.claude/` artifacts are dedicated kit artifacts (the agent-context 0.4.0 exception), seeded only when absent.

## After seeding (per repo, by hand or by the agent)

1. Fill `verify/verify.yml` `app:` for the stack (examples in the file).
2. `npm i -D @playwright/test yaml && npx playwright install --with-deps chromium`.
3. Replace the `TODO-001` entry in `features/features.yml` with real features (the hub's `tools/features_index.py check .` validates; `coverage .` shows gaps).
4. `node verify/runner.mjs` — the smoke scenario should pass; open the PNGs.
5. Add the `verify` and `skip-evidence` labels (`gh label create`).

## What the hub does with it

`tools/features_index.py fleet --write` aggregates every checked-out submodule's index into `_data/features_index.yml`, rendered at `/features/` on the dash — one listing of every feature in the fleet with its docs, tests, scenarios, evidence, screenshots, and verification stamp, plus per-repo coverage and the attention list of unverified UI features. `tools/conformance.py` grades UPS-QA-50..53 from the same files.

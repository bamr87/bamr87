# templates/verify — agent verification kit

> The fleet standard for proving a feature, change, or fix works **the way a user experiences it**: a feature index every agent reads for context, declarative user scenarios both a Playwright runner and an AI agent execute, evidence bundles (screenshots + metrics + explanation) linked back to the feature, and a CI caller that runs it all — with an optional Claude Code pass that drives the live app through the Playwright MCP. Spec: [`specs/QUALITY.md`](../../specs/QUALITY.md) "Verification" (UPS-QA-50..53). Operator doc: [`docs/VERIFICATION.md`](../../docs/VERIFICATION.md).

| Template | Seeds | Purpose |
| --- | --- | --- |
| `features.template.yml` | `features/features.yml` (only when absent) | The feature index, `features/v1` — a strict superset of the shape zer0-mistakes, it-journey, and barodybroject already use. Per feature: id, surface, route, docs, tests, scenarios, evidence, screenshots, provenance, `verified:` stamp. |
| `verify.template.yml` | `verify/verify.yml` | How to run the app like a user: build/start command, base URL, readiness path, viewports, where scenarios and evidence live, what the agent must never do. |
| `scenario.template.yml` | `verify/scenarios/smoke-home.yml` | A `scenario/v1` user path: `goto` / `click` / `fill` / `press` / `select` / `hover` / `wait` / `expect` / `screenshot` / `eval`, executed once per viewport. |
| `runner.mjs` | `verify/runner.mjs` | Dependency-light Playwright executor (`@playwright/test` + `yaml`): runs scenarios → `test/evidence/<id>/` (screenshots, `report.json`, README scaffold) + aggregate report; `--stamp` writes `verified:` into the index with comments preserved. |
| `mcp.json` | `verify/mcp.json` | The Playwright MCP server the verification agent drives the app with (CI passes `--mcp-config verify/mcp.json`; locally `claude --mcp-config verify/mcp.json`). |
| `verify.yml` | `.github/workflows/verify.yml` | Thin caller of the hub's reusable [`fleet-verify.yml`](../../.github/workflows/fleet-verify.yml): index validation + scenarios on every PR commit; the agent pass on `verify`-labelled PRs or dispatch. Other labels and pushes to the default branch do not run it ([Triggers](#triggers)). Advisory until `gate: true`. |
| `SKILL.template.md` | `.claude/skills/verify-feature/SKILL.md` | The repo-local skill: scope from the index → start the app → run existing scenarios → drive it via the MCP → write a scenario → write the evidence README → link back + stamp → report honestly. |
| `verifier.template.md` | `.claude/agents/verifier.md` | The acceptance-tester subagent persona that follows the skill and never claims what it did not observe. |
| `EVIDENCE-README.template.md` | (reference) | The shape of a `test/evidence/<slug>/README.md`. |
| `VERSION` | — | Kit provenance + changelog. |
| `archive/` | — | The shapes earlier kit versions seeded (`verify-0.1.0.yml`, `verify.template-0.1.0.yml`, `runner-0.1.0.mjs`), so `--upgrade` can tell an untouched seed from a hand-edited copy. Snapshot the outgoing shape here before editing `verify.yml`, `verify.template.yml` or `runner.mjs`, or bumping `VERSION`. |

## Seed it

```bash
tools/fanout.sh --kit verify --target <name>            # dry run: branch + diffstat
tools/fanout.sh --kit verify --target <name> --apply    # push + PR (test/agent-verification)
tools/dash verify deploy --target <name> [--apply]      # same, via the CLI
```

Additive-only: a repo that already has `features/features.yml`, `verify/`, or a `verify.yml` workflow keeps its own. The `.claude/` artifacts are dedicated kit artifacts (the agent-context 0.4.0 exception), seeded only when absent.

`--upgrade` refreshes `.github/workflows/verify.yml`, `verify/verify.yml` and `verify/runner.mjs` only where the copy is byte-identical to a shape in `archive/`, which proves nobody edited it. A hand-edited copy is reported and left alone. Since 0.2.0 that is the way to move a repo onto the new triggers: `tools/fanout.sh --kit verify --target <name> --upgrade` (dry run), then `--apply`.

## Triggers

The caller runs the pass when a pull request is opened, pushed to or reopened, when the `verify` label is added (which also starts the agent pass and supersedes the run in flight), and on dispatch. It does not run for:

- **Any other label.** Bots label a pull request in bursts as they open it, and up to 0.1.0 each label started a full pass that cancelled the one before it: three runs per Dependabot PR, five per content-agent PR. A non-`verify` label run now takes a concurrency group of its own and its job skips, at zero minutes. The group and the job `if:` go together. With the `if:` alone, the label run still takes the shared group and can cancel the real run before it skips.
- **A push to the default branch.** In the 2026-11 sample, 151 of 155 such pushes were the merge of a pull request whose commits had just been verified. Dispatch the workflow to verify the default branch on demand.

These are the triggers of the hub's own [`verify.yml`](../../.github/workflows/verify.yml). The measurements behind them are in `VERSION`.

## After seeding (per repo, by hand or by the agent)

1. Fill `verify/verify.yml` `app:` for the stack (examples in the file).
2. `npm i -D @playwright/test yaml && npx playwright install --with-deps chromium`.
3. Replace the `TODO-001` entry in `features/features.yml` with real features (the hub's `tools/features_index.py check .` validates; `coverage .` shows gaps).
4. `node verify/runner.mjs` — the smoke scenario should pass; open the PNGs.
5. Add the `verify` and `skip-evidence` labels (`gh label create`).

## What the hub does with it

`tools/features_index.py fleet --write` aggregates every checked-out submodule's index into `_data/features_index.yml`, rendered at `/features/` on the dash — one listing of every feature in the fleet with its docs, tests, scenarios, evidence, screenshots, and verification stamp, plus per-repo coverage and the attention list of unverified UI features. `tools/conformance.py` grades UPS-QA-50..53 from the same files.

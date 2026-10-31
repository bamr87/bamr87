# ADR 0002 — Agent step specs and the local loop runner

- **Status**: proposed
- **Date**: 2026-10-30
- **Deciders**: proposed by an agent for bamr87/bamr87#485; the maintainer accepts or rejects it in that PR's review
- **Related**: epic bamr87/bamr87#484, P0 bamr87/bamr87#485, the motivating incident bamr87/bamr87#89, constitution § 10.8 (PR #480), § 12.3 (PR #481), § 13 (PR #482), § 15 (PR #491), [`docs/JEV.md`](../JEV.md)

## Context

### Needs assessment

**Who needs what.** The maintainer wants every fleet loop to run locally with Claude Code agents using JEV's optimizations, and #484 (epic) and #485 (P0) record this. A local run is only worth having if it does exactly what CI does: the same hard-rules prompt, tool allowlist, model, turn and dollar caps, and workspace contract. Today the CI copy is the only copy. P1 (the JEV loop engine) needs one machine-readable source to render from. The console, the TUI and the fleet MCP need that same source to describe and later drive the loop. The § 13 tracing and eval work needs to pin a run to the exact text and model it used.

**Evidence from the hub:**

- Agent prompts live only inside workflow YAML. There are 7 inline `prompt: |` blocks across 5 workflows that call `anthropics/claude-code-action@v1`: fleet-pulse, issue-pipeline (×3), fleet-verify, repo-scout, repo-evolution. Two more take an expression: fanout.yml's `agent-fill` builds its hard-rules brief in a shell heredoc (`steps.brief.outputs.prompt`), and ai-lane.yml passes the caller's `inputs.prompt`. No workflow reads a prompt from a committed file. repo-scout's hard rules were at `repo-scout.yml:277-338` at `cb8c077`.
- The console can plan scout but cannot run its agent. `LOOPS` maps `repo_scout` → workflow `repo-scout` (`tools/console/core.py:202-204`). Its only local op is `scout` = `dash-gen scout --offline` (`core.py:1200`). Every agent step is reachable only through `DISPATCH_WORKFLOWS` (`core.py:103`), which means GitHub runs it.
- The one local headless wrapper, `dash ai run` (`ai_activity.run_headless`), takes its cap from `budget.local_usd` ($5), not the call site's cap (`repo-scout.yml:scout` = $8). Prompt, tools and model pass through untouched, so a hand-run local scout would be capped differently from CI.
- Scout's caps already exist in up to five places, held together only by hand-written tests: `--max-turns 40` = `scout.max_turns`, `--max-budget-usd 8` = `budget.call_sites`, and `claude-cost budget-usd` (`test_scout.py:222-283` at `cb8c077`, `test_ai_budget.py`). `harness_registry` records scout's model as `null` because `MODEL_RX` cannot read `${{ needs.plan.outputs.model }}`.
- When a prompt and its allowlist are written in two places, they drift, silently and at a cost. In bamr87/bamr87#89 the prompt's first order is to Read a file, but the compiled `--allowedTools` grants no Read. The result was 12 of 26 turns denied, `error_max_turns`, and $0.55 API-equivalent (estimate) on every scheduled run. Scout's prompt names both Read and Write, so it carries the same exposure.
- § 13.3 (ratified, PR #482) requires exact model ids from `_data/fleet.yml` `ai_models.allowed` (claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5). Scout runs on `scout.model: sonnet` with the fallback `// "sonnet"`. A step format that copies today's values would carry the alias into the new format.
- The brief templates (`.github/scout/`, `.github/evolution/`) already split tunable material from hard rules using `{{UPPER_SNAKE}}` tokens. But `evolution.render_template` (`evolution.py:401-404`) chains `str.replace` calls. That makes it multi-pass: a GitHub-synced `DESCRIPTION` containing a later token gets expanded. It also leaves unknown tokens in place silently and never reports missing values. It cannot carry hard rules safely.

**Why now.** Every later phase builds on the format this P0 fixes, and changing it after P1 ships would touch every consumer:

- P1: the local runner.
- P2: the console "run locally" surface.
- P3: the doctor, evolve and issue-pipeline step specs.
- P4: CI executing through the runner.
- P5: local schedules.

§ 10.8 (ratified, PR #480) requires this record before any of that code exists. #466 (kaizen) is waiting to be born as a spec rather than inline.

### The § 13 no-op claim, as far as the repo can show it

The only repo-side mapping is `ai_activity.MODEL_ALIASES` (`ai_activity.py:110-112`: `"sonnet": "claude-sonnet-5-5"`). That is the hub's cost-accounting normalization, not the CLI's alias resolution. `docs/AI-INTEGRATION.md` does not mention a sonnet alias.

External evidence settles it for first-party auth. Scheduled run 41169651906 passed `--model sonnet` and logged `system/init "model": "claude-sonnet-5-5"`, with `modelUsage` provider `firstParty`. The Claude Code model-config docs map `sonnet` to Sonnet 5.5 on the Anthropic API, but to Sonnet 4.5/4.6 on Bedrock, Vertex and Foundry.

So pinning `claude-sonnet-5-5` is a no-op for the fleet's `oauth,api_key` auth order, and it removes a latent difference on third-party providers. The pin covers the main loop only. The same run made one `claude-haiku-5-5` side call ($0.0002 API-equivalent (estimate)), so the ledger must sum `modelUsage` across models.

## Decision

**Build the format, adopt everything around it.** No candidate holds prompt, allowlist, caps, inputs, workspace contract and risk in one file that both a GitHub-hosted action and a local `claude -p` can render byte-identically. JEV capability two therefore adds a small stdlib+PyYAML spec format and loader under `tools/jev/` (`tools/jev/spec.py`, specs at `tools/jev/steps/<loop>/<step>.yml` + `<step>.prompt.txt`), with `python3 -m tools.jev steps check|render`.

### Adopted as is

- `anthropics/claude-code-action@v1` stays the CI executor in P0. The spec renders its `prompt` and its `claude_args` stays literal, so the workflow diff is the prompt source only.
- The `{{UPPER_SNAKE}}` token syntax and names from the brief templates (`REPO_NAME`, `NWO`, `BRANCH`, plus `BRIEF`).
- The tunable/hard-rules split. The briefs stay in `.github/scout/` as inputs, and the spec is the hard-rules half.
- JEV house style: header docstring, no import side effects, a `python3 -m tools.jev` subcommand, and a plain-python test runner.
- `fleet.yml` as the single home of values that already live there.
- The console's `LOOPS.workflow` field as the join key.
- `claude -p --output-format json` as P1's local executor (recorded here, built in P1).

### Extended

- `dash ai run` / `run_headless`: in P1 it takes its cap from the spec's `call_site` via `budget.call_sites` instead of `local_usd`, and it gains the stream, timeout, repo and result-file changes listed in #486.
- JEV's `claude_argv` shape: it gains `--allowedTools` rendered from the spec.
- JEV's charge-at-cap and `cost_source` rules apply to loop runs.
- The existing `test_scout` contract checks are repointed at the spec rather than duplicated.
- The `harness_registry` cap regexes `MAX_TURNS_RX` and `MAX_BUDGET_RX` are inlined into `spec.py`, citing `harness_registry.py:87,91-92`, so `tools/jev` never imports dash-gen.

### Spec format decisions

- **Placement:** under `tools/jev/steps/`, beside JEV capability one, so the local engine (P1) and the specs share a home with no dash-gen dependency.
- **Prompt file:** `.prompt.txt`, not `.md`, because markdown-oneline would reflow a `.md` prompt (60 → 28 lines) and push the reflow with `GITHUB_TOKEN`, where it could merge green. `.gitattributes` pins `eol=lf`, and the loader refuses trailing whitespace or more than one final LF, because pre-commit's whitespace hooks do touch `.txt`.
- **References, not copies** (AGENTS.md central configuration): `model_from: scout.model`, `max_turns_from: scout.max_turns`, `call_site: repo-scout.yml:scout` (→ `budget.call_sites`). The spec carries no literal model, turns or budget.
- **Literals** only for what has no other home: `prompt`, `inputs`, `allowed_tools`, `timeout_minutes`, `workspace`, `risk`.
- **Placeholders:** caller-filled `{{UPPER_SNAKE}}`, rendered in a single pass by `re.sub` with a callback that refuses unknown tokens, unfilled declared inputs and undeclared inputs. A value is never re-scanned, which closes the `DESCRIPTION` expansion hole in `render_template`.
- **Caps stay literal in the workflow's `claude_args`,** so `harness_registry`, the workflow atlas and `test_ai_budget` keep reading them unchanged. `parity_errors` resolves the references and holds every workflow literal equal to the resolved values: `--max-turns`, `--max-budget-usd`, `claude-cost budget-usd`, `timeout-minutes`, `--allowedTools`, the download/upload paths, and the absence of a GitHub token in the agent step's effective env (workflow, job and step), its `github_token` input and any earlier `$GITHUB_ENV` export. What the action does outside that env — it exports its OIDC App token to Claude's subprocesses, and without `--setting-sources` it loads the checkout's `.claude/` settings and hooks — is a gap parity reports: the spec declares each open gap under `workspace.exceptions` with its reason, and `steps check` fails on an undeclared gap or a stale exception. It adds the #89 lint: every tool the prompt orders by name ("with the Read tool") must be in `allowed_tools`.
- **Content-hash pin:** the agent step carries `env: JEV_STEP_SHA256: <sha256 of <step>.yml, a NUL, <step>.prompt.txt>`, a runtime no-op that parity requires to equal the spec pair. It follows the literal-plus-parity pattern of the caps, and it means any edit to the hard rules also edits the workflow file (see the governance trade-off).
- **Exact model ids:** the resolved model must appear in `ai_models.allowed` (any provider list), and the loader and parity refuse an alias. Scout is pinned to `claude-sonnet-5-5` in `fleet.yml` `scout.model` and in the `repo-scout.yml` fallback, with `repo_scout.DEFAULTS` and its tests updated to match.
- **Optional `risk:`** (§ 13.6): per action, tags from {reversible, external, money} and a tier low|medium|high, where irreversible, external or money starts high. For scout:
  - the agent step (a run-to-verify, code-executing allowlist plus Write of `.scout/proposals.json`) is external, high: it runs the target repo's interpreters, package managers and `make` with network egress over untrusted repo and issue text, and the action's App token reaches it, so it meets the § 13.8 trifecta (private data, untrusted content, an external send) with the send ungated;
  - the publish action (`dash-gen scout-file --apply`, files issues) is external, high.
  - Both tiers are declared, not enforced: CI reads neither today, and the scheduled file job runs `--apply` without a human yes, gated only by `REPO_SCOUT_ENABLED`. The tier lint (HUB-049) and P2's confirm gate are where they start to bind.
- **Optional `evals:`** (§ 13.1): a path to the eval set, or `null` during the grace period. Its shape is validated when present.
- **Versioning:** `loop-step/v1` evolves the way `harness-registry/v1` does (AGENTS.md, consumed interfaces): an optional key added together with its loader support keeps v1; removing or renaming a key, making an optional key required, or changing a key's meaning bumps to `loop-step/v2`. The strict refusal of an unknown key is deliberate — the Rejected list faults `.claude/agents` for silently ignoring unknown fields — and every consumer reads specs through `tools/jev/spec.py`.

### Loop key mapping

The spec directory is the workflow stem (`repo-scout`), matching wtd's "lane id = workflow stem". The console `LOOPS` id `repo_scout` and the schedule key join through `LOOPS[...]["workflow"]`. Neither side is renamed.

### Rejected

- **`claude-run/run.sh` as the runner:** `acceptEdits` auto-approves edits outside the allowlist, it resolves the model consumer-side, it needs Ruby, and it hands a 429 to the API key (#348). P1 ports only its per-attempt `env -u` credential isolation, its exit contract and its stubbed-`claude` test pattern.
- **`.claude/agents` frontmatter or `--agents` JSON:** no caps, inputs or references, it silently ignores unknown fields, and it replaces the system prompt, which breaks byte parity. P1 may generate one from `steps render` later; the direction is spec → artifact, never the reverse.
- **Copilot-format prompts, Dotprompt, LangSmith:** no agent-loop semantics, extra dependencies, or the prompt leaves the repo.
- **Agent SDK as P1's executor:** a dependency for no parity gain. Held in reserve for `can_use_tool` gating of high-risk actions.
- **gh-aw, act, self-hosted runner:** none runs locally and faithfully.
- **Waiting for a platform prompt-file standard:** the one GitHub-native standard (`.prompt.yml`) was retired.

### Governance trade-off

Moving the hard rules out of `.github/workflows/` into `tools/jev/steps/` would remove GitHub's `workflow`-scope barrier from them. The identities that barrier stops are the ones GitHub refuses on `.github/workflows/*`:

- `GITHUB_TOKEN` pushers: the `github.token` fallback of `resolve-fleet-token` (issue-pipeline, fleet-pulse), jev-conflicts' `FLEET_TOKEN || GITHUB_TOKEN`, and markdown-oneline's repair push.
- The Claude GitHub App installation token: `claude.yml`, and the token claude-code-action exports to every agent's subprocesses — the scout agent's included (Follow-ups).

`FLEET_TOKEN` is not among them: it already holds `workflows:write` on the repos the fixer opens PRs against, the hub included (`docs/AI-INTEGRATION.md`, `fleet.yml` `tokens:`), so an agent holding it could always edit the inline prompt. For it the maintainer's review is the only control, before this change and after it. This reverses the stated rule in `.github/scout/README.md`, so that sentence is rewritten in the same PR.

The control that restores the barrier is the content-hash pin. The Scout step carries `JEV_STEP_SHA256`, and `steps check` refuses a spec pair whose hash differs from it, so an edit to `scout.prompt.txt` or `scout.yml` is also an edit to `repo-scout.yml` — which `GITHUB_TOKEN` and the App token cannot push. Without the pin nothing would hold: `steps check` does not read the prompt's text, and the byte pins in `tools/test_jev_spec.py` and `test_scout.py` are re-pinned by the same PR, which makes a change visible but does not block it.

What is not a control, stated so the trade is accepted on the facts:

- `CODEOWNERS` names `@bamr87` for every path (`*`), `/tools/` and `/.github/workflows/` alike, and is not enforced: `main` has no branch protection and the `strict` ruleset is disabled. It becomes a control only if the maintainer turns on required code-owner review (§ 12.4). Agent PRs pushed with `FLEET_TOKEN` are authored as the owner anyway.
- An agent may merge a mergeable PR (§ 12.2) and never a gated one (§ 12.5). A change under `tools/jev/steps/**` is security-sensitive config under § 12.3, so it is gated; `tools/jev/steps/SCHEMA.md` and its README say so where agents read them. The § 12.4 `needs-amr` label does not exist yet (HUB-045), so today the effective control is that no workflow merges and the maintainer reviews every such PR.
- JEV's conflict classifier gives `tools/jev/steps/**` the kind `source`, not `workflow`, so with `jev.auto_tiers` beyond `tier0` a conflict in a prompt would be open to tiers 1 and 2. It is off today (`auto_tiers: [tier0]`), and § 12.3 gates a non-trivial resolution anyway; P1 makes step specs a tier-1-forbidden kind routed to tier 3.

The fallback, if the maintainer rejects the trade, is `.github/loops/`. It does not restore the barrier either — only `.github/workflows/*` carries it — so the content-hash pin is the one option that does.

The maintainer accepts or rejects this explicitly in the PR review.

### What P1-P5 build on this

- **P1** (`python3 -m tools.jev loop run`) renders the same spec into `claude -p` with the resolved model, turns and call-site cap and the rendered `--allowedTools`. It isolates settings with `--setting-sources`, `--strict-mcp-config` and `disableAllHooks` (never `--bare`), and picks one credential per `CLAUDE_AUTH_ORDER` with `env -u` for the rest. It sandboxes code-executing tools per § 13.8, writes a redacted stream-json trace and one ledger entry, and refuses non-allowed models.
- **P2** exposes the publish action as a `remote` op behind the existing confirm gate (high), so § 13.6 is enforced by code that already exists. The agent step becomes a console/MCP op at the tier its spec declares: high today, and lower only once P1's § 13.8 sandbox (no network, no credentials) lets a § 13.9-gated re-tier bring it down.
- **P3** gives doctor, evolve and the three issue-pipeline tiers their specs and appends their decisions here. Because v1 allows no literal model or turns, P3 first adds their `fleet.yml` homes: `remediation.model` and `remediation.max_turns: 240` (test_fleet_pulse_doctor keeps it ≥ `max_candidates` × 55), `issue_pipeline.tiers.<tier>.model` and `.max_turns` (250/400/400), `evolution.model`, and `verification.agent.model` repinned from `sonnet` — every model an exact id there (`opus` → `claude-opus-5-5`); changing the format instead is appended to this ADR. P3 also brings in `fleet-verify.yml:verify` and `fanout.yml:agent-fill` (which passes no `--model` today and needs one before parity can pass) or records why not. `claude.yml` (interactive, no hard-rules prompt) and `ai-lane.yml` (the prompt is the caller's input; its spec belongs to the caller) are out of scope. Any agent step added after P0 (e.g. kaizen #466) is born as a spec.
- **P4** first teaches the detectors (atlas, `harness_registry`, `ai_usage_collector`, `test_ai_budget`, `test_schedule`) the new step shape, then may move CI to `base-action` with `prompt_file` or to `loop run --ci`, keeping caps literal on that line.
- **P5** schedules local runs under its own budget ceiling in the `budget.jev` shape.

Every later phase that changes the format or the executor (the P1 runner, the P4 keep-or-convert decision) appends its decision to this ADR or supersedes it, and never records it only in a PR.

## Consequences

**Positive**

- One file pair holds scout's prompt and its grant, and a lint holds them together, so the #89 failure mode is caught before spend.
- CI and the coming local runner render the same bytes from the same spec, and the model, turns and dollar cap resolve from `_data/fleet.yml` for both.
- The model is an exact, allowed id, which § 13.3 requires and which removes the alias's provider-dependent meaning.

**Negative**

- The hard rules leave `.github/workflows/`; the `workflow`-scope barrier still covers them only through the `JEV_STEP_SHA256` pin, so every spec pair edit carries a matching workflow edit. For `FLEET_TOKEN` identities the maintainer's review stays the only control (see the governance trade-off).
- The CI agent step meets the § 13.8 trifecta today with an ungated send, and its spec declares the two action gaps (`app-token`, `setting-sources`) as known exceptions rather than claiming a credential-free step CI does not deliver.
- Scout's caps now have one more reader that must agree (the spec's resolved values), so a cap bump touches several files, though parity fails loudly until they agree.
- `dash-gen scout` (the plan job, `tools/dash scout plan` and the console `scout` op) now depends on the spec loading; a broken spec fails the plan before any spend.

**Follow-ups outside P0**

- claude-code-action's App token reaches Claude's subprocesses, contradicting the "NO GitHub token in this step's env" comment, and with no `--setting-sources` the action loads the scouted repo's `.claude/settings.json` (permissions and hooks). The spec declares both as `workspace.exceptions` (`app-token`, `setting-sources`). File a separate issue; the fix options are `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: '1'`, a read-only `github_token: ${{ github.token }}` (which needs a new `github_credential` posture, since `none` refuses any `github_token`), or base-action, plus `--setting-sources user`. Closing one makes its exception stale, and `steps check` then asks for its removal. P1 must not reproduce either.
- JEV's classifier treats `tools/jev/steps/**` as `source` (governance trade-off); P1 makes it a tier-1-forbidden kind, with a case in `tools/test_jev_classify.py`.
- JEV's tier-1/2 models are outside `ai_models.allowed`. That is a § 13.3 follow-up for the maintainer.
- `harness_registry` keeps recording scout's model as `null` until it resolves the model through the spec or the workflow passes a literal `--model`.
- Byte identity at the action boundary (JSON through the matrix) is verified on the first maintainer-dispatched run by comparing the action's logged prompt with `steps render`. Agents do not trigger that run.

## Alternatives considered

### In-repo candidates

- **ai-runner kit** (`claude-run/run.sh`, `ai-lane.yml`, `templates/ai-runner/` 0.2.0): Partial fit.
  - It standardises how a call is made (auth order, exit contract, `AI_REPO_ROOT` for local trees) but has no spec, so nothing keeps CI and local identical.
  - It hard-codes `--permission-mode acceptEdits` (`run.sh:143`), resolves the model from the target repo's `_data/ai.yml`, and needs Ruby.
  - No hub loop uses it; all 9 hub agent call sites use claude-code-action.
- **`dash ai run`** (`ai_activity.run_headless`, `:771-856`): Partial fit.
  - It covers the cost and ledger half (`result_record`, `budget_was_hit`, `usage_from_result`, `models_from_result`, `record_run`), and it refuses a passed-through `--max-budget-usd`.
  - It knows nothing about specs, and its cap is `local_usd` rather than the call site's.
- **JEV conflict engine** (`tools/jev/conflicts.py`): Strong precedent for house style.
  - It is one Python code path for local and CI, with a capped `claude_argv`, a free-first tier ladder, and a ledger with `cost_source` reported/estimated/no-spend.
  - It is not a spec: prompts are f-strings (`_prompt`, `:382-398`) and `claude_argv` passes no `--allowedTools`.
  - Its tier models (`claude-haiku-4-5-20251001`, `claude-sonnet-5`) are not in `ai_models.allowed`.
- **Brief templates** (`.github/scout/`, `.github/evolution/`): They set the `{{UPPER_SNAKE}}` syntax and token names (`REPO_NAME`, `NWO`, `BRANCH`) and the tunable/hard-rules split. They cannot carry hard rules: the render is multi-pass, never reports unknown or missing tokens, and the Markdown files are reflowed by the prose gates.
- **`.claude/agents`, skills and commands**: No fit to carry the spec.
  - They have no place for caps, inputs, workspace, risk or evals, and `model: inherit` conflicts with § 13.3.
  - Scout runs in the target repo's checkout, where hub agent files are not on the path.
  - Command `allowed-tools` is precedent for keeping an allowlist next to its prompt.
- **`.github/agents|instructions|prompts`** (Copilot-format reference templates): No fit. They are repo-agnostic by rule, have no allowlist or caps, use model aliases, and nothing renders them. Their README rule ("concrete paths belong in the invoking prompt") supports caller-filled inputs.
- **Harness Console OPS/LOOPS/JobManager and the fleet MCP**: The surface for P1 and P2, not the format.
  - `LOOPS.workflow` is the join key to the spec directory.
  - The `remote` op and its `confirm=true` gate are the runtime counterpart of a § 13.6 high-risk action.
- **GitFactory/gitorio** (`agent.claude` machine, blueprint compiler): The closest precedent, but it points the wrong way for P0.
  - It compiles to CI only, in TypeScript the hub cannot import, and it derives grants in code, which is how #89 happened.
  - Its lessons: "frontmatter is documentation; the compiled `claude_args` is what grants", an exact-id model list identical to `ai_models.allowed`, and belt mode (the agent writes JSON, a deterministic sink consumes it).
  - It is a future consumer of the spec.
- **wtd `fleet/v1` lane manifest** (`fleet.manifest.yml`): Not a step spec. It has no prompt, allowlist, caps or inputs, and the hub copy is stale (0 `repo-scout` lanes). It backs "lane id = workflow stem".
- **bamr87/bamr87#89**: The motivating incident, not a tool. It justifies one file holding prompt and grant together, plus a lint that checks the prompt against the grant.
- **Existing parity tests** (`test_scout.test_workflow_contract`, `test_ai_budget.py`, `harness_registry` cap regexes `:86-92`): Direct precedent for the parity half, but tied to one workflow rather than driven by a spec. Keep and repoint them; do not duplicate them.

### External candidates

- **`anthropics/claude-code-action@v1`** (agent mode): The right CI executor today; it passes the prompt verbatim to the SDK's `query()`.
  - It cannot run outside Actions: it needs `@actions/github` context, `GITHUB_ACTION_PATH`, an OIDC URL and `github.token`.
  - It has no spec, cap, ledger or tiers.
  - It exports its minted App token (contents/issues/PR write) into `GH_TOKEN`/`GITHUB_TOKEN` for Claude's subprocesses, and it loads the scouted repo's `.claude` hooks and `.mcp.json` (`settingSources` default user,project,local). See Consequences.
- **`claude-code-action/base-action@v1`** (mirror: claude-code-base-action, `v0.0.x` only): A better later CI executor.
  - It accepts `prompt_file` and mints no GitHub token.
  - It shares the SDK option parsing, so the parity rules carry over.
  - It still cannot run outside Actions, and it is not a format.
- **Claude Code headless CLI** (`claude -p`, 2.1.308 installed): The right local executor for P1.
  - It takes exactly the flags the spec renders, and `--output-format json` returns `total_cost_usd`, per-model `modelUsage`, `session_id` and `permission_denials`.
  - Gotcha: `--bare` never reads `CLAUDE_CODE_OAUTH_TOKEN`, which breaks oauth-first auth. Isolate with `--setting-sources`, `--strict-mcp-config` and `disableAllHooks` instead.
- **Claude Agent SDK** (Python/TS): The same loop, with a `can_use_tool` seam that could enforce risk tiers per call.
  - It adds a non-stdlib dependency to a stdlib+PyYAML hub, and the docs steer SDK products away from claude.ai login.
  - Its option names become the spec's vocabulary; the SDK itself is held in reserve.
- **Claude Code sandboxed Bash + `dontAsk`**: The right § 13.8 control for laptop runs of scout's code-executing allowlist (python3, node, npm, make). It is per-run `--settings` JSON. It does not cover Read/Write or MCP. P1 concern.
- **`anthropics/sandbox-runtime` (`srt`)**: Optional whole-process boundary. It is beta, not installed, and an npm dependency, so it becomes an opt-in runner flag at most.
- **Claude Code subagent definitions** (`--agent`, `--agents <json>`): Native, but there is no budget field, no caller inputs, no risk or evals, and no way to reference fleet.yml. The body replaces the system prompt, which breaks byte parity with today's user-turn prompt. Unknown fields are ignored silently.
- **GitHub Agentic Workflows** (`gh-aw` v1.0.1): The closest concept (safe-outputs ≈ scout's plan → scout → file split), but `run` and `trial` execute on GitHub. The Claude engine rejects subscription OAuth, and adopting it would hand workflow generation to a compiler outside the workflow-atlas rules.
- **GitHub Models `.prompt.yml`** (actions/ai-inference): Dead. The service was retired 2026-07-30 and gh-models is archived, and the format was single-shot with no agent concepts. Only the `{{var}}` and testData conventions survive as reference.
- **nektos/act** (v0.2.92): No. It ignores `timeout-minutes` and `permissions`, has no OIDC (so the action's token exchange fails), needs Docker, and runs whole workflows.
- **Self-hosted runner on the Mac**: No. GitHub advises against it for public repos; it is still dispatched by GitHub; and installing it breaks § 10's no-change-to-the-Mac rule.
- **Promptfoo**: Not a runner or format, but the best fit for the § 13.1 `evals:` slot. It can point `file://` at the same `.prompt.txt` and run it through the Agent SDK with the spec's caps. Its Nunjucks templating is a superset, so either pre-render with JEV or keep prompts free of `{%`.
- **Dotprompt** (google/dotprompt): Format only. It has no turn, budget or permission concepts; it needs a non-stdlib dependency; and Handlebars logic makes byte-exact rendering across runtimes harder. Its typed `inputs:` (missing or unknown fails) is borrowed.
- **LangSmith prompt hub**: No. Prompts would live in a SaaS store behind a key, so they are no longer reviewed in a PR. Only content-hash pinning is borrowed, for the § 13.5 trace.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none

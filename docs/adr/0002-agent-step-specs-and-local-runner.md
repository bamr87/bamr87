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

- **P1** (`python3 -m tools.jev loop run`) renders the same spec into `claude -p` with the resolved model, turns and call-site cap and the rendered `--allowedTools`. It isolates settings with `--setting-sources`, `--strict-mcp-config` and `disableAllHooks` (never `--bare`; amended in [P1](#p1--the-headless-executor-and-its--138-posture): `--restricted`, not `--setting-sources`), and picks one credential per `CLAUDE_AUTH_ORDER` with `env -u` for the rest. It sandboxes code-executing tools per § 13.8, writes a redacted stream-json trace and one ledger entry, and refuses non-allowed models.
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

- claude-code-action's App token reaches Claude's subprocesses, contradicting the "NO GitHub token in this step's env" comment, and with no `--setting-sources` the action loads the scouted repo's `.claude/settings.json` (permissions and hooks). The spec declares both as `workspace.exceptions` (`app-token`, `setting-sources`). File a separate issue; the fix options are `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: '1'`, a read-only `github_token: ${{ github.token }}` (which needs a new `github_credential` posture, since `none` refuses any `github_token`), or base-action, plus `--setting-sources user`. Closing one makes its exception stale, and `steps check` then asks for its removal. P1 must not reproduce either. (P1 found that on CLI 2.1.308 `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` also forces the permission mode to `default`, overriding `--permission-mode` and the settings' `defaultMode`; choosing that option in CI changes the step's permission posture too.)
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

## P1 — the headless executor and its § 13.8 posture

- **Status**: proposed, with the maintainer's decisions of 2026-10-31 for #486 (P1 of #484) recorded below
- **Date**: 2026-10-31
- **Scope**: the executor and the posture (PR-A, `feature/jev-headless-executor`); the $0 engine (PR-B, `feature/jev-loop-engine`, below); attempts, budget and publishing (PR-C) build on them and append here if they change them

### The executor

**Extended, not forked.** `dash ai run` (`dash-gen ai-run`, `ai_activity.run_headless`) is the one capped, streamed, ledgered headless executor, for a human and for the loop engine alike. It gains `--call-site` (the cap is `budget.call_sites[...]`, and `--max-budget-usd` may only lower it), `--stream`, `--timeout`, `--repo`, `--cwd`, `--prompt-file`, `--trace`, `--result-file` (readable by claude-cost's `log:`), `--outcome-file`, `--isolate`, `--auth-order`, `--usage-limit` and `--meta`. Without them it behaves as before, except for deliberate changes: a run with no result record is now ledgered at its cap, which is a correctness fix (below); the wrapper adds `--session-id <uuid>` unless the passthrough names a session; the passthrough also refuses `-p`, `--print`, `--output-format`, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, any `--permission-mode` or hidden `--inherit-permission-mode` of `bypassPermissions`, a `--settings` value whose `defaultMode` is `bypassPermissions`, an `--agents` value that gives an agent that `permissionMode`, a `--settings` or `--agents` value it cannot read (a relative path is read from `--cwd`, where claude reads it), and `--cloud`, `--remote` and `--teleport` (an attached cloud session enforces no cap from this invocation); the result file and the stdout echo are redacted like the trace; both output files are removed when ai-run starts; the row's `model` is never guessed from `modelUsage`; a claude killed by a signal exits 128+N; and every dollar figure printed is labelled API-equivalent (estimate). The refusal reads flags only: the user's and the project's settings files still load unless the passthrough carries `--restricted`, which `--isolate` does not add.

**The boundary points one way.** The new [`tools/jev/headless.py`](../../tools/jev/headless.py) holds the isolation argv, the `--settings` document, the agent environment, the credential choice, redaction, the streaming runner and the outcome classifier. dash-gen imports it lazily, with the hub root appended to `sys.path` (the way `repo_scout.step_spec()` imports `tools.jev.spec`), and `tools/jev` never imports dash-gen. The engine (PR-B) runs `tools/dash-gen ai-run` as a subprocess.

**One ledger row per invocation.** `record_run` and `merge_ledger` take an exclusive `flock` on `<ledger>.lock`, so concurrent attempts and a `dash ai` scan cannot drop each other's rows. `dash ai run` waits for it at most `--ledger-wait` seconds (30 by default), because it holds a cancel while it records: past that a stopped or hung writer costs the run its row, never the cancel, and the outcome file's `ledger_error` says so. `RUN_FIELDS` grows additively (`call_site`, `origin`, `run_id`, `attempt_id`, `loop`, `step`, `item`, `tier`, `model`, `outcome`, `cost_source`, `cap_usd`, `auth_method`, `cli_version`, `duration_s`) and `LEDGER_VERSION` stays 1. JEV's charge-at-cap rule now applies to `dash ai run` itself: a run whose session may have started, or that a wall clock or signal stopped, and that left no result is recorded at its cap as `estimated`; `no-spend` needs proof that the model was never reached — under stream-json, an exit before the init event the CLI prints ahead of any request; under json, which shows no init, the CLI's own argv refusal as the first stderr line. A CLI that is missing or cannot start writes an outcome file and no row. A signal that lands before claude is started cancels the run with no process and no row (`interrupted`, `no-spend`, exit 130); one that arrives once claude has exited does not change the run's outcome and is held until the row and both files are written (the CLI's version is read before the run, so no process starts in that window), and ai-run then exits 128+N. `dash ai` reports `billed_cost_usd` (reported rows) and `estimated_cost_usd` apart, so an estimate never reads as measured spend (HUB-032).

**The wall clock is SIGINT first.** The headless docs say SIGTERM leaves the turn unfinished and records no result, while SIGINT ends the turn; so a timeout sends SIGINT to claude's process group, SIGTERM 15 s later and SIGKILL 10 s after that, and kills what is left of the group. A SIGINT, SIGTERM, SIGHUP or SIGQUIT sent to ai-run, or any other asynchronous signal that would end it (USR1, USR2, ALRM, VTALRM, PROF, XCPU), starts the same ladder, so an outer backstop or a closed terminal still gets a result: claude runs in its own session, out of the terminal's reach, and only a signal ai-run cannot forward orphans it (bounded by its cap and turn limit): SIGKILL, which nothing can catch, a fault, or a Linux real-time signal. A tee that can no longer be written, as after a hangup, is dropped and the run goes on. Exit 124 for the wall clock; a forwarded signal (Ctrl-C, a console cancel) is the `interrupted` outcome, exit 130, and is read before the usage-limit and credential tests, because a turn aborted before its first response reports $0 and an empty `modelUsage`, the credential-rejected signature, for a request that was in flight.

### Amendment: `--restricted` instead of `--setting-sources`

The P1 bullet above planned to isolate settings with `--setting-sources`, `--strict-mcp-config` and `disableAllHooks`. P1 uses **`--restricted`** instead, because:

- the permissions docs say that under `-p` a repository's settings `env` block is applied, and that it survives even `--bare`. A target repo's `.claude/settings.json` with `env: {ANTHROPIC_BASE_URL: …}` would send the session, with its OAuth credential, to another host, and `disableAllHooks` does not cover `env`;
- `--setting-sources ''` parses on 2.1.308, but what an empty list means is undocumented, and a control whose meaning is undocumented cannot carry that risk;
- `--restricted` is documented to ignore the user, project and local settings files while managed policy and `--settings` still apply; it also confines the file tools to the working directories and removes the code-running tools unless `--tools` names them.

It is joined by `--safe-mode` (no CLAUDE.md or memory, skills, installed plugins or mods — a mod can approve calls under dontAsk — hooks, MCP or custom agents), `--tools` limited to the spec's tool families, each of which must be in `GRANTABLE_TOOLS` (Bash, Read, Write, Edit, NotebookEdit, Glob, Grep — an allowlist, because the CLI keeps adding tools such as Artifact, RemoteTrigger, PushNotification and SendUserFile that reach past the sandbox; the default `-p` toolset carries Task, Skill, SendMessage and ListAgents, which reach the user's other local sessions, ScheduleWakeup, Workflow, Edit, WebFetch and WebSearch), `--permission-mode dontAsk --permission-prompts none`, the spec's allowlist verbatim plus a deny list (`gh`, `git push|remote|config`, `curl`, `wget`, `ssh`, `scp`, `nc`, `open`, `osascript`, `security`, WebFetch, WebSearch), `--strict-mcp-config` with an empty config, `--disable-slash-commands`, `--no-session-persistence`, a `--session-id` the engine chose and a `--debug-file`. A generic local-runner note goes in with `--append-system-prompt`, so the byte-pinned spec prompt stays the CI prompt. `MIN_CLI` is 2.1.259, the first release that accepts `--permission-prompts`. `--bare` stays rejected: it never reads OAuth or the keychain.

### § 13.8 posture for local runs: both layers (maintainer decision 1)

1. **Session isolation**, the flags above.
2. **A mandatory, fail-closed Seatbelt sandbox for Bash and its children**, from the `--settings` document: `enabled`, `failIfUnavailable`, `allowUnsandboxedCommands: false`, `autoAllowBashIfSandboxed: false` (its default would approve any sandboxed command), `network.allowedDomains: []` with `strictAllowlist`, `permissions.blockReadsOutsideWorkingDirectories`, `disableAllHooks`, and `sandbox.credentials` denying every credential variable (`GH_TOKEN`, `GITHUB_TOKEN`, `FLEET_TOKEN`, `FLEET_WRITE_TOKEN`, `PROJECTS_TOKEN`, `NPM_TOKEN`, `RUBYGEMS_API_KEY`, both Claude credentials, `ANTHROPIC_AUTH_TOKEN`) and file (`~/.ssh`, `~/.aws`, `~/.config/gh`, `~/.netrc`, `~/.git-credentials`, `~/.npmrc`, `~/.docker`, `~/.kube`, `~/.gnupg`, `~/.claude`, `~/.claude.json` and the hub `.env`).
3. **An environment built from scratch** (`headless.agent_env`): PATH without hub or work-root entries, HOME (the keychain login needs it), the locale, offline git/npm/pip settings, `GIT_CONFIG_GLOBAL=/dev/null`, an empty `GH_CONFIG_DIR` and at most one Claude credential. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` is deliberately NOT set: on 2.1.308 it forces the permission mode to `default` whatever `--permission-mode` and the settings say, so the posture the probe proves (`dontAsk`) would not be the one the run has. The credential variables are kept from Bash by the sandbox's `credentials.envVars` deny list instead, and the reduced posture has no Bash. ai-run's own process keeps the caller's environment, because on the maintainer's Mac PyYAML imports only through PYTHONPATH.
4. **A workspace outside the hub tree and inside the home fence**: `~/.cache/jev/work/<run_id>/` (0700, `JEV_WORK_ROOT` overrides), so there is no CLAUDE.md walk-up into the hub and no nested clone for hub scanners; run records in the gitignored `.fleet/runs/` (PR-B).

CI's allowlist is kept verbatim locally (npm, pip, node, python3 and the rest stay): dropping package managers would change the scout without reducing arbitrary-code risk, so containment rests on the sandbox and the absence of network, and offline installs simply fail. No network domain is allowed in P1; any future one is a per-domain, § 12.3-gated decision recorded with its exfiltration trade-off. `--posture reduced` (no Bash at all, same isolation) is the explicit fallback for a host without Seatbelt or bubblewrap and is never scheduled.

**Proof before trust.** Three checks, each failing closed (exit 4, outputs discarded unread):

- the **$0 flag preflight** (`preflight_parse`): the real argv, which must carry `-p` and `--max-budget-usd`, with stdin `/dev/null` must answer "Input must be provided", which proves every flag parses, the hidden `--max-turns` included, on the installed CLI; nothing it prints or logs may report the `--settings` document skipped, because under `-p` a document that fails validation is skipped with nothing but a debug-log line. That check is negative (a debug log that was never written passes it): the positive `flagSettings` proof is the probe's, and which settings keys the CLI honours (unknown keys are dropped silently) only the canary proves;
- the **$0 self-calibrating isolation probe** (`probe_isolation`): both $0 checks run in `probe_env`, the run's own environment (`agent_env`) with no credential and a scratch `CLAUDE_CONFIG_DIR`, refused outright if that environment is logged in. The fixture plants a SessionStart hook, an `env` block, an output style, a `.mcp.json` server, a skill, a CLAUDE.md and an AGENTS.md. The control run must show the hook, the server, the output style and the skill, or the result is "detector stale". The isolated run must pass `init_problems` (exactly the spec's tool families, nothing never-grantable or outside `GRANTABLE_TOOLS`, `dontAsk`, no MCP server, no skill, the default output style), run no hook or server, apply no planted `env`, and log the `flagSettings` rules and "project memory is off". Memory content reaching the model and user-scope settings (the probe's config dir is a scratch one) have no $0 check: they rest on the documented `--restricted`, `--safe-mode` and `--strict-mcp-config` semantics and on the canary;
- a **per-run sandbox-engaged check** (PR-C) and a one-time **live canary** of at most $0.10 API-equivalent (estimate) per CLI version and posture template (`posture_template_sha`: the settings document, the isolation flags with the spec's toolset, the environment's key set and the posture's name, so changing any of them invalidates a cached pass), which proves enforcement (home and secret reads, network, writes outside the clone, symlinks, no token in the sandbox). The canary and the pilot are implemented, and run only with the maintainer's approval (§ 10.5); no agent runs them.

Sandbox enforcement under `-p` with `--restricted` and `--safe-mode` has not been observed yet — every probe so far ran without a credential — so until the canary passes, a sandbox-posture run refuses rather than running untrusted repo code unproven.

### Credentials (maintainer decision 5)

`CLAUDE_AUTH_ORDER` (else the hub's `ai_auth:` entry, else `oauth,api_key`). Within `oauth`: the env token, then the keychain login (`claude auth status`), then the hub `.env` value; within `api_key`: the env key, then `.env`. The `.env` is parsed for those two names only and never sourced. The first present credential is chosen once and the other is unset; nothing falls back in the run. A 429 is capacity: `usage_limit`, a warning, exit 0 under `--usage-limit skip` so the P2 console shows it as a warning and not red; the queue stops. A refused credential is `credential_rejected`, and a cancelled run is `interrupted`, never `credential_rejected`. Where a credential is chosen, the CLI's other auth inputs (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDE_CONFIG_DIR`, the provider switches) are removed too, so the run uses the credential that was checked. Neither is retried with the other method (#348's status quo; its decision stays with #348). The run records the method and source, never the value.

### Publishing (maintainer decision 3): `--apply` is the yes

This differs from the design's exact-bytes gate (a plan id typed back on a TTY). **A `loop run … --apply` typed by the maintainer is the § 13.6 "high waits for Amr's yes"**: the run still does its dry-run preview first — the exact issue bodies written to the run directory — and then files in the same run, with no typed-back plan id. The reasoning: the maintainer runs the command by hand, names the target, and can read the preview it writes; a second confirmation on the same terminal adds friction without adding a person. Review-then-file stays available: `loop publish <run_id> --apply` publishes a previous dry run's reviewed bytes, idempotently (`publish-result.json`), and refuses changed bytes or a second apply. The refusals that remain:

- `--apply` with `--scheduled` is refused: no unattended local filing until § 13.7 earned autonomy exists;
- the console and MCP stay unable to apply until the § 11 decision (#487); P1 adds nothing that lets them;
- `--apply` refuses a dirty spec or adapter unless `--allow-dirty`;
- before filing, a live recheck runs: backpressure, the publish token probed with `gh api user`, and per-issue failure detection the way CI's file job greps `gh issue create failed`.

Implemented in PR-C.

### Budget and budget hits (maintainer decisions 2 and 4)

`_data/fleet.yml` `budget.loops: {monthly_usd: 25, scheduled_stop_pct: 80}`, in the `budget.jev` shape, enforced through `tools.jev.ledger.BudgetState` over the AI ledger's `origin: local` rows that carry a `loop` field (a plain `dash ai run` row is `origin: local` too but has none, so hand runs never count against it), by UTC month; each attempt is still capped by `budget.call_sites` (scout $8), and `test_ai_budget` asserts `loops + jev ≤ harnesses.budget.monthly_ai_usd`. Every figure is labelled API-equivalent (estimate). A scout attempt that hits its budget is **discarded** locally (JEV's rule), a deliberate divergence from CI's file job, which files whatever a budget-hit leg left behind: a local rerun costs about $0.61, and the bytes a human reviews should come from a completed run. Implemented in PR-C.

### Recorded local-vs-CI differences

No network, so dependency installs fail and the runner note says not to propose from that; symlinks in the clone are plain files; the target's CLAUDE.md is not auto-loaded (the scout prompt reads it); the target's `.claude/` settings are never loaded, where CI's claude-code-action loads them; a budget hit discards the output.

### § 10.8, the alternatives for the executor

- **`--bare`**: rejected — it never reads OAuth or the keychain, and the docs say it will become the `-p` default; the preflight and `credential_rejected` would catch that change.
- **`claude-run/run.sh`**: only its per-attempt `env -u` credential isolation is ported (`with_one_credential`).
- **The Agent SDK**: deferred; held in reserve for per-call `can_use_tool` gating.
- **`anthropics/sandbox-runtime` and a devcontainer**: P5.
- **act and a self-hosted runner**: no, for the reasons above.

### Consequences of P1's executor

- **Positive**: one executor and one ledger shape for every local headless run; no local run is free in the books; the agent's environment holds no GitHub credential by construction, and the flags, the settings document loading, the toolset, the permission mode, project hooks, `env`, MCP, skills and memory-off each have a $0 check against the installed CLI (memory content, user-scope settings and sandbox enforcement rest on the canary).
- **Negative**: the detectors read the CLI's own output (init fields, debug-log wording, the preflight text), so a Claude Code update can turn the probe into "detector stale" until the maintainer re-runs it and the canary; local proposals can differ from CI's for the recorded reasons; the trace holds repository content and its redaction is pattern- and value-based, so it stays local and gitignored.
- **Outstanding**: `tools/jev/conflicts.py` `claude_argv` (tiers 1–2) still builds its own argv without this isolation; it is switched off by `jev.auto_tiers: [tier0]` and is ported onto `headless.py` (follow-up 1) before tier1 or tier2 is enabled.

### The engine, at $0 (PR-B)

`python3 -m tools.jev loop` (`tools/dash loop`) is [`tools/jev/loop.py`](../../tools/jev/loop.py) with [`workspace.py`](../../tools/jev/workspace.py) and [`adapters/`](../../tools/jev/adapters/README.md); the spec gains one optional key, `local:` (adapter, switch, planner, publish, on_budget_hit), which every P0 consumer ignores and `steps check` holds to the workflow's gating `if:`. This slice is `list`, `doctor` (no `--live`), `plan`, `run --rehearse` and `show`; a `run` without `--rehearse` refuses, so nothing in it can reach a model. Where it departs from the design, and why:

- **A rehearsal reports, a live attempt refuses.** A missing isolation probe, a missing canary and a missing credential are notes under `--rehearse` and refusals (exit 4, 4, 3) for a live attempt (PR-C); a failed probe, an old CLI, no sandbox and a failed flag preflight refuse either way. The canary cannot exist before PR-C, so requiring it would make the $0 slice unusable.
- **The planned executor command is proven at $0.** The rehearsal runs the exact `tools/dash-gen ai-run` command an attempt will run, as `ai-run --dry-run`, without its `--prompt-file` and on an empty stdin: ai-run's own parsing, passthrough refusals, call-site cap and credential choice are exercised, and even if `--dry-run` were ever ignored the CLI would answer "Input must be provided" before any request.
- **ai-run gets the chosen credential, the deterministic halves get none.** The planner and the filer run with the user's environment minus every Claude credential (their gh auth reads GitHub); ai-run runs with it minus every GitHub and Claude secret and the SSH agent, plus the one chosen Claude credential, and builds claude's own environment from scratch with `--isolate`.
- **The harvest refuses a hard link** as well as a symlink, a non-regular file, an oversize file and a real-path escape: a hard link to a file outside the clone passes every path check.
- **The gh and git guards are allowlists.** A denylist kept missing spellings the tools still run: gh finds the verb past a flag (`gh pr -R o/r merge`) and takes aliases (`gh secret remove`), pflag splits `-iXPUT` into `-i -X PUT`, and git runs an alias, an autocorrected typo, `send-pack`, a `:ref` refspec set through `-c` and config passed by `--config-env` or the environment. So `assert_no_admin` passes only the `gh <noun> <verb>` commands JEV issues, read from the argv's first two words (a flag there is refused), and fails closed on `gh api`: every call but a GET, or an inline GraphQL query that is no mutation, is refused (a REST POST can merge, transfer or move a ref; gh POSTs implicitly once a field is added), with shorthand bundles read as gh reads them and an unknown shorthand refused. `assert_safe_git` passes only the subcommands, global options and `-c` keys JEV uses (none that undoes the wrapper's own hook, fsmonitor and pager settings), refuses config injected through `env`, holds `clone`, `fetch`, `remote` and `git config` writes to the options and keys JEV uses (a second review planted a delete refspec through a clone's own `-c`, `remote add --mirror` and `include.path`), and on a push refuses a force, mirror, delete or prune flag in any spelling and any refspec but an explicit `<src>:<dst>`, so config that got in some other way is never followed. `jev conflicts`' own calls are unaffected. Both guard only the calls JEV makes itself: the planner and filer are dash-gen subprocesses, bounded instead by their argv templates, whose subcommands `spec.py` pins (`PLANNER_COMMANDS`, `PUBLISH_COMMANDS`) and which may not carry the apply flag or a prefix argparse would read as it.
- **The engine's git never reads an agent-touched `.git` configuration.** The design's tamper baseline (config, HEAD, info/exclude, hooks) left `commondir` and a gitfile planted in a submodule directory, each of which makes a later `git status` run an agent-defined filter on the host, outside the sandbox; `config.worktree` and `info/attributes` cannot define a filter on their own but widen what a config change does. So every engine git call on a clone runs against a copy of the fresh GIT_DIR held beside the clone — its config, hooks, index and attributes, sharing only the object store through `objects/info/alternates` — with no global or system config (a `.gitattributes` the agent writes could otherwise name a filter from the user's own `~/.gitconfig`), no attributes file and `--ignore-submodules=all`, and is refused when the baseline — now all of `.git` but its objects and index, plus the alternates files and any nested `.git` — has changed; a tampered clone is destroyed with no git run in it, even under `--keep-workspace`. A workspace is removed on any failure before it is handed back, a Ctrl-C included, and `workspace.brief_dir` must be a relative path inside the clone (the agent's TMPDIR is built from it). A target that commits the brief directory is refused (its file would be harvested as the agent's), a fork's upstream remote is removed, and `destroy` never chmods through a symlink.
- **The publish phases get their own bodies directories** (`{bodies_dir}`: `items/<dir>/bodies/` for the preview, `filed/` for the apply), and `scout-file --apply` never clears one, so filing cannot overwrite or renumber the bytes a person reviewed. **Item directories are keyed by the item, not the repo** (`workspace.item_dirname`: `<owner>__<repo>` for a repo key, else the key's safe characters plus 8 hex of its sha256), so P3's per-marker and per-issue items fit without a layout change. **A publish is matched to an attempt by the validated file's sha256**, so a later run that reused and filed an attempt's outputs marks it published.
- **Planner flags are passed as `--flag=value`**, so a free-text `--focus` that starts with `-` cannot read as an option.
- **Every refusal ends with its documented code and a closed record.** A work root inside the hub is host safety (exit 4) for `run` as for `doctor`, checked before anything is planned or any CLI runs, and the rehearsal's flag preflight runs in a throwaway directory under the work root, never in the hub tree. A step with no `local.switch` refuses `--scheduled` (AGENTS.md: every scheduled loop has a kill switch), and a default-on switch reads "not found" as unset only once the hub repository is shown readable. An item that fails after its clone is that item's failure (exit 1) and the run goes on; a malformed or missing `--plan-file` is a usage error; any other error ends the record `failed` before its traceback, so no run stays `running`.
- **`--json` puts only the run record on stdout**; the `run: <path>` line goes to stderr, so the console (P2) can parse stdout.
- **The sandbox posture requires macOS Seatbelt in P1** (`sandbox-exec`), as designed; Linux bubblewrap is a P4/P5 posture.

The budget block (`budget.loops`), the live attempt, the per-run sandbox-engaged check, `loop doctor --live`, the dry-run preview with `scout-file --bodies-dir` and the `--apply` gate recorded above are PR-C. `scout-file --bodies-dir` is new for the local runner and the runner uses the existing `scout-file --offline` as its $0 structural check; CI passes neither.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none

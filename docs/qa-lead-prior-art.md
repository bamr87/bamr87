# QA Lead: prior art and the build-vs-adopt decision

> Amendment 0008 ([`harness-prior-art-research`](amendments/0008-harness-prior-art-research.md), ratified in #480) requires a needs assessment, a survey of existing tools and a recorded build-vs-adopt decision before any new loop is built. This is that record for QA Lead, the completeness reviewer of constitution § 15.5 (issue #492; amendments 0010, 0011, 0012).

## Needs assessment

Constitution § 15 asks for a completeness review on every major (§ 15.1) or frontend (§ 15.3) pull request. QA Lead must:

1. Decide, with no model, whether a pull request is major (the `major` label or the § 15.1 interim heuristics) or frontend (the § 15.3 globs plus a repo's `verify/verify.yml` `frontend_paths:`), so a pull request that is neither costs nothing.
2. Grade four lines, each pass or gap: the tests are listed (§ 15.2); the body links a green CI run of the head commit (§ 15.2); a frontend change carries visual evidence at two or more viewports (§ 15.4, UPS-QA-52); the PR template's docs and feature index are complete (§ 15.7).
3. Request changes on any gap, and never approve or merge (§ 15.5, § 19.5).
4. Never review its own pull requests: the maintainer reviews in its place (§ 15.5).
5. Accept exactly one waiver, `skip-evidence` with a reason, as [VERIFICATION.md](VERIFICATION.md) defines it, and of the visual line only.
6. Comment only through the fleet's one PR commenter, `pr-review.yml` (§ 19.1), and run AI only on the asks, never on every push (§ 19.7).
7. Hold to an eval set of real past pull requests that runs in CI and fails on regression (§ 13.1).
8. Spend $0 of Actions on private repositories, use only `claude-opus-5-5`, `claude-sonnet-5-5` or `claude-haiku-5-5`, and sit behind a kill switch (§ 13.3, § 17, § 29).

## Survey

### In the hub

| Existing piece | What it does | Fit for QA Lead |
| --- | --- | --- |
| `pr-review.yml` + `pr_review.py` | The fleet's one PR commenter: the sticky CI-failure comment, inline findings, and posting other workflows' reviews from artifacts (§ 19) | **Adopt as the poster.** QA Lead leaves an artifact and `pr_review.qa_lead_of` posts the review. This keeps § 19.1 intact and runs the poster from the default branch. |
| `pr-ai-review.yml` + `pr_ai_review.py` | A capped, read-only AI review of a pull request marked ready; artifacts posted by `pr-review.yml` | **Adopt the pattern, not the job.** It is a code review, not a completeness checklist, and its verdict is advisory. QA Lead reuses its shape: a plan step, a fenced model, an artifact, posting from `pr-review.yml`. |
| `pr_ai_analysis.py` (§ 19.11) | One tool-less, one-turn Sonnet call per failed run, with validated, escaped output | **Adopt the call shape** for QA Lead's advisory read: no tools, one turn, a $1 cap, and the answer held to a JSON contract and escaped. |
| `.github/actions/claude-run`, `ai-lane.yml` | The fleet route to a model: exact model, turn cap, dollar cap, OAuth order | **Adopt.** The advisory read runs through `claude-run@v2` (harness standard). |
| `fleet-verify.yml`, `verify.yml`, `templates/verify/`, `verify/runner.mjs` | Run the app, drive user scenarios with Playwright, write `test/evidence/<slug>/` bundles at the `verify.yml` viewports | **Adopt as the evidence source.** QA Lead does not take screenshots. It checks that a bundle (or body images) covers two or more viewports, using the `<viewport>-<name>.png` naming the runner writes. |
| zer0-mistakes visual-evidence kit (`scripts/ci/visual_evidence_autogen.py`) | Generates before/after evidence and pixel baselines in that repo | **Adopt as an evidence producer.** It writes into the same `test/evidence/` layout QA Lead reads, so it needs no parallel implementation. |
| `issue-pipeline.yml` | Evidence bundles for issues, not pull requests | Not a fit. Different object, different gate. |
| `claude.yml` | The `@claude` mention handler | Not a fit. Human-triggered, with no checklist contract. |
| `fleet-pulse.yml` doctor | Daily fleet triage and fix PRs | Not a fit. Scheduled, fleet-wide, and opens PRs rather than reviewing them. |
| `tools/evals.py` | The § 13 eval runner with deterministic and model adapters | **Adopt.** `evals/qa-lead/` is a deterministic set run by `tools/test_evals.py` in `python-tests`. |

### Outside the fleet

| Tool | Kind | Fit |
| --- | --- | --- |
| Claude Code GitHub Action (`anthropics/claude-code-action`) | AI review and mention bot | The fleet already wraps Claude Code in `claude-run`. Used on its own, it posts with the job's token, which can approve, and that bypasses § 19.1. Its model would decide the verdict, which § 15.5 rules out ("a bot reviewer cannot waive a requirement"). |
| CodeRabbit, Qodo PR-Agent, GitHub Copilot code review | Hosted or self-hosted AI PR reviewers | Strong at code review, weak at a fixed checklist. They run vendor models outside the § 13.3 allowlist, post as their own app (outside § 19.1), and some need a paid seat or org install. Their findings are model output, so the verdict is not deterministic or testable against an eval set. |
| Danger (danger-js / danger-ruby) | Rules-as-code PR checks | The closest fit for the deterministic half. It would add a Node or Ruby runtime and its own commenting path for four rules that are about 150 lines of Python. It cannot read the fleet's `verify.yml` or `fleet.yml` without glue code, so the glue would be the product. |
| Task-list and PR-template checkers (for example `task-list-completed`, `pr-body-checker` style actions) | Checkbox and section linting | Too shallow. A ticked box is self-attestation. QA Lead must look at the diff (test files, `test/evidence/`) and resolve the linked CI run against the head commit. |
| Percy, Chromatic, Argos | Hosted visual regression | Produce visual evidence; they do not judge completeness. They are paid hosted services that would add a second evidence layout beside `test/evidence/`. A repo may still use one as its evidence producer. |
| reviewdog | Linter-to-review bridge | Posts findings; has no checklist. `pr-review.yml` already plays this role (§ 19.3). |

## Decision

**Build a thin QA Lead on adopted parts.** The checklist logic is small, fleet-specific and must be deterministic and eval-tested, and no surveyed tool provides that without a parallel commenting path or a vendor model making the verdict. So:

- **Build** only `.github/scripts/dash-gen/qa_lead.py`: the gate, the four lines and the event, as pure functions over a pull request's facts, plus the recorder for eval cases.
- **Adopt** `pr-review.yml` as the poster (§ 19.1), `claude-run@v2` as the model route, the `pr_ai_analysis` call shape for the advisory read, `test/evidence/` and the verify kit (and the zer0-mistakes kit) as the evidence producers, `skip-evidence` as the only waiver, and `tools/evals.py` for the eval set.
- **Reject** hosted AI reviewers and Danger for this role. Each would add a second commenting path, a model outside the allowlist or a runtime the hub does not need. Revisit if a tool appears that can read the fleet's own registries and post through `pr-review.yml`.

The decision stays vendor-neutral as 0008 asks: the verdict depends on no model, and the advisory read can move to any allowed model by changing `_data/fleet.yml` `qa_lead.model`.

## How it runs

`qa-lead.yml` runs on `pull_request` with a read-only token, gates and grades with no model, and on the asks (opened, reopened, ready for review, a label) lets one capped Sonnet call add advisory notes. When it finishes, `pr-review.yml` (from the default branch) recomputes the gate and the four lines from live GitHub, so a pull request that edits QA Lead cannot grade itself. It then posts one review per head commit and result: `REQUEST_CHANGES` on any gap, `COMMENT` otherwise. Once nothing is missing, it dismisses its own earlier request for changes. A pull request from QA Lead's own identity (`github-actions[bot]`) gets one comment saying the maintainer reviews it.

- Settings: `_data/fleet.yml` `qa_lead` (globs, heuristics, thresholds, identity, model, cap). Kill switch: `vars.QA_LEAD_ENABLED` (opt-in, `switches.loops` `hub/qa-lead`). The `major` label is created by the maintainer.
- Code and tests: `.github/scripts/dash-gen/qa_lead.py`, `test_qa_lead.py`. Eval set: `evals/qa-lead/cases.yml`.
- From a terminal: `python3 .github/scripts/dash-gen/qa_lead.py local --repo OWNER/NAME --pr N` prints the review it would post (read-only).
- Out of scope here: JEV as the second reviewer, the fan-out to fleet repos (a later `fanout.yml` kit PR, one repo per PR), and flipping § 15.7 from warn to fail.

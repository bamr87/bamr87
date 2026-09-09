import { describe, expect, it } from 'vitest';
import { classifyArchetype, classifyDashType, extractFacts } from './facts.js';
import type { ArchetypeSignals } from './facts.js';
import type { AiFacts } from './types.js';

// ── fixtures: verbatim real fleet workflows (see fixtures/README.md) ─────────
// The path passed to extractFacts is the file's real in-repo path — the repo
// prefix (zm--/lh--/ij--/cv--/hub--) exists only in the fixture filename.

import { readFileSync } from 'node:fs';
const fx = (name: string): string => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8');
const cvMarkdownOneline = fx('cv--markdown-oneline.yml');
const edgRefreshData = fx('edg--refresh-data.yml');
const hubStandardCi = fx('hub--standard-ci.yml');
const ijAgentAudit = fx('ij--agent-audit.yml');
const ijAgentPlanThenAct = fx('ij--agent-plan-then-act.yml');
const ijAgenticQuestReview = fx('ij--agentic-quest-review.yml');
const ijCmsDailyLoop = fx('ij--cms-daily-loop.yml');
const ijContentAutoMerge = fx('ij--content-auto-merge.yml');
const ijContentFactory = fx('ij--content-factory.yml');
const ijContentQuality = fx('ij--content-quality.yml');
const ijContentReview = fx('ij--content-review.yml');
const ijDependabotAutoMerge = fx('ij--dependabot-auto-merge.yml');
const ijFrontmatterValidation = fx('ij--frontmatter-validation.yml');
const ijIssueAutopilot = fx('ij--issue-autopilot.yml');
const ijLinkChecker = fx('ij--link-checker.yml');
const ijQuestFix = fx('ij--quest-fix.yml');
const ijQuestForge = fx('ij--quest-forge.yml');
const ijQuestIdeaIntake = fx('ij--quest-idea-intake.yml');
const ijQuestPerfection = fx('ij--quest-perfection.yml');
const ijQuestWalkthrough = fx('ij--quest-walkthrough.yml');
const ijSyncGhPages = fx('ij--sync-gh-pages.yml');
const lawEvolve = fx('law--evolve.yml');
const lawNightlyTests = fx('law--nightly-tests.yml');
const lhAiUsage = fx('lh--ai-usage.yml');
const lhAutoFix = fx('lh--auto-fix.yml');
const lhAutoMerge = fx('lh--auto-merge.yml');
const lhCi = fx('lh--ci.yml');
const lhContentFactory = fx('lh--content-factory.yml');
const lhIssueFactory = fx('lh--factory--issue-factory-2.yml');
const lhPipeline = fx('lh--pipeline.yml');
const lhThemeScout = fx('lh--theme-scout.yml');
const zmAutoMerge = fx('zm--auto-merge.yml');
const zmCi = fx('zm--ci.yml');
const zmCiSelfRepair = fx('zm--ci-self-repair.yml');
const zmClaude = fx('zm--claude.yml');
const zmIssueAutopilot = fx('zm--issue-autopilot.yml');
const zmRelease = fx('zm--release.yml');
const zmUiAudit = fx('zm--ui-audit.yml');

/** Extract with the fixture's real in-repo path (prefix stripped). */
function facts(file: string, text: string) {
  return extractFacts(`.github/workflows/${file}`, text);
}

// ── zer0-mistakes ─────────────────────────────────────────────────────────────

describe('extractFacts — zm ci.yml (tiered CI pipeline)', () => {
  const f = facts('ci.yml', zmCi);

  it('classifies as a ci-gate of dash type ci, with no AI', () => {
    expect(f.archetype).toBe('ci-gate');
    expect(f.dashType).toBe('ci');
    expect(f.ai.present).toBe(false);
  });

  it('reads structure: jobs, matrix, timeouts, composites, concurrency, permissions', () => {
    expect(f.jobCount).toBeGreaterThanOrEqual(5);
    expect(f.hasMatrix).toBe(true);
    expect(f.timeoutMinutes).toBe(30);
    expect(f.compositeLocals).toContain('./.github/actions/quality-checks');
    expect(f.concurrency.present).toBe(true);
    expect(f.concurrency.cancelInProgress).toBe('conditional');
    expect(f.permissions.declared).toBe(true);
    expect(f.permissions.topLevelRead).toBe(true);
  });
});

describe('extractFacts — zm claude.yml (@claude mention handler)', () => {
  const f = facts('claude.yml', zmClaude);

  it('classifies as the ai mention-handler', () => {
    expect(f.archetype).toBe('mention-handler');
    expect(f.dashType).toBe('ai');
    expect(f.guards).toContain('mention-phrase');
  });

  it('finds exactly the claude-code-action runner, wired oauth-first', () => {
    expect(f.ai.present).toBe(true);
    expect(f.ai.runners).toEqual(['claude-code-action']);
    expect(f.ai.authMode).toBe('oauth-first');
  });

  it('has no concurrency block', () => {
    expect(f.concurrency.present).toBe(false);
  });
});

describe('extractFacts — zm auto-merge.yml (label-gated native auto-merge)', () => {
  const f = facts('auto-merge.yml', zmAutoMerge);

  it('classifies as an auto-merge-bot despite mentioning release/evidence files', () => {
    expect(f.archetype).toBe('auto-merge-bot');
    expect(f.ai.present).toBe(false);
  });

  it('sees the merge sink, the pull_request_target trigger, and the label opt-in', () => {
    expect(f.sinks).toContain('merge');
    expect(f.triggers.map((t) => t.kind)).toContain('pull_request_target');
    expect(f.guards).toContain('label-opt-in');
  });
});

describe('extractFacts — zm issue-autopilot.yml', () => {
  const f = facts('issue-autopilot.yml', zmIssueAutopilot);

  it('classifies as the issue-autopilot with a serialized matrix', () => {
    expect(f.archetype).toBe('issue-autopilot');
    expect(f.hasMatrix).toBe(true);
  });

  it('collects all four lane kill switches', () => {
    expect(f.killSwitches).toContain('ISSUE_AUTOPILOT_ENABLED');
    expect(f.killSwitches).toContain('ISSUE_RESOLVE_ENABLED');
    expect(f.killSwitches.length).toBeGreaterThanOrEqual(4);
  });

  it('sees the claude-run composite (the naive-scan-invisible AI path)', () => {
    expect(f.ai.present).toBe(true);
    expect(f.ai.runners).toContain('claude-run');
  });
});

describe('extractFacts — zm ui-audit.yml (weekly sweep + agent review)', () => {
  const f = facts('ui-audit.yml', zmUiAudit);

  it('classifies as a nightly-audit with a sticky-marker issue upsert', () => {
    expect(f.archetype).toBe('nightly-audit');
    expect(f.guards).toContain('sticky-marker');
  });

  it('reads the claude CLI invocation: model, turn cap, api-key-only auth', () => {
    expect(f.ai.runners).toContain('claude-cli');
    expect(f.ai.models).toContain('claude-sonnet-4-6');
    expect(f.ai.maxTurns).toBe(40);
    expect(f.ai.authMode).toBe('api-key-only');
  });
});

describe('extractFacts — zm release.yml (release-please pipeline)', () => {
  const f = facts('release.yml', zmRelease);

  it('classifies as release with two branch-pinned reusable calls', () => {
    expect(f.archetype).toBe('release');
    expect(f.reusableCalls).toHaveLength(2);
    expect(f.reusableCalls).toContain('bamr87/.github/.github/workflows/release-please.yml@main');
    const calls = f.actions.filter((a) => a.action.includes('/.github/workflows/'));
    expect(calls).toHaveLength(2);
    for (const c of calls) expect(c.pin).toBe('branch');
  });
});

describe('extractFacts — zm ci-self-repair.yml', () => {
  const f = facts('ci-self-repair.yml', zmCiSelfRepair);

  it('classifies as self-repair off a workflow_run trigger', () => {
    expect(f.archetype).toBe('self-repair');
    expect(f.triggers.map((t) => t.kind)).toContain('workflow_run');
  });

  it('sees the retry budget and the fork fence', () => {
    expect(f.guards).toContain('attempt-limit');
    expect(f.guards).toContain('same-repo-only');
  });

  it('runs the claude CLI on the API key only', () => {
    expect(f.ai.runners).toContain('claude-cli');
    expect(f.ai.authMode).toBe('api-key-only');
  });
});

// ── lifehacker.dev ────────────────────────────────────────────────────────────

describe('extractFacts — lh pipeline.yml (tiered gate with embedded agents)', () => {
  const f = facts('pipeline.yml', lhPipeline);

  it('stays a ci-gate even though agents ride inside it', () => {
    expect(f.archetype).toBe('ci-gate');
    expect(f.ai.present).toBe(true);
  });

  it('sees the loop-breaker, the token chain, and conditional cancellation', () => {
    expect(f.guards).toContain('synchronize-skip');
    expect(f.tokenChain).toContain('FLEET_TOKEN');
    expect(f.concurrency.cancelInProgress).toBe('conditional');
  });
});

describe('extractFacts — lh ci.yml (thin standard-ci caller)', () => {
  const f = facts('ci.yml', lhCi);

  it('classifies as a standard-ci-caller of the hub reusable workflow', () => {
    expect(f.archetype).toBe('standard-ci-caller');
    expect(f.reusableCalls[0]).toContain('bamr87/bamr87/.github/workflows/standard-ci.yml');
  });
});

describe('extractFacts — lh content-factory.yml', () => {
  const f = facts('content-factory.yml', lhContentFactory);

  it('classifies as a content-factory (cron + agent + PR obligation)', () => {
    expect(f.archetype).toBe('content-factory');
    expect(f.hasMatrix).toBe(true);
    // The PR sink is declared only as a prompt obligation — no `gh pr create`.
    expect(f.sinks).toContain('pr');
  });

  it('is gated by its kill switch and names its agent role', () => {
    expect(f.killSwitches).toContain('CONTENT_FACTORY_ENABLED');
    expect(f.ai.agents).toContain('grow-lifehacker');
  });
});

describe('extractFacts — lh auto-fix.yml', () => {
  const f = facts('auto-fix.yml', lhAutoFix);

  it('classifies as self-repair with an attempt budget and a kill switch', () => {
    expect(f.archetype).toBe('self-repair');
    expect(f.guards).toContain('attempt-limit');
    expect(f.killSwitches).toContain('AUTO_FIX_ENABLED');
  });

  it('detects the run.sh universal AI runner', () => {
    expect(f.ai.runners).toContain('run-sh');
  });
});

describe('extractFacts — lh theme-scout.yml (upstream filer)', () => {
  const f = facts('theme-scout.yml', lhThemeScout);

  it('classifies as a cross-repo-filer targeting the theme repo', () => {
    expect(f.archetype).toBe('cross-repo-filer');
    expect(f.crossRepoTargets).toContain('bamr87/zer0-mistakes');
  });

  it('is kill-switched and exposes the plan/apply dispatch duality', () => {
    expect(f.killSwitches).toContain('THEME_SCOUT_ENABLED');
    expect(f.planApply).toBe(true);
  });
});

describe('extractFacts — lh factory--issue-factory-2.yml (GitFactory output)', () => {
  const f = facts('factory--issue-factory-2.yml', lhIssueFactory);

  it('classifies as a generated-line with blueprint provenance', () => {
    expect(f.archetype).toBe('generated-line');
    expect(f.generated).not.toBeNull();
    expect(f.generated?.blueprintPath).toBe('.factory/issue-factory.blueprint.json');
  });

  it('reads the compiled agent step: runner, model, auth, guards, gate', () => {
    expect(f.ai.runners).toContain('claude-code-action');
    expect(f.ai.models).toContain('claude-opus-4-8');
    expect(f.ai.authMode).toBe('oauth-first');
    expect(f.guards).toContain('rate-limiter');
    expect(f.killSwitches).toContain('ISSUE_FACTORY_ENABLED');
  });
});

describe('extractFacts — lh ai-usage.yml (ledger with a disabled cron)', () => {
  const f = facts('ai-usage.yml', lhAiUsage);

  it('classifies as a ledger gated by its kill switch', () => {
    expect(f.archetype).toBe('ledger');
    expect(f.killSwitches).toContain('AI_USAGE_ENABLED');
  });

  it('surfaces the commented-out schedule as a dormant cron', () => {
    expect(f.crons).toEqual([]);
    expect(f.dormantCrons.length).toBeGreaterThan(0);
    expect(f.dormantCrons).toContain('17 8 * * *');
  });
});

describe('extractFacts — lh auto-merge.yml (smuggle-guarded sweep)', () => {
  const f = facts('auto-merge.yml', lhAutoMerge);

  it('classifies as an auto-merge-bot with the diff re-classification guard', () => {
    expect(f.archetype).toBe('auto-merge-bot');
    expect(f.sinks).toContain('merge');
    expect(f.guards).toContain('smuggle-guard');
    expect(f.killSwitches).toContain('AUTO_MERGE_ENABLED');
  });
});

// ── it-journey ────────────────────────────────────────────────────────────────

describe('extractFacts — ij content-factory.yml (sha-pinned)', () => {
  const f = facts('content-factory.yml', ijContentFactory);

  it('classifies as a content-factory with sha-pinned actions', () => {
    expect(f.archetype).toBe('content-factory');
    expect(f.killSwitches).toContain('CONTENT_FACTORY_ENABLED');
    expect(f.actions.some((a) => a.pin === 'sha')).toBe(true);
  });
});

describe('extractFacts — ij dependabot-auto-merge.yml', () => {
  const f = facts('dependabot-auto-merge.yml', ijDependabotAutoMerge);

  it('classifies as a dependency-bot guarded on the actor', () => {
    expect(f.archetype).toBe('dependency-bot');
    expect(f.guards).toContain('actor-guard');
    expect(f.sinks).toContain('merge');
  });

  it('extracts the elevated-token fallback chain', () => {
    expect(f.tokenChain.length).toBeGreaterThanOrEqual(2);
    expect(f.tokenChain).toContain('AUTO_PR_GITHUB_TOKEN');
  });
});

// ── it-journey: the agentic-engine cost center (the #1 fleet consumer) ─────────

describe('extractFacts — ij agentic-quest-review.yml (agentic engine, no claude-run)', () => {
  const f = facts('agentic-quest-review.yml', ijAgenticQuestReview);

  it('detects the agentic engine even with NO claude-run step, so ai.present is true', () => {
    expect(f.ai.present).toBe(true);
    expect(f.ai.runners).toEqual(['agentic-engine']);
  });

  it('reads the per-run cost ceiling and turn cap, wired oauth-first', () => {
    expect(f.ai.maxCostUsd).toBe(3);
    expect(f.ai.maxTurns).toBe(30);
    expect(f.ai.authMode).toBe('oauth-first');
  });

  it('classifies as an agentic-validator that comments via github-script', () => {
    expect(f.archetype).toBe('agentic-validator');
    expect(f.sinks).toContain('comment');
    expect(f.triggers.map((t) => t.kind)).toContain('pull_request');
  });
});

describe('extractFacts — ij agent-plan-then-act.yml (control-plane demo, not AI)', () => {
  const f = facts('agent-plan-then-act.yml', ijAgentPlanThenAct);

  it('does NOT read a runner from run.sh mentioned only in a comment / step title', () => {
    expect(f.ai.present).toBe(false);
    expect(f.ai.runners).toEqual([]);
    expect(f.archetype).toBe('other');
  });

  it('still sees the kill switch and the serializing concurrency group', () => {
    expect(f.killSwitches).toContain('AGENT_DEMO_ENABLED');
    expect(f.guards).toContain('concurrency-singleton');
    expect(f.guards).not.toContain('gate-job');
  });
});

describe('extractFacts — ij quest-perfection.yml (the perfection loop orchestrator)', () => {
  const f = facts('quest-perfection.yml', ijQuestPerfection);

  it('classifies as perfection-loop (beats dispatch-hub and content-factory)', () => {
    expect(f.archetype).toBe('perfection-loop');
    expect(f.crons.length).toBeGreaterThan(0);
  });

  it('sees the runtime fan-out matrix and the intra-repo workflow call', () => {
    expect(f.hasMatrix).toBe(true);
    expect(f.matrixDynamic).toBe(true);
    expect(f.localWorkflowCalls).toContain('./.github/workflows/quest-fix.yml');
    expect(f.reusableCalls).not.toContain('./.github/workflows/quest-fix.yml');
    expect(f.compositeLocals).not.toContain('./.github/workflows/quest-fix.yml');
  });

  it('runs both the composite and the agentic engine, gated by a gate job', () => {
    expect(f.ai.runners).toContain('agentic-engine');
    expect(f.ai.runners).toContain('claude-run');
    expect(f.killSwitches).toContain('QUEST_PERFECTION_ENABLED');
    expect(f.guards).toContain('gate-job');
    expect(f.guards).toContain('concurrency-singleton');
  });
});

describe('extractFacts — ij quest-walkthrough.yml (agentic validator)', () => {
  const f = facts('quest-walkthrough.yml', ijQuestWalkthrough);

  it('classifies as agentic-validator, running the engine + the walker composite', () => {
    expect(f.archetype).toBe('agentic-validator');
    expect(f.ai.runners).toContain('agentic-engine');
    expect(f.ai.runners).toContain('claude-run');
  });

  it('opens the report as a PR', () => {
    expect(f.sinks).toContain('pr');
  });
});

describe('extractFacts — ij quest-forge.yml (issue → content PR)', () => {
  const f = facts('quest-forge.yml', ijQuestForge);

  it('classifies as issue-to-content: issue-triggered AI opening a PR', () => {
    expect(f.archetype).toBe('issue-to-content');
    expect(f.ai.present).toBe(true);
    expect(f.triggers.map((t) => t.kind)).toContain('issues');
    expect(f.sinks).toContain('pr');
  });
});

describe('extractFacts — ij quest-idea-intake.yml (agent gatekeeper)', () => {
  const f = facts('quest-idea-intake.yml', ijQuestIdeaIntake);

  it('classifies as agent-gatekeeper: issue-triggered AI that only comments/labels', () => {
    expect(f.archetype).toBe('agent-gatekeeper');
    expect(f.ai.present).toBe(true);
    expect(f.sinks).toContain('comment');
    expect(f.sinks).not.toContain('pr');
  });
});

describe('extractFacts — ij agent-audit.yml (meta-loop, not content-factory)', () => {
  const f = facts('agent-audit.yml', ijAgentAudit);

  it('classifies as a meta-loop that audits the AI fleet itself', () => {
    expect(f.archetype).toBe('meta-loop');
    expect(f.crons.length).toBeGreaterThan(0);
    expect(f.ai.present).toBe(true);
    expect(f.sinks).toContain('pr');
  });
});

describe('extractFacts — ij content-review.yml (PR-triggered AI editor)', () => {
  const f = facts('content-review.yml', ijContentReview);

  it('classifies as a pr-editor (PR + AI, no merge)', () => {
    expect(f.archetype).toBe('pr-editor');
    expect(f.ai.present).toBe(true);
    expect(f.sinks).not.toContain('merge');
    expect(f.sinks).toContain('comment');
  });

  it('is loop-safe because its pull_request types omit synchronize', () => {
    expect(f.guards).toContain('synchronize-skip');
  });
});

describe('extractFacts — ij content-quality.yml + frontmatter-validation.yml (pr-gates)', () => {
  it('content-quality is a deterministic pr-gate that only comments', () => {
    const f = facts('content-quality.yml', ijContentQuality);
    expect(f.archetype).toBe('pr-gate');
    expect(f.ai.present).toBe(false);
    expect(f.sinks).toContain('comment');
  });

  it('frontmatter-validation is a pr-gate; its github-script comment is a comment sink', () => {
    const f = facts('frontmatter-validation.yml', ijFrontmatterValidation);
    expect(f.archetype).toBe('pr-gate');
    expect(f.ai.present).toBe(false);
    expect(f.sinks).toContain('comment');
    expect(f.sinks).not.toContain('issue');
  });
});

describe('extractFacts — ij sync-gh-pages.yml (a Pages publisher that merges a PR)', () => {
  const f = facts('sync-gh-pages.yml', ijSyncGhPages);

  it('classifies as deploy even though it merges a mirror PR', () => {
    expect(f.archetype).toBe('deploy');
    expect(f.sinks).toContain('merge');
    expect(f.crons.length).toBeGreaterThan(0);
  });
});

describe('extractFacts — ij link-checker.yml (nightly audit filing an issue)', () => {
  const f = facts('link-checker.yml', ijLinkChecker);

  it('sees the --create-issue sink and classifies as a nightly-audit', () => {
    expect(f.sinks).toContain('issue');
    expect(f.archetype).toBe('nightly-audit');
    expect(f.ai.present).toBe(false);
  });
});

describe('extractFacts — ij content-auto-merge.yml (wait-bound auto-merge bot)', () => {
  const f = facts('content-auto-merge.yml', ijContentAutoMerge);

  it('stays an auto-merge-bot with the smuggle guard', () => {
    expect(f.archetype).toBe('auto-merge-bot');
    expect(f.sinks).toContain('merge');
    expect(f.guards).toContain('smuggle-guard');
  });

  it('is wait-bound: it burns minutes polling checks, not computing', () => {
    expect(f.waitBound).toBe(true);
  });

  it('routes three label lanes, each with its own kill switch', () => {
    expect(f.killSwitches).toContain('CONTENT_AUTOMERGE_ENABLED');
    expect(f.killSwitches.length).toBeGreaterThanOrEqual(3);
  });
});

describe('extractFacts — ij dependabot-auto-merge.yml is also wait-bound', () => {
  it('polls the PR checks before merging', () => {
    expect(facts('dependabot-auto-merge.yml', ijDependabotAutoMerge).waitBound).toBe(true);
  });
});

describe('extractFacts — ij issue-autopilot.yml (the daily issue pipeline)', () => {
  const f = facts('issue-autopilot.yml', ijIssueAutopilot);

  it('classifies as issue-autopilot with a runtime-computed matrix', () => {
    expect(f.archetype).toBe('issue-autopilot');
    expect(f.hasMatrix).toBe(true);
    expect(f.matrixDynamic).toBe(true);
    expect(f.triggers.map((t) => t.kind)).toContain('issues');
  });

  it('writes to the issue tracker and opens a resolve PR', () => {
    expect(f.sinks).toContain('issue');
    expect(f.sinks).toContain('pr');
  });

  it('exposes plan/apply via the resolve dispatch toggle, and gates on a gate job', () => {
    expect(f.planApply).toBe(true);
    expect(f.guards).toContain('gate-job');
    expect(f.guards).toContain('concurrency-singleton');
    expect(f.killSwitches.length).toBeGreaterThanOrEqual(3);
  });
});

describe('extractFacts — ij cms-daily-loop.yml (content factory, enable_* plan/apply)', () => {
  const f = facts('cms-daily-loop.yml', ijCmsDailyLoop);

  it('classifies as a content-factory with a bare-CLI agentic engine', () => {
    expect(f.archetype).toBe('content-factory');
    expect(f.ai.present).toBe(true);
    expect(f.ai.runners).toContain('agentic-engine');
    expect(f.ai.runners).toContain('claude-cli');
  });

  it('reads the enable_substantive false-default toggle as plan/apply', () => {
    expect(f.planApply).toBe(true);
    expect(f.killSwitches).toContain('CMS_LOOP_SUBSTANTIVE');
    expect(f.killSwitches).toContain('CMS_MECHANICAL_AUTOMERGE');
  });

  it('has no fan-out matrix, so matrixDynamic is false', () => {
    expect(f.hasMatrix).toBe(false);
    expect(f.matrixDynamic).toBe(false);
  });
});

describe('extractFacts — ij quest-fix.yml (reusable library)', () => {
  const f = facts('quest-fix.yml', ijQuestFix);

  it('classifies as reusable-library (on: workflow_call)', () => {
    expect(f.isReusable).toBe(true);
    expect(f.archetype).toBe('reusable-library');
  });

  it('still surfaces the agentic engine it runs when called', () => {
    expect(f.ai.runners).toContain('agentic-engine');
  });
});

describe('extractFacts — ij content-factory.yml gate + static matrix', () => {
  const f = facts('content-factory.yml', ijContentFactory);

  it('has a gate job and a static (non-dynamic) collection matrix', () => {
    expect(f.guards).toContain('gate-job');
    expect(f.hasMatrix).toBe(true);
    expect(f.matrixDynamic).toBe(false);
  });
});

// ── law-ai + fredgar: cron loops that must not mis-hit autopilot / ledger ──────

describe('extractFacts — law evolve.yml (weekly autonomy loop, not issue-autopilot)', () => {
  const f = facts('evolve.yml', lawEvolve);

  it('classifies as autonomy-loop despite the word "autopilot" in its name', () => {
    // It files a `gh issue create` but has NO issues trigger, so it is not an
    // issue-autopilot — it is a scheduled evolve loop that opens a PR.
    expect(f.archetype).toBe('autonomy-loop');
    expect(f.ai.present).toBe(false);
    expect(f.sinks).toContain('pr');
    expect(f.sinks).toContain('issue');
    expect(f.triggers.map((t) => t.kind)).not.toContain('issues');
  });
});

describe('extractFacts — law nightly-tests.yml (autonomy loop, not a ledger)', () => {
  const f = facts('nightly-tests.yml', lawNightlyTests);

  it('classifies as autonomy-loop: uploading an artifact is not a ledger sweep', () => {
    expect(f.archetype).toBe('autonomy-loop');
    expect(f.ai.present).toBe(false);
    expect(f.sinks).toContain('pr');
  });

  it('exposes plan/apply via its dry_run dispatch input', () => {
    expect(f.planApply).toBe(true);
  });
});

describe('extractFacts — edg refresh-data.yml (a dispatch-only data refresher)', () => {
  const f = facts('refresh-data.yml', edgRefreshData);

  it('classifies as other — it dispatches a publish, but writes no PR/issue/deploy sink', () => {
    // Ground truth: no pr/commit/issue sink and no deploy signal in name/path, so it
    // falls through the taxonomy to `other` (the survey guessed data-sync).
    expect(f.archetype).toBe('other');
    expect(f.ai.present).toBe(false);
    expect(f.sinks).toContain('dispatch');
  });
});

// ── cv-builder-pro + hub ──────────────────────────────────────────────────────

describe('extractFacts — cv markdown-oneline.yml (seeded prose kit)', () => {
  const f = facts('markdown-oneline.yml', cvMarkdownOneline);

  it('classifies as the seeded prose-kit with no AI', () => {
    expect(f.archetype).toBe('prose-kit');
    expect(f.ai.present).toBe(false);
    // The dash's exact classifier has no keyword matching "markdown-oneline",
    // so this one falls through to 'other' (not 'docs').
    expect(f.dashType).toBe('other');
  });
});

describe('extractFacts — hub standard-ci.yml (reusable library)', () => {
  const f = facts('standard-ci.yml', hubStandardCi);

  it('classifies as a reusable-library via workflow_call', () => {
    expect(f.isReusable).toBe(true);
    expect(f.archetype).toBe('reusable-library');
  });
});

// ── malformed / edge inputs ───────────────────────────────────────────────────

describe('extractFacts — robustness', () => {
  it('yields empty-but-total facts for an empty file', () => {
    const f = facts('empty.yml', '');
    expect(f.name).toBe('empty');
    expect(f.triggers).toEqual([]);
    expect(f.jobCount).toBe(0);
    expect(f.timeoutMinutes).toBeNull();
    expect(f.concurrency.present).toBe(false);
    expect(f.ai.present).toBe(false);
    expect(f.generated).toBeNull();
    expect(f.archetype).toBe('other');
  });

  it('still mines signals from unparseable YAML via raw-text fallbacks', () => {
    const broken = [
      'name: [broken',
      'uses: anthropics/claude-code-action@v1',
      'timeout-minutes: 45',
      'strategy:',
      '  matrix:',
      "if: ${{ vars.NIGHTLY_ENABLED == 'true' }}",
      'env:',
      '  KEY: ${{ secrets.ANTHROPIC_API_KEY }}',
      'run: gh pr merge --squash',
      '',
    ].join('\n');
    const f = facts('broken.yml', broken);
    expect(f.name).toBe('broken');
    expect(f.jobCount).toBe(0);
    expect(f.hasMatrix).toBe(true);
    expect(f.timeoutMinutes).toBe(45);
    expect(f.ai.runners).toContain('claude-code-action');
    expect(f.ai.authMode).toBe('api-key-only');
    expect(f.killSwitches).toEqual(['NIGHTLY_ENABLED']);
    expect(f.sinks).toContain('merge');
  });

  it('falls back to the filename when no name: is present', () => {
    const f = facts('no-name.yml', 'on: push\n');
    expect(f.name).toBe('no-name');
    expect(f.triggers).toEqual([{ kind: 'push' }]);
  });

  it('keeps active crons out of the dormant list', () => {
    const mixed = [
      'name: sweep',
      'on:',
      '  schedule:',
      "    - cron: '0 9 * * *'",
      '# retired schedule:',
      "#   - cron: '0 9 * * *' (mirror of the active one)",
      "#   - cron: '30 3 * * 0'",
      '',
    ].join('\n');
    const f = facts('sweep.yml', mixed);
    expect(f.crons).toEqual(['0 9 * * *']);
    expect(f.dormantCrons).toEqual(['30 3 * * 0']);
  });

  it('does not flag prose comments mentioning a cron as dormant schedules', () => {
    const prosey = [
      'name: docs',
      'on: [push]',
      "# This job used to run on a cron: '0 6 * * 1' but we moved it to push.",
      '#   see the cron: syntax docs for the schedule field',
      'jobs:',
      '  build: { runs-on: ubuntu-latest }',
      '',
    ].join('\n');
    const f = facts('docs.yml', prosey);
    // The cron token lives inside prose, not a commented-out `# - cron:` list item.
    expect(f.dormantCrons).toEqual([]);
  });

  it('flags a commented-out schedule item (with or without the list dash) as dormant', () => {
    const bare = ['on: [workflow_dispatch]', "  # cron: '0 4 * * *'", ''].join('\n');
    expect(facts('x.yml', bare).dormantCrons).toEqual(['0 4 * * *']);
  });
});

// ── classifyDashType (direct) ─────────────────────────────────────────────────

describe('classifyDashType — ordered substring rules', () => {
  it('earlier rules win: dependabot beats security, deploy beats docs', () => {
    expect(classifyDashType('Dependabot security scan', 'x.yml')).toBe('dependencies');
    expect(classifyDashType('Deploy docs', 'deploy-docs.yml')).toBe('deploy');
  });

  it('honors the trailing space in "bump " ahead of the release rule', () => {
    expect(classifyDashType('Version bump', 'x.yml')).toBe('dependencies');
  });

  it('falls back to other when nothing matches', () => {
    expect(classifyDashType('mystery', 'mystery.yml')).toBe('other');
  });
});

// ── classifyArchetype (direct) ────────────────────────────────────────────────

/** Minimal blank signal set for direct archetype tests. */
function signals(extra: Partial<ArchetypeSignals> = {}): ArchetypeSignals {
  return {
    path: '.github/workflows/x.yml',
    name: 'x',
    triggers: [],
    crons: [],
    isReusable: false,
    reusableCalls: [],
    jobCount: 1,
    hasMatrix: false,
    matrixDynamic: false,
    sinks: [],
    crossRepoTargets: [],
    ai: {
      present: false,
      runners: [],
      models: [],
      maxTurns: null,
      maxCostUsd: null,
      authMode: 'none',
      agents: [],
    },
    guards: [],
    generated: null,
    ...extra,
  };
}

describe('classifyArchetype — precedence', () => {
  it('the generated header outranks every other signal', () => {
    const s = signals({ generated: { blueprintPath: null, hash: null }, isReusable: true });
    expect(classifyArchetype(s, '')).toBe('generated-line');
  });

  it('workflow_call makes a reusable-library', () => {
    expect(classifyArchetype(signals({ isReusable: true }), '')).toBe('reusable-library');
  });

  it('nothing matched falls through to other', () => {
    expect(classifyArchetype(signals(), '')).toBe('other');
  });
});

/** A present AiFacts with the given runner(s), for direct classifier tests. */
function ai(runners: AiFacts['runners']): AiFacts {
  return {
    present: runners.length > 0,
    runners,
    models: [],
    maxTurns: null,
    maxCostUsd: null,
    authMode: 'oauth-first',
    agents: [],
  };
}

describe('classifyArchetype — the agentic-engine cost-center archetypes (direct)', () => {
  it('perfection-loop needs cron + AI + dynamic matrix + a fromJSON(plan) matrix', () => {
    const s = signals({
      crons: ['0 11 * * *'],
      ai: ai(['agentic-engine']),
      matrixDynamic: true,
      sinks: ['pr'],
    });
    expect(classifyArchetype(s, 'matrix: ${{ fromJson(needs.plan.outputs.matrix) }}')).toBe(
      'perfection-loop',
    );
  });

  it('agentic-validator needs the agentic-engine runner AND the engine signal in text', () => {
    const s = signals({ ai: ai(['agentic-engine']), triggers: [{ kind: 'workflow_dispatch' }] });
    expect(classifyArchetype(s, 'python3 test/quest-validator/agentic_validate.py --mode execute')).toBe(
      'agentic-validator',
    );
    // The engine runner alone is not enough without the validate/--mode signal.
    expect(classifyArchetype(s, 'echo no engine here')).not.toBe('agentic-validator');
  });

  it('issue-to-content vs agent-gatekeeper turns on the PR sink', () => {
    const base = { triggers: [{ kind: 'issues' }], ai: ai(['claude-run']) };
    expect(classifyArchetype(signals({ ...base, sinks: ['pr'] }), '')).toBe('issue-to-content');
    expect(classifyArchetype(signals({ ...base, sinks: ['comment'] }), '')).toBe('agent-gatekeeper');
  });

  it('issue-autopilot requires an issues/label trigger, not just the word autopilot', () => {
    // A scheduled "evolve (weekly autopilot)" that files issues but has no issues
    // trigger is an autonomy-loop, never an issue-autopilot.
    const evolve = signals({
      name: 'Evolve (weekly autopilot)',
      crons: ['0 13 * * 1'],
      triggers: [{ kind: 'schedule' }, { kind: 'workflow_dispatch' }],
      sinks: ['pr', 'issue'],
    });
    expect(classifyArchetype(evolve, '')).toBe('autonomy-loop');
    // Add the issues trigger + AI + matrix and it becomes the autopilot.
    const autopilot = signals({
      name: 'Issue Autopilot',
      crons: ['0 7 * * *'],
      triggers: [{ kind: 'schedule' }, { kind: 'issues' }],
      ai: ai(['claude-run']),
      hasMatrix: true,
      sinks: ['issue', 'pr'],
    });
    expect(classifyArchetype(autopilot, '')).toBe('issue-autopilot');
  });

  it('deploy beats auto-merge-bot: a gh-pages publisher that merges a PR is a deploy', () => {
    const s = signals({
      name: 'Sync gh-pages from main',
      path: '.github/workflows/sync-gh-pages.yml',
      sinks: ['merge', 'comment'],
    });
    expect(classifyArchetype(s, '')).toBe('deploy');
  });

  it('pr-editor / pr-gate / ci-gate: PR-only AI vs PR-only gate vs push+PR pipeline', () => {
    const prAi = signals({ triggers: [{ kind: 'pull_request' }], ai: ai(['claude-run']), sinks: ['comment'] });
    expect(classifyArchetype(prAi, '')).toBe('pr-editor');
    const prGate = signals({ triggers: [{ kind: 'pull_request' }], sinks: ['comment'] });
    expect(classifyArchetype(prGate, '')).toBe('pr-gate');
    const ciGate = signals({ triggers: [{ kind: 'push' }, { kind: 'pull_request' }] });
    expect(classifyArchetype(ciGate, '')).toBe('ci-gate');
  });
});
